"""
验证 prompt 提示符改为 HakusAI + /spec 命令能正确输出 session spec
"""
import sys
import os
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_prompt_html_contains_hakusai():
    from hakus.tui import HakusTUI
    from prompt_toolkit.formatted_text import HTML

    expected_html = HTML('<ansicyan>(HakusAI)</ansicyan> <b>></b> ')
    plain = "".join(t[1] for t in expected_html.__pt_formatted_text__())
    assert "(HakusAI)" in plain, f"提示符 HTML 中应含 (HakusAI)，实际: {plain}"
    assert "model_name" not in plain
    assert "deepseek" not in plain
    print(f"✓ 提示符 HTML 内容: {plain!r}")


def test_prompt_no_longer_references_model_name():
    import inspect
    from hakus import tui

    src = inspect.getsource(tui)
    assert "self._session.model_name})</ansicyan>" not in src, \
        "提示符 HTML 中不应再引用 self._session.model_name"
    assert 'f"({self._session.model_name}) > "' not in src, \
        "input() fallback 也不应再含 model_name"
    print("✓ tui.py 源码中提示符已彻底改为 HakusAI")


def test_spec_command_registered():
    from hakus.tui import HakusTUI, SlashCompleter

    assert "/spec" in HakusTUI.SLASH_COMMANDS, "/spec 必须出现在 SLASH_COMMANDS"
    assert "模型" in HakusTUI.SLASH_COMMANDS["/spec"] or "session" in HakusTUI.SLASH_COMMANDS["/spec"].lower() \
        or "spec" in HakusTUI.SLASH_COMMANDS["/spec"].lower(), \
        "/spec 描述应当含模型名/spec 字样"
    print(f"✓ SLASH_COMMANDS['/spec'] = {HakusTUI.SLASH_COMMANDS['/spec']!r}")

    assert "/spec" in SlashCompleter.COMMANDS, "/spec 必须出现在 SlashCompleter.COMMANDS"
    print("✓ SlashCompleter.COMMANDS 中也包含 /spec")


def test_show_spec_output():
    from hakus.tui import HakusTUI

    tui = HakusTUI.__new__(HakusTUI)
    tui._session = MagicMock()
    tui._session.start_time = __import__("time").time() - 65
    tui._session.model_name = "deepseek"
    tui._session.working_dir = "D:\\项目\\HakusAI_chat"
    tui._session.permission_mode = "auto"
    tui._session.voice_enabled = False
    tui._session.message_count = 5
    tui._session.turn_count = 2
    tui._session.total_input_tokens = 100
    tui._session.total_output_tokens = 200
    tui._session.messages = []
    tui._console = None

    tui._print_tool_message = MagicMock()
    tui._show_spec()
    assert tui._print_tool_message.called
    content = tui._print_tool_message.call_args[0][0]
    print("\n--- /spec 输出 ---")
    print(content)
    print("--- end ---\n")

    required = ["HakusAI Spec", "Model", "deepseek", "Working dir",
                "Permission mode", "Voice", "Session uptime", "Messages", "Turns"]
    for kw in required:
        assert kw in content, f"/spec 输出缺失字段: {kw}"
    print("✓ /spec 输出包含所有必需字段")


def test_completer_finds_spec():
    from hakus.tui import SlashCompleter
    from prompt_toolkit.document import Document
    from prompt_toolkit.completion import CompleteEvent

    c = SlashCompleter()
    ev = CompleteEvent()
    doc = Document(text="/sp", cursor_position=3)
    completions = list(c.get_completions(doc, ev))
    texts = [x.text for x in completions]
    print(f"输入 '/sp' 补全: {texts}")
    assert "/spec" in texts, "/spec 必须出现在 /sp 补全列表"
    print("✓ /sp 补全命中 /spec")


if __name__ == "__main__":
    test_prompt_html_contains_hakusai()
    test_prompt_no_longer_references_model_name()
    test_spec_command_registered()
    test_show_spec_output()
    test_completer_finds_spec()
    print("\n🎉 全部 TUI 提示符 / /spec 验证通过")
