"""Source-time observation windows. Unknown events never acquire scheduled timestamps."""

import hashlib
import json
import os

from fastapi import HTTPException

from app.domain.catalog_v3 import BehaviorCatalogV3, ProtocolV3, PROTOCOL_VERSION
from app.domain.recording_v3 import RecordingV3
from app.domain.preprocess_v3 import BatchV3
from app.intake import selected_session
from app.media import MediaError, NoVideoError, cut_clip, probe
from app.recording_v3 import validate_recording_media
from app.storage import REPO_ROOT, encode, now, uid

RULE_PATH = REPO_ROOT / "resources/rules/preprocess-v3.json"
RULES = json.loads(RULE_PATH.read_bytes())
PROTOCOL_PATH = REPO_ROOT / "resources/rules/protocol-v3.json"
PROTOCOL = ProtocolV3.model_validate_json(PROTOCOL_PATH.read_bytes())
CATALOG_PATH = REPO_ROOT / "resources/catalogs/behavior-v3.json"
CATALOG = BehaviorCatalogV3.model_validate_json(CATALOG_PATH.read_bytes())
ASSET_HASHES = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in (
    ("rules_hash", RULE_PATH), ("protocol_hash", PROTOCOL_PATH), ("catalog_hash", CATALOG_PATH))}


def verify_assets():
    if any(ASSET_HASHES[name] != hashlib.sha256(path.read_bytes()).hexdigest() for name, path in (
        ("rules_hash", RULE_PATH), ("protocol_hash", PROTOCOL_PATH), ("catalog_hash", CATALOG_PATH))):
        raise HTTPException(409, "처리 규칙/카탈로그가 실행 중 바뀌었습니다. 앱을 다시 시작한 뒤 전처리하세요.")


def file_hash(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def window_plan(session):
    if session.protocol_version != PROTOCOL_VERSION or not session.recording or not session.recording.confirmed:
        raise HTTPException(409, "신판 실제 촬영 기록을 확정한 뒤 전처리하세요.")
    record = RecordingV3.model_validate(session.recording)
    by_id = {window.segment: window for window in record.segments}
    offsets = {offset.video_id: offset.offset_seconds for offset in record.video_offsets if offset.confirmed}
    events = [event for event in record.events if event.status == "observed"]
    clips, windows = [], []
    intervals = {}

    def time(event, end=False):
        seconds = event.end_seconds if end else event.seconds
        return None if seconds is None else seconds - offsets.get(event.video_id, 0)

    def unique(kind, segment):
        matches = [event for event in events if event.kind == kind and event.segment == segment]
        return matches[0] if len(matches) == 1 else None

    def add(window_id, segment, start=None, end=None, *, status="available", reason=None, event_ids=(), point=None):
        parent = by_id.get(segment)
        if parent and parent.state == "not_performed":
            start, end, point, status, reason = None, None, None, "not_performed", parent.reason
        elif start is not None and end is not None and end <= start:
            start, end, status, reason = None, None, "unobserved", reason or "단축으로 해당 관찰창이 없거나 실제 경계가 모순됩니다."
        if point is not None and (start is None or end is None):
            start, end = None, None
        item = {"window_id": window_id, "segment": segment, "status": status, "reason": reason,
                "capture_state": parent.state if parent else "performed", "start_sec": start, "end_sec": end,
                "source_point_sec": point, "event_ids": list(event_ids), "clip_names": [],
                "item_codes": [value.code for value in CATALOG.items if value.usage != "unused" and window_id in value.windows]}
        if start is not None and end is not None and end > start:
            key = (start, end)
            if key not in intervals:
                name = f"window-{len(clips) + 1:03}"
                intervals[key] = name
                clips.append({"name": name, "segment": segment, "start_sec": start, "end_sec": end,
                              "fps": None, "window_ids": [], "video_id": record.video_id})
            item["clip_names"] = [intervals[key]]
            next(clip for clip in clips if clip["name"] == intervals[key])["window_ids"].append(window_id)
        elif point is None and status == "available":
            item.update(status="unobserved", reason=reason or "실제 관찰창 경계가 없거나 길이가0입니다.", start_sec=None, end_sec=None)
        windows.append(item)
        return item

    # The whole actual segment remains available for continuous body movements and full vocalization denominators.
    for window in record.segments:
        add(window.segment, window.segment, window.start_sec, window.end_sec)
    fixed = {"alone_initial": ("alone", 0, 10), "alone_later": ("alone", 10, 60),
             "reunion_first": ("reunion", 0, 15), "reunion_second": ("reunion", 15, 30),
             "separation_shake": ("alone", 0, 5)}
    for name, (segment, start, end) in fixed.items():
        parent = by_id[segment]
        if parent.state == "not_performed":
            add(name, segment)
            continue
        clipped = min(parent.start_sec + end, parent.end_sec)
        beginning = parent.start_sec + start
        add(name, segment, beginning, clipped, status="partial" if clipped < parent.start_sec + end else "available",
            reason="실제 단축 창입니다. 원항목 문턱/최소 관찰량은 보간하지 않습니다." if clipped < parent.start_sec + end else None)
    for number, phase in enumerate(record.walk_phases, 1):
        add(f"walk_phase_{number}", "walk", phase.start_sec, phase.end_sec,
            status="not_performed" if phase.state == "not_performed" else "available", reason=phase.reason)
    for number in range(len(record.walk_phases) + 1, 7):
        add(f"walk_phase_{number}", "walk", status="not_performed", reason="걷기 미실시")

    for name, segment, kind, following in (
        ("stranger_gate", "stranger", "stranger_gate_wait", "stranger_enter"),
        ("stranger_enter", "stranger", "stranger_enter", "stranger_approach"),
        ("stranger_approach", "stranger", "stranger_approach", "stranger_name"),
        ("stranger_exit", "stranger", "stranger_exit", None),
        ("stranger_wait", "stranger", "stranger_wait", None),
    ):
        event, next_event = unique(kind, segment), unique(following, segment) if following else None
        start = time(event) if event else None
        end = time(event, True) if event else None
        if end is None and next_event:
            end = time(next_event)
        if name == "stranger_exit" and event and end is None:
            end = by_id[segment].end_sec
        add(name, segment, start, end, event_ids=tuple(e.event_id for e in (event, next_event) if e),
            reason=None if start is not None and end is not None else "실제 사건 경계 누락/여러 사건으로 창 불명확")
    for name, segment, kind, duration in (("floor_shake", "entry", "floor_contact", 5),
                                          ("stranger_call", "stranger", "stranger_name", 4)):
        event = unique(kind, segment)
        if not event:
            add(name, segment, status="unobserved", reason="실제 부름/바닥 접촉 누락 또는 사건 여러 개")
            continue
        start, parent_end = time(event), by_id[segment].end_sec
        end = min(start + duration, parent_end)
        add(name, segment, start, end, event_ids=(event.event_id,),
            status="partial" if end < start + duration else "available",
            reason="구간 끝에서 잘린 실제 사건 창" if end < start + duration else None)
    for segment in ("reunion", "stranger"):
        start, end = unique(f"{segment}_contact_start", segment), unique(f"{segment}_contact_end", segment)
        observed_contact = any(event.kind in (f"{segment}_contact_start", f"{segment}_contact_end") for event in events)
        no_contact = not observed_contact and any(event.kind == f"{segment}_contact_start" and event.status == "not_occurred" for event in record.events)
        if start and end:
            add(f"{segment}_contact", segment, time(start), time(end), event_ids=(start.event_id, end.event_id))
        else:
            add(f"{segment}_contact", segment, status="no_opportunity" if no_contact and not start else "unobserved",
                reason="명시 미접촉" if no_contact and not start else "실제 접촉 끝/시작 누락·미관찰 또는 여러 접촉: 임의 결합하지 않음")
    add("stranger_contact_plan", "stranger", status="guidance_only", reason="예정20~23초는 실제 접촉 근거가 아닙니다.")
    waiting = next(window for window in windows if window["window_id"] == "stranger_wait")
    observed_contact = any(event.kind in ("stranger_contact_start", "stranger_contact_end") for event in events)
    no_contact = not observed_contact and any(event.kind == "stranger_contact_start" and event.status == "not_occurred" for event in record.events)
    add("stranger_no_contact", "stranger", waiting["start_sec"] if no_contact else None,
        waiting["end_sec"] if no_contact else None, status=waiting["status"] if no_contact else "unobserved",
        reason=waiting["reason"] if no_contact else "명시 미접촉과 실제 대기 범위가 필요합니다.")

    for segment in ("entry", "exit"):
        near, stop = unique("object_near", segment), unique("object_stop", segment)
        add(f"{segment}_object", segment, time(near) if near else None, time(stop, True) if stop else None,
            event_ids=tuple(e.event_id for e in (near, stop) if e), reason="물건1m 진입/실제 정지 끝 경계를 확인하세요." if not near or not stop or stop.end_seconds is None else None)
        parent = by_id[segment]
        if stop and stop.end_seconds is not None and parent.state != "not_performed":
            pieces = []
            for suffix, start, end in (("before", parent.start_sec, time(stop)), ("after", time(stop, True), parent.end_sec)):
                if end > start:
                    pieces.append(add(f"{segment}_leash_{suffix}", segment, start, end, event_ids=(stop.event_id,)))
            value = add(f"{segment}_leash", segment, status="available" if pieces else "no_opportunity", reason="물건 앞 정지 제외")
            value["clip_names"] = [name for piece in pieces for name in piece["clip_names"]]
            value["status"] = "available" if pieces else "no_opportunity"
        else:
            add(f"{segment}_leash", segment, status="unobserved", reason="물건 정지 제외 경계가 미확인입니다. 정지 시간을 줄 당김 분모로 넣지 않습니다.")
    before, alone = by_id["baseline"], by_id["alone"]
    add("before_separation", "baseline", before.end_sec, alone.start_sec,
        reason="분리 전 실제 전환 범위가 없거나 분리 미실시" if alone.start_sec is None else None)
    ignore, walk, stranger = by_id["ignore"], by_id["walk"], by_id["stranger"]
    add("walk_preparation", "walk", ignore.end_sec, walk.start_sec)
    add("walk_seating_wait", "walk", walk.end_sec, stranger.start_sec)
    # A source point is not a fabricated zero-second clip. Use explicit preparation evidence when present.
    prep = next(window for window in windows if window["window_id"] == "walk_preparation")
    value = add("walk_start", "walk", prep["start_sec"], prep["end_sec"], point=walk.start_sec,
                reason="첫걸음 직전 거리: Q08 측정/보정 미확정")
    if not value["clip_names"] and walk.state != "not_performed":
        value.update(status="unobserved", reason="첫걸음 직전 전환 영상창이 없습니다.0초 클립을 만들지 않습니다.")
    for event in events:
        if event.segment is None:
            add(f"transition-{event.event_id}", "transition", time(event), time(event, True),
                event_ids=(event.event_id,), point=time(event) if event.end_seconds is None else None)
    return {"clips": clips, "windows": windows, "events": record.model_dump(mode="json")["events"]}


def plan(session):
    return window_plan(session)["clips"]


def union_duration(ranges):
    end, total = None, 0.0
    for start, stop in sorted(ranges):
        if stop > start:
            total += max(0, stop - max(start, end if end is not None else start))
            end = max(stop, end if end is not None else stop)
    return total


def run(store, case_id, session_id, actor, *, expected_revision=None, request_id=None):
    verify_assets()
    with store.connect() as db:
        row = store.case(db, case_id, expected=expected_revision)
        manifest = store.manifest(row)
    session = selected_session(manifest, session_id)
    planned = window_plan(session)
    if not planned["clips"]:
        raise HTTPException(409, "실시한 실제 관찰창이 없습니다. 미실시 사유는 보존됩니다.")
    record = session.recording
    validate_recording_media(store, session, record)
    video = next(video for video in session.videos if video.video_id == record.video_id)
    source = store.path(video.storage_ref)
    info = probe(source)
    batch = uid()
    folder = f"clips/{case_id}/{session_id}/{batch}"
    store.path(folder).mkdir(parents=True, exist_ok=False)
    outputs = []
    offsets = {value.video_id: value.offset_seconds for value in record.video_offsets if value.confirmed}
    for clip in planned["clips"]:
        with store.connect() as db:
            store.case(db, case_id, expected=row["input_revision"])
        ref = f"{folder}/{clip['name']}.mp4"
        cut_clip(source, store.path(ref), clip["start_sec"], clip["end_sec"], None, RULES)
        try:
            output = probe(store.path(ref))
        except NoVideoError:
            store.path(ref).unlink()
            for window in planned["windows"]:
                if clip["name"] in window["clip_names"]:
                    window["clip_names"].remove(clip["name"])
                    window.update(status="partial" if window["clip_names"] else "unobserved",
                                  reason="실제 창 안에 영상 프레임이 없습니다. 원본 사건/시각은 보존하며 전체 구간 오디오는 별도 유지합니다.")
            continue
        audio_ranges = [(max(clip["start_sec"], value["start_sec"]), min(clip["end_sec"], value["end_sec"])) for value in info["audio_ranges"]]
        if union_duration(audio_ranges) > 0 and output["audio_status"] != "present":
            raise MediaError("클립 오디오가 누락되었습니다.")
        # A positive source window shorter than a video frame can have no decoded visual evidence.
        if output["duration_sec"] <= 0:
            raise MediaError("클립의 실제 디코딩 길이가 없습니다.")
        losses, quality = [], []
        for event in record.events:
            if event.status != "observed" or event.kind not in ("audio_loss", "occlusion") or event.video_id != clip["video_id"]:
                continue
            shift = offsets.get(event.video_id, 0)
            start = max(clip["start_sec"], event.seconds - shift)
            end = min(clip["end_sec"], (event.end_seconds if event.end_seconds is not None else event.seconds) - shift)
            if start < end or clip["start_sec"] <= event.seconds - shift < clip["end_sec"]:
                quality.append({"event_id": event.event_id, "kind": event.kind, "note": event.note,
                                "start_sec": start, "end_sec": end, "affected_codes": list(event.affected_codes)})
                if event.kind == "audio_loss" and start < end:
                    losses.append((start, end))
        available_audio = union_duration(audio_ranges)
        lost_audio = union_duration([(max(start, audio_start), min(end, audio_end)) for start, end in losses for audio_start, audio_end in audio_ranges])
        outputs.append({**clip, "ref": ref, "hash": file_hash(store.path(ref)),
                        "size_bytes": store.path(ref).stat().st_size, "fps": output["fps"],
                        "source_time_offset_sec": clip["start_sec"], "decoded_duration_sec": output["duration_sec"],
                        "audio_status": output["audio_status"], "audio_available_seconds": max(0, available_audio - lost_audio),
                        "audio_listened_seconds": None, "vocal_seconds": None, "quality_events": quality})
    if not outputs:
        raise HTTPException(409, "실제 창 안에 영상 프레임이 없습니다. 원본 촬영 기록을 확인하세요.")
    # A changing source, deletion, or a new revision never becomes a completed batch.
    validate_recording_media(store, session, record)
    verify_assets()
    result = {"schema_version": "3.0", "rules_version": RULES["version"], **ASSET_HASHES,
              "protocol_version": PROTOCOL.version, "rules": RULES, "case_id": case_id, "session_id": session_id,
              "batch_id": batch, "input_revision": row["input_revision"],
              "input": {"manifest_ref": row["manifest_ref"], "manifest_hash": row["manifest_hash"]},
              "video_id": video.video_id, "source_sha256": video.sha256, "source_duration_sec": info["duration_sec"],
              "source_width": info["width"], "source_height": info["height"], "source_fps": info["fps"], "source_audio": info["audio_status"],
              "source_audio_ranges": info["audio_ranges"],
              "sources": [value.model_dump() for value in session.videos], "created_at": now(), "clips": outputs,
              "windows": planned["windows"], "recording": record.model_dump(mode="json"), "provisional": RULES["provisional"],
              "provisional_reason": RULES["provisional_reason"], "listening_policy": RULES["listening_policy"]}
    manifest_ref = f"{folder}/clips.json"
    result = BatchV3.model_validate_json(json.dumps(result)).model_dump(mode="json")
    data = encode(result).encode("utf-8")
    with store.path(manifest_ref).open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    with store.connect(write=True) as db:
        store.case(db, case_id, expected=row["input_revision"])
        store.audit(db, actor, case_id, "preprocess.complete", {"ref": manifest_ref, "hash": hashlib.sha256(data).hexdigest(),
                    "session_id": session_id, "input_revision": row["input_revision"], "clips": len(outputs), "request_id": request_id})
    return result
