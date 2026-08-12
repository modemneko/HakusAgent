"""
测试 TUI 简化的斜杠命令 (移除 /export, /review, /orchestrate)
Agent 模式为默认
"""
import pytest
from prompt_toolkit.document import Document
from prompt_toolkit.completion import CompleteEvent

from hakus.tui import HakusTUI, SlashCompleter


class TestSimplifiedCommands:
    """验证简化后的 SLASH_COMMANDS 列表."""

    def test_export_removed(self):
        """用户要求: 移除 /export 命令."""
        assert "/export" not in HakusTUI.SLASH_COMMANDS, \
            "/export 命令应已移除"

    def test_review_removed(self):
        """用户要求: 移除 /review 命令."""
        assert "/review" not in HakusTUI.SLASH_COMMANDS, \
            "/review 命令应已移除"

    def test_orchestrate_removed(self):
        """用户要求: 移除 /orchestrate 命令 (agent 自动调度)."""
        assert "/orchestrate" not in HakusTUI.SLASH_COMMANDS, \
            "/orchestrate 命令应已移除"

    def test_essential_commands_present(self):
        """核心命令应保留 (使用 SLASH_COMMANDS 实际的 key 格式)."""
        essential_keys = [
            "/help", "/model <name>", "/permission <mode>", "/clear",
            "/plan", "/plan exit", "/approve", "/reject [reason]",
            "/todos", "/git", "/diff", "/tree [path]",
            "/status", "/exit",
        ]
        for cmd in essential_keys:
            assert cmd in HakusTUI.SLASH_COMMANDS, f"{cmd} 不应被移除"

    def test_db_command_present(self):
        """/db 主命令或子命令应保留 (Navicat 风格)."""
        # /db 在 SlashCompleter.COMMANDS 中
        all_keys = list(HakusTUI.SLASH_COMMANDS.keys()) + list(SlashCompleter.COMMANDS.keys())
        db_keys = [k for k in all_keys if k.startswith("/db")]
        assert len(db_keys) > 0, "/db 命令族应保留"
        assert any("connect" in k for k in db_keys)
        assert any("tables" in k for k in db_keys)


class TestCompleterConsistency:
    """验证补全器与 SLASH_COMMANDS 同步."""

    def test_completer_excludes_removed(self):
        c = SlashCompleter()
        ev = CompleteEvent()
        # 移除的命令不应被补全 (使用前缀查询, 不传完整 key)
        for removed in ("/export", "/review", "/orchestrate"):
            doc = Document(text=removed, cursor_position=len(removed))
            completions = [x.text for x in c.get_completions(doc, ev)]
            # 移除的命令不应被补全 (前缀匹配)
            matches = [c for c in completions if c.lower().startswith(removed.lower())]
            assert len(matches) == 0, \
                f"补全器仍在补全已移除的命令: {removed} -> {matches}"

    def test_completer_includes_essential(self):
        c = SlashCompleter()
        ev = CompleteEvent()
        # 测试核心命令的前缀补全
        test_cases = [
            ("/he", "/help"),
            ("/mo", "/model"),  # 可能是 /model <name>
            ("/pl", "/plan"),
            ("/ex", "/exit"),
        ]
        for prefix, expected_full in test_cases:
            doc = Document(text=prefix, cursor_position=len(prefix))
            completions = [x.text for x in c.get_completions(doc, ev)]
            assert any(c.startswith(expected_full) for c in completions), \
                f"补全器丢失核心命令: {prefix} -> {expected_full}"


class TestDefaultAgentMode:
    """验证 Agent 模式为默认 (无需切换)."""

    def test_welcome_banner_mentions_agent_mode(self):
        import inspect
        from hakus import tui
        src = inspect.getsource(tui)
        # 欢迎语应说明 Agent 是默认模式
        assert "Agent" in tui.HakusTUI._render_welcome.__code__.co_consts[0:50] or \
               "Agent" in inspect.getsource(tui.HakusTUI._render_welcome), \
            "欢迎面板应说明 Agent 是默认模式"

    def test_process_user_input_dispatches_to_agent(self):
        """默认情况下, _process_user_input 应直接走 agent 流."""
        import inspect
        from hakus import tui
        src = inspect.getsource(tui.HakusTUI._process_user_input)
        # 应调用 run_turn 协议 (新版事件流接口), 直接或通过 _process_stream
        assert "run_turn" in src or "_process_stream" in src, (
            "默认输入处理应走 run_turn 事件流 (直接调或通过 _process_stream)"
        )
        # 不应有特殊模式判断
        assert "mode" not in src.lower() or "plan_pending" in src.lower()
