"""Explicit source-grounded T05/T08/T18/T21/T23 report combinations, all synthetic."""
import unittest

from app.report_profile_v4 import build
from tests.report_fixture_v4 import fixture


class AcceptanceV4Tests(unittest.TestCase):
    def profile(self, values):
        final,pointer,batch = fixture(values)
        return build(final,pointer,batch=batch)

    def claims(self, profile):
        return [claim for section in (*profile.cards,*profile.details,*profile.scenes) for claim in section.claims]

    def test_t05_zero_exploration_and_natural_body_are_distinct_and_no_old_v(self):
        profile = self.profile({"개8":0,"환경1":0,"개23":0})
        facts = {fact.fact_id:fact for fact in profile.facts}
        self.assertEqual([facts["observation:"+code].value for code in ("개8","환경1","개23")],[0,0,0])
        self.assertIn("탐색을 관찰하지 못함",facts["observation:개8"].label)
        self.assertIn("자연스러운 자세",facts["observation:환경1"].label)
        self.assertIn("자연스럽게",facts["observation:개23"].label)
        self.assertNotIn("metric:V",facts)
        self.assertFalse(any(issue.blocking for issue in profile.validation_issues))

    def test_t08_positive_separation_values_keep_two_specific_source_descriptions(self):
        profile = self.profile({"개9":2,"개10":1})
        facts = {fact.fact_id:fact for fact in profile.facts}
        self.assertIn("문 쪽 방향 전환·접근이 관찰되지 않음",facts["observation:개9"].label)
        self.assertIn("절반 초과",facts["observation:개10"].label)
        self.assertIn("문에서 떨어진 곳",facts["observation:개10"].label)
        text = " ".join(claim.text for claim in self.claims(profile))
        self.assertIn(facts["observation:개9"].label,text)
        self.assertIn(facts["observation:개10"].label,text)
        self.assertIn("처음 10초",facts["metric:개60"].value)

    def test_t18_w_zero_keeps_direction_reversal_separate_from_zero_to_zero(self):
        reversed_profile = self.profile({"개58":-2,"개18":2})
        unchanged_profile = self.profile({"개58":0,"개18":0})
        for profile in (reversed_profile,unchanged_profile):
            self.assertEqual(next(f.value for f in profile.facts if f.fact_id == "metric:W"),0)
        def pair(profile):
            facts = {f.fact_id:f for f in profile.facts}
            return [facts["observation:"+code].value for code in ("개58","개18")]
        self.assertEqual(pair(reversed_profile),[-2,2])
        self.assertEqual(pair(unchanged_profile),[0,0])
        self.assertNotEqual([claim.text for claim in self.claims(reversed_profile)],[claim.text for claim in self.claims(unchanged_profile)])

    def test_t21_missing_optional_tail_does_not_suppress_valid_social_result(self):
        profile = self.profile({"개51":1})
        social = next(card for card in profile.cards if card.key == "social")
        self.assertEqual(social.status,"partial")
        self.assertTrue(any("observation:개51" in claim.fact_ids for claim in social.claims))
        self.assertFalse(any(fact.fact_id in ("observation:바54","observation:바55") for fact in profile.facts))
        self.assertFalse(any("꼬리" in claim.text for claim in self.claims(profile)))
        self.assertFalse(any(issue.blocking for issue in profile.validation_issues))

    def test_t23_body_shake_and_scratch_evidence_keeps_exactly_four_result_cards(self):
        profile = self.profile({"개23":1,"바14":1,"바46":2})
        self.assertEqual([card.key for card in profile.cards],["education_attitude","attachment","social","walking"])
        self.assertTrue({"observation:개23","observation:바14","observation:바46"} <= {fact.fact_id for fact in profile.facts})
        self.assertFalse(any(card.key in ("body","body_state","body_signal") for card in profile.cards))
        self.assertFalse(any(issue.blocking for issue in profile.validation_issues))
