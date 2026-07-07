"""/spec — Spec 模式管理"""
from . import SlashCommand, CommandContext


class SpecCommand(SlashCommand):
    name = "spec"
    description = "Spec 模式 (init/list/show/use)"

    async def execute(self, ctx: CommandContext) -> None:
        from ...spec.mode import SpecMode
        sub = ctx.arg(0, "")
        if sub == "init":
            result = SpecMode.init()
            self._ok(ctx, result)
        elif sub == "list":
            result = SpecMode.list()
            self._ok(ctx, result)
        elif sub == "show" and len(ctx.parts) > 1:
            result = SpecMode.show(ctx.arg(1))
            self._ok(ctx, result)
        elif sub == "use" and len(ctx.parts) > 1:
            result = SpecMode.use(ctx.arg(1))
            self._ok(ctx, result)
        else:
            text = "**用法:**\n- `/spec init`  初始化\n- `/spec list`  列表\n- `/spec show <name>`  显示\n- `/spec use <name>`  切换"
            self._ok(ctx, text)
