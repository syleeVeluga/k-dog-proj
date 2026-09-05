"""Read-only extraction of the supplied 20260904 templates; never imports responses."""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook

from .domain.contracts import BehaviorCatalog, SurveyCatalog

ROOT = Path(__file__).resolve().parents[2]
BEHAVIOR_FILE = "큐브_행동채점표_최종양식_55항목_20260904.xlsx"
SURVEY_FILE = "큐브_통합설문_최종양식_20260904.xlsx"
GROUPS = (("BS", "1_바디시그널", 16), ("DOG", "2_개행동", 20), ("OWN", "3_보호자행동", 19))
DOMAIN_MAP = {
    "교육태도": "EDU", "사회성-사람": "SOC_P", "사회성-개": "SOC_D",
    "사회성-환경": "SOC_E", "친밀·애착": "ATT", "보호자 행동 일관성": "CON",
    "훈련 수행(개)": "TRN", "— 적응 지표 (영역 집계 제외)": None,
    "— 기준선 (영역 집계 제외)": None,
}


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_behavior(path: Path) -> BehaviorCatalog:
    source_hash = file_hash(path)
    book = load_workbook(path, read_only=True, data_only=False)
    items = []
    try:
        for prefix, name, count in GROUPS:
            sheet = book[name]
            if tuple(sheet.cell(4, c).value for c in range(3, 8)) != (
                "1점 (양호)", "2점", "3점 (중간)", "4점", "5점 (강한 문제)",
            ):
                raise ValueError(f"unexpected score headers in {name}")
            for number, row in enumerate(sheet.iter_rows(min_row=5, max_row=4 + count, max_col=9), 1):
                item_id = f"{prefix}-{number:02d}"
                options = []
                for score, cell in enumerate(row[2:7], 1):
                    if cell.value is None:
                        continue
                    if cell.data_type == "f" or not isinstance(cell.value, str):
                        raise ValueError(f"expected literal option at {name}!{cell.coordinate}")
                    tags = re.findall(r"\[([AB])\]", cell.value)
                    if len(set(tags)) > 1:
                        raise ValueError(f"ambiguous direction at {name}!{cell.coordinate}")
                    options.append({
                        "option_id": f"{item_id}:S{score}", "text": cell.value,
                        "score": score, "direction": tags[0] if tags else None,
                        "source_cell": cell.coordinate,
                    })
                items.append({
                    "item_id": item_id, "text": row[1].value, "segment": row[0].value,
                    "domain": DOMAIN_MAP[row[7].value], "source_sheet": name,
                    "source_row": number + 4, "options": options,
                })
    finally:
        book.close()
    catalog = BehaviorCatalog.model_validate_json(json.dumps({
        "version": "catalog-20260904-v1", "source_filename": path.name,
        "source_sha256": source_hash, "provenance": "excel_verified", "items": items,
    }, ensure_ascii=False))
    expected = {"EDU": 7, "SOC_P": 1, "SOC_D": 1, "SOC_E": 9, "ATT": 14, "CON": 12, "TRN": 6, None: 5}
    if Counter(item.domain for item in catalog.items) != expected:
        raise ValueError("behavior domain counts differ from the agreed 50 + 5 mapping")
    if file_hash(path) != source_hash:
        raise ValueError("source workbook changed during extraction")
    return catalog


def read_survey(path: Path) -> SurveyCatalog:
    source_hash = file_hash(path)
    book = load_workbook(path, read_only=True, data_only=False)
    items = []
    try:
        sheet = book["데이터입력"]
        instructions = sheet["A2"].value
        if not isinstance(instructions, str) or "1~5" not in instructions:
            raise ValueError("survey response scale needs review")
        for number, row in enumerate(sheet.iter_rows(min_row=6, max_row=35, max_col=5), 1):
            if row[0].value != number or any(cell.data_type == "f" for cell in row):
                raise ValueError("survey numbering or literal content changed")
            items.append({
                "item_id": f"q{number:02d}", "text": row[3].value,
                "domain_label": row[1].value, "source_layer": row[2].value,
                "scoring_note": row[4].value, "source_sheet": sheet.title,
                "source_row": number + 5,
            })
    finally:
        book.close()
    if file_hash(path) != source_hash:
        raise ValueError("source workbook changed during extraction")
    return SurveyCatalog.model_validate_json(json.dumps({
        "version": "catalog-20260904-v1", "source_filename": path.name,
        "source_sha256": source_hash, "provenance": "excel_verified",
        "response_instructions": instructions, "allowed_responses": [1, 2, 3, 4, 5],
        "items": items,
    }, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT / "docs")
    parser.add_argument("--check", action="store_true", help="compare existing JSON without writing")
    args = parser.parse_args()
    catalogs = {
        "behavior-v1.json": read_behavior(args.source_dir / BEHAVIOR_FILE),
        "survey-v1.json": read_survey(args.source_dir / SURVEY_FILE),
    }
    for name, catalog in catalogs.items():
        destination = ROOT / "resources" / "catalogs" / name
        content = catalog.model_dump_json(indent=2) + "\n"
        if args.check:
            if not destination.exists() or destination.read_text(encoding="utf-8") != content:
                raise ValueError(f"catalog is absent or differs from source: {name}")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
        print(f"{name}: {len(catalog.items)} items; source SHA-256 {catalog.source_sha256}")


if __name__ == "__main__":
    main()
