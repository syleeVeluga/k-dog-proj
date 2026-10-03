"""S1 stateless Gemini REST requests with a durable remote-file cleanup ledger."""

import json
import re
import time

from app.gemini import BASE, INTERACTION_TIMEOUT, ProviderError, interaction_request, interaction_text, request, video_processing
from app.secrets import credential
from app.storage import uid


class GeminiScorerV4:
    def __init__(self, store, transport=request):
        self.store = store
        self.transport = transport

    def request_v4(self, files, config, context, schema, guard):
        key, reference = credential(self.store, "gemini")
        names = []
        usage = {"provider": "gemini", "credential_reference": reference, "model": config["model"],
                 "timing": {name: 0.0 for name in ("upload_seconds", "processing_seconds", "inference_seconds", "cleanup_seconds")}}

        def audit(action, value):
            with self.store.connect(write=True) as db:
                self.store.audit(db, context["audit_actor"], context["run_id"], action, value)

        def timed(name, function):
            started = time.monotonic()
            try:
                return function()
            finally:
                usage["timing"][name] += time.monotonic() - started

        try:
            inputs = []
            for path, clip in files:
                if clip.size_bytes > 2_000_000_000:
                    raise ProviderError("v4_file_size_limit")
                guard()
                upload_id = uid()
                audit("remote.upload_started", {"upload_id": upload_id, "credential_reference": reference})
                _, headers = timed("upload_seconds", lambda: self.transport("POST", BASE + "/upload/v1beta/files", key,
                    data={"file": {"display_name": "kdog-s1-clip"}}, headers={"X-Goog-Upload-Protocol": "resumable",
                    "X-Goog-Upload-Command": "start", "X-Goog-Upload-Header-Content-Length": str(clip.size_bytes),
                    "X-Goog-Upload-Header-Content-Type": "video/mp4"}))
                upload_url = headers.get("X-Goog-Upload-URL")
                if not upload_url:
                    raise ProviderError("provider_response_invalid", uncertain=True)
                guard()
                with path.open("rb") as handle:
                    uploaded, _ = timed("upload_seconds", lambda: self.transport("POST", upload_url, key, data=handle,
                        headers={"Content-Length": str(clip.size_bytes), "Content-Type": "video/mp4",
                        "X-Goog-Upload-Offset": "0", "X-Goog-Upload-Command": "upload, finalize"}))
                remote = uploaded["file"]
                name = remote["name"]
                if not re.fullmatch(r"files/[A-Za-z0-9_-]+", name):
                    raise ProviderError("provider_response_invalid", uncertain=True)
                names.append((name, upload_id))
                audit("remote.uploaded", {"upload_id": upload_id, "remote_file_name": name, "credential_reference": reference})
                started = time.monotonic()
                try:
                    deadline = started + 300
                    while remote.get("state") == "PROCESSING":
                        if time.monotonic() >= deadline:
                            raise ProviderError("remote_processing_timeout", retryable=True)
                        guard()
                        time.sleep(2)
                        guard()
                        remote, _ = self.transport("GET", BASE + "/v1beta/" + name, key)
                finally:
                    usage["timing"]["processing_seconds"] += time.monotonic() - started
                if remote.get("state") != "ACTIVE":
                    raise ProviderError("remote_file_failed")
                video = {"type": "video", "uri": remote["uri"], "mime_type": "video/mp4",
                         "processing": video_processing(config), "resolution": config["media_resolution"]}
                if config.get("processing_mode") == "agentic":
                    video["name"] = clip.clip_id
                inputs.extend(({"type": "text", "text": "다음 영상의 clip_id: " + clip.clip_id}, video))
            inputs.append({"type": "text", "text": json.dumps(context, ensure_ascii=False)})
            guard()
            result, _ = timed("inference_seconds", lambda: self.transport("POST", BASE + "/v1beta/interactions", key,
                data=interaction_request(config["model"], config["prompt"], inputs, schema, config["max_output_tokens"],
                    thinking_level=config.get("thinking_level")), timeout=INTERACTION_TIMEOUT))
            if isinstance(result, dict):
                usage["provider_usage"] = result.get("usage", {})
            raw = interaction_text(result, "v4_incomplete", usage)
            try:
                return json.loads(raw), usage
            except ValueError:
                raise ProviderError("v4_schema_invalid", retryable=True, usage=usage) from None
        except ProviderError as exc:
            if exc.code == "v4_incomplete":
                exc.uncertain = True
            usage.update(exc.usage)
            exc.usage = usage
            raise
        except (KeyError, TypeError, ValueError):
            raise ProviderError("provider_response_invalid", uncertain=True, usage=usage) from None
        finally:
            failures = []
            started = time.monotonic()
            for name, upload_id in names:
                try:
                    self.transport("DELETE", BASE + "/v1beta/" + name, key)
                except ProviderError:
                    failures.append(name)
                else:
                    audit("remote.deleted", {"upload_id": upload_id})
            usage["timing"]["cleanup_seconds"] += time.monotonic() - started
            usage["remote_cleanup_pending"] = bool(failures)
            if failures:
                audit("v4.remote_cleanup_failed", {"remote_file_names": failures, "credential_reference": reference})
