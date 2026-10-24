"""Shared models for HAXcms API envelopes (PLAN Phase 1 T1.8)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class Envelope(BaseModel):
    """The `{status, data}` JSON envelope every HAXcms route returns.

    Legacy routes add top-level extras (`jwt`, `link`, `id`, `slug`), so extra keys are kept.
    """

    model_config = ConfigDict(extra="allow")

    status: int
    data: Any = None


class PageInfo(BaseModel):
    """Pagination block returned by list endpoints (`page.limit/offset/total`)."""

    model_config = ConfigDict(extra="allow")

    limit: int | None = None
    offset: int | None = None
    total: int | None = None


def dump_model(model: BaseModel) -> dict[str, Any]:
    """Serialise a model for a tool result (PLAN §5: mode="json", exclude_none=True)."""
    return model.model_dump(mode="json", exclude_none=True)
