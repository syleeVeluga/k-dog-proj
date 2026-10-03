import subprocess
import sys
import unittest
from collections import Counter

from app.domain.catalog_v3 import BehaviorCatalogV3, OWNER_ROWS, ScoringRulesV3, SurveyCatalogV3
from app.import_catalogs_v3 import CUSTOMER_DIR_V3, ROOT, extract_v3, verify_attachments


class CatalogV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BehaviorCatalogV3.model_validate_json((ROOT / "resources/catalogs/behavior-v3.json").read_text(encoding="utf-8"))
        cls.survey = SurveyCatalogV3.model_validate_json((ROOT / "resources/catalogs/survey-v3.json").read_text(encoding="utf-8"))
        cls.items = {item.code: item for item in cls.catalog.items}

    def test_all_attachments_and_extractions_match_read_only_sources(self):
        manifest = verify_attachments(CUSTOMER_DIR_V3)
        self.assertEqual(len(manifest["files"]), 14)
        for filename, extracted in extract_v3(CUSTOMER_DIR_V3).items():
            with self.subTest(filename=filename):
                self.assertEqual((ROOT / "resources" / filename).read_text(encoding="utf-8"), extracted)

    def test_exact_source_row_counts_and_discontinuous_owner_rows(self):
        self.assertEqual(Counter(item.code[0] for item in self.catalog.items), {"바": 41, "개": 56, "보": 20})
        self.assertEqual(Counter(item.usage for item in self.catalog.items), {"direct": 109, "automatic": 4, "unused": 4})
        self.assertEqual(tuple(item.row for item in self.catalog.items if item.code.startswith("보")), OWNER_ROWS)
        self.assertEqual([item.code for item in self.catalog.items if item.usage == "unused"], ["개20", "개31", "개33", "개35"])
        self.assertEqual([item.code for item in self.catalog.items if item.usage == "automatic"], ["개26", "개27", "개36", "개60"])

    def test_heterogeneous_values_follow_row_definitions_not_headers(self):
        expected = {"바5": (-2, -1, 0, 1, 2), "바6": (0, 1, 2, 3), "개7": (0, 1),
                    "개16": (0, 1, 2, 3, 4), "개37": (0, 1, 2, 3), "보5": (-1, 0, 1),
                    "보12": (1, 2, 3), "보16": (0, 1), "보38": (0, 1, 2, 3)}
        for code, values in expected.items():
            self.assertEqual(self.items[code].allowed_values, values)
        self.assertEqual(self.items["바14"].value_type, "count")
        self.assertEqual(self.items["개32"].value_type, "seconds")
        self.assertEqual(self.items["보25"].value_type, "memo")
        self.assertTrue(self.items["개37"].labels[0].text.startswith("0 실제 신체 접촉"))
        self.assertTrue(self.items["보5"].labels[0].source.location.endswith("D5"))

    def test_opportunities_representative_rules_and_multiple_windows(self):
        self.assertEqual(self.items["보22"].opportunity_codes, ("보38",))
        self.assertEqual(self.items["보39"].opportunity_codes, ("보38",))
        self.assertEqual(self.items["보24"].opportunity_codes, ("보40",))
        self.assertEqual(self.items["보14"].windows, ("entry_object", "exit_object"))
        self.assertIn("C→G", self.items["개9"].representative_rule)
        self.assertIn("구간 단축은 빈칸", self.items["개10"].representative_rule)
        self.assertEqual(self.items["보10"].windows, ("before_separation",))
        for row in range(37, 44):
            for required in ("사람 양발 중점", "주된 시간의 범주", "가려 못 보면 빈칸"):
                self.assertIn(required, self.items[f"개{row}"].representative_rule)

    def test_survey_has_eight_domains_and_separate_question_25(self):
        self.assertEqual(len(self.survey.items), 28)
        self.assertEqual(len({item.report_domain for item in self.survey.items if not item.standalone}), 8)
        self.assertEqual([item.number for item in self.survey.items if item.standalone], [25])
        for item in self.survey.items:
            self.assertFalse(item.allows_not_applicable)
            self.assertEqual(item.reverse_scored, item.number >= 26)
        self.assertEqual(self.survey.items[9].allowed_values, (0, 1, 2, 3, 4))
        self.assertIn("늦게 데려온", self.survey.items[6].text)

    def test_rules_preserve_directions_counts_contact_and_entry_override_sources(self):
        rules = ScoringRulesV3.model_validate_json((ROOT / "resources/rules/scoring-v3.json").read_text(encoding="utf-8"))
        self.assertEqual(len(rules.owner_type_points), 29)
        self.assertEqual(rules.owner_type_thresholds.minimum_items, 3)
        self.assertEqual(rules.owner_type_thresholds.minimum_scenes, 2)
        self.assertEqual(rules.owner_type_thresholds.dominant_ratio, 0.6)
        self.assertEqual(rules.owner_type_thresholds.ratio_gap, 0.15)
        formulas = {item.source.location: item.formula for item in rules.formula_templates}
        for cell in ("CA6", "CB6", "CC6", "BV6", "BW6", "BX6", "AW6", "AX6", "AY6", "Z6"):
            self.assertIn(f"여러쌍비교!{cell}", formulas)
        self.assertIn("6_행사전문가의견", formulas["여러쌍비교!CA6"])
        self.assertIn("J51", formulas["여러쌍비교!AX6"])
        self.assertIn("0_안내!A52", {item.source.location for item in rules.definitions})
        self.assertEqual(len(rules.separation_combinations), 25)
        self.assertEqual((rules.separation_combinations[0].initial, rules.separation_combinations[0].later), (-2, -2))
        self.assertEqual((rules.separation_combinations[-1].initial, rules.separation_combinations[-1].later), (2, 2))
        self.assertIn("이후 50초", rules.separation_combinations[0].text)

    def test_cli_checks_historical_edition_with_an_explicit_spec(self):
        for options in (("--check",), ("--customer-dir", str(CUSTOMER_DIR_V3), "--check")):
            run = subprocess.run([sys.executable, "-X", "utf8", "-m", "app.import_catalogs", "--spec", "20260929", *options],
                                 cwd=ROOT / "backend", capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(run.returncode, 0, run.stderr)


if __name__ == "__main__":
    unittest.main()
