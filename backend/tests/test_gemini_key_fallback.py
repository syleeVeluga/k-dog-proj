"""GK-T07–T16: real Worker/REST assembly with synthetic keys and transports."""

import hashlib
import io
import json
import os
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from app import gemini, gemini_keys, run_v4, secrets, usage, reset_s1
from app.gemini_v4 import GeminiScorerV4
from app.storage import encode, uid
from app.worker import Worker
from tests import test_run_v4 as run_fixture
from tests import test_attachment_ai_v4 as attachment_fixture
from tests import test_report_narrative_v4 as narrative_fixture


PRIMARY = "synthetic-primary-project-A"
BACKUP = "synthetic-backup-project-B"


class SyntheticGemini:
    def __init__(self, responder=None):
        self.calls = []
        self.responder = responder
        self.fail_primary = True
        self.fail_backup = False
        self.cleanup_failure = False
        self.hook = None

    def __call__(self, method, url, key, **options):
        self.calls.append((method, url, key, options))
        project = "A" if key == PRIMARY else "B"
        if method == "DELETE":
            if self.cleanup_failure and key == PRIMARY:
                raise gemini.ProviderError("provider_connection_lost", retryable=True, uncertain=True)
            return {}, {}
        if url.endswith("/upload/v1beta/files"):
            return {}, {"X-Goog-Upload-URL": gemini.BASE + "/upload-" + project}
        if "/upload-" in url:
            data = options["data"].read()
            options["synthetic_hash"] = hashlib.sha256(data).hexdigest()
            name = "files/project-" + project + "-" + uid()
            return {"file": {"name": name, "uri": gemini.BASE + "/v1beta/" + name, "state": "ACTIVE"}}, {}
        context = json.loads(options["data"]["input"][-1]["text"])
        if self.hook:
            self.hook(key, context)
        if (key == PRIMARY and self.fail_primary) or (key != PRIMARY and self.fail_backup):
            raise gemini.ProviderError("provider_http_503", http_status=503, retryable=True, uncertain=True, delay=17)
        response = self.responder(context) if self.responder else {**context["identity"], "observations": [
            {"code": item["code"], "value": None, "status": "unobserved", "reason": "synthetic absent observation"} for item in context["items"]]}
        return {"status": "completed", "usage": {"total_tokens": 9}, "steps": [
            {"type": "model_output", "content": [{"type": "text", "text": json.dumps(response)}]}]}, {}


class GeminiFallbackTests(unittest.TestCase):
    def setUp(self):
        self.fixture = run_fixture.RunV4Tests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store
        environment = patch.dict(os.environ, {"GEMINI_API_KEY": ""})
        environment.start()
        self.addCleanup(environment.stop)
        self.primary = secrets.change(self.store, "gemini", PRIMARY, "developer")
        self.backup = secrets.change(self.store, "gemini", BACKUP, "developer", slot="backup")
        self.transport = SyntheticGemini()

    def worker(self):
        return Worker(self.store, observer=GeminiScorerV4(self.store, self.transport))

    def enqueue(self, **changes):
        configuration = self.fixture.config.model_copy(update=changes)
        return self.fixture.enqueue(config=configuration)

    def steps(self, run):
        with self.store.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM steps WHERE run_id=? ORDER BY attempt", (run["run_id"],))]

    def finish(self, run):
        self.fixture.due(run["run_id"])
        self.worker().once()
        return run_v4.view(self.store, run["run_id"], self.fixture.user)

    def test_primary_failure_backup_new_attempt_project_upload_and_uncertainty_preserved(self):
        self.transport.cleanup_failure = True
        run = self.enqueue()
        self.worker().once()
        first = self.steps(run)[0]
        self.assertEqual(first["status"], "retry_wait")
        self.assertEqual(json.loads(first["usage_json"])["fallback_status"], "backup_retry_wait")
        view = self.finish(run)
        self.assertEqual((view["status"], view["reserved_calls"], view["credential_slot"]), ("succeeded", 2, "backup"))
        self.assertTrue(view["steps"][0]["billing_uncertain"])
        self.assertTrue(view["steps"][0]["remote_cleanup_pending"])
        self.assertEqual([s["credential_slot"] for s in view["steps"]], ["primary", "backup"])
        self.assertNotIn("credential_reference", encode(view))
        hashes = [options["synthetic_hash"] for _, _, _, options in self.transport.calls if "synthetic_hash" in options]
        self.assertEqual(hashes[:len(hashes)//2], hashes[len(hashes)//2:])
        for method, url, key, options in self.transport.calls:
            if method == "DELETE":
                self.assertIn("project-A" if key == PRIMARY else "project-B", url)
            if url.endswith("/interactions"):
                for value in options["data"]["input"]:
                    if value["type"] == "video":
                        self.assertIn("project-A" if key == PRIMARY else "project-B", value["uri"])
        summary = usage.summarize(self.store)
        self.assertEqual(summary["calls_reserved"], 2)
        self.assertEqual(len(summary["runs"][0]["attempts"]), 2)
        self.assertTrue(summary["runs"][0]["attempts"][0]["billing_uncertain"])
        self.assertEqual(len(reset_s1.pending_remote_cleanup(self.store)), 1)

    def test_locally_removed_primary_uses_backup_first_without_primary_request(self):
        secrets.change(self.store, "gemini", None, "developer", expected_reference=self.primary["reference"], check_reference=True)
        run = self.enqueue()
        self.worker().once()
        view = run_v4.view(self.store, run["run_id"], self.fixture.user)
        self.assertEqual((view["status"], view["reserved_calls"], view["credential_slot"]), ("succeeded", 1, "backup"))
        self.assertEqual(view["fallback_reason"], "primary_removed")
        self.assertTrue(all(key == BACKUP for _, _, key, _ in self.transport.calls))

    def test_attempt_and_call_limits_do_not_hide_backup_inference(self):
        for changes, status in (({"max_attempts": 1}, "attempt_limit"), ({"max_ai_calls": 1}, "call_limit")):
            with self.subTest(changes=changes):
                self.fixture.request = self.fixture.request.model_copy(update={"request_id": uid()})
                run = self.enqueue(**changes)
                self.worker().once()
                view = run_v4.view(self.store, run["run_id"], self.fixture.user)
                self.assertEqual((view["reserved_calls"], view["steps"][0]["fallback_status"]), (1, status))
        self.assertFalse(any(key == BACKUP for _, _, key, _ in self.transport.calls))

    def test_backup_failure_never_returns_primary_and_new_run_starts_primary(self):
        run = self.enqueue()
        self.worker().once()
        self.transport.fail_backup = True
        self.finish(run)
        self.finish(run)
        view = run_v4.view(self.store, run["run_id"], self.fixture.user)
        self.assertEqual([s["credential_slot"] for s in view["steps"]], ["primary", "backup", "backup"])
        self.assertEqual(view["reserved_calls"], 3)
        self.fixture.request = self.fixture.request.model_copy(update={"request_id": uid()})
        next_run = self.enqueue(max_attempts=1)
        self.worker().once()
        self.assertEqual(run_v4.view(self.store, next_run["run_id"], self.fixture.user)["credential_slot"], "primary")

    def test_selected_slot_rotation_applies_next_attempt_and_stop_blocks_request(self):
        run = self.enqueue()
        self.worker().once()
        new = BACKUP + "-rotated"
        secrets.change(self.store, "gemini", new, "developer", slot="backup")
        view = self.finish(run)
        self.assertEqual(view["status"], "succeeded")
        with self.store.connect() as db:
            latest = gemini_keys.selection(db, run["run_id"])
        self.assertEqual(latest["credential_reference"], secrets.state(self.store, "gemini", "backup")["reference"])
        self.assertTrue(any(key == new for _, _, key, _ in self.transport.calls))
        self.fixture.request = self.fixture.request.model_copy(update={"request_id": uid()})
        stopped = self.enqueue()
        self.worker().once()
        count = len(self.transport.calls)
        self.fixture.action(stopped["run_id"])
        self.finish(stopped)
        self.assertEqual(len(self.transport.calls), count)

    def test_backup_actor_revocation_prevents_adoption_and_preserves_selection(self):
        run = self.enqueue()
        self.worker().once()
        def revoke(key, context):
            if key == BACKUP:
                with self.store.connect(write=True) as db:
                    db.execute("UPDATE users SET active=0 WHERE username='operator'")
        self.transport.hook = revoke
        self.fixture.due(run["run_id"])
        self.worker().once()
        with self.store.connect() as db:
            row = db.execute("SELECT result_ref FROM runs WHERE run_id=?", (run["run_id"],)).fetchone()
            self.assertIsNone(row[0])
            self.assertEqual(gemini_keys.selection(db, run["run_id"])["credential_slot"], "backup")

    def test_cleanup_retry_uses_exact_backup_reference_and_retired_key_stays_pending(self):
        run = self.enqueue()
        self.transport.fail_primary = False
        self.transport.cleanup_failure = True
        self.worker().once()
        self.assertTrue(reset_s1.pending_remote_cleanup(self.store))
        secrets.change(self.store, "gemini", "synthetic-replacement", "developer")
        with patch("app.gemini.request") as request:
            reset_s1.retry_remote_cleanup(self.store, "operator")
            request.assert_not_called()
        self.assertTrue(reset_s1.pending_remote_cleanup(self.store))
        with self.store.connect(write=True) as db:
            self.store.audit(db, "operator", run["run_id"], "remote.uploaded", {"upload_id": "backup-cleanup", "remote_file_name": "files/backup-pending", "credential_reference": self.backup["reference"]})
        with patch("app.gemini.request", return_value=({}, {})) as request:
            reset_s1.retry_remote_cleanup(self.store, "operator")
            self.assertEqual(request.call_count, 1)
            self.assertEqual(request.call_args.args[2], BACKUP)
        self.assertEqual(len(reset_s1.pending_remote_cleanup(self.store)), 1)

    def test_pending_fallback_rechecks_input_hash_and_actor_without_backup_request(self):
        raw_path = self.store.path("videos/v1.mp4")
        raw = raw_path.read_bytes()
        revision = self.fixture.current()["input_revision"]
        for mode in ("input", "actor", "hash"):
            self.fixture.request = self.fixture.request.model_copy(update={"request_id": uid()})
            run = self.enqueue()
            self.worker().once()
            count = len(self.transport.calls)
            with self.store.connect(write=True) as db:
                if mode == "input":
                    db.execute("UPDATE cases SET input_revision=input_revision+1 WHERE case_id=?", (self.fixture.case_id,))
                if mode == "actor":
                    db.execute("UPDATE users SET active=0 WHERE username='operator'")
            if mode == "hash":
                raw_path.write_bytes(b"synthetic changed source")
            self.fixture.due(run["run_id"])
            self.worker().once()
            self.assertEqual(len(self.transport.calls), count, mode)
            self.assertIsNone(self.fixture.row(run["run_id"])["result_ref"])
            with self.store.connect(write=True) as db:
                db.execute("UPDATE cases SET input_revision=? WHERE case_id=?", (revision, self.fixture.case_id))
                db.execute("UPDATE users SET active=1 WHERE username='operator'")
            raw_path.write_bytes(raw)

    def test_late_backup_lease_and_token_changes_block_output(self):
        for mode in ("lease", "token"):
            self.fixture.request = self.fixture.request.model_copy(update={"request_id": uid()})
            run = self.enqueue()
            self.transport.hook = None
            self.worker().once()
            def change(key, context):
                if key == BACKUP:
                    with self.store.connect(write=True) as db:
                        if mode == "lease":
                            db.execute("UPDATE runs SET lease_expires_at='2000-01-01T00:00:00Z' WHERE run_id=?", (run["run_id"],))
                        else:
                            db.execute("UPDATE runs SET claim_token='synthetic-other-token' WHERE run_id=?", (run["run_id"],))
            self.transport.hook = change
            self.fixture.due(run["run_id"])
            self.worker().once()
            self.assertIsNone(self.fixture.row(run["run_id"])["result_ref"])

    def test_two_attempt_limit_is_shared_with_backup_failure(self):
        run = self.enqueue(max_attempts=2)
        self.worker().once()
        self.transport.fail_backup = True
        view = self.finish(run)
        self.assertEqual(view["reserved_calls"], 2)
        self.assertEqual([step["credential_slot"] for step in view["steps"]], ["primary", "backup"])
        count = len(self.transport.calls)
        self.fixture.due(run["run_id"])
        self.worker().once()
        self.assertEqual(len(self.transport.calls), count)

    def test_local_file_and_decrypt_failures_use_only_backup_and_missing_both_stops(self):
        protect = secrets.protect
        for mode, reason in (("file", "primary_file_unavailable"), ("decrypt", "primary_decrypt_failed")):
            self.fixture.request = self.fixture.request.model_copy(update={"request_id": uid()})
            registered = secrets.change(self.store, "gemini", PRIMARY, "developer")
            path = self.store.path(f"secrets/{registered['reference']}.bin")
            ciphertext = path.read_bytes()
            if mode == "file":
                path.unlink()
            def decrypt(data, **kwargs):
                if data == ciphertext:
                    from fastapi import HTTPException
                    raise HTTPException(409, "synthetic DPAPI failure")
                return protect(data, **kwargs)
            run = self.enqueue()
            before = len(self.transport.calls)
            if mode == "decrypt":
                with patch("app.secrets.protect", side_effect=decrypt):
                    self.worker().once()
            else:
                self.worker().once()
            view = run_v4.view(self.store, run["run_id"], self.fixture.user)
            self.assertEqual(view["fallback_reason"], reason)
            self.assertTrue(all(key == BACKUP for _, _, key, _ in self.transport.calls[before:]))
        secrets.change(self.store, "gemini", None, "developer")
        self.fixture.request = self.fixture.request.model_copy(update={"request_id": uid()})
        run = self.enqueue()
        count = len(self.transport.calls)
        self.worker().once()
        view = run_v4.view(self.store, run["run_id"], self.fixture.user)
        self.assertFalse(view["result_available"])
        self.assertEqual(view["steps"][0]["fallback_status"], "backup_unavailable")
        self.assertEqual(len(self.transport.calls), count)


class GeminiErrorPolicyTests(unittest.TestCase):
    def test_error_status_code_and_phase_table(self):
        for status in (401, 402, 403, 429, 500, 502, 503, 504):
            for phase in ("upload", "processing", "inference"):
                error = gemini.ProviderError("synthetic", http_status=status, usage={"credential_slot": "primary", "operation_phase": phase})
                self.assertIsNotNone(gemini_keys.fallback_reason(error), (status, phase))
        for status in (400, 404, 409, 416, 501):
            error = gemini.ProviderError("synthetic", http_status=status, usage={"credential_slot": "primary", "operation_phase": "inference"})
            self.assertIsNone(gemini_keys.fallback_reason(error), status)
        for slot, phase in (("backup", "inference"), ("primary", "cleanup"), ("primary", "credential")):
            error = gemini.ProviderError("synthetic", http_status=503, usage={"credential_slot": slot, "operation_phase": phase})
            self.assertIsNone(gemini_keys.fallback_reason(error))
        error = gemini.ProviderError("provider_http_400", http_status=400, provider_code="API_KEY_INVALID", usage={"credential_slot": "primary", "operation_phase": "upload"})
        self.assertEqual(gemini_keys.fallback_reason(error), "primary_api_key_invalid")

    def test_real_http_error_retains_only_whitelisted_machine_fields_and_retry_after(self):
        for body, expected in (({"error": {"code": "authentication", "message": PRIMARY}}, "authentication"),
            ({"error": {"code": 400, "message": "API_KEY_INVALID " + PRIMARY, "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID", "domain": "googleapis.com"}]}}, "API_KEY_INVALID"),
            ({"error": {"message": "API_KEY_INVALID " + PRIMARY}}, None)):
            error = HTTPError(gemini.BASE, 400, "synthetic", {"Retry-After": "31"}, io.BytesIO(json.dumps(body).encode()))
            opener = unittest.mock.Mock()
            opener.open.side_effect = error
            with patch("app.gemini.build_opener", return_value=opener), self.assertRaises(gemini.ProviderError) as caught:
                gemini.request("POST", gemini.BASE + "/v1beta/interactions", PRIMARY, data={})
            self.assertEqual(caught.exception.provider_code, expected)
            self.assertEqual(caught.exception.delay, 31)
            self.assertNotIn(PRIMARY, str(caught.exception) + encode(caught.exception.usage))
            self.assertNotIn("provider_error_message", caught.exception.usage)


class GeminiOtherPathsTests(unittest.TestCase):
    def keys(self, store):
        with store.connect(write=True) as db:
            db.execute("INSERT OR IGNORE INTO users(username,role,password_hash) VALUES('developer','developer','synthetic')")
        secrets.change(store, "gemini", PRIMARY, "developer")
        secrets.change(store, "gemini", BACKUP, "developer", slot="backup")

    def due(self, store, run_id):
        with store.connect(write=True) as db:
            db.execute("UPDATE steps SET retry_at='2000-01-01T00:00:00Z' WHERE run_id=? AND status='retry_wait'", (run_id,))

    def test_standalone_attachment_uses_real_worker_with_backup(self):
        fixture = attachment_fixture.AttachmentOpinionTests()
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.keys(fixture.store)
        transport = SyntheticGemini(attachment_fixture.selected)
        run = fixture.start()
        Worker(fixture.store, observer=GeminiScorerV4(fixture.store, transport)).once()
        self.due(fixture.store, run["run_id"])
        Worker(fixture.store, observer=GeminiScorerV4(fixture.store, transport)).once()
        view = attachment_fixture.runs.view(fixture.store, fixture.case_id, fixture.session_id, run["run_id"], fixture.user)
        self.assertEqual((view["status"], view["reserved_calls"], view["credential_slot"]), ("succeeded", 2, "backup"))

    def test_narrative_uses_real_worker_backup_and_immutable_reuse(self):
        fixture = narrative_fixture.NarrativeRunTests()
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.keys(fixture.store)
        transport = SyntheticGemini(narrative_fixture.generated)
        run = fixture.helper.enqueue()
        Worker(fixture.store, observer=GeminiScorerV4(fixture.store, transport)).once()
        self.due(fixture.store, run["run_id"])
        Worker(fixture.store, observer=GeminiScorerV4(fixture.store, transport)).once()
        view = narrative_fixture.runs.view(fixture.store, run["run_id"], fixture.helper.user)
        self.assertEqual((view["status"], view["credential_slot"]), ("succeeded", "backup"))
        self.assertEqual(sum(s["provider_calls"] for s in view["steps"]), 2)
        before = len(transport.calls)
        contents = []
        for format in ("html", "pdf", "manifest"):
            contents.append(narrative_fixture.runs.download(fixture.store, fixture.helper.case_id, fixture.helper.session_id,
                            run["run_id"], format, fixture.helper.user)[0])
        self.assertEqual(len(transport.calls), before)
        self.assertTrue(all(contents))
        request = fixture.helper.request.model_copy(update={"request_id": uid(), "reuse_run_id": run["run_id"]})
        reused = fixture.helper.enqueue(request)
        Worker(fixture.store, observer=GeminiScorerV4(fixture.store, transport)).once()
        reused_view = narrative_fixture.runs.view(fixture.store, reused["run_id"], fixture.helper.user)
        self.assertEqual((reused_view["status"], reused_view["credential_slot"]), ("succeeded", None))
        self.assertEqual(reused_view["steps"][0]["source_credential_slot"], "backup")
        self.assertEqual(len(transport.calls), before)
        for format, old in zip(("html", "pdf", "manifest"), contents):
            self.assertEqual(narrative_fixture.runs.download(fixture.store, fixture.helper.case_id, fixture.helper.session_id,
                            run["run_id"], format, fixture.helper.user)[0], old)

    def test_integrated_scoring_attachment_backoff_remaining_steps_and_new_run(self):
        fixture = run_fixture.RunV4Tests()
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.keys(fixture.store)
        def respond(context):
            if context.get("task") == "attachment_v4":
                return attachment_fixture.selected(context)
            observations = [{"code": item["code"], "value": None, "status": "unobserved", "reason": "synthetic missing"} for item in context["items"]]
            for item in observations:
                if item["code"] == "개18":
                    definition = next(value for value in context["items"] if value["code"] == "개18")
                    window = next(value["window"] for value in context["windows"] if value["window"]["window_id"] == definition["windows"][0])
                    item.update(value=1, status="observed", opportunity="present", validity="valid", evidence=[{
                        "clip_id": "c1", "window_id": window["window_id"], "start_seconds": window["start_seconds"],
                        "end_seconds": window["end_seconds"], "observed_seconds": window["end_seconds"] - window["start_seconds"], "note": "synthetic reunion"}])
            return {**context["identity"], "observations": observations}
        transport = SyntheticGemini(respond)
        pipeline = run_fixture.settings_v4.defaults(); pipeline.raw_observation_scope_confirmed = True
        run = fixture.enqueue(config=run_fixture.scoring_ai_v4.configuration(None, pipeline))
        Worker(fixture.store, observer=GeminiScorerV4(fixture.store, transport)).once()
        self.assertEqual(sum(url.endswith("/interactions") for _, url, _, _ in transport.calls), 1)
        self.due(fixture.store, run["run_id"])
        Worker(fixture.store, observer=GeminiScorerV4(fixture.store, transport)).once()
        view = run_v4.view(fixture.store, run["run_id"], fixture.user)
        self.assertEqual((view["status"], view["reserved_calls"], view["credential_slot"]), ("succeeded", 44, "backup"))
        attachment = [s for s in view["steps"] if s["stage"] == "attachment_v4"]
        self.assertEqual(attachment[0]["credential_slot"], "backup")
        self.assertTrue(all(key == BACKUP for _, url, key, _ in transport.calls if url.endswith("/interactions") and key != PRIMARY))
