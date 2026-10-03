"""Synthetic reset fixtures exercise preserved inputs, cleanup retries and old workers."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import analysis, maintenance, reset_s1
from app.domain.catalog import SURVEY_IDS
from app.gemini import GeminiObserver, ProviderError
from app.input_models_v3 import ManifestV3, SessionV3
from app.storage import Store, encode, now


class ResetS1Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kdog-reset-synthetic-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "data"
        self.store = Store(self.root)
        self.video = self.file("videos/received.mp4", b"synthetic-received-mp4")
        session = SessionV3(session_id="session", note="input note", survey_version="survey-20260929-v3",
                            protocol_version="protocol-20260929-v3", protocol_source="new_session",
                            survey={code: 2 if code == "s10" else None for code in SURVEY_IDS},
                            videos=[{"video_id": "video", "original_name": "received.mp4", "storage_ref": self.video[0],
                                     "sha256": self.video[1], "size_bytes": len(b"synthetic-received-mp4")}])
        self.manifest = ManifestV3(case_id="case", event_id="SYNTHETIC", participant_id="0001",
                                   input_revision=1, selected_session_id="session", sessions=[session])
        self.input_ref, self.input_hash = self.store.write_manifest(self.manifest)
        sheet_ref, sheet_hash = self.file("sheets/case/old.json", b'{"schema_version":"3.0","score":99}')
        self.result_ref, result_hash = self.file("results/old.json", b'{"score":99}')
        self.file("clips/old.mp4", b"regenerable")
        self.file("secrets/credential.bin", b"synthetic-credential-placeholder")
        settings_ref, settings_hash = self.file("settings/old.json", b'{"setting":"preserved"}')
        with self.store.connect(write=True) as db:
            db.execute("INSERT INTO users(username,password_hash,role) VALUES ('admin','synthetic','admin')")
            db.execute("INSERT INTO users(username,password_hash,role) VALUES ('operator','synthetic','operator')")
            db.execute("INSERT INTO cases(case_id,event_id,participant_id,dog_name,reservation_at,input_revision,selected_session_id,"
                       "manifest_ref,manifest_hash,created_at,updated_at,manifest_schema_version,consents_v3_json) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("case", "SYNTHETIC", "0001", "Synthetic dog", "", 1, "session", self.input_ref,
                        self.input_hash, now(), now(), "intake-3.0", self.manifest.consents.model_dump_json()))
            db.execute("INSERT INTO runs(run_id,case_id,session_id,input_revision,input_snapshot_json,config_snapshot_json,"
                       "status,claim_token,lease_expires_at,created_at,updated_at,kind) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("old-run", "case", "session", 1, self.manifest.model_dump_json(), '{}', "running", "old-token",
                        "2099-01-01T00:00:00+00:00", now(), now(), "scoring_v3"))
            db.execute("INSERT INTO steps(step_id,run_id,stage,branch_key,attempt,status,claim_token,usage_json,created_at,updated_at,call_reserved) "
                       "VALUES (?,?,?,?,?,?,?,?,?,?,?)", ("old-step", "old-run", "score_v3", "group", 1, "running", "old-token",
                        encode({"provider": "gemini", "model": "synthetic", "provider_usage": {"total_tokens": 7}}), now(), now(), 1))
            db.execute("INSERT INTO score_sheets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       ("sheet", "case", "session", "operator", "rater", "Synthetic rater", "source", "research", "draft", 1, 1, sheet_ref, sheet_hash))
            db.execute("INSERT INTO basic_results VALUES (?,?,?,?,?,?,?)", ("result", "sheet", "case", "session", 1, self.result_ref, result_hash))
            self.store.audit(db, "admin", "case", "basic.calculate", {"ref": self.result_ref, "hash": result_hash})
            self.store.audit(db, "admin", "settings", "settings.draft", {"ref": settings_ref, "hash": settings_hash})
            self.store.audit(db, "admin", "absent-case", "deletion.record", {"event_id": "ABSENT", "participant_id": "deleted"})
            self.old_run = dict(db.execute("SELECT * FROM runs").fetchone())
            self.old_step = dict(db.execute("SELECT * FROM steps").fetchone())

    def file(self, name, payload):
        path = self.store.path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return name, hashlib.sha256(payload).hexdigest()

    def original_input(self):
        original = {"schema_version": "intake-1.0", "case_id": "case", "event_id": "SYNTHETIC", "participant_id": "0001",
                    "input_revision": 1, "selected_session_id": "session", "display_run_id": "old-run",
                    "sessions": [{"session_id": "session", "capture_mode": "simultaneous", "route_note": "original route",
                                  "survey_version": "catalog-20260904-v1", "survey": {f"q{i:02}": i % 5 + 1 for i in range(1, 31)},
                                  "videos": [{**self.manifest.sessions[0].videos[0].model_dump(), "camera_id": "CAM-ORIGINAL"}],
                                  "checklist": {"entry": "performed", "training": "skipped"}}]}
        raw = encode(original).encode()
        ref, digest = self.file("inputs/original-1.json", raw)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE cases SET manifest_schema_version='intake-2.0',manifest_ref=?,manifest_hash=?", (ref, digest))
            db.execute("PRAGMA user_version=4")
        self.store = Store(self.root)
        return ref, raw

    def test_reset_removes_scores_preserves_inputs_accounts_settings_and_uncertain_usage(self):
        preview = reset_s1.preview(self.store)
        self.assertEqual((preview["cases"], preview["runs"], preview["sheets"]), (1, 1, 1))
        self.assertTrue(self.store.path(self.result_ref).exists())
        result = reset_s1.execute(self.store, "admin")
        self.assertEqual(result["status"], "complete")
        with self.store.connect() as db:
            value = self.store.manifest(self.store.case(db, "case"))
            for table in ("runs", "steps", "score_sheets", "score_grants", "basic_results"):
                self.assertEqual(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM users").fetchone()[0], 2)
            usage = json.loads(db.execute("SELECT detail_json FROM changes WHERE action='s1.reset.usage'").fetchone()[0])
            maintenance.references(self.store, db)
        self.assertEqual(value.schema_version, "intake-4.0")
        self.assertEqual(value.input_revision, 2)
        self.assertEqual(value.sessions[0].survey, self.manifest.sessions[0].survey)
        self.assertEqual(value.sessions[0].videos, self.manifest.sessions[0].videos)
        self.assertEqual(value.prior_inputs, [])
        self.assertIsNone(value.display_run_id)
        self.assertTrue(usage["billing_uncertain"])
        self.assertEqual(usage["meters"], {"total_tokens": 7})
        self.assertIsNone(usage["meter_cost_estimate"])
        self.assertFalse(self.store.path(self.result_ref).exists())
        self.assertFalse(self.store.path(self.input_ref).exists())
        self.assertEqual(maintenance.file_hash(self.store.path(self.video[0])), self.video[1])
        self.assertTrue(self.store.path("settings/old.json").exists())
        self.assertTrue(self.store.path("secrets/credential.bin").exists())
        self.assertIn(("absent-case", "ABSENT", "deleted"), maintenance.deletion_records(self.store))

    def test_original_30_answers_camera_and_checklist_survive_as_source_only_bytes(self):
        ref, raw = self.original_input()
        reset_s1.execute(self.store, "admin")
        with self.store.connect() as db:
            manifest = self.store.manifest(self.store.case(db, "case"))
            refs = maintenance.references(self.store, db)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)
        self.assertEqual(manifest.raw_input_sources[0].ref, ref)
        self.assertEqual(manifest.raw_input_sources[0].purpose, "source_only")
        self.assertEqual(manifest.prior_inputs, [])
        self.assertIn(ref, refs)
        self.assertEqual(self.store.path(ref).read_bytes(), raw)
        original = json.loads(raw)["sessions"][0]
        self.assertEqual(len(original["survey"]), 30)
        self.assertEqual(original["videos"][0]["camera_id"], "CAM-ORIGINAL")
        self.assertEqual(original["checklist"]["training"], "skipped")
        self.assertFalse(self.store.path(self.result_ref).exists())
        backup = Path(self.temp.name) / "source-backup"
        maintenance.backup(self.store, backup, "admin")
        destination = Path(self.temp.name) / "source-restored"
        maintenance.restore(self.store, backup, destination)
        self.assertEqual((destination / ref).read_bytes(), raw)

    def test_original_source_hash_identity_and_original_video_are_checked_before_reset(self):
        ref, raw = self.original_input()
        self.store.path(ref).write_bytes(raw + b" ")
        with self.assertRaises(HTTPException):
            reset_s1.execute(self.store, "admin")
        self.store.path(ref).write_bytes(raw)
        self.store.path(self.video[0]).write_bytes(b"bad original video")
        with self.assertRaises(HTTPException):
            reset_s1.execute(self.store, "admin")
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action='s1.reset.commit'").fetchone()[0], 0)

    def test_interrupted_file_cleanup_retries_fixed_generation_and_preserves_new_s1_results(self):
        original = Path.unlink
        def interrupted(path, *args, **kwargs):
            if path.name == "old.json":
                raise OSError("synthetic interrupted cleanup")
            return original(path, *args, **kwargs)
        with patch.object(Path, "unlink", interrupted), self.assertRaises(OSError):
            reset_s1.execute(self.store, "admin")
        self.assertEqual(reset_s1.preview(self.store)["status"], "cleanup_pending")
        new_ref, new_hash = self.file("results/new-s1.json", b'{"schema_version":"4.0","new":true}')
        with self.store.connect(write=True) as db:
            self.store.audit(db, "admin", "case", "basic.calculate", {"ref": new_ref, "hash": new_hash})
        reset_s1.execute(self.store, "admin")
        reset_s1.execute(self.store, "admin")
        self.assertTrue(self.store.path(new_ref).exists())
        with self.store.connect() as db:
            self.assertEqual(self.store.case(db, "case")["input_revision"], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action='s1.reset.plan'").fetchone()[0], 1)

    def test_offline_lock_permissions_and_tampered_input_stop_before_reset(self):
        with maintenance.runtime_lock(self.store, "worker"), self.assertRaises(HTTPException):
            reset_s1.execute(self.store, "admin")
        with self.assertRaises(HTTPException) as denied:
            reset_s1.execute(self.store, "operator")
        self.assertEqual(denied.exception.status_code, 403)
        self.store.path(self.video[0]).write_bytes(b"tampered")
        with self.assertRaises(HTTPException):
            reset_s1.execute(self.store, "admin")
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM changes WHERE action='s1.reset.commit'").fetchone()[0], 0)

    def test_unsafe_input_reference_is_never_followed(self):
        outside = Path(self.temp.name) / "outside.mp4"
        outside.write_bytes(b"outside")
        self.manifest.sessions[0].videos[0].storage_ref = "../outside.mp4"
        ref, digest = self.store.write_manifest(self.manifest)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE cases SET manifest_ref=?,manifest_hash=?", (ref, digest))
        with self.assertRaises(HTTPException):
            reset_s1.execute(self.store, "admin")
        self.assertEqual(outside.read_bytes(), b"outside")

    def test_video_change_after_persisted_plan_is_checked_before_commit(self):
        with patch("app.reset_s1._commit", side_effect=OSError("synthetic interruption")), self.assertRaises(OSError):
            reset_s1.execute(self.store, "admin")
        self.store.path(self.video[0]).write_bytes(b"changed after planning")
        with self.assertRaises(HTTPException):
            reset_s1.execute(self.store, "admin")
        with self.store.connect() as db:
            self.assertEqual(self.store.case(db, "case")["manifest_schema_version"], "intake-3.0")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)

    def test_old_worker_cannot_publish_after_reset(self):
        reset_s1.execute(self.store, "admin")
        with self.assertRaises(HTTPException):
            analysis.guard(self.store, "old-run", "old-token")
        with self.assertRaises(HTTPException):
            analysis.write_output(self.store, self.old_run, self.old_step, {"score": 99})
        self.assertFalse(self.store.path("runs/old-run/old-step/output.json").exists())

    def test_cli_worker_refuses_old_queue_before_claim_and_starts_after_reset(self):
        with self.store.connect(write=True) as db:
            db.execute("UPDATE runs SET status='queued',claim_token=NULL,lease_expires_at=NULL")
        command = [sys.executable, "-X", "utf8", "-m", "app.manage", "--data-dir", str(self.root), "worker", "--once"]
        before = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True,
                                text=True, encoding="utf-8", timeout=30)
        self.assertNotEqual(before.returncode, 0)
        self.assertIn("reset-s1", before.stderr)
        with self.store.connect() as db:
            row = db.execute("SELECT status,claim_token FROM runs WHERE run_id='old-run'").fetchone()
            self.assertEqual(row["status"], "queued")
            self.assertIsNone(row["claim_token"])
        reset_s1.execute(self.store, "admin")
        after = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], capture_output=True,
                               text=True, encoding="utf-8", timeout=30)
        self.assertEqual(after.returncode, 0, after.stderr)

    def test_damaged_s1_sheet_blocks_reset_without_deleting_new_generation(self):
        upgraded = reset_s1.upgrade_to_s1(self.manifest)
        ref, digest = self.store.write_manifest(upgraded)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE cases SET manifest_schema_version='intake-4.0',input_revision=2,manifest_ref=?,manifest_hash=?", (ref, digest))
        self.store.path("sheets/case/old.json").write_bytes(b"damaged S1 sheet")
        with self.assertRaises(HTTPException):
            reset_s1.execute(self.store, "admin")
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM score_sheets").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)

    def test_exports_use_snapshot_generation_and_preserve_s1_binary_output(self):
        old_snapshot = self.file("exports/old/snapshot.json", encode({"members": [{"case_id": "case", "run_id": "old-run"}]}).encode())
        new_snapshot = self.file("exports/new/snapshot.json", b'{"schema_version":"4.0","members":[]}')
        old_file = self.file("exports/old/result.xlsx", b"synthetic old binary")
        new_file = self.file("exports/new/result.xlsx", b"synthetic S1 binary")
        with self.store.connect(write=True) as db:
            for target, snapshot, output in (("old-export", old_snapshot, old_file), ("new-export", new_snapshot, new_file)):
                self.store.audit(db, "admin", target, "export.snapshot", {"ref": snapshot[0], "hash": snapshot[1]})
                self.store.audit(db, "admin", target, "export.file", {"ref": output[0], "hash": output[1]})
        reset_s1.execute(self.store, "admin")
        self.assertFalse(self.store.path(old_file[0]).exists())
        self.assertFalse(self.store.path(old_snapshot[0]).exists())
        self.assertTrue(self.store.path(new_file[0]).exists())
        self.assertTrue(self.store.path(new_snapshot[0]).exists())

    def test_reserved_failed_call_without_settlement_stays_uncertain(self):
        with self.store.connect(write=True) as db:
            db.execute("UPDATE steps SET status='failed',usage_json='{}'")
        reset_s1.execute(self.store, "admin")
        with self.store.connect() as db:
            usage = json.loads(db.execute("SELECT detail_json FROM changes WHERE action='s1.reset.usage'").fetchone()[0])
        self.assertTrue(usage["billing_uncertain"])
        self.assertTrue(usage["call_reserved"])
        self.assertIsNone(usage["meter_cost_estimate"])

    def test_pre_reset_backup_rejected_and_s1_backup_restores(self):
        old_backup = Path(self.temp.name) / "before"
        maintenance.backup(self.store, old_backup, "admin")
        reset_s1.execute(self.store, "admin")
        with self.assertRaises(HTTPException):
            maintenance.restore(self.store, old_backup, Path(self.temp.name) / "forbidden")
        fresh = Path(self.temp.name) / "after"
        maintenance.backup(self.store, fresh, "admin")
        target = Path(self.temp.name) / "restored"
        maintenance.restore(self.store, fresh, target)
        recovered = Store(target)
        with recovered.connect() as db:
            self.assertEqual(recovered.manifest(recovered.case(db, "case")).schema_version, "intake-4.0")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 0)
        self.assertIn(("absent-case", "ABSENT", "deleted"), maintenance.deletion_records(recovered))

    def test_failed_remote_deletion_and_upload_response_loss_survive_reset_and_retry(self):
        with self.store.connect(write=True) as db:
            self.store.audit(db, "admin", "old-run", "remote.upload_started", {"upload_id": "lost", "credential_reference": "credential"})
            self.store.audit(db, "admin", "old-run", "v3.remote_cleanup_failed", {"remote_file_names": ["files/failed"], "credential_reference": "credential"})
        reset_s1.execute(self.store, "admin")
        self.assertEqual(len(reset_s1.pending_remote_cleanup(self.store)), 2)
        with self.assertRaises(HTTPException):
            reset_s1.retry_remote_cleanup(self.store, "operator", delete=lambda *args: None)
        failing = lambda *args: (_ for _ in ()).throw(ProviderError("delete_failed"))
        self.assertEqual(len(reset_s1.retry_remote_cleanup(self.store, "admin", delete=failing)["pending"]), 2)
        deleted = []
        pending = reset_s1.retry_remote_cleanup(self.store, "admin", delete=lambda *args: deleted.append(args))["pending"]
        self.assertEqual(deleted, [("files/failed", "credential")])
        self.assertEqual([item["status"] for item in pending], ["upload_response_unconfirmed"])

    def test_provider_upload_name_is_durable_before_inference_and_delete_failure(self):
        config = {"model": "synthetic", "prompt": "synthetic", "processing_mode": "static", "fps": 1,
                  "media_resolution": "low", "max_output_tokens": 256}
        clip = SimpleNamespace(size_bytes=1, name="synthetic")
        def transport(method, url, key, **kwargs):
            if url.endswith("/upload/v1beta/files"):
                self.assertEqual(reset_s1.pending_remote_cleanup(self.store)[0]["status"], "upload_response_unconfirmed")
                return {}, {"X-Goog-Upload-URL": "https://generativelanguage.googleapis.com/upload/synthetic"}
            if url.endswith("/upload/synthetic"):
                return {"file": {"name": "files/synthetic", "state": "ACTIVE", "uri": "synthetic"}}, {}
            self.assertEqual(reset_s1.pending_remote_cleanup(self.store)[0]["remote_file_name"], "files/synthetic")
            raise ProviderError("synthetic_failure", uncertain=True)
        with patch("app.secrets.credential", return_value=("synthetic-key", "credential")), patch("app.gemini.request", side_effect=transport):
            with self.assertRaises(ProviderError):
                GeminiObserver(self.store).request_v3([(self.store.path(self.video[0]), clip)], config,
                    {"run_id": "old-run", "audit_actor": "admin"}, {}, lambda: None)
        self.assertEqual(len(reset_s1.pending_remote_cleanup(self.store)), 1)
        reset_s1.execute(self.store, "admin")
        self.assertEqual(reset_s1.pending_remote_cleanup(self.store)[0]["remote_file_name"], "files/synthetic")

    def test_remote_delete_response_loss_can_be_closed_by_confirmed_absence(self):
        with self.store.connect(write=True) as db:
            self.store.audit(db, "admin", "old-run", "v3.remote_cleanup_failed", {
                "remote_file_names": ["files/already-deleted"], "credential_reference": "credential"})
        def absent(*args):
            raise ProviderError("provider_http_404")
        self.assertEqual(reset_s1.retry_remote_cleanup(self.store, "admin", delete=absent), {"pending": []})
