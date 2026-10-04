"""Shared wholly synthetic report inputs, independent of a live provider."""
from app import analysis, final_results_v4 as finals, judgements_v4 as judgements, scoring_ai_v4 as ai
from app.domain.catalog_v4 import load_catalog_v4
from app.domain.final_results_v4 import FinalReferenceV4, FinalResultV4, OpinionDocumentV4, OpinionReferenceV4
from app.domain.results_v4 import BasicResultV4, CalculationConditionsV4, ResultReferenceV4
from app.domain.sheets_v4 import SheetReferenceV4
from app.scoring_v4 import RULE_HASH, RULE_VERSION, calculate, verify_rules
from app.storage import encode
from tests.test_scoring_ai_v4 import snapshot


def fixture(values=None, *, cameras=1, survey=None, opinion=None, exceptions=None, evidence=None, scene_codes=()):
    source = snapshot(cameras)
    if survey:
        source.session.survey.update(survey)
    indexed = {item.window.window_id:item.window for item in source.batch.windows}
    rows = []
    for item in load_catalog_v4().rated_items():
        if item.code not in (values or {}):
            rows.append({"code":item.code,"value":None,"status":"unobserved","reason":"synthetic missing"})
            continue
        window = indexed[item.windows[0]]
        start,end = window.start_seconds,window.end_seconds
        if item.code in ("개38","개39","개40","개41","개42","개43"):
            phase = source.session.recording_s1.walk_phases[int(item.code[1:])-38]
            start,end = phase.start_sec,phase.end_sec
        if start is None or end is None:
            raise ValueError("synthetic event fixture must define the observation window")
        rows.append({"code":item.code,"value":values[item.code],"status":"observed","opportunity":"present","validity":"valid","whole_interval_observed":True,
            "evidence":[{"video_id":"v1","video_sha256":"1"*64,"camera_id":"CAM1","window_id":window.window_id,
                         "start_seconds":start,"end_seconds":end,"observed_seconds":end-start,"note":"synthetic actual evidence"}]})
        if evidence and item.code in evidence:
            rows[-1]["evidence"] = evidence[item.code]
    doc = ai.sheet_document(source,rows,{},"2026-10-04T00:00:00+00:00","synthetic-report")
    if exceptions:
        phases = tuple(phase.model_copy(update={"proximity_exception":exceptions[i]}) for i,phase in enumerate(doc.sheet.walk_phases))
        doc = doc.model_copy(update={"sheet":doc.sheet.model_copy(update={"walk_phases":phases})})
    ref = SheetReferenceV4(sheet_id=doc.sheet.sheet_id,revision=1,ref="sheets/case/synthetic/r1.json",hash=analysis.digest(doc.model_dump(mode="json")))
    calculated = calculate(doc)
    decisions = judgements.initial_decisions(doc,ref,calculated)
    basic = BasicResultV4.model_validate_json(encode({"result_id":"basic-synthetic","case_id":source.case_id,"session_id":source.session_id,
        "revision":1,"actor":"op","recorded_at":"2026-10-04","change_reason":"synthetic","input":ref.model_dump(mode="json"),
        "input_document":doc.model_dump(mode="json"),"rule_version":RULE_VERSION,"rule_hash":RULE_HASH,"rule_snapshot":verify_rules(),
        "conditions":CalculationConditionsV4().model_dump(mode="json"),"evaluation_context":{"purpose":"independent","ai_exposed":False},
        "calculations":calculated.model_dump(mode="json"),"automatic_decisions":decisions,"decisions":decisions,
        "decision_sources":{item["key"]:"automatic" for item in decisions}}))
    basic_ref = ResultReferenceV4(result_id=basic.result_id,revision=1,ref="results/case/synthetic/r1.json",hash=analysis.digest(basic.model_dump(mode="json")))
    if scene_codes:
        opinion = {"domains":[{"domain":"people_response","text":"확인한 장면을 중심으로 살펴보았습니다.","evidence_codes":scene_codes,
            "scene_refs":[basis.model_dump(mode="json") for row in doc.sheet.observations if row.code in scene_codes for basis in row.evidence]}]}
    opinion_doc = OpinionDocumentV4.model_validate_json(encode({"opinion_id":"opinion-synthetic","case_id":source.case_id,"session_id":source.session_id,
        "revision":1,"actor":"op","recorded_at":"2026-10-04","change_reason":"synthetic","basic":basic_ref.model_dump(mode="json"),
        "evaluator":"synthetic evaluator","completion_requested":True,"state":"complete",**opinion})) if opinion else None
    opinion_ref = OpinionReferenceV4(opinion_id=opinion_doc.opinion_id,revision=1,ref="opinions/case/synthetic/r1.json",hash=analysis.digest(opinion_doc.model_dump(mode="json"))) if opinion_doc else None
    final = FinalResultV4(final_id="final-synthetic",case_id=source.case_id,session_id=source.session_id,actor="op",recorded_at="2026-10-04",change_reason="synthetic",
        basic=basic_ref,basic_document=basic,opinion=opinion_ref,opinion_document=opinion_doc,domains=finals.domains_for(basic,opinion_doc),
        priority_help=opinion_doc.priority_help or None if opinion_doc else None,independent_ai=opinion_doc is None)
    pointer = FinalReferenceV4(final_id=final.final_id,ref="finals/case/synthetic.json",hash=analysis.digest(final.model_dump(mode="json")))
    return final,pointer,source.batch
