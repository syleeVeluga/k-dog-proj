"""Read-only comparison workbook cells; never approves the missing S1 blank form."""
from io import BytesIO
import posixpath
import re
import math
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
MAX_FILE = 20 * 1024 * 1024
MAX_EXPANDED = 100 * 1024 * 1024


def reference_cells(data: bytes, *, include_sheets=False):
    """Preserve XML raw values, formula text and stored cache separately, without execution."""
    if not data or len(data) > MAX_FILE:
        raise ValueError("reference workbook size is invalid")
    try:
        with ZipFile(BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > 10000 or sum(info.file_size for info in infos) > MAX_EXPANDED:
                raise ValueError("reference workbook expansion limit exceeded")
            names = {info.filename for info in infos}
            if len(names) != len(infos) or any("vbaProject" in name or name.startswith("xl/externalLinks/") for name in names):
                raise ValueError("macros, external links and duplicate package parts are unsupported")
            def xml(name):
                raw = archive.read(name)
                if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
                    raise ValueError("XML entities are unsupported")
                return ET.fromstring(raw)
            strings = ["".join(value.itertext()) for value in xml("xl/sharedStrings.xml").findall("s:si", NS)] if "xl/sharedStrings.xml" in names else []
            rels = {value.attrib["Id"]: value for value in xml("xl/_rels/workbook.xml.rels")}
            cells, sheet_names = [], []
            for sheet in xml("xl/workbook.xml").findall("s:sheets/s:sheet", NS):
                if sheet.attrib["name"] in sheet_names:
                    raise ValueError("duplicate worksheet name")
                sheet_names.append(sheet.attrib["name"])
                relation = rels[sheet.attrib[REL]]
                if relation.attrib.get("TargetMode") == "External":
                    raise ValueError("external sheets are unsupported")
                target = relation.attrib["Target"]
                path = posixpath.normpath(target.lstrip("/") if target.startswith("/") else "xl/"+target)
                if not path.startswith("xl/worksheets/"):
                    raise ValueError("worksheet path is outside workbook")
                addresses = set()
                for cell in xml(path).findall(".//s:sheetData/s:row/s:c", NS):
                    address = cell.attrib["r"]
                    if address in addresses or not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]{0,6}", address):
                        raise ValueError("invalid cell address")
                    addresses.add(address)
                    node, formula = cell.find("s:v", NS), cell.find("s:f", NS)
                    raw = None if node is None else node.text
                    kind = cell.attrib.get("t", "n")
                    if kind == "s":
                        value = strings[int(raw)] if raw is not None else None
                    elif kind == "inlineStr":
                        inline = cell.find("s:is", NS)
                        value = "".join(inline.itertext()) if inline is not None else None
                    elif kind == "b":
                        value = None if raw is None else raw == "1"
                    elif kind in ("str", "e", "d"):
                        value = raw
                    else:
                        value = None if raw is None else float(raw) if any(char in raw for char in ".eE") else int(raw)
                    if isinstance(value, float) and not math.isfinite(value):
                        raise ValueError("non-finite cell number")
                    if raw is None and value is None and formula is None:
                        continue
                    cells.append({"sheet": sheet.attrib["name"], "cell": address, "raw_type": kind, "raw_xml_value": raw,
                        "value": None if formula is not None else value,
                        "formula": "="+(formula.text or "") if formula is not None else None,
                        "formula_attributes": dict(formula.attrib) if formula is not None else {},
                        "cached_value": value if formula is not None else None,
                        "cache_present": formula is not None and node is not None})
                    if len(cells) > 100000:
                        raise ValueError("reference cell limit exceeded")
            return {"sheets": sheet_names, "cells": cells} if include_sheets else cells
    except (BadZipFile, KeyError, ET.ParseError, IndexError, TypeError) as exc:
        raise ValueError("invalid reference workbook package") from exc


def profile():
    return {"profile": "comparison-reference-s1-1", "reference_only": True, "score_import_enabled": False,
        "blank_template_approved": False, "cache_is_recalculation": False,
        "reason": "누적 비교 자료는 출처 검토용이며 G01/G04 빈양식 승인이나 S1 신규 채점이 아닙니다."}
