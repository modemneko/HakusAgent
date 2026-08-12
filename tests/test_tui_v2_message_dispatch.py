"""
TUI v2 — 消息 dispatcher 测试

验证 Message → Widget 的映射:
  - user  → UserBubble
  - assistant → AssistantText
  - tool → ToolResult
  - command → CommandResult
  - error → ErrorBlock
  - >800 字符的 tool result 默认折叠
"""
from __future__ import annotations

import pytest

from hakus.tui_v2.messages import Message
from hakus.tui_v2.widgets.user_bubble import UserBubble
from hakus.tui_v2.widgets.assistant_text import AssistantText
from hakus.tui_v2.widgets.tool_result import ToolResult
from hakus.tui_v2.widgets.command_result import CommandResult
from hakus.tui_v2.widgets.error_block import ErrorBlock


# ===== Message 工厂方法 =====

def test_user_message_factory():
    msg = Message.user("中午好")
    assert msg.role == "user"
    assert msg.content == "中午好"
    assert msg.id  # 自动生成 id


def test_assistant_message_factory():
    msg = Message.assistant("你好!")
    assert msg.role == "assistant"
    assert msg.content == "你好!"


def test_tool_message_factory_basic():
    msg = Message.tool("file_read", {"path": "/tmp/x.txt"}, "文件内容...")
    assert msg.role == "tool"
    assert msg.tool_name == "file_read"
    assert msg.tool_success
    assert not msg.collapsed  # 短结果不折叠


def test_tool_message_factory_long_result_collapses():
    """>800 字符的 tool result 应该默认折叠 — 解决'工具结果展示冗余'."""
    long_result = "x" * 1000
    msg = Message.tool("file_read", {"path": "/tmp/x.txt"}, long_result)
    assert msg.collapsed is True


def test_tool_message_factory_error_state():
    msg = Message.tool("bash", {"cmd": "false"}, "exit code 1", success=False)
    assert msg.is_error is False  # tool_success=False 不一定代表 is_error
    assert msg.tool_success is False


def test_command_message_factory():
    msg = Message.command("help", "# Help")
    assert msg.role == "command"
    assert msg.metadata["cmd"] == "help"


def test_error_message_factory():
    msg = Message.error("出错了")
    assert msg.role == "error"
    assert msg.is_error


# ===== Dispatcher 行为 (单元级, 无需 mount) =====

def test_widget_creation_user():
    """用户消息 → UserBubble — 解决'用户输入回显重复'."""
    msg = Message.user("test")
    widget = UserBubble(msg)
    assert widget._message.content == "test"


def test_widget_creation_assistant():
    msg = Message.assistant("hi")
    widget = AssistantText(msg)
    assert widget._message.content == "hi"


def test_widget_creation_tool():
    msg = Message.tool("ls", {"path": "."}, "file1\nfile2")
    widget = ToolResult(msg)
    assert widget._message.tool_name == "ls"


def test_widget_creation_command():
    msg = Message.command("model", "current: deepseek")
    widget = CommandResult(msg)
    assert widget._message.metadata["cmd"] == "model"


def test_widget_creation_error():
    msg = Message.error("crash")
    widget = ErrorBlock(msg)
    assert widget._message.is_error


# ===== 消息唯一性 (去重) =====

def test_message_ids_unique():
    """每条消息 id 唯一 — MessageList 虚拟化靠 id 做 key."""
    ids = set()
    for _ in range(100):
        msg = Message.user("hi")
        assert msg.id not in ids
        ids.add(msg.id)


def test_message_timestamp_default():
    import time
    before = time.time()
    msg = Message.user("hi")
    after = time.time()
    assert before <= msg.timestamp <= after
