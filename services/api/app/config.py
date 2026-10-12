"""Application settings loaded from environment variables.

All secrets come from the environment (or a local, git-ignored `.env`).
Nothing in this module should ever contain a real credential.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
DEV_JWT_SECRET = "dev-only-change-me-please-0123456789abcdef"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Blindspot Lab API"
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    # --- Database -------------------------------------------------------
    database_url: str = "postgresql+psycopg://blindspot:blindspot@localhost:5432/blindspot"

    # --- Auth -------------------------------------------------------------
    jwt_secret: str = DEV_JWT_SECRET
    jwt_expire_minutes: int = 60 * 24 * 7
    media_url_ttl_seconds: int = 60 * 60 * 6
    # Optional: accept Supabase-issued access tokens (HS256 project JWT secret).
    supabase_jwt_secret: str | None = None

    # --- Storage ----------------------------------------------------------
    storage_backend: Literal["local", "supabase"] = "local"
    local_storage_dir: Path = REPO_ROOT / "data" / "storage"
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    supabase_storage_bucket: str = "course-materials"

    # --- Upload limits ------------------------------------------------------
    max_document_mb: int = 60
    max_video_mb: int = 400
    max_video_minutes: int = 90

    # --- AI providers -------------------------------------------------------
    # "local": no external calls. Extractive answers, template/bank questions,
    #          rule-based diagnosis, local embeddings + Whisper + OCR.
    # "openai": any OpenAI-compatible endpoint (OpenAI, Azure-compatible
    #           proxies, Groq, Together, vLLM, Ollama, llama.cpp server ...).
    llm_provider: Literal["local", "openai"] = "local"
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    verifier_model: str | None = None  # defaults to llm_model; set a different one for cross-model checks
    vision_model: str | None = None  # defaults to llm_model
    llm_timeout_seconds: float = 60.0
    llm_max_output_tokens: int = 900
    llm_temperature: float = 0.2

    embedding_provider: Literal["local", "openai"] = "local"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 384

    reranker_enabled: bool = True
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"

    transcription_provider: Literal["local", "openai"] = "local"
    whisper_model: str = "base.en"
    openai_transcription_model: str = "whisper-1"

    model_cache_dir: Path = Path.home() / ".cache" / "blindspot-models"

    # Bounded cost controls
    max_vision_calls_per_source: int = 24
    max_llm_calls_per_user_per_day: int = 400

    # --- Retrieval / grounding ---------------------------------------------
    retrieval_top_k: int = 6
    retrieval_candidates: int = 24
    # Minimum reranker probability / similarity for a query to count as supported.
    grounding_min_score: float = 0.30

    # --- Runtime ----------------------------------------------------------
    # NoDecode: accept "a,b" from the environment instead of requiring a JSON array
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"])
    run_worker_in_process: bool = True
    worker_poll_seconds: float = 2.0
    demo_enabled: bool = True

    @model_validator(mode="after")
    def _production_secrets(self) -> Settings:
        if self.environment == "production" and (
            self.jwt_secret == DEV_JWT_SECRET or len(self.jwt_secret) < 32
        ):
            raise ValueError("JWT_SECRET must be set to a random value of at least 32 characters in production")
        return self

    @field_validator("database_url", mode="after")
    @classmethod
    def _psycopg_driver(cls, v: str) -> str:
        """Hosting providers hand out postgres:// or postgresql:// URLs; SQLAlchemy needs the psycopg driver."""
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            if v.strip().startswith("["):
                return json.loads(v)
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider == "openai" and bool(self.openai_api_key)

    @property
    def effective_verifier_model(self) -> str:
        return self.verifier_model or self.llm_model

    @property
    def effective_vision_model(self) -> str:
        return self.vision_model or self.llm_model

    @property
    def mode_label(self) -> str:
        return "llm" if self.llm_enabled else "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()
