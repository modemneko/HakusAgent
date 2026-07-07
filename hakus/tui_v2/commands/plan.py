"""/plan /approve /reject — Plan 模式控制"""
from . import SlashCommand, CommandContext


class PlanCommand(SlashCommand):
    name = "plan"
    description = "进入 Plan 模式 (先规划后执行)"

    async def execute(self, ctx: CommandContext) -> None:
        sub = ctx.arg(0, "")
        pm = getattr(ctx.app._agent, '_plan_manager', None)
        if pm is None:
            self._err(ctx, "Plan 模式未启用")
            return
        if sub == "exit":
            result = pm.exit_plan_mode()
        else:
            result = pm.enter_plan_mode()
        self._ok(ctx, result)


class ApproveCommand(SlashCommand):
    name = "approve"
    description = "批准当前计划"

    async def execute(self, ctx: CommandContext) -> None:
        pm = getattr(ctx.app._agent, '_plan_manager', None)
        if pm is None:
            self._err(ctx, "无计划可批准")
            return
        result = pm.approve()
        self._ok(ctx, result)


class RejectCommand(SlashCommand):
    name = "reject"
    description = "拒绝当前计划 (可附 reason)"

    async def execute(self, ctx: CommandContext) -> None:
        pm = getattr(ctx.app._agent, '_plan_manager', None)
        if pm is None:
            self._err(ctx, "无计划可拒绝")
            return
        result = pm.reject(reason=ctx.args)
        self._ok(ctx, result)
