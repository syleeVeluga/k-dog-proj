"""Intake contracts (intake-2.0): 42-item specification sessions — 28-item survey, several video files, free note."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.catalog import SURVEY_IDS


Key = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")]
Text = Annotated[str, Field(min_length=1, max_length=200)]
Note = Annotated[str, Field(max_length=2000)]
Role = Literal["operator", "reviewer", "admin", "developer"]


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


class CaseEdit(Revision):
    participant_id: Key
    dog_name: Text
    reservation_at: str = ""


class SurveyEdit(Revision):
    session_id: Key
    survey_version: Text
    answers: dict[str, Annotated[int, Field(ge=1, le=5)] | None]
    not_applicable: list[Key] = Field(default_factory=list)

    @model_validator(mode="after")
    def complete(self) -> Self:
        if set(self.answers) != set(SURVEY_IDS):
            raise ValueError("s01~s28을 모두 포함하고 미응답은 null로 입력하세요.")
        if len(set(self.not_applicable)) != len(self.not_applicable) or not set(self.not_applicable) <= set(SURVEY_IDS):
            raise ValueError("「해당 없음」 문항 ID를 확인하세요.")
        if any(self.answers[item_id] is not None for item_id in self.not_applicable):
            raise ValueError("「해당 없음」 문항은 응답을 비워 두세요. 해당 없음은 결측이지 점수가 아닙니다.")
        return self


class SessionEdit(Revision):
    session_id: Key | None = None
    note: Note = ""


class SessionMetadata(Revision):
    note: Note


class StoredVideo(Model):
    video_id: Key
    original_name: Text
    storage_ref: str
    sha256: str
    size_bytes: int
    media_status: Literal["pending_probe"] = "pending_probe"


class Session(Model):
    session_id: Key
    note: str
    survey_version: str
    survey: dict[str, int | None]
    survey_not_applicable: list[str] = Field(default_factory=list)
    videos: list[StoredVideo]


class Manifest(Model):
    schema_version: Literal["intake-2.0"] = "intake-2.0"
    case_id: Key
    event_id: Key
    participant_id: Key
    input_revision: int
    selected_session_id: Key
    display_run_id: str | None = None
    sessions: list[Session]
    migration_note: str | None = None


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
    session_label: str = ""
    source_location: str = ""
    changed_questions: list[str] = Field(default_factory=list)


class ImportMapping(Model):
    sheet: Annotated[str, Field(max_length=100)] | None = None
    columns: dict[str, str] = Field(default_factory=dict)


class ImportColumn(Model):
    key: str
    label: str


class ImportColumns(Model):
    columns: list[ImportColumn]


class ImportPreview(Model):
    rows: list[ImportRow]
    errors: list[str]


class ImportCommit(Model):
    rows: Annotated[list[ImportRow], Field(min_length=1, max_length=10000)]


class Message(Model):
    message: str
