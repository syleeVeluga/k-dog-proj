"""Local FFmpeg preprocessing: cut the confirmed eight segments of the reference file into immutable, hashed clips.

Operator-recorded stimulus windows are kept at a dense frame rate, the rest sparse (Excel provisional rule). Nothing here
scores anything; the clips are the input the AI 채점 단계 (P2) will read instead of the multi-gigabyte original.
"""

import hashlib
import json
import os

from fastapi import HTTPException

from app.domain.contracts import SessionSegments
from app.domain.validation import validate_segments
from app.intake import selected_session
from app.media import MediaError, cut_clip, probe
from app.storage import REPO_ROOT, encode, now, uid

RULES = json.loads((REPO_ROOT / "resources/rules/preprocess-v2.json").read_text(encoding="utf-8"))


def plan(session, rules=RULES):
    """Tile each segment without overlaps: sparse before the event, dense event window, sparse remainder."""
    if session.segments is None or not session.segments.confirmed:
        raise HTTPException(409, "8구간 시각을 확정한 뒤 전처리할 수 있습니다.")
    try:
        SessionSegments(session_id=session.session_id, video_id=session.segments.video_id, windows=tuple(
            {"segment": w.segment, "start_sec": w.start_sec, "end_sec": w.end_sec, "source": "operator_confirmed"}
            for w in session.segments.windows))
    except ValueError as exc:
        raise HTTPException(422, "8구간의 끝은 시작보다 늦고 절차 순서대로 겹치지 않아야 합니다. 구간을 보완해 다시 확정하세요.") from exc
    clips = []
    if session.stimuli is None or session.stimuli.video_id != session.segments.video_id:
        raise HTTPException(409, "구간 기준 영상의 자극 시각 4개를 촬영 화면에서 기록하세요.")
    for window in session.segments.windows:
        if window.segment in rules["dense_segments"]:
            moment = getattr(session.stimuli.moments, window.segment)
            if moment is None or not window.start_sec <= moment < window.end_sec:
                raise HTTPException(422, "자극 시각 4개는 각 해당 구간의 시작 이상, 끝 미만이어야 합니다. 미지정·사건 없음·판독 불가는 임의로 채우지 말고 확인하세요.")
            dense_start = max(window.start_sec, moment - rules["before_sec"])
            dense_end = min(moment + rules["after_sec"], window.end_sec)
            if dense_start > window.start_sec:
                clips.append({"name": f"{window.segment}-sparse-before", "segment": window.segment, "start_sec": window.start_sec,
                              "end_sec": dense_start, "fps": rules["sparse_fps"]})
            clips.append({"name": f"{window.segment}-dense", "segment": window.segment, "start_sec": dense_start,
                          "end_sec": dense_end, "fps": rules["dense_fps"]})
            if dense_end < window.end_sec:
                clips.append({"name": f"{window.segment}-sparse", "segment": window.segment, "start_sec": dense_end,
                              "end_sec": window.end_sec, "fps": rules["sparse_fps"]})
        else:
            clips.append({"name": f"{window.segment}-sparse", "segment": window.segment, "start_sec": window.start_sec,
                          "end_sec": window.end_sec, "fps": rules["sparse_fps"]})
    return clips


def run(store, case_id, session_id, actor, rules=RULES, *, expected_revision=None, request_id=None):
    """Probe the reference file, check the confirmed segments against its length, cut every clip, then record the manifest."""
    with store.connect() as db:
        row = store.case(db, case_id, expected=expected_revision)
        manifest = store.manifest(row)
    session = selected_session(manifest, session_id)
    clips = plan(session, rules)
    video = next((v for v in session.videos if v.video_id == session.segments.video_id), None)
    if video is None:
        raise HTTPException(409, "구간 기준 영상이 이 세션에 없습니다.")
    source = store.path(video.storage_ref)
    with source.open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != video.sha256:
            raise MediaError("기준 영상 해시가 등록 당시와 다릅니다.")
    info = probe(source)
    segments = SessionSegments(session_id=session_id, video_id=video.video_id, windows=tuple(
        {"segment": w.segment, "start_sec": w.start_sec, "end_sec": w.end_sec, "source": "operator_confirmed"} for w in session.segments.windows))
    try:
        validate_segments(segments, info["duration_sec"])
    except ValueError as exc:
        raise HTTPException(422, f"확정한 구간이 기준 영상 길이({info['duration_sec']:.1f}초)를 넘습니다.") from exc
    batch = uid()
    folder = f"clips/{case_id}/{session_id}/{batch}"
    store.path(folder).mkdir(parents=True, exist_ok=False)
    outputs = []
    for clip in clips:
        ref = f"{folder}/{clip['name']}.mp4"
        cut_clip(source, store.path(ref), clip["start_sec"], clip["end_sec"], clip["fps"], rules)
        path = store.path(ref)
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        outputs.append({**clip, "ref": ref, "hash": digest, "size_bytes": path.stat().st_size})
    result = {"schema_version": "1.0", "rules_version": rules["version"], "case_id": case_id, "session_id": session_id,
              "input_revision": row["input_revision"], "video_id": video.video_id, "source_sha256": video.sha256,
              "source_duration_sec": info["duration_sec"], "source_width": info["width"], "source_height": info["height"],
              "source_audio": info["audio_status"], "created_at": now(), "clips": outputs,
              "stimuli": session.stimuli.model_dump()}
    manifest_ref = f"{folder}/clips.json"
    data = encode(result).encode("utf-8")
    with store.path(manifest_ref).open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    # The audit row is what keeps these files referenced for backup and offline cleanup; a revision bump during cutting is a 409.
    with store.connect(write=True) as db:
        store.case(db, case_id, expected=row["input_revision"])
        store.audit(db, actor, case_id, "preprocess.complete", {"ref": manifest_ref, "hash": hashlib.sha256(data).hexdigest(),
                    "session_id": session_id, "input_revision": row["input_revision"], "clips": len(outputs), "request_id": request_id})
    return result


def latest(store, db, case_id, session_id):
    """The newest recorded clip manifest for this session, or None."""
    for entry in db.execute("SELECT detail_json FROM changes WHERE target=? AND action='preprocess.complete' ORDER BY rowid DESC", (case_id,)):
        detail = json.loads(entry[0])
        if detail["session_id"] != session_id:
            continue
        raw = store.path(detail["ref"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != detail["hash"]:
            raise HTTPException(409, "전처리 기록 파일 해시가 일치하지 않습니다.")
        return json.loads(raw)
    return None


def execute(store, case_id, session_id, actor, *, expected_revision=None):
    """One explicit request, serialized with CLI preprocessing and offline maintenance."""
    from app.maintenance import runtime_lock
    with runtime_lock(store, "preprocess"):
        with store.connect(write=True) as db:
            row = store.case(db, case_id, expected=expected_revision)
            session = selected_session(store.manifest(row), session_id)
            plan(session)
            request_id = uid()
            revision = row["input_revision"]
            store.audit(db, actor, case_id, "preprocess.started", {"request_id": request_id, "session_id": session_id, "input_revision": revision})
        try:
            return run(store, case_id, session_id, actor, expected_revision=revision, request_id=request_id)
        except (HTTPException, MediaError, OSError, ValueError) as exc:
            message = exc.detail if isinstance(exc, HTTPException) else "영상 형식, FFmpeg 설치, 저장 공간과 파일 접근 권한을 확인한 뒤 다시 시작하세요."
            with store.connect(write=True) as db:
                store.audit(db, actor, case_id, "preprocess.failed", {"request_id": request_id, "session_id": session_id, "input_revision": revision, "message": message})
            raise HTTPException(exc.status_code if isinstance(exc, HTTPException) else 422, message) from exc


def status(store, case_id, session_id):
    from app.maintenance import runtime_lock
    with store.connect() as db:
        row = store.case(db, case_id)
        manifest = store.manifest(row)
        session = next((s for s in manifest.sessions if s.session_id == session_id), None)
        if session is None:
            raise HTTPException(422, "이 참가자의 촬영 회차가 아닙니다.")
        result = latest(store, db, case_id, session_id)
        entries = db.execute("SELECT action,detail_json FROM changes WHERE target=? AND action IN ('preprocess.started','preprocess.failed','preprocess.complete') ORDER BY rowid DESC", (case_id,)).fetchall()
        entry = next(((e["action"], json.loads(e["detail_json"])) for e in entries if json.loads(e["detail_json"]).get("session_id") == session_id), None)
        latest_start = db.execute("SELECT detail_json FROM changes WHERE action='preprocess.started' ORDER BY rowid DESC LIMIT 1").fetchone()
    video = next((v for v in session.videos if session.segments and v.video_id == session.segments.video_id), None)
    planned_clips = []
    try:
        planned_clips = plan(session)
        ready = video is not None and manifest.selected_session_id == session_id
        message = "실행 가능합니다. 기준 영상과 처리 규칙을 확인한 뒤 시작하세요." if ready else "운영자가 이 촬영 회차를 저장 대상으로 선택해야 합니다."
    except HTTPException as exc:
        ready, message = False, exc.detail
    state = "ready" if ready else "not_ready"
    readiness_message = message
    if entry:
        action, detail = entry
        if action == "preprocess.started":
            active = latest_start and json.loads(latest_start[0])["request_id"] == detail["request_id"]
            if active:
                try:
                    with runtime_lock(store, "preprocess"):
                        active = False
                except HTTPException:
                    pass
            state = "running" if active else "interrupted"
            message = "전처리 중입니다. 완료된 산출물만 공개합니다." if active else "전처리가 중단되었습니다. 완료되지 않은 파일은 결과로 사용하지 않습니다. 상태를 확인한 뒤 다시 시작하세요."
        elif action == "preprocess.failed":
            state, message = "failed", detail["message"]
        else:
            state, message = "complete", "전처리가 완료되었습니다."
    outdated = bool(result and (result["input_revision"] != row["input_revision"] or result["rules_version"] != RULES["version"] or not video or result["source_sha256"] != video.sha256))
    return {"status": state, "message": message, "readiness_message": readiness_message, "planned_clips": planned_clips, "ready": ready, "outdated": outdated,
            "rules_version": RULES["version"], "dense_fps": RULES["dense_fps"], "sparse_fps": RULES["sparse_fps"],
            "input_revision": row["input_revision"], "video_name": video.original_name if video else None, "result": result}
