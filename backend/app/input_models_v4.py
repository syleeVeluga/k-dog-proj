"""S1 intake: preserve input facts, start all assessment results afresh."""

from __future__ import annotations

import json
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from app.domain.catalog import SURVEY_IDS
from app.domain.catalog_v3 import SURVEY_VERSION
from app.domain.catalog_v4 import CATALOG_VERSION, PROTOCOL_VERSION
from app.domain.media_v4 import StoredMediaV4
from app.domain.recording_v4 import RecordingV4
from app.domain.recording_v3 import RecordingV3
from app.input_models import CaseView, Key, Manifest, Model, Session, StoredVideo
from app.input_models_v3 import ConsentsV3, ManifestV3, SessionV3


def parse_manifest(data: bytes) -> Manifest | ManifestV3 | ManifestV4:
    from app.input_models_v3 import parse_manifest as parse_previous
    decoded = json.loads(data)
    if isinstance(decoded, dict) and decoded.get("schema_version") == "intake-4.0":
        return ManifestV4.model_validate_json(data)
    return parse_previous(data)


class SessionV4(Session):
    videos: list[StoredMediaV4 | StoredVideo] = Field(default_factory=list)
    scoring_catalog_version: Literal["catalog-20261002-s1.1"] = CATALOG_VERSION
    protocol_version: Literal["protocol-20261002-s1.1", "protocol-20260929-v3", "protocol-20260913-v2", "unconfirmed"] = PROTOCOL_VERSION
    protocol_source: Literal["new_session", "confirmed_v2_recording", "unconfirmed"] = "new_session"
    survey_blank_reasons: dict[Key, Annotated[str, Field(min_length=1, max_length=200)]] = Field(default_factory=dict)
    comparison_eligibility: Literal["unconfirmed"] = "unconfirmed"
    # Retained capture facts are reviewed against S1 windows in S04, never rescored here.
    recording: RecordingV3 | None = None
    recording_s1: RecordingV4 | None = None
    recording_review_required: bool = False

    @model_validator(mode="after")
    def input_facts(self) -> Self:
        values = self.model_dump(mode="json")
        for name in ("scoring_catalog_version", "recording_review_required", "recording_s1"):
            values.pop(name)
        # Reuse input-fact validation without dropping S1 provenance in the manifest.
        values["videos"] = [
            {**{key: value for key, value in video.items() if key in StoredVideo.model_fields},
             "media_status": "pending_probe"}
            for video in values["videos"]
        ]
        if self.protocol_version == PROTOCOL_VERSION:
            if self.recording is not None:
                raise ValueError("a previous capture record cannot be relabelled S1")
            values["protocol_version"] = "protocol-20260929-v3"
        SessionV3.model_validate_json(json.dumps(values, ensure_ascii=False))
        return self


class PriorInputV4(Model):
    ref: Annotated[str, Field(pattern=r"^inputs/[^/\\]+\.json$")]
    hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    revision: Annotated[int, Field(ge=1)]
    schema_version: Literal["intake-4.0"] = "intake-4.0"


class RawInputSourceV4(Model):
    """The original 30-question input is evidence, never an S1 score/revision parent."""
    ref: Annotated[str, Field(pattern=r"^inputs/[^/\\]+\.json$")]
    hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    schema_version: Literal["intake-1.0"] = "intake-1.0"
    purpose: Literal["source_only"] = "source_only"


class ManifestV4(Model):
    schema_version: Literal["intake-4.0"] = "intake-4.0"
    case_id: Key
    event_id: Key
    participant_id: Key
    input_revision: Annotated[int, Field(ge=1)]
    selected_session_id: Key
    display_run_id: str | None = None
    sessions: Annotated[list[SessionV4], Field(min_length=1)]
    consents: ConsentsV3 = Field(default_factory=ConsentsV3)
    prior_inputs: list[PriorInputV4] = Field(default_factory=list)
    raw_input_sources: list[RawInputSourceV4] = Field(default_factory=list)
    migration_note: str | None = None

    @model_validator(mode="after")
    def references(self) -> Self:
        ids = [session.session_id for session in self.sessions]
        if len(set(ids)) != len(ids) or self.selected_session_id not in ids:
            raise ValueError("session references must be unique and selected session must exist")
        refs = [entry.ref for entry in self.prior_inputs]
        if len(set(refs)) != len(refs) or any(entry.revision >= self.input_revision for entry in self.prior_inputs):
            raise ValueError("only earlier unique S1 input revisions can be referenced")
        source_refs = [source.ref for source in self.raw_input_sources]
        if len(set(source_refs)) != len(source_refs) or set(source_refs).intersection(refs):
            raise ValueError("raw input sources must be distinct from S1 revision history")
        return self


class CaseViewV4(CaseView):
    manifest: ManifestV4
    consents: ConsentsV3
    scoring_status: Literal["reanalysis_required"] = "reanalysis_required"


def new_session_v4(session_id: str, note: str = "", survey_version: str = SURVEY_VERSION) -> SessionV4:
    return SessionV4(session_id=session_id, note=note, survey_version=survey_version,
                     survey=dict.fromkeys(SURVEY_IDS), videos=[])


def upgrade_to_s1(old: Manifest | ManifestV3) -> ManifestV4:
    """One-time reset copies current raw inputs, never previous result references."""
    if isinstance(old, ManifestV4):
        raise ValueError("S1 input cannot be reset as an old generation")
    sessions = []
    for session in old.sessions:
        values = session.model_dump(mode="json")
        if not isinstance(session, SessionV3):
            confirmed = bool(session.segments and session.segments.confirmed and
                             not (old.migration_note and "intake-1.0" in old.migration_note))
            values.update(protocol_version="protocol-20260913-v2" if confirmed else "unconfirmed",
                          protocol_source="confirmed_v2_recording" if confirmed else "unconfirmed")
        values["recording_review_required"] = bool(session.segments or session.stimuli or getattr(session, "recording", None))
        sessions.append(values)
    return ManifestV4.model_validate_json(json.dumps({
        "case_id": old.case_id, "event_id": old.event_id, "participant_id": old.participant_id,
        "input_revision": old.input_revision + 1, "selected_session_id": old.selected_session_id,
        "display_run_id": None, "sessions": sessions,
        "consents": getattr(old, "consents", ConsentsV3()).model_dump(mode="json"),
        "migration_note": "S1 전환: 원입력 보존, 기존 점수·분석 결과 초기화. 촬영 시각은 S1 관찰창으로 재확인 필요.",
    }, ensure_ascii=False))
