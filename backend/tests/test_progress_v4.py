"""U06: 읽기 전용 단계 요약은 기존 기록에서만 계산하고, 교수/검토자에게는 다른 평가자 진행을 보이지 않는다."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from app import progress_v4
from app.storage import Store, encode


class ProgressV4Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="kdog-progress-")
        self.addCleanup(temporary.cleanup)
        self.store = Store(Path(temporary.name))
        progress_v4._usable_videos.cache_clear()
        with self.store.connect(write=True) as db:
            for name, role in (("operator", "operator"), ("reviewer", "reviewer"), ("reviewer2", "reviewer")):
                db.execute("INSERT INTO users(username,password_hash,role) VALUES (?,?,?)", (name, "unused", role))
            db.execute("INSERT INTO cases(case_id,event_id,participant_id,dog_name,reservation_at,input_revision,selected_session_id,manifest_ref,manifest_hash,created_at,updated_at) "
                       "VALUES ('C1','E','P','합성견','',3,'S1','inputs/none.json','h','now','now')")
        self.revision = 3

    def view(self, confirmed=False, videos=("v1", "v2")):
        recording = SimpleNamespace(confirmed=confirmed) if confirmed is not None else None
        session = SimpleNamespace(session_id="S1", recording_s1=recording, videos=[SimpleNamespace(video_id=name, media_status="pending_probe") for name in videos]
                                  + [SimpleNamespace(video_id="insv", media_status="storage_only")])
        return SimpleNamespace(case_id="C1", input_revision=self.revision, manifest=SimpleNamespace(selected_session_id="S1", sessions=[session]))

    def audit(self, action, detail, target="C1"):
        with self.store.connect(write=True) as db:
            self.store.audit(db, "operator", target, action, detail)

    def sheet(self, user, state, number):
        with self.store.connect(write=True) as db:
            db.execute("INSERT INTO score_sheets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (f"sheet-{number}", "C1", "S1", user, f"rater-{number}", user, "h" * 64, "independent", state, 1, 1, f"ref-{number}", "h" * 64))

    def build(self, user, **views):
        with self.store.connect() as db:
            return progress_v4.build(self.store, db, [self.view(**views)], SimpleNamespace(username=user, role="reviewer" if user.startswith("reviewer") else "operator"))["C1"]

    def batch(self, clips):
        ref = "clips/C1/S1/b1/t1/batch.json"
        path = self.store.root / ref
        path.parent.mkdir(parents=True)
        path.write_text(encode({"clips": clips}), encoding="utf-8")
        return ref

    def test_a_new_participant_starts_at_the_recording_stage(self):
        value = self.build("operator")
        self.assertEqual((value.stage, value.recording, value.preprocess, value.scoring, value.final, value.report), ("recording", False, "none", "none", False, False))
        self.assertEqual((value.videos_total, value.videos_usable), (2, 0))  # storage-only INSV is not a readable video

    def test_preprocess_states_and_usable_videos_come_from_real_clips(self):
        self.audit("preprocess_v4.started", {"session_id": "S1", "input_revision": 3})
        self.assertEqual(self.build("operator", confirmed=True).preprocess, "running")
        ref = self.batch([{"video_id": "v1", "status": "complete"}, {"video_id": "v2", "status": "failed"}])
        self.audit("preprocess_v4.completed", {"session_id": "S1", "input_revision": 3, "ref": ref, "hash": "x"})
        value = self.build("operator", confirmed=True)
        self.assertEqual((value.preprocess, value.stage, value.videos_usable), ("done", "scoring", 1))
        self.revision = 4
        value = self.build("operator", confirmed=True)  # input changed: still counted as processed but flagged
        self.assertEqual((value.preprocess, value.stage, value.videos_usable), ("outdated", "scoring", 1))
        self.audit("preprocess_v4.failed", {"session_id": "S1", "input_revision": 4, "message": "synthetic"})
        value = self.build("operator", confirmed=True)
        self.assertEqual((value.preprocess, value.stage, value.videos_usable), ("failed", "preprocess", 0))

    def test_other_sessions_and_missing_files_do_not_count(self):
        self.audit("preprocess_v4.completed", {"session_id": "OTHER", "input_revision": 3, "ref": "clips/none.json", "hash": "x"})
        self.assertEqual(self.build("operator", confirmed=True).preprocess, "none")
        self.audit("preprocess_v4.completed", {"session_id": "S1", "input_revision": 3, "ref": "clips/missing.json", "hash": "x"})
        value = self.build("operator", confirmed=True)
        self.assertEqual((value.preprocess, value.videos_usable), ("done", 0))

    def test_staff_see_sheet_counts_assignees_and_every_later_stage(self):
        ref = self.batch([{"video_id": "v1", "status": "partial"}])
        self.audit("preprocess_v4.completed", {"session_id": "S1", "input_revision": 3, "ref": ref, "hash": "x"})
        self.sheet("reviewer", "submitted", 1)
        self.sheet("reviewer2", "draft", 2)
        value = self.build("operator", confirmed=True)
        self.assertEqual((value.stage, value.scoring, value.sheets_total, value.sheets_submitted, value.assigned), ("scoring", "partial", 2, 1, ["reviewer", "reviewer2"]))
        with self.store.connect(write=True) as db:
            db.execute("UPDATE score_sheets SET state='submitted'")
        self.assertEqual(self.build("operator", confirmed=True).stage, "final")
        self.audit("final.s1.publish", {"session_id": "S1", "ref": "f", "hash": "x"})
        self.assertEqual(self.build("operator", confirmed=True).stage, "report")
        with self.store.connect(write=True) as db:
            db.execute("INSERT INTO runs(run_id,case_id,session_id,input_revision,input_snapshot_json,config_snapshot_json,status,created_at,updated_at,kind,result_ref) "
                       "VALUES ('R1','C1','S1',3,'{}','{}','succeeded','now','now','report_v4','report/ref')")
        value = self.build("operator", confirmed=True)
        self.assertEqual((value.stage, value.final, value.report), ("complete", True, True))

    def test_reviewers_never_see_other_raters_counts_names_or_final_progress(self):
        self.sheet("reviewer", "draft", 1)
        self.sheet("reviewer2", "submitted", 2)
        self.audit("final.s1.publish", {"session_id": "S1", "ref": "f", "hash": "x"})
        value = self.build("reviewer", confirmed=True)
        self.assertEqual((value.sheets_total, value.sheets_submitted, value.assigned, value.final), (None, None, [], None))
        self.assertEqual((value.my_sheet, value.scoring), ("draft", "partial"))
        other = self.build("reviewer2", confirmed=True)
        self.assertEqual((other.my_sheet, other.scoring), ("submitted", "done"))
        dumped = json.dumps(value.model_dump())
        self.assertNotIn("reviewer2", dumped)
        nothing = self.build("reviewer", confirmed=True)
        self.assertNotEqual(nothing.stage, "complete")

    def test_cases_endpoint_includes_progress_without_changing_stored_inputs(self):
        from app.api import create_app
        from app.auth import create_user
        from app.input_models import UserCreate
        from fastapi.testclient import TestClient
        fresh = tempfile.TemporaryDirectory(prefix="kdog-progress-api-")
        self.addCleanup(fresh.cleanup)
        app = create_app(Path(fresh.name))
        with app.state.store.connect(write=True) as db:
            create_user(db, UserCreate(username="staff", password="Synthetic-test-only-42", role="operator"))
        client = TestClient(app, base_url="http://127.0.0.1:8000", headers={"X-KDOG-Request": "1"})
        self.addCleanup(client.close)
        self.assertEqual(client.post("/api/auth/login", json={"username": "staff", "password": "Synthetic-test-only-42"}).status_code, 200)
        created = client.post("/api/cases", json={"event_id": "U06", "participant_id": "P1", "dog_name": "초코"})
        self.assertEqual(created.status_code, 201)
        self.assertIsNone(created.json().get("progress"))
        listed = client.get("/api/cases").json()
        self.assertEqual(listed[0]["progress"]["stage"], "recording")
        self.assertEqual(listed[0]["progress"]["assigned"], [])
        single = client.get(f"/api/cases/{created.json()['case_id']}").json()
        self.assertIsNone(single["progress"])
        self.assertNotIn("progress", json.dumps(single["manifest"]))
