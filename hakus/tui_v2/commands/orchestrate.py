"""/orchestrate — 手动触发多智能体协同.

行为:
- 把后续输入强制走多 Agent 路径 (Planner → Dev → 6 维测试 → 修复循环)
- 不依赖 `_should_use_orchestrator` 的启发式 — 用户显式选择
- TUI 状态栏切到 "Orchestrating" phase
- 实时显示阶段 (plan / dev / test / fix / final / done) 切换

例:
  /orchestrate 用 spring boot 写个 AI 挂号系统
"""
from __future__ import annotations

import asyncio
from typing import List, Optional

from . import CommandContext, SlashCommand


class OrchestrateCommand(SlashCommand):
    name = "orchestrate"
    description = (
        "用多智能体协同 (Planner + Dev + 6 维测试 + 修复循环) "
        "处理复杂长时任务"
    )
    aliases = ["orch"]
    requires_args = True

    async def execute(self, ctx: CommandContext) -> None:
        requirement = ctx.args.strip()
        if not requirement:
            self._err(ctx, "用法: /orchestrate <需求描述>")
            return

        agent = ctx.app._agent
        orch = getattr(agent, "_orchestrator", None)
        if orch is None:
            self._err(
                ctx,
                "❌ Orchestrator 未初始化."
                "请确认 entry.py 中已挂载 orchestrator.",
            )
            return

        # Force the agent's `run_turn` to take the
        # orchestrator path on its very next call, regardless of the
        # auto-detection heuristic. The flag is per-turn: cleared in
        # the `finally` block so subsequent turns go back to the
        # normal routing decision.
        agent.force_orchestrator = True
        try:
            await ctx.app._run_stream(requirement)
        finally:
            agent.force_orchestrator = False


# Alias: /multi (claude code 风格)
class MultiAgentCommand(OrchestrateCommand):
    name = "multi"
    description = "= /orchestrate"
    aliases = []  # 不继承父类 aliases
