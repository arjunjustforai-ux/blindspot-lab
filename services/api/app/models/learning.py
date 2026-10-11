"""Tutor conversations, assessments, questions, attempts and the learner model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
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
from app.models.knowledge import EMBEDDING_DIM


class Conversation(UUIDPk, Timestamped, Base):
    __tablename__ = "conversations"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="New conversation")

    __table_args__ = (Index("ix_conversations_user_course", "user_id", "course_id"),)


class TutorMessage(UUIDPk, Timestamped, Base):
    __tablename__ = "tutor_messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(12), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # grounded | refused | external | error | n/a (user turns)
    grounding_status: Mapped[str] = mapped_column(String(12), nullable=False, default="n/a")
    answer_mode: Mapped[str | None] = mapped_column(String(20))  # extractive | llm
    allow_external: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    external_content: Mapped[str | None] = mapped_column(Text)
    concept_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    support_score: Mapped[float | None] = mapped_column(Float)
    ai_log_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ai_operation_logs.id", ondelete="SET NULL"))

    __table_args__ = (
        CheckConstraint("role in ('user','assistant')", name="role"),
        Index("ix_tutor_messages_conv", "conversation_id", "created_at"),
    )


class Question(UUIDPk, Timestamped, Base):
    __tablename__ = "questions"

    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    concept_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False)
    question_type: Mapped[str] = mapped_column(String(16), nullable=False)
    difficulty: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 easy, 2 medium, 3 hard
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    correct_option_id: Mapped[str | None] = mapped_column(String(8))
    numeric_answer: Mapped[float | None] = mapped_column(Float)
    numeric_tolerance: Mapped[float | None] = mapped_column(Float)
    tolerance_mode: Mapped[str | None] = mapped_column(String(10))  # abs | rel
    answer_unit: Mapped[str | None] = mapped_column(String(30))
    rubric: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    assumptions: Mapped[str | None] = mapped_column(Text)
    # Misconception "signatures": responses a specific misconception predicts.
    misconception_signatures: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    template_key: Mapped[str | None] = mapped_column(String(80))
    family_key: Mapped[str | None] = mapped_column(String(80))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    verification_status: Mapped[str] = mapped_column(String(12), nullable=False, default="pending")
    verification_report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    generation_meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False, default="assessment")

    __table_args__ = (
        CheckConstraint("question_type in ('mcq','short_answer','numerical')", name="qtype"),
        CheckConstraint("difficulty between 1 and 3", name="difficulty"),
        CheckConstraint("origin in ('bank','template','extractive','llm')", name="origin"),
        CheckConstraint("verification_status in ('pending','verified','rejected')", name="verification"),
        CheckConstraint("purpose in ('assessment','probe','practice','transfer','heldout')", name="purpose"),
        UniqueConstraint("course_id", "content_hash", name="uq_question_course_hash"),
        Index("ix_questions_course_concept", "course_id", "concept_id"),
    )


class QuestionSource(UUIDPk, Base):
    __tablename__ = "question_sources"

    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    content_unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_units.id", ondelete="CASCADE"), nullable=False)
    support_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    __table_args__ = (UniqueConstraint("question_id", "content_unit_id", name="uq_question_unit"),)


class Assessment(UUIDPk, Timestamped, Base):
    __tablename__ = "assessments"

    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="in_progress")
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    selection_log: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "kind in ('diagnostic','practice','follow_up','review','mock_exam','tutor_check')", name="kind"
        ),
        CheckConstraint("status in ('in_progress','completed','abandoned')", name="status"),
        Index("ix_assessments_user_course", "user_id", "course_id"),
    )


class AssessmentItem(UUIDPk, Base):
    __tablename__ = "assessment_items"

    assessment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    selection_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("assessment_id", "question_id", name="uq_item_assessment_question"),
        UniqueConstraint("assessment_id", "position", name="uq_item_assessment_position"),
    )


class QuestionExposure(UUIDPk, Base):
    """Novelty tracking: which questions a learner has already seen."""

    __tablename__ = "question_exposures"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    first_shown_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_shown_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    times_shown: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    deliberate_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (UniqueConstraint("user_id", "question_id", name="uq_exposure_user_question"),)


class QuestionAttempt(UUIDPk, Timestamped, Base):
    __tablename__ = "question_attempts"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    question_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assessments.id", ondelete="SET NULL"))
    diagnostic_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("diagnostic_sessions.id", ondelete="SET NULL")
    )
    context: Mapped[str] = mapped_column(String(16), nullable=False, default="assessment")
    response: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reasoning: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[int | None] = mapped_column(Integer)  # self-reported 1..5
    is_correct: Mapped[bool | None] = mapped_column(Boolean)
    score: Mapped[float | None] = mapped_column(Float)
    grading_method: Mapped[str] = mapped_column(String(24), nullable=False)
    grading_detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    classification: Mapped[str | None] = mapped_column(String(40))
    classification_detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    feedback: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    time_spent_ms: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint(
            "context in ('assessment','diagnostic','probe','practice','transfer','tutor_check','simulation')",
            name="context",
        ),
        CheckConstraint("confidence is null or confidence between 1 and 5", name="confidence"),
        Index("ix_attempts_user_course", "user_id", "course_id", "created_at"),
        Index("ix_attempts_question", "question_id"),
    )


class MasteryState(UUIDPk, Base):
    __tablename__ = "mastery_states"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    concept_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False)
    p_mastery: Mapped[float] = mapped_column(Float, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    n_observations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_correct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    effective_evidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    distinct_questions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_observation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_correct_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "concept_id", name="uq_mastery_user_concept"),
        CheckConstraint("p_mastery >= 0 and p_mastery <= 1", name="p_range"),
        Index("ix_mastery_user_course", "user_id", "course_id"),
    )


class MasteryHistory(UUIDPk, Timestamped, Base):
    __tablename__ = "mastery_history"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    concept_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False)
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("question_attempts.id", ondelete="SET NULL"))
    p_before: Mapped[float] = mapped_column(Float, nullable=False)
    p_after: Mapped[float] = mapped_column(Float, nullable=False)
    observed_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evidence_weight: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    session_key: Mapped[str | None] = mapped_column(String(80))
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (Index("ix_mastery_history_user_concept", "user_id", "concept_id", "created_at"),)
