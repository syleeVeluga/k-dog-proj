"""S1 multi-view raw observation normalization and immutable AI publication."""

import json
import secrets
import time
from types import SimpleNamespace
from fastapi import HTTPException
from pydantic import ValidationError, field_validator

from . import analysis, judgements_v4 as judgements, sheets_v4 as sheets
from .domain.catalog_v4 import (AUTO_CODES, COUNT_CODES, MEMO_CODES, NUMERIC_CODES, OPTIONAL_CODES, VOCAL_CODES,
                                load_catalog_v4)
from .domain.contracts_v4 import EvidenceV4, LinkedMemoV4, ObservationV4
from .domain.runs_v4 import RunConfigV4
from .domain.results_v4 import BasicResultV4, CalculationConditionsV4, CalculationsV4
from .domain.scoring_ai_v4 import AiResponseV4
from .domain.sheets_v4 import AI_ACCOUNT, SheetDocumentV4, SheetInputV4, SheetReferenceV4
from .auth import password_hash
from .gemini import ProviderError
from .gemini_v4 import GeminiScorerV4
from .recording_v4 import build_windows_v4
from .scoring_v4 import RULE_HASH, RULE_VERSION, calculate, verify_rules, vocal_score
from .storage import encode, now

VERSION = "ai-scoring-20261002-s1.1-1"
CATALOG = load_catalog_v4()


class AiRevealResultV4(sheets.SheetRevealResultV4):
    results: list[BasicResultV4]

    @field_validator("results", mode="before")
    @classmethod
    def results_contract(cls, values):
        return [BasicResultV4.model_validate_json(encode(value)) if isinstance(value, dict) else value for value in values]


class AiReadinessV4(sheets.Model):
    active_version: str
    planned_provider_calls: int
    enabled: bool
    judgement_status: str = "policy_pending_D04"


def readiness(store):
    from . import settings_v4
    with store.connect() as db:
        version = settings_v4.active(db)
        pipeline = settings_v4.load(store, db, version) if version != "inactive" else None
    return {"active_version": version, "planned_provider_calls": sum(group["provider_call"] for group in groups().values()),
            "enabled": pipeline is not None and pipeline.raw_observation_scope_confirmed,
            "judgement_status": "policy_pending_D04"}


def reveal(store, sheet_id, value, user):
    disclosed = sheets.revise(store, sheet_id, value, user, "reveal")
    target = SheetDocumentV4.model_validate_json(encode(disclosed["target"]))
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


def start(store, case_id, session_id, value, user):
    from . import run_v4, settings_v4
    from .domain.runs_v4 import ReuseV4
    sheets.manager(user)
    with store.connect() as db:
        version = value.settings_version or settings_v4.active(db)
        if version == "inactive":
            raise HTTPException(503, "S1 AI 설정을 먼저 저장·활성화하세요.")
        pipeline = settings_v4.load(store, db, version)
        if not pipeline.raw_observation_scope_confirmed:
            raise HTTPException(503, "S1 관찰 원자료 범위를 확인한 운영 설정이 필요합니다.")
    config = configuration(version, pipeline)
    reuse = []
    if value.reuse_run_id:
        with store.connect() as db:
            source = run_v4.row_for(store, db, value.reuse_run_id)
            original = RunConfigV4.model_validate_json(source["config_snapshot_json"])
            fingerprint = run_v4.compatibility(run_v4.snapshot_for(source), original)
            for step in db.execute("SELECT * FROM steps WHERE run_id=? AND stage='score_v4' AND status='succeeded'", (source["run_id"],)):
                reuse.append(ReuseV4(source_run_id=source["run_id"], step_id=step["step_id"], stage=step["stage"], key=step["branch_key"],
                    ref=step["output_ref"], hash=step["output_hash"], compatibility_hash=fingerprint))
            if not reuse:
                raise HTTPException(409, "명시한 실행에 성공한 S1 재사용 항목군이 없습니다.")
    return run_v4.enqueue(store, case_id, session_id, value, user, config, enabled=True, reuse=reuse)


def groups():
    """Group only identical windows, modality, whole-window and opportunity conditions."""
    result = {}
    for item in CATALOG.rated_items():
        signature = {"windows": list(item.windows), "usage": item.usage,
                     "modality": "audio" if item.code in VOCAL_CODES else "visual",
                     "whole": item.whole_interval_required or item.code in VOCAL_CODES,
                     "opportunity_codes": list(item.opportunity_codes), "pending": item.code == "개21"}
        key = "group-" + analysis.digest(signature)[:12]
        result.setdefault(key, {**signature, "codes": [], "provider_call": item.code != "개21"})["codes"].append(item.code)
    return result


def response_schema(codes):
    schema = AiResponseV4.model_json_schema()
    # The provider must emit explicit state/evidence; persisted model defaults remain compatible.
    for definition in [schema, *schema["$defs"].values()]:
        definition["required"] = list(definition["properties"])
        version = definition["properties"]["schema_version"]
        version["enum"] = [version.pop("const")]
    row = schema["$defs"]["AiRowV4"]
    row["properties"]["code"]["enum"] = list(codes)
    memo = set(codes) <= set(MEMO_CODES)
    observed = {"status": {"enum": ["observed"]},
                "value": {"type": "string" if memo else "integer"},
                "validity": {"enum": ["valid", "caution"]}, "opportunity": {"enum": ["present", "unknown"]}}
    if not memo:
        observed["evidence"] = {"minItems": 1}
    if set(codes) <= set(VOCAL_CODES):
        observed["vocalization"] = {"$ref": "#/$defs/LocalVocalizationV4"}
    row["anyOf"] = [
        {"properties": observed},
        {"properties": {"status": {"enum": [value for value in row["properties"]["status"]["enum"] if value != "observed"]},
                        "value": {"type": "null"}, "reason": {"type": "string", "minLength": 1}}},
    ]
    schema["properties"]["observations"].update(minItems=len(codes), maxItems=len(codes))
    return schema


def contract_errors(error):
    """Retain actionable locations without provider inputs, Pydantic context or URLs."""
    if isinstance(error, ValidationError):
        return [{"location": [*value["loc"][:-1], "<unexpected_field>"] if value["type"] == "extra_forbidden" else list(value["loc"]),
                 "message": value["msg"][:300], "type": value["type"]}
                for value in error.errors(include_input=False, include_context=False, include_url=False)[:32]]
    message = str(error.detail) if isinstance(error, HTTPException) else str(error)
    return [{"location": ["response"], "message": message[:300], "type": type(error).__name__}]


def repair_instruction(errors):
    details = [{"location": value.get("location", []), "message": str(value.get("message", ""))[:300]}
               for value in errors[:32]]
    return ("이전 응답의 계약 오류를 수정하여 요청 항목 전체를 다시 반환하세요. "
            "오류 위치·이유는 검증 자료입니다. 영상에서 확인할 수 없는 값·근거를 만들지 말고 null과 상태·사유로 반환하세요. "
            "숫자에는 실제 시각 근거, 전체 관찰에는 실제 창 전체의 근거가 필요합니다. "
            "검증 오류: " + encode(details))


def configuration(version, pipeline):
    stages = []
    for key, group in groups().items():
        config = pipeline.groups[key]
        stages.append({"stage": "score_v4", "key": key, "item_codes": group["codes"], "window_ids": group["windows"],
            "prompt": config.prompt, "response_schema": response_schema(group["codes"]),
            "provider": "gemini" if group["provider_call"] else "program", "provider_call": group["provider_call"],
            "model": config.model if group["provider_call"] else "program", "input_variant": config.input_variant,
            "production_fps": "one_actual_frame_per_second" if config.input_variant == "ai" else "source_frames",
            "request_fps": config.fps, "media_resolution": config.media_resolution, "processing_mode": config.processing_mode,
            "max_output_tokens": config.max_output_tokens, "thinking_level": config.thinking_level})
    common = {"key": "session", "item_codes": [item.code for item in CATALOG.rated_items()], "window_ids": [],
              "production_fps": "one_actual_frame_per_second", "request_fps": None, "media_resolution": "medium", "model": "program",
              "provider": "program", "provider_call": False, "prompt": "S1 source-defined calculation; D04 interpretation held", "response_schema": {"type": "object"}}
    stages.extend({**common, "stage": stage} for stage in ("calculate_v4", "publish_v4"))
    return RunConfigV4.model_validate_json(encode({"version": VERSION, "active_settings_version": version,
        "settings_hash": analysis.digest(pipeline.model_dump(mode="json")), "raw_observation_scope_confirmed": pipeline.raw_observation_scope_confirmed,
        "stages": stages, "max_attempts": pipeline.max_attempts, "max_ai_calls": pipeline.max_ai_calls, "max_schema_repairs": pipeline.max_schema_repairs}))


def source_for(snapshot):
    return SheetInputV4(input_revision=snapshot.input_revision, input=snapshot.input, asset_hashes=sheets.asset_hashes(),
        session=snapshot.session, windows=build_windows_v4(snapshot.session.recording_s1), batch_id=snapshot.batch.batch_id,
        preprocess=snapshot.preprocess)


def sheet_document(snapshot, observations, failures, recorded_at, run_id, *, linked_memos=()):
    source = source_for(snapshot)
    capture = snapshot.session.recording_s1
    phases = [{"code": f"개{38+i}", "proximity_exception": phase.proximity_exception,
               "note": phase.proximity_note, "evidence": []} for i, phase in enumerate(capture.walk_phases)]
    return SheetDocumentV4.model_validate_json(encode({"revision": 1, "state": "submitted", "assigned_username": AI_ACCOUNT,
        "rater_name": "AI" + (" · 일부 요청 실패" if failures else ""), "purpose": "independent", "origin": "ai_service", "active": True,
        "actor": snapshot.requested_by, "recorded_at": recorded_at, "change_reason": "S1 AI 고정 원자료 생성",
        "source": source.model_dump(mode="json"), "source_hash": analysis.digest(source.model_dump(mode="json")),
        "ai_run_id": run_id, "ai_failures": failures, "sheet": {"sheet_id": "ai-"+run_id, "case_id": snapshot.case_id,
            "session_id": snapshot.session_id, "batch_id": snapshot.batch.batch_id, "rater_id": "ai-"+run_id, "rater_kind": "ai",
            "input_revision": snapshot.input_revision, "input_sha256": snapshot.input.manifest_hash,
            "observations": observations, "walk_phases": phases, "linked_memos": linked_memos}}))


def clips_for(snapshot, group):
    ids = {key for window in snapshot.batch.windows if window.window.window_id in group.window_ids
           for view in window.views if view.availability in ("available", "partial") for key in view.clip_ids}
    return tuple(clip for clip in snapshot.batch.clips if clip.clip_id in ids and clip.status in ("complete", "partial") and getattr(clip, group.input_variant) is not None)


def context(snapshot, group, row):
    clips = clips_for(snapshot, group)
    return {"run_id": row["run_id"], "audit_actor": snapshot.requested_by,
        "identity": {"case_id": snapshot.case_id, "session_id": snapshot.session_id, "batch_id": snapshot.batch.batch_id},
        "catalog_version": CATALOG.version, "items": [item.model_dump(mode="json") for item in CATALOG.rated_items() if item.code in group.item_codes],
        "windows": [window.model_dump(mode="json") for window in snapshot.batch.windows if window.window.window_id in group.window_ids],
        "clips": [{"clip_id": clip.clip_id, "video_id": clip.video_id, "camera_id": clip.camera_id,
                   "reference_offset_seconds": clip.offset_seconds, "source_start_seconds": clip.source_start_seconds,
                   "source_end_seconds": clip.source_end_seconds, "window_ids": clip.window_ids,
                   "file": getattr(clip, group.input_variant).model_dump(mode="json", exclude={"ref"})} for clip in clips],
        "capture_events": [event.model_dump(mode="json") for event in snapshot.session.recording_s1.events],
        "sampling": {"production": group.production_fps, "request_fps": group.request_fps, "mode": group.processing_mode,
                     "media_resolution": group.media_resolution}, "no_cross_view_count_sum": True,
        "pending_policies": {"개21": "D03 전체 30초 집계 미승인; null policy_pending", "보5": "서로 다른 사건간 종합 미승인; 한 사건만 확정 가능"}}


def normalize(snapshot, group, raw):
    response = AiResponseV4.model_validate_json(encode(raw))
    if (response.case_id, response.session_id, response.batch_id) != (snapshot.case_id, snapshot.session_id, snapshot.batch.batch_id):
        raise ValueError("provider returned another subject/session/batch")
    if len(response.observations) != len(group.item_codes) or {item.code for item in response.observations} != set(group.item_codes):
        raise ValueError("provider must return each exact direct item once")
    available = {clip.clip_id: clip for clip in clips_for(snapshot, group)}
    videos = {video.video_id: video for video in snapshot.session.videos}
    windows = {window.window.window_id: window for window in snapshot.batch.windows}
    def convert(local):
        clip = available.get(local.clip_id)
        if clip is None or local.window_id not in clip.window_ids or local.window_id not in group.window_ids:
            raise ValueError("evidence references an unrequested clip/window")
        derivative = getattr(clip, group.input_variant)
        if local.end_seconds > derivative.duration_seconds or local.end_seconds <= local.start_seconds:
            raise ValueError("evidence lies outside actual derivative duration")
        start = local.start_seconds + derivative.source_time_offset_seconds
        end = local.end_seconds + derivative.source_time_offset_seconds
        if not clip.source_start_seconds <= start < end <= clip.source_end_seconds:
            raise ValueError("mapped evidence lies outside original cut range")
        basis = EvidenceV4(video_id=clip.video_id, video_sha256=videos[clip.video_id].sha256, camera_id=clip.camera_id,
                           window_id=local.window_id, start_seconds=start, end_seconds=end, observed_seconds=local.observed_seconds, note=local.note)
        return basis, (start-clip.offset_seconds, end-clip.offset_seconds)
    events, ranges = {}, {}
    for event in response.events:
        if event.event_id in events or not event.item_codes or not set(event.item_codes) <= set(group.item_codes):
            raise ValueError("duplicate/foreign shared event identity")
        converted = [convert(value) for value in event.views]
        low, high = max(value[1][0] for value in converted), min(value[1][1] for value in converted)
        if low >= high:
            raise ValueError("camera views cannot identify the same event at disjoint reference times")
        if len({value.clip_id for value in event.views}) != len(event.views):
            raise ValueError("one event cannot repeat the same camera clip")
        for other_id, (other_low, other_high) in ranges.items():
            if set(event.item_codes) & set(events[other_id].item_codes) and low < other_high and high > other_low:
                raise ValueError("overlapping same-item events must share one event identity across cameras")
        events[event.event_id] = event
        ranges[event.event_id] = (low, high)
    observations = []
    for item in response.observations:
        if item.code in AUTO_CODES or len(set(item.event_ids)) != len(item.event_ids) or any(key not in events or item.code not in events[key].item_codes for key in item.event_ids):
            raise ValueError("automatic item or nonexistent/duplicate event reference")
        if item.code == "개21" and (item.value is not None or item.status != "policy_pending"):
            raise ValueError("D03 count aggregation cannot be asserted by the model")
        if item.code == "보5" and item.status == "observed" and len(item.event_ids) != 1:
            raise ValueError("보5 requires one explicit speech event; cross-event aggregation remains pending")
        if item.code in COUNT_CODES and item.code != "개21" and item.status == "observed" and (type(item.value) is not int or item.value != len(item.event_ids)):
            raise ValueError("counts equal unique common events, never camera views")
        converted = [convert(value)[0] for value in item.evidence]
        for key in item.event_ids:
            event_bases = [convert(value)[0] for value in events[key].views]
            # Descriptions may differ by item; source identity, times and observation amount must match.
            if not any(basis.model_dump(exclude={"note"}) == retained.model_dump(exclude={"note"})
                       for basis in event_bases for retained in converted):
                raise ValueError("row must retain the actual shared-event evidence")
        if item.code in VOCAL_CODES and item.status == "observed":
            if item.vocalization is None:
                raise ValueError("vocal category needs full listened seconds and cumulative seconds")
            representative = {windows[key].representative_audio_video_id for key in group.window_ids}
            if any(basis.video_id not in representative for basis in converted):
                raise ValueError("vocalization uses the selected representative audio, not a camera sum")
            if vocal_score(item.vocalization.listened_seconds, item.vocalization.cumulative_vocal_seconds) != item.value:
                raise ValueError("vocal category differs from actual duration ratio")
            for local in item.evidence:
                clip = available[local.clip_id]
                derivative = getattr(clip, group.input_variant)
                if not sheets._covered([(span.start_seconds, span.end_seconds) for span in derivative.audio_ranges], local.start_seconds, local.end_seconds):
                    raise ValueError("derivative has missing audio over claimed listening evidence")
        value = item.model_dump(mode="json", exclude={"event_ids"})
        value["evidence"] = [basis.model_dump(mode="json") for basis in converted]
        observations.append(ObservationV4.model_validate_json(encode(value)).model_dump(mode="json"))
    linked = []
    for memo in response.linked_memos:
        if not memo.item_codes or not set(memo.item_codes) <= set(group.item_codes):
            raise ValueError("linked memo must refer only to requested observations")
        linked.append(LinkedMemoV4(text=memo.text, item_codes=memo.item_codes, evidence=tuple(convert(value)[0] for value in memo.evidence)).model_dump(mode="json"))
    doc = sheet_document(snapshot, observations, {}, "validation", "validation", linked_memos=linked)
    sheets.validate_observations(doc, sheets.analysis_input(doc).model_dump(mode="json"))
    return {"observations": observations, "linked_memos": linked,
            "events": [event.model_dump(mode="json") for event in response.events]}


def program_group(snapshot, group):
    if group.item_codes == ("개21",):
        reason, status = "D03: 반응 가능한 기회와 30초 전체 집계 규칙 미승인", "policy_pending"
    elif not clips_for(snapshot, group):
        windows = [window.window for window in snapshot.batch.windows if window.window.window_id in group.window_ids]
        status = "not_performed" if windows and all(window.status == "not_performed" for window in windows) else "unobserved"
        reason = "실제 요청 가능한 유효 클립 없음: " + "; ".join(reason for window in windows for reason in (window.reasons or (window.status,)))
    else:
        return None
    raw = [{"code": code, "value": None, "status": status, "reason": reason} for code in group.item_codes]
    doc = sheet_document(snapshot, raw, {}, now(), "validation")
    return {"observations": [item.model_dump(mode="json") for item in doc.sheet.observations], "linked_memos": [],
            "events": [], "program_reason": reason}


def stored_group(snapshot, group, payload):
    expected = program_group(snapshot, group)
    if expected is None:
        expected = normalize(snapshot, group, payload["response"])
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError("adopted S1 observations differ from their frozen source response")
    if "program_reason" in payload and "program_reason" not in expected:
        raise ValueError("provider response cannot replace an observable group with a program result")
    return payload


def guarded(worker, row, snapshot):
    from . import run_v4
    worker.check(row)
    run_v4.assets(snapshot)
    run_v4.verify_files(worker.store, snapshot)
    with worker.store.connect() as db:
        run_v4.check_access(worker.store, db, row)


def stage_result(worker, row, stage):
    from .run_v4 import DependenciesPending
    with worker.store.connect() as db:
        step = db.execute("SELECT * FROM steps WHERE run_id=? AND stage=? ORDER BY attempt DESC LIMIT 1", (row["run_id"], stage)).fetchone()
    if not step or step["status"] in ("running", "retry_wait"):
        raise DependenciesPending()
    return analysis.step_payload(worker.store, row, step) if step["status"] == "succeeded" else None


def collect(worker, row, snapshot):
    from .run_v4 import DependenciesPending
    config = RunConfigV4.model_validate_json(row["config_snapshot_json"])
    observations, linked_memos, failures = [], [], {}
    for group in config.stages:
        if group.stage != "score_v4":
            continue
        with worker.store.connect() as db:
            step = db.execute("SELECT * FROM steps WHERE run_id=? AND stage='score_v4' AND branch_key=? ORDER BY attempt DESC LIMIT 1", (row["run_id"], group.key)).fetchone()
        if not step or step["status"] in ("running", "retry_wait"):
            raise DependenciesPending()
        if step["status"] == "succeeded":
            payload = stored_group(snapshot, group, analysis.step_payload(worker.store, row, step))
            observations.extend(payload["observations"])
            linked_memos.extend(payload["linked_memos"])
        else:
            code = json.loads(step["usage_json"]).get("code", "request_failed")
            failures[group.key] = code
            observations.extend({"code": item, "value": None, "status": "unobserved", "reason": "AI 요청 오류: " + code} for item in group.item_codes)
    return sheet_document(snapshot, observations, failures, row["created_at"], row["run_id"], linked_memos=linked_memos)


def calc_payload(worker, row, snapshot):
    started = time.monotonic()
    doc = collect(worker, row, snapshot)
    sheets.validate_observations(doc, doc.sheet.model_dump(mode="json"), complete=True)
    audio, facts = judgements.audio_amounts(worker.store, doc)
    calculations = calculate(doc, audio_available=audio)
    ref, file_hash = sheets.write_document(worker.store, doc.model_dump(mode="json"))
    return {"input": {"sheet_id": doc.sheet.sheet_id, "revision": 1, "ref": ref, "hash": file_hash},
        "calculations": calculations.model_dump(mode="json"), "audio_sources": facts,
        "usage": {"program_merge": True, "timing": {"calculation_seconds": time.monotonic()-started}}}


def calc_document(worker, row, payload):
    from .run_v4 import snapshot_for
    ref = SheetReferenceV4.model_validate_json(encode(payload["input"]))
    doc = sheets.read_document(worker.store, ref.ref, ref.hash)
    if doc.ai_run_id != row["run_id"] or doc.sheet.sheet_id != ref.sheet_id or doc.revision != ref.revision or doc.source != source_for(snapshot_for(row)):
        raise ValueError("S1 calculation input belongs to another execution")
    return ref, doc


def basic_data(worker, row, calculation):
    ref, doc = calc_document(worker, row, calculation)
    calculated = CalculationsV4.model_validate_json(encode(calculation["calculations"]))
    decisions = judgements.initial_decisions(doc, ref, calculated)
    return {"result_id": "ai-basic-"+row["run_id"], "case_id": row["case_id"], "session_id": row["session_id"], "revision": 1,
        "actor": doc.actor, "recorded_at": doc.recorded_at, "change_reason": "S1 AI 고정 원자료의 기본 계산; D04 AI 해석 보류",
        "input": ref.model_dump(mode="json"), "input_document": doc.model_dump(mode="json"), "rule_version": RULE_VERSION,
        "rule_hash": RULE_HASH, "rule_snapshot": verify_rules(), "conditions": CalculationConditionsV4().model_dump(mode="json"),
        "audio_sources": calculation["audio_sources"], "evaluation_context": {"purpose": "independent", "ai_exposed": False, "exposures": []},
        "calculations": calculation["calculations"], "automatic_decisions": decisions, "decisions": decisions,
        "decision_sources": {item["key"]: "automatic" for item in decisions}}


def publish(worker, row, snapshot, calculation):
    from . import run_v4
    started = time.monotonic()
    data = basic_data(worker, row, calculation)
    model = BasicResultV4.model_validate_json(encode(data))
    result_ref, result_hash = judgements.write_result(worker.store, data)
    guarded(worker, row, snapshot)
    identities = run_v4.verify_files(worker.store, snapshot)
    account_hash = password_hash(secrets.token_urlsafe(48))
    doc = model.input_document
    with worker.store.connect(write=True) as db:
        current = run_v4.row_for(worker.store, db, row["run_id"])
        if current["status"] != "running" or current["claim_token"] != row["claim_token"] or current["lease_expires_at"] <= now():
            raise HTTPException(409, "S1 AI 채택 점유가 변경되었습니다.")
        run_v4.check_access(worker.store, db, current)
        run_v4.check_stamps(worker.store, identities)
        existing = db.execute("SELECT * FROM basic_results WHERE result_id=?", (model.result_id,)).fetchone()
        if existing:
            if judgements.document_for(worker.store, existing) != model:
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
    return {"sheet_id": doc.sheet.sheet_id, "basic_result": {"result_id": model.result_id, "revision": 1, "ref": result_ref, "hash": result_hash},
            "usage": {"program_merge": True, "timing": {"publish_seconds": time.monotonic()-started}}}


def handler(worker, snapshot, group, row):
    from .run_v4 import DependenciesPending
    if group.stage == "calculate_v4":
        collect(worker, row, snapshot)
    calculation = stage_result(worker, row, "calculate_v4") if group.stage == "publish_v4" else None
    if group.stage == "publish_v4" and calculation is None:
        raise DependenciesPending()

    def validate(payload):
        if group.stage == "score_v4":
            return stored_group(snapshot, group, payload)
        if group.stage == "calculate_v4":
            _, doc = calc_document(worker, row, payload)
            expected = collect(worker, row, snapshot)
            if doc != expected:
                raise ValueError("S1 calculation input differs from the adopted raw observations")
            audio, facts = judgements.audio_amounts(worker.store, doc)
            if calculate(doc, audio_available=audio).model_dump(mode="json") != payload["calculations"] or facts != payload["audio_sources"]:
                raise ValueError("S1 calculation differs from pinned observation/audio")
        elif group.stage == "publish_v4":
            link = payload["basic_result"]
            model = judgements.read_result(worker.store, link["ref"], link["hash"])
            expected = BasicResultV4.model_validate_json(encode(basic_data(worker, row, calculation)))
            if model != expected or model.input.sheet_id != payload["sheet_id"]:
                raise ValueError("published AI result differs from this execution")
        else:
            raise ValueError("unsupported S1 stage")
        return payload

    def work(step):
        guarded(worker, row, snapshot)
        if group.stage == "calculate_v4":
            return calc_payload(worker, row, snapshot)
        if group.stage == "publish_v4":
            return publish(worker, row, snapshot, calculation)
        program = program_group(snapshot, group)
        if program is not None:
            return {**program, "usage": {"program_merge": True}}
        info = context(snapshot, group, row)
        config = {"model": group.model, "prompt": group.prompt, "fps": group.request_fps, "processing_mode": group.processing_mode,
            "media_resolution": group.media_resolution, "thinking_level": group.thinking_level, "max_output_tokens": group.max_output_tokens}
        if step["attempt"] > 1:
            with worker.store.connect() as db:
                previous = db.execute("SELECT usage_json FROM steps WHERE run_id=? AND stage=? AND branch_key=? "
                    "AND attempt<? ORDER BY attempt DESC",
                    (row["run_id"], group.stage, group.key, step["attempt"])).fetchall()
            history = [json.loads(value[0]) for value in previous]
            errors = next((value["contract_errors"] for value in history if value.get("contract_errors")), [])
            info["repair"] = repair_instruction(errors)
        files = [(worker.store.path(getattr(clip, group.input_variant).ref),
                  SimpleNamespace(clip_id=clip.clip_id, size_bytes=getattr(clip, group.input_variant).size_bytes))
                 for clip in clips_for(snapshot, group)]
        worker.reserve_call(row, step)
        observer = worker.observer if hasattr(worker.observer, "request_v4") else GeminiScorerV4(worker.store)
        raw, usage = observer.request_v4(files, config, info, group.response_schema, lambda: guarded(worker, row, snapshot))
        try:
            payload = {**normalize(snapshot, group, raw), "response": raw, "usage": usage}
            if step["attempt"] > 1:
                timing = usage.setdefault("timing", {})
                timing["repair_seconds"] = sum(timing.values())
            return validate(payload)
        except (ValueError, KeyError, HTTPException) as exc:
            usage["contract_errors"] = contract_errors(exc)
            raise ProviderError("v4_schema_invalid", retryable=True, usage=usage) from None
    return validate, work
