"""
Regression tests for the Claude Code-style optimizations applied to HakusAI:
  1. Tool result collapsing (truncate long results in display)
  2. /verify and /btw slash commands
  3. /context command shows usage breakdown
  4. Parallel tool execution for safe batches
  5. Context window progress bar in status bar
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


# ============================================================
# 1. Tool result collapsing
# ============================================================
class TestToolResultCollapsing:
    def test_collapse_threshold_defined(self):
        """A COLLAPSE_THRESHOLD must be present to gate long-result collapsing."""
        src = _read("hakus/tui.py")
        m = re.search(r"def _display_tool_results.*?(?=\n    async def |\n    def |\Z)",
                      src, re.DOTALL)
        assert m
        body = m.group(0)
        assert "COLLAPSE_THRESHOLD" in body, (
            "Expected COLLAPSE_THRESHOLD constant for tool result collapsing"
        )

    def test_full_content_still_kept_in_session(self):
        """The model must still receive the full tool result via session
        messages — only the terminal display is collapsed."""
        src = _read("hakus/tui.py")
        m = re.search(r"def _display_tool_results.*?(?=\n    async def |\n    def |\Z)",
                      src, re.DOTALL)
        body = m.group(0)
        # Both full message append and a (possibly) truncated display must exist
        assert "self._session.messages.append" in body
        assert "self._print_tool_message" in body

    def test_collapse_message_includes_omitted_count(self):
        """When collapsing, the display should mention how many lines were omitted."""
        src = _read("hakus/tui.py")
        m = re.search(r"def _display_tool_results.*?(?=\n    async def |\n    def |\Z)",
                      src, re.DOTALL)
        body = m.group(0)
        assert "已折叠" in body or "omitted" in body.lower() or "折叠" in body, (
            "Collapsed display should show how many lines were omitted"
        )


# ============================================================
# 2. /verify and /btw slash commands
# ============================================================
class TestVerifyAndBtwCommands:
    def test_verify_in_commands(self):
        src = _read("hakus/tui.py")
        assert '"/verify"' in src, "Missing /verify in SLASH_COMMANDS"

    def test_btw_in_commands(self):
        src = _read("hakus/tui.py")
        assert '"/btw' in src, "Missing /btw in SLASH_COMMANDS"

    def test_verify_handled_in_handler(self):
        src = _read("hakus/tui.py")
        m = re.search(r"async def _handle_slash_command.*?(?=\n    async def |\n    def |\Z)",
                      src, re.DOTALL)
        assert m
        body = m.group(0)
        assert 'cmd == "/verify"' in body
        assert "PASS" in body or "pass" in body or "检查" in body, (
            "/verify handler should ask the model to PASS/FAIL check"
        )

    def test_btw_handled_in_handler(self):
        src = _read("hakus/tui.py")
        m = re.search(r"async def _handle_slash_command.*?(?=\n    async def |\n    def |\Z)",
                      src, re.DOTALL)
        assert m
        body = m.group(0)
        assert 'cmd == "/btw"' in body
        assert "旁注" in body or "btw" in body.lower(), (
            "/btw handler should mark the note as a side note"
        )


# ============================================================
# 3. /context command
# ============================================================
class TestContextCommand:
    def test_context_in_commands(self):
        src = _read("hakus/tui.py")
        assert '"/context"' in src, "Missing /context in SLASH_COMMANDS"

    def test_show_context_window_method_exists(self):
        src = _read("hakus/tui.py")
        assert "def _show_context_window" in src, (
            "Missing _show_context_window implementation"
        )

    def test_show_context_window_includes_breakdown(self):
        src = _read("hakus/tui.py")
        m = re.search(r"def _show_context_window.*?(?=\n    def |\Z)",
                      src, re.DOTALL)
        assert m
        body = m.group(0)
        for kw in ("系统提示", "对话历史", "工具结果", "budget"):
            assert kw in body or kw.lower() in body, (
                f"/context breakdown should include {kw!r}"
            )


# ============================================================
# 4. Parallel tool execution
# ============================================================
class TestParallelToolExecution:
    def test_parallel_branch_in_run_tool_loop(self):
        src = _read("hakus/agent.py")
        m = re.search(r"async def _run_tool_loop.*?(?=\n    async def |\n    def |\Z)",
                      src, re.DOTALL)
        assert m
        body = m.group(0)
        assert "asyncio.gather" in body, (
            "Parallel tool execution must use asyncio.gather"
        )
        assert "is_concurrency_safe" in body, (
            "Parallel branch must check concurrency safety per tool"
        )

    def test_falls_back_to_sequential_for_unsafe_tools(self):
        src = _read("hakus/agent.py")
        m = re.search(r"async def _run_tool_loop.*?(?=\n    async def |\n    def |\Z)",
                      src, re.DOTALL)
        body = m.group(0)
        # Both paths must exist. The codex-style refactor renamed the
        # inner loop variable to ``current_tool_calls`` (so we can
        # reload it at each round), so accept either spelling.
        assert (
            "if len(tool_calls) > 1 and all_safe" in body
            or "if len(current_tool_calls) > 1 and all_safe" in body
        ), (
            "Sequential fallback condition missing"
        )


# ============================================================
# 5. Status bar context window
# ============================================================
class TestStatusBarContext:
    def test_status_bar_computes_context_pct(self):
        src = _read("hakus/tui.py")
        m = re.search(r"def _render_status_bar.*?(?=\n    def |\Z)", src, re.DOTALL)
        assert m
        body = m.group(0)
        assert "_total_estimated_tokens" in body, (
            "Status bar should query ContextManager for token usage"
        )
        assert "ctx_pct" in body, "Status bar should compute percentage"
        assert "agent_ctx" in body, "Status bar should reach into agent context"

    def test_status_bar_color_thresholds(self):
        """Bar color should change at 50% and 75% thresholds."""
        src = _read("hakus/tui.py")
        m = re.search(r"def _render_status_bar.*?(?=\n    def |\Z)", src, re.DOTALL)
        body = m.group(0)
        assert ">= 75" in body, "Expected red threshold at >= 75%"
        assert ">= 50" in body, "Expected yellow threshold at >= 50%"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
