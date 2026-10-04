"""Same-edition cohort snapshots and fail-closed external research gates."""
from collections import Counter
import hashlib
import json
import os

from fastapi import HTTPException
from pydantic import Field,field_validator

from . import analysis
from .domain.catalog_v3 import SurveyCatalogV3
from .domain.catalog_v4 import RESOURCES,validate_source_references_v4
from .domain.comparisons_v4 import (CohortDomainV4,CohortMemberV4,CohortPublicDomainV4,CohortPublicV4,CohortReferenceV4,
    CohortSelectionV4,CohortSnapshotV4,ComparisonScopeV4,ExternalGateV4,ExternalValuesV4,ResearchConfirmationV4,
    ResearchReferenceV4,ResearchReviewV4,TechnicalActivationV4)
from .domain.preprocess_v4 import FileV4
from .domain.sheets_v4 import InputPointerV4
from .input_models import Model
from .input_models_v4 import ManifestV4
from .intake import selected_session
from .storage import encode,now,uid
from .survey_v4 import survey_scores_v4

COHORT_ACTION="comparison.s1.snapshot"
RESEARCH_ACTION="comparison.research"
ACTIVATION_ACTION="comparison.activation"
SOURCE_ASSET="report/comparison-sources-v4.json"
SURVEY_ASSETS=("catalogs/survey-v3.json","rules/survey-policy-v4.json")
CHECKS=("numerical_table","question_equivalence","scale_direction","missing_policy","translation_usage","population_scope")


class CohortCreateV4(Model):
    request_id: str = Field(min_length=1,max_length=200)
    title: str = Field(min_length=1,max_length=200)
    reason: str = Field(min_length=1,max_length=4000)
    members: list[CohortSelectionV4] = Field(min_length=1,max_length=5000)

    @field_validator("members",mode="before")
    @classmethod
    def contracts(cls,value):
        return [CohortSelectionV4.model_validate_json(encode(item)) if isinstance(item,dict) else item for item in value]

    @field_validator("request_id","title","reason")
    @classmethod
    def text(cls,value):
        if not value.strip():raise ValueError("comparison selection requires meaningful text")
        return value


class CohortViewV4(Model):
    reference: CohortReferenceV4
    document: CohortSnapshotV4
    outdated_member_case_ids: list[str]


class CohortSessionCandidateV4(Model):
    session_id: str
    note: str
    survey_version: str


class CohortCandidateV4(Model):
    case_id: str
    event_id: str
    participant_id: str
    dog_name: str
    input_revision: int
    input: InputPointerV4
    sessions: list[CohortSessionCandidateV4]


class CohortSummaryV4(Model):
    reference: CohortReferenceV4
    title: str
    selection_count: int = Field(ge=1)
    outdated: bool


class ConfirmResearchV4(Model):
    expected_revision: int = Field(ge=0,strict=True)
    document: ResearchReviewV4

    @field_validator("document",mode="before")
    @classmethod
    def contract(cls,value):
        return ResearchReviewV4.model_validate_json(encode(value)) if isinstance(value,dict) else value


class ActivateExternalV4(Model):
    source_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0,strict=True)
    confirmation: ResearchReferenceV4 | None = None
    enabled: bool = Field(strict=True)
    reason: str = Field(min_length=1,max_length=4000)

    @field_validator("confirmation",mode="before")
    @classmethod
    def contract(cls,value):
        return ResearchReferenceV4.model_validate_json(encode(value)) if isinstance(value,dict) else value


def _account(db,user,*,admin=False):
    row=db.execute("SELECT active,role FROM users WHERE username=?",(user.username,)).fetchone()
    if not row or not row["active"] or row["role"] not in (("admin",) if admin else ("operator","admin")):
        raise HTTPException(403,"집단 비교 관리 권한이 없습니다.")
    return row


def assets():
    return {name:hashlib.sha256((RESOURCES/name).read_bytes()).hexdigest() for name in SURVEY_ASSETS}


def _sources():
    raw=(RESOURCES/SOURCE_ASSET).read_bytes()
    value=json.loads(raw)
    validate_source_references_v4({"source":value["source"]})
    if value["version"]!="comparison-sources-20261002-s1.1-1" or value["default_status"]!="pending_D06":
        raise HTTPException(409,"외부 비교 출처 판본이 다릅니다.")
    return value,hashlib.sha256(raw).hexdigest()


def public_sources(store=None, user=None):
    value,_=_sources()
    result = {"version":value["version"],"status":"pending_D06","sources":[{"source_id":item["source_id"],"title":item["title"],
        "status":"blocked","reason":"연구 확인자료와 별도의 관리자 기술 활성화가 모두 필요합니다."} for item in value["sources"]],
        "domestic_status":value["domestic_status"],"domestic_reason":value["domestic_reason"]}
    if store is not None:
        with store.connect() as db:
            _account(db,user)
            for item in result["sources"]:
                pointer=_record(db,RESEARCH_ACTION,item["source_id"])
                activation=_record(db,ACTIVATION_ACTION,item["source_id"])
                if not pointer or not activation:continue
                try:
                    reference=ResearchReferenceV4.model_validate_json(encode(pointer))
                    doc=research_document(store,reference)
                    source,digest=_source(item["source_id"])
                    result_gate=gate(source,digest,doc,reference,TechnicalActivationV4.model_validate_json(encode(activation)),
                        target_scope(item["source_id"]),doc.scope.population_requirements)
                except (HTTPException,ValueError):continue
                if result_gate.status=="approved":
                    item.update(status="conditionally_available",reason="연구 확인과 기술 활성화가 기록되었습니다. 대상의 실제 설문·프로필 조건은 명시 snapshot 생성 시 검증합니다.")
        if any(item["status"]=="conditionally_available" for item in result["sources"]):result["status"]="conditional_selection_available"
    return result


def _source(source_id):
    sources,digest=_sources()
    source=next((item for item in sources["sources"] if item["source_id"]==source_id),None)
    if source is None:raise HTTPException(404,"외부 비교 출처가 없습니다.")
    return source,digest


def target_scope(source_id):
    """Server-generated local questionnaire identity, not a research approval."""
    source,_=_source(source_id)
    catalog=SurveyCatalogV3.model_validate_json((RESOURCES/SURVEY_ASSETS[0]).read_bytes())
    questions=[{"id":item.item_id,"text":item.text,"allowed_values":item.allowed_values} for item in catalog.items if item.item_id in source["question_ids"]]
    return ComparisonScopeV4(survey_version="survey-20260929-v3",policy_version="survey-policy-20261002-s1.1",domain=source["domain"],
        question_ids=tuple(source["question_ids"]),question_text_hash=analysis.digest(questions),scale_minimum=source["scale_minimum"],
        scale_maximum=source["scale_maximum"],direction=source["direction"],aggregation=source["aggregation"],missing_policy=source["missing_policy"])


def _record(db,action,target):
    row=db.execute("SELECT detail_json FROM changes WHERE action=? AND target=? ORDER BY rowid DESC LIMIT 1",(action,target)).fetchone()
    return json.loads(row[0]) if row else None


def _read(store,pointer,model,*,prefix="comparisons/"):
    try:
        if not pointer.ref.startswith(prefix):raise ValueError("comparison path")
        raw=store.path(pointer.ref).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=pointer.hash:raise ValueError("comparison hash")
        return model.model_validate_json(raw)
    except (OSError,ValueError) as exc:
        raise HTTPException(409,"비교 snapshot 또는 확인자료가 손상되었습니다.") from exc


def _write(store,kind,doc):
    data=encode(doc.model_dump(mode="json")).encode()
    ref=f"comparisons/{kind}/{uid()}.json"
    path=store.path(ref)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data);handle.flush();os.fsync(handle.fileno())
    return FileV4(ref=ref,hash=hashlib.sha256(data).hexdigest())


def _member(store,db,selection,*,current=True):
    case=store.case(db,selection.case_id,expected=selection.expected_revision if current else None)
    live=store.manifest(case)
    if not isinstance(live,ManifestV4):raise HTTPException(409,"S1 설문 입력만 자체 집단에 포함할 수 있습니다.")
    if live.consents.analysis_feedback!="confirmed":raise HTTPException(403,"분석·피드백 동의가 확인된 자료만 집단에 포함할 수 있습니다.")
    if current and (case["manifest_ref"],case["manifest_hash"])!=(selection.input.manifest_ref,selection.input.manifest_hash):
        raise HTTPException(409,"선택한 입력 판본이 현재 입력과 다릅니다.")
    frozen=_read(store,FileV4(ref=selection.input.manifest_ref,hash=selection.input.manifest_hash),ManifestV4,prefix="inputs/")
    if (frozen.case_id,frozen.input_revision)!=(selection.case_id,selection.expected_revision):raise HTTPException(409,"고정 집단 원자료의 대상·판본이 다릅니다.")
    if frozen.consents.analysis_feedback!="confirmed":raise HTTPException(403,"고정 원자료의 분석 동의가 확인되지 않았습니다.")
    session=selected_session(frozen,selection.session_id)
    if session.survey_version!="survey-20260929-v3":raise HTTPException(422,"다른 원문·척도 설문을 자체 집단에 혼합할 수 없습니다.")
    catalog=SurveyCatalogV3.model_validate_json((RESOURCES/SURVEY_ASSETS[0]).read_bytes())
    return CohortMemberV4(case_id=selection.case_id,session_id=selection.session_id,input_revision=frozen.input_revision,
        input=selection.input,survey=survey_scores_v4(session,catalog)),case


def aggregate(members):
    if not members or len({member.case_id for member in members})!=len(members):raise ValueError("explicit distinct-case cohort required")
    if any((member.survey.survey_version,member.survey.policy_version)!=("survey-20260929-v3","survey-policy-20261002-s1.1") for member in members):
        raise ValueError("mixed survey edition or aggregation policy")
    definitions=members[0].survey.domains
    result=[]
    for definition in (*definitions,None):
        key=definition.domain if definition else "일상 따라옴 (Q25 단일 응답)"
        ids=definition.question_ids if definition else ("s25",)
        included,excluded,values=[],{},[]
        allowed={value for item in members[0].survey.items if item.item_id in ids for value in item.allowed_values}
        for member in members:
            row=next((value for value in member.survey.domains if value.domain==key),None) if definition else member.survey.standalone
            value=row.mean if definition and row is not None else row.raw if row is not None else None
            status=row.status if row is not None else "missing"
            if value is not None and status in ("calculated","answered"):
                included.append(member.case_id);values.append(value)
            else:excluded[member.case_id]=status
        result.append(CohortDomainV4(domain=key,question_ids=ids,scale_minimum=min(allowed),scale_maximum=max(allowed),
            mean=sum(values)/len(values) if values else None,n=len(values),sum_values=float(sum(values)) if values else None,
            included_case_ids=tuple(included),excluded=excluded))
    return tuple(result)


def _validate_snapshot(store,db,pointer):
    doc=_read(store,pointer,CohortSnapshotV4)
    if (doc.snapshot_id,doc.revision)!=(pointer.snapshot_id,pointer.revision):raise HTTPException(409,"비교 참조가 다릅니다.")
    if _record(db,"comparison.deleted",doc.snapshot_id):raise HTTPException(403,"삭제된 대상이 포함된 집단입니다.")
    if doc.asset_hashes!=assets():raise HTTPException(409,"다른 설문 집계 정책의 집단입니다.")
    outdated=[]
    for member in doc.members:
        current,row=_member(store,db,CohortSelectionV4(case_id=member.case_id,session_id=member.session_id,expected_revision=member.input_revision,input=member.input),current=False)
        if current!=member:raise HTTPException(409,"집단의 고정 설문 산출이 원자료와 다릅니다.")
        if (row["manifest_ref"],row["manifest_hash"])!=(member.input.manifest_ref,member.input.manifest_hash):outdated.append(member.case_id)
    if aggregate(doc.members)!=doc.domains:raise HTTPException(409,"집단 평균·유효 n이 고정 원자료와 다릅니다.")
    return doc,outdated


def create(store,value:CohortCreateV4,user):
    value=CohortCreateV4.model_validate_json(value.model_dump_json())
    if len({member.case_id for member in value.members})!=len(value.members):raise HTTPException(422,"한 대상에서 하나의 회차만 명시적으로 선택하세요.")
    request_hash=analysis.digest(value.model_dump(mode="json"))
    request_target=f"{user.username}:{value.request_id}"
    with store.connect() as db:
        _account(db,user)
        previous=_record(db,"comparison.request",request_target)
        if previous:
            if previous["request_hash"]!=request_hash:raise HTTPException(409,"같은 요청 ID의 집단 선택이 달라졌습니다.")
            return view(store,previous["snapshot_id"],user)
        members=tuple(_member(store,db,selection)[0] for selection in value.members)
    doc=CohortSnapshotV4(snapshot_id=uid(),title=value.title,actor=user.username,recorded_at=now(),reason=value.reason,
        asset_hashes=assets(),members=members,domains=aggregate(members))
    file=_write(store,"cohorts",doc)
    pointer=CohortReferenceV4(snapshot_id=doc.snapshot_id,ref=file.ref,hash=file.hash)
    with store.connect(write=True) as db:
        _account(db,user)
        if _record(db,"comparison.request",request_target):raise HTTPException(409,"같은 요청이 저장되었습니다. 다시 조회하세요.")
        if tuple(_member(store,db,selection)[0] for selection in value.members)!=doc.members or assets()!=doc.asset_hashes:
            raise HTTPException(409,"저장 중 집단 입력 또는 집계 정책이 달라졌습니다.")
        if _read(store,pointer,CohortSnapshotV4)!=doc:raise HTTPException(409,"저장 중 집단 snapshot이 달라졌습니다.")
        store.audit(db,user.username,doc.snapshot_id,COHORT_ACTION,{"reference":pointer.model_dump(mode="json"),"case_ids":[member.case_id for member in members]})
        store.audit(db,user.username,request_target,"comparison.request",{"request_hash":request_hash,"snapshot_id":doc.snapshot_id})
    return view(store,doc.snapshot_id,user)


def view(store,snapshot_id,user):
    with store.connect() as db:
        _account(db,user)
        record=_record(db,COHORT_ACTION,snapshot_id)
        if not record:raise HTTPException(404,"집단 snapshot을 찾을 수 없습니다.")
        pointer=CohortReferenceV4.model_validate_json(encode(record["reference"]))
        doc,outdated=_validate_snapshot(store,db,pointer)
        return CohortViewV4(reference=pointer,document=doc,outdated_member_case_ids=outdated)


def candidates(store,user):
    with store.connect() as db:
        _account(db,user)
        result=[]
        for row in db.execute("SELECT * FROM cases WHERE deletion_requested=0 ORDER BY event_id,participant_id"):
            manifest=store.manifest(row)
            if not isinstance(manifest,ManifestV4) or manifest.consents.analysis_feedback!="confirmed":
                continue
            sessions=[CohortSessionCandidateV4(session_id=session.session_id,note=session.note,survey_version=session.survey_version)
                      for session in manifest.sessions if session.survey_version=="survey-20260929-v3"]
            if sessions:
                result.append(CohortCandidateV4(case_id=row['case_id'],event_id=row['event_id'],participant_id=row['participant_id'],dog_name=row['dog_name'],
                    input_revision=row['input_revision'],input=InputPointerV4(manifest_ref=row['manifest_ref'],manifest_hash=row['manifest_hash']),sessions=sessions))
        return result


def list_snapshots(store,user):
    with store.connect() as db:
        _account(db,user)
        ids=[row[0] for row in db.execute("SELECT target FROM changes WHERE action=? ORDER BY rowid DESC",(COHORT_ACTION,))]
    result=[]
    for snapshot_id in ids:
        try:
            value=view(store,snapshot_id,user)
            result.append({"reference":value.reference.model_dump(mode="json"),"title":value.document.title,"selection_count":len(value.document.members),"outdated":bool(value.outdated_member_case_ids)})
        except HTTPException as exc:
            if exc.status_code not in (403,404):raise
    return result


def for_report(store,pointer,user):
    pointer=CohortReferenceV4.model_validate(pointer)
    value=view(store,pointer.snapshot_id,user)
    if value.reference!=pointer:raise HTTPException(409,"명시한 비교 snapshot의 고정 참조가 다릅니다.")
    doc=value.document
    return CohortPublicV4(reference=pointer,title=doc.title,selection_count=len(doc.members),selection_note=doc.identity_limitation,
        domains=tuple(CohortPublicDomainV4(domain=row.domain,question_ids=row.question_ids,scale_minimum=row.scale_minimum,
            scale_maximum=row.scale_maximum,mean=row.mean,n=row.n,excluded_count=len(row.excluded),exclusion_reasons=dict(Counter(row.excluded.values()))) for row in doc.domains))


def purge_case(db,case_id):
    """Drop all multi-case capsules containing the revoked case; keep only IDs."""
    snapshots={}
    for row in db.execute("SELECT actor,target,detail_json FROM changes WHERE action=?",(COHORT_ACTION,)):
        if case_id in json.loads(row["detail_json"])["case_ids"]:snapshots[row["target"]]=row["actor"]
    for snapshot_id,actor in snapshots.items():
        if not _record(db,"comparison.deleted",snapshot_id):
            db.execute("INSERT INTO changes VALUES (?,?,?,?,?,?)",(uid(),actor,now(),snapshot_id,"comparison.deleted",encode({"snapshot_id":snapshot_id})))
        db.execute("DELETE FROM changes WHERE action=? AND target=?",(COHORT_ACTION,snapshot_id))
        db.execute("DELETE FROM changes WHERE action='comparison.request' AND json_extract(detail_json,'$.snapshot_id')=?",(snapshot_id,))
    return set(snapshots)


def purge_deleted(db):
    deleted={row[0] for row in db.execute("SELECT target FROM changes WHERE action='deletion.record'")}
    deleted.update(row[0] for row in db.execute("SELECT case_id FROM cases WHERE deletion_requested=1"))
    purged=set()
    for case_id in deleted:purged.update(purge_case(db,case_id))
    return purged


def _evidence(store,document):
    for pointer in document.evidence:
        try:
            if not pointer.ref.startswith("comparison-evidence/"):raise ValueError("research evidence path")
            data=store.path(pointer.ref).read_bytes()
            if not data or hashlib.sha256(data).hexdigest()!=pointer.hash:raise ValueError("research evidence hash")
        except (OSError,ValueError) as exc:
            raise HTTPException(409,"연구 확인 근거 파일의 고정 참조가 유효하지 않습니다.") from exc


def research_inventory(store,user):
    """Privileged source review only. Never reuse this response for output."""
    with store.connect() as db:
        _account(db,user,admin=True)
        sources,digest=_sources()
        confirmations={source["source_id"]:_record(db,RESEARCH_ACTION,source["source_id"]) for source in sources["sources"]}
        documents,errors={},{}
        for source_id,pointer in confirmations.items():
            try:documents[source_id]=research_document(store,ResearchReferenceV4.model_validate_json(encode(pointer))).model_dump(mode="json") if pointer else None
            except HTTPException as exc:documents[source_id]=None;errors[source_id]=str(exc.detail)
        return {**sources,"sources":[{**source,"scope":target_scope(source["source_id"]).model_dump(mode="json")} for source in sources["sources"]],
            "asset_hash":digest,"confirmations":confirmations,"documents":documents,"document_errors":errors,
            "activations":{source["source_id"]:_record(db,ACTIVATION_ACTION,source["source_id"]) for source in sources["sources"]}}


def research_document(store,pointer):
    pointer=ResearchReferenceV4.model_validate(pointer)
    doc=_read(store,pointer,ResearchConfirmationV4)
    if (doc.confirmation_id,doc.revision)!=(pointer.confirmation_id,pointer.revision):raise HTTPException(409,"연구 확인자료 참조가 다릅니다.")
    _evidence(store,doc)
    return doc


def confirm_research(store,value:ConfirmResearchV4,user):
    value=ConfirmResearchV4.model_validate_json(value.model_dump_json())
    doc=value.document
    _,digest=_source(doc.source_id)
    with store.connect() as db:
        _account(db,user,admin=True)
        prior=_record(db,RESEARCH_ACTION,doc.source_id)
        revision=prior["revision"] if prior else 0
        if revision!=value.expected_revision:raise HTTPException(409,"연구 확인자료 판본이 변경되었습니다.")
    expected=target_scope(doc.source_id).model_dump(mode="json",exclude={"population_requirements"})
    if doc.source_asset_hash!=digest or doc.scope.model_dump(mode="json",exclude={"population_requirements"})!=expected:
        raise HTTPException(422,"연구 확인 범위가 해당 출처·설문 원문·척도와 다릅니다.")
    doc=ResearchConfirmationV4.model_validate_json(encode({**doc.model_dump(mode="json"),"confirmation_id":uid(),"revision":revision+1,"actor":user.username,"recorded_at":now()}))
    _evidence(store,doc)
    file=_write(store,"research",doc)
    pointer=ResearchReferenceV4(confirmation_id=doc.confirmation_id,revision=doc.revision,ref=file.ref,hash=file.hash)
    with store.connect(write=True) as db:
        _account(db,user,admin=True)
        if _record(db,RESEARCH_ACTION,doc.source_id)!=prior:raise HTTPException(409,"연구 확인자료가 동시에 변경되었습니다.")
        if _source(doc.source_id)[1]!=digest or research_document(store,pointer)!=doc:raise HTTPException(409,"연구 근거가 저장 중 변경되었습니다.")
        store.audit(db,user.username,doc.source_id,RESEARCH_ACTION,pointer.model_dump(mode="json"))
        from .external_comparisons_v4 import record_impacts
        record_impacts(store,db,doc.source_id,user.username,"연구 확인자료가 새 판본으로 변경되었습니다. 새 출력에는 다시 선택한 현재 승인 범위가 필요합니다.")
    return pointer


def gate(source,source_hash,confirmation,confirmation_ref,activation,target,population=None):
    """The one gate for API/report/export. No blocked branch contains values."""
    def blocked(reason):return ExternalGateV4(source_id=source["source_id"],status="blocked",reason=reason)
    if confirmation is None:return blocked("D06 연구 확인자료가 없습니다.")
    if activation is None or not activation.enabled:return blocked("관리자 기술 활성화가 꺼져 있습니다.")
    if confirmation.source_id!=source["source_id"] or activation.source_id!=source["source_id"] or confirmation.source_asset_hash!=source_hash:
        return blocked("확인자료와 출처 판본이 다릅니다.")
    if activation.confirmation!=confirmation_ref:return blocked("기술 활성화가 현재 연구 확인자료 판본을 명시하지 않았습니다.")
    if any(getattr(confirmation,key).status!="confirmed" for key in CHECKS):return blocked("문헌·문항·척도·결측·번안/사용·대상 조건의 연구 확인이 미완료입니다.")
    if confirmation.scope.model_dump(mode="json",exclude={"population_requirements"})!=target.model_dump(mode="json",exclude={"population_requirements"}):
        return blocked("입력의 설문·문항·척도·방향·산식·결측 정책이 승인 범위와 다릅니다.")
    if any((population or {}).get(key)!=expected for key,expected in confirmation.scope.population_requirements.items()):
        return blocked("필요한 대상 정보가 없거나 승인된 대상 범위와 다릅니다.")
    return ExternalGateV4(source_id=source["source_id"],status="approved",reason="연구 확인 범위와 별도 관리자 활성화가 모두 일치합니다.",
        scope=confirmation.scope,confirmation=confirmation_ref,activation_revision=activation.revision,
        values=ExternalValuesV4.model_validate_json(encode(source["reference_values"])))


def activate_external(store,value:ActivateExternalV4,user):
    value=ActivateExternalV4.model_validate_json(value.model_dump_json())
    source,digest=_source(value.source_id)
    with store.connect(write=True) as db:
        _account(db,user,admin=True)
        prior=_record(db,ACTIVATION_ACTION,value.source_id)
        revision=prior["revision"] if prior else 0
        if revision!=value.expected_revision:raise HTTPException(409,"외부 비교 활성화 판본이 변경되었습니다.")
        activation=TechnicalActivationV4(source_id=value.source_id,revision=revision+1,actor=user.username,recorded_at=now(),enabled=value.enabled,confirmation=value.confirmation,reason=value.reason)
        if value.enabled:
            latest=_record(db,RESEARCH_ACTION,value.source_id)
            reference=ResearchReferenceV4.model_validate_json(encode(latest)) if latest else None
            doc=research_document(store,reference) if reference else None
            result=gate(source,digest,doc,reference,activation,target_scope(value.source_id),doc.scope.population_requirements if doc else {})
            if result.status!="approved":raise HTTPException(422,result.reason)
        store.audit(db,user.username,value.source_id,ACTIVATION_ACTION,activation.model_dump(mode="json"))
        from .external_comparisons_v4 import record_impacts
        record_impacts(store,db,value.source_id,user.username,"기술 활성화 판본이 변경되었습니다. 기존 발급 파일은 보존하며 현재 제공 조건을 다시 확인합니다.")
    return activation


def external_for_report(store,source_id,target,user,*,population=None):
    target=ComparisonScopeV4.model_validate(target)
    source,digest=_source(source_id)
    with store.connect() as db:
        _account(db,user)
        latest=_record(db,RESEARCH_ACTION,source_id)
        activation=_record(db,ACTIVATION_ACTION,source_id)
        reference=ResearchReferenceV4.model_validate_json(encode(latest)) if latest else None
        try:document=research_document(store,reference) if reference else None
        except HTTPException:
            return ExternalGateV4(source_id=source_id,status="blocked",reason="연구 확인자료 또는 근거 파일이 손상되어 출력을 보류합니다.")
        active=TechnicalActivationV4.model_validate_json(encode(activation)) if activation else None
        return gate(source,digest,document,reference,active,target,population)
