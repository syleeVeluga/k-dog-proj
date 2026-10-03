"""Revision-bound S1 recording edits; original procedure facts remain untouched."""

from typing import Annotated

from fastapi import HTTPException
from pydantic import Field

from app import uploads
from app.auth import authenticate
from app.domain.contracts_v4 import ContractV4
from app.domain.media_v4 import StoredMediaV4
from app.domain.recording_v4 import (
    ItemCaptureGateV4, RecordingV4, RecordingWindowV4, SafeBaseResultV4,
)
from app.input_models_v4 import ManifestV4
from app.intake import selected_session
from app.recording_v4 import (
    build_windows_v4, item_capture_gates_v4, safe_base_sequence_v4, validate_recording_media_v4,
)


class RecordingEditV4(ContractV4):
    expected_revision: Annotated[int, Field(ge=1)]
    recording: RecordingV4


class RecordingStateV4(ContractV4):
    recording: RecordingV4 | None
    windows: tuple[RecordingWindowV4, ...] = ()
    gates: tuple[ItemCaptureGateV4, ...] = ()
    safe_base: SafeBaseResultV4 | None = None


def _session(store, db, case_id, session_id, expected=None, *, selected=True):
    row = store.case(db, case_id, expected=expected)
    manifest = store.manifest(row)
    if not isinstance(manifest, ManifestV4):
        raise HTTPException(409, "S1 원입력 전환이 필요합니다.")
    if manifest.consents.analysis_feedback == "declined":
        raise HTTPException(403, "분석·피드백 동의가 거절된 자료입니다.")
    session = selected_session(manifest, session_id) if selected else next((value for value in manifest.sessions if value.session_id == session_id), None)
    if session is None:
        raise HTTPException(404, "촬영 회차를 찾을 수 없습니다.")
    return row, manifest, session


def state(store, case_id, session_id, actor):
    with store.connect() as db:
        uploads._account(db, actor, linked_reader=True)
        _, _, session = _session(store, db, case_id, session_id, selected=False)
        record = session.recording_s1
    if record is None:
        return RecordingStateV4(recording=None)
    return RecordingStateV4(recording=record, windows=build_windows_v4(record),
        gates=item_capture_gates_v4(record), safe_base=safe_base_sequence_v4(record))


def save(store, case_id, session_id, value: RecordingEditV4, token):
    value = RecordingEditV4.model_validate_json(value.model_dump_json())
    record = value.recording
    try:
        build_windows_v4(record)
        item_capture_gates_v4(record)
        safe_base_sequence_v4(record)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    video_ids = {record.video_id, *(event.video_id for event in record.events),
                 *(offset.video_id for offset in record.video_offsets), *(item.video_id for item in record.coverage)}
    sources = {}
    with store.connect() as db:
        actor = authenticate(db, token)["username"]
        uploads._account(db, actor)
        _, _, session = _session(store, db, case_id, session_id, value.expected_revision)
        referenced = [video for video in session.videos if video.video_id in video_ids]
        for video in referenced:
            if isinstance(video, StoredMediaV4):
                receipt = uploads._linked_source(store, db, case_id, video.video_id, actor)
                sources.update(uploads._lineage(db, receipt))
    # Hash/probe outside the write transaction; retain file identities through adoption.
    identities = {video.storage_ref: uploads._file_identity(store.path(video.storage_ref)) for video in referenced}
    source_identities = uploads._verify_sources(store, sources)
    validate_recording_media_v4(store, session, record)
    with store.connect(write=True) as db:
        actor = authenticate(db, token)["username"]
        uploads._account(db, actor)
        row, manifest, session = _session(store, db, case_id, session_id, value.expected_revision)
        uploads._assert_sources(store, db, sources, source_identities)
        for video in referenced:
            if uploads._file_identity(store.path(video.storage_ref)) != identities[video.storage_ref]:
                raise HTTPException(409, "확인 중 영상 파일이 변경되었습니다.")
            if isinstance(video, StoredMediaV4):
                uploads._linked_source(store, db, case_id, video.video_id, actor)
        session.recording_s1 = record
        session.recording_review_required = not record.confirmed or record.procedure_edition != "s1_confirmed"
        store.save(db, row, manifest, actor, "recording.s1.confirm" if record.confirmed else "recording.s1.update")
        return store.view(store.case(db, case_id))
