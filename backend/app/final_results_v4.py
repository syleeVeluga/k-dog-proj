"""Explicit S1 event assembly without changing original scores or prior publications."""
import hashlib
import json
import os

from fastapi import HTTPException
from pydantic import field_validator

from . import judgements_v4 as judgements, opinions_v4 as opinions, sheets_v4 as sheets
from .domain.final_results_v4 import (DOMAIN_LABELS, FinalDomainV4, FinalReferenceV4, FinalResultV4,
                                      OpinionReferenceV4)
from .domain.results_v4 import ResultReferenceV4
from .input_models import Model
from .storage import encode, now, uid


class AssembleFinalV4(Model):
    basic: ResultReferenceV4
    opinion: OpinionReferenceV4 | None = None
    viewer_sheet_id: str | None = None
    reason: str

    @field_validator("basic", "opinion", mode="before")
    @classmethod
    def contracts(cls, value, info):
        model = ResultReferenceV4 if info.field_name == "basic" else OpinionReferenceV4
        return model.model_validate_json(encode(value)) if isinstance(value, dict) else value

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value):
        if not value.strip() or len(value) > 4000:
            raise ValueError("최종 입력을 선택한 사유가 필요합니다.")
        return value


class FinalViewV4(Model):
    reference: FinalReferenceV4
    document: FinalResultV4

    @field_validator("reference", "document", mode="before")
    @classmethod
    def contracts(cls, value, info):
        model = FinalReferenceV4 if info.field_name == "reference" else FinalResultV4
        return model.model_validate_json(encode(value)) if isinstance(value, dict) else value


class FinalSummaryV4(Model):
    reference: FinalReferenceV4
    recorded_at: str
    actor: str
    basic: ResultReferenceV4
    opinion: OpinionReferenceV4 | None
    requires_reveal: bool = False

    @field_validator("reference", "basic", "opinion", mode="before")
    @classmethod
    def contracts(cls, value, info):
        model = {"reference": FinalReferenceV4, "basic": ResultReferenceV4, "opinion": OpinionReferenceV4}[info.field_name]
        return model.model_validate_json(encode(value)) if isinstance(value, dict) else value


def domains_for(basic, opinion):
    automatic = {item.key: item for item in basic.automatic_decisions}
    manual = {item.key: item for item in basic.manual_decisions}
    effective = {item.key: item for item in basic.decisions}
    entries = {item.domain: item for item in opinion.domains} if opinion and opinion.state == "complete" else {}
    observations = {item.code: item for item in sheets.analysis_input(basic.input_document).observations}
    source_codes = {"people_response": ("개13", "개55", "개15", "개51", "개52", "개54", "개16", "개14", "개53"),
                    "nonsocial_response": ("개30", "개34", "보14"), "environment": ("개5", "개6", "개8", "환경1"), "tendency": ()}
    result = []
    for domain in DOMAIN_LABELS:
        key = {"attachment": "attachment_type", "education_attitude": "owner_type"}.get(domain)
        original = automatic[key].label if key else None
        item = entries.get(domain)
        if item and item.text.strip():
            choice, issue = opinions.selection(item, basic, opinion.evaluator)
            result.append(FinalDomainV4(domain=domain, label=choice.label if choice else None, text=item.text,
                source="completed_opinion", status="selected" if choice else "policy_pending" if key else "observation_text",
                reason="완료된 해당 영역 의견과 명시한 유효 유형 적용" if choice else
                    ("D04: 자유서술에서 유형을 추정하지 않음; " + (issue or "상세 해석 계약 대기")) if key else "완료된 해당 영역 원문 의견 보존; 유형 추론 없음",
                evidence_codes=item.evidence_codes, counter_codes=item.counter_codes, counter_note=item.counter_note,
                original_label=original, opinion_revision=opinion.revision))
            continue
        choice = manual.get(key)
        if choice and choice.status == "complete":
            try:
                judgements.validate_judgement(choice, basic)
            except ValueError:
                choice = None
        else:
            choice = None
        if choice:
            result.append(FinalDomainV4(domain=domain, label=choice.label, source="manual_selection", status="selected",
                reason=choice.reason, evidence_codes=choice.evidence_codes, counter_codes=choice.counter_codes,
                counter_note=choice.counter_note, original_label=original))
        elif key:
            value = effective[key]
            result.append(FinalDomainV4(domain=domain, label=value.label, source="basic", status="draft" if value.label else "policy_pending" if key == "attachment_type" else "missing",
                reason=value.reason, evidence_codes=value.evidence_codes, counter_codes=value.counter_codes,
                counter_note=value.counter_note, original_label=original))
        else:
            codes = tuple(code for code in source_codes[domain] if code in observations and observations[code].status == "observed"
                          and observations[code].validity in ("valid", "caution"))
            result.append(FinalDomainV4(domain=domain, source="basic", status="facts_available" if codes else "missing",
                reason="확인된 기본 원관찰을 그대로 연결; 설명 작성은 별도 단계" if codes else "이 영역에 연결된 확정 해석 없음; 없는 유형·사실을 생성하지 않음",
                evidence_codes=codes))
    return tuple(result)


def read_document(store, ref, digest):
    try:
        if not ref.startswith("finals/"):
            raise ValueError("final path")
        payload = store.path(ref).read_bytes()
        if hashlib.sha256(payload).hexdigest() != digest:
            raise ValueError("final hash")
        doc = FinalResultV4.model_validate_json(payload)
        if judgements.read_result(store, doc.basic.ref, doc.basic.hash) != doc.basic_document:
            raise ValueError("basic snapshot")
        if doc.opinion and opinions.read_document(store, doc.opinion.ref, doc.opinion.hash) != doc.opinion_document:
            raise ValueError("opinion snapshot")
        if domains_for(doc.basic_document, doc.opinion_document) != doc.domains:
            raise ValueError("domain priority")
        return doc
    except (OSError, ValueError) as exc:
        raise HTTPException(409, "S1 최종 결과 또는 부모 참조가 손상되었습니다.") from exc


def write_document(store, data):
    doc = FinalResultV4.model_validate_json(encode(data))
    payload = doc.model_dump_json().encode()
    ref = f"finals/{doc.case_id}/{doc.final_id}.json"
    path = store.path(ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return FinalReferenceV4(final_id=doc.final_id, ref=ref, hash=hashlib.sha256(payload).hexdigest())


def assemble(store, case_id, session_id, value: AssembleFinalV4, user):
    from . import disclosures_v4 as disclosures
    value = AssembleFinalV4.model_validate_json(value.model_dump_json())
    with store.connect() as db:
        case = opinions.context(store, db, case_id, session_id, user)
        basic_row, basic = opinions.selected_basic(store, db, case_id, session_id, value.basic, user, value.viewer_sheet_id)
        latest = opinions.latest(store, db, case_id, session_id)
        if value.opinion != latest:
            raise HTTPException(409, "현재 의견 revision을 명시적으로 연결하세요. 누락·철회 전 의견으로 완료 의견을 우회할 수 없습니다.")
        opinion = opinions.read_document(store, value.opinion.ref, value.opinion.hash) if value.opinion else None
        if opinion:
            disclosures.require(db, case_id, session_id, user, disclosures.target("opinion", value.opinion), opinion.actor)
        if opinion and opinion.basic != value.basic:
            raise HTTPException(409, "의견과 행사 기본 입력이 다릅니다. 명시적으로 재개방·연결하세요.")
    domains = domains_for(basic, opinion)
    identities = sheets._source_identities(store, basic.input_document.source)
    priority = opinion.priority_help.strip() if opinion and opinion.state == "complete" else ""
    data = {"final_id": uid(), "case_id": case_id, "session_id": session_id, "actor": user.username, "recorded_at": now(),
        "change_reason": value.reason, "basic": value.basic.model_dump(mode="json"), "basic_document": basic.model_dump(mode="json"),
        "opinion": value.opinion.model_dump(mode="json") if value.opinion else None,
        "opinion_document": opinion.model_dump(mode="json") if opinion else None, "domains": [item.model_dump(mode="json") for item in domains],
        "priority_help": priority or None,
        "independent_ai": basic.input_document.sheet.rater_kind == "ai" and all(item.source == "basic" for item in domains) and not priority}
    link = write_document(store, data)
    with store.connect(write=True) as db:
        current = opinions.context(store, db, case_id, session_id, user)
        if current["input_revision"] != case["input_revision"] or opinions.latest(store, db, case_id, session_id) != latest:
            raise HTTPException(409, "최종 조립 중 입력 또는 의견이 변경되었습니다.")
        new_row, new_basic = opinions.selected_basic(store, db, case_id, session_id, value.basic, user, value.viewer_sheet_id)
        if tuple(new_row) != tuple(basic_row) or new_basic != basic:
            raise HTTPException(409, "최종 조립 중 기본 결과가 변경되었습니다.")
        sheets._unchanged_sources(store, basic.input_document.source, identities)
        if value.opinion:
            opinions.read_document(store, value.opinion.ref, value.opinion.hash)
        read_document(store, link.ref, link.hash)
        store.audit(db, user.username, case_id, "final.s1.publish", {**link.model_dump(mode="json"), "session_id": session_id})
    return {"reference": link.model_dump(mode="json"), "document": FinalResultV4.model_validate_json(encode(data)).model_dump(mode="json")}


def list_results(store, case_id, session_id, user, viewer_sheet_id=None):
    from . import disclosures_v4 as disclosures
    result = []
    with store.connect() as db:
        opinions.context(store, db, case_id, session_id, user)
        for row in db.execute("SELECT detail_json FROM changes WHERE target=? AND action='final.s1.publish' ORDER BY rowid DESC", (case_id,)):
            value = json.loads(row["detail_json"])
            if value.get("session_id") != session_id:
                continue
            link = FinalReferenceV4.model_validate_json(encode({key: value[key] for key in ("final_id", "ref", "hash")}))
            doc = read_document(store, link.ref, link.hash)
            result.append({"reference": link.model_dump(mode="json"), "recorded_at": doc.recorded_at, "actor": doc.actor,
                           "basic": doc.basic.model_dump(mode="json"), "opinion": doc.opinion.model_dump(mode="json") if doc.opinion else None,
                           "requires_reveal": not disclosures.allowed(db, case_id, session_id, user, disclosures.target("final", link), doc.actor)})
    return result


def view(store, case_id, session_id, final_id, user, viewer_sheet_id=None):
    from . import disclosures_v4 as disclosures
    with store.connect() as db:
        opinions.context(store, db, case_id, session_id, user)
        for row in db.execute("SELECT detail_json FROM changes WHERE target=? AND action='final.s1.publish' ORDER BY rowid DESC", (case_id,)):
            value = json.loads(row["detail_json"])
            if value.get("session_id") == session_id and value.get("final_id") == final_id:
                doc = read_document(store, value["ref"], value["hash"])
                opinions.selected_basic(store, db, case_id, session_id, doc.basic, user, viewer_sheet_id)
                disclosures.require(db, case_id, session_id, user, disclosures.target("final", value), doc.actor)
                return {"reference": {key: value[key] for key in ("final_id", "ref", "hash")}, "document": doc.model_dump(mode="json")}
    raise HTTPException(404, "S1 최종 결과를 찾을 수 없습니다.")
