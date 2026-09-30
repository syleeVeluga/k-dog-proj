from fractions import Fraction
import json
import unittest

from app.scoring_v3 import calculate, owner_ratio_gate, owner_threshold, vocal_category
from tests.scoring_fixtures_v3 import event, fixture


class ScoringV3Tests(unittest.TestCase):
    def values(self, data, **options):
        return {item.key: item for item in calculate(fixture(data, **options)).values}

    def test_walk_source_six_phases_and_conditions_never_fill_missing(self):
        raw = {f"개{i}": value for i, value in zip(range(38, 44), (0, 0, 2, 3, 2, 0))}
        for condition, expected in ((None, "condition_unknown"), (1, "calculated"), (2, "calculated"), (3, "invalid")):
            values = self.values({**raw, **({"보13": condition} if condition is not None else {})})
            self.assertEqual(values["개27"].status, expected)
            self.assertEqual(values["개27"].value, .5 if expected == "calculated" else None)
            if expected == "calculated":
                self.assertEqual(values["개26"].value, 1)
                self.assertEqual(values["개36"].value, 2)
        missing = self.values({**raw, "개43": None, "보13": 1})
        self.assertEqual(missing["개27"].status, "missing")
        invalid = self.values({**raw, "개43": None, "보13": 3})
        self.assertEqual(invalid["개27"].status, "invalid")
        for value in range(4):
            all_same = self.values({**{f"개{i}": value for i in range(38, 44)}, "개37": 3, "보13": 1})
            self.assertEqual(all_same["개27"].value, 1 if value <= 1 else 0)

    def test_body_changes_keep_signs_and_ignore_condition_is_local(self):
        for before, after, expected in ((-2, 0, 2), (2, 0, 2), (-2, 2, 0), (0, 0, 0)):
            values = self.values({"개58": before, "개18": after, "개8": before, "개23": after, "보12": 3})
            self.assertEqual(values["separation_reunion_body"].value, expected)
            self.assertEqual(values["baseline_ignore_body"].status, "invalid")
        values = self.values({"개8": 0, "개23": 0, "보12": 2})
        self.assertEqual(values["baseline_ignore_body"].value, 0)
        self.assertIn("보12=2", values["baseline_ignore_body"].reason)
        self.assertEqual(self.values({"개8": 0, "개23": 0})["baseline_ignore_body"].status, "condition_unknown")
        for value in (0, 1.2345, 99, None):
            result = self.values({"개32": value})["object_latency_seconds"]
            self.assertEqual(result.value, value if value not in (99, None) else None)

    def test_separation_all_25_preserve_temporal_sequence_and_shortening(self):
        beginnings = ("문·안전문을 향해 뛰거나", "문을 코나 앞발로", "문 앞 몸길이", "문 쪽을 향하거나", "문 쪽 방향 전환·접근이 관찰되지")
        endings = ("지속적 시도", "가끔 코나 앞발", "20초 이상", "5초 이상 20초 미만", "돌아오지 않음")
        for initial in range(-2, 3):
            for later in range(-2, 3):
                result = calculate(fixture({"개9": initial, "개10": later})).descriptions[0]
                self.assertEqual(result.status, "calculated")
                self.assertIn(beginnings[initial + 2], result.text)
                self.assertIn(endings[later + 2], result.text)
        shortened = calculate(fixture({"개9": 0, "개10": 0}, alone_end=80)).descriptions[0]
        self.assertEqual(shortened.status, "missing")
        self.assertIsNone(shortened.text)

    def test_vocal_boundaries_whole_listening_and_actual_short_denominator(self):
        for vocal, expected in ((0, 0), (.01, 1), (20, 1), (20.001, 2), (40, 2), (40.001, 3), (60, 3)):
            self.assertEqual(vocal_category(vocal, 60), expected)
        for listened, whole, available, expected in ((60, True, 60, "calculated"), (30, False, 60, "missing"), (60, True, 30, "missing"), (61, True, 60, "invalid")):
            raw = {"value": 1, "vocalization": {"video_id": "video1", "listened_seconds": listened, "cumulative_vocal_seconds": 20, "whole_interval_judged": whole, "note": "발성 실제 누적20초"}}
            result = calculate(fixture({"개11": raw}), audio_available={"alone": available}).vocalizations[1]
            self.assertEqual(result.result.status, expected)
            self.assertEqual(result.actual_interval_seconds, 60)
        raw = {"value": 1, "vocalization": {"video_id": "video1", "listened_seconds": 30, "cumulative_vocal_seconds": 10, "whole_interval_judged": True, "note": "단축한 전체30초 청취"}}
        result = calculate(fixture({"개11": raw}, alone_end=80), audio_available={"alone": 30}).vocalizations[1]
        self.assertEqual(result.result.value, 1)
        self.assertEqual(result.actual_interval_seconds, 30)
        raw["value"] = 0
        self.assertEqual(calculate(fixture({"개11": raw}, alone_end=80), audio_available={"alone": 30}).vocalizations[1].result.status, "invalid")

    def test_technical_metrics_weights_directions_and_entry_source_thresholds(self):
        raw = {"개5": 0, "개6": -1, "개30": 1, "보14": 1, "개13": -2, "개14": 2, "개15": 0, "개54": 0}
        result = calculate(fixture(raw))
        values = {item.key: item for item in result.values}
        self.assertAlmostEqual(values["AW"].value, 200 / 3)
        self.assertEqual(values["AX"].value, 50)
        self.assertAlmostEqual(values["AY"].value, 400 / 7)
        env, people = result.directions[:2]
        self.assertEqual((env.negative_sum, env.positive_sum, env.observed_items), (1, 1, 3))
        self.assertEqual((people.negative_sum, people.positive_sum, people.observed_items), (2, 2, 4))
        self.assertEqual(result.entry_label, "자극에 따라 다름")
        for values, label in (({"개5": -1, "개6": -2}, "주저함 · 거리를 벌림"), ({"개5": 0, "개6": 0}, "뚜렷한 치우침 없음"), ({"개5": 1, "개6": 2}, "살피지 않고 들이닥침"), ({"개5": 0}, None)):
            self.assertEqual(calculate(fixture(values)).entry_label, label)
        self.assertEqual(self.values({**raw, "개54": None})["AX"].status, "missing")
        self.assertEqual(self.values({**raw, "보14": 3})["AW"].status, "invalid")
        self.assertEqual(self.values({"개5": 0, "보14": 1})["AW"].status, "missing")

    def test_owner_scene_means_opportunities_zero_points_and_safety_exclusions(self):
        raw = {"보6": -2, "보9": -2, "보22": 2, "보38": 2}
        result = calculate(fixture(raw)).owner
        self.assertEqual(result.evidence_items, 3)
        self.assertEqual(result.scenes, 2)
        self.assertEqual(result.scene_means["줄 대처"], (2, 0, 0))
        self.assertEqual(result.ratios, (.5, 0, .5))
        self.assertIsNone(result.label)
        result = calculate(fixture({"보6": 0, "보9": -1, "보22": -2, "보38": 2})).owner
        self.assertEqual(result.label, "조율형")
        self.assertEqual(result.ratios, (0, 1, 0))
        for code, value, condition_code, condition_value in (("보22", -2, "보38", 1), ("보39", 2, "보38", 2), ("보24", -1, "보40", 0), ("보23", 0, "보40", 1)):
            result = calculate(fixture({code: value, condition_code: condition_value})).owner
            self.assertEqual(result.evidence_items, 0)
        stopped = calculate(fixture(raw, events=[event("staff_stop", 0, "entry")])).owner
        self.assertFalse(stopped.items[0].used)
        self.assertTrue(stopped.items[0].excluded_evidence)
        before_stop = calculate(fixture(raw, events=[event("welfare_stop", 10, "entry")])).owner
        self.assertTrue(before_stop.items[0].used)
        empty = fixture({"보6": -2}).model_dump(mode="json")
        basis = empty["sheet"]["observations"][0]["evidence"][0]
        basis.update(end_seconds=basis["start_seconds"], observed_seconds=0.)
        empty = type(fixture({"보6": -2})).model_validate_json(json.dumps(empty))
        no_actual_time = calculate(empty).owner
        self.assertEqual(no_actual_time.evidence_items, 0)
        self.assertIn("확인량", no_actual_time.items[0].excluded_evidence[0].reason)
        directed = calculate(fixture({"보22": -2, "보38": 2}, events=[event("reunion_name", 120, "reunion")])).owner
        self.assertFalse(directed.items[2].used)

    def test_owner_exact_sixty_and_fifteen_point_boundaries(self):
        for totals, items, scenes, label in (((60, 40, 0), 3, 2, "허용형"), ((Fraction(599, 10), Fraction(401, 10), 0), 3, 2, None),
            ((60, 40, 0), 2, 2, None), ((60, 40, 0), 3, 1, None), ((50, 50, 0), 6, 3, None)):
            self.assertEqual(owner_threshold(totals, items, scenes)[1], label)
        # Test the gap predicate independently: a valid 3-type 60% leader already implies at least a 20%p gap.
        self.assertTrue(owner_ratio_gate(Fraction(60, 100), Fraction(45, 100)))
        self.assertFalse(owner_ratio_gate(Fraction(60, 100), Fraction(451, 1000)))
        with self.assertRaises(ValueError):
            owner_threshold((60, 45, -5), 3, 2)


if __name__ == "__main__":
    unittest.main()
