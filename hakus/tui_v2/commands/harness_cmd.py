"""Harness 命令 — 控制 Agent Harness 评估框架 (开关/状态/测试)."""
from __future__ import annotations

from . import SlashCommand, CommandContext


class HarnessCommand(SlashCommand):
    name = "harness"
    description = "Toggle agent harness guard, view status, or run tests"
    aliases = ["harn"]

    async def execute(self, ctx: CommandContext) -> None:
        sub = ctx.args.strip().lower()

        if sub in ("on", "1", "true", "enable"):
            await self._set_enabled(ctx, True)
        elif sub in ("off", "0", "false", "disable"):
            await self._set_enabled(ctx, False)
        elif sub in ("status",):
            await self._show_status(ctx)
        elif sub in ("test",):
            await self._run_test(ctx)
        else:
            # 默认: toggle
            await self._toggle(ctx)

    async def _toggle(self, ctx: CommandContext) -> None:
        """切换 harness 开关."""
        try:
            agent = getattr(ctx.app, "_agent", None)
            if agent is None:
                self._ok(ctx, "[dim]Agent not initialized[/]")
                return

            current = getattr(agent, "_harness_enabled", True)
            agent._harness_enabled = not current
            state = "enabled" if not current else "disabled"
            self._ok(ctx, f"[bold #00f5ff]Harness {state}[/]")
        except Exception as e:
            self._err(ctx, f"{e}")

    async def _set_enabled(self, ctx: CommandContext, enabled: bool) -> None:
        """设置 harness 开关."""
        try:
            agent = getattr(ctx.app, "_agent", None)
            if agent is None:
                self._ok(ctx, "[dim]Agent not initialized[/]")
                return

            agent._harness_enabled = enabled
            state = "enabled" if enabled else "disabled"
            self._ok(ctx, f"[bold #00f5ff]Harness {state}[/]")
        except Exception as e:
            self._err(ctx, f"{e}")

    async def _show_status(self, ctx: CommandContext) -> None:
        """显示 harness 状态."""
        try:
            agent = getattr(ctx.app, "_agent", None)
            lines = ["[bold #00f5ff]═══ Harness Status ═══[/]", ""]

            if agent is None:
                lines.append("[dim]Agent not initialized[/]")
            else:
                enabled = getattr(agent, "_harness_enabled", True)
                lines.append(
                    f"  Enabled: [bold {'#00f5ff' if enabled else '#ff006e'}]"
                    f"{'YES' if enabled else 'NO'}[/]"
                )

                guard = getattr(agent, "_harness_guard", None)
                if guard:
                    lines.append(f"  Max iterations: {guard.max_iterations}")
                    lines.append(f"  Max duplicate calls: {guard.max_duplicate_calls}")
                    lines.append(f"  Max context %: {guard.max_context_pct}")
                    lines.append(f"  Violations: {len(guard.get_violations())}")
                else:
                    lines.append("  [dim]Guard not active (no turn in progress)[/]")

                context = getattr(agent, "_context", None)
                if context:
                    calib = getattr(context, "_calibration_factor", 1.0)
                    lines.append(f"  Calibration factor: {calib:.2f}")

            lines.append("")
            lines.append("[dim]Usage: /harness [on|off|status|test][/]")
            self._ok(ctx, "\n".join(lines))
        except Exception as e:
            self._err(ctx, f"{e}")

    async def _run_test(self, ctx: CommandContext) -> None:
        """运行内置 smoke test."""
        try:
            from hakus.harness import HarnessSuite

            suite = HarnessSuite.create_smoke_test()
            await suite.run_all()

            # 格式化结果
            lines = ["[bold #00f5ff]═══ Harness Smoke Test ═══[/]", ""]
            for result in suite.results:
                status = "[bold #00f5ff]PASS[/]" if result["passed"] else "[bold #ff006e]FAIL[/]"
                lines.append(f"  {status} {result['name']}")
                if result.get("error"):
                    lines.append(f"       [dim]{result['error']}[/]")

            total = len(suite.results)
            passed = sum(1 for r in suite.results if r["passed"])
            lines.append("")
            lines.append(f"  Results: [bold]{passed}/{total}[/] passed")

            self._ok(ctx, "\n".join(lines))
        except Exception as e:
            self._err(ctx, f"Error running test: {e}")
