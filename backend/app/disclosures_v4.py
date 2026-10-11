"""Read-only historical interpretation exposure and common account access."""
import json
from fastapi import HTTPException

from .domain.disclosures_v4 import InterpretationExposureV4, InterpretationReferenceV4
from .storage import encode

ACTION = "interpretation.s1.reveal"


def records(db, case_id, session_id):
    for row in db.execute("SELECT detail_json FROM changes WHERE target=? AND action=? ORDER BY rowid", (case_id, ACTION)):
        raw = json.loads(row["detail_json"])
        value = InterpretationExposureV4.model_validate_json(encode(raw["exposure"]))
        if value.case_id == case_id and value.session_id == session_id:
            yield value


def inherited(db, case_id, session_id, username, rater_id, source):
    hashes = {video.sha256 for video in source.session.videos}
    return {entry.exposure_id: entry for entry in records(db, case_id, session_id)
            if (entry.viewer_username == username or entry.viewer_rater_id == rater_id) and hashes.intersection(entry.video_hashes)}


def target(kind, link):
    data = link.model_dump(mode="json") if hasattr(link, "model_dump") else link
    return InterpretationReferenceV4(kind=kind, document_id=data["opinion_id" if kind == "opinion" else "final_id"],
        revision=data.get("revision") if kind == "opinion" else None, ref=data["ref"], hash=data["hash"])


def allowed(db, case_id, session_id, user, pointer, source_actor):
    account = db.execute("SELECT active FROM users WHERE username=?", (user.username,)).fetchone()
    return bool(account and account["active"])



def require(db, case_id, session_id, user, pointer, source_actor):
    if not allowed(db, case_id, session_id, user, pointer, source_actor):
        raise HTTPException(403, "활성 업무 계정이 필요합니다.")


def resolve(store, db, case_id, session_id, pointer):
    from . import opinions_v4 as opinions, final_results_v4 as finals
    action = "opinion.s1.save" if pointer.kind == "opinion" else "final.s1.publish"
    for row in db.execute("SELECT detail_json FROM changes WHERE target=? AND action=?", (case_id, action)):
        value = json.loads(row["detail_json"])
        if value.get("session_id") != session_id or target(pointer.kind, value) != pointer:
            continue
        doc = (opinions if pointer.kind == "opinion" else finals).read_document(store, pointer.ref, pointer.hash)
        if (doc.case_id, doc.session_id) != (case_id, session_id):
            raise HTTPException(409, "해석 문서의 대상·회차가 다릅니다.")
        return doc
    raise HTTPException(404, "기록된 정확한 해석 판본을 선택하세요.")
