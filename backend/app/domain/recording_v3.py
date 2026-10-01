"""Actual recording boundaries and exceptions; scheduled guidance is never observation."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from .base import Identifier, Text, require_unique
from .catalog_v3 import ContractV3, ItemCode, PROTOCOL_VERSION, SEGMENTS, SegmentId

Seconds = Annotated[float, Field(ge=0)]
CaptureState = Literal["performed", "shortened", "not_performed", "welfare_stopped"]
EventKind = Literal[
    "floor_contact", "object_stop", "object_contact", "object_removed", "guardian_speech", "guardian_gesture",
    "staff_signal", "food", "route_deviation", "occlusion", "welfare_stop", "welfare_action",
    "reunion_name", "reunion_contact_start", "reunion_contact_end", "stranger_gate_wait", "stranger_enter",
    "stranger_approach", "stranger_name", "stranger_contact_start", "stranger_contact_end", "stranger_exit",
    "walk_name", "walk_to_s_start", "walk_to_s_end", "walk_seated", "transition_wait_start", "transition_wait_end", "leash_attach",
]
WALK_PHASES = ("move_1", "stop_1", "move_2", "stop_2", "move_3", "stop_3")
TRANSITIONS = {"walk_name", "walk_to_s_start", "walk_to_s_end", "walk_seated", "transition_wait_start", "transition_wait_end", "leash_attach"}


class CaptureSegmentV3(ContractV3):
    segment: SegmentId
    video_id: Identifier
    state: CaptureState = "performed"
    start_sec: Seconds | None = None
    end_sec: Seconds | None = None
    reason: Text | None = None

    @model_validator(mode="after")
    def state_and_boundaries(self) -> Self:
        if self.state != "performed" and (self.reason is None or not self.reason.strip()):
            raise ValueError("capture exception needs an explicit reason")
        if self.state == "not_performed" and (self.start_sec is not None or self.end_sec is not None):
            raise ValueError("a skipped segment has no fabricated zero-second window")
        if self.start_sec is not None and self.end_sec is not None and self.end_sec <= self.start_sec:
            raise ValueError("actual segment must have positive duration")
        return self


class WalkPhaseV3(ContractV3):
    phase: Literal["move_1", "stop_1", "move_2", "stop_2", "move_3", "stop_3"]
    video_id: Identifier
    state: CaptureState = "performed"
    start_sec: Seconds | None = None
    end_sec: Seconds | None = None
    reason: Text | None = None

    @model_validator(mode="after")
    def boundaries(self) -> Self:
        CaptureSegmentV3(segment="walk", **self.model_dump(exclude={"phase", "schema_version"}))
        return self


class ActualEventV3(ContractV3):
    event_id: Identifier
    kind: EventKind
    video_id: Identifier
    segment: SegmentId | None = None  # None explicitly means a transition outside the scored segment.
    status: Literal["observed", "not_occurred", "unobserved"] = "observed"
    seconds: Seconds | None = None
    end_seconds: Seconds | None = None
    note: Text
    affected_codes: tuple[ItemCode, ...] = ()

    @model_validator(mode="after")
    def actual_event(self) -> Self:
        if not self.note.strip():
            raise ValueError("event requires actual context or missing-observation reason")
        require_unique(self.affected_codes, "affected code")
        if self.status == "observed":
            if self.seconds is None or (self.end_seconds is not None and self.end_seconds < self.seconds):
                raise ValueError("observed event needs an actual time range")
        elif self.seconds is not None or self.end_seconds is not None:
            raise ValueError("non-observation must not acquire an invented event time")
        if self.kind in TRANSITIONS and self.segment is not None:
            raise ValueError("transition is outside the main segment denominator")
        expected = "reunion" if self.kind.startswith("reunion_") else "stranger" if self.kind.startswith("stranger_") else None
        if expected and self.segment != expected:
            raise ValueError("event belongs to a different procedure segment")
        return self


class VideoOffsetV3(ContractV3):
    video_id: Identifier
    offset_seconds: float  # other_video_time = reference_video_time + offset_seconds
    confirmed: bool = False
    note: Text

    @model_validator(mode="after")
    def explicit_basis(self) -> Self:
        if not self.note.strip():
            raise ValueError("manual synchronization needs an explicit basis")
        return self


class RecordingV3(ContractV3):
    protocol_version: Literal["protocol-20260929-v3"] = PROTOCOL_VERSION
    video_id: Identifier
    confirmed: bool = False
    segments: Annotated[tuple[CaptureSegmentV3, ...], Field(min_length=8, max_length=8)]
    walk_phases: tuple[WalkPhaseV3, ...] = ()
    events: tuple[ActualEventV3, ...] = ()
    video_offsets: tuple[VideoOffsetV3, ...] = ()

    @model_validator(mode="after")
    def procedure(self) -> Self:
        if tuple(window.segment for window in self.segments) != tuple(segment for segment, _, _ in SEGMENTS):
            raise ValueError("capture windows must use the current eight-segment order")
        if any(window.video_id != self.video_id for window in self.segments):
            raise ValueError("segment boundaries use the explicitly selected reference video")
        previous_end = None
        for window in self.segments:
            if previous_end is not None and window.start_sec is not None and window.start_sec < previous_end:
                raise ValueError("actual segments overlap or are out of procedure order")
            if window.end_sec is not None:
                previous_end = window.end_sec
            if self.confirmed and window.state != "not_performed" and (window.start_sec is None or window.end_sec is None):
                raise ValueError("confirmation requires actual boundaries for performed segments")
        by_id = {window.segment: window for window in self.segments}
        alone, reunion, walk = by_id["alone"], by_id["reunion"], by_id["walk"]
        if alone.state == "not_performed" and reunion.state != "not_performed":
            raise ValueError("skipped separation also skips reunion")
        if self.confirmed and alone.state in ("shortened", "welfare_stopped"):
            if reunion.state == "not_performed" or reunion.start_sec != alone.end_sec:
                raise ValueError("interrupted separation records the immediate actual reunion")
        require_unique(tuple(phase.phase for phase in self.walk_phases), "walk phase")
        if self.walk_phases and tuple(phase.phase for phase in self.walk_phases) != WALK_PHASES:
            raise ValueError("walk phases must be the three actual movement/stop pairs")
        if self.confirmed and walk.state != "not_performed" and not self.walk_phases:
            raise ValueError("confirmed walking needs all six phase records, including exceptions")
        if self.confirmed and walk.state == "performed" and any(phase.state != "performed" for phase in self.walk_phases):
            raise ValueError("normal walking cannot contain skipped or interrupted phases")
        previous_end = walk.start_sec
        for phase in self.walk_phases:
            if phase.video_id != self.video_id:
                raise ValueError("walking phases use reference video times")
            if walk.state == "not_performed" and phase.state != "not_performed":
                raise ValueError("skipped walking has no performed phases")
            if phase.start_sec is not None and previous_end is not None and phase.start_sec < previous_end:
                raise ValueError("walking phases overlap or precede walking")
            if self.confirmed and phase.start_sec is not None and previous_end is not None and phase.start_sec != previous_end:
                raise ValueError("actual walking phases must cover the walking interval without unexplained gaps")
            if phase.end_sec is not None:
                previous_end = phase.end_sec
                if walk.end_sec is not None and phase.end_sec > walk.end_sec:
                    raise ValueError("walking phase exceeds the main walking boundary")
            if self.confirmed and phase.state != "not_performed" and (phase.start_sec is None or phase.end_sec is None):
                raise ValueError("performed walking phases need actual boundaries")
        if self.confirmed and walk.state != "not_performed" and self.walk_phases:
            actual = [phase for phase in self.walk_phases if phase.state != "not_performed"]
            if not actual:
                raise ValueError("performed walking requires an actual movement or stop phase")
            first, last = actual[0], actual[-1]
            if first.start_sec != walk.start_sec:
                raise ValueError("walking starts at the first actual movement phase")
            if last.end_sec != walk.end_sec:
                raise ValueError("walking ends when the last actual stop ends")
        require_unique(tuple(event.event_id for event in self.events), "event")
        require_unique(tuple(offset.video_id for offset in self.video_offsets), "video offset")
        if any(offset.video_id == self.video_id for offset in self.video_offsets):
            raise ValueError("reference video has no inferred offset")
        offsets = {offset.video_id: offset for offset in self.video_offsets}
        if self.confirmed:
            for segment in ("reunion", "stranger"):
                starts = [event for event in self.events if event.kind == f"{segment}_contact_start" and event.status == "observed"]
                ends = [event for event in self.events if event.kind == f"{segment}_contact_end" and event.status == "observed"]
                if len(starts) == len(ends) == 1:
                    start, end = starts[0], ends[0]
                    start_shift = offsets[start.video_id].offset_seconds if start.video_id in offsets else 0
                    end_shift = offsets[end.video_id].offset_seconds if end.video_id in offsets else 0
                    if end.seconds - end_shift < start.seconds - start_shift:
                        raise ValueError("actual contact end precedes its start")
        for event in self.events:
            if event.status != "observed":
                continue
            offset = offsets.get(event.video_id) if event.video_id != self.video_id else None
            if event.video_id != self.video_id and (offset is None or not offset.confirmed):
                if self.confirmed:
                    raise ValueError("cross-video events need a confirmed manual offset")
                continue  # Raw unsynchronized draft evidence is preserved; not adopted as a scored time.
            shift = offset.offset_seconds if offset else 0.0
            start = event.seconds - shift
            end = (event.end_seconds if event.end_seconds is not None else event.seconds) - shift
            if event.segment:
                window = by_id[event.segment]
                if window.state == "not_performed" or (window.start_sec is not None and start < window.start_sec) or (window.end_sec is not None and end > window.end_sec):
                    raise ValueError("actual event lies outside its performed segment")
            elif self.confirmed:
                if any(window.start_sec is not None and window.end_sec is not None and start < window.end_sec and end > window.start_sec for window in self.segments):
                    raise ValueError("transition duration overlaps a main scored segment")
                if event.kind in ("walk_name", "walk_to_s_start", "walk_to_s_end") and walk.start_sec is not None and end > walk.start_sec:
                    raise ValueError("walking preparation precedes the first S step")
                if event.kind in ("walk_name", "walk_to_s_start", "walk_to_s_end") and by_id["ignore"].end_sec is not None and start < by_id["ignore"].end_sec:
                    raise ValueError("walking preparation follows the ignore segment")
                if event.kind in ("walk_seated", "transition_wait_start", "transition_wait_end") and walk.end_sec is not None and start < walk.end_sec:
                    raise ValueError("seating and transition wait follow walking")
                if event.kind in ("walk_seated", "transition_wait_start", "transition_wait_end") and by_id["stranger"].start_sec is not None and end > by_id["stranger"].start_sec:
                    raise ValueError("seating and transition wait precede the stranger segment")
        return self
