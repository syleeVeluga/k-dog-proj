"""Catalog-aware validation of v3 raw values and normalized references."""

from .catalog_v3 import BehaviorCatalogV3, MappingV3, ProtocolV3, SurveyCatalogV3
from .contracts_v3 import DecisionV3, DerivedValueV3, ScoreSheetV3


def validate_sheet_v3(sheet: ScoreSheetV3, catalog: BehaviorCatalogV3, protocol: ProtocolV3) -> ScoreSheetV3:
    sheet = ScoreSheetV3.model_validate(sheet)
    catalog = BehaviorCatalogV3.model_validate(catalog)
    protocol = ProtocolV3.model_validate(protocol)
    if sheet.catalog_version != catalog.version or sheet.protocol_version != protocol.version:
        raise ValueError("sheet editions differ from catalogs")
    items = {item.code: item for item in catalog.items}
    windows = {window.window_id for window in protocol.windows}
    for observation in sheet.observations:
        item = items.get(observation.code)
        if item is None or item.usage != "direct":
            raise ValueError(f"unknown, automatic or unused direct input: {observation.code}")
        value = observation.value
        if observation.status == "observed":
            if item.value_type == "memo":
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"{item.code} needs a nonblank memo")
            elif item.value_type == "category":
                if type(value) is not int or value not in item.allowed_values:
                    raise ValueError(f"{item.code} needs one of its original category codes")
            elif item.value_type == "count":
                if type(value) is not int or value < 0:
                    raise ValueError(f"{item.code} needs a nonnegative whole count")
            elif item.value_type == "seconds":
                if type(value) not in (int, float) or value < 0:
                    raise ValueError(f"{item.code} needs raw seconds")
            limits = item.input_range
            if limits and (value < limits.minimum or limits.maximum is not None and value > limits.maximum):
                raise ValueError(f"{item.code} outside original cell validation range")
        for evidence in observation.evidence:
            if evidence.window_id not in windows or evidence.window_id not in item.windows:
                raise ValueError(f"{item.code} has an unrelated/unknown evidence window")
    return sheet


def validate_references_v3(catalog: BehaviorCatalogV3, survey: SurveyCatalogV3,
                           protocol: ProtocolV3, mappings: tuple[MappingV3, ...]) -> None:
    codes = {item.code for item in catalog.items if item.usage != "unused"}
    windows = {window.window_id for window in protocol.windows}
    survey_ids = {item.item_id for item in survey.items}
    result_ids = {entry.entry_id for mapping in mappings if mapping.kind == "results" for entry in mapping.entries}
    for item in catalog.items:
        if not set(item.windows) <= windows or not set(item.opportunity_codes) <= codes:
            raise ValueError(f"invalid item window/opportunity reference: {item.code}")
    for mapping in mappings:
        for entry in mapping.entries:
            if not set(entry.behavior_codes) <= codes or not set(entry.survey_ids) <= survey_ids:
                raise ValueError(f"unknown source code or question in {entry.entry_id}")
            if not set(entry.windows) <= windows or not set(entry.result_basis_ids) <= result_ids:
                raise ValueError(f"unknown window/result basis in {entry.entry_id}")
            if entry.original.get("comparison") == "설문 단독" and entry.behavior_codes:
                raise ValueError("survey-only mappings cannot invent behavior codes")


def validate_derived_v3(value: DerivedValueV3, catalog: BehaviorCatalogV3) -> DerivedValueV3:
    value = DerivedValueV3.model_validate(value)
    codes = {item.code for item in catalog.items if item.usage != "unused"}
    if not set(value.input_codes) <= codes:
        raise ValueError("derived value references unused/unknown source codes")
    return value


def validate_decision_v3(value: DecisionV3, catalog: BehaviorCatalogV3, protocol: ProtocolV3) -> DecisionV3:
    value = DecisionV3.model_validate(value)
    codes = {item.code: item for item in catalog.items if item.usage != "unused"}
    if not set(value.evidence_codes) <= codes.keys():
        raise ValueError("decision references unused/unknown source codes")
    windows = {window.window_id for window in protocol.windows}
    applicable = {window for code in value.evidence_codes for window in codes[code].windows}
    for evidence in (*value.evidence, *value.counter_evidence):
        if evidence.window_id not in windows or evidence.window_id not in applicable:
            raise ValueError("decision evidence references an unknown/unrelated window")
    return value
