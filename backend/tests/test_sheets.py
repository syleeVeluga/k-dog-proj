"""Independent reviewer permissions and immutable input/revision/exposure records."""

import hashlib
import json
import shutil
from unittest.mock import patch

from app import maintenance, sheets
from app.api import create_app
from app.auth import create_user
from app.domain.recording_v3 import WALK_PHASES
from app.input_models import UserCreate
from tests.support import AppCase, PASSWORD


class SheetTests(AppCase):
    def setUp(self):
        super().setUp()
        self.app = create_app(self.root, intake_spec="20260929")
        self.store = self.app.state.store
        with self.store.connect(write=True) as db:
            create_user(db, UserCreate(username="reviewer2", password=PASSWORD, role="reviewer"))
        self.client = self.client_for("operator")
        self.reviewer = self.client_for("reviewer")
        self.other = self.client_for("reviewer2")
        self.probe = patch("app.recording_v3.probe", return_value={"duration_sec": 100.0}).start()
        self.addCleanup(patch.stopall)
        self.item = self.upload(self.make_case()).json()
        self.video = self.item["manifest"]["sessions"][0]["videos"][0]
        self.base = f"/api/cases/{self.item['case_id']}/sessions/{self.item['selected_session_id']}"
        spans = [("entry", 0, 10), ("baseline", 10, 20), ("alone", 20, 30), ("reunion", 30, 40),
                 ("ignore", 40, 50), ("walk", 52, 64), ("stranger", 70, 80), ("exit", 82, 92)]
        recording = {"video_id": self.video["video_id"], "segments": [
            {"segment": segment, "video_id": self.video["video_id"], "start_sec": start, "end_sec": end}
            for segment, start, end in spans], "walk_phases": [
                {"phase": phase, "video_id": self.video["video_id"], "start_sec": 52 + i * 2, "end_sec": 54 + i * 2}
                for i, phase in enumerate(WALK_PHASES)]}
        saved = self.client.put(self.base + "/recording", json={"expected_revision": self.item["input_revision"], "recording": recording, "confirm": True})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.item = saved.json()

    def assign(self, account="reviewer", *, source=None, purpose="independent"):
        response = self.client.post(self.base + "/sheets", json={"expected_revision": self.item["input_revision"],
            "assigned_username": account, "rater_id": "rater-" + account, "rater_name": "독립 전문가 " + account,
            "purpose": purpose, "source_sheet_id": source})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def observation(self, code="바5", value=0):
        return {"code": code, "value": value, "status": "observed", "opportunity": "present", "validity": "valid",
                "evidence": [{"video_id": self.video["video_id"], "video_sha256": self.video["sha256"], "window_id": "entry",
                              "start_seconds": 0, "end_seconds": 1, "observed_seconds": 1, "note": "원본 첫1초 관찰"}]}

    def save(self, summary, observations, client=None):
        response = (client or self.reviewer).put(f"/api/sheets/{summary['sheet_id']}", json={"expected_revision": summary["revision"], "observations": observations})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def submit(self, summary, client=None):
        blanks = [{"code": item.code, "value": None, "status": "unobserved", "reason": "합성 fixture: 실제 채점 미실시"} for item in sheets.CATALOG.rated_items()]
        blanks[0] = self.observation()
        saved = self.save(summary, blanks, client)
        response = (client or self.reviewer).post(f"/api/sheets/{saved['sheet_id']}/submit", json={"expected_revision": saved["revision"], "reason": "독립 원자료 확정"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_assignment_ownership_is_separate_from_general_write_and_source_is_frozen(self):
        first = self.assign()
        second = self.assign("reviewer2", source=first["sheet_id"])
        self.assertEqual(first["source_hash"], second["source_hash"])
        self.assertNotEqual(first["sheet_id"], second["sheet_id"])
        self.assertEqual(self.reviewer.get(self.base + "/sheets").json(), [{**first, "own": True}])
        self.assertEqual(self.reviewer.get(f"/api/sheets/{second['sheet_id']}").status_code, 403)
        self.assertEqual(self.client.get(f"/api/sheets/{first['sheet_id']}").status_code, 403)
        self.assertEqual(self.other.put(f"/api/sheets/{first['sheet_id']}", json={"expected_revision": 1, "observations": []}).status_code, 403)
        self.assertEqual(self.reviewer.post(self.base + "/sheets", json={"expected_revision": self.item["input_revision"], "assigned_username": "reviewer", "rater_id": "invented", "rater_name": "임의 이름"}).status_code, 403)
        self.assertEqual(self.client_for("developer").get(self.base + "/sheets").status_code, 403)
        self.assertEqual(self.client.post(self.base + "/sheets", json={"expected_revision": self.item["input_revision"], "assigned_username": "admin", "rater_id": "_invalid", "rater_name": "잘못된 ID"}).status_code, 422)
        self.assertEqual(self.reviewer.put(f"/api/cases/{self.item['case_id']}", json={"expected_revision": self.item["input_revision"], "dog_name": "수정", "participant_id": "0001"}).status_code, 403)
        edit = self.client.put(f"/api/cases/{self.item['case_id']}", json={"expected_revision": self.item["input_revision"], "dog_name": "촬영 뒤 수정", "participant_id": "0001"})
        self.assertEqual(edit.status_code, 200, edit.text)
        self.item = edit.json()
        own = self.reviewer.get(f"/api/sheets/{first['sheet_id']}").json()
        self.assertTrue(own["outdated"])
        self.assertEqual(own["document"]["source"]["input_revision"], 3)
        third = self.assign("admin", source=first["sheet_id"])
        self.assertEqual(third["source_hash"], first["source_hash"])

    def test_source_values_zero_negative_memo_counts_latency_and_forbidden_rows(self):
        sheet = self.assign()
        for value in (-2, 0, 2):
            sheet = self.save(sheet, [self.observation(value=value)])
        path = f"/api/sheets/{sheet['sheet_id']}"
        for code, value in (("바5", 3), ("바14", -1), ("바14", .5), ("개32", 99)):
            raw = {"code": code, "value": value, "status": "observed"}
            self.assertEqual(self.reviewer.put(path, json={"expected_revision": sheet["revision"], "observations": [raw]}).status_code, 422)
        for code in ("개26", "개27", "개36", "개60", "개20", "개31", "개33", "개35", "개999"):
            self.assertEqual(self.reviewer.put(path, json={"expected_revision": sheet["revision"], "observations": [{"code": code, "value": 0, "status": "observed"}]}).status_code, 422)
        raw = {"code": "개32", "value": 99, "status": "observed", "latency_not_occurred": True}
        sheet = self.save(sheet, [raw])
        self.assertEqual(self.reviewer.get(path).json()["document"]["sheet"]["observations"][0]["value"], 99)
        raw.update(value=1.2345, latency_not_occurred=False, actual_latency_seconds=1.2345)
        sheet = self.save(sheet, [raw])
        self.assertEqual(self.reviewer.get(path).json()["document"]["sheet"]["observations"][0]["actual_latency_seconds"], 1.2345)
        sheet = self.save(sheet, [{"code": "바14", "value": 0, "status": "observed"},
                                  {"code": "개59", "value": "실제 접촉 중 중단, 관찰한 원값 보존", "status": "observed", "welfare_stopped": True}])
        self.assertEqual(self.reviewer.get(path).json()["document"]["sheet"]["observations"][0]["value"], 0)
        for memo in (0, " "):
            self.assertEqual(self.reviewer.put(path, json={"expected_revision": sheet["revision"], "observations": [{"code": "개59", "value": memo, "status": "observed"}]}).status_code, 422)
        missing = {"code": "바5", "value": None, "status": "no_opportunity", "opportunity": "absent", "reason": "미접촉"}
        sheet = self.save(sheet, [missing])
        invalid_evidence = self.observation()
        invalid_evidence["evidence"][0]["end_seconds"] = 11
        self.assertEqual(self.reviewer.put(path, json={"expected_revision": sheet["revision"], "observations": [invalid_evidence]}).status_code, 422)
        missing["reason"] = " "
        self.assertEqual(self.reviewer.put(path, json={"expected_revision": sheet["revision"], "observations": [missing]}).status_code, 422)

    def test_submission_lock_reopen_preserves_original_and_revisions_conflict(self):
        sheet = self.assign()
        path = f"/api/sheets/{sheet['sheet_id']}"
        self.assertEqual(self.reviewer.post(path + "/submit", json={"expected_revision": 1, "reason": "누락"}).status_code, 422)
        original = self.submit(sheet)
        data = self.store.path(original["manifest_ref"]).read_bytes()
        self.assertEqual(self.reviewer.put(path, json={"expected_revision": original["revision"], "observations": []}).status_code, 409)
        self.assertEqual(self.reviewer.post(path + "/reopen", json={"expected_revision": original["revision"], "reason": "자기 재개방"}).status_code, 403)
        opened = self.client.post(path + "/reopen", json={"expected_revision": original["revision"], "reason": "근거 정정 승인"})
        self.assertEqual(opened.status_code, 200, opened.text)
        updated = self.save(opened.json(), [self.observation(value=1)])
        self.assertEqual(self.reviewer.put(path, json={"expected_revision": opened.json()["revision"], "observations": []}).status_code, 409)
        self.assertEqual(self.store.path(original["manifest_ref"]).read_bytes(), data)
        current = self.reviewer.get(path).json()["document"]
        self.assertEqual(current["initial_submission"]["ref"], original["manifest_ref"])
        old = self.reviewer.get(path + f"/revisions/{original['revision']}").json()
        self.assertEqual(old["state"], "submitted")
        self.assertEqual(old["sheet"]["observations"][0]["value"], 0)
        self.assertEqual(updated["revision"], original["revision"] + 2)

    def test_explicit_grant_then_actual_reveal_changes_current_source_not_independent_original(self):
        one = self.assign()
        two = self.assign("reviewer2", source=one["sheet_id"])
        grant = {"expected_revision": one["revision"], "target_sheet_id": two["sheet_id"], "target_revision": two["revision"], "reason": "독립 완료 후 검수 공개"}
        self.assertEqual(self.client.post(f"/api/sheets/{one['sheet_id']}/grants", json=grant).status_code, 409)
        one, two = self.submit(one), self.submit(two, self.other)
        own_path = f"/api/sheets/{one['sheet_id']}"
        self.assertEqual(self.reviewer.get(own_path).json()["grants"], [])
        grant.update(expected_revision=one["revision"], target_revision=two["revision"])
        self.assertEqual(self.reviewer.post(own_path + "/grants", json=grant).status_code, 403)
        granted = self.client.post(own_path + "/grants", json=grant)
        self.assertEqual(granted.status_code, 200, granted.text)
        self.assertEqual(self.reviewer.get(own_path).json()["document"]["purpose"], "independent")
        reveal = self.reviewer.post(own_path + "/reveal", json={"expected_revision": one["revision"], "ref": two["manifest_ref"]})
        self.assertEqual(reveal.status_code, 200, reveal.text)
        exposed = self.reviewer.get(own_path).json()["document"]
        self.assertEqual(exposed["purpose"], "review")
        self.assertEqual(exposed["exposures"][0]["hash"], two["manifest_hash"])
        self.assertFalse(exposed["sheet"]["ai_exposed"])
        original = self.reviewer.get(own_path + f"/revisions/{one['revision']}").json()
        self.assertEqual(original["purpose"], "independent")
        self.assertEqual(original["exposures"], [])
        self.assertEqual(self.reviewer.get(f"/api/sheets/{two['sheet_id']}").status_code, 403)
        self.assertEqual(self.client.post(self.base + "/sheets", json={"expected_revision": self.item["input_revision"], "assigned_username": "reviewer", "rater_id": "new-name", "rater_name": "새 독립 이름"}).status_code, 409)
        cancelled = self.client.patch(f"/api/sheets/{two['sheet_id']}/assignment", json={"expected_revision": two["revision"], "reason": "공개 대상 취소", "active": False})
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(self.reviewer.post(own_path + "/reveal", json={"expected_revision": exposed["revision"], "ref": two["manifest_ref"]}).status_code, 403)

    def test_hash_backup_restore_revocation_and_deleted_case_purge(self):
        sheet = self.submit(self.assign())
        backup = self.root.parent / (self.root.name + "-sheet-backup")
        restored = self.root.parent / (self.root.name + "-sheet-restored")
        self.addCleanup(lambda: shutil.rmtree(backup, ignore_errors=True))
        self.addCleanup(lambda: shutil.rmtree(restored, ignore_errors=True))
        maintenance.backup(self.store, backup, "operator")
        maintenance.restore(self.store, backup, restored)
        self.assertEqual(hashlib.sha256((restored / sheet["manifest_ref"]).read_bytes()).hexdigest(), sheet["manifest_hash"])
        reopened = self.client.post(f"/api/sheets/{sheet['sheet_id']}/reopen", json={"expected_revision": sheet["revision"], "reason": "수정"}).json()
        revoked = self.client.patch(f"/api/sheets/{sheet['sheet_id']}/assignment", json={"expected_revision": reopened["revision"], "reason": "평가 취소", "active": False})
        self.assertEqual(revoked.status_code, 200, revoked.text)
        self.assertEqual(self.reviewer.get(f"/api/sheets/{sheet['sheet_id']}").status_code, 403)
        enabled = self.client.patch(f"/api/sheets/{sheet['sheet_id']}/assignment", json={"expected_revision": revoked.json()["revision"], "reason": "재배정 확인", "active": True}).json()
        self.store.path(enabled["manifest_ref"]).write_bytes(b"corrupt")
        self.assertEqual(self.reviewer.get(f"/api/sheets/{sheet['sheet_id']}").status_code, 409)
        self.delete_case(self.item)
        self.assertEqual(self.reviewer.get(f"/api/sheets/{sheet['sheet_id']}").status_code, 403)
        maintenance.clean(self.store, purge_deleted=True)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM score_sheets").fetchone()[0], 0)
        self.assertFalse(self.store.path(enabled["manifest_ref"]).exists())

    def test_case_or_assignment_change_between_write_and_adoption_is_not_published(self):
        sheet = self.assign()
        original = sheets.write_document
        def cancel_between_write(*args):
            result = original(*args)
            response = self.client.patch(f"/api/sheets/{sheet['sheet_id']}/assignment", json={"expected_revision": 1, "reason": "동시 취소", "active": False})
            self.assertEqual(response.status_code, 200, response.text)
            return result
        # Only intercept the candidate write; the cancellation's own immutable write is real.
        def candidate(*args):
            with patch("app.sheets.write_document", original):
                return cancel_between_write(*args)
        with patch("app.sheets.write_document", side_effect=candidate):
            self.assertEqual(self.reviewer.put(f"/api/sheets/{sheet['sheet_id']}", json={"expected_revision": 1, "observations": [self.observation()]}).status_code, 409)
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM score_sheets WHERE sheet_id=?", (sheet["sheet_id"],)).fetchone()
            self.assertEqual(sheets.document_for(self.store, row).sheet.observations, ())

    def test_exposure_through_other_purpose_and_preprocess_retry_cannot_reset_independence(self):
        one = self.assign()
        review = self.assign(purpose="review", source=one["sheet_id"])
        two = self.submit(self.assign("reviewer2", source=one["sheet_id"]), self.other)
        review = self.submit(review)
        path = f"/api/sheets/{review['sheet_id']}"
        self.assertEqual(self.client.post(path + "/grants", json={"expected_revision": review["revision"], "target_sheet_id": two["sheet_id"], "target_revision": two["revision"], "reason": "별도 검수 공개"}).status_code, 200)
        original = sheets.write_document
        def reveal_between_write(*args):
            with patch("app.sheets.write_document", original):
                result = original(*args)
                self.assertEqual(self.reviewer.post(path + "/reveal", json={"expected_revision": review["revision"], "ref": two["manifest_ref"]}).status_code, 200)
                return result
        with patch("app.sheets.write_document", side_effect=reveal_between_write):
            response = self.reviewer.put(f"/api/sheets/{one['sheet_id']}", json={"expected_revision": one["revision"], "observations": [self.observation()]})
        self.assertEqual(response.status_code, 409, response.text)
        one = self.submit(one)
        own = self.reviewer.get(f"/api/sheets/{one['sheet_id']}").json()["document"]
        self.assertEqual(own["purpose"], "review")
        self.assertEqual(own["exposures"][0]["ref"], two["manifest_ref"])
        self.assertIsNone(own["initial_submission"])
        # C04 retries change provenance only, not the original manifest. This is a contract fixture, no provider call.
        ref = "clips/retry-fixture/clips.json"
        self.store.path(ref).parent.mkdir(parents=True)
        self.store.path(ref).write_bytes(b"{}")
        with self.store.connect(write=True) as db:
            self.store.audit(db, "operator", self.item["case_id"], "preprocess.complete", {"session_id": self.item["selected_session_id"], "ref": ref, "hash": hashlib.sha256(b"{}").hexdigest()})
        batch = {"schema_version": "3.0", "input_revision": self.item["input_revision"], **sheets.ASSET_HASHES, "windows": own["source"]["windows"]}
        with patch("app.sheets.latest", return_value=batch):
            response = self.client.post(self.base + "/sheets", json={"expected_revision": self.item["input_revision"], "assigned_username": "reviewer", "rater_id": "retry-name", "rater_name": "새 독립 이름"})
        self.assertEqual(response.status_code, 409, response.text)
        edit = self.client.put(f"/api/cases/{self.item['case_id']}", json={"expected_revision": self.item["input_revision"], "dog_name": "오타만 정정", "participant_id": "0001"})
        self.assertEqual(edit.status_code, 200, edit.text)
        self.item = edit.json()
        response = self.client.post(self.base + "/sheets", json={"expected_revision": self.item["input_revision"], "assigned_username": "reviewer", "rater_id": "metadata-name", "rater_name": "오타 정정 뒤 새 이름"})
        self.assertEqual(response.status_code, 409, response.text)
        fresh_review = self.assign(purpose="review")
        fresh_review = self.save(fresh_review, [self.observation()])
        current = self.reviewer.get(f"/api/sheets/{fresh_review['sheet_id']}").json()["document"]
        self.assertEqual(current["exposures"][0]["ref"], two["manifest_ref"])

    def test_separate_review_assignment_does_not_block_original_reveal(self):
        one = self.assign()
        self.assign(purpose="review", source=one["sheet_id"])
        one, two = self.submit(one), self.submit(self.assign("reviewer2", source=one["sheet_id"]), self.other)
        path = f"/api/sheets/{one['sheet_id']}"
        self.assertEqual(self.client.post(path + "/grants", json={"expected_revision": one["revision"], "target_sheet_id": two["sheet_id"], "target_revision": two["revision"], "reason": "독립 완료 공개"}).status_code, 200)
        reveal = self.reviewer.post(path + "/reveal", json={"expected_revision": one["revision"], "ref": two["manifest_ref"]})
        self.assertEqual(reveal.status_code, 200, reveal.text)
        self.assertEqual(self.reviewer.get(path).json()["document"]["purpose"], "review")

    def test_composite_leash_evidence_keeps_separate_actual_ranges_and_excludes_object_stop(self):
        recording = self.item["manifest"]["sessions"][0]["recording"]
        recording["events"] = [{"event_id": "actual-stop", "kind": "object_stop", "video_id": self.video["video_id"], "segment": "entry", "status": "observed", "seconds": 3, "end_seconds": 5, "note": "합성 실제 정지"}]
        response = self.client.put(self.base + "/recording", json={"expected_revision": self.item["input_revision"], "recording": recording, "confirm": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.item = response.json()
        sheet = self.assign()
        raw = self.observation("개45", 0)
        raw["evidence"][0]["window_id"] = "entry_leash"
        raw["evidence"].append({**raw["evidence"][0], "start_seconds": 6, "end_seconds": 7})
        sheet = self.save(sheet, [raw])
        for start, end in ((3, 4), (2, 6)):
            invalid = {**raw, "evidence": [{**raw["evidence"][0], "start_seconds": start, "end_seconds": end}]}
            self.assertEqual(self.reviewer.put(f"/api/sheets/{sheet['sheet_id']}", json={"expected_revision": sheet["revision"], "observations": [invalid]}).status_code, 422)
        blanks = [{"code": item.code, "value": None, "status": "unobserved", "reason": "합성 시험"} if item.code != "개45" else raw for item in sheets.CATALOG.rated_items()]
        sheet = self.save(sheet, blanks)
        self.assertEqual(self.reviewer.post(f"/api/sheets/{sheet['sheet_id']}/submit", json={"expected_revision": sheet["revision"], "reason": "실제 줄 근거 제출"}).status_code, 200)

    def test_other_camera_evidence_must_fit_its_own_actual_duration(self):
        self.item = self.upload(self.item, b"short-other-camera", "other.mp4").json()
        session = self.item["manifest"]["sessions"][0]
        other = session["videos"][-1]
        self.probe.side_effect = lambda path: {"duration_sec": 10.0 if path.read_bytes() == b"short-other-camera" else 100.0}
        recording = session["recording"]
        recording["video_offsets"] = [{"video_id": other["video_id"], "offset_seconds": 0, "confirmed": True, "note": "동시 촬영 합성 fixture"}]
        response = self.client.put(self.base + "/recording", json={"expected_revision": self.item["input_revision"], "recording": recording, "confirm": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.item = response.json()
        sheet = self.assign()
        raw = self.observation("개23", 0)
        raw["evidence"] = [{**raw["evidence"][0], "video_id": other["video_id"], "video_sha256": other["sha256"], "window_id": "ignore", "start_seconds": 40, "end_seconds": 41}]
        response = self.reviewer.put(f"/api/sheets/{sheet['sheet_id']}", json={"expected_revision": sheet["revision"], "observations": [raw]})
        self.assertEqual(response.status_code, 422, response.text)
        raw = self.observation()
        raw["evidence"][0].update(video_id=other["video_id"], video_sha256=other["sha256"])
        self.save(sheet, [raw])

    def test_completed_ai_contract_is_read_only_and_disclosure_records_ai_exposure(self):
        one = self.submit(self.assign())
        two = self.submit(self.assign("reviewer2", source=one["sheet_id"]), self.other)
        # Trusted C07 service fixture; C05 human assignment API never creates AI sheets.
        with self.store.connect(write=True) as db:
            row = sheets.row_for(self.store, db, two["sheet_id"])
            doc = sheets.document_for(self.store, row).model_dump(mode="json")
            doc["sheet"]["rater_kind"] = "ai"
            doc["revision"] += 1
            doc["previous"].append(sheets.reference(row))
            ref, digest = sheets.write_document(self.store, doc)
            db.execute("UPDATE score_sheets SET revision=?,manifest_ref=?,manifest_hash=? WHERE sheet_id=?", (doc["revision"], ref, digest, two["sheet_id"]))
            two.update(revision=doc["revision"], manifest_ref=ref, manifest_hash=digest)
        target = f"/api/sheets/{two['sheet_id']}"
        self.assertEqual(self.other.get(target).json()["document"]["state"], "submitted")
        self.assertEqual(self.other.put(target, json={"expected_revision": two["revision"], "observations": []}).status_code, 403)
        self.assertEqual(self.other.post(target + "/submit", json={"expected_revision": two["revision"], "reason": "대리 AI 덮어쓰기"}).status_code, 403)
        path = f"/api/sheets/{one['sheet_id']}"
        self.assertEqual(self.client.post(path + "/grants", json={"expected_revision": one["revision"], "target_sheet_id": two["sheet_id"], "target_revision": two["revision"], "reason": "AI 완료 원자료 공개"}).status_code, 200)
        self.assertEqual(self.reviewer.post(path + "/reveal", json={"expected_revision": one["revision"], "ref": two["manifest_ref"]}).status_code, 200)
        current = self.reviewer.get(path).json()["document"]
        self.assertTrue(current["sheet"]["ai_exposed"])
        self.assertEqual(current["purpose"], "review")
        self.assertFalse(self.reviewer.get(path + f"/revisions/{one['revision']}").json()["sheet"]["ai_exposed"])
