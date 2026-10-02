import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from app.domain.catalog import SURVEY_IDS, SurveyCatalog

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "resources/catalogs/survey-v2.json"
MAPPING = ROOT / "resources/catalogs/survey-v1-to-v2.json"


class SurveyCatalogV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = SurveyCatalog.model_validate_json(CATALOG.read_bytes())
        cls.old = json.loads((ROOT / "resources/catalogs/survey-v1.json").read_text(encoding="utf-8"))

    def test_layout(self):
        self.assertEqual(self.catalog.source_filename, "04_보호자_설문지_28문항.pdf")
        self.assertEqual(tuple(item.item_id for item in self.catalog.items), SURVEY_IDS)
        self.assertEqual([item.domain for item in self.catalog.items], list("A" * 9 + "B" * 5 + "C" * 7 + "D" * 4 + "E" * 3))
        self.assertEqual([item.number for item in self.catalog.items if item.allows_not_applicable], [7, 8, 9])
        self.assertEqual([item.number for item in self.catalog.items if item.source_page == 2], [26, 27, 28])
        self.assertEqual(self.catalog.response_scale, ("전혀 아니다", "아니다", "보통", "그렇다", "매우 그렇다"))

    def test_mapping_links_identical_sentences_only(self):
        mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
        old_text = {item["item_id"]: item["text"] for item in self.old["items"]}
        new_text = {item.item_id: item.text for item in self.catalog.items}
        self.assertEqual(set(mapping["mapping"]), set(old_text))
        linked = {new for new in mapping["mapping"].values() if new is not None}
        self.assertEqual(len(linked), len([v for v in mapping["mapping"].values() if v is not None]))
        for old, new in mapping["mapping"].items():
            with self.subTest(old=old):
                if new is None:
                    self.assertNotIn(old_text[old], new_text.values())
                else:
                    self.assertEqual(old_text[old], new_text[new])
        self.assertEqual(set(new_text) - linked, set(mapping["new_without_source"]))
        for new in mapping["new_without_source"]:
            self.assertNotIn(new_text[new], old_text.values())

    def test_contract_rejects_invented_layouts(self):
        data = json.loads(CATALOG.read_text(encoding="utf-8"))
        for index, mutate in enumerate((lambda d: d["items"].pop(), lambda d: d["items"][0].update(allows_not_applicable=True),
                       lambda d: d["items"][6].update(allows_not_applicable=False), lambda d: d["items"][9].update(domain="A"),
                       lambda d: d.update(response_scale=["1", "2", "3", "4", "5"]), lambda d: d["items"][0].update(item_id="q01"))):
            copy = json.loads(json.dumps(data))
            mutate(copy)
            with self.subTest(mutation=index):
                with self.assertRaises(ValidationError):
                    SurveyCatalog.model_validate_json(json.dumps(copy, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
