"""Run-local Gemini credential choice; caller holds the reservation write fence."""

import json

from app import secrets
from app.gemini import ProviderError
from app.storage import encode, now


POLICY = "gemini-primary-backup-v1"


def selection(db, run_id):
    row = db.execute("SELECT detail_json FROM changes WHERE target=? AND action IN "
                     "('gemini.credential_selected','gemini.fallback_requested') ORDER BY rowid DESC LIMIT 1", (run_id,)).fetchone()
    return json.loads(row[0]) if row else {}


def select(store, db, row, step, actor):
    previous = selection(db, row["run_id"])
    slot = previous.get("credential_slot", "primary")
    reason = previous.get("fallback_reason")
    try:
        key, reference = secrets._credential(store, db, "gemini", slot)
    except ProviderError as exc:
        if slot == "backup":
            exc.usage = {"credential_policy": POLICY, "credential_slot": slot, "fallback_reason": reason,
                         "fallback_status": "backup_unavailable"}
            raise
        reason = "primary_" + exc.credential_reason
        try:
            key, reference = secrets._credential(store, db, "gemini", "backup")
        except ProviderError as missing:
            missing.usage = {"credential_policy": POLICY, "credential_slot": "primary", "fallback_reason": reason,
                             "fallback_status": "backup_unavailable"}
            raise missing from None
        slot = "backup"
    metadata = {"credential_policy": POLICY, "credential_slot": slot, "credential_reference": reference,
                "fallback_reason": reason, "step_id": step["step_id"], "attempt": step["attempt"],
                "audit_actor": actor, "selected_at": now()}
    store.audit(db, actor, row["run_id"], "gemini.credential_selected", metadata)
    db.execute("UPDATE steps SET usage_json=? WHERE step_id=?", (encode(metadata), step["step_id"]))
    return key, metadata


def fallback_reason(exc):
    if exc.usage.get("credential_slot") != "primary" or exc.usage.get("operation_phase") not in ("upload", "processing", "inference"):
        return None
    status = exc.http_status
    if status in (401, 402, 403):
        return {401: "primary_authentication", 402: "primary_payment_required", 403: "primary_permission_denied"}[status]
    if status == 400 and exc.provider_code == "API_KEY_INVALID":
        return "primary_api_key_invalid"
    if status == 429:
        return "primary_rate_limit"
    if status in (500, 502, 503, 504):
        return "primary_service_unavailable"
    if exc.code in ("provider_connection_lost", "remote_processing_timeout"):
        return "primary_connection_lost"
    return None


def request_fallback(store, db, row, step, exc, maximum):
    reason = fallback_reason(exc)
    if not reason:
        return False
    limit = json.loads(row["config_snapshot_json"]).get("max_ai_calls", 1000)
    used = db.execute("SELECT COUNT(*) FROM steps WHERE run_id=? AND call_reserved=1", (row["run_id"],)).fetchone()[0]
    if step["attempt"] >= maximum or used >= limit:
        exc.usage["fallback_status"] = "attempt_limit" if step["attempt"] >= maximum else "call_limit"
        return False
    try:
        secrets._credential(store, db, "gemini", "backup")
    except ProviderError:
        exc.usage["fallback_status"] = "backup_unavailable"
        return False
    exc.usage.update(fallback_reason=reason, fallback_status="backup_retry_wait")
    store.audit(db, exc.usage["audit_actor"], row["run_id"], "gemini.fallback_requested",
                {"credential_policy": POLICY, "credential_slot": "backup", "fallback_reason": reason,
                 "fallback_status": "backup_retry_wait",
                 "step_id": step["step_id"], "attempt": step["attempt"], "selected_at": now()})
    return True


def view(db, run_id):
    return public(selection(db, run_id))


def public(usage):
    reasons = ("primary_unregistered", "primary_removed", "primary_file_unavailable", "primary_decrypt_failed", "primary_restore_required",
               "primary_authentication", "primary_payment_required", "primary_permission_denied", "primary_api_key_invalid",
               "primary_rate_limit", "primary_service_unavailable", "primary_connection_lost")
    return {"credential_slot": usage.get("credential_slot") if usage.get("credential_slot") in ("primary", "backup") else None,
            "fallback_reason": usage.get("fallback_reason") if usage.get("fallback_reason") in reasons else None,
            "fallback_status": usage.get("fallback_status") if usage.get("fallback_status") in ("backup_unavailable", "attempt_limit", "call_limit", "backup_retry_wait") else None,
            "credential_selected_at": usage.get("selected_at") if isinstance(usage.get("selected_at"), str) else None,
            "source_credential_slot": usage.get("source_credential_slot") if usage.get("source_credential_slot") in ("primary", "backup") else None,
            "source_fallback_reason": usage.get("source_fallback_reason") if usage.get("source_fallback_reason") in reasons else None}


def reused_usage(usage, source_run_id):
    source = public(usage)
    return {"reused": True, "source_run_id": source_run_id,
            "source_credential_slot": source["credential_slot"] or source["source_credential_slot"],
            "source_fallback_reason": source["fallback_reason"] or source["source_fallback_reason"]}
