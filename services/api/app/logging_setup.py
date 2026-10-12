"""Structured JSON logging via structlog (falls back to stdlib formatting for library logs)."""

from __future__ import annotations

import logging
import sys

import structlog

from app.config import get_settings


def configure_logging() -> None:
    level = getattr(logging, get_settings().log_level.upper(), logging.INFO)
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared = [structlog.stdlib.add_log_level, structlog.stdlib.add_logger_name, timestamper]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                        structlog.processors.JSONRenderer()],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for noisy in ("httpx", "httpcore", "faster_whisper", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
