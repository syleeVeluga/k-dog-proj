"""Local-first intake API (접수·설문·촬영·계정·개발자 키). All participant media is served through authorization."""

import base64
import asyncio
import binascii
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi import Path as ApiPath
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field, SecretStr

from app.auth import authenticate, check_password, create_user, password_hash, token_hash, user_view
from app.domain.catalog import SurveyCatalog
from app.domain.catalog_v3 import SurveyCatalogV3
from app.survey_v4 import SurveyResultV4, survey_scores_v4
from app.input_models import (
    ImportColumns, Key, Login, Message,
    Revision, SessionEdit, SessionMetadata, StoredVideo, UserCreate, UserEdit, UserView,
)
from app.intake import create_case, new_session, save_survey, selected_session, template
from app.storage import REPO_ROOT, Store, install_id, now, uid
from app import settings
from app import forms_v4, uploads, capture_v4, preprocess_v4, sheets_v4
from app.domain.catalog_v4 import BehaviorCatalogV4, load_catalog_v4
from app.domain.sheets_v4 import SheetDocumentV4
from app import judgements_v4
from app import run_v4, scoring_ai_v4, settings_v4
from app import opinions_v4, final_results_v4, disclosures_v4
from app import report_runs_v4, comparisons_v4
from app import external_comparisons_v4
from app import validation_data_v4, exports_v4
from app.domain.runs_v4 import ActionV4, RunViewV4, StartV4
from app.domain.preprocess_v4 import BatchV4, PreprocessRequestV4, PreprocessStatusV4
from app.domain.media_v4 import PreservedMediaRegistrationV4, StoredMediaV4, UploadCreateV4, UploadLinkV4, UploadReceiptV4
from app import secrets as vault
from app.input_models import Model
from app.input_models_v3 import CaseCreateV3, CaseEditV3, SurveyEditV3
from app.input_models_v4 import CaseViewV4, SessionV4


class SecretEdit(Model):
    value: Annotated[SecretStr, Field(min_length=8, max_length=512)]


class DeveloperKeys(Model):
    keys: list[settings.KeyState]


class FormsFile(Model):
    config: forms_v4.FormsPreviewRequestV4
    file_base64: Annotated[str, Field(max_length=45 * 1024 * 1024)]


class WorkbookFileV4(Model):
    file_base64: Annotated[str, Field(max_length=28 * 1024 * 1024)]


class ValidationFileV4(WorkbookFileV4):
    config: validation_data_v4.ValidationImportV4


COOKIE = "kdog_session"
DEFAULT_DATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "K-DOG" / "data"


def create_app(data_dir: Path | None = None, *, public_origin: str = "http://127.0.0.1:8000") -> FastAPI:
    origin = urlsplit(public_origin)
    if not origin.hostname or origin.scheme not in ("http", "https") or origin.path or origin.query or origin.fragment or origin.username:
        raise ValueError("K-DOG origin에는 스킴·호스트·포트만 지정하세요.")
    if origin.hostname not in ("127.0.0.1", "localhost", "::1") and origin.scheme != "https":
        raise ValueError("내부망 접속은 HTTPS origin과 TLS 프록시가 필요합니다.")
    store = Store(data_dir or DEFAULT_DATA)
    old_catalog = SurveyCatalog.model_validate_json((REPO_ROOT / "resources/catalogs/survey-v2.json").read_bytes())
    current_catalog = SurveyCatalogV3.model_validate_json((REPO_ROOT / "resources/catalogs/survey-v3.json").read_bytes())
    catalog = current_catalog
    dummy_password = password_hash(secrets.token_urlsafe(32))
    @asynccontextmanager
    async def lifespan(app):
        from app.maintenance import runtime_lock
        with runtime_lock(store, "api"):
            with store.connect(write=True) as db:
                uploads.recover_interrupted(db)
            yield

    app = FastAPI(title="K-DOG", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.store = store

    @app.get("/api/health")
    def health():
        return {"service": "K-DOG", "instance": os.environ.get("KDOG_INSTANCE", ""), "spec": "20261002",
                "install": install_id(store.root)}

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        if request.headers.get("host") != origin.netloc:
            return JSONResponse({"detail": "허용되지 않은 호스트입니다."}, status_code=400)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if request.headers.get("x-kdog-request") != "1" or request.headers.get("origin", public_origin) != public_origin:
                return JSONResponse({"detail": "요청 출처를 확인할 수 없습니다."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers.setdefault("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'")
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Never echo submitted passwords or participant values in validation errors.
        errors = [".".join(map(str, error["loc"])) + ": " + error["msg"] for error in exc.errors()]
        return JSONResponse({"detail": "; ".join(errors)}, status_code=422)

    @app.exception_handler(sqlite3.IntegrityError)
    async def conflict(request, exc):
        return JSONResponse({"detail": "중복 ID 또는 연결 충돌입니다. 입력을 확인하세요."}, status_code=409)

    @app.exception_handler(OSError)
    async def storage_error(request, exc):
        return JSONResponse({"detail": "파일 저장소를 사용할 수 없습니다. 공간과 접근 권한을 확인하세요."}, status_code=503)

    def current(request: Request):
        with store.connect() as db:
            return user_view(authenticate(db, request.cookies.get(COOKIE)))

    def roles(*allowed):
        def check(request: Request, user: Annotated[UserView, Depends(current)]):
            if user.role not in allowed:
                raise HTTPException(403, "이 작업에 필요한 권한이 없습니다.")
            if request.url.path.startswith(("/api/cases", "/api/forms")):
                with store.connect() as db:
                    old = db.execute("SELECT 1 FROM cases WHERE manifest_schema_version!='intake-4.0' LIMIT 1").fetchone()
                if old:
                    raise HTTPException(409, "S1 초기화가 필요합니다. 관리 명령으로 원입력을 보존하여 전환하세요.")
            return user
        return check

    reader = roles("operator", "reviewer", "admin")
    writer = roles("operator", "admin")
    administrator = roles("admin")
    developer = roles("developer")


    @app.get("/api/developer/settings", response_model=DeveloperKeys)
    def developer_settings(user=Depends(developer)):
        return {"keys": [{"provider": provider, "available": vault.available(store, provider),
            "reference": (vault.state(store, provider) or {}).get("reference", "environment")} for provider in vault.PROVIDERS]}

    @app.get("/api/settings-s1", response_model=settings_v4.AiSettingsViewV4)
    def ai_settings_s1(user=Depends(developer)):
        return settings_v4.view(store)

    @app.post("/api/settings-s1", response_model=dict[str, str], status_code=201)
    def ai_draft_s1(value: settings_v4.AiDraftV4, user=Depends(developer)):
        return settings_v4.save(store, value, user.username)

    @app.get("/api/settings-s1/{version}/diff", response_model=settings_v4.AiDifferenceV4)
    def ai_difference_s1(version: Key, user=Depends(developer)):
        return settings_v4.difference(store, version)

    @app.post("/api/settings-s1/{version}/activate", response_model=dict[str, str])
    def ai_activate_s1(version: Key, value: settings_v4.AiActivateV4, user=Depends(developer)):
        return settings_v4.activate(store, version, value, user.username)

    @app.post("/api/settings-s1/{version}/validate-s1", response_model=settings_v4.AiTrialResultV4)
    def ai_validate_s1(version: Key, value: settings_v4.AiTrialV4, user=Depends(developer)):
        return settings_v4.trial(store, version, value, user.username)

    @app.get("/api/scoring-ai-s1/readiness", response_model=scoring_ai_v4.AiReadinessV4)
    def ai_readiness_s1(user=Depends(reader)):
        return scoring_ai_v4.readiness(store)

    @app.get("/api/cases/{case_id}/sessions/{session_id}/runs-s1", response_model=list[RunViewV4])
    def ai_runs_s1(case_id: Key, session_id: Key, user=Depends(reader)):
        with store.connect() as db:
            preprocess_v4._case(store, db, case_id, session_id, user.username, selected=False)
            ids = [row[0] for row in db.execute("SELECT run_id FROM runs WHERE case_id=? AND session_id=? AND kind='s1' ORDER BY created_at DESC",
                                               (case_id, session_id))]
        return [run_v4.view(store, run_id, user) for run_id in ids]

    @app.post("/api/cases/{case_id}/sessions/{session_id}/runs-s1", response_model=RunViewV4, status_code=201)
    def ai_start_s1(case_id: Key, session_id: Key, value: StartV4, user=Depends(writer)):
        return scoring_ai_v4.start(store, case_id, session_id, value, user)

    @app.get("/api/runs-s1/{run_id}", response_model=RunViewV4)
    def ai_run_s1(run_id: Key, user=Depends(reader)):
        return run_v4.view(store, run_id, user)

    @app.post("/api/runs-s1/{run_id}/stop", response_model=RunViewV4)
    def ai_stop_s1(run_id: Key, value: ActionV4, user=Depends(writer)):
        return run_v4.action(store, run_id, value, user)

    @app.post("/api/runs-s1/{run_id}/retry", response_model=RunViewV4)
    def ai_retry_s1(run_id: Key, value: ActionV4, user=Depends(writer)):
        return run_v4.action(store, run_id, value, user, retry=True)

    @app.post("/api/score-sheets-s1/{sheet_id}/reveal-ai-s1", response_model=scoring_ai_v4.AiRevealResultV4)
    def ai_reveal_s1(sheet_id: Key, value: sheets_v4.SheetRevealV4, user=Depends(reader)):
        return scoring_ai_v4.reveal(store, sheet_id, value, user)


    @app.put("/api/developer/keys/{provider}", response_model=settings.KeyState)
    def register_key(provider: Literal["gemini", "openai", "anthropic"], value: SecretEdit, user=Depends(developer)):
        return vault.change(store, provider, value.value.get_secret_value(), user.username)

    @app.delete("/api/developer/keys/{provider}", response_model=settings.KeyState)
    def revoke_key(provider: Literal["gemini", "openai", "anthropic"], user=Depends(developer)):
        return vault.change(store, provider, None, user.username)

    @app.post("/api/developer/keys/{provider}/test", response_model=settings.KeyTest)
    def test_key(provider: Literal["gemini", "openai", "anthropic"], user=Depends(developer)):
        return vault.connection_test(store, provider, user.username)

    @app.post("/api/admin/backups", status_code=201)
    def backup_data(user=Depends(administrator)):
        from app.maintenance import backup
        return backup(store, store.root.parent / "backups" / uid(), user.username)

    @app.get("/api/admin/recovery")
    def recovery_status(user=Depends(administrator)):
        from app.maintenance import status
        return status(store)

    @app.post("/api/auth/login", response_model=UserView)
    def login(value: Login, response: Response):
        valid = False
        with store.connect(write=True) as db:
            row = db.execute("SELECT * FROM users WHERE username=?", (value.username,)).fetchone()
            matches = check_password(value.password, row["password_hash"] if row else dummy_password)
            if row and row["active"] and row["locked_until"] <= time.time():
                valid = matches
                if valid:
                    token = secrets.token_urlsafe(32)
                    db.execute("UPDATE users SET session_hash=?,session_expires=?,failed_logins=0,locked_until=0 WHERE username=?",
                               (token_hash(token), time.time() + 8 * 3600, value.username))
                else:
                    count = row["failed_logins"] + 1
                    db.execute("UPDATE users SET failed_logins=?,locked_until=? WHERE username=?",
                               (count, time.time() + 60 if count >= 5 else 0, value.username))
        if not valid:
            raise HTTPException(401, "로그인 정보를 확인하세요. 반복 실패 시 잠시 후 다시 시도하세요.")
        response.set_cookie(COOKIE, token, httponly=True, secure=origin.scheme == "https",
                            samesite="strict", max_age=8 * 3600, path="/")
        return user_view(row)

    @app.get("/api/auth/me", response_model=UserView)
    def me(user=Depends(current)):
        return user

    @app.post("/api/auth/logout", response_model=Message)
    def logout(request: Request, response: Response, user=Depends(current)):
        with store.connect(write=True) as db:
            db.execute("UPDATE users SET session_hash=NULL,session_expires=NULL WHERE session_hash=?",
                       (token_hash(request.cookies.get(COOKIE, "")),))
        response.delete_cookie(COOKIE, path="/")
        return Message(message="로그아웃되었습니다.")

    @app.get("/api/admin/users", response_model=list[UserView])
    def users(user=Depends(administrator)):
        with store.connect() as db:
            return [user_view(row) for row in db.execute("SELECT * FROM users WHERE role!='developer' ORDER BY username")]

    @app.post("/api/admin/users", response_model=UserView, status_code=201)
    def add_user(value: UserCreate, user=Depends(administrator)):
        if value.role == "developer":
            raise HTTPException(403, "개발자 계정은 별도 로컬 관리 경로로 발급합니다.")
        with store.connect(write=True) as db:
            create_user(db, value)
            store.audit(db, user.username, value.username, "user.create", {"role": value.role})
        return UserView(username=value.username, role=value.role, active=True)

    @app.patch("/api/admin/users/{username}", response_model=UserView)
    def edit_user(username: Key, value: UserEdit, user=Depends(administrator)):
        with store.connect(write=True) as db:
            row = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            if row is None:
                raise HTTPException(404, "계정이 없습니다.")
            if row["role"] == "developer" or value.role == "developer" or username == user.username:
                raise HTTPException(403, "개발자 계정 또는 자신의 권한을 변경할 수 없습니다.")
            db.execute("UPDATE users SET role=?,active=?,session_hash=NULL,session_expires=NULL WHERE username=?",
                       (value.role, value.active, username))
            store.audit(db, user.username, username, "user.update", value.model_dump())
        return UserView(username=username, role=value.role, active=value.active)


    @app.get("/api/catalog/survey", response_model=SurveyCatalog | SurveyCatalogV3)
    def survey_catalog(version: str | None = None, user=Depends(reader)):
        if version is None:
            return catalog
        if version == old_catalog.version:
            return old_catalog
        if version == current_catalog.version:
            return current_catalog
        raise HTTPException(422, "지원하지 않는 설문 판본입니다.")

    @app.get("/api/cases", response_model=list[CaseViewV4])
    def cases(response: Response, user=Depends(reader)):
        values, unavailable = [], 0
        with store.connect() as db:
            for row in db.execute("SELECT * FROM cases WHERE deletion_requested=0 ORDER BY created_at DESC"):
                try:
                    values.append(store.view(row))
                except HTTPException as exc:
                    if exc.status_code != 409:
                        raise
                    unavailable += 1
        response.headers["X-KDOG-Unavailable-Cases"] = str(unavailable)
        return values

    @app.post("/api/cases", response_model=CaseViewV4, status_code=201)
    def add_case(value: CaseCreateV3, user=Depends(writer)):
        with store.connect(write=True) as db:
            case_id = create_case(store, db, value, user.username, catalog.version)
            return store.view(store.case(db, case_id))

    @app.get("/api/cases/{case_id}", response_model=CaseViewV4)
    def get_case(case_id: Key, user=Depends(reader)):
        with store.connect() as db:
            return store.view(store.case(db, case_id))

    @app.put("/api/cases/{case_id}", response_model=CaseViewV4)
    def edit_case(case_id: Key, value: CaseEditV3, user=Depends(writer)):
        with store.connect(write=True) as db:
            row = store.case(db, case_id, expected=value.expected_revision)
            manifest = store.manifest(row)
            manifest.participant_id = value.participant_id
            if value.consents is not None:
                manifest.consents = value.consents
            store.save(db, row, manifest, user.username, "case.update")
            db.execute("UPDATE cases SET participant_id=?,dog_name=?,reservation_at=?,sequence_no=?,consent_confirmed=?,guardian_name=?,dog_profile_json=? WHERE case_id=?",
                       (value.participant_id, value.dog_name, value.reservation_at, value.sequence_no, int(value.consent_confirmed),
                        value.guardian_name, value.dog.model_dump_json(), case_id))
            store.audit(db, user.username, case_id, "case.identity", {
                "before": {**{k: row[k] for k in ("participant_id", "dog_name", "reservation_at", "sequence_no", "guardian_name")},
                           "consent_confirmed": bool(row["consent_confirmed"]), "consents": json.loads(row["consents_v3_json"]),
                           "dog": json.loads(row["dog_profile_json"])},
                "after": value.model_dump(exclude={"expected_revision"})})
            return store.view(store.case(db, case_id))

    @app.put("/api/cases/{case_id}/survey", response_model=CaseViewV4)
    def survey(case_id: Key, value: SurveyEditV3, user=Depends(writer)):
        with store.connect(write=True) as db:
            save_survey(store, db, case_id, value, user.username, current_catalog if value.survey_version == current_catalog.version else old_catalog)
            return store.view(store.case(db, case_id))

    @app.get("/api/cases/{case_id}/survey/result", response_model=SurveyResultV4)
    def survey_result(case_id: Key, session_id: Key | None = None, user=Depends(reader)):
        """Deterministic, so it is computed on read: domain answer counts and the separation type, never a total (01 §6)."""
        with store.connect() as db:
            manifest = store.manifest(store.case(db, case_id))
        session = next((item for item in manifest.sessions if item.session_id == (session_id or manifest.selected_session_id)), None)
        if session is None:
            raise HTTPException(422, "이 참가자의 촬영 회차가 아닙니다.")
        if session.survey_version != current_catalog.version:
            raise HTTPException(409, "이 회차는 과거 설문 원자료 참고 상태입니다. S1 설문 산출에 포함하지 않습니다.")
        return survey_scores_v4(SessionV4.model_validate(session), current_catalog)

    @app.post("/api/cases/{case_id}/deletion", response_model=Message)
    def request_deletion(case_id: Key, value: Revision, user=Depends(writer)):
        with store.connect(write=True) as db:
            store.case(db, case_id, expected=value.expected_revision)
            db.execute("UPDATE cases SET deletion_requested=1,updated_at=? WHERE case_id=?", (now(), case_id))
            db.execute("UPDATE runs SET status='stopped',claim_token=NULL,lease_expires_at=NULL "
                       "WHERE case_id=? AND status IN ('queued','running','retry_wait')", (case_id,))
            store.audit(db, user.username, case_id, "deletion.request", {})
        return Message(message="삭제 요청을 접수했습니다.")

    @app.post("/api/cases/{case_id}/sessions", response_model=CaseViewV4)
    def sessions(case_id: Key, value: SessionEdit, user=Depends(writer)):
        with store.connect(write=True) as db:
            row = store.case(db, case_id, expected=value.expected_revision)
            manifest = store.manifest(row)
            if value.session_id is None:
                session = new_session(catalog.version, value.note)
                manifest.sessions.append(session)
                manifest.selected_session_id = session.session_id
            else:
                if value.session_id not in {item.session_id for item in manifest.sessions}:
                    raise HTTPException(422, "이 참가자의 촬영 세션이 아닙니다.")
                manifest.selected_session_id = value.session_id
            store.save(db, row, manifest, user.username, "session.select")
            return store.view(store.case(db, case_id))

    @app.post("/api/cases/{case_id}/videos", response_model=CaseViewV4, status_code=201)
    async def upload_video(case_id: Key, request: Request,
                           session_id: Key,
                           filename: Annotated[str, Query(min_length=1, max_length=200)],
                           expected_revision: Annotated[int, Query(ge=1)], user=Depends(writer)):
        extension = Path(filename).suffix.lower()
        if extension not in (".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"):
            raise HTTPException(422, "지원 영상 파일 확장자를 확인하세요.")
        with store.connect() as db:
            row = store.case(db, case_id, expected=expected_revision)
            selected_session(store.manifest(row), session_id)
        video_id = uid()
        key = f"videos/{video_id}{extension}"
        path = store.path(key)
        digest = hashlib.sha256()
        size = 0
        adopted = False
        try:
            with path.open("xb") as handle:
                async for chunk in request.stream():
                    size += len(chunk)
                    handle.write(chunk)
                    digest.update(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if size == 0:
                raise HTTPException(422, "빈 영상 파일은 등록할 수 없습니다.")
            with store.connect(write=True) as db:
                current_user = authenticate(db, request.cookies.get(COOKIE))
                if current_user["role"] not in ("operator", "admin"):
                    raise HTTPException(403, "업로드 권한이 변경되었습니다.")
                row = store.case(db, case_id, expected=expected_revision)
                manifest = store.manifest(row)
                session = selected_session(manifest, session_id)
                if any(video.sha256 == digest.hexdigest() for video in session.videos):
                    raise HTTPException(409, "이 촬영 세션에 동일한 파일이 이미 등록되어 있습니다.")
                session.videos.append(StoredVideo(video_id=video_id,
                                      original_name=filename, storage_ref=key,
                                      sha256=digest.hexdigest(), size_bytes=size))
                store.save(db, row, manifest, user.username, "video.register")
                result = store.view(store.case(db, case_id))
            adopted = True
            return result
        finally:
            if not adopted:
                path.unlink(missing_ok=True)

    @app.get("/api/cases/{case_id}/videos/{video_id}")
    def video_file(case_id: Key, video_id: Key, request: Request, user=Depends(reader)):
        with store.connect() as db:
            row = store.case(db, case_id)
            manifest = store.manifest(row)
            videos = [video for session in manifest.sessions for video in session.videos]
            video = next((item for item in videos if item.video_id == video_id), None)
            if video is None:
                raise HTTPException(404, "이 참가자의 영상이 아닙니다.")
            if manifest.schema_version == "intake-4.0" and manifest.consents.analysis_feedback == "declined":
                raise HTTPException(403, "분석·피드백 동의가 거절된 자료입니다.")
            if isinstance(video, StoredMediaV4):
                path = uploads.linked_video_path(store, case_id, video_id, user.username)
                return FileResponse(path, filename=video.original_name,
                    content_disposition_type="attachment" if video.media_status == "storage_only" else "inline")
            path = store.path(video.storage_ref)
            if not path.is_file() or path.stat().st_size != video.size_bytes:
                raise HTTPException(409, "영상 파일이 없거나 크기가 변경되었습니다.")
            with path.open("rb") as handle:
                if hashlib.file_digest(handle, "sha256").hexdigest() != video.sha256:
                    raise HTTPException(409, "영상 파일 해시가 일치하지 않습니다.")
            # Hashing a large file can take time; refresh access immediately before serving.
            current_user = authenticate(db, request.cookies.get(COOKIE))
            if current_user["role"] not in ("operator", "reviewer", "admin"):
                raise HTTPException(403, "영상 열람 권한이 변경되었습니다.")
            current_manifest = store.manifest(store.case(db, case_id))
            if current_manifest.schema_version == "intake-4.0" and current_manifest.consents.analysis_feedback == "declined":
                raise HTTPException(403, "분석·피드백 동의가 거절된 자료입니다.")
            return FileResponse(path, filename=f"{video_id}{path.suffix}", content_disposition_type="inline")

    @app.put("/api/cases/{case_id}/sessions/{session_id}", response_model=CaseViewV4)
    def session_metadata(case_id: Key, session_id: Key, value: SessionMetadata, user=Depends(writer)):
        with store.connect(write=True) as db:
            row = store.case(db, case_id, expected=value.expected_revision)
            manifest = store.manifest(row)
            session = selected_session(manifest, session_id)
            session.note = value.note
            store.save(db, row, manifest, user.username, "session.metadata")
            return store.view(store.case(db, case_id))

    @app.get("/api/uploads", response_model=list[UploadReceiptV4])
    def upload_receipts(user=Depends(writer)):
        return uploads.list_receipts(store, user.username)

    @app.post("/api/uploads", response_model=UploadReceiptV4, status_code=201)
    def upload_create(value: UploadCreateV4, user=Depends(writer)):
        return uploads.create_receipt(store, value, user.username)

    @app.get("/api/uploads/{upload_id}", response_model=UploadReceiptV4)
    def upload_receipt(upload_id: Key, user=Depends(writer)):
        return uploads.get_receipt(store, upload_id, user.username)

    @app.put("/api/uploads/{upload_id}/content", response_model=UploadReceiptV4)
    async def upload_receive(upload_id: Key, request_id: Key, request: Request, user=Depends(writer)):
        return await uploads.receive(store, upload_id, request_id, request.stream(), user.username)

    @app.post("/api/uploads/{upload_id}/link", response_model=UploadReceiptV4)
    def upload_link(upload_id: Key, value: UploadLinkV4, user=Depends(writer)):
        return uploads.link_receipt(store, upload_id, value, user.username)

    @app.get("/api/uploads/{upload_id}/content")
    def upload_download(upload_id: Key, user=Depends(writer)):
        receipt = uploads.get_receipt(store, upload_id, user.username)
        path = uploads.download_path(store, upload_id, user.username)
        return FileResponse(path, filename=receipt.filename, media_type="application/octet-stream")

    @app.delete("/api/uploads/{upload_id}", response_model=UploadReceiptV4)
    def upload_abort(upload_id: Key, user=Depends(writer)):
        return uploads.abort_receipt(store, upload_id, user.username)

    @app.put("/api/cases/{case_id}/sessions/{session_id}/videos/{video_id}/registration", response_model=CaseViewV4)
    def preserved_video_registration(case_id: Key, session_id: Key, video_id: Key,
                                     value: PreservedMediaRegistrationV4, user=Depends(writer)):
        uploads.register_preserved_video(store, case_id, session_id, video_id, value, user.username)
        with store.connect() as db:
            return store.view(store.case(db, case_id))

    @app.get("/api/catalog/protocol-s1")
    def protocol_s1(user=Depends(reader)):
        from app.domain.catalog_v4 import load_rules_v4
        return load_rules_v4("protocol")

    @app.get("/api/cases/{case_id}/sessions/{session_id}/recording-s1", response_model=capture_v4.RecordingStateV4)
    def recording_s1(case_id: Key, session_id: Key, user=Depends(reader)):
        return capture_v4.state(store, case_id, session_id, user.username)

    @app.put("/api/cases/{case_id}/sessions/{session_id}/recording-s1", response_model=CaseViewV4)
    async def recording_s1_save(case_id: Key, session_id: Key, request: Request, user=Depends(writer)):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 1024 * 1024:
                raise HTTPException(413, "촬영 기록 크기가 제한을 넘었습니다.")
        from pydantic import ValidationError
        try:
            value = capture_v4.RecordingEditV4.model_validate_json(data)
        except ValidationError as exc:
            errors = [".".join(map(str, error["loc"])) + ": " + error["msg"] for error in exc.errors()]
            raise HTTPException(422, "; ".join(errors)) from None
        return await asyncio.to_thread(capture_v4.save, store, case_id, session_id, value, request.cookies.get(COOKIE))

    @app.get("/api/cases/{case_id}/sessions/{session_id}/preprocess-s1", response_model=PreprocessStatusV4)
    def preprocessing_s1_status(case_id: Key, session_id: Key, user=Depends(reader)):
        return preprocess_v4.status(store, case_id, session_id, user.username)

    @app.post("/api/cases/{case_id}/sessions/{session_id}/preprocess-s1", response_model=BatchV4)
    async def preprocessing_s1_start(case_id: Key, session_id: Key, request: Request, user=Depends(writer)):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 65536:
                raise HTTPException(413, "전처리 요청 크기가 제한을 넘었습니다.")
        from pydantic import ValidationError
        try:
            value = PreprocessRequestV4.model_validate_json(data)
        except ValidationError:
            raise HTTPException(422, "전처리 요청 ID·입력 버전·카메라·재사용 원본을 확인하세요.") from None
        return await asyncio.to_thread(preprocess_v4.execute, store, case_id, session_id, user.username, value)

    @app.get("/api/cases/{case_id}/sessions/{session_id}/preprocess-s1/{batch_id}/clips/{clip_id}/{kind}")
    def preprocessing_s1_clip(case_id: Key, session_id: Key, batch_id: Key, clip_id: Key,
                              kind: Literal["original", "ai"], user=Depends(reader)):
        return FileResponse(preprocess_v4.clip_path(store, case_id, session_id, batch_id, clip_id, kind, user.username),
                            media_type="video/mp4", content_disposition_type="inline")

    @app.get("/api/catalog/behavior-s1", response_model=BehaviorCatalogV4)
    def behavior_s1(user=Depends(reader)):
        return load_catalog_v4()

    @app.get("/api/cases/{case_id}/sessions/{session_id}/sheets-s1", response_model=list[sheets_v4.SheetSummaryV4])
    def scoring_s1_sheets(case_id: Key, session_id: Key, user=Depends(reader)):
        return sheets_v4.list_sheets(store, case_id, session_id, user)

    @app.post("/api/cases/{case_id}/sessions/{session_id}/sheets-s1", response_model=sheets_v4.SheetSummaryV4, status_code=201)
    def scoring_s1_assign(case_id: Key, session_id: Key, value: sheets_v4.SheetAssignmentV4, user=Depends(writer)):
        return sheets_v4.assign(store, case_id, session_id, value, user)

    @app.get("/api/score-sheets-s1/{sheet_id}", response_model=sheets_v4.SheetViewV4)
    def scoring_s1_sheet(sheet_id: Key, user=Depends(reader)):
        return sheets_v4.view(store, sheet_id, user)

    @app.get("/api/score-sheets-s1/{sheet_id}/revisions/{revision}", response_model=SheetDocumentV4)
    def scoring_s1_revision(sheet_id: Key, revision: Annotated[int, ApiPath(ge=1)], user=Depends(reader)):
        return sheets_v4.revision(store, sheet_id, revision, user)

    @app.put("/api/score-sheets-s1/{sheet_id}", response_model=sheets_v4.SheetSummaryV4)
    def scoring_s1_save(sheet_id: Key, value: sheets_v4.SheetEditV4, user=Depends(reader)):
        return sheets_v4.revise(store, sheet_id, value, user, "save")

    @app.post("/api/score-sheets-s1/{sheet_id}/submit", response_model=sheets_v4.SheetSummaryV4)
    def scoring_s1_submit(sheet_id: Key, value: sheets_v4.SheetReasonV4, user=Depends(reader)):
        return sheets_v4.revise(store, sheet_id, value, user, "submit")

    @app.post("/api/score-sheets-s1/{sheet_id}/reopen", response_model=sheets_v4.SheetSummaryV4)
    def scoring_s1_reopen(sheet_id: Key, value: sheets_v4.SheetReasonV4, user=Depends(writer)):
        return sheets_v4.revise(store, sheet_id, value, user, "reopen")

    @app.post("/api/score-sheets-s1/{sheet_id}/assignment", response_model=sheets_v4.SheetSummaryV4)
    def scoring_s1_active(sheet_id: Key, value: sheets_v4.SheetActiveV4, user=Depends(writer)):
        return sheets_v4.revise(store, sheet_id, value, user, "assignment")

    @app.post("/api/score-sheets-s1/{sheet_id}/grants", response_model=sheets_v4.SheetSummaryV4)
    def scoring_s1_grant(sheet_id: Key, value: sheets_v4.SheetGrantV4, user=Depends(writer)):
        return sheets_v4.grant(store, sheet_id, value, user)

    @app.post("/api/score-sheets-s1/{sheet_id}/reveal", response_model=sheets_v4.SheetRevealResultV4)
    def scoring_s1_reveal(sheet_id: Key, value: sheets_v4.SheetRevealV4, user=Depends(reader)):
        return sheets_v4.revise(store, sheet_id, value, user, "reveal")

    @app.get("/api/import/s1-workbook/status")
    def s1_workbook_status(user=Depends(writer)):
        return sheets_v4.workbook_preflight()

    @app.get("/api/score-sheets-s1/{sheet_id}/basic-results-s1", response_model=list[judgements_v4.ResultSummaryV4])
    def basic_s1_results(sheet_id: Key, user=Depends(reader)):
        return judgements_v4.list_results(store, sheet_id, user)

    @app.post("/api/score-sheets-s1/{sheet_id}/basic-results-s1", response_model=judgements_v4.ResultViewV4, status_code=201)
    def basic_s1_calculate(sheet_id: Key, value: judgements_v4.CalculateV4, user=Depends(reader)):
        return judgements_v4.create(store, sheet_id, value, user)

    @app.get("/api/basic-results-s1/{result_id}", response_model=judgements_v4.ResultViewV4)
    def basic_s1_result(result_id: Key, user=Depends(reader)):
        return judgements_v4.view(store, result_id, user)

    @app.get("/api/basic-results-s1/{result_id}/revisions/{revision}", response_model=judgements_v4.ResultViewV4)
    def basic_s1_result_revision(result_id: Key, revision: Annotated[int, ApiPath(ge=1)], user=Depends(reader)):
        return judgements_v4.view(store, result_id, user, revision)

    @app.put("/api/basic-results-s1/{result_id}/judgements", response_model=judgements_v4.ResultViewV4)
    def basic_s1_judgements(result_id: Key, value: judgements_v4.JudgementEditV4, user=Depends(reader)):
        return judgements_v4.revise(store, result_id, value, user)

    @app.get("/api/cases/{case_id}/sessions/{session_id}/opinions-s1", response_model=opinions_v4.OpinionViewV4)
    def opinions_s1(case_id: Key, session_id: Key, viewer_sheet_id: Key | None = None, user=Depends(reader)):
        return opinions_v4.view(store, case_id, session_id, user, viewer_sheet_id)

    @app.put("/api/cases/{case_id}/sessions/{session_id}/opinions-s1", response_model=opinions_v4.OpinionViewV4)
    def opinions_s1_save(case_id: Key, session_id: Key, value: opinions_v4.OpinionWriteV4, user=Depends(reader)):
        return opinions_v4.save(store, case_id, session_id, value, user)

    @app.get("/api/cases/{case_id}/sessions/{session_id}/opinions-s1/metadata", response_model=opinions_v4.OpinionMetadataV4)
    def opinions_s1_metadata(case_id: Key, session_id: Key, user=Depends(reader)):
        return opinions_v4.metadata(store, case_id, session_id, user)

    @app.post("/api/cases/{case_id}/sessions/{session_id}/opinions-s1/reveal", response_model=disclosures_v4.InterpretationRevealResultV4)
    def opinions_s1_reveal(case_id: Key, session_id: Key, value: disclosures_v4.InterpretationRevealV4, user=Depends(reader)):
        if value.target.kind != "opinion":
            raise HTTPException(422, "의견 판본만 열람할 수 있습니다.")
        return disclosures_v4.reveal(store, case_id, session_id, value, user)

    @app.post("/api/cases/{case_id}/sessions/{session_id}/opinions-s1/reopen", response_model=opinions_v4.OpinionViewV4)
    def opinions_s1_reopen(case_id: Key, session_id: Key, value: opinions_v4.OpinionActionV4, user=Depends(reader)):
        return opinions_v4.action(store, case_id, session_id, value, user, "reopen")

    @app.post("/api/cases/{case_id}/sessions/{session_id}/opinions-s1/withdraw", response_model=opinions_v4.OpinionViewV4)
    def opinions_s1_withdraw(case_id: Key, session_id: Key, value: opinions_v4.OpinionActionV4, user=Depends(reader)):
        return opinions_v4.action(store, case_id, session_id, value, user, "withdraw")

    @app.get("/api/cases/{case_id}/sessions/{session_id}/final-results-s1", response_model=list[final_results_v4.FinalSummaryV4])
    def final_s1_results(case_id: Key, session_id: Key, viewer_sheet_id: Key | None = None, user=Depends(reader)):
        return final_results_v4.list_results(store, case_id, session_id, user, viewer_sheet_id)

    @app.post("/api/cases/{case_id}/sessions/{session_id}/final-results-s1", response_model=final_results_v4.FinalViewV4, status_code=201)
    def final_s1_assemble(case_id: Key, session_id: Key, value: final_results_v4.AssembleFinalV4, user=Depends(reader)):
        return final_results_v4.assemble(store, case_id, session_id, value, user)

    @app.get("/api/cases/{case_id}/sessions/{session_id}/final-results-s1/candidates", response_model=list[judgements_v4.ResultSummaryV4])
    def final_s1_candidates(case_id: Key, session_id: Key, viewer_sheet_id: Key | None = None, user=Depends(reader)):
        return opinions_v4.basic_candidates(store, case_id, session_id, user, viewer_sheet_id)

    @app.get("/api/cases/{case_id}/sessions/{session_id}/final-results-s1/candidates/{result_id}/{revision}", response_model=judgements_v4.ResultViewV4)
    def final_s1_candidate(case_id: Key, session_id: Key, result_id: Key, revision: Annotated[int, ApiPath(ge=1)], viewer_sheet_id: Key | None = None, user=Depends(reader)):
        return opinions_v4.basic_candidate(store, case_id, session_id, result_id, revision, user, viewer_sheet_id)

    @app.get("/api/cases/{case_id}/sessions/{session_id}/final-results-s1/{final_id}", response_model=final_results_v4.FinalViewV4)
    def final_s1_result(case_id: Key, session_id: Key, final_id: Key, viewer_sheet_id: Key | None = None, user=Depends(reader)):
        return final_results_v4.view(store, case_id, session_id, final_id, user, viewer_sheet_id)

    @app.post("/api/cases/{case_id}/sessions/{session_id}/final-results-s1/{final_id}/reveal", response_model=disclosures_v4.InterpretationRevealResultV4)
    def final_s1_reveal(case_id: Key, session_id: Key, final_id: Key, value: disclosures_v4.InterpretationRevealV4, user=Depends(reader)):
        if value.target.kind != "final" or value.target.document_id != final_id:
            raise HTTPException(422, "선택한 최종 판본과 열람 대상이 다릅니다.")
        return disclosures_v4.reveal(store, case_id, session_id, value, user)

    @app.get("/api/cases/{case_id}/sessions/{session_id}/report-runs-s1", response_model=list[report_runs_v4.ReportRunViewV4])
    def report_s1_runs(case_id: Key, session_id: Key, user=Depends(reader)):
        return report_runs_v4.list_runs(store, case_id, session_id, user)

    @app.post("/api/cases/{case_id}/sessions/{session_id}/report-runs-s1", response_model=report_runs_v4.ReportRunViewV4, status_code=201)
    def report_s1_start(case_id: Key, session_id: Key, value: report_runs_v4.ReportStartV4, user=Depends(reader)):
        return report_runs_v4.enqueue(store, case_id, session_id, value, user)

    @app.get("/api/report-runs-s1/{run_id}", response_model=report_runs_v4.ReportRunViewV4)
    def report_s1_run(run_id: Key, viewer_sheet_id: Key | None = None, user=Depends(reader)):
        return report_runs_v4.view(store, run_id, user, viewer_sheet_id)

    @app.post("/api/report-runs-s1/{run_id}/stop", response_model=report_runs_v4.ReportRunViewV4)
    def report_s1_stop(run_id: Key, value: report_runs_v4.ReportActionV4, user=Depends(reader)):
        return report_runs_v4.action(store, run_id, value, user)

    @app.post("/api/report-runs-s1/{run_id}/retry", response_model=report_runs_v4.ReportRunViewV4)
    def report_s1_retry(run_id: Key, value: report_runs_v4.ReportActionV4, user=Depends(reader)):
        return report_runs_v4.action(store, run_id, value, user, retry=True)

    @app.get("/api/cases/{case_id}/sessions/{session_id}/report-runs-s1/{run_id}/files/{format}")
    def report_s1_file(case_id: Key, session_id: Key, run_id: Key, format: Literal["html", "pdf", "manifest"], viewer_sheet_id: Key | None = None, inline: bool = False, user=Depends(reader)):
        data, mime, filename = report_runs_v4.download(store, case_id, session_id, run_id, format, user, viewer_sheet_id)
        headers = {"Content-Disposition": f'{"inline" if inline and format in ("html", "pdf") else "attachment"}; filename="{filename}"'}
        if format == "html":
            headers["Content-Security-Policy"] = "default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; font-src data:; img-src data:; frame-ancestors 'self'; base-uri 'none'; form-action 'none'"
        return Response(data, media_type=mime, headers=headers)

    @app.get("/api/comparisons-s1/candidates", response_model=list[comparisons_v4.CohortCandidateV4])
    def comparison_s1_candidates(user=Depends(writer)):
        return comparisons_v4.candidates(store, user)

    @app.get("/api/comparisons-s1/cohorts", response_model=list[comparisons_v4.CohortSummaryV4])
    def comparison_s1_list(user=Depends(writer)):
        return comparisons_v4.list_snapshots(store, user)

    @app.post("/api/comparisons-s1/cohorts", response_model=comparisons_v4.CohortViewV4, status_code=201)
    def comparison_s1_create(value: comparisons_v4.CohortCreateV4, user=Depends(writer)):
        return comparisons_v4.create(store, value, user)

    @app.get("/api/comparisons-s1/cohorts/{snapshot_id}", response_model=comparisons_v4.CohortViewV4)
    def comparison_s1_view(snapshot_id: Key, user=Depends(writer)):
        return comparisons_v4.view(store, snapshot_id, user)

    @app.get("/api/comparisons-s1/sources")
    def comparison_s1_sources(user=Depends(writer)):
        return comparisons_v4.public_sources(store,user)

    @app.post("/api/comparisons-s1/evidence", response_model=external_comparisons_v4.FileV4, status_code=201)
    async def comparison_s1_evidence(request: Request, filename: Annotated[str,Query(min_length=1,max_length=200)], user=Depends(administrator)):
        data=bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data)>16*1024*1024:raise HTTPException(413,"연구 근거 파일은 16 MiB 이하만 등록할 수 있습니다.")
        return external_comparisons_v4.upload_evidence(store,bytes(data),filename,user)

    @app.post("/api/comparisons-s1/external-snapshots", response_model=external_comparisons_v4.ExternalViewV4, status_code=201)
    def comparison_s1_external_create(value:external_comparisons_v4.ExternalCreateV4,user=Depends(writer)):
        return external_comparisons_v4.create(store,value,user)

    @app.get("/api/comparisons-s1/external-snapshots", response_model=list[external_comparisons_v4.ExternalSummaryV4])
    def comparison_s1_external_list(user=Depends(writer)):
        return external_comparisons_v4.list_snapshots(store,user)

    @app.get("/api/comparisons-s1/external-snapshots/{snapshot_id}", response_model=external_comparisons_v4.ExternalViewV4)
    def comparison_s1_external_view(snapshot_id:Key,user=Depends(writer)):
        return external_comparisons_v4.view(store,snapshot_id,user)

    @app.get("/api/comparisons-s1/research")
    def comparison_s1_research(user=Depends(writer)):
        return comparisons_v4.research_inventory(store, user)

    @app.post("/api/comparisons-s1/research")
    def comparison_s1_confirm(value: comparisons_v4.ConfirmResearchV4, user=Depends(writer)):
        return comparisons_v4.confirm_research(store, value, user)

    @app.post("/api/comparisons-s1/activation")
    def comparison_s1_activate(value: comparisons_v4.ActivateExternalV4, user=Depends(writer)):
        return comparisons_v4.activate_external(store, value, user)

    async def validation_file_s1(request, model=ValidationFileV4):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 32 * 1024 * 1024:
                raise HTTPException(413, "참고 XLSX는 20 MiB 이하로 등록하세요.")
        from pydantic import ValidationError
        try:
            value = model.model_validate_json(data)
            source = base64.b64decode(value.file_base64, validate=True)
        except (ValidationError, binascii.Error, ValueError):
            raise HTTPException(422, "참고 파일과 명시 셀 연결 형식을 확인하세요.") from None
        return source, value

    @app.post("/api/validation-data-s1/workbook")
    async def validation_s1_workbook(request: Request, user=Depends(writer)):
        from app import s1_workbook
        source, _ = await validation_file_s1(request, WorkbookFileV4)
        try:
            workbook = s1_workbook.reference_cells(source, include_sheets=True)
        except (ValueError, OverflowError):
            raise HTTPException(422, "참고 XLSX 셀을 읽을 수 없습니다.") from None
        return {"source_sha256": hashlib.sha256(source).hexdigest(), "profile": s1_workbook.profile(), **workbook}

    @app.post("/api/validation-data-s1/preview", response_model=validation_data_v4.ValidationPreviewV4)
    async def validation_s1_preview(request: Request, user=Depends(writer)):
        source, value = await validation_file_s1(request)
        return validation_data_v4.preview(store, source, value.config, user)

    @app.post("/api/validation-data-s1", response_model=validation_data_v4.ValidationFullViewV4, status_code=201)
    async def validation_s1_register(request: Request, user=Depends(writer)):
        source, value = await validation_file_s1(request)
        return validation_data_v4.register(store, source, value.config, user)

    @app.get("/api/validation-data-s1/candidates", response_model=list[comparisons_v4.CohortCandidateV4])
    def validation_s1_candidates(user=Depends(writer)):
        return validation_data_v4.candidates(store, user)

    @app.get("/api/validation-data-s1", response_model=list[validation_data_v4.ValidationHistoryV4])
    def validation_s1_list(user=Depends(writer)):
        return validation_data_v4.list_records(store, user)

    @app.get("/api/validation-data-s1/{validation_id}", response_model=validation_data_v4.ValidationFullViewV4)
    def validation_s1_view(validation_id: Key, user=Depends(writer)):
        return validation_data_v4.view(store, validation_id, user)

    @app.post("/api/exports-s1", response_model=exports_v4.ExportViewV4, status_code=201)
    def export_s1_create(value: exports_v4.ExportCreateV4, user=Depends(writer)):
        return exports_v4.create(store, value, user)

    @app.get("/api/exports-s1", response_model=list[exports_v4.ExportHistoryV4])
    def export_s1_list(user=Depends(writer)):
        return exports_v4.list_exports(store, user)

    @app.get("/api/exports-s1/{export_id}", response_model=exports_v4.ExportViewV4)
    def export_s1_view(export_id: Key, user=Depends(writer)):
        return exports_v4.view(store, export_id, user)

    @app.get("/api/exports-s1/{export_id}/download")
    def export_s1_download(export_id: Key, user=Depends(writer)):
        data, mime, filename = exports_v4.download(store, export_id, user)
        return Response(data, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


    @app.get("/api/scoring/accounts", response_model=list[UserView])
    def scoring_accounts(user=Depends(writer)):
        with store.connect() as db:
            return [user_view(row) for row in db.execute("SELECT * FROM users WHERE active=1 AND role IN ('operator','reviewer','admin') ORDER BY username")]


    @app.get("/api/templates/{kind}")
    def input_template(kind: Literal["participants", "survey"], format: Literal["csv", "xlsx"] = "csv", user=Depends(writer)):
        return Response(template(kind, format, catalog.version), media_type="application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="kdog-{kind}.{format}"'})

    @app.post("/api/forms/columns", response_model=ImportColumns)
    async def forms_columns(request: Request, format: Literal["csv", "xlsx"],
                            layout: Literal["rows", "transposed"] = "rows", sheet: str | None = None, user=Depends(writer)):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > forms_v4.MAX_BYTES:
                raise HTTPException(413, "입력 파일은 32 MiB 이하로 나누어 등록하세요.")
        return forms_v4.inspect_columns(bytes(data), format, sheet, layout)

    @app.post("/api/forms/preview", response_model=forms_v4.FormsPreviewV4)
    async def forms_preview(request: Request, user=Depends(writer)):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 45 * 1024 * 1024:
                raise HTTPException(413, "입력 파일은 32 MiB 이하로 나누어 등록하세요.")
        from pydantic import ValidationError
        try:
            value = FormsFile.model_validate_json(data)
            source = base64.b64decode(value.file_base64, validate=True)
        except (ValidationError, binascii.Error, ValueError):
            raise HTTPException(422, "파일과 열 연결 형식을 확인하세요.") from None
        return forms_v4.preview(store, source, value.config, user.username)

    @app.post("/api/forms/commit", response_model=forms_v4.FormsCommitResultV4)
    def forms_commit(value: forms_v4.FormsCommitRequestV4, user=Depends(writer)):
        return forms_v4.commit(store, value, user.username)


    @app.api_route("/api/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"], include_in_schema=False)
    def missing_api(path: str):
        raise HTTPException(404, "API 경로가 없습니다.")

    build = REPO_ROOT / "frontend/dist"
    if build.is_dir():
        app.mount("/", StaticFiles(directory=build, html=True), name="ui")
    return app
