"""Versioned intake envelopes; prior raw manifests remain immutable history."""

import json
from typing import Annotated, Literal, Self

from pydantic import Field, field_validator, model_validator

from app.domain.base import Hash, require_unique
from app.domain.catalog import SURVEY_IDS
from app.domain.catalog_v3 import PROTOCOL_VERSION, SURVEY_VERSION
from app.domain.recording_v3 import RecordingV3
from app.domain.preprocess_v3 import BatchV3, WindowV3
from app.input_models import PreprocessPlannedClip, PreprocessResult, PreprocessStatus
from app.input_models import CaseCreate, CaseEdit, CaseView, ImportMapping, ImportRow, Key, Manifest, Model, Revision, Session

ProtocolVersion = Literal["protocol-20260929-v3", "protocol-20260913-v2", "unconfirmed"]
SurveyVersion = Literal["survey-20260929-v3", "catalog-20260913-v2"]
ConsentState = Literal["unknown", "declined", "confirmed"]


class ConsentsV3(Model):
    analysis_feedback: ConsentState = "unknown"
    stranger_contact: ConsentState = "unknown"


class CaseCreateV3(CaseCreate):
    consents: ConsentsV3 = Field(default_factory=ConsentsV3)


class CaseEditV3(CaseEdit):
    # Old clients omitting this field must not clear independently recorded consents.
    consents: ConsentsV3 | None = None


class SurveyEditV3(Revision):
    session_id: Key
    survey_version: SurveyVersion
    answers: dict[str, Annotated[int, Field(ge=0, le=5)] | None]
    not_applicable: list[Key] = Field(default_factory=list)
    blank_reasons: dict[Key, Annotated[str, Field(min_length=1, max_length=200)]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def responses(self) -> Self:
        SessionV3(session_id=self.session_id, note="", survey_version=self.survey_version,
                  protocol_version="unconfirmed", protocol_source="unconfirmed", videos=[],
                  survey=self.answers, survey_not_applicable=self.not_applicable,
                  survey_blank_reasons=self.blank_reasons)
        return self


class ImportMappingV3(ImportMapping):
    survey_version: SurveyVersion | None = None


class RecordingEditV3(Revision):
    recording: RecordingV3
    confirm: bool = False

    @field_validator("recording", mode="before")
    @classmethod
    def json_contract(cls, value):
        # FastAPI decodes JSON arrays into lists before validating the strict domain model.
        return RecordingV3.model_validate_json(json.dumps(value)) if isinstance(value, dict) else value


class RunCreateV3(Revision):
    request_id: Key
    preprocess_ref: Annotated[str, Field(pattern=r"^clips/[^\\]+/clips\.json$")]
    preprocess_hash: Hash
    settings_version: str | None = None
    reuse_run_id: Key | None = None


class RunActionV3(Model):
    expected_updated_at: str
    reason: Annotated[str, Field(min_length=1, max_length=2000, pattern=r"\S")]


class RunStepViewV3(Model):
    stage: str
    key: str
    attempt: int
    status: str
    code: str | None
    billing_uncertain: bool
    call_reserved: bool


class RunViewV3(Model):
    run_id: Key
    case_id: Key
    session_id: Key
    kind: str
    input_revision: int
    status: str
    updated_at: str
    outdated: bool
    failure_code: str | None
    result_available: bool
    steps: list[RunStepViewV3]


class PreprocessPlannedClipV3(Model):
    name: Key
    segment: str
    start_sec: float
    end_sec: float
    fps: None
    window_ids: list[str]
    video_id: Key


class PreprocessPointerV3(Model):
    ref: str
    hash: str


class PreprocessStatusV3(PreprocessStatus):
    result_pointer: PreprocessPointerV3 | None = None
    planned_clips: list[PreprocessPlannedClipV3 | PreprocessPlannedClip]
    dense_fps: int | None
    sparse_fps: int | None
    observation_windows: list[WindowV3]
    provisional: bool
    provisional_reason: str | None
    result: BatchV3 | PreprocessResult | None

    @field_validator("result", mode="before")
    @classmethod
    def batch_contract(cls, value):
        return BatchV3.model_validate_json(json.dumps(value)) if isinstance(value, dict) and value.get("schema_version") == "3.0" else value

    @field_validator("observation_windows", mode="before")
    @classmethod
    def window_contracts(cls, values):
        return [WindowV3.model_validate_json(json.dumps(value)) if isinstance(value, dict) else value for value in values]


class SessionV3(Session):
    survey_version: SurveyVersion
    protocol_version: ProtocolVersion
    protocol_source: Literal["new_session", "confirmed_v2_recording", "unconfirmed"]
    survey_blank_reasons: dict[Key, Annotated[str, Field(min_length=1, max_length=200)]] = Field(default_factory=dict)
    comparison_eligibility: Literal["unconfirmed"] = "unconfirmed"
    recording: RecordingV3 | None = None

    @model_validator(mode="after")
    def references_and_editions(self) -> Self:
        if set(self.survey) != set(SURVEY_IDS):
            raise ValueError("session must retain all 28 question identities")
        require_unique(self.survey_not_applicable, "not-applicable question")
        if not set(self.survey_blank_reasons) <= set(SURVEY_IDS):
            raise ValueError("unknown blank-reason question")
        if any(not reason.strip() or self.survey[question] is not None for question, reason in self.survey_blank_reasons.items()):
            raise ValueError("blank reasons belong to unanswered questions only")
        if self.survey_version == SURVEY_VERSION:
            if self.survey_not_applicable:
                raise ValueError("v3 does not offer NA responses")
            for question, answer in self.survey.items():
                allowed = range(5) if 10 <= int(question[1:]) <= 14 else range(1, 6)
                if answer is not None and (type(answer) is not int or answer not in allowed):
                    raise ValueError("v3 answer outside its question-specific scale")
        else:
            if not set(self.survey_not_applicable) <= {"s07", "s08", "s09"}:
                raise ValueError("v2 NA is limited to 7-9")
            if any(answer is not None and (type(answer) is not int or not 1 <= answer <= 5) for answer in self.survey.values()):
                raise ValueError("v2 answers retain their original 1-5 scale")
        if any(self.survey[question] is not None for question in self.survey_not_applicable):
            raise ValueError("NA is a missing answer, never a value")
        if (self.protocol_version == "unconfirmed") != (self.protocol_source == "unconfirmed"):
            raise ValueError("unconfirmed capture must be identified explicitly")
        if self.protocol_source == "confirmed_v2_recording" and self.protocol_version != "protocol-20260913-v2":
            raise ValueError("confirmed v2 recording source requires the v2 protocol")
        video_ids = [video.video_id for video in self.videos]
        require_unique(video_ids, "session video")
        for timing in (self.segments, self.stimuli):
            if timing and timing.video_id not in video_ids:
                raise ValueError("timing references a missing video")
        if self.recording:
            if self.protocol_version != PROTOCOL_VERSION:
                raise ValueError("new capture record cannot reinterpret a different protocol")
            referenced = {self.recording.video_id, *(event.video_id for event in self.recording.events),
                          *(offset.video_id for offset in self.recording.video_offsets)}
            if not referenced <= set(video_ids):
                raise ValueError("capture record references an unregistered video")
        return self


class PriorInputV3(Model):
    ref: Annotated[str, Field(pattern=r"^inputs/[^/\\]+\.json$")]
    hash: Hash
    revision: Annotated[int, Field(ge=1)]
    schema_version: Literal["intake-1.0", "intake-2.0", "intake-3.0"]


class ManifestV3(Model):
    schema_version: Literal["intake-3.0"] = "intake-3.0"
    case_id: Key
    event_id: Key
    participant_id: Key
    input_revision: Annotated[int, Field(ge=1)]
    selected_session_id: Key
    display_run_id: str | None = None
    sessions: Annotated[list[SessionV3], Field(min_length=1)]
    consents: ConsentsV3 = Field(default_factory=ConsentsV3)
    prior_inputs: list[PriorInputV3] = Field(default_factory=list)
    migration_note: str | None = None

    @model_validator(mode="after")
    def unique_session_references(self) -> Self:
        sessions = [session.session_id for session in self.sessions]
        require_unique(sessions, "session")
        if self.selected_session_id not in sessions:
            raise ValueError("selected session does not exist")
        require_unique([item.ref for item in self.prior_inputs], "prior input")
        if any(item.revision >= self.input_revision for item in self.prior_inputs):
            raise ValueError("prior input revision must precede current revision")
        return self


class CaseViewV3(CaseView):
    consents: ConsentsV3
    manifest: ManifestV3


class ImportRowV3(ImportRow):
    participant: CaseCreateV3 | None = None
    survey: SurveyEditV3 | None = None


class ImportPreviewV3(Model):
    rows: list[ImportRowV3]
    errors: list[str]


class ImportCommitV3(Model):
    rows: Annotated[list[ImportRowV3], Field(min_length=1, max_length=10000)]


def parse_manifest(data: bytes) -> Manifest | ManifestV3:
    decoded = json.loads(data)
    if not isinstance(decoded, dict):
        raise ValueError("manifest must be an object")
    version = decoded.get("schema_version")
    if version == "intake-3.0":
        return ManifestV3.model_validate_json(data)
    if version == "intake-2.0":
        return Manifest.model_validate_json(data)
    raise ValueError("unsupported intake schema")


def upgrade_v2(old: Manifest, *, ref: str, digest: str) -> ManifestV3:
    """Only confirmed v2 recording evidence establishes capture edition, not the survey."""
    from app.domain.contracts import SegmentWindow, SessionSegments

    legacy_origin = bool(old.migration_note and "intake-1.0" in old.migration_note)
    sessions = []
    for session in old.sessions:
        confirmed = False
        if session.segments:
            SessionSegments(session_id=session.session_id, video_id=session.segments.video_id,
                            windows=tuple(SegmentWindow(**window.model_dump(), source="operator_confirmed" if session.segments.confirmed else "operator_draft") for window in session.segments.windows))
            confirmed = not legacy_origin and session.segments.confirmed
        sessions.append({**session.model_dump(mode="json"),
                         "protocol_version": "protocol-20260913-v2" if confirmed else "unconfirmed",
                         "protocol_source": "confirmed_v2_recording" if confirmed else "unconfirmed"})
    return ManifestV3.model_validate_json(json.dumps({
        **old.model_dump(mode="json"), "schema_version": "intake-3.0", "input_revision": old.input_revision + 1,
        "sessions": sessions, "consents": ConsentsV3().model_dump(),
        "prior_inputs": [{"ref": ref, "hash": digest, "revision": old.input_revision, "schema_version": old.schema_version}],
        "migration_note": (old.migration_note + " · " if old.migration_note else "") +
                          "intake-3.0 판본 태그 이관. 설문 원응답·영상·시각 보존, 새 동의 미확인.",
    }, ensure_ascii=False))
