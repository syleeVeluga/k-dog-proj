"""S1 event opinions and explicitly assembled immutable final-domain snapshots."""
from typing import Annotated, Literal, Self
from pydantic import Field, model_validator

from .catalog_v4 import ContractV4, Hash, ItemCode, Text
from .contracts_v4 import ATTACHMENT_TYPES, OWNER_TYPES, EvidenceV4
from .media_v4 import MediaKey
from .results_v4 import BasicResultV4, ResultReferenceV4
from .attachment_v4 import AttachmentAssessmentV4, AttachmentReferenceV4

DomainKeyV4 = Literal["attachment", "education_attitude", "people_response", "nonsocial_response", "environment", "tendency"]
DOMAIN_LABELS = {"attachment": "애착", "education_attitude": "교육태도", "people_response": "사람 반응",
                 "nonsocial_response": "비사회적 반응", "environment": "환경", "tendency": "성향"}
OPINION_CELLS = dict(zip(DOMAIN_LABELS, ("D33", "D34", "D35", "D36", "D37", "D38")))
FINAL_POLICY = "final-opinion-20261002-s1.1-1"


class DomainOpinionV4(ContractV4):
    domain: DomainKeyV4
    text: Annotated[str, Field(max_length=12000)] = ""
    label: Text | None = None
    reason: Annotated[str, Field(max_length=4000)] = ""
    evidence_codes: tuple[ItemCode, ...] = ()
    counter_codes: tuple[ItemCode, ...] = ()
    counter_note: Text | None = None
    scene_refs: tuple[EvidenceV4, ...] = ()

    @model_validator(mode="after")
    def typed_selection(self) -> Self:
        if self.label is not None:
            allowed = ATTACHMENT_TYPES if self.domain == "attachment" else OWNER_TYPES if self.domain == "education_attitude" else ()
            if self.label not in allowed:
                raise ValueError("only the approved attachment/education type names may be selected")
        if len(set(self.evidence_codes)) != len(self.evidence_codes) or len(set(self.counter_codes)) != len(self.counter_codes):
            raise ValueError("duplicate opinion evidence")
        if not set(self.counter_codes) <= set(self.evidence_codes):
            raise ValueError("counter evidence must be among selected observations")
        return self


class OpinionReferenceV4(ContractV4):
    opinion_id: MediaKey
    revision: Annotated[int, Field(ge=1)]
    ref: Annotated[str, Field(pattern=r"^opinions/[^\\]+\.json$")]
    hash: Hash


class OpinionDocumentV4(ContractV4):
    opinion_id: MediaKey
    case_id: MediaKey
    session_id: MediaKey
    revision: Annotated[int, Field(ge=1)]
    actor: MediaKey
    recorded_at: Text
    change_reason: Text
    policy_version: Literal["final-opinion-20261002-s1.1-1"] = FINAL_POLICY
    basic: ResultReferenceV4
    evaluator: Annotated[str, Field(max_length=200)] = ""
    completion_requested: bool = False
    state: Literal["draft", "complete", "withdrawn"] = "draft"
    completion_issues: tuple[Text, ...] = ()
    entry_completion_policy: Literal["pending_G01"] = "pending_G01"
    domains: tuple[DomainOpinionV4, ...] = ()
    priority_help: Annotated[str, Field(max_length=12000)] = ""
    previous: tuple[OpinionReferenceV4, ...] = ()

    @model_validator(mode="after")
    def identity(self) -> Self:
        if len({item.domain for item in self.domains}) != len(self.domains):
            raise ValueError("an opinion has only one entry per domain")
        if any(item.opinion_id != self.opinion_id or item.revision >= self.revision for item in self.previous):
            raise ValueError("opinion history must be earlier revisions of the same record")
        if len({item.revision for item in self.previous}) != len(self.previous):
            raise ValueError("duplicate opinion revision")
        if self.state == "complete" and (not self.completion_requested or not self.evaluator.strip() or self.completion_issues):
            raise ValueError("completed opinion requires the actual completion gate")
        if self.state == "complete" and not any(item.text.strip() for item in self.domains):
            raise ValueError("D33-D38 substantive opinion is required; entry alternative is pending G01")
        return self


class FinalDomainV4(ContractV4):
    domain: DomainKeyV4
    label: Text | None = None
    text: Text | None = None
    source: Literal["completed_opinion", "completed_opinion_inference", "manual_selection", "basic"]
    status: Literal["selected", "draft", "held", "observation_text", "facts_available", "missing", "policy_pending"]
    reason: Text
    evidence_codes: tuple[ItemCode, ...] = ()
    counter_codes: tuple[ItemCode, ...] = ()
    counter_note: Text | None = None
    original_label: Text | None = None
    opinion_revision: int | None = None

    @model_validator(mode="after")
    def explicit_type(self) -> Self:
        allowed = ATTACHMENT_TYPES if self.domain == "attachment" else OWNER_TYPES if self.domain == "education_attitude" else ()
        if self.label is not None and self.label not in allowed:
            raise ValueError("final domain cannot invent a type name")
        if not set(self.counter_codes) <= set(self.evidence_codes):
            raise ValueError("counter codes must preserve their selected observation links")
        return self


class FinalReferenceV4(ContractV4):
    final_id: MediaKey
    ref: Annotated[str, Field(pattern=r"^finals/[^\\]+\.json$")]
    hash: Hash


class FinalResultV4(ContractV4):
    final_id: MediaKey
    case_id: MediaKey
    session_id: MediaKey
    actor: MediaKey
    recorded_at: Text
    change_reason: Text
    policy_version: Literal["final-opinion-20261002-s1.1-1"] = FINAL_POLICY
    basic: ResultReferenceV4
    basic_document: BasicResultV4
    opinion: OpinionReferenceV4 | None = None
    opinion_document: OpinionDocumentV4 | None = None
    domains: tuple[FinalDomainV4, ...]
    priority_help: Text | None = None
    independent_ai: bool = False
    interpretation_policy: Literal["D04_pending", "attachment-20261007-rp02"] = "D04_pending"
    attachment_inference: AttachmentReferenceV4 | None = Field(default=None, exclude_if=lambda value: value is None)
    attachment_assessment: AttachmentAssessmentV4 | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def pinned_identity(self) -> Self:
        basic = self.basic_document
        if (self.basic.result_id, self.basic.revision, self.case_id, self.session_id) != (basic.result_id, basic.revision, basic.case_id, basic.session_id):
            raise ValueError("final result and selected basic revision differ")
        if len(self.domains) != 6 or {item.domain for item in self.domains} != set(DOMAIN_LABELS):
            raise ValueError("final results preserve exactly six opinion domains")
        if (self.opinion is None) != (self.opinion_document is None):
            raise ValueError("opinion reference and source snapshot must be paired")
        if (self.attachment_inference is None) != (self.attachment_assessment is None):
            raise ValueError("opinion inference reference and snapshot must be paired")
        if self.attachment_assessment and (not self.opinion_document or self.attachment_assessment.source != "completed_opinion_inference"):
            raise ValueError("completed opinion inference requires the opinion source")
        if self.opinion_document:
            doc = self.opinion_document
            if (doc.case_id, doc.session_id, doc.opinion_id, doc.revision, doc.basic) != (self.case_id, self.session_id, self.opinion.opinion_id, self.opinion.revision, self.basic):
                raise ValueError("opinion belongs to a different fixed basic result")
        if self.independent_ai and (basic.input_document.sheet.rater_kind != "ai" or any(item.source != "basic" for item in self.domains)):
            raise ValueError("human opinions or selections are not independent AI output")
        return self
