"""Content units, concepts, prerequisite edges and concept-to-source mappings."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.config import get_settings
from app.models.base import Base, Timestamped, UUIDPk

EMBEDDING_DIM = get_settings().embedding_dim

UNIT_MODALITIES = (
    "pdf_text",
    "pdf_table",
    "pdf_figure",
    "pdf_ocr",
    "slide_text",
    "slide_notes",
    "slide_figure",
    "slide_chart",
    "slide_table",
    "transcript",
    "video_frame",
)


class ContentUnit(UUIDPk, Timestamped, Base):
    """A retrievable, source-anchored piece of course content.

    Exactly one of (page_number | slide_number | start_seconds) anchors the unit
    to its origin, depending on the source modality.
    """

    __tablename__ = "content_units"

    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    source_file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_files.id", ondelete="CASCADE"), nullable=False)
    modality: Mapped[str] = mapped_column(String(20), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    heading: Mapped[str | None] = mapped_column(String(300))
    section_path: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    slide_number: Mapped[int | None] = mapped_column(Integer)
    start_seconds: Mapped[float | None] = mapped_column(Float)
    end_seconds: Mapped[float | None] = mapped_column(Float)
    bbox: Mapped[list[float] | None] = mapped_column(JSONB)
    image_storage_key: Mapped[str | None] = mapped_column(String(500))
    # True when `content` is a model-generated interpretation (e.g. a vision
    # description of a figure) rather than text extracted verbatim.
    is_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    generation_meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    extraction_meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str | None] = mapped_column(String(120))
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', coalesce(heading, '') || ' ' || content)", persisted=True),
    )

    __table_args__ = (
        CheckConstraint(
            "modality in (" + ",".join(f"'{m}'" for m in UNIT_MODALITIES) + ")",
            name="modality",
        ),
        CheckConstraint(
            "(page_number IS NOT NULL) OR (slide_number IS NOT NULL) OR (start_seconds IS NOT NULL)",
            name="has_anchor",
        ),
        Index("ix_units_course", "course_id"),
        Index("ix_units_source_order", "source_file_id", "order_index"),
        Index("ix_units_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_units_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class Concept(UUIDPk, Timestamped, Base):
    __tablename__ = "concepts"

    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("concepts.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(12), nullable=False, default="concept")
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    aliases: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    catalog_key: Mapped[str | None] = mapped_column(String(80))
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="extracted")
    review_status: Mapped[str] = mapped_column(String(12), nullable=False, default="proposed")
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("course_id", "slug", name="uq_concept_course_slug"),
        CheckConstraint("kind in ('topic','concept','subconcept')", name="kind"),
        CheckConstraint("origin in ('catalog','heading','keyphrase','llm','instructor')", name="origin"),
        CheckConstraint("review_status in ('proposed','approved','rejected')", name="review_status"),
        Index("ix_concepts_course", "course_id"),
    )


class ConceptPrerequisite(UUIDPk, Timestamped, Base):
    """Directed edge: `prerequisite_id` should be understood before `concept_id`."""

    __tablename__ = "concept_prerequisites"

    course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    concept_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False)
    prerequisite_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False)
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="heuristic")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    rationale: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(String(12), nullable=False, default="proposed")

    __table_args__ = (
        UniqueConstraint("concept_id", "prerequisite_id", name="uq_prereq_pair"),
        CheckConstraint("concept_id <> prerequisite_id", name="no_self_loop"),
        CheckConstraint("origin in ('catalog','heuristic','llm','instructor')", name="origin"),
        CheckConstraint("review_status in ('proposed','approved','rejected')", name="review_status"),
        Index("ix_prereq_course", "course_id"),
    )


class ConceptSource(UUIDPk, Base):
    """Concept-to-content-unit tag (every unit is tagged to at least one concept)."""

    __tablename__ = "concept_sources"

    concept_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False)
    content_unit_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_units.id", ondelete="CASCADE"), nullable=False)
    relevance: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    method: Mapped[str] = mapped_column(String(20), nullable=False, default="similarity")
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("concept_id", "content_unit_id", name="uq_concept_unit"),
        Index("ix_concept_sources_unit", "content_unit_id"),
    )
