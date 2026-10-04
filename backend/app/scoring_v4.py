"""Source-grounded S1 formulas; no legacy numerical classifier or hidden DB reads."""

from fractions import Fraction
import hashlib

from .domain.catalog_v4 import (RESOURCES, SCORING_VERSION, MEMO_CODES, load_catalog_v4,
                                load_rules_v4, validate_source_references_v4)
from .domain.contracts_v4 import ScoreSheetV4
from .domain.results_v4 import (CalculationConditionsV4, CalculationsV4, MetricV4,
                                OwnerCalculationV4, OwnerPointsV4)
from .recording_v4 import build_windows_v4, safe_base_sequence_v4
from .sheets_v4 import analysis_input, asset_hashes
from .domain.sheets_v4 import SheetDocumentV4

RULE_VERSION = SCORING_VERSION
RULE_HASH = hashlib.sha256((RESOURCES / "rules/scoring-v4.json").read_bytes()).hexdigest()
OWNER_TYPES = ("허용형", "조율형", "통제형")
ATTACHMENT_TYPES = ("곁에서 안심하는 사이", "가까이 있어도 안심이 어려운 사이", "거리를 두고 지내는 사이", "다가감과 물러섬이 함께 나오는 사이")
OWNER_CODES = ("보6", "보9", "보22", "보39", "보23", "보24")
PEOPLE_CODES = ("개13", "개14", "개15", "개51", "개52", "개54", "개55")
WALK_CODES = tuple(f"개{n}" for n in range(38, 44))
VOCAL_WINDOWS = {"바6": "entry_whole", "개11": "alone_whole", "개47": "reunion_whole",
                 "개48": "ignore_whole", "개49": "stranger_whole", "개50": "exit_whole"}


def verify_rules():
    rules = load_rules_v4()
    if hashlib.sha256((RESOURCES / "rules/scoring-v4.json").read_bytes()).hexdigest() != RULE_HASH:
        raise ValueError("S1 scoring rules changed after process initialization")
    return rules


def vocal_score(total, vocal):
    """Exact decimal boundaries, not rounded display percentages."""
    if type(total) not in (int, float) or type(vocal) not in (int, float):
        raise ValueError("finite numeric observation durations required")
    total, vocal = Fraction(str(total)), Fraction(str(vocal))
    if total <= 0 or not 0 <= vocal <= total:
        raise ValueError("vocal duration must fit the actual whole interval")
    return 0 if vocal == 0 else 1 if vocal * 3 <= total else 2 if vocal * 3 <= total * 2 else 3


def dominant_type(ratios, rules):
    """Fractions stay exact through both threshold comparisons."""
    ordered = sorted(range(3), key=lambda index: ratios[index], reverse=True)
    top, second = (ratios[index] for index in ordered[:2])
    limits = rules["owner_type_thresholds"]
    return OWNER_TYPES[ordered[0]] if top >= Fraction(str(limits["dominance"])) and top - second >= Fraction(str(limits["margin"])) else None


def calculate(doc: SheetDocumentV4, *, rules=None, audio_available=None, conditions=None) -> CalculationsV4:
    rules = verify_rules() if rules is None else rules
    validate_source_references_v4(rules)
    if rules != load_rules_v4():
        raise ValueError("unapproved scoring snapshot")
    conditions = conditions or CalculationConditionsV4()
    conditions = CalculationConditionsV4.model_validate_json(conditions.model_dump_json())
    # Pydantic can serialize a forged bool in an int union as 1; reject it first.
    for item in doc.sheet.observations:
        if item.code not in MEMO_CODES and item.value is not None and type(item.value) is not int:
            raise ValueError(f"strict S1 raw integer required: {item.code}")
    sheet = ScoreSheetV4.model_validate_json(analysis_input(doc).model_dump_json())
    catalog = {item.code: item for item in load_catalog_v4().items}
    observations = {item.code: item for item in sheet.observations}
    recording = doc.source.session.recording_s1
    if doc.source.asset_hashes != asset_hashes() or tuple(doc.source.windows) != build_windows_v4(recording):
        raise ValueError("S1 asset/window snapshot differs from its confirmed recording facts")
    windows = {window.window_id: window for window in doc.source.windows}
    for item in observations.values():
        definition = catalog[item.code]
        if item.status == "observed" and definition.usage == "numeric":
            if type(item.value) is not int or definition.allowed_values and item.value not in definition.allowed_values or definition.value_type == "count" and item.value < 0:
                raise ValueError(f"invalid S1 raw value: {item.code}")
    def numeric(code):
        item = observations.get(code)
        if not item or item.status != "observed" or item.validity not in ("valid", "caution") or type(item.value) is not int:
            return None
        if not any(basis.observed_seconds > 0 for basis in item.evidence):
            return None
        definition = catalog[code]
        if definition.whole_interval_required and (not item.whole_interval_observed or
                any(windows[key].status != "confirmed" for key in definition.windows)):
            return None
        return item.value
    def metric(key, codes, value=None, *, status=None, reason, used=None, excluded=None, **extra):
        missing = {code: observations[code].reason or observations[code].status if code in observations else "원관찰 없음"
                   for code in codes if numeric(code) is None}
        return MetricV4(key=key, value=value, status=status or ("calculated" if value is not None else "missing"), reason=reason,
                        inputs=tuple(observations[code] for code in codes if code in observations),
                        used_codes=tuple(code for code in (codes if used is None else used) if numeric(code) is not None), excluded={**missing, **(excluded or {})}, **extra)
    metrics = []
    # Walking uses all six raw distances, even when an exception contributes zero.
    distances = [numeric(code) for code in WALK_CODES]
    exceptions = {phase.code: phase.proximity_exception for phase in sheet.walk_phases}
    condition = numeric("보13")
    status, reason = "calculated", "거리 0/1이며 근접 예외 해당 없음인 국면; 제외 국면도 분모 6 유지"
    if condition == 3:
        status, reason = "invalid", "보13=3: 걷기 조건 무효"
    elif condition not in (1, 2):
        status, reason = "condition_unknown", "보13 조건 미확인"
    elif any(value is None for value in distances):
        status, reason = "missing", "여섯 실제 국면의 거리 모두 필요; 결측을 새 분모로 바꾸지 않음"
    elif any(exceptions.get(code) == "recheck" or value in (0, 1) and exceptions.get(code, "unknown") == "unknown" for code, value in zip(WALK_CODES, distances)):
        status, reason = "condition_unknown", "근접 예외 재확인 또는 가까운 국면의 예외 미기록"
    recognized = [int(value in (0, 1) and exceptions.get(code) == "none") for code, value in zip(WALK_CODES, distances)]
    moving, stopped = sum(recognized[::2]), sum(recognized[1::2])
    for key, value in (("개26", moving), ("개36", stopped), ("개27", (moving + stopped) / 6)):
        metrics.append(metric(key, (*WALK_CODES, "보13"), value if status == "calculated" else None, status=status, reason=reason,
                              numerator=moving + stopped if key == "개27" and status == "calculated" else None,
                              denominator=6 if key == "개27" else None, caution=condition == 2))
    # Absolute-state difference is deliberately independent of contact and ignore validity.
    alone, reunion = numeric("개58"), numeric("개18")
    metrics.append(metric("W", ("개58", "개18", "보12", "개19", "개44"), abs(alone) - abs(reunion) if alone is not None and reunion is not None else None,
                          used=("개58", "개18"), reason="abs(개58)−abs(개18); 방향 원값·시간창을 함께 보존, 인과로 해석하지 않음"))
    # Audio availability comes from pinned media bytes/probe, never a caller's raw integer.
    vocals = {}
    for code, window_id in VOCAL_WINDOWS.items():
        item, window = observations.get(code), windows.get(window_id)
        available = audio_available is not None and audio_available.get(code) is True
        amount = item.vocalization if item else None
        spans = [part for part in window.source_intervals if part.evidence_id is None] if window else []
        total = sum(part.end_seconds - part.start_seconds for part in spans)
        ready = (numeric(code) is not None and available and window and window.status == "confirmed" and amount
                 and item.whole_interval_observed and amount.whole_interval_judged and total > 0 and abs(amount.listened_seconds - total) < 1e-6)
        value = vocal_score(total, amount.cumulative_vocal_seconds) if ready else None
        if ready and value != numeric(code):
            raise ValueError(f"{code}: raw category differs from actual vocal duration")
        vocals[code] = value
        metrics.append(metric(code, (code,), value, reason="실제 전체 구간의 중복 없는 발성 시간 비중" if ready else "실제 전체 구간·전체 청취량·음성 가용 근거 부족",
                              numerator=amount.cumulative_vocal_seconds if ready else None, denominator=total if total > 0 else None))
    initial, later = numeric("개9"), numeric("개10")
    combo = next((row for row in rules["separation_combinations"] if (row["initial"], row["later"]) == (initial, later)), None)
    text = combo["text"] if combo else None
    labels = lambda code, value: next((label.text for label in catalog[code].labels if label.value == value), None)
    if text:
        for code, value in (("개58", alone), ("개11", vocals["개11"])):
            label = labels(code, value)
            text += f" {code}: {label if label else '관찰 근거 부족'}."
    metrics.append(metric("개60", ("개9", "개10", "개58", "개11"), text,
                          reason="S1.1 SEP25 범주 조합과 몸 상태·발성 원문; 숫자 대소로 마음 상태를 판정하지 않음"))
    # Object identity is an explicit observation fact, distinct from procedure compliance.
    before, after, compliance = numeric("개30"), numeric("개34"), numeric("보14")
    object_status, object_reason, object_value = "missing", "입장·퇴장 회피 원값 필요", None
    if compliance == 3 or conditions.same_object is False or any(event.kind == "object_removed" and event.status == "observed" for event in recording.events):
        object_status, object_reason = "invalid", "물건 조건 무효·다른 물건·복지 중단 제거"
    elif compliance not in (1, 2) or conditions.same_object is None:
        object_status, object_reason = "condition_unknown", "보14와 같은 물건 확인 필요"
    elif before is not None and after is not None:
        object_status, object_reason = "calculated", "같은 물건의 개34와 개30 비교; 코접촉 시간은 요구하지 않음"
        object_value = "회피 감소" if after < before else "회피 유지" if after == before else "회피 증가"
    metrics.append(metric("object_change", ("개30", "개34", "보14"), object_value, status=object_status, reason=object_reason, caution=compliance == 2))
    valid_entry = {code: numeric(code) for code in ("개5", "개6", "개30") if numeric(code) is not None}
    if compliance == 3:
        valid_entry.pop("개30", None)
    hesitation = any(value <= -1 for code, value in valid_entry.items() if code != "개30") or valid_entry.get("개30", 0) >= 1
    advance = any(value >= 1 for code, value in valid_entry.items() if code != "개30")
    entry = ("자극에 따라 다름" if hesitation and advance else "주저 근거" if hesitation else "전진 근거" if advance else "뚜렷한 주저·전진 근거 없음") if len(valid_entry) >= 2 else None
    metrics.append(metric("BY", ("개5", "개6", "개30", "보14"), entry, used=tuple(valid_entry),
                          excluded={"개30": "보14=3 조건 무효"} if compliance == 3 else {}, reason="유효 2개 이상; 물건 양수는 주저 근거이며 전진에 합산하지 않음"))
    # A failed stranger contact is not a zero-valued contact observation.
    people = {code: numeric(code) for code in PEOPLE_CODES if numeric(code) is not None}
    excluded = {}
    if numeric("개53") == 2 or not any(event.kind == "stranger_contact_start" and event.status == "observed" for event in recording.events):
        for code in ("개51", "개52"):
            if code in people:
                people.pop(code)
                excluded[code] = "낯선 사람 실제 접촉 미성립"
    n = len(people)
    negative, positive = sum(max(-value, 0) for value in people.values()), sum(max(value, 0) for value in people.values())
    for key, value in (("BD", negative if n else None), ("BE", positive if n else None), ("BF", n if n else None),
                       ("people_negative_mean", negative / n if n >= 4 else None), ("people_positive_mean", positive / n if n >= 4 else None),
                       ("AX", sum(100 - 50 * abs(value) for value in people.values()) / n if n >= 4 else None)):
        metrics.append(metric(key, (*PEOPLE_CODES, "개53"), value, used=tuple(people), excluded=excluded,
                              denominator=n if "mean" in key or key == "AX" else None, internal_only=key == "AX",
                              reason="사람 반응의 방향 원값; 평균과 내부 AX는 유효 4개 이상. 사회성%가 아님"))
    reunion_values = [numeric(code) for code in ("개17", "개19", "개22")]
    ignore = numeric("보12")
    reunion_status = "invalid" if ignore == 3 else "condition_unknown" if ignore not in (1, 2) else "missing" if None in reunion_values else "calculated"
    for key, sign in (("AE", -1), ("AF", 1)):
        value = sum(max(sign * value, 0) for value in reunion_values) if reunion_status == "calculated" else None
        metrics.append(metric(key, ("개17", "개19", "개22", "보12"), value, status=reunion_status, caution=ignore == 2,
                              reason="개17·19·22 세 원값의 방향 합; 보12=1/2 필요, 최대값 6으로 나누지 않음"))
    for key in ("AU", "BK"):
        metrics.append(metric(key, ("개9", "개17", "개18", "개19", "개22", "개23", "보12"), status="policy_pending",
                              reason="복합 관찰 보조서술이며 고정 수치 분기표가 제공되지 않음; 네 애착 유형으로 치환하지 않음"))
    owner = owner_calculation(observations, recording, rules, numeric)
    return CalculationsV4(metrics=tuple(metrics), owner=owner, safe_base=safe_base_sequence_v4(recording))


def owner_calculation(observations, recording, rules, numeric):
    matrix = {(row["code"], row["value"]): row for row in rules["owner_type_points"]}
    items, groups = [], {}
    for code in OWNER_CODES:
        raw = numeric(code)
        point = matrix.get((code, raw))
        scene = next(row["scene"] for row in rules["owner_type_points"] if row["code"] == code)
        observation = observations.get(code)
        reason = "유효 관찰 배점"
        used = point is not None
        evidence = observation.evidence if observation else ()
        if not used:
            reason = "유효 원관찰 없음"
        elif observation.opportunity != "present":
            used, reason = False, "실제 관찰 기회 미확인"
        elif code == "보22" and numeric("보38") not in (2, 3) or code == "보39" and numeric("보38") not in (1, 3) or code == "보24" and numeric("보40") not in (1, 2):
            used, reason = False, "보38/보40 관찰 기회 조건 미충족"
        elif not sum(point["points"]):
            used, reason = False, "세 배점 합 0: 근거 수·장면 평균에서 제외"
        elif not evidence:
            used, reason = False, "실제 사건 영상 근거 없음"
        if used:
            for basis in evidence:
                offset = recording.offset(basis.video_id)
                for event in recording.events:
                    times = recording.event_times(event)
                    applies = not event.affected_codes or code in event.affected_codes
                    if event.status != "observed" or not times or not applies or offset is None:
                        continue
                    start, end = basis.start_seconds - offset, basis.end_seconds - offset
                    segment = next((part for part in recording.segments if part.start_sec is not None and part.end_sec is not None and part.start_sec <= start <= part.end_sec), None)
                    after_stop = event.kind in ("staff_stop", "welfare_stop") and event.segment == (segment.segment if segment else None) and end > times[0]
                    during_action = event.kind == "welfare_action" and start <= times[1] and end >= times[0]
                    if after_stop or during_action:
                        used, reason = False, "직원 중단 지시 뒤 또는 복지 안전조치 근거 제외; 혼합 원값은 다시 관찰 필요"
        points = tuple(point["points"]) if point else None
        items.append(OwnerPointsV4(code=code, value=raw, scene=scene, points=points, used=used, reason=reason, used_evidence=evidence if used else ()))
        if used:
            groups.setdefault(scene, []).append(points)
    means = {scene: tuple(sum(Fraction(row[i]) for row in vectors) / len(vectors) for i in range(3)) for scene, vectors in groups.items()}
    totals = tuple(sum((vector[i] for vector in means.values()), Fraction(0)) for i in range(3))
    count, scenes = sum(item.used for item in items), len(groups)
    limits = rules["owner_type_thresholds"]
    ratios, label = None, None
    if count >= limits["minimum_items"] and scenes >= limits["minimum_scenes"] and sum(totals):
        ratios = tuple(value / sum(totals) for value in totals)
        label = dominant_type(ratios, rules)
    status = "insufficient" if ratios is None else "dominant" if label else "held"
    return OwnerCalculationV4(items=tuple(items), inputs=tuple(observations[code] for code in (*OWNER_CODES, "보38", "보40") if code in observations),
                              scene_means={key: tuple(map(float, value)) for key, value in means.items()}, totals=tuple(map(float, totals)),
                              ratios=tuple(map(float, ratios)) if ratios else None, valid_items=count, valid_scenes=scenes, label=label, status=status,
                              reason="최소 3항목·2장면 필요" if ratios is None else "장면 내 평균→장면 합→정규화; 반올림 전 60%·15%p 임시 기준")
