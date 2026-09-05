import copy
import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from app.domain.contracts import (
    BEHAVIOR_IDS, BehaviorCatalog, BranchEvaluation, DomainScore, Evidence,
    ItemEvaluation, ItemScore, ReportResult, RunInput, ScoreResult, SurveyCatalog,
    VideoReference,
)
from app.domain.validation import resolve_branch_scores, validate_evidence, validate_report_evidence

ROOT = Path(__file__).resolve().parents[2]


def parse(model, value):
    return model.model_validate_json(json.dumps(value, ensure_ascii=False))


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads((Path(__file__).parent / "fixtures/contract-case.json").read_text(encoding="utf-8"))
        self.run = parse(RunInput, self.fixture["run"])
        self.evidence = tuple(parse(Evidence, value) for value in self.fixture["evidence"])
        self.catalog = BehaviorCatalog.model_validate_json((ROOT / "resources/catalogs/behavior-v1.json").read_bytes())

    def branch(self, branch="dog", first=None):
        values = [{
            "item_id": item_id, "status": "not_visible", "selected_option_id": None,
            "evidence_ids": [], "reason": "가상 시험: 관찰 없음",
        } for item_id in BEHAVIOR_IDS if item_id.startswith("OWN-") == (branch == "owner")]
        values[0] = first or self.fixture["scored" if branch == "dog" else "missing"]
        return parse(BranchEvaluation, {"run_id": self.run.run_id, "branch": branch, "items": values})

    def report(self):
        return {
            "run_id": self.run.run_id, "report_mapping_version": "pending-v1", "result_revision": 1,
            "cover": {"text": "시험용 요약", "evidence_ids": ["test-ev01"]},
            "domains": [{"slot": number, "status": "mapping_pending", "label": None,
                         "value": None, "comment": "표시 규칙 미정", "evidence_ids": []}
                        for number in range(1, 5)],
            "cross_type": {"status": "type_rule_pending", "rule_id": None, "type_name": None,
                           "explanation": "유형 규칙 미정", "evidence_ids": []},
            "tips": [{"text": "시험용 안내", "evidence_ids": []}],
            "notice": "진단이 아닌 관찰 기반 제안",
        }

    def test_run_round_trip_keeps_leading_zero_and_null_response(self):
        restored = RunInput.model_validate_json(self.run.model_dump_json())
        self.assertEqual(restored.participant_id, "0001")
        self.assertIsNone(restored.survey["q02"])
        self.assertEqual(restored.survey["q23"], 3)
        self.assertEqual(len(restored.videos), 1)  # 2 cameras/3 minutes are planning, not limits.

    def test_wrong_id_type_unknown_fields_and_survey_values_rejected(self):
        for field, value in (("participant_id", 1), ("input_revision", True), ("api_key", "test")):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                parse(RunInput, {**self.fixture["run"], field: value})
        for value in (True, 0, 6, "3", 1.5, float("nan")):
            data = copy.deepcopy(self.fixture["run"])
            data["survey"]["q01"] = value
            with self.subTest(value=value), self.assertRaises(ValidationError):
                parse(RunInput, data)

    def test_survey_requires_all_30_keys(self):
        data = copy.deepcopy(self.fixture["run"])
        del data["survey"]["q30"]
        with self.assertRaises(ValidationError):
            parse(RunInput, data)
        data["survey"]["q31"] = None
        with self.assertRaises(ValidationError):
            parse(RunInput, data)

    def test_duplicate_video_rejected(self):
        data = copy.deepcopy(self.fixture["run"])
        data["videos"] *= 2
        with self.assertRaises(ValidationError):
            parse(RunInput, data)

    def test_invalid_video_paths_hash_duration_and_sync_rejected(self):
        source = self.fixture["run"]["videos"][0]
        for key, value in (("storage_ref", "../secret"), ("storage_ref", "C:/secret"),
                           ("storage_ref", "/absolute"), ("sha256", "example-hash"),
                           ("duration_sec", 0), ("duration_sec", float("inf")),
                           ("sync_offset_sec", 1.0)):
            with self.subTest(key=key, value=value), self.assertRaises(ValidationError):
                parse(VideoReference, {**source, key: value})

    def test_source_time_bounds_and_cross_case_references_rejected(self):
        for key, value in (("case_id", "other"), ("session_id", "other"), ("run_id", "other"),
                           ("video_id", "other"), ("camera_id", "other"), ("source_end_sec", 31.0),
                           ("source_start_sec", 6.0), ("modality", "audio")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                evidence = parse(Evidence, {**self.fixture["evidence"][0], key: value})
                validate_evidence(self.run, (evidence,))

    def test_duplicate_evidence_rejected(self):
        with self.assertRaises(ValueError):
            validate_evidence(self.run, self.evidence * 2)

    def test_branch_requires_exact_item_set(self):
        data = self.branch().model_dump(mode="json")
        for items in (data["items"][:-1], data["items"] + [data["items"][0]]):
            with self.assertRaises(ValidationError):
                parse(BranchEvaluation, {**data, "items": items})
        data["items"][-1]["item_id"] = "OWN-01"
        with self.assertRaises(ValidationError):
            parse(BranchEvaluation, data)

    def test_actual_option_lookup_and_independent_missing_branch(self):
        scores = resolve_branch_scores(self.run, self.branch(), self.catalog, self.evidence)
        self.assertEqual((scores[0].raw_score, scores[0].direction), (2.0, "B"))
        self.assertTrue(all(score.raw_score is None for score in scores[1:]))
        owner = resolve_branch_scores(self.run, self.branch("owner"), self.catalog, ())
        self.assertEqual(len(owner), 19)
        self.assertEqual(owner[0].status, "audio_unusable")
        self.assertIsNone(owner[0].raw_score)

    def test_invented_option_and_unknown_or_unrelated_evidence_rejected(self):
        for key, value in (("selected_option_id", "BS-01:S4"), ("selected_option_id", "DOG-01:S1"),
                           ("evidence_ids", ["unknown"])):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                branch = self.branch(first={**self.fixture["scored"], key: value})
                resolve_branch_scores(self.run, branch, self.catalog, self.evidence)
        unrelated = parse(Evidence, {**self.fixture["evidence"][0], "candidate_item_ids": ["BS-02"]})
        with self.assertRaises(ValueError):
            resolve_branch_scores(self.run, self.branch(), self.catalog, (unrelated,))

    def test_scored_requires_option_and_evidence(self):
        for key, value in (("selected_option_id", None), ("evidence_ids", [])):
            with self.assertRaises(ValidationError):
                parse(ItemEvaluation, {**self.fixture["scored"], key: value})

    def test_missing_and_pending_never_gain_score_or_direction(self):
        for status in ("not_visible", "audio_unusable", "not_performed", "not_applicable",
                       "insufficient_evidence", "conflicting_evidence", "rule_pending"):
            missing = {**self.fixture["missing"], "status": status}
            with self.subTest(status=status):
                parse(ItemEvaluation, missing)
                with self.assertRaises(ValidationError):
                    parse(ItemEvaluation, {**missing, "selected_option_id": "OWN-01:S1"})
                with self.assertRaises(ValidationError):
                    ItemScore(item_id="OWN-01", status=status, raw_score=1.0, direction=None, reason="test")
                scores = resolve_branch_scores(self.run, self.branch("owner", missing), self.catalog, ())
                self.assertIsNone(scores[0].raw_score)
                self.assertIsNone(scores[0].direction)

    def test_test_catalog_requires_explicit_test_mode(self):
        catalog = parse(BehaviorCatalog, {**self.catalog.model_dump(mode="json"), "provenance": "test_fixture"})
        with self.assertRaises(ValueError):
            resolve_branch_scores(self.run, self.branch(), catalog, self.evidence)
        self.assertEqual(len(resolve_branch_scores(self.run, self.branch(), catalog, self.evidence, mode="test")), 36)

    def test_run_and_catalog_version_mismatch_rejected(self):
        data = self.fixture["run"]
        for key in ("run_id", "catalog_version"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                resolve_branch_scores(parse(RunInput, {**data, key: "other"}), self.branch(), self.catalog, self.evidence)

    def test_empty_domain_is_null_and_denominator_valid(self):
        empty = dict(domain="EDU", mean=None, maximum=None, valid_count=0, target_count=7)
        DomainScore(**empty)
        for changes in ({"mean": 0.0}, {"valid_count": 8}, {"valid_count": 1}):
            with self.assertRaises(ValidationError):
                DomainScore(**{**empty, **changes})

    def test_rule_pending_preserves_exact_boundary_observations(self):
        for boundary in (2.0, 5.0, 15.0):
            evidence = parse(Evidence, {**self.fixture["evidence"][0], "source_start_sec": 0.0,
                                      "source_end_sec": boundary, "candidate_item_ids": ["OWN-14"]})
            validate_evidence(self.run, (evidence,))
            item = ItemEvaluation(item_id="OWN-14", status="rule_pending", selected_option_id=None,
                                  evidence_ids=(evidence.evidence_id,), reason="시간 경계·선택 규칙 미정")
            self.assertIsNone(item.selected_option_id)

    def test_pending_report_keeps_four_slots_without_invented_mapping(self):
        report = parse(ReportResult, self.report())
        validate_report_evidence(self.run, report, self.evidence)
        self.assertEqual(len(report.domains), 4)
        self.assertIsNone(report.cross_type.type_name)
        self.assertEqual(ReportResult.model_validate_json(report.model_dump_json()), report)

    def test_invented_report_values_and_references_rejected(self):
        for key, value in (("value", 3), ("label", "임의 영역"), ("slot", 2)):
            data = self.report()
            data["domains"][0][key] = value
            with self.assertRaises(ValidationError):
                parse(ReportResult, data)
        data = self.report()
        data["cover"]["evidence_ids"] = ["other-participant"]
        with self.assertRaises(ValueError):
            validate_report_evidence(self.run, parse(ReportResult, data), self.evidence)

    def test_core_models_generate_json_schema(self):
        for model in (RunInput, VideoReference, Evidence, ItemEvaluation, ScoreResult, ReportResult,
                      BehaviorCatalog, SurveyCatalog, BranchEvaluation):
            with self.subTest(model=model.__name__):
                schema = model.model_json_schema()
                self.assertFalse(schema["additionalProperties"])
                self.assertEqual(json.loads(json.dumps(schema)), schema)


if __name__ == "__main__":
    unittest.main()
