"""dtranscript web UI (Gradio). Run: python app.py  ->  http://127.0.0.1:7860"""

from __future__ import annotations

import os

import gradio as gr

from dtranscript.core import (
    LANG_INSTRUCTIONS,
    analyze,
    list_templates,
    render_markdown,
    save_markdown,
)
from dtranscript.youtube import get_transcript

MODES = {"Raw transcript": "raw", "AI summary": "summary"}
MODELS = ["CLI default", "sonnet", "opus", "haiku"]
WHISPER_SIZES = ["tiny", "base", "small", "medium", "large-v3"]


def run(url, mode_label, template, language, model_label, timestamps, append_transcript,
        force_whisper, whisper_size):
    log_lines: list[str] = []

    def log(msg: str):
        log_lines.append(msg)

    def status():
        return "\n".join(log_lines)

    mode = MODES[mode_label]
    model = None if model_label == "CLI default" else model_label

    if not (url or "").strip():
        yield "", None, "Paste a YouTube URL first."
        return
    if mode == "summary" and not template:
        yield "", None, "No template selected. Add a .md file to prompts/."
        return

    try:
        yield "", None, "Starting..."
        t = get_transcript(url, force_whisper=force_whisper, whisper_model=whisper_size, log=log)
        log(f"Transcript ready: {len(t.segments)} segments via {t.source}.")
        yield "", None, status()

        analysis = None
        if mode == "summary":
            log(f"Analyzing with Claude (template: {template}, model: {model_label})...")
            yield "", None, status()
            analysis = analyze(t, template, language=language, model=model)

        md = render_markdown(t, mode, analysis=analysis, template=template, model=model,
                             timestamps=timestamps, append_transcript=append_transcript)
        path = save_markdown(t, md, mode, template)
        log(f"Saved: {path}")
        yield md, str(path), status()
    except Exception as exc:  # surface any failure in the UI
        log(f"ERROR: {type(exc).__name__}: {exc}")
        yield "", None, status()


def build_ui() -> gr.Blocks:
    templates = list_templates()
    with gr.Blocks(title="dtranscript") as demo:
        gr.Markdown("# dtranscript\nYouTube video or Short to Markdown transcript or AI summary.")

        with gr.Row():
            url = gr.Textbox(label="YouTube URL", placeholder="https://www.youtube.com/watch?v=... or /shorts/...", scale=4)
            go = gr.Button("Run", variant="primary", scale=1)

        with gr.Row():
            mode = gr.Radio(list(MODES), value="AI summary", label="Mode")
            template = gr.Dropdown(templates, value=templates[0] if templates else None, label="Summary template")
            language = gr.Dropdown(list(LANG_INSTRUCTIONS), value="Same as video", label="Output language")
            model = gr.Dropdown(MODELS, value="CLI default", label="Claude model")

        with gr.Accordion("Options", open=False):
            with gr.Row():
                timestamps = gr.Checkbox(value=True, label="Timestamps in transcript")
                append_transcript = gr.Checkbox(value=False, label="Append full transcript to summary")
                force_whisper = gr.Checkbox(value=False, label="Skip captions, force Whisper")
                whisper_size = gr.Dropdown(WHISPER_SIZES,
                                           value=os.getenv("DTRANSCRIPT_WHISPER_MODEL", "small"),
                                           label="Whisper model")
            refresh = gr.Button("Reload templates", size="sm")

        status = gr.Textbox(label="Status", lines=4, interactive=False)
        file_out = gr.File(label="Markdown file")
        preview = gr.Markdown(label="Preview")

        inputs = [url, mode, template, language, model, timestamps, append_transcript,
                  force_whisper, whisper_size]
        go.click(run, inputs, [preview, file_out, status])
        url.submit(run, inputs, [preview, file_out, status])
        refresh.click(lambda: gr.Dropdown(choices=list_templates()), None, template)

    return demo


if __name__ == "__main__":
    build_ui().queue().launch(
        server_name=os.getenv("DTRANSCRIPT_HOST", "127.0.0.1"),
        server_port=int(os.getenv("DTRANSCRIPT_PORT", "7860")),
    )
