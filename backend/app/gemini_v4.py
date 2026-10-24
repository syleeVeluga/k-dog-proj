"""S1 stateless Gemini REST requests with a durable remote-file cleanup ledger."""

import json
import time

from app.gemini import BASE, INTERACTION_TIMEOUT, ProviderError, interaction_request, interaction_text, request, video_processing
from app.gemini_uploads import UploadPool
from app.secrets import credential
from app.storage import now, uid

CLOCK_ID = uid()


class GeminiScorerV4:
    def __init__(self, store, transport=request):
        self.store = store
        self.transport = transport
        self.uploads = UploadPool(store, transport, CLOCK_ID)

    def begin_run(self, row):
        self.uploads.begin(row)

    def finish_run(self, row):
        self.uploads.finish(row)

    def close(self):
        self.uploads.close_all()

    def request_v4(self, files, config, context, schema, guard, *, selected=None):
        if selected is None:
            key, reference = credential(self.store, "gemini")
            metadata = {"credential_slot": "primary", "credential_reference": reference}
        else:
            key, metadata = selected
        usage = {**metadata, "provider": "gemini", "model": config["model"],
                 "timing": {name: 0.0 for name in ("upload_seconds", "processing_seconds", "inference_seconds", "cleanup_seconds")}}
        usage["request_interval"] = {"clock_id": CLOCK_ID, "start": time.monotonic(), "started_at_utc": now()}
        usage["provider_intervals"] = []

        def timed(name, function):
            started = time.monotonic()
            try:
                return function()
            finally:
                ended = time.monotonic()
                usage["timing"][name] += ended - started
                usage["provider_intervals"].append({"clock_id": CLOCK_ID, "phase": name, "start": started, "end": ended})

        try:
            with self.uploads.request(context, usage) as (scope, shared):
                inputs = []
                for path, clip in files:
                    remote = self.uploads.get(scope, shared, path, clip, key, metadata, context, guard, usage)
                    video = {"type": "video", "uri": remote["uri"], "mime_type": "video/mp4",
                             "processing": video_processing(config), "resolution": config["media_resolution"]}
                    if config.get("processing_mode") == "agentic":
                        video["name"] = clip.clip_id
                    inputs.extend(({"type": "text", "text": "다음 영상의 clip_id: " + clip.clip_id}, video))
                inputs.append({"type": "text", "text": json.dumps(context, ensure_ascii=False)})
                guard()
                usage["operation_phase"] = "inference"
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
        except Exception as exc:
            exc.usage = usage
            raise
        finally:
            usage["request_interval"].update(end=time.monotonic(), finished_at_utc=now())
