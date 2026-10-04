"""Single DB-backed worker; requests only enqueue, browser lifetime is irrelevant."""

from contextlib import contextmanager
import json
import threading
import time

from fastapi import HTTPException

from app.analysis import adopt, check_access, claim, guard, later, step_payload, step_output, write_output
from app.gemini import ProviderError
from app.gemini_v4 import GeminiScorerV4
from app.media import MediaError
from app.storage import encode, now, uid


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

    def reserve_call(self, row, step):
        self.check(row)
        with self.store.connect(write=True) as db:
            current = db.execute("SELECT * FROM runs WHERE run_id=?", (row["run_id"],)).fetchone()
            if current["claim_token"] != row["claim_token"] or current["status"] != "running" or current["lease_expires_at"] <= now():
                raise HTTPException(409, "실행 점유가 변경되었습니다.")
            check_access(self.store, db, current)
            limit = json.loads(row["config_snapshot_json"]).get("max_ai_calls", 1000)
            used = db.execute("SELECT COUNT(*) FROM steps WHERE run_id=? AND call_reserved=1", (row["run_id"],)).fetchone()[0]
            if used >= limit:
                raise ProviderError("call_budget_exhausted")
            changed = db.execute("UPDATE steps SET call_reserved=1 WHERE step_id=? AND run_id=? AND status='running' "
                                 "AND claim_token=? AND call_reserved=0", (step["step_id"], row["run_id"], row["claim_token"])).rowcount
            if not changed:
                raise HTTPException(409, "호출은 현재 점유한 attempt에서 한 번만 예약할 수 있습니다.")

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
        if previous and previous["status"] == "failed" and not row.get("retry_failed", False):
            return None
        if previous and previous["status"] == "running":
            # The latest uncommitted attempt is eligible only before a new attempt exists.
            ref = f"runs/{row['run_id']}/{previous['step_id']}/output.json"
            try:
                payload, ref, output_hash, _ = step_output(self.store, row, previous, recover=True)
                parsed = validate(payload)
                adopt(self.store, row, previous, ref, output_hash, payload.get("usage", {}))
                return parsed
            except (HTTPException, ValueError, KeyError, OSError):
                self.check(row)
                with self.store.connect(write=True) as db:
                    current = db.execute("SELECT * FROM runs WHERE run_id=?", (row["run_id"],)).fetchone()
                    if current["claim_token"] != row["claim_token"] or current["status"] != "running" or current["lease_expires_at"] <= now():
                        raise HTTPException(409, "복구 중 실행 점유가 변경되었습니다.")
                    check_access(self.store, db, current)
                    db.execute("UPDATE steps SET status='abandoned',usage_json=?,updated_at=? WHERE step_id=? AND status='running'",
                               (encode({"code": "worker_interrupted", "billing_uncertain": bool(provider_stage and previous["call_reserved"])}), now(), previous["step_id"]))
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
        with self.store.connect(write=True) as db:
            current = db.execute("SELECT * FROM runs WHERE run_id=?", (row["run_id"],)).fetchone()
            if current["claim_token"] != row["claim_token"] or current["status"] != "running" or current["lease_expires_at"] <= now():
                raise HTTPException(409, "실행 점유가 변경되었습니다.")
            check_access(self.store, db, current)
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
            usage = {**exc.usage, "code": exc.code, "billing_uncertain": exc.uncertain}
            with self.store.connect() as db:
                schema_failures = sum(json.loads(s[0]).get("code") == schema_code for s in db.execute(
                    "SELECT usage_json FROM steps WHERE run_id=? AND stage=? AND branch_key=?", (row["run_id"], stage, branch)))
            retry = exc.retryable and attempt < maximum and not (exc.code == schema_code and schema_failures >= repair_limit)
            self.fail(row, step, "retry_wait" if retry else "failed", usage,
                      later(max(exc.delay, 10 * 2 ** (attempt - 1))) if retry else None)
        except MediaError as exc:
            self.fail(row, step, "failed", {"code": str(exc)}, None)
        except (ValueError, KeyError):
            with self.store.connect() as db:
                reserved = db.execute("SELECT call_reserved FROM steps WHERE step_id=?", (step["step_id"],)).fetchone()[0]
            self.fail(row, step, "failed", {"code": "artifact_invalid", "billing_uncertain": bool(reserved)}, None)
        return None

    def fail(self, row, step, status, usage, retry_at):
        self.check(row)
        with self.store.connect(write=True) as db:
            current = db.execute("SELECT * FROM runs WHERE run_id=?", (row["run_id"],)).fetchone()
            if current["claim_token"] != row["claim_token"] or current["status"] != "running":
                raise HTTPException(409, "실행 점유가 변경되었습니다.")
            check_access(self.store, db, current)
            db.execute("UPDATE steps SET status=?,usage_json=?,retry_at=?,updated_at=? WHERE step_id=? AND claim_token=? AND status='running'",
                       (status, encode(usage), retry_at, now(), step["step_id"], row["claim_token"]))


    def process(self, row):
        if row["kind"] == "report_v4":
            from app import report_runs_v4
            return report_runs_v4.process(self, row)
        if row["kind"] == "s1":
            from app import run_v4
            return run_v4.process(self, row)
        raise ValueError("unsupported run kind")


    def once(self):
        row = claim(self.store)
        if row is None:
            return False
        try:
            with heartbeat(self.store, row):
                self.process(row)
        except (HTTPException, OSError, ValueError, KeyError):
            with self.store.connect(write=True) as db:
                current = db.execute("SELECT * FROM cases WHERE case_id=?", (row["case_id"],)).fetchone()
                stopped = not current or current["deletion_requested"]
                changed = db.execute("UPDATE runs SET status=?,claim_token=NULL,lease_expires_at=NULL,updated_at=? "
                           "WHERE run_id=? AND claim_token=? AND status='running'",
                           ("stopped" if stopped else "failed", now(), row["run_id"], row["claim_token"])).rowcount
                if changed:
                    for step in db.execute("SELECT * FROM steps WHERE run_id=? AND status='running'", (row["run_id"],)).fetchall():
                        usage = {**json.loads(step["usage_json"]), "code": "worker_interrupted",
                                 "billing_uncertain": bool(step["call_reserved"])}
                        db.execute("UPDATE steps SET usage_json=?,updated_at=? WHERE step_id=?", (encode(usage), now(), step["step_id"]))
        return True

    def run(self):
        while True:
            if not self.once():
                time.sleep(2)
