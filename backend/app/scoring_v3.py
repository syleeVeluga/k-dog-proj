"""Source-defined v3 calculations. Raw directions, missingness and causes are preserved."""

from fractions import Fraction
import hashlib
import json

from fastapi import HTTPException

from app.domain.results_v3 import CalculationsV3
from app.domain.validation_v3 import validate_sheet_v3
from app.preprocess_v3 import CATALOG, PROTOCOL
from app.storage import REPO_ROOT, encode

RULE_PATH = REPO_ROOT / "resources/rules/scoring-v3.json"
RULE_BYTES = RULE_PATH.read_bytes()
RULES = json.loads(RULE_BYTES)
RULE_HASH = hashlib.sha256(RULE_BYTES).hexdigest()
RULE_VERSION = "scoring-20260929-v3-app-1"
OWNER_TYPES = ("허용형", "조율형", "통제형")
ATTACHMENT_TYPES = ("곁에서 안심하는 사이", "가까이 있어도 안심이 어려운 사이", "거리를 두고 지내는 사이", "다가감과 물러섬이 함께 나오는 사이")
ENTRY_TYPES = ("주저함 · 거리를 벌림", "뚜렷한 치우침 없음", "살피지 않고 들이닥침", "자극에 따라 다름")
ENV_CODES = ("개5", "개6", "개30")
PEOPLE_CODES = ("개13", "개14", "개15", "개51", "개52", "개54", "개55")
VOCAL_SEGMENTS = {"바6": "entry", "개11": "alone", "개47": "reunion", "개48": "ignore", "개49": "walk", "개50": "stranger"}


def verify_rules():
    if hashlib.sha256(RULE_PATH.read_bytes()).hexdigest() != RULE_HASH:
        raise HTTPException(409, "계산 규칙이 실행 중 변경되었습니다. 앱을 다시 시작하세요.")


def vocal_category(vocal_seconds, actual_seconds):
    vocal, duration = Fraction(str(vocal_seconds)), Fraction(str(actual_seconds))
    if duration <= 0 or vocal < 0 or vocal > duration:
        raise ValueError("vocal amount must fit a positive actual interval")
    return 0 if vocal == 0 else 1 if vocal * 3 <= duration else 2 if vocal * 3 <= duration * 2 else 3


def owner_threshold(totals, items, scenes):
    totals = [value if isinstance(value, Fraction) else Fraction(str(value)) for value in totals]
    if any(value < 0 for value in totals):
        raise ValueError("owner source points cannot be negative")
    total = sum(totals)
    ratios = [value / total for value in totals] if total else None
    limits = RULES["owner_type_thresholds"]
    if items < limits["minimum_items"] or scenes < limits["minimum_scenes"] or not total:
        return ratios, None, "근거3항목·2장면 부족 또는 배점 합0"
    order = sorted(range(3), key=lambda i: totals[i], reverse=True)
    # Compare exact rational points before display rounding, including the 60% and 15%p boundaries.
    if not owner_ratio_gate(ratios[order[0]], ratios[order[1]]):
        return ratios, None, "우세60% 또는 차이15%p 미달·동률"
    return ratios, OWNER_TYPES[order[0]], "v0.2 임시 근거 비율의 자동 초안; 성격 확률이 아님"


def owner_ratio_gate(first, second):
    limits = RULES["owner_type_thresholds"]
    return first >= Fraction(str(limits["dominant_ratio"])) and first - second >= Fraction(str(limits["ratio_gap"]))


def calculate(doc, *, audio_available=None):
    validate_sheet_v3(doc.sheet, CATALOG, PROTOCOL)
    observations = {item.code: item for item in doc.sheet.observations}
    windows = {item.window_id: item for item in doc.source.windows}
    recording = doc.source.session.recording
    offsets = {item.video_id: item.offset_seconds for item in recording.video_offsets if item.confirmed}
    values, descriptions, vocalizations = [], [], []

    def state(code):
        item = observations.get(code)
        if item and item.validity == "invalid":
            return "invalid", f"{code}: 시행 무효; 원자료 보존"
        if not item or item.status != "observed":
            return "missing", f"{code}: {item.reason if item else '원값 미기록'}"
        if item.validity == "unknown":
            return "condition_unknown", f"{code}: 시행 유효성 미확인"
        if code == "개10" and (not windows.get("alone_later") or windows["alone_later"].status != "available"):
            return "missing", "개10: 단축한 후기 관찰을 정상50초로 보간하지 않음"
        return "calculated", None

    def usable(code):
        return state(code)[0] == "calculated"

    def condition(code):
        item = observations.get(code)
        if item and item.status == "observed" and item.value == 3:
            return "invalid", f"{code}=3: 해당 구간/비교 무효"
        status, reason = state(code)
        if status != "calculated":
            return ("invalid" if status == "invalid" else "condition_unknown"), reason
        return "calculated", None

    def dependencies(codes, guard=None):
        checks = [condition(guard)] if guard else []
        checks += [state(code) for code in codes]
        for status in ("invalid", "condition_unknown", "missing", "policy_pending"):
            reasons = [reason for current, reason in checks if current == status]
            if reasons:
                return status, "; ".join(reasons)
        return "calculated", None

    def metric(key, codes, value=None, guard=None, check=None):
        status, reason = check or dependencies(codes, guard)
        if status == "calculated" and guard and observations[guard].value == 2:
            label = next(label.text for item in CATALOG.items if item.code == guard for label in item.labels if label.value == 2)
            reason = f"{guard}=2: {label}; 주의 조건을 원값과 함께 보존"
        result = {"key": key, "input_codes": [*codes, *([guard] if guard and guard not in codes else [])],
                  "value": value if status == "calculated" else None, "status": status, "reason": reason}
        values.append(result)
        return result

    walk_codes = tuple(f"개{number}" for number in range(38, 44))
    walk_check = dependencies(walk_codes, "보13")
    move = sum(observations[code].value <= 1 for code in ("개38", "개40", "개42")) if walk_check[0] == "calculated" else None
    stop = sum(observations[code].value <= 1 for code in ("개39", "개41", "개43")) if walk_check[0] == "calculated" else None
    metric("개26", walk_codes, move, "보13", walk_check)
    metric("개36", walk_codes, stop, "보13", walk_check)
    metric("개27", walk_codes, (move + stop) / 6 if move is not None else None, "보13", walk_check)
    for key, codes, guard in (("separation_reunion_body", ("개58", "개18"), None), ("baseline_ignore_body", ("개8", "개23"), "보12")):
        check = dependencies(codes, guard)
        raw = abs(observations[codes[0]].value) - abs(observations[codes[1]].value) if check[0] == "calculated" else None
        metric(key, codes, raw, guard, check)
    latency_check = state("개32")
    latency = observations.get("개32")
    if latency_check[0] == "calculated" and latency.latency_not_occurred:
        latency_check = "missing", "개32=99는 미발생 원코드이며 실제99초가 아님"
    metric("object_latency_seconds", ("개32",), latency.actual_latency_seconds if latency else None, check=latency_check)

    separation_check = dependencies(("개9", "개10"))
    text = None
    if separation_check[0] == "calculated":
        text = next(item["text"] for item in RULES["separation_combinations"] if (item["initial"], item["later"]) == (observations["개9"].value, observations["개10"].value))
        for code, name in (("개58", "몸 상태"), ("개11", "발성")):
            item = next(item for item in CATALOG.items if item.code == code)
            label = next(label.text for label in item.labels if label.value == observations[code].value) if usable(code) else "미확인"
            text += f" / 분리 전체 {name}: {label}"
    descriptions.append({"key": "개60", "input_codes": ["개9", "개10", "개58", "개11"], "text": text,
                         "status": separation_check[0], "reason": separation_check[1]})

    directions, technical = [], {}
    contact_events = [item for item in recording.events if item.kind == "stranger_contact_start"]
    contact = True if any(item.status == "observed" for item in contact_events) else False if any(item.status == "not_occurred" for item in contact_events) else None
    for key, codes, minimum, guard in (("environment", ENV_CODES, 2, "보14"), ("people", PEOPLE_CODES, 4, None)):
        present = {code: observations[code].value for code in codes if usable(code)}
        check = condition(guard) if guard else ("calculated", None)
        if check[0] == "calculated" and len(present) < minimum:
            invalid = [state(code) for code in codes if state(code)[0] == "invalid"]
            check = invalid[0] if invalid else ("missing", f"{key}: 관찰{minimum}항목 필요, 현재{len(present)}항목")
        value = sum(100 - 50 * abs(raw) for raw in present.values()) / len(present) if check[0] == "calculated" else None
        metric("AW" if key == "environment" else "AX", codes, value, guard, check)
        technical[key] = value, len(present), check
        negative, positive = sum(max(0, -raw) for raw in present.values()), sum(max(0, raw) for raw in present.values())
        direction = "양방향 관찰" if negative and positive else "−방향 관찰" if negative else "+방향 관찰" if positive else "중앙범주만 관찰"
        directions.append({"key": key, "raw_values": present, "negative_sum": negative if present else None,
                           "positive_sum": positive if present else None, "observed_items": len(present),
                           "status": direction if check[0] == "calculated" else check[1], "actual_contact": contact if key == "people" else None})
    aw, env_count, env_check = technical["environment"]
    ax, people_count, people_check = technical["people"]
    combined_check = next((check for status in ("invalid", "condition_unknown", "missing", "policy_pending")
                           for check in (env_check, people_check) if check[0] == status), ("calculated", None))
    metric("AY", (*ENV_CODES, *PEOPLE_CODES), (aw * env_count + ax * people_count) / (env_count + people_count) if aw is not None and ax is not None else None,
           "보14", combined_check)

    for key, codes, minimum, guard in (("reunion_ignore", ("개17", "개19", "개22"), 3, "보12"),
                                      ("body_sign_counts", ("개8", "개14", "개18", "개23", "개44", "개52", "개58"), 1, None)):
        present = {code: observations[code].value for code in codes if usable(code)}
        negative = sum(value < 0 if key == "body_sign_counts" else max(0, -value) for value in present.values())
        positive = sum(value > 0 if key == "body_sign_counts" else max(0, value) for value in present.values())
        check = condition(guard) if guard else ("calculated", None)
        status = "양방향 관찰" if negative and positive else "−방향 관찰" if negative else "+방향 관찰" if positive else "중앙범주만 관찰"
        if check[0] != "calculated" or len(present) < minimum:
            status = check[1] or f"관찰{minimum}항목 필요; 자료 부족"
        actual_reunion = [event for event in recording.events if event.kind == "reunion_contact_start"]
        reunion_contact = True if any(event.status == "observed" for event in actual_reunion) else False if any(event.status == "not_occurred" for event in actual_reunion) else None
        directions.append({"key": key, "raw_values": present, "negative_sum": negative if present else None,
                           "positive_sum": positive if present else None, "observed_items": len(present), "status": status,
                           "actual_contact": reunion_contact if key == "reunion_ignore" else None})

    for code, segment in VOCAL_SEGMENTS.items():
        window, item = windows.get(segment), observations.get(code)
        duration = window.end_sec - window.start_sec if window and window.start_sec is not None else None
        available = (audio_available or {}).get(code, (audio_available or {}).get(segment))
        amount = item.vocalization if item else None
        check = state(code)
        if check[0] == "calculated":
            if duration is None or not amount or available is None:
                check = "missing", "실제 구간/음성 사용 가능량/청취·누적 발성량 미확인"
            elif amount.listened_seconds > duration or amount.cumulative_vocal_seconds > duration:
                check = "invalid", "청취/발성량이 실제 구간 길이를 벗어남"
            elif available < duration or not amount.whole_interval_judged or amount.listened_seconds < duration:
                check = "missing", "일부 청취로 전체 발성 비중을 판단할 수 없음; 실제 분모 유지"
        category = vocal_category(amount.cumulative_vocal_seconds, duration) if check[0] == "calculated" else None
        if category is not None and category != item.value:
            check = "invalid", "누적 발성 비중의 범주와 평가 원코드가 다름; 원자료 정정 필요"
        result = metric("vocal_" + code, (code,), category, check=check)
        vocalizations.append({"code": code, "actual_interval_seconds": duration, "audio_available_seconds": available,
                              "listened_seconds": amount.listened_seconds if amount else None,
                              "cumulative_vocal_seconds": amount.cumulative_vocal_seconds if amount else None, "result": result})

    owner_items, scene_points = [], {}
    for code in ("보6", "보9", "보22", "보39", "보23", "보24"):
        item = observations.get(code)
        rows = [point for point in RULES["owner_type_points"] if point["code"] == code]
        scene = rows[0]["scene"]
        raw = item.value if item and item.status == "observed" else None
        point = next((row["points"] for row in rows if row["raw_value"] == raw), None)
        status, reason = state(code)
        used, excluded = [], []
        for evidence in item.evidence if item else ():
            basis = evidence.model_dump(mode="json")
            event_ids, exclusion = [], None
            if evidence.observed_seconds <= 0 or evidence.end_seconds <= evidence.start_seconds:
                exclusion = "실제 확인량/관찰기간 없음; 원자료 보존"
            if evidence.scoring_exclusion != "none":
                exclusion = "명시 배점 제외: " + evidence.scoring_exclusion
            end = evidence.end_seconds - offsets.get(evidence.video_id, 0)
            parent = windows.get(evidence.window_id)
            for event in recording.events:
                if event.status != "observed" or not parent or event.segment not in (None, parent.segment) or event.affected_codes and code not in event.affected_codes:
                    continue
                stop_at = event.seconds - offsets.get(event.video_id, 0)
                if (event.kind in ("welfare_stop", "staff_stop") or code == "보22" and event.kind == "reunion_name") and end > stop_at:
                    event_ids.append(event.event_id)
                    exclusion = "중단/지시 뒤 조치 또는 경계를 걸친 근거: 앞뒤 원자료를 분리해 기록"
            if exclusion:
                excluded.append({"evidence": basis, "reason": exclusion, "event_ids": event_ids})
            else:
                used.append(basis)
        if status == "calculated" and code in ("보6", "보9") and item.opportunity != "present":
            status, reason = "condition_unknown", "실제 당김/버팀 사건의 기회 미확인"
        opportunity = {"보22": ("보38", (2, 3)), "보39": ("보38", (1, 3)), "보24": ("보40", (1, 2))}.get(code)
        if status == "calculated" and opportunity:
            guard, allowed = opportunity
            if not usable(guard):
                status, reason = "condition_unknown", f"{guard}: 실제 관찰 기회 미확인"
            elif observations[guard].value not in allowed:
                status, reason = "missing", f"{guard}: 해당 대응 기회 없음"
        relevant_stops = [event for event in recording.events if event.kind in ("welfare_stop", "staff_stop") and event.status == "observed"
                          and (not event.affected_codes or code in event.affected_codes)
                          and any(event.segment in (None, windows[basis["window_id"]].segment) for basis in used)]
        if status == "calculated" and item.welfare_stopped and not excluded and not relevant_stops:
            status, reason = "policy_pending", "Q05 중단 영향의 실제 경계/배점 제외 근거 미확인"
        if status == "calculated" and (not used or not point or sum(point) == 0):
            status, reason = "missing", "배점 근거 없음/전부 제외 또는 모든 유형0배점 범주"
        accepted = status == "calculated"
        owner_items.append({"code": code, "scene": scene, "raw_value": raw, "points": point, "used": accepted,
                            "reason": "실제 기회·유효 근거의 원항목 배점" if accepted else reason,
                            "used_evidence": used if accepted else [], "excluded_evidence": excluded})
        if accepted:
            scene_points.setdefault(scene, []).append(point)
    means = {scene: [sum(Fraction(row[index]) for row in rows) / len(rows) for index in range(3)] for scene, rows in scene_points.items()}
    totals = [sum((row[index] for row in means.values()), Fraction(0)) for index in range(3)]
    count = sum(item["used"] for item in owner_items)
    ratios, label, owner_reason = owner_threshold(totals, count, len(means))
    owner = {"items": owner_items, "scene_means": {key: [float(value) for value in row] for key, row in means.items()},
             "totals": [float(value) for value in totals], "ratios": [float(value) for value in ratios] if ratios else None,
             "evidence_items": count, "scenes": len(means), "label": label, "status": "draft" if label else "held", "reason": owner_reason}

    entry = {code: observations[code].value for code in ENV_CODES if usable(code) and (code != "개30" or condition("보14")[0] == "calculated")}
    entry_label = None
    if len(entry) >= 2:
        negative = sum(value <= -1 for value in entry.values())
        positive = sum(value >= 1 for value in entry.values())
        entry_label = "자극에 따라 다름" if negative and positive else "주저함 · 거리를 벌림" if negative >= 2 else "살피지 않고 들이닥침" if positive >= 2 else "뚜렷한 치우침 없음"
    comparisons = {key: [observations[code].model_dump(mode="json") for code in codes if code in observations] for key, codes in
                   (("object", ("개30", "개34", "개32")), ("tail", ("바38", "바39", "바43", "바44", "바45")),
                    ("body", ("개8", "개23", "개58", "개18")), ("entry", (*ENV_CODES, "바5", "바6", "바7", "바14", "바15", "바16", "개7", "보14")))}
    return CalculationsV3.model_validate_json(encode({"values": values, "descriptions": descriptions, "directions": directions,
        "owner": owner, "vocalizations": vocalizations, "raw_observations": [item.model_dump(mode="json") for item in doc.sheet.observations],
        "entry_label": entry_label, "entry_reason": "02 BV/BW/BX/BY의 입장 자동 초안; 원항목·몸 신호·실제 조건과 함께 검토, Q06 완료 조건 확인 대기" if entry_label else "입장 원항목2개 미만 또는 시행 유효성 미확인; 자동 판단 보류", "comparisons": comparisons}))
