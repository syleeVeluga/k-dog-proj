"""Participant and survey intake, shared by manual entry and standard imports."""

import csv
from io import BytesIO, StringIO

from fastapi import HTTPException
from openpyxl import Workbook, load_workbook
from pydantic import ValidationError

from app.input_models import (
    CaseCreate, ImportPreview, ImportRow, Manifest, Session, SurveyEdit, SURVEY_IDS,
)
from app.storage import now, uid


def new_session(survey_version: str, capture_mode="unknown", route_note="") -> Session:
    return Session(session_id=uid(), capture_mode=capture_mode, route_note=route_note,
                   survey_version=survey_version, survey=dict.fromkeys(SURVEY_IDS), videos=[])


def create_case(store, db, value: CaseCreate, actor: str, version: str):
    session = new_session(version)
    manifest = Manifest(case_id=uid(), event_id=value.event_id,
                        participant_id=value.participant_id, input_revision=1,
                        selected_session_id=session.session_id, sessions=[session])
    key, digest = store.write_manifest(manifest)
    db.execute(
        "INSERT INTO cases(case_id,event_id,participant_id,dog_name,reservation_at,"
        "input_revision,selected_session_id,manifest_ref,manifest_hash,created_at,updated_at) "
        "VALUES (?,?,?,?,?,1,?,?,?,?,?)",
        (manifest.case_id, value.event_id, value.participant_id, value.dog_name,
         value.reservation_at, session.session_id, key, digest, now(), now()),
    )
    store.audit(db, actor, manifest.case_id, "case.create", {"revision": 1})
    return manifest.case_id


def selected_session(manifest, session_id):
    if manifest.selected_session_id != session_id:
        raise HTTPException(409, "선택된 촬영 세션이 변경되었습니다. 다시 조회하세요.")
    return next(item for item in manifest.sessions if item.session_id == session_id)


def save_survey(store, db, case_id, value: SurveyEdit, actor, version):
    if value.survey_version != version:
        raise HTTPException(422, "확정 설문 버전과 일치하지 않습니다.")
    row = store.case(db, case_id, expected=value.expected_revision)
    manifest = store.manifest(row)
    session = selected_session(manifest, value.session_id)
    if session.survey == value.answers:
        return  # Identical re-import is idempotent.
    session.survey = value.answers
    store.save(db, row, manifest, actor, "survey.update")


def headers(kind):
    if kind == "participants":
        return ["event_id", "participant_id", "dog_name", "reservation_at"]
    return ["event_id", "participant_id", "survey_version", *SURVEY_IDS]


def template(kind, format):
    columns = headers(kind)
    if format == "csv":
        output = StringIO(newline="")
        csv.writer(output).writerow(columns)
        return output.getvalue().encode("utf-8-sig")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "입력"
    sheet.append(columns)
    # IDs must remain text, including leading zeroes.
    for row in sheet.iter_rows(min_row=2, max_row=101, max_col=len(columns)):
        for cell in row:
            cell.number_format = "@"
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def read_rows(data: bytes, format: str):
    if format == "csv":
        try:
            return list(csv.reader(StringIO(data.decode("utf-8-sig")), strict=True))
        except (UnicodeError, csv.Error) as exc:
            raise HTTPException(422, "UTF-8 CSV 형식을 확인하세요.") from exc
    try:
        # Reject oversized expanded XML before parsing a compressed workbook.
        from zipfile import ZipFile
        with ZipFile(BytesIO(data)) as archive:
            if sum(info.file_size for info in archive.infolist()) > 32 * 1024 * 1024:
                raise ValueError("expanded workbook too large")
        workbook = load_workbook(BytesIO(data), read_only=True, data_only=False)
        try:
            sheet = workbook.active
            if (sheet.max_row or 0) > 10001 or (sheet.max_column or 0) > 100:
                raise ValueError("too many cells")
            return [list(row) for row in sheet.iter_rows(values_only=True)]
        finally:
            workbook.close()
    except Exception as exc:
        raise HTTPException(422, "표준 XLSX 파일을 확인하세요. 수식 대신 원응답을 입력하세요.") from exc


def preview(store, db, data, kind, format, version):
    rows = read_rows(data, format)
    if not rows or len(rows) > 10001:
        raise HTTPException(422, "헤더와 최대 10,000개 입력 행이 필요합니다.")
    columns = rows[0]
    if len(columns) != len(set(columns)) or set(columns) != set(headers(kind)):
        raise HTTPException(422, "표준 양식의 열을 사용하세요. 열 순서 변경은 허용됩니다.")
    result = ImportPreview(rows=[], errors=[])
    seen = set()
    for number, values in enumerate(rows[1:], 2):
        if all(value is None or value == "" for value in values):
            continue
        try:
            if len(values) != len(columns):
                raise ValueError("열 수가 헤더와 다릅니다.")
            value = dict(zip(columns, values))
            for key in ("event_id", "participant_id"):
                if not isinstance(value[key], str) or not value[key].strip():
                    raise ValueError(f"{key}: 텍스트 ID가 필요합니다. Excel 숫자 ID는 자동 변환하지 않습니다.")
            pair = value["event_id"], value["participant_id"]
            if pair in seen:
                raise ValueError("파일 안에 중복 참가자 ID가 있습니다.")
            seen.add(pair)
            existing = db.execute("SELECT * FROM cases WHERE event_id=? AND participant_id=?", pair).fetchone()
            if kind == "participants":
                if existing:
                    raise ValueError("이미 등록된 참가자 ID입니다.")
                value["reservation_at"] = value.get("reservation_at") or ""
                result.rows.append(ImportRow(row_number=number, event_id=pair[0], participant_id=pair[1],
                                             participant=CaseCreate.model_validate(value)))
            else:
                if existing is None or existing["deletion_requested"]:
                    raise ValueError("등록된 활성 참가자에 연결할 수 없습니다.")
                answers = {}
                for question in SURVEY_IDS:
                    raw = value[question]
                    if raw is None or raw == "":
                        answers[question] = None
                    elif (type(raw) is int and 1 <= raw <= 5) or (type(raw) is str and raw in ("1", "2", "3", "4", "5")):
                        answers[question] = int(raw)
                    else:
                        raise ValueError(f"{question}: 1~5 또는 빈칸만 허용됩니다.")
                if value["survey_version"] != version:
                    raise ValueError("survey_version: 확정 설문 버전이 아닙니다.")
                survey = SurveyEdit(expected_revision=existing["input_revision"],
                                    session_id=existing["selected_session_id"],
                                    survey_version=version, answers=answers)
                result.rows.append(ImportRow(row_number=number, event_id=pair[0], participant_id=pair[1],
                                             case_id=existing["case_id"], survey=survey))
        except (ValueError, ValidationError) as exc:
            if isinstance(exc, ValidationError):
                explanation = "; ".join(".".join(map(str, e["loc"])) + ": " + e["msg"] for e in exc.errors())
            else:
                explanation = str(exc)
            result.errors.append(f"{number}행: {explanation}")
    return result
