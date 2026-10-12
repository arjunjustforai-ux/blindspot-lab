"""Users, courses, memberships, source files and ingestion jobs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamped, UUIDPk, utcnow


class User(UUIDPk, Timestamped, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(200))
    auth_provider: Mapped[str] = mapped_column(String(20), nullable=False, default="local")
    external_subject: Mapped[str | None] = mapped_column(String(200), unique=True)
    # Synthetic/demo accounts are always labelled as such in the UI.
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        CheckConstraint("auth_provider in ('local','supabase','demo','system')", name="auth_provider"),
    )


class Course(UUIDPk, Timestamped, Base):
    __tablename__ = "courses"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(String(120))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    knowledge_status: Mapped[str] = mapped_column(String(20), nullable=False, default="empty")
    knowledge_built_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    memberships: Mapped[list[CourseMembership]] = relationship(back_populates="course", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("knowledge_status in ('empty','building','ready','failed','stale')", name="knowledge_status"),
    )


class CourseMembership(UUIDPk, Timestamped, Base):
    __tablename__ = "course_memberships"

    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="student")

    course: Mapped[Course] = relationship(back_populates="memberships")

    __table_args__ = (
        UniqueConstraint("course_id", "user_id", name="uq_membership_course_user"),
        CheckConstraint("role in ('owner','instructor','student')", name="role"),
        Index("ix_membership_user", "user_id"),
    )


class SourceFile(UUIDPk, Timestamped, Base):
    __tablename__ = "source_files"

    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    modality: Mapped[str] = mapped_column(String(10), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    # uploaded -> extracting -> indexing -> ready | failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="uploaded")
    status_detail: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    slide_count: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        CheckConstraint("modality in ('pdf','pptx','video')", name="modality"),
        CheckConstraint("status in ('uploaded','extracting','indexing','ready','failed')", name="status"),
        UniqueConstraint("course_id", "sha256", name="uq_source_course_sha"),
        Index("ix_source_course", "course_id"),
    )


class IngestionJob(UUIDPk, Timestamped, Base):
    """Database-backed job queue (claimed with SELECT ... FOR UPDATE SKIP LOCKED)."""

    __tablename__ = "ingestion_jobs"

    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    source_file_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_files.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="ingest_source")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    stage: Mapped[str | None] = mapped_column(String(60))
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    error: Mapped[str | None] = mapped_column(Text)
    log: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    locked_by: Mapped[str | None] = mapped_column(String(120))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("kind in ('ingest_source','rebuild_knowledge')", name="kind"),
        CheckConstraint("status in ('queued','running','succeeded','failed','cancelled')", name="status"),
        Index("ix_jobs_status_created", "status", "created_at"),
        Index("ix_jobs_source", "source_file_id"),
    )
