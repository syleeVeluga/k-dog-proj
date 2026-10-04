import json
import unittest

from pydantic import ValidationError

from app.domain.catalog_v4 import AUTO_CODES, load_catalog_v4
from app.domain.contracts_v4 import (DecisionV4, DerivedValueV4, EvidenceV4, LinkedMemoV4,
                                    ObservationV4, ScoreSheetV4, VocalizationV4, WalkPhaseV4)
from app.domain.validation_v4 import validate_sheet_v4


def evidence(window="entry_whole", duration=30.0):
    return EvidenceV4(video_id="synthetic_video", video_sha256="a" * 64, camera_id="CAM1",
                      window_id=window, start_seconds=0.0, end_seconds=duration,
                      observed_seconds=duration, note="합성 관찰 근거")


def observation(code="개5", value=0, window="entry_whole", **changes):
    data = dict(code=code, value=value, status="observed", validity="valid",
                evidence=(evidence(window),), **changes)
    return ObservationV4(**data)


def sheet(*observations, **changes):
    return ScoreSheetV4(sheet_id="synthetic_sheet", case_id="synthetic_case", session_id="synthetic_session",
                        batch_id="synthetic_batch", rater_id="synthetic_rater", rater_kind="human",
                        input_revision=1, input_sha256="b" * 64, observations=observations, **changes)


class ContractsV4Tests(unittest.TestCase):
    def test_zero_is_valid_and_null_is_not_zero(self):
        self.assertEqual(validate_sheet_v4(sheet(observation())).observations[0].value, 0)
        with self.assertRaises(ValidationError):
            observation(value=None)
        missing = ObservationV4(code="개5", value=None, status="unobserved", reason="아직 관찰하지 않음")
        self.assertIsNone(validate_sheet_v4(sheet(missing)).observations[0].value)

    def test_nonobserved_states_preserve_reason(self):
        for status in ("unobserved", "not_performed", "insufficient_observation", "policy_pending"):
            with self.subTest(status=status):
                self.assertEqual(ObservationV4(code="개5", value=None, status=status, reason="합성 사유").status, status)
                with self.assertRaises(ValidationError):
                    ObservationV4(code="개5", value=0, status=status, reason="합성 사유")
        with self.assertRaises(ValidationError):
            ObservationV4(code="개5", value=None, status="unobserved")

    def test_no_opportunity_and_invalid_are_distinct(self):
        absent = ObservationV4(code="개19", value=None, status="no_opportunity", opportunity="absent", reason="미접촉")
        invalid = ObservationV4(code="개23", value=None, status="invalid", validity="invalid", reason="조건 이탈")
        self.assertNotEqual(absent.status, invalid.status)
        with self.assertRaises(ValidationError):
            ObservationV4(code="개19", value=None, status="no_opportunity", reason="기회 미확인")

    def test_old_codes_auto_input_boolean_text_float_rejected(self):
        for code in (*AUTO_CODES, "개59", "개94", "개32", "바5"):
            with self.subTest(code=code), self.assertRaises(ValidationError):
                observation(code=code)
        for value in (True, False, "0", 0.0, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                observation(value=value)

    def test_catalog_range_including_unused_signed_request(self):
        for code, value, window in (("보5", 2, "entry_free"), ("보5", -2, "entry_free"),
                                     ("환경1", 4, "baseline_whole"), ("개8", -1, "baseline_whole"),
                                     ("개30", -1, "entry_object"), ("바54", 2, "reunion_tail_event")):
            with self.subTest(code=code), self.assertRaises(ValueError):
                validate_sheet_v4(sheet(observation(code, value, window, whole_interval_observed=True)))

    def test_count_is_nonnegative_and_partial_observation_cannot_be_zero(self):
        with self.assertRaises(ValidationError):
            observation("바46", -1)
        with self.assertRaisesRegex(ValueError, "whole-interval"):
            validate_sheet_v4(sheet(observation("바46", 0)))
        self.assertEqual(validate_sheet_v4(sheet(observation("바46", 0, whole_interval_observed=True))).observations[0].value, 0)

    def test_exploration_requires_whole_interval_and_unknown_is_null(self):
        with self.assertRaisesRegex(ValueError, "whole-interval"):
            validate_sheet_v4(sheet(observation("개8", 0, "baseline_whole")))
        validate_sheet_v4(sheet(observation("개8", 0, "baseline_whole", whole_interval_observed=True)))

    def test_late_separation_needs_whole_window(self):
        with self.assertRaisesRegex(ValueError, "whole-interval"):
            validate_sheet_v4(sheet(observation("개10", 1, "alone_later")))
        validate_sheet_v4(sheet(observation("개10", 1, "alone_later", whole_interval_observed=True)))

    def test_departure_and_avoidance_evidence_use_the_source_events(self):
        validate_sheet_v4(sheet(observation("보10", 0, "separation_departure")))
        with self.assertRaisesRegex(ValueError, "another observation window"):
            validate_sheet_v4(sheet(observation("보10", 0, "alone_whole")))
        # Moving a hand away following avoidance can occur before actual contact.
        validate_sheet_v4(sheet(observation("보22", -1, "reunion_later")))

    def test_voice_ratio_boundary_and_actual_listening(self):
        for amount, value in ((0.0, 0), (20.0, 1), (40.0, 2), (40.1, 3)):
            item = observation("개11", value, "alone_whole", vocalization=VocalizationV4(
                listened_seconds=60.0, cumulative_vocal_seconds=amount, whole_interval_judged=True, note="합성 음성"))
            validate_sheet_v4(sheet(item))
        with self.assertRaisesRegex(ValueError, "ratio"):
            validate_sheet_v4(sheet(observation("개11", 3, "alone_whole", vocalization=VocalizationV4(
                listened_seconds=60.0, cumulative_vocal_seconds=40.0, whole_interval_judged=True, note="합성 음성"))))

    def test_evidence_order_and_item_window(self):
        with self.assertRaises(ValidationError):
            EvidenceV4(video_id="demo", video_sha256="a" * 64, camera_id="CAM1", window_id="entry_whole",
                       start_seconds=5.0, end_seconds=4.0, observed_seconds=0.0, note="합성")
        with self.assertRaisesRegex(ValueError, "another observation window"):
            validate_sheet_v4(sheet(observation("개5", 0, "alone_initial")))
        with self.assertRaisesRegex(ValueError, "source evidence"):
            validate_sheet_v4(sheet(ObservationV4(code="개5", value=0, status="observed", validity="valid")))

    def test_memos_and_walking_metadata_do_not_expand_active_catalog(self):
        memo = ObservationV4(code="보25", value="접근과 대응 시각 기록", status="observed", validity="valid")
        result = sheet(memo, linked_memos=(LinkedMemoV4(text="사건 종합 메모", item_codes=("보5",)),),
                       walk_phases=(WalkPhaseV4(code="개38", proximity_exception="guardian_approach"),))
        validate_sheet_v4(result)
        self.assertEqual(result.linked_memos[0].code, "개59")
        self.assertEqual(len(load_catalog_v4().items), 90)

    def test_duplicate_rows_and_mixed_versions_rejected(self):
        with self.assertRaises(ValidationError):
            sheet(observation(), observation())
        payload = sheet(observation()).model_dump(mode="json")
        for key, value in (("catalog_version", "catalog-20260929-v3"), ("schema_version", "3.0"),
                           ("protocol_version", "protocol-20260929-v3")):
            changed = {**payload, key: value}
            with self.subTest(key=key), self.assertRaises(ValidationError):
                ScoreSheetV4.model_validate_json(json.dumps(changed))

    def test_decision_names_and_holds_are_strict(self):
        data = dict(key="attachment_type", label="곁에서 안심하는 사이", status="complete",
                    evidence_codes=("개17",), evidence=(evidence("reunion_approach"),), reason="합성 근거",
                    rater_id="rater", input_sheet_id="sheet", input_revision=1, input_sha256="a" * 64)
        DecisionV4(**data)
        for label in ("찾고, 차분히 재회", "판정보류", "안정형"):
            with self.subTest(label=label), self.assertRaises(ValidationError):
                DecisionV4(**{**data, "label": label})
        DecisionV4(**{**data, "label": None, "status": "held"})

    def test_retired_derived_results_and_false_missing_zero_rejected(self):
        for key in ("V", "AW", "AY", "개32"):
            with self.subTest(key=key), self.assertRaises(ValidationError):
                DerivedValueV4(key=key, value=0, status="calculated", input_codes=("개8",))
        with self.assertRaises(ValidationError):
            DerivedValueV4(key="W", value=0, status="missing", reason="자료 부족", input_codes=("개58", "개18"))


if __name__ == "__main__":
    unittest.main()
