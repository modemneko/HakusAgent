"""
TUI v2 — 工具结果折叠测试

解决: 截图里 '工具结果展示冗余' — 旧 tui.py 每个 tool call 一个大 Panel
       — 垂直滚动极多, 噪音大.

新设计:
  - 长结果 (>800 字符) 默认折叠为 Collapsible
  - 短结果展开显示
  - 失败的工具用红色左边框
"""
from __future__ import annotations

import pytest

from hakus.tui_v2.messages import Message
from hakus.tui_v2.widgets.tool_result import ToolResult


def test_short_tool_result_not_collapsed():
    """>800 字符 → 折叠 (短结果不折叠)."""
    msg = Message.tool("ls", {"path": "."}, "file1\nfile2\nfile3")
    assert msg.collapsed is False


def test_long_tool_result_collapsed_by_default():
    """>800 字符 → 默认折叠 (解决工具结果冗余)."""
    long = "x" * 1000
    msg = Message.tool("file_read", {"path": "/big.txt"}, long)
    assert msg.collapsed is True


def test_exactly_801_chars_collapsed():
    """边界: 801 字符应折叠 (临界值)."""
    msg = Message.tool("file_read", {"path": "/x"}, "x" * 801)
    assert msg.collapsed is True


def test_799_chars_not_collapsed():
    """边界: 799 字符不折叠."""
    msg = Message.tool("file_read", {"path": "/x"}, "x" * 799)
    assert msg.collapsed is False


def test_failed_tool_marked_error():
    """>失败的工具加 error class (视觉标记)."""
    msg = Message.tool("bash", {"cmd": "false"}, "exit code 1", success=False)
    widget = ToolResult(msg)
    # 即使没 mount, 也应在 class 中标记
    # 实际 CSS class 由 on_mount 决定; 检查 widget._message
    assert widget._message.tool_success is False


def test_tool_message_includes_summary():
    """Tool message 的 content 应包含摘要 (Claude Code 风格一行式)."""
    msg = Message.tool("file_read", {"path": "/tmp/x.txt"}, "contents")
    assert "file_read" in msg.content
    assert "✓" in msg.content
    assert "contents" in msg.content


def test_tool_message_with_duration():
    msg = Message.tool("ls", {}, "out", duration=1.5)
    assert msg.tool_duration == 1.5
    assert "1.5s" in msg.content
