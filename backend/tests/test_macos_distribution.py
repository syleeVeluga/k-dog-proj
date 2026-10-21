"""macOS dispatch, authenticated vault and ZIP contract; native checks are explicit."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

from fastapi import HTTPException

from app import launcher, macos_keychain, secrets
from app.storage import REPO_ROOT


class MacOSVaultTests(unittest.TestCase):
    def test_ciphertext_roundtrip_random_nonce_and_tampering(self):
        with patch.object(macos_keychain, "keychain_key", return_value=b"k" * 32) as key:
            first = macos_keychain.protect(b"synthetic-provider-key")
            second = macos_keychain.protect(b"synthetic-provider-key")
            self.assertNotEqual(first, second)
            self.assertNotIn(b"synthetic-provider-key", first)
            self.assertEqual(macos_keychain.protect(first, decrypt=True), b"synthetic-provider-key")
            key.assert_called_with(create=False)
            for damaged in (b"", b"DPAPI", first[:-1], first[:-1] + bytes([first[-1] ^ 1])):
                with self.assertRaises(HTTPException) as error:
                    macos_keychain.protect(damaged, decrypt=True)
                self.assertEqual(error.exception.status_code, 409)

    def test_unavailable_keychain_has_no_plaintext_or_new_key_fallback(self):
        ciphertext = macos_keychain.HEADER + b"n" * 12 + b"c" * 16
        with patch.object(macos_keychain, "keychain_key", side_effect=ValueError("denied")) as key:
            with self.assertRaises(HTTPException):
                macos_keychain.protect(ciphertext, decrypt=True)
            key.assert_called_once_with(create=False)
            with self.assertRaises(HTTPException):
                macos_keychain.protect(b"synthetic-provider-key")

    def test_darwin_dispatch_does_not_call_windows_dpapi(self):
        with patch.object(secrets, "sys", SimpleNamespace(platform="darwin")), patch.object(
                macos_keychain, "protect", return_value=b"encrypted") as protect:
            self.assertEqual(secrets.protect(b"synthetic-key"), b"encrypted")
            protect.assert_called_once_with(b"synthetic-key", decrypt=False)

    def test_posix_session_cleanup_is_scoped_to_attached_children(self):
        kill = Mock()
        with patch.object(launcher, "os", SimpleNamespace(name="posix", killpg=kill)), patch.object(
                launcher, "signal", SimpleNamespace(SIGKILL=9)):
            with launcher.process_group() as attach:
                attach(Mock(pid=12345))
                attach(Mock(pid=23456))
            self.assertEqual([call.args[0] for call in kill.call_args_list], [12345, 23456])

    def test_supervisor_eof_kills_only_an_isolated_posix_session(self):
        for group, expected in ((12345, True), (23456, False)):
            kill, leave = Mock(), Mock()
            fake_os = SimpleNamespace(name="posix", getpid=lambda: 12345, getpgrp=lambda: group,
                                      killpg=kill, _exit=leave)
            with patch.object(launcher, "os", fake_os), patch.object(launcher, "signal", SimpleNamespace(SIGKILL=9)):
                launcher.supervisor_exit()
                self.assertEqual(kill.called, expected)
                leave.assert_called_once_with(0)


class MacOSPackageTests(unittest.TestCase):
    @unittest.skipUnless((REPO_ROOT / "frontend/dist/index.html").is_file(), "build frontend first")
    def test_archive_contains_unix_launchers_hashes_and_no_windows_runtime(self):
        spec = importlib.util.spec_from_file_location("macos_release_test", REPO_ROOT / "scripts/build_release.py")
        release = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release)
        tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=REPO_ROOT)
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT)

        def git_output(command, **kwargs):
            return {("git", "status", "--porcelain"): b"", ("git", "ls-files", "-z"): tracked,
                    ("git", "rev-parse", "HEAD"): commit}[tuple(command)]

        with tempfile.TemporaryDirectory(prefix="kdog-mac-zip-") as temporary, patch.object(
                release.subprocess, "check_output", side_effect=git_output), patch.object(release.subprocess, "run"):
            destination = Path(temporary) / "mac.zip"
            release.build(destination, "macos-online")
            with ZipFile(destination) as archive:
                names = archive.namelist()
                manifest = json.loads(archive.read("release.json"))
                self.assertEqual(manifest["variant"], "macos-online")
                self.assertEqual(manifest["platform"], "darwin")
                self.assertIn("backend/uv.lock", names)
                self.assertIn("macOS_설치안내.md", names)
                self.assertIn("backend/app/macos_keychain.py", names)
                self.assertFalse(any(name.startswith("runtime/") or name.endswith((".exe", ".cmd", ".ps1")) for name in names))
                for name in ("Install.command", "Start.command"):
                    info = archive.getinfo(name)
                    self.assertEqual(info.create_system, 3)
                    self.assertEqual((info.external_attr >> 16) & 0o777, 0o755)
                    self.assertNotIn(b"\r", archive.read(name))
                sums = dict(line.split("  ", 1)[::-1] for line in archive.read("SHA256SUMS").decode().splitlines())
                self.assertEqual(set(sums), set(manifest["files"]) | {"release.json"})
                for name, digest in sums.items():
                    self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest, name)

    def test_default_macos_data_path_is_outside_program_directory(self):
        code = "import app.api, importlib, sys; sys.platform='darwin'; print(importlib.reload(app.api).DEFAULT_DATA)"
        result = subprocess.check_output([sys.executable, "-X", "utf8", "-c", code], cwd=REPO_ROOT / "backend")
        self.assertEqual(result.decode().strip(), str(Path.home() / "Library/Application Support/K-DOG/data"))


@unittest.skipUnless(sys.platform == "darwin", "requires a real macOS login Keychain")
class NativeKeychainTests(unittest.TestCase):
    def test_keychain_creation_read_and_missing_decryption(self):
        # Dedicated test item only; never modify the application's actual vault item.
        import uuid
        service = "K-DOG test " + uuid.uuid4().hex
        try:
            with self.assertRaises(ValueError):
                macos_keychain.keychain_key(service=service)
            first = macos_keychain.keychain_key(service=service, create=True)
            self.assertEqual(len(first), 32)
            self.assertEqual(macos_keychain.keychain_key(service=service), first)
            self.assertEqual(macos_keychain.keychain_key(service=service, create=True), first)
        finally:
            subprocess.run(["/usr/bin/security", "delete-generic-password", "-s", service, "-a", "aes256-v1"],
                           check=False, capture_output=True)


if __name__ == "__main__":
    unittest.main()
