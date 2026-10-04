"""S1 capture facts; planned timing, policy and observation remain separate."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .catalog_v4 import ContractV4, ItemCode, PROTOCOL_VERSION, SEGMENTS, SegmentId, Text
from .media_v4 import MediaKey

Seconds = Annotated[float, Field(ge=0)]
CaptureState = Literal["performed", "shortened", "not_performed", "welfare_stopped"]
WALK_PHASES = ("move_1", "stop_1", "move_2", "stop_2", "move_3", "stop_3")
EventKind = Literal[
    "floor_contact", "object_near", "object_stop", "object_passage", "object_contact", "object_removed", "free_movement",
    "guardian_speech", "guardian_gesture", "guardian_departure_preparation", "guardian_fully_outside",
    "staff_signal", "staff_stop", "food", "route_deviation", "occlusion", "body_not_visible", "audio_loss", "external_stimulus",
    "welfare_stop", "welfare_action", "reunion_name", "reunion_contact_start", "reunion_contact_end",
    "reunion_head_turn", "reunion_check", "stranger_gate_wait", "stranger_enter", "stranger_approach",
    "stranger_name", "stranger_contact_start", "stranger_contact_end", "stranger_wait", "stranger_exit",
    "stranger_head_turn", "walk_name", "walk_to_s_start", "walk_to_s_end", "walk_seated",
    "transition_wait_start", "transition_wait_end", "leash_attach", "body_scratch", "body_shake",
    "guardian_approach", "guardian_contact", "exploration_resumed",
]
TRANSITIONS = {"walk_name", "walk_to_s_start", "walk_to_s_end", "walk_seated", "transition_wait_start",
               "transition_wait_end", "leash_attach", "guardian_departure_preparation", "guardian_fully_outside"}


def unique(values, name):
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {name}")


class CaptureSegmentV4(ContractV4):
    segment: SegmentId
    video_id: MediaKey
    state: CaptureState = "performed"
    start_sec: Seconds | None = None
    end_sec: Seconds | None = None
    reason: Text | None = None

    @model_validator(mode="after")
    def boundaries(self) -> Self:
        if self.state != "performed" and self.reason is None:
            raise ValueError("capture exception needs its actual reason")
        if self.state == "not_performed" and (self.start_sec is not None or self.end_sec is not None):
            raise ValueError("skipped capture has no invented times")
        if self.start_sec is not None and self.end_sec is not None and self.end_sec <= self.start_sec:
            raise ValueError("capture duration must be positive")
        return self


class WalkCapturePhaseV4(ContractV4):
    phase: Literal[*WALK_PHASES]
    video_id: MediaKey
    state: CaptureState = "performed"
    start_sec: Seconds | None = None
    end_sec: Seconds | None = None
    reason: Text | None = None
    proximity_exception: Literal["none", "guardian_approach", "recheck", "unknown"] = "unknown"
    proximity_note: Text | None = None

    @model_validator(mode="after")
    def boundaries(self) -> Self:
        CaptureSegmentV4(segment="walk", video_id=self.video_id, state=self.state,
                         start_sec=self.start_sec, end_sec=self.end_sec, reason=self.reason)
        if self.proximity_exception in ("guardian_approach", "recheck") and self.proximity_note is None:
            raise ValueError("proximity exception requires evidence, without replacing distance")
        return self


class ActualEventV4(ContractV4):
    event_id: MediaKey
    kind: EventKind
    video_id: MediaKey
    segment: SegmentId | None = None
    status: Literal["observed", "not_occurred", "unobserved"] = "observed"
    seconds: Seconds | None = None
    end_seconds: Seconds | None = None
    note: Text
    affected_codes: tuple[ItemCode, ...] = ()

    @model_validator(mode="after")
    def actual_event(self) -> Self:
        unique(self.affected_codes, "affected code")
        if self.status == "observed":
            if self.seconds is None or (self.end_seconds is not None and self.end_seconds < self.seconds):
                raise ValueError("observed event requires actual ordered times")
        elif self.seconds is not None or self.end_seconds is not None:
            raise ValueError("missing or absent events have null times, not zero")
        if self.kind in TRANSITIONS and self.segment is not None:
            raise ValueError("preparation and transition events are outside main scored segments")
        expected = "reunion" if self.kind.startswith("reunion_") else "stranger" if self.kind.startswith("stranger_") else None
        if expected and self.segment != expected:
            raise ValueError("event belongs to a different segment")
        return self


class VideoOffsetV4(ContractV4):
    video_id: MediaKey
    offset_seconds: float | None = None  # source seconds = reference seconds + offset
    confirmed: bool = False
    note: Text

    @model_validator(mode="after")
    def basis(self) -> Self:
        if self.confirmed and self.offset_seconds is None:
            raise ValueError("confirmed synchronization requires an explicit offset")
        return self


class WindowCoverageV4(ContractV4):
    evidence_id: MediaKey
    window_id: MediaKey
    video_id: MediaKey
    start_seconds: Seconds
    end_seconds: Seconds
    observed_seconds: Seconds
    coverage: Literal["whole", "partial", "none"]
    modality: Literal["visual", "audio"] = "visual"
    note: Text

    @model_validator(mode="after")
    def amount(self) -> Self:
        duration = self.end_seconds - self.start_seconds
        if duration <= 0 or self.observed_seconds > duration:
            raise ValueError("observation amount must fit its actual positive source range")
        if self.coverage == "whole" and abs(self.observed_seconds - duration) > 1e-6:
            raise ValueError("whole observation must cover the entire source range")
        if self.coverage == "none" and self.observed_seconds != 0:
            raise ValueError("unobserved range cannot claim observation time")
        return self


class TailSelectionV4(ContractV4):
    code: Literal["바54", "바55"]
    event_id: MediaKey
    first_clear_confirmed: bool = False
    same_posture: bool | None = None
    same_movement: bool | None = None
    tail_visible_before: bool | None = None
    tail_visible_after: bool | None = None
    note: Text


class CaptureMemoV4(ContractV4):
    code: Literal["개59"] = "개59"
    memo_id: MediaKey
    text: Text
    item_codes: tuple[ItemCode, ...] = ()
    event_ids: tuple[MediaKey, ...] = ()


class SafeBaseSequenceV4(ContractV4):
    approach_event_id: MediaKey | None = None
    contact_event_id: MediaKey | None = None
    exploration_event_id: MediaKey | None = None
    note: Text


class RecordingV4(ContractV4):
    protocol_version: Literal["protocol-20261002-s1.1"] = PROTOCOL_VERSION
    procedure_edition: Literal["s1_confirmed", "legacy", "unconfirmed"] = "unconfirmed"
    procedure_note: Text
    video_id: MediaKey
    confirmed: bool = False
    segments: Annotated[tuple[CaptureSegmentV4, ...], Field(min_length=8, max_length=8)]
    walk_phases: tuple[WalkCapturePhaseV4, ...] = ()
    events: tuple[ActualEventV4, ...] = ()
    video_offsets: tuple[VideoOffsetV4, ...] = ()
    coverage: tuple[WindowCoverageV4, ...] = ()
    tail_selections: tuple[TailSelectionV4, ...] = ()
    linked_memos: tuple[CaptureMemoV4, ...] = ()
    safe_base_sequence: SafeBaseSequenceV4 | None = None

    @model_validator(mode="after")
    def procedure(self) -> Self:
        expected = tuple(segment for segment, _, _ in SEGMENTS)
        unique(tuple(window.segment for window in self.segments), "segment")
        if set(window.segment for window in self.segments) != set(expected):
            raise ValueError("record all eight segment identities, including explicit omissions")
        standard = self.procedure_edition == "s1_confirmed"
        if standard and tuple(window.segment for window in self.segments) != expected:
            raise ValueError("confirmed S1 procedure uses the specified segment order")
        if any(window.video_id != self.video_id for window in (*self.segments, *self.walk_phases)):
            raise ValueError("segment and phase boundaries use reference-video times")
        for windows in (self.segments, self.walk_phases):
            actual = [window for window in windows if window.start_sec is not None and window.end_sec is not None]
            ordered = actual if standard else sorted(actual, key=lambda window: window.start_sec)
            if any(a.end_sec > b.start_sec for a, b in zip(ordered, ordered[1:])):
                raise ValueError("actual capture intervals overlap or contradict confirmed procedure order")
            if self.confirmed and any(window.state != "not_performed" and
                                      (window.start_sec is None or window.end_sec is None) for window in windows):
                raise ValueError("confirmed capture facts require actual performed boundaries")
        by_id = {window.segment: window for window in self.segments}
        alone, reunion, walk = (by_id[key] for key in ("alone", "reunion", "walk"))
        if standard and alone.state == "not_performed" and reunion.state != "not_performed":
            raise ValueError("omitted separation omits reunion in standard S1")
        if standard and self.confirmed and alone.state in ("shortened", "welfare_stopped"):
            if reunion.state == "not_performed" or reunion.start_sec != alone.end_sec:
                raise ValueError("interrupted separation requires the actual immediate reunion")
        unique(tuple(phase.phase for phase in self.walk_phases), "walk phase")
        if self.walk_phases and tuple(phase.phase for phase in self.walk_phases) != WALK_PHASES:
            raise ValueError("walking has three ordered movement and stop pairs")
        if standard and self.confirmed and walk.state != "not_performed" and not self.walk_phases:
            raise ValueError("confirmed S1 walking needs six phase records")
        actual_phases = [phase for phase in self.walk_phases if phase.state != "not_performed"]
        if walk.state == "not_performed" and actual_phases:
            raise ValueError("omitted walking has no performed phases")
        if standard and self.confirmed and walk.state == "performed" and any(phase.state != "performed" for phase in self.walk_phases):
            raise ValueError("ordinary walking cannot contain skipped or interrupted phases")
        for phase in actual_phases:
            if ((phase.start_sec is not None and walk.start_sec is not None and phase.start_sec < walk.start_sec) or
                    (phase.end_sec is not None and walk.end_sec is not None and phase.end_sec > walk.end_sec)):
                raise ValueError("walking phase lies outside actual walking")
        if standard and self.confirmed and actual_phases:
            if actual_phases[0].start_sec != walk.start_sec or actual_phases[-1].end_sec != walk.end_sec:
                raise ValueError("walking starts at first movement and ends at last performed stop")
            if any(a.end_sec != b.start_sec for a, b in zip(actual_phases, actual_phases[1:])):
                raise ValueError("explain walking exceptions without unrecorded phase gaps")
        unique(tuple(event.event_id for event in self.events), "event")
        unique(tuple(offset.video_id for offset in self.video_offsets), "video offset")
        unique(tuple(evidence.evidence_id for evidence in self.coverage), "coverage evidence")
        unique(tuple(value.code for value in self.tail_selections), "tail selection")
        unique(tuple(value.memo_id for value in self.linked_memos), "linked memo")
        if any(offset.video_id == self.video_id for offset in self.video_offsets):
            raise ValueError("reference video does not need an offset")
        events = {event.event_id: event for event in self.events}
        for selection in self.tail_selections:
            kind = "reunion_head_turn" if selection.code == "바54" else "stranger_head_turn"
            if selection.event_id not in events or events[selection.event_id].kind != kind:
                raise ValueError("tail selection must identify its own actual head-turn event")
        for memo in self.linked_memos:
            if not set(memo.event_ids) <= events.keys():
                raise ValueError("linked memo refers to an absent event")
        for event in self.events:
            times = self.event_times(event)
            if times is None:
                continue  # Unconfirmed offsets retain raw facts but never become scored times.
            start, end = times
            if start < 0:
                raise ValueError("synchronized event predates the reference video")
            if event.segment is not None:
                window = by_id[event.segment]
                if window.state == "not_performed" or (window.start_sec is not None and start < window.start_sec) or (window.end_sec is not None and end > window.end_sec):
                    raise ValueError("event lies outside its actual segment")
            elif standard and event.kind in TRANSITIONS:
                if any(window.start_sec is not None and window.end_sec is not None and start < window.end_sec and end > window.start_sec for window in self.segments):
                    raise ValueError("transition duration overlaps a main scored segment")
        for segment in ("reunion", "stranger"):
            starts = [event for event in self.events if event.kind == f"{segment}_contact_start" and self.event_times(event)]
            ends = [event for event in self.events if event.kind == f"{segment}_contact_end" and self.event_times(event)]
            if len(starts) == len(ends) == 1 and self.event_times(ends[0])[0] < self.event_times(starts[0])[0]:
                raise ValueError("actual contact end precedes its start")
        return self

    def offset(self, video_id: str) -> float | None:
        if video_id == self.video_id:
            return 0.0
        found = next((value for value in self.video_offsets if value.video_id == video_id), None)
        return found.offset_seconds if found and found.confirmed else None

    def event_times(self, event: ActualEventV4) -> tuple[float, float] | None:
        offset = self.offset(event.video_id)
        if event.status != "observed" or offset is None:
            return None
        return event.seconds - offset, (event.end_seconds if event.end_seconds is not None else event.seconds) - offset


class SourceIntervalV4(ContractV4):
    video_id: MediaKey
    start_seconds: Seconds
    end_seconds: Seconds
    offset_seconds: float
    evidence_id: MediaKey | None = None


class RecordingWindowV4(ContractV4):
    window_id: MediaKey
    segment: SegmentId
    reference_video_id: MediaKey
    start_seconds: Seconds | None = None
    end_seconds: Seconds | None = None
    status: Literal["confirmed", "partial", "unobserved", "not_performed", "no_opportunity", "policy_pending", "compatibility_pending"]
    reasons: tuple[Text, ...] = ()
    policy_ids: tuple[Text, ...] = ()
    event_ids: tuple[MediaKey, ...] = ()
    source_intervals: tuple[SourceIntervalV4, ...] = ()
    coverage: tuple[WindowCoverageV4, ...] = ()
    whole_visual_observed: bool = False
    whole_audio_observed: bool = False
    trial_only: bool = False


class ItemCaptureGateV4(ContractV4):
    code: ItemCode
    window_ids: tuple[MediaKey, ...]
    status: Literal["ready", "partial", "unobserved", "not_performed", "no_opportunity", "policy_pending", "compatibility_pending"]
    reasons: tuple[Text, ...] = ()
    policy_ids: tuple[Text, ...] = ()
    whole_interval_observed: bool = False
    proximity_exception: Literal["none", "guardian_approach", "recheck", "unknown"] | None = None


class SafeBaseResultV4(ContractV4):
    status: Literal["confirmed_sequence", "unconfirmed"]
    event_ids: tuple[MediaKey, ...] = ()
    reference_seconds: tuple[Seconds, ...] = ()
    reasons: tuple[Text, ...] = ()
