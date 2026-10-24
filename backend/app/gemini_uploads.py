"""Run-owned remote video reuse. Owners close only after every request drains."""

from contextlib import contextmanager
import copy
import hashlib
import json
import re
import threading
import time

from .gemini import BASE, ProviderError
from .storage import encode, now, uid

POLICY = "s1-shared-video-20261024"


class UploadPool:
    def __init__(self, store, transport, clock_id):
        self.store, self.transport, self.clock_id = store, transport, clock_id
        self.condition = threading.Condition()
        self.runs, self.entries, self.retired, self.users = {}, {}, {}, {}

    def begin(self, row):
        self.runs[row["run_id"]] = (row["claim_token"], row["worker_actor"])
        grouped = {}
        for value in self.pending(row["run_id"]).values():
            grouped.setdefault(value["cache_key"], []).append(value)
        known = {e["upload_id"] for (s, _), e in self.entries.items() if s == row["run_id"]}
        known.update(e["upload_id"] for e in self.retired.get(row["run_id"], []))
        for cache_key, values in grouped.items():
            for value in reversed(values):
                if value["upload_id"] in known:
                    continue
                entry = {"loading": False, "attempt": 0, "key": None,
                    "metadata": {"credential_reference": value["credential_reference"]},
                    "context": {"run_id": row["run_id"], "audit_actor": row["worker_actor"]},
                    "remote": {"name": value["remote_file_name"]}, "upload_id": value["upload_id"], "claim": None}
                identity = row["run_id"], cache_key
                if identity not in self.entries:
                    self.entries[identity] = entry
                else:
                    self.retired.setdefault(row["run_id"], []).append(entry)

    def audit(self, context, metadata, action, detail):
        with self.store.connect(write=True) as db:
            self.store.audit(db, context["audit_actor"], context["run_id"], action, {**metadata, **detail})

    def timed(self, usage, phase, work):
        start = time.monotonic()
        try:
            return work()
        finally:
            end = time.monotonic()
            usage["timing"][phase] += end-start
            usage["provider_intervals"].append({"clock_id": self.clock_id, "phase": phase, "start": start, "end": end})

    @contextmanager
    def request(self, context, usage):
        shared = context["run_id"] in self.runs
        scope = context["run_id"] if shared else uid()
        with self.condition:
            self.users[scope] = self.users.get(scope, 0)+1
        try:
            yield scope, shared
        finally:
            with self.condition:
                self.users[scope] -= 1
                self.condition.notify_all()
            if not shared:
                self.close(scope, usage)
            else:
                usage["remote_cleanup_deferred"] = True
                usage["remote_cleanup_pending"] = False

    def pending(self, run_id):
        with self.store.connect() as db:
            rows = db.execute("SELECT actor,action,detail_json FROM changes WHERE target=? AND action IN "
                              "('remote.uploaded','remote.deleted') ORDER BY rowid", (run_id,)).fetchall()
        pending = {}
        for row in rows:
            value = json.loads(row["detail_json"])
            if row["action"] == "remote.deleted":
                pending.pop(value["upload_id"], None)
            elif value.get("upload_cache_policy") == POLICY:
                pending[value["upload_id"]] = {**value, "actor": row["actor"]}
        return pending

    def active(self, remote, key, guard, usage):
        start = time.monotonic()
        try:
            while remote.get("state") == "PROCESSING":
                if time.monotonic()-start >= 300:
                    raise ProviderError("remote_processing_timeout", retryable=True)
                guard()
                time.sleep(2)
                guard()
                remote, _ = self.transport("GET", BASE+"/v1beta/"+remote["name"], key)
        finally:
            usage["timing"]["processing_seconds"] += time.monotonic()-start
        if remote.get("state") != "ACTIVE":
            raise ProviderError("remote_file_failed")
        return remote

    def get(self, scope, shared, path, clip, key, metadata, context, guard, usage):
        guard()
        if clip.size_bytes > 2_000_000_000:
            raise ProviderError("v4_file_size_limit")
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if path.stat().st_size != clip.size_bytes or digest != getattr(clip, "sha256", digest):
            raise ProviderError("video_file_changed")
        cache_key = hashlib.sha256(encode({"hash": digest, "credential": metadata["credential_reference"]}).encode()).hexdigest()
        identity = scope, cache_key
        claim = self.runs.get(scope, (None, None))[0]
        waited = time.monotonic()
        owner, hit = False, True
        stats = usage.setdefault("upload_cache", {"policy": POLICY, "wait_seconds": 0.0, "files": []})
        def record(entry, reused):
            if entry["upload_id"] and not any(v["upload_id"] == entry["upload_id"] for v in stats["files"]):
                stats["files"].append({"upload_id": entry["upload_id"], "file_sha256": digest,
                    "credential_reference": metadata["credential_reference"], "reused": reused})
        while True:
            guard()
            with self.condition:
                entry = self.entries.get(identity)
                if entry and entry.get("error") and (metadata.get("attempt", 1) > entry["attempt"] or entry.get("claim") != claim):
                    self.retired.setdefault(scope, []).append(entry)
                    del self.entries[identity]
                    entry = None
                if entry is None:
                    entry = {"loading": True, "attempt": metadata.get("attempt", 1), "claim": claim, "key": key,
                             "metadata": metadata, "context": context, "remote": None, "upload_id": None}
                    self.entries[identity] = entry
                    owner, hit = True, False
                    break
                if not entry["loading"]:
                    if entry.get("error"):
                        error = copy.copy(entry["error"])
                        error.usage = {}
                        usage["operation_phase"] = entry["error_phase"]
                        record(entry, True)
                        raise error
                    if entry.get("claim") != claim:
                        entry["loading"] = True
                        entry["key"] = key
                        owner = True
                    break
                self.condition.wait(0.2)
        stats["wait_seconds"] += time.monotonic()-waited
        if owner:
            try:
                remote = entry["remote"]
                if shared and remote is None:
                    previous = [v for v in self.pending(context["run_id"]).values() if v.get("cache_key") == cache_key]
                    if previous:
                        value = previous[-1]
                        if not re.fullmatch(r"files/[A-Za-z0-9_-]+", value["remote_file_name"]):
                            raise ProviderError("provider_response_invalid", uncertain=True)
                        entry["upload_id"] = value["upload_id"]
                        remote = {"name": value["remote_file_name"]}
                if remote is not None:
                    try:
                        usage["operation_phase"] = "processing"
                        remote, _ = self.transport("GET", BASE+"/v1beta/"+remote["name"], key)
                        remote = self.active(remote, key, guard, usage)
                        hit = True
                    except ProviderError as exc:
                        if exc.http_status != 404:
                            raise
                        self.audit(context, metadata, "remote.deleted", {"upload_id": entry["upload_id"], "already_absent": True})
                        entry.update(remote=None, upload_id=None)
                        remote = None
                if remote is None:
                    hit = False
                    upload_id = entry["upload_id"] = uid()
                    extra = {"upload_cache_policy": POLICY, "cache_key": cache_key, "file_sha256": digest} if shared else {}
                    self.audit(context, metadata, "remote.upload_started", {**extra, "upload_id": upload_id})
                    usage["operation_phase"] = "upload"
                    _, headers = self.timed(usage, "upload_seconds", lambda: self.transport("POST", BASE+"/upload/v1beta/files", key,
                        data={"file": {"display_name": "kdog-s1-clip"}}, headers={"X-Goog-Upload-Protocol": "resumable",
                        "X-Goog-Upload-Command": "start", "X-Goog-Upload-Header-Content-Length": str(clip.size_bytes),
                        "X-Goog-Upload-Header-Content-Type": "video/mp4"}))
                    upload_url = headers.get("X-Goog-Upload-URL")
                    if not upload_url:
                        raise ProviderError("provider_response_invalid", uncertain=True)
                    guard()
                    with path.open("rb") as handle:
                        uploaded, _ = self.timed(usage, "upload_seconds", lambda: self.transport("POST", upload_url, key, data=handle,
                            headers={"Content-Length": str(clip.size_bytes), "Content-Type": "video/mp4",
                                     "X-Goog-Upload-Offset": "0", "X-Goog-Upload-Command": "upload, finalize"}))
                    remote = uploaded["file"]
                    if not re.fullmatch(r"files/[A-Za-z0-9_-]+", remote["name"]):
                        raise ProviderError("provider_response_invalid", uncertain=True)
                    entry["remote"] = remote
                    self.audit(context, metadata, "remote.uploaded", {**extra, "upload_id": upload_id, "remote_file_name": remote["name"]})
                    usage["operation_phase"] = "processing"
                    remote = self.active(remote, key, guard, usage)
                guard()
                with self.condition:
                    entry.update(remote=remote, claim=claim, loading=False)
                    self.condition.notify_all()
            except Exception as exc:
                record(entry, hit)
                with self.condition:
                    entry.update(error=exc, error_phase=usage.get("operation_phase", "upload"), loading=False)
                    self.condition.notify_all()
                raise
        record(entry, hit)
        return entry["remote"]

    def close(self, scope, usage=None):
        with self.condition:
            while self.users.get(scope, 0):
                self.condition.wait(0.2)
            entries = self.retired.pop(scope, []) + [v for (s, _), v in self.entries.items() if s == scope]
            self.entries = {k: v for k, v in self.entries.items() if k[0] != scope}
            self.runs.pop(scope, None)
        start, failed, seen = time.monotonic(), set(), set()
        for entry in entries:
            upload_id, remote = entry["upload_id"], entry["remote"]
            if upload_id in seen or upload_id is None:
                continue
            seen.add(upload_id)
            if remote is None:
                failed.add(upload_id)
                continue
            try:
                if not re.fullmatch(r"files/[A-Za-z0-9_-]+", remote["name"]):
                    raise ProviderError("provider_response_invalid")
                key = entry["key"]
                if key is None:
                    from .secrets import credential_for_reference
                    key, _ = credential_for_reference(self.store, entry["metadata"]["credential_reference"])
                self.transport("DELETE", BASE+"/v1beta/"+remote["name"], key)
            except ProviderError as exc:
                if exc.http_status != 404:
                    failed.add(upload_id)
                    self.audit(entry["context"], entry["metadata"], "v4.remote_cleanup_failed", {"remote_file_names": [remote["name"]]})
                    continue
            self.audit(entry["context"], entry["metadata"], "remote.deleted", {"upload_id": upload_id})
        elapsed = time.monotonic()-start
        if usage is not None:
            usage["timing"]["cleanup_seconds"] += elapsed
            usage["remote_cleanup_pending"] = bool(failed)
        elif entries:
            # Late cleanup metadata never changes an immutable attempt artifact.
            with self.store.connect(write=True) as db:
                rows = db.execute("SELECT step_id,usage_json FROM steps WHERE run_id=? ORDER BY updated_at", (scope,)).fetchall()
                for row in rows:
                    value = json.loads(row["usage_json"])
                    ids = {v["upload_id"] for v in value.get("upload_cache", {}).get("files", [])}
                    if ids & seen:
                        value.update(remote_cleanup_deferred=False, remote_cleanup_pending=bool(ids & failed))
                        db.execute("UPDATE steps SET usage_json=? WHERE step_id=?", (encode(value), row["step_id"]))
                if rows:
                    row = rows[-1]
                    value = json.loads(db.execute("SELECT usage_json FROM steps WHERE step_id=?", (row["step_id"],)).fetchone()[0])
                    value.setdefault("timing", {}).setdefault("cleanup_seconds", 0.0)
                    value["timing"]["cleanup_seconds"] += elapsed
                    db.execute("UPDATE steps SET usage_json=? WHERE step_id=?", (encode(value), row["step_id"]))

    def finish(self, row):
        with self.store.connect() as db:
            current = db.execute("SELECT status FROM runs WHERE run_id=?", (row["run_id"],)).fetchone()
        if current is None or current["status"] != "retry_wait":
            self.close(row["run_id"])

    def close_all(self):
        for scope in list({s for s, _ in self.entries}):
            self.close(scope)

    def drain_terminal(self):
        for scope in list(self.runs):
            with self.store.connect() as db:
                row = db.execute("SELECT status FROM runs WHERE run_id=?", (scope,)).fetchone()
            if row is None or row["status"] in {"succeeded", "partial_failed", "failed", "stopped", "settings_required"}:
                self.close(scope)

    def recover_terminal(self):
        with self.store.connect() as db:
            rows = db.execute("SELECT run_id,input_snapshot_json FROM runs WHERE status IN "
                              "('succeeded','partial_failed','failed','stopped','settings_required')").fetchall()
        for row in rows:
            if self.pending(row["run_id"]):
                actor = json.loads(row["input_snapshot_json"])["requested_by"]
                value = {"run_id": row["run_id"], "claim_token": None, "worker_actor": actor}
                self.begin(value)
                self.finish(value)
