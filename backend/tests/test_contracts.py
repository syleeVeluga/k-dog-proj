"""42-item contracts: three-state scores, rater sheets, segment timing, survey answers and derived results."""

import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from app.domain.catalog import BehaviorCatalog, SEGMENTS, SURVEY_IDS, SurveyCatalog
from app.domain.contracts import (
    DomainSummary, Indicator, ItemScore, Rater, ScoreResult, ScoreSheet, SegmentWindow, SeparationType,
    SessionSegments, SurveyAnswers, SurveyDomainScore, SurveyItemValue, SurveyResult, TypeResult,
)
from app.domain.validation import validate_score_sheet, validate_segments, validate_survey_answers

ROOT = Path(__file__).resolve().parents[2]
RATER = Rater(rater_id="human-01", kind="human", label="채점자 A")


def parse(model, value):
    return model.model_validate_json(json.dumps(value, ensure_ascii=False))


def unreadable(item_id, reason="가상 시험: 관찰 없음"):
    return {"item_id": item_id, "score": None, "status": "unreadable", "reason": reason}


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = BehaviorCatalog.model_validate_json((ROOT / "resources/catalogs/behavior-v2.json").read_bytes())
        cls.survey_catalog = SurveyCatalog.model_validate_json((ROOT / "resources/catalogs/survey-v2.json").read_bytes())

    def sheet(self, overrides=None, items=None):
        entries = {item.item_id: unreadable(item.item_id) for item in self.catalog.rated_items()}
        for item_id, score in (overrides or {}).items():
            entries[item_id] = {"item_id": item_id, "score": score, "status": "scored", "reason": None}
        return parse(ScoreSheet, {
            "sheet_id": "sheet-1", "case_id": "case-1", "session_id": "session-1",
            "catalog_version": self.catalog.version, "rater": RATER.model_dump(mode="json"),
            "recorded_at": "2026-09-16T10:00:00+09:00", "items": items if items is not None else list(entries.values()),
        })

    def segments(self, **changes):
        windows = []
        for index, (segment, _) in enumerate(SEGMENTS):
            windows.append({"segment": segment, "start_sec": float(index * 20), "end_sec": float(index * 20 + 15),
                            "source": "operator_confirmed"})
        data = {"session_id": "session-1", "video_id": "video-1", "windows": windows, **changes}
        return parse(SessionSegments, data)

    def test_item_score_three_states(self):
        self.assertEqual(ItemScore(item_id="BS-04", score=0, status="scored").score, 0)  # 0회 is an observation
        for bad in ({"item_id": "BS-04", "score": None, "status": "scored", "reason": None},
                    {"item_id": "BS-04", "score": 1, "status": "unreadable", "reason": "x"},
                    {"item_id": "BS-04", "score": None, "status": "unreadable", "reason": None},
                    {"item_id": "BS-04", "score": None, "status": "not_applicable", "reason": None},
                    {"item_id": "BS-04", "score": True, "status": "scored", "reason": None},
                    {"item_id": "BS-04", "score": -1, "status": "scored", "reason": None},
                    {"item_id": "BS-17", "score": 3, "status": "scored", "reason": None}):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                parse(ItemScore, bad)
        parse(ItemScore, {"item_id": "OWN-05", "score": None, "status": "not_applicable", "reason": "개가 버틴 장면이 없음"})

    def test_sheet_holds_exactly_the_rated_items(self):
        sheet = self.sheet({"BS-01": 3, "DOG-03": 5, "OWN-04": 4, "DOG-21": 6, "BS-04": 0, "OWN-08": 1})
        validate_score_sheet(sheet, self.catalog)
        items = [item.model_dump(mode="json") for item in sheet.items]
        for variant in (items[:-1], items + [unreadable("DOG-22")], items[:-1] + [unreadable("DOG-22")]):
            with self.subTest(count=len(variant)), self.assertRaises(ValueError):
                validate_score_sheet(self.sheet(items=variant), self.catalog)
        with self.assertRaises(ValidationError):
            self.sheet(items=items + [items[0]])
        with self.assertRaises(ValueError):
            validate_score_sheet(self.sheet(), self.catalog.model_copy(update={"version": "other"}))

    def test_scored_values_must_be_labelled(self):
        for item_id, score in (("DOG-03", 4), ("DOG-24", 1), ("OWN-04", 2), ("OWN-08", 4), ("OWN-09", 5), ("DOG-21", 7), ("BS-01", 0)):
            with self.subTest(item=item_id, score=score), self.assertRaises(ValueError):
                validate_score_sheet(self.sheet({item_id: score}), self.catalog)
        validate_score_sheet(self.sheet({"BS-06": 4, "DOG-16": 2}), self.catalog)  # counts are open integers

    def test_test_catalog_requires_explicit_test_mode(self):
        fixture = self.catalog.model_copy(update={"provenance": "test_fixture"})
        with self.assertRaises(ValueError):
            validate_score_sheet(self.sheet(), fixture)
        validate_score_sheet(self.sheet(), fixture, mode="test")

    def test_sheet_timestamp_must_be_iso(self):
        with self.assertRaises(ValidationError):
            parse(ScoreSheet, {**self.sheet().model_dump(mode="json"), "recorded_at": "16/09/2026"})

    def test_segments_are_eight_ordered_windows(self):
        segments = self.segments()
        self.assertTrue(segments.confirmed())
        validate_segments(segments, 160.0)
        with self.assertRaises(ValueError):
            validate_segments(segments, 150.0)
        windows = [window.model_dump(mode="json") for window in segments.windows]
        for variant in (windows[:-1], windows[1:] + windows[:1], [{**windows[0], "end_sec": 25.0}] + windows[1:]):
            with self.subTest(variant=len(variant)), self.assertRaises(ValidationError):
                self.segments(windows=variant)
        with self.assertRaises(ValidationError):
            SegmentWindow(segment="entry", start_sec=5.0, end_sec=4.0, source="ai_proposed")
        proposed = self.segments(windows=[{**windows[0], "source": "ai_proposed"}] + windows[1:])
        self.assertFalse(proposed.confirmed())

    def test_survey_answers_complete_and_not_applicable_is_missing(self):
        answers = {item_id: 3 for item_id in SURVEY_IDS}
        parsed = parse(SurveyAnswers, {"answers": {**answers, "s07": None}, "not_applicable": ["s07"]})
        validate_survey_answers(parsed, self.survey_catalog)
        for bad in ({"answers": {k: v for k, v in answers.items() if k != "s28"}},
                    {"answers": {**answers, "s29": 3}},
                    {"answers": {**answers, "s01": 0}},
                    {"answers": {**answers, "s01": True}},
                    {"answers": answers, "not_applicable": ["s07"]},
                    {"answers": {**answers, "s07": None}, "not_applicable": ["s07", "s07"]}):
            with self.subTest(bad=list(bad.get("not_applicable", []))), self.assertRaises(ValidationError):
                parse(SurveyAnswers, bad)
        with self.assertRaises(ValueError):
            validate_survey_answers(parse(SurveyAnswers, {"answers": {**answers, "s10": None}, "not_applicable": ["s10"]}),
                                    self.survey_catalog)

    def test_domain_summary_invariants(self):
        base = dict(domain="EDU", target_count=5, scored_count=2, unreadable_count=3, not_applicable_count=0, excluded_count=0,
                    mean=3.0, lean=0.0, width=1, degree=None)
        DomainSummary(**base)
        empty = {**base, "scored_count": 0, "unreadable_count": 5, "mean": None, "lean": None, "width": None}
        DomainSummary(**empty)
        for changes in ({"unreadable_count": 2}, {"lean": None}, {"width": 3}, {"scored_count": 0, "unreadable_count": 5, "mean": None, "lean": None}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                DomainSummary(**{**base, **changes})

    def test_indicator_and_type_states(self):
        Indicator(key="recovery", value=1.0, status="calculated")
        Indicator(key="sync_rate", value=None, status="invalid", reason="걷기 시행 유효성 3")
        TypeResult(key="attachment", label="안정", status="calculated")
        TypeResult(key="sociability_person", label=None, status="missing", reason="낯선 각성 미판독")
        for bad in (dict(key="recovery", value=None, status="calculated"), dict(key="recovery", value=1.0, status="missing", reason="x"),
                    dict(key="recovery", value=None, status="missing")):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                Indicator(**bad)
        for bad in (dict(key="attachment", label="Secure", status="calculated"), dict(key="attachment", label="편안·우호", status="calculated"),
                    dict(key="attachment", label=None, status="calculated"), dict(key="attachment", label=None, status="invalid")):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                TypeResult(**bad)

    def test_score_result_shape(self):
        items = [unreadable(item.item_id) for item in self.catalog.rated_items()]
        domains = [dict(domain=code, target_count=count, scored_count=0, unreadable_count=count, not_applicable_count=0,
                        excluded_count=0, mean=None, lean=None, width=None, degree=None)
                   for code, count in (("SOC_E", 5), ("SOC_H", 4), ("ATT", 9), ("SYN", 3), ("EDU", 5), ("EXIT", 2))]
        indicators = [dict(key=key, value=None, status="missing", reason="미판독") for key in ("adaptation", "recovery", "stranger_calming", "sync_rate")]
        types = [dict(key=key, label=None, status="missing", reason="미판독") for key in ("attachment", "sociability_person")]
        data = dict(sheet_id="sheet-1", catalog_version=self.catalog.version, scoring_rule_version="scoring-v2",
                    rater=RATER.model_dump(mode="json"), items=items, baseline_arousal=None, domains=domains,
                    indicators=indicators, types=types)
        result = parse(ScoreResult, data)
        self.assertEqual(ScoreResult.model_validate_json(result.model_dump_json()), result)
        for changes in ({"items": items[::-1]}, {"items": items + items[:1]}, {"items": []}, {"domains": domains[:-1]},
                        {"indicators": indicators[::-1]}, {"types": types[:1]}, {"baseline_arousal": 0}):
            with self.subTest(changes=list(changes)), self.assertRaises(ValidationError):
                parse(ScoreResult, {**data, **changes})
        self.assertFalse({"total", "overall_reference", "rank"} & set(ScoreResult.model_fields))

    def test_survey_result_shape_has_no_total(self):
        items = [dict(item_id=item_id, raw=None, converted=None, not_applicable=item_id == "s07") for item_id in SURVEY_IDS]
        domains = [dict(domain=domain, mean=None, answered_count=0, target_count=count, status="missing")
                   for domain, count in (("A", 9), ("B", 5), ("C", 7), ("E", 3))]
        separation = dict(resistance=None, recovery=None, label=None, status="missing", reason="미응답")
        data = dict(catalog_version=self.survey_catalog.version, scoring_rule_version="scoring-v2", items=items,
                    domains=domains, separation=separation, status="unregistered")
        parse(SurveyResult, data)
        self.assertFalse({"total", "overall_reference"} & set(SurveyResult.model_fields))
        for changes in ({"status": "calculated"}, {"domains": domains + [dict(domain="A", mean=None, answered_count=0, target_count=9, status="missing")]},
                        {"items": items[:-1]}):
            with self.subTest(changes=list(changes)), self.assertRaises(ValidationError):
                parse(SurveyResult, {**data, **changes})
        for bad in (dict(item_id="s01", raw=3, converted=None, not_applicable=False), dict(item_id="s07", raw=3, converted=3, not_applicable=True)):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                SurveyItemValue(**bad)
        for bad in (dict(domain="A", mean=3.0, answered_count=9, target_count=9, status="partial"),
                    dict(domain="D", mean=3.0, answered_count=4, target_count=4, status="calculated"),
                    dict(domain="A", mean=None, answered_count=3, target_count=9, status="partial")):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                SurveyDomainScore(**bad)
        SeparationType(resistance=3.5, recovery=4, label="안정", status="calculated")
        with self.assertRaises(ValidationError):
            SeparationType(resistance=3.5, recovery=None, label="안정", status="calculated")

    def test_core_models_generate_json_schema(self):
        for model in (ItemScore, ScoreSheet, SessionSegments, SurveyAnswers, ScoreResult, SurveyResult):
            with self.subTest(model=model.__name__):
                schema = model.model_json_schema()
                self.assertFalse(schema["additionalProperties"])
                self.assertEqual(json.loads(json.dumps(schema)), schema)


if __name__ == "__main__":
    unittest.main()
