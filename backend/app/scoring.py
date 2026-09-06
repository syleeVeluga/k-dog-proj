"""Versioned S5 arithmetic; no inferred assessment boundaries or report mapping."""

from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path

from app.domain.contracts import DomainScore, ScoreResult, SURVEY_IDS
from app.domain.validation import resolve_branch_scores
from app.evaluation_models import SurveyGroup, SurveyResult, SurveyValue


RULES = json.loads((Path(__file__).resolve().parents[2] / "resources/rules/scoring-v1.json").read_text(encoding="utf-8"))


def rounded(value):
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if value is not None else None


def average(values):
    return sum(values, Decimal(0)) / len(values) if values else None


def behavior_scores(run, branches, catalog, evidence):
    if run.scoring_rule_version != RULES["version"]:
        raise ValueError("unsupported scoring rule version")
    if len({branch.branch for branch in branches}) != len(branches):
        raise ValueError("duplicate scoring branch")
    resolved = {score.item_id: score for branch in branches for score in resolve_branch_scores(run, branch, catalog, evidence)}
    items = tuple(resolved[item.item_id] for item in catalog.items if item.item_id in resolved)
    mapping = {item.item_id: item.domain for item in catalog.items}
    domains = []
    for domain in ("EDU", "SOC_P", "SOC_D", "SOC_E", "ATT", "CON", "TRN"):
        valid = [item for item in items if mapping[item.item_id] == domain and item.status == "scored"]
        values = [Decimal(str(item.raw_score)) for item in valid]
        a, b = (sum((Decimal(str(item.raw_score)) for item in valid if item.direction == direction), Decimal(0))
                for direction in ("A", "B"))
        domains.append(DomainScore(domain=domain, mean=rounded(average(values)),
            maximum=float(max(values)) if values else None, valid_count=len(valid),
            target_count=sum(item.domain == domain for item in catalog.items),
            direction="A" if a > b else "B" if b > a else None,
            direction_a_sum=float(a), direction_b_sum=float(b)))
    return ScoreResult(run_id=run.run_id, catalog_version=catalog.version, scoring_rule_version=RULES["version"],
                       items=items, domains=tuple(domains))


def survey_scores(run_id, answers, catalog):
    if set(answers) != set(SURVEY_IDS) or any(value is not None and (type(value) is not int or value not in range(1, 6))
                                             for value in answers.values()):
        raise ValueError("survey requires exactly 30 valid raw answers")
    items = []
    for item in catalog.items:
        raw = answers[item.item_id]
        converted = None if raw is None or item.item_id == "q23" else 6 - raw if item.item_id in RULES["reverse_items"] else raw
        items.append(SurveyValue(item_id=item.item_id, raw=raw, converted=converted, source_layer=item.source_layer,
                                status="missing" if raw is None else "rule_pending" if item.item_id == "q23" else "calculated"))
    converted = {item.item_id: item.converted for item in items}
    means, groups = {}, []
    for name, ids in RULES["survey_groups"].items():
        values = [Decimal(converted[item]) for item in ids if converted[item] is not None]
        means[name] = average(values) if len(values) == len(ids) else None
        groups.append(SurveyGroup(group=name, mean=rounded(means[name]), valid_count=len(values),
                                  target_count=len(ids), status="calculated" if means[name] is not None else "missing"))
    # C-2 membership itself is unresolved, so even its denominator is not asserted.
    groups.append(SurveyGroup(group="C-2", mean=None, valid_count=0, target_count=None, status="rule_pending"))
    overall = [means[group] for group in RULES["overall_groups"]]
    return SurveyResult(run_id=run_id, catalog_version=catalog.version, scoring_rule_version=RULES["version"],
        items=items, groups=groups, overall_reference=rounded(average(overall)) if all(v is not None for v in overall) else None,
        status="unregistered" if all(v is None for v in answers.values()) else "partial" if any(v is None for v in answers.values()) else "calculated")
