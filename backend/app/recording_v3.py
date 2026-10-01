"""Validate source bytes and actual recording time references without rewriting media."""

import hashlib

from fastapi import HTTPException

from app.domain.recording_v3 import RecordingV3
from app.media import MediaError, probe


def validate_recording_media(store, session, recording: RecordingV3):
    videos = {video.video_id: video for video in session.videos}
    referenced = {recording.video_id, *(event.video_id for event in recording.events),
                  *(offset.video_id for offset in recording.video_offsets)}
    if not referenced <= videos.keys():
        raise HTTPException(422, "촬영 기록은 이 회차에 등록된 영상만 참조할 수 있습니다.")
    durations = {}
    try:
        for video_id in referenced:
            video = videos[video_id]
            path = store.path(video.storage_ref)
            with path.open("rb") as handle:
                if path.stat().st_size != video.size_bytes or hashlib.file_digest(handle, "sha256").hexdigest() != video.sha256:
                    raise HTTPException(409, "원본 영상 해시·크기가 등록 당시와 다릅니다.")
            durations[video_id] = probe(path)["duration_sec"]
            with path.open("rb") as handle:
                if hashlib.file_digest(handle, "sha256").hexdigest() != video.sha256:
                    raise HTTPException(409, "검사 중 원본 영상이 변경되었습니다.")
    except (MediaError, OSError, ValueError) as exc:
        raise HTTPException(422, "원본 영상 형식·길이·접근 상태를 확인하세요.") from exc
    for window in (*recording.segments, *recording.walk_phases):
        if any(value is not None and value > durations[window.video_id] for value in (window.start_sec, window.end_sec)):
            raise HTTPException(422, "구간·국면 시각이 영상 범위를 벗어납니다.")
    for event in recording.events:
        if any(value is not None and value > durations[event.video_id] for value in (event.seconds, event.end_seconds)):
            raise HTTPException(422, "실제 사건 시각이 해당 영상 범위를 벗어납니다.")
    offsets = {offset.video_id: offset for offset in recording.video_offsets if offset.confirmed}
    for event in recording.events:
        offset = offsets.get(event.video_id)
        if event.status == "observed" and offset:
            times = (event.seconds, event.end_seconds)
            if any(value is not None and not 0 <= value - offset.offset_seconds <= durations[recording.video_id] for value in times):
                raise HTTPException(422, "확인된 오프셋의 사건 시각이 기준 영상 범위를 벗어납니다.")
    return durations
