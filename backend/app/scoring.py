"""42-item arithmetic mirroring 03 `여러쌍비교!D6:Z6` and 01 §4. Formulas live here; thresholds, item roles, labels and trial-validity rules come from scoring-v2.json."""

from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path

from app.domain.catalog import BehaviorCatalog, SurveyCatalog
from app.domain.contracts import (
    DomainSummary, INDICATOR_KEYS, Indicator, ScoreResult, ScoreSheet, SeparationType, SurveyAnswers,
    SurveyDomainScore, SurveyItemValue, SurveyResult, TypeResult,
)
from app.domain.validation import validate_score_sheet, validate_survey_answers

RULES = json.loads((Path(__file__).resolve().parents[2] / "resources/rules/scoring-v2.json").read_text(encoding="utf-8"))
CENTER = Decimal(RULES["center"])


def rounded(value):
    """Excel ROUND(x, 2): half away from zero, applied only where the workbook rounds."""
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if value is not None else None


def average(values):
    return sum(values, Decimal(0)) / len(values) if values else None


def distance(score):
    return abs(Decimal(score) - CENTER)


def behavior_scores(sheet: ScoreSheet, catalog: BehaviorCatalog, *, mode="production") -> ScoreResult:
    validate_score_sheet(sheet, catalog, mode=mode)
    if catalog.version != RULES["catalog_version"]:
        raise ValueError("scoring-v2 is defined for catalog-20260913-v2 only")
    entries = {entry.item_id: entry for entry in sheet.items}
    scored = {item_id: entry.score for item_id, entry in entries.items() if entry.status == "scored"}

    # Trial validity (R5, R6): a compliance item at its invalid score removes that trial's items from every calculation.
    excluded, voided_indicators, voided_types = {}, {}, {}
    for rule in RULES["invalidation"].values():
        if scored.get(rule["item"]) == rule["invalid_score"]:
            reason = f"{rule['item']} = {rule['invalid_score']}: 시행 무효"
            excluded.update({item_id: reason for item_id in rule["excludes"]})
            voided_indicators.update({key: reason for key in rule["voids_indicators"]})
            voided_types.update({key: reason for key in rule["voids_types"]})

    def value(item_id):
        return None if item_id in excluded else scored.get(item_id)

    def role(name):
        return value(RULES["roles"][name])

    domains = []
    for domain in RULES["domain_output"]:
        members = [item for item in catalog.items if item.domain == domain]
        usable = [item for item in members if item.item_id not in excluded]
        states = [entries[item.item_id].status for item in usable]
        live = [item for item in usable if item.item_id in scored]
        means = [Decimal(scored[item.item_id]) for item in live if item.scale in RULES["mean_scales"]]
        widths = [distance(scored[item.item_id]) for item in live if item.scale in RULES["width_scales"]]
        degrees = [Decimal(scored[item.item_id]) for item in live if item.scale in RULES["degree_scales"]]
        mean = average(means)
        domains.append(DomainSummary(
            domain=domain, target_count=len(members), scored_count=len(live),
            unreadable_count=states.count("unreadable"), not_applicable_count=states.count("not_applicable"),
            excluded_count=len(members) - len(usable),
            mean=rounded(mean), lean=rounded(mean - CENTER) if mean is not None else None,
            width=int(max(widths)) if widths else None, degree=rounded(average(degrees)),
        ))

    def derived(key, needed, compute, voided):
        if key in voided:
            return None, "invalid", voided[key]
        missing = [RULES["roles"][name] for name in needed if role(name) is None]
        if missing:
            return None, "missing", "미판독: " + ", ".join(missing)
        return compute(), "calculated", None

    indicators = []
    formulas = {
        "adaptation": (("baseline_arousal", "ignore_arousal"),
                       lambda: distance(role("baseline_arousal")) - distance(role("ignore_arousal"))),
        "recovery": (("alone_arousal", "reunion_calm"),
                     lambda: distance(role("alone_arousal")) - distance(role("reunion_calm"))),
        "stranger_calming": (("alone_arousal", "stranger_arousal"),
                             lambda: distance(role("alone_arousal")) - distance(role("stranger_arousal"))),
        "sync_rate": (("sync_phase_count",), lambda: Decimal(role("sync_phase_count")) / 6),
    }
    for key in INDICATOR_KEYS:
        needed, compute = formulas[key]
        result, status, reason = derived(key, needed, compute, voided_indicators)
        indicators.append(Indicator(key=key, value=float(result) if result is not None else None, status=status, reason=reason))

    attachment, sociability = RULES["types"]["attachment"], RULES["types"]["sociability_person"]

    def attachment_label():
        if role(attachment["consistency_item"]) >= attachment["consistency_threshold"]:
            return attachment["labels"]["inconsistent"]
        degree = average([Decimal(role(name)) for name in attachment["degree_items"]])
        side = "low" if degree <= Decimal(str(attachment["degree_threshold"])) else "high"
        calm = "calm" if distance(role(attachment["calm_item"])) <= attachment["calm_tolerance"] else "restless"
        return attachment["labels"][f"{side}_{calm}"]

    def sociability_label():
        side = "high" if role(sociability["affiliation_item"]) >= sociability["affiliation_threshold"] else "low"
        calm = "calm" if distance(role(sociability["arousal_item"])) <= sociability["calm_tolerance"] else "restless"
        return sociability["labels"][f"{side}_{calm}"]

    types = []
    for key, rule, compute in (("attachment", attachment, attachment_label), ("sociability_person", sociability, sociability_label)):
        label, status, reason = derived(key, rule["required"], compute, voided_types)
        types.append(TypeResult(key=key, label=label, status=status, reason=reason))

    return ScoreResult(
        sheet_id=sheet.sheet_id, catalog_version=catalog.version, scoring_rule_version=RULES["version"], rater=sheet.rater,
        items=tuple(entries[item.item_id] for item in catalog.rated_items()), baseline_arousal=role("baseline_arousal"),
        domains=tuple(domains), indicators=tuple(indicators), types=tuple(types),
    )


def survey_scores(answers: SurveyAnswers, catalog: SurveyCatalog) -> SurveyResult:
    validate_survey_answers(answers, catalog)
    if catalog.version != RULES["catalog_version"]:
        raise ValueError("scoring-v2 is defined for catalog-20260913-v2 only")
    rules = RULES["survey"]
    items = []
    for item in catalog.items:
        raw = answers.answers[item.item_id]
        converted = None if raw is None else 6 - raw if item.item_id in rules["reverse_items"] else raw
        items.append(SurveyItemValue(item_id=item.item_id, raw=raw, converted=converted,
                                     not_applicable=item.item_id in answers.not_applicable))
    converted = {item.item_id: item.converted for item in items}
    domains = []
    for domain, ids in rules["domain_means"].items():
        values = [Decimal(converted[item_id]) for item_id in ids if converted[item_id] is not None]
        domains.append(SurveyDomainScore(
            domain=domain, mean=rounded(average(values)), answered_count=len(values), target_count=len(ids),
            status="missing" if not values else "calculated" if len(values) == len(ids) else "partial"))
    separation = rules["separation"]
    resistance_values = [converted[item_id] for item_id in separation["resistance_items"]]
    recovery = converted[separation["recovery_item"]]
    if None in resistance_values or recovery is None:
        missing = [item_id for item_id in (*separation["resistance_items"], separation["recovery_item"]) if converted[item_id] is None]
        result = SeparationType(resistance=None, recovery=None, label=None, status="missing", reason="미응답: " + ", ".join(missing))
    else:
        resistance = average([Decimal(v) for v in resistance_values])
        side = "high" if resistance >= Decimal(str(separation["resistance_threshold"])) else "low"
        result = SeparationType(resistance=float(resistance), recovery=recovery, status="calculated",
                                label=separation["labels"][f"{side}_{'high' if recovery in separation['recovery_high'] else 'low'}"])
    answered = sum(item.raw is not None for item in items)
    return SurveyResult(catalog_version=catalog.version, scoring_rule_version=RULES["version"], items=tuple(items),
                        domains=tuple(domains), separation=result,
                        status="unregistered" if answered == 0 else "calculated" if answered == len(items) else "partial")
