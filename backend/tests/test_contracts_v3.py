import json
import unittest

from pydantic import ValidationError

from app.domain.catalog_v3 import BehaviorCatalogV3, ProtocolV3
from app.domain.contracts_v3 import DecisionV3, DerivedValueV3, ScoreSheetV3
from app.domain.validation_v3 import validate_decision_v3, validate_derived_v3, validate_sheet_v3
from app.import_catalogs_v3 import ROOT


class ContractsV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BehaviorCatalogV3.model_validate_json((ROOT / "resources/catalogs/behavior-v3.json").read_text(encoding="utf-8"))
        cls.protocol = ProtocolV3.model_validate_json((ROOT / "resources/rules/protocol-v3.json").read_text(encoding="utf-8"))

    def sheet(self, observations, **overrides):
        data = {"sheet_id": "sheet1", "case_id": "case1", "session_id": "session1", "rater_id": "rater1",
                "rater_kind": "human", "observations": observations, **overrides}
        return ScoreSheetV3.model_validate_json(json.dumps(data))

    def validate(self, observations, **overrides):
        return validate_sheet_v3(self.sheet(observations, **overrides), self.catalog, self.protocol)

    def test_zero_signed_values_counts_and_memos(self):
        for code, value in (("바5", -2), ("개7", 0), ("보5", -1), ("보12", 3), ("개16", 4),
                            ("바14", 0), ("바14", 9999), ("보25", "관찰 사유와 실제 시각")):
            with self.subTest(code=code, value=value):
                result = self.validate([{"code": code, "value": value, "status": "observed"}])
                self.assertEqual(result.observations[0].value, value)

    def test_invalid_values_are_rejected(self):
        for code, value in (("바5", True), ("바5", -3), ("개7", 2), ("보5", -2), ("보12", 0),
                            ("개16", 5), ("바14", -1), ("바14", 0.5), ("바14", 10000),
                            ("보25", " "), ("개32", float("nan")), ("바5", float("inf")),
                            ("바5", "0"), ("바14", False), ("개32", True)):
            with self.subTest(code=code, value=value):
                with self.assertRaises((ValueError, ValidationError)):
                    self.validate([{"code": code, "value": value, "status": "observed"}])

    def test_unused_auto_unknown_and_duplicate_are_rejected(self):
        for code in ("개20", "개31", "개33", "개35", "개26", "개27", "개36", "개60", "보7", "바46", "DOG-17"):
            with self.subTest(code=code):
                with self.assertRaises(ValueError):
                    self.validate([{"code": code, "value": 0, "status": "observed"}])
        item = {"code": "바5", "value": 0, "status": "observed"}
        with self.assertRaises(ValueError):
            self.validate([item, item])

    def test_missing_states_require_reason_and_preserve_separate_conditions(self):
        for status in ("unobserved", "no_opportunity", "not_performed"):
            data = {"code": "바5", "value": None, "status": status,
                    "opportunity": "absent" if status == "no_opportunity" else "unknown"}
            with self.assertRaises(ValueError):
                self.validate([data])
            result = self.validate([{**data, "reason": "미관찰 사유", "validity": "invalid", "welfare_stopped": True}])
            self.assertIsNone(result.observations[0].value)
            with self.assertRaises(ValueError):
                self.validate([{**data, "reason": "미관찰 사유", "value": 0}])
        with self.assertRaises(ValueError):
            self.validate([{"code": "바5", "value": None, "status": "observed"}])

    def test_latency_sentinel_is_not_actual_seconds_and_decimals_are_preserved(self):
        data = {"code": "개32", "value": 99, "status": "observed"}
        with self.assertRaises(ValueError):
            self.validate([data])
        result = self.validate([{**data, "latency_not_occurred": True}])
        self.assertIsNone(result.observations[0].actual_latency_seconds)
        with self.assertRaises(ValueError):
            self.validate([{**data, "latency_not_occurred": True, "actual_latency_seconds": 99}])
        result = self.validate([{**data, "value": 2.25, "actual_latency_seconds": 2.25}])
        self.assertEqual(result.observations[0].value, 2.25)

    def test_evidence_references_and_time_ranges(self):
        evidence = {"video_id": "video1", "video_sha256": "a" * 64, "window_id": "entry",
                    "start_seconds": 5, "end_seconds": 10, "observed_seconds": 4, "note": "시각 근거"}
        self.validate([{"code": "바5", "value": 0, "status": "observed", "evidence": [evidence]}])
        for change in ({"window_id": "no_such_window"}, {"window_id": "alone"}, {"end_seconds": 4},
                       {"observed_seconds": 6}):
            with self.assertRaises(ValueError):
                self.validate([{"code": "바5", "value": 0, "status": "observed", "evidence": [{**evidence, **change}]}])

    def test_old_versions_cannot_enter_v3(self):
        for overrides in ({"schema_version": "2.0"}, {"catalog_version": "catalog-20260913-v2"},
                          {"protocol_version": "protocol-20260913-v2"}):
            with self.assertRaises(ValueError):
                self.validate([], **overrides)

    def test_derived_missing_and_held_decisions_cannot_claim_values(self):
        DerivedValueV3(key="body_change", value=0, status="calculated", input_codes=("개58", "개18"))
        with self.assertRaises(ValueError):
            DerivedValueV3(key="body_change", value=0, status="missing", reason="누락", input_codes=("개58", "개18"))
        with self.assertRaises(ValueError):
            DerivedValueV3(key="body_change", value=None, status="invalid", input_codes=("개58", "개18"))

    def test_derived_and_decision_references_are_catalog_validated(self):
        with self.assertRaises(ValueError):
            DerivedValueV3(key="body_change", value=0, status="calculated", input_codes=("개999",))
        derived = DerivedValueV3(key="body_change", value=0, status="calculated", input_codes=("개20",))
        with self.assertRaises(ValueError):
            validate_derived_v3(derived, self.catalog)
        data = {"key": "attachment", "label": "곁에서 안심하는 사이", "status": "complete",
                "evidence_codes": ["개17"], "evidence": [{"video_id": "video1", "video_sha256": "a" * 64,
                "window_id": "reunion_first", "start_seconds": 0, "end_seconds": 15,
                "observed_seconds": 15, "note": "접근 근거"}], "opportunity_note": "실제 재회",
                "reason": "접근 장면", "rater_id": "rater1", "recorded_at": "2026-10-01T00:00:00+09:00",
                "input_sheet_id": "sheet1", "input_revision": 1, "input_sha256": "a" * 64,
                "rule_version": "scoring-20260929-v3"}
        validate_decision_v3(DecisionV3.model_validate_json(json.dumps(data)), self.catalog, self.protocol)
        for window in ("no_such_window", "alone"):
            changed = json.loads(json.dumps(data))
            changed["evidence"][0]["window_id"] = window
            with self.assertRaises(ValueError):
                validate_decision_v3(DecisionV3.model_validate_json(json.dumps(changed)), self.catalog, self.protocol)
        changed = {**data, "evidence_codes": ["보7"]}
        with self.assertRaises(ValueError):
            DecisionV3.model_validate_json(json.dumps(changed))


if __name__ == "__main__":
    unittest.main()
