"""LLM access through the Claude Code CLI (`claude -p`).

No API key is read, stored or passed by this project. Authentication is whatever
the `claude` CLI on this machine is already logged in with (`claude login` OAuth,
or ANTHROPIC_API_KEY in the environment, which the CLI picks up by itself).

Account selection:
- `claude`, `claude-work` and `claude-personal` are zsh shell functions (see
  ~/.zshrc), not separate binaries. All three invoke the same `claude`
  executable; `claude-work`/`claude-personal` just export CLAUDE_CONFIG_DIR
  first to point at a different account's config/keychain entry. A subprocess
  can't see shell functions, so the same effect is reproduced here by setting
  CLAUDE_CONFIG_DIR on the child process's environment before exec'ing the one
  real `claude` binary. Select the account via DTRANSCRIPT_CLAUDE_PROFILE
  (work|personal|regular); defaults to "work".

Design notes:
- The user prompt (transcript) goes through stdin, not argv: avoids the
  ~32k-char Windows command-line limit on long videos.
- The system prompt goes through a temp file (--system-prompt-file): avoids
  cmd.exe quoting issues when `claude` resolves to the `claude.cmd` shim.
- `--tools ""` disables all tools: the model only reads and writes text.
- `--setting-sources ""` ignores user/project settings, so personal hooks,
  plugins or output styles don't leak into summaries. OAuth still works
  (unlike `--bare`, which skips keychain reads).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

# Mirrors the claude-work/claude-personal functions in ~/.zshrc. "regular"
# means "don't override CLAUDE_CONFIG_DIR", i.e. plain `claude`.
PROFILE_CONFIG_DIRS = {
    "work": Path.home() / ".claude",
    "personal": Path.home() / ".claude-personal",
    "regular": None,
}
DEFAULT_PROFILE = "work"


class LLMError(RuntimeError):
    pass


def claude_binary() -> str:
    exe = os.getenv("DTRANSCRIPT_CLAUDE_BIN") or shutil.which("claude")
    if not exe:
        raise LLMError(
            "`claude` CLI not found on PATH. Install Claude Code and run `claude login` "
            "(or set DTRANSCRIPT_CLAUDE_BIN to its full path)."
        )
    return exe


def claude_profile() -> str:
    profile = os.getenv("DTRANSCRIPT_CLAUDE_PROFILE", DEFAULT_PROFILE)
    if profile not in PROFILE_CONFIG_DIRS:
        raise LLMError(
            f"Unknown DTRANSCRIPT_CLAUDE_PROFILE={profile!r}; "
            f"expected one of {sorted(PROFILE_CONFIG_DIRS)}."
        )
    return profile


def claude_env(profile: str | None = None) -> dict[str, str]:
    """Environment for the claude subprocess, with CLAUDE_CONFIG_DIR set per profile."""
    profile = profile or claude_profile()
    env = os.environ.copy()
    config_dir = PROFILE_CONFIG_DIRS[profile]
    if config_dir is None:
        env.pop("CLAUDE_CONFIG_DIR", None)
    else:
        env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    return env


def call_claude(
    prompt: str,
    system: str = "",
    model: str | None = None,
    profile: str | None = None,
    timeout: int = 900,
) -> str:
    """Send `prompt` to Claude via the CLI and return the text reply."""
    model = model or os.getenv("DTRANSCRIPT_MODEL") or None
    cmd = [
        claude_binary(),
        "-p",
        "--output-format", "text",
        "--tools", "",
        "--setting-sources", "",
        "--no-session-persistence",
    ]
    if model:
        cmd += ["--model", model]

    sys_file = None
    try:
        if system:
            fd, sys_file = tempfile.mkstemp(prefix="dtranscript_sys_", suffix=".md")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(system)
            cmd += ["--system-prompt-file", sys_file]

        # Neutral cwd so no project CLAUDE.md gets auto-discovered.
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=tempfile.gettempdir(),
            env=claude_env(profile),
        )
    except subprocess.TimeoutExpired as exc:
        raise LLMError(f"claude CLI timed out after {timeout}s") from exc
    finally:
        if sys_file:
            Path(sys_file).unlink(missing_ok=True)

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-2000:]
        raise LLMError(f"claude CLI exited with code {result.returncode}: {detail}")
    return result.stdout.strip()
