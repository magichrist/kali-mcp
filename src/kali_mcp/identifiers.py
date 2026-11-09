"""Assessment/job ID generation and context propagation for kali-mcp v2.0.

Provides opaque identifiers (assessment_id, job_id) and a thread-local
context so that persist_run and other helpers can propagate them without
requiring explicit arguments at every call site.
"""

from __future__ import annotations

import contextvars
import uuid
from typing import Any

# ── context variables ───────────────────────────────────────────────────

_assessment_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "kali_mcp_assessment_id", default=None
)
_job_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "kali_mcp_job_id", default=None
)


def generate_assessment_id() -> str:
    """Generate an opaque assessment identifier."""
    return f"assessment_{uuid.uuid4().hex[:12]}"


def generate_job_id() -> str:
    """Generate an opaque job identifier."""
    return f"job_{uuid.uuid4().hex[:12]}"


def set_assessment_context(
    assessment_id: str | None = None, job_id: str | None = None
) -> dict[str, Any]:
    """Set the current assessment/job context for the calling thread/task.

    Returns a dict of tokens that can be passed to :func:`reset_assessment_context`
    to restore the previous values.
    """
    tokens: dict[str, Any] = {}
    if assessment_id is not None:
        tokens["assessment"] = _assessment_ctx.set(assessment_id)
    if job_id is not None:
        tokens["job"] = _job_ctx.set(job_id)
    return tokens


def reset_assessment_context(tokens: dict[str, Any]) -> None:
    """Reset the assessment/job context to previous values."""
    if "assessment" in tokens:
        _assessment_ctx.reset(tokens["assessment"])
    if "job" in tokens:
        _job_ctx.reset(tokens["job"])


def get_assessment_context() -> tuple[str | None, str | None]:
    """Return the current (assessment_id, job_id) context, or (None, None)."""
    return _assessment_ctx.get(), _job_ctx.get()


__all__ = [
    "generate_assessment_id",
    "generate_job_id",
    "get_assessment_context",
    "reset_assessment_context",
    "set_assessment_context",
]
