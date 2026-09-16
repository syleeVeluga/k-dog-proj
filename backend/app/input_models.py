"""Intake contracts (intake-2.0): 42-item specification sessions — 28-item survey, several video files, free note."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.catalog import SURVEY_IDS, SegmentId
from app.domain.contracts import StimulusMoments


Key = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")]
Text = Annotated[str, Field(min_length=1, max_length=200)]
Note = Annotated[str, Field(max_length=2000)]
Role = Literal["operator", "reviewer", "admin", "developer"]
# 04 설문지 머리 칸. 연락처는 받지 않는다(01 §7).
Sex = Literal["암", "수", "중성화", "미기재"]
Size = Literal["소형", "중형", "대형", "미기재"]
Adoption = Literal["분양", "입양", "기타", "미기재"]


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


class DogProfile(Model):
    breed: Annotated[str, Field(max_length=100)] = ""
    sex: Sex = "미기재"
    age_years: Annotated[int, Field(ge=0, le=30)] | None = None
    size: Size = "미기재"
    years_together: Annotated[str, Field(max_length=50)] = ""
    adoption_route: Adoption = "미기재"


class Participant(Model):
    """Intake fields beyond the identifiers: 순번, 동의 확인, 보호자명, 반려견 정보 (01 §1 ①)."""

    sequence_no: Annotated[int, Field(ge=1, le=9999)] | None = None
    consent_confirmed: bool = False
    guardian_name: Annotated[str, Field(max_length=100)] = ""
    dog: DogProfile = Field(default_factory=DogProfile)


class CaseCreate(Participant):
    event_id: Key
    participant_id: Key
    dog_name: Text
    reservation_at: str = ""


class Revision(Model):
    expected_revision: Annotated[int, Field(ge=1)]


class CaseEdit(Revision, Participant):
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


class SegmentWindowInput(Model):
    segment: SegmentId
    start_sec: Annotated[float, Field(ge=0)]
    end_sec: Annotated[float, Field(ge=0)]


class SegmentsEdit(Revision):
    """8구간 시작·끝 시각(01 §2). 구조 검증은 domain.contracts.SessionSegments가 한다."""

    video_id: Key
    windows: Annotated[list[SegmentWindowInput], Field(min_length=8, max_length=8)]
    confirm: bool = False


class SegmentTimes(Model):
    video_id: Key
    confirmed: bool
    windows: Annotated[list[SegmentWindowInput], Field(min_length=8, max_length=8)]


class StimulusEdit(Revision):
    video_id: Key
    moments: StimulusMoments


class StimulusTimes(Model):
    video_id: Key
    input_revision: Annotated[int, Field(ge=1)]
    source: Literal["operator_confirmed"] = "operator_confirmed"
    moments: StimulusMoments


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
    segments: SegmentTimes | None = None
    stimuli: StimulusTimes | None = None


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
    sequence_no: int | None
    consent_confirmed: bool
    guardian_name: str
    dog: DogProfile
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
    sheets: list[str] = Field(default_factory=list)
    selected_sheet: str | None = None


class ImportPreview(Model):
    rows: list[ImportRow]
    errors: list[str]


class ImportCommit(Model):
    rows: Annotated[list[ImportRow], Field(min_length=1, max_length=10000)]


class Message(Model):
    message: str


class PreprocessPlannedClip(Model):
    name: str
    segment: SegmentId
    start_sec: float
    end_sec: float
    fps: int


class PreprocessClip(PreprocessPlannedClip):
    ref: str
    hash: str
    size_bytes: int


class PreprocessResult(Model):
    stimuli: StimulusTimes | None = None
    schema_version: Literal["1.0"]
    rules_version: str
    case_id: Key
    session_id: Key
    input_revision: int
    video_id: Key
    source_sha256: str
    source_duration_sec: float
    source_width: int
    source_height: int
    source_audio: str
    created_at: str
    clips: list[PreprocessClip]


class PreprocessStatus(Model):
    readiness_message: str
    planned_clips: list[PreprocessPlannedClip]
    status: Literal["ready", "not_ready", "running", "interrupted", "failed", "complete"]
    message: str
    ready: bool
    outdated: bool
    rules_version: str
    dense_fps: int
    sparse_fps: int
    input_revision: int
    video_name: str | None
    result: PreprocessResult | None
