"""Participant and 28-item survey intake, shared by manual entry and standard imports."""

import csv
from io import BytesIO, StringIO

from fastapi import HTTPException
from openpyxl import Workbook, load_workbook

from app.domain.catalog import SURVEY_IDS, SurveyCatalog
from app.domain.contracts import SurveyAnswers
from app.domain.validation import validate_survey_answers
from app.input_models import CaseCreate
from app.storage import now, uid
from app.domain.catalog_v3 import SURVEY_VERSION
from app.input_models_v3 import CaseCreateV3, ConsentsV3, SurveyEditV3
from app.input_models_v4 import ManifestV4, SessionV4, new_session_v4


def new_session(survey_version: str = SURVEY_VERSION, note="") -> SessionV4:
    return new_session_v4(uid(), note, survey_version)


def create_case(store, db, value: CaseCreate, actor: str, version: str):
    session = new_session(version)
    manifest = ManifestV4(case_id=uid(), event_id=value.event_id,
                        participant_id=value.participant_id, input_revision=1,
                        selected_session_id=session.session_id, sessions=[session],
                        consents=getattr(value, "consents", ConsentsV3()))
    key, digest = store.write_manifest(manifest)
    db.execute(
        "INSERT INTO cases(case_id,event_id,participant_id,dog_name,reservation_at,sequence_no,consent_confirmed,guardian_name,"
        "dog_profile_json,input_revision,selected_session_id,manifest_ref,manifest_hash,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,1,?,?,?,?,?)",
        (manifest.case_id, value.event_id, value.participant_id, value.dog_name, value.reservation_at,
         value.sequence_no, int(value.consent_confirmed), value.guardian_name, value.dog.model_dump_json(),
         session.session_id, key, digest, now(), now()),
    )
    db.execute("UPDATE cases SET manifest_schema_version=?,consents_v3_json=? WHERE case_id=?",
               (manifest.schema_version, manifest.consents.model_dump_json(), manifest.case_id))
    store.audit(db, actor, manifest.case_id, "case.create", {"revision": 1})
    return manifest.case_id


def selected_session(manifest, session_id):
    if manifest.selected_session_id != session_id:
        raise HTTPException(409, "선택된 촬영 세션이 변경되었습니다. 다시 조회하세요.")
    return next(item for item in manifest.sessions if item.session_id == session_id)


def save_survey(store, db, case_id, value: SurveyEditV3, actor, catalog):
    if value.survey_version != catalog.version:
        raise HTTPException(422, "확정 설문 버전과 일치하지 않습니다.")
    value = SurveyEditV3.model_validate_json(value.model_dump_json())
    if isinstance(catalog, SurveyCatalog):
        validate_survey_answers(SurveyAnswers(answers=value.answers, not_applicable=tuple(value.not_applicable)), catalog)
    row = store.case(db, case_id, expected=value.expected_revision)
    manifest = store.manifest(row)
    session = selected_session(manifest, value.session_id)
    if session.survey_version != value.survey_version:
        raise HTTPException(422, "선택한 세션의 설문 판본과 일치하지 않습니다.")
    not_applicable = sorted(value.not_applicable)
    if session.survey == value.answers and session.survey_not_applicable == not_applicable and session.survey_blank_reasons == value.blank_reasons:
        return  # Identical re-import is idempotent.
    session.survey = value.answers
    session.survey_not_applicable = not_applicable
    session.survey_blank_reasons = value.blank_reasons
    store.save(db, row, manifest, actor, "survey.update")


PROFILE_COLUMNS = ("dog_breed", "dog_sex", "dog_age_years", "dog_size", "years_together", "adoption_route")
TRUE_TOKENS = ("1", "Y", "y", "예", "동의", "true", "True", "O")
FALSE_TOKENS = ("", "0", "N", "n", "아니오", "미확인", "false", "False", "X")


def headers(kind, version=None):
    if kind == "participants":
        return ["event_id", "participant_id", "dog_name", "reservation_at", "sequence_no", "consent_confirmed", "guardian_name", *PROFILE_COLUMNS,
                "consent_analysis_feedback", "consent_stranger_contact"]
    return ["event_id", "participant_id", "survey_version", *SURVEY_IDS,
            *([f"{question}_reason" for question in SURVEY_IDS] if version == SURVEY_VERSION else [])]


def participant_row(value):
    """Map spreadsheet cells to CaseCreate: blanks mean 「미기재」, never a guessed value."""
    def text(key):
        raw = value.get(key)
        return "" if raw is None else str(raw).strip()

    def integer(key):
        raw = value.get(key)
        if raw is None or raw == "":
            return None
        if type(raw) is int or (type(raw) is str and raw.strip().isdigit()):
            return int(raw)
        raise ValueError(f"{key}: 정수만 허용됩니다.")

    consent = text("consent_confirmed")
    if consent not in TRUE_TOKENS + FALSE_TOKENS:
        raise ValueError("동의 확인(consent_confirmed): 확인은 예 또는 1, 미확인은 빈칸으로 고친 뒤 다시 검증하세요.")
    def consent_state(key):
        raw = text(key)
        if raw in ("", "미확인", "unknown"):
            return "unknown"
        if raw in ("거절", "declined", "0", "N", "아니오"):
            return "declined"
        if raw in ("확인", "confirmed", "1", "Y", "예", "동의"):
            return "confirmed"
        raise ValueError(f"{key}: 미확인/거절/확인 값을 사용하세요.")

    return CaseCreateV3.model_validate({
        "event_id": value["event_id"], "participant_id": value["participant_id"], "dog_name": value["dog_name"],
        "reservation_at": text("reservation_at"), "sequence_no": integer("sequence_no"),
        "consent_confirmed": consent in TRUE_TOKENS, "guardian_name": text("guardian_name"),
        "consents": {"analysis_feedback": consent_state("consent_analysis_feedback"),
                     "stranger_contact": consent_state("consent_stranger_contact")},
        "dog": {"breed": text("dog_breed"), "sex": text("dog_sex") or "미기재", "age_years": integer("dog_age_years"),
                "size": text("dog_size") or "미기재", "years_together": text("years_together"), "adoption_route": text("adoption_route") or "미기재"},
    })


def template(kind, format, version=None):
    columns = headers(kind, version)
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


def read_rows(data: bytes, format: str, sheet_name=None, layout=None):
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
            sheet = workbook[sheet_name] if sheet_name else workbook.active
            if layout is not None:
                layout.update(sheets=workbook.sheetnames, selected_sheet=sheet.title)
            if (sheet.max_row or 0) > 10001 or (sheet.max_column or 0) > 100:
                raise ValueError("too many cells")
            return [list(row) for row in sheet.iter_rows(values_only=True)]
        finally:
            workbook.close()
    except Exception as exc:
        raise HTTPException(422, "표준 XLSX 파일을 확인하세요. 수식 대신 원응답을 입력하세요.") from exc
