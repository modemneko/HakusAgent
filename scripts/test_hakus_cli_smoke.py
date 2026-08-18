"""HakusCLI smoke tests — 不启动 TUI, 仅验证核心模块可导入和组合.

运行:
    python -m pytest scripts/test_hakus_cli_smoke.py -v
或直接:
    python scripts/test_hakus_cli_smoke.py
"""
from __future__ import annotations

import os
import sys
import traceback


def _check(name: str, fn) -> bool:
    try:
        fn()
        print(f"  ✓ {name}")
        return True
    except Exception as e:
        print(f"  ✗ {name}: {e}")
        traceback.print_exc()
        return False


def test_imports() -> None:
    """所有关键模块可导入."""
    from hakus.cli import HakusCLI
    from hakus.cli.app import HakusCLI as App
    from hakus.cli.session import CLISession, TurnStats
    from hakus.cli.commands import register_builtin, parse, all_commands, lookup
    from hakus.cli.theme import THEMES, get_theme, to_color_system
    from hakus.cli.widgets.composer import Composer
    from hakus.cli.widgets.conversation import ConversationView
    from hakus.cli.widgets.status_bar import StatusBar
    from hakus.cli.widgets.slash_picker import SlashPicker
    from hakus.entry import main, _normalize_effort
    assert HakusCLI is App


def test_app_instantiation() -> None:
    """App 可以实例化."""
    from hakus.cli import HakusCLI
    app = HakusCLI()
    assert app.session.run_mode == "swift"
    assert app.session.reasoning_effort is None
    assert app.theme_name == "dark"


def test_app_instantiation_code_mode() -> None:
    """App 可以 Code 模式实例化."""
    from hakus.cli import HakusCLI
    app = HakusCLI(run_mode="deep", reasoning_effort="high", theme="light")
    assert app.session.run_mode == "deep"
    assert app.session.reasoning_effort == "high"
    assert app.theme_name == "light"


def test_commands_registered() -> None:
    """内置命令全部注册."""
    from hakus.cli.commands import register_builtin, all_commands
    register_builtin()
    names = {c.name for c in all_commands()}
    expected = {"help", "clear", "exit", "mode", "effort", "model", "theme", "tools", "about", "compact"}
    missing = expected - names
    assert not missing, f"缺少命令: {missing}"


def test_command_aliases() -> None:
    """别名正常解析."""
    from hakus.cli.commands import register_builtin, lookup
    register_builtin()
    assert lookup("quit").name == "exit"
    assert lookup("q").name == "exit"
    assert lookup("?").name == "help"
    assert lookup("cls").name == "clear"
    assert lookup("think").name == "effort"
    assert lookup("ls").name == "tools"
    assert lookup("v").name == "about"
    assert lookup("version").name == "about"


def test_parse_command() -> None:
    """/cmd args 解析正确."""
    from hakus.cli.commands import register_builtin, parse
    register_builtin()
    cmd, args = parse("/help")
    assert cmd is not None and cmd.name == "help"
    assert args == ""

    cmd, args = parse("/mode work")
    assert cmd is not None and cmd.name == "mode"
    assert args == "work"

    cmd, args = parse("/effort ultra")
    assert cmd is not None and cmd.name == "effort"
    assert args == "ultra"

    cmd, args = parse("hello world")
    assert cmd is None
    assert args == "hello world"


def test_themes() -> None:
    """三套主题存在且可取."""
    from hakus.cli.theme import THEMES, get_theme
    assert set(THEMES.keys()) == {"dark", "light", "auto"}
    dark = get_theme("dark")
    light = get_theme("light")
    auto = get_theme("auto")
    assert dark.name == "dark"
    assert light.name == "light"
    assert auto.name == "auto"
    # fallback
    assert get_theme("nonexistent").name == "dark"
    assert get_theme(None).name == "dark"


def test_effort_normalization() -> None:
    """思考强度归一化."""
    from hakus.entry import _normalize_effort
    assert _normalize_effort("quick") is None
    assert _normalize_effort("fast") is None
    assert _normalize_effort("low") == "low"
    assert _normalize_effort("deep") == "high"
    assert _normalize_effort("high") == "high"
    assert _normalize_effort("ultra") == "max"
    assert _normalize_effort("max") == "max"


def test_error_translate() -> None:
    """已知 SDK 错误 → 中文映射."""
    from hakus.cli.app import translate_error
    cases = [
        ("Rate limit exceeded", "请求太频繁"),
        ("Invalid API key provided", "API Key"),
        ("Connection timed out", "超时"),
        ("context_length_exceeded: too long", "对话太长"),
        ("DNS resolution failed", "DNS"),
        ("SSL certificate error", "SSL"),
        ("auth error: 401 Unauthorized", "API Key"),
    ]
    for raw, expected_keyword in cases:
        friendly, _ = translate_error(raw)
        assert expected_keyword in friendly, \
            f"({raw!r}) → {friendly!r}, 期望包含 {expected_keyword!r}"


def test_command_help_output() -> None:
    """/help 命令可执行."""
    from hakus.cli import HakusCLI
    from hakus.cli.commands import register_builtin, parse
    register_builtin()
    app = HakusCLI()
    cmd, args = parse("/help")
    assert cmd is not None and cmd.handler is not None
    result = cmd.handler(args, app)
    assert result.message is not None
    assert "help" in result.message


def test_command_mode_switch() -> None:
    """/mode code 可切换模式."""
    from hakus.cli import HakusCLI
    from hakus.cli.commands import register_builtin, parse
    register_builtin()
    app = HakusCLI()
    cmd, args = parse("/mode code")
    assert cmd is not None and cmd.handler is not None
    result = cmd.handler(args, app)
    assert "Code" in result.message
    assert app.session.run_mode == "deep"

    cmd, args = parse("/mode work")
    result = cmd.handler(args, app)
    assert "Work" in result.message
    assert app.session.run_mode == "swift"


def test_command_effort_switch() -> None:
    """/effort deep 可切换思考强度."""
    from hakus.cli import HakusCLI
    from hakus.cli.commands import register_builtin, parse
    register_builtin()
    app = HakusCLI()
    cmd, args = parse("/effort ultra")
    assert cmd is not None and cmd.handler is not None
    result = cmd.handler(args, app)
    assert "极致" in result.message
    assert app.session.reasoning_effort == "max"


def test_command_theme_switch() -> None:
    """/theme light 可切换主题."""
    from hakus.cli import HakusCLI
    from hakus.cli.commands import register_builtin, parse
    register_builtin()
    app = HakusCLI()
    cmd, args = parse("/theme light")
    assert cmd is not None and cmd.handler is not None
    result = cmd.handler(args, app)
    assert "light" in result.message
    assert app.theme_name == "light"


def test_session_event_handler_default() -> None:
    """CLISession 默认回调不会 crash."""
    from hakus.cli.session import CLISession
    sess = CLISession(model_type="deepseek", run_mode="swift")
    # 默认 on_event = lambda: None, 应该不抛
    sess.on_event(None)
    sess.on_turn_start(None)  # type: ignore
    sess.on_turn_end(None)  # type: ignore


def main() -> int:
    print("=== HakusCLI smoke tests ===")
    tests = [
        ("imports", test_imports),
        ("app_instantiation", test_app_instantiation),
        ("app_instantiation_code_mode", test_app_instantiation_code_mode),
        ("commands_registered", test_commands_registered),
        ("command_aliases", test_command_aliases),
        ("parse_command", test_parse_command),
        ("themes", test_themes),
        ("effort_normalization", test_effort_normalization),
        ("error_translate", test_error_translate),
        ("command_help_output", test_command_help_output),
        ("command_mode_switch", test_command_mode_switch),
        ("command_effort_switch", test_command_effort_switch),
        ("command_theme_switch", test_command_theme_switch),
        ("session_event_handler_default", test_session_event_handler_default),
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        if _check(name, fn):
            passed += 1
        else:
            failed += 1
    print(f"\n=== {passed}/{passed + failed} passed ===")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
