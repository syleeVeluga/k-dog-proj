"""intake-1.0 session shape (55-item specification), kept to read stored run snapshots and to upgrade case manifests."""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SURVEY_IDS = tuple(f"q{i:02}" for i in range(1, 31))
Checklist = dict[Literal["entry", "separation", "training", "play", "exit"], Literal["unknown", "performed", "skipped", "retake"]]
MAPPING_FILE = Path(__file__).resolve().parents[3] / "resources/catalogs/survey-v1-to-v2.json"


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class StoredVideo(Model):
    video_id: str
    camera_id: str
    original_name: str
    storage_ref: str
    sha256: str
    size_bytes: int
    media_status: Literal["pending_probe"] = "pending_probe"


class Session(Model):
    session_id: str
    capture_mode: Literal["simultaneous", "sequential", "unknown"]
    route_note: str
    survey_version: str
    survey: dict[str, int | None]
    videos: list[StoredVideo]
    checklist: Checklist = Field(default_factory=dict)


class Manifest(Model):
    schema_version: Literal["intake-1.0"] = "intake-1.0"
    case_id: str
    event_id: str
    participant_id: str
    input_revision: int
    selected_session_id: str
    display_run_id: str | None = None
    sessions: list[Session]


def upgrade(data: dict, *, survey_version: str) -> tuple[dict, list[str]]:
    """Return an intake-2.0 manifest dict and the ids of non-null answers that had no 28-item counterpart."""
    old = Manifest.model_validate(data)
    table = json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    mapping = table["mapping"]
    new_ids = sorted((set(mapping.values()) - {None}) | set(table["new_without_source"]))
    dropped, sessions = [], []
    for session in old.sessions:
        survey = dict.fromkeys(new_ids)
        for q, s in mapping.items():
            if s is not None:
                survey[s] = session.survey.get(q)
            elif session.survey.get(q) is not None:
                dropped.append(f"{session.session_id}:{q}")
        note_parts = [session.route_note] if session.route_note else []
        if session.capture_mode != "unknown":
            note_parts.append({"simultaneous": "동시 촬영", "sequential": "순차 촬영"}[session.capture_mode])
        sessions.append({
            "session_id": session.session_id, "note": " · ".join(note_parts)[:2000], "survey_version": survey_version,
            "survey": survey, "survey_not_applicable": [],
            "videos": [video.model_dump(exclude={"camera_id"}) for video in session.videos],
        })
    upgraded = {
        "schema_version": "intake-2.0", "case_id": old.case_id, "event_id": old.event_id,
        "participant_id": old.participant_id, "input_revision": old.input_revision,
        "selected_session_id": old.selected_session_id, "display_run_id": old.display_run_id, "sessions": sessions,
        "migration_note": f"intake-1.0에서 이관. 대응 문항이 없어 버린 응답 {len(dropped)}개: {', '.join(dropped) or '없음'}",
    }
    return upgraded, dropped
