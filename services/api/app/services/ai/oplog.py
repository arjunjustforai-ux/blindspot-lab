"""AI operation logging and simple per-user budget enforcement."""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.config import get_settings
from app.db import SessionLocal
from app.models import AIOperationLog


class BudgetExceeded(RuntimeError):
    pass


def check_user_budget(user_id: uuid.UUID | None) -> None:
    if user_id is None:
        return
    s = get_settings()
    since = datetime.now(UTC) - timedelta(days=1)
    with SessionLocal() as db:
        n = db.scalar(
            select(func.count(AIOperationLog.id)).where(
                AIOperationLog.user_id == user_id,
                AIOperationLog.created_at >= since,
                AIOperationLog.provider == "openai",
            )
        )
    if (n or 0) >= s.max_llm_calls_per_user_per_day:
        raise BudgetExceeded("Daily AI request budget reached for this account")


def log_operation(
    *,
    operation: str,
    provider: str,
    model: str | None,
    status: str = "ok",
    latency_ms: int | None = None,
    course_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    prompt_version: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    error: str | None = None,
    meta: dict[str, Any] | None = None,
) -> uuid.UUID:
    """Write a log row in its own short transaction (never blocks the caller's transaction)."""
    with SessionLocal() as db:
        row = AIOperationLog(
            operation=operation,
            provider=provider,
            model=model,
            status=status,
            latency_ms=latency_ms,
            course_id=course_id,
            user_id=user_id,
            prompt_version=prompt_version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error=(error or None) and error[:2000],
            meta=meta or {},
        )
        db.add(row)
        db.commit()
        return row.id


@contextmanager
def timer() -> Iterator[dict[str, int]]:
    out = {"ms": 0}
    t0 = time.perf_counter()
    try:
        yield out
    finally:
        out["ms"] = int((time.perf_counter() - t0) * 1000)
