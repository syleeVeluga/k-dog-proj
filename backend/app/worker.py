"""Single DB-backed worker; requests only enqueue, browser lifetime is irrelevant."""

from contextlib import contextmanager
import json
import threading
import time

from fastapi import HTTPException

from app.analysis import adopt, claim, guard, later, owned_write, step_payload, step_output, write_output
from app.gemini import ProviderError
from app.gemini_v4 import GeminiScorerV4
from app import gemini_keys
from app.maintenance import runtime_lock
from app.media import MediaError
from app.storage import encode, now, uid


class ProviderWaiting(Exception):
    """Retry admission after releasing the reservation transaction."""


def provider_wait_until(db, row):
    until = db.execute("SELECT MAX(json_extract(detail_json,'$.retry_at')) FROM changes "
        "WHERE action='gemini.cooldown'").fetchone()[0]
    fallback = db.execute("SELECT MAX(retry_at) FROM steps WHERE run_id=? AND status='retry_wait' "
        "AND json_extract(usage_json,'$.fallback_status')='backup_retry_wait'", (row["run_id"],)).fetchone()[0]
    return max(until or "", fallback or "")


@contextmanager
def heartbeat(store, row):
    stop = threading.Event()

    def renew():
        while not stop.wait(30):
            try:
                guard(store, row["run_id"], row["claim_token"])
            except (HTTPException, OSError):
                return

    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1)


class Worker:
    def __init__(self, store, *, observer=None, v4_work=None):
        self.store = store
        self.v4_work = v4_work
        # Injection is only a Python test seam; CLI/API never offer a fake provider.
        self.observer = observer if observer is not None else GeminiScorerV4(store)

    def check(self, row):
        return guard(self.store, row["run_id"], row["claim_token"])

    def reserve_call(self, row, step, *, credential_actor=None):
        self.check(row)
        selected = failure = None
        with owned_write(self.store, row, conflict_detail="실행 점유가 변경되었습니다.") as (db, current):
            if provider_wait_until(db, row) > now():
                raise ProviderWaiting()
            limit = json.loads(row["config_snapshot_json"]).get("max_ai_calls", 1000)
            used = db.execute("SELECT COUNT(*) FROM steps WHERE run_id=? AND call_reserved=1", (row["run_id"],)).fetchone()[0]
            if used >= limit:
                raise ProviderError("call_budget_exhausted")
            changed = db.execute("UPDATE steps SET call_reserved=1 WHERE step_id=? AND run_id=? AND status='running' "
                                 "AND claim_token=? AND call_reserved=0", (step["step_id"], row["run_id"], row["claim_token"])).rowcount
            if not changed:
                raise HTTPException(409, "호출은 현재 점유한 attempt에서 한 번만 예약할 수 있습니다.")
            if credential_actor is not None:
                try:
                    selected = gemini_keys.select(self.store, db, row, step, credential_actor)
                except ProviderError as exc:
                    failure = exc
        if failure:
            raise failure
        return selected

    def gemini_request(self, row, step, files, config, context, schema, guard):
        guard()
        observer = self.observer if hasattr(self.observer, "request_v4") else GeminiScorerV4(self.store)
        while True:
            self.wait_for_provider(row, step, guard)
            try:
                selected = self.reserve_call(row, step, credential_actor=context["audit_actor"] if isinstance(observer, GeminiScorerV4) else None)
                break
            except ProviderWaiting:
                continue
        usage = None
        try:
            result = observer.request_v4(files, config, context, schema, guard, selected=selected) if isinstance(observer, GeminiScorerV4) else observer.request_v4(files, config, context, schema, guard)
            usage = result[1]
            return result
        except Exception as exc:
            usage = getattr(exc, "usage", None)
            raise
        finally:
            if isinstance(usage, dict):
                with self.store.connect(write=True) as db:
                    saved = db.execute("SELECT usage_json FROM steps WHERE step_id=? AND run_id=? AND claim_token=?",
                        (step["step_id"], row["run_id"], step["claim_token"])).fetchone()
                    if saved:
                        db.execute("UPDATE steps SET usage_json=? WHERE step_id=?", (encode({**json.loads(saved[0]), **usage}), step["step_id"]))

    def wait_for_provider(self, row, step, check):
        while True:
            check()
            with self.store.connect() as db:
                until = provider_wait_until(db, row)
            if until <= now():
                return
            # No transaction is held across the interruptible wait or transport.
            time.sleep(0.2)

    def stage(self, row, stage, branch, validate, work):
        self.check(row)
        config = json.loads(row["config_snapshot_json"])
        new_group = next((group for group in config.get("stages", []) if (group["stage"], group["key"]) == (stage, branch)), None)
        provider_stage = bool(new_group and new_group["provider_call"])
        with self.store.connect() as db:
            previous = db.execute("SELECT * FROM steps WHERE run_id=? AND stage=? AND branch_key=? ORDER BY attempt DESC LIMIT 1",
                                  (row["run_id"], stage, branch)).fetchone()
        if previous and previous["status"] == "succeeded":
            return validate(step_payload(self.store, row, previous))
        if provider_stage:
            with self.store.connect() as db:
                waiting = db.execute("SELECT 1 FROM steps WHERE run_id=? AND status='retry_wait' AND retry_at>? "
                                     "AND json_extract(usage_json,'$.fallback_status')='backup_retry_wait' LIMIT 1", (row["run_id"], now())).fetchone()
            if waiting:
                return None
        if previous and previous["status"] == "failed" and not row.get("retry_failed", False):
            return None
        if previous and previous["status"] == "running":
            if previous["claim_token"] == row["claim_token"]:
                return None
            # The latest uncommitted attempt is eligible only before a new attempt exists.
            ref = f"runs/{row['run_id']}/{previous['step_id']}/output.json"
            try:
                payload, ref, output_hash, _ = step_output(self.store, row, previous, recover=True)
                parsed = validate(payload)
                adopt(self.store, row, previous, ref, output_hash, payload.get("usage", {}))
                return parsed
            except (HTTPException, ValueError, KeyError, OSError):
                self.check(row)
                with owned_write(self.store, row, conflict_detail="복구 중 실행 점유가 변경되었습니다.") as (db, current):
                    db.execute("UPDATE steps SET status='abandoned',usage_json=?,updated_at=? WHERE step_id=? AND status='running'",
                               (encode({**json.loads(previous["usage_json"]), "code": "worker_interrupted", "billing_uncertain": bool(provider_stage and previous["call_reserved"])}), now(), previous["step_id"]))
        attempt = previous["attempt"] + 1 if previous else 1
        maximum = json.loads(row["config_snapshot_json"]).get("max_attempts", 3)
        if attempt > maximum:
            return None
        if previous and previous["status"] == "retry_wait" and previous["retry_at"] > now():
            return None
        # Schema repair has its own one-repair cap inside the shared three-attempt budget.
        schema_code = "v4_schema_invalid"
        repair_limit = config.get("max_schema_repairs", 1)
        if provider_stage:
            with self.store.connect() as db:
                history = [json.loads(s[0]) for s in db.execute(
                    "SELECT usage_json FROM steps WHERE run_id=? AND stage=? AND branch_key=?", (row["run_id"], stage, branch))]
            if sum(s.get("code") == schema_code for s in history) >= repair_limit + 1:
                return None
        with owned_write(self.store, row, conflict_detail="실행 점유가 변경되었습니다.") as (db, current):
            latest = db.execute("SELECT step_id,status,claim_token FROM steps WHERE run_id=? AND stage=? AND branch_key=? ORDER BY attempt DESC LIMIT 1",
                (row["run_id"], stage, branch)).fetchone()
            if (latest[0] if latest else None) != (previous["step_id"] if previous else None):
                return None
            if latest and (latest["status"] in ("running", "succeeded") or latest["claim_token"] != previous["claim_token"]):
                return None
            if previous and previous["status"] == "retry_wait":
                db.execute("UPDATE steps SET status='superseded',updated_at=? WHERE step_id=? AND status='retry_wait'",
                           (now(), previous["step_id"]))
            step = {"step_id": uid(), "claim_token": row["claim_token"], "attempt": attempt, "stage": stage, "branch_key": branch}
            db.execute("INSERT INTO steps(step_id,run_id,stage,branch_key,attempt,status,claim_token,created_at,updated_at) "
                       "VALUES(?,?,?,?,?,'running',?,?,?)",
                       (step["step_id"], row["run_id"], stage, branch, attempt, row["claim_token"], now(), now()))
        try:
            payload = work(step)
            parsed = validate(payload)
            self.check(row)
            ref, output_hash = write_output(self.store, row, step, payload)
            adopt(self.store, row, step, ref, output_hash, payload.get("usage", {}))
            return parsed
        except ProviderError as exc:
            with self.store.connect() as db:
                schema_failures = sum(json.loads(s[0]).get("code") == schema_code for s in db.execute(
                    "SELECT usage_json FROM steps WHERE run_id=? AND stage=? AND branch_key=?", (row["run_id"], stage, branch)))
            retry = exc.retryable and attempt < maximum and not (exc.code == schema_code and schema_failures >= repair_limit)
            usage = {**exc.usage, "code": exc.code, "billing_uncertain": exc.uncertain}
            self.fail(row, step, "retry_wait" if retry else "failed", usage,
                      later(max(exc.delay, 10 * 2 ** (attempt - 1))), provider_error=exc, maximum=maximum)
        except MediaError as exc:
            self.fail(row, step, "failed", {"code": str(exc)}, None)
        except (ValueError, KeyError):
            with self.store.connect() as db:
                reserved = db.execute("SELECT call_reserved FROM steps WHERE step_id=?", (step["step_id"],)).fetchone()[0]
            self.fail(row, step, "failed", {"code": "artifact_invalid", "billing_uncertain": bool(reserved)}, None)
        return None

    def fail(self, row, step, status, usage, retry_at, *, provider_error=None, maximum=None):
        self.check(row)
        with owned_write(self.store, row, conflict_detail="실행 점유가 변경되었습니다.") as (db, current):
            saved = db.execute("SELECT usage_json FROM steps WHERE step_id=?", (step["step_id"],)).fetchone()
            usage = {**json.loads(saved[0]), **usage}
            if provider_error is not None:
                if provider_error.http_status == 429:
                    self.store.audit(db, usage.get("audit_actor") or row.get("worker_actor") or json.loads(row["input_snapshot_json"])["requested_by"], row["run_id"], "gemini.cooldown",
                        {"retry_at": retry_at, "reason": "project_rate_limit", "step_id": step["step_id"]})
                fallback = gemini_keys.request_fallback(self.store, db, row, step, provider_error, maximum, retry_at=retry_at)
                usage.update(provider_error.usage)
                if fallback:
                    status = "retry_wait"
                    retry_at = provider_error.usage.get("fallback_retry_at") or retry_at
                elif provider_error.usage.get("fallback_status") in ("attempt_limit", "call_limit"):
                    status = "failed"
                if status != "retry_wait":
                    retry_at = None
            db.execute("UPDATE steps SET status=?,usage_json=?,retry_at=?,updated_at=? WHERE step_id=? AND claim_token=? AND status='running'",
                       (status, encode(usage), retry_at, now(), step["step_id"], row["claim_token"]))


    def process(self, row):
        if row["kind"] == "attachment_v4":
            from app import attachment_runs_v4
            return attachment_runs_v4.process(self, row)
        if row["kind"] == "report_v4":
            from app import report_runs_v4
            return report_runs_v4.process(self, row)
        if row["kind"] == "s1":
            from app import run_v4
            return run_v4.process(self, row)
        raise ValueError("unsupported run kind")


    def once(self):
        with runtime_lock(self.store, "worker-execution"):
            return self._once()

    def _once(self):
        row = claim(self.store)
        if row is None:
            return False
        with self.store.connect(write=True) as db:
            from app.run_v4 import execution_actor
            row["worker_actor"] = execution_actor(db, row["run_id"], json.loads(row["input_snapshot_json"])["requested_by"],
                "report.s1.retry" if row["kind"] == "report_v4" else "run_v4.retry")
            self.store.audit(db, row["worker_actor"], row["run_id"], "worker.cycle_started", {"claim_token": row["claim_token"]})
        try:
            with heartbeat(self.store, row):
                self.process(row)
        except (HTTPException, OSError, ValueError, KeyError):
            with self.store.connect(write=True) as db:
                current = db.execute("SELECT * FROM cases WHERE case_id=?", (row["case_id"],)).fetchone()
                stopped = not current
                changed = db.execute("UPDATE runs SET status=?,claim_token=NULL,lease_expires_at=NULL,updated_at=? "
                           "WHERE run_id=? AND claim_token=? AND status='running'",
                           ("stopped" if stopped else "failed", now(), row["run_id"], row["claim_token"])).rowcount
                if changed:
                    for step in db.execute("SELECT * FROM steps WHERE run_id=? AND status='running'", (row["run_id"],)).fetchall():
                        usage = {**json.loads(step["usage_json"]), "code": "worker_interrupted",
                                 "billing_uncertain": bool(step["call_reserved"])}
                        db.execute("UPDATE steps SET usage_json=?,updated_at=? WHERE step_id=?", (encode(usage), now(), step["step_id"]))
        finally:
            with self.store.connect(write=True) as db:
                self.store.audit(db, row["worker_actor"], row["run_id"], "worker.cycle_drained", {"claim_token": row["claim_token"]})
        return True

    def run(self):
        while True:
            if not self.once():
                time.sleep(2)
