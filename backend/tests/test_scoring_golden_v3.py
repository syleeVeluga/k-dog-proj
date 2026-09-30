"""Independent expectations transcribed from 02 original formulas/point cells, not Excel recalculation."""

import unittest

from app.scoring_v3 import RULES, calculate
from tests.scoring_fixtures_v3 import fixture


class GoldenScoringV3Tests(unittest.TestCase):
    def test_all_29_original_owner_point_rows(self):
        expected = {
            "보6": {-2: (2, 0, 0), -1: (0, 2, 0), 0: (0, 2, 0), 1: (0, 0, 1), 2: (0, 0, 2)},
            "보9": {-2: (2, 0, 0), -1: (0, 2, 0), 0: (0, 1, 0), 1: (0, 0, 1), 2: (0, 0, 2)},
            "보22": {-2: (0, 2, 0), -1: (0, 2, 0), 0: (0, 0, 0), 1: (0, 0, 1), 2: (0, 0, 2)},
            "보23": {-2: (0, 0, 0), -1: (0, 0, 0), 0: (0, 0, 0), 1: (0, 0, 1), 2: (0, 0, 2)},
            "보24": {-2: (0, 0, 1), -1: (2, 0, 0), 0: (0, 2, 0), 1: (0, 0, 0), 2: (0, 0, 2)},
            "보39": {0: (0, 0, 1), 1: (2, 0, 0), 2: (0, 2, 0), 3: (0, 0, 2)},
        }
        actual = {(item["code"], item["raw_value"]): tuple(item["points"]) for item in RULES["owner_type_points"]}
        self.assertEqual(actual, {(code, raw): point for code, rows in expected.items() for raw, point in rows.items()})

    def test_original_scene_averages_and_one_two_three_scene_limits(self):
        one = calculate(fixture({"보6": -2, "보9": -2})).owner
        self.assertEqual((one.evidence_items, one.scenes, one.label), (2, 1, None))
        two = calculate(fixture({"보6": 0, "보9": -1, "보22": -2, "보38": 2})).owner
        self.assertEqual((two.evidence_items, two.scenes, two.totals, two.ratios, two.label), (3, 2, (0, 4, 0), (0, 1, 0), "조율형"))
        three = calculate(fixture({"보6": -2, "보9": -1, "보22": 2, "보39": 2, "보38": 3, "보23": 2, "보24": -1, "보40": 1})).owner
        self.assertEqual(three.scene_means, {"줄 대처": (1, 1, 0), "재회": (0, 1, 1), "낯선 사람": (1, 0, 1)})
        self.assertEqual((three.evidence_items, three.scenes, three.totals, three.label), (6, 3, (2, 2, 2), None))
        self.assertEqual(three.ratios, (1/3, 1/3, 1/3))


if __name__ == "__main__":
    unittest.main()
