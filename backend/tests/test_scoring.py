"""Synthetic cases for scoring-v2: width vs mean, trial invalidation, type branches, rounding and the survey rules."""

import unittest
from decimal import Decimal
from pathlib import Path

from app.domain.catalog import BehaviorCatalog, SURVEY_IDS, SurveyCatalog
from app.domain.contracts import Rater, ScoreResult, ScoreSheet, SurveyAnswers, SurveyResult
from app.scoring import RULES, behavior_scores, rounded, survey_scores

ROOT = Path(__file__).resolve().parents[2]


class ScoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BehaviorCatalog.model_validate_json((ROOT / "resources/catalogs/behavior-v2.json").read_bytes())
        cls.survey_catalog = SurveyCatalog.model_validate_json((ROOT / "resources/catalogs/survey-v2.json").read_bytes())

    def sheet(self, scores):
        items = []
        for item in self.catalog.rated_items():
            if item.item_id in scores:
                items.append({"item_id": item.item_id, "score": scores[item.item_id], "status": "scored", "reason": None})
            else:
                items.append({"item_id": item.item_id, "score": None, "status": "unreadable", "reason": "합성 사례: 미판독"})
        return ScoreSheet(sheet_id="s", case_id="c", session_id="v", catalog_version=self.catalog.version,
                          rater=Rater(rater_id="ai-1", kind="ai"), recorded_at="2026-09-16T00:00:00+09:00",
                          items=tuple(items))

    def result(self, scores):
        return behavior_scores(self.sheet(scores), self.catalog)

    def domain(self, result, code):
        return next(d for d in result.domains if d.domain == code)

    def indicator(self, result, key):
        return next(i for i in result.indicators if i.key == key)

    def type_(self, result, key):
        return next(t for t in result.types if t.key == key)

    def test_width_shows_what_the_mean_hides(self):
        result = self.result({"BS-01": 1, "DOG-01": 5})
        soc_e = self.domain(result, "SOC_E")
        self.assertEqual((soc_e.mean, soc_e.lean, soc_e.width, soc_e.scored_count, soc_e.unreadable_count), (3.0, 0.0, 2, 2, 3))

    def test_one_items_feed_width_and_degree_but_not_mean(self):
        edu = self.domain(self.result({"OWN-04": 5}), "EDU")
        self.assertEqual((edu.mean, edu.lean, edu.width, edu.degree), (None, None, 2, 5.0))

    def test_rounding_is_half_away_from_zero_like_excel(self):
        self.assertEqual(rounded(Decimal("2.665")), 2.67)
        self.assertEqual(rounded(Decimal("-0.335")), -0.34)
        self.assertIsNone(rounded(None))
        syn = self.domain(self.result({"BS-08": 3, "DOG-19": 2, "DOG-20": 3}), "SYN")
        self.assertEqual((syn.mean, syn.lean), (2.67, -0.33))

    def test_indicators_use_distance_from_center(self):
        result = self.result({"DOG-04": 5, "DOG-18": 3, "DOG-06": 3, "DOG-13": 1, "DOG-10": 4, "DOG-21": 0})
        self.assertEqual(ScoreResult.model_validate_json(result.model_dump_json()), result)
        self.assertEqual(self.indicator(result, "adaptation").value, 2.0)
        self.assertEqual(self.indicator(result, "recovery").value, -2.0)  # 얼어붙음(1)은 「가라앉음」이 아니다
        self.assertEqual(self.indicator(result, "stranger_calming").value, -1.0)
        self.assertEqual((self.indicator(result, "sync_rate").value, self.indicator(result, "sync_rate").status), (0.0, "calculated"))
        self.assertEqual(result.baseline_arousal, 5)
        missing = self.indicator(self.result({"DOG-04": 3}), "adaptation")
        self.assertEqual((missing.status, missing.reason), ("missing", "미판독: DOG-18"))

    def test_ignore_trial_invalidation(self):
        result = self.result({"OWN-08": 3, "DOG-17": 1, "DOG-18": 5, "DOG-04": 3, "DOG-05": 3, "DOG-12": 3, "DOG-14": 3, "DOG-13": 3, "DOG-16": 0})
        att = self.domain(result, "ATT")
        self.assertEqual((att.excluded_count, att.scored_count, att.width), (2, 4, 0))
        self.assertEqual(self.indicator(result, "adaptation").status, "invalid")
        self.assertEqual(self.type_(result, "attachment").status, "invalid")
        valid = self.result({"OWN-08": 2, "DOG-17": 1, "DOG-18": 5, "DOG-04": 3})
        self.assertEqual(self.domain(valid, "ATT").width, 2)
        self.assertEqual(self.indicator(valid, "adaptation").value, -2.0)

    def test_walk_trial_invalidation(self):
        result = self.result({"OWN-09": 3, "BS-08": 5, "DOG-19": 5, "DOG-20": 5, "DOG-21": 6})
        syn = self.domain(result, "SYN")
        self.assertEqual((syn.excluded_count, syn.scored_count, syn.mean), (3, 0, None))
        self.assertEqual(self.indicator(result, "sync_rate").status, "invalid")
        self.assertEqual(self.type_(result, "attachment").status, "missing")
        cautious = self.result({"OWN-09": 2, "DOG-21": 6})
        self.assertEqual(self.indicator(cautious, "sync_rate").value, 1.0)

    def test_attachment_type_branches(self):
        base = {"DOG-17": 3, "DOG-05": 3, "DOG-12": 3, "DOG-14": 3, "DOG-13": 3, "DOG-16": 0}
        cases = (
            ({}, "안정"),
            ({"DOG-13": 5}, "불안"),
            ({"DOG-17": 5, "DOG-05": 5, "DOG-12": 3, "DOG-14": 3}, "거리 둠"),      # mean 4 > 3.5, calm
            ({"DOG-17": 5, "DOG-05": 5, "DOG-13": 1}, "일관되지 않음"),              # mean 4, restless
            ({"DOG-17": 4, "DOG-05": 4, "DOG-12": 3, "DOG-14": 3}, "안정"),          # mean 3.5 is still "low"
            ({"DOG-16": 1, "DOG-13": 3}, "일관되지 않음"),                            # consistency wins first
        )
        for changes, label in cases:
            with self.subTest(changes=changes):
                self.assertEqual(self.type_(self.result({**base, **changes}), "attachment").label, label)
        for missing in base:
            with self.subTest(missing=missing):
                partial = self.type_(self.result({k: v for k, v in base.items() if k != missing}), "attachment")
                self.assertEqual((partial.status, partial.reason), ("missing", f"미판독: {missing}"))

    def test_sociability_type_branches(self):
        for affiliation, arousal, label in ((3, 3, "편안·우호"), (3, 5, "우호·들뜸"), (2, 4, "담담·거리둠"), (2, 1, "경계·긴장"), (5, 2, "편안·우호")):
            with self.subTest(affiliation=affiliation, arousal=arousal):
                result = self.result({"DOG-09": affiliation, "DOG-10": arousal})
                self.assertEqual(self.type_(result, "sociability_person").label, label)
        self.assertEqual(self.type_(self.result({"DOG-09": 3}), "sociability_person").reason, "미판독: DOG-10")

    def test_wrong_catalog_version_rejected(self):
        other = self.catalog.model_copy(update={"version": "catalog-other"})
        sheet = self.sheet({}).model_copy(update={"catalog_version": "catalog-other"})
        with self.assertRaises(ValueError):
            behavior_scores(sheet, other)

    def answers(self, values=None, not_applicable=()):
        base = {item_id: 4 for item_id in SURVEY_IDS}
        base.update(values or {})
        return SurveyAnswers(answers=base, not_applicable=tuple(not_applicable))

    def test_survey_reverse_items_and_domain_means(self):
        result = survey_scores(self.answers({"s26": 1, "s27": 2, "s28": 5}), self.survey_catalog)
        values = {item.item_id: item.converted for item in result.items}
        self.assertEqual((values["s26"], values["s27"], values["s28"], values["s01"]), (5, 4, 1, 4))
        domains = {d.domain: (d.mean, d.answered_count, d.target_count, d.status) for d in result.domains}
        self.assertEqual(domains, {"A": (4.0, 9, 9, "calculated"), "B": (4.0, 5, 5, "calculated"),
                                   "C": (4.0, 7, 7, "calculated"), "E": (3.33, 3, 3, "calculated")})
        self.assertEqual(result.status, "calculated")
        self.assertFalse(hasattr(result, "total"))
        self.assertEqual(SurveyResult.model_validate_json(result.model_dump_json()), result)

    def test_not_applicable_is_missing_not_zero(self):
        result = survey_scores(self.answers({"s07": None, "s08": None, "s09": None, "s01": 2}, not_applicable=("s07", "s08", "s09")),
                               self.survey_catalog)
        a = next(d for d in result.domains if d.domain == "A")
        self.assertEqual((a.mean, a.answered_count, a.target_count, a.status), (3.67, 6, 9, "partial"))
        self.assertTrue(next(item for item in result.items if item.item_id == "s07").not_applicable)
        self.assertEqual(result.status, "partial")

    def test_separation_type_four_ways_and_s25_stored_only(self):
        for s22, s23, s24, label in ((4, 3, 4, "안정"), (4, 3, 3, "불안"), (3, 3, 5, "회피 쪽"), (1, 2, 1, "무덤덤")):
            with self.subTest(label=label):
                result = survey_scores(self.answers({"s22": s22, "s23": s23, "s24": s24, "s25": 1}), self.survey_catalog)
                self.assertEqual((result.separation.label, result.separation.resistance, result.separation.recovery),
                                 (label, (s22 + s23) / 2, s24))
        self.assertNotIn("D", {d.domain for d in result.domains})
        missing = survey_scores(self.answers({"s23": None}), self.survey_catalog).separation
        self.assertEqual((missing.status, missing.label, missing.reason), ("missing", None, "미응답: s23"))

    def test_unregistered_survey(self):
        result = survey_scores(self.answers({item_id: None for item_id in SURVEY_IDS}), self.survey_catalog)
        self.assertEqual(result.status, "unregistered")
        self.assertTrue(all(d.status == "missing" for d in result.domains))


if __name__ == "__main__":
    unittest.main()
