"""D03 issued packages: key format, sealing, account provisioning and the issue pipeline."""

import hashlib
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from app.auth import check_password, password_hash, provision_accounts
from app.storage import REPO_ROOT, Store


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = load("kdog_install_test", "scripts/windows/kdog_install.py")
CRYPTO = "runtime/python/Lib/site-packages/cryptography-50.0.2.dist-info/METADATA"


def provision(*accounts, customer="SCHOOL-1"):
    return json.dumps({"format": "kdog-provision-1", "customer": customer, "issued_at": "2026-10-05T00:00:00+00:00",
                       "accounts": [{"username": username, "role": role, "password_hash": password_hash(password)}
                                    for username, role, password in accounts]}).encode()


class KeyAndSealTests(unittest.TestCase):
    def test_keys_are_random_25_character_crockford_and_typed_forms_normalize(self):
        keys = {installer.new_key() for _ in range(200)}
        self.assertEqual(len(keys), 200)
        for key in keys:
            self.assertEqual(len(key), 25)
            self.assertTrue(set(key) <= set(installer.ALPHABET))
            shown = installer.display_key(key)
            self.assertRegex(shown, r"^KDOG(-[0-9A-Z]{5}){5}$")
            wide = "".join(chr(ord(char) + 0xFEE0) if "!" <= char <= "~" else char for char in shown)
            for typed in (shown, shown.lower(), shown.replace("-", " "), shown[5:], f"  kdog {shown[5:]}  ",
                          f"K-DOG-{shown[5:]}", f"KD0G-{shown[5:]}", wide):
                self.assertEqual(installer.normalize_key(typed), key)
        self.assertEqual(installer.normalize_key("KDOG-OILOO-11111-22222-33333-44444"), "01100111112222233333" + "44444")
        for typed in ("", "KDOG-", "KDOG-11111-22222-33333-44444", "KDOG-11111-22222-33333-44444-5555U",
                      "11111-22222-33333-44444-555555"):
            self.assertIsNone(installer.normalize_key(typed), typed)

    def test_seal_round_trip_rejects_wrong_key_and_any_changed_byte(self):
        key, product = installer.new_key(), b"product zip bytes" * 100
        data = installer.seal(product, key, customer="SCHOOL-1", version="0.3.0", commit="a" * 40)
        header, opened = installer.unseal(data, key)
        self.assertEqual((header["customer"], header["version"], opened), ("SCHOOL-1", "0.3.0", product))
        self.assertNotIn(b"product zip bytes", data)
        with self.assertRaises(installer.WrongKey):
            installer.unseal(data, installer.new_key())
        size = int.from_bytes(data[8:12], "big")
        changed_header = data.replace(b'"SCHOOL-1"', b'"SCHOOL-2"')
        self.assertNotEqual(changed_header, data)
        changed_body = data[:-1] + bytes([data[-1] ^ 1])
        for altered in (changed_header, changed_body, data[:12 + size + 20] + bytes([data[12 + size + 20] ^ 1]) + data[12 + size + 21:]):
            with self.assertRaises(installer.WrongKey):
                installer.unseal(altered, key)
        unsafe = [installer.seal(product, key, customer="SCHOOL-1", version="../x", commit="a" * 40),
                  installer.seal(product, key, customer="SCHOOL-1", version="0.3.0", commit="abc"),
                  installer.MAGIC + (3).to_bytes(4, "big") + b"[1]" + bytes(16)]
        for damaged in (b"", b"PK\x03\x04" + data[4:], data[:12 + size], data[:8] + (5000).to_bytes(4, "big") + data[12:], *unsafe):
            with self.assertRaises(installer.PackageError):
                installer.unseal(damaged, key)


class ProvisionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="kdog-provision-")
        self.store = Store(Path(self.temporary.name))

    def tearDown(self):
        self.temporary.cleanup()

    def provision(self, document):
        with self.store.connect(write=True) as db:
            return provision_accounts(db, self.store, document)

    def users(self):
        with self.store.connect() as db:
            return {row["username"]: dict(row) for row in db.execute("SELECT * FROM users")}

    def test_creates_new_accounts_then_keeps_same_role_accounts_and_their_passwords(self):
        messages = self.provision(provision(("manager", "admin", "Issued-admin-pass-1"), ("keyman", "developer", "Issued-dev-pass-1")))
        self.assertEqual(len(messages), 2)
        self.assertTrue(all("새 계정" in message for message in messages))
        users = self.users()
        self.assertEqual({name: row["role"] for name, row in users.items()}, {"manager": "admin", "keyman": "developer"})
        self.assertTrue(check_password("Issued-admin-pass-1", users["manager"]["password_hash"]))
        with self.store.connect() as db:
            audits = db.execute("SELECT detail_json FROM changes WHERE action='user.provisioned'").fetchall()
        self.assertEqual(len(audits), 2)
        self.assertIn("SCHOOL-1", audits[0]["detail_json"])
        # A later package with the same IDs keeps the existing passwords.
        messages = self.provision(provision(("manager", "admin", "A-different-password-2")))
        self.assertIn("기존 비밀번호가 유지", messages[0])
        self.assertTrue(check_password("Issued-admin-pass-1", self.users()["manager"]["password_hash"]))

    def test_role_mismatch_or_inactive_account_changes_nothing(self):
        self.provision(provision(("manager", "admin", "Issued-admin-pass-1"), ("keyman", "developer", "Issued-dev-pass-1")))
        with self.store.connect(write=True) as db:
            db.execute("UPDATE users SET active=0 WHERE username='keyman'")
        before = self.users()
        for document in (provision(("keyman", "admin", "Issued-admin-pass-1")),
                         provision(("new-admin", "admin", "Issued-admin-pass-1"), ("manager", "developer", "Issued-dev-pass-1")),
                         provision(("other", "admin", "Issued-admin-pass-1"), ("keyman", "developer", "Issued-dev-pass-1"))):
            with self.assertRaisesRegex(ValueError, "아무것도 바꾸지 않았습니다"):
                self.provision(document)
            self.assertEqual(self.users(), before)

    def test_rejects_malformed_provision_documents(self):
        good = json.loads(provision(("manager", "admin", "Issued-admin-pass-1"), ("keyman", "developer", "Issued-dev-pass-1")))
        def variant(change):
            document = json.loads(json.dumps(good))
            change(document)
            return json.dumps(document).encode()
        for document in (b"not json", b"[]", variant(lambda d: d.update(format="other")),
                         variant(lambda d: d.update(customer="bad customer")),
                         variant(lambda d: d.update(accounts=[])),
                         variant(lambda d: d["accounts"].pop(0)),  # developer only, no admin
                         variant(lambda d: d["accounts"][1].update(role="admin")),
                         variant(lambda d: d["accounts"][1].update(role="operator")),
                         variant(lambda d: d["accounts"][1].update(username="manager")),
                         variant(lambda d: d["accounts"][0].update(username="has space")),
                         variant(lambda d: d["accounts"][0].update(password_hash="plain-password")),
                         variant(lambda d: d["accounts"][0].update(password="Issued-admin-pass-1"))):
            with self.assertRaisesRegex(ValueError, "올바르지 않습니다"):
                self.provision(document)
        self.assertEqual(self.users(), {})

    def test_manage_command_reads_stdin_and_reports_failures(self):
        def run(document):
            return subprocess.run([sys.executable, "-X", "utf8", "-m", "app.manage", "--data-dir", self.temporary.name,
                                   "provision-accounts"], input=document, capture_output=True, cwd=REPO_ROOT / "backend",
                                  timeout=60)
        created = run(provision(("manager", "admin", "Issued-admin-pass-1")))
        self.assertEqual(created.returncode, 0, created.stderr.decode("utf-8", "replace"))
        self.assertIn("새 계정", created.stdout.decode("utf-8"))
        failed = run(b"{}")
        self.assertEqual(failed.returncode, 1)
        self.assertIn("계정 생성 실패", failed.stderr.decode("utf-8"))


class IssueTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="kdog-issue-")
        self.root = Path(self.temporary.name)
        self.issuer = load("issue_release_test", "scripts/issue_release.py")

    def tearDown(self):
        self.temporary.cleanup()

    def plain(self, tamper=False, supported=True):
        files = {"Start.cmd": b"@echo off\r\n", "backend/app/secret.py": b"PRODUCT_SOURCE_MARKER = 1\n",
                 "backend/app/manage.py": b'sub.add_parser("provision-accounts")\n' if supported else b"",
                 "runtime/python/python.exe": b"MZ runtime", CRYPTO: b"Name: cryptography\n", "오픈소스고지.txt": "고지".encode()}
        manifest = {"format": "kdog-release-1", "version": "0.3.0", "commit": "b" * 40,
                    "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
        path = self.root / f"plain-{tamper}-{supported}.zip"
        with ZipFile(path, "w") as archive:
            for name, data in files.items():
                archive.writestr(name, data + (b"x" if tamper and name == "Start.cmd" else b""))
            archive.writestr("release.json", json.dumps(manifest))
        return path

    def test_issue_seals_product_and_accounts_and_records_no_secret(self):
        accounts = [("manager", "admin", "Issued-admin-pass-1"), ("keyman", "developer", "Issued-dev-pass-1")]
        result = self.issuer.issue(self.plain(), "SCHOOL-1", accounts, self.root / "out")
        package = result["path"]
        self.assertEqual(package.name, "K-DOG-SCHOOL-1-v0.3.0-bbbbbbb.zip")
        with ZipFile(package) as issued:
            names = set(issued.namelist())
            self.assertEqual(names, {"Install.cmd", "설치안내.txt", "installer/kdog_install.py",
                                     "runtime/python/python.exe", CRYPTO, "오픈소스고지.txt", "payload.kdog"})
            for name in names - {"payload.kdog"}:
                content = issued.read(name)
                self.assertNotIn(b"PRODUCT_SOURCE_MARKER", content)
                self.assertNotIn(b"password_hash", content)
            self.assertIn(b"\r\n", issued.read("Install.cmd"))
            header, product = installer.unseal(issued.read("payload.kdog"), installer.normalize_key(result["key"]))
        self.assertEqual((header["customer"], header["commit"]), ("SCHOOL-1", "b" * 40))
        with ZipFile(BytesIO(product)) as sealed:
            self.assertEqual(set(sealed.namelist()), {"Start.cmd", "backend/app/secret.py", "backend/app/manage.py",
                                                      "release.json", "provision.json"})
            accounts_in = json.loads(sealed.read("provision.json"))["accounts"]
        self.assertEqual([(row["username"], row["role"]) for row in accounts_in], [("manager", "admin"), ("keyman", "developer")])
        self.assertTrue(check_password("Issued-admin-pass-1", accounts_in[0]["password_hash"]))
        record = (self.root / "out/K-DOG-SCHOOL-1-v0.3.0-bbbbbbb.json").read_text(encoding="utf-8")
        sha = (self.root / "out/K-DOG-SCHOOL-1-v0.3.0-bbbbbbb.zip.sha256").read_text(encoding="utf-8")
        self.assertEqual(sha.split()[0], hashlib.sha256(package.read_bytes()).hexdigest())
        self.assertIn("installer_sha256", record)
        for secret in ("Issued-admin-pass-1", "Issued-dev-pass-1", result["key"], installer.normalize_key(result["key"]), "scrypt$"):
            self.assertNotIn(secret, record)
        # Every issue gets a new key; an existing package is never overwritten.
        again = self.issuer.issue(self.plain(), "SCHOOL-1", accounts[:1], self.root / "out2")
        self.assertNotEqual(again["key"], result["key"])
        with self.assertRaisesRegex(ValueError, "이미 있습니다"):
            self.issuer.issue(self.plain(), "SCHOOL-1", accounts[:1], self.root / "out")

    def test_issue_rejects_bad_inputs_before_writing(self):
        good = [("manager", "admin", "Issued-admin-pass-1")]
        for plain, customer, accounts, message in (
                (self.plain(tamper=True), "SCHOOL-1", good, "release.json"),
                (self.plain(supported=False), "SCHOOL-1", good, "발행 설치를 지원하지"),
                (self.plain(), "bad customer", good, "고객 ID"),
                (self.plain(), "SCHOOL-1", [("manager", "admin", "short")], "비밀번호"),
                (self.plain(), "SCHOOL-1", [("keyman", "developer", "Issued-dev-pass-1")], "관리자"),
                (self.plain(), "SCHOOL-1", good + [("manager", "developer", "Issued-dev-pass-1")], "관리자")):
            with self.assertRaisesRegex(ValueError, message):
                self.issuer.issue(plain, customer, accounts, self.root / "rejected")
        self.assertFalse((self.root / "rejected").exists())


class InstallerTests(unittest.TestCase):
    def test_cancel_or_wrong_key_writes_nothing(self):
        with tempfile.TemporaryDirectory(prefix="kdog-installer-") as temporary:
            package = Path(temporary) / "package"
            (package / "installer").mkdir(parents=True)
            key = installer.new_key()
            (package / "payload.kdog").write_bytes(installer.seal(b"zip", key, customer="SCHOOL-1", version="0.3.0", commit="c" * 40))
            root = Path(temporary) / "Programs"
            with patch.object(installer, "__file__", str(package / "installer/kdog_install.py")), \
                    patch("builtins.input", side_effect=["KDOG-" + "1" * 25, "not a key", ""]) as prompt, \
                    patch("builtins.print") as output:
                self.assertEqual(installer.main(["--install-root", str(root), "--shortcut-dir", str(Path(temporary) / "desk")]), 1)
            self.assertEqual(prompt.call_count, 3)
            printed = " ".join(str(call.args[0]) for call in output.call_args_list if call.args)
            self.assertIn("키가 맞지 않습니다", printed)
            self.assertIn("키 형식이 맞지 않습니다", printed)
            self.assertFalse(root.exists())
            self.assertFalse((Path(temporary) / "desk").exists())

    def product(self, extra=None):
        listed = {"Start.cmd": b"@echo off\r\n", "runtime/python/python.exe": b"MZ", "오픈소스고지.txt": b"notice"}
        buffer = BytesIO()
        with ZipFile(buffer, "w") as archive:
            archive.writestr("Start.cmd", listed["Start.cmd"])
            archive.writestr("provision.json", b"{}")
            archive.writestr("release.json", json.dumps({"files": {name: "0" * 64 for name in listed}}))
            for name, data in (extra or {}).items():
                archive.writestr(name, data)
        return ZipFile(BytesIO(buffer.getvalue()))

    def test_install_files_keeps_provision_in_memory_and_copies_only_listed_public_files(self):
        with tempfile.TemporaryDirectory(prefix="kdog-install-files-") as temporary:
            package, root = Path(temporary) / "package", Path(temporary) / "설치 위치"
            (package / "runtime/python").mkdir(parents=True)
            (package / "runtime/python/python.exe").write_bytes(b"MZ")
            (package / "runtime/python/sitecustomize.py").write_bytes(b"planted after the hash check")
            (package / "오픈소스고지.txt").write_bytes(b"notice")
            root.mkdir()
            (root / ".tmp-leftover").mkdir()
            target = root / "0.3.0-ccccccc"
            with patch.object(installer, "check", return_value=False):
                self.assertFalse(installer.install_files(self.product(), package, root, target))
            self.assertEqual(list(root.iterdir()), [])  # failed check removes its temporary folder and leftovers
            with patch.object(installer, "check", return_value=True):
                self.assertTrue(installer.install_files(self.product(), package, root, target))
            installed = sorted(path.relative_to(target).as_posix() for path in target.rglob("*") if path.is_file())
            self.assertEqual(installed, ["Start.cmd", "release.json", "runtime/python/python.exe", "오픈소스고지.txt"])
            with patch.object(installer, "check", return_value=True) as check:
                self.assertTrue(installer.install_files(self.product(), package, root, target))
            check.assert_called_once_with(target)  # an installed version is only re-checked
            with self.assertRaises(installer.PackageError):
                installer.install_files(self.product({"../escape.txt": b"x"}), package, root, root / "0.3.0-ddddddd")
            self.assertFalse((Path(temporary) / "escape.txt").exists())

    def test_shortcut_failure_falls_back_to_start_path(self):
        with tempfile.TemporaryDirectory(prefix="kdog-shortcut-") as temporary:
            failed = subprocess.CompletedProcess([], 1, stdout=b"", stderr=b"denied")
            with patch.object(installer.subprocess, "run", return_value=failed):
                self.assertIsNone(installer.shortcut(Path(temporary) / "app", Path(temporary) / "desk"))
            with patch.object(installer.subprocess, "run", side_effect=OSError):
                self.assertIsNone(installer.shortcut(Path(temporary) / "app", Path(temporary) / "desk"))


if __name__ == "__main__":
    unittest.main()
