"""Explicit external comparison snapshots; approval is checked again on every use."""
import hashlib
import json
import os

from fastapi import HTTPException
from pydantic import Field, field_validator

from . import analysis, comparisons_v4 as comparisons
from .domain.comparisons_v4 import (CohortSelectionV4, ExternalEntryV4, ExternalPublicV4,
    ExternalReferenceV4, ExternalSnapshotV4, ResearchReferenceV4)
from .domain.preprocess_v4 import FileV4
from .input_models import Model
from .storage import encode, now, uid

ACTION = "comparison.external.snapshot"
DELETED = "comparison.external.deleted"
IMPACT = "comparison.external.impact"


class ExternalCreateV4(Model):
    request_id: str = Field(min_length=1, max_length=200)
    target: CohortSelectionV4
    source_ids: list[str] = Field(min_length=1, max_length=2)
    reason: str = Field(min_length=1, max_length=4000, pattern=r"\S")

    @field_validator("target", mode="before")
    @classmethod
    def target_contract(cls, value):
        return CohortSelectionV4.model_validate_json(encode(value)) if isinstance(value, dict) else value

    @field_validator("source_ids")
    @classmethod
    def distinct(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("select each external source once")
        return sorted(value)


class ExternalSummaryV4(Model):
    reference: ExternalReferenceV4
    target: CohortSelectionV4
    source_ids: list[str]
    source_titles: list[str]
    status: str
    reason: str
    recorded_at: str


class ExternalViewV4(ExternalSummaryV4):
    document: ExternalSnapshotV4 | None = None
    impact_history: list[dict] = Field(default_factory=list)


def upload_evidence(store, data, filename, user):
    if not data or len(data) > 16 * 1024 * 1024 or not filename.strip() or len(filename) > 200:
        raise HTTPException(422, "연구 근거는 파일명과 16 MiB 이하의 비어 있지 않은 파일이 필요합니다.")
    with store.connect() as db:
        comparisons._account(db, user, admin=True)
    pointer = FileV4(ref=f"comparison-evidence/{uid()}.bin", hash=hashlib.sha256(data).hexdigest())
    path = store.path(pointer.ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(data); handle.flush(); os.fsync(handle.fileno())
    with store.connect(write=True) as db:
        comparisons._account(db, user, admin=True)
        if hashlib.sha256(path.read_bytes()).hexdigest() != pointer.hash:
            raise HTTPException(409, "저장된 연구 근거 hash가 다릅니다.")
        store.audit(db, user.username, uid(), "comparison.evidence", {**pointer.model_dump(mode="json"), "filename": filename})
    return pointer


def _population(case, requirements):
    """Only explicit existing profile facts; unknown/custom research criteria stay unknown."""
    profile = json.loads(case["dog_profile_json"])
    facts = {f"dog.{key}": str(value) for key, value in profile.items()
             if value is not None and value not in ("", "미기재", "unknown") and not isinstance(value, (dict, list))}
    return {key: facts[key] for key in requirements if key in facts}


def _entries(store, target, source_ids, user, db):
    comparisons._account(db, user)
    member, case = comparisons._member(store, db, target, current=False)
    if not case["consent_confirmed"]:
        raise HTTPException(403, "외부 비교 대상의 동의 확인이 필요합니다.")
    entries = []
    for source_id in source_ids:
        source, _ = comparisons._source(source_id)
        latest = comparisons._record(db, comparisons.RESEARCH_ACTION, source_id)
        reference = ResearchReferenceV4.model_validate_json(encode(latest)) if latest else None
        confirmation = comparisons.research_document(store, reference) if reference else None
        population = _population(case, confirmation.scope.population_requirements if confirmation else {})
        gate = comparisons.external_for_report(store, source_id, comparisons.target_scope(source_id), user, population=population)
        if gate.status != "approved":
            raise HTTPException(409, gate.reason)
        domain = next((row for row in member.survey.domains if row.domain == gate.scope.domain), None)
        if (domain is None or domain.question_ids != gate.scope.question_ids or domain.status != "calculated"
                or domain.mean is None or domain.answered_count != domain.target_count
                or domain.aggregation != gate.scope.aggregation):
            raise HTTPException(409, "승인 범위의 모든 설문 원응답이 확인된 경우에만 외부 비교할 수 있습니다.")
        entries.append(ExternalEntryV4(title=source["title"], literature=source["literature"], doi=source["doi"],
            population_scope=source["population_scope"], number_provenance=source["number_provenance"],
            gate=gate, local_mean=domain.mean, local_n=domain.answered_count, population=population))
    return tuple(entries)


def document(store, pointer):
    pointer = ExternalReferenceV4.model_validate(pointer)
    doc = comparisons._read(store, pointer, ExternalSnapshotV4)
    if (doc.snapshot_id, doc.revision) != (pointer.snapshot_id, pointer.revision):
        raise HTTPException(409, "외부 비교 snapshot 참조가 다릅니다.")
    with store.connect() as db:
        record = comparisons._record(db, ACTION, pointer.snapshot_id)
        if record is None or record["reference"] != pointer.model_dump(mode="json"):
            raise HTTPException(409, "채택되지 않은 외부 비교 snapshot입니다.")
        if comparisons._record(db, DELETED, pointer.snapshot_id):
            raise HTTPException(403, "삭제된 대상의 외부 비교입니다.")
    return doc


def for_output(store, pointer, user):
    pointer = ExternalReferenceV4.model_validate(pointer)
    doc = document(store, pointer)
    with store.connect() as db:
        comparisons._account(db, user)
        source_hash = comparisons._sources()[1]
        if doc.source_hash != source_hash or doc.survey_assets != comparisons.assets():
            raise HTTPException(409, "외부 비교 출처 또는 설문 정책 판본이 변경되어 제공을 보류합니다.")
        actual = _entries(store, doc.target, [entry.gate.source_id for entry in doc.entries], user, db)
        if actual != doc.entries:
            raise HTTPException(409, "외부 비교의 연구 확인·활성화·대상 조건이 변경되어 제공을 보류합니다.")
    return ExternalPublicV4(reference=pointer, target=doc.target, entries=doc.entries)


def files(store, pointer):
    doc = document(store, pointer)
    found = {pointer.ref: pointer.hash, doc.target.input.manifest_ref: doc.target.input.manifest_hash}
    for entry in doc.entries:
        research = comparisons.research_document(store, entry.gate.confirmation)
        found[entry.gate.confirmation.ref] = entry.gate.confirmation.hash
        for evidence in research.evidence:
            found[evidence.ref] = evidence.hash
    return tuple(FileV4(ref=ref, hash=digest) for ref, digest in sorted(found.items()))


def create(store, value, user):
    value = ExternalCreateV4.model_validate_json(value.model_dump_json())
    request_hash = analysis.digest({"request": value.model_dump(mode="json"), "actor": user.username})
    with store.connect() as db:
        comparisons._account(db, user)
        for row in db.execute("SELECT detail_json FROM changes WHERE action=? AND actor=?", (ACTION, user.username)):
            record = json.loads(row[0])
            if record["request_id"] == value.request_id:
                if record["request_hash"] != request_hash:
                    raise HTTPException(409, "같은 요청 ID의 외부 비교 선택이 다릅니다.")
                return view(store, record["reference"]["snapshot_id"], user)
        entries = _entries(store, value.target, value.source_ids, user, db)
    doc = ExternalSnapshotV4(snapshot_id=uid(), request_id=value.request_id, request_hash=request_hash,
        actor=user.username, recorded_at=now(), reason=value.reason, target=value.target,
        source_hash=comparisons._sources()[1], survey_assets=comparisons.assets(), entries=entries)
    file = comparisons._write(store, "external", doc)
    pointer = ExternalReferenceV4(snapshot_id=doc.snapshot_id, revision=1, ref=file.ref, hash=file.hash)
    with store.connect(write=True) as db:
        comparisons._account(db, user)
        if (comparisons._read(store, pointer, ExternalSnapshotV4) != doc or comparisons._sources()[1] != doc.source_hash
                or comparisons.assets() != doc.survey_assets or _entries(store, value.target, value.source_ids, user, db) != entries):
            raise HTTPException(409, "외부 비교 저장 중 근거 또는 조건이 변경되었습니다.")
        for row in db.execute("SELECT detail_json FROM changes WHERE action=? AND actor=?", (ACTION, user.username)):
            record = json.loads(row[0])
            if record["request_id"] == value.request_id:
                if record["request_hash"] != request_hash:
                    raise HTTPException(409, "같은 요청 ID의 외부 비교 선택이 다릅니다.")
                return view(store, record["reference"]["snapshot_id"], user)
        store.audit(db, user.username, doc.snapshot_id, ACTION, {"reference": pointer.model_dump(mode="json"),
            "request_id": value.request_id, "request_hash": request_hash, "case_id": value.target.case_id,
            "source_ids": value.source_ids, "target": value.target.model_dump(mode="json"), "recorded_at": doc.recorded_at})
    return view(store, doc.snapshot_id, user)


def view(store, snapshot_id, user):
    with store.connect() as db:
        comparisons._account(db, user)
        record = comparisons._record(db, ACTION, snapshot_id)
        if record is None or comparisons._record(db, DELETED, snapshot_id):
            raise HTTPException(404, "외부 비교 snapshot이 없습니다.")
        store.case(db, record["case_id"])
        history = [json.loads(row[0]) for row in db.execute("SELECT detail_json FROM changes WHERE action=? AND target=? ORDER BY rowid", (IMPACT, snapshot_id))]
    pointer = ExternalReferenceV4.model_validate_json(encode(record["reference"]))
    status, reason, doc = "approved", "선택한 승인 범위를 현재 제공할 수 있습니다.", None
    try:
        for_output(store, pointer, user)
        doc = document(store, pointer)
        final = for_output(store, pointer, user)
        if final.target != doc.target or final.entries != doc.entries:
            raise HTTPException(409, "외부 비교를 읽는 중 승인 범위가 변경되었습니다.")
    except HTTPException as exc:
        if exc.status_code in (401, 403):
            raise
        status, reason, doc = "blocked", str(exc.detail), None
    return ExternalViewV4(reference=pointer, target=CohortSelectionV4.model_validate_json(encode(record["target"])),
        source_ids=record["source_ids"], source_titles=[comparisons._source(value)[0]["title"] for value in record["source_ids"]],
        status=status, reason=reason, recorded_at=record["recorded_at"], document=doc, impact_history=history)


def list_snapshots(store, user):
    with store.connect() as db:
        comparisons._account(db, user)
        ids = [row[0] for row in db.execute("SELECT target FROM changes WHERE action=? ORDER BY rowid DESC", (ACTION,))]
    result = []
    for snapshot_id in ids:
        try:
            shown = view(store, snapshot_id, user)
        except HTTPException as exc:
            if exc.status_code in (403, 404):
                continue
            raise
        result.append(ExternalSummaryV4.model_validate(shown.model_dump(exclude={"document", "impact_history"})))
    return result


def record_impacts(store, db, source_id, actor, reason):
    for row in db.execute("SELECT target,detail_json FROM changes WHERE action=?", (ACTION,)).fetchall():
        record = json.loads(row["detail_json"])
        if source_id in record["source_ids"]:
            store.audit(db, actor, row["target"], IMPACT, {"source_id": source_id, "reason": reason, "recorded_at": now(),
                "research": comparisons._record(db, comparisons.RESEARCH_ACTION, source_id),
                "activation": comparisons._record(db, comparisons.ACTIVATION_ACTION, source_id)})


def purge_case(db, case_id):
    removed = set()
    for row in db.execute("SELECT target,detail_json FROM changes WHERE action=?", (ACTION,)).fetchall():
        if json.loads(row["detail_json"])["case_id"] == case_id:
            removed.add(row["target"])
            db.execute("DELETE FROM changes WHERE target=? AND action IN (?,?)", (row["target"], ACTION, IMPACT))
    return removed
