import json
import shutil
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import media, preprocess_executions_v4 as queries, preprocess_v4 as preprocess
from app.domain.preprocess_v4 import PreprocessRequestV4
from app.maintenance import runtime_lock
from app.intake import new_session
from tests import test_preprocess_v4 as helpers
from tests.support import AppCase


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Synthetic FFmpeg media required")
class PreprocessExecutionV4Tests(unittest.TestCase):
    setUpClass = classmethod(helpers.PreprocessV4Tests.setUpClass.__func__)
    tearDownClass = classmethod(helpers.PreprocessV4Tests.tearDownClass.__func__)
    setUp = helpers.PreprocessV4Tests.setUp
    current = helpers.PreprocessV4Tests.current
    upload = helpers.PreprocessV4Tests.upload
    recording = helpers.PreprocessV4Tests.recording
    run_batch = helpers.PreprocessV4Tests.run_batch

    def prepare(self):
        video = self.upload()
        self.recording(video.video_id)

    def details(self, batch_id, actor="review"):
        return queries.execution(self.store, self.case_id, self.session_id, batch_id, actor)

    def test_other_actor_failure_does_not_replace_completion_and_queries_are_read_only(self):
        self.prepare()
        batch = self.run_batch()
        with self.store.connect() as db:
            before = [tuple(row) for row in db.execute("SELECT * FROM changes")]
        item = queries.executions(self.store, "op").items[0]
        self.assertEqual(item.status, "complete")
        self.assertEqual(item.current_stage, "verify_save")
        self.assertIsNotNone(item.finished_at)
        self.assertEqual(self.details(batch.batch_id).result, batch)
        self.assertEqual(queries.executions(self.store, "review").items, [])
        with self.store.connect() as db:
            self.assertEqual(before, [tuple(row) for row in db.execute("SELECT * FROM changes")])
        with patch.object(preprocess, "_prepare_clips", side_effect=HTTPException(422, "합성 실패")):
            with self.assertRaises(HTTPException):
                preprocess.execute(self.store, self.case_id, self.session_id, "review",
                    PreprocessRequestV4(request_id="other-fail", expected_revision=self.current()["input_revision"]))
        self.assertEqual(queries.executions(self.store, "review").items[0].status, "failed")
        self.assertEqual(queries.executions(self.store, "op").items[0].result_pointer, item.result_pointer)
        self.assertEqual(self.details(batch.batch_id, "dev").status, "complete")

    def test_progress_stages_guard_idempotency_and_reuse(self):
        self.prepare()
        observed = []
        original = preprocess._prepare_clips

        def inspect(*args):
            item = queries.executions(self.store, "op").items[0]
            observed.append((item.status, item.current_stage))
            return original(*args)

        with patch.object(preprocess, "_prepare_clips", side_effect=inspect):
            first = self.run_batch()
        self.assertEqual(observed, [("running", "clips")])
        self.assertEqual(self.run_batch().batch_id, first.batch_id)
        pointer = queries.executions(self.store, "op").items[0].result_pointer
        reused = self.run_batch("reuse", reuse=pointer)
        self.assertNotEqual(first.batch_id, reused.batch_id)
        with self.store.connect() as db:
            stages = [json.loads(row[0])["stage"] for row in db.execute(
                "SELECT detail_json FROM changes WHERE action='preprocess_v4.progress' ORDER BY rowid")]
        self.assertEqual(stages, ["clips", "windows", "verify_save", "reuse_verify", "verify_save"])
        self.assertEqual(len(queries.executions(self.store, "op").items), 2)
        self.assertEqual(queries.executions(self.store, "op", request_id="reuse").items[0].execution_id, reused.batch_id)
        with self.assertRaises(HTTPException) as error:
            preprocess.execute(self.store, self.case_id, self.session_id, "review",
                PreprocessRequestV4(request_id="reuse", expected_revision=self.current()["input_revision"], reuse=pointer))
        self.assertEqual(error.exception.status_code, 409)

    def test_success_outdated_overlap_and_damaged_pointer(self):
        self.prepare()
        batch = self.run_batch()
        with self.store.connect(write=True) as db:
            row = self.store.case(db, self.case_id)
            manifest = self.store.manifest(row)
            self.store.save(db, row, manifest, "op", "synthetic.revision")
        item = self.details(batch.batch_id)
        self.assertEqual(item.status, "complete")
        self.assertTrue(item.outdated)
        self.assertEqual(len(queries.executions(self.store, "op", status="complete").items), 1)
        self.assertEqual(len(queries.executions(self.store, "op", status="attention").items), 1)
        self.store.path(item.result_pointer.ref).write_bytes(b"broken")
        damaged = self.details(batch.batch_id)
        self.assertEqual(damaged.status, "failed")
        self.assertIsNone(damaged.result_pointer)
        self.assertEqual(queries.executions(self.store, "op", status="complete").items, [])

    def test_previous_session_retains_immutable_result_and_missing_artifact_is_failed(self):
        self.prepare()
        batch = self.run_batch()
        pointer = self.details(batch.batch_id).result_pointer
        original = self.store.path(pointer.ref).read_bytes()
        with self.store.connect(write=True) as db:
            row = self.store.case(db, self.case_id)
            manifest = self.store.manifest(row)
            session = new_session(note="합성 다음 회차")
            manifest.sessions.append(session)
            manifest.selected_session_id = session.session_id
            self.store.save(db, row, manifest, "review", "session.add")
        preserved = self.details(batch.batch_id)
        self.assertEqual(preserved.status, "complete")
        self.assertTrue(preserved.outdated)
        self.assertEqual(self.store.path(pointer.ref).read_bytes(), original)
        self.store.path(batch.clips[0].ai.ref).unlink()
        self.assertEqual(self.details(batch.batch_id).status, "failed")

    def test_partial_completion_and_legacy_no_progress(self):
        self.prepare()
        with patch.object(preprocess, "_ai_clip", side_effect=media.MediaError("합성 AI 클립 실패")):
            batch = self.run_batch()
        self.assertEqual(self.details(batch.batch_id).status, "partial")
        self.assertEqual(queries.executions(self.store, "op", status="attention").items[0].status, "partial")
        with self.store.connect(write=True) as db:
            db.execute("DELETE FROM changes WHERE action='preprocess_v4.progress'")
        preserved = self.details(batch.batch_id)
        self.assertEqual(preserved.status, batch.status)
        self.assertIsNone(preserved.current_stage)
        self.assertIsNotNone(preserved.finished_at)

    def test_lock_rejection_has_no_start_and_disabled_actor_cannot_read(self):
        self.prepare()
        with runtime_lock(self.store, "preprocess"):
            with self.assertRaises(HTTPException) as error:
                self.run_batch("locked")
            self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(queries.executions(self.store, "op", request_id="locked").items, [])
        with self.store.connect(write=True) as db:
            db.execute("UPDATE users SET active=0 WHERE username='op'")
        with self.assertRaises(HTTPException) as error:
            queries.executions(self.store, "op")
        self.assertEqual(error.exception.status_code, 403)

    def test_original_tamper_is_not_a_valid_completed_result(self):
        self.prepare()
        batch = self.run_batch()
        self.store.path(batch.source_files[0].ref).write_bytes(b"broken original")
        item = self.details(batch.batch_id)
        self.assertEqual(item.status, "failed")
        self.assertIsNone(item.result_pointer)
        self.assertEqual(queries.executions(self.store, "op", status="complete").items, [])

    def test_new_claim_between_query_and_lock_check_does_not_revive_old_run(self):
        from contextlib import contextmanager

        self.start("old")

        @contextmanager
        def occupied(*args):
            self.start("new", "review")
            raise HTTPException(409, "새 실행 점유")
            yield

        with patch.object(queries, "runtime_lock", occupied):
            self.assertEqual(self.details("old").status, "interrupted")

    def start(self, identifier, actor="op", session_id=None):
        value = dict(batch_id=identifier, claim_token="claim-" + identifier, request_id="request-" + identifier,
                     request_hash="a" * 64, session_id=session_id or self.session_id,
                     input_revision=self.current()["input_revision"])
        with self.store.connect(write=True) as db:
            self.store.audit(db, actor, self.case_id, "preprocess_v4.started", value)
        return value

    def test_interruption_global_claim_and_late_terminal_identity(self):
        old = self.start("old")
        self.assertEqual(self.details("old").status, "interrupted")
        with runtime_lock(self.store, "preprocess"):
            self.assertEqual(self.details("old").status, "running")
            new = self.start("new", "review")
            self.assertEqual(self.details("old").status, "interrupted")
            self.assertEqual(self.details("new").status, "running")
            with self.store.connect(write=True) as db:
                self.store.audit(db, "op", self.case_id, "preprocess_v4.superseded", {**old, "message": "이전 점유 대체"})
                self.store.audit(db, "op", self.case_id, "preprocess_v4.failed", {**new, "message": "잘못된 actor"})
                self.store.audit(db, "review", self.case_id, "preprocess_v4.failed", {**new, "claim_token": "wrong", "message": "잘못된 claim"})
            self.assertEqual(self.details("old").status, "failed")
            self.assertEqual(self.details("new").status, "running")
        self.assertEqual(self.details("new").status, "interrupted")
        self.assertIsNone(self.details("new").current_stage)

    def test_pagination_filters_request_recovery_and_ledger_preservation(self):
        for index in range(55):
            self.start("batch-" + str(index))
        self.start("other", "review")
        page = queries.executions(self.store, "op")
        self.assertEqual(len(page.items), 50)
        self.assertEqual(page.items[0].execution_id, "batch-54")
        self.start("new-arrival")
        second = queries.executions(self.store, "op", cursor=page.next_cursor)
        self.assertEqual([item.execution_id for item in second.items], ["batch-4", "batch-3", "batch-2", "batch-1", "batch-0"])
        self.assertIsNone(second.next_cursor)
        self.assertEqual(queries.executions(self.store, "op", request_id="request-batch-0").items[0].execution_id, "batch-0")
        self.assertEqual(queries.executions(self.store, "op", search="합성견").items[0].execution_id, "new-arrival")
        self.assertEqual(queries.executions(self.store, "op", event_id="other").items, [])
        self.assertEqual(queries.executions(self.store, "op", status="running").items, [])


class PreprocessExecutionApiV4Tests(AppCase):
    def test_actor_scope_shared_detail_and_parameter_validation(self):
        self.client = self.client_for("operator")
        item = self.make_case()
        with self.store.connect(write=True) as db:
            self.store.audit(db, "operator", item["case_id"], "preprocess_v4.started", dict(batch_id="synthetic",
                claim_token="claim", request_id="request", request_hash="a" * 64,
                session_id=item["selected_session_id"], input_revision=item["input_revision"]))
        path = "/api/preprocess-s1/executions"
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, response.text)
        row = response.json()["items"][0]
        self.assertNotIn("claim_token", row)
        self.assertNotIn("result", row)
        self.assertEqual(self.client.get(path, params={"case_id": item["case_id"]}).json()["items"], [row])
        self.assertEqual(self.client.get(path, params={"case_id": "unrelated-case"}).json()["items"], [])
        self.assertEqual(self.client_for("reviewer").get(path + "?username=operator").json()["items"], [])
        detail = f"/api/cases/{item['case_id']}/sessions/{item['selected_session_id']}/preprocess-s1/executions/synthetic"
        self.assertEqual(self.client_for("reviewer").get(detail).json()["requested_by"], "operator")
        self.assertEqual(self.client.get(detail + "-missing").status_code, 404)
        self.assertEqual(self.client.get(path + "?cursor=0").status_code, 422)
        self.assertEqual(self.client.get(path + "?status=queued").status_code, 422)
