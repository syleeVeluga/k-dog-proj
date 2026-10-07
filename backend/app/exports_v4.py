"""Pinned S1 research tables; no legacy-score restoration or aggregate accuracy claim."""
import csv
import hashlib
from io import BytesIO, StringIO
import json
from typing import Literal
from zipfile import ZipFile, ZIP_DEFLATED

from fastapi import HTTPException
from openpyxl import Workbook
from pydantic import Field, field_validator

from . import analysis, comparisons_v4, disclosures_v4, external_comparisons_v4, final_results_v4 as finals, judgements_v4 as basics
from . import opinions_v4 as opinions, report_runs_v4 as reports, sheets_v4 as sheets, uploads, validation_data_v4 as validation
from .domain.catalog_v4 import RESOURCES, load_catalog_v4
from .domain.catalog_v3 import SurveyCatalogV3
from .domain.comparisons_v4 import CohortReferenceV4, ExternalReferenceV4
from .domain.exports_v4 import ExportMemberV4, ExportSelectionV4, ExportSnapshotV4
from .domain.final_results_v4 import FinalResultV4
from .domain.media_v4 import MediaKey, StoredMediaV4
from .domain.preprocess_v4 import BatchV4, FileV4
from .domain.report_runs_v4 import ReportPublicationV4
from .domain.sheets_v4 import SheetReferenceV4
from .domain.validation_data_v4 import ValidationReferenceV4
from .input_models import Model
from .input_models_v4 import ManifestV4
from .storage import encode, now, uid
from .survey_v4 import survey_scores_v4

ACTION = "export.s1.issue"
ASSETS = ("catalogs/behavior-v4.json", "catalogs/survey-v3.json", "rules/survey-policy-20261007.json")


def _assets():
    return {name:hashlib.sha256((RESOURCES/name).read_bytes()).hexdigest() for name in ASSETS}


class ExportCreateV4(Model):
    request_id: MediaKey
    format: Literal["csv_zip", "xlsx"]
    members: list[ExportSelectionV4] = Field(min_length=1, max_length=100)
    references: list[ValidationReferenceV4] = Field(default_factory=list, max_length=100)
    comparison: CohortReferenceV4 | None = None
    external_comparisons: list[ExternalReferenceV4] = Field(default_factory=list, max_length=100, exclude_if=lambda value: not value)
    redact_terms: list[str] = Field(default_factory=list, max_length=200)
    reason: str = Field(min_length=1, max_length=4000, pattern=r"\S")

    @field_validator("members", "references", "external_comparisons", mode="before")
    @classmethod
    def lists(cls, value, info):
        kind = {"members": ExportSelectionV4, "references": ValidationReferenceV4, "external_comparisons": ExternalReferenceV4}[info.field_name]
        return [kind.model_validate_json(encode(item)) if isinstance(item, dict) else item for item in value]

    @field_validator("comparison", mode="before")
    @classmethod
    def pointer(cls, value):
        return CohortReferenceV4.model_validate_json(encode(value)) if isinstance(value, dict) else value


class ExportViewV4(Model):
    export_id: str
    format: Literal["csv_zip", "xlsx"]
    created_at: str
    member_count: int
    excluded_count: int
    snapshot_sha256: str
    output_sha256: str
    status: Literal["ready"]


class ExportBlockedV4(Model):
    export_id: str
    status: Literal["blocked"] = "blocked"
    reason: str


ExportHistoryV4 = ExportViewV4 | ExportBlockedV4


def _case(store, db, selection, user):
    sheets.manager(user, db)
    case = store.case(db, selection.case_id)
    manifest = store.manifest(case)
    if not isinstance(manifest, ManifestV4) or not any(item.session_id == selection.session_id for item in manifest.sessions):
        raise HTTPException(404, "선택한 S1 대상·회차가 없습니다.")
    return case, manifest


def _sheet(store, db, selection, user):
    row = sheets.row_for(store, db, selection.sheet.sheet_id)
    if (row["case_id"], row["session_id"]) != (selection.case_id, selection.session_id):
        raise HTTPException(409, "연구 선택 시트의 대상·회차가 다릅니다.")
    current = sheets.document_for(store, row)
    links = [SheetReferenceV4.model_validate_json(encode(sheets.reference(row))), *current.previous]
    if selection.sheet not in links:
        raise HTTPException(409, "보존한 연구 원자료 revision/hash와 다릅니다.")
    doc = sheets.read_document(store, selection.sheet.ref, selection.sheet.hash)
    if not row["active"]:
        raise HTTPException(403, "취소된 평가 배정은 내보낼 수 없습니다.")
    if row["assigned_username"] == user.username:
        sheets.owner(db, row, user)
    else:
        if not selection.viewer_sheet_id:
            raise HTTPException(403, "다른 평가 원본은 실제 공개한 본인 시트를 지정하세요.")
        viewer = sheets.row_for(store, db, selection.viewer_sheet_id)
        sheets.owner(db, viewer, user)
        shown = sheets.document_for(store, viewer)
        exposed, _ = sheets.related_exposure(store, db, viewer, shown)
        exposed.update({item.ref:item.model_dump(mode="json") for item in shown.exposures})
        grant = db.execute("SELECT * FROM score_grants WHERE viewer_sheet_id=? AND ref=?", (viewer["sheet_id"], selection.sheet.ref)).fetchone()
        if (shown.state != "submitted" or shown.source_hash != doc.source_hash or exposed.get(selection.sheet.ref) != selection.sheet.model_dump(mode="json")
                or not grant or grant["hash"] != selection.sheet.hash or grant["target_sheet_id"] != selection.sheet.sheet_id):
            raise HTTPException(403, "내보낼 원자료 판본의 공개 배정과 실제 노출 이력이 필요합니다.")
    return doc


def _member(store, selection, user):
    with store.connect() as db:
        case, manifest = _case(store, db, selection, user)
        doc = _sheet(store, db, selection, user)
        for video in doc.source.session.videos:
            if isinstance(video,StoredMediaV4):uploads._linked_source(store,db,selection.case_id,video.video_id,user.username)
        if not case["consent_confirmed"] or manifest.consents.analysis_feedback != "confirmed":
            return None, "consent_not_confirmed", ()
        basic = opinions.selected_basic(store, db, selection.case_id, selection.session_id, selection.basic, user, selection.viewer_sheet_id)[1] if selection.basic else None
        if basic and (basic.input != selection.sheet or basic.input_document != doc):
            raise HTTPException(409, "선택한 계산과 연구 원자료 판본이 다릅니다.")
        redactions = (case["dog_name"], case["guardian_name"], case["participant_id"], case["event_id"], doc.rater_name, doc.assigned_username)
        for change in db.execute("SELECT detail_json FROM changes WHERE target=? AND action='case.identity'",(selection.case_id,)):
            history = json.loads(change[0])
            redactions += tuple(value for side in ("before","after") for key,value in history.get(side,{}).items()
                if key in ("dog_name","guardian_name","participant_id","event_id") and isinstance(value,str) and value)
    final = None
    if selection.final:
        value = finals.view(store, selection.case_id, selection.session_id, selection.final.final_id, user, selection.viewer_sheet_id)
        if any(value["reference"][key] != getattr(selection.final, key) for key in ("final_id", "ref", "hash")):
            raise HTTPException(409, "선택한 최종 결과 hash가 다릅니다.")
        final = FinalResultV4.model_validate_json(encode(value["document"]))
        if final.basic_document.input != selection.sheet or (selection.basic and final.basic != selection.basic):
            raise HTTPException(409, "최종본과 내보낼 원자료·계산 pin이 다릅니다.")
        if final.opinion_document:
            redactions += (final.opinion_document.evaluator, final.opinion_document.actor)
    report, report_file = None, None
    if selection.report_run_id:
        raw, _, _ = reports.download(store, selection.case_id, selection.session_id, selection.report_run_id, "manifest", user, selection.viewer_sheet_id)
        report = ReportPublicationV4.model_validate_json(raw)
        redactions += (report.header.dog_name,report.header.guardian_name,report.header.participant_id,report.header.event_name)
        if not selection.final or report.final != selection.final:
            raise HTTPException(409, "리포트의 최종본을 정확히 함께 선택하세요.")
        with store.connect() as db:
            row = reports.row_for(store, db, selection.report_run_id)
            report_file = FileV4(ref=row["result_ref"], hash=row["result_hash"])
    return {"selection": selection, "sheet": doc, "basic": basic, "final": final, "report": report, "report_file": report_file}, None, redactions


def _parents(store, member, user):
    source = member.sheet.source
    files = [FileV4(ref=member.selection.sheet.ref, hash=member.selection.sheet.hash),
        FileV4(ref=source.input.manifest_ref, hash=source.input.manifest_hash)]
    files.extend(FileV4(ref=video.storage_ref, hash=video.sha256) for video in source.session.videos)
    with store.connect() as db:
        for video in source.session.videos:
            if isinstance(video,StoredMediaV4):
                receipt = uploads._linked_source(store,db,member.selection.case_id,video.video_id,user.username)
                for row in uploads._lineage(db,receipt).values():
                    if row["state"] not in ("linked","complete"):raise HTTPException(409,"취소된 변환 부모는 연구 자료로 내보낼 수 없습니다.")
                    files.append(FileV4(ref=row["storage_ref"],hash=row["sha256"]))
    if source.preprocess:
        files.append(FileV4(ref=source.preprocess.ref, hash=source.preprocess.hash))
        batch = BatchV4.model_validate_json(reports._read_file(store, source.preprocess))
        files.extend(batch.source_files)
        files.extend(file for clip in batch.clips for file in (clip.original, clip.ai) if file)
        if batch.reuse_manifest:
            files.append(batch.reuse_manifest)
    if member.selection.basic:
        files.append(FileV4(ref=member.selection.basic.ref, hash=member.selection.basic.hash))
    if member.selection.final:
        files.append(FileV4(ref=member.selection.final.ref, hash=member.selection.final.hash))
        if member.final.opinion:
            files.append(FileV4(ref=member.final.opinion.ref, hash=member.final.opinion.hash))
    if member.report_file:
        files.extend((member.report_file, member.report.output.html, member.report.output.pdf))
        files.extend(image.file for image in member.report.output.images)
    return files


def _external_member(members, external):
    target = external.target
    for member in members:
        source = member.sheet.source
        if (member.selection.case_id == target.case_id and source.session.session_id == target.session_id
                and source.input_revision == target.expected_revision
                and source.input == target.input):
            return member
    raise HTTPException(409, "외부 비교 대상의 회차·입력 판본이 선택한 연구 원자료와 일치하지 않습니다.")


def _snapshot(store, value, user):
    assets = _assets()
    identities = [(item.sheet.ref, item.sheet.hash) for item in value.members]
    if len(set(identities)) != len(identities):
        raise HTTPException(422, "같은 연구 원자료 판본을 중복 선택할 수 없습니다.")
    members, excluded, redactions, parents = [], [], set(value.redact_terms), {}
    cases, sessions, raters = {}, {}, {}
    for selection in value.members:
        cases.setdefault(selection.case_id, f"P{len(cases)+1:03}")
        pseudonym = cases[selection.case_id]
        data, exclusion, names = _member(store, selection, user)
        if exclusion:
            excluded.append({"case_id": selection.case_id, "pseudonym": pseudonym, "reason": exclusion})
            continue
        sessions.setdefault(selection.session_id, f"S{len(sessions)+1:03}")
        rater_key = data["sheet"].sheet.rater_id
        raters.setdefault(rater_key, f"R{len(raters)+1:03}")
        member = ExportMemberV4(**data, pseudonym=pseudonym, session_alias=sessions[selection.session_id], rater_alias=raters[rater_key])
        members.append(member); redactions.update(name for name in names if name)
        for file in _parents(store, member, user):
            if file.ref in parents and parents[file.ref] != file.hash:
                raise HTTPException(409, "같은 부모 파일에 다른 hash를 선택할 수 없습니다.")
            parents[file.ref] = file.hash
    reference_metadata = []
    for pointer in value.references:
        shown = validation.view(store, pointer.validation_id, user)
        if {key:shown["reference"][key] for key in ("ref", "hash")} != {"ref":pointer.ref, "hash":pointer.hash}:
            raise HTTPException(409, "검수 참고 원본 pin이 다릅니다.")
        doc = validation.document(store, pointer)
        parents[pointer.ref] = pointer.hash; parents[doc.source.ref] = doc.source.hash
        reference_metadata.extend({"source_sha256": doc.source.hash, "code":row.selection.code, "source_edition":row.selection.source_edition,
            "status":row.effective_status, "evaluator_status":row.selection.evaluator_status, "exposure":row.selection.exposure,
            "exclusion_reasons":list(row.exclusion_reasons), "included_in_score_denominator":False} for row in doc.rows)
    cohort = comparisons_v4.for_report(store, value.comparison, user) if value.comparison else None
    if cohort:
        parents[cohort.reference.ref] = cohort.reference.hash
    if not members:
        raise HTTPException(422, {"message":"연구용으로 내보낼 동의 확인 원자료가 없습니다.", "excluded":[{"pseudonym":row["pseudonym"], "reason":row["reason"]} for row in excluded]})
    external = []
    if len({pointer.snapshot_id for pointer in value.external_comparisons}) != len(value.external_comparisons):
        raise HTTPException(422, "같은 외부 비교 snapshot을 중복 선택할 수 없습니다.")
    for pointer in value.external_comparisons:
        public = external_comparisons_v4.for_output(store, pointer, user)
        _external_member(members, public)
        for file in external_comparisons_v4.files(store, pointer):
            if file.ref in parents and parents[file.ref] != file.hash:
                raise HTTPException(409, "외부 비교 부모 파일의 hash가 충돌합니다.")
            parents[file.ref] = file.hash
        external.append(public)
    catalog = load_catalog_v4()
    survey_catalog = SurveyCatalogV3.model_validate_json((RESOURCES/"catalogs/survey-v3.json").read_bytes())
    surveys = tuple(survey_scores_v4(member.sheet.source.session,survey_catalog) for member in members)
    if cohort and any((survey.survey_version, survey.policy_version) != (cohort.survey_version, cohort.survey_policy) for survey in surveys):
        raise HTTPException(409, "연구 설문과 선택 집단의 문항·집계 정책 판본이 다릅니다.")
    if any((entry.gate.scope.survey_version, entry.gate.scope.policy_version) != (surveys[0].survey_version, surveys[0].policy_version)
           for comparison in external for entry in comparison.entries):
        raise HTTPException(409, "연구 설문과 외부 비교의 문항·집계 정책 판본이 다릅니다.")
    if _assets() != assets:raise HTTPException(409,"연구 파일 생성 중 카탈로그·설문 정책이 변경되었습니다.")
    return ExportSnapshotV4(export_id=uid(), request_id=value.request_id, request_hash=analysis.digest(value.model_dump(mode="json")),
        actor=user.username, created_at=now(), reason=value.reason, format=value.format, members=tuple(members), excluded=tuple(excluded),
        references=tuple(value.references), reference_metadata=tuple(reference_metadata), cohort=cohort, external_comparisons=tuple(external),
        parent_files=tuple(FileV4(ref=ref, hash=digest) for ref,digest in sorted(parents.items())), redactions=tuple(sorted((term for term in redactions if term), key=lambda text:(-len(text),text))),
        catalog=catalog,surveys=surveys,asset_hashes=assets)


def _live_guard(store,db,snapshot,user):
    sheets.manager(user,db)
    for member in snapshot.members:
        case,manifest = _case(store,db,member.selection,user)
        if not case["consent_confirmed"] or manifest.consents.analysis_feedback != "confirmed":
            raise HTTPException(403,"연구 자료의 동의가 철회되었습니다.")
        _sheet(store,db,member.selection,user)
        for video in member.sheet.source.session.videos:
            if isinstance(video,StoredMediaV4):
                receipt = uploads._linked_source(store,db,member.selection.case_id,video.video_id,user.username)
                if any(row["state"] not in ("linked","complete") for row in uploads._lineage(db,receipt).values()):
                    raise HTTPException(409,"변환 부모가 취소되어 연구 자료를 사용할 수 없습니다.")
        if member.final:
            disclosures_v4.require(db,member.selection.case_id,member.selection.session_id,user,
                disclosures_v4.target("final",member.selection.final),member.final.actor)
        if member.report:
            row = reports.row_for(store,db,member.selection.report_run_id)
            if row["status"] != "succeeded" or (row["result_ref"],row["result_hash"]) != (member.report_file.ref,member.report_file.hash):
                raise HTTPException(409,"연결한 리포트 발급본이 취소·변경되었습니다.")


def guard(store, snapshot, user):
    with store.connect() as db:
        _live_guard(store,db,snapshot,user)
    if snapshot.actor != user.username:
        raise HTTPException(403, "본인이 생성한 연구 내보내기만 열 수 있습니다.")
    for expected in snapshot.members:
        data, excluded, _ = _member(store, expected.selection, user)
        if excluded or any(data[key] != getattr(expected, key) for key in ("sheet", "basic", "final", "report", "report_file")):
            raise HTTPException(409, "선택한 연구 원자료의 동의·판본·공개 권한이 변경되었습니다.")
    for pointer in snapshot.references:
        shown = validation.view(store, pointer.validation_id, user)
        if shown["reference"]["hash"] != pointer.hash:
            raise HTTPException(409, "검수 참고 출처가 변경되었습니다.")
    if snapshot.cohort and comparisons_v4.for_report(store, snapshot.cohort.reference, user) != snapshot.cohort:
        raise HTTPException(409, "연구 비교집단 출처가 변경되었습니다.")
    for expected in snapshot.external_comparisons:
        _external_member(snapshot.members, expected)
        if external_comparisons_v4.for_output(store, expected.reference, user) != expected:
            raise HTTPException(409, "연구 외부 비교의 승인·출처 또는 대상 조건이 변경되었습니다.")


def _files(store, snapshot):
    stamps = {}
    for file in snapshot.parent_files:
        reports._verify_pointer(store, file, stamps)
    return stamps


def _text(snapshot, value):
    if not isinstance(value, str):
        return value
    for name in snapshot.redactions:
        value = value.replace(name, "[비식별]")
    return value


def _base(member):
    doc = member.sheet
    return {"subject":member.pseudonym, "session":member.session_alias, "rater":member.rater_alias,
        "rater_kind":doc.sheet.rater_kind, "purpose":doc.purpose, "origin":doc.origin, "state":doc.state,
        "sheet_revision":doc.revision, "sheet_sha256":member.selection.sheet.hash, "input_revision":doc.source.input_revision,
        "input_sha256":doc.source.input.manifest_hash, "batch_sha256":analysis.digest({"batch_id":doc.source.batch_id,"source_hash":doc.source_hash}),
        "catalog_version":doc.sheet.catalog_version, "protocol_version":doc.sheet.protocol_version, "scoring_version":doc.sheet.scoring_version,
        "ai_exposed":doc.sheet.ai_exposed, "raw_exposure_count":len(doc.exposures), "interpretation_exposure_count":len(doc.interpretation_exposures)}


def _evidence(snapshot, entries):
    return encode([{**{key:value for key,value in entry.model_dump(mode="json").items() if key not in ("video_id","note")},
        "note":_text(snapshot,entry.note)} for entry in entries])


def tables(snapshot):
    output = {name:[] for name in ("raw_observations","linked_memos","walk_exceptions","automatic_calculations","decisions","opinions","final_results","reports",
        "survey_responses","survey_domains","comparisons","independent_pairs","item_denominators","quality","reference_sources","excluded")}
    catalog = snapshot.catalog
    for member,survey in zip(snapshot.members,snapshot.surveys,strict=True):
        base, doc = _base(member), member.sheet
        observations = {row.code:row for row in doc.sheet.observations}
        metrics = {row.key:row for row in member.basic.calculations.metrics} if member.basic else {}
        for item in catalog.items:
            row = observations.get(item.code)
            metric = metrics.get(item.code)
            windows = sorted({entry.window_id for entry in row.evidence}) if row and row.evidence else [None]
            for window in windows:
                evidence = [entry for entry in row.evidence if entry.window_id == window] if row else []
                output["raw_observations"].append({**base,"code":item.code,"segment":item.segment,"input_kind":item.usage,
                    "value_type":item.value_type,"optional":item.optional,"window":window,
                    "value":_text(snapshot,row.value) if row else metric.value if metric else None,
                    "status":row.status if row else metric.status if metric else "not_selected" if item.usage == "automatic" else "not_recorded",
                    "reason":_text(snapshot,row.reason if row else metric.reason if metric else "자동 계산 미선택" if item.usage == "automatic" else "원관찰 미기록"),
                    "validity":row.validity if row else None,"opportunity":row.opportunity if row else None,
                    "whole_interval_observed":row.whole_interval_observed if row else None,
                    "observed_seconds_by_view":encode([{"camera_id":entry.camera_id,"seconds":entry.observed_seconds} for entry in evidence]),
                    "evidence":_evidence(snapshot,evidence),
                    "vocalization":encode({**row.vocalization.model_dump(mode="json"),"note":_text(snapshot,row.vocalization.note)}) if row and row.vocalization else None,
                    "review_memo":_text(snapshot,row.review_memo) if row else None})
        for memo in doc.sheet.linked_memos:
            output["linked_memos"].append({**base,"code":"개59","text":_text(snapshot,memo.text),"item_codes":encode(memo.item_codes),
                "evidence":_evidence(snapshot,memo.evidence)})
        for phase in doc.sheet.walk_phases:
            output["walk_exceptions"].append({**base,"code":phase.code,"proximity_exception":phase.proximity_exception,
                "note":_text(snapshot,phase.note),"evidence":_evidence(snapshot,phase.evidence)})
        if member.basic:
            basic = member.basic
            for metric in basic.calculations.metrics:
                output["automatic_calculations"].append({**base,"basic_revision":basic.revision,"basic_sha256":member.selection.basic.hash,
                    "key":metric.key,"value":metric.value,"status":metric.status,"reason":_text(snapshot,metric.reason),
                    "numerator":metric.numerator,"denominator":metric.denominator,"used_codes":encode(metric.used_codes),"excluded":encode(metric.excluded),"caution":metric.caution})
            owner = basic.calculations.owner
            for index, name in enumerate(("허용형","조율형","통제형")):
                output["automatic_calculations"].append({**base,"key":"owner_ratio_"+name,"value":owner.ratios[index] if owner.ratios else None,
                    "status":owner.status,"reason":_text(snapshot,owner.reason),"denominator":owner.valid_items,"valid_scenes":owner.valid_scenes})
            for kind, values in (("automatic",basic.automatic_decisions),("manual",basic.manual_decisions),("effective",basic.decisions)):
                for decision in values:
                    output["decisions"].append({**base,"basis":kind,"key":decision.key,"label":decision.label,"status":decision.status,
                        "reason":_text(snapshot,decision.reason),"evidence_codes":encode(decision.evidence_codes),"counter_codes":encode(decision.counter_codes)})
        if member.final:
            final = member.final
            if final.opinion_document:
                opinion = final.opinion_document
                for domain in opinion.domains:
                    output["opinions"].append({**base,"opinion_revision":opinion.revision,"opinion_sha256":final.opinion.hash,"state":opinion.state,
                        "completion_requested":opinion.completion_requested,"domain":domain.domain,"text":_text(snapshot,domain.text),"label":domain.label,
                        "evidence_codes":encode(domain.evidence_codes),"counter_codes":encode(domain.counter_codes)})
            for domain in final.domains:
                output["final_results"].append({**base,"final_sha256":member.selection.final.hash,"domain":domain.domain,"label":domain.label,
                    "status":domain.status,"source":domain.source,"text":_text(snapshot,domain.text),"reason":_text(snapshot,domain.reason)})
        if member.report:
            output["reports"].append({**base,"report_sha256":member.report_file.hash,"input_sha256":member.report.input_hash,
                "config_sha256":member.report.config_hash,"html_sha256":member.report.output.html.hash,"pdf_sha256":member.report.output.pdf.hash,
                "state":member.report.publication_state,"cohort_sha256":member.report.cohort.reference.hash if member.report.cohort else None})
        for question in survey.items:
            output["survey_responses"].append({**base,"survey_version":survey.survey_version,"policy_version":survey.policy_version,
                **question.model_dump(mode="json"),"blank_reason":_text(snapshot,question.blank_reason)})
        for domain in survey.domains:
            output["survey_domains"].append({**base,"survey_version":survey.survey_version,"policy_version":survey.policy_version,**domain.model_dump(mode="json")})
        required = [item.code for item in catalog.items if item.usage == "numeric" and not item.optional]
        nulls = sum(not observations.get(code) or observations[code].value is None for code in required)
        valid = sum(row.status == "observed" and row.validity == "valid" and type(row.value) is int for row in doc.sheet.observations)
        output["quality"].append({**base,"required_numeric_total":len(required),"required_null_count":nulls,
            "required_null_rate":nulls/len(required),"valid_numeric_count":valid,"camera_count":len({video.camera_id for video in doc.source.session.videos if hasattr(video,"camera_id")})})
    output["reference_sources"] = list(snapshot.reference_metadata)
    output["excluded"] = [{key:value for key,value in row.items() if key != "case_id"} for row in snapshot.excluded]
    if snapshot.cohort:
        for domain in snapshot.cohort.domains:
            output["comparisons"].append({"source":"selected_own_cohort","snapshot_sha256":snapshot.cohort.reference.hash,
                "survey_version":snapshot.cohort.survey_version,"policy_version":snapshot.cohort.survey_policy,**domain.model_dump(mode="json")})
    for external in snapshot.external_comparisons:
        member = _external_member(snapshot.members, external)
        for entry in external.entries:
            scope, values, confirmation = entry.gate.scope, entry.gate.values, entry.gate.confirmation
            output["comparisons"].append({"source":"external_reference", "participant":member.pseudonym, "session":member.session_alias,
                "snapshot_sha256":external.reference.hash, "snapshot_revision":external.reference.revision,
                "source_id":entry.gate.source_id, "title":_text(snapshot,entry.title), "literature":_text(snapshot,entry.literature),
                "doi":entry.doi, "population_scope":_text(snapshot,entry.population_scope), "number_provenance":_text(snapshot,entry.number_provenance),
                "domain":scope.domain, "question_ids":encode(scope.question_ids), "survey_version":scope.survey_version,
                "policy_version":scope.policy_version, "question_text_sha256":scope.question_text_hash,
                "scale_minimum":scope.scale_minimum, "scale_maximum":scope.scale_maximum, "aggregation":scope.aggregation,
                "direction":scope.direction, "missing_policy":scope.missing_policy,
                "population_requirements":encode({key:_text(snapshot,value) for key,value in scope.population_requirements.items()}),
                "local_mean":entry.local_mean, "local_n":entry.local_n, "local_n_label":"유효 응답 문항", "mean":values.mean,
                "standard_deviation":values.standard_deviation, "valid_n":values.valid_n, "total_n":values.total_n,
                "external_valid_n_label":"외부 유효 표본", "external_total_n_label":"외부 전체 표본",
                "research_sha256":confirmation.hash, "research_revision":confirmation.revision,
                "activation_revision":entry.gate.activation_revision})
    _pairs(snapshot, output, catalog)
    return output


def _pairs(snapshot, output, catalog):
    totals = {}
    for index,left in enumerate(snapshot.members):
        for right in snapshot.members[index+1:]:
            if left.selection.case_id != right.selection.case_id or left.selection.session_id != right.selection.session_id:
                continue
            if left.sheet.sheet.rater_kind == right.sheet.sheet.rater_kind:
                continue
            lrows, rrows = ({row.code:row for row in member.sheet.sheet.observations} for member in (left,right))
            common = []
            for member in (left,right):
                doc = member.sheet
                if doc.state != "submitted":common.append("not_submitted")
                if doc.purpose != "independent" or doc.sheet.ai_exposed or doc.exposures or doc.interpretation_exposures:common.append("not_independent")
                if doc.sheet.rater_kind == "ai" and (doc.origin != "ai_service" or doc.revision != 1 or doc.previous):
                    common.append("not_initial_ai_output")
            if left.sheet.source_hash != right.sheet.source_hash:common.append("different_input_or_batch")
            for item in catalog.items:
                if item.usage != "numeric":continue
                one,two = lrows.get(item.code),rrows.get(item.code)
                reasons = list(common)
                if item.policy_pending:reasons.append("policy_pending")
                if any(row is None or row.status != "observed" or row.validity != "valid" or type(row.value) is not int for row in (one,two)):
                    reasons.append("both_valid_observations_required")
                if one and two:
                    left_windows, right_windows = ({entry.window_id for entry in row.evidence} for row in (one,two))
                    if not left_windows or not right_windows:reasons.append("observation_window_required")
                    elif left_windows != right_windows:reasons.append("different_observation_windows")
                valid = not reasons
                output["independent_pairs"].append({"subject":left.pseudonym,"session":left.session_alias,"left_rater":left.rater_alias,
                    "right_rater":right.rater_alias,"left_sheet_sha256":left.selection.sheet.hash,"right_sheet_sha256":right.selection.sheet.hash,
                    "code":item.code,"value_type":item.value_type,"included":valid,"excluded_reasons":encode(sorted(set(reasons))),
                    "left_value":one.value if valid else None,"right_value":two.value if valid else None,
                    "equal":one.value == two.value if valid else None,"difference":one.value-two.value if valid and item.value_type == "count" else None})
                count = totals.setdefault(item.code,{"code":item.code,"value_type":item.value_type,"valid_pair_n":0,"equal_n":0,"excluded_pair_n":0})
                count["valid_pair_n" if valid else "excluded_pair_n"] += 1
                if valid and one.value == two.value:count["equal_n"] += 1
    output["item_denominators"] = list(totals.values())


def _cell(value):
    if isinstance(value,(dict,list,tuple)):
        value = encode(value)
    if isinstance(value,str) and value.lstrip(" \t\r\n").startswith(("=","+","-","@")):
        return "'"+value
    return value


def render(snapshot):
    values = tables(snapshot)
    if snapshot.format == "csv_zip":
        output = BytesIO()
        with ZipFile(output,"w",ZIP_DEFLATED) as archive:
            for name,rows in values.items():
                columns = list(dict.fromkeys(key for row in rows for key in row)) or ["no_rows"]
                text = StringIO(newline="")
                writer = csv.writer(text); writer.writerow(columns)
                for row in rows:writer.writerow([_cell(row.get(key)) for key in columns])
                archive.writestr(name+".csv",text.getvalue().encode("utf-8-sig"))
        return output.getvalue()
    workbook = Workbook(); workbook.remove(workbook.active)
    for name,rows in values.items():
        if len(rows) >= 1048576:
            raise HTTPException(422,"XLSX 최대 행 수를 넘습니다. 원값을 보존하는 CSV ZIP을 선택하세요.")
        sheet = workbook.create_sheet(name[:31])
        columns = list(dict.fromkeys(key for row in rows for key in row)) or ["no_rows"]
        sheet.append(columns)
        for row in rows:
            cells = [_cell(row.get(key)) for key in columns]
            if any(isinstance(value,str) and (len(value)>32767 or any(ord(char)<32 and char not in "\t\r\n" for char in value)) for value in cells):
                raise HTTPException(422,"XLSX가 보존할 수 없는 긴 셀 또는 제어문자가 있습니다. 원값을 보존하는 CSV ZIP을 선택하세요.")
            sheet.append(cells)
        sheet.freeze_panes = "A2"; sheet.auto_filter.ref = sheet.dimensions
    output = BytesIO(); workbook.save(output); workbook.close()
    return output.getvalue()


def _record(db, export_id):
    row = db.execute("SELECT detail_json FROM changes WHERE target=? AND action=? ORDER BY rowid DESC LIMIT 1", (export_id,ACTION)).fetchone()
    if not row:raise HTTPException(404,"연구 내보내기가 없습니다.")
    return json.loads(row[0])


def _load(store, record):
    value = ExportSnapshotV4.model_validate_json(reports._read_file(store,FileV4(ref=record["ref"],hash=record["hash"])))
    if value.export_id != record["export_id"]:raise HTTPException(409,"연구 내보내기 식별자가 다릅니다.")
    return value


def view(store, export_id, user):
    with store.connect() as db:record = _record(db,export_id)
    snapshot = _load(store,record); guard(store,snapshot,user)
    return {"export_id":export_id,"format":snapshot.format,"created_at":snapshot.created_at,"member_count":len(snapshot.members),
        "excluded_count":len(snapshot.excluded),"snapshot_sha256":record["hash"],"output_sha256":snapshot.output.hash,"status":"ready"}


def create(store,value:ExportCreateV4,user):
    value = ExportCreateV4.model_validate_json(value.model_dump_json())
    request_hash = analysis.digest(value.model_dump(mode="json"))
    with store.connect() as db:
        sheets.manager(user,db)
        for row in db.execute("SELECT detail_json FROM changes WHERE actor=? AND action=?",(user.username,ACTION)):
            record = json.loads(row[0])
            if record["request_id"] == value.request_id:
                if record["request_hash"] != request_hash:raise HTTPException(409,"동일 요청 ID의 연구 선택이 다릅니다.")
                return view(store,record["export_id"],user)
    snapshot = _snapshot(store,value,user)
    stamps = _files(store,snapshot)
    data = render(snapshot)
    output = reports._write_bytes(store,f"exports/{snapshot.export_id}/research."+("zip" if value.format == "csv_zip" else "xlsx"),data)
    snapshot = snapshot.model_copy(update={"output":output})
    pointer = reports._write_bytes(store,f"exports/{snapshot.export_id}/snapshot.json",snapshot.model_dump_json().encode())
    guard(store,snapshot,user)
    reports._read_file(store,output,stamps); reports._read_file(store,pointer,stamps)
    with store.connect(write=True) as db:
        _live_guard(store,db,snapshot,user)
        guard(store,snapshot,user)
        if _assets() != snapshot.asset_hashes:raise HTTPException(409,"연구 저장 직전 설문·카탈로그 판본이 변경되었습니다.")
        reports.check_stamps(store,stamps)
        if ExportSnapshotV4.model_validate_json(reports._read_file(store,pointer)) != snapshot:raise HTTPException(409,"새 연구 저장물이 변경되었습니다.")
        for row in db.execute("SELECT detail_json FROM changes WHERE actor=? AND action=?",(user.username,ACTION)):
            previous = json.loads(row[0])
            if previous["request_id"] == value.request_id:
                if previous["request_hash"] != request_hash:raise HTTPException(409,"같은 요청 ID의 연구 선택이 동시에 변경되었습니다.")
                return view(store,previous["export_id"],user)
        store.audit(db,user.username,snapshot.export_id,ACTION,{"export_id":snapshot.export_id,"ref":pointer.ref,"hash":pointer.hash,
            "request_id":value.request_id,"request_hash":request_hash,"case_ids":sorted({member.case_id for member in value.members}),
            "cohort_id":snapshot.cohort.reference.snapshot_id if snapshot.cohort else None,"report_run_ids":[member.report_run_id for member in value.members if member.report_run_id],
            "validation_ids":[pointer.validation_id for pointer in value.references],
            "external_snapshot_ids":[pointer.snapshot_id for pointer in value.external_comparisons]})
    return view(store,snapshot.export_id,user)


def download(store,export_id,user):
    with store.connect() as db:record = _record(db,export_id)
    snapshot = _load(store,record); guard(store,snapshot,user)
    stamps = _files(store,snapshot)
    data = reports._read_file(store,snapshot.output,stamps)
    guard(store,snapshot,user)
    with store.connect() as db:
        _live_guard(store,db,snapshot,user)
        if _record(db,export_id) != record:raise HTTPException(409,"다운로드 중 연구 저장 참조가 변경되었습니다.")
        reports.check_stamps(store,stamps)
    return data, "application/zip" if snapshot.format == "csv_zip" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "research-"+export_id+(".zip" if snapshot.format == "csv_zip" else ".xlsx")


def list_exports(store,user):
    with store.connect() as db:
        sheets.manager(user,db)
        ids = [row[0] for row in db.execute("SELECT DISTINCT target FROM changes WHERE actor=? AND action=?",(user.username,ACTION))]
    result = []
    for export_id in ids:
        try:
            result.append(view(store,export_id,user))
        except (HTTPException, ValueError, OSError) as exc:
            if isinstance(exc,HTTPException) and exc.status_code not in (403,404,409,422):
                raise
            result.append(ExportBlockedV4(export_id=export_id,
                reason="원자료·출력 또는 현재 동의·공개·비교 조건을 확인할 수 없어 제공을 보류합니다.").model_dump())
    with store.connect() as db:
        sheets.manager(user,db)
    return result


def purge_deleted(db,*,cohort_ids=(),report_run_ids=(),validation_ids=(),external_snapshot_ids=()):
    deleted = {row[0] for row in db.execute("SELECT case_id FROM cases WHERE deletion_requested=1")}
    revoked = set()
    for row in db.execute("SELECT target,detail_json FROM changes WHERE action=?",(ACTION,)):
        data = json.loads(row["detail_json"])
        if (deleted.intersection(data["case_ids"]) or data.get("cohort_id") in set(cohort_ids)
                or set(report_run_ids).intersection(data.get("report_run_ids",())) or set(validation_ids).intersection(data.get("validation_ids",()))
                or set(external_snapshot_ids).intersection(data.get("external_snapshot_ids",()))):
            revoked.add(row["target"])
    for export_id in revoked:db.execute("DELETE FROM changes WHERE target=? AND action=?",(export_id,ACTION))
    return revoked
