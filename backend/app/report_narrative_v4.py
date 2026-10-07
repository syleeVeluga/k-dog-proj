"""Generate, validate and replay one immutable report narrative from pinned facts."""
import json
import re
from . import analysis
from .domain.contracts_v4 import ATTACHMENT_TYPES, OWNER_TYPES
from .domain.report_narrative_v4 import NARRATIVE_VERSION, NarrativeAssessmentV4, NarrativeResponseV4
from .domain.report_profile_v4 import ClaimV4, ReportSectionV4, ReportProfileV4
from .gemini import ProviderError
from .gemini_v4 import GeminiScorerV4
from .storage import REPO_ROOT, encode

ASSET = "report/content-20261007.json"
PLACEHOLDER = re.compile(r"\[\[([^\[\]]+)\]\]")


def instructions():
    document = json.loads((REPO_ROOT / "resources" / ASSET).read_text(encoding="utf-8"))
    if document.get("version") != NARRATIVE_VERSION:
        raise ValueError("report narrative instruction version")
    return document, analysis.digest(document)


def stage():
    from .domain.report_runs_v4 import ReportStageV4
    document, _ = instructions()
    return ReportStageV4(stage="content_v4", provider="gemini", provider_call=True, model="gemini-3.8-flash",
        prompt=encode(document), response_schema=NarrativeResponseV4.model_json_schema(), thinking_level="low", max_output_tokens=8192)


def action_evidence(fact):
    return fact.value is not None and (fact.kind == "observation" or fact.kind == "survey" and fact.fact_id.startswith("survey:"))


def context_for(profile, instruction_snapshot=None):
    document = instruction_snapshot if instruction_snapshot is not None else instructions()[0]
    human_actions = tuple(item for item in profile.actions if item.validation == "human_verbatim")
    valid_data = any(action_evidence(item) for item in profile.facts)
    facts = [{"fact_id": item.fact_id, "kind": item.kind, "value": item.value, "unit": item.unit, "label": item.label} for item in profile.facts]
    content = {"profile_hash": analysis.digest(profile.model_dump(mode="json")), "facts": facts,
        "cards": [{"key": item.key, "title": item.title, "status": item.status, "label": item.label} for item in profile.cards],
        "fixed_explanations": [{"section": section.key, "title": section.title, "text": item.text, "fact_ids": item.fact_ids}
            for section in (*profile.cards, *profile.details, *profile.comparisons) for item in section.claims],
        "survey_questions": [{"key": item.key, "question": item.title, "survey_fact_ids": item.survey_fact_ids,
            "video_fact_ids": item.video_fact_ids, "direct_video_task": item.direct_video_task} for item in profile.comparisons],
        "action_capacity": 3-len(human_actions) if valid_data else 0}
    identity = {"input_hash": analysis.digest(content), "instruction_version": NARRATIVE_VERSION, "instruction_hash": analysis.digest(document)}
    return {**content, "identity": identity, "instruction_snapshot": document}


def apply(profile, assessment):
    context = context_for(profile, assessment.instruction_snapshot)
    if assessment.instruction_snapshot.get("version") != NARRATIVE_VERSION or {key: getattr(assessment.response, key) for key in context["identity"]} != context["identity"]:
        raise ValueError("narrative input/instruction pins differ")
    response = assessment.response
    if tuple(item.key for item in response.cards) != tuple(item.key for item in profile.cards):
        raise ValueError("narrative must cover each pinned card exactly once")
    if len(response.actions) > context["action_capacity"] or context["action_capacity"] and not response.actions:
        raise ValueError("narrative action count differs from available evidence")
    facts = {item.fact_id: item for item in profile.facts}
    type_names = set((*ATTACHMENT_TYPES, *OWNER_TYPES))

    def claim(item, key):
        if len(set(item.fact_ids)) != len(item.fact_ids) or not set(item.fact_ids) <= set(facts):
            raise ValueError("narrative references duplicate or unknown facts")
        if key.startswith("action:") and not any(action_evidence(facts[value]) for value in item.fact_ids):
            raise ValueError("narrative action lacks observed or survey evidence")
        card_key = key.split(":")[1] if key.startswith("card:") else None
        if card_key and any(facts[value].kind == "final_type" and value != "final:"+card_key for value in item.fact_ids):
            raise ValueError("narrative card references another final type")
        supported_types = {facts[value].value for value in item.fact_ids if facts[value].kind == "final_type" and facts[value].value}
        plain = PLACEHOLDER.sub("", item.text)
        if any(character.isdecimal() for character in plain) or any(term in item.text for term in assessment.instruction_snapshot["forbidden_terms"]):
            raise ValueError("narrative contains unpinned number or forbidden claim")
        if any(term in item.text for term in type_names - supported_types):
            raise ValueError("narrative contains contradictory type")
        if "%" in item.text or "퍼센트" in item.text or re.search(r"\]\]\s*(?:점|회|배|명|개|국면|분|초|세|등급|비율|백분율)", item.text):
            raise ValueError("narrative adds an unpinned unit or scale")
        if any(term in item.text.lower() for term in ("<", ">", "http:", "https:", "javascript:")):
            raise ValueError("narrative contains markup or link")

        def number(match):
            fact_id = match[1]
            fact = facts.get(fact_id)
            if fact is None or fact_id not in item.fact_ids or fact.kind not in ("metric", "survey") or type(fact.value) not in (int, float):
                raise ValueError("narrative numeric slot is not a pinned numeric fact")
            if fact.kind == "survey" and fact.unit:
                return f"{fact.value} (원척도 {fact.unit})"
            return str(fact.value) + (" " + fact.unit if fact.unit else "")
        text = PLACEHOLDER.sub(number, item.text)
        if "[[" in text or "]]" in text:
            raise ValueError("invalid numeric slot")
        return ClaimV4(claim_id="narrative:"+key, text=text, fact_ids=item.fact_ids)

    cards = tuple(old.model_copy(update={"claims": (*old.claims, *(claim(item, f"card:{old.key}:{index}") for index, item in enumerate(generated.claims)))})
        for old, generated in zip(profile.cards, response.cards))
    details = profile.details
    if response.details:
        details += (ReportSectionV4(key="narrative", title="관찰을 함께 읽기", status="available",
            claims=tuple(claim(item, f"detail:{index}") for index, item in enumerate(response.details))),)
    actions = (*tuple(item for item in profile.actions if item.validation == "human_verbatim"), *(claim(item, f"action:{index}") for index, item in enumerate(response.actions)))
    data = profile.model_dump(mode="json")
    data.update(cards=[item.model_dump(mode="json") for item in cards], details=[item.model_dump(mode="json") for item in details],
        summary=[claim(item, f"summary:{index}").model_dump(mode="json") for index, item in enumerate(response.summary)],
        actions=[item.model_dump(mode="json") for item in actions], actions_notice=profile.actions_notice if not actions else None,
        sentence_bank_status="generated_rp03", provider_text_status="generated_professor_test_pending", narrative=assessment.model_dump(mode="json"))
    return ReportProfileV4.model_validate_json(encode(data))


def normalize(profile, raw, model, instruction_snapshot=None):
    document = instruction_snapshot if instruction_snapshot is not None else instructions()[0]
    result = NarrativeAssessmentV4.model_validate_json(encode({"model": model, "instruction_snapshot": document, "response": raw}))
    apply(profile, result)
    return result


def validate(base, generated):
    if generated.narrative is None or apply(base, generated.narrative) != generated:
        raise ValueError("generated narrative differs from pinned input or stored response")
    return generated


def request(worker, row, step, group, profile, guard):
    expected = stage()
    if group != expected:
        raise ValueError("narrative stage instructions/schema changed")
    context = context_for(profile)
    info = {key: value for key, value in context.items() if key != "instruction_snapshot"}
    info.update(audit_actor=json.loads(row["input_snapshot_json"])["requested_by"], run_id=row["run_id"])
    if step["attempt"] > 1:
        from .scoring_ai_v4 import repair_instruction
        with worker.store.connect() as db:
            history = db.execute("SELECT usage_json FROM steps WHERE run_id=? AND stage='content_v4' AND attempt<? ORDER BY attempt DESC", (row["run_id"], step["attempt"])).fetchall()
        errors = next((json.loads(item[0])["contract_errors"] for item in history if json.loads(item[0]).get("contract_errors")), [])
        info["repair"] = repair_instruction(errors)
    guard(); worker.reserve_call(row, step)
    observer = worker.observer if hasattr(worker.observer, "request_v4") else GeminiScorerV4(worker.store)
    raw, usage = observer.request_v4([], {"model": group.model, "prompt": group.prompt, "thinking_level": group.thinking_level, "max_output_tokens": group.max_output_tokens}, info, group.response_schema, guard)
    guard()
    try:
        assessment = normalize(profile, raw, group.model)
        return apply(profile, assessment), usage
    except (ValueError, KeyError) as exc:
        from .scoring_ai_v4 import contract_errors
        usage["contract_errors"] = contract_errors(exc)
        raise ProviderError("v4_schema_invalid", retryable=True, usage=usage) from None
