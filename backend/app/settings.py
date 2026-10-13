"""Provider key response contracts shared by the S1 developer API."""

from typing import Literal

from app.input_models import Model


class KeyState(Model):
    provider: Literal["gemini", "openai", "anthropic"]
    reference: str
    available: bool


class KeyTest(Model):
    provider: Literal["gemini", "openai", "anthropic"]
    reference: str
    status: str
    slot: Literal["primary", "backup"] = "primary"
    tested_at: str


class GeminiSlotState(Model):
    slot: Literal["primary", "backup"]
    reference: str | None
    source: Literal["vault", "environment", "none"]
    available: bool
    unavailable_reason: Literal["unregistered", "removed", "file_unavailable", "decrypt_failed", "restore_required"] | None
    last_test: KeyTest | None
