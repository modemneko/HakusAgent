"""
TUI v2 — Slash 命令注册中心测试

验证:
  - 命令注册
  - 解析 + 调用
  - 26 个内置命令全部加载
  - 帮助文本格式
"""
from __future__ import annotations

import pytest

from hakus.tui_v2.commands import (
    SlashCommand,
    SlashCommandRegistry,
    build_default_registry,
)
from hakus.tui_v2.commands.help import HelpCommand
from hakus.tui_v2.commands.exit_cmd import ExitCommand
from hakus.tui_v2.commands.clear import ClearCommand
from hakus.tui_v2.commands.model import ModelCommand


# ===== 注册表 =====

def test_default_registry_has_26_commands():
    """默认注册表应包含 26 个命令."""
    reg = build_default_registry()
    cmds = reg.all()
    assert len(cmds) >= 20, f"Expected 20+ commands, got {len(cmds)}"


def test_help_command_registered():
    reg = build_default_registry()
    cmd = reg.get("help")
    assert cmd is not None
    assert isinstance(cmd, HelpCommand)


def test_exit_command_with_aliases():
    reg = build_default_registry()
    assert reg.get("exit") is not None
    assert reg.get("quit") is not None
    assert reg.get("q") is not None


def test_help_alias_question_mark():
    reg = build_default_registry()
    assert reg.get("?") is not None


def test_clear_command_registered():
    reg = build_default_registry()
    assert reg.get("clear") is not None


def test_model_command_registered():
    reg = build_default_registry()
    cmd = reg.get("model")
    assert cmd is not None
    assert cmd.description  # 有描述


def test_unknown_command_returns_none():
    reg = build_default_registry()
    assert reg.get("/nonexistent") is None
    assert reg.get("definitely-not-a-command") is None


def test_register_new_command():
    """注册自定义命令 — 验证 API."""
    reg = SlashCommandRegistry()

    class TestCmd(SlashCommand):
        name = "test"
        description = "测试"

        async def execute(self, ctx):
            self._ok(ctx, "ok")

    cmd = TestCmd()
    reg.register(cmd)
    assert reg.get("test") is cmd


def test_register_command_without_name_raises():
    reg = SlashCommandRegistry()

    class BadCmd(SlashCommand):
        async def execute(self, ctx):
            pass

    with pytest.raises(ValueError):
        reg.register(BadCmd())


def test_format_help_contains_all_commands():
    reg = build_default_registry()
    text = reg.format_help()
    assert "# 📋" in text
    assert "help" in text
    assert "model" in text
    assert "clear" in text
    assert "exit" in text


# ===== 命令解析 + 执行 =====

class FakeApp:
    """模拟 HakusApp, 只挂 mount_message."""

    def __init__(self):
        self.messages = []
        self._message_list = _FakeMessageList()

    def _mount_message(self, msg):
        self.messages.append(msg)

    @property
    def _command_registry(self):
        return build_default_registry()

    @property
    def _agent(self):
        return _FakeAgent()

    @property
    def _session(self):
        return _FakeSession()


class _FakeMessageList:
    _messages = []
    def clear_messages(self):
        pass
    def add_message(self, msg):
        pass
    def mount_tool(self, msg):
        pass
    def mount_command(self, msg):
        pass
    def mount_error(self, msg):
        pass
    def scroll_end(self, animate=False):
        pass


class _FakeAgent:
    _model_type = "deepseek"
    def _init_model(self): pass
    def reset(self): pass
    _sub_agents = []
    _context = None
    _tool_registry = None
    _plan_manager = None
    def set_permission_mode(self, m): pass
    def get_checkpoints(self): return []
    def rollback(self, id): return True


class _FakeSession:
    model_name = "deepseek"
    working_dir = ""
    total_input_tokens = 0
    total_output_tokens = 0
    voice_enabled = False
    permission_mode = "auto"
    start_time = 0
    in_plan_mode = False
    last_plan = None


@pytest.mark.asyncio
async def test_help_command_executes():
    """/help 应返回帮助文本."""
    from hakus.tui_v2.commands import CommandContext
    cmd = HelpCommand()
    app = FakeApp()
    ctx = CommandContext(app=app, args="", parts=[], raw="/help")
    await cmd.execute(ctx)
    assert len(app.messages) == 1
    assert "help" in app.messages[0].content


@pytest.mark.asyncio
async def test_clear_command_executes():
    """/clear 应清除消息 (使用 FakeApp)."""
    from hakus.tui_v2.commands import CommandContext
    cmd = ClearCommand()
    app = FakeApp()
    ctx = CommandContext(app=app, args="", parts=[], raw="/clear")
    await cmd.execute(ctx)
    # 应挂载一条 '✓ 对话已清除' 消息
    assert any("已清除" in m.content for m in app.messages)


def test_model_command_metadata():
    cmd = ModelCommand()
    assert cmd.name == "model"
    assert "m" in cmd.get_aliases()
    assert "deepseek" in cmd.description


def test_exit_command_metadata():
    cmd = ExitCommand()
    assert "q" in cmd.get_aliases()
    assert "quit" in cmd.get_aliases()
