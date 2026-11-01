"""YouTube helpers: URL parsing, metadata, captions and Whisper fallback."""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_PATH_PREFIXES = ("shorts", "embed", "live", "v", "e")


class TranscriptError(RuntimeError):
    """Raised when no transcript could be produced."""


@dataclass
class Segment:
    start: float  # seconds
    text: str


@dataclass
class Transcript:
    video_id: str
    url: str
    segments: list[Segment]
    source: str  # e.g. "captions:pt" or "whisper:small"
    language: str | None = None
    meta: dict = field(default_factory=dict)

    @property
    def title(self) -> str:
        return self.meta.get("title") or self.video_id

    def plain_text(self) -> str:
        return " ".join(s.text for s in self.segments).strip()

    def timestamped_text(self) -> str:
        return "\n".join(f"[{fmt_ts(s.start)}] {s.text}" for s in self.segments)


def fmt_ts(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def parse_video_id(url: str) -> str:
    """Extract the 11-char video id from any common YouTube URL (incl. Shorts)."""
    url = (url or "").strip()
    if _ID_RE.match(url):
        return url
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    parts = [p for p in parsed.path.split("/") if p]

    candidate = None
    if host == "youtu.be" and parts:
        candidate = parts[0]
    elif host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
        if parts and parts[0] == "watch":
            candidate = parse_qs(parsed.query).get("v", [None])[0]
        elif len(parts) >= 2 and parts[0] in _PATH_PREFIXES:
            candidate = parts[1]

    if candidate and _ID_RE.match(candidate):
        return candidate
    raise ValueError(f"Not a recognizable YouTube video URL: {url!r}")


def canonical_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


# --------------------------------------------------------------------------- #
# Metadata
# --------------------------------------------------------------------------- #

def _ydl_opts(**extra) -> dict:
    opts = {"quiet": True, "no_warnings": True, "noprogress": True}
    opts.update(extra)
    return opts


def fetch_metadata(video_id: str) -> dict:
    """Best-effort metadata via yt-dlp. Returns {} on failure (never fatal)."""
    try:
        from yt_dlp import YoutubeDL

        with YoutubeDL(_ydl_opts(skip_download=True)) as ydl:
            info = ydl.extract_info(canonical_url(video_id), download=False)
    except Exception:
        return {}
    upload = info.get("upload_date") or ""
    if len(upload) == 8:
        upload = f"{upload[:4]}-{upload[4:6]}-{upload[6:]}"
    return {
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "upload_date": upload or None,
        "duration": info.get("duration"),
        "language": info.get("language"),
    }


# --------------------------------------------------------------------------- #
# Captions (fast path)
# --------------------------------------------------------------------------- #

def fetch_captions(video_id: str, languages: list[str]) -> tuple[list[Segment], str]:
    """Fetch existing YouTube captions. Prefers manual over auto-generated."""
    from youtube_transcript_api import YouTubeTranscriptApi

    api = YouTubeTranscriptApi()
    listing = api.list(video_id)
    try:
        chosen = listing.find_transcript(languages)
    except Exception:
        # No preferred language: take whatever exists (manual first).
        available = sorted(listing, key=lambda t: t.is_generated)
        if not available:
            raise TranscriptError("Video has no captions.")
        chosen = available[0]

    fetched = chosen.fetch()
    segments = [
        Segment(start=s.start, text=s.text.replace("\n", " ").strip())
        for s in fetched.snippets
        if s.text.strip()
    ]
    if not segments:
        raise TranscriptError("Captions were empty.")
    return segments, chosen.language_code


# --------------------------------------------------------------------------- #
# Whisper (fallback)
# --------------------------------------------------------------------------- #

_whisper_cache: dict[tuple[str, str], object] = {}


def _whisper_model(size: str, device: str):
    key = (size, device)
    if key not in _whisper_cache:
        from faster_whisper import WhisperModel

        compute = os.getenv("DTRANSCRIPT_WHISPER_COMPUTE", "int8" if device == "cpu" else "default")
        _whisper_cache[key] = WhisperModel(size, device=device, compute_type=compute)
    return _whisper_cache[key]


def _run_whisper(audio_path: str, size: str) -> tuple[list[Segment], str]:
    device = os.getenv("DTRANSCRIPT_WHISPER_DEVICE", "auto")
    try:
        model = _whisper_model(size, device)
        raw_segments, info = model.transcribe(audio_path, vad_filter=True)
        # Segments are lazy: CUDA errors only surface while iterating.
        segments = [Segment(start=s.start, text=s.text.strip()) for s in raw_segments if s.text.strip()]
        return segments, info.language
    except RuntimeError as exc:
        # GPU detected but CUDA/cuDNN libs missing: retry on CPU.
        if device == "cpu" or not re.search(r"cuda|cublas|cudnn", str(exc), re.I):
            raise
        model = _whisper_model(size, "cpu")
        raw_segments, info = model.transcribe(audio_path, vad_filter=True)
        segments = [Segment(start=s.start, text=s.text.strip()) for s in raw_segments if s.text.strip()]
        return segments, info.language


def whisper_transcribe(video_id: str, model_size: str) -> tuple[list[Segment], str]:
    """Download audio with yt-dlp and transcribe locally with faster-whisper.

    faster-whisper decodes audio through PyAV, so no system ffmpeg is needed.
    """
    from yt_dlp import YoutubeDL

    with tempfile.TemporaryDirectory(prefix="dtranscript_") as tmp:
        opts = _ydl_opts(
            format="bestaudio/best",
            outtmpl=str(Path(tmp) / "%(id)s.%(ext)s"),
        )
        with YoutubeDL(opts) as ydl:
            ydl.download([canonical_url(video_id)])
        files = list(Path(tmp).iterdir())
        if not files:
            raise TranscriptError("Audio download produced no file.")

        segments, language = _run_whisper(str(files[0]), model_size)

    if not segments:
        raise TranscriptError("Whisper produced an empty transcript.")
    return segments, language


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def get_transcript(
    url: str,
    languages: list[str] | None = None,
    force_whisper: bool = False,
    whisper_model: str | None = None,
    log=print,
) -> Transcript:
    """Captions first; fall back to local Whisper transcription."""
    video_id = parse_video_id(url)
    languages = languages or ["pt", "pt-BR", "en"]
    whisper_model = whisper_model or os.getenv("DTRANSCRIPT_WHISPER_MODEL", "small")

    log(f"Video id: {video_id}. Fetching metadata...")
    meta = fetch_metadata(video_id)

    if not force_whisper:
        try:
            log("Trying YouTube captions...")
            segments, lang = fetch_captions(video_id, languages)
            return Transcript(video_id, canonical_url(video_id), segments, f"captions:{lang}", lang, meta)
        except Exception as exc:  # noqa: BLE001 - any failure means "use fallback"
            log(f"Captions unavailable ({type(exc).__name__}). Falling back to Whisper...")

    try:
        log(f"Downloading audio and transcribing with Whisper ({whisper_model})...")
        segments, lang = whisper_transcribe(video_id, whisper_model)
    except Exception as exc:
        raise TranscriptError(f"Whisper fallback failed: {exc}") from exc
    return Transcript(video_id, canonical_url(video_id), segments, f"whisper:{whisper_model}", lang, meta)
