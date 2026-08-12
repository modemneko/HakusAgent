"""
Regression test: ensure _process_stream() does NOT use Rich Live in a way
that breaks Windows console rendering. On Windows, Rich's Live display
falls back to appending content instead of redrawing in place, which
caused the "▌ Streaming…" line to be printed dozens of times during
a single stream.

The fix: _process_stream() should call `console.print` with `end=""` on
each token, not `live.update(...)` inside a `with Live(...)` block.
"""
import asyncio
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _read_tui_source() -> str:
    tui_path = ROOT / "hakus" / "tui.py"
    return tui_path.read_text(encoding="utf-8")


def test_process_stream_does_not_use_live_context():
    """_process_stream must not use `with Live(...)` for token streaming.

    Using Rich's Live display on Windows appends each update as a new
    line, causing "▌ Streaming…" to repeat dozens of times.
    """
    src = _read_tui_source()

    # Find the _process_stream function
    m = re.search(r"async def _process_stream.*?(?=\n    async def |\n    def |\Z)",
                  src, re.DOTALL)
    assert m, "_process_stream not found"
    body = m.group(0)

    # No `with Live(` should appear inside the streaming loop
    # (Live may still be used elsewhere — but not for the token stream)
    assert "with Live(" not in body, (
        "_process_stream must not use Rich Live — on Windows it appends "
        "each update instead of redrawing, causing the '▌ Streaming…' "
        "line to be printed dozens of times. Use direct console.print() "
        "with end='' instead."
    )


def test_process_stream_uses_throttled_console_print():
    """Tokens should be printed with end='' via throttled console.print.

    codex-style refactor: the legacy token-based path was replaced
    by an event-driven loop. ``_process_stream`` now iterates
    ``agent.run_turn`` and prints ``event.text`` throttled on each
    :class:`TextDelta` event.
    """
    src = _read_tui_source()
    m = re.search(r"async def _process_stream.*?(?=\n    async def |\n    def |\Z)",
                  src, re.DOTALL)
    assert m
    body = m.group(0)
    # The streaming path now consumes TextDelta events; the print
    # call should pass `end=""` to keep tokens on one line.
    assert 'end=""' in body or "end=''" in body, (
        "Expected throttled `console.print(event.text, end='')` for streaming"
    )
    assert "TextDelta" in body, (
        "Expected streaming to dispatch on TextDelta events (codex-style refactor)"
    )


def test_process_stream_prints_final_markdown_panel():
    """After streaming, a final Markdown panel must be printed so the
    user sees the fully-rendered result (not just raw text)."""
    src = _read_tui_source()
    m = re.search(r"async def _process_stream.*?(?=\n    async def |\n    def |\Z)",
                  src, re.DOTALL)
    assert m
    body = m.group(0)
    assert "Markdown(full_response" in body, (
        "Expected final Markdown panel render after streaming"
    )


def test_no_live_update_call_in_streaming():
    """live.update() is the symptom of the bug — must not appear."""
    src = _read_tui_source()
    m = re.search(r"async def _process_stream.*?(?=\n    async def |\n    def |\Z)",
                  src, re.DOTALL)
    assert m
    body = m.group(0)
    assert "live.update" not in body


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
