"""AgentCore hook 与 plan mode 集成测试."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hakus.agent import AgentCore, _PLAN_MODE_BLOCKED_TOOLS
from hakus.hooks import HookChain, HookContext, HookEvent, HookRegistry
from hakus.plan_mode import PlanManager
from hakus.permission import PermissionMode
from hakus.tools import Tool


class _EchoTool(Tool):
    name = "Write"
    description = "test write"
    parameters_schema = {"type": "object", "properties": {}}
    is_dangerous = True

    async def execute(self, **kwargs) -> str:
        return "written"


@pytest.fixture
def agent_with_hooks(monkeypatch):
    monkeypatch.setattr(
        AgentCore, "_init_model",
        lambda self: setattr(self, "_model", MagicMock()),
    )
    agent = AgentCore(
        model_type="deepseek",
        permission_mode=PermissionMode.BYPASS,
        session_id="test_hooks_plan",
    )
    agent.register_tool(_EchoTool())
    registry = HookRegistry()
    agent._hook_chain = HookChain(registry)
    agent._plan_manager = PlanManager()
    return agent, registry


@pytest.mark.asyncio
async def test_hook_blocks_user_message(agent_with_hooks):
    agent, registry = agent_with_hooks

    async def block_hook(ctx: HookContext):
        return {"decision": "block", "reason": "test block"}

    registry.register(HookEvent.USER_PROMPT_SUBMIT, callback=block_hook, name="block-test")

    response = await agent.process("hello")
    assert "Blocked" in response.content
    assert response.content == "Blocked: test block"


@pytest.mark.asyncio
async def test_hook_blocks_tool_use(agent_with_hooks):
    agent, registry = agent_with_hooks

    async def block_tool(ctx: HookContext):
        return False

    registry.register(HookEvent.PRE_TOOL_USE, callback=block_tool, name="block-tool")

    result = await agent._execute_tool_call("Write", {})
    assert not result.success
    assert "Blocked by hook" in result.result


@pytest.mark.asyncio
async def test_plan_mode_blocks_write_tools(agent_with_hooks):
    agent, _ = agent_with_hooks
    agent._plan_manager.enter_plan_mode()

    result = await agent._execute_tool_call("Write", {})
    assert not result.success
    assert "Plan mode" in result.result


def test_plan_mode_blocked_tools_include_write():
    assert "Write" in _PLAN_MODE_BLOCKED_TOOLS
    assert "Bash" in _PLAN_MODE_BLOCKED_TOOLS


@pytest.mark.asyncio
async def test_build_messages_includes_plan_suffix(agent_with_hooks):
    agent, _ = agent_with_hooks
    agent._plan_manager.enter_plan_mode()
    agent._context.add_message("user", "plan something")
    messages = agent._build_messages()
    assert messages[0]["role"] == "system"
    assert "PLAN MODE" in messages[0]["content"]
