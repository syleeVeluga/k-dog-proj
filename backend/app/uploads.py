"""Receive immutable files before separately appending them to an S1 session."""

from dataclasses import dataclass
import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import BinaryIO

from fastapi import HTTPException
from pydantic import ValidationError

from .domain.media_v4 import (CAMERA_ORIGINALS, MediaParentV4, PreservedMediaRegistrationV4, StoredMediaV4,
                              UploadCreateV4, UploadLinkV4, UploadReceiptV4)
from .intake import selected_session
from .storage import encode, now, uid


def init_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS upload_receipts (
        upload_id TEXT PRIMARY KEY, creator TEXT NOT NULL REFERENCES users(username),
        request_id TEXT NOT NULL, request_hash TEXT NOT NULL, request_json TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('receiving','complete','failed','linked')),
        scope_case_id TEXT, scope_session_id TEXT, claim_token TEXT, session_hash TEXT,
        temp_ref TEXT, storage_ref TEXT, sha256 TEXT, size_bytes INTEGER,
        linked_case_id TEXT, linked_session_id TEXT, video_id TEXT, link_json TEXT,
        linked_revision INTEGER, failure_code TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(creator,request_id))""")
    db.execute("CREATE INDEX IF NOT EXISTS receipt_case ON upload_receipts(linked_case_id,scope_case_id)")


def _account(db, actor, *, linked_reader=False):
    account = db.execute("SELECT * FROM users WHERE username=?", (actor,)).fetchone()
    allowed = ("operator", "admin", "reviewer") if linked_reader else ("operator", "admin")
    if not account or not account["active"] or account["role"] not in allowed:
        raise HTTPException(403, "영상 수신·연결 권한이 없습니다.")
    return account


def _case(store, db, case_id, session_id, expected=None, *, selected=True):
    row = store.case(db, case_id, expected=expected)
    manifest = store.manifest(row)
    if manifest.schema_version != "intake-4.0":
        raise HTTPException(409, "S1 전환을 완료한 대상에 연결하세요.")
    if manifest.consents.analysis_feedback == "declined":
        raise HTTPException(403, "분석·피드백 동의가 거절된 자료입니다.")
    if selected:
        session = selected_session(manifest, session_id)
    else:
        session = next((item for item in manifest.sessions if item.session_id == session_id), None)
        if session is None:
            raise HTTPException(409, "연결된 촬영 회차가 더 이상 존재하지 않습니다.")
    return row, manifest, session


def _row(store, db, upload_id, actor, request_id=None, *, available_parents=True, linked_reader=False):
    _account(db, actor, linked_reader=linked_reader)
    row = db.execute("SELECT * FROM upload_receipts WHERE upload_id=?", (upload_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "수신물을 찾을 수 없습니다.")
    if linked_reader and row["state"] != "linked":
        raise HTTPException(403, "참가자·회차에 연결된 영상만 열람할 수 있습니다.")
    if request_id is not None and (row["creator"] != actor or row["request_id"] != request_id):
        raise HTTPException(409, "수신 요청 식별자가 일치하지 않습니다.")
    case_id = row["linked_case_id"] or row["scope_case_id"]
    if case_id:
        _case(store, db, case_id, row["linked_session_id"] or row["scope_session_id"], selected=False)
    for parent in json.loads(row["request_json"])["parents"]:
        parent_row = _row(store, db, parent["upload_id"], actor, available_parents=available_parents,
                          linked_reader=linked_reader)
        if available_parents and (parent_row["state"] not in ("complete", "linked") or parent_row["sha256"] != parent["sha256"]):
            raise HTTPException(409, "변환 원본 수신물이 더 이상 유효하지 않습니다.")
    return row


def _view(row):
    request = json.loads(row["request_json"])
    link = json.loads(row["link_json"]) if row["link_json"] else {}
    return UploadReceiptV4(
        upload_id=row["upload_id"], request_id=row["request_id"], creator=row["creator"],
        filename=request["filename"], state=row["state"], expected_size=request["expected_size"],
        size_bytes=row["size_bytes"], sha256=row["sha256"], source_kind=request["source_kind"],
        media_status="storage_only" if Path(request["filename"]).suffix.lower() == ".insv" else "pending_probe",
        case_id=row["linked_case_id"] or row["scope_case_id"],
        session_id=row["linked_session_id"] or row["scope_session_id"], video_id=row["video_id"],
        camera_id=link.get("camera_id"), linked_revision=row["linked_revision"], failure_code=row["failure_code"],
        created_at=row["created_at"], updated_at=row["updated_at"])


def _parents(store, db, request, actor, target=None):
    parents = []
    for parent in request.parents:
        row = _row(store, db, parent.upload_id, actor)
        if row["state"] not in ("complete", "linked") or row["sha256"] != parent.sha256:
            raise HTTPException(409, "변환 원본의 수신 상태 또는 해시가 다릅니다.")
        if parent.video_id is not None and parent.video_id != row["video_id"]:
            raise HTTPException(409, "변환 원본 영상 식별자가 다릅니다.")
        if target and (row["linked_case_id"], row["linked_session_id"]) != target:
            raise HTTPException(409, "변환 원본을 같은 대상·회차에 먼저 연결하세요.")
        parents.append(MediaParentV4(upload_id=parent.upload_id, sha256=parent.sha256, video_id=row["video_id"]))
    return tuple(parents)


def create_receipt(store, value: UploadCreateV4, actor: str) -> UploadReceiptV4:
    value = UploadCreateV4.model_validate_json(value.model_dump_json())
    request_json = encode(value.model_dump(mode="json"))
    request_hash = hashlib.sha256(request_json.encode()).hexdigest()
    with store.connect(write=True) as db:
        _account(db, actor)
        existing = db.execute("SELECT * FROM upload_receipts WHERE creator=? AND request_id=?", (actor, value.request_id)).fetchone()
        if existing:
            existing = _row(store, db, existing["upload_id"], actor, value.request_id, available_parents=False)
            if existing["request_hash"] != request_hash:
                raise HTTPException(409, "같은 요청 ID에 다른 파일 정보를 사용할 수 없습니다.")
            return _view(existing)
        if value.case_id:
            _case(store, db, value.case_id, value.session_id)
        _parents(store, db, value, actor)
        upload_id, timestamp = uid(), now()
        db.execute("INSERT INTO upload_receipts(upload_id,creator,request_id,request_hash,request_json,state,scope_case_id,"
                   "scope_session_id,created_at,updated_at) VALUES(?,?,?,?,?,'receiving',?,?,?,?)",
                   (upload_id, actor, value.request_id, request_hash, request_json, value.case_id, value.session_id, timestamp, timestamp))
        store.audit(db, actor, upload_id, "upload.create", {"case_id": value.case_id})
        return _view(_row(store, db, upload_id, actor))


def get_receipt(store, upload_id, actor):
    with store.connect() as db:
        return _view(_row(store, db, upload_id, actor, available_parents=False))


def list_receipts(store, actor):
    with store.connect() as db:
        _account(db, actor)
        result = []
        for row in db.execute("SELECT upload_id FROM upload_receipts ORDER BY created_at DESC"):
            try:
                result.append(_view(_row(store, db, row["upload_id"], actor, available_parents=False)))
            except HTTPException as exc:
                if exc.status_code not in (403, 404):
                    raise
        return result


@dataclass
class UploadWriter:
    upload_id: str
    request_id: str
    actor: str
    token: str | None
    session_hash: str | None
    request: UploadCreateV4
    handle: BinaryIO | None
    temp_ref: str | None
    final_ref: str | None
    digest: object
    size: int = 0


def begin_receive(store, upload_id, request_id, actor) -> UploadWriter:
    with store.connect(write=True) as db:
        row = _row(store, db, upload_id, actor, request_id)
        account = _account(db, actor)
        request = UploadCreateV4.model_validate_json(row["request_json"])
        if row["state"] in ("complete", "linked"):
            return UploadWriter(upload_id, request_id, actor, None, account["session_hash"], request,
                                None, None, None, hashlib.sha256())
        if row["claim_token"]:
            raise HTTPException(409, "이 파일의 수신이 이미 진행 중입니다.")
        token = uid()
        temp_ref = f"videos/{upload_id}-{token}.part"
        final_ref = f"videos/{upload_id}-{token}{Path(request.filename).suffix.lower()}"
        db.execute("UPDATE upload_receipts SET state='receiving',claim_token=?,session_hash=?,temp_ref=?,"
                   "failure_code=NULL,updated_at=? WHERE upload_id=?",
                   (token, account["session_hash"], temp_ref, now(), upload_id))
    writer = UploadWriter(upload_id, request_id, actor, token, account["session_hash"], request,
                          None, temp_ref, final_ref, hashlib.sha256())
    try:
        writer.handle = store.path(temp_ref).open("xb")
    except OSError:
        fail_receive(store, writer, "write_failed")
        raise HTTPException(507, "수신 파일을 저장할 공간과 권한을 확인하세요.") from None
    return writer


def write_chunk(writer: UploadWriter, chunk: bytes):
    if not isinstance(chunk, bytes):
        raise ValueError("upload stream must contain bytes")
    writer.size += len(chunk)
    if writer.size > writer.request.expected_size:
        raise HTTPException(422, "선언한 파일 크기를 초과했습니다.")
    if writer.handle is not None:
        writer.handle.write(chunk)
    writer.digest.update(chunk)


def finish_receive(store, writer: UploadWriter) -> UploadReceiptV4:
    if writer.handle is not None:
        writer.handle.flush()
        os.fsync(writer.handle.fileno())
        writer.handle.close()
        writer.handle = None
    digest = writer.digest.hexdigest()
    if writer.size != writer.request.expected_size or writer.size == 0:
        raise HTTPException(422, "수신 파일 크기가 선언한 값과 다릅니다.")
    if writer.request.expected_sha256 and digest != writer.request.expected_sha256:
        raise HTTPException(422, "수신 파일 해시가 선언한 값과 다릅니다.")
    with store.connect() as db:
        checked = _row(store, db, writer.upload_id, writer.actor, writer.request_id)
        sources = _lineage(db, checked)
        if writer.token is not None:
            sources.pop(writer.upload_id)
    identities = _verify_sources(store, sources)
    with store.connect(write=True) as db:
        row = _row(store, db, writer.upload_id, writer.actor, writer.request_id)
        if _account(db, writer.actor)["session_hash"] != writer.session_hash:
            raise HTTPException(403, "수신 중 로그인 권한이 변경되었습니다.")
        _assert_sources(store, db, sources, identities)
        if writer.token is None:
            if row["state"] not in ("complete", "linked") or (digest, writer.size) != (row["sha256"], row["size_bytes"]):
                raise HTTPException(409, "같은 요청 ID로 다른 파일을 재전송할 수 없습니다.")
            return _view(row)
        if row["state"] != "receiving" or row["claim_token"] != writer.token:
            raise HTTPException(409, "이 수신 시도는 더 이상 유효하지 않습니다.")
        _parents(store, db, writer.request, writer.actor)
        os.replace(store.path(writer.temp_ref), store.path(writer.final_ref))
        db.execute("UPDATE upload_receipts SET state='complete',claim_token=NULL,session_hash=NULL,temp_ref=NULL,"
                   "storage_ref=?,sha256=?,size_bytes=?,failure_code=NULL,updated_at=? WHERE upload_id=?",
                   (writer.final_ref, digest, writer.size, now(), writer.upload_id))
        store.audit(db, writer.actor, writer.upload_id, "upload.complete", {"size_bytes": writer.size})
        return _view(_row(store, db, writer.upload_id, writer.actor))


def fail_receive(store, writer: UploadWriter, code="interrupted"):
    if writer.handle is not None:
        writer.handle.close()
        writer.handle = None
    if writer.token is None:
        return
    with store.connect(write=True) as db:
        row = db.execute("SELECT state,claim_token FROM upload_receipts WHERE upload_id=?", (writer.upload_id,)).fetchone()
        completed = row and row["state"] in ("complete", "linked")
        if row and row["claim_token"] == writer.token:
            db.execute("UPDATE upload_receipts SET state='failed',claim_token=NULL,session_hash=NULL,temp_ref=NULL,"
                       "failure_code=?,updated_at=? WHERE upload_id=?", (code, now(), writer.upload_id))
    for ref in (writer.temp_ref, None if completed else writer.final_ref):
        if ref:
            store.path(ref).unlink(missing_ok=True)


async def _offload(operation, *args):
    # Cancellation must not close/unlink the writer while its disk operation is still running.
    running = asyncio.create_task(asyncio.to_thread(operation, *args))
    try:
        return await asyncio.shield(running)
    except asyncio.CancelledError:
        while not running.done():
            try:
                await asyncio.shield(running)
            except asyncio.CancelledError:
                continue
            except BaseException:
                break
        if not running.cancelled():
            running.exception()  # Retrieve a worker failure while preserving the cancellation.
        raise


async def receive(store, upload_id, request_id, chunks, actor):
    writer = begin_receive(store, upload_id, request_id, actor)
    try:
        async for chunk in chunks:
            await _offload(write_chunk, writer, chunk)
        return await _offload(finish_receive, store, writer)
    except BaseException:
        await _offload(fail_receive, store, writer)
        raise


def _verify_file(store, row):
    if not row["storage_ref"] or not row["sha256"]:
        raise HTTPException(409, "수신 완료된 파일이 없습니다.")
    path = store.path(row["storage_ref"])
    if not path.is_file() or path.stat().st_size != row["size_bytes"]:
        raise HTTPException(409, "수신 파일이 없거나 크기가 다릅니다.")
    with path.open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != row["sha256"]:
            raise HTTPException(409, "수신 파일의 해시가 다릅니다.")
    return path


def _file_identity(path):
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _lineage(db, receipt):
    """Snapshot all immutable source rows while the receipt's access check is current."""
    sources, pending = {}, [receipt]
    while pending:
        row = pending.pop()
        if row["upload_id"] in sources:
            continue
        sources[row["upload_id"]] = dict(row)
        for parent in json.loads(row["request_json"])["parents"]:
            source = db.execute("SELECT * FROM upload_receipts WHERE upload_id=?", (parent["upload_id"],)).fetchone()
            if source is None:
                raise HTTPException(409, "변환 원본 수신물이 없습니다.")
            pending.append(source)
    return sources


def _verify_sources(store, sources):
    identities = {}
    try:
        for source_id, source in sources.items():
            identities[source_id] = _file_identity(store.path(source["storage_ref"]))
            _verify_file(store, source)
    except OSError:
        raise HTTPException(409, "수신 파일 또는 변환 원본을 확인할 수 없습니다.") from None
    return identities


def _assert_sources(store, db, sources, identities):
    for source_id, source in sources.items():
        current = db.execute("SELECT * FROM upload_receipts WHERE upload_id=?", (source_id,)).fetchone()
        if (current is None or current["state"] not in ("complete", "linked") or any(
                current[key] != source[key] for key in ("storage_ref", "sha256", "size_bytes"))):
            raise HTTPException(409, "수신 파일 또는 변환 원본의 참조가 변경되었습니다.")
        try:
            if _file_identity(store.path(source["storage_ref"])) != identities[source_id]:
                raise HTTPException(409, "검증 중 수신 파일 또는 변환 원본이 변경되었습니다.")
        except OSError:
            raise HTTPException(409, "검증 중 수신 파일 또는 변환 원본이 사라졌습니다.") from None


def link_receipt(store, upload_id, value: UploadLinkV4, actor) -> UploadReceiptV4:
    value = UploadLinkV4.model_validate_json(value.model_dump_json())
    binding = value.model_dump(mode="json", exclude={"expected_revision"})
    binding["source_original_number"] = value.source_original_number or CAMERA_ORIGINALS.get(value.camera_id)
    # Large-file hashing precedes the short append transaction. Complete files are immutable.
    with store.connect() as db:
        checked = dict(_row(store, db, upload_id, actor))
        sources = _lineage(db, checked)
    if checked["state"] not in ("complete", "linked"):
        raise HTTPException(409, "파일 수신을 완료한 후 연결하세요.")
    identities = _verify_sources(store, sources)
    with store.connect(write=True) as db:
        receipt = _row(store, db, upload_id, actor)
        _assert_sources(store, db, sources, identities)
        if receipt["scope_case_id"] and (receipt["scope_case_id"], receipt["scope_session_id"]) != (value.case_id, value.session_id):
            raise HTTPException(409, "수신할 때 지정한 대상·회차와 다릅니다.")
        if receipt["state"] == "linked":
            if json.loads(receipt["link_json"]) != binding:
                raise HTTPException(409, "이미 연결한 수신물의 대상·카메라는 변경할 수 없습니다.")
            return _view(receipt)
        if receipt["state"] != "complete":
            raise HTTPException(409, "파일 수신을 완료한 후 연결하세요.")
        case, manifest, session = _case(store, db, value.case_id, value.session_id, value.expected_revision)
        request = UploadCreateV4.model_validate_json(receipt["request_json"])
        parents = _parents(store, db, request, actor, (value.case_id, value.session_id))
        existing = next((video for video in session.videos if video.sha256 == receipt["sha256"]), None)
        if existing is not None:
            if not isinstance(existing, StoredMediaV4) or (existing.camera_id, existing.source_original_number,
                    existing.source_kind, existing.parents, existing.conversion) != (
                    value.camera_id, binding["source_original_number"], request.source_kind, parents, request.conversion):
                raise HTTPException(409, "이 회차에 동일 파일이 다른 촬영 정보로 등록되어 있습니다.")
            video_id, revision = existing.video_id, case["input_revision"]
        else:
            video_id = uid()
            session.videos.append(StoredMediaV4(video_id=video_id, upload_id=upload_id,
                original_name=request.filename, storage_ref=receipt["storage_ref"], sha256=receipt["sha256"],
                size_bytes=receipt["size_bytes"], camera_id=value.camera_id,
                source_original_number=binding["source_original_number"], source_kind=request.source_kind,
                parents=parents, conversion=request.conversion, media_status=_view(receipt).media_status))
            store.save(db, case, manifest, actor, "video.receipt.link")
            revision = manifest.input_revision
        db.execute("UPDATE upload_receipts SET state='linked',linked_case_id=?,linked_session_id=?,video_id=?,"
                   "link_json=?,linked_revision=?,updated_at=? WHERE upload_id=?",
                   (value.case_id, value.session_id, video_id, encode(binding), revision, now(), upload_id))
        store.audit(db, actor, upload_id, "upload.link", {"case_id": value.case_id, "video_id": video_id})
        return _view(_row(store, db, upload_id, actor))


def register_preserved_video(store, case_id: str, session_id: str, video_id: str,
                             value: PreservedMediaRegistrationV4, actor: str) -> UploadReceiptV4:
    """Register capture provenance on preserved bytes without replacing their path or ID."""
    value = PreservedMediaRegistrationV4.model_validate_json(value.model_dump_json())
    with store.connect() as db:
        account = _account(db, actor)
        _, _, session = _case(store, db, case_id, session_id)
        video = next((item for item in session.videos if item.video_id == video_id), None)
        if video is None:
            raise HTTPException(404, "이 회차에 보존된 영상을 찾을 수 없습니다.")
        try:
            request = UploadCreateV4(request_id=value.request_id, filename=video.original_name,
                expected_size=video.size_bytes, expected_sha256=video.sha256, case_id=case_id, session_id=session_id,
                source_kind=value.source_kind, parents=value.parents, conversion=value.conversion)
        except ValidationError:
            raise HTTPException(422, "보존된 파일 형식과 원본·변환 출처 정보가 맞지 않습니다.") from None
        binding = UploadLinkV4(case_id=case_id, session_id=session_id, camera_id=value.camera_id,
            source_original_number=value.source_original_number or CAMERA_ORIGINALS.get(value.camera_id),
            expected_revision=value.expected_revision).model_dump(mode="json", exclude={"expected_revision"})
        request_json = encode(request.model_dump(mode="json"))
        request_hash = hashlib.sha256(request_json.encode()).hexdigest()
        existing = db.execute("SELECT * FROM upload_receipts WHERE creator=? AND request_id=?", (actor, value.request_id)).fetchone()
        if existing and (existing["request_hash"] != request_hash or existing["state"] != "linked" or
                         (existing["linked_case_id"], existing["linked_session_id"], existing["video_id"]) != (case_id, session_id, video_id)):
            raise HTTPException(409, "같은 요청 ID가 다른 영상·출처 등록에 사용되었습니다.")
        if isinstance(video, StoredMediaV4) and (existing is None or existing["upload_id"] != video.upload_id):
            raise HTTPException(409, "이미 등록한 영상 출처를 이 경로에서 바꿀 수 없습니다.")
        _parents(store, db, request, actor, (case_id, session_id))
        sources = {}
        for parent in request.parents:
            sources.update(_lineage(db, _row(store, db, parent.upload_id, actor)))
        if existing:
            sources.update(_lineage(db, _row(store, db, existing["upload_id"], actor)))
        preserved = {"storage_ref": video.storage_ref, "sha256": video.sha256, "size_bytes": video.size_bytes}
        base_identity = (video.video_id, video.original_name, video.storage_ref, video.sha256, video.size_bytes)
        login_hash = account["session_hash"]
    identities = _verify_sources(store, sources)
    try:
        if existing:
            file_identity = identities[existing["upload_id"]]
        else:
            file_identity = _file_identity(store.path(video.storage_ref))
            _verify_file(store, preserved)
    except OSError:
        raise HTTPException(409, "보존된 영상 원본을 확인할 수 없습니다.") from None
    with store.connect(write=True) as db:
        if _account(db, actor)["session_hash"] != login_hash:
            raise HTTPException(403, "출처 등록 중 로그인 권한이 변경되었습니다.")
        case, manifest, session = _case(store, db, case_id, session_id)
        current = next((item for item in session.videos if item.video_id == video_id), None)
        if current is None or (current.video_id, current.original_name, current.storage_ref, current.sha256, current.size_bytes) != base_identity:
            raise HTTPException(409, "보존된 영상의 고정 참조가 변경되었습니다.")
        _assert_sources(store, db, sources, identities)
        parents = _parents(store, db, request, actor, (case_id, session_id))
        try:
            if _file_identity(store.path(video.storage_ref)) != file_identity:
                raise HTTPException(409, "확인 중 보존된 영상 원본이 변경되었습니다.")
        except OSError:
            raise HTTPException(409, "확인 중 보존된 영상 원본이 사라졌습니다.") from None
        existing = db.execute("SELECT * FROM upload_receipts WHERE creator=? AND request_id=?", (actor, value.request_id)).fetchone()
        if existing:
            if (existing["request_hash"] != request_hash or existing["state"] != "linked" or not isinstance(current, StoredMediaV4) or
                    current.upload_id != existing["upload_id"] or json.loads(existing["link_json"]) != binding or
                    (current.camera_id, current.source_original_number, current.source_kind, current.parents, current.conversion) !=
                    (value.camera_id, binding["source_original_number"], request.source_kind, parents, request.conversion)):
                raise HTTPException(409, "이미 등록된 출처 또는 수신 요청 정보가 다릅니다.")
            return _view(_row(store, db, existing["upload_id"], actor))
        if isinstance(current, StoredMediaV4):
            raise HTTPException(409, "이미 등록한 영상 출처를 이 경로에서 바꿀 수 없습니다.")
        _case(store, db, case_id, session_id, value.expected_revision)
        upload_id, timestamp = uid(), now()
        registered = StoredMediaV4(video_id=video_id, upload_id=upload_id, original_name=current.original_name,
            storage_ref=current.storage_ref, sha256=current.sha256, size_bytes=current.size_bytes,
            camera_id=value.camera_id, source_original_number=binding["source_original_number"], source_kind=request.source_kind,
            parents=parents, conversion=request.conversion,
            media_status="storage_only" if Path(current.original_name).suffix.lower() == ".insv" else "pending_probe")
        session.videos = [registered if item.video_id == video_id else item for item in session.videos]
        store.save(db, case, manifest, actor, "video.preserved.register")
        db.execute("INSERT INTO upload_receipts(upload_id,creator,request_id,request_hash,request_json,state,scope_case_id,scope_session_id,"
                   "storage_ref,sha256,size_bytes,linked_case_id,linked_session_id,video_id,link_json,linked_revision,created_at,updated_at) "
                   "VALUES(?,?,?,?,?,'linked',?,?,?,?,?,?,?,?,?,?,?,?)", (upload_id, actor, value.request_id, request_hash, request_json,
                   case_id, session_id, current.storage_ref, current.sha256, current.size_bytes, case_id, session_id, video_id,
                   encode(binding), manifest.input_revision, timestamp, timestamp))
        store.audit(db, actor, upload_id, "upload.register_preserved", {"case_id": case_id, "video_id": video_id,
                    "linked_revision": manifest.input_revision, "source_kind": request.source_kind})
        return _view(_row(store, db, upload_id, actor))


def download_path(store, upload_id, actor):
    with store.connect() as db:
        row = _row(store, db, upload_id, actor)
        if row["state"] not in ("complete", "linked"):
            raise HTTPException(409, "수신 완료된 파일만 내려받을 수 있습니다.")
        sources = _lineage(db, row)
    identities = _verify_sources(store, sources)
    with store.connect() as db:
        row = _row(store, db, upload_id, actor)
        _assert_sources(store, db, sources, identities)
        return store.path(row["storage_ref"])


def _linked_source(store, db, case_id, video_id, actor):
    _account(db, actor, linked_reader=True)
    manifest = store.manifest(store.case(db, case_id))
    if manifest.schema_version != "intake-4.0":
        raise HTTPException(409, "S1 연결 영상이 아닙니다.")
    if manifest.consents.analysis_feedback == "declined":
        raise HTTPException(403, "분석·피드백 동의가 거절된 자료입니다.")
    found = next(((session, video) for session in manifest.sessions for video in session.videos
                  if video.video_id == video_id), None)
    if found is None or not isinstance(found[1], StoredMediaV4):
        raise HTTPException(404, "이 참가자의 S1 수신 영상이 아닙니다.")
    session, video = found
    row = _row(store, db, video.upload_id, actor, linked_reader=True)
    if (row["linked_case_id"], row["linked_session_id"], row["video_id"], row["storage_ref"], row["sha256"], row["size_bytes"]) != (
            case_id, session.session_id, video_id, video.storage_ref, video.sha256, video.size_bytes):
        raise HTTPException(409, "참가자 영상과 수신 원본의 고정 연결이 다릅니다.")
    return row


def linked_video_path(store, case_id, video_id, actor):
    """Case readers can view linked media; the unlinked operator inbox stays separate."""
    with store.connect() as db:
        row = _linked_source(store, db, case_id, video_id, actor)
        sources = _lineage(db, row)
    identities = _verify_sources(store, sources)
    with store.connect() as db:
        row = _linked_source(store, db, case_id, video_id, actor)
        _assert_sources(store, db, sources, identities)
        return store.path(row["storage_ref"])


def abort_receipt(store, upload_id, actor):
    with store.connect(write=True) as db:
        row = _row(store, db, upload_id, actor, available_parents=False)
        account = _account(db, actor)
        if actor != row["creator"] and account["role"] != "admin":
            raise HTTPException(403, "작성자 또는 관리자만 수신물을 정리할 수 있습니다.")
        if row["state"] == "linked":
            raise HTTPException(409, "연결된 자료는 대상 삭제 절차로 정리하세요.")
        if any(parent["upload_id"] == upload_id for other in db.execute(
                "SELECT request_json FROM upload_receipts WHERE state!='failed'")
                for parent in json.loads(other["request_json"])["parents"]):
            raise HTTPException(409, "이 원본을 사용하는 파생 수신물을 먼저 정리하세요.")
        db.execute("UPDATE upload_receipts SET state='failed',claim_token=NULL,session_hash=NULL,temp_ref=NULL,"
                   "storage_ref=NULL,sha256=NULL,size_bytes=NULL,failure_code='cancelled',updated_at=? WHERE upload_id=?",
                   (now(), upload_id))
        store.audit(db, actor, upload_id, "upload.cancel", {})
        # Files become unreferenced; offline maintenance removes them after tombstones commit.
        return _view(db.execute("SELECT * FROM upload_receipts WHERE upload_id=?", (upload_id,)).fetchone())


def recover_interrupted(db):
    """Only call while API/upload writers are stopped, never on every Store open."""
    return db.execute("UPDATE upload_receipts SET state='failed',claim_token=NULL,session_hash=NULL,temp_ref=NULL,"
                      "failure_code='server_interrupted',updated_at=? WHERE state='receiving' AND claim_token IS NOT NULL",
                      (now(),)).rowcount


def references(db):
    return {row["storage_ref"]: row["sha256"] for row in db.execute(
        "SELECT storage_ref,sha256 FROM upload_receipts WHERE state IN ('complete','linked')")}


def _descendant_ids(rows, upload_ids):
    targets = set(upload_ids)
    while True:
        descendants = {row["upload_id"] for row in rows if any(
            parent["upload_id"] in targets for parent in json.loads(row["request_json"])["parents"])}
        if descendants <= targets:
            return targets
        targets.update(descendants)


def collect_case_upload_ids(db, case_id):
    """Read-only deletion scope, including failed/incomplete receipt descendants."""
    rows = db.execute("SELECT * FROM upload_receipts").fetchall()
    targets = {row["upload_id"] for row in rows if case_id in (row["scope_case_id"], row["linked_case_id"])}
    return _descendant_ids(rows, targets)


def purge_upload_ids(db, upload_ids):
    """Apply stable receipt tombstones even to backups predating their case link."""
    targets = _descendant_ids(db.execute("SELECT * FROM upload_receipts").fetchall(), upload_ids)
    for upload_id in targets:
        db.execute("DELETE FROM changes WHERE target=? AND action LIKE 'upload.%'", (upload_id,))
        db.execute("DELETE FROM upload_receipts WHERE upload_id=?", (upload_id,))
    return targets


def purge_case(db, case_id):
    """Call after recording receipt tombstones; offline clean removes unreferenced bytes."""
    return len(purge_upload_ids(db, collect_case_upload_ids(db, case_id)))
