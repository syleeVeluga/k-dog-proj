"""Read-only extraction of the customer's 42-item workbook and 28-item questionnaire into versioned catalogs; never imports responses."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from openpyxl import load_workbook

from .domain.catalog import (
    ALL_SEGMENTS_LABEL, SURVEY_DOMAINS, BehaviorCatalog, PHASE_COUNT_RANGE, SEGMENTS, SHEET_GROUPS,
    SurveyCatalog,
)

ROOT = Path(__file__).resolve().parents[2]
CUSTOMER_DIR = ROOT / "docs/최종 고객 문서"
BEHAVIOR_V2_FILE = "03_행동_채점표_42항목_20260913.xlsx"
BEHAVIOR_V2_VERSION = "catalog-20260913-v2"
SURVEY_V2_FILE = "04_보호자_설문지_28문항.pdf"
SURVEY_V2_VERSION = "catalog-20260913-v2"
HEADERS = {"A": "구간", "B": "관찰 항목", "C": "1", "D": "2", "E": "3", "F": "4", "G": "5",
           "H": "영역", "I": "척도·축", "AD": "영역코드", "AY": "척도"}
SEGMENT_BY_LABEL = {label: segment for segment, label in SEGMENTS}
# Reference items have no data-type column; the B-column marker decides (계획 R1).
VALUE_TYPE_MARKERS = (("※자동 계산", "auto_ratio"), ("※0~6", "phase_count"), ("※횟수", "count"))


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def literal(cell):
    if cell.data_type == "f":
        raise ValueError(f"expected a literal value at {cell.parent.title}!{cell.coordinate}")
    return cell.value


def read_behavior_v2(path: Path) -> BehaviorCatalog:
    source_hash = file_hash(path)
    book = load_workbook(path, data_only=False)
    items = []
    try:
        for prefix, name, count in SHEET_GROUPS:
            sheet = book[name]
            for column, expected in HEADERS.items():
                if sheet[f"{column}4"].value != expected:
                    raise ValueError(f"unexpected header {name}!{column}4")
            for number in range(1, count + 1):
                row = number + 4
                text = literal(sheet[f"B{row}"])
                if not isinstance(text, str):
                    raise ValueError(f"item text missing at {name}!B{row}")
                segment_label = literal(sheet[f"A{row}"])
                if segment_label != ALL_SEGMENTS_LABEL and segment_label not in SEGMENT_BY_LABEL:
                    raise ValueError(f"unknown segment label at {name}!A{row}")
                axis_label = literal(sheet[f"I{row}"])
                if not isinstance(axis_label, str):
                    raise ValueError(f"axis label missing at {name}!I{row}")
                domain = literal(sheet[f"AD{row}"])
                scale = literal(sheet[f"AY{row}"])
                value_type = next((kind for marker, kind in VALUE_TYPE_MARKERS if marker in text), "scale")
                cells = [sheet[f"{column}{row}"] for column in "CDEFG"]
                labels = [{"score": score, "text": literal(cell), "source_cell": cell.coordinate}
                          for score, cell in enumerate(cells, 1) if cell.value is not None]
                if value_type == "scale":
                    allowed, note = [label["score"] for label in labels], None
                else:
                    if len(labels) != 1 or labels[0]["score"] != 1:
                        raise ValueError(f"count/auto item needs a single instruction in C at {name}!C{row}")
                    allowed, note, labels = (list(PHASE_COUNT_RANGE) if value_type == "phase_count" else []), labels[0]["text"], []
                items.append({
                    "item_id": f"{prefix}-{number:02d}", "sheet": name, "source_row": row,
                    "segment_label": segment_label,
                    "segment": None if segment_label == ALL_SEGMENTS_LABEL else SEGMENT_BY_LABEL[segment_label],
                    "text": text, "domain_label": literal(sheet[f"H{row}"]), "domain": domain,
                    "axis_label": axis_label, "axis": axis_label.split("·", 1)[1] if "·" in axis_label else None,
                    "scale": scale, "value_type": value_type, "labels": labels,
                    "allowed_scores": allowed, "note": note,
                })
            if sheet[f"B{5 + count}"].value is not None:
                raise ValueError(f"{name} has more item rows than the agreed {count}")
    finally:
        book.close()
    if file_hash(path) != source_hash:
        raise ValueError("source workbook changed during extraction")
    return BehaviorCatalog.model_validate_json(json.dumps({
        "version": BEHAVIOR_V2_VERSION, "source_filename": path.name,
        "source_sha256": source_hash, "provenance": "excel_verified", "items": items,
    }, ensure_ascii=False))


SECTION = re.compile(r"^([A-E])\. (.+?)\s{2,}①")
ITEM = re.compile(r"^(\d{1,2}) (\S.*?)\s*(□)?\s*$")


def read_survey_v2(path: Path) -> SurveyCatalog:
    from pypdf import PdfReader  # development-only dependency; the runtime never reads the PDF

    source_hash = file_hash(path)
    items, section, scale = [], None, None
    for page_number, page in enumerate(PdfReader(path).pages, 1):
        for raw in page.extract_text().splitlines():
            line = raw.strip()
            heading = SECTION.match(line)
            if heading:
                section = heading.group(1)
                if SURVEY_DOMAINS[section][2] != heading.group(2).strip():
                    raise ValueError(f"unexpected section title for {section} on page {page_number}")
                printed = tuple(part.strip() for part in re.split(r"[①②③④⑤]", line[line.index("①"):]) if part.strip())
                scale = scale or printed
                if printed != scale:
                    raise ValueError(f"response scale differs in section {section}")
                continue
            item = ITEM.match(line)
            if not item or section is None:
                continue
            number = int(item.group(1))
            items.append({
                "item_id": f"s{number:02d}", "number": number, "text": item.group(2),
                "domain": section, "allows_not_applicable": item.group(3) is not None,
                "source_page": page_number,
            })
    if [item["number"] for item in items] != list(range(1, 29)):
        raise ValueError("survey numbering changed; expected 1 to 28 in print order")
    if file_hash(path) != source_hash:
        raise ValueError("source questionnaire changed during extraction")
    return SurveyCatalog.model_validate_json(json.dumps({
        "version": SURVEY_V2_VERSION, "source_filename": path.name,
        "source_sha256": source_hash, "provenance": "excel_verified",
        "response_scale": list(scale), "items": items,
    }, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--customer-dir", type=Path, default=CUSTOMER_DIR, help="folder holding the customer's 42-item workbook and 28-item questionnaire PDF")
    parser.add_argument("--check", action="store_true", help="compare existing JSON without writing")
    args = parser.parse_args()
    catalogs = {
        "behavior-v2.json": read_behavior_v2(args.customer_dir / BEHAVIOR_V2_FILE),
        "survey-v2.json": read_survey_v2(args.customer_dir / SURVEY_V2_FILE),
    }
    for name, catalog in catalogs.items():
        destination = ROOT / "resources" / "catalogs" / name
        content = catalog.model_dump_json(indent=2) + "\n"
        if args.check:
            if not destination.exists() or destination.read_text(encoding="utf-8") != content:
                raise ValueError(f"catalog is absent or differs from source: {name}")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8", newline="\n")
        print(f"{name}: {len(catalog.items)} items; source SHA-256 {catalog.source_sha256}")


if __name__ == "__main__":
    main()
