#!/usr/bin/env bash
# =====================================================================
# Build the HakusAI Python server as a PyInstaller sidecar bundle.
#
# Output: sidecar/dist/hakusai-server{.exe,_onefile.exe,bin}
#
# The resulting single-file executable can be invoked by Electron's
# sidecar API to start the HakusAI backend alongside the desktop client.
#
# Usage:
#   bash scripts/build-sidecar.sh        # build for current platform
#   bash scripts/build-sidecar.sh --clean  # remove build cache first
#
# Requirements:
#   - Python 3.10+
#   - PyInstaller:  pip install pyinstaller
#   - HakusAI deps: pip install -r requirements.txt
# =====================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLIENT_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(dirname "$(dirname "$CLIENT_DIR")")"
SIDECAR_DIR="$CLIENT_DIR/sidecar"
DIST_DIR="$SIDECAR_DIR/dist"
WORK_DIR="$SIDECAR_DIR/build"

# Parse args
CLEAN=0
for arg in "$@"; do
  case "$arg" in
    --clean) CLEAN=1 ;;
    *) echo "Unknown argument: $arg"; exit 1 ;;
  esac
done

echo "============================================"
echo "  HakusAI Server Sidecar Builder"
echo "============================================"
echo "Repo root:   $REPO_ROOT"
echo "Sidecar dir: $SIDECAR_DIR"
echo "Output dir:  $DIST_DIR"
echo ""

# Sanity checks
if [[ ! -d "$REPO_ROOT/src/hakusai_server" ]]; then
  echo "ERROR: Cannot find $REPO_ROOT/src/hakusai_server"
  echo "       Run this script from the HakusAgent repo (or frontend/client/scripts/)."
  exit 1
fi

if ! command -v pyinstaller &>/dev/null; then
  echo "ERROR: pyinstaller not found in PATH."
  echo "       Install with:  pip install pyinstaller"
  exit 1
fi

# Prepare sidecar directory
mkdir -p "$SIDECAR_DIR" "$WORK_DIR"

if [[ "$CLEAN" -eq 1 ]]; then
  echo "Cleaning previous build..."
  rm -rf "$DIST_DIR" "$WORK_DIR"
fi

# =====================================================================
# Convert paths to platform-native form.
#
# On Git Bash for Windows, $REPO_ROOT etc. look like "/d/a/HakusAgent/..."
# which native Python (and thus PyInstaller) CANNOT resolve — it interprets
# the leading "/" as the current drive's root, not as a MSYS mount point.
#
# `cygpath -m` converts to mixed-mode Windows paths (forward slashes, drive
# letter) like "D:/a/HakusAgent/...", which Python handles correctly on all
# platforms. On Linux/macOS, cygpath is absent so we skip the conversion.
# =====================================================================
if command -v cygpath &>/dev/null; then
  echo "[sidecar] Detected Git Bash/MSYS — converting paths to Windows form"
  REPO_ROOT=$(cygpath -m "$REPO_ROOT")
  SIDECAR_DIR=$(cygpath -m "$SIDECAR_DIR")
  CLIENT_DIR=$(cygpath -m "$CLIENT_DIR")
  # WORK_DIR and DIST_DIR are only used by PyInstaller CLI args (which are
  # invoked from bash, so bash handles them), but convert them too for safety.
  WORK_DIR=$(cygpath -m "$WORK_DIR")
  DIST_DIR=$(cygpath -m "$DIST_DIR")
fi

# Write the sidecar entry-point script
cat > "$SIDECAR_DIR/hakusai_server_entry.py" <<'PYEOF'
"""Sidecar entry point for HakusAI server.

This script launches the FastAPI server with sensible defaults:
- Host: 127.0.0.1 (loopback only, for security)
- Port: 8080 (or first available)
- No SPA mount (the client provides its own UI)
"""
import os
import sys
import socket
import logging

# When running from PyInstaller bundle, the bundled deps are in sys.path
if getattr(sys, "frozen", False):
    bundle_dir = os.path.dirname(sys.executable)
    sys.path.insert(0, bundle_dir)

# Add the repo root to sys.path so `hakusai_server` and `hakusai_core` are importable
# In a frozen bundle, these modules are bundled by PyInstaller
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def find_free_port(start: int = 8080, attempts: int = 10) -> int:
    """Find the first free port starting from `start`."""
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port found in range {start}-{start + attempts}")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logger = logging.getLogger("hakusai.sidecar")

    port = find_free_port(int(os.environ.get("HAKUSAI_PORT", "8080")))
    logger.info("Starting HakusAI server on http://127.0.0.1:%d", port)

    # Pre-flight: try importing the server module BEFORE printing HAKUSAI_PORT.
    # If imports fail (e.g. PyInstaller missed a hidden_import), we want the
    # traceback to be the LAST thing on stderr, not a misleading "started on port" message.
    try:
        logger.info("Pre-flight import check...")
        from hakusai_server.server import HakusAIServer
        logger.info("Pre-flight OK")
    except Exception as e:
        logger.exception("Pre-flight import failed: %s", e)
        # Still print HAKUSAI_PORT so Electron's sidecar.ts can parse it
        # (it will then time out on /health and surface the error to the UI)
        print(f"HAKUSAI_PORT={port}", flush=True)
        sys.exit(1)

    # Print the chosen port to stdout so the Electron main process can parse it
    print(f"HAKUSAI_PORT={port}", flush=True)

    try:
        server = HakusAIServer()
        # Force loopback-only binding for security when bundled
        if hasattr(server, "config") and hasattr(server.config, "server"):
            server.config.server.host = "127.0.0.1"
            server.config.server.port = port
        server.run()
    except Exception as e:
        logger.exception("HakusAI server failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
PYEOF

# Write the PyInstaller spec file
# NOTE: All paths are wrapped in os.path.abspath() so PyInstaller (which is
# native Python and does NOT understand Git Bash's /d/a/... Unix-style paths
# on Windows) can resolve them correctly across platforms.
cat > "$SIDECAR_DIR/hakusai_server.spec" <<SPECEOF
# PyInstaller spec for HakusAI server sidecar
# Auto-generated by scripts/build-sidecar.sh

import os

block_cipher = None

# Resolve all paths through os.path.abspath so they become platform-native:
#   - On Linux/macOS: /home/runner/work/... or /Users/runner/work/...
#   - On Windows:     D:\\a\\HakusAgent\\HakusAgent\\...
# This is critical because Git Bash on Windows uses /d/a/... which native
# Python (and thus PyInstaller) cannot resolve.
REPO_ROOT = os.path.abspath("$REPO_ROOT")
SIDECAR_DIR = os.path.abspath("$SIDECAR_DIR")
CLIENT_DIR = os.path.abspath("$CLIENT_DIR")

# Bundle the entire src/ directory as data so hakusai_server / hakusai_core
# modules can be imported at runtime.
datas = [
    (os.path.join(REPO_ROOT, "src"), "src"),
    (os.path.join(REPO_ROOT, "configs"), "configs"),
    (os.path.join(REPO_ROOT, "hakus"), "hakus"),
    (os.path.join(REPO_ROOT, "models"), "models"),
    (os.path.join(REPO_ROOT, "utils"), "utils"),
    (os.path.join(REPO_ROOT, "voice"), "voice"),
    (os.path.join(REPO_ROOT, "tts"), "tts"),
    (os.path.join(REPO_ROOT, "config.yaml"), "."),
]
# Filter out paths that don't exist (some dirs may be absent on certain setups)
datas = [(src, dst) for src, dst in datas if os.path.exists(src)]

hidden_imports = [
    "hakusai_server.server",
    "hakusai_server.vtuber_websocket",
    "hakusai_core.config",
    "hakusai_core.models",
    "hakusai_core.agent",
    "hakusai_core.memory",
    "hakusai_core.voice.tts",
    "hakusai_core.utils.events",
    # watchdog — used by hakusai_core.config.manager for hot-reload.
    # Must be listed here because PyInstaller's static analysis can't
    # trace the `from watchdog.observers import Observer` dynamic import.
    "watchdog",
    "watchdog.observers",
    "watchdog.observers.polling",
    "watchdog.events",
    "watchdog.utils",
    "watchdog.utils.bricks",
    "watchdog.utils.delayed_queue",
    "watchdog.utils.dirsnapshot",
    "watchdog.utils.platform",
    "watchdog.utils.patterns",
    # uvicorn extras — without these, uvicorn falls back to slow asyncio loop
    "uvicorn.logging",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.wsproto_impl",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    # FastAPI / Starlette / Pydantic internals commonly missed
    "fastapi",
    "fastapi.responses",
    "fastapi.middleware",
    "fastapi.middleware.cors",
    "fastapi.staticfiles",
    "starlette.responses",
    "starlette.middleware",
    "starlette.middleware.cors",
    "starlette.staticfiles",
    "pydantic",
    "pydantic._internal._core_utils",
    # YAML config loader
    "yaml",
    # multipart form parsing (FastAPI File uploads)
    "multipart",
    # Python typing / email / etc. sometimes missed
    "email.utils",
    "email.message",
]

a = Analysis(
    [os.path.join(SIDECAR_DIR, "hakusai_server_entry.py")],
    pathex=[REPO_ROOT, os.path.join(REPO_ROOT, "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="hakusai-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=True,
    icon=os.path.join(CLIENT_DIR, "build-resources", "icon.png"),
)

SPECEOF

echo ""
echo "==> Running PyInstaller..."
echo ""

cd "$SIDECAR_DIR"
pyinstaller hakusai_server.spec \
  --distpath "$DIST_DIR" \
  --workpath "$WORK_DIR" \
  --noconfirm \
  --clean

echo ""
echo "============================================"
echo "  Sidecar build complete!"
echo "============================================"
echo "Output:"
ls -la "$DIST_DIR/"
echo ""
echo "Next step: run 'npm run dist' to package the Electron app with sidecar bundled."
