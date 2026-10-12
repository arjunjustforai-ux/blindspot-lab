"""Evaluation datasets, runs, case-level results and AI operation logs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamped, UUIDPk


class EvaluationCase(UUIDPk, Timestamped, Base):
    __tablename__ = "evaluation_cases"

    dataset_name: Mapped[str] = mapped_column(String(80), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(20), nullable=False)
    case_key: Mapped[str] = mapped_column(String(80), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    reference_answer: Mapped[str | None] = mapped_column(Text)
    reference_contexts: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    expected_sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    should_refuse: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (UniqueConstraint("dataset_name", "dataset_version", "case_key", name="uq_eval_case"),)


class EvaluationRun(UUIDPk, Timestamped, Base):
    __tablename__ = "evaluation_runs"

    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    course_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("courses.id", ondelete="SET NULL"))
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    dataset_name: Mapped[str | None] = mapped_column(String(80))
    dataset_version: Mapped[str | None] = mapped_column(String(20))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    model_info: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    seed: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    limitations: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(120))

    __table_args__ = (
        CheckConstraint("kind in ('rag','assessment','personalization')", name="kind"),
        CheckConstraint("status in ('queued','running','succeeded','failed')", name="status"),
        Index("ix_eval_runs_kind_created", "kind", "created_at"),
    )


class EvaluationResult(UUIDPk, Timestamped, Base):
    __tablename__ = "evaluation_results"

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False)
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("evaluation_cases.id", ondelete="SET NULL"))
    case_key: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str | None] = mapped_column(String(40))
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    output: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    passed: Mapped[bool | None] = mapped_column(Boolean)

    __table_args__ = (Index("ix_eval_results_run", "run_id"),)


class AIOperationLog(UUIDPk, Timestamped, Base):
    """Every model/retrieval operation. Stores no learner identity beyond a user id FK."""

    __tablename__ = "ai_operation_logs"

    course_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("courses.id", ondelete="SET NULL"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    operation: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    model: Mapped[str | None] = mapped_column(String(120))
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="ok")
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint("status in ('ok','error','refused','skipped')", name="status"),
        Index("ix_ai_logs_course_op", "course_id", "operation", "created_at"),
        Index("ix_ai_logs_user_created", "user_id", "created_at"),
    )
