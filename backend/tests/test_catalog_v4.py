import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.domain.catalog_v4 import (AUTO_CODES, BehaviorCatalogV4, COUNT_CODES, ITEM_CODES,
                                   MEMO_CODES, NUMERIC_CODES, RESOURCES, load_catalog_v4,
                                   load_rules_v4, load_mapping_v4)
from app.import_catalogs_v4 import CUSTOMER_DIR_V4, SOURCES, extract_v4, verify_sources


class CatalogV4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog_v4()
        cls.items = {item.code: item for item in cls.catalog.items}

    def test_exact_counts_and_retired_identity_exclusion(self):
        self.assertEqual(len(ITEM_CODES), 90)
        self.assertEqual((len(NUMERIC_CODES), len(AUTO_CODES), len(MEMO_CODES)), (83, 4, 3))
        self.assertEqual(117 - 4 - 33 - 1 + 11, len(self.catalog.items))
        changes = json.loads((RESOURCES / "catalogs/changes-v4.json").read_text(encoding="utf-8"))
        retired = {row["code"] for row in changes["entries"] if row["change"] == "폐기"}
        self.assertEqual(len(retired), 33)
        self.assertFalse(retired & set(ITEM_CODES))
        self.assertFalse({"개59", "개94", "개32", *changes["unused_codes"]} & set(ITEM_CODES))

    def test_new_source_scales_and_environment_identity(self):
        for code in ("개8", "개12"):
            self.assertEqual(self.items[code].allowed_values, (0, 1, 2))
        for code in ("개30", "개34", "환경1"):
            self.assertEqual(self.items[code].allowed_values, (0, 1, 2, 3))
        self.assertEqual(self.items["환경1"].internal_address, "2_개행동!J94")
        self.assertEqual(self.items["환경1"].category_priority, (1,))
        self.assertEqual(self.items["보5"].allowed_values, (-1, 0, 1))
        for code in ("바54", "바55"):
            self.assertEqual(self.items[code].allowed_values, (0, 1))
            self.assertTrue(self.items[code].optional)
        self.assertEqual(len(COUNT_CODES), 17)

    def test_value_and_display_order_are_separate(self):
        self.assertEqual(self.items["개9"].category_priority, (-2, -1, 0, 1, 2))
        for code in ("보10", "보11", "보23"):
            self.assertEqual(self.items[code].allowed_values, (-2, -1, 0, 1, 2))
            self.assertEqual(self.items[code].display_order, (2, 1, 0, -1, -2))
            self.assertEqual(self.items[code].category_priority, (2, 1, 0, -1, -2))

    def test_docx_corrections_override_workbook_description(self):
        for code in ("개23", "개58"):
            self.assertIn("개8은 환경 탐색 항목", self.items[code].text)
        self.assertIn("0~15초", self.items["개21"].text)
        self.assertEqual(self.items["개21"].policy_pending, ("D03",))
        self.assertEqual(self.items["개21"].windows, ("reunion_approach",))

    def test_owner_points_and_separation_texts_are_source_checked(self):
        rules = load_rules_v4()
        self.assertTrue(rules["owner_points_unchanged_from_v3"])
        self.assertEqual(len(rules["owner_type_points"]), 29)
        self.assertEqual(len(rules["separation_combinations"]), 25)
        pair = next(row for row in rules["separation_combinations"] if row["initial"] == 2 and row["later"] == 1)
        self.assertIn("문에서 떨어진 곳에서 조용히", pair["text"])
        self.assertFalse({"V", "AW", "AY", "개32"} & set(rules["active_derived_keys"]))

    def test_catalog_rejects_old_edition_or_unknown_address(self):
        document = self.catalog.model_dump(mode="json")
        document["schema_version"] = "3.0"
        with self.assertRaises(ValidationError):
            BehaviorCatalogV4.model_validate_json(json.dumps(document))
        document["schema_version"] = "4.0"
        document["items"][0]["internal_address"] = "2_개행동!J94"
        with self.assertRaises(ValidationError):
            BehaviorCatalogV4.model_validate_json(json.dumps(document))

    def test_runtime_source_hash_is_pinned(self):
        document = self.catalog.model_dump(mode="json")
        document["sources"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValidationError, "SHA-256"):
            BehaviorCatalogV4.model_validate_json(json.dumps(document))
        # Every persisted rule/mapping reader applies the same nested source pins.
        cases = (("rules/scoring-v4.json", load_rules_v4, "scoring", ["owner_type_points", 0, "source"]),
                 ("rules/protocol-v4.json", load_rules_v4, "protocol", ["source"]),
                 ("rules/preprocess-v4.json", load_rules_v4, "preprocess", ["source"]),
                 ("mappings/survey-behavior-v4.json", load_mapping_v4, "survey-behavior", ["entries", 0, "source"]),
                 ("mappings/results-v4.json", load_mapping_v4, "results", ["entries", 0, "source"]),
                 ("mappings/s1-input-v4.json", load_mapping_v4, "s1-input", ["source"]))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, loader, argument, keys in cases:
                content = json.loads((RESOURCES / name).read_text(encoding="utf-8"))
                target = content
                for key in keys:
                    target = target[key]
                target["sha256"] = "0" * 64
                destination = root / name
                destination.parent.mkdir(exist_ok=True)
                destination.write_text(json.dumps(content), encoding="utf-8")
                with self.subTest(name=name), patch("app.domain.catalog_v4.RESOURCES", root):
                    with self.assertRaisesRegex(ValidationError, "SHA-256"):
                        loader(argument)

    def test_user_reset_instruction_supersedes_original_migration_proposal(self):
        rules = load_rules_v4()
        r25 = next(rule for rule in rules["rules"] if rule["rule_id"] == "R25")
        self.assertEqual(r25["application_status"], "superseded_by_user_20261003")
        self.assertIn("점수 이관 금지", r25["effective_policy"])

    def test_missing_or_changed_source_fails_explicitly(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaisesRegex(ValueError, "missing"):
                verify_sources(root)
            (root / SOURCES["SRC02"][0]).write_bytes(b"synthetic changed source")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                verify_sources(root)

    @unittest.skipUnless(all((CUSTOMER_DIR_V4 / name).exists() for name, _ in SOURCES.values()),
                         "private SRC02/SRC03 unavailable; source extraction verification not performed")
    def test_received_source_bytes_and_committed_assets_match(self):
        before = {key: hashlib.sha256((CUSTOMER_DIR_V4 / name).read_bytes()).hexdigest()
                  for key, (name, _) in SOURCES.items()}
        extracted = extract_v4()
        for name, content in extracted.items():
            self.assertEqual((RESOURCES / name).read_text(encoding="utf-8"), content, name)
        for key, (name, expected) in SOURCES.items():
            self.assertEqual(before[key], expected)
            self.assertEqual(hashlib.sha256((CUSTOMER_DIR_V4 / name).read_bytes()).hexdigest(), expected)
        for options in (("--check",), ("--customer-dir", str(CUSTOMER_DIR_V4), "--check")):
            completed = subprocess.run([sys.executable, "-X", "utf8", "-m", "app.import_catalogs", *options],
                                       cwd=RESOURCES.parent / "backend", capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn("behavior-v4.json: source verified", completed.stdout)
            self.assertIn("Excel import disabled", completed.stdout)


if __name__ == "__main__":
    unittest.main()
