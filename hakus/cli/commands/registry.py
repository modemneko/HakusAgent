"""Slash 命令注册表.

命令分两类：
- **同步命令**：``/help`` ``/clear`` ``/exit`` — 立即返回, 不调 AgentCore.
- **配置命令**：``/mode work`` ``/effort deep`` ``/model glm-4.5`` — 改 session 配置.

未来扩展：
- ``/diff`` ``/review`` ``/rollback`` (Phase 2)
- ``/fork`` ``/resume`` ``/compact`` (Phase 3)
- ``/mcp`` ``/theme`` ``/agents`` (Phase 4)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class CommandResult:
    """命令执行结果."""

    # 显示给用户的消息（None = 命令自己已经处理了显示）
    message: Optional[str] = None
    # 是否退出 TUI
    exit: bool = False
    # 是否清空对话历史
    clear: bool = False


# 命令处理器签名：(args, ctx) -> CommandResult
# args 是 ``/cmd arg1 arg2`` 后面的字符串（已 strip）.
# ctx 是 HakusCLI 实例, 提供访问 session / TUI 的能力.
CommandHandler = Callable[["str", "HakusCLI"], CommandResult]


@dataclass(frozen=True)
class SlashCommand:
    """一条 slash 命令的定义."""

    name: str               # 不含 /, 如 "help"
    aliases: tuple[str, ...] = ()
    description: str = ""
    usage: str = ""          # 简短用法提示
    handler: Optional[CommandHandler] = None
    # 是否在 /help 列表中隐藏
    hidden: bool = False


_REGISTRY: dict[str, SlashCommand] = {}


def register(cmd: SlashCommand) -> None:
    """注册一条命令. 别名也注册到同一个对象."""
    _REGISTRY[cmd.name] = cmd
    for alias in cmd.aliases:
        _REGISTRY[alias] = cmd


def lookup(name: str) -> Optional[SlashCommand]:
    """按名字或别名查找命令."""
    return _REGISTRY.get(name.lstrip("/"))


def all_commands() -> list[SlashCommand]:
    """列出所有主命令（去重别名）."""
    seen: set[str] = set()
    out: list[SlashCommand] = []
    for name, cmd in _REGISTRY.items():
        if name in seen or cmd.name in seen:
            continue
        seen.add(cmd.name)
        out.append(cmd)
    return sorted(out, key=lambda c: c.name)


def parse(raw: str) -> tuple[Optional[SlashCommand], str]:
    """解析一行输入.

    Returns:
        (cmd, args) — 如果 raw 不以 / 开头, 返回 (None, raw).
    """
    s = raw.strip()
    if not s.startswith("/"):
        return None, s
    # /cmd args...
    parts = s[1:].split(maxsplit=1)
    name = parts[0]
    args = parts[1] if len(parts) > 1 else ""
    cmd = lookup(name)
    return cmd, args


__all__ = [
    "CommandResult",
    "CommandHandler",
    "SlashCommand",
    "register",
    "lookup",
    "all_commands",
    "parse",
]
