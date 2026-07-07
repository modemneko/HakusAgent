"""/init — 初始化项目 .hakus.md"""
from . import SlashCommand, CommandContext
import os


class InitCommand(SlashCommand):
    name = "init"
    description = "初始化项目 .hakus.md"

    async def execute(self, ctx: CommandContext) -> None:
        workdir = ctx.app._session.working_dir or os.getcwd()
        md_path = os.path.join(workdir, ".hakus.md")
        if os.path.exists(md_path):
            self._ok(ctx, "`.hakus.md` 已存在")
            return
        try:
            from ...memory import create_project_memory
            create_project_memory(workdir)
            self._ok(ctx, f"✓ 已创建 `.hakus.md` 在 `{workdir}`")
        except Exception as e:
            self._err(ctx, f"创建 .hakus.md 失败: {e}")
