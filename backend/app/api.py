"""Local-first M1 API. All participant media is served through authorization."""

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
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field, SecretStr

from app.auth import authenticate, check_password, create_user, password_hash, token_hash, user_view
from app.analysis import check_access, control, enqueue, step_payload, validated_prepared, view_analysis
from app.domain.contracts import SurveyCatalog
from app.input_models import (
    CaseCreate, CaseEdit, CaseView, ImportColumns, ImportCommit, ImportMapping, ImportPreview, Key, Login, Message, Revision,
    SessionEdit, SessionMetadata, StoredVideo, SurveyEdit, UserCreate, UserEdit, UserView,
)
from app.intake import create_case, new_session, preview, read_rows, save_survey, selected_session, template
from app.storage import REPO_ROOT, Store, now, uid
from app.observation_models import AnalysisRequest, AnalysisView
from app.evaluation import active_configuration
from app.evaluation_models import SettingsEdit, SettingsView
from app.gemini import configuration as observation_configuration
from app.report_models import DeliveryRecord, ExportRequest, ExportView, FrameEdit, ReportSettingsEdit, ReportSettingsView, ReportView, ReviewEdit
from app import exports, reporting, settings
from app import secrets as vault
from app.input_models import Model


class SecretEdit(Model):
    value: Annotated[SecretStr, Field(min_length=8, max_length=512)]


COOKIE = "kdog_session"
DEFAULT_DATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "K-DOG" / "data"


def create_app(data_dir: Path | None = None, *, public_origin: str = "http://127.0.0.1:8000") -> FastAPI:
    origin = urlsplit(public_origin)
    if not origin.hostname or origin.scheme not in ("http", "https") or origin.path or origin.query or origin.fragment or origin.username:
        raise ValueError("K-DOG origin에는 스킴·호스트·포트만 지정하세요.")
    if origin.hostname not in ("127.0.0.1", "localhost", "::1") and origin.scheme != "https":
        raise ValueError("내부망 접속은 HTTPS origin과 TLS 프록시가 필요합니다.")
    store = Store(data_dir or DEFAULT_DATA)
    catalog = SurveyCatalog.model_validate_json((REPO_ROOT / "resources/catalogs/survey-v1.json").read_bytes())
    dummy_password = password_hash(secrets.token_urlsafe(32))
    @asynccontextmanager
    async def lifespan(app):
        from app.maintenance import runtime_lock
        with runtime_lock(store, "api"):
            yield

    app = FastAPI(title="K-DOG", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.store = store

    @app.get("/api/health")
    def health():
        return {"service": "K-DOG", "instance": os.environ.get("KDOG_INSTANCE", "")}

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
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
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
        def check(user: Annotated[UserView, Depends(current)]):
            if user.role not in allowed:
                raise HTTPException(403, "이 작업에 필요한 권한이 없습니다.")
            return user
        return check

    reader = roles("operator", "reviewer", "admin")
    writer = roles("operator", "admin")
    administrator = roles("admin")
    developer = roles("developer")

    @app.get("/api/developer/settings", response_model=settings.SettingsView)
    def developer_settings(user=Depends(developer)):
        return settings.view(store)

    @app.post("/api/developer/settings/drafts", status_code=201, response_model=settings.Version)
    def draft_settings(value: settings.DraftEdit, user=Depends(developer)):
        return settings.save(store, value, user.username)

    @app.get("/api/developer/settings/{version}", response_model=settings.Difference)
    def settings_difference(version: Key, user=Depends(developer)):
        return settings.difference(store, version)

    @app.post("/api/developer/settings/{version}/activate", response_model=settings.ActiveVersion)
    def activate_settings(version: Key, value: settings.Activate, user=Depends(developer)):
        return settings.activate(store, version, value, user.username)

    @app.post("/api/developer/settings/{version}/trial", response_model=settings.TrialResult)
    def trial_settings(version: Key, value: settings.TrialRequest, user=Depends(developer)):
        return settings.trial(store, version, value, user.username)

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

    def report_settings_view(db):
        version, config = reporting.active_report_configuration(db, observation_configuration()["model"])
        if settings.active(db) != "legacy":
            version, pipeline = settings.current(store, db)
            config = pipeline.report.model_dump()
        return ReportSettingsView(version=version, selection={"provider": config["provider"], "model": config["model"]},
            key_available=vault.available(store, config["provider"]))

    @app.get("/api/developer/report", response_model=ReportSettingsView)
    def report_settings(user=Depends(developer)):
        with store.connect() as db:
            return report_settings_view(db)

    @app.put("/api/developer/report", response_model=ReportSettingsView)
    def save_report_settings(value: ReportSettingsEdit, user=Depends(developer)):
        with store.connect(write=True) as db:
            if settings.active(db) != "legacy":
                raise HTTPException(409, "버전 편집 화면에서 초안과 운영 적용을 사용하세요.")
            if report_settings_view(db).version != value.expected_version:
                raise HTTPException(409, "설명 설정이 변경되었습니다. 새로 조회하세요.")
            version = uid()
            store.audit(db, user.username, version, "report.configure", {"version": version, "selection": value.selection.model_dump()})
            return report_settings_view(db)

    @app.get("/api/cases/{case_id}/reports/{run_id}", response_model=ReportView)
    def get_report(case_id: Key, run_id: Key, user=Depends(reader)):
        with store.connect(write=True) as db:
            return reporting.report_view(store, db, reporting.run_row(store, db, case_id, run_id))

    @app.put("/api/cases/{case_id}/reports/{run_id}", response_model=ReportView)
    def edit_report(case_id: Key, run_id: Key, value: ReviewEdit, user=Depends(reader)):
        return reporting.edit_review(store, case_id, run_id, value, user.username)

    @app.post("/api/cases/{case_id}/reports/{run_id}/generate", response_model=Message)
    def request_report(case_id: Key, run_id: Key, user=Depends(reader)):
        with store.connect(write=True) as db:
            row = reporting.run_row(store, db, case_id, run_id)
            if "report" not in json.loads(row["config_snapshot_json"]):
                raise HTTPException(409, "M4 설명 설정이 없는 이전 실행입니다. 관찰·평가를 재사용한 새 분석을 시작하세요.")
            view = reporting.report_view(store, db, row)
            if len(view.result["evaluations"]) != 2:
                raise HTTPException(409, "두 평가 분기가 준비된 후 설명을 생성하세요.")
            if row["status"] in ("queued", "running", "retry_wait"):
                return Message(message="실행이 처리 중입니다.")
            if view.status in ("ready", "manual"):
                return Message(message="현재 점수에 맞는 설명이 준비되어 있습니다.")
            steps = db.execute("SELECT * FROM steps WHERE run_id=? AND stage='report' AND branch_key=?", (run_id, view.source_hash)).fetchall()
            if len(steps) >= json.loads(row["config_snapshot_json"]).get("max_attempts", 3) or sum(json.loads(s["usage_json"]).get("code") == "evaluation_schema_invalid" for s in steps) >= 2:
                raise HTTPException(409, "설명 시도 한도에 도달했습니다. 수동 설명 수정 또는 새 실행을 사용하세요.")
            db.execute("UPDATE runs SET status='queued',claim_token=NULL,lease_expires_at=NULL WHERE run_id=?", (run_id,))
            store.audit(db, user.username, run_id, "report.request", {"source_hash": view.source_hash})
        return Message(message="설명 생성을 접수했습니다. 점수는 계속 조회할 수 있습니다.")

    @app.put("/api/cases/{case_id}/reports/{run_id}/image", response_model=ReportView)
    def choose_frame(case_id: Key, run_id: Key, value: FrameEdit, user=Depends(reader)):
        return reporting.save_frame(store, case_id, run_id, value, user.username)

    @app.get("/api/cases/{case_id}/reports/{run_id}/image")
    def report_image(case_id: Key, run_id: Key, user=Depends(reader)):
        with store.connect() as db:
            reporting.run_row(store, db, case_id, run_id)
            selected = reporting.revision_state(store, db, run_id)["image"]
            if not selected:
                raise HTTPException(404, "대표 이미지가 없습니다.")
            raw = store.path(selected["ref"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != selected["hash"]:
                raise HTTPException(409, "대표 이미지 해시가 일치하지 않습니다.")
            reporting.run_row(store, db, case_id, run_id)
            return Response(raw, media_type="image/png")

    @app.post("/api/exports", response_model=ExportView, status_code=201)
    def create_export(value: ExportRequest, user=Depends(reader)):
        return exports.export_view(exports.capture(store, value, user.username))

    @app.post("/api/exports/preview", response_model=ExportView)
    def preview_export(value: ExportRequest, user=Depends(reader)):
        return exports.export_view(exports.capture(store, value, user.username, persist=False), "preview")

    @app.post("/api/exports/{export_id}/deliveries", response_model=ExportView)
    def record_delivery(export_id: Key, value: DeliveryRecord, user=Depends(writer)):
        return exports.record_delivery(store, export_id, value, user.username)

    @app.get("/api/exports", response_model=list[ExportView])
    def list_exports(case_id: Key | None = None, user=Depends(reader)):
        result = []
        with store.connect() as db:
            for row in db.execute("SELECT target FROM changes WHERE action='export.snapshot' ORDER BY rowid DESC"):
                try:
                    snapshot = exports.load_snapshot(store, db, row["target"])
                except HTTPException as exc:
                    if exc.status_code == 403:
                        continue
                    raise
                if case_id and (not snapshot["individual"] or snapshot["members"][0]["case_id"] != case_id):
                    continue
                ready = db.execute("SELECT 1 FROM changes WHERE target=? AND action='export.file'", (row["target"],)).fetchone()
                result.append(exports.export_view(snapshot, "ready" if ready else "snapshot", store=store, db=db))
        return result

    @app.post("/api/exports/{export_id}/generate", response_model=Message)
    def generate_export(export_id: Key, user=Depends(reader)):
        exports.generate(store, export_id, user.username)
        return Message(message="파일이 준비되었습니다.")

    @app.get("/api/exports/{export_id}/file")
    def download_export(export_id: Key, user=Depends(reader)):
        with store.connect() as db:
            snapshot = exports.load_snapshot(store, db, export_id)
            row = db.execute("SELECT detail_json FROM changes WHERE target=? AND action='export.file' ORDER BY rowid DESC LIMIT 1", (export_id,)).fetchone()
            if not row:
                raise HTTPException(409, "파일 생성을 먼저 요청하세요.")
            link = json.loads(row[0])
            path = store.path(link["ref"])
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != link["hash"]:
                raise HTTPException(409, "내보내기 파일 해시가 일치하지 않습니다.")
            exports.guard_snapshot(store, db, snapshot)
            return Response(raw, media_type={".pdf": "application/pdf", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".zip": "application/zip"}[path.suffix],
                            headers={"Content-Disposition": f'attachment; filename="kdog-{export_id}{path.suffix}"'})

    def settings_view(db):
        version, config = active_configuration(db, observation_configuration()["model"])
        if settings.active(db) != "legacy":
            version, pipeline = settings.current(store, db)
            config = {branch: getattr(pipeline, branch).model_dump() for branch in ("dog", "owner")}
        return SettingsView(version=version, branches={branch: {"provider": c["provider"], "model": c["model"]}
            for branch, c in config.items()}, key_available={branch: vault.available(store, c["provider"]) for branch, c in config.items()})

    @app.get("/api/developer/evaluation", response_model=SettingsView)
    def evaluation_settings(user=Depends(developer)):
        with store.connect() as db:
            return settings_view(db)

    @app.put("/api/developer/evaluation", response_model=SettingsView)
    def save_evaluation_settings(value: SettingsEdit, user=Depends(developer)):
        with store.connect(write=True) as db:
            if settings.active(db) != "legacy":
                raise HTTPException(409, "버전 편집 화면에서 초안과 운영 적용을 사용하세요.")
            current = settings_view(db)
            if value.expected_version != current.version:
                raise HTTPException(409, "평가 설정이 변경되었습니다. 새로고침 후 다시 적용하세요.")
            version = uid()
            store.audit(db, user.username, version, "evaluation.configure", {"version": version, "branches": value.branches.model_dump()})
            return settings_view(db)

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

    @app.get("/api/developer/status", response_model=Message)
    def developer_status(user=Depends(developer)):
        return Message(message="개발자 인증 완료. Gemini 모델·키는 서버 실행 환경에서 설정하세요. 설정 편집 UI는 M5 예정입니다.")

    @app.get("/api/catalog/survey", response_model=SurveyCatalog)
    def survey_catalog(user=Depends(reader)):
        return catalog

    @app.get("/api/cases", response_model=list[CaseView])
    def cases(user=Depends(reader)):
        with store.connect() as db:
            return [store.view(row) for row in db.execute("SELECT * FROM cases WHERE deletion_requested=0 ORDER BY created_at DESC")]

    @app.post("/api/cases", response_model=CaseView, status_code=201)
    def add_case(value: CaseCreate, user=Depends(writer)):
        with store.connect(write=True) as db:
            case_id = create_case(store, db, value, user.username, catalog.version)
            return store.view(store.case(db, case_id))

    @app.get("/api/cases/{case_id}", response_model=CaseView)
    def get_case(case_id: Key, user=Depends(reader)):
        with store.connect() as db:
            return store.view(store.case(db, case_id))

    @app.put("/api/cases/{case_id}", response_model=CaseView)
    def edit_case(case_id: Key, value: CaseEdit, user=Depends(writer)):
        with store.connect(write=True) as db:
            row = store.case(db, case_id, expected=value.expected_revision)
            manifest = store.manifest(row)
            manifest.participant_id = value.participant_id
            store.save(db, row, manifest, user.username, "case.update")
            db.execute("UPDATE cases SET participant_id=?,dog_name=?,reservation_at=? WHERE case_id=?",
                       (value.participant_id, value.dog_name, value.reservation_at, case_id))
            store.audit(db, user.username, case_id, "case.identity", {"before": {k: row[k] for k in ("participant_id", "dog_name", "reservation_at")},
                "after": value.model_dump(exclude={"expected_revision"})})
            return store.view(store.case(db, case_id))

    @app.put("/api/cases/{case_id}/survey", response_model=CaseView)
    def survey(case_id: Key, value: SurveyEdit, user=Depends(writer)):
        with store.connect(write=True) as db:
            save_survey(store, db, case_id, value, user.username, catalog.version)
            return store.view(store.case(db, case_id))

    @app.post("/api/cases/{case_id}/deletion", response_model=Message)
    def request_deletion(case_id: Key, value: Revision, user=Depends(writer)):
        with store.connect(write=True) as db:
            store.case(db, case_id, expected=value.expected_revision)
            db.execute("UPDATE cases SET deletion_requested=1,updated_at=? WHERE case_id=?", (now(), case_id))
            db.execute("UPDATE runs SET status='stopped',claim_token=NULL,lease_expires_at=NULL "
                       "WHERE case_id=? AND status IN ('queued','running','retry_wait')", (case_id,))
            store.audit(db, user.username, case_id, "deletion.request", {})
        return Message(message="삭제 요청을 접수했습니다.")

    @app.post("/api/cases/{case_id}/sessions", response_model=CaseView)
    def sessions(case_id: Key, value: SessionEdit, user=Depends(writer)):
        with store.connect(write=True) as db:
            row = store.case(db, case_id, expected=value.expected_revision)
            manifest = store.manifest(row)
            if value.session_id is None:
                session = new_session(catalog.version, value.capture_mode, value.route_note)
                manifest.sessions.append(session)
                manifest.selected_session_id = session.session_id
            else:
                if value.session_id not in {item.session_id for item in manifest.sessions}:
                    raise HTTPException(422, "이 참가자의 촬영 세션이 아닙니다.")
                manifest.selected_session_id = value.session_id
            store.save(db, row, manifest, user.username, "session.select")
            return store.view(store.case(db, case_id))

    @app.post("/api/cases/{case_id}/videos", response_model=CaseView, status_code=201)
    async def upload_video(case_id: Key, request: Request,
                           session_id: Key, camera_id: Key,
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
                session.videos.append(StoredVideo(video_id=video_id, camera_id=camera_id,
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
    def video_file(case_id: Key, video_id: Key, user=Depends(reader)):
        with store.connect() as db:
            row = store.case(db, case_id)
            videos = [video for session in store.manifest(row).sessions for video in session.videos]
            video = next((item for item in videos if item.video_id == video_id), None)
            if video is None:
                raise HTTPException(404, "이 참가자의 영상이 아닙니다.")
            path = store.path(video.storage_ref)
            if not path.is_file() or path.stat().st_size != video.size_bytes:
                raise HTTPException(409, "영상 파일이 없거나 크기가 변경되었습니다.")
            with path.open("rb") as handle:
                if hashlib.file_digest(handle, "sha256").hexdigest() != video.sha256:
                    raise HTTPException(409, "영상 파일 해시가 일치하지 않습니다.")
            # Hashing a large file can take time; refresh access immediately before serving.
            store.case(db, case_id)
            return FileResponse(path, filename=f"{video_id}{path.suffix}", content_disposition_type="inline")

    @app.put("/api/cases/{case_id}/sessions/{session_id}", response_model=CaseView)
    def session_metadata(case_id: Key, session_id: Key, value: SessionMetadata, user=Depends(writer)):
        with store.connect(write=True) as db:
            row = store.case(db, case_id, expected=value.expected_revision)
            manifest = store.manifest(row)
            session = selected_session(manifest, session_id)
            session.capture_mode = value.capture_mode
            session.route_note = value.route_note
            if value.checklist is not None:
                session.checklist = value.checklist
            store.save(db, row, manifest, user.username, "session.metadata")
            return store.view(store.case(db, case_id))

    @app.get("/api/templates/{kind}")
    def input_template(kind: Literal["participants", "survey"], format: Literal["csv", "xlsx"] = "csv", user=Depends(writer)):
        return Response(template(kind, format), media_type="application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="kdog-{kind}.{format}"'})

    @app.post("/api/imports/preview", response_model=ImportPreview)
    async def import_preview(request: Request, kind: Literal["participants", "survey"],
                             format: Literal["csv", "xlsx"], mapping: Annotated[str | None, Query(max_length=20000)] = None, user=Depends(writer)):
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 8 * 1024 * 1024:
                raise HTTPException(413, "표준 입력 파일은 8 MiB 이하로 나누어 등록하세요.")
        with store.connect() as db:
            from pydantic import ValidationError
            try:
                layout = ImportMapping.model_validate_json(mapping) if mapping else None
            except ValidationError:
                raise HTTPException(422, "열 연결 형식을 확인하세요.") from None
            return preview(store, db, bytes(data), kind, format, catalog.version, layout)

    @app.post("/api/imports/columns", response_model=ImportColumns)
    async def import_columns(request: Request, format: Literal["csv", "xlsx"], sheet: str | None = None,
                             horizontal: bool = False, user=Depends(writer)):
        from openpyxl.utils.cell import get_column_letter
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 8 * 1024 * 1024:
                raise HTTPException(413, "입력 파일은 8 MiB 이하로 나누어 등록하세요.")
        rows = read_rows(bytes(data), format, sheet)
        if horizontal:
            if len(rows) < 35:
                raise HTTPException(422, "원본 설문 데이터입력 시트를 확인하세요.")
            return {"columns": [{"key": get_column_letter(i + 1), "label": str(rows[4][i] or "이름 없음")} for i in range(5, len(rows[4]))
                if any(i < len(row) and row[i] not in (None, "") for row in rows[5:35])]}
        return {"columns": [{"key": str(value), "label": str(value)} for value in (rows[0] if rows else []) if value is not None]}

    @app.post("/api/imports/commit", response_model=Message)
    def commit_import(value: ImportCommit, user=Depends(writer)):
        with store.connect(write=True) as db:
            for row in value.rows:
                if row.participant is not None and row.survey is None and row.case_id is None:
                    if (row.event_id, row.participant_id) != (row.participant.event_id, row.participant.participant_id):
                        raise HTTPException(422, "미리보기 참가자 연결이 일치하지 않습니다.")
                    create_case(store, db, row.participant, user.username, catalog.version)
                elif row.participant is None and row.survey is not None and row.case_id is not None:
                    current_case = store.case(db, row.case_id)
                    if (row.event_id, row.participant_id) != (current_case["event_id"], current_case["participant_id"]):
                        raise HTTPException(422, "미리보기 참가자 연결이 일치하지 않습니다.")
                    save_survey(store, db, row.case_id, row.survey, user.username, catalog.version)
                else:
                    raise HTTPException(422, "참가자 또는 설문 행을 올바르게 지정하세요.")
        return Message(message=f"{len(value.rows)}개 정상 행을 저장했습니다.")

    @app.get("/api/cases/{case_id}/analysis", response_model=AnalysisView)
    def analysis_status(case_id: Key, user=Depends(reader)):
        return view_analysis(store, case_id)

    @app.post("/api/cases/{case_id}/analysis", response_model=AnalysisView, status_code=202)
    def analysis_start(case_id: Key, value: AnalysisRequest, user=Depends(writer)):
        enqueue(store, case_id, value, user.username)
        return view_analysis(store, case_id)

    @app.post("/api/cases/{case_id}/analysis/{run_id}/{action}", response_model=AnalysisView)
    def analysis_control(case_id: Key, run_id: Key, action: Literal["retry", "cancel"], user=Depends(writer)):
        control(store, case_id, run_id, user.username, action)
        return view_analysis(store, case_id)

    @app.get("/api/cases/{case_id}/analysis/{run_id}/videos/{video_id}")
    def observation_video(case_id: Key, run_id: Key, video_id: Key, user=Depends(reader)):
        with store.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE case_id=? AND run_id=?", (case_id, run_id)).fetchone()
            if not row:
                raise HTTPException(404, "이 참가자의 실행이 아닙니다.")
            check_access(store, db, row)
            step = db.execute("SELECT * FROM steps WHERE run_id=? AND stage='prepare' AND status='succeeded'", (run_id,)).fetchone()
            if not step:
                raise HTTPException(409, "미디어 검사가 완료되지 않았습니다.")
            prepared = validated_prepared(row, step_payload(store, row, step))
            media = next((m for m in prepared.media if m.video_id == video_id), None)
            if not media:
                raise HTTPException(404, "이 실행의 영상이 아닙니다.")
            path = store.path(media.storage_ref)
            with path.open("rb") as handle:
                if hashlib.file_digest(handle, "sha256").hexdigest() != media.sha256:
                    raise HTTPException(409, "재생 영상 해시가 일치하지 않습니다.")
            check_access(store, db, row)
            return FileResponse(path, media_type=media.mime_type, filename=f"{video_id}{path.suffix}", content_disposition_type="inline")

    build = REPO_ROOT / "frontend/dist"
    if build.is_dir():
        app.mount("/", StaticFiles(directory=build, html=True), name="ui")
    return app
