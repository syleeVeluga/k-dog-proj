"""Actual S1 scene selection; time overlap alone never establishes a common event."""
from dataclasses import dataclass

from . import analysis, sheets_v4 as sheets
from .domain.catalog_v4 import COUNT_CODES, ContractV4, Hash, ItemCode, Text, load_catalog_v4
from .domain.contracts_v4 import EvidenceV4
from .domain.report_profile_v4 import SceneReviewV4
from .storage import encode

PLACEHOLDERS = ("작성 필요", "예시 메모", "입력 예시", "example memo", "sample memo")
CATALOG = {item.code: item for item in load_catalog_v4().rated_items()}


class CommonEventV4(ContractV4):
    event_id: Text
    item_codes: tuple[ItemCode, ...]
    evidence: tuple[EvidenceV4, ...]
    source_ref: Text
    source_hash: Hash


@dataclass(frozen=True)
class Candidate:
    event_id: str
    codes: tuple[str, ...]
    evidence: tuple[EvidenceV4, ...]
    domain: str
    start: float
    end: float
    explicit_common: bool
    nominated: bool
    changed: bool


def placeholder(text):
    return bool(text and any(word.casefold() in text.casefold() for word in PLACEHOLDERS))


def basis_key(basis):
    return encode(basis.model_dump(mode="json"))


def source_basis_key(basis):
    return encode(basis.model_dump(mode="json", exclude={"note"}))


def domain_for(code):
    if code.startswith("보"):
        return "education_attitude"
    if code in ("개38", "개39", "개40", "개41", "개42", "개43"):
        return "walking"
    return "attachment" if CATALOG[code].segment in ("alone", "reunion", "ignore") else "social"


def usable(item):
    return (item.status == "observed" and item.validity in ("valid", "caution") and item.code != "개21"
            and not isinstance(item.value, str) and item.value is not None and
            any(basis.observed_seconds > 0 and basis.end_seconds > basis.start_seconds and not placeholder(basis.note) for basis in item.evidence))


def events_from_ai(snapshot, stage, payload, output_ref, output_hash):
    """Called only for an adopted S08 step whose envelope/ref/hash was verified."""
    from . import scoring_ai_v4 as ai
    ai.stored_group(snapshot, stage, payload)
    if "response" not in payload:
        return ()
    clips = {clip.clip_id: clip for clip in ai.clips_for(snapshot, stage)}
    videos = {video.video_id: video for video in snapshot.session.videos}
    result = []
    for event in payload["response"].get("events", []):
        evidence = []
        for view in event["views"]:
            clip = clips[view["clip_id"]]
            derivative = getattr(clip, stage.input_variant)
            evidence.append(EvidenceV4(video_id=clip.video_id, video_sha256=videos[clip.video_id].sha256, camera_id=clip.camera_id,
                window_id=view["window_id"], start_seconds=view["start_seconds"]+derivative.source_time_offset_seconds,
                end_seconds=view["end_seconds"]+derivative.source_time_offset_seconds, observed_seconds=view["observed_seconds"], note=view.get("note")))
        result.append(CommonEventV4(event_id=stage.key+":"+event["event_id"], item_codes=tuple(event["item_codes"]),
            evidence=tuple(evidence), source_ref=output_ref, source_hash=output_hash))
    return tuple(result)


def select(final, common_events=()):
    basic = final.basic_document
    source = basic.input_document
    sheet = sheets.analysis_input(source)
    observations = {item.code: item for item in sheet.observations if usable(item)}
    capture = source.source.session.recording_s1
    allowed = {code: {basis_key(basis): basis for basis in item.evidence if not placeholder(basis.note)} for code, item in observations.items()}
    allowed_sources = {code: {source_basis_key(basis) for basis in values.values()} for code, values in allowed.items()}
    nominated = {source_basis_key(basis) for item in final.opinion_document.domains for basis in item.scene_refs} if final.opinion_document and final.opinion_document.state == "complete" else set()
    metrics = {metric.key: metric for metric in basic.calculations.metrics}
    changed_codes = set()
    if metrics.get("W") and metrics["W"].status == "calculated":
        changed_codes.update(("개58", "개18"))
    if basic.conditions.same_object is True and observations.get("개30") and observations.get("개34"):
        changed_codes.update(("개30", "개34"))
    candidates, reviews, covered = [], [], set()

    def candidate(event_id, codes, evidence, explicit):
        offsets = [capture.offset(basis.video_id) for basis in evidence]
        if not evidence or any(value is None for value in offsets):
            raise ValueError("scene lacks synchronized actual source evidence")
        starts = [basis.start_seconds-offset for basis, offset in zip(evidence, offsets)]
        ends = [basis.end_seconds-offset for basis, offset in zip(evidence, offsets)]
        if explicit and max(starts) >= min(ends):
            raise ValueError("common event views have no shared actual time")
        return Candidate(event_id, tuple(codes), tuple(evidence), domain_for(codes[0]), min(starts), max(ends), explicit,
                         any(source_basis_key(basis) in nominated for basis in evidence), bool(set(codes) & changed_codes))

    seen_events = set()
    for event in common_events:
        if event.event_id in seen_events:
            raise ValueError("duplicate common scene event")
        seen_events.add(event.event_id)
        if not event.item_codes or not set(event.item_codes) <= observations.keys() or any(
                not any(source_basis_key(basis) in allowed_sources[code] for basis in event.evidence) for code in event.item_codes):
            raise ValueError("scene event references another source or an unobserved item")
        # The adopted raw response proves common-event membership. Each item
        # needs an exact original observation link; extra synchronized views
        # still require their own actual source identity/window validation.
        for basis in event.evidence:
            if placeholder(basis.note) or basis.observed_seconds <= 0 or not any(basis.window_id in CATALOG[code].windows for code in event.item_codes):
                raise ValueError("scene event lacks valid actual observation evidence")
            for code in event.item_codes:
                if basis.window_id in CATALOG[code].windows:
                    sheets._source_evidence(source,basis,code=code)
        if any(code in COUNT_CODES and observations[code].value == 0 for code in event.item_codes):
            raise ValueError("zero occurrences cannot provide a positive event scene")
        value = candidate(event.event_id, event.item_codes, event.evidence, True)
        candidates.append(value)
        covered.update((code, source_basis_key(basis)) for code in event.item_codes for basis in event.evidence)
    for code, item in observations.items():
        if code in COUNT_CODES and item.value == 0:
            continue
        for key, basis in allowed[code].items():
            if (code, source_basis_key(basis)) in covered:
                continue
            event_id = "observation-"+analysis.digest({"code": code, "evidence": key})[:20]
            candidates.append(candidate(event_id, (code,), (basis,), False))

    ambiguous = set()
    for i, one in enumerate(candidates):
        for two in candidates[i+1:]:
            same_codes = bool(set(one.codes) & set(two.codes))
            different_camera = {basis.video_id for basis in one.evidence} != {basis.video_id for basis in two.evidence}
            overlap = one.start < two.end and two.start < one.end
            if same_codes and different_camera and overlap and not (one.explicit_common and two.explicit_common):
                ambiguous.update((one.event_id, two.event_id))
    pending = [item for item in candidates if item.event_id in ambiguous]
    reviews.extend(SceneReviewV4(candidate_id=item.event_id, reason="같은 항목의 여러 카메라 근거가 겹치지만 공통 사건 연결이 없습니다. 시간 겹침만으로 합치지 않고 선택 검토를 기다립니다.", evidence=item.evidence) for item in pending)
    remaining = [item for item in candidates if item.event_id not in ambiguous]
    selected, used_domains = [], set()
    while remaining and len(selected) < 3:
        remaining.sort(key=lambda value: (not value.nominated, not value.changed, value.domain in used_domains, value.start, value.end, value.event_id))
        choice = remaining.pop(0)
        selected.append(choice)
        used_domains.add(choice.domain)
    return tuple(selected), tuple(reviews)
