#!/usr/bin/env python3
"""
HakusAgent sidecar runtime import smoke test.

Simulates the EXACT import chain that the PyInstaller-bundled
hakusai-server.exe would execute on startup. If this script runs clean
in a fresh venv that has only the runtime deps installed, the bundled
exe will also start without "No module named xxx" errors.

Run AFTER fixing the .spec file, BEFORE pushing.

Usage:
    # In repo root, inside the project venv:
    python scripts/sidecar_import_smoke.py

Exit codes:
    0 = all imports OK
    1 = at least one import failed
"""

from __future__ import annotations

import importlib
import sys
import traceback
from typing import NamedTuple


class Check(NamedTuple):
    name: str
    module: str
    required: bool = True


# ---------------------------------------------------------------------------
# The import chain mirrors the sidecar startup order observed in the
# traceback:  entry -> server -> hakusai_core -> config -> agent -> ...
# Each module here is one that PyInstaller's static analysis might miss
# because it's loaded dynamically or transitively.
# ---------------------------------------------------------------------------
CHECKS: list[Check] = [
    # --- web framework stack ---
    Check("uvicorn",        "uvicorn"),
    Check("fastapi",        "fastapi"),
    Check("starlette",      "starlette"),
    Check("pydantic",       "pydantic"),
    Check("pydantic-core",  "pydantic_core"),
    Check("anyio",          "anyio"),
    Check("sniffio",        "sniffio"),
    Check("h11",            "h11"),
    Check("httptools",      "httptools"),
    Check("websockets",     "websockets"),
    Check("multipart",      "multipart"),
    Check("python-multipart", "multipart.python_api"),

    # --- config / utils ---
    Check("watchdog",              "watchdog"),
    Check("watchdog.observers",    "watchdog.observers"),
    Check("watchdog.observers.polling", "watchdog.observers.polling"),
    Check("pyyaml",         "yaml"),
    Check("tomli",          "tomli"),
    Check("tomllib",        "tomllib", required=False),  # py<3.11 only
    Check("python-dotenv",  "dotenv"),
    Check("filelock",       "filelock"),

    # --- logging / observability ---
    Check("structlog",      "structlog"),
    Check("loguru",         "loguru", required=False),

    # --- HTTP client ---
    Check("httpx",          "httpx"),
    Check("httpcore",       "httpcore"),
    Check("certifi",        "certifi"),
    Check("idna",           "idna"),
    Check("urllib3",        "urllib3", required=False),
    Check("requests",       "requests", required=False),

    # --- AI / LLM providers ---
    Check("openai",         "openai"),
    Check("anthropic",      "anthropic", required=False),
    Check("tiktoken",       "tiktoken", required=False),
    Check("tokenizers",     "tokenizers", required=False),
    Check("transformers",   "transformers", required=False),
    Check("torch",          "torch", required=False),
    Check("sentence-transformers", "sentence_transformers", required=False),

    # --- audio / voice (THIS IS WHERE numpy WAS MISSING) ---
    Check("numpy",          "numpy"),
    Check("scipy",          "scipy", required=False),
    Check("librosa",        "librosa", required=False),
    Check("soundfile",      "soundfile", required=False),
    Check("pydub",          "pydub", required=False),
    Check("audioop",        "audioop", required=False),  # stdlib but py3.13+ removed

    # --- ASR / TTS providers ---
    Check("whisper",        "whisper", required=False),
    Check("faster-whisper", "faster_whisper", required=False),
    Check("edge-tts",       "edge_tts", required=False),
    Check("pyttsx3",        "pyttsx3", required=False),

    # --- websocket / async ---
    Check("websockets.legacy", "websockets.legacy", required=False),
    Check("aiosqlite",      "aiosqlite", required=False),
    Check("asyncpg",        "asyncpg", required=False),

    # --- templating / utils ---
    Check("jinja2",         "jinja2"),
    Check("markupsafe",     "markupsafe"),
    Check("click",          "click", required=False),
    Check("rich",           "rich", required=False),

    # --- first-party (these should always succeed after pip install -e .) ---
    Check("hakusai_server", "hakusai_server"),
    Check("hakusai_core",   "hakusai_core"),
]


def run_one(check: Check) -> tuple[bool, str]:
    """Try to import the module; return (ok, message)."""
    try:
        importlib.import_module(check.module)
        return True, "ok"
    except ImportError as e:
        if check.required:
            return False, f"REQUIRED MISSING: {e}"
        return True, f"optional skip: {e}"
    except Exception as e:
        # Module imported but raised something else (e.g. circular import,
        # missing native binary, version mismatch). Still counts as a
        # failure for required modules because the sidecar would crash.
        if check.required:
            return False, f"REQUIRED ERROR: {type(e).__name__}: {e}"
        return True, f"optional error: {type(e).__name__}: {e}"


def main() -> int:
    print("=" * 70)
    print("HakusAgent sidecar import smoke test")
    print("=" * 70)
    print(f"Python: {sys.version.split()[0]} @ {sys.executable}")
    print()

    failures: list[tuple[Check, str]] = []
    for check in CHECKS:
        ok, msg = run_one(check)
        flag = "OK " if ok else "FAIL"
        required_tag = "" if check.required else " (optional)"
        print(f"  [{flag}] {check.name:30s}{required_tag}  {msg}")
        if not ok:
            failures.append((check, msg))

    print()
    print("=" * 70)
    if failures:
        print(f"FAILED: {len(failures)} required module(s) could not be imported.")
        print()
        print("These will cause 'No module named xxx' in the bundled exe.")
        print("Fix: add them to hiddenimports in the .spec file, OR add the")
        print("corresponding pip package to pyproject.toml's sidecar deps.")
        print()
        for c, m in failures:
            print(f"  - {c.module}: {m}")
        return 1
    else:
        print("ALL REQUIRED IMPORTS OK. The bundled exe should start cleanly.")
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
