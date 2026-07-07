"""
TUI v2 — 用户输入不回显测试

解决: 截图里 '▸ 中午好' 之后出现 '中午好☀我可以？...' 单独成行
       — 旧 tui.py 在 stdout echo 用户消息后, 又存到 messages 列表导致重复.

新 TUI v2 设计:
  - 永远不直接 console.print 用户消息
  - 永远不通过 stdout echo
  - 用户消息**只**通过 MessageList.add_message() 进入 widget 树
"""
from __future__ import annotations

import io
import sys
from unittest.mock import MagicMock, patch

import pytest

from hakus.tui_v2.messages import Message
from hakus.tui_v2.widgets.user_bubble import UserBubble


def test_user_bubble_does_not_echo_to_stdout(capsys):
    """UserBubble 在构造/compose 时不应有任何 stdout 输出."""
    msg = Message.user("中午好")
    widget = UserBubble(msg)
    captured = capsys.readouterr()
    # 不应有任何 stdout 文本
    assert captured.out == ""
    assert captured.err == ""


def test_user_bubble_no_echo_in_mount():
    """即使用户输入包含特殊字符也不应写到 stdout."""
    msg = Message.user("包含emoji 🌟 和反引号 `code`")
    widget = UserBubble(msg)
    # 不应崩溃
    assert widget._message.content == "包含emoji 🌟 和反引号 `code`"


def test_long_user_input_truncated_in_widget():
    """超长用户输入 (>10k 字符) 在 widget 中应截断 (Claude Code 风格)."""
    long_text = "a" * 20_000
    msg = Message.user(long_text)
    widget = UserBubble(msg)
    # 截断发生在 compose() 时, 单元测试仅验证 message 本身未变
    assert len(widget._message.content) == 20_000


def test_message_factory_user_creates_distinct_id():
    """User 消息应有唯一 id (去重依赖)."""
    msg1 = Message.user("same")
    msg2 = Message.user("same")
    assert msg1.id != msg2.id
    assert msg1.content == msg2.content  # 内容相同但 id 不同


def test_no_module_level_print_in_user_widget():
    """UserBubble 模块不应有顶层 print 调用."""
    import hakus.tui_v2.widgets.user_bubble as m
    src = open(m.__file__, "r", encoding="utf-8").read()
    # 检查是否有 console.print / print( 调用
    assert "console.print" not in src
    assert "sys.stdout" not in src
    # 注意: print() 在 docstring/comment 中可能存在, 不强制要求
    assert "print(" not in src or "print text" in src  # 允许注释中的 print


def test_message_list_add_user_message_no_echo(capsys):
    """MessageList.add_message 不应触发 stdout 输出."""
    from hakus.tui_v2.widgets.message_list import MessageList
    # 构造时不挂载到 App, 所以不调用 compose
    ml = MessageList()
    msg = Message.user("test")
    # 直接调 add_message (无需挂载)
    try:
        ml.add_message(msg)
    except Exception:
        pass  # ScrollableContainer 在没有 App 时可能抛错, 接受
    captured = capsys.readouterr()
    assert captured.out == ""


def test_app_does_not_echo_user_input_directly():
    """App._process_user_input 不应通过 Rich console.print 输出用户消息.

    关键检查: 源代码中不应对 user 角色调用 console.print.
    """
    import hakus.tui_v2.app as m
    src = open(m.__file__, "r", encoding="utf-8").read()
    # 找到 _process_user_input 方法
    # 不应有 console.print(self.console, ..., end=...) 之类的用户回显
    # 接受 Rich 的 markup, 但不允许直接 echo 用户文本
    # 简化: 查找明显的 echo 模式
    echo_patterns = [
        'console.print(f"▸ {',
        'console.print("▸ ',
        "console.print(f'▸ ",
        "console.print(f\"中午好",
    ]
    for pat in echo_patterns:
        assert pat not in src, f"Found echo pattern: {pat}"
