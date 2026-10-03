"""Deterministic S1 report content from pinned results, never a second judgement."""
import hashlib
import json
import re

from fastapi import HTTPException

from . import analysis, final_results_v4 as finals, report_scenes_v4 as scenes, sheets_v4 as sheets
from .domain.catalog_v3 import SurveyCatalogV3
from .domain.catalog_v4 import RESOURCES, load_catalog_v4, load_mapping_v4, validate_source_references_v4
from .domain.final_results_v4 import FinalReferenceV4, FinalResultV4
from .domain.report_profile_v4 import (CONTENT_VERSION, SELECTION_VERSION, ClaimV4, FactV4, ReportCardV4,
    ReportProfileV4, ReportSectionV4, ReportSourceV4, SceneV4, SurveyComparisonV4, TimelineIntervalV4, ValidationIssueV4)
from .domain.preprocess_v4 import FileV4
from .survey_v4 import survey_scores_v4
from .storage import encode

ASSETS = ("report/content-v4.json", "report/feedback-candidates-v4.json", "mappings/results-v4.json",
          "mappings/survey-behavior-v4.json", "catalogs/behavior-v4.json", "catalogs/survey-v3.json", "rules/survey-policy-v4.json")


def assets():
    hashes = {name: hashlib.sha256((RESOURCES/name).read_bytes()).hexdigest() for name in ASSETS}
    content = json.loads((RESOURCES/ASSETS[0]).read_bytes())
    candidates = json.loads((RESOURCES/ASSETS[1]).read_bytes())
    validate_source_references_v4(content)
    validate_source_references_v4(candidates)
    if (content["version"], content["selection_version"], content["approved_sentence_bank"], len(candidates["items"])) != (CONTENT_VERSION, SELECTION_VERSION, False, 126):
        raise ValueError("report content/candidate policy differs from the pinned S1 contract")
    return content, hashes


def build(final, final_ref, *, batch=None, common_events=()):
    final = FinalResultV4.model_validate(final)
    final_ref = FinalReferenceV4.model_validate(final_ref)
    if final.final_id != final_ref.final_id or finals.domains_for(final.basic_document, final.opinion_document) != final.domains:
        raise ValueError("final result identity or domain priority differs")
    basic = final.basic_document
    doc = basic.input_document
    if doc.source.asset_hashes != sheets.asset_hashes():
        raise ValueError("report source uses another catalog/rule edition")
    sheet = sheets.analysis_input(doc)
    sheets.validate_observations(doc, sheet.model_dump(mode="json"), complete=True)
    if batch is not None and (doc.source.preprocess is None or (batch.batch_id, batch.case_id, batch.session_id, batch.input_revision, batch.input.hash) !=
            (doc.source.batch_id, final.case_id, final.session_id, doc.source.input_revision, doc.source.input.manifest_hash)):
        raise ValueError("report batch belongs to another source")
    if doc.source.preprocess is not None and batch is None:
        raise ValueError("pinned preprocessing batch must be supplied and verified")
    policy, hashes = assets()
    templates = policy["templates"]
    catalog = {item.code: item for item in load_catalog_v4().rated_items()}
    survey_catalog = SurveyCatalogV3.model_validate_json((RESOURCES/"catalogs/survey-v3.json").read_bytes())
    survey = survey_scores_v4(doc.source.session, survey_catalog)
    source = ReportSourceV4(final=final_ref, basic=final.basic, sheet=basic.input, input=doc.source.input,
        batch=doc.source.preprocess, survey=survey, asset_hashes=hashes,
        common_events_hash=analysis.digest([event.model_dump(mode="json") for event in common_events]),
        event_sources=tuple(FileV4(ref=ref,hash=digest) for ref,digest in sorted({(event.source_ref,event.source_hash) for event in common_events})))
    source_hash = analysis.digest(source.model_dump(mode="json"))
    observations = {item.code: item for item in sheet.observations if scenes.usable(item)}
    metrics = {item.key: item for item in basic.calculations.metrics}
    domains = {item.domain: item for item in final.domains}
    facts, issues = {}, []

    def fact(key, kind, value, *, codes=(), evidence=(), refs=(), unit=None, label=None):
        facts[key] = FactV4(fact_id=key, kind=kind, value=value, item_codes=tuple(codes), evidence=tuple(evidence),
                            source_refs=tuple(refs) or (final_ref.ref,), unit=unit,label=label)
        return key

    def claim(key, text, ids, human=False, expected_type=None, type_family=()):
        if scenes.placeholder(text):
            issues.append(ValidationIssueV4(code="placeholder_text", target=key, reason="예시·작성 지시문은 보호자 설명에 사용할 수 없습니다.", blocking=True))
            return None
        if type_family and any(name in text for name in type_family if name != expected_type):
            issues.append(ValidationIssueV4(code="contradictory_type" if expected_type else "unresolved_type_text", target=key,
                reason="명시한 최종 유형과 연결되지 않은 유형명이 설명에 포함되어 검토가 필요합니다.", blocking=True))
            return None
        if human:
            # Only the confirmed walking statement grammar is machine-checked.
            # Other human prose remains attributed verbatim, never AI-verified.
            pattern = r"(?:여섯|6)\s*(?:개\s*)?국면\s*중\s*(\d+)\s*(?:개|국면)(?:[^.%\n]{0,40}?\(?\s*(\d+(?:\.\d+)?)\s*%)?"
            for match in re.finditer(pattern,text):
                walk = metrics.get("개27")
                expected = float(walk.value)*100 if walk and walk.status=="calculated" and walk.value is not None else None
                percent = match.group(2)
                digits = len(percent.split('.',1)[1]) if percent and '.' in percent else 0
                if (expected is None or int(match.group(1)) != walk.numerator or
                        percent is not None and float(percent) != round(expected,digits)):
                    issues.append(ValidationIssueV4(code="walking_claim_mismatch",target=key,
                        reason="사람 문장의 여섯 국면 수·비율이 고정된 함께걷기 산출값과 일치하지 않아 검토가 필요합니다.",blocking=True))
                    return None
        return ClaimV4(claim_id=key, text=text, fact_ids=tuple(ids), validation="human_verbatim" if human else "source_verified")

    def keep(*values):
        return tuple(value for value in values if value is not None)

    for code, item in observations.items():
        label = next((entry.text for entry in catalog[code].labels if entry.value==item.value),None)
        fact("observation:"+code, "observation", item.value, codes=(code,), evidence=tuple(basis for basis in item.evidence if not scenes.placeholder(basis.note)), refs=(basic.input.ref,),
            unit="회" if code in scenes.COUNT_CODES else "범주 원값",label=label)
    for key, item in metrics.items():
        if item.status == "calculated" and item.value is not None and not item.internal_only:
            fact("metric:"+key, "metric", item.value, codes=item.used_codes, refs=(final.basic.ref,), unit="국면 비율" if key == "개27" else None)
    for key, item in domains.items():
        fact("final:"+key, "final_type", item.label, codes=item.evidence_codes, refs=(final_ref.ref,))
        if item.text:
            fact("opinion:"+key, "opinion", item.text, codes=item.evidence_codes, refs=(final.opinion.ref,))
    fact("policy:scope", "policy", "S1 실제 관찰 범위와 명시된 계산만 사용")
    fact("policy:survey", "policy", templates["survey_separation"])
    fact("policy:contact", "policy", templates["contact_caution"])
    fact("policy:noise", "policy", templates["noise_no_task"])
    fact("policy:walking", "policy", templates["walking_meaning"])

    def observation_claim(code, prefix="detail"):
        if code not in observations:
            return None
        item, definition = observations[code], catalog[code]
        label = next((label.text for label in definition.labels if label.value == item.value), None)
        if label is None:
            # Count values remain counts, never constructed occurrences or mind states.
            label = f"관찰 범위에서 {item.value}회 기록됨" if code in scenes.COUNT_CODES else str(item.value)
        return claim(prefix+":"+code, f"{definition.segment_label}: {label}", ("observation:"+code,))

    cards = []
    from .domain.contracts_v4 import ATTACHMENT_TYPES, OWNER_TYPES
    for key, title in (("education_attitude", "보호자 교육태도"), ("attachment", "반려견과 보호자의 애착관계")):
        item = domains[key]
        lines = [claim("card:"+key, templates["selected_type"].format(title=title,label=item.label) if item.label else templates["missing_type"].format(title=title), ("final:"+key,))]
        if item.text:
            lines.append(claim("card-opinion:"+key, item.text, ("opinion:"+key,), human=True, expected_type=item.label,
                type_family=OWNER_TYPES if key=="education_attitude" else ATTACHMENT_TYPES))
        cards.append(ReportCardV4(key=key,title=title,status="available" if item.label else "held",label=item.label,claims=keep(*lines)))
    social_lines = []
    people_codes = ("개13", "개55", "개15", "개51", "개52", "개54", "개16", "개14", "개53")
    for domain, fallback in (("people_response", people_codes), ("nonsocial_response", ("개30", "개34"))):
        item = domains[domain]
        if item.text:
            social_lines.append(claim("card-opinion:"+domain,item.text,("opinion:"+domain,),human=True))
        else:
            found = [observation_claim(code,"card-social") for code in fallback if code in observations]
            social_lines.extend(found or [claim("card-missing:"+domain, "사람 반응을 더 확인해야 합니다." if domain == "people_response" else "물건에 대한 반응을 더 확인해야 합니다.", ("policy:scope",))])
    people = bool(domains["people_response"].text or any(code in observations for code in people_codes))
    nonsocial = bool(domains["nonsocial_response"].text or any(code in observations for code in ("개30","개34")))
    cards.append(ReportCardV4(key="social",title="사회성: 사람 반응·비사회적 반응",status="available" if people and nonsocial else "partial" if people or nonsocial else "insufficient",claims=keep(*social_lines)))
    walk = metrics.get("개27")
    valid_walk = walk is not None and walk.status == "calculated" and walk.value is not None
    if valid_walk:
        walk_text = templates["walking"].format(numerator=walk.numerator,percent=f"{float(walk.value)*100:.1f}".rstrip("0").rstrip("."))
        walk_claims = [claim("card:walking",walk_text,("metric:개27",)),claim("walking:meaning",templates["walking_meaning"],("policy:walking",))]
        if walk.caution:
            walk_claims.append(claim("walking:caution","걷기 절차에 주의 조건이 있어 관찰 범위와 함께 해석해 주세요.",("metric:개27",)))
    else:
        walk_claims = [claim("card:walking",templates["walking_missing"],("policy:walking",))]
    cards.append(ReportCardV4(key="walking",title="함께걷기",status="available" if valid_walk else "insufficient",claims=keep(*walk_claims)))

    chosen, scene_review = scenes.select(final, common_events)
    selected_scenes = []
    for index, item in enumerate(chosen):
        selected_scenes.append(SceneV4(scene_id="scene-"+analysis.digest(item.event_id)[:16],common_event_id=item.event_id,domain=item.domain,
            title=catalog[item.codes[0]].segment_label+"에서 확인한 장면",claims=keep(*(observation_claim(code,"scene:"+item.event_id) for code in item.codes)),
            evidence=item.evidence,reference_start_seconds=item.start,reference_end_seconds=item.end,
            priority="completed_opinion" if item.nominated else "before_after" if item.changed else "domain_diversity"))

    comparisons = []
    mappings = {entry["question_id"]: entry for entry in load_mapping_v4("survey-behavior")["entries"]}
    for item in survey.items:
        mapping = mappings["Q"+item.item_id[1:]]
        key = fact("survey:"+item.item_id,"survey",item.converted,refs=(doc.source.input.manifest_ref,),unit="0~4" if 10 <= int(item.item_id[1:]) <= 14 else "1~5")
        raw_key = fact("survey-raw:"+item.item_id,"survey",item.raw,refs=(doc.source.input.manifest_ref,),unit="0~4" if 10 <= int(item.item_id[1:]) <= 14 else "1~5")
        video_ids = tuple("observation:"+code for code in mapping["behavior_codes"] if code in observations)
        text = f"평소 설문 응답: {item.converted}" if item.converted is not None else "평소 설문 응답이 아직 없습니다."
        if item.reverse_scored and item.raw is not None:
            text = f"평소 설문 원응답: {item.raw}, 역채점 값: {item.converted}"
        noise = item.item_id == "s12"
        comparisons.append(SurveyComparisonV4(key=item.item_id,title=next(q.text for q in survey_catalog.items if q.item_id==item.item_id),
            survey_fact_ids=(raw_key,key),video_fact_ids=() if noise else video_ids,direct_video_task=not noise and bool(mapping["behavior_codes"]),
            claims=keep(claim("survey:"+item.item_id,text,(raw_key,key)),claim("compare:"+item.item_id,templates["noise_no_task"] if noise else templates["survey_separation"],("policy:noise" if noise else "policy:survey",)))))

    details = []
    relationship = keep(*(observation_claim(code) for code in ("개9","개10","개58","개18","개19")))
    safe = basic.calculations.safe_base
    if safe.status == "confirmed_sequence":
        ids = []
        for event_id, seconds in zip(safe.event_ids,safe.reference_seconds):
            ids.append(fact("event:"+event_id,"recorded_event",seconds,refs=(doc.source.input.manifest_ref,),unit="공통 시각 초"))
        relationship += keep(claim("safe-base:sequence",f"실제 공통 시각 {safe.reference_seconds[0]:g}초 접근, {safe.reference_seconds[1]:g}초 접촉, {safe.reference_seconds[2]:g}초 탐색 재개 순서가 기록되었습니다.",ids))
    else:
        relationship += keep(claim("safe-base:missing","접촉 뒤 탐색을 다시 시작한 실제 순서는 아직 모두 확인되지 않았습니다.",("policy:scope",)))
    details.append(ReportSectionV4(key="relationship",title="관계와 장면",status="available" if safe.status == "confirmed_sequence" else "partial" if len(relationship)>1 else "insufficient",claims=relationship))
    contact = keep(observation_claim("개19","contact"),observation_claim("개51","contact"))
    if contact:
        contact += keep(claim("contact:caution",templates["contact_caution"],("policy:contact",)))
    details.append(ReportSectionV4(key="contact_comparison",title="접촉 장면의 행동 비교",status="available" if len(contact)==3 else "partial" if contact else "insufficient",claims=contact))
    environment = keep(*(observation_claim(code) for code in ("개8","개12","환경1","개30","개34")))
    if domains["environment"].text:
        environment = keep(claim("detail-opinion:environment",domains["environment"].text,("opinion:environment",),human=True)) + environment
    if metrics.get("object_change") and metrics["object_change"].status == "calculated":
        environment += keep(claim("object:change",f"같은 물건에 대한 입장·퇴장 관찰: {metrics['object_change'].value}",("metric:object_change",)))
    details.append(ReportSectionV4(key="environment",title="환경을 살핀 모습",status="available" if environment else "insufficient",claims=environment))
    details.append(ReportSectionV4(key="walking",title="함께걷기의 여섯 국면",status="available" if valid_walk else "insufficient",claims=cards[-1].claims))
    if domains["tendency"].text:
        details.append(ReportSectionV4(key="tendency",title="함께 살펴볼 성향",status="available",
            claims=keep(claim("detail-opinion:tendency",domains["tendency"].text,("opinion:tendency",),human=True))))
    summary = tuple(card.claims[0] for card in cards if card.claims and card.status in ("available","partial"))
    actions = []
    if final.priority_help:
        key = fact("opinion:priority_help","opinion",final.priority_help,refs=(final.opinion.ref,))
        actions = list(keep(claim("action:priority_help",final.priority_help,(key,),human=True)))
    elif "개15" in observations and "개51" not in observations:
        contact_absent = any(event.kind == "stranger_contact_start" and event.status == "not_occurred" for event in doc.source.session.recording_s1.events)
        if contact_absent:
            actions = list(keep(claim("action:approach_without_contact",templates["approach_without_contact_advice"],("observation:개15",))))
    status = "review_required" if any(issue.blocking for issue in issues) else "partial" if any(card.status != "available" for card in cards) or scene_review else "ready"
    capture = doc.source.session.recording_s1
    videos = {video.video_id:video for video in doc.source.session.videos}
    timeline = []
    for kind, intervals in (("segment",capture.segments),("walk_phase",capture.walk_phases)):
        for interval in intervals:
            offset = capture.offset(interval.video_id)
            video = videos[interval.video_id]
            timeline.append(TimelineIntervalV4(key=interval.segment if kind=="segment" else interval.phase,kind=kind,
                video_id=video.video_id,camera_id=video.camera_id,video_sha256=video.sha256,state=interval.state,
                source_start_seconds=interval.start_sec,source_end_seconds=interval.end_sec,
                reference_start_seconds=interval.start_sec-offset if interval.start_sec is not None and offset is not None else None,
                reference_end_seconds=interval.end_sec-offset if interval.end_sec is not None and offset is not None else None,reason=interval.reason))
    return ReportProfileV4(profile_id="profile-"+source_hash[:24],case_id=final.case_id,session_id=final.session_id,source=source,source_hash=source_hash,
        status=status,timeline=tuple(timeline),cards=tuple(cards),facts=tuple(facts.values()),scenes=tuple(selected_scenes),scene_notice=templates["no_scenes"] if not selected_scenes else None,
        scene_review=scene_review,comparisons=tuple(comparisons),details=tuple(details),summary=summary,actions=tuple(actions),
        actions_notice=templates["actions_missing"] if not actions else None,validation_issues=tuple(issues))


def validate_profile(profile, final, final_ref, *, batch=None, common_events=()):
    profile = ReportProfileV4.model_validate(profile)
    expected = build(final, final_ref, batch=batch, common_events=common_events)
    if profile != expected:
        raise ValueError("report contains an unsupported claim, value, type, scene, source, or policy")
    return profile


def from_final(store, case_id, session_id, final_id, user, viewer_sheet_id=None):
    shown = finals.view(store,case_id,session_id,final_id,user,viewer_sheet_id)
    final = FinalResultV4.model_validate_json(encode(shown["document"]))
    pointer = FinalReferenceV4.model_validate_json(encode(shown["reference"]))
    doc = final.basic_document.input_document
    batch = None
    if doc.source.preprocess:
        from .preprocess_v4 import verified_batch
        batch = verified_batch(store,case_id,session_id,FileV4(ref=doc.source.preprocess.ref,hash=doc.source.preprocess.hash),user.username,
            expected_input=FileV4(ref=doc.source.input.manifest_ref,hash=doc.source.input.manifest_hash),expected_revision=doc.source.input_revision)
    common = []
    if doc.ai_run_id:
        from . import run_v4
        from .domain.runs_v4 import RunConfigV4
        with store.connect() as db:
            row = run_v4.row_for(store,db,doc.ai_run_id)
            snapshot = run_v4.snapshot_for(row)
            config = RunConfigV4.model_validate_json(row["config_snapshot_json"])
            stages = {stage.key:stage for stage in config.stages if stage.stage=="score_v4"}
            for step in db.execute("SELECT * FROM steps WHERE run_id=? AND stage='score_v4' AND status='succeeded'",(doc.ai_run_id,)):
                common.extend(scenes.events_from_ai(snapshot,stages[step["branch_key"]],analysis.step_payload(store,row,step),step["output_ref"],step["output_hash"]))
    identities = sheets._source_identities(store,doc.source)
    result = build(final,pointer,batch=batch,common_events=tuple(common))
    with store.connect() as db:
        from .opinions_v4 import selected_basic
        selected_basic(store,db,case_id,session_id,final.basic,user,viewer_sheet_id)
        sheets._unchanged_sources(store,doc.source,identities)
        if finals.read_document(store,pointer.ref,pointer.hash) != final:
            raise HTTPException(409,"고정 최종 결과가 달라졌습니다.")
        for source in result.source.event_sources:
            try:
                valid = hashlib.sha256(store.path(source.ref).read_bytes()).hexdigest() == source.hash
            except OSError:
                valid = False
            if not valid:
                raise HTTPException(409,"고정 장면 사건 원자료가 달라졌습니다.")
    # Recheck interpretation disclosure as well as the underlying score access.
    # A formerly allowed opinion/final must not remain readable after revocation.
    current = finals.view(store,case_id,session_id,final_id,user,viewer_sheet_id)
    if current["reference"] != shown["reference"] or current["document"] != shown["document"]:
        raise HTTPException(409,"고정 최종 결과가 달라졌습니다.")
    return result
