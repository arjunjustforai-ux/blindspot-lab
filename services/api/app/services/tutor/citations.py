"""Citation construction and validation.

A citation always refers to an existing content unit that was actually retrieved
and used. Its anchor (page / slide / timestamp) is copied from the unit; for video
transcript units we point at the start of the Whisper segment within the unit that
best matches the cited text (a real segment boundary, never an interpolation).
"""

from __future__ import annotations

import uuid
from typing import Any

from app.models import ContentUnit, SourceFile
from app.services.ai.text import lexical_overlap, normalize_ws


def fmt_ts(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def best_segment(unit: ContentUnit, focus_text: str) -> dict[str, Any] | None:
    segs = (unit.extraction_meta or {}).get("segments") or []
    if not segs:
        return None
    scored = [(lexical_overlap(focus_text, sg["text"]) + 0.001 * -i, sg) for i, sg in enumerate(segs)]
    return max(scored, key=lambda x: x[0])[1]


def anchor_label(source: SourceFile, unit: ContentUnit, start: float | None = None) -> str:
    if unit.page_number is not None:
        return f"{source.filename} — Page {unit.page_number}"
    if unit.slide_number is not None:
        return f"{source.filename} — Slide {unit.slide_number}"
    return f"{source.filename} — {fmt_ts(start if start is not None else unit.start_seconds)}"


def build_citation(
    cid: str, unit: ContentUnit, source: SourceFile, *, focus_text: str = "", excerpt: str | None = None,
    support: float | None = None, start_override: float | None = None,
) -> dict[str, Any]:
    start = unit.start_seconds
    seg = None
    if start_override is not None:
        start = start_override
        seg = next((sg for sg in (unit.extraction_meta or {}).get("segments", []) if sg["start"] == start_override),
                   None)
    elif unit.modality == "transcript" and focus_text:
        seg = best_segment(unit, focus_text)
        if seg:
            start = seg["start"]
    text_excerpt = excerpt or (seg["text"] if seg else unit.content)
    params = []
    if unit.page_number is not None:
        params.append(f"page={unit.page_number}")
    if unit.slide_number is not None:
        params.append(f"slide={unit.slide_number}")
    if start is not None and unit.page_number is None and unit.slide_number is None:
        params.append(f"t={start:.2f}")
    params.append(f"unit={unit.id}")
    return {
        "id": cid,
        "unit_id": str(unit.id),
        "source_id": str(source.id),
        "course_id": str(source.course_id),
        "filename": source.filename,
        "source_modality": source.modality,
        "unit_modality": unit.modality,
        "page": unit.page_number,
        "slide": unit.slide_number,
        "start": start,
        "end": unit.end_seconds if seg is None else seg["end"],
        "label": anchor_label(source, unit, start),
        "heading": unit.heading,
        "excerpt": normalize_ws(text_excerpt)[:600],
        "is_generated": unit.is_generated,
        "has_image": bool(unit.image_storage_key),
        "support": None if support is None else round(support, 3),
        "link": f"/app/courses/{source.course_id}/sources/{source.id}?" + "&".join(params),
    }


def validate_citation_ids(cited: list[str], allowed: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Split cited ids into (valid, invalid) against the set actually provided to the model."""
    valid, invalid = [], []
    for c in cited:
        (valid if c in allowed else invalid).append(c)
    return list(dict.fromkeys(valid)), invalid


def unit_uuid(v: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(v)
    except (ValueError, TypeError):
        return None
