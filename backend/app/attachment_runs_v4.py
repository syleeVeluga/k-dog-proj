"""Explicit asynchronous inference over one completed opinion revision."""
import json
import hashlib
from types import SimpleNamespace
from fastapi import HTTPException
from pydantic import field_validator
from . import analysis, attachment_ai_v4 as attachment, disclosures_v4, opinions_v4 as opinions, sheets_v4 as sheets, settings_v4
from .domain.attachment_v4 import AttachmentAssessmentV4, AttachmentReferenceV4
from .domain.catalog_v4 import ContractV4, Hash, Text
from .domain.final_results_v4 import OpinionDocumentV4, OpinionReferenceV4
from .domain.results_v4 import BasicResultV4, ResultReferenceV4
from .domain.runs_v4 import ActionV4, RunConfigV4
from .input_models import Model
from .storage import encode, now, uid


class AttachmentStartV4(Model):
    request_id: str
    basic: ResultReferenceV4
    opinion: OpinionReferenceV4
    viewer_sheet_id: str | None = None

    @field_validator("basic", "opinion", mode="before")
    @classmethod
    def contracts(cls, value, info):
        model = ResultReferenceV4 if info.field_name == "basic" else OpinionReferenceV4
        return model.model_validate_json(encode(value)) if isinstance(value, dict) else value

    @field_validator("request_id")
    @classmethod
    def request_key(cls, value):
        if not value.strip() or len(value) > 128:
            raise ValueError("bounded explicit request ID required")
        return value


class AttachmentInputV4(ContractV4):
    case_id: Text
    session_id: Text
    input_revision: int
    manifest_ref: Text
    manifest_hash: Hash
    requested_by: Text
    viewer_sheet_id: Text | None
    basic: ResultReferenceV4
    basic_document: BasicResultV4
    opinion: OpinionReferenceV4
    opinion_document: OpinionDocumentV4


class AttachmentRunViewV4(Model):
    run_id: str
    status: str
    updated_at: str
    reserved_calls: int
    judgement_status: str
    reference: AttachmentReferenceV4 | None

    @field_validator("reference", mode="before")
    @classmethod
    def contract(cls, value):
        return AttachmentReferenceV4.model_validate_json(encode(value)) if isinstance(value, dict) else value


def snapshot_for(row):
    source = AttachmentInputV4.model_validate_json(row["input_snapshot_json"])
    if (source.case_id, source.session_id, source.input_revision, analysis.digest(source.model_dump(mode="json"))) != (row["case_id"], row["session_id"], row["input_revision"], row["input_hash"]):
        raise ValueError("attachment run input pins differ")
    return source


def eligible(opinion):
    item = next(item for item in opinion.domains if item.domain == "attachment")
    if opinion.state != "complete" or not item.text.strip() or item.label is not None:
        raise HTTPException(409, "유형을 명시하지 않은 완료 애착 의견만 별도 해석할 수 있습니다.")


def verify_sources(store, basic):
    source = basic.input_document.source
    files = {source.input.manifest_ref: source.input.manifest_hash,
        **{video.storage_ref: video.sha256 for video in source.session.videos}}
    if source.preprocess:
        files[source.preprocess.ref] = source.preprocess.hash
    for ref, expected in files.items():
        path = store.path(ref)
        stamp = analysis.file_stamp(path)
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected or analysis.file_stamp(path) != stamp:
            raise HTTPException(409, "애착 해석의 고정 원자료 파일/hash가 변경되었습니다.")


def check_access(store, db, row):
    source = snapshot_for(row)
    user = SimpleNamespace(username=source.requested_by, role="operator")
    case = opinions.context(store, db, source.case_id, source.session_id, user)
    if (case["input_revision"], case["manifest_ref"], case["manifest_hash"]) != (source.input_revision, source.manifest_ref, source.manifest_hash):
        raise HTTPException(409, "애착 해석 중 개체 입력이 변경되었습니다.")
    if store.manifest(case).consents.analysis_feedback != "confirmed":
        raise HTTPException(403, "분석·피드백 동의를 확인하세요.")
    if opinions.latest(store, db, source.case_id, source.session_id) != source.opinion:
        raise HTTPException(409, "완료 의견이 수정·철회되었습니다. 새 판본으로 해석하세요.")
    _, basic = opinions.selected_basic(store, db, source.case_id, source.session_id, source.basic, user, source.viewer_sheet_id)
    if basic != source.basic_document or opinions.read_document(store, source.opinion.ref, source.opinion.hash) != source.opinion_document:
        raise HTTPException(409, "애착 해석 부모 문서가 변경되었습니다.")
    disclosures_v4.require(db, source.case_id, source.session_id, user, disclosures_v4.target("opinion", source.opinion), source.opinion_document.actor)
    eligible(source.opinion_document)
    verify_sources(store, basic)
    return source


def row_for(db, run_id):
    row = db.execute("SELECT * FROM runs WHERE run_id=? AND kind='attachment_v4'", (run_id,)).fetchone()
    if not row:
        raise HTTPException(404, "완료 의견 애착 해석 실행이 없습니다.")
    return row


def view(store, case_id, session_id, run_id, user, viewer_sheet_id=None):
    with store.connect() as db:
        row = row_for(db, run_id)
        source = snapshot_for(row)
        if (source.case_id, source.session_id) != (case_id, session_id):
            raise HTTPException(404, "이 개체·회차의 실행이 아닙니다.")
        opinions.selected_basic(store, db, case_id, session_id, source.basic, user, viewer_sheet_id)
        disclosures_v4.require(db, case_id, session_id, user, disclosures_v4.target("opinion", source.opinion), source.opinion_document.actor)
        reserved = db.execute("SELECT COUNT(*) FROM steps WHERE run_id=? AND call_reserved=1", (run_id,)).fetchone()[0]
    return {"run_id": run_id, "status": row["status"], "updated_at": row["updated_at"], "reserved_calls": reserved,
        "judgement_status": "completed_opinion_inference", "reference": {"run_id": run_id, "ref": row["result_ref"], "hash": row["result_hash"]} if row["status"] == "succeeded" else None}


def enqueue(store, case_id, session_id, value, user):
    value = AttachmentStartV4.model_validate_json(value.model_dump_json())
    sheets.manager(user)
    request_hash = analysis.digest({"request": value.model_dump(mode="json"), "actor": user.username})
    with store.connect(write=True) as db:
        case = opinions.context(store, db, case_id, session_id, user)
        prior = db.execute("SELECT * FROM runs WHERE kind='attachment_v4' AND case_id=? AND session_id=? AND request_id=?", (case_id, session_id, value.request_id)).fetchone()
        if prior:
            if prior["request_hash"] != request_hash:
                raise HTTPException(409, "같은 요청 ID의 해석 입력이 다릅니다.")
            check_access(store, db, prior)
            run_id = prior["run_id"]
        else:
            _, basic = opinions.selected_basic(store, db, case_id, session_id, value.basic, user, value.viewer_sheet_id)
            if value.opinion != opinions.latest(store, db, case_id, session_id):
                raise HTTPException(409, "현재 완료 의견 revision을 명시하세요.")
            opinion = opinions.read_document(store, value.opinion.ref, value.opinion.hash)
            if opinion.basic != value.basic:
                raise HTTPException(409, "의견과 기본 결과 판본이 다릅니다.")
            eligible(opinion)
            disclosures_v4.require(db, case_id, session_id, user, disclosures_v4.target("opinion", value.opinion), opinion.actor)
            version = settings_v4.active(db)
            if version == "inactive":
                raise HTTPException(503, "활성 S1 AI 설정이 필요합니다.")
            pipeline = settings_v4.load(store, db, version)
            if not pipeline.raw_observation_scope_confirmed:
                raise HTTPException(503, "관찰 적용 범위를 확인한 활성 설정이 필요합니다.")
            common = {"item_codes": [item.code for item in basic.input_document.sheet.observations],
                "production_fps": "one_actual_frame_per_second", "request_fps": 1}
            config = RunConfigV4.model_validate_json(encode({"active_settings_version": version, "settings_hash": analysis.digest(pipeline.model_dump(mode="json")),
                "stages": [attachment.configuration(common)], "max_attempts": pipeline.max_attempts,
                "max_ai_calls": pipeline.max_ai_calls, "max_schema_repairs": pipeline.max_schema_repairs}))
            source = AttachmentInputV4(case_id=case_id, session_id=session_id, input_revision=case["input_revision"], manifest_ref=case["manifest_ref"],
                manifest_hash=case["manifest_hash"], requested_by=user.username, viewer_sheet_id=value.viewer_sheet_id,
                basic=value.basic, basic_document=basic, opinion=value.opinion, opinion_document=opinion)
            run_id = uid()
            db.execute("INSERT INTO runs(run_id,case_id,session_id,input_revision,input_snapshot_json,config_snapshot_json,reuse_manifest_json,status,created_at,updated_at,kind,request_id,request_hash,input_hash) VALUES(?,?,?,?,?,?,?,'queued',?,?,'attachment_v4',?,?,?)",
                (run_id, case_id, session_id, source.input_revision, source.model_dump_json(), config.model_dump_json(), "[]", now(), now(), value.request_id, request_hash, analysis.digest(source.model_dump(mode="json"))))
            check_access(store, db, row_for(db, run_id))
            store.audit(db, user.username, run_id, "attachment.opinion.create", {"basic": value.basic.model_dump(mode="json"), "opinion": value.opinion.model_dump(mode="json")})
    return view(store, case_id, session_id, run_id, user, value.viewer_sheet_id)


def read_result(store, reference, basic, opinion_ref, opinion):
    with store.connect() as db:
        row = row_for(db, reference.run_id)
        if row["status"] != "succeeded" or (row["result_ref"], row["result_hash"]) != (reference.ref, reference.hash):
            raise HTTPException(409, "성공한 해석 산출물의 고정 참조가 필요합니다.")
        step = db.execute("SELECT * FROM steps WHERE run_id=? AND stage='attachment_v4' AND status='succeeded' ORDER BY attempt DESC LIMIT 1", (reference.run_id,)).fetchone()
    source = snapshot_for(row)
    if not step or (step["output_ref"], step["output_hash"]) != (reference.ref, reference.hash):
        raise HTTPException(409, "해석 참조가 채택된 시도 산출물과 다릅니다.")
    if source.basic_document != basic or source.opinion != opinion_ref or source.opinion_document != opinion:
        raise HTTPException(409, "다른 기본 결과·의견 판본의 해석은 재사용할 수 없습니다.")
    payload = analysis.step_payload(store, row, step)
    assessment = AttachmentAssessmentV4.model_validate_json(encode(payload["assessment"]))
    context = attachment.context_for(basic.input_document, basic.input, basic.calculations.model_dump(mode="json"), opinion, instruction_snapshot=assessment.instruction_snapshot)
    if attachment.normalize(context, payload["response"], assessment.model) != assessment:
        raise ValueError("opinion inference and provider response differ")
    attachment.validate(assessment, basic.input_document, basic.input, basic.calculations.model_dump(mode="json"), opinion)
    return assessment


def process(worker, row):
    source = snapshot_for(row)
    config = RunConfigV4.model_validate_json(row["config_snapshot_json"])
    group = config.stages[0]
    attachment.verify_stage(group)
    basic = source.basic_document
    context = attachment.context_for(basic.input_document, basic.input, basic.calculations.model_dump(mode="json"), source.opinion_document)

    def guard():
        worker.check(row)
        attachment.verify_stage(group)

    def validate(payload):
        assessment = AttachmentAssessmentV4.model_validate_json(encode(payload["assessment"]))
        if attachment.normalize(context, payload["response"], assessment.model) != assessment:
            raise ValueError("completed opinion inference response differs")
        attachment.validate(assessment, basic.input_document, basic.input, basic.calculations.model_dump(mode="json"), source.opinion_document)
        return payload

    def work(step):
        guard()
        payload = attachment.request(worker, row, step, group, context, guard)
        try:
            return validate(payload)
        except (ValueError, KeyError) as exc:
            from .scoring_ai_v4 import contract_errors
            from .gemini import ProviderError
            payload["usage"]["contract_errors"] = contract_errors(exc)
            raise ProviderError("v4_schema_invalid", retryable=True, usage=payload["usage"]) from None

    result = worker.stage(row, group.stage, group.key, validate, work)
    guard()
    with worker.store.connect(write=True) as db:
        check_access(worker.store, db, row)
        current = row_for(db, row["run_id"])
        if current["claim_token"] != row["claim_token"] or current["status"] != "running" or current["lease_expires_at"] <= now():
            raise HTTPException(409, "애착 해석 실행 점유가 변경되었습니다.")
        step = db.execute("SELECT * FROM steps WHERE run_id=? ORDER BY attempt DESC LIMIT 1", (row["run_id"],)).fetchone()
        state = "succeeded" if result else "retry_wait" if step and step["status"] == "retry_wait" else "failed"
        db.execute("UPDATE runs SET status=?,result_ref=?,result_hash=?,claim_token=NULL,lease_expires_at=NULL,updated_at=? WHERE run_id=?",
            (state, step["output_ref"] if result else None, step["output_hash"] if result else None, now(), row["run_id"]))


def stop(store, case_id, session_id, run_id, value, user, viewer_sheet_id=None):
    value = ActionV4.model_validate_json(value.model_dump_json())
    view(store, case_id, session_id, run_id, user, viewer_sheet_id)
    with store.connect(write=True) as db:
        sheets.manager(user, db)
        row = row_for(db, run_id)
        if row["updated_at"] != value.expected_updated_at or row["status"] not in ("queued", "running", "retry_wait"):
            raise HTTPException(409, "실행 상태가 변경되었거나 이미 종료되었습니다.")
        db.execute("UPDATE runs SET status='stopped',claim_token=NULL,lease_expires_at=NULL,updated_at=? WHERE run_id=?", (now(), run_id))
        for step in db.execute("SELECT * FROM steps WHERE run_id=? AND status='running'", (run_id,)).fetchall():
            db.execute("UPDATE steps SET usage_json=?,updated_at=? WHERE step_id=?", (encode({**json.loads(step["usage_json"]), "code": "worker_interrupted", "billing_uncertain": bool(step["call_reserved"])}), now(), step["step_id"]))
        store.audit(db, user.username, run_id, "attachment.opinion.stop", {"reason": value.reason})
    return view(store, case_id, session_id, run_id, user, viewer_sheet_id)
