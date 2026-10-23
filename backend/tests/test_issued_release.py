"""D03 issued packages: key format, sealing, account provisioning and the issue pipeline."""

from datetime import date, timedelta
import hashlib
import importlib.util
import os
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from app.auth import check_password, create_first_user, first_user_needed, password_hash, provision_accounts
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

    def test_install_period_is_authenticated_and_includes_its_last_day(self):
        key, product = installer.new_key(), b"product"
        data = installer.seal(product, key, customer="SCHOOL-1", version="0.3.0", commit="a" * 40, expires="2026-12-31")
        header, raw, ciphertext = installer.read_header(data)
        self.assertEqual((header["expires"], installer.unseal(data, key)[1]), ("2026-12-31", product))
        self.assertFalse(installer.expired(header, date(2026, 12, 31)))
        self.assertTrue(installer.expired(header, date(2027, 1, 1)))
        self.assertFalse(installer.expired(installer.read_header(
            installer.seal(product, key, customer="SCHOOL-1", version="0.3.0", commit="a" * 40))[0], date(2999, 1, 1)))
        # Extending or removing the period fails authentication even with the right key.
        dropped = json.dumps({name: value for name, value in header.items() if name != "expires"}, sort_keys=True).encode()
        for altered in (data.replace(b'"2026-12-31"', b'"2099-12-31"'),
                        installer.MAGIC + len(dropped).to_bytes(4, "big") + dropped + ciphertext):
            with self.assertRaises(installer.WrongKey):
                installer.unseal(altered, key)
        for bad in ("2026-13-01", "2026-1-1", "20261231", 20261231):
            wrong = json.dumps({**header, "expires": bad}, sort_keys=True).encode()
            with self.assertRaises(installer.PackageError):
                installer.read_header(installer.MAGIC + len(wrong).to_bytes(4, "big") + wrong + ciphertext)
        self.assertEqual(raw, data[12:12 + len(raw)])


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

    def test_common_business_roles_can_be_provisioned_without_admin(self):
        for role in ("operator","reviewer"):
            name=f"issued-{role}"
            self.provision(provision((name,role,"Issued-business-pass-1")))
            before=self.users()[name]
            self.assertEqual(before["role"],role)
            self.provision(provision((name,role,"Different-business-pass-2")))
            self.assertEqual(self.users()[name]["password_hash"],before["password_hash"])

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
                         variant(lambda d: d["accounts"][0].update(role="developer")),  # two developers
                         variant(lambda d: d["accounts"][1].update(role="admin")),
                         variant(lambda d: d["accounts"][1].update(role="operator")),
                         variant(lambda d: d["accounts"][1].update(username="manager")),
                         variant(lambda d: d["accounts"][0].update(username="has space")),
                         variant(lambda d: d["accounts"][0].update(password_hash="plain-password")),
                         variant(lambda d: d["accounts"][0].update(password="Issued-admin-pass-1"))):
            with self.assertRaisesRegex(ValueError, "올바르지 않습니다"):
                self.provision(document)
        self.assertEqual(self.users(), {})

    def test_developer_only_package_leaves_the_first_business_account_to_the_installer(self):
        self.provision(provision(("keyman", "developer", "Issued-dev-pass-1")))
        with self.store.connect(write=True) as db:
            self.assertTrue(first_user_needed(db))
            for document in (b"not json", json.dumps({"username": "manager", "password": "short"}).encode(),
                             json.dumps({"username": "has space", "password": "First-user-pass-1"}).encode(),
                             json.dumps({"username": "manager", "password": "First-user-pass-1", "role": "admin"}).encode(),
                             json.dumps({"username": "keyman", "password": "First-user-pass-1"}).encode()):
                with self.assertRaises(ValueError):
                    create_first_user(db, self.store, document)
            self.assertTrue(create_first_user(db, self.store, json.dumps({"username": "manager", "password": "First-user-pass-1"}).encode()))
            self.assertFalse(first_user_needed(db))
            self.assertFalse(create_first_user(db, self.store, json.dumps({"username": "second", "password": "First-user-pass-2"}).encode()))
            audit = db.execute("SELECT actor,detail_json FROM changes WHERE action='user.local_create'").fetchall()
        users = self.users()
        self.assertEqual({name: row["role"] for name, row in users.items()}, {"keyman": "developer", "manager": "operator"})
        self.assertTrue(check_password("First-user-pass-1", users["manager"]["password_hash"]))
        self.assertEqual([row["actor"] for row in audit], ["manager"])
        self.assertIn("installer", audit[0]["detail_json"])
        # An inactive business account does not count; the PC still needs an active one to log in.
        with self.store.connect(write=True) as db:
            db.execute("UPDATE users SET active=0 WHERE username='manager'")
            self.assertTrue(first_user_needed(db))

    def test_manage_create_first_user_checks_then_creates_once(self):
        def run(*arguments, document=b""):
            return subprocess.run([sys.executable, "-X", "utf8", "-m", "app.manage", "--data-dir", self.temporary.name,
                                   "create-first-user", *arguments], input=document, capture_output=True,
                                  cwd=REPO_ROOT / "backend", timeout=60)
        self.assertEqual(run("--check").stdout.decode().strip(), "needed")
        failed = run(document=b'{"username": "manager", "password": "short"}')
        self.assertEqual(failed.returncode, 1)
        self.assertIn("계정 생성 실패", failed.stderr.decode("utf-8"))
        created = run(document=b'{"username": "manager", "password": "First-user-pass-1"}')
        self.assertEqual(created.returncode, 0, created.stderr.decode("utf-8", "replace"))
        self.assertEqual(run("--check").stdout.decode().strip(), "exists")
        self.assertEqual(run(document=b'{"username": "other", "password": "First-user-pass-2"}').returncode, 0)
        self.assertEqual(set(self.users()), {"manager"})

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

    def plain(self, tamper=False, supported=True, variant=None):
        files = {"Start.cmd": b"@echo off\r\n", "backend/app/secret.py": b"PRODUCT_SOURCE_MARKER = 1\n",
                 "backend/app/manage.py": b'sub.add_parser("provision-accounts")\nsub.add_parser("create-first-user")\n'
                                          if supported else b'sub.add_parser("provision-accounts")\n',
                 "runtime/python/python.exe": b"MZ runtime", CRYPTO: b"Name: cryptography\n", "오픈소스고지.txt": "고지".encode()}
        manifest = {"format": "kdog-release-1", "version": "0.3.0", "commit": "b" * 40,
                    "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
                    **({"variant": variant} if variant else {})}
        path = self.root / f"plain-{tamper}-{supported}-{variant}.zip"
        with ZipFile(path, "w") as archive:
            for name, data in files.items():
                archive.writestr(name, data + (b"x" if tamper and name == "Start.cmd" else b""))
            archive.writestr("release.json", json.dumps(manifest))
        return path

    def test_issue_general_business_account_unseals_and_provisions(self):
        result=self.issuer.issue(self.plain(),"GENERAL",[("worker","operator","Issued-business-pass-1")],self.root/"general")
        with ZipFile(result["path"]) as issued:
            _,product=installer.unseal(issued.read("payload.kdog"),installer.normalize_key(result["key"]))
        with ZipFile(BytesIO(product)) as sealed:
            document=sealed.read("provision.json")
        store=Store(self.root/"general-data")
        with store.connect(write=True) as db:
            provision_accounts(db,store,document)
            row=db.execute("SELECT * FROM users WHERE username='worker'").fetchone()
            self.assertEqual(row["role"],"operator")
            self.assertTrue(check_password("Issued-business-pass-1",row["password_hash"]))

    def test_issue_developer_only_with_install_period(self):
        last = (date.today() + timedelta(days=30)).isoformat()
        result = self.issuer.issue(self.plain(), "SCHOOL-1", [("keyman", "developer", "Issued-dev-pass-1")], self.root / "dev", last)
        self.assertEqual(result["expires"], last)
        with ZipFile(result["path"]) as issued:
            header, product = installer.unseal(issued.read("payload.kdog"), installer.normalize_key(result["key"]))
        self.assertEqual(header["expires"], last)
        with ZipFile(BytesIO(product)) as sealed:
            accounts = json.loads(sealed.read("provision.json"))["accounts"]
        self.assertEqual([(row["username"], row["role"]) for row in accounts], [("keyman", "developer")])
        record = json.loads((self.root / "dev/K-DOG-SCHOOL-1-v0.3.0-bbbbbbb.json").read_text(encoding="utf-8"))
        self.assertEqual(record["expires"], last)
        today = self.issuer.issue(self.plain(), "SCHOOL-1", [("keyman", "developer", "Issued-dev-pass-1")], self.root / "today",
                                  date.today().isoformat())
        self.assertEqual(today["expires"], date.today().isoformat())
        unlimited = self.issuer.issue(self.plain(), "SCHOOL-1", [("keyman", "developer", "Issued-dev-pass-1")], self.root / "open")
        self.assertIsNone(unlimited["expires"])
        with ZipFile(unlimited["path"]) as issued:
            self.assertNotIn("expires", installer.read_header(issued.read("payload.kdog"))[0])

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
                (self.plain(variant="online"), "SCHOOL-1", good, "사용자 설치형"),
                (self.plain(), "bad customer", good, "고객 ID"),
                (self.plain(), "SCHOOL-1", [("manager", "admin", "short")], "비밀번호"),
                (self.plain(), "SCHOOL-1", [], "업무 계정"),
                (self.plain(), "SCHOOL-1", [("keyman", "developer", "Issued-dev-pass-1"), ("keyman2", "developer", "Issued-dev-pass-1")], "업무 계정"),
                (self.plain(), "SCHOOL-1", good + [("worker", "operator", "Issued-business-pass-1")], "업무 계정"),
                (self.plain(), "SCHOOL-1", good + [("manager", "developer", "Issued-dev-pass-1")], "업무 계정")):
            with self.assertRaisesRegex(ValueError, message):
                self.issuer.issue(plain, customer, accounts, self.root / "rejected")
        for expires in ((date.today() - timedelta(days=1)).isoformat(), "2026-13-01", "2026/12/31", ""):
            with self.assertRaisesRegex(ValueError, "유효 기간"):
                self.issuer.issue(self.plain(), "SCHOOL-1", good, self.root / "rejected", expires)
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

    def test_expired_package_stops_before_the_key_and_writes_nothing(self):
        with tempfile.TemporaryDirectory(prefix="kdog-installer-expired-") as temporary:
            package = Path(temporary) / "package"
            (package / "installer").mkdir(parents=True)
            key = installer.new_key()
            (package / "payload.kdog").write_bytes(installer.seal(b"zip", key, customer="SCHOOL-1", version="0.3.0",
                                                                  commit="c" * 40, expires="2026-01-01"))
            root = Path(temporary) / "Programs"
            with patch.object(installer, "__file__", str(package / "installer/kdog_install.py")), \
                    patch("builtins.input", side_effect=[installer.display_key(key)]) as prompt, \
                    patch("builtins.print") as output:
                self.assertEqual(installer.main(["--install-root", str(root), "--shortcut-dir", str(Path(temporary) / "desk")]), 1)
            prompt.assert_not_called()
            printed = " ".join(str(call.args[0]) for call in output.call_args_list if call.args)
            self.assertIn("유효 기간(2026-01-01)이 지났습니다", printed)
            self.assertFalse(root.exists())
            self.assertFalse((Path(temporary) / "desk").exists())

    def test_first_user_prompt_creates_once_skips_and_retries(self):
        with tempfile.TemporaryDirectory(prefix="kdog-installer-first-") as temporary:
            data = Path(temporary) / "data"
            env = {**os.environ, "KDOG_DATA_DIR": str(data), "PYTHONUTF8": "1"}

            def run_python(folder, *arguments, stdin=None):
                # The real manage command on a temporary data folder stands in for the installed runtime.
                return subprocess.run([sys.executable, "-X", "utf8", *arguments], cwd=REPO_ROOT / "backend", env=env,
                                      input=stdin, capture_output=True, timeout=60)

            def ask(*answers):
                with patch.object(installer, "run_python", side_effect=run_python), \
                        patch.object(installer.sys.stdin, "isatty", return_value=False), \
                        patch("builtins.input", side_effect=list(answers)) as prompt, \
                        patch("builtins.print") as output:
                    self.assertTrue(installer.first_user(Path(temporary) / "app"))
                return prompt.call_count, " ".join(str(call.args[0]) for call in output.call_args_list if call.args)

            calls, printed = ask("")
            self.assertEqual(calls, 1)
            self.assertIn("create-user <아이디> --role operator", printed)
            calls, printed = ask("has space", "manager", "short", "short",
                                 "manager", "First-user-pass-1", "Different-pass-2",
                                 "manager", "First-user-pass-1", "First-user-pass-1")
            self.assertEqual(calls, 10)
            self.assertIn("영문·숫자", printed)
            self.assertIn("비밀번호 확인과 길이", printed)
            self.assertIn("업무 계정을 만들었습니다", printed)
            store = Store(data)
            with store.connect() as db:
                row = db.execute("SELECT role,password_hash FROM users WHERE username='manager'").fetchone()
            self.assertEqual(row["role"], "operator")
            self.assertTrue(check_password("First-user-pass-1", row["password_hash"]))
            calls, _ = ask()  # reinstall: an active business account exists, so nothing is asked
            self.assertEqual(calls, 0)

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
            self.assertEqual(list(root.iterdir()), [root / '.tmp-leftover'])  # another install's folder is never removed
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
            self.assertEqual(sorted(root.iterdir()), sorted([root / '.tmp-leftover', target]))

    def test_concurrent_installs_preserve_each_others_active_files(self):
        self.concurrent_installs('version-b')

    def test_concurrent_same_version_rechecks_the_completed_install(self):
        self.concurrent_installs('version-a')

    def concurrent_installs(self, second_version):
        with tempfile.TemporaryDirectory(prefix="kdog-install-concurrent-") as temporary:
            package, root = Path(temporary) / "package", Path(temporary) / "Programs"
            (package / "runtime/python").mkdir(parents=True)
            (package / "runtime/python/python.exe").write_bytes(b"MZ")
            (package / "오픈소스고지.txt").write_bytes(b"notice")
            root.mkdir()
            extracted, resume = threading.Event(), threading.Event()
            result, errors = [], []
            first_target, second_target = root / "version-a", root / second_version
            with self.product() as first_archive, self.product() as second_archive:
                extract = first_archive.extract

                def pause_after_extract(info, destination):
                    value = extract(info, destination)
                    if info.filename == 'Start.cmd':
                        extracted.set()
                        if not resume.wait(10):
                            raise RuntimeError('concurrent install synchronization timed out')
                    return value

                def first_install():
                    try:
                        result.append(installer.install_files(first_archive, package, root, first_target))
                    except BaseException as error:
                        errors.append(error)

                with patch.object(first_archive, 'extract', side_effect=pause_after_extract), \
                        patch.object(installer, 'check', side_effect=lambda folder: (folder / 'Start.cmd').is_file()):
                    thread = threading.Thread(target=first_install)
                    thread.start()
                    try:
                        self.assertTrue(extracted.wait(10))
                        self.assertTrue(installer.install_files(second_archive, package, root, second_target))
                    finally:
                        resume.set()
                        thread.join(10)
                    self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(result, [True])
            for target in (first_target, second_target):
                self.assertEqual((target / 'Start.cmd').read_bytes(), b'@echo off\r\n')
            self.assertEqual(sorted(root.iterdir()), sorted({first_target, second_target}))

    def test_shortcut_failure_falls_back_to_start_path(self):
        with tempfile.TemporaryDirectory(prefix="kdog-shortcut-") as temporary:
            failed = subprocess.CompletedProcess([], 1, stdout=b"", stderr=b"denied")
            with patch.object(installer.subprocess, "run", return_value=failed):
                self.assertIsNone(installer.shortcut(Path(temporary) / "app", Path(temporary) / "desk"))
            with patch.object(installer.subprocess, "run", side_effect=OSError):
                self.assertIsNone(installer.shortcut(Path(temporary) / "app", Path(temporary) / "desk"))


if __name__ == "__main__":
    unittest.main()
