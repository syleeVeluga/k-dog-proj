import json
import unittest
from copy import deepcopy

from pydantic import ValidationError

from app.domain.catalog_v3 import SurveyCatalogV3
from app.domain.catalog_v4 import RESOURCES
from app.input_models_v4 import new_session_v4
from app.survey_v4 import SurveyPolicyV4, load_survey_policy_v4, survey_scores_v4


class SurveyV4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = SurveyCatalogV3.model_validate_json((RESOURCES / "catalogs/survey-v3.json").read_bytes())

    def session(self, **responses):
        session = new_session_v4("synthetic-survey-session")
        session.survey.update(responses)
        return session

    def result(self, **responses):
        return survey_scores_v4(self.session(**responses), self.catalog)

    def domain(self, result, first):
        return next(domain for domain in result.domains if domain.question_ids[0] == first)

    def test_t14_two_fear_means_and_zero_are_source_values(self):
        result = self.result(s10=0, s11=2, s12=0, s13=1, s14=2)
        stranger, nonsocial = (self.domain(result, key) for key in ("s10", "s12"))
        self.assertEqual((stranger.mean, stranger.numerator, stranger.denominator), (1.0, 2, 2))
        self.assertEqual((nonsocial.mean, nonsocial.numerator, nonsocial.denominator), (1.0, 3, 3))
        self.assertEqual(result.items[9].raw, 0)
        self.assertEqual(result.answered_count, 5)
        self.assertEqual(len(result.domains), 8)

    def test_every_fear_missing_position_holds_only_its_group(self):
        answers = dict(s10=0, s11=2, s12=0, s13=1, s14=2)
        for question in answers:
            with self.subTest(question=question):
                sample = {**answers, question: None}
                result = self.result(**sample)
                missing = self.domain(result, "s10" if question in ("s10", "s11") else "s12")
                other = self.domain(result, "s12" if question in ("s10", "s11") else "s10")
                self.assertEqual((missing.mean, missing.numerator, missing.denominator), (None, None, None))
                self.assertEqual(missing.status, "insufficient_responses")
                self.assertEqual(missing.missing_question_ids, (question,))
                self.assertEqual(other.mean, 1.0)
                self.assertTrue(other.same_edition_value_available)

    def test_t25_nonfear_partial_policy_does_not_block_complete_fear(self):
        result = self.result(s01=5, s07=1, s15=2, s22=3, s26=1, s10=0, s11=2)
        for first in ("s01", "s07", "s15", "s22", "s26"):
            domain = self.domain(result, first)
            self.assertEqual(domain.status, "policy_pending")
            self.assertIn("D05", domain.reason)
            self.assertIsNone(domain.denominator)
            self.assertIsNone(domain.mean)
        self.assertEqual(self.domain(result, "s10").mean, 1.0)
        self.assertEqual(result.calculation_status, "partial")

    def test_complete_groups_are_independent_of_missing_other_domains(self):
        answers = {f"s{n:02}": 3 for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 15, 16, 17, 18, 19, 20, 21, 22, 23)}
        result = self.result(**answers)
        for first, denominator in (("s01", 6), ("s07", 3), ("s15", 7), ("s22", 2)):
            domain = self.domain(result, first)
            self.assertEqual((domain.mean, domain.denominator, domain.status), (3.0, denominator, "calculated"))
        self.assertEqual(self.domain(result, "s10").status, "missing")

    def test_q24_and_q25_stay_separate_raw_single_values(self):
        result = self.result(s24=5, s25=1)
        reunion = self.domain(result, "s24")
        self.assertEqual((reunion.aggregation, reunion.mean, reunion.denominator), ("single_raw", 5.0, 1))
        self.assertEqual((result.standalone.raw, result.standalone.converted, result.standalone.conversion), (1, 1, "identity"))
        self.assertFalse(any("s25" in domain.question_ids for domain in result.domains))
        absent = self.result(s25=1)
        self.assertEqual(self.domain(absent, "s24").status, "missing")
        self.assertEqual(absent.standalone.raw, 1)

    def test_reverse_scoring_preserves_raw_and_metadata_without_mutating_input(self):
        session = self.session(s26=1, s27=3, s28=5)
        before = session.model_dump_json()
        result = survey_scores_v4(session, self.catalog)
        self.assertEqual([item.raw for item in result.items[25:]], [1, 3, 5])
        self.assertEqual([item.converted for item in result.items[25:]], [5, 3, 1])
        self.assertTrue(all(item.reverse_scored and item.conversion == "6-raw" for item in result.items[25:]))
        self.assertEqual((self.domain(result, "s26").mean, self.domain(result, "s26").numerator), (3.0, 9))
        self.assertEqual(session.model_dump_json(), before)

    def test_registration_and_external_approval_do_not_block_own_values(self):
        answers = {f"s{n:02}": 0 if 10 <= n <= 14 else 1 for n in range(1, 29)}
        result = self.result(**answers)
        self.assertEqual((result.status, result.calculation_status, result.registration_status), ("calculated", "complete", "all_answered"))
        self.assertIsNone(result.registration_complete)
        self.assertEqual(result.external_comparison_status, "pending_approval")
        self.assertTrue(all(domain.same_edition_value_available for domain in result.domains))
        self.assertEqual((result.schema_version, result.policy_version), ("4.0", "survey-policy-20261002-s1.1"))

    def test_no_answers_and_recorded_blank_reasons_remain_missing(self):
        empty = self.result()
        self.assertEqual((empty.status, empty.registration_status, empty.calculation_status), ("unregistered", "unregistered", "unavailable"))
        self.assertTrue(all(domain.mean is None and domain.status == "missing" for domain in empty.domains))
        session = self.session()
        session.survey_blank_reasons = {f"s{n:02}": "합성 미응답 사유" for n in range(1, 29)}
        result = survey_scores_v4(session, self.catalog)
        self.assertEqual((result.answered_count, result.blank_reason_count), (0, 28))
        self.assertEqual(result.registration_status, "answers_or_reasons_recorded")
        self.assertEqual(result.items[9].blank_reason, "합성 미응답 사유")
        self.assertIsNone(result.items[9].raw)
        self.assertIsNone(result.registration_complete)

    def test_invalid_mutated_answers_and_unknown_id_are_rejected(self):
        for key, value in (("s01", 0), ("s10", 5), ("s10", True), ("s01", "3"), ("s01", 3.0)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                survey_scores_v4(self.session(**{key: value}), self.catalog)
        session = self.session()
        session.survey["s99"] = 3
        with self.assertRaises(ValidationError):
            survey_scores_v4(session, self.catalog)

    def test_old_survey_scale_is_not_reinterpreted_as_s1(self):
        session = new_session_v4("synthetic-old-survey", survey_version="catalog-20260913-v2")
        session.survey["s10"] = 5
        with self.assertRaisesRegex(ValueError, "original survey"):
            survey_scores_v4(session, self.catalog)

    def test_policy_source_versions_and_confirmed_pending_boundary_are_validated(self):
        policy = load_survey_policy_v4().model_dump(mode="json")
        for mutate in (lambda p: p.update(version="old-policy"),
                       lambda p: p["source"].update(sha256="0" * 64),
                       lambda p: p["groups"][1].update(partial_status="insufficient_responses"),
                       lambda p: p["groups"][2].update(question_ids=["s10", "s11", "s12"])):
            with self.subTest(mutate=mutate), self.assertRaises(ValidationError):
                data = deepcopy(policy)
                mutate(data)
                SurveyPolicyV4.model_validate_json(json.dumps(data))
