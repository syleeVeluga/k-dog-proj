"""Confirmed survey→metric comparison mapping (delivered EXT1.1); no runtime workbook parsing."""
import hashlib
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from . import analysis
from .domain.catalog_v3 import SurveyCatalogV3
from .domain.catalog_v4 import RESOURCES, RUNTIME_SURVEY_POLICY_VERSION, SURVEY_VERSION, ContractV4, Hash, Text
from .survey_v4 import load_survey_policy_v4

ASSET = "report/survey-comparison-20261008.json"
VERSION = "survey-comparison-20261008-ext1.1"
METRIC_IDS = tuple(f"S{n:02}" for n in range(1, 10))
QuestionId = Annotated[str, Field(pattern=r"^s(0[1-9]|1[0-9]|2[0-8])$")]


class DeliveryV4(ContractV4):
    filename: Text
    sha256: Hash
    size: Annotated[int, Field(ge=1)]
    edition: Literal["EXT1.1"]
    delivered_at: Text
    locations: Annotated[tuple[Text, ...], Field(min_length=1)]
    edition_note: Text


class MetricV4(ContractV4):
    metric_id: Literal["S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09"]
    alias: Literal["SF", "NF"] | None
    title: Text
    question_ids: Annotated[tuple[QuestionId, ...], Field(min_length=1)]
    aggregation: Literal["mean", "reverse_mean", "single_raw"]
    scale_minimum: int
    scale_maximum: int
    direction: Literal["higher_more_agreement", "higher_more_fear", "higher_more_consistency"]
    missing_policy: Literal["complete_group_required", "single_response_required"]
    external_source_id: Text | None
    location: Text


class ExternalMappingV4(ContractV4):
    source_id: Text
    metric_id: Literal["S03", "S04"]
    alias: Literal["SF", "NF"]
    subscale: Text
    mean: float
    standard_deviation: Annotated[float, Field(ge=0)]
    valid_n: Annotated[int, Field(ge=1)]
    total_n: Annotated[int, Field(ge=1)]
    location: Text


class ComparisonMappingV4(ContractV4):
    artifact_kind: Literal["survey-comparison-mapping"] = "survey-comparison-mapping"
    version: Literal["survey-comparison-20261008-ext1.1"]
    survey_version: Literal["survey-20260929-v3"]
    policy_version: Literal["survey-policy-20261007-rp01"]
    delivery: DeliveryV4
    metrics: tuple[MetricV4, ...]
    external_sources: tuple[ExternalMappingV4, ...]
    sentences: dict[Literal["TXT-H", "TXT-L", "TXT-E", "TXT-M", "TXT-V", "TXT-I"], Text]
    external_limitation: Text
    cumulative_label: Text
    cumulative_note: Text
    minimum_cumulative_n: Literal[2]

    @model_validator(mode="after")
    def partition(self) -> Self:
        if tuple(metric.metric_id for metric in self.metrics) != METRIC_IDS:
            raise ValueError("comparison mapping must list S01-S09 exactly once in order")
        ids = [item for metric in self.metrics for item in metric.question_ids]
        if ids != [f"s{n:02}" for n in range(1, 29)]:
            raise ValueError("every survey question belongs to exactly one metric")
        if len(self.sentences) != 6:
            raise ValueError("all fixed comparison sentences are required")
        linked = {metric.external_source_id: metric for metric in self.metrics if metric.external_source_id}
        if (set(linked) != {source.source_id for source in self.external_sources} or len(linked) != len(self.external_sources)
                or sum(bool(metric.external_source_id) for metric in self.metrics) != len(linked)):
            raise ValueError("external references attach only to their mapped metric")
        for source in self.external_sources:
            metric = linked[source.source_id]
            if (metric.metric_id, metric.alias) != (source.metric_id, source.alias) or not metric.scale_minimum <= source.mean <= metric.scale_maximum:
                raise ValueError("external reference differs from its metric")
            if source.valid_n > source.total_n:
                raise ValueError("subscale valid n cannot exceed total study n")
        return self


def raw():
    return (RESOURCES / ASSET).read_bytes()


def asset_hash():
    return hashlib.sha256(raw()).hexdigest()


def load():
    """Load and cross-check against the committed survey catalog, RP01 policy and source asset."""
    data = raw()
    mapping = ComparisonMappingV4.model_validate_json(data)
    catalog = SurveyCatalogV3.model_validate_json((RESOURCES / "catalogs/survey-v3.json").read_bytes())
    policy = load_survey_policy_v4(RUNTIME_SURVEY_POLICY_VERSION)
    if (mapping.survey_version, mapping.policy_version) != (SURVEY_VERSION, policy.version) or catalog.version != SURVEY_VERSION:
        raise ValueError("comparison mapping survey edition or policy differs")
    if tuple(metric.question_ids for metric in mapping.metrics) != tuple(group.question_ids for group in policy.groups):
        raise ValueError("comparison metrics must keep the survey policy groups")
    questions = {item.item_id: item for item in catalog.items}
    for metric, group in zip(mapping.metrics, policy.groups):
        reverse = {questions[item].reverse_scored for item in metric.question_ids}
        allowed = {value for item in metric.question_ids for value in questions[item].allowed_values}
        if metric.aggregation != group.aggregation or reverse != {metric.aggregation == "reverse_mean"}:
            raise ValueError("comparison metric aggregation or reverse scoring differs from policy")
        if (min(allowed), max(allowed)) != (metric.scale_minimum, metric.scale_maximum) or len(allowed) != metric.scale_maximum - metric.scale_minimum + 1:
            raise ValueError("comparison metric scale differs from the survey catalog")
    from .comparisons_v4 import _sources
    sources = {item["source_id"]: item for item in _sources()[0]["sources"]}
    for source in mapping.external_sources:
        metric = next(item for item in mapping.metrics if item.metric_id == source.metric_id)
        known = sources.get(source.source_id)
        if known is None or (tuple(known["question_ids"]), known["scale_minimum"], known["scale_maximum"], known["direction"], known["aggregation"]) != (
                metric.question_ids, metric.scale_minimum, metric.scale_maximum, metric.direction, metric.aggregation):
            raise ValueError("comparison external mapping differs from its source definition")
        if known["reference_values"] != {"mean": source.mean, "standard_deviation": source.standard_deviation,
                                         "valid_n": source.valid_n, "total_n": source.total_n}:
            raise ValueError("comparison external values differ from the recorded source table")
    return mapping


def question_signature():
    """Identity of the question text/options/direction that a mapped submission must share."""
    catalog = SurveyCatalogV3.model_validate_json((RESOURCES / "catalogs/survey-v3.json").read_bytes())
    return analysis.digest([{"id": item.item_id, "text": item.text, "allowed_values": item.allowed_values,
                             "reverse_scored": item.reverse_scored} for item in catalog.items])


def public():
    mapping = load()
    return {"version": mapping.version, "asset_hash": asset_hash(), "delivery": mapping.delivery.model_dump(mode="json"),
            "metrics": [metric.model_dump(mode="json") for metric in mapping.metrics],
            "external_sources": [source.model_dump(mode="json") for source in mapping.external_sources]}


def evaluate(answers, mapping=None):
    """Per-metric individual status from raw answers: valid / insufficient / input_check.

    Only exact integers inside the catalog options are valid; None is a missing answer. Nothing is
    clipped, rounded or zero-filled. Reverse-scored items use 6−raw before the exact integer sum.
    """
    mapping = mapping or load()
    catalog = SurveyCatalogV3.model_validate_json((RESOURCES / "catalogs/survey-v3.json").read_bytes())
    allowed = {item.item_id: item.allowed_values for item in catalog.items}
    result = {}
    for metric in mapping.metrics:
        values = [answers.get(item) for item in metric.question_ids]
        if any(value is not None and (type(value) is not int or value not in allowed[item])
               for item, value in zip(metric.question_ids, values)):
            result[metric.metric_id] = {"status": "input_check", "numerator": None, "denominator": None}
        elif any(value is None for value in values):
            result[metric.metric_id] = {"status": "insufficient", "numerator": None, "denominator": None}
        else:
            converted = [6 - value if metric.aggregation == "reverse_mean" else value for value in values]
            result[metric.metric_id] = {"status": "valid", "numerator": sum(converted), "denominator": len(converted)}
    return result


def definition_mismatch(definition, mapping=None):
    """Return why a saved external definition differs from the delivered mapping, else None."""
    mapping = mapping or load()
    source = next((item for item in mapping.external_sources if item.source_id == definition.source_id), None)
    if source is None:
        return "전달 기준에 연결되지 않은 외부 출처입니다."
    metric = next(item for item in mapping.metrics if item.metric_id == source.metric_id)
    scope = definition.scope
    if (tuple(scope.question_ids), scope.scale_minimum, scope.scale_maximum, scope.direction, scope.aggregation, scope.missing_policy) != (
            metric.question_ids, metric.scale_minimum, metric.scale_maximum, metric.direction, metric.aggregation, metric.missing_policy):
        return "기준 정의의 문항·척도·방향·산식이 전달 기준과 다릅니다."
    values = definition.values
    if (values.mean, values.standard_deviation, values.valid_n, values.total_n) != (
            source.mean, source.standard_deviation, source.valid_n, source.total_n):
        return "기준 정의의 평균·표준편차·유효 n이 전달 기준과 다릅니다."
    return None
