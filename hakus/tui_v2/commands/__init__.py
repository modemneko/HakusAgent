"""
Slash Command 注册中心 (借鉴 Claude Code src/commands/)

设计:
- 每个命令继承 SlashCommand, 声明 name/description/args
- 注册到 SlashCommandRegistry
- App 在 on_prompt_submitted 中解析 → 查表 → 执行
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from ..app import HakusApp
    from .messages import Message


@dataclass
class CommandContext:
    """命令执行上下文."""
    app: "HakusApp"
    args: str  # 命令名后的剩余参数
    parts: List[str]  # 拆分后的参数列表
    raw: str  # 原始完整输入

    def arg(self, idx: int, default: Optional[str] = None) -> Optional[str]:
        if idx < len(self.parts):
            return self.parts[idx]
        return default

    def mount_message(self, msg: "Message") -> None:
        """把消息挂到 MessageList (供命令快捷调用)."""
        self.app._mount_message(msg)


class SlashCommand:
    """Slash 命令基类.

    子类通过类属性声明 metadata:
        name = "foo"
        description = "..."
        aliases = ["f"]  # 可选
        requires_args = False  # 可选
    """

    name: str = ""
    description: str = ""
    aliases: List[str] = []
    requires_args: bool = False

    def get_aliases(self) -> List[str]:
        return list(self.aliases) if isinstance(self.aliases, list) else []

    async def execute(self, ctx: CommandContext) -> None:
        raise NotImplementedError

    # ---- 内部辅助 ----

    def _ok(self, ctx: CommandContext, content: str) -> None:
        from ..messages import Message
        ctx.mount_message(Message.command(self.name, content))

    def _err(self, ctx: CommandContext, content: str) -> None:
        from ..messages import Message
        ctx.mount_message(Message.error(content))

    def _warn(self, ctx: CommandContext, content: str) -> None:
        from ..messages import Message
        ctx.mount_message(Message.command(self.name, f"⚠ {content}"))


class SlashCommandRegistry:
    """Slash 命令注册表."""

    def __init__(self) -> None:
        self._commands: Dict[str, SlashCommand] = {}

    def register(self, command: SlashCommand) -> None:
        if not command.name:
            raise ValueError("command must have a name")
        self._commands[command.name] = command
        for alias in command.get_aliases():
            self._commands[alias] = command

    def get(self, name: str) -> Optional[SlashCommand]:
        return self._commands.get(name)

    def all(self) -> List[SlashCommand]:
        # 去重 (按 command 实例)
        seen: Dict[int, SlashCommand] = {}
        for cmd in self._commands.values():
            seen[id(cmd)] = cmd
        return list(seen.values())

    def format_help(self) -> str:
        lines = ["# 📋 可用命令", ""]
        for cmd in self.all():
            name = cmd.name
            aliases = f" (别名: {', '.join(cmd.aliases)})" if cmd.aliases else ""
            lines.append(f"- **`{name}`**{aliases} — {cmd.description}")
        lines.append("")
        lines.append("**Tip:** 输入 `/` 触发自动补全")
        return "\n".join(lines)


# 延迟注册: 避免循环 import
def build_default_registry() -> SlashCommandRegistry:
    from .help import HelpCommand
    from .model import ModelCommand
    from .config_cmd import ConfigCommand
    from .permission_cmd import PermissionCommand
    from .clear import ClearCommand
    from .compact import CompactCommand
    from .cost import CostCommand
    from .context import ContextCommand
    from .verify import VerifyCommand
    from .btw import BtwCommand
    from .checkpoint import CheckpointCommand
    from .rollback import RollbackCommand
    from .task import TaskCommand
    from .init import InitCommand
    from .memory import MemoryCommand
    from .plan import PlanCommand, ApproveCommand, RejectCommand
    from .todos import TodosCommand
    from .tree import TreeCommand
    from .tools import ToolsCommand
    from .git_cmd import GitCommand
    from .diff import DiffCommand
    from .voice import VoiceCommand
    from .status import StatusCommand
    from .spec import SpecCommand
    from .exit_cmd import ExitCommand
    from .orchestrate import OrchestrateCommand, MultiAgentCommand
    from .debug_cmd import DebugCommand
    from .harness_cmd import HarnessCommand

    reg = SlashCommandRegistry()
    for cmd_cls in [
        HelpCommand, ModelCommand, ConfigCommand, PermissionCommand, ClearCommand,
        CompactCommand, CostCommand, ContextCommand, VerifyCommand,
        BtwCommand, CheckpointCommand, RollbackCommand, TaskCommand,
        InitCommand, MemoryCommand, PlanCommand, ApproveCommand, RejectCommand,
        TodosCommand, TreeCommand, ToolsCommand, GitCommand, DiffCommand,
        VoiceCommand, StatusCommand, SpecCommand, ExitCommand,
        OrchestrateCommand, MultiAgentCommand, DebugCommand, HarnessCommand,
    ]:
        reg.register(cmd_cls())
    return reg
