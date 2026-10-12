"""Figure / diagram understanding.

Two complementary paths, both anchored to the original image:
  1. OCR (Tesseract, always available locally): extracts the literal text in a figure
     (axis labels, data labels, annotations). Stored verbatim, marked `ocr`.
  2. Vision-language model (when an OpenAI-compatible multimodal model is configured):
     produces a structured description. Stored with is_generated=True and labelled
     as a model interpretation in the UI.
"""

from __future__ import annotations

import io
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from PIL import Image

from app.config import get_settings
from app.services.ai import llm

VISION_PROMPT_VERSION = "vision-figure-v1"


@dataclass
class OCRResult:
    text: str
    mean_confidence: float | None
    word_count: int
    lines: list[str] = field(default_factory=list)


_NOISE = re.compile(r"^[eoa=~_\-—–.,'`\"|]{1,6}$", re.IGNORECASE)


def ocr_image(img: Image.Image, *, currency_symbol: str | None = None) -> OCRResult:
    """OCR an image with Tesseract (sparse-text mode suits charts and diagrams).

    Post-processing (recorded so it is auditable):
      - drops low-confidence and punctuation-only noise tokens;
      - if `currency_symbol` is given (the document itself uses that symbol), a
        currency-like glyph Tesseract commonly misreads (#, %, ¥, $) directly
        before a digit is mapped back to it, e.g. "+%60k" -> "+₹60k".
    """
    import pytesseract
    from PIL import ImageOps, ImageStat

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    if ImageStat.Stat(img.convert("L")).mean[0] < 110:  # light text on dark background
        img = ImageOps.invert(img.convert("L"))
    if img.width < 2400:
        scale = min(3.0, 2400 / max(img.width, 1))
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, config="--psm 11")
    words, confs = [], []
    by_line: dict[tuple[int, int, int], list[str]] = {}
    for i, w in enumerate(data["text"]):
        w = (w or "").strip()
        try:
            c = float(data["conf"][i])
        except (TypeError, ValueError):
            c = -1
        if not w or c < 50 or _NOISE.match(w) or not re.search(r"[A-Za-z0-9]", w):
            continue
        if currency_symbol:
            w = re.sub(r"(^|[+\-(])[#%¥$](?=\d)", lambda m: m.group(1) + currency_symbol, w)
        words.append(w)
        confs.append(c)
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        by_line.setdefault(key, []).append(w)
    lines = [" ".join(v) for v in by_line.values()]
    return OCRResult(
        text=" | ".join(lines),
        mean_confidence=round(sum(confs) / len(confs), 1) if confs else None,
        word_count=len(words),
        lines=lines,
    )


def describe_figure(
    png_bytes: bytes, *, context: str, course_id: uuid.UUID | None = None
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Ask a vision model for a grounded, structured description. Returns (None, info) if unavailable."""
    s = get_settings()
    if not s.llm_enabled:
        return None, {"status": "skipped", "reason": "no vision model configured"}
    messages = [
        {
            "role": "system",
            "content": (
                "You describe figures from course materials for a study assistant. Describe ONLY what is visible. "
                "Transcribe numbers and labels exactly. Do not add outside facts. " + llm.UNTRUSTED_NOTICE
            ),
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Surrounding text (caption/heading) for context, untrusted:\n<source>"
                        + context[:800]
                        + "</source>\nReturn JSON: {\"figure_type\": str, \"title\": str, \"description\": str "
                        "(2-5 sentences), \"data_points\": [{\"label\": str, \"value\": str}], "
                        "\"key_takeaway\": str, \"is_decorative\": bool}"
                    ),
                },
                llm.image_part(png_bytes),
            ],
        },
    ]
    try:
        data, info = llm.chat(
            messages, operation="vision_figure", prompt_version=VISION_PROMPT_VERSION,
            model=s.effective_vision_model, course_id=course_id, max_tokens=500,
        )
    except (llm.LLMError, llm.LLMUnavailable) as e:
        return None, {"status": "error", "reason": str(e)}
    return data, {"status": "ok", **info}


def image_from_bytes(b: bytes) -> Image.Image:
    return Image.open(io.BytesIO(b))


def is_meaningful_image(img: Image.Image, *, min_side: int = 120, min_area_frac: float | None = None,
                        page_area: float | None = None, rect_area: float | None = None) -> bool:
    if img.width < min_side or img.height < min_side:
        return False
    if min_area_frac and page_area and rect_area is not None and rect_area / page_area < min_area_frac:
        return False
    # Skip near-uniform images (backgrounds, rules, spacer images).
    small = img.convert("L").resize((32, 32))
    px = list(small.getdata())
    mean = sum(px) / len(px)
    var = sum((p - mean) ** 2 for p in px) / len(px)
    return var > 40.0


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
