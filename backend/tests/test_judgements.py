"""Pinned input, judgement completeness, permissions and maintenance safeguards."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import judgements, maintenance, sheets
from app.domain.contracts_v3 import DecisionV3
from app.domain.results_v3 import BasicResultV3
from app.scoring_v3 import RULE_HASH, RULE_VERSION, calculate
from app.storage import Store
from tests import test_sheets
from tests.scoring_fixtures_v3 import event, fixture


class JudgementTests(test_sheets.SheetTests):
    def calculated(self, sheet=None):
        sheet = sheet or self.save(self.assign(), [self.observation("개5", -1), self.observation("개6", 1), self.observation("개7", 0)])
        link = {"sheet_id": sheet["sheet_id"], "revision": sheet["revision"], "ref": sheet["manifest_ref"], "hash": sheet["manifest_hash"]}
        response = self.reviewer.post(f"/api/sheets/{sheet['sheet_id']}/basic-results", json={"input": link})
        self.assertEqual(response.status_code, 201, response.text)
        return sheet, response.json()

    def edit(self, view, *, status="complete", label="자극에 따라 다름", codes=("개5", "개6"), counter=(), key="entry"):
        return {"expected_revision": view["document"]["revision"], "reason": "영상 근거와 실제 기회 검토",
                "decisions": [{"key": key, "label": label, "status": status, "evidence_codes": list(codes), "counter_codes": list(counter),
                               "counter_note": "고정 원본에서 추가 반대 근거 미관찰",
                               "opportunity_note": "실제 입장 자유 이동 관찰", "reason": "음수와 양수 반응을 같은 원본에서 각각 확인"}]}

    def test_pinned_revision_old_source_and_concurrent_sheet_edit(self):
        sheet, view = self.calculated()
        self.assertEqual(view["document"]["calculations"]["entry_label"], "자극에 따라 다름")
        ref = view["document"]["input"]
        sheet = self.save(sheet, [self.observation("개5", 0)])
        current = self.reviewer.get(f"/api/basic-results/{view['document']['result_id']}").json()
        self.assertTrue(current["sheet_changed"])
        self.assertEqual(current["document"]["input"], ref)
        self.assertEqual(current["document"]["calculations"]["raw_observations"][0]["value"], -1)
        real_calculate = judgements.calculate
        def concurrent(doc, **kwargs):
            self.save(sheet, [self.observation("개5", -2)])
            return real_calculate(doc, **kwargs)
        with patch("app.judgements.calculate", side_effect=concurrent):
            response = self.reviewer.post(f"/api/sheets/{sheet['sheet_id']}/basic-results", json={"input": ref})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertTrue(response.json()["sheet_changed"])
        self.assertEqual(response.json()["document"]["input"], ref)
        wrong = {**ref, "hash": "0" * 64}
        self.assertEqual(self.reviewer.post(f"/api/sheets/{sheet['sheet_id']}/basic-results", json={"input": wrong}).status_code, 409)

    def test_own_permissions_revision_conflict_history_and_completed_hold(self):
        sheet, view = self.calculated()
        path = f"/api/basic-results/{view['document']['result_id']}"
        for other in (self.client, self.other):
            self.assertEqual(other.get(path).status_code, 403)
            self.assertEqual(other.get(f"/api/sheets/{sheet['sheet_id']}/basic-results").status_code, 403)
            self.assertEqual(other.put(path + "/decisions", json=self.edit(view)).status_code, 403)
        response = self.reviewer.put(path + "/decisions", json=self.edit(view))
        self.assertEqual(response.status_code, 200, response.text)
        completed = response.json()
        self.assertEqual(completed["document"]["decisions"][2]["status"], "complete")
        self.assertEqual(completed["document"]["decision_sources"]["entry"], "human")
        self.assertEqual(completed["document"]["calculations"], view["document"]["calculations"])
        self.assertEqual(self.reviewer.put(path + "/decisions", json=self.edit(view)).status_code, 409)
        held = self.reviewer.put(path + "/decisions", json=self.edit(completed, status="held", label=None, codes=())).json()
        self.assertEqual(held["document"]["decisions"][2]["status"], "held")
        old = self.reviewer.get(path + "/revisions/2").json()
        self.assertEqual(old["document"]["decisions"][2]["status"], "complete")
        self.assertEqual(self.reviewer.get(path + "/revisions/999").status_code, 404)
        for invalid in (self.edit(held, label="임의성격"), self.edit(held, codes=("개60",)), self.edit(held, codes=("개5",), counter=("개5",)), self.edit(held, label="판단보류", status="held")):
            self.assertEqual(self.reviewer.put(path + "/decisions", json=invalid).status_code, 422)
        unreviewed = self.edit(held)
        unreviewed["decisions"][0]["counter_note"] = None
        self.assertEqual(self.reviewer.put(path + "/decisions", json=unreviewed).status_code, 422)
        cancelled = self.client.patch(f"/api/sheets/{sheet['sheet_id']}/assignment", json={"expected_revision": sheet["revision"], "reason": "취소", "active": False})
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(self.reviewer.get(path).status_code, 403)

    def test_audio_selected_camera_loss_and_actual_denominator(self):
        raw = self.observation("개11", 1)
        raw["evidence"][0].update(window_id="alone", start_seconds=20, end_seconds=21)
        raw["vocalization"] = {"video_id": self.video["video_id"], "listened_seconds": 10, "cumulative_vocal_seconds": 3,
                               "whole_interval_judged": True, "note": "실제 분리10초 청취·발성3초"}
        sheet = self.save(self.assign(), [raw])
        metadata = {"duration_sec": 100., "width": 96, "height": 64, "fps": "12/1", "audio_ranges": [{"start_sec": 0., "end_sec": 100., "basis": "stream_metadata"}], "audio_status": "present"}
        with patch("app.judgements.probe", return_value=metadata):
            _, view = self.calculated(sheet)
        vocal = next(item for item in view["document"]["calculations"]["vocalizations"] if item["code"] == "개11")
        self.assertEqual(vocal["result"]["value"], 1)
        self.assertEqual(vocal["actual_interval_seconds"], 10)
        self.assertIn(self.video["video_id"], view["document"]["audio_sources"])
        doc = sheets.read_document(self.store, sheet["manifest_ref"], sheet["manifest_hash"])
        changed = doc.model_dump(mode="json")
        changed["source"]["session"]["recording"]["events"] = [{"event_id": "lost", "kind": "audio_loss", "video_id": self.video["video_id"], "segment": "alone", "seconds": 25., "end_seconds": 27., "note": "합성 음성 손실"}]
        changed["source_hash"] = hashlib.sha256(sheets.encode(changed["source"]).encode()).hexdigest()
        changed = type(doc).model_validate_json(json.dumps(changed))
        with patch("app.judgements.probe", return_value=metadata):
            amount, _ = judgements.audio_amounts(self.store, changed)
        self.assertEqual(amount["개11"], 8)
        self.assertEqual(calculate(changed, audio_available=amount).vocalizations[1].result.status, "missing")
        for loss_start, expected in ((25., 5), (31., 10)):
            unbounded = changed.model_dump(mode="json")
            unbounded["source"]["session"]["recording"]["events"][0].update(segment="alone" if loss_start == 25 else "reunion", seconds=loss_start, end_seconds=None)
            unbounded["source_hash"] = hashlib.sha256(sheets.encode(unbounded["source"]).encode()).hexdigest()
            unbounded = type(doc).model_validate_json(json.dumps(unbounded))
            with patch("app.judgements.probe", return_value=metadata):
                amount, _ = judgements.audio_amounts(self.store, unbounded)
            self.assertEqual(amount["개11"], expected)

    def test_candidate_adoption_deleted_case_never_published(self):
        sheet, view = self.calculated()
        write = judgements.write_result
        def deleted(store, data):
            ref = write(store, data)
            with store.connect(write=True) as db:
                db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (self.item["case_id"],))
            return ref
        with patch("app.judgements.write_result", side_effect=deleted):
            response = self.reviewer.put(f"/api/basic-results/{view['document']['result_id']}/decisions", json=self.edit(view))
        self.assertEqual(response.status_code, 403)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT revision FROM basic_results").fetchone()[0], 1)

    def test_exposed_judgement_and_old_input_cannot_become_independent_again(self):
        one, original = self.calculated()
        one = self.submit(one)
        two = self.submit(self.assign("reviewer2", source=one["sheet_id"]), self.other)
        with self.store.connect(write=True) as db:
            row = sheets.row_for(self.store, db, two["sheet_id"])
            data = sheets.document_for(self.store, row).model_dump(mode="json")
            data["sheet"]["rater_kind"] = "ai"
            data["revision"] += 1
            data["previous"].append(sheets.reference(row))
            ref, digest = sheets.write_document(self.store, data)
            db.execute("UPDATE score_sheets SET revision=?,manifest_ref=?,manifest_hash=? WHERE sheet_id=?", (data["revision"], ref, digest, two["sheet_id"]))
            two.update(revision=data["revision"], manifest_ref=ref, manifest_hash=digest)
        # Completed AI raw/automatic basic calculations are allowed, human impersonation is not.
        ai_link = {"sheet_id": two["sheet_id"], "revision": two["revision"], "ref": two["manifest_ref"], "hash": two["manifest_hash"]}
        ai = self.other.post(f"/api/sheets/{two['sheet_id']}/basic-results", json={"input": ai_link})
        self.assertEqual(ai.status_code, 201, ai.text)
        self.assertEqual(self.other.put(f"/api/basic-results/{ai.json()['document']['result_id']}/decisions", json=self.edit(ai.json(), status="held", label=None, codes=())).status_code, 403)
        path = f"/api/sheets/{one['sheet_id']}"
        self.assertEqual(self.client.post(path + "/grants", json={"expected_revision": one["revision"], "target_sheet_id": two["sheet_id"], "target_revision": two["revision"], "reason": "AI 원본 공개"}).status_code, 200)
        def reveal():
            response = self.reviewer.post(path + "/reveal", json={"expected_revision": one["revision"], "ref": two["manifest_ref"]})
            self.assertEqual(response.status_code, 200, response.text)
        real_write = judgements.write_result
        def exposed(store, data):
            output = real_write(store, data)
            reveal()
            return output
        with patch("app.judgements.write_result", side_effect=exposed):
            conflict = self.reviewer.put(f"/api/basic-results/{original['document']['result_id']}/decisions", json=self.edit(original))
        self.assertEqual(conflict.status_code, 409, conflict.text)
        revised = self.reviewer.put(f"/api/basic-results/{original['document']['result_id']}/decisions", json=self.edit(original))
        self.assertEqual(revised.status_code, 200, revised.text)
        context = revised.json()["document"]["evaluation_context"]
        self.assertEqual(context["purpose"], "review")
        self.assertTrue(context["ai_exposed"])
        self.assertEqual(context["exposures"][0]["ref"], two["manifest_ref"])
        previous = self.reviewer.get(f"/api/basic-results/{original['document']['result_id']}/revisions/1").json()
        self.assertEqual(previous["document"]["evaluation_context"]["purpose"], "independent")

    def test_corrupt_pinned_result_or_sheet_never_returns_values(self):
        sheet, result = self.calculated()
        path = f"/api/basic-results/{result['document']['result_id']}"
        result_path = self.store.path(result["summary"]["manifest_ref"])
        original = result_path.read_bytes()
        result_path.write_bytes(b"corrupt")
        self.assertEqual(self.reviewer.get(path).status_code, 409)
        result_path.write_bytes(original)
        self.store.path(sheet["manifest_ref"]).write_bytes(b"corrupt input")
        self.assertEqual(self.reviewer.get(path).status_code, 409)
        self.assertEqual(self.reviewer.put(path + "/decisions", json=self.edit(result)).status_code, 409)

    def test_backup_restore_references_history_and_purge(self):
        sheet, view = self.calculated()
        path = f"/api/basic-results/{view['document']['result_id']}"
        revised = self.reviewer.put(path + "/decisions", json=self.edit(view))
        self.assertEqual(revised.status_code, 200)
        with self.store.connect() as db:
            refs = maintenance.references(self.store, db)
        self.assertIn(view["summary"]["manifest_ref"], refs)
        self.assertIn(revised.json()["summary"]["manifest_ref"], refs)
        self.assertIn(sheet["manifest_ref"], refs)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            maintenance.backup(self.store, root / "backup", "admin")
            maintenance.restore(self.store, root / "backup", root / "restored")
            recovered = Store(root / "restored")
            with recovered.connect() as db:
                refs = maintenance.references(recovered, db)
                self.assertEqual(db.execute("SELECT revision FROM basic_results").fetchone()[0], 2)
                self.assertIn(view["summary"]["manifest_ref"], refs)
        with self.store.connect(write=True) as db:
            db.execute("UPDATE cases SET deletion_requested=1 WHERE case_id=?", (self.item["case_id"],))
        maintenance.clean(self.store, purge_deleted=True)
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM basic_results").fetchone()[0], 0)
        self.assertFalse(self.store.path(view["summary"]["manifest_ref"]).exists())

    def test_shared_attachment_completeness_ai_and_single_behavior_rejection(self):
        source = fixture({"개21": 0, "개18": 0, "개58": 0, "개13": 0, "개14": 0}, rater_kind="ai",
                         events=[event("stranger_gate_wait", 198., "stranger"), event("stranger_enter", 208., "stranger")])
        ref = {"sheet_id": "sheet1", "revision": 1, "ref": "sheets/fixture.json", "hash": "c" * 64}
        result = BasicResultV3.model_validate_json(json.dumps({"result_id": "result1", "case_id": "case1", "session_id": "session1", "revision": 1,
            "actor": "reviewer", "recorded_at": "2026-10-01", "change_reason": "합성 AI 검증", "input": ref, "input_document": source.model_dump(mode="json"),
            "rule_version": RULE_VERSION, "rule_hash": RULE_HASH, "evaluation_context": {"purpose": "independent", "ai_exposed": False, "exposures": []},
            "calculations": calculate(source).model_dump(mode="json"), "decisions": [], "decision_sources": {}}))
        evidence = {item.code: item.evidence for item in source.sheet.observations}
        self.assertTrue(all(evidence[code] and evidence[code][0].observed_seconds > 0 for code in ("개13", "개14")))
        data = {"key": "attachment", "label": "곁에서 안심하는 사이", "status": "complete", "evidence_codes": ["개21"], "evidence": [item.model_dump(mode="json") for item in evidence["개21"]],
                "counter_evidence": [], "counter_note": "별도 반대 행동 미관찰", "opportunity_note": "실제 접근과 몸 상태 관찰", "reason": "다중 근거 검토", "rater_id": "rater1", "recorded_at": "2026-10-01",
                "input_sheet_id": "sheet1", "input_revision": 1, "input_sha256": "c" * 64, "rule_version": RULE_VERSION}
        with self.assertRaises(ValueError):
            judgements.validate_judgement(DecisionV3.model_validate_json(json.dumps(data)), result)
        data["evidence_codes"] = ["개21", "개18", "개58"]
        data["evidence"] = [item.model_dump(mode="json") for code in data["evidence_codes"] for item in evidence[code]]
        data["counter_evidence"] = []
        zero_source = source.model_dump(mode="json")
        for raw in zero_source["sheet"]["observations"]:
            if raw["code"] in ("개18", "개58"):
                for basis in raw["evidence"]:
                    basis.update(end_seconds=basis["start_seconds"], observed_seconds=0.)
        zero_source = type(source).model_validate_json(json.dumps(zero_source))
        zero_result = result.model_dump(mode="json")
        zero_result.update(input_document=zero_source.model_dump(mode="json"), calculations=calculate(zero_source).model_dump(mode="json"))
        zero_result = BasicResultV3.model_validate_json(json.dumps(zero_result))
        for basis in data["evidence"][1:]:
            basis.update(end_seconds=basis["start_seconds"], observed_seconds=0.)
        with self.assertRaises(ValueError):
            judgements.validate_judgement(DecisionV3.model_validate_json(json.dumps(data)), zero_result)
        data["evidence_codes"] = ["개21", "개18", "개58"]
        data["evidence"] = [item.model_dump(mode="json") for code in data["evidence_codes"] for item in evidence[code]]
        self.assertEqual(judgements.validate_judgement(DecisionV3.model_validate_json(json.dumps(data)), result).status, "complete")
        data["evidence"] = [item.model_dump(mode="json") for item in evidence["개21"]]
        data["counter_evidence"] = [item.model_dump(mode="json") for item in evidence["개18"]]
        with self.assertRaises(ValueError):
            judgements.validate_judgement(DecisionV3.model_validate_json(json.dumps(data)), result)
        data["evidence_codes"] = ["개13", "개14"]
        data["evidence"] = [item.model_dump(mode="json") for code in ("개13", "개14") for item in evidence[code]]
        data["counter_evidence"] = []
        with self.assertRaises(ValueError):
            judgements.validate_judgement(DecisionV3.model_validate_json(json.dumps(data)), result)

    def test_cold_review_owner_completion_never_uses_excluded_post_stop_evidence(self):
        record = self.item["manifest"]["sessions"][0]["recording"]
        record["events"] = [{"event_id": "object", "kind": "object_stop", "video_id": self.video["video_id"], "segment": "entry", "seconds": 2., "end_seconds": 3., "note": "물건 실제 정지"},
                            {"event_id": "stop", "kind": "welfare_stop", "video_id": self.video["video_id"], "segment": "entry", "seconds": 5., "note": "복지 중단"}]
        response = self.client.put(self.base + "/recording", json={"expected_revision": self.item["input_revision"], "recording": record, "confirm": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.item = response.json()
        raw = self.observation("보6", -2)
        raw["evidence"][0]["window_id"] = "entry_leash"
        raw["evidence"].append({**raw["evidence"][0], "start_seconds": 6., "end_seconds": 7.})
        sheet = self.save(self.assign(), [raw])
        _, result = self.calculated(sheet)
        owner = result["document"]["calculations"]["owner"]["items"][0]
        self.assertEqual(len(owner["used_evidence"]), 1)
        self.assertEqual(len(owner["excluded_evidence"]), 1)
        complete = self.edit(result, label="허용형", codes=("보6",), key="owner_type")
        response = self.reviewer.put(f"/api/basic-results/{result['document']['result_id']}/decisions", json=complete)
        self.assertEqual(response.status_code, 200, response.text)
        decision = response.json()["document"]["decisions"][1]
        self.assertEqual(len(decision["evidence"]), 1)
        self.assertEqual(decision["evidence"][0]["start_seconds"], 0.)
        # The same gate protects provider decisions that explicitly submit only the excluded interval.
        decision["evidence"] = [owner["excluded_evidence"][0]["evidence"]]
        model = BasicResultV3.model_validate_json(json.dumps(result["document"]))
        with self.assertRaises(ValueError):
            judgements.validate_judgement(DecisionV3.model_validate_json(json.dumps(decision)), model)

    def test_explicit_invalid_ignore_is_local_not_whole_attachment(self):
        source = fixture({"개9": 0, "개21": 0, "개23": 0, "개58": 0, "보12": 3})
        ref = {"sheet_id": "sheet1", "revision": 1, "ref": "sheets/fixture.json", "hash": "c" * 64}
        model = BasicResultV3.model_validate_json(json.dumps({"result_id": "result1", "case_id": "case1", "session_id": "session1", "revision": 1,
            "actor": "reviewer", "recorded_at": "2026-10-01", "change_reason": "무시 시행 무효와 다른 유효 근거",
            "input": ref, "input_document": source.model_dump(mode="json"), "rule_version": RULE_VERSION, "rule_hash": RULE_HASH,
            "evaluation_context": {"purpose": "independent", "ai_exposed": False, "exposures": []},
            "calculations": calculate(source).model_dump(mode="json"), "decisions": [], "decision_sources": {}}))
        for codes, valid in ((("개9", "개21", "개23"), False), (("개9", "개21", "개58"), True)):
            decision = DecisionV3.model_validate_json(json.dumps({"key": "attachment", "label": "곁에서 안심하는 사이", "status": "complete",
                "evidence_codes": codes, "evidence": [basis.model_dump(mode="json") for item in source.sheet.observations if item.code in codes for basis in item.evidence],
                "counter_note": "별도 반대 근거 미관찰", "opportunity_note": "실제 분리·재회 관찰, 무시 시행은 별도 무효",
                "reason": "다른 장면의 다중 근거 검토", "rater_id": "rater1", "recorded_at": "2026-10-01", "input_sheet_id": "sheet1", "input_revision": 1, "input_sha256": "c" * 64, "rule_version": RULE_VERSION}))
            if valid:
                self.assertEqual(judgements.validate_judgement(decision, model).status, "complete")
            else:
                with self.assertRaises(ValueError):
                    judgements.validate_judgement(decision, model)


def load_tests(loader, tests, pattern):
    # Inherit the existing source setup without re-running its unrelated C05 test methods.
    return unittest.TestSuite(JudgementTests(name) for name in JudgementTests.__dict__ if name.startswith("test_"))
