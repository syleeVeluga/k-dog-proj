"""Gemini Files + Interactions REST adapter; no SDK retries or secret persistence."""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
from http.client import HTTPException as HTTPTransportError
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


BASE = "https://generativelanguage.googleapis.com"
# Agentic navigation and on-demand loading make one call take far longer than a single pass.
INTERACTION_TIMEOUT = 900


class ProviderError(Exception):
    def __init__(self, code: str, *, retryable=False, delay=0, uncertain=False, usage=None):
        super().__init__(code)
        self.code, self.retryable, self.delay = code, retryable, delay
        self.uncertain = uncertain
        self.usage = usage if usage is not None else {}


def interaction_request(model: str, prompt: str, inputs, schema: dict, max_output_tokens: int,
                        *, thinking_level=None, media_resolution=None) -> dict:
    generation = {"max_output_tokens": max_output_tokens}
    # Omitted keys keep the provider default; "minimal" is rejected before it reaches here.
    if thinking_level:
        generation["thinking_level"] = thinking_level
    if media_resolution:
        generation["media_resolution"] = media_resolution
    return {"model": model, "system_instruction": prompt, "input": inputs, "store": False,
            "response_format": {"type": "text", "mime_type": "application/json", "schema": schema},
            "generation_config": generation}


def video_processing(config: dict):
    # Agentic navigation supports neither a fixed frame rate nor clipping offsets.
    if config.get("processing_mode") == "agentic":
        return "agentic"
    return {"type": "static", "fps": config["fps"]}


def interaction_text(result: dict, incomplete_code: str, usage: dict) -> str:
    if not isinstance(result, dict):
        raise ProviderError("provider_response_invalid", uncertain=True, usage=usage)
    provider_usage = result.get("usage", {})
    if not isinstance(provider_usage, dict):
        raise ProviderError("provider_response_invalid", uncertain=True, usage=usage)
    usage.update({key: value for key, value in provider_usage.items()
                  if "tokens" in key and type(value) is int})
    usage.update(model=str(result.get("model", usage.get("model", ""))),
                 response_id=str(result.get("id", "")))
    if result.get("status") != "completed":
        raise ProviderError(incomplete_code, usage=usage)
    steps = result.get("steps")
    if not isinstance(steps, list):
        raise ProviderError("provider_response_invalid", uncertain=True, usage=usage)
    text = []
    for step in steps:
        if not isinstance(step, dict) or step.get("type") != "model_output":
            continue
        content = step.get("content")
        if not isinstance(content, list):
            raise ProviderError("provider_response_invalid", uncertain=True, usage=usage)
        text.extend(part["text"] for part in content
                    if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str))
    return "".join(text)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(method, url, key, *, data=None, headers=None, provider="gemini", timeout=120):
    # Upload URLs are credentials too. Accept only the fixed provider origin.
    parsed = urlsplit(url)
    hosts = {"gemini": "generativelanguage.googleapis.com", "openai": "api.openai.com", "anthropic": "api.anthropic.com"}
    if parsed.scheme != "https" or parsed.netloc != hosts.get(provider):
        raise ProviderError("provider_response_invalid")
    authentication = {"gemini": {"x-goog-api-key": key}, "openai": {"Authorization": f"Bearer {key}"},
                      "anthropic": {"x-api-key": key, "anthropic-version": "2023-06-01"}}
    outgoing = {**authentication[provider], **(headers or {})}
    if isinstance(data, dict):
        data = json.dumps(data, ensure_ascii=False).encode("utf-8")
        outgoing["Content-Type"] = "application/json"
    try:
        with build_opener(NoRedirect()).open(Request(url, data=data, headers=outgoing, method=method), timeout=timeout) as response:
            raw = response.read(16 * 1024 * 1024 + 1)
            if len(raw) > 16 * 1024 * 1024:
                raise ProviderError("provider_response_invalid")
            # Also redact JSON-escaped reflections and request IDs before usage is persisted.
            def redact(value):
                if isinstance(value, str):
                    return value.replace(key, "[REDACTED]") if key else value
                if isinstance(value, dict):
                    return {redact(k): redact(v) for k, v in value.items()}
                if isinstance(value, list):
                    return [redact(v) for v in value]
                return value
            return redact(json.loads(raw) if raw else {}), {k: redact(v) for k, v in response.headers.items()}
    except HTTPError as exc:
        delay = 0
        value = exc.headers.get("Retry-After", "0")
        try:
            delay = max(0, int(value))
        except ValueError:
            try:
                delay = max(0, int((parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()))
            except (ValueError, TypeError):
                pass
        error_usage = {}
        try:
            raw = exc.read(64 * 1024 + 1)
            if len(raw) <= 64 * 1024:
                payload = json.loads(raw)
                error = payload.get("error", {}) if isinstance(payload, dict) else {}
                if isinstance(error, dict):
                    status = error.get("status")
                    if isinstance(status, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", status):
                        error_usage["provider_error_status"] = status
                    message = error.get("message")
                    if isinstance(message, str):
                        message = message.replace(key, "[REDACTED]") if key else message
                        message = re.sub(r"https?://\S+", "[URL]", " ".join(message.split()))
                        message = re.sub(r"files/[A-Za-z0-9_-]+", "files/[REDACTED]", message)
                        error_usage["provider_error_message"] = message[:500]
        except (ValueError, TypeError, OSError, AttributeError):
            pass
        code = "developer_settings_required" if exc.code in (401, 403) else f"provider_http_{exc.code}"
        exc.close()
        raise ProviderError(code, retryable=exc.code == 429 or exc.code >= 500,
                            delay=delay, uncertain=exc.code >= 500, usage=error_usage) from None
    except (URLError, TimeoutError, OSError, HTTPTransportError):
        raise ProviderError("provider_connection_lost", retryable=True, uncertain=True) from None
    except (ValueError, KeyError):
        raise ProviderError("provider_response_invalid", uncertain=True) from None
