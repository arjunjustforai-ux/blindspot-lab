"""Speech transcription with segment-level timestamps.

Local: faster-whisper (CTranslate2 Whisper). Remote: OpenAI-compatible
/audio/transcriptions with verbose_json segment timestamps. Timestamps always come
from the transcription model's own segment boundaries; we never interpolate them
from chunk positions.
"""

from __future__ import annotations

import math
import threading
import wave
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import httpx
import numpy as np

from app.config import get_settings


@dataclass
class Segment:
    start: float
    end: float
    text: str
    confidence: float | None  # exp(avg_logprob) when available
    no_speech_prob: float | None


@dataclass
class Transcript:
    segments: list[Segment]
    language: str | None
    model: str
    duration: float | None


def _read_wav_16k_mono(path: Path) -> np.ndarray:
    """Decode the 16 kHz mono PCM WAV produced by our FFmpeg step into float32 samples."""
    with wave.open(str(path)) as wf:
        if wf.getframerate() != 16000 or wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            raise ValueError("expected 16 kHz mono 16-bit PCM audio")
        raw = wf.readframes(wf.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


class LocalWhisper:
    def __init__(self, model: str, cache_dir: str) -> None:
        from faster_whisper import WhisperModel

        self.model_name = f"faster-whisper:{model}"
        self._m = WhisperModel(model, device="cpu", compute_type="int8", download_root=cache_dir)
        self._lock = threading.Lock()

    def transcribe(self, audio_path: Path, prompt: str | None = None) -> Transcript:
        audio = _read_wav_16k_mono(audio_path)
        with self._lock:
            segs, info = self._m.transcribe(audio, beam_size=5, vad_filter=True, word_timestamps=False,
                                            initial_prompt=prompt or None)
            out = [
                Segment(
                    start=round(s.start, 2),
                    end=round(s.end, 2),
                    text=s.text.strip(),
                    confidence=round(math.exp(s.avg_logprob), 3) if s.avg_logprob is not None else None,
                    no_speech_prob=round(s.no_speech_prob, 3) if s.no_speech_prob is not None else None,
                )
                for s in segs
                if s.text.strip()
            ]
        return Transcript(segments=out, language=info.language, model=self.model_name, duration=info.duration)


class OpenAITranscriber:
    def __init__(self, model: str, base_url: str, api_key: str) -> None:
        self.model_name = f"openai:{model}"
        self.model = model
        self.url = base_url.rstrip("/") + "/audio/transcriptions"
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def transcribe(self, audio_path: Path, prompt: str | None = None) -> Transcript:
        data = {"model": self.model, "response_format": "verbose_json", "timestamp_granularities[]": "segment"}
        if prompt:
            data["prompt"] = prompt
        with audio_path.open("rb") as f:
            r = httpx.post(
                self.url,
                headers=self.headers,
                data=data,
                files={"file": (audio_path.name, f, "audio/mpeg")},
                timeout=600,
            )
        r.raise_for_status()
        d = r.json()
        segs = [
            Segment(
                start=round(float(s["start"]), 2),
                end=round(float(s["end"]), 2),
                text=str(s["text"]).strip(),
                confidence=round(math.exp(s["avg_logprob"]), 3) if s.get("avg_logprob") is not None else None,
                no_speech_prob=s.get("no_speech_prob"),
            )
            for s in d.get("segments", [])
            if str(s.get("text", "")).strip()
        ]
        return Transcript(segments=segs, language=d.get("language"), model=self.model_name, duration=d.get("duration"))


@lru_cache
def get_transcriber() -> LocalWhisper | OpenAITranscriber:
    s = get_settings()
    if s.transcription_provider == "openai":
        if not s.openai_api_key:
            raise RuntimeError("TRANSCRIPTION_PROVIDER=openai requires OPENAI_API_KEY")
        return OpenAITranscriber(s.openai_transcription_model, s.openai_base_url, s.openai_api_key)
    return LocalWhisper(s.whisper_model, str(s.model_cache_dir))
