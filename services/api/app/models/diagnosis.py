"""Misconception catalogue, hypotheses, evidence, diagnostic sessions, probes and interventions."""

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

from app.models.base import Base, Timestamped, UUIDPk, utcnow


class MisconceptionDefinition(UUIDPk, Timestamped, Base):
    """Instructor-reviewable catalogue entry. Not a validated diagnostic instrument."""

    __tablename__ = "misconception_definitions"

    key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    concept_keys: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    detection_cues: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    competing_interpretations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    diagnostic_probes: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    repair: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    support_query: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")

    __table_args__ = (
        CheckConstraint("review_status in ('draft','instructor_reviewed','retired')", name="review_status"),
    )


class CourseMisconception(UUIDPk, Timestamped, Base):
    """Activation of a catalogue entry for a course, only when the course sources support it."""

    __tablename__ = "course_misconceptions"

    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    misconception_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("misconception_definitions.id", ondelete="CASCADE"), nullable=False
    )
    concept_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("concepts.id", ondelete="SET NULL"))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supporting_unit_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    support_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (UniqueConstraint("course_id", "misconception_id", name="uq_course_misconception"),)


class DiagnosticSession(UUIDPk, Timestamped, Base):
    __tablename__ = "diagnostic_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    concept_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    # answer -> probing -> repair -> practice -> transfer -> completed
    stage: Mapped[str] = mapped_column(String(16), nullable=False, default="answer")
    outcome: Mapped[str | None] = mapped_column(String(40))
    hypotheses: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    timeline: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    practice_question_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("questions.id", ondelete="SET NULL"))
    transfer_question_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("questions.id", ondelete="SET NULL"))
    is_demo_script: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "stage in ('answer','probing','repair','practice','transfer','completed')", name="stage"
        ),
        Index("ix_diag_user_course", "user_id", "course_id"),
    )


class DiagnosticProbe(UUIDPk, Timestamped, Base):
    __tablename__ = "diagnostic_probes"

    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("diagnostic_sessions.id", ondelete="CASCADE"), nullable=False)
    misconception_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("misconception_definitions.id", ondelete="SET NULL")
    )
    probe_key: Mapped[str] = mapped_column(String(80), nullable=False)
    probe_type: Mapped[str] = mapped_column(String(16), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    # How each possible response shifts each competing hypothesis (likelihood ratios).
    discrimination: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    expected_numeric: Mapped[float | None] = mapped_column(Float)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    interpretation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (CheckConstraint("probe_type in ('mcq','numerical','free_text')", name="probe_type"),)


class MisconceptionHypothesis(UUIDPk, Timestamped, Base):
    """Per-learner, per-misconception hypothesis state (never 'confirmed')."""

    __tablename__ = "misconception_hypotheses"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    misconception_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("misconception_definitions.id", ondelete="CASCADE"), nullable=False
    )
    concept_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("concepts.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="suspected")
    posterior: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evidence_kinds: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    revisit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "misconception_id", "course_id", name="uq_hypothesis_user_mc_course"),
        CheckConstraint(
            "status in ('suspected','supported','unresolved','rejected','resolving','resolved')", name="status"
        ),
    )


class MisconceptionEvidence(UUIDPk, Timestamped, Base):
    __tablename__ = "misconception_evidence"

    hypothesis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("misconception_hypotheses.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("diagnostic_sessions.id", ondelete="SET NULL"))
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("question_attempts.id", ondelete="SET NULL"))
    probe_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("diagnostic_probes.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    likelihood_ratio: Mapped[float] = mapped_column(Float, nullable=False)
    posterior_before: Mapped[float] = mapped_column(Float, nullable=False)
    posterior_after: Mapped[float] = mapped_column(Float, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (Index("ix_evidence_hypothesis", "hypothesis_id", "created_at"),)


class LearningIntervention(UUIDPk, Timestamped, Base):
    __tablename__ = "learning_interventions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("diagnostic_sessions.id", ondelete="CASCADE"))
    concept_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("concepts.id", ondelete="SET NULL"))
    misconception_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("misconception_definitions.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    question_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("questions.id", ondelete="SET NULL"))
    outcome: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "kind in ('contrastive_explanation','worked_example','targeted_practice','transfer_test','review')",
            name="kind",
        ),
    )
