"""V3-only AI groups, clip-local validation, pure calculation and blinded publication."""

import hashlib
import json
import secrets

from fastapi import HTTPException
from pydantic import field_validator

from app import analysis, judgements, run_v3, settings_v3, sheets
from app.auth import password_hash
from app.domain.contracts_v3 import DecisionV3, ObservationV3
from app.domain.results_v3 import BasicResultV3
from app.domain.results_v3 import CalculationsV3
from app.domain.runs_v3 import ReuseV3, RunConfigV3
from app.domain.scoring_ai_v3 import AiResponseV3
from app.domain.sheets_v3 import AI_ACCOUNT, SheetDocumentV3, SheetInputV3, SheetReferenceV3
from app.gemini import ProviderError
from app.preprocess_v3 import CATALOG
from app.scoring_v3 import RULE_HASH, RULE_VERSION, VOCAL_SEGMENTS, calculate, vocal_category
from app.storage import encode, now

VERSION = "ai-scoring-20260929-v3-1"


class AiRevealResultV3(sheets.SheetRevealResultV3):
    results: list[BasicResultV3]

    @field_validator("results", mode="before")
    @classmethod
    def results_contract(cls, values):
        return [BasicResultV3.model_validate_json(encode(value)) if isinstance(value, dict) else value for value in values]


class AiReadinessV3(sheets.Model):
    active_version: str
    planned_provider_calls: int
    enabled: bool


def readiness(store):
    with store.connect() as db:
        version = settings_v3.active(db)
        pipeline = settings_v3.load(store, db, version) if version != "inactive" else None
    return {"active_version": version, "planned_provider_calls": len(settings_v3.groups()) + 1,
            "enabled": pipeline is not None and pipeline.q11_scope_confirmed}


def reveal(store, sheet_id, value, user):
    disclosed = sheets.revise(store, sheet_id, value, user, "reveal")
    target = SheetDocumentV3.model_validate_json(encode(disclosed["target"]))
    results = []
    if target.sheet.rater_kind == "ai":
        with store.connect() as db:
            row = sheets.row_for(store, db, target.sheet.sheet_id)
            if not row["active"]:
                raise HTTPException(403, "공개 대상의 배정이 취소되었습니다.")
            for entry in db.execute("SELECT * FROM basic_results WHERE sheet_id=?", (target.sheet.sheet_id,)):
                doc = judgements.document_for(store, entry)
                refs = {(link.ref, link.hash, link.revision) for link in target.previous}
                same_reference = doc.input.ref == value.ref or (doc.input.ref, doc.input.hash, doc.input.revision) in refs
                if same_reference and doc.input_document.sheet == target.sheet and doc.input_document.source == target.source and doc.input_document.ai_run_id == target.ai_run_id:
                    results.append(doc.model_dump(mode="json"))
    return {**disclosed, "results": results}


def response_schema(codes):
    schema = AiResponseV3.model_json_schema()
    schema["$defs"]["AiRowV3"]["properties"]["code"]["enum"] = list(codes)
    schema["properties"]["observations"].update(minItems=len(codes), maxItems=len(codes))
    return schema


def configuration(version, pipeline):
    stages = []
    for key, group in settings_v3.groups().items():
        config = pipeline.groups[key]
        stages.append({"stage": "score_v3", "key": key, "item_codes": group["codes"], "prompt": config.prompt,
            "response_schema": response_schema(group["codes"]), "provider": "gemini", "model": config.model,
            "production_fps": "native", "request_fps": config.fps, "media_resolution": config.media_resolution,
            "processing_mode": config.processing_mode, "max_output_tokens": config.max_output_tokens, "thinking_level": config.thinking_level})
    codes = [item.code for item in CATALOG.rated_items()]
    common = {"key": "session", "item_codes": codes, "production_fps": "native", "request_fps": None,
              "media_resolution": "medium", "model": "program", "provider": "program", "provider_call": False,
              "prompt": "source-defined program calculation", "response_schema": {"type": "object"}}
    stages.append({**common, "stage": "calculate_v3"})
    config = pipeline.judgement
    schema = judgements.JudgementEditV3.model_json_schema()
    stages.append({**common, "stage": "judge_v3", "model": config.model, "provider": "gemini", "provider_call": True,
        "prompt": config.prompt, "response_schema": schema, "request_fps": config.fps, "media_resolution": config.media_resolution,
        "processing_mode": config.processing_mode, "max_output_tokens": config.max_output_tokens, "thinking_level": config.thinking_level})
    stages.append({**common, "stage": "publish_v3"})
    return RunConfigV3.model_validate_json(encode({"version": VERSION, "active_settings_version": version,
        "settings_hash": hashlib.sha256(pipeline.model_dump_json().encode()).hexdigest(), "q11_scope_confirmed": pipeline.q11_scope_confirmed, "stages": stages,
        "max_attempts": pipeline.max_attempts, "max_ai_calls": pipeline.max_ai_calls, "max_schema_repairs": pipeline.max_schema_repairs}))


def consent(store, case_id):
    with store.connect() as db:
        case = store.case(db, case_id)
        if store.manifest(case).consents.analysis_feedback != "confirmed":
            raise HTTPException(403, "분석·피드백 동의가 확인된 자료만 AI 처리할 수 있습니다.")


def start(store, case_id, session_id, value, user):
    sheets.manager(user)
    with store.connect() as db:
        version = value.settings_version or settings_v3.active(db)
        if version == "inactive":
            raise HTTPException(503, "신판 AI 설정을 먼저 저장·활성화하세요. 구판 설정으로 대체하지 않습니다.")
        pipeline = settings_v3.load(store, db, version)
        if not pipeline.q11_scope_confirmed:
            raise HTTPException(503, "Q11 적용 범위가 확인된 운영 설정이 필요합니다.")
    config = configuration(version, pipeline)
    consent(store, case_id)
    reuse = []
    if value.reuse_run_id:
        with store.connect() as db:
            source = run_v3.row_for(store, db, value.reuse_run_id)
            snapshot = run_v3.snapshot_for(source)
            original = RunConfigV3.model_validate_json(source["config_snapshot_json"])
            fingerprint = run_v3.compatibility(snapshot, original)
            for step in db.execute("SELECT * FROM steps WHERE run_id=? AND stage='score_v3' AND status='succeeded'", (source["run_id"],)):
                reuse.append(ReuseV3(source_run_id=source["run_id"], step_id=step["step_id"], stage=step["stage"], key=step["branch_key"],
                    ref=step["output_ref"], hash=step["output_hash"], compatibility_hash=fingerprint))
            if not reuse:
                raise HTTPException(409, "명시한 실행에 성공한 재사용 항목군이 없습니다.")
    return run_v3.enqueue(store, case_id, session_id, value, user, config, enabled=True, reuse=reuse)


def source_for(snapshot):
    return SheetInputV3(input_revision=snapshot.input_revision, input=snapshot.input, catalog_hash=snapshot.batch.catalog_hash,
        protocol_hash=snapshot.batch.protocol_hash, window_rules_hash=snapshot.batch.rules_hash, session=snapshot.session,
        windows=snapshot.batch.windows, preprocess=snapshot.preprocess)


def sheet_document(snapshot, observations, failures, recorded_at):
    source = source_for(snapshot)
    run_id = failures.pop("_run_id")
    return SheetDocumentV3.model_validate_json(encode({"revision": 1, "state": "submitted", "assigned_username": AI_ACCOUNT,
        "rater_name": "AI" + (" · 일부 요청 실패" if failures else ""), "purpose": "independent", "active": True,
        "actor": snapshot.requested_by, "recorded_at": recorded_at, "change_reason": "AI 고정 입력 원자료 생성",
        "source": source.model_dump(mode="json"), "source_hash": analysis.digest(source.model_dump(mode="json")),
        "ai_run_id": run_id, "ai_failures": failures, "sheet": {"sheet_id": "ai-" + run_id, "case_id": snapshot.case_id,
        "session_id": snapshot.session_id, "rater_id": "ai-" + run_id, "rater_kind": "ai", "observations": observations}}))


def clips_for(snapshot, group):
    windows = {key for code in group.item_codes for item in CATALOG.rated_items() if item.code == code for key in item.windows}
    names = {name for window in snapshot.batch.windows if window.window_id in windows and window.status in ("available", "partial") for name in window.clip_names}
    return tuple(clip for clip in snapshot.batch.clips if clip.name in names)


def context(snapshot, group, row):
    clips = clips_for(snapshot, group)
    codes = set(group.item_codes)
    window_ids = {key for item in CATALOG.rated_items() if item.code in codes for key in item.windows}
    return {"run_id": row["run_id"], "audit_actor": snapshot.requested_by, "catalog_version": CATALOG.version,
        "items": [item.model_dump(mode="json") for item in CATALOG.rated_items() if item.code in codes],
        "windows": [window.model_dump(mode="json") for window in snapshot.batch.windows if window.window_id in window_ids],
        "clips": [clip.model_dump(mode="json", exclude={"ref"}) for clip in clips],
        "events": [event.model_dump(mode="json") for event in snapshot.session.recording.events],
        "note_as_data": snapshot.session.note, "sampling": {"production": "native", "request_fps": group.request_fps,
        "mode": group.processing_mode, "media_resolution": group.media_resolution}, "no_cross_clip_count_sum": True}


def normalize(snapshot, group, raw):
    response = AiResponseV3.model_validate_json(encode(raw))
    if len(response.observations) != len(group.item_codes) or {item.code for item in response.observations} != set(group.item_codes):
        raise ValueError("AI 응답의 요청 항목 집합이 정확하지 않습니다.")
    clips = {clip.name: clip for clip in clips_for(snapshot, group)}
    windows = {window.window_id: window for window in snapshot.batch.windows}
    observations = []
    for item in response.observations:
        data = item.model_dump(mode="json")
        data["evidence"] = []
        if item.status == "observed" and (item.opportunity != "present" or item.validity == "unknown" or not item.evidence):
            raise ValueError("관찰값에는 실제 기회·유효성·영상 근거가 필요합니다.")
        for basis in item.evidence:
            clip = clips.get(basis.clip_name)
            window = windows.get(basis.window_id)
            if not clip or not window or clip.name not in window.clip_names or not 0 <= basis.start_seconds < basis.end_seconds <= clip.end_sec - clip.start_sec or not 0 < basis.observed_seconds <= basis.end_seconds - basis.start_seconds:
                raise ValueError("클립·창·실제 확인량 또는 클립 내부 시각이 요청 범위 밖입니다.")
            data["evidence"].append({"video_id": clip.video_id, "video_sha256": snapshot.batch.source_sha256,
                "window_id": basis.window_id, "start_seconds": clip.start_sec + basis.start_seconds,
                "end_seconds": clip.start_sec + basis.end_seconds, "observed_seconds": basis.observed_seconds,
                "note": basis.note, "scoring_exclusion": basis.scoring_exclusion})
        if item.vocalization:
            amount = item.vocalization
            clip = clips.get(amount.clip_name)
            window = windows.get(VOCAL_SEGMENTS.get(item.code))
            if not clip or not window or window.start_sec is None or clip.start_sec != window.start_sec or clip.end_sec != window.end_sec:
                raise ValueError("발성은 원항목의 전체 실제 오디오 창이 필요합니다.")
            duration = window.end_sec - window.start_sec
            if item.status == "observed" and (clip.audio_available_seconds < duration or not amount.whole_interval_judged or
                amount.listened_seconds != duration or amount.cumulative_vocal_seconds > duration or vocal_category(amount.cumulative_vocal_seconds, duration) != item.value):
                raise ValueError("전체 음성/청취량/누적 발성 비중과 원코드가 일치해야 합니다.")
            data["vocalization"] = {"video_id": clip.video_id, "listened_seconds": amount.listened_seconds,
                "cumulative_vocal_seconds": amount.cumulative_vocal_seconds, "whole_interval_judged": amount.whole_interval_judged, "note": amount.note}
        elif item.code in VOCAL_SEGMENTS and item.status == "observed":
            raise ValueError("발성값에 실제 청취/누적 발성량이 없습니다.")
        observations.append(ObservationV3.model_validate_json(encode(data)))
    doc = sheet_document(snapshot, [item.model_dump(mode="json") for item in observations], {"_run_id": "validation"}, now())
    sheets.validate_observations(doc, [item.model_dump(mode="json") for item in observations])
    return [item.model_dump(mode="json") for item in observations]


def stored_group(snapshot, group, payload):
    observations = payload["observations"]
    doc = sheet_document(snapshot, observations, {"_run_id": "validation"}, now())
    sheets.validate_observations(doc, observations)
    if len(observations) != len(group.item_codes) or {item["code"] for item in observations} != set(group.item_codes):
        raise ValueError("adopted AI group differs from its frozen request")
    for item in doc.sheet.observations:
        if item.status == "observed" and (item.opportunity != "present" or item.validity == "unknown" or not item.evidence):
            raise ValueError("adopted observation lacks actual opportunity/evidence")
        if item.status == "observed" and any(basis.observed_seconds <= 0 or basis.end_seconds <= basis.start_seconds for basis in item.evidence):
            raise ValueError("adopted observation has no actual confirmation")
        for basis in item.evidence:
            if not any(clip.video_id == basis.video_id and basis.window_id in clip.window_ids and
                       clip.start_sec <= basis.start_seconds < basis.end_seconds <= clip.end_sec
                       for clip in clips_for(snapshot, group)):
                raise ValueError("adopted evidence falls outside the requested clips")
        if item.status == "observed" and item.code in VOCAL_SEGMENTS:
            window = next(window for window in snapshot.batch.windows if window.window_id == VOCAL_SEGMENTS[item.code])
            duration = window.end_sec - window.start_sec
            amount = item.vocalization
            if not amount or not amount.whole_interval_judged or amount.listened_seconds != duration or vocal_category(amount.cumulative_vocal_seconds, duration) != item.value or not any(
                    clip.video_id == amount.video_id and clip.start_sec == window.start_sec and clip.end_sec == window.end_sec and
                    clip.audio_available_seconds >= duration for clip in clips_for(snapshot, group)):
                raise ValueError("adopted vocal value lacks the complete requested audio")
    return payload


def guarded(worker, row, snapshot):
    worker.check(row)
    run_v3.assets(snapshot)
    run_v3.verify_files(worker.store, snapshot)
    consent(worker.store, row["case_id"])
    with worker.store.connect() as db:
        user = db.execute("SELECT active,role FROM users WHERE username=?", (snapshot.requested_by,)).fetchone()
        if not user or not user["active"] or user["role"] not in ("operator", "admin"):
            raise HTTPException(403, "AI 요청 계정의 운영 권한이 변경되었습니다.")


def stage_result(worker, row, stage):
    with worker.store.connect() as db:
        step = db.execute("SELECT * FROM steps WHERE run_id=? AND stage=? ORDER BY attempt DESC LIMIT 1", (row["run_id"], stage)).fetchone()
    if not step or step["status"] in ("running", "retry_wait"):
        raise run_v3.DependenciesPending()
    return analysis.step_payload(worker.store, row, step) if step["status"] == "succeeded" else None


def collect(worker, row, snapshot):
    config = RunConfigV3.model_validate_json(row["config_snapshot_json"])
    observed, failures = [], {}
    for group in config.stages:
        if group.stage != "score_v3":
            continue
        with worker.store.connect() as db:
            step = db.execute("SELECT * FROM steps WHERE run_id=? AND stage='score_v3' AND branch_key=? ORDER BY attempt DESC LIMIT 1", (row["run_id"], group.key)).fetchone()
        if not step or step["status"] in ("running", "retry_wait"):
            raise run_v3.DependenciesPending()
        if step["status"] == "succeeded":
            payload = stored_group(snapshot, group, analysis.step_payload(worker.store, row, step))
            observed.extend(payload["observations"])
        else:
            code = json.loads(step["usage_json"]).get("code", "request_failed")
            failures[group.key] = code
            observed.extend({"code": item, "value": None, "status": "unobserved", "reason": "AI 요청 오류: " + code} for item in group.item_codes)
    return sheet_document(snapshot, observed, {**failures, "_run_id": row["run_id"]}, now())


def calc_payload(worker, row, snapshot):
    doc = collect(worker, row, snapshot)
    sheets.validate_observations(doc, doc.sheet.model_dump(mode="json")["observations"], complete=True)
    audio, facts = judgements.audio_amounts(worker.store, doc)
    calculations = calculate(doc, audio_available=audio)
    ref, file_hash = sheets.write_document(worker.store, doc.model_dump(mode="json"))
    return {"input": {"sheet_id": doc.sheet.sheet_id, "revision": 1, "ref": ref, "hash": file_hash},
        "calculations": calculations.model_dump(mode="json"), "audio_sources": facts, "usage": {"program_merge": True}}


def calc_document(worker, row, payload):
    ref = SheetReferenceV3.model_validate_json(encode(payload["input"]))
    doc = sheets.read_document(worker.store, ref.ref, ref.hash)
    if doc.ai_run_id != row["run_id"] or doc.sheet.sheet_id != ref.sheet_id or doc.revision != ref.revision or doc.source != source_for(run_v3.snapshot_for(row)):
        raise ValueError("AI calculation input belongs to another run")
    return ref, doc


def basic_data(worker, row, calculation, decisions=None):
    ref, doc = calc_document(worker, row, calculation)
    return {"result_id": "ai-basic-" + row["run_id"], "case_id": row["case_id"], "session_id": row["session_id"], "revision": 1,
        "actor": doc.actor, "recorded_at": doc.recorded_at, "change_reason": "AI 고정 원자료의 기본 계산·판정",
        "input": ref.model_dump(mode="json"), "input_document": doc.model_dump(mode="json"), "rule_version": RULE_VERSION, "rule_hash": RULE_HASH,
        "audio_sources": calculation["audio_sources"], "evaluation_context": {"purpose": "independent", "ai_exposed": False, "exposures": []},
        "calculations": calculation["calculations"], "decisions": decisions or judgements.initial_decisions(doc, ref, CalculationsV3.model_validate_json(encode(calculation["calculations"]))),
        "decision_sources": {key: "ai" if decisions else "automatic" for key in ("attachment", "owner_type", "entry")}}


def convert_decisions(worker, row, calculation, raw):
    edits = judgements.JudgementEditV3.model_validate_json(encode(raw))
    if {item.key for item in edits.decisions} != {"attachment", "owner_type", "entry"} or len(edits.decisions) != 3:
        raise ValueError("three basic decisions are required")
    model = BasicResultV3.model_validate_json(encode(basic_data(worker, row, calculation)))
    original = {item.key: item.model_dump(mode="json") for item in model.decisions}
    observations = {item.code: item for item in model.input_document.sheet.observations}
    used = {item.code: item.used_evidence for item in model.calculations.owner.items}
    result = []
    for edit in edits.decisions:
        if not set(edit.counter_codes) <= set(edit.evidence_codes):
            raise ValueError("counter evidence must be selected from the same raw observations")
        supporting = [basis for code in edit.evidence_codes if code not in edit.counter_codes
                      for basis in (used.get(code, observations[code].evidence) if edit.key == "owner_type" else observations[code].evidence)]
        counter = [basis for code in edit.counter_codes for basis in observations[code].evidence]
        decision = DecisionV3.model_validate_json(encode({**original[edit.key], **edit.model_dump(exclude={"counter_codes"}),
            "evidence": [basis.model_dump(mode="json") for basis in supporting], "counter_evidence": [basis.model_dump(mode="json") for basis in counter]}))
        judgements.validate_judgement(decision, model)
        result.append(decision.model_dump(mode="json"))
    return result


def publish(worker, row, snapshot, calculation, judgement):
    data = basic_data(worker, row, calculation, judgement["decisions"] if judgement else None)
    if judgement is None:
        data["decisions"] = [{**item, "label": None, "status": "held", "reason": "AI 판정 요청/계약 오류로 보류. 관찰 원자료와 계산은 보존."} for item in data["decisions"]]
    model = BasicResultV3.model_validate_json(encode(data))
    for decision in model.decisions:
        judgements.validate_judgement(decision, model)
    result_ref, result_hash = judgements.write_result(worker.store, data)
    guarded(worker, row, snapshot)
    account_hash = password_hash(secrets.token_urlsafe(48))
    doc = model.input_document
    with worker.store.connect(write=True) as db:
        current = run_v3.row_for(worker.store, db, row["run_id"])
        if current["status"] != "running" or current["claim_token"] != row["claim_token"] or current["lease_expires_at"] <= now():
            raise HTTPException(409, "AI 채택 점유가 변경되었습니다.")
        case = worker.store.case(db, snapshot.case_id)
        account = db.execute("SELECT role,active FROM users WHERE username=?", (snapshot.requested_by,)).fetchone()
        if worker.store.manifest(case).consents.analysis_feedback != "confirmed" or not account or not account["active"] or account["role"] not in ("operator", "admin"):
            raise HTTPException(403, "AI 게시 직전 동의 또는 요청 계정 권한이 변경되었습니다.")
        existing = db.execute("SELECT * FROM basic_results WHERE result_id=?", (model.result_id,)).fetchone()
        if existing:
            original = judgements.document_for(worker.store, existing)
            if original != model:
                raise HTTPException(409, "이미 채택한 AI 원본과 다른 결과는 새 실행으로 생성하세요.")
            return {"sheet_id": doc.sheet.sheet_id, "basic_result": judgements.reference(existing), "usage": {"program_merge": True}}
        account = db.execute("SELECT role,active FROM users WHERE username=?", (AI_ACCOUNT,)).fetchone()
        if account and (account["role"] != "developer" or account["active"]):
            raise HTTPException(409, "AI 기록 전용 계정 이름이 다른 계정과 충돌합니다.")
        if not account:
            db.execute("INSERT INTO users(username,password_hash,role,active) VALUES (?,?,'developer',0)", (AI_ACCOUNT, account_hash))
        db.execute("INSERT INTO score_sheets VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (doc.sheet.sheet_id, snapshot.case_id, snapshot.session_id,
            AI_ACCOUNT, doc.sheet.rater_id, doc.rater_name, doc.source_hash, doc.purpose, "submitted", 1, 1, model.input.ref, model.input.hash))
        db.execute("INSERT INTO basic_results VALUES (?,?,?,?,?,?,?)", (model.result_id, doc.sheet.sheet_id, snapshot.case_id, snapshot.session_id, 1, result_ref, result_hash))
        worker.store.audit(db, snapshot.requested_by, snapshot.case_id, "ai.publish", {"run_id": row["run_id"], "sheet_id": doc.sheet.sheet_id,
            "ref": result_ref, "hash": result_hash, "input": model.input.model_dump(mode="json")})
    return {"sheet_id": doc.sheet.sheet_id, "basic_result": {"result_id": model.result_id, "revision": 1, "ref": result_ref, "hash": result_hash}, "usage": {"program_merge": True}}


def handler(worker, snapshot, group, row):
    if group.stage == "calculate_v3":
        collect(worker, row, snapshot)
    def validate(payload):
        if group.stage == "score_v3":
            return stored_group(snapshot, group, payload)
        if group.stage == "calculate_v3":
            _, doc = calc_document(worker, row, payload)
            expected = collect(worker, row, snapshot)
            if doc.sheet.observations != expected.sheet.observations or doc.ai_failures != expected.ai_failures:
                raise ValueError("calculation input differs from the adopted groups")
            audio, facts = judgements.audio_amounts(worker.store, doc)
            if calculate(doc, audio_available=audio).model_dump(mode="json") != payload["calculations"] or facts != payload["audio_sources"]:
                raise ValueError("AI calculations are not derived from the pinned raw observations/audio")
        elif group.stage == "judge_v3":
            calc = stage_result(worker, row, "calculate_v3")
            model = BasicResultV3.model_validate_json(encode(basic_data(worker, row, calc, payload["decisions"])))
            for item in model.decisions:
                judgements.validate_judgement(item, model)
        elif group.stage == "publish_v3":
            link = payload["basic_result"]
            model = judgements.read_result(worker.store, link["ref"], link["hash"])
            if model.result_id != "ai-basic-" + row["run_id"] or model.input.sheet_id != payload["sheet_id"]:
                raise ValueError("published AI identity differs from execution")
        else:
            raise ValueError("unsupported v3 AI stage")
        return payload

    calculation = stage_result(worker, row, "calculate_v3") if group.stage in ("judge_v3", "publish_v3") else None
    if group.stage in ("judge_v3", "publish_v3") and calculation is None:
        raise run_v3.DependenciesPending()
    judgement = stage_result(worker, row, "judge_v3") if group.stage == "publish_v3" else None

    def work(step):
        guarded(worker, row, snapshot)
        if group.stage == "calculate_v3":
            return calc_payload(worker, row, snapshot)
        if group.stage == "publish_v3":
            return publish(worker, row, snapshot, calculation, judgement)
        files = clips_for(snapshot, group) if group.stage == "score_v3" else ()
        if group.stage == "score_v3" and not files:
            windows = {window.window_id: window for window in snapshot.batch.windows}
            observations = []
            for code in group.item_codes:
                item = next(item for item in CATALOG.rated_items() if item.code == code)
                states = [windows[key] for key in item.windows]
                observations.append({"code": code, "value": None, "status": "not_performed" if all(window.status == "not_performed" for window in states) else "unobserved",
                    "reason": "실제 요청 가능한 클립 없음: " + "; ".join(window.reason or window.status for window in states)})
            return {"observations": observations, "usage": {"program_merge": True}}
        info = context(snapshot, group, row) if group.stage == "score_v3" else {
            "run_id": row["run_id"], "audit_actor": snapshot.requested_by, "basic": basic_data(worker, row, calculation),
            "allowed_types": {"attachment": judgements.ATTACHMENT_TYPES, "owner_type": judgements.OWNER_TYPES, "entry": judgements.ENTRY_TYPES}}
        config = {"model": group.model, "prompt": group.prompt, "fps": group.request_fps, "processing_mode": group.processing_mode,
            "media_resolution": group.media_resolution, "thinking_level": group.thinking_level, "max_output_tokens": group.max_output_tokens}
        if step["attempt"] > 1:
            info["repair"] = "이전 응답 계약을 위반했습니다. 제공한 정확한 코드·원라벨·실제 창·근거·누락/기회/유효성을 schema와 대조해 수정하세요."
        worker.reserve_call(row, step)
        raw, usage = worker.observer.request_v3([(worker.store.path(clip.ref), clip) for clip in files], config, info,
            group.response_schema, lambda: guarded(worker, row, snapshot))
        try:
            payload = {"observations": normalize(snapshot, group, raw), "usage": usage} if group.stage == "score_v3" else {
                "decisions": convert_decisions(worker, row, calculation, raw), "usage": usage}
            return validate(payload)
        except (ValueError, KeyError, HTTPException):
            raise ProviderError("v3_schema_invalid", retryable=True, usage=usage) from None
    return validate, work
