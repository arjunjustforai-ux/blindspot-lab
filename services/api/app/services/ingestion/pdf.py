"""PDF extraction with PyMuPDF.

Produces page-anchored units:
  - pdf_text   heading-aware text chunks (never crossing a page boundary)
  - pdf_table  tables detected by PyMuPDF, serialised as Markdown
  - pdf_figure embedded figures: caption + OCR'd text (extracted), plus an optional
               vision-model description stored as a separate, generated unit
  - pdf_ocr    OCR text for scanned/image-only pages (with mean OCR confidence)
"""

from __future__ import annotations

import re
import statistics
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.config import get_settings
from app.services.ai import vision
from app.services.ai.text import looks_like_injection, normalize_ws
from app.services.ingestion.chunking import chunk_paragraphs
from app.services.ingestion.types import ExtractedUnit, ExtractionError, ExtractionResult, ProgressFn

CAPTION_RE = re.compile(r"^(figure|fig\.|table|exhibit|chart)\s*\d+([.:]\d+)*", re.IGNORECASE)


@dataclass
class _Line:
    page: int
    block: int
    text: str
    size: float
    bold: bool
    bbox: tuple[float, float, float, float]


def _is_bold(span: dict) -> bool:
    return bool(span.get("flags", 0) & 16) or "bold" in span.get("font", "").lower()


def _collect_lines(doc: pymupdf.Document) -> list[_Line]:
    lines: list[_Line] = []
    for page in doc:
        d = page.get_text("dict", sort=True)
        for bi, b in enumerate(d.get("blocks", [])):
            if b.get("type") != 0:
                continue
            for ln in b.get("lines", []):
                spans = [s for s in ln.get("spans", []) if s.get("text", "").strip()]
                if not spans:
                    continue
                text = normalize_ws("".join(s["text"] for s in ln["spans"]))
                size = max(s["size"] for s in spans)
                bold = all(_is_bold(s) for s in spans)
                lines.append(_Line(page.number + 1, bi, text, round(size, 1), bold, tuple(ln["bbox"])))
    return lines


def _repeated_margin_lines(lines: list[_Line], page_heights: dict[int, float], n_pages: int) -> set[str]:
    def norm(t: str) -> str:
        return re.sub(r"\d+", "#", t.lower())

    counts: Counter[str] = Counter()
    for ln in lines:
        h = page_heights[ln.page]
        if ln.bbox[1] < 0.08 * h or ln.bbox[3] > 0.92 * h:
            counts[norm(ln.text)] += 1
    threshold = max(2, int(0.5 * n_pages))
    return {t for t, c in counts.items() if c >= threshold}


def extract_pdf(path: Path, *, course_id: uuid.UUID | None, progress: ProgressFn) -> ExtractionResult:
    s = get_settings()
    try:
        doc = pymupdf.open(path)
    except Exception as e:
        raise ExtractionError(f"Could not open PDF: {e}") from e
    if doc.is_encrypted:
        raise ExtractionError("PDF is password-protected; please upload an unencrypted copy")
    if doc.page_count == 0:
        raise ExtractionError("PDF has no pages")

    n_pages = doc.page_count
    page_heights = {p.number + 1: p.rect.height for p in doc}
    lines = _collect_lines(doc)
    margin = _repeated_margin_lines(lines, page_heights, n_pages)

    def is_margin(ln: _Line) -> bool:
        h = page_heights[ln.page]
        in_margin = ln.bbox[1] < 0.08 * h or ln.bbox[3] > 0.92 * h
        return in_margin and re.sub(r"\d+", "#", ln.text.lower()) in margin

    sizes: list[float] = []
    for ln in lines:
        sizes.extend([ln.size] * len(ln.text))
    body = statistics.median(sizes) if sizes else 11.0

    def heading_candidate(ln: _Line) -> bool:
        return (
            ln.size >= body * 1.15
            and len(ln.text) <= 160
            and (ln.bold or ln.size >= body * 1.3)
            and not CAPTION_RE.match(ln.text)
        )

    head_sizes = sorted({ln.size for ln in lines if heading_candidate(ln)}, reverse=True)
    pages_by_size = {sz: {ln.page for ln in lines if heading_candidate(ln) and ln.size == sz} for sz in head_sizes}
    title_sizes = {sz for sz in head_sizes if pages_by_size[sz] == {1} and n_pages > 2 and sz == head_sizes[0]}
    level_sizes = [sz for sz in head_sizes if sz not in title_sizes]
    level_of = {sz: min(i + 1, 3) for i, sz in enumerate(level_sizes)}

    doc_title = (doc.metadata or {}).get("title") or path.stem
    units: list[ExtractedUnit] = []
    warnings: list[str] = []
    vision_calls = 0
    section: dict[int, str] = {}

    def section_path() -> list[str]:
        return [section[k] for k in sorted(section)]

    def current_heading() -> str | None:
        return section[max(section)] if section else None

    all_text = " ".join(ln.text for ln in lines)
    currency = next((c for c in ("₹", "€", "£") if c in all_text), None)

    for page in doc:
        pno = page.number + 1
        progress(f"Reading page {pno}/{n_pages}", 0.05 + 0.75 * (pno - 1) / n_pages)
        page_area = page.rect.width * page.rect.height
        page_lines = [ln for ln in lines if ln.page == pno and not is_margin(ln)]
        # (y, section snapshot) marks let tables/figures inherit the heading above them.
        marks: list[tuple[float, list[str], str | None]] = [(-1.0, section_path(), current_heading())]

        def section_at(y: float) -> tuple[list[str], str | None]:
            best = marks[0]
            for m in marks:
                if m[0] <= y:
                    best = m
            return best[1], best[2]

        # ---- detect tables first so their cells are excluded from the text flow
        table_rows: list[tuple[pymupdf.Rect, list[list[str]]]] = []
        try:
            tables = page.find_tables().tables
        except Exception:
            tables = []
        for t in tables:
            rows = [[normalize_ws(c or "") for c in r] for r in t.extract()]
            rows = [r for r in rows if any(r)]
            if len(rows) >= 2 and max(len(r) for r in rows) >= 2:
                table_rows.append((pymupdf.Rect(t.bbox), rows))
        table_rects = [r for r, _ in table_rows]

        # Caption blocks (a caption line plus its wrapped continuation lines).
        caption_blocks = {ln.block for ln in page_lines if CAPTION_RE.match(ln.text)}
        captions: list[tuple[str, tuple]] = []
        for b in sorted(caption_blocks):
            blk = [ln for ln in page_lines if ln.block == b]
            first = next(i for i, ln in enumerate(blk) if CAPTION_RE.match(ln.text))
            cap_lines = blk[first:]
            captions.append((normalize_ws(" ".join(ln.text for ln in cap_lines)), _union([ln.bbox for ln in cap_lines])))
        caption_line_ids = {
            id(ln) for b in caption_blocks for ln in page_lines if ln.block == b
            and any(ln.bbox[1] >= c[1][1] - 1 for c in captions if c[1][0] <= ln.bbox[0] + 1)
        }

        # ---- text flow with heading tracking --------------------------------
        paragraphs: list[str] = []
        para_bboxes: list[tuple[float, float, float, float]] = []
        cur_block = -1
        cur_para: list[str] = []
        pending_heading: list[_Line] = []

        def flush_para() -> None:
            nonlocal cur_para
            if cur_para:
                paragraphs.append(" ".join(cur_para))
            cur_para = []

        def flush_section() -> None:
            nonlocal paragraphs, para_bboxes
            flush_para()
            if paragraphs:
                for chunk in chunk_paragraphs(paragraphs):
                    meta = {"injection_suspect": True} if looks_like_injection(chunk) else {}
                    units.append(
                        ExtractedUnit(
                            modality="pdf_text", content=chunk, heading=current_heading(),
                            section_path=section_path(), page_number=pno,
                            bbox=_union(para_bboxes) if para_bboxes else None, extraction_meta=meta,
                        )
                    )
            paragraphs, para_bboxes = [], []

        def commit_heading() -> None:
            if not pending_heading:
                return
            text = normalize_ws(" ".join(h.text for h in pending_heading))
            lvl = level_of.get(pending_heading[0].size)
            y = pending_heading[0].bbox[1]
            pending_heading.clear()
            if lvl is None:  # document title on the cover
                return
            for k in [k for k in section if k >= lvl]:
                del section[k]
            section[lvl] = text
            marks.append((y, section_path(), current_heading()))

        for ln in page_lines:
            cx, cy = (ln.bbox[0] + ln.bbox[2]) / 2, (ln.bbox[1] + ln.bbox[3]) / 2
            if any(r.contains(pymupdf.Point(cx, cy)) for r in table_rects):
                continue
            if id(ln) in caption_line_ids:
                continue
            if heading_candidate(ln) and (ln.size in level_of or ln.size in title_sizes):
                if pending_heading and (pending_heading[-1].block != ln.block or pending_heading[-1].size != ln.size):
                    flush_section()
                    commit_heading()
                if not pending_heading:
                    flush_section()
                pending_heading.append(ln)
                continue
            if pending_heading:
                commit_heading()
            if ln.block != cur_block:
                flush_para()
                cur_block = ln.block
            cur_para.append(ln.text)
            para_bboxes.append(ln.bbox)
        flush_section()
        commit_heading()

        # ---- tables ----------------------------------------------------------
        for rect, rows in table_rows:
            caption = next(
                (c for c, bb in captions if c.lower().startswith("table") and 0 <= rect.y0 - bb[3] < 40), None
            )
            md = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * len(rows[0])]
            md += ["| " + " | ".join(r) + " |" for r in rows[1:]]
            sp, hd = section_at(rect.y0)
            units.append(
                ExtractedUnit(
                    modality="pdf_table", content=((caption + "\n") if caption else "") + "\n".join(md),
                    heading=hd, section_path=sp, page_number=pno, bbox=list(rect),
                    extraction_meta={"rows": len(rows), "cols": len(rows[0]), "caption": caption},
                )
            )

        # ---- figures ------------------------------------------------------
        for info in page.get_image_info(xrefs=True):
            rect = pymupdf.Rect(info["bbox"]) & page.rect
            if rect.is_empty or rect.width < 60 or rect.height < 60:
                continue
            if rect.width * rect.height / page_area > 0.85 and len(page_lines) < 3:
                continue  # full-page scan; handled by OCR below
            png = None
            if info.get("xref"):
                try:
                    raw = doc.extract_image(info["xref"])
                    img = vision.image_from_bytes(raw["image"])
                    png = vision.png_bytes(img)
                except Exception:
                    png = None
            if png is None:
                png = page.get_pixmap(clip=rect, dpi=200).tobytes("png")
            img = vision.image_from_bytes(png)
            if not vision.is_meaningful_image(img):
                continue
            caption = _nearest_caption(rect, captions)
            ocr = vision.ocr_image(img, currency_symbol=currency)
            sp, hd = section_at(rect.y0)
            parts = [caption] if caption else []
            parts.append(f"[Figure on page {pno}]")
            if ocr.word_count:
                parts.append("Text and labels read from the figure (OCR): " + "; ".join(ocr.lines))
            units.append(
                ExtractedUnit(
                    modality="pdf_figure", content="\n".join(parts), heading=hd, section_path=sp, page_number=pno,
                    bbox=list(rect), image_png=png,
                    extraction_meta={
                        "caption": caption, "ocr_words": ocr.word_count, "ocr_mean_confidence": ocr.mean_confidence,
                        "image_size": [img.width, img.height], "method": "tesseract-ocr",
                    },
                )
            )
            if vision_calls < s.max_vision_calls_per_source:
                desc, vinfo = vision.describe_figure(png, context=caption or (hd or ""), course_id=course_id)
                if desc is not None:
                    vision_calls += 1
                    if not desc.get("is_decorative"):
                        dp = "; ".join(f"{d.get('label')}: {d.get('value')}" for d in desc.get("data_points", [])[:20])
                        units.append(
                            ExtractedUnit(
                                modality="pdf_figure",
                                content=(f"{caption}\n" if caption else "")
                                + f"Model description of the figure on page {pno}: {desc.get('description', '')}"
                                + (f"\nData points: {dp}" if dp else "")
                                + (f"\nTakeaway: {desc.get('key_takeaway')}" if desc.get("key_takeaway") else ""),
                                heading=hd, section_path=sp, page_number=pno, bbox=list(rect), image_png=png,
                                is_generated=True, generation_meta={"kind": "vision_description", **vinfo, "raw": desc},
                            )
                        )

        # ---- scanned / image-only page → OCR -----------------------------
        if sum(len(ln.text) for ln in page_lines) < 40:
            pix = page.get_pixmap(dpi=200)
            img = vision.image_from_bytes(pix.tobytes("png"))
            ocr = vision.ocr_image(img, currency_symbol=currency)
            if ocr.word_count >= 8:
                for chunk in chunk_paragraphs(ocr.lines):
                    units.append(
                        ExtractedUnit(
                            modality="pdf_ocr", content=chunk, heading=current_heading(),
                            section_path=section_path(), page_number=pno,
                            extraction_meta={"method": "tesseract-ocr", "ocr_mean_confidence": ocr.mean_confidence},
                        )
                    )
            elif not page_lines:
                warnings.append(f"Page {pno} has no extractable text")

    if not units:
        raise ExtractionError("No text, tables or figures could be extracted from this PDF")
    meta = {k: v for k, v in (doc.metadata or {}).items() if v}
    meta.update({"title": doc_title, "body_font_size": body, "heading_levels": {str(k): v for k, v in level_of.items()},
                 "vision_calls": vision_calls})
    return ExtractionResult(units=units, metadata=meta, page_count=n_pages, warnings=warnings)


def _union(bbs: list[tuple[float, float, float, float]]) -> list[float]:
    return [min(b[0] for b in bbs), min(b[1] for b in bbs), max(b[2] for b in bbs), max(b[3] for b in bbs)]


def _nearest_caption(rect: pymupdf.Rect, captions: list[tuple[str, tuple]]) -> str | None:
    best, best_d = None, 1e9
    for text, bb in captions:
        if not text.lower().startswith(("figure", "fig", "chart", "exhibit")):
            continue
        d = bb[1] - rect.y1 if bb[1] >= rect.y1 - 5 else rect.y0 - bb[3]
        if -5 <= d < 80 and d < best_d:
            best, best_d = text, d
    return best
