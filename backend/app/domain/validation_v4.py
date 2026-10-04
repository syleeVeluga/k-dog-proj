"""Cross-document S1 checks; source observations and unresolved policies stay distinct."""

from .catalog_v4 import (AUTO_CODES, BehaviorCatalogV4, CATALOG_VERSION, ITEM_CODES,
                         VOCAL_CODES, load_catalog_v4, load_rules_v4, validate_source_references_v4)
from .contracts_v4 import ScoreSheetV4


def validate_sheet_v4(sheet: ScoreSheetV4, catalog: BehaviorCatalogV4 | None = None,
                      protocol: dict | None = None) -> ScoreSheetV4:
    catalog = catalog or load_catalog_v4()
    protocol = protocol or load_rules_v4("protocol")
    sheet = ScoreSheetV4.model_validate(sheet)
    if catalog.version != sheet.catalog_version or protocol["version"] != sheet.protocol_version:
        raise ValueError("mixed S1 catalog/protocol versions")
    items = {item.code: item for item in catalog.items}
    windows = {window["window_id"] for window in protocol["windows"]}
    for observation in sheet.observations:
        item = items[observation.code]
        for evidence in observation.evidence:
            if evidence.window_id not in windows or evidence.window_id not in item.windows:
                raise ValueError(f"{item.code}: evidence belongs to another observation window")
        if observation.status != "observed":
            continue
        if item.value_type == "category" and observation.value not in item.allowed_values:
            raise ValueError(f"{item.code}: value is outside its S1 scale")
        if item.whole_interval_required and not observation.whole_interval_observed:
            raise ValueError(f"{item.code}: whole-interval observation required; partial is null")
        if item.usage == "numeric" and not observation.evidence:
            raise ValueError(f"{item.code}: observed numeric values require source evidence")
        if item.code == "보23" and observation.value == -2 and not observation.whole_interval_observed:
            raise ValueError("보23 no-instruction category requires the whole interval")
        if observation.vocalization is not None and item.code not in VOCAL_CODES:
            raise ValueError("listening metadata belongs to vocalization items only")
        if item.code in VOCAL_CODES:
            vocal = observation.vocalization
            if vocal is None or not vocal.whole_interval_judged:
                raise ValueError("vocalization needs actual listening time and whole interval judgement")
            amount, duration = vocal.cumulative_vocal_seconds, vocal.listened_seconds
            expected = 0 if amount == 0 else 1 if amount * 3 <= duration else 2 if amount * 3 <= 2 * duration else 3
            if observation.value != expected:
                raise ValueError("vocal category disagrees with observed duration ratio")
    return sheet


def validate_asset_references_v4(assets: dict[str, dict]) -> None:
    catalog = assets["catalogs/behavior-v4.json"]
    protocol = assets["rules/protocol-v4.json"]
    codes = {item["code"] for item in catalog["items"]}
    windows = {window["window_id"] for window in protocol["windows"]}
    if len(codes) != 90 or codes != set(ITEM_CODES):
        raise ValueError("S1 asset must have exact active identities")
    if len(windows) != len(protocol["windows"]):
        raise ValueError("duplicate S1 window")
    for item in catalog["items"]:
        if not set(item["windows"]) <= windows or not set(item["opportunity_codes"]) <= codes:
            raise ValueError(f"unresolved catalog reference: {item['code']}")
    for name, asset in assets.items():
        validate_source_references_v4(asset)
        if name == "catalogs/behavior-v4.json":
            continue
        if asset.get("schema_version") != "4.0" or asset.get("catalog_version") != CATALOG_VERSION:
            raise ValueError(f"mixed asset version: {name}")
    survey = assets["mappings/survey-behavior-v4.json"]
    if [entry["question_id"] for entry in survey["entries"]] != [f"Q{n:02}" for n in range(1, 29)]:
        raise ValueError("survey references must cover the 28 original questions exactly")
    for name in ("mappings/survey-behavior-v4.json", "mappings/results-v4.json"):
        for entry in assets[name]["entries"]:
            if not set(entry["behavior_codes"]) <= codes:
                raise ValueError(f"retired or unknown reference in {name}")
    inputs = assets["mappings/s1-input-v4.json"]
    if {entry["code"] for entry in inputs["entries"]} != codes:
        raise ValueError("S1 input mapping differs from active catalog")
    if inputs["excel_import_enabled"] or inputs["physical_verification"] != "not_received_G01_G04":
        raise ValueError("physical Excel source remains unverified")
    rules = assets["rules/scoring-v4.json"]
    if [rule["rule_id"] for rule in rules["rules"]] != [f"R{n:02}" for n in range(1, 26)]:
        raise ValueError("expected all 25 source rules")
    if not set(AUTO_CODES) <= set(rules["active_derived_keys"]) or {"V", "AW", "AY", "개32"} & set(rules["active_derived_keys"]):
        raise ValueError("invalid S1 derived result keys")
    pairs = {(row["initial"], row["later"]) for row in rules["separation_combinations"]}
    if pairs != {(a, b) for a in range(-2, 3) for b in range(-2, 3)}:
        raise ValueError("separation combinations do not cover all 25 pairs")
