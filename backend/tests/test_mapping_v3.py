import json
import unittest

from app.domain.catalog_v3 import BehaviorCatalogV3, MappingV3, ProtocolV3, SurveyCatalogV3
from app.domain.validation_v3 import validate_references_v3
from app.import_catalogs_v3 import ROOT


class MappingV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        def read(model, name):
            return model.model_validate_json((ROOT / "resources" / name).read_text(encoding="utf-8"))
        cls.catalog = read(BehaviorCatalogV3, "catalogs/behavior-v3.json")
        cls.survey = read(SurveyCatalogV3, "catalogs/survey-v3.json")
        cls.protocol = read(ProtocolV3, "rules/protocol-v3.json")
        cls.results = read(MappingV3, "mappings/results-v3.json")
        cls.mapping = read(MappingV3, "mappings/survey-behavior-v3.json")

    def test_all_real_references_resolve(self):
        validate_references_v3(self.catalog, self.survey, self.protocol, (self.results, self.mapping))
        self.assertEqual(len(self.mapping.entries), 28)
        self.assertEqual(len(self.results.entries), 11)

    def test_question_ranges_and_prose_become_explicit_references(self):
        entries = {entry.entry_id: entry for entry in self.results.entries}
        self.assertEqual(entries["owner_type"].survey_ids, tuple(f"s{number:02d}" for number in range(1, 7)))
        self.assertIn("attachment_type", entries["summary_advice"].result_basis_ids)
        self.assertFalse(entries["summary_advice"].behavior_codes)
        self.assertIn("s25", entries["summary_advice"].survey_ids)

    def test_survey_only_has_no_invented_behavior_links(self):
        for entry in self.mapping.entries:
            if entry.original["comparison"] == "설문 단독":
                self.assertFalse(entry.behavior_codes)
                self.assertFalse(entry.windows)
        self.assertEqual({entry.entry_id for entry in self.mapping.entries if entry.original["comparison"] == "설문 단독"},
                         {f"Q{number:02d}" for number in (*range(7, 10), 12, *range(15, 22), *range(26, 29))})

    def test_actual_windows_and_new_procedure_order(self):
        self.assertEqual(self.protocol.segment_order, ("entry", "baseline", "alone", "reunion", "ignore", "walk", "stranger", "exit"))
        windows = {window.window_id: window for window in self.protocol.windows}
        self.assertEqual((windows["alone_later"].start_seconds, windows["alone_later"].end_seconds), (10, 60))
        self.assertTrue(windows["reunion_contact"].actual_event_required)
        self.assertEqual(windows["stranger_call"].anchor, "name_called")
        self.assertEqual(len([key for key in windows if key.startswith("walk_phase_")]), 6)

    def test_unknown_references_and_duplicate_mapping_are_rejected(self):
        original = self.mapping.model_dump(mode="json")
        for field, value in (("behavior_codes", ["개61"]), ("survey_ids", ["s29"]),
                             ("windows", ["unknown"]), ("result_basis_ids", ["unknown"])):
            changed = json.loads(json.dumps(original))
            changed["entries"][0][field] = value
            with self.assertRaises(ValueError):
                mapping = MappingV3.model_validate_json(json.dumps(changed))
                validate_references_v3(self.catalog, self.survey, self.protocol, (self.results, mapping))
        changed = json.loads(json.dumps(original))
        changed["entries"].append(changed["entries"][0])
        with self.assertRaises(ValueError):
            MappingV3.model_validate_json(json.dumps(changed))


if __name__ == "__main__":
    unittest.main()
