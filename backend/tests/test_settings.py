"""Developer settings, key vault, backup/restore and offline cleanup — infrastructure kept for the 42-item build."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException

from app import maintenance
from app.secrets import credential, protect
from app.secrets import change as change_key
from app.storage import Store, encode
from tests.support import AppCase


class SettingsTests(AppCase):
    def setUp(self):
        super().setUp()
        self.env = patch.dict(os.environ, {"KDOG_GEMINI_MODEL": "gemini-test-only", "GEMINI_API_KEY": "synthetic-secret-only"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.item = self.make_case(event_id="M2")
        self.base = f"/api/cases/{self.item['case_id']}"

    def config(self):
        self.login("developer")
        response = self.client.get("/api/developer/settings")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def draft(self, value=None):
        data = self.config()
        response = self.client.post("/api/developer/settings/drafts", json={"expected_active": data["active_version"], "config": value or data["config"]})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["version"]

    def activate(self, version):
        data = self.config()
        result = self.client.post(f"/api/developer/settings/{version}/activate", json={"expected_active": data["active_version"]})
        self.assertEqual(result.status_code, 200, result.text)

    def test_every_developer_route_denies_staff_and_data_routes_deny_developer(self):
        version = self.draft()
        for role in ("operator", "reviewer", "admin"):
            self.login(role)
            for method, url, value in [
                ("get", "/api/developer/settings", None), ("get", f"/api/developer/settings/{version}", None),
                ("post", "/api/developer/settings/drafts", {"expected_active": "legacy", "config": {}}),
                ("post", f"/api/developer/settings/{version}/activate", {"expected_active": "legacy"}),
                ("post", f"/api/developer/settings/{version}/trial", {"stage": "dog", "mode": "provider"}),
                ("put", "/api/developer/keys/gemini", {"value": "synthetic-secret"}),
                ("delete", "/api/developer/keys/gemini", None), ("post", "/api/developer/keys/gemini/test", None),
            ]:
                response = getattr(self.client, method)(url, **({"json": value} if value is not None else {}))
                self.assertEqual(response.status_code, 403, (role, url, response.text))
        self.login("developer")
        for url in (self.base, "/api/cases", "/api/admin/recovery"):
            self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post("/api/admin/backups").status_code, 403)

    def test_draft_activate_restore_and_diff(self):
        first = self.draft()
        config = self.config()["config"]
        config["dog"]["prompt"] += "\n가상 추가 지시."
        second = self.draft(config)
        self.assertEqual(self.config()["active_version"], "legacy")
        diff = self.client.get(f"/api/developer/settings/{second}").json()["diff"]
        self.assertIn("가상 추가 지시", diff)
        self.activate(second)
        self.assertEqual(self.client.post(f"/api/developer/settings/{first}/activate", json={"expected_active": "legacy"}).status_code, 409)
        self.activate(first)
        self.assertEqual(self.config()["active_version"], first)

    def test_config_rejects_unknown_fields_provider_options_and_nonfinite_limits(self):
        data = self.config()
        for stage in ("observe", "dog", "owner", "report"):
            data["config"][stage]["max_output_tokens"] = 65536
        self.assertEqual(self.client.post("/api/developer/settings/drafts", json={
            "expected_active": "legacy", "config": data["config"]}).status_code, 201)
        data["config"]["dog"]["max_output_tokens"] = 65537
        self.assertEqual(self.client.post("/api/developer/settings/drafts", json={
            "expected_active": "legacy", "config": data["config"]}).status_code, 422)
        data = self.config()
        for field, value in [("max_attempts", 4), ("max_ai_calls", 0), ("evaluation_concurrency", 3), ("fps", 0), ("catalog", [])]:
            response = self.client.post("/api/developer/settings/drafts", json={"expected_active": "legacy", "config": {**data["config"], field: value}})
            self.assertEqual(response.status_code, 422, response.text)
        data["config"]["observe"]["provider"] = "openai"
        self.assertEqual(self.client.post("/api/developer/settings/drafts", json={"expected_active": "legacy", "config": data["config"]}).status_code, 422)

    def test_sampling_and_reasoning_options_are_mutually_checked(self):
        data = self.config()
        base = data["config"]
        self.assertEqual(base["processing_mode"], "static")
        # Agentic navigation has no frame rate, so specifying one is a contradiction, not a hint.
        rejected = [{"processing_mode": "agentic", "fps": 2.0}, {"thinking_level": "minimal"},
                    {"thinking_level": "none"}, {"media_resolution": "ultra_high"}, {"processing_mode": "adaptive"}]
        for value in rejected:
            response = self.client.post("/api/developer/settings/drafts",
                                        json={"expected_active": "legacy", "config": {**base, **value}})
            self.assertEqual(response.status_code, 422, response.text)
        for value in [{"processing_mode": "agentic"}, {"processing_mode": "agentic", "fps": 1.0},
                      {"thinking_level": "high", "media_resolution": "low"}, {"processing_mode": "static", "fps": 0.5}]:
            response = self.client.post("/api/developer/settings/drafts",
                                        json={"expected_active": "legacy", "config": {**base, **value}})
            self.assertEqual(response.status_code, 201, response.text)

    def test_inference_settings_version_the_snapshot(self):
        from app.settings import apply_snapshot
        base = self.config()["config"]
        versions = []
        for value in [{}, {"processing_mode": "agentic"}, {"thinking_level": "high"}, {"media_resolution": "high"}]:
            version = self.draft({**base, **value})
            self.activate(version)
            snapshot = {}
            with self.store.connect() as db:
                apply_snapshot(self.store, db, snapshot)
            versions.append(snapshot["config_version"])
            self.assertEqual(snapshot["processing_mode"], value.get("processing_mode", "static"))
            self.assertEqual(snapshot["thinking_level"], value.get("thinking_level"))
            self.assertEqual(snapshot["media_resolution"], value.get("media_resolution"))
        self.assertEqual(len(set(versions)), 4)

    def test_schema_trials_never_create_case_runs_or_change_active_version(self):
        version = self.draft()
        for stage in ("observe", "dog", "owner", "report"):
            result = self.client.post(f"/api/developer/settings/{version}/trial", json={"stage": stage, "mode": "schema"})
            self.assertEqual(result.json()["status"], "schema_valid")
        self.assertEqual(self.config()["active_version"], "legacy")
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM cases").fetchone()[0], 1)

    @unittest.skipUnless(os.name == "nt", "DPAPI requires Windows")
    def test_key_ciphertext_rotation_revocation_connection_and_no_plaintext_in_backups(self):
        self.login("developer")
        key = "synthetic-m5-key-never-live"
        self.assertEqual(protect(protect(key.encode()), decrypt=True), key.encode())
        response = self.client.put("/api/developer/keys/gemini", json={"value": key})
        self.assertEqual(response.status_code, 200, response.text)
        first = response.json()["reference"]
        self.assertNotIn(key, response.text + self.client.get("/api/developer/settings").text)
        self.assertEqual(credential(self.store, "gemini"), (key, first))
        with patch("app.gemini.request", return_value=({}, {})) as request:
            result = self.client.post("/api/developer/keys/gemini/test")
            self.assertEqual(result.json()["status"], "connected")
            self.assertEqual(request.call_args.args[2], key)
        next_key = key + "-rotated"
        second = self.client.put("/api/developer/keys/gemini", json={"value": next_key}).json()["reference"]
        self.assertNotEqual(first, second)
        self.assertEqual(credential(self.store, "gemini"), (next_key, second))
        # Database, normal artifacts, settings and ciphertext never contain the key bytes.
        for path in self.store.root.rglob("*"):
            if path.is_file():
                self.assertNotIn(key.encode(), path.read_bytes(), str(path))
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "backup"
            maintenance.backup(self.store, destination, "admin")
            self.assertFalse((destination / "secrets").exists())
            for path in destination.rglob("*"):
                if path.is_file():
                    self.assertNotIn(key.encode(), path.read_bytes())
        self.assertEqual(self.client.delete("/api/developer/keys/gemini").status_code, 200)
        from app.gemini import ProviderError
        with self.assertRaises(ProviderError):
            credential(self.store, "gemini")  # Must not fall back to the configured environment key.

    def test_backup_restore_keeps_inputs_and_reapplies_current_deletion_ledger(self):
        item = self.upload(self.item).json()
        saved = self.client.put(self.base + "/survey", json=self.answers(item, 4, not_applicable=("s07",))).json()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            maintenance.backup(self.store, root / "backup", "admin")
            maintenance.restore(self.store, root / "backup", root / "restored")
            restored = Store(root / "restored")
            with restored.connect() as db:
                maintenance.references(restored, db)
                row = restored.case(db, item["case_id"])
                manifest = restored.manifest(row)
            self.assertEqual(manifest.model_dump(), saved["manifest"])
            self.delete_case(saved)
            maintenance.clean(self.store, purge_deleted=True)
            self.assertNotIn("가상견".encode(), (self.store.root / "kdog.sqlite3").read_bytes())
            self.assertEqual(maintenance.deletion_records(self.store), {("M2", "0001")})
            maintenance.restore(self.store, root / "backup", root / "deleted-restored")
            recovered = Store(root / "deleted-restored")
            with recovered.connect() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM cases").fetchone()[0], 0)
            self.assertFalse(any((recovered.root / "videos").glob("*")))

    def test_backup_corruption_and_path_traversal_rejected_before_destination_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            maintenance.backup(self.store, root / "backup", "admin")
            manifest_path = root / "backup/backup.json"
            manifest = json.loads(manifest_path.read_bytes())
            manifest["files"]["../escape"] = "0" * 64
            manifest_path.write_text(encode(manifest), encoding="utf-8")
            with self.assertRaises(HTTPException):
                maintenance.restore(self.store, root / "backup", root / "invalid")
            self.assertFalse((root / "invalid").exists())
            del manifest["files"]["../escape"]
            manifest["files"]["kdog.sqlite3"] = "0" * 64
            manifest_path.write_text(encode(manifest), encoding="utf-8")
            with self.assertRaises(HTTPException):
                maintenance.restore(self.store, root / "backup", root / "invalid")

    def test_offline_cleanup_refuses_running_process_and_keeps_referenced_files(self):
        orphan = self.store.path("inputs/unreferenced.json")
        orphan.write_text("{}")
        with maintenance.runtime_lock(self.store, "api"):
            with self.assertRaises(HTTPException):
                maintenance.clean(self.store)
        self.assertTrue(orphan.exists())
        result = maintenance.clean(self.store)
        self.assertGreaterEqual(result["removed_files"], 1)
        self.assertFalse(orphan.exists())
        self.assertEqual(self.client.get(self.base).status_code, 200)

    @unittest.skipUnless(os.name == "nt", "DPAPI requires Windows")
    def test_cold_review_simultaneous_rotations_never_remove_the_current_ciphertext(self):
        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(lambda i: change_key(self.store, "gemini", f"synthetic-concurrent-{i}", "developer"), range(12)))
        value, reference = credential(self.store, "gemini")
        self.assertTrue(value.startswith("synthetic-concurrent-"))
        self.assertIn(reference, [r["reference"] for r in results])
        self.assertEqual(len(list(self.store.path("secrets").glob("*.bin"))), 1)

    def test_cold_review_failed_restore_never_publishes_and_missing_tombstones_survive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.store.connect(write=True) as db:
                self.store.audit(db, "admin", "absent-case", "deletion.record", {"event_id": "OLDER", "participant_id": "9999"})
            maintenance.backup(self.store, root / "backup", "admin")
            with patch("app.maintenance.clean", side_effect=OSError("synthetic disk failure")):
                with self.assertRaises(OSError):
                    maintenance.restore(self.store, root / "backup", root / "failed")
            self.assertFalse((root / "failed").exists())
            # Ledger entry added after backup, with no matching participant in that backup.
            with self.store.connect(write=True) as db:
                self.store.audit(db, "admin", "new-absent-case", "deletion.record", {"event_id": "NEW", "participant_id": "8888"})
            maintenance.restore(self.store, root / "backup", root / "recovered")
            recovered = Store(root / "recovered")
            self.assertEqual(maintenance.deletion_records(recovered), {("OLDER", "9999"), ("NEW", "8888")})

    def test_provider_echoes_are_redacted_even_in_json_escapes_and_request_headers(self):
        from app.gemini import request, BASE
        from unittest.mock import MagicMock
        response = MagicMock()
        response.read.return_value = b'{"message":"synthetic-\\u0073ecret"}'
        response.headers = {"x-request-id": "synthetic-secret"}
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = response
        with patch("app.gemini.build_opener", return_value=opener):
            value, headers = request("GET", BASE + "/v1beta/models", "synthetic-secret")
        self.assertNotIn("synthetic-secret", encode(value) + encode(headers))


if __name__ == "__main__":
    unittest.main()
