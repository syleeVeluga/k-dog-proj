"""Resolve S1 observation windows from actual capture facts, without assigning scores."""

import hashlib

from fastapi import HTTPException

from .domain.catalog_v4 import VOCAL_CODES, load_catalog_v4, load_rules_v4
from .domain.recording_v4 import (ItemCaptureGateV4, RecordingV4, RecordingWindowV4,
                                  SafeBaseResultV4, SourceIntervalV4)
from .media import MediaError, probe


def _events(recording, kind, segment=None):
    return [event for event in recording.events if event.kind == kind and
            (segment is None or event.segment == segment)]


def _span(recording, event):
    times = recording.event_times(event)
    return times if times and times[1] > times[0] else None


def observation_clear_v4(recording, video_id, start_seconds, end_seconds, *, modality, code=None):
    """Whether a source-time evidence range contradicts an explicit loss for this item.

    This never establishes observation by itself; the caller must still supply
    complete observation evidence. Missing offsets cannot establish coverage.
    """
    if recording.offset(video_id) is None:
        return False
    kinds = ("audio_loss",) if modality == "audio" else ("occlusion", "body_not_visible")
    for event in recording.events:
        if event.video_id != video_id or event.kind not in kinds or event.status != "observed":
            continue
        if code is not None and event.affected_codes and code not in event.affected_codes:
            continue
        end = event.end_seconds if event.end_seconds is not None else event.seconds
        if event.seconds < end_seconds and (end > start_seconds or end == event.seconds and end >= start_seconds):
            return False
    return True


def _whole_observed(recording, spans, evidence, modality, code=None):
    return bool(spans) and all(any(value.modality == modality and value.coverage == "whole" and
        (offset := recording.offset(value.video_id)) is not None and
        value.start_seconds - offset <= start and value.end_seconds - offset >= end and
        observation_clear_v4(recording, value.video_id, start + offset, end + offset, modality=modality, code=code)
        for value in evidence) for start, end in spans)


def build_windows_v4(recording: RecordingV4) -> tuple[RecordingWindowV4, ...]:
    """Confirmed means time geometry is usable; observation coverage stays explicit."""
    recording = RecordingV4.model_validate_json(recording.model_dump_json())
    protocol = load_rules_v4("protocol")
    by_id = {window.segment: window for window in recording.segments}
    result = []
    phase_specs = [{"window_id": f"walk_phase_{number}", "segment": "walk", "anchor": "actual_walk_phase", "status": "confirmed", "phase_index": number - 1}
                   for number in range(1, 7)]
    known_windows = {spec["window_id"] for spec in [*protocol["windows"], *phase_specs]}
    if any(value.window_id not in known_windows for value in recording.coverage):
        raise ValueError("coverage must reference an active S1 observation window")
    for spec in [*protocol["windows"], *phase_specs]:
        key, segment = spec["window_id"], spec["segment"]
        capture = by_id[segment]
        spans, event_ids, reasons = [], [], []
        status = "confirmed"
        trial = spec["status"] == "optional_trial"
        if capture.state == "not_performed":
            status, reasons = "not_performed", [capture.reason]
        elif capture.start_sec is None or capture.end_sec is None:
            status, reasons = "unobserved", ["actual_segment_boundaries_missing"]
        elif spec["anchor"] == "actual_segment" and not key.startswith("stranger_"):
            start = capture.start_sec + (spec["start_offset"] or 0)
            planned_end = capture.start_sec + spec["end_offset"] if spec["end_offset"] is not None else capture.end_sec
            end = min(planned_end, capture.end_sec)
            if end > start:
                spans = [(start, end)]
                if end < planned_end:
                    status, reasons = "partial", ["actual_capture_ends_before_required_window"]
            else:
                status, reasons = "unobserved", ["required_window_not_reached"]
        elif key == "stranger_whole":
            spans = [(capture.start_sec, capture.end_sec)]
        elif spec["anchor"] == "actual_walk_phase":
            phase = recording.walk_phases[spec["phase_index"]] if recording.walk_phases else None
            if phase and phase.state == "not_performed":
                status, reasons = "not_performed", [phase.reason]
            elif phase and phase.start_sec is not None and phase.end_sec is not None:
                spans = [(phase.start_sec, phase.end_sec)]
        elif key in ("entry_free", "exit_free", "entry_object", "exit_object", "stranger_exit"):
            kind = "free_movement" if key.endswith("_free") else "object_passage" if key.endswith("_object") else "stranger_exit"
            events = _events(recording, kind, segment)
            spans = [times for event in events if (times := _span(recording, event))]
            event_ids = [event.event_id for event in events]
        elif key == "separation_departure":
            starts, ends = _events(recording, "guardian_departure_preparation"), _events(recording, "guardian_fully_outside")
            event_ids = [event.event_id for event in (*starts, *ends)]
            if len(starts) == len(ends) == 1 and recording.event_times(starts[0]) and recording.event_times(ends[0]):
                start, end = recording.event_times(starts[0])[0], recording.event_times(ends[0])[0]
                if start < end and end == capture.start_sec:
                    spans = [(start, end)]
                else:
                    reasons.append("departure_events_do_not_match_actual_exit")
        elif key.endswith("_contact"):
            starts, ends = _events(recording, f"{segment}_contact_start"), _events(recording, f"{segment}_contact_end")
            event_ids = [event.event_id for event in (*starts, *ends)]
            observed_starts = sorted([recording.event_times(event)[0] for event in starts if recording.event_times(event)])
            observed_ends = sorted([recording.event_times(event)[0] for event in ends if recording.event_times(event)])
            if starts and all(event.status == "not_occurred" for event in starts) and not observed_ends:
                status, reasons = "no_opportunity", ["actual_contact_not_occurred"]
            elif len(observed_starts) == len(observed_ends) and observed_starts:
                pairs = list(zip(observed_starts, observed_ends))
                if all(start < end for start, end in pairs) and all(a[1] <= b[0] for a, b in zip(pairs, pairs[1:])):
                    spans = pairs
                else:
                    reasons.append("contact_intervals_need_review")
            elif observed_starts:
                status, reasons = "partial", ["actual_contact_end_missing"]
        elif key in ("stranger_gate", "stranger_approach", "stranger_call"):
            kind = {"stranger_gate": "stranger_gate_wait", "stranger_approach": "stranger_approach", "stranger_call": "stranger_name"}[key]
            events = _events(recording, kind, segment)
            event_ids = [event.event_id for event in events]
            if len(events) == 1 and recording.event_times(events[0]):
                start, end = recording.event_times(events[0])
                if key == "stranger_call":
                    end = min(start + 4, capture.end_sec)
                    if end < start + 4:
                        status, reasons = "partial", ["actual_capture_ends_before_call_response_window"]
                if end > start:
                    spans = [(start, end)]
        elif key.endswith("_tail_event"):
            code = "바54" if segment == "reunion" else "바55"
            selected = next((value for value in recording.tail_selections if value.code == code), None)
            if selected:
                event = next(value for value in recording.events if value.event_id == selected.event_id)
                event_ids = [event.event_id]
                times = recording.event_times(event)
                earlier = [recording.event_times(value)[0] for value in _events(recording, event.kind)
                           if recording.event_times(value)]
                conditions = (selected.first_clear_confirmed, selected.same_posture, selected.same_movement,
                              selected.tail_visible_before, selected.tail_visible_after)
                if times and all(value is True for value in conditions) and times[0] == min(earlier):
                    start, end = times[0] - 2, times[0] + 3
                    if start >= capture.start_sec and end <= capture.end_sec:
                        spans = [(start, end)]
                    else:
                        reasons.append("tail_before_2_or_after_3_seconds_unavailable")
                else:
                    reasons.append("first_clear_turn_or_comparable_tail_view_unconfirmed")
            else:
                reasons.append("optional_tail_observation_not_selected")
        if not spans and status == "confirmed":
            status = "unobserved"
            reasons.append("actual_event_window_missing_or_unsynchronized")
        if spans:
            spans.sort()
            if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
                raise ValueError(f"overlapping actual intervals in {key}")
        # Keep source event IDs on whole/phase windows as well as special event windows.
        for event in recording.events:
            if event.segment != segment:
                continue
            times = recording.event_times(event)
            if times is None or any(times[0] <= end and times[1] >= start for start, end in spans):
                event_ids.append(event.event_id)
        event_ids = list(dict.fromkeys(event_ids))
        evidence = tuple(value for value in recording.coverage if value.window_id == key)
        intervals = [SourceIntervalV4(video_id=recording.video_id, start_seconds=start, end_seconds=end,
                                      offset_seconds=0.0) for start, end in spans]
        whole = {modality: _whole_observed(recording, spans, evidence, modality) for modality in ("visual", "audio")}
        for value in evidence:
            offset = recording.offset(value.video_id)
            if offset is not None:
                intervals.append(SourceIntervalV4(video_id=value.video_id, start_seconds=value.start_seconds,
                                                  end_seconds=value.end_seconds, offset_seconds=offset,
                                                  evidence_id=value.evidence_id))
        if not recording.confirmed and status == "confirmed":
            status, reasons = "unobserved", [*reasons, "recording_facts_not_confirmed"]
        if recording.procedure_edition != "s1_confirmed" and status in ("confirmed", "partial"):
            status, reasons = "compatibility_pending", [*reasons, "actual_procedure_requires_s1_compatibility_review"]
        result.append(RecordingWindowV4(
            window_id=key, segment=segment, reference_video_id=recording.video_id,
            start_seconds=spans[0][0] if spans else None, end_seconds=spans[-1][1] if spans else None,
            status=status, reasons=tuple(reasons), event_ids=tuple(event_ids), source_intervals=tuple(intervals),
            coverage=evidence, whole_visual_observed=whole["visual"], whole_audio_observed=whole["audio"], trial_only=trial))
    return tuple(result)


def item_capture_gates_v4(recording: RecordingV4) -> tuple[ItemCaptureGateV4, ...]:
    windows = {value.window_id: value for value in build_windows_v4(recording)}
    result = []
    for item in load_catalog_v4().items:
        phase_index = int(item.code[1:]) - 38 if item.code in tuple(f"개{n}" for n in range(38, 44)) else None
        window_ids = (f"walk_phase_{phase_index + 1}",) if phase_index is not None else item.windows
        relevant = [windows[key] for key in window_ids]
        whole = all(_whole_observed(recording,
            [(part.start_seconds - part.offset_seconds, part.end_seconds - part.offset_seconds)
             for part in value.source_intervals if part.evidence_id is None], value.coverage,
            "audio" if item.code in VOCAL_CODES else "visual", item.code) for value in relevant)
        reasons = tuple(dict.fromkeys(reason for value in relevant for reason in value.reasons))
        if item.policy_pending:
            status, reasons = "policy_pending", (*reasons, "source_policy_unresolved_preserve_raw_events")
        else:
            status = next((state for state in ("compatibility_pending", "not_performed", "no_opportunity", "unobserved", "partial")
                           if any(value.status == state for value in relevant)), "ready")
            if status == "ready" and item.whole_interval_required and not whole:
                status, reasons = "unobserved", (*reasons, "whole_interval_observation_required_no_zero_imputation")
        exception = recording.walk_phases[phase_index].proximity_exception if phase_index is not None and recording.walk_phases else None
        if exception == "recheck" and status == "ready":
            status, reasons = "unobserved", (*reasons, "proximity_exception_requires_review")
        result.append(ItemCaptureGateV4(code=item.code, window_ids=window_ids, status=status, reasons=reasons,
                                        policy_ids=item.policy_pending, whole_interval_observed=whole,
                                        proximity_exception=exception))
    return tuple(result)


def safe_base_sequence_v4(recording: RecordingV4) -> SafeBaseResultV4:
    selection = recording.safe_base_sequence
    if selection is None:
        return SafeBaseResultV4(status="unconfirmed", reasons=("actual_approach_contact_exploration_sequence_missing",))
    ids = (selection.approach_event_id, selection.contact_event_id, selection.exploration_event_id)
    events = {value.event_id: value for value in recording.events}
    if any(value is None or value not in events for value in ids):
        return SafeBaseResultV4(status="unconfirmed", event_ids=tuple(value for value in ids if value in events), reasons=("sequence_event_missing",))
    kinds = ("guardian_approach", "guardian_contact", "exploration_resumed")
    if any(events[key].kind != kind or recording.event_times(events[key]) is None for key, kind in zip(ids, kinds)):
        return SafeBaseResultV4(status="unconfirmed", event_ids=ids, reasons=("sequence_event_kind_or_synchronization_unconfirmed",))
    times = tuple(recording.event_times(events[key])[0] for key in ids)
    contact_end = recording.event_times(events[ids[1]])[1]
    if not recording.confirmed or not times[0] < times[1] <= contact_end < times[2]:
        return SafeBaseResultV4(status="unconfirmed", event_ids=ids, reference_seconds=times, reasons=("actual_sequence_order_not_established",))
    return SafeBaseResultV4(status="confirmed_sequence", event_ids=ids, reference_seconds=times)


def validate_recording_media_v4(store, session, recording: RecordingV4):
    """Recheck immutable source bytes and time bounds; INSV cannot be timed input."""
    recording = RecordingV4.model_validate_json(recording.model_dump_json())
    videos = {video.video_id: video for video in session.videos}
    referenced = {recording.video_id, *(value.video_id for value in recording.events),
                  *(value.video_id for value in recording.video_offsets), *(value.video_id for value in recording.coverage)}
    if not referenced <= videos.keys():
        raise HTTPException(422, "촬영 근거는 이 회차에 연결된 영상만 참조할 수 있습니다.")
    durations = {}
    try:
        for key in referenced:
            video = videos[key]
            if video.media_status == "storage_only":
                raise HTTPException(422, "INSV 보관 원본은 변환·확인 전 관찰 시각으로 사용할 수 없습니다.")
            path = store.path(video.storage_ref)
            with path.open("rb") as handle:
                if path.stat().st_size != video.size_bytes or hashlib.file_digest(handle, "sha256").hexdigest() != video.sha256:
                    raise HTTPException(409, "영상 원본 크기·해시가 변경되었습니다.")
            durations[key] = probe(path)["duration_sec"]
            with path.open("rb") as handle:
                if hashlib.file_digest(handle, "sha256").hexdigest() != video.sha256:
                    raise HTTPException(409, "검사 중 영상 원본이 변경되었습니다.")
    except (MediaError, OSError, ValueError) as exc:
        raise HTTPException(422, "영상 형식·길이·접근 상태를 확인하세요.") from exc
    ranges = [(value.video_id, value.start_sec, value.end_sec) for value in (*recording.segments, *recording.walk_phases)]
    ranges += [(value.video_id, value.seconds, value.end_seconds) for value in recording.events]
    ranges += [(value.video_id, value.start_seconds, value.end_seconds) for value in recording.coverage]
    for video_id, start, end in ranges:
        if any(value is not None and value > durations[video_id] for value in (start, end)):
            raise HTTPException(422, "관찰 구간·사건이 해당 원본 영상의 길이를 벗어납니다.")
        offset = recording.offset(video_id)
        if offset is not None and any(value is not None and not 0 <= value - offset <= durations[recording.video_id] for value in (start, end)):
            raise HTTPException(422, "확인된 동기화 시각이 기준 영상의 길이를 벗어납니다.")
    return durations
