"""M5 T08–T11: version fencing, secrets, isolated trials and data recovery."""

import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import maintenance, settings
from app.api import create_app
from app.auth import create_user
from app.input_models import UserCreate
from app.secrets import credential, protect
from app.secrets import change as change_key
from app.storage import Store, encode
from app.worker import Worker
from tests import test_observation as observation
from tests.evaluation_fixtures import FakeEvaluator
from tests.report_fixtures import FakeReporter


class SettingsTests(unittest.TestCase):
    login = observation.ObservationTests.login
    access = observation.ObservationTests.access
    start = observation.ObservationTests.start
    view = observation.ObservationTests.view

    def setUp(self):
        observation.ObservationTests.setUp(self)
        with self.store.connect(write=True) as db:
            create_user(db, UserCreate(username="admin", role="admin", password="Synthetic-test-only-42"))

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

    def test_draft_activate_restore_and_queued_running_snapshots_stay_frozen(self):
        queued = self.start()
        with self.store.connect() as db:
            old = db.execute("SELECT config_snapshot_json FROM runs WHERE run_id=?", (queued,)).fetchone()[0]
        first = self.draft()
        config = self.config()["config"]
        config["dog"]["prompt"] += "\n가상 추가 지시."
        second = self.draft(config)
        self.assertEqual(self.config()["active_version"], "legacy")
        diff = self.client.get(f"/api/developer/settings/{second}").json()["diff"]
        self.assertIn("가상 추가 지시", diff)
        self.activate(second)
        self.assertEqual(self.client.post(f"/api/developer/settings/{first}/activate", json={"expected_active": "legacy"}).status_code, 409)
        def switch_during_call(media, guard):
            self.activate(first)
            self.login("operator")
            return observation.response(), {"totalTokenCount": 1}
        self.observer.callback = switch_during_call
        self.worker.once()
        with self.store.connect() as db:
            self.assertEqual(old, db.execute("SELECT config_snapshot_json FROM runs WHERE run_id=?", (queued,)).fetchone()[0])
        self.assertEqual(self.view()["status"], "scored")
        new = self.start(reanalyze=True)
        with self.store.connect() as db:
            snapshot = json.loads(db.execute("SELECT config_snapshot_json FROM runs WHERE run_id=?", (new,)).fetchone()[0])
        self.assertEqual(snapshot["settings_version"], first)
        self.assertNotIn("가상 추가 지시", snapshot["evaluation"]["dog"]["prompt"])

    def test_editing_owner_reuses_observation_and_dog_but_not_owner(self):
        first = self.draft()
        self.activate(first)
        self.login("operator")
        old = self.start()
        self.worker.once()
        config = self.config()["config"]
        config["owner"]["prompt"] += "\n시험 변경"
        second = self.draft(config)
        self.activate(second)
        self.login("operator")
        new = self.start(reanalyze=True, reuse_run_id=old)
        with self.store.connect() as db:
            reuse = json.loads(db.execute("SELECT reuse_manifest_json FROM runs WHERE run_id=?", (new,)).fetchone()[0])
        self.assertEqual(len([r for r in reuse if r.get("stage", "observe") == "observe"]), 2)
        self.assertEqual([r["branch"] for r in reuse if r.get("stage") == "evaluate"], ["dog"])

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

    def test_trials_never_create_case_runs_or_change_active_version(self):
        version = self.draft()
        for stage in ("observe", "dog", "owner", "report"):
            result = self.client.post(f"/api/developer/settings/{version}/trial", json={"stage": stage, "mode": "schema"})
            self.assertEqual(result.json()["status"], "schema_valid")
        fake = FakeEvaluator()
        with patch("app.developer_sample.Evaluator", return_value=fake), patch("app.developer_sample.Reporter", return_value=FakeReporter()):
            for stage in ("dog", "owner", "report"):
                result = self.client.post(f"/api/developer/settings/{version}/trial", json={"stage": stage, "mode": "provider"})
                self.assertEqual(result.json()["status"], "provider_valid", result.text)
        self.assertEqual(self.config()["active_version"], "legacy")
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM cases").fetchone()[0], 1)

    def test_frozen_call_budget_stops_parallel_requests_and_preserves_completed_observations(self):
        config = self.config()["config"]
        config["max_ai_calls"] = 3
        config["max_attempts"] = 1
        self.activate(self.draft(config))
        self.login("operator")
        self.start()
        self.worker.once()
        result = self.view()
        self.assertEqual(result["status"], "partial_failed")
        self.assertEqual(len(result["evidence"]), 2)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT SUM(call_reserved) FROM steps").fetchone()[0], 3)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM steps WHERE stage='evaluate' AND status='succeeded'").fetchone()[0], 1)
            failed = [json.loads(r[0]) for r in db.execute("SELECT usage_json FROM steps WHERE status='failed'")]
        self.assertIn("call_budget_exhausted", [f["code"] for f in failed])

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

    def test_backup_restore_keeps_report_files_and_reapplies_current_deletion_ledger(self):
        run_id = self.start()
        self.worker.once()
        exported = self.client.post("/api/exports", json={"format": "xlsx", "case_id": self.item["case_id"], "run_id": run_id}).json()
        self.assertEqual(self.client.post(f"/api/exports/{exported['export_id']}/generate").status_code, 200)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            maintenance.backup(self.store, root / "backup", "admin")
            maintenance.restore(self.store, root / "backup", root / "restored")
            restored = Store(root / "restored")
            with restored.connect() as db:
                maintenance.references(restored, db)
                self.assertEqual(db.execute("SELECT status FROM runs").fetchone()[0], "scored")
            client = TestClient(create_app(restored.root), base_url="http://127.0.0.1:8000", headers={"X-KDOG-Request": "1"})
            self.addCleanup(client.close)
            client.post("/api/auth/login", json={"username": "operator", "password": "Synthetic-test-only-42"})
            self.assertEqual(client.get(f"/api/exports/{exported['export_id']}/file").status_code, 200)
            self.access(delete=True)
            maintenance.clean(self.store, purge_deleted=True)
            self.assertNotIn("가상견".encode(), (self.store.root / "kdog.sqlite3").read_bytes())
            self.assertEqual(maintenance.deletion_records(self.store), {("M2", "0001")})
            maintenance.restore(self.store, root / "backup", root / "deleted-restored")
            recovered = Store(root / "deleted-restored")
            with recovered.connect() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM cases").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action='export.snapshot'").fetchone()[0], 0)
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

    def test_cold_review_corrupt_active_settings_cannot_hide_old_results(self):
        version = self.draft()
        self.activate(version)
        self.login("operator")
        run_id = self.start()
        self.worker.once()
        self.store.path(f"settings/{version}.json").write_text("{}")
        self.assertEqual(self.view()["status"], "scored")
        self.assertEqual(self.client.get(f"{self.base}/reports/{run_id}").status_code, 200)

    def test_actual_worker_exit_between_file_and_db_recovers_from_backup_without_recall(self):
        run_id = self.start()
        script = '''
import os, sys
from pathlib import Path
from app.storage import Store
from app.worker import Worker
import app.worker as module
from app.maintenance import runtime_lock
from tests.test_observation import FakeObserver, fake_probe
from tests.evaluation_fixtures import FakeEvaluator
from tests.report_fixtures import FakeReporter
store = Store(Path(sys.argv[1]))
original = module.adopt
def interrupted(store, row, step, *args):
    with store.connect() as db:
        stage = db.execute('SELECT stage FROM steps WHERE step_id=?', (step['step_id'],)).fetchone()[0]
    if stage == 'observe':
        os._exit(91)
    return original(store, row, step, *args)
module.adopt = interrupted
with runtime_lock(store, 'worker'):
    Worker(store, observer=FakeObserver(), evaluator=FakeEvaluator(), reporter=FakeReporter(), probe=fake_probe).once()
'''
        result = subprocess.run([sys.executable, "-X", "utf8", "-c", script, str(self.store.root)],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, 91, result.stderr.decode())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            maintenance.backup(self.store, root / "backup", "admin")
            maintenance.restore(self.store, root / "backup", root / "recovered")
            recovered = Store(root / "recovered")
            observer = observation.FakeObserver()
            worker = Worker(recovered, observer=observer, evaluator=FakeEvaluator(), reporter=FakeReporter(), probe=observation.fake_probe)
            self.assertTrue(worker.once())
            self.assertEqual(len(observer.calls), 1)
            with recovered.connect() as db:
                self.assertEqual(db.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()[0], "scored")
                self.assertEqual(db.execute("SELECT COUNT(*) FROM steps WHERE stage='observe' AND attempt=1 AND status='succeeded'").fetchone()[0], 2)

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
