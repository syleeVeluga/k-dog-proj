"""GK-T01–T06: synthetic credentials and real Windows DPAPI, no provider traffic."""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from fastapi import HTTPException

from app import maintenance, secrets
from app.gemini import ProviderError
from app.storage import Store
from tests.support import AppCase


class GeminiKeySlotTests(AppCase):
    def setUp(self):
        super().setUp()
        self.env = patch.dict(os.environ, {"GEMINI_API_KEY": "synthetic-environment-primary"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.login("developer")

    def slots(self):
        response = self.client.get("/api/developer/settings")
        self.assertEqual(response.status_code, 200, response.text)
        return {s["slot"]: s for s in response.json()["gemini_slots"]}

    def put(self, slot, value, expected=None):
        return self.client.put(f"/api/developer/keys/gemini/slots/{slot}",
                               json={"value": value, "expected_reference": expected})

    def remove(self, slot, expected):
        return self.client.request("DELETE", f"/api/developer/keys/gemini/slots/{slot}",
                                   json={"expected_reference": expected})

    def test_legacy_primary_and_environment_without_backup(self):
        slots = self.slots()
        self.assertEqual(slots["primary"]["source"], "environment")
        self.assertEqual(slots["primary"]["reference"], "environment")
        self.assertEqual(slots["backup"]["source"], "none")
        self.assertIsNone(slots["backup"]["reference"])
        legacy = self.client.put("/api/developer/keys/gemini", json={"value": "synthetic-legacy-primary"}).json()
        before = self.store.path(f"secrets/{legacy['reference']}.bin").read_bytes()
        self.assertEqual(self.slots()["primary"]["reference"], legacy["reference"])
        self.assertEqual(self.put("backup", "synthetic-backup").status_code, 200)
        self.assertEqual(self.store.path(f"secrets/{legacy['reference']}.bin").read_bytes(), before)
        self.assertEqual(secrets.credential(self.store, "gemini"), ("synthetic-legacy-primary", legacy["reference"]))

    def test_independent_rotation_removal_and_atomic_global_stop(self):
        primary = self.put("primary", "synthetic-primary", "environment").json()
        backup = self.put("backup", "synthetic-backup").json()
        rotated = self.put("backup", "synthetic-backup-new", backup["reference"])
        self.assertEqual(rotated.status_code, 200, rotated.text)
        backup = rotated.json()
        self.assertEqual(secrets.credential(self.store, "gemini")[1], primary["reference"])
        self.assertNotIn(b"synthetic-primary", self.store.path(f"secrets/{primary['reference']}.bin").read_bytes())
        self.assertEqual(self.remove("primary", primary["reference"]).status_code, 200)
        with self.assertRaises(ProviderError) as missing:
            secrets.credential(self.store, "gemini")
        self.assertEqual(missing.exception.credential_reason, "removed")
        self.assertEqual(secrets.credential(self.store, "gemini", "backup")[1], backup["reference"])
        with patch.object(Path, "unlink", side_effect=PermissionError("synthetic cleanup lock")):
            self.assertEqual(self.client.delete("/api/developer/keys/gemini").status_code, 200)
        self.assertTrue(all(not s["available"] for s in self.slots().values()))
        for slot in ("primary", "backup"):
            with self.assertRaises(ProviderError):
                secrets.credential(self.store, "gemini", slot)
        self.assertEqual(self.put("primary", "synthetic-reregister", self.slots()["primary"]["reference"]).status_code, 200)
        self.assertFalse(self.slots()["backup"]["available"])

    def test_stale_edit_and_duplicate_plaintext_rejected_without_secret_echo(self):
        key = "synthetic-environment-primary"
        self.assertEqual(self.put("backup", key).status_code, 409)
        self.assertEqual(self.put("primary", "synthetic-primary", None).status_code, 409)
        first = self.put("backup", "synthetic-backup").json()
        second = self.put("backup", "synthetic-backup-new", first["reference"]).json()
        self.assertEqual(self.put("backup", key, first["reference"]).status_code, 409)
        self.assertEqual(self.remove("backup", first["reference"]).status_code, 409)
        self.assertEqual(self.slots()["backup"]["reference"], second["reference"])
        self.assertEqual(self.put("primary", "synthetic-backup-new", "environment").status_code, 409)
        self.assertNotIn(key, self.client.get("/api/developer/settings").text)

    def test_write_fence_serializes_slots_and_rechecks_current_developer(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda slot: secrets.change(
                self.store, "gemini", f"synthetic-{slot}", "developer", slot=slot,
                expected_reference="environment" if slot == "primary" else None, check_reference=True),
                ("primary", "backup")))
        self.assertEqual(len(list(self.store.path("secrets").glob("*.bin"))), 2)
        for result in results:
            self.assertEqual(secrets.credential(self.store, "gemini", result["slot"])[1], result["reference"])
        with self.store.connect(write=True) as db:
            db.execute("UPDATE users SET active=0 WHERE username='developer'")
        with self.assertRaises(HTTPException) as denied:
            secrets.change(self.store, "gemini", "synthetic-denied", "developer")
        self.assertEqual(denied.exception.status_code, 403)

    def test_concurrent_same_slot_only_one_expected_reference_wins(self):
        def change(index):
            try:
                secrets.change(self.store, "gemini", f"synthetic-race-{index}", "developer", slot="backup",
                               expected_reference=None, check_reference=True)
                return 200
            except HTTPException as exc:
                return exc.status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(change, range(2))), [200, 409])
        self.assertEqual(len(list(self.store.path("secrets").glob("*.bin"))), 1)

    def test_global_stop_failure_rolls_back_both_slots(self):
        primary = self.put("primary", "synthetic-primary", "environment").json()
        backup = self.put("backup", "synthetic-backup").json()
        audit = self.store.audit
        def fail_second(db, actor, target, action, detail):
            if target == "gemini:backup" and action == "secret.change":
                raise RuntimeError("synthetic transaction failure")
            return audit(db, actor, target, action, detail)
        with patch.object(self.store, "audit", side_effect=fail_second), self.assertRaises(RuntimeError):
            secrets.change(self.store, "gemini", None, "developer")
        self.assertEqual(secrets.credential(self.store, "gemini")[1], primary["reference"])
        self.assertEqual(secrets.credential(self.store, "gemini", "backup")[1], backup["reference"])

    def test_worker_reads_consistent_credentials_during_both_slot_rotations(self):
        def rotate(slot):
            for index in range(5):
                secrets.change(self.store, "gemini", f"synthetic-{slot}-{index}", "developer", slot=slot)
        def read():
            for index in range(10):
                for slot in ("primary", "backup"):
                    try:
                        value, reference = secrets.credential(self.store, "gemini", slot)
                    except ProviderError as exc:
                        self.assertEqual(exc.credential_reason, "unregistered")
                    else:
                        self.assertTrue(value.startswith(f"synthetic-{slot}-") or reference == "environment")
        with ThreadPoolExecutor(max_workers=3) as executor:
            for future in (executor.submit(rotate, "primary"), executor.submit(rotate, "backup"), executor.submit(read)):
                future.result()
        self.assertEqual(len(list(self.store.path("secrets").glob("*.bin"))), 2)

    def test_missing_ciphertext_and_failed_decrypt_are_locally_unavailable(self):
        backup = self.put("backup", "synthetic-backup").json()
        with patch("app.secrets.protect", side_effect=HTTPException(409, "synthetic DPAPI failure")):
            self.assertEqual(self.slots()["backup"]["unavailable_reason"], "decrypt_failed")
        self.store.path(f"secrets/{backup['reference']}.bin").unlink()
        self.assertEqual(self.slots()["backup"]["unavailable_reason"], "file_unavailable")
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            self.assertEqual(self.slots()["primary"]["source"], "none")

    def test_tests_are_slot_reference_and_time_pinned_during_rotation(self):
        first = self.put("backup", "synthetic-backup").json()
        def rotate(*args, **kwargs):
            self.assertEqual(args[2], "synthetic-backup")
            secrets.change(self.store, "gemini", "synthetic-backup-new", "developer", slot="backup",
                           expected_reference=first["reference"], check_reference=True)
            return {}, {}
        with patch("app.gemini.request", side_effect=rotate) as request:
            result = self.client.post("/api/developer/keys/gemini/slots/backup/test")
            self.assertEqual(request.call_count, 1)
        self.assertEqual(result.json()["reference"], first["reference"])
        self.assertEqual(result.json()["slot"], "backup")
        self.assertTrue(result.json()["tested_at"])
        self.assertIsNone(self.slots()["backup"]["last_test"])
        with patch("app.gemini.request", return_value=({}, {})):
            current = self.client.post("/api/developer/keys/gemini/slots/backup/test").json()
        self.assertEqual(self.slots()["backup"]["last_test"], current)
        self.assertIsNone(self.slots()["primary"]["last_test"])
        with patch("app.gemini.request", side_effect=ProviderError("provider_http_403")) as request:
            self.assertEqual(self.client.post("/api/developer/keys/gemini/slots/primary/test").json()["status"], "provider_http_403")
            self.assertEqual(request.call_count, 1)

    def test_historical_and_late_connection_results_keep_current_reference(self):
        with self.store.connect(write=True) as db:
            secrets._developer(db, "developer")
            self.store.audit(db, "developer", "gemini", "secret.test",
                             {"provider": "gemini", "reference": "environment", "status": "connected"})
        test = self.slots()["primary"]["last_test"]
        self.assertEqual(test["slot"], "primary")
        self.assertTrue(test["tested_at"])
        with self.store.connect(write=True) as db:
            self.store.audit(db, "developer", "gemini", "secret.test",
                             {"provider": "gemini", "reference": "retired-reference", "status": "connected"})
        self.assertEqual(self.slots()["primary"]["last_test"], test)

    def test_slot_security_validation_origin_host_and_no_plaintext_backup(self):
        path = "/api/developer/keys/gemini/slots/backup"
        key = "synthetic-security-secret"
        for role in ("operator", "reviewer", "admin"):
            self.login(role)
            self.assertEqual(self.put("backup", key).status_code, 403)
            self.assertEqual(self.remove("backup", None).status_code, 403)
            self.assertEqual(self.client.post(path + "/test").status_code, 403)
        self.client.cookies.clear()
        self.assertEqual(self.put("backup", key).status_code, 401)
        self.login("developer")
        for value in ("short", key * 30, {"secret": key}):
            response = self.put("backup", value)
            self.assertEqual(response.status_code, 422, response.text)
            self.assertNotIn(key, response.text)
        for headers, expected_status in (({"Origin": "https://evil.invalid"}, 403), ({"Host": "evil.invalid"}, 400)):
            response = self.client.put(path, json={"value": key, "expected_reference": None}, headers=headers)
            self.assertEqual(response.status_code, expected_status, response.text)
        self.assertEqual(self.put("unknown", key).status_code, 422)
        self.assertEqual(self.put("backup", key).status_code, 200)
        self.assertEqual(self.put("primary", "synthetic-security-primary", "environment").status_code, 200)
        self.assertIn("no-store", self.client.get("/api/developer/settings").headers["cache-control"])
        for file in self.store.root.rglob("*"):
            if file.is_file():
                self.assertNotIn(key.encode(), file.read_bytes(), str(file))
        with tempfile.TemporaryDirectory() as directory:
            backup = Path(directory) / "backup"
            maintenance.backup(self.store, backup, "developer")
            self.assertFalse((backup / "secrets").exists())
            maintenance.restore(self.store, backup, Path(directory) / "restored")
            restored = Store(Path(directory) / "restored")
            self.assertTrue(all(not s["available"] for s in secrets.slot_states(restored)))
            for slot in ("primary", "backup"):
                with self.assertRaises(ProviderError):
                    secrets.credential(restored, "gemini", slot)

    def test_other_provider_storage_remains_independent(self):
        response = self.client.put("/api/developer/keys/openai", json={"value": "synthetic-openai"})
        self.assertEqual(response.status_code, 200)
        self.put("backup", "synthetic-backup")
        self.client.delete("/api/developer/keys/gemini")
        self.assertEqual(secrets.credential(self.store, "openai")[0], "synthetic-openai")
