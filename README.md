# dtranscript

Paste a YouTube video or Short URL into a local web page and get a Markdown file with either:

- the **raw transcript** (with or without timestamps), or
- an **AI analysis/summary** in a shape you define with a plain Markdown template.

Everything runs locally. The AI step uses the [Claude Code](https://docs.claude.com/en/docs/claude-code) CLI you are already logged in to, so **this project stores and reads no API keys**.

```
URL ─► YouTube captions (youtube-transcript-api)      fast, free
        └─ fallback: yt-dlp audio ─► faster-whisper   local speech-to-text
     ─► [raw]     Markdown transcript
     ─► [summary] claude -p + prompts/<template>.md ─► Markdown summary
     ─► output/YYYY-MM-DD_<title>_<id>_<mode>.md (with YAML frontmatter)
```

## Requirements

| Tool | Why | Check |
|---|---|---|
| Python 3.11+ | runs the app | `python --version` |
| Claude Code CLI, logged in | AI summaries (raw mode works without it) | `claude -p "hello"` |

You don't need ffmpeg: faster-whisper decodes audio through PyAV.

### Claude authentication (one-time)

1. Install Claude Code: `npm install -g @anthropic-ai/claude-code`, or see the official docs.
2. Run `claude` once and log in. The credentials are kept by the CLI in your OS credential store.
3. Verify: `claude -p "hello"` should print a reply.

If you use API-key billing instead of a subscription, set `ANTHROPIC_API_KEY` in your environment. The CLI picks it up by itself, and this app never reads it.

## Install

```powershell
git clone https://github.com/pedrovanzo/dtranscript.git
cd dtranscript
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

## Run the server

```powershell
.venv\Scripts\activate
python app.py
```

Open **http://127.0.0.1:7860** in your browser. Stop the server with `Ctrl+C` in the terminal.

To use another port: `$env:DTRANSCRIPT_PORT=8080; python app.py` (PowerShell) or `DTRANSCRIPT_PORT=8080 python app.py` (bash).

The server binds only to `127.0.0.1`, so it is not reachable from other machines.

## Use

1. Paste a URL. Supported formats: `watch?v=`, `youtu.be/`, `/shorts/`, `/live/`, `/embed/`, or a bare 11-character video ID.
2. Pick a **Mode**:
   - **Raw transcript**: no AI involved.
   - **AI summary**: pick a **template**, an **output language** and a **Claude model** (`CLI default`, `sonnet`, `opus`, `haiku`).
3. Click **Run**. The status box shows progress. The preview shows the result, and the `.md` file is saved in `output/` and offered for download.

**Options** (collapsed panel):
- timestamps on or off;
- append the full transcript to the summary (inside a collapsible `<details>` block);
- skip captions and force Whisper, for example when the auto-captions are bad;
- Whisper model size: `tiny` is fastest, `large-v3` is the most accurate. The model downloads on first use.

## Custom summary shapes

Each `.md` file in `prompts/` becomes a template in the dropdown. The file content describes the output structure you want. See `prompts/summary.md` and `prompts/news-brief.md`.

To add a template, create `prompts/my-shape.md` and click **Reload templates**. You don't need to restart the server.

The app always prepends base rules: use only the transcript, never invent facts, quote verbatim with `[mm:ss]` timestamps, and output Markdown only.

## How the Claude call works

`dtranscript/llm.py` shells out to the CLI:

```
claude -p --output-format text --tools "" --setting-sources "" --no-session-persistence \
       [--model <m>] --system-prompt-file <tmp>   < transcript on stdin
```

- **stdin for the transcript**: long videos would exceed the Windows command-line length limit.
- **system prompt in a temp file**: avoids `cmd.exe` quoting problems with the `claude.cmd` shim.
- **`--tools ""`**: the model only reads text. It cannot run commands or edit files.
- **`--setting-sources ""`**: your personal Claude Code hooks, plugins and output styles don't leak into summaries.
- `--bare` is **not** used, because it skips the OS credential store and would break subscription login.

## Configuration (environment variables, all optional)

| Variable | Default | Purpose |
|---|---|---|
| `DTRANSCRIPT_PORT` | `7860` | UI port |
| `DTRANSCRIPT_HOST` | `127.0.0.1` | Bind address |
| `DTRANSCRIPT_MODEL` | CLI default | Claude model when the UI shows "CLI default" |
| `DTRANSCRIPT_CLAUDE_BIN` | `claude` on PATH | Full path to the CLI |
| `DTRANSCRIPT_WHISPER_MODEL` | `small` | Default Whisper size |
| `DTRANSCRIPT_WHISPER_DEVICE` | `auto` | `auto`, `cpu` or `cuda`. `auto` falls back to CPU if the CUDA libraries are missing |
| `DTRANSCRIPT_WHISPER_COMPUTE` | `int8` on CPU | CTranslate2 compute type |
| `DTRANSCRIPT_OUTPUT_DIR` | `./output` | Where `.md` files go |
| `DTRANSCRIPT_PROMPTS_DIR` | `./prompts` | Template folder |

## Tests

```powershell
python -m pytest -q
```

## Troubleshooting

- **Captions fail on every video**: YouTube blocks caption requests from cloud and datacenter IPs. Run from a home or office connection. Whisper is used automatically as the fallback.
- **Download errors**: YouTube changes often. Update with `pip install -U yt-dlp`.
- **`claude CLI not found`**: make sure `claude` is on PATH in the same terminal, or set `DTRANSCRIPT_CLAUDE_BIN`.
- **`cublas64_12.dll` / CUDA errors**: handled automatically by retrying on CPU. To force CPU, set `DTRANSCRIPT_WHISPER_DEVICE=cpu`.
- **Symlink warning from Hugging Face on Windows**: harmless. The model cache just uses more disk space.

## Responsible use

- AI summaries can be wrong or incomplete. Check facts and quotes against the transcript before any reuse or publication. Every summary file is marked with `ai_generated: true`.
- Transcripts of third-party videos are for personal or research use. Respect copyright and YouTube's Terms of Service. `output/` is git-ignored so third-party content is not committed.
