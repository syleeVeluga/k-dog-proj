"""Pinned program-only report runs, explicit content reuse and atomic publication."""
import hashlib
import json
import os
import time
from types import SimpleNamespace
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import Field, field_validator

from . import analysis, disclosures_v4, final_results_v4 as finals, media, opinions_v4 as opinions
from . import comparisons_v4, external_comparisons_v4, report_profile_v4 as profiles, sheets_v4 as sheets, uploads
from .domain.comparisons_v4 import CohortReferenceV4, ExternalReferenceV4
from .domain.final_results_v4 import FinalReferenceV4, FinalResultV4
from .domain.preprocess_v4 import BatchV4, FileV4
from .domain.report_profile_v4 import ReportProfileV4
from .domain.report_render_v4 import ReportHeaderV4, SceneImageV4
from .domain.report_runs_v4 import (REPORT_STAGES, ReportConfigV4, ReportImageV4, ReportInputV4,
    ReportPreparedV4, ReportPublicationV4, ReportRenderedV4, ReportReuseV4, ReportStageV4)
from .domain.sheets_v4 import InputPointerV4
from .domain.media_v4 import MediaKey, StoredMediaV4
from .domain.catalog_v4 import Hash, Text
from .input_models import Model
from .input_models_v4 import ManifestV4
from .storage import REPO_ROOT, encode, now, uid

KIND = "report_v4"
TERMINAL = ("succeeded", "failed", "stopped", "review_required")


class ReportStartV4(Model):
    expected_revision: Annotated[int, Field(ge=1)]
    request_id: MediaKey
    final: FinalReferenceV4
    viewer_sheet_id: MediaKey | None = None
    reuse_run_id: MediaKey | None = None
    comparison: CohortReferenceV4 | None = None
    external_comparison: ExternalReferenceV4 | None = Field(default=None, exclude_if=lambda value: value is None)

    @field_validator("final", mode="before")
    @classmethod
    def contract(cls, value):
        return FinalReferenceV4.model_validate_json(encode(value)) if isinstance(value, dict) else value

    @field_validator("comparison", mode="before")
    @classmethod
    def comparison_contract(cls, value):
        return CohortReferenceV4.model_validate_json(encode(value)) if isinstance(value, dict) else value

    @field_validator("external_comparison", mode="before")
    @classmethod
    def external_contract(cls, value):
        return ExternalReferenceV4.model_validate_json(encode(value)) if isinstance(value, dict) else value


class ReportActionV4(Model):
    expected_updated_at: Text
    reason: Annotated[str, Field(min_length=1, max_length=2000, pattern=r"\S")]


class ReportStepViewV4(Model):
    stage: str
    attempt: int
    status: str
    code: str | None
    timing: dict[str, float]
    reused: bool
    provider_calls: Literal[0] = 0


class ReportRunViewV4(Model):
    run_id: str
    case_id: str
    session_id: str
    input_revision: int
    kind: Literal["report_v4"] = KIND
    status: str
    updated_at: str
    failure_code: str | None
    outdated: bool
    result_available: bool
    is_latest_issued: bool
    publication_state: Literal["issued"] | None
    pending_reasons: list[str]
    normal_publish_available: bool
    final: FinalReferenceV4
    steps: list[ReportStepViewV4]
    external_comparison: ExternalReferenceV4 | None = None
    external_comparison_status: Literal["not_selected", "approved", "blocked"] = "not_selected"
    external_comparison_reason: str | None = None

    @field_validator("final", mode="before")
    @classmethod
    def contract(cls, value):
        return FinalReferenceV4.model_validate_json(encode(value)) if isinstance(value, dict) else value


def config(comparison=None, external_comparison=None):
    from .report_render_v4 import assets
    return ReportConfigV4(stages=tuple(ReportStageV4(stage=name) for name in REPORT_STAGES),
        template_hashes=assets(), content_hashes=profiles.assets()[1], comparison_snapshot=comparison, external_comparison=external_comparison)


def _actor(db, username):
    row = db.execute("SELECT active,role FROM users WHERE username=?", (username,)).fetchone()
    if not row or not row["active"] or row["role"] not in ("operator", "admin"):
        raise HTTPException(403, "활성 리포트 운영 권한이 필요합니다.")
    return SimpleNamespace(username=username, role=row["role"])


def _case(store, db, case_id, session_id, user):
    _actor(db, user.username)
    row = store.case(db, case_id)
    manifest = store.manifest(row)
    if not isinstance(manifest, ManifestV4) or manifest.consents.analysis_feedback != "confirmed":
        raise HTTPException(403, "분석·피드백 동의가 확인된 S1 자료만 리포트를 열 수 있습니다.")
    if not any(session.session_id == session_id for session in manifest.sessions):
        raise HTTPException(404, "이 대상의 촬영 회차가 없습니다.")
    return row, manifest


def _opinion_pin(store, db, case_id, session_id):
    link = opinions.latest(store, db, case_id, session_id)
    return FileV4(ref=link.ref, hash=link.hash) if link else None


def _source_access(store, db, snapshot, user, viewer_sheet_id=None):
    case, manifest = _case(store, db, snapshot.case_id, snapshot.session_id, user)
    basic_row, basic = opinions.selected_basic(store, db, snapshot.case_id, snapshot.session_id,
        snapshot.final_document.basic, user, viewer_sheet_id or snapshot.viewer_sheet_id)
    disclosures_v4.require(db, snapshot.case_id, snapshot.session_id, user,
        disclosures_v4.target("final", snapshot.final), snapshot.final_document.actor)
    if basic != snapshot.final_document.basic_document:
        raise HTTPException(409, "고정한 최종 기본 입력이 변경되었습니다.")
    if _media_files(store, db, snapshot.final_document, user.username) != snapshot.media_sources:
        raise HTTPException(409, "리포트 원본·변환 부모의 고정 연결이 변경되었습니다.")
    if snapshot.cohort and comparisons_v4.for_report(store, snapshot.cohort.reference, user) != snapshot.cohort:
        raise HTTPException(409, "고정한 자체 비교 집단의 출처가 변경되었습니다.")
    if snapshot.profile.external_comparison and external_comparisons_v4.for_output(store,
            snapshot.profile.external_comparison.reference, user) != snapshot.profile.external_comparison:
        raise HTTPException(409, "고정한 외부 비교의 현재 제공 조건이 변경되었습니다.")
    return case, manifest, basic_row


def _media_files(store, db, final, actor):
    files = {}
    for video in final.basic_document.input_document.source.session.videos:
        if not isinstance(video, StoredMediaV4):
            continue
        receipt = uploads._linked_source(store, db, final.case_id, video.video_id, actor)
        if (receipt["storage_ref"], receipt["sha256"]) != (video.storage_ref, video.sha256):
            raise HTTPException(409, "리포트 영상과 수신물이 다릅니다.")
        for row in uploads._lineage(db, receipt).values():
            if row["state"] not in ("complete", "linked"):
                raise HTTPException(409, "취소한 원본·변환 부모는 리포트에 사용할 수 없습니다.")
            files[row["storage_ref"]] = row["sha256"]
    return tuple(FileV4(ref=ref, hash=files[ref]) for ref in sorted(files))


def snapshot_for(row):
    if row["kind"] != KIND:
        raise HTTPException(409, "S1 리포트 실행만 사용할 수 있습니다.")
    snapshot = ReportInputV4.model_validate_json(row["input_snapshot_json"])
    if (row["case_id"], row["session_id"], row["input_revision"], row["input_hash"]) != (
            snapshot.case_id, snapshot.session_id, snapshot.input_revision, analysis.digest(snapshot.model_dump(mode="json"))):
        raise HTTPException(409, "리포트 실행 입력 pin이 다릅니다.")
    if analysis.digest(snapshot.profile.model_dump(mode="json")) != snapshot.profile_hash:
        raise HTTPException(409, "리포트 중간 내용 hash가 다릅니다.")
    return snapshot


def check_access(store, db, row):
    snapshot = snapshot_for(row)
    user = _actor(db, snapshot.requested_by)
    case, _, basic_row = _source_access(store, db, snapshot, user)
    source = sheets.row_for(store, db, snapshot.final_document.basic_document.input.sheet_id)
    if (case["input_revision"], case["manifest_ref"], case["manifest_hash"]) != (
            snapshot.input_revision, snapshot.admission_input.manifest_ref, snapshot.admission_input.manifest_hash):
        raise HTTPException(409, "실행 중 접수·설문 입력이 변경되었습니다. 새 리포트를 생성하세요.")
    if (case["dog_name"], case["guardian_name"], case["participant_id"], case["event_id"]) != (
            snapshot.header.dog_name, snapshot.header.guardian_name, snapshot.header.participant_id, snapshot.header.event_name):
        raise HTTPException(409, "실행 중 리포트 표지 정보가 변경되었습니다.")
    if (basic_row["manifest_ref"], basic_row["manifest_hash"]) != (snapshot.current_basic.ref, snapshot.current_basic.hash) or (
            source["manifest_ref"], source["manifest_hash"]) != (snapshot.source_sheet_head.ref, snapshot.source_sheet_head.hash):
        raise HTTPException(409, "실행 중 기본 판정·원자료가 변경되었습니다.")
    if _opinion_pin(store, db, snapshot.case_id, snapshot.session_id) != snapshot.current_opinion:
        raise HTTPException(409, "실행 중 의견이 수정·철회되었습니다.")
    return snapshot


def _read_file(store, pointer, stamps=None):
    try:
        path = store.path(pointer.ref)
        before = analysis.file_stamp(path)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != pointer.hash or analysis.file_stamp(path) != before:
            raise ValueError("changed file")
        if stamps is not None:
            stamps[pointer.ref] = before
        return data
    except (OSError, ValueError) as exc:
        raise HTTPException(409, "리포트 원본·출력 파일의 hash가 다릅니다.") from exc


def _verify_pointer(store, pointer, stamps):
    try:
        path = store.path(pointer.ref)
        before = analysis.file_stamp(path)
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if digest != pointer.hash or analysis.file_stamp(path) != before:
            raise ValueError("changed source")
        stamps[pointer.ref] = before
    except (OSError, ValueError) as exc:
        raise HTTPException(409, "리포트 원본·부모 참조가 변경되었습니다.") from exc


def check_stamps(store, stamps):
    from .run_v4 import check_stamps as check
    check(store, stamps)


def verify_files(store, snapshot):
    doc = snapshot.final_document.basic_document.input_document
    pointers = [snapshot.final, snapshot.final_document.basic, snapshot.final_document.basic_document.input,
        FileV4(ref=snapshot.admission_input.manifest_ref, hash=snapshot.admission_input.manifest_hash),
        FileV4(ref=doc.source.input.manifest_ref, hash=doc.source.input.manifest_hash), snapshot.current_basic, snapshot.source_sheet_head]
    if snapshot.final_document.opinion:
        pointers.append(snapshot.final_document.opinion)
    if snapshot.current_opinion:
        pointers.append(snapshot.current_opinion)
    if doc.source.preprocess:
        pointers.append(doc.source.preprocess)
        batch = BatchV4.model_validate_json(_read_file(store, doc.source.preprocess))
        pointers.extend(batch.source_files)
        pointers.extend(file for clip in batch.clips for file in (clip.original, clip.ai) if file)
        if batch.reuse_manifest:
            pointers.append(batch.reuse_manifest)
    pointers.extend(FileV4(ref=video.storage_ref, hash=video.sha256) for video in doc.source.session.videos)
    pointers.extend(getattr(snapshot.profile.source, "event_sources", ()))
    pointers.extend(snapshot.media_sources)
    if snapshot.cohort:
        pointers.append(snapshot.cohort.reference)
    if snapshot.profile.external_comparison:
        pointers.extend(external_comparisons_v4.files(store, snapshot.profile.external_comparison.reference))
    stamps = {}
    for pointer in pointers:
        if pointer.ref not in stamps:
            _verify_pointer(store, pointer, stamps)
    if finals.read_document(store, snapshot.final.ref, snapshot.final.hash) != snapshot.final_document:
        raise HTTPException(409, "리포트 최종 결과 snapshot이 원본과 다릅니다.")
    return stamps


def verify_assets(configuration):
    from .report_render_v4 import ASSETS, assets
    survey_policy = profiles.RUNTIME_SURVEY_POLICY_VERSION if "rules/survey-policy-20261007.json" in configuration.content_hashes else profiles.SURVEY_POLICY_VERSION
    names = (*ASSETS, *("resources/"+name for name in profiles.asset_names(survey_policy)))
    stamps = {name: analysis.file_stamp(REPO_ROOT/name) for name in names}
    if configuration.template_hashes != assets() or configuration.content_hashes != profiles.assets(survey_policy)[1]:
        raise HTTPException(409, "실행 중 문장·선택 기준 또는 출력 템플릿이 변경되었습니다.")
    check_asset_stamps(stamps)
    return stamps


def check_asset_stamps(stamps):
    if any(analysis.file_stamp(REPO_ROOT/name) != stamp for name, stamp in stamps.items()):
        raise HTTPException(409, "리포트 채택 직전 문장·출력 템플릿이 변경되었습니다.")


def compatibility(snapshot, configuration):
    data = snapshot.model_dump(mode="json")
    data.pop("requested_by"); data.pop("viewer_sheet_id")
    data["header"].pop("generated_at")
    return analysis.digest({"input": data, "config": configuration.model_dump(mode="json")})


def reuse_for(store, db, source_id, snapshot, configuration):
    source = db.execute("SELECT * FROM runs WHERE run_id=? AND kind=?", (source_id, KIND)).fetchone()
    if not source or source["case_id"] != snapshot.case_id or source["session_id"] != snapshot.session_id:
        raise HTTPException(409, "같은 대상·회차의 S1 리포트 내용만 재사용할 수 있습니다.")
    old = snapshot_for(source)
    old_config = ReportConfigV4.model_validate_json(source["config_snapshot_json"])
    expected = compatibility(snapshot, configuration)
    if compatibility(old, old_config) != expected:
        raise HTTPException(409, "리포트 재사용 입력·설정·출처가 다릅니다.")
    step = db.execute("SELECT * FROM steps WHERE run_id=? AND stage='content_v4' AND status='succeeded' ORDER BY attempt DESC LIMIT 1", (source_id,)).fetchone()
    if not step:
        raise HTTPException(409, "재사용할 성공 내용 단계가 없습니다.")
    payload = analysis.step_payload(store, source, step)
    prepared = ReportPreparedV4.model_validate_json(encode(payload["prepared"]))
    validate_prepared(store, snapshot, prepared)
    return ReportReuseV4(source_run_id=source_id, step_id=step["step_id"], ref=step["output_ref"], hash=step["output_hash"], compatibility_hash=expected)


def enqueue(store, case_id, session_id, value: ReportStartV4, user):
    value = ReportStartV4.model_validate_json(value.model_dump_json())
    request_hash = analysis.digest({"request": value.model_dump(mode="json"), "actor": user.username})
    with store.connect() as db:
        case, manifest = _case(store, db, case_id, session_id, user)
        previous = db.execute("SELECT * FROM runs WHERE case_id=? AND session_id=? AND kind=? AND request_id=?",
            (case_id, session_id, KIND, value.request_id)).fetchone()
        if previous:
            if previous["request_hash"] != request_hash:
                raise HTTPException(409, "같은 요청 ID에 다른 리포트 입력을 사용할 수 없습니다.")
            _source_access(store, db, snapshot_for(previous), user, value.viewer_sheet_id)
            return view(store, previous["run_id"], user, value.viewer_sheet_id)
        store.case(db, case_id, expected=value.expected_revision)
        opinion_pin = _opinion_pin(store, db, case_id, session_id)
    shown = finals.view(store, case_id, session_id, value.final.final_id, user, value.viewer_sheet_id)
    if FinalReferenceV4.model_validate_json(encode(shown["reference"])) != value.final:
        raise HTTPException(409, "리포트로 선택한 최종 결과 pin이 다릅니다.")
    final = FinalResultV4.model_validate_json(encode(shown["document"]))
    profile = profiles.from_final(store, case_id, session_id, value.final.final_id, user, value.viewer_sheet_id)
    cohort = comparisons_v4.for_report(store, value.comparison, user) if value.comparison else None
    if value.external_comparison:
        external = external_comparisons_v4.for_output(store, value.external_comparison, user)
        source = final.basic_document.input_document.source
        if (external.target.case_id, external.target.session_id, external.target.expected_revision, external.target.input) != (
                case_id, session_id, source.input_revision, source.input):
            raise HTTPException(409, "외부 비교와 최종 결과의 설문 원입력 판본이 다릅니다.")
        profile = type(profile).model_validate_json(encode({**profile.model_dump(mode="json"),
            "external_comparison": external.model_dump(mode="json"), "external_comparison_status": "approved_selected"}))
    configuration = config(value.comparison, value.external_comparison)
    with store.connect() as db:
        basic_row, _ = opinions.selected_basic(store, db, case_id, session_id, final.basic, user, value.viewer_sheet_id)
        source_row = sheets.row_for(store, db, final.basic_document.input.sheet_id)
        media_sources = _media_files(store, db, final, user.username)
    header = ReportHeaderV4(dog_name=case["dog_name"], guardian_name=case["guardian_name"], participant_id=manifest.participant_id,
        event_name=manifest.event_id, observed_date="", generated_at=now(), preview=False)
    snapshot = ReportInputV4(case_id=case_id, session_id=session_id, input_revision=case["input_revision"],
        admission_input=InputPointerV4(manifest_ref=case["manifest_ref"], manifest_hash=case["manifest_hash"]), requested_by=user.username,
        viewer_sheet_id=value.viewer_sheet_id, final=value.final, final_document=final, profile=profile,
        profile_hash=analysis.digest(profile.model_dump(mode="json")), header=header, current_opinion=opinion_pin,
        current_basic=FileV4(ref=basic_row["manifest_ref"], hash=basic_row["manifest_hash"]),
        source_sheet_head=FileV4(ref=source_row["manifest_ref"], hash=source_row["manifest_hash"]), media_sources=media_sources, cohort=cohort)
    asset_identities = verify_assets(configuration)
    stamps = verify_files(store, snapshot)
    with store.connect() as db:
        reuse = reuse_for(store, db, value.reuse_run_id, snapshot, configuration) if value.reuse_run_id else None
    if reuse:
        _verify_pointer(store, reuse, stamps)
    with store.connect(write=True) as db:
        _case(store, db, case_id, session_id, user)
        store.case(db, case_id, expected=value.expected_revision)
        check_stamps(store, stamps)
        check_asset_stamps(asset_identities)
        previous = db.execute("SELECT * FROM runs WHERE case_id=? AND session_id=? AND kind=? AND request_id=?",
            (case_id, session_id, KIND, value.request_id)).fetchone()
        if previous:
            if previous["request_hash"] != request_hash:
                raise HTTPException(409, "같은 요청 ID의 리포트 입력이 다릅니다.")
            run_id = previous["run_id"]
        else:
            run_id = uid()
            db.execute("INSERT INTO runs(run_id,case_id,session_id,input_revision,input_snapshot_json,config_snapshot_json,reuse_manifest_json,"
                "status,created_at,updated_at,kind,request_id,request_hash,input_hash) VALUES(?,?,?,?,?,?,?,'queued',?,?,?,?,?,?)",
                (run_id, case_id, session_id, case["input_revision"], snapshot.model_dump_json(), configuration.model_dump_json(),
                    encode([reuse.model_dump(mode="json")] if reuse else []), now(), now(), KIND, value.request_id, request_hash,
                    analysis.digest(snapshot.model_dump(mode="json"))))
            check_access(store, db, db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone())
            store.audit(db, user.username, run_id, "report.s1.create", {"request_id": value.request_id, "final": value.final.model_dump(mode="json")})
    return view(store, run_id, user, value.viewer_sheet_id)


def _write_bytes(store, ref, data):
    path = store.path(ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(uid()+".tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return FileV4(ref=ref, hash=hashlib.sha256(data).hexdigest())


def capture_images(store, snapshot, run_id, step_id, guard):
    """Select an actual original frame index whose PTS lies inside approved evidence."""
    source = snapshot.final_document.basic_document.input_document.source
    videos = {video.video_id: video for video in source.session.videos}
    frame_cache, images, issues = {}, [], {}
    stamps = verify_files(store, snapshot)
    for scene in snapshot.profile.scenes:
        guard()
        selected = None
        for evidence in scene.evidence:
            video = videos.get(evidence.video_id)
            if video is None or video.sha256 != evidence.video_sha256 or getattr(video, "camera_id", None) != evidence.camera_id:
                raise HTTPException(409, "선택 장면의 원본·카메라가 고정 입력과 다릅니다.")
            if video.video_id not in frame_cache:
                raw = json.loads(media.command(["ffprobe", "-v", "error", *media.LOCAL_INPUT, "-select_streams", "v:0",
                    "-show_frames", "-show_format", "-show_entries", "frame=best_effort_timestamp_time:format=start_time", "-of", "json",
                    str(store.path(video.storage_ref))], timeout=1800))
                origin = float(raw.get("format", {}).get("start_time", 0))
                frame_cache[video.video_id] = tuple((index, float(frame["best_effort_timestamp_time"])-origin)
                    for index, frame in enumerate(raw.get("frames", [])) if "best_effort_timestamp_time" in frame)
            candidates = [(index, pts) for index, pts in frame_cache[video.video_id]
                if evidence.start_seconds <= pts < evidence.end_seconds and pts >= 0]
            if candidates:
                index, pts = min(candidates, key=lambda item: (abs(item[1]-(evidence.start_seconds+evidence.end_seconds)/2), item[1]))
                selected = video, evidence, index, pts
                break
        if selected is None:
            issues[scene.scene_id] = "선택한 실제 관찰 범위 안에 확인된 원본 프레임이 없습니다."
            continue
        video, evidence, index, pts = selected
        ref = f"runs/{run_id}/{step_id}/scene-{len(images)+1}.png"
        path = store.path(ref); path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(uid()+".png")
        try:
            guard(); check_stamps(store, stamps)
            media.command(["ffmpeg", "-v", "error", "-nostdin", "-n", *media.LOCAL_INPUT, "-i", str(store.path(video.storage_ref)),
                "-map", "0:v:0", "-vf", f"select=eq(n\\,{index}),scale=960:960:force_original_aspect_ratio=decrease", "-fps_mode", "vfr",
                "-frames:v", "1", "-update", "1", str(temporary)], timeout=180)
            data = temporary.read_bytes()
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("invalid extracted frame")
            guard(); check_stamps(store, stamps)
            pointer = _write_bytes(store, ref, data)
            images.append(ReportImageV4(scene_id=scene.scene_id, video_id=video.video_id, video_sha256=video.sha256,
                camera_id=evidence.camera_id, source_seconds=pts, file=pointer))
        finally:
            temporary.unlink(missing_ok=True)
    return tuple(images), issues


def _image_stamps(store, images, *, profile=None):
    stamps = {}
    if len({image.scene_id for image in images}) != len(images):
        raise ValueError("duplicate scene image")
    scenes = {scene.scene_id: scene for scene in profile.scenes} if profile else {}
    for image in images:
        raw = _read_file(store, image.file, stamps)
        if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("image format")
        if profile:
            scene = scenes.get(image.scene_id)
            if not scene or not any((basis.video_id, basis.video_sha256, basis.camera_id) == (
                    image.video_id, image.video_sha256, image.camera_id) and basis.start_seconds <= image.source_seconds < basis.end_seconds
                    for basis in scene.evidence):
                raise ValueError("image lacks exact scene evidence")
    return stamps


def validate_prepared(store, snapshot, prepared):
    if prepared.profile != snapshot.profile or prepared.profile_hash != snapshot.profile_hash:
        raise ValueError("report content differs from pinned profile")
    if {image.scene_id for image in prepared.images} | set(prepared.image_issues) != {scene.scene_id for scene in snapshot.profile.scenes}:
        raise ValueError("each scene must preserve an image or explicit missing reason")
    if {image.scene_id for image in prepared.images} & set(prepared.image_issues):
        raise ValueError("scene image cannot be both present and missing")
    _image_stamps(store, prepared.images, profile=prepared.profile)
    return prepared


def validate_rendered(store, rendered):
    stamps = _image_stamps(store, rendered.images)
    html = _read_file(store, rendered.html, stamps)
    pdf = _read_file(store, rendered.pdf, stamps)
    if b"<html" not in html.lower() or b"</html>" not in html.lower() or not pdf.startswith(b"%PDF-") or not pdf.rstrip().endswith(b"%%EOF"):
        raise ValueError("report output format is invalid")
    return stamps


def output_stamps(store, stage, payload):
    stamps = {}
    if stage in ("content_v4", "validate_content_v4"):
        prepared = ReportPreparedV4.model_validate_json(encode(payload["prepared"]))
        stamps.update(_image_stamps(store, prepared.images, profile=prepared.profile))
    elif stage in ("render_v4", "validate_output_v4"):
        rendered = ReportRenderedV4.model_validate_json(encode(payload["rendered"]))
        stamps.update(validate_rendered(store, rendered))
    elif stage == "publish_report_v4":
        pointer = FileV4.model_validate_json(encode(payload["publication"]))
        publication = ReportPublicationV4.model_validate_json(_read_file(store, pointer, stamps))
        stamps.update(validate_rendered(store, publication.output))
    else:
        raise ValueError("unknown report stage")
    return stamps


def render_report(profile, header, images, *, cohort=None):
    """Narrow pure-renderer seam; tests inject bytes without a provider or network."""
    from .report_render_v4 import render_html
    from .report_pdf_v4 import render_pdf
    options = {"cohort": cohort} if cohort else {}
    return render_html(profile, header, images=images, **options), render_pdf(profile, header, images=images, **options)


def _stage_payload(store, row, stage):
    with store.connect() as db:
        step = db.execute("SELECT * FROM steps WHERE run_id=? AND stage=? AND status='succeeded' ORDER BY attempt DESC LIMIT 1", (row["run_id"], stage)).fetchone()
    if not step:
        raise HTTPException(409, "리포트의 앞선 검증 단계가 완료되지 않았습니다.")
    return analysis.step_payload(store, row, step)


def process(worker, row):
    snapshot = snapshot_for(row)
    configuration = ReportConfigV4.model_validate_json(row["config_snapshot_json"])
    if configuration.comparison_snapshot != (snapshot.cohort.reference if snapshot.cohort else None):
        raise ValueError("cohort input and configuration pins differ")
    if configuration.external_comparison != (snapshot.profile.external_comparison.reference if snapshot.profile.external_comparison else None):
        raise ValueError("external comparison input and configuration pins differ")
    worker.check(row); verify_assets(configuration); verify_files(worker.store, snapshot)
    reuses = [ReportReuseV4.model_validate_json(encode(entry)) for entry in json.loads(row["reuse_manifest_json"])]
    if len(reuses) > 1:
        raise ValueError("report reuses only one explicit content stage")
    for group in configuration.stages:
        stage = group.stage
        worker.check(row)
        def validate(payload, stage=stage):
            verify_assets(configuration)
            if stage in ("content_v4", "validate_content_v4"):
                prepared = ReportPreparedV4.model_validate_json(encode(payload["prepared"]))
                validate_prepared(worker.store, snapshot, prepared)
                if stage == "validate_content_v4" and any(issue.blocking for issue in prepared.profile.validation_issues):
                    raise ValueError("blocking report content issue")
            elif stage in ("render_v4", "validate_output_v4"):
                rendered = ReportRenderedV4.model_validate_json(encode(payload["rendered"]))
                if rendered.profile_hash != snapshot.profile_hash or rendered.header_hash != analysis.digest(snapshot.header.model_dump(mode="json")):
                    raise ValueError("rendered input mismatch")
                prepared = ReportPreparedV4.model_validate_json(encode(_stage_payload(worker.store, row, "validate_content_v4")["prepared"]))
                if (rendered.images, rendered.image_issues) != (prepared.images, prepared.image_issues):
                    raise ValueError("rendered scene evidence differs from validated content")
                if stage == "validate_output_v4" and rendered != ReportRenderedV4.model_validate_json(encode(_stage_payload(worker.store, row, "render_v4")["rendered"])):
                    raise ValueError("output validation differs from rendered files")
                validate_rendered(worker.store, rendered)
            else:
                pointer = FileV4.model_validate_json(encode(payload["publication"]))
                publication = ReportPublicationV4.model_validate_json(_read_file(worker.store, pointer))
                if (publication.run_id, publication.case_id, publication.session_id, publication.input_hash, publication.config_hash,
                        publication.final, publication.header, publication.profile, publication.cohort) != (
                        row["run_id"], snapshot.case_id, snapshot.session_id, row["input_hash"], analysis.digest(configuration.model_dump(mode="json")),
                        snapshot.final, snapshot.header, snapshot.profile, snapshot.cohort):
                    raise ValueError("publication snapshot mismatch")
                if publication.output != ReportRenderedV4.model_validate_json(encode(_stage_payload(worker.store, row, "validate_output_v4")["rendered"])):
                    raise ValueError("publication differs from validated output")
                validate_rendered(worker.store, publication.output)
            return payload

        def work(step, stage=stage):
            started = time.monotonic()
            worker.check(row); verify_assets(configuration); verify_files(worker.store, snapshot)
            if stage == "content_v4":
                if reuses:
                    with worker.store.connect() as db:
                        exact = reuse_for(worker.store, db, reuses[0].source_run_id, snapshot, configuration)
                        if exact != reuses[0]:
                            raise HTTPException(409, "명시한 재사용 내용 단계가 변경되었습니다.")
                        source = db.execute("SELECT * FROM runs WHERE run_id=?", (exact.source_run_id,)).fetchone()
                        old_step = db.execute("SELECT * FROM steps WHERE step_id=?", (exact.step_id,)).fetchone()
                        payload = analysis.step_payload(worker.store, source, old_step)
                    payload["usage"] = {"program_merge": True, "reused": True, "source_run_id": exact.source_run_id}
                else:
                    images, issues = capture_images(worker.store, snapshot, row["run_id"], step["step_id"], lambda: worker.check(row))
                    prepared = ReportPreparedV4(profile=snapshot.profile, profile_hash=snapshot.profile_hash, images=images, image_issues=issues)
                    payload = {"prepared": prepared.model_dump(mode="json")}
            elif stage == "validate_content_v4":
                payload = _stage_payload(worker.store, row, "content_v4")
                if snapshot.profile.status == "review_required" or any(issue.blocking for issue in snapshot.profile.validation_issues):
                    raise ValueError("blocking report content requires review")
                payload = {"prepared": payload["prepared"]}
            elif stage == "render_v4":
                prepared = ReportPreparedV4.model_validate_json(encode(_stage_payload(worker.store, row, "validate_content_v4")["prepared"]))
                images = tuple(SceneImageV4(scene_id=image.scene_id, video_id=image.video_id, video_sha256=image.video_sha256,
                    camera_id=image.camera_id, source_seconds=image.source_seconds, image_sha256=image.file.hash,
                    mime=image.mime, data=_read_file(worker.store, image.file)) for image in prepared.images)
                html, pdf = render_report(prepared.profile, snapshot.header, images, **({"cohort": snapshot.cohort} if snapshot.cohort else {}))
                prefix = f"runs/{row['run_id']}/{step['step_id']}"
                rendered = ReportRenderedV4(profile_hash=snapshot.profile_hash, header_hash=analysis.digest(snapshot.header.model_dump(mode="json")),
                    html=_write_bytes(worker.store, prefix+"/report.html", html), pdf=_write_bytes(worker.store, prefix+"/report.pdf", pdf),
                    images=prepared.images, image_issues=prepared.image_issues)
                payload = {"rendered": rendered.model_dump(mode="json")}
            elif stage == "validate_output_v4":
                rendered = ReportRenderedV4.model_validate_json(encode(_stage_payload(worker.store, row, "render_v4")["rendered"]))
                validate_rendered(worker.store, rendered)
                payload = {"rendered": rendered.model_dump(mode="json")}
            else:
                rendered = ReportRenderedV4.model_validate_json(encode(_stage_payload(worker.store, row, "validate_output_v4")["rendered"]))
                publication = ReportPublicationV4(report_id=row["run_id"], case_id=snapshot.case_id, session_id=snapshot.session_id,
                    run_id=row["run_id"], input_hash=row["input_hash"], config_hash=analysis.digest(configuration.model_dump(mode="json")),
                    final=snapshot.final, input_revision=snapshot.input_revision, header=snapshot.header, profile=snapshot.profile,
                    output=rendered, cohort=snapshot.cohort, created_at=now())
                pointer = _write_bytes(worker.store, f"runs/{row['run_id']}/{step['step_id']}/report.json", publication.model_dump_json().encode())
                payload = {"publication": pointer.model_dump(mode="json")}
            payload.setdefault("usage", {}).update(program_merge=True, timing={"stage_seconds": time.monotonic()-started})
            return payload
        result = worker.stage(row, stage, group.key, validate, work)
        if result is None:
            held = stage == "validate_content_v4" and (snapshot.profile.status == "review_required" or any(issue.blocking for issue in snapshot.profile.validation_issues))
            finish(worker, row, "review_required" if held else "failed", "report_content_review_required" if held else "report_stage_failed")
            return
    publication = FileV4.model_validate_json(encode(_stage_payload(worker.store, row, "publish_report_v4")["publication"]))
    stamps = verify_files(worker.store, snapshot)
    stamps.update(output_stamps(worker.store, "publish_report_v4", {"publication": publication.model_dump(mode="json")}))
    finish(worker, row, "succeeded", None, publication=publication, stamps=stamps)


def finish(worker, row, status, code, *, publication=None, stamps=None):
    worker.check(row)
    asset_identities = verify_assets(ReportConfigV4.model_validate_json(row["config_snapshot_json"]))
    with worker.store.connect(write=True) as db:
        current = db.execute("SELECT * FROM runs WHERE run_id=?", (row["run_id"],)).fetchone()
        if not current or current["claim_token"] != row["claim_token"] or current["status"] != "running" or current["lease_expires_at"] <= now():
            raise HTTPException(409, "오래된 리포트 실행은 게시할 수 없습니다.")
        check_access(worker.store, db, current)
        if stamps:
            check_stamps(worker.store, stamps)
        check_asset_stamps(asset_identities)
        db.execute("UPDATE runs SET status=?,failure_code=?,result_ref=?,result_hash=?,claim_token=NULL,lease_expires_at=NULL,updated_at=? WHERE run_id=?",
            (status, code, publication.ref if publication else None, publication.hash if publication else None, now(), row["run_id"]))
        if publication:
            worker.store.audit(db, snapshot_for(current).requested_by, row["run_id"], "report.s1.issue", {"ref": publication.ref, "hash": publication.hash})


def row_for(store, db, run_id):
    row = db.execute("SELECT * FROM runs WHERE run_id=? AND kind=?", (run_id, KIND)).fetchone()
    if not row:
        raise HTTPException(404, "S1 리포트 실행이 없습니다.")
    store.case(db, row["case_id"])
    return row


def _outdated(store, db, row, snapshot, case):
    basic = db.execute("SELECT manifest_ref,manifest_hash FROM basic_results WHERE result_id=?", (snapshot.final_document.basic.result_id,)).fetchone()
    source = db.execute("SELECT manifest_ref,manifest_hash FROM score_sheets WHERE sheet_id=?", (snapshot.final_document.basic_document.input.sheet_id,)).fetchone()
    configuration = ReportConfigV4.model_validate_json(row["config_snapshot_json"])
    try:
        verify_assets(configuration)
        assets_changed = configuration.content_hashes != profiles.assets()[1]
    except (HTTPException, OSError, ValueError):
        assets_changed = True
    return (case["input_revision"] != snapshot.input_revision or case["selected_session_id"] != snapshot.session_id
        or snapshot.final_document.basic_document.input_document.source.input_revision != case["input_revision"]
        or not basic or tuple(basic) != (snapshot.final_document.basic.ref, snapshot.final_document.basic.hash)
        or not source or tuple(source) != (snapshot.source_sheet_head.ref, snapshot.source_sheet_head.hash)
        or _opinion_pin(store, db, snapshot.case_id, snapshot.session_id) != snapshot.current_opinion
        or (case["dog_name"], case["guardian_name"]) != (snapshot.header.dog_name, snapshot.header.guardian_name) or assets_changed)


def view(store, run_id, user, viewer_sheet_id=None):
    with store.connect() as db:
        row = row_for(store, db, run_id)
        snapshot = snapshot_for(row)
        case, _ = _case(store, db, row["case_id"], row["session_id"], user)
        latest = db.execute("SELECT run_id FROM runs WHERE case_id=? AND session_id=? AND kind=? AND status='succeeded' AND result_ref IS NOT NULL ORDER BY created_at DESC,run_id DESC LIMIT 1",
            (row["case_id"], row["session_id"], KIND)).fetchone()
        steps = []
        for step in db.execute("SELECT * FROM steps WHERE run_id=? ORDER BY created_at,attempt", (run_id,)):
            usage = json.loads(step["usage_json"])
            steps.append({"stage": step["stage"], "attempt": step["attempt"], "status": step["status"], "code": usage.get("code"),
                "timing": {key: value for key, value in usage.get("timing", {}).items() if type(value) in (int, float)}, "reused": bool(usage.get("reused")), "provider_calls": 0})
        external_status,external_reason="not_selected",None
        external=snapshot.profile.external_comparison
        if external:
            try:
                if external_comparisons_v4.for_output(store,external.reference,user)!=external:
                    raise HTTPException(409,"외부 비교의 고정 승인 범위가 변경되었습니다.")
                external_status="approved"
            except HTTPException as exc:
                if exc.status_code in (401,403):raise
                external_status,external_reason="blocked",str(exc.detail)
        available=bool(row["result_ref"]) and external_status!="blocked"
        return {"run_id": run_id, "case_id": row["case_id"], "session_id": row["session_id"], "kind": KIND,
            "input_revision": row["input_revision"], "status": row["status"], "updated_at": row["updated_at"], "failure_code": row["failure_code"],
            "outdated": _outdated(store, db, row, snapshot, case), "result_available": available,
            "is_latest_issued": bool(latest and latest["run_id"] == run_id), "publication_state": "issued" if row["result_ref"] else None,
            "pending_reasons": ["G02"], "normal_publish_available": row["status"] == "succeeded" and available,
            "final": snapshot.final.model_dump(mode="json"), "steps": steps,
            "external_comparison":external.reference.model_dump(mode="json") if external else None,
            "external_comparison_status":external_status,"external_comparison_reason":external_reason}


def list_runs(store, case_id, session_id, user):
    with store.connect() as db:
        _case(store, db, case_id, session_id, user)
        ids = [row[0] for row in db.execute("SELECT run_id FROM runs WHERE case_id=? AND session_id=? AND kind=? ORDER BY created_at DESC,run_id DESC", (case_id, session_id, KIND))]
    return [view(store, run_id, user) for run_id in ids]


def purge_comparisons(db, snapshot_ids):
    """Remove dependent report references when a cohort member's data is deleted."""
    revoked = set(snapshot_ids)
    run_ids = set()
    for row in db.execute("SELECT run_id,input_snapshot_json FROM runs WHERE kind=?", (KIND,)):
        cohort = json.loads(row["input_snapshot_json"]).get("cohort")
        if cohort and cohort["reference"]["snapshot_id"] in revoked:
            run_ids.add(row["run_id"])
    for run_id in run_ids:
        db.execute("DELETE FROM steps WHERE run_id=?", (run_id,))
        db.execute("DELETE FROM changes WHERE target=?", (run_id,))
        db.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
    return run_ids


def purge_external(db, snapshot_ids):
    revoked = set(snapshot_ids)
    run_ids = set()
    for row in db.execute("SELECT run_id,input_snapshot_json FROM runs WHERE kind=?", (KIND,)):
        external = json.loads(row["input_snapshot_json"]).get("profile", {}).get("external_comparison")
        if external and external["reference"]["snapshot_id"] in revoked:
            run_ids.add(row["run_id"])
    for run_id in run_ids:
        db.execute("DELETE FROM steps WHERE run_id=?", (run_id,))
        db.execute("DELETE FROM changes WHERE target=?", (run_id,))
        db.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
    return run_ids


def action(store, run_id, value: ReportActionV4, user, *, retry=False):
    value = ReportActionV4.model_validate(value)
    with store.connect(write=True) as db:
        row = row_for(store, db, run_id)
        snapshot = snapshot_for(row)
        _source_access(store, db, snapshot, user)
        if row["updated_at"] != value.expected_updated_at:
            raise HTTPException(409, "리포트 실행 상태가 변경되었습니다.")
        if retry:
            check_access(store, db, row)
            if row["status"] not in ("failed", "stopped"):
                raise HTTPException(409, "실패·중지 실행만 고정 입력으로 재시도할 수 있습니다.")
        elif row["status"] in TERMINAL:
            raise HTTPException(409, "이미 종료된 리포트 실행입니다.")
        db.execute("UPDATE runs SET status=?,failure_code=NULL,claim_token=NULL,lease_expires_at=NULL,updated_at=? WHERE run_id=?",
            ("queued" if retry else "stopped", now(), run_id))
        store.audit(db, user.username, run_id, "report.s1.retry" if retry else "report.s1.stop", {"reason": value.reason})
    return view(store, run_id, user)


def download(store, case_id, session_id, run_id, format, user, viewer_sheet_id=None):
    if format not in ("html", "pdf", "manifest"):
        raise HTTPException(404, "지원하는 리포트 출력 형식이 아닙니다.")
    with store.connect() as db:
        row = row_for(store, db, run_id)
        if (row["case_id"], row["session_id"]) != (case_id, session_id):
            raise HTTPException(404, "이 대상·회차의 리포트가 아닙니다.")
        snapshot = snapshot_for(row)
        _source_access(store, db, snapshot, user, viewer_sheet_id)
        if row["status"] != "succeeded" or not row["result_ref"]:
            raise HTTPException(409, "검증을 마친 리포트 발급본이 아직 없습니다.")
    stamps = verify_files(store, snapshot)
    pointer = FileV4(ref=row["result_ref"], hash=row["result_hash"])
    raw = _read_file(store, pointer, stamps)
    publication = ReportPublicationV4.model_validate_json(raw)
    configuration = ReportConfigV4.model_validate_json(row["config_snapshot_json"])
    if (publication.run_id, publication.case_id, publication.session_id, publication.input_revision, publication.input_hash,
            publication.config_hash, publication.final, publication.profile, publication.header, publication.cohort) != (
            run_id, case_id, session_id, snapshot.input_revision, row["input_hash"], analysis.digest(configuration.model_dump(mode="json")),
            snapshot.final, snapshot.profile, snapshot.header, snapshot.cohort):
        raise HTTPException(409, "리포트 발급본의 고정 입력이 다릅니다.")
    stamps.update(validate_rendered(store, publication.output))
    data = raw if format == "manifest" else _read_file(store, getattr(publication.output, format), stamps)
    with store.connect() as db:
        current = row_for(store, db, run_id)
        _source_access(store, db, snapshot, user, viewer_sheet_id)
        if (current["result_ref"], current["result_hash"]) != (pointer.ref, pointer.hash):
            raise HTTPException(409, "다운로드 중 발급 참조가 변경되었습니다.")
        check_stamps(store, stamps)
    return data, {"html":"text/html; charset=utf-8", "pdf":"application/pdf", "manifest":"application/json"}[format], f"kdog-s1-{run_id}.{'json' if format == 'manifest' else format}"
