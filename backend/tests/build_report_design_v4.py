"""Reproducible synthetic RP04 HTML/PDF cases for visual verification."""
import argparse
from pathlib import Path

from app.domain.catalog_v4 import load_catalog_v4
from app.domain.comparisons_v4 import CohortPublicV4
from app.domain.report_profile_v4 import ClaimV4, ReportProfileV4
from app.domain.report_render_v4 import ReportHeaderV4
from app.domain.validation_v4 import VOCAL_CODES
from app import report_narrative_v4 as narrative, report_profile_v4 as profiles
from app.report_render_v4 import render_html, survey_rows
from app.report_pdf_v4 import render_pdf
from app.storage import encode
from tests.report_fixture_v4 import fixture
from tests.test_report_narrative_v4 import generated
from tests.test_scoring_ai_v4 import snapshot

VERSION = "report-presentation-20261007-rp04"


def write_previews(output):
    output.mkdir(parents=True, exist_ok=True)
    header = ReportHeaderV4(dog_name="합성 반려견",guardian_name="합성 보호자",participant_id="RP04-SYNTHETIC",event_name="합성 출력 검수",observed_date="2026-10-08",generated_at="2026-10-07T15:00:00Z")
    answers = {f"s{i:02}": 3 for i in range(1,29)}
    answers.update(s10=0,s11=0,s12=0,s13=0,s14=0,s26=1,s27=1,s28=1)
    windows = {entry.window.window_id:entry.window for entry in snapshot().batch.windows}
    values = {item.code: (item.allowed_values[len(item.allowed_values)//2] if item.allowed_values else 1) for item in load_catalog_v4().rated_items()
        if item.usage == "numeric" and item.code not in VOCAL_CODES and windows[item.windows[0]].start_seconds is not None and windows[item.windows[0]].end_seconds is not None}
    def profile(values=None, survey=None):
        final, ref, batch = fixture(values, survey=survey)
        base = profiles.build(final,ref,batch=batch,presentation_version=VERSION)
        result = narrative.apply(base,narrative.normalize(base,generated(narrative.context_for(base)),"gemini-3.8-flash"))
        profiles.validate_profile(result,final,ref,batch=batch)
        return result
    filled = profile(values,answers)
    partial = profile({"개5":-2,"개58":-2,"보23":2},{"s10":0,"s26":1})
    missing = profile()
    long_claim = ClaimV4(claim_id="synthetic:long",text="긴 한국어 근거 설명을 누락 없이 보존하고 다음 쪽에서 이어서 읽습니다. "*220+"마지막검증표식",fact_ids=("policy:scope",))
    long = ReportProfileV4.model_validate_json(filled.model_copy(update={"summary": (long_claim,)}).model_dump_json())
    rows = survey_rows(filled)
    cohort = CohortPublicV4.model_validate_json(encode({"reference":{"snapshot_id":"synthetic-rp04-cohort","revision":1,"ref":"synthetic/cohort.json","hash":"a"*64},"title":"합성 동일 응답 세 개체","survey_version":filled.source.survey.survey_version,"survey_policy":filled.source.survey.policy_version,"selection_count":3,"selection_note":"출력 시험용 동일 응답 세 개체의 합성 자체 집단입니다.","domains":[{"domain":row["title"],"question_ids":row["question_ids"],"scale_minimum":row["minimum"],"scale_maximum":row["maximum"],"mean":row["value"],"n":3 if row["value"] is not None else 0,"excluded_count":0 if row["value"] is not None else 3,"exclusion_reasons":{}} for row in rows]}))
    variants = {"filled":(filled,header,None),"partial":(partial,header,None),"missing":(missing,header,None),"long":(long,header.model_copy(update={"dog_name":"아주 긴 합성 이름 "*12}),None),"comparison":(filled,header,cohort)}
    action = ClaimV4(claim_id="synthetic:action",text="합성 상황에서 편안한 거리를 확보하고 반응을 살펴봐 주세요.",fact_ids=("policy:scope",))
    for count in range(4):
        changed = ReportProfileV4.model_validate_json(filled.model_copy(update={"actions":tuple(action.model_copy(update={"claim_id":"synthetic:action:"+str(index)}) for index in range(count)),"actions_notice":"현재 도움 근거가 부족합니다." if not count else None}).model_dump_json())
        variants["actions"+str(count)] = (changed,header,None)
    for name,(result,title,cohort) in variants.items():
        (output/(name+".html")).write_bytes(render_html(result,title,cohort=cohort))
        (output/(name+".pdf")).write_bytes(render_pdf(result,title,cohort=cohort))
    (output/"expected.json").write_text(encode({"variants":list(variants),"survey":rows,"long_marker":"마지막검증표식","note":"모든 자료는 합성이며 전문적 정답·실제 공급자 결과가 아닙니다."}),encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    write_previews(parser.parse_args().output.resolve())
