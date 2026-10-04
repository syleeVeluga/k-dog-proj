"""Deterministic, read-only S1 extraction from the two hash-pinned source documents."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from .domain.catalog_v4 import (AUTO_CODES, BehaviorCatalogV4, CATALOG_VERSION, COUNT_CODES,
                               ITEM_CODES, MEMO_CODES, OPTIONAL_CODES, PROTOCOL_VERSION,
                               ROOT, SCORING_VERSION, SEGMENTS, SOURCE_FILES, SURVEY_POLICY_VERSION,
                               SURVEY_VERSION, VOCAL_CODES)

CUSTOMER_DIR_V4 = ROOT / "docs" / "요구사항_20261003"
SOURCES = SOURCE_FILES
W = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
X = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def source(source_id: str, location: str) -> dict:
    filename, digest = SOURCES[source_id]
    return {"schema_version": "4.0", "source_id": source_id, "filename": filename,
            "sha256": digest, "location": location}


def verify_sources(root: Path) -> None:
    for source_id, (filename, expected) in SOURCES.items():
        path = root / filename
        if not path.is_file():
            raise ValueError(f"{source_id}: required local-only source is missing")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"{source_id}: source SHA-256 mismatch; S1 extraction refused")


def read_docx(path: Path) -> tuple[list[str], list[list[list[str]]]]:
    with ZipFile(path) as archive:
        doc = ET.fromstring(archive.read("word/document.xml"))
    def text(element):
        return "".join(node.text or "" for node in element.findall(".//w:t", W))
    paragraphs = [text(p) for p in doc.findall(".//w:body/w:p", W)]
    tables = [[["\n".join(text(p) for p in cell.findall("w:p", W))
                for cell in row.findall("w:tc", W)] for row in table.findall("w:tr", W)]
              for table in doc.findall(".//w:tbl", W)]
    return paragraphs, tables


def read_workbook(path: Path) -> dict[str, dict[int, dict[str, str]]]:
    """Read values/formula text only; never executes Excel or touches participant files."""
    result = {}
    with ZipFile(path) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ["".join(node.itertext()) for node in
                       ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("s:si", X)]
        rels = {r.attrib["Id"]: r.attrib["Target"] for r in
                ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))}
        for sheet in ET.fromstring(archive.read("xl/workbook.xml")).findall("s:sheets/s:sheet", X):
            target = rels[sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]]
            name = target.lstrip("/") if target.startswith("/") else "xl/" + target
            rows = {}
            for row in ET.fromstring(archive.read(name)).findall(".//s:sheetData/s:row", X):
                cells = {}
                for cell in row.findall("s:c", X):
                    value = cell.find("s:v", X)
                    value = value.text if value is not None else ""
                    if cell.attrib.get("t") == "s":
                        value = strings[int(value)]
                    elif cell.attrib.get("t") == "inlineStr":
                        value = "".join(cell.find("s:is", X).itertext())
                    if cell.find("s:f", X) is not None:
                        raise ValueError("source evidence workbook unexpectedly contains an executable formula")
                    if value:
                        cells[re.sub(r"\d", "", cell.attrib["r"])] = value
                if cells:
                    rows[int(row.attrib["r"])] = cells
            result[sheet.attrib["name"]] = rows
    return result


def code_references(text: str) -> list[str]:
    """Expand source shorthand such as 개38~43 and 보6·9 without interpreting prose."""
    found = []
    for match in re.finditer(r"(환경|개|보|바)(\d+(?:(?:[·~])(?:환경|개|보|바)?\d+)*)", text):
        prefix, sequence = match.groups()
        parts = re.split(r"([·~])", sequence)
        current = int(parts[0])
        found.append(f"{prefix}{current}")
        for separator, token in zip(parts[1::2], parts[2::2]):
            explicit = re.match(r"(환경|개|보|바)?(\d+)$", token)
            if explicit.group(1):
                prefix = explicit.group(1)
            number = int(explicit.group(2))
            numbers = range(current + 1, number + 1) if separator == "~" else (number,)
            found.extend(f"{prefix}{n}" for n in numbers)
            current = number
    return list(dict.fromkeys(found))


def item_windows(code: str, segment: str) -> list[str]:
    specific = {
        "개9": ["alone_initial"], "개10": ["alone_later"],
        "보10": ["separation_departure"],
        "개17": ["reunion_approach"], "개18": ["reunion_later"],
        "개19": ["reunion_contact"], "개44": ["reunion_contact"],
        "개21": ["reunion_approach"], "보11": ["reunion_later"],
        "보22": ["reunion_later"], "보38": ["reunion_later"], "보39": ["reunion_later"],
        "개13": ["stranger_gate"], "개55": ["stranger_approach"],
        "개15": ["stranger_call"], "개51": ["stranger_contact"],
        "개52": ["stranger_contact"], "개54": ["stranger_exit"],
        "바54": ["reunion_tail_event"], "바55": ["stranger_tail_event"],
        "보5": ["entry_free", "exit_free"], "보6": ["entry_free", "exit_free"],
        "보9": ["entry_free", "exit_free"], "보14": ["entry_object", "exit_object"],
        "개30": ["entry_object"], "개34": ["exit_object"],
    }
    return specific.get(code, [f"{segment}_whole"])


def read_behavior(tables: list, sheets: dict) -> dict:
    definitions = {}
    for table_number in (25, 26, 27):
        for row_number, row in enumerate(tables[table_number][1:], 2):
            code = re.match(r"(?:바|개|보|환경)\d+", row[0]).group()
            definitions[code] = (row, f"부록 A / 표 {table_number + 1} / 행 {row_number}")
    if set(definitions) != set(ITEM_CODES):
        raise ValueError("DOCX appendix A code set differs from the 90 S1 identities")
    items = []
    for row_number, row in sheets["영상 90항목"].items():
        if row_number < 7:
            continue
        code = row["A"]
        doc_row, location = definitions[code]
        text, address = doc_row[1].rsplit("입력:", 1)
        input_address, internal_address = (v.strip() for v in address.split(" / "))
        if f"{input_address} / {internal_address}" != row["G"]:
            raise ValueError(f"{code}: DOCX/XLSX input addresses disagree")
        usage = {"직접 숫자": "numeric", "자동": "automatic", "메모": "memo"}[row["F"]]
        value_type = "count" if code in COUNT_CODES else "category" if usage == "numeric" else usage
        values, labels = [], []
        if value_type == "category":
            if code in tuple(f"개{i}" for i in range(37, 44)):
                values = [0, 1, 2, 3]
                labels = [{"value": v, "text": part.strip()} for v, part in
                          zip(values, row["E"].split(" / "))]
            else:
                for line in row["E"].replace("−", "-").splitlines():
                    match = re.match(r"^([+-]?\d+)\s*(.*)$", line)
                    if match and "미사용" not in match.group(2):
                        value = int(match.group(1))
                        values.append(value)
                        labels.append({"value": value, "text": match.group(2).lstrip(" :—")})
            if not values:
                raise ValueError(f"{code}: categorical scale could not be extracted")
        segment = SEGMENTS[int(input_address[0]) - 1][0]
        priority = values if code in ("개9", "개10") else list(reversed(values)) if code in (
            "보10", "보11", "보23", "개30", "개34") else [1] if code == "환경1" else []
        items.append({
            "code": code, "text": text.strip(), "scale_text": doc_row[2],
            "segment": segment, "segment_label": row["B"], "axis_label": row["D"],
            "usage": usage, "value_type": value_type, "allowed_values": values, "labels": labels,
            "display_order": list(reversed(values)) if code in ("보10", "보11", "보23") else values,
            "category_priority": priority, "optional": code in OPTIONAL_CODES,
            "whole_interval_required": code in COUNT_CODES and code != "개21" or code in ("개8", "개10", "개12"),
            "windows": item_windows(code, segment),
            "opportunity_codes": {"보22": ["보38"], "보39": ["보38"], "보24": ["보40"],
                                  "개51": ["개53"], "개52": ["개53"]}.get(code, []),
            "policy_pending": ["D03"] if code in ("개21", "보5") else [],
            "input_address": input_address, "internal_address": internal_address,
            "automatic_formula": row.get("H"),
            "source": source("SRC02", location),
            "scale_source": source("SRC03", f"영상 90항목!E{row_number}"),
        })
    catalog = {"schema_version": "4.0", "version": CATALOG_VERSION, "source_version": "v1.3/S1.1",
               "sources": [source("SRC02", "부록 A"), source("SRC03", "영상 90항목!A7:J96")], "items": items}
    return json.loads(BehaviorCatalogV4.model_validate_json(json.dumps(catalog)).model_dump_json())


def envelope(version: str) -> dict:
    return {"schema_version": "4.0", "version": version, "catalog_version": CATALOG_VERSION}


def protocol(tables: list) -> dict:
    windows = []
    for segment, label, seconds in SEGMENTS:
        windows.append({"window_id": f"{segment}_whole", "segment": segment,
                        "anchor": "actual_segment", "start_offset": 0, "end_offset": None,
                        "nominal_seconds": seconds, "status": "confirmed"})
    fixed = [("alone_initial", "alone", 0, 10), ("alone_later", "alone", 10, 60),
             ("reunion_approach", "reunion", 0, 15), ("reunion_later", "reunion", 15, 30),
             ("stranger_gate", "stranger", 0, 10), ("stranger_approach", "stranger", 12, 16),
             ("stranger_call", "stranger", 0, 4)]
    for name, segment, start, end in fixed:
        windows.append({"window_id": name, "segment": segment,
                        "anchor": "actual_call" if name == "stranger_call" else "actual_segment",
                        "start_offset": start, "end_offset": end, "status": "confirmed"})
    for segment in ("entry", "exit"):
        for suffix in ("free", "object"):
            windows.append({"window_id": f"{segment}_{suffix}", "segment": segment,
                            "anchor": "actual_free_movement" if suffix == "free" else "actual_object_stop_and_passage",
                            "start_offset": None, "end_offset": None, "status": "confirmed"})
    for segment in ("reunion", "stranger"):
        windows.append({"window_id": f"{segment}_contact", "segment": segment, "anchor": "actual_contact",
                        "start_offset": 0, "end_offset": None, "status": "confirmed"})
        windows.append({"window_id": f"{segment}_tail_event", "segment": segment,
                        "anchor": "first_clear_head_turn", "start_offset": -2, "end_offset": 3,
                        "status": "optional_trial"})
    windows.append({"window_id": "stranger_exit", "segment": "stranger", "anchor": "actual_staff_exit",
                    "start_offset": 0, "end_offset": None, "status": "confirmed"})
    windows.append({"window_id": "separation_departure", "segment": "alone",
                    "anchor": "actual_guardian_departure_preparation", "end_event": "guardian_fully_outside",
                    "start_offset": None, "end_offset": None, "status": "confirmed"})
    return {**envelope(PROTOCOL_VERSION), "source": source("SRC02", "3~6절 / 부록 A"),
            "segments": [{"segment": s[0], "label": s[1], "nominal_seconds": s[2],
                          "start_event": row[1], "procedure": row[2]} for s, row in zip(SEGMENTS, tables[5][1:])],
            "windows": windows, "walk_phases": tables[7][1:], "stranger_script": tables[8][1:],
            "pending_policies": {"D03": "개21 현재 전반 0~15초 배치 유지; 전체30초 집계안 미확정. 보5 사건간 종합·동률·최소량 미확정.",
                                 "D05": "추가 무효 조건은 확인 전 임의 적용하지 않음."}}


def scoring(tables: list, sheets: dict) -> dict:
    rule_rows = sheets["산출 규칙"]
    points = [{"code": r[0], "value": int(r[1]), "points": [int(n) for n in r[2:5]],
               "scene": r[5], "reason": r[6], "source": source("SRC02", f"부록 B / 행 {i}")}
              for i, r in enumerate(tables[28][1:], 2)]
    combinations = [{"initial": int(r[0]), "later": int(r[1]), "text": r[2],
                     "source": source("SRC02", f"부록 C / 행 {i}")}
                    for i, r in enumerate(tables[29][1:], 2)]
    owts = [r for r in rule_rows.values() if re.fullmatch(r"OWT\d{2}", r.get("A", ""))]
    seps = [r for r in rule_rows.values() if re.fullmatch(r"SEP\d{2}", r.get("A", ""))]
    if len(points) != 29 or len(owts) != 29 or len(combinations) != 25 or len(seps) != 25:
        raise ValueError("source owner/separation row counts disagree")
    for point, row in zip(points, owts):
        code, value = re.fullmatch(r"(보\d+) 코드 ([+-]?\d+)", row["B"]).groups()
        if (point["code"], point["value"], point["points"]) != (code, int(value), list(map(int, re.findall(r"\d+", row["C"])))):
            raise ValueError("DOCX/XLSX owner points disagree")
    for combination, row in zip(combinations, seps):
        values = list(map(int, re.findall(r"=([+-]?\d+)", row["B"])))
        if [combination["initial"], combination["later"]] != values or combination["text"] != row["C"]:
            raise ValueError("DOCX/XLSX separation combinations disagree")
    old = json.loads((ROOT / "resources/rules/scoring-v3.json").read_text(encoding="utf-8"))
    old_points = old["owner_type_points"]
    old_vectors = {(r["code"], r["raw_value"]): tuple(r["points"]) for r in old_points}
    unchanged = all(old_vectors.get((p["code"], p["value"])) == tuple(p["points"]) for p in points)
    if not unchanged:
        raise ValueError("appendix B changed from recorded v3 owner points")
    rules = [{"rule_id": r["A"], "title": r["B"], "definition": r["C"], "conditions": r["D"],
              "source_status": r["E"], "source_location": r["F"],
              "source": source("SRC03", f"산출 규칙!A{n}:F{n}")}
             for n, r in rule_rows.items() if re.fullmatch(r"R\d{2}", r.get("A", ""))]
    for rule in rules:
        if rule["rule_id"] == "R25":
            rule["application_status"] = "superseded_by_user_20261003"
            rule["effective_policy"] = "기존 점수·파생 결과 전부 폐기, 원입력 유지, S1 전 항목 null에서 재채점. 같은 정의도 점수 이관 금지."
        else:
            rule["application_status"] = "source_rule_with_declared_pending_boundaries"
    return {**envelope(SCORING_VERSION), "rules": rules, "owner_type_points": points,
            "owner_points_unchanged_from_v3": unchanged,
            "owner_type_thresholds": {"minimum_items": 3, "minimum_scenes": 2, "dominance": 0.60, "margin": 0.15,
                                      "source": source("SRC02", "8절 / 부록 B")},
            "separation_combinations": combinations,
            "active_derived_keys": ["개26", "개36", "개27", "개60", "W", "AE", "AF", "AX", "BY", "AU", "BK"],
            "pending_policies": {"D03": "보5 사건간 종합·동률·최소량·개21 전체30초안 미확정",
                                 "D04": "자유 의견에서 최종 유형을 자동 결정하는 상세 절차 미확정",
                                 "D05": "비공포 묶음의 부분 결측 확대안 미확정"},
            "precedence": {"source": source("SRC02", "10.1절 / 부록 E 잔재 해석"),
                           "R02_partial_missing": "Q10~14 외 완전응답 자료는 계산 가능; 부분결측은 policy_pending",
                           "R25_old_scores": "사용자 2026-10-03 지시 및 개발반영계획 §4가 원문 이관 제안을 대체함. 기존 점수 복사 금지.",
                           "body_state_codes": ["개14", "개18", "개23", "개58"]}}


def mappings(catalog: dict, tables: list, sheets: dict) -> dict:
    entries = []
    for n, row in sheets["설문 28문항"].items():
        if n < 7:
            continue
        entries.append({"question_id": row["A"], "behavior_codes": code_references(row["G"]),
                        "relationship": row["F"], "condition": row["H"],
                        "source": source("SRC03", f"설문 28문항!A{n}:J{n}")})
    survey = {**envelope("survey-behavior-20261002-s1.1"), "survey_version": SURVEY_VERSION,
              "policy_version": SURVEY_POLICY_VERSION, "entries": entries,
              "groups": tables[20][1:], "fear_missing_policy": "any_missing_holds_that_group",
              "other_partial_missing_policy": "policy_pending_D05",
              "policy_source": source("SRC02", "10.1절")}
    results = {**envelope("results-20261002-s1.1"), "entries": []}
    for n, row in sheets["리포트 출력 연결"].items():
        if n < 7:
            continue
        codes = code_references(row["D"])
        results["entries"].append({"order": int(row["A"]), "label": row["B"], "linked_ids": row["C"],
                                   "behavior_codes": [c for c in codes if c != "개59"],
                                   "linked_memo": "개59" in codes, "evidence": row["D"],
                                   "process": row["E"], "output": row["F"], "missing": row["G"],
                                   "source": source("SRC03", f"리포트 출력 연결!A{n}:H{n}")})
    addresses = [{"code": item["code"], "input_address": item["input_address"],
                  "internal_address": item["internal_address"], "source": item["source"]} for item in catalog["items"]]
    inputs = {**envelope("s1-input-20261002-s1.1"), "excel_import_enabled": False,
              "physical_verification": "not_received_G01_G04", "entries": addresses,
              "column_roles": {"D": "raw_numeric_input", "F": "observation_evidence_or_reason", "G": "review_memo"},
              "linked_memo": {"code": "개59", "counts_as_active_item": False},
              "walk_phase_metadata": [{"code": f"개{n}", "address": f"6_걷기!H{n - 28}"} for n in range(38, 44)],
              "source": source("SRC02", "2절 / 부록 A; 주소 선언만 확인, 실물 미수령")}
    return {"mappings/survey-behavior-v4.json": survey, "mappings/results-v4.json": results,
            "mappings/s1-input-v4.json": inputs}


def extract_v4(root: Path = CUSTOMER_DIR_V4) -> dict[str, str]:
    verify_sources(root)
    paragraphs, tables = read_docx(root / SOURCES["SRC02"][0])
    sheets = read_workbook(root / SOURCES["SRC03"][0])
    catalog = read_behavior(tables, sheets)
    rules = scoring(tables, sheets)
    changes = [{"code": row[0], "change": row[1], "before": row[2], "after": row[3],
                "source": source("SRC02", f"부록 F / 행 {i}")}
               for i, row in enumerate(tables[32][1:], 2)]
    if len(changes) != 54 or Counter(row["change"] for row in changes)["폐기"] != 33:
        raise ValueError("appendix F must contain 54 change records including 33 retired rows")
    workbook_changes = [row for n, row in sheets["변경 항목"].items() if n >= 7]
    if len(workbook_changes) != len(changes):
        raise ValueError("DOCX/XLSX change row counts disagree")
    for change, row in zip(changes, workbook_changes):
        actual = (change["code"], change["change"], change["before"], change["after"].replace("\n", ""))
        expected = (row["A"], row["B"], row["C"], row["D"] + row["E"])
        if actual != expected:
            raise ValueError(f"DOCX/XLSX change record disagrees: {change['code']}")
    extracted = {"catalogs/behavior-v4.json": catalog, "rules/scoring-v4.json": rules,
                 "rules/protocol-v4.json": protocol(tables),
                 "rules/preprocess-v4.json": {**envelope("preprocess-20261002-s1.1"),
                     "source": source("SRC02", "3~6절 / 부록 G D01"),
                     "camera_mapping": {"CAM1": "1", "CAM2": "3", "CAM3": "2"},
                     "camera_layout_status": "provisional_D01", "visibility_threshold": None,
                     "unknown_threshold_policy": "do_not_invent", "deduplicate_audio_across_cameras": True,
                     "preserve_original_time_and_offset": True},
                 "catalogs/changes-v4.json": {**envelope("changes-20261002-s1.1"), "entries": changes,
                     "unused_codes": ["개20", "개31", "개33", "개35"],
                     "count_reconciliation": "117-4-33-1+11=90", "old_score_migration": False},
                 **mappings(catalog, tables, sheets)}
    from .domain.validation_v4 import validate_asset_references_v4
    validate_asset_references_v4(extracted)
    verify_sources(root)
    return {name: json.dumps(content, ensure_ascii=False, indent=2) + "\n" for name, content in extracted.items()}
