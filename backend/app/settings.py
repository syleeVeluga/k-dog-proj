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
