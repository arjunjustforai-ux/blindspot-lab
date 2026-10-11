from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

ProgressFn = Callable[[str, float], None]


@dataclass
class ExtractedUnit:
    modality: str
    content: str
    heading: str | None = None
    section_path: list[str] = field(default_factory=list)
    page_number: int | None = None
    slide_number: int | None = None
    start_seconds: float | None = None
    end_seconds: float | None = None
    bbox: list[float] | None = None
    image_png: bytes | None = None  # stored by the pipeline; key recorded on the unit
    is_generated: bool = False
    generation_meta: dict[str, Any] = field(default_factory=dict)
    extraction_meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractionResult:
    units: list[ExtractedUnit]
    metadata: dict[str, Any] = field(default_factory=dict)
    page_count: int | None = None
    slide_count: int | None = None
    duration_seconds: float | None = None
    previews: dict[int, bytes] = field(default_factory=dict)  # slide number -> PNG
    warnings: list[str] = field(default_factory=list)


class ExtractionError(Exception):
    """Raised with a user-meaningful message when a file cannot be processed."""
