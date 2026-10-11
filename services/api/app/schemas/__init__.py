"""Typed API contracts (request bodies and the main response objects)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth -------------------------------------------------------------------------------------
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(ORM):
    id: uuid.UUID
    email: str
    display_name: str
    auth_provider: str
    is_demo: bool


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserOut


# --- courses & sources ---------------------------------------------------------------------------
class CourseIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    subject: str | None = Field(default=None, max_length=120)


class CourseOut(ORM):
    id: uuid.UUID
    title: str
    description: str | None
    subject: str | None
    is_demo: bool
    knowledge_status: str
    knowledge_built_at: datetime | None
    created_at: datetime


class SourceOut(ORM):
    id: uuid.UUID
    course_id: uuid.UUID
    filename: str
    modality: str
    mime_type: str
    size_bytes: int
    status: str
    status_detail: str | None
    error: str | None
    page_count: int | None
    slide_count: int | None
    duration_seconds: float | None
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_json")


class JobOut(ORM):
    id: uuid.UUID
    course_id: uuid.UUID
    source_file_id: uuid.UUID | None
    kind: str
    status: str
    stage: str | None
    progress: float
    attempts: int
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


# --- knowledge -----------------------------------------------------------------------------------
class ConceptPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    review_status: Literal["proposed", "approved", "rejected"] | None = None


class PrerequisiteIn(BaseModel):
    concept_id: uuid.UUID
    prerequisite_id: uuid.UUID
    rationale: str | None = Field(default=None, max_length=1000)


class PrerequisitePatch(BaseModel):
    review_status: Literal["proposed", "approved", "rejected"]


# --- tutor -----------------------------------------------------------------------------------------
class ConversationIn(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class MessageIn(BaseModel):
    content: str = Field(min_length=2, max_length=2000)
    allow_external: bool = False


class KnowledgeCheckIn(BaseModel):
    message_id: uuid.UUID | None = None
    concept_id: uuid.UUID | None = None


# --- assessments & diagnostics --------------------------------------------------------------------
class AssessmentIn(BaseModel):
    kind: Literal["diagnostic", "practice", "follow_up", "review", "mock_exam"] = "practice"
    concept_ids: list[uuid.UUID] | None = None
    count: int = Field(default=6, ge=1, le=25)
    difficulty: int | None = Field(default=None, ge=1, le=3)
    question_types: list[Literal["mcq", "short_answer", "numerical"]] | None = None


class AnswerIn(BaseModel):
    question_id: uuid.UUID | None = None
    response: dict[str, Any]
    reasoning: str | None = Field(default=None, max_length=3000)
    confidence: int | None = Field(default=None, ge=1, le=5)
    time_spent_ms: int | None = Field(default=None, ge=0, le=86_400_000)

    @field_validator("response")
    @classmethod
    def _small(cls, v: dict[str, Any]) -> dict[str, Any]:
        allowed = {"option_id", "value", "text"}
        if not v or not set(v) <= allowed:
            raise ValueError("response must contain option_id, value or text")
        for k, val in v.items():
            if isinstance(val, str) and len(val) > 4000:
                raise ValueError(f"{k} is too long")
        return v


class DiagnosticIn(BaseModel):
    concept_id: uuid.UUID | None = None
    misconception_key: str | None = Field(default=None, max_length=80)
    scenario: Literal["contribution_price_cut"] | None = None


class ProbeAnswerIn(BaseModel):
    probe_id: uuid.UUID
    response: dict[str, Any]


class EvaluationRunIn(BaseModel):
    kind: Literal["rag", "assessment", "personalization"]
    course_id: uuid.UUID | None = None
