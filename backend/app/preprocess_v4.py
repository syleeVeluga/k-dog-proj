"""S1 local preprocessing with immutable attempts and separately retained observation windows."""

import hashlib
import json
import os
from pathlib import Path

from fastapi import HTTPException

from . import media
from .domain.catalog_v4 import RESOURCES, load_catalog_v4, load_rules_v4
from .domain.media_v4 import StoredMediaV4
from .domain.preprocess_v4 import (BatchV4, ClipFileV4, FileV4, PhysicalClipV4, PreprocessRequestV4,
                                    PreprocessStatusV4, TimeRangeV4, ViewWindowV4, WindowV4)
from .intake import selected_session
from .input_models_v4 import ManifestV4
from .maintenance import file_hash, managed_path, runtime_lock
from .recording_v4 import build_windows_v4, item_capture_gates_v4
from .storage import encode, now, uid

CUT_SETTINGS = {"version": "s1-cut-1", "source_fps": "passthrough", "ai_fps": "first_actual_frame_per_second",
                "video_codec": "libx264", "crf": 20, "audio": "continuous_aac", "pixel_format": "yuv420p"}


def _digest(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def union(ranges):
    result = []
    for start, end in sorted(ranges):
        if end <= start:
            continue
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return result


def intersection(left, right):
    return union((max(a, c), min(b, d)) for a, b in left for c, d in right)


def subtract(ranges, removed):
    result = union(ranges)
    for start, end in union(removed):
        result = [piece for a, b in result for piece in ((a, min(b, start)), (max(a, end), b))
                  if piece[1] > piece[0]]
    return result


def _ranges(values):
    return tuple(TimeRangeV4(start_seconds=a, end_seconds=b) for a, b in union(values))


def _seconds(values):
    return sum(b - a for a, b in union(values))


def _spans(window):
    # Coverage footprints are evidence, never extra logical observation windows.
    return [(value.start_seconds - value.offset_seconds, value.end_seconds - value.offset_seconds)
            for value in window.source_intervals if value.evidence_id is None]


def _case(store, db, case_id, session_id, actor, expected=None, *, write=False, selected=True):
    account = db.execute("SELECT role,active FROM users WHERE username=?", (actor,)).fetchone()
    if not account or not account["active"] or account["role"] not in (("operator", "admin") if write else ("operator", "admin", "reviewer")):
        raise HTTPException(403, "전처리 자료 접근 권한이 없습니다.")
    row = store.case(db, case_id, expected=expected)
    manifest = store.manifest(row)
    if manifest.schema_version != "intake-4.0":
        raise HTTPException(409, "S1 전환 후 전처리하세요.")
    if manifest.consents.analysis_feedback == "declined":
        raise HTTPException(403, "분석·피드백 동의가 거절된 자료입니다.")
    session = selected_session(manifest, session_id) if selected else next((value for value in manifest.sessions if value.session_id == session_id), None)
    if session is None:
        raise HTTPException(409, "촬영 회차가 더 이상 존재하지 않습니다.")
    return row, session


def _recording(session):
    recording = session.recording_s1
    if recording is None or not recording.confirmed or recording.procedure_edition != "s1_confirmed":
        raise HTTPException(409, "S1 촬영 절차와 실제 시각을 확인·확정한 뒤 전처리하세요.")
    known = {video.video_id for video in session.videos}
    used = {recording.video_id, *(item.video_id for item in recording.video_offsets),
            *(item.video_id for item in recording.events), *(item.video_id for item in recording.coverage)}
    if not used <= known:
        raise HTTPException(409, "촬영 기록이 없는 영상 식별자를 참조합니다.")
    return recording


def _source_snapshot(store, db, case_id, session, actor):
    files, metadata = {}, []

    def receipt(upload_id, expected_hash=None, stack=()):
        if upload_id in stack:
            raise HTTPException(409, "변환 원본 계보가 순환합니다.")
        source = db.execute("SELECT * FROM upload_receipts WHERE upload_id=?", (upload_id,)).fetchone()
        if source is None or (source["state"], source["linked_case_id"], source["linked_session_id"]) != (
                "linked", case_id, session.session_id) or (expected_hash is not None and source["sha256"] != expected_hash):
            raise HTTPException(409, "변환 원본의 대상·회차·연결·해시가 다릅니다.")
        if hashlib.sha256(source["request_json"].encode()).hexdigest() != source["request_hash"]:
            raise HTTPException(409, "영상 수신 요청의 고정 해시가 다릅니다.")
        for parent in json.loads(source["request_json"])["parents"]:
            previous = receipt(parent["upload_id"], parent["sha256"], (*stack, upload_id))
            if parent.get("video_id") is not None and parent["video_id"] != previous["video_id"]:
                raise HTTPException(409, "변환 원본 영상 식별자가 다릅니다.")
        files[source["storage_ref"]] = source["sha256"]
        return source

    for video in session.videos:
        files[video.storage_ref] = video.sha256
        metadata.append(video.model_dump(mode="json"))
        if not isinstance(video, StoredMediaV4):
            continue
        linked = receipt(video.upload_id)
        if (linked["state"], linked["linked_case_id"], linked["linked_session_id"], linked["video_id"],
                linked["storage_ref"], linked["sha256"], linked["size_bytes"]) != (
                "linked", case_id, session.session_id, video.video_id, video.storage_ref, video.sha256, video.size_bytes):
            raise HTTPException(409, "영상의 수신·연결 원장이 입력 스냅샷과 다릅니다.")
        request, binding = json.loads(linked["request_json"]), json.loads(linked["link_json"])
        if (binding["camera_id"], binding["source_original_number"], request["source_kind"], request["conversion"]) != (
                video.camera_id, video.source_original_number, video.source_kind,
                video.conversion.model_dump(mode="json") if video.conversion else None):
            raise HTTPException(409, "카메라 또는 변환 출처가 수신 원장과 다릅니다.")
        if [(p["upload_id"], p["sha256"]) for p in request["parents"]] != [(p.upload_id, p.sha256) for p in video.parents]:
            raise HTTPException(409, "변환 원본 계보가 수신 원장과 다릅니다.")
    return tuple(FileV4(ref=key, hash=value) for key, value in sorted(files.items())), tuple(metadata)


def _verify_files(store, files):
    identities = {}
    try:
        for pointer in files:
            path = managed_path(store, pointer.ref)
            identities[pointer.ref] = _file_identity(path)
            if file_hash(path) != pointer.hash or identities[pointer.ref] != _file_identity(path):
                raise HTTPException(409, "원본 또는 전처리 파일의 해시가 변경되었습니다.")
    except OSError:
        raise HTTPException(409, "원본 또는 전처리 파일을 확인할 수 없습니다.") from None
    return identities


def _file_identity(path):
    value = path.stat()
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def _assert_files(store, identities):
    try:
        if any(_file_identity(managed_path(store, ref)) != identity for ref, identity in identities.items()):
            raise HTTPException(409, "검증 이후 전처리 파일 또는 원본이 변경되었습니다.")
    except OSError:
        raise HTTPException(409, "검증 이후 전처리 파일 또는 원본이 사라졌습니다.") from None


def _assets():
    load_catalog_v4()
    for name in ("protocol", "preprocess", "scoring"):
        load_rules_v4(name)
    return {name: file_hash(RESOURCES / name) for name in (
        "catalogs/behavior-v4.json", "rules/protocol-v4.json", "rules/preprocess-v4.json", "rules/scoring-v4.json")}


def _compatibility(row, session, files, request, assets, encoder):
    return _digest({"input": {"ref": row["manifest_ref"], "hash": row["manifest_hash"], "revision": row["input_revision"]},
                    "session": session.model_dump(mode="json"), "sources": [value.model_dump(mode="json") for value in files],
                    "request": request.model_dump(mode="json", exclude={"request_id", "reuse"}),
                    "assets": assets, "cut": CUT_SETTINGS, "encoder": encoder})


def _history(db, case_id, session_id):
    return [(row["action"], json.loads(row["detail_json"]), row["actor"]) for row in db.execute(
        "SELECT action,detail_json,actor FROM changes WHERE target=? AND action IN "
        "('preprocess_v4.started','preprocess_v4.completed','preprocess_v4.failed') ORDER BY rowid DESC", (case_id,))
        if json.loads(row["detail_json"]).get("session_id") == session_id]


def _load_batch(store, db, case_id, session_id, pointer):
    records = _history(db, case_id, session_id)
    published = next((detail for action, detail, _ in records if action == "preprocess_v4.completed" and
                      detail.get("ref") == pointer.ref and detail.get("hash") == pointer.hash), None)
    if published is None:
        raise HTTPException(409, "채택 완료된 전처리 원본 연결이 없습니다.")
    _verify_files(store, (pointer,))
    try:
        batch = BatchV4.model_validate_json(managed_path(store, pointer.ref).read_bytes())
    except (OSError, ValueError):
        raise HTTPException(409, "전처리 결과 계약을 확인할 수 없습니다.") from None
    if (batch.case_id, batch.session_id, batch.batch_id, batch.claim_token) != (
            case_id, session_id, published["batch_id"], published["claim_token"]):
        raise HTTPException(409, "전처리 시도·점유 식별자가 다릅니다.")
    return batch


def _artifacts(batch):
    return tuple(file for clip in batch.clips for file in (clip.original, clip.ai) if file is not None)


def verified_batch(store, case_id, session_id, pointer: FileV4, actor, *, expected_input=None, expected_revision=None) -> BatchV4:
    """Verify current selection, or an explicit S1 pin when copying an existing sheet.

    Only the source-sheet copy path supplies both historical pin parameters.
    Live role, consent and deletion checks apply in either mode.
    """
    historical = expected_input is not None
    if historical != (expected_revision is not None):
        raise HTTPException(422, "고정 입력 참조와 입력 revision을 함께 지정하세요.")
    with store.connect() as db:
        row, session = _case(store, db, case_id, session_id, actor, selected=not historical)
        batch = _load_batch(store, db, case_id, session_id, pointer)
        expected = (expected_revision, expected_input.ref, expected_input.hash) if historical else (
            row["input_revision"], row["manifest_ref"], row["manifest_hash"])
        if (batch.input_revision, batch.input.ref, batch.input.hash) != expected:
            raise HTTPException(409, "전처리 이후 입력이 변경되었습니다. 다시 전처리하세요.")
        if historical:
            _verify_files(store, (batch.input,))
            try:
                manifest = ManifestV4.model_validate_json(managed_path(store, batch.input.ref).read_bytes())
            except (OSError, ValueError):
                raise HTTPException(409, "고정 S1 입력 계약이 유효하지 않습니다.") from None
            if (manifest.case_id, manifest.input_revision, manifest.selected_session_id) != (case_id, expected_revision, session_id):
                raise HTTPException(409, "고정 입력의 대상·회차·revision이 다릅니다.")
            session = selected_session(manifest, session_id)
        files, _ = _source_snapshot(store, db, case_id, session, actor)
    if batch.source_files != files or batch.asset_hashes != _assets():
        raise HTTPException(409, "전처리 원본 또는 적용 규칙이 변경되었습니다.")
    identities = _verify_files(store, (batch.input, *files, *_artifacts(batch)))
    with store.connect() as db:
        _case(store, db, case_id, session_id, actor, None if historical else batch.input_revision, selected=not historical)
        _assert_files(store, identities)
    return batch


def _frame_times(path):
    value = json.loads(media.command(["ffprobe", "-v", "error", *media.LOCAL_INPUT, "-select_streams", "v:0",
        "-show_frames", "-show_format", "-show_entries", "frame=best_effort_timestamp_time:format=start_time",
        "-of", "json", str(path)], timeout=1800))
    origin = float(value.get("format", {}).get("start_time", 0))
    return tuple(float(frame["best_effort_timestamp_time"]) - origin for frame in value.get("frames", [])
                 if "best_effort_timestamp_time" in frame)


def _clip_file(store, path, start, policy, source_times):
    info, times = media.probe(path), _frame_times(path)
    if not times:
        raise media.NoVideoError("실제 관찰창 안에 영상 프레임이 없습니다.")
    if len(times) != len(source_times):
        raise media.MediaError("원본 프레임과 파생 영상 프레임의 연결을 확인할 수 없습니다.")
    return ClipFileV4(ref=path.relative_to(store.root).as_posix(), hash=file_hash(path), size_bytes=path.stat().st_size,
        duration_seconds=info["duration_sec"], source_time_offset_seconds=start, frame_times_seconds=times,
        source_frame_times_seconds=source_times,
        audio_ranges=_ranges((value["start_sec"], value["end_sec"]) for value in info["audio_ranges"]), fps_policy=policy)


def _ai_clip(source, output):
    # select + passthrough retains actual frame PTS. The fps filter would fabricate
    # duplicate frames in subsecond/low-FPS/gapped media and is deliberately absent.
    media.command(["ffmpeg", "-v", "error", "-xerror", "-nostdin", "-n", *media.LOCAL_INPUT, "-i", str(source),
        "-map", "0:v:0", "-map", "0:a?", "-vf", "select=isnan(prev_selected_t)+gt(floor(t)\\,floor(prev_selected_t))",
        "-fps_mode", "passthrough", "-enc_time_base:v", "demux", "-c:v", "libx264", "-crf", "20",
        "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(output)], timeout=1800)


def _prepare_clips(store, session, recording, windows, directory, guard):
    clips, unavailable = [], {}
    for video in session.videos:
        guard()
        if not isinstance(video, StoredMediaV4):
            unavailable[video.video_id] = "camera_unassigned"
            continue
        offset = recording.offset(video.video_id)
        if video.media_status == "storage_only":
            unavailable[video.video_id] = "conversion_required"
            continue
        if offset is None:
            unavailable[video.video_id] = "offset_unconfirmed"
            continue
        path = managed_path(store, video.storage_ref)
        try:
            duration = media.probe(path)["duration_sec"]
            source_times = _frame_times(path)
        except media.MediaError:
            unavailable[video.video_id] = "failed"
            continue
        requested = [(max(0.0, a + offset), min(duration, b + offset), window.window_id)
                     for window in windows for a, b in _spans(window)]
        for start, end in union((a, b) for a, b, _ in requested):
            clip_id = uid()
            members = tuple(dict.fromkeys(key for a, b, key in requested if a < end and b > start))
            base = {"clip_id": clip_id, "video_id": video.video_id, "camera_id": video.camera_id,
                    "source_start_seconds": start, "source_end_seconds": end, "offset_seconds": offset, "window_ids": members}
            original_path, ai_path = directory / (clip_id + ".mp4"), directory / (clip_id + "-ai.mp4")
            original = None
            try:
                guard()
                media.cut_clip(path, original_path, start, end, None, {"keep_audio": True})
                original = _clip_file(store, original_path, start, "source_frames", tuple(t for t in source_times if start <= t < end))
                guard()
                _ai_clip(original_path, ai_path)
                selected, last_second = [], None
                for derived_time, source_time in zip(original.frame_times_seconds, original.source_frame_times_seconds):
                    second = int(derived_time)
                    if second != last_second:
                        selected.append(source_time)
                        last_second = second
                ai = _clip_file(store, ai_path, start, "one_actual_frame_per_second", tuple(selected))
                clips.append(PhysicalClipV4(**base, status="complete", original=original, ai=ai))
            except media.NoVideoError:
                clips.append(PhysicalClipV4(**base, status="partial" if original else "no_frames", original=original,
                                             reason="ai_no_frames" if original else "no_actual_frames_in_window"))
            except media.MediaError:
                clips.append(PhysicalClipV4(**base, status="partial" if original else "failed", original=original,
                                             reason="ai_encoding_failed" if original else "source_decode_failed"))
    return tuple(clips), unavailable


def _window_results(session, recording, windows, clips, unavailable, request):
    gates = item_capture_gates_v4(recording)
    result = []
    priority = {camera: i for i, camera in enumerate(request.camera_priority)}
    videos = sorted(session.videos, key=lambda video: (priority.get(getattr(video, "camera_id", None), len(priority)), video.video_id))
    for window in windows:
        spans, views = _spans(window), []
        codes = tuple(gate.code for gate in gates if window.window_id in gate.window_ids)
        for video in videos:
            offset = recording.offset(video.video_id)
            found = [clip for clip in clips if clip.video_id == video.video_id and window.window_id in clip.window_ids]
            visual, audio = [], []
            for clip in found:
                if clip.original:
                    visual.extend(intersection(spans, [(clip.source_start_seconds - offset, clip.source_end_seconds - offset)]))
                    audio.extend(intersection(spans, [(value.start_seconds + clip.source_start_seconds - offset,
                        value.end_seconds + clip.source_start_seconds - offset) for value in clip.original.audio_ranges]))
            events = [event for event in recording.events if event.video_id == video.video_id and event.event_id in window.event_ids
                      and event.kind in ("occlusion", "body_not_visible", "audio_loss")]
            losses = [recording.event_times(event) for event in events if event.kind == "audio_loss" and
                      recording.event_times(event) and event.end_seconds is not None]
            audio = subtract(audio, losses)
            observed = [value for value in window.coverage if value.video_id == video.video_id and value.modality == "visual"]
            whole_ranges = [(value.start_seconds - offset, value.end_seconds - offset) for value in observed
                            if value.coverage == "whole" and offset is not None]
            whole = bool(spans) and _seconds(intersection(spans, whole_ranges)) >= _seconds(spans) - 1e-6
            kinds = {event.kind for event in events if event.status == "observed"}
            state = ("body_unobserved" if "body_not_visible" in kinds else "occluded" if "occlusion" in kinds else
                     "whole_observed" if whole else "partial_observed" if any(v.observed_seconds > 0 for v in observed) else "unobserved")
            available = _seconds(visual)
            availability = unavailable.get(video.video_id, "available" if available and available >= _seconds(spans) - 1e-6 else
                "partial" if available else "no_frames" if any(clip.status == "no_frames" for clip in found) else
                "failed" if any(clip.status == "failed" for clip in found) else "missing")
            if any(clip.status != "complete" for clip in found) and availability == "available":
                availability = "partial"
            views.append(ViewWindowV4(video_id=video.video_id, camera_id=getattr(video, "camera_id", None), offset_seconds=offset,
                source_start_seconds=min((clip.source_start_seconds for clip in found), default=None),
                source_end_seconds=max((clip.source_end_seconds for clip in found), default=None),
                clip_ids=tuple(clip.clip_id for clip in found), availability=availability, visual_state=state,
                visual_ranges=_ranges(visual), audio_ranges=_ranges(audio), quality_event_ids=tuple(event.event_id for event in events),
                reasons=tuple(dict.fromkeys([*(clip.reason for clip in found if clip.reason),
                    *([availability] if availability != "available" else []),
                    *(["audio_absent_or_unavailable"] if not audio and spans else [])]))))
        candidates = [view for view in views if view.audio_ranges]
        selected = next((view for view in candidates if view.video_id == request.audio_video_id), None)
        if request.audio_video_id:
            reason = "operator_selected_audio" if selected else "operator_selected_audio_unavailable"
        else:
            # Coverage duration is a file-availability choice, not an observation or scoring threshold.
            selected = max(candidates, key=lambda view: _seconds([(v.start_seconds, v.end_seconds) for v in view.audio_ranges]), default=None)
            reason = "maximum_available_audio_then_camera_priority" if selected else "no_usable_audio"
        selected_audio = [(v.start_seconds, v.end_seconds) for v in selected.audio_ranges] if selected else []
        result.append(WindowV4(window=window, item_codes=codes, views=tuple(views),
            media_available_seconds=_seconds([(v.start_seconds, v.end_seconds) for view in views for v in view.visual_ranges]),
            representative_audio_video_id=selected.video_id if selected else None, audio_selection_reason=reason,
            audio_available_seconds=_seconds(selected_audio), audio_loss_ranges=_ranges(subtract(spans, selected_audio))))
    return tuple(result)


def execute(store, case_id, session_id, actor, request: PreprocessRequestV4) -> BatchV4:
    request = PreprocessRequestV4.model_validate_json(request.model_dump_json())
    request_hash = _digest(request.model_dump(mode="json"))
    with runtime_lock(store, "preprocess"):
        with store.connect(write=True) as db:
            row, session = _case(store, db, case_id, session_id, actor, request.expected_revision, write=True)
            prior = [(action, detail, owner) for action, detail, owner in _history(db, case_id, session_id)
                     if detail.get("request_id") == request.request_id]
            if prior:
                action, detail, owner = prior[0]
                if owner != actor or detail["request_hash"] != request_hash:
                    raise HTTPException(409, "같은 전처리 요청 ID에 다른 요청을 사용할 수 없습니다.")
                if action == "preprocess_v4.completed":
                    pointer = FileV4(ref=detail["ref"], hash=detail["hash"])
                else:
                    raise HTTPException(409, "중단·실패한 전처리는 새 요청 ID로 다시 시작하세요.")
            else:
                pointer = None
            recording = _recording(session)
            files, metadata = _source_snapshot(store, db, case_id, session, actor)
            initial = dict(row)
        if pointer:
            return verified_batch(store, case_id, session_id, pointer, actor)
        _verify_files(store, files)
        assets = _assets()
        encoder = media.command(["ffmpeg", "-version"], timeout=30).splitlines()[0]
        compatibility = _compatibility(initial, session, files, request, assets, encoder)
        batch_id, claim_token = uid(), uid()
        detail = {"batch_id": batch_id, "claim_token": claim_token, "request_id": request.request_id,
                  "request_hash": request_hash, "session_id": session_id, "input_revision": request.expected_revision}
        with store.connect(write=True) as db:
            _case(store, db, case_id, session_id, actor, request.expected_revision, write=True)
            store.audit(db, actor, case_id, "preprocess_v4.started", detail)

        def guard(db=None):
            if db is None:
                with store.connect() as current:
                    return guard(current)
            current, _ = _case(store, db, case_id, session_id, actor, request.expected_revision, write=True)
            if current["manifest_hash"] != initial["manifest_hash"]:
                raise HTTPException(409, "전처리 중 입력 참조가 변경되었습니다.")
            history = _history(db, case_id, session_id)
            if not history or history[0][0] != "preprocess_v4.started" or history[0][1].get("claim_token") != claim_token:
                raise HTTPException(409, "전처리 점유가 만료되었습니다.")

        try:
            if request.audio_video_id and request.audio_video_id not in {video.video_id for video in session.videos}:
                raise HTTPException(422, "대표 오디오 영상이 회차에 없습니다.")
            directory = managed_path(store, f"clips/{case_id}/{session_id}/{batch_id}/{claim_token}")
            directory.mkdir(parents=True, exist_ok=False)
            windows = build_windows_v4(recording)
            if request.reuse:
                old = verified_batch(store, case_id, session_id, request.reuse, actor)
                if old.compatibility_hash != compatibility:
                    raise HTTPException(409, "재사용 원본·카메라·오프셋·FPS·규칙 설정이 다릅니다.")
                clips, results = old.clips, old.windows
            else:
                clips, unavailable = _prepare_clips(store, session, recording, windows, directory, guard)
                results = _window_results(session, recording, windows, clips, unavailable, request)
            batch = BatchV4(batch_id=batch_id, claim_token=claim_token, case_id=case_id, session_id=session_id,
                input_revision=request.expected_revision, input=FileV4(ref=initial["manifest_ref"], hash=initial["manifest_hash"]),
                created_at=now(), status="complete" if clips and all(clip.status == "complete" for clip in clips) and
                all(view.availability == "available" for window in results if _spans(window.window) for view in window.views) else "partial",
                request=request, compatibility_hash=compatibility, asset_hashes=assets, encoder_version=encoder,
                cut_settings=CUT_SETTINGS,
                source_files=files, source_metadata=metadata, recording=recording, clips=clips, windows=results,
                reuse_manifest=request.reuse)
            identities = _verify_files(store, (*files, *_artifacts(batch)))
            if assets != _assets():
                raise HTTPException(409, "전처리 중 규칙 파일이 변경되었습니다.")
            with store.connect(write=True) as db:
                guard(db)
                current_files, current_metadata = _source_snapshot(store, db, case_id, session, actor)
                if current_files != files or current_metadata != metadata:
                    raise HTTPException(409, "전처리 중 영상 계보가 변경되었습니다.")
                _assert_files(store, identities)
                path = directory / "batch.json"
                data = batch.model_dump_json().encode()
                with path.open("xb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                store.audit(db, actor, case_id, "preprocess_v4.completed", {**detail,
                    "ref": path.relative_to(store.root).as_posix(), "hash": hashlib.sha256(data).hexdigest()})
            return batch
        except (HTTPException, media.MediaError, OSError, ValueError) as exc:
            message = exc.detail if isinstance(exc, HTTPException) else "전처리 파일·FFmpeg·저장 공간을 확인하고 새 요청으로 다시 시작하세요."
            with store.connect(write=True) as db:
                history = _history(db, case_id, session_id)
                own_claim = bool(history and history[0][1].get("claim_token") == claim_token)
                store.audit(db, actor, case_id, "preprocess_v4.failed" if own_claim else "preprocess_v4.superseded",
                            {**detail, "message": str(message)})
            raise HTTPException(exc.status_code if isinstance(exc, HTTPException) else 422, message) from exc


def clip_path(store, case_id, session_id, batch_id, clip_id, kind, actor):
    with store.connect() as db:
        _case(store, db, case_id, session_id, actor, selected=False)
        published = next((detail for action, detail, _ in _history(db, case_id, session_id)
                          if action == "preprocess_v4.completed" and detail["batch_id"] == batch_id), None)
        if published is None:
            raise HTTPException(404, "채택된 전처리 시도를 찾을 수 없습니다.")
        pointer = FileV4(ref=published["ref"], hash=published["hash"])
        batch = _load_batch(store, db, case_id, session_id, pointer)
    batch = verified_batch(store, case_id, session_id, pointer, actor,
                           expected_input=batch.input, expected_revision=batch.input_revision)
    clip = next((clip for clip in batch.clips if clip.clip_id == clip_id), None)
    file = getattr(clip, kind, None) if kind in ("original", "ai") else None
    if file is None:
        raise HTTPException(404, "이 전처리 시도의 영상 파일이 없습니다.")
    return managed_path(store, file.ref)


def status(store, case_id, session_id, actor) -> PreprocessStatusV4:
    with store.connect() as db:
        row, session = _case(store, db, case_id, session_id, actor, selected=False)
        records = _history(db, case_id, session_id)
        published = next((detail for action, detail, _ in records if action == "preprocess_v4.completed"), None)
        pointer = FileV4(ref=published["ref"], hash=published["hash"]) if published else None
        batch = _load_batch(store, db, case_id, session_id, pointer) if pointer else None
    try:
        _recording(session)
        ready, message = True, "확정된 S1 촬영 창을 전처리할 수 있습니다."
    except HTTPException as exc:
        ready, message = False, exc.detail
    state = "ready" if ready else "not_ready"
    outdated = bool(batch and (batch.input_revision != row["input_revision"] or batch.asset_hashes != _assets()))
    if batch:
        state, message = batch.status, "전처리 완료" if not outdated else "입력이 변경되었습니다. 다시 전처리하세요."
    if records and records[0][0] == "preprocess_v4.failed":
        state, message = "failed", records[0][1]["message"]
    elif records and records[0][0] == "preprocess_v4.started":
        try:
            with runtime_lock(store, "preprocess"):
                state, message = "interrupted", "중단된 전처리입니다. 새 요청으로 다시 시작하세요."
        except HTTPException:
            with store.connect() as db:
                latest = db.execute("SELECT target,detail_json FROM changes WHERE action='preprocess_v4.started' ORDER BY rowid DESC LIMIT 1").fetchone()
            if latest and latest["target"] == case_id and json.loads(latest["detail_json"]).get("claim_token") == records[0][1].get("claim_token"):
                state, message = "running", "전처리 실행 중"
            else:
                state, message = "interrupted", "중단된 전처리입니다. 새 요청으로 다시 시작하세요."
    if session_id != row["selected_session_id"]:
        ready, message = False, "이전 촬영 회차의 보존 결과입니다. 새 전처리는 현재 회차에서 실행하세요."
    return PreprocessStatusV4(case_id=case_id, session_id=session_id, input_revision=row["input_revision"], ready=ready,
        status=state, message=message, outdated=outdated, result_pointer=pointer, result=batch)
