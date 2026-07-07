"""
验证 SlashCompleter 在输入 / 时不再抛 AttributeError。
直接调用 get_completions() 并消费所有 yield 的 Completion。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_standalone():
    from hakus.tui import SlashCompleter
    from prompt_toolkit.document import Document
    from prompt_toolkit.completion import CompleteEvent

    completer = SlashCompleter()
    ev = CompleteEvent()
    print("--- 测试 1: 输入 '/' 触发补全 ---")
    doc = Document(text="/", cursor_position=1)
    completions = list(completer.get_completions(doc, ev))
    print(f"  返回 {len(completions)} 个补全项")
    assert len(completions) > 0, "应当有补全项"
    print(f"  示例: {[c.text for c in completions[:5]]}")

    print("--- 测试 2: 输入 '/mod' 触发补全 ---")
    doc = Document(text="/mod", cursor_position=4)
    completions = list(completer.get_completions(doc, ev))
    print(f"  返回 {len(completions)} 个补全项")
    print(f"  内容: {[c.text for c in completions]}")
    assert any("/model" in c.text for c in completions), \
        "应补全到 /model"

    print("--- 测试 3: 输入 '/model de' 触发模型补全 ---")
    doc = Document(text="/model de", cursor_position=len("/model de"))
    completions = list(completer.get_completions(doc, ev))
    print(f"  返回 {len(completions)} 个补全项")
    print(f"  内容: {[c.text for c in completions]}")
    assert any("deepseek" in c.text for c in completions), \
        "应补全到 deepseek"

    print("--- 测试 4: 输入 '/permission a' 触发模式补全 ---")
    doc = Document(text="/permission a", cursor_position=len("/permission a"))
    completions = list(completer.get_completions(doc, ev))
    print(f"  返回 {len(completions)} 个补全项")
    print(f"  内容: {[c.text for c in completions]}")
    assert any("auto" in c.text for c in completions), \
        "应补全到 auto"

    print("✅ SlashCompleter 全部补全路径正常")


def test_with_tui_sync():
    """当 SlashCompleter 由 HakusTUI 注入时，应能同步 SLASH_COMMANDS"""
    from hakus.tui import SlashCompleter, HakusTUI
    from prompt_toolkit.document import Document
    from prompt_toolkit.completion import CompleteEvent
    from unittest.mock import MagicMock

    tui = MagicMock(spec=HakusTUI)
    tui.SLASH_COMMANDS = {
        "/foo": "foo 命令",
        "/bar": "bar 命令",
        "/model": "模型切换",
    }
    completer = SlashCompleter(tui)
    print(f"--- 测试 5: 注入 TUI 后命令数: {len(completer.COMMANDS)} ---")
    assert "/foo" in completer.COMMANDS
    assert "/model" in completer.COMMANDS
    print("  ✓ COMMANDS 已从 TUI 同步")

    ev = CompleteEvent()
    doc = Document(text="/f", cursor_position=len("/f"))
    completions = list(completer.get_completions(doc, ev))
    print(f"  输入 '/f' 补全: {[c.text for c in completions]}")
    assert any(c.text == "/foo" for c in completions)
    print("✅ TUI 同步补全正常")


if __name__ == "__main__":
    test_standalone()
    test_with_tui_sync()
    print("\n🎉 全部 SlashCompleter 验证通过")
