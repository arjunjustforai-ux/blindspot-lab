"""Ingestion quality checks against ground truth that exists for the demo pack.

  asr_wer                 word error rate of the stored lecture transcript against the narration script that was
                          synthesised into the MP4 (lecture_03_narration.json). Numbers and symbols are normalised
                          ("₹" -> "rupees", "%" -> "percent"), so number-format differences still count as errors.
  page_coverage           share of PDF pages that have at least one extracted unit anchored to them
  slide_coverage          share of PPTX slides with at least one unit
  video_span_coverage     share of the narration's timed segments overlapped by at least one transcript unit
  units_with_provenance   share of units carrying a page, slide or timestamp anchor (enforced by a DB constraint)
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import REPO_ROOT
from app.models import ContentUnit, SourceFile

NARRATION = REPO_ROOT / "demo" / "course-materials" / "lecture_03_narration.json"
VIDEO_FILE = "Lecture_03_Price_Cuts.mp4"


def _norm(t: str) -> list[str]:
    t = t.lower().replace("₹", " rupees ").replace("%", " percent ")
    return re.sub(r"[^a-z0-9. ]", " ", t).replace(". ", " ").split()


def word_error_rate(reference: str, hypothesis: str) -> float:
    r, h = _norm(reference), _norm(hypothesis)
    if not r:
        return 0.0 if not h else 1.0
    d = np.zeros((len(r) + 1, len(h) + 1), dtype=np.int32)
    d[:, 0] = np.arange(len(r) + 1)
    d[0, :] = np.arange(len(h) + 1)
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + (r[i - 1] != h[j - 1]))
    return float(d[-1, -1]) / len(r)


def evaluate(db: Session, course_id: uuid.UUID) -> dict[str, Any]:
    sources = list(db.scalars(select(SourceFile).where(SourceFile.course_id == course_id, SourceFile.status == "ready")))
    out: dict[str, Any] = {"sources": {}}
    total_units = with_anchor = 0
    for src in sources:
        units = list(db.scalars(select(ContentUnit).where(ContentUnit.source_file_id == src.id)
                                .order_by(ContentUnit.order_index)))
        total_units += len(units)
        with_anchor += sum(1 for u in units if u.page_number or u.slide_number or u.start_seconds is not None)
        info: dict[str, Any] = {"modality": src.modality, "units": len(units)}
        if src.modality == "pdf" and src.page_count:
            pages = {u.page_number for u in units if u.page_number}
            info["page_coverage"] = round(len(pages) / src.page_count, 4)
        if src.modality == "pptx" and src.slide_count:
            slides = {u.slide_number for u in units if u.slide_number}
            info["slide_coverage"] = round(len(slides) / src.slide_count, 4)
        if src.modality == "video":
            transcript = [u for u in units if u.modality == "transcript"]
            info["transcription_model"] = (src.metadata_json or {}).get("transcription_model")
            if src.filename == VIDEO_FILE and NARRATION.exists():
                nar = json.loads(NARRATION.read_text())
                ref = " ".join(s["narration"] for s in nar["segments"])
                hyp = " ".join(u.content for u in transcript)
                info["asr_wer"] = round(word_error_rate(ref, hyp), 4)
                info["asr_reference_words"] = len(_norm(ref))
                covered = sum(
                    1 for s in nar["segments"]
                    if any((u.start_seconds or 0) <= s["end"] and (u.end_seconds or 0) >= s["start"] for u in transcript)
                )
                info["video_span_coverage"] = round(covered / len(nar["segments"]), 4)
            info["transcript_units"] = len(transcript)
            info["frame_units"] = sum(1 for u in units if u.modality == "video_frame")
        out["sources"][src.filename] = info
    out["units_total"] = total_units
    out["units_with_provenance"] = round(with_anchor / total_units, 4) if total_units else None
    return out
