import hashlib
import json
from pathlib import Path
import tempfile
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app import sheets_v4 as sheets
from app.domain.catalog_v4 import OPTIONAL_CODES, SURVEY_VERSION, load_catalog_v4
from app.domain.media_v4 import StoredMediaV4
from app.domain.sheets_v4 import AI_ACCOUNT, SheetDocumentV4
from app.input_models_v3 import CaseCreateV3
from app.intake import create_case
from app.storage import Store, encode, uid
from tests.test_recording_v4 import event, fixture, recording


def model(cls, **values):
    return cls.model_validate_json(json.dumps(values, ensure_ascii=False))


class SheetsV4Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kdog-sheet-s1-")
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "store")
        self.people = {name: SimpleNamespace(username=name, role=role) for name, role in
                       (("operator", "operator"), ("reviewer", "reviewer"), ("other", "reviewer"), ("admin", "admin"), ("developer", "developer"))}
        with self.store.connect(write=True) as db:
            for user in self.people.values():
                db.execute("INSERT INTO users(username,role,password_hash,active) VALUES(?,?,?,1)", (user.username, user.role, "synthetic-password"))
            case = create_case(self.store, db, model(CaseCreateV3, participant_id="SYNTHETIC", event_id="TEST", dog_name="합성견"),
                               "operator", SURVEY_VERSION)
            self.case_id = case
        self.payload = b"synthetic source bytes, never participant video"
        self.video_hash = hashlib.sha256(self.payload).hexdigest()
        self.store.path("videos/v1.mp4").write_bytes(self.payload)
        video = StoredMediaV4(video_id="v1", upload_id="up1", original_name="synthetic.mp4", storage_ref="videos/v1.mp4",
                              sha256=self.video_hash, size_bytes=len(self.payload), camera_id="CAM1", source_original_number="1",
                              source_kind="original", media_status="pending_probe")
        with self.store.connect(write=True) as db:
            row = self.store.case(db, self.case_id)
            manifest = self.store.manifest(row)
            session = manifest.sessions[0]
            session.videos = [video]
            session.recording_s1 = recording()
            self.session_id = session.session_id
            self.store.save(db, row, manifest, "operator", "synthetic.recording")
        self.addCleanup(patch.stopall)
        patch("app.recording_v4.probe", return_value={"duration_sec": 300}).start()

    def case_revision(self):
        with self.store.connect() as db:
            return self.store.case(db, self.case_id)["input_revision"]

    def assign(self, who="reviewer", *, source=None, purpose="independent", batch=None):
        value = model(sheets.SheetAssignmentV4, expected_revision=self.case_revision(), assigned_username=who,
                      rater_id="rater-" + who, rater_name="합성 평가자 " + who, source_sheet_id=source, purpose=purpose, batch_id=batch)
        return sheets.assign(self.store, self.case_id, self.session_id, value, self.people["operator"])

    def observe(self, code="개5", value=0, window="entry_whole", start=0, end=1, whole=False):
        return {"code": code, "value": value, "status": "observed", "opportunity": "present", "validity": "valid",
                "whole_interval_observed": whole, "evidence": [{"video_id": "v1", "video_sha256": self.video_hash,
                "camera_id": "CAM1", "window_id": window, "start_seconds": start, "end_seconds": end,
                "observed_seconds": end - start, "note": "F 원관찰 근거"}]}

    def save(self, row, observations, who="reviewer", **extra):
        value = model(sheets.SheetEditV4, expected_revision=row["revision"], observations=observations, **extra)
        return sheets.revise(self.store, row["sheet_id"], value, self.people[who], "save")

    def submit(self, row, who="reviewer"):
        blanks = [{"code": item.code, "value": None, "status": "unobserved", "reason": "합성 관찰 불가"}
                  for item in load_catalog_v4().rated_items() if item.code not in OPTIONAL_CODES]
        blanks[0] = self.observe()
        row = self.save(row, blanks, who)
        return sheets.revise(self.store, row["sheet_id"], model(sheets.SheetReasonV4, expected_revision=row["revision"], reason="합성 독립 제출"),
                             self.people[who], "submit")

    def view(self, row, who="reviewer"):
        return sheets.view(self.store, row["sheet_id"], self.people[who])

    def grant(self, viewer, target):
        return sheets.grant(self.store, viewer["sheet_id"], model(sheets.SheetGrantV4, expected_revision=viewer["revision"],
                            target_sheet_id=target["sheet_id"], target_revision=target["revision"], reason="합성 명시 공개"), self.people["operator"])

    def reveal(self, viewer, target, who="reviewer"):
        return sheets.revise(self.store, viewer["sheet_id"], model(sheets.SheetRevealV4, expected_revision=viewer["revision"], ref=target["manifest_ref"]),
                             self.people[who], "reveal")

    def test_empty_s1_ownership_frozen_input_and_required_optional_separation(self):
        one = self.assign()
        two = self.assign("other", source=one["sheet_id"])
        self.assertEqual(one["source_hash"], two["source_hash"])
        result = self.view(one)
        self.assertEqual(result["document"]["sheet"]["observations"], [])
        self.assertEqual(len(result["missing_required_codes"]), 84)
        self.assertNotIn("바54", result["missing_required_codes"])
        for who in ("other", "operator", "admin", "developer"):
            with self.assertRaises(HTTPException) as caught:
                self.view(one, who)
            self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(len(sheets.list_sheets(self.store, self.case_id, self.session_id, self.people["reviewer"])), 1)
        with self.assertRaises(HTTPException):
            sheets.list_sheets(self.store, self.case_id, self.session_id, self.people["developer"])
        with self.store.connect(write=True) as db:
            row = self.store.case(db, self.case_id)
            manifest = self.store.manifest(row)
            manifest.sessions[0].note = "새 운영 메모"
            self.store.save(db, row, manifest, "operator", "synthetic.edit")
        self.assertTrue(self.view(one)["outdated"])
        self.assertEqual(self.view(one)["document"]["source"]["session"]["note"], "")

    def test_strict_values_auto_retired_and_missing_na_insufficient_policy_states(self):
        row = self.assign()
        for value in (-2, 0, 2):
            row = self.save(row, [self.observe(value=value)])
        for code, value in (("개5", 3), ("개5", True), ("개5", "0"), ("개5", 0.0), ("개26", 0), ("개32", 99), ("개59", "memo"), ("바46", -1)):
            with self.assertRaises((HTTPException, ValidationError)):
                self.save(row, [self.observe(code=code, value=value)])
        states = [{"code": "개19", "value": None, "status": "no_opportunity", "opportunity": "absent", "reason": "실제 미접촉"},
                  {"code": "바46", "value": None, "status": "insufficient_observation", "reason": "일부 가림", "evidence": self.observe()["evidence"]},
                  {"code": "개21", "value": None, "status": "policy_pending", "reason": "D03 시간 정의"}]
        row = self.save(row, states)
        self.assertEqual([value["status"] for value in self.view(row)["document"]["sheet"]["observations"]],
                         ["no_opportunity", "insufficient_observation", "policy_pending"])
        for bad in ({"code": "개5", "value": None, "status": "unobserved"}, {"code": "개5", "value": 0, "status": "unobserved", "reason": "미관찰"}):
            with self.assertRaises(ValidationError):
                self.save(row, [bad])

    def test_whole_body_count_zero_and_vocal_denominator_need_actual_whole_evidence(self):
        row = self.assign()
        with self.assertRaises(HTTPException):
            self.save(row, [self.observe("바46", 0, end=15, whole=True)])
        row = self.save(row, [self.observe("바46", 0, end=30, whole=True)])
        vocal = self.observe("바6", 1, end=30, whole=True)
        vocal["vocalization"] = {"listened_seconds": 30, "cumulative_vocal_seconds": 10, "whole_interval_judged": True, "note": "합성 전체 청취"}
        row = self.save(row, [vocal])
        vocal["vocalization"].update(listened_seconds=60, cumulative_vocal_seconds=20)
        with self.assertRaises(HTTPException):
            self.save(row, [vocal])

    def test_f_g_notes_walk_exceptions_and_separate_59_survive_without_g_analysis_leak(self):
        row = self.assign()
        observation = self.observe()
        observation["review_memo"] = "G 양식 오타 검토: 분석 제외"
        row = self.save(row, [observation, {"code": "보25", "value": "접촉 기회 실제 메모", "status": "observed", "validity": "valid"}],
                        walk_phases=[{"code": "개38", "proximity_exception": "recheck", "note": "재확인 필요"}],
                        linked_memos=[{"text": "개59 원관찰 연결", "item_codes": ["개5"], "evidence": observation["evidence"]}])
        raw = self.view(row)["document"]
        result = sheets.analysis_input(SheetDocumentV4.model_validate_json(encode(raw)))
        self.assertIsNone(result.observations[0].review_memo)
        self.assertEqual(result.observations[0].evidence[0].note, "F 원관찰 근거")
        self.assertEqual(raw["sheet"]["observations"][0]["review_memo"], observation["review_memo"])
        self.assertEqual(result.linked_memos[0].code, "개59")
        self.assertEqual(result.walk_phases[0].proximity_exception, "recheck")
        document = SheetDocumentV4.model_validate_json(encode(raw))
        corrupted = document.sheet.observations[0].model_copy(update={"value": True})
        sheet = document.sheet.model_copy(update={"observations": (corrupted, *document.sheet.observations[1:])})
        with self.assertRaises(ValidationError):
            sheets.analysis_input(document.model_copy(update={"sheet": sheet}))

    def test_submission_lock_optional_absence_reopen_and_revision_conflicts(self):
        row = self.assign()
        with self.assertRaises(HTTPException) as caught:
            sheets.revise(self.store, row["sheet_id"], model(sheets.SheetReasonV4, expected_revision=1, reason="누락"), self.people["reviewer"], "submit")
        self.assertEqual(caught.exception.status_code, 422)
        submitted = self.submit(row)
        original = self.store.path(submitted["manifest_ref"]).read_bytes()
        self.assertEqual(len(self.view(submitted)["document"]["sheet"]["observations"]), 86)
        with self.assertRaises(HTTPException):
            self.save(submitted, [])
        reason = model(sheets.SheetReasonV4, expected_revision=submitted["revision"], reason="근거 정정")
        with self.assertRaises(HTTPException):
            sheets.revise(self.store, row["sheet_id"], reason, self.people["reviewer"], "reopen")
        opened = sheets.revise(self.store, row["sheet_id"], reason, self.people["operator"], "reopen")
        updated = self.save(opened, [self.observe(value=1)])
        with self.assertRaises(HTTPException) as caught:
            self.save(opened, [self.observe(value=2)])
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self.store.path(submitted["manifest_ref"]).read_bytes(), original)
        self.assertEqual(self.view(updated)["document"]["initial_submission"]["ref"], submitted["manifest_ref"])
        self.assertEqual(sheets.revision(self.store, row["sheet_id"], submitted["revision"], self.people["reviewer"]).state, "submitted")

    def test_grant_is_not_exposure_reveal_preserves_independent_original(self):
        first = self.assign()
        second = self.assign("other", source=first["sheet_id"])
        first, second = self.submit(first), self.submit(second, "other")
        with self.assertRaises(HTTPException):
            self.reveal(first, second)
        self.grant(first, second)
        self.assertEqual(self.view(first)["document"]["exposures"], [])
        disclosed = self.reveal(first, second)
        self.assertEqual(disclosed["viewer"]["purpose"], "review")
        self.assertEqual(disclosed["target"]["sheet"]["rater_id"], "rater-other")
        original = sheets.revision(self.store, first["sheet_id"], first["revision"], self.people["reviewer"])
        self.assertEqual(original.purpose, "independent")
        self.assertEqual(original.exposures, ())
        self.assertEqual(len(self.view(disclosed["viewer"])["document"]["exposures"]), 1)

    def test_duplicate_assignment_and_new_batch_do_not_reset_independence(self):
        original = self.assign()
        with self.assertRaises(HTTPException):
            self.assign(batch="another-batch")
        review = self.assign(purpose="review", batch="another-batch")
        self.assertNotEqual(original["source_hash"], review["source_hash"])
        with self.assertRaises(HTTPException):
            self.assign(purpose="review", batch="another-batch")

    def test_mutation_adoption_rechecks_case_revision_assignment_and_user(self):
        row = self.assign()
        write = sheets.write_document
        def deactivate(store, data):
            output = write(store, data)
            with store.connect(write=True) as db:
                db.execute("UPDATE users SET active=0 WHERE username='reviewer'")
            return output
        with patch("app.sheets_v4.write_document", side_effect=deactivate):
            with self.assertRaises(HTTPException) as caught:
                self.save(row, [self.observe()])
        self.assertEqual(caught.exception.status_code, 403)
        with self.store.connect(write=True) as db:
            self.assertEqual(db.execute("SELECT revision FROM score_sheets WHERE sheet_id=?", (row["sheet_id"],)).fetchone()[0], 1)
            db.execute("UPDATE users SET active=1 WHERE username='reviewer'")
        def change_case(store, data):
            output = write(store, data)
            with store.connect(write=True) as db:
                current = store.case(db, self.case_id)
                manifest = store.manifest(current)
                manifest.sessions[0].note = "동시 운영 변경"
                store.save(db, current, manifest, "operator", "synthetic.concurrent")
            return output
        with patch("app.sheets_v4.write_document", side_effect=change_case):
            with self.assertRaises(HTTPException) as caught:
                self.save(row, [self.observe()])
        self.assertEqual(caught.exception.status_code, 409)

    def test_revoked_target_cannot_be_revealed_even_with_existing_grant(self):
        first = self.assign()
        second = self.assign("other", source=first["sheet_id"])
        first, second = self.submit(first), self.submit(second, "other")
        self.grant(first, second)
        sheets.revise(self.store, second["sheet_id"], model(sheets.SheetActiveV4, expected_revision=second["revision"], reason="배정 취소", active=False),
                      self.people["operator"], "assignment")
        with self.assertRaises(HTTPException) as caught:
            self.reveal(first, second)
        self.assertEqual(caught.exception.status_code, 403)

    def test_hash_damage_and_deletion_prevent_reads_and_writes(self):
        row = self.assign()
        payload = self.store.path(row["manifest_ref"]).read_bytes()
        self.store.path(row["manifest_ref"]).write_bytes(payload + b" ")
        with self.assertRaises(HTTPException) as caught:
            self.view(row)
        self.assertEqual(caught.exception.status_code, 409)
        self.store.path(row["manifest_ref"]).write_bytes(payload)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (self.case_id,))
        with self.assertRaises(HTTPException):
            self.view(row)
        with self.assertRaises(HTTPException):
            self.save(row, [])

    def test_ai_original_cannot_claim_human_origin_or_be_overwritten(self):
        human = self.submit(self.assign())
        data = self.view(human)["document"]
        data.update(assigned_username=AI_ACCOUNT, origin="ai_service", ai_run_id="synthetic-ai-run", previous=[], initial_submission=None, revision=1)
        data["sheet"].update(sheet_id=uid(), rater_id="ai-model", rater_kind="ai")
        model_doc = SheetDocumentV4.model_validate_json(encode(data))
        wrong = model_doc.model_dump(mode="json")
        wrong["origin"] = "human_web"
        with self.assertRaises(ValidationError):
            SheetDocumentV4.model_validate_json(encode(wrong))
        ref, digest = sheets.write_document(self.store, data)
        with self.store.connect(write=True) as db:
            db.execute("INSERT OR IGNORE INTO users(username,role,password_hash,active) VALUES(?,?,?,0)", (AI_ACCOUNT, "developer", "service-only"))
            db.execute("INSERT INTO score_sheets VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (model_doc.sheet.sheet_id, self.case_id, self.session_id,
                       AI_ACCOUNT, "ai-model", model_doc.rater_name, model_doc.source_hash, "independent", "submitted", 1, 1, ref, digest))
        with self.assertRaises(HTTPException):
            sheets.revise(self.store, model_doc.sheet.sheet_id, model(sheets.SheetReasonV4, expected_revision=1, reason="AI 정정"), self.people["operator"], "reopen")
        target = {"sheet_id": model_doc.sheet.sheet_id, "revision": 1, "manifest_ref": ref}
        self.grant(human, target)
        revealed = self.reveal(human, target)
        self.assertTrue(self.view(revealed["viewer"])["document"]["sheet"]["ai_exposed"])

    def test_fake_camera_hash_unsynchronized_and_outside_window_evidence_rejected(self):
        row = self.assign()
        for key, value in (("camera_id", "CAM2"), ("video_sha256", "0" * 64), ("video_id", "unknown"), ("end_seconds", 31)):
            observation = self.observe()
            observation["evidence"][0][key] = value
            with self.assertRaises(HTTPException):
                self.save(row, [observation])
        phase = self.observe("개40", 1, window="walk_phase_3", start=176, end=189)
        row = self.save(row, [phase])
        self.assertEqual(self.view(row)["document"]["sheet"]["observations"][0]["evidence"][0]["window_id"], "walk_phase_3")
        with self.assertRaises(HTTPException):
            self.save(row, [self.observe("개40", 1, window="walk_whole", start=167, end=170)])

    def test_explicit_occlusion_cannot_be_overridden_by_claiming_whole_observation(self):
        value = fixture()
        loss = event("loss", "body_not_visible", "entry", 10, 12)
        loss["affected_codes"] = ["바46"]
        value["events"] = [loss]
        with self.store.connect(write=True) as db:
            row = self.store.case(db, self.case_id)
            manifest = self.store.manifest(row)
            manifest.sessions[0].recording_s1 = recording(value)
            self.store.save(db, row, manifest, "operator", "synthetic.occlusion")
        row = self.assign()
        with self.assertRaises(HTTPException):
            self.save(row, [self.observe("바46", 0, end=30, whole=True)])
        row = self.save(row, [{"code": "바46", "value": None, "status": "insufficient_observation", "reason": "실제 신체 미관찰"}])
        self.assertEqual(self.view(row)["document"]["sheet"]["observations"][0]["value"], None)

    def test_exposure_in_other_purpose_is_inherited_and_cannot_be_raced(self):
        independent = self.assign()
        review = self.assign(purpose="review", source=independent["sheet_id"])
        other = self.assign("other", source=independent["sheet_id"])
        review, other = self.submit(review), self.submit(other, "other")
        self.grant(review, other)
        original_write = sheets.write_document
        triggered = False
        def reveal_while_saving(store, data):
            nonlocal triggered
            result = original_write(store, data)
            if data["sheet"]["sheet_id"] == independent["sheet_id"] and not triggered:
                triggered = True
                self.reveal(review, other)
            return result
        with patch("app.sheets_v4.write_document", side_effect=reveal_while_saving):
            with self.assertRaises(HTTPException) as caught:
                self.save(independent, [self.observe()])
        self.assertEqual(caught.exception.status_code, 409)
        current = self.save(independent, [self.observe()])
        self.assertEqual(current["purpose"], "review")
        self.assertEqual(len(self.view(current)["document"]["exposures"]), 1)

    def test_media_change_after_validation_is_not_adopted(self):
        row = self.assign()
        original_write = sheets.write_document
        def tamper(store, data):
            output = original_write(store, data)
            store.path("videos/v1.mp4").write_bytes(b"changed after source validation")
            return output
        with patch("app.sheets_v4.write_document", side_effect=tamper):
            with self.assertRaises(HTTPException) as caught:
                self.save(row, [self.observe()])
        self.assertEqual(caught.exception.status_code, 409)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT revision FROM score_sheets WHERE sheet_id=?", (row["sheet_id"],)).fetchone()[0], 1)

    def test_closed_store_backup_restore_preserves_original_and_owner_permissions(self):
        row = self.submit(self.assign())
        root = Path(self.temp.name) / "restored"
        shutil.copytree(self.store.root, root)
        restored = Store(root)
        saved = sheets.view(restored, row["sheet_id"], self.people["reviewer"])
        self.assertEqual(saved["document"]["state"], "submitted")
        self.assertEqual(hashlib.sha256(restored.path(row["manifest_ref"]).read_bytes()).hexdigest(), row["manifest_hash"])
        with self.assertRaises(HTTPException):
            sheets.view(restored, row["sheet_id"], self.people["other"])


if __name__ == "__main__":
    unittest.main()
