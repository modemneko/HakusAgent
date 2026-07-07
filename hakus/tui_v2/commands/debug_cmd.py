"""Debug 命令 — 切换调试模式, 查看调试日志目录."""
from __future__ import annotations

from . import SlashCommand, CommandContext


class DebugCommand(SlashCommand):
    name = "debug"
    description = "Toggle debug mode or show debug log directory"
    aliases = ["dbg"]

    async def execute(self, ctx: CommandContext) -> None:
        from utils.turn_debug import (
            get_debug_logger, init_debug_logger, shutdown_debug_logger,
            is_debug_enabled,
        )

        sub = ctx.args.strip().lower()

        if sub in ("on", "1", "true", "enable"):
            # 开启 debug
            dbg = get_debug_logger()
            if dbg is None:
                dbg = init_debug_logger()
                ctx.app._debug_logger = dbg
                ctx.app._debug_enabled = True
            self._ok(ctx, f"Debug mode ON\nLogs → {dbg.session_dir}")
            return

        if sub in ("off", "0", "false", "disable"):
            # 关闭 debug
            shutdown_debug_logger()
            ctx.app._debug_logger = None
            ctx.app._debug_enabled = False
            self._ok(ctx, "Debug mode OFF")
            return

        if sub in ("path", "dir", "where", "log"):
            # 显示日志目录
            dbg = get_debug_logger()
            if dbg:
                self._ok(ctx, f"Debug log directory:\n{dbg.session_dir}\nCurrent turn: {dbg.turn_number}")
            else:
                self._ok(ctx, "Debug mode is OFF. Use /debug on to enable.")
            return

        if sub in ("status",):
            enabled = is_debug_enabled()
            dbg = get_debug_logger()
            if enabled and dbg:
                self._ok(ctx, f"Debug: ON\nSession dir: {dbg.session_dir}\nTurn: {dbg.turn_number}")
            else:
                self._ok(ctx, f"Debug: OFF\nUse /debug on to enable")
            return

        # 默认: toggle
        dbg = get_debug_logger()
        if dbg:
            shutdown_debug_logger()
            ctx.app._debug_logger = None
            ctx.app._debug_enabled = False
            self._ok(ctx, "Debug mode OFF")
        else:
            dbg = init_debug_logger()
            ctx.app._debug_logger = dbg
            ctx.app._debug_enabled = True
            self._ok(ctx, f"Debug mode ON\nLogs → {dbg.session_dir}")
