"""Lecture video extraction: FFmpeg + Whisper + keyframe OCR.

Timestamp-anchored units:
  - transcript   groups of consecutive Whisper segments (~30-60 s). The exact
                 per-segment timestamps and confidences are kept in
                 extraction_meta["segments"], so a citation can point at the start
                 of the specific segment that supports an answer.
  - video_frame  on-screen text from keyframes chosen by scene-change detection
                 (start = frame time, end = next scene change), with the frame image.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import uuid
from pathlib import Path

from PIL import Image
from rapidfuzz import fuzz

from app.config import get_settings
from app.services.ai import vision
from app.services.ai.text import looks_like_injection, normalize_ws, word_count
from app.services.ai.transcription import Segment, get_transcriber
from app.services.ingestion.types import ExtractedUnit, ExtractionError, ExtractionResult, ProgressFn

MAX_FRAMES = 40


def probe(path: Path) -> dict:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            check=True, capture_output=True, timeout=60,
        ).stdout
    except (subprocess.SubprocessError, OSError) as e:
        raise ExtractionError(f"Could not read video container (ffprobe failed): {e}") from e
    return json.loads(out)


def group_segments(segments: list[Segment], *, target_seconds: float = 40.0, max_words: int = 130,
                   pause_split: float = 2.5) -> list[list[Segment]]:
    groups: list[list[Segment]] = []
    cur: list[Segment] = []
    for seg in segments:
        if cur:
            span = seg.end - cur[0].start
            words = sum(word_count(s.text) for s in cur) + word_count(seg.text)
            gap = seg.start - cur[-1].end
            if span > target_seconds or words > max_words or gap > pause_split:
                groups.append(cur)
                cur = []
        cur.append(seg)
    if cur:
        groups.append(cur)
    return groups


def _scene_frames(path: Path, outdir: Path, duration: float) -> list[tuple[float, Path]]:
    """Keyframes at scene changes, sampled on a 1-fps grid (timestamps have 1 s resolution).

    The scene threshold is low so that slide-style lectures (static cards whose text
    changes) are caught; frames closer than 4 s apart are dropped and the result is
    capped at MAX_FRAMES spread evenly across the video.
    """
    pattern = outdir / "f_%04d.png"
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-vf",
         "fps=1,select='eq(n\\,0)+gt(scene\\,0.02)',showinfo,scale=1280:-2", "-vsync", "vfr",
         "-frames:v", "240", str(pattern)],
        capture_output=True, text=True, timeout=1800,
    )
    times = [float(m) for m in re.findall(r"pts_time:([0-9.]+)", proc.stderr)]
    files = sorted(outdir.glob("f_*.png"))
    frames: list[tuple[float, Path]] = []
    for t, f in zip(times, files):
        if not frames or t - frames[-1][0] >= 4.0:
            frames.append((t, f))
    if len(frames) > MAX_FRAMES:
        step = len(frames) / MAX_FRAMES
        frames = [frames[int(i * step)] for i in range(MAX_FRAMES)]
    if not frames and duration > 0:  # fallback: fixed sampling every 20 s
        for i, t in enumerate(range(0, int(duration), 20)):
            f = outdir / f"s_{i:04d}.png"
            subprocess.run(["ffmpeg", "-y", "-ss", str(t), "-i", str(path), "-frames:v", "1", "-vf", "scale=1280:-2",
                            str(f)], capture_output=True, timeout=120)
            if f.exists():
                frames.append((float(t), f))
    return frames


def extract_video(path: Path, *, course_id: uuid.UUID | None, progress: ProgressFn) -> ExtractionResult:
    s = get_settings()
    info = probe(path)
    streams = info.get("streams", [])
    if not any(st.get("codec_type") == "audio" for st in streams):
        raise ExtractionError("Video has no audio track; a narrated lecture is required for transcription")
    duration = float(info.get("format", {}).get("duration") or 0)
    if duration <= 0:
        raise ExtractionError("Could not determine video duration")
    if duration > s.max_video_minutes * 60:
        raise ExtractionError(f"Video is longer than the {s.max_video_minutes}-minute limit")
    title = (info.get("format", {}).get("tags") or {}).get("title") or path.stem

    units: list[ExtractedUnit] = []
    warnings: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)
        progress("Extracting audio track", 0.05)
        wav = tmpd / "audio.wav"
        try:
            subprocess.run(["ffmpeg", "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", str(wav)],
                           check=True, capture_output=True, timeout=900)
        except subprocess.SubprocessError as e:
            raise ExtractionError(f"Audio extraction failed: {e}") from e

        progress("Transcribing speech (Whisper)", 0.15)
        transcriber = get_transcriber()
        transcript = transcriber.transcribe(wav)
        if not transcript.segments:
            raise ExtractionError("No speech was detected in the video")

        spoken = " ".join(sg.text.lower() for sg in transcript.segments)
        currency = "₹" if "rupee" in spoken else "€" if "euro" in spoken else "£" if "pound" in spoken else None

        progress("Detecting keyframes", 0.6)
        frames_dir = tmpd / "frames"
        frames_dir.mkdir()
        frames = _scene_frames(path, frames_dir, duration)
        frame_units: list[ExtractedUnit] = []
        seen: list[str] = []
        for i, (t, f) in enumerate(frames):
            progress(f"Reading on-screen text ({i + 1}/{len(frames)})", 0.65 + 0.2 * i / max(len(frames), 1))
            img = Image.open(f)
            ocr = vision.ocr_image(img, currency_symbol=currency)
            end = frames[i + 1][0] if i + 1 < len(frames) else duration
            if ocr.word_count < 3:
                continue
            if seen and fuzz.ratio(ocr.text, seen[-1]) >= 90:
                frame_units[-1].end_seconds = round(end, 2)  # same on-screen text continues
                continue
            seen.append(ocr.text)
            png = vision.png_bytes(img)
            frame_units.append(ExtractedUnit(
                modality="video_frame",
                content=f"On-screen text at {_ts(t)}: " + " / ".join(ocr.lines),
                heading=ocr.lines[0][:200] if ocr.lines else None, section_path=[title],
                start_seconds=round(t, 2), end_seconds=round(end, 2), image_png=png,
                extraction_meta={"method": "scene-change keyframe + tesseract-ocr", "timestamp_resolution_s": 1,
                                 "ocr_words": ocr.word_count,
                                 "ocr_mean_confidence": ocr.mean_confidence},
            ))

        def heading_at(t0: float, t1: float) -> str | None:
            cands = [u for u in frame_units if u.start_seconds is not None and u.start_seconds <= t1
                     and (u.end_seconds or 0) >= t0]
            return cands[0].heading if cands else None

        progress("Building transcript units", 0.9)
        for grp in group_segments(transcript.segments):
            text = normalize_ws(" ".join(sg.text for sg in grp))
            confs = [sg.confidence for sg in grp if sg.confidence is not None]
            meta = {
                "segments": [{"start": sg.start, "end": sg.end, "text": sg.text, "confidence": sg.confidence}
                             for sg in grp],
                "mean_confidence": round(sum(confs) / len(confs), 3) if confs else None,
                "transcription_model": transcript.model,
                "language": transcript.language,
            }
            if looks_like_injection(text):
                meta["injection_suspect"] = True
            units.append(ExtractedUnit(
                modality="transcript", content=text, heading=heading_at(grp[0].start, grp[-1].end),
                section_path=[title], start_seconds=grp[0].start, end_seconds=grp[-1].end, extraction_meta=meta,
            ))
        units.extend(frame_units)

    units.sort(key=lambda u: (u.start_seconds or 0, 0 if u.modality == "transcript" else 1))
    return ExtractionResult(
        units=units, duration_seconds=round(duration, 2), warnings=warnings,
        metadata={"title": title, "transcription_model": transcript.model, "language": transcript.language,
                  "segments": len(transcript.segments), "keyframes": len(frames), "frame_units": len(frame_units)},
    )


def _ts(t: float) -> str:
    m, sec = divmod(int(round(t)), 60)
    return f"{m:02d}:{sec:02d}"
