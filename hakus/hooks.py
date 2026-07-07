"""
HakusAI Hook 系统
对标 Claude Code 的 PreToolUse / PostToolUse / UserPromptSubmit hooks

支持 4 种 hook 事件:
  - PreToolUse       工具调用前
  - PostToolUse      工具调用后
  - UserPromptSubmit 用户消息提交时
  - Stop             会话结束时

每个 hook 可选择注册:
  - Python 回调函数
  - 外部 shell 命令
"""
import asyncio
import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from utils.logger import get_logger

logger = get_logger(__name__)


class HookEvent(str, Enum):
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    STOP = "Stop"
    NOTIFICATION = "Notification"


@dataclass
class HookContext:
    event: HookEvent
    tool_name: Optional[str] = None
    tool_input: Optional[Dict[str, Any]] = None
    tool_output: Optional[str] = None
    user_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


HookCallback = Callable[[HookContext], Union[None, Awaitable[None], bool, Dict[str, Any]]]
Decision = Optional[Union[bool, Dict[str, Any]]]


class HookRegistry:
    """Hook 注册表, 存储和执行 hooks"""

    def __init__(self):
        self._hooks: Dict[HookEvent, List[Dict]] = {
            event: [] for event in HookEvent
        }

    def register(self, event: HookEvent,
                 callback: Optional[HookCallback] = None,
                 shell_command: Optional[str] = None,
                 name: str = "unnamed") -> None:
        """注册一个 hook."""
        if not callback and not shell_command:
            raise ValueError("必须提供 callback 或 shell_command")
        self._hooks[event].append({
            "name": name,
            "callback": callback,
            "shell_command": shell_command
        })
        logger.info(f"Hook 已注册: {event.value} -> {name}")

    def unregister(self, event: HookEvent, name: str) -> bool:
        for i, h in enumerate(self._hooks[event]):
            if h["name"] == name:
                del self._hooks[event][i]
                return True
        return False

    def list_hooks(self) -> Dict[str, List[str]]:
        return {
            e.value: [h["name"] for h in hooks]
            for e, hooks in self._hooks.items()
        }

    async def trigger(self, ctx: HookContext) -> List[Decision]:
        """触发事件的所有 hooks, 返回每个 hook 的决策."""
        decisions: List[Decision] = []
        for hook in self._hooks[ctx.event]:
            try:
                if hook["callback"]:
                    result = hook["callback"](ctx)
                    if asyncio.iscoroutine(result):
                        result = await result
                    decisions.append(result)
                elif hook["shell_command"]:
                    decisions.append(await self._run_shell(hook["shell_command"], ctx))
            except Exception as e:
                logger.error(f"Hook {hook['name']} 失败: {e}")
                decisions.append(None)
        return decisions

    async def _run_shell(self, command: str, ctx: HookContext) -> Decision:
        env = os.environ.copy()
        env["HAKUS_EVENT"] = ctx.event.value
        if ctx.tool_name:
            env["HAKUS_TOOL_NAME"] = ctx.tool_name
        if ctx.tool_input:
            env["HAKUS_TOOL_INPUT"] = json.dumps(ctx.tool_input, ensure_ascii=False)
        if ctx.tool_output:
            env["HAKUS_TOOL_OUTPUT"] = ctx.tool_output[:2000]
        if ctx.user_message:
            env["HAKUS_USER_MESSAGE"] = ctx.user_message

        try:
            result = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )
            stdout, stderr = await asyncio.wait_for(result.communicate(), timeout=30)
            if result.returncode == 0:
                try:
                    return json.loads(stdout.decode().strip())
                except Exception:
                    return True
            else:
                logger.warning(f"Shell hook '{command}' 失败: {stderr.decode()}")
                return None
        except asyncio.TimeoutError:
            logger.warning(f"Shell hook '{command}' 超时")
            return None
        except Exception as e:
            logger.error(f"Shell hook 错误: {e}")
            return None


class HookChain:
    """对 hook 决策链式处理."""

    def __init__(self, registry: HookRegistry):
        self.registry = registry

    async def before_tool_use(self, tool_name: str, tool_input: Dict) -> bool:
        """PreToolUse. 返回 True 允许, False 阻止."""
        ctx = HookContext(
            event=HookEvent.PRE_TOOL_USE,
            tool_name=tool_name,
            tool_input=tool_input
        )
        decisions = await self.registry.trigger(ctx)
        for d in decisions:
            if d is False:
                logger.info(f"Hook 阻止工具调用: {tool_name}")
                return False
            if isinstance(d, dict) and d.get("decision") == "block":
                return False
        return True

    async def after_tool_use(self, tool_name: str, tool_input: Dict, output: str) -> None:
        """PostToolUse. 仅记录, 不影响流程."""
        ctx = HookContext(
            event=HookEvent.POST_TOOL_USE,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=output
        )
        await self.registry.trigger(ctx)

    async def on_user_message(self, message: str) -> tuple:
        """UserPromptSubmit. 返回 (message, block_reason). block_reason 非空则阻断."""
        ctx = HookContext(event=HookEvent.USER_PROMPT_SUBMIT, user_message=message)
        decisions = await self.registry.trigger(ctx)
        for d in decisions:
            if isinstance(d, dict):
                if d.get("decision") == "block":
                    return message, d.get("reason", "Blocked by hook")
                if "user_message" in d:
                    message = d["user_message"]
        return message, None

    async def on_stop(self) -> None:
        ctx = HookContext(event=HookEvent.STOP)
        await self.registry.trigger(ctx)


def setup_default_hooks(registry: HookRegistry) -> None:
    """注册一组常用的默认 hooks."""

    async def log_tool_use(ctx: HookContext) -> None:
        logger.info(f"工具调用: {ctx.tool_name}({json.dumps(ctx.tool_input, ensure_ascii=False)[:200]})")

    async def log_tool_result(ctx: HookContext) -> None:
        output = ctx.tool_output or ""
        logger.info(f"工具结果 [{ctx.tool_name}]: {output[:200]}")

    async def log_user_message(ctx: HookContext) -> None:
        logger.info(f"用户消息: {(ctx.user_message or '')[:200]}")

    registry.register(HookEvent.PRE_TOOL_USE, callback=log_tool_use, name="log-tool-use")
    registry.register(HookEvent.POST_TOOL_USE, callback=log_tool_result, name="log-tool-result")
    registry.register(HookEvent.USER_PROMPT_SUBMIT, callback=log_user_message, name="log-user-message")