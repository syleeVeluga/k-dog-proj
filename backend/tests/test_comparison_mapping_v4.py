"""Delivered EXT1.1 survey comparison mapping; all participant answers here are synthetic."""
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app import comparison_mapping_v4 as mapping, comparisons_v4 as comparisons
from app.domain.catalog_v3 import SurveyCatalogV3
from app.domain.catalog_v4 import RESOURCES
from app.input_models_v4 import SessionV4
from app.storage import REPO_ROOT, encode
from app.survey_v4 import survey_scores_v4
from tests import test_comparisons_v4 as comparison_fixture
from tests import test_external_comparisons_v4 as external_fixture

DELIVERY = "외부연구값_문항대조와출력기준_누적비교반영_20261008.xlsx"
PRESERVED = {"report/comparison-sources-v4.json": "9ad069bfd05b04697e9296fb76f6880daae76088e72210dfd7ee0ee22aef0e9b",
             "catalogs/survey-v3.json": "4d6963a22c30c03d4784a3a1702290762b2ffcf1a107aa01c561f2a95215df1b",
             "rules/survey-policy-20261007.json": "fe0574328e4e4b2b0af7ad35ad7b601c12f67a5e3931eafa0500158874c39901",
             "rules/survey-policy-v4.json": "9af6d83d6d92a5831b37f0fd01f20da85f29db66618b735b7b4968535eb597a7"}


def answers(**update):
    value = {f"s{n:02}": 3 for n in range(1, 29)}
    value.update(s10=1, s11=2, s12=0, s13=1, s14=1)
    value.update(update)
    return value


def session(survey):
    return SessionV4(session_id="SYNTHETIC", note="synthetic", survey_version="survey-20260929-v3", survey=survey)


class MappingContractTests(unittest.TestCase):
    def test_t01_all_28_questions_map_to_nine_metrics_and_only_fear_links_external(self):
        loaded = mapping.load()
        self.assertEqual([metric.metric_id for metric in loaded.metrics], [f"S{n:02}" for n in range(1, 10)])
        ids = [item for metric in loaded.metrics for item in metric.question_ids]
        self.assertEqual(ids, [f"s{n:02}" for n in range(1, 29)])
        by_id = {metric.metric_id: metric for metric in loaded.metrics}
        self.assertEqual(by_id["S08"].question_ids, ("s25",))
        self.assertEqual(by_id["S07"].question_ids, ("s24",))
        self.assertEqual({metric.metric_id: metric.external_source_id for metric in loaded.metrics if metric.external_source_id},
                         {"S03": "us2026-stranger-fear", "S04": "us2026-nonsocial-fear"})
        self.assertEqual((by_id["S03"].alias, by_id["S04"].alias), ("SF", "NF"))
        self.assertEqual({(source.alias, source.mean, source.standard_deviation, source.valid_n, source.total_n) for source in loaded.external_sources},
                         {("SF", 0.66, 0.91, 42926, 43517), ("NF", 1.03, 0.78, 42764, 43517)})
        self.assertEqual(loaded.delivery.sha256, "6e52a3ad3cb00cffa9675521d956af8f2e446fcf298d519384106e68a803bcfa")

    def test_t01_mapping_covers_policy_domains_and_q25_standalone(self):
        catalog = SurveyCatalogV3.model_validate_json((RESOURCES / "catalogs/survey-v3.json").read_bytes())
        result = survey_scores_v4(session(answers()), catalog)
        groups = [domain.question_ids for domain in result.domains] + [(result.standalone.item_id,)]
        self.assertEqual(sorted(groups), sorted(metric.question_ids for metric in mapping.load().metrics))
        self.assertEqual(len(result.domains), 8, "an implementation that only iterates domains misses Q25")

    def test_t02_t03_values_status_and_reverse_scoring(self):
        loaded = mapping.load()
        self.assertEqual(mapping.evaluate(answers(s10=0, s11=0), loaded)["S03"], {"status": "valid", "numerator": 0, "denominator": 2})
        self.assertEqual(mapping.evaluate(answers(s10=0, s11=None), loaded)["S03"]["status"], "insufficient")
        self.assertEqual(mapping.evaluate(answers(s10=5, s11=1), loaded)["S03"]["status"], "input_check")
        self.assertEqual(mapping.evaluate(answers(s10=0.5, s11=1), loaded)["S03"]["status"], "input_check")
        self.assertEqual(mapping.evaluate(answers(s10="1", s11=1), loaded)["S03"]["status"], "input_check")
        reverse = mapping.evaluate(answers(s26=1, s27=3, s28=5), loaded)["S09"]
        self.assertEqual((reverse["numerator"], reverse["denominator"]), (9, 3))
        single = mapping.evaluate(answers(s24=None, s25=4, s26=None), loaded)
        self.assertEqual((single["S07"]["status"], single["S08"], single["S09"]["status"]),
                         ("insufficient", {"status": "valid", "numerator": 4, "denominator": 1}, "insufficient"))
        catalog = SurveyCatalogV3.model_validate_json((RESOURCES / "catalogs/survey-v3.json").read_bytes())
        survey = survey_scores_v4(session(answers(s26=1, s27=3, s28=5)), catalog)
        self.assertEqual([item.raw for item in survey.items if item.item_id in ("s26", "s27", "s28")], [1, 3, 5])
        for domain in survey.domains:
            metric = next(metric for metric in loaded.metrics if metric.question_ids == domain.question_ids)
            expected = mapping.evaluate(answers(s26=1, s27=3, s28=5), loaded)[metric.metric_id]
            self.assertEqual((domain.numerator, domain.denominator), (expected["numerator"], expected["denominator"]))

    def test_t11_tampered_or_mismatched_mapping_is_rejected(self):
        document = json.loads(mapping.raw())
        broken = []
        swapped = json.loads(json.dumps(document)); swapped["metrics"][0]["question_ids"] = ["s01", "s02", "s03", "s04", "s05"]
        broken.append(swapped)
        value = json.loads(json.dumps(document)); value["external_sources"][0]["mean"] = 0.67
        broken.append(value)
        scale = json.loads(json.dumps(document)); scale["metrics"][2]["scale_minimum"] = 1
        broken.append(scale)
        extra = json.loads(json.dumps(document)); extra["metrics"][0]["external_source_id"] = "us2026-stranger-fear"
        broken.append(extra)
        reverse = json.loads(json.dumps(document)); reverse["metrics"][8]["aggregation"] = "mean"
        broken.append(reverse)
        for item in broken:
            with self.subTest(item=item["metrics"][0]["question_ids"]), patch.object(mapping, "raw", return_value=encode(item).encode()):
                with self.assertRaises(ValueError):
                    mapping.load()

    def test_t22_existing_source_and_survey_assets_are_unchanged_and_not_extended(self):
        for name, digest in PRESERVED.items():
            self.assertEqual(hashlib.sha256((RESOURCES / name).read_bytes()).hexdigest(), digest, name)
        self.assertEqual(comparisons._sources()[1], PRESERVED["report/comparison-sources-v4.json"])
        self.assertNotIn(mapping.ASSET, comparisons.assets())
        self.assertNotIn("resources/" + mapping.ASSET, comparisons.assets())

    def test_runtime_asset_is_required_for_release(self):
        from app.launcher import REQUIRED
        self.assertIn("resources/" + mapping.ASSET, REQUIRED)
        self.assertFalse([name for name in REQUIRED if name.endswith(".xlsx")])


@unittest.skipUnless((REPO_ROOT / "docs/참고자료" / DELIVERY).is_file() or os.environ.get("KDOG_COMPARISON_DELIVERY"),
                     "owner-provided delivery workbook is local-only")
class DeliveryWorkbookTests(unittest.TestCase):
    def test_t24_committed_mapping_matches_local_delivery_cells(self):
        import openpyxl
        path = Path(os.environ.get("KDOG_COMPARISON_DELIVERY") or REPO_ROOT / "docs/참고자료" / DELIVERY)
        loaded = mapping.load()
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), loaded.delivery.sha256, "delivery workbook differs; confirm a corrected edition")
        self.assertEqual(path.stat().st_size, loaded.delivery.size)
        book = openpyxl.load_workbook(path, data_only=True)
        rules, table = book.worksheets
        for row, metric in zip(range(13, 22), loaded.metrics):
            listed = [f"s{int(part.strip()[1:]):02}" for part in rules[f"C{row}"].value.split("·")]
            self.assertEqual(tuple(listed), metric.question_ids)
            self.assertEqual(rules[f"B{row}"].value, metric.title)
            self.assertTrue(rules[f"A{row}"].value.startswith(metric.metric_id))
        for row, source in zip((46, 47), loaded.external_sources):
            self.assertEqual((table[f"A{row}"].value, table[f"C{row}"].value, table[f"D{row}"].value, table[f"E{row}"].value, table[f"G{row}"].value),
                             (source.alias, source.mean, source.standard_deviation, source.valid_n, source.total_n))
        self.assertEqual(rules["A3"].value.split("|")[0].split()[-1], "EXT1.1")
        self.assertIn("EXT1.0", table["C55"].value)
        for key, row in (("TXT-H", 44), ("TXT-L", 45), ("TXT-E", 46), ("TXT-M", 47), ("TXT-V", 48), ("TXT-I", 49)):
            source = rules[f"C{row}"].value.strip("“”")
            expected = loaded.sentences[key].replace("{domain}", "{영역}").replace("{ours}", "{우리값}").replace("{reference}", "{연구값}")
            self.assertEqual(source, expected)


class DefinitionMappingTests(comparison_fixture.ComparisonFixture):
    def test_t15_t20_saved_definition_is_checked_against_delivery_without_override(self):
        pointer, _ = external_fixture.define(self.store, user=SimpleNamespace(username="reviewer"))
        inventory = comparisons.definition_inventory(self.store, self.user)
        self.assertIsNone(inventory["mapping_mismatches"][external_fixture.SOURCE])
        self.assertEqual(inventory["mapping"]["version"], mapping.VERSION)
        self.assertEqual(comparisons.definition_document(self.store, pointer).actor, "reviewer")
        document = comparisons.definition_document(self.store, pointer)
        changed = comparisons.ComparisonDefinitionInputV4.model_validate_json(encode({**{key: value for key, value in document.model_dump(mode="json").items()
            if key not in ("definition_id", "revision", "actor", "recorded_at", "artifact_kind")}, "values": {**document.values.model_dump(mode="json"), "mean": 0.7},
            "reason": "SYNTHETIC CORRECTION"}))
        corrected = comparisons.save_definition(self.store, comparisons.SaveDefinitionV4(expected_revision=1, document=changed), self.user)
        inventory = comparisons.definition_inventory(self.store, self.user)
        self.assertIn("평균", inventory["mapping_mismatches"][external_fixture.SOURCE])
        self.assertEqual(comparisons.definition_document(self.store, corrected).values.mean, 0.7, "mapping never rewrites saved numbers")
        with self.store.connect(write=True) as db:
            db.execute("UPDATE users SET active=0 WHERE username='operator'")
        with self.assertRaises(HTTPException):
            comparisons.definition_inventory(self.store, self.user)
