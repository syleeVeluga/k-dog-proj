import copy
import json
import unittest

from app.domain.catalog_v4 import RESOURCES
from app.domain.validation_v4 import validate_asset_references_v4
from app.import_catalogs_v4 import code_references


class MappingV4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = ("catalogs/behavior", "catalogs/changes", "rules/scoring", "rules/protocol", "rules/preprocess",
                 "mappings/survey-behavior", "mappings/results", "mappings/s1-input")
        cls.assets = {f"{name}-v4.json": json.loads((RESOURCES / f"{name}-v4.json").read_text(encoding="utf-8"))
                      for name in names}

    def test_all_references_resolve(self):
        validate_asset_references_v4(self.assets)

    def test_shorthand_keeps_codes_and_range_context(self):
        self.assertEqual(code_references("개38~43; 보6·9·보22; 환경1"),
                         ["개38", "개39", "개40", "개41", "개42", "개43", "보6", "보9", "보22", "환경1"])

    def test_survey_connections_use_s1_and_keep_policy_waiting(self):
        mapping = self.assets["mappings/survey-behavior-v4.json"]
        entries = {row["question_id"]: row for row in mapping["entries"]}
        self.assertEqual(entries["Q11"]["behavior_codes"], ["개51", "개52", "개53"])
        self.assertEqual(entries["Q13"]["behavior_codes"], ["개30", "개34", "보14"])
        self.assertEqual(entries["Q14"]["behavior_codes"], ["개5", "개6", "개8", "환경1"])
        self.assertEqual(entries["Q07"]["behavior_codes"], [])
        self.assertEqual(mapping["other_partial_missing_policy"], "policy_pending_D05")

    def test_input_addresses_and_physical_verification_are_distinct(self):
        mapping = self.assets["mappings/s1-input-v4.json"]
        self.assertFalse(mapping["excel_import_enabled"])
        self.assertEqual(mapping["physical_verification"], "not_received_G01_G04")
        environment = next(row for row in mapping["entries"] if row["code"] == "환경1")
        self.assertEqual(environment["input_address"], "2_기준!D14")
        self.assertEqual(environment["internal_address"], "2_개행동!J94")
        self.assertEqual([p["address"] for p in mapping["walk_phase_metadata"]], [f"6_걷기!H{n}" for n in range(10, 16)])

    def test_retired_reference_and_false_excel_verification_are_rejected(self):
        changed = copy.deepcopy(self.assets)
        changed["mappings/results-v4.json"]["entries"][0]["behavior_codes"].append("개32")
        with self.assertRaisesRegex(ValueError, "retired"):
            validate_asset_references_v4(changed)
        changed = copy.deepcopy(self.assets)
        changed["mappings/s1-input-v4.json"]["excel_import_enabled"] = True
        with self.assertRaisesRegex(ValueError, "unverified"):
            validate_asset_references_v4(changed)


if __name__ == "__main__":
    unittest.main()
