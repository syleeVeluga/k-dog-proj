import hashlib
import json
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from pydantic import ValidationError

from app.domain.catalog import SURVEY_IDS, SurveyCatalog
from app.import_catalogs import CUSTOMER_DIR, SURVEY_V2_FILE, read_survey_v2

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "resources/catalogs/survey-v2.json"
MAPPING = ROOT / "resources/catalogs/survey-v1-to-v2.json"
RATIONALE = CUSTOMER_DIR / "04_보호자_설문지_문항근거.docx"
WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_paragraphs(path):
    root = ElementTree.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
    return {"".join(node.text or "" for node in paragraph.iter(WORD + "t")).strip() for paragraph in root.iter(WORD + "p")}


class SurveyCatalogV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = SurveyCatalog.model_validate_json(CATALOG.read_bytes())
        cls.source = CUSTOMER_DIR / cls.catalog.source_filename
        cls.old = json.loads((ROOT / "resources/catalogs/survey-v1.json").read_text(encoding="utf-8"))

    def test_layout_and_source_hash(self):
        self.assertEqual(self.catalog.source_filename, SURVEY_V2_FILE)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.catalog.source_sha256)
        self.assertEqual(tuple(item.item_id for item in self.catalog.items), SURVEY_IDS)
        self.assertEqual([item.domain for item in self.catalog.items], list("A" * 9 + "B" * 5 + "C" * 7 + "D" * 4 + "E" * 3))
        self.assertEqual([item.number for item in self.catalog.items if item.allows_not_applicable], [7, 8, 9])
        self.assertEqual([item.number for item in self.catalog.items if item.source_page == 2], [26, 27, 28])
        self.assertEqual(self.catalog.response_scale, ("전혀 아니다", "아니다", "보통", "그렇다", "매우 그렇다"))

    def test_every_question_appears_in_the_rationale_document(self):
        paragraphs = docx_paragraphs(RATIONALE)
        for item in self.catalog.items:
            with self.subTest(item=item.item_id):
                self.assertIn(item.text, paragraphs)

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

    def test_reader_reproduces_the_committed_json(self):
        self.assertEqual(read_survey_v2(self.source).model_dump_json(indent=2) + "\n", CATALOG.read_text(encoding="utf-8"))

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
