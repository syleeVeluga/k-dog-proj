"""Pinned attachment requests and validation; no provider calls from read paths."""
import json
from types import SimpleNamespace
from pathlib import Path
from . import analysis, judgements_v4 as judgements, sheets_v4 as sheets
from .domain.attachment_v4 import AttachmentAssessmentV4, AttachmentResponseV4
from .domain.contracts_v4 import DecisionV4
from .domain.results_v4 import CalculationsV4
from .gemini import ProviderError
from .gemini_v4 import GeminiScorerV4
from .storage import encode

VERSION = "attachment-20261007-rp02"
ASSET = Path(__file__).resolve().parents[2] / "resources/rules/attachment-instructions-20261007.json"


def instructions():
    raw = ASSET.read_bytes()
    document = json.loads(raw)
    if document["version"] != VERSION:
        raise ValueError("attachment instruction version")
    return document, analysis.digest(document)


def configuration(common):
    document, file_hash = instructions()
    schema = AttachmentResponseV4.model_json_schema()
    schema["properties"]["instruction_hash"]["const"] = file_hash
    return {**common, "stage": "attachment_v4", "key": "attachment", "provider": "gemini", "provider_call": True,
        "model": "gemini-3.8-flash", "prompt": encode(document), "response_schema": schema,
        "request_fps": 1, "max_output_tokens": 8192}


def verify_stage(group):
    document, file_hash = instructions()
    if group.prompt != encode(document) or group.response_schema["properties"]["instruction_hash"]["const"] != file_hash:
        raise ValueError("attachment instructions changed during execution")


def context_for(doc, ref, calculations, opinion=None, *, instruction_snapshot=None):
    document, file_hash = instructions() if instruction_snapshot is None else (instruction_snapshot, analysis.digest(instruction_snapshot))
    evidence, observations = {}, []
    for item in sheets.analysis_input(doc).observations:
        # Only usable source observations; private review memos are never model input.
        if item.status != "observed" or item.validity not in ("valid", "caution"):
            continue
        ids = []
        for index, basis in enumerate(item.evidence):
            if basis.observed_seconds > 0 and basis.end_seconds > basis.start_seconds:
                key = f"{item.code}:{index}"
                evidence[key] = {"code": item.code, "evidence": basis.model_dump(mode="json")}
                ids.append(key)
        observations.append({"code": item.code, "value": item.value, "opportunity": item.opportunity,
            "validity": item.validity, "evidence_refs": ids})
    facts = {"case_id": doc.sheet.case_id, "session_id": doc.sheet.session_id, "input": ref.model_dump(mode="json"),
        "observations": observations, "evidence": evidence, "calculations": calculations,
        "recording": doc.source.session.recording_s1.model_dump(mode="json")}
    if opinion is not None:
        item = next(item for item in opinion.domains if item.domain == "attachment")
        facts["completed_opinion"] = {"opinion_id": opinion.opinion_id, "revision": opinion.revision,
            "document_hash": analysis.digest(opinion.model_dump(mode="json")), "text": item.text,
            "evidence_codes": item.evidence_codes, "counter_codes": item.counter_codes, "counter_note": item.counter_note}
    return {"task": "attachment_v4", "source": "completed_opinion_inference" if opinion else "independent_ai",
        "identity": {"input_hash": analysis.digest(facts), "instruction_version": VERSION, "instruction_hash": file_hash},
        "facts": facts, "instruction_snapshot": document}


def held(context, reason):
    response = {**context["identity"], "status": "held", "label": None, "reason": reason,
        "evidence_refs": [], "counter_evidence_refs": [], "counter_note": None, "hold_reason": reason}
    return normalize(context, response, "program")


def normalize(context, raw, model):
    response = AttachmentResponseV4.model_validate_json(encode(raw))
    if any(getattr(response, name) != value for name, value in context["identity"].items()):
        raise ValueError("attachment belongs to another input or instruction")
    known = context["facts"]["evidence"]
    if any(ref not in known for ref in (*response.evidence_refs, *response.counter_evidence_refs)):
        raise ValueError("attachment evidence reference does not exist in pinned usable observations")
    if model == "program" and response.status != "held":
        raise ValueError("program does not infer an attachment type")
    return AttachmentAssessmentV4.model_validate_json(encode({"source": context["source"], "model": model,
        "instruction_snapshot": context["instruction_snapshot"], "response": response.model_dump(mode="json")}))


def decision(assessment, context, doc, ref, calculations):
    value = assessment.response
    evidence = context["facts"]["evidence"]
    support = [evidence[key] for key in value.evidence_refs]
    counters = [evidence[key] for key in value.counter_evidence_refs]
    counter_codes = tuple(dict.fromkeys(item["code"] for item in counters))
    # A code may support and counter a judgement at distinct times; retain both links.
    data = {"key": "attachment_type", "label": value.label, "status": "complete" if value.label else "held",
        "reason": value.reason if value.label else value.hold_reason, "evidence_codes": list(dict.fromkeys(item["code"] for item in (*support, *counters))),
        "evidence": [item["evidence"] for item in support], "counter_evidence": [item["evidence"] for item in counters],
        "counter_codes": [code for code in counter_codes if code not in {item["code"] for item in support}],
        "counter_note": value.counter_note, "rater_id": doc.sheet.rater_id,
        "input_sheet_id": ref.sheet_id, "input_revision": ref.revision, "input_sha256": ref.hash}
    parsed = DecisionV4.model_validate_json(encode(data))
    basis = SimpleNamespace(input_document=doc, input=ref, rule_version=parsed.rule_version,
        calculations=CalculationsV4.model_validate_json(encode(calculations)))
    judgements.validate_judgement(parsed, basis)
    return parsed


def validate(assessment, doc, ref, calculations, opinion=None):
    # Archived instructions are validated against their stored bytes, not upgraded on read.
    context = context_for(doc, ref, calculations, opinion, instruction_snapshot=assessment.instruction_snapshot)
    if assessment.instruction_snapshot.get("version") != VERSION:
        raise ValueError("attachment instruction snapshot version")
    normalized = normalize(context, assessment.response.model_dump(mode="json"), assessment.model)
    if normalized != assessment:
        raise ValueError("attachment pinned result differs")
    return decision(assessment, context, doc, ref, calculations)


def request(worker, row, step, group, context, guard):
    verify_stage(group)
    if not context["facts"]["evidence"]:
        result = held(context, "유효한 실제 관찰 근거가 없어 애착 유형 보류")
        return {"assessment": result.model_dump(mode="json"), "response": result.response.model_dump(mode="json"), "usage": {"program_merge": True}}
    info = {key: value for key, value in context.items() if key != "instruction_snapshot"}
    info.update(audit_actor=row["requested_by"] if "requested_by" in row else json.loads(row["input_snapshot_json"])["requested_by"], run_id=row["run_id"])
    if step["attempt"] > 1:
        from .scoring_ai_v4 import repair_instruction
        with worker.store.connect() as db:
            history = db.execute("SELECT usage_json FROM steps WHERE run_id=? AND stage=? AND attempt<? ORDER BY attempt DESC",
                (row["run_id"], group.stage, step["attempt"])).fetchall()
        errors = next((json.loads(value[0]).get("contract_errors") for value in history if json.loads(value[0]).get("contract_errors")), [])
        info["repair"] = repair_instruction(errors)
    worker.reserve_call(row, step)
    observer = worker.observer if hasattr(worker.observer, "request_v4") else GeminiScorerV4(worker.store)
    config = {"model": group.model, "prompt": group.prompt, "thinking_level": group.thinking_level, "max_output_tokens": group.max_output_tokens}
    raw, usage = observer.request_v4([], config, info, group.response_schema, guard)
    guard()
    try:
        result = normalize(context, raw, group.model)
        return {"assessment": result.model_dump(mode="json"), "response": raw, "usage": usage}
    except (ValueError, KeyError) as exc:
        from .scoring_ai_v4 import contract_errors
        usage["contract_errors"] = contract_errors(exc)
        raise ProviderError("v4_schema_invalid", retryable=True, usage=usage) from None
