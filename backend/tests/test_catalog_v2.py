import hashlib
import json
import unittest
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook
from pydantic import ValidationError

from app.domain.catalog import BEHAVIOR_IDS, BehaviorCatalog, DOMAIN_COUNTS
from app.import_catalogs import BEHAVIOR_V2_FILE, CUSTOMER_DIR, read_behavior_v2

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "resources/catalogs/behavior-v2.json"
# 계획 문서 1장 표: item -> (domain, scale, axis, value_type, allowed scores). This table is the
# written-down interpretation of the B-column markers and the labelled cells (R1, R2).
EXPECTED = {}
for number, domain, axis in ((1, "SOC_E", "각성"), (2, "SOC_E", "각성"), (3, "SOC_E", "각성"), (5, "ATT", "각성"),
                             (7, "SOC_H", "각성"), (8, "SYN", "각성"), (9, "EXIT", "각성")):
    EXPECTED[f"BS-{number:02d}"] = (domain, "BI", axis, "scale", (1, 2, 3, 4, 5))
EXPECTED["BS-04"] = EXPECTED["BS-06"] = (None, None, None, "count", ())
for number, domain, axis in ((1, "SOC_E", "각성"), (2, "SOC_E", "사회화"), (5, "ATT", "애착"), (6, "ATT", "각성"),
                             (9, "SOC_H", "우호"), (10, "SOC_H", "각성"), (11, "SOC_H", "우호"), (12, "ATT", "애착"),
                             (13, "ATT", "각성"), (14, "ATT", "애착"), (15, "ATT", "각성"), (17, "ATT", "애착"),
                             (18, "ATT", "각성"), (19, "SYN", "거리"), (20, "SYN", "거리"), (23, "EXIT", "각성")):
    EXPECTED[f"DOG-{number:02d}"] = (domain, "BI", axis, "scale", (1, 2, 3, 4, 5))
EXPECTED["DOG-03"] = EXPECTED["DOG-24"] = (None, None, None, "scale", (3, 5))
for number in (4, 7, 8):
    EXPECTED[f"DOG-{number:02d}"] = (None, None, None, "scale", (1, 2, 3, 4, 5))
EXPECTED["DOG-16"] = (None, None, None, "count", ())
EXPECTED["DOG-21"] = (None, None, None, "phase_count", (0, 1, 2, 3, 4, 5, 6))
EXPECTED["DOG-22"] = (None, None, None, "auto_ratio", ())
for number in (1, 2, 3, 5):
    EXPECTED[f"OWN-{number:02d}"] = ("EDU", "BI", None, "scale", (1, 2, 3, 4, 5))
EXPECTED["OWN-04"] = ("EDU", "ONE", None, "scale", (3, 4, 5))
EXPECTED["OWN-06"] = EXPECTED["OWN-07"] = (None, None, None, "scale", (1, 2, 3, 4, 5))
EXPECTED["OWN-08"] = EXPECTED["OWN-09"] = (None, None, None, "scale", (1, 2, 3))


class BehaviorCatalogV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BehaviorCatalog.model_validate_json(CATALOG.read_bytes())
        cls.source = CUSTOMER_DIR / cls.catalog.source_filename

    def test_layout_counts_and_source_hash(self):
        self.assertEqual(self.catalog.source_filename, BEHAVIOR_V2_FILE)
        self.assertEqual(self.catalog.version, "catalog-20260913-v2")
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.catalog.source_sha256)
        self.assertEqual(tuple(item.item_id for item in self.catalog.items), BEHAVIOR_IDS)
        self.assertEqual(Counter(item.sheet for item in self.catalog.items),
                         {"1_바디시그널": 9, "2_개행동": 24, "3_보호자행동": 9})
        self.assertEqual(Counter(item.domain for item in self.catalog.items), DOMAIN_COUNTS)
        self.assertEqual(len(self.catalog.rated_items()), 41)
        self.assertEqual([item.item_id for item in self.catalog.items if item.value_type == "auto_ratio"], ["DOG-22"])

    def test_every_item_matches_the_plan_table(self):
        self.assertEqual(set(EXPECTED), set(BEHAVIOR_IDS))
        for item in self.catalog.items:
            with self.subTest(item=item.item_id):
                self.assertEqual((item.domain, item.scale, item.axis, item.value_type, item.allowed_scores), EXPECTED[item.item_id])
                self.assertEqual(item.domain is None, item.axis_label == "참고")
                self.assertEqual(item.domain is None, item.domain_label.startswith("—"))

    def test_every_cell_matches_the_workbook(self):
        book = load_workbook(self.source, data_only=False)
        try:
            for item in self.catalog.items:
                sheet, row = book[item.sheet], item.source_row
                with self.subTest(item=item.item_id):
                    self.assertEqual((item.segment_label, item.text, item.domain_label, item.axis_label, item.domain, item.scale),
                                     tuple(sheet[f"{column}{row}"].value for column in ("A", "B", "H", "I", "AD", "AY")))
                    original = {f"{column}{row}": sheet[f"{column}{row}"].value for column in "CDEFG"
                                if sheet[f"{column}{row}"].value is not None}
                    if item.value_type == "scale":
                        self.assertEqual({label.source_cell: label.text for label in item.labels}, original)
                        for label in item.labels:
                            self.assertEqual(label.score, "CDEFG".index(label.source_cell[0]) + 1)
                    else:
                        self.assertEqual(original, {f"C{row}": item.note})
        finally:
            book.close()

    def test_segments_follow_the_procedure(self):
        segments = {item.item_id: item.segment for item in self.catalog.items}
        self.assertEqual([segments[f"BS-{n:02d}"] for n in range(1, 10)],
                         ["entry", "entry", "entry", "entry", "alone", "alone", "stranger", "walk", "exit"])
        self.assertEqual(segments["DOG-04"], "baseline")
        self.assertEqual({segments[f"OWN-{n:02d}"] for n in range(1, 6)}, {None})
        self.assertEqual([segments[f"OWN-{n:02d}"] for n in range(6, 10)], ["alone", "reunion", "ignore", "walk"])

    def test_reader_reproduces_the_committed_json(self):
        content = read_behavior_v2(self.source).model_dump_json(indent=2) + "\n"
        self.assertEqual(content, CATALOG.read_text(encoding="utf-8"))

    def test_contract_rejects_invented_layouts(self):
        data = json.loads(CATALOG.read_text(encoding="utf-8"))
        items = data["items"]
        for mutate in (lambda d: d["items"].pop(), lambda d: d["items"].append(dict(items[0])),
                       lambda d: d["items"][0].update(domain=None, scale=None),
                       lambda d: d["items"][0].update(scale=None),
                       lambda d: d["items"][2].update(allowed_scores=[1, 2, 3]),
                       lambda d: d["items"][3].update(note=None),
                       lambda d: d["items"][0].update(segment=None)):
            copy = json.loads(json.dumps(data))
            mutate(copy)
            with self.assertRaises(ValidationError):
                BehaviorCatalog.model_validate_json(json.dumps(copy, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
