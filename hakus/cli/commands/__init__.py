"""Slash 命令注册表."""
from .registry import (
    CommandResult,
    CommandHandler,
    SlashCommand,
    register,
    lookup,
    all_commands,
    parse,
)
from .builtin import register_builtin

__all__ = [
    "CommandResult",
    "CommandHandler",
    "SlashCommand",
    "register",
    "lookup",
    "all_commands",
    "parse",
    "register_builtin",
]
