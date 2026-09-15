"""Shared primitives for the 42-item (2026-09-13) contracts. The 55-item legacy keeps its own copies."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")]
Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Revision = Annotated[int, Field(ge=1)]


def require_unique(values: list[str] | tuple[str, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"duplicate {label}")


class Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, allow_inf_nan=False,
        revalidate_instances="always",
    )
    schema_version: Literal["2.0"] = "2.0"
