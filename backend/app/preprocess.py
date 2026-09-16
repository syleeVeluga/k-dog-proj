"""Local FFmpeg preprocessing: cut the confirmed eight segments of the reference file into immutable, hashed clips.

Stimulus windows (first seconds of 입장·혼자·낯선·재회) are kept at a dense frame rate, the rest sparse (01 §5). Nothing here
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

RULES = json.loads((REPO_ROOT / "resources/rules/preprocess-v1.json").read_text(encoding="utf-8"))


def plan(session, rules=RULES):
    """Clip specs for the reference file: dense window then sparse remainder for stimulus segments, one sparse clip otherwise."""
    if session.segments is None or not session.segments.confirmed:
        raise HTTPException(409, "8구간 시각을 확정한 뒤 전처리할 수 있습니다.")
    try:
        SessionSegments(session_id=session.session_id, video_id=session.segments.video_id, windows=tuple(
            {"segment": w.segment, "start_sec": w.start_sec, "end_sec": w.end_sec, "source": "operator_confirmed"}
            for w in session.segments.windows))
    except ValueError as exc:
        raise HTTPException(422, "8구간의 끝은 시작보다 늦고 절차 순서대로 겹치지 않아야 합니다. 구간을 보완해 다시 확정하세요.") from exc
    clips = []
    for window in session.segments.windows:
        if window.segment in rules["dense_segments"]:
            dense_end = min(window.start_sec + rules["window_sec"], window.end_sec)
            clips.append({"name": f"{window.segment}-dense", "segment": window.segment, "start_sec": window.start_sec,
                          "end_sec": dense_end, "fps": rules["dense_fps"]})
            if dense_end < window.end_sec:
                clips.append({"name": f"{window.segment}-sparse", "segment": window.segment, "start_sec": dense_end,
                              "end_sec": window.end_sec, "fps": rules["sparse_fps"]})
        else:
            clips.append({"name": f"{window.segment}-sparse", "segment": window.segment, "start_sec": window.start_sec,
                          "end_sec": window.end_sec, "fps": rules["sparse_fps"]})
    return clips


def run(store, case_id, session_id, actor, rules=RULES):
    """Probe the reference file, check the confirmed segments against its length, cut every clip, then record the manifest."""
    with store.connect() as db:
        row = store.case(db, case_id)
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
              "source_audio": info["audio_status"], "created_at": now(), "clips": outputs}
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
                    "session_id": session_id, "input_revision": row["input_revision"], "clips": len(outputs)})
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
