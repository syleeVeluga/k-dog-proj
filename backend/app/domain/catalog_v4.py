"""S1.1 identities and strict catalog contracts, independent of legacy row numbers."""

from collections import Counter
import json
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

CATALOG_VERSION = "catalog-20261002-s1.1"
PROTOCOL_VERSION = "protocol-20261002-s1.1"
SCORING_VERSION = "scoring-20261002-s1.1-app-1"
SURVEY_VERSION = "survey-20260929-v3"
SURVEY_POLICY_VERSION = "survey-policy-20261002-s1.1"
RUNTIME_SURVEY_POLICY_VERSION = "survey-policy-20261007-rp01"
SurveyPolicyVersion = Literal["survey-policy-20261002-s1.1", "survey-policy-20261007-rp01"]
SOURCE_FILES = {
    "SRC02": ("K-DOG_개발기준_통합명세_20261002.docx",
              "4a1b3696246d55b34f6ca2b919c1599da4b15b47fa7a4e5ae624a2669a17493a"),
    "SRC03": ("리포트_산출근거_간소화S1_20261002.xlsx",
              "11b9fd6c1241679d175998d04e0f29fd4420228dc2abb0d0d84e72f055b22941"),
}
ROOT = Path(__file__).resolve().parents[3]
RESOURCES = ROOT / "resources"
ITEM_CODES = tuple((
    "개5 개45 바6 개6 개7 개30 바14 바46 개8 바17 환경1 바47 보10 개9 개10 개58 개11 개12 바20 개60 바48 "
    "개17 개18 개19 개44 보11 보38 보22 보25 보39 개47 개21 바26 바49 바54 보12 개22 개23 개48 바29 바50 "
    "보13 개37 개38 개39 개40 개41 개42 개43 개24 개25 바32 개26 개36 개27 바51 보18 개13 개56 보16 "
    "보23 보26 개55 개15 개53 개51 개52 개54 개57 보17 보40 보24 보27 개14 개16 개49 바23 바52 바55 "
    "개34 보14 개28 개29 개46 보5 보6 보9 개50 바35 바53"
).split())
AUTO_CODES = ("개26", "개27", "개36", "개60")
MEMO_CODES = ("보25", "보26", "보27")
NUMERIC_CODES = tuple(code for code in ITEM_CODES if code not in AUTO_CODES + MEMO_CODES)
OPTIONAL_CODES = ("바54", "바55")
COUNT_CODES = tuple(f"바{i}" for i in (14, 17, 20, 26, 29, 32, 23, 35, *range(46, 54))) + ("개21",)
VOCAL_CODES = ("바6", "개11", "개47", "개48", "개49", "개50")
ItemCode = Literal[*ITEM_CODES]
Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
SegmentId = Literal["entry", "baseline", "alone", "reunion", "ignore", "walk", "stranger", "exit"]
SEGMENTS = (("entry", "입장", 30), ("baseline", "기준", 20), ("alone", "혼자", 60),
            ("reunion", "재회", 30), ("ignore", "무시", 20), ("walk", "걷기", 30),
            ("stranger", "낯선", 30), ("exit", "퇴장", 30))


class ContractV4(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, allow_inf_nan=False,
                              revalidate_instances="always")
    schema_version: Literal["4.0"] = "4.0"


class SourceV4(ContractV4):
    source_id: Literal["SRC02", "SRC03"]
    filename: Text
    sha256: Hash
    location: Text

    @model_validator(mode="after")
    def pinned_source(self) -> Self:
        if (self.filename, self.sha256) != SOURCE_FILES[self.source_id]:
            raise ValueError("S1 source identity/SHA-256 differs from the verified source inventory")
        return self


class LabelV4(ContractV4):
    value: int
    text: Text


class CatalogItemV4(ContractV4):
    code: ItemCode
    text: Text
    scale_text: Text
    segment: SegmentId
    segment_label: Text
    axis_label: Text
    usage: Literal["numeric", "automatic", "memo"]
    value_type: Literal["category", "count", "automatic", "memo"]
    allowed_values: tuple[int, ...]
    labels: tuple[LabelV4, ...]
    display_order: tuple[int, ...]
    category_priority: tuple[int, ...] = ()
    optional: bool = False
    whole_interval_required: bool = False
    windows: tuple[Text, ...]
    opportunity_codes: tuple[ItemCode, ...] = ()
    policy_pending: tuple[Literal["D03", "D05"], ...] = ()
    input_address: Text
    internal_address: Text
    automatic_formula: str | None = None
    source: SourceV4
    scale_source: SourceV4

    @model_validator(mode="after")
    def consistent(self) -> Self:
        expected = "automatic" if self.code in AUTO_CODES else "memo" if self.code in MEMO_CODES else "numeric"
        if self.usage != expected:
            raise ValueError("incorrect S1 input kind")
        if self.value_type == "category":
            if not self.allowed_values or tuple(label.value for label in self.labels) != self.allowed_values:
                raise ValueError("category labels must preserve exact raw values")
            if len(set(self.allowed_values)) != len(self.allowed_values) or set(self.display_order) != set(self.allowed_values):
                raise ValueError("invalid category values/display order")
            if len(set(self.category_priority)) != len(self.category_priority) or not set(self.category_priority) <= set(self.allowed_values):
                raise ValueError("invalid category priority")
        elif self.allowed_values or self.labels or self.display_order or self.category_priority:
            raise ValueError("non-category items have no category values")
        if self.optional != (self.code in OPTIONAL_CODES):
            raise ValueError("only two tail event items are optional")
        if (self.code in COUNT_CODES) != (self.value_type == "count"):
            raise ValueError("incorrect count item")
        if self.usage != "numeric" and self.value_type != self.usage:
            raise ValueError("automatic and memo input kinds are distinct")
        if self.code == "환경1" and self.internal_address != "2_개행동!J94":
            raise ValueError("환경1 is stored at J94 and is not 개94")
        if self.code != "환경1":
            sheet = {"바": "1_바디시그널", "개": "2_개행동", "보": "3_보호자행동"}[self.code[0]]
            if self.internal_address != f"{sheet}!J{self.code[1:]}":
                raise ValueError("internal address differs from source identity")
        return self


class BehaviorCatalogV4(ContractV4):
    version: Literal["catalog-20261002-s1.1"] = CATALOG_VERSION
    source_version: Literal["v1.3/S1.1"] = "v1.3/S1.1"
    sources: tuple[SourceV4, ...]
    items: tuple[CatalogItemV4, ...]

    @model_validator(mode="after")
    def exact_items(self) -> Self:
        if tuple(item.code for item in self.items) != ITEM_CODES:
            raise ValueError("expected the exact 90 S1 items in segment order")
        if Counter(item.usage for item in self.items) != {"numeric": 83, "automatic": 4, "memo": 3}:
            raise ValueError("S1 requires 83 numeric + 4 automatic + 3 memo")
        return self

    def rated_items(self) -> tuple[CatalogItemV4, ...]:
        return tuple(item for item in self.items if item.usage != "automatic")


def load_catalog_v4() -> BehaviorCatalogV4:
    return BehaviorCatalogV4.model_validate_json((RESOURCES / "catalogs/behavior-v4.json").read_bytes())


def validate_source_references_v4(document: object) -> None:
    """Validate nested rule/mapping provenance with the same pins as catalog models."""
    if isinstance(document, dict):
        if "source_id" in document:
            SourceV4.model_validate(document)
        for key, value in document.items():
            if key in ("source", "scale_source", "policy_source"):
                SourceV4.model_validate(value)
            elif key == "sources":
                for entry in value:
                    SourceV4.model_validate(entry)
            else:
                validate_source_references_v4(value)
    elif isinstance(document, (list, tuple)):
        for entry in document:
            validate_source_references_v4(entry)


def load_rules_v4(name: Literal["scoring", "protocol", "preprocess"] = "scoring") -> dict:
    document = json.loads((RESOURCES / f"rules/{name}-v4.json").read_text(encoding="utf-8"))
    expected = {"scoring": SCORING_VERSION, "protocol": PROTOCOL_VERSION, "preprocess": "preprocess-20261002-s1.1"}
    if (document.get("schema_version") != "4.0" or document.get("catalog_version") != CATALOG_VERSION
            or document.get("version") != expected[name]):
        raise ValueError("S1 rule/catalog version mismatch")
    validate_source_references_v4(document)
    return document


def load_mapping_v4(name: Literal["survey-behavior", "results", "s1-input"]) -> dict:
    document = json.loads((RESOURCES / f"mappings/{name}-v4.json").read_text(encoding="utf-8"))
    if (document.get("schema_version") != "4.0" or document.get("catalog_version") != CATALOG_VERSION
            or document.get("version") != f"{name}-20261002-s1.1"):
        raise ValueError("S1 mapping/catalog version mismatch")
    validate_source_references_v4(document)
    return document
