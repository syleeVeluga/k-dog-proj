"""M1 intake contracts; media properties remain unknown until M2 probing."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


Key = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")]
Text = Annotated[str, Field(min_length=1, max_length=200)]
Role = Literal["operator", "reviewer", "admin", "developer"]
SURVEY_IDS = tuple(f"q{i:02}" for i in range(1, 31))


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Login(Model):
    username: Key
    password: Annotated[str, Field(min_length=1, max_length=256)]


class UserCreate(Login):
    role: Role


class UserEdit(Model):
    role: Role
    active: bool


class UserView(Model):
    username: str
    role: Role
    active: bool


class CaseCreate(Model):
    event_id: Key
    participant_id: Key
    dog_name: Text
    reservation_at: str = ""


class Revision(Model):
    expected_revision: Annotated[int, Field(ge=1)]


class SurveyEdit(Revision):
    session_id: Key
    survey_version: Text
    answers: dict[str, Annotated[int, Field(ge=1, le=5)] | None]

    @model_validator(mode="after")
    def complete(self) -> Self:
        if set(self.answers) != set(SURVEY_IDS):
            raise ValueError("q01~q30을 모두 포함하고 미응답은 null로 입력하세요.")
        return self


class SessionEdit(Revision):
    session_id: Key | None = None
    capture_mode: Literal["simultaneous", "sequential", "unknown"] = "unknown"
    route_note: Annotated[str, Field(max_length=2000)] = ""


class SessionMetadata(Revision):
    capture_mode: Literal["simultaneous", "sequential", "unknown"]
    route_note: Annotated[str, Field(max_length=2000)]


class StoredVideo(Model):
    video_id: Key
    camera_id: Key
    original_name: Text
    storage_ref: str
    sha256: str
    size_bytes: int
    media_status: Literal["pending_probe"] = "pending_probe"


class Session(Model):
    session_id: Key
    capture_mode: Literal["simultaneous", "sequential", "unknown"]
    route_note: str
    survey_version: str
    survey: dict[str, int | None]
    videos: list[StoredVideo]


class Manifest(Model):
    schema_version: Literal["intake-1.0"] = "intake-1.0"
    case_id: Key
    event_id: Key
    participant_id: Key
    input_revision: int
    selected_session_id: Key
    display_run_id: str | None = None
    sessions: list[Session]


class CaseView(Model):
    analysis_status: str = "not_started"
    case_id: str
    event_id: str
    participant_id: str
    dog_name: str
    reservation_at: str
    input_revision: int
    selected_session_id: str
    deletion_requested: bool
    manifest: Manifest


class ImportRow(Model):
    row_number: int
    event_id: Key
    participant_id: Key
    participant: CaseCreate | None = None
    case_id: Key | None = None
    survey: SurveyEdit | None = None


class ImportPreview(Model):
    rows: list[ImportRow]
    errors: list[str]


class ImportCommit(Model):
    rows: Annotated[list[ImportRow], Field(min_length=1, max_length=10000)]


class Message(Model):
    message: str
