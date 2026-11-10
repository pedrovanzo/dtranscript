"""Pipeline: transcript -> (optional) AI analysis -> Markdown file."""

from __future__ import annotations

import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from .llm import call_claude
from .youtube import Transcript, fmt_ts

ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = Path(os.getenv("DTRANSCRIPT_PROMPTS_DIR", ROOT / "prompts"))
OUTPUT_DIR = Path(os.getenv("DTRANSCRIPT_OUTPUT_DIR", ROOT / "output"))

BASE_SYSTEM = """You analyze transcripts of YouTube videos.
Rules:
- Use ONLY information present in the transcript. Never invent facts, names, numbers or quotes.
- Quotes must be verbatim from the transcript and carry their [mm:ss] timestamp.
- If the transcript is unclear or likely mis-transcribed, say so.
- Output Markdown only, starting directly with the content (no preamble, no closing remarks).
- Start headings at level 2 (##); the document title is added by the app.
"""

LANG_INSTRUCTIONS = {
    "Same as video": "Write in the same language as the transcript.",
    "Português": "Write in Brazilian Portuguese.",
    "English": "Write in English.",
}


def list_templates() -> list[str]:
    return sorted(p.stem for p in PROMPTS_DIR.glob("*.md"))


def load_template(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"Template not found: {path}")
    return path.read_text(encoding="utf-8")


def analyze(
    t: Transcript,
    template: str,
    language: str = "Same as video",
    model: str | None = None,
    profile: str | None = None,
) -> str:
    system = "\n\n".join([
        BASE_SYSTEM,
        LANG_INSTRUCTIONS.get(language, LANG_INSTRUCTIONS["Same as video"]),
        "## Output shape\n\n" + load_template(template),
    ])
    prompt = (
        f"Video title: {t.title}\n"
        f"Channel: {t.meta.get('channel') or 'unknown'}\n"
        f"URL: {t.url}\n\n"
        f"<transcript>\n{t.timestamped_text()}\n</transcript>"
    )
    return call_claude(prompt, system=system, model=model, profile=profile)


# --------------------------------------------------------------------------- #
# Markdown rendering
# --------------------------------------------------------------------------- #

def slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s_]+", "-", text)[:max_len].strip("-") or "video"


def _yaml_str(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, (int, float, bool)):
        return str(value).lower() if isinstance(value, bool) else str(value)
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _frontmatter(fields: dict) -> str:
    lines = [f"{k}: {_yaml_str(v)}" for k, v in fields.items()]
    return "---\n" + "\n".join(lines) + "\n---\n"


def _raw_body(t: Transcript, timestamps: bool) -> str:
    if timestamps:
        return "\n".join(f"**[{fmt_ts(s.start)}]** {s.text}  " for s in t.segments)
    return t.plain_text()


def render_markdown(
    t: Transcript,
    mode: str,
    analysis: str | None = None,
    template: str | None = None,
    model: str | None = None,
    timestamps: bool = True,
    append_transcript: bool = False,
) -> str:
    fm = {
        "title": t.title,
        "channel": t.meta.get("channel"),
        "url": t.url,
        "video_id": t.video_id,
        "upload_date": t.meta.get("upload_date"),
        "duration": fmt_ts(t.meta["duration"]) if t.meta.get("duration") else None,
        "transcript_source": t.source,
        "language": t.language,
        "mode": mode,
        "template": template,
        "model": (model or "cli-default") if mode == "summary" else None,
        "ai_generated": mode == "summary",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    parts = [_frontmatter(fm), f"# {t.title}\n", f"Source: <{t.url}>\n"]

    if mode == "summary":
        parts.append(
            "> AI-generated summary. Verify facts and quotes against the transcript "
            "before any use or publication.\n"
        )
        parts.append(analysis or "")
        if append_transcript:
            parts.append("\n## Transcript\n\n<details>\n<summary>Show full transcript</summary>\n\n")
            parts.append(_raw_body(t, timestamps))
            parts.append("\n\n</details>")
    else:
        parts.append("## Transcript\n")
        parts.append(_raw_body(t, timestamps))

    return "\n".join(parts).rstrip() + "\n"


def save_markdown(t: Transcript, content: str, mode: str, template: str | None = None) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = template if mode == "summary" and template else "transcript"
    name = f"{datetime.now():%Y-%m-%d}_{slugify(t.title)}_{t.video_id}_{suffix}.md"
    path = OUTPUT_DIR / name
    path.write_text(content, encoding="utf-8")
    return path
