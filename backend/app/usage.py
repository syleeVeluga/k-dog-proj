"""Read-only attempt accounting and explicit, user-priced meter estimates."""

from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json

from app.storage import now


def amount(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("단가는 유한한 0 이상의 숫자여야 합니다.") from None
    if not result.is_finite() or result < 0:
        raise ValueError("단가는 유한한 0 이상의 숫자여야 합니다.")
    return result


def validate_prices(prices):
    if prices is None:
        return
    if not isinstance(prices, dict) or set(prices) != {"currency", "as_of", "source", "models"}:
        raise ValueError("단가 파일은 currency/as_of/source/models가 필요합니다.")
    if any(not isinstance(prices[k], str) or not prices[k].strip() for k in ("currency", "as_of", "source")):
        raise ValueError("단가 통화·확인일·출처를 명시하세요.")
    if not isinstance(prices["models"], dict):
        raise ValueError("models는 provider/model별 객체여야 합니다.")
    for rates in prices["models"].values():
        if not isinstance(rates, dict) or not rates:
            raise ValueError("모델별 사용량 필드와 백만 단위당 단가가 필요합니다.")
        for meter, rate in rates.items():
            if "token" not in meter.lower():
                raise ValueError("기록된 token 사용량 필드만 단가에 사용할 수 있습니다.")
            amount(rate)


def token_meters(value, prefix=""):
    meters = {}
    for key, item in value.items():
        name = prefix + key
        if isinstance(item, dict):
            meters.update(token_meters(item, name + "."))
        elif "token" in name.lower() and type(item) is int and item >= 0:
            meters[name] = item
    return meters


def summarize(store, *, event_id=None, prices=None):
    validate_prices(prices)
    with store.connect() as db:
        # Hold one read snapshot across run and attempt queries.
        db.execute("BEGIN")
        runs = db.execute("SELECT r.*,c.event_id,c.participant_id FROM runs r JOIN cases c ON c.case_id=r.case_id "
                          "WHERE c.deletion_requested=0 AND (? IS NULL OR c.event_id=?) ORDER BY r.created_at,r.run_id",
                          (event_id, event_id)).fetchall()
        steps = db.execute("SELECT s.* FROM steps s JOIN runs r ON r.run_id=s.run_id JOIN cases c ON c.case_id=r.case_id "
                           "WHERE c.deletion_requested=0 AND (? IS NULL OR c.event_id=?) ORDER BY s.created_at,s.step_id",
                           (event_id, event_id)).fetchall()
    by_run = {row["run_id"]: [] for row in runs}
    for step in steps:
        by_run[step["run_id"]].append(step)
    groups = {}
    results = []
    known_cost = Decimal(0)
    unknown = reserved_count = unreserved_count = reused_count = 0
    for run in runs:
        records = []
        config = json.loads(run["config_snapshot_json"])
        for step in by_run[run["run_id"]]:
            if step["stage"] not in ("observe", "review_video", "evaluate", "report"):
                continue
            if json.loads(step["usage_json"]).get("program_merge"):
                continue
            if not step["call_reserved"]:
                if json.loads(step["usage_json"]).get("reused"):
                    reused_count += 1
                else:
                    unreserved_count += 1
                continue  # Reused artifacts retain source usage; never charge it twice.
            reserved_count += 1
            usage = json.loads(step["usage_json"])
            selected = config if step["stage"] in ("observe", "review_video") else (
                config.get("report", {}) if step["stage"] == "report" else
                config.get("evaluation", {}).get(step["branch_key"], {}))
            provider = usage.get("provider", selected.get("provider", "gemini" if step["stage"] in ("observe", "review_video") else "unknown"))
            model = usage.get("model", selected.get("model", "unknown"))
            meters = token_meters(usage)
            uncertain = bool(usage.get("billing_uncertain")) or step["status"] in ("running", "abandoned")
            rates = (prices or {}).get("models", {}).get(f"{provider}/{model}")
            cost = None
            if rates and not uncertain and all(meter in meters for meter in rates):
                cost = sum((Decimal(meters[meter]) * amount(rate) / 1_000_000 for meter, rate in rates.items()), Decimal(0))
                known_cost += cost
            else:
                unknown += 1
            group = groups.setdefault((provider, model, step["stage"]), {"calls_reserved": 0, "meters": Counter()})
            group["calls_reserved"] += 1
            group["meters"].update(meters)
            records.append({"step_id": step["step_id"], "stage": step["stage"], "branch": step["branch_key"],
                "attempt": step["attempt"], "status": step["status"], "provider": provider, "model": model,
                "meters": meters, "billing_uncertain": uncertain, "meter_cost_estimate": str(cost) if cost is not None else None})
        results.append({"event_id": run["event_id"], "participant_id": run["participant_id"],
            "run_id": run["run_id"], "status": run["status"],
            "elapsed_to_last_update_sec": (datetime.fromisoformat(run["updated_at"]) - datetime.fromisoformat(run["created_at"])).total_seconds(),
            "attempts": records})
    return {"generated_at": now(), "scope": "non-deleted operational runs; developer samples excluded",
        "runs": results, "run_statuses": dict(Counter(row["status"] for row in runs)),
        "groups": [{"provider": key[0], "model": key[1], "stage": key[2], **value} for key, value in sorted(groups.items())],
        "calls_reserved": reserved_count, "unreserved_ai_steps": unreserved_count, "reused_ai_steps": reused_count,
        "unpriced_or_uncertain_calls": unknown, "known_meter_cost_estimate": str(known_cost) if prices else None,
        "complete_meter_cost_estimate": str(known_cost) if prices and unknown == 0 and unreserved_count == 0 else None,
        "price_basis": prices,
        "notice": "사용자 지정 계량식의 추정이며 청구액·결제 상한이 아닙니다. 중첩 token 필드·캐시·추론·구간 단가를 확인하세요. "
                  "누락/응답 유실 비용은 미확인입니다. 예약 없는 재사용 및 M5 이전 단계는 비용 합계에서 제외합니다."}
