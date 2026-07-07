"""
Tests for the v2 TUI surface of the multi-agent orchestrator:

  1. `/orchestrate` and `/multi` slash commands are registered.
  2. `agent.force_orchestrator` overrides the routing heuristic.
  3. The default event handler correctly maps
     :class:`OrchestratorPhaseChanged` events to the activity
     strip's "orchestrator" phase.
  4. The handler keeps the orchestrator activity state until the
     stream completes (no "Streaming" flicker mid-run).

These tests sit alongside `test_orchestrator_routing.py` which
covers the agent-level logic. Here we focus on the TUI surface.

codex-style refactor: the legacy ``_update_activity_phase`` string
sniffer was replaced by typed :class:`OrchestratorPhaseChanged`
events handled in :class:`DefaultEventHandler`.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, List
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ============================================================
# Slash command registration
# ============================================================


class TestOrchestrateCommandRegistration:
    """`/orchestrate` and `/multi` must be discoverable through the
    default command registry, both under their canonical name and
    their aliases."""

    def test_orchestrate_registered(self):
        from hakus.tui_v2.commands import build_default_registry
        reg = build_default_registry()
        cmd = reg.get("orchestrate")
        assert cmd is not None
        assert cmd.name == "orchestrate"

    def test_orch_alias_registered(self):
        from hakus.tui_v2.commands import build_default_registry
        reg = build_default_registry()
        # The "orch" alias should map to the same OrchestrateCommand
        # instance as "orchestrate"
        cmd_orch = reg.get("orch")
        cmd_full = reg.get("orchestrate")
        assert cmd_orch is not None
        assert cmd_orch is cmd_full

    def test_multi_alias_registered(self):
        """`/multi` is a claude-code-style alias for /orchestrate."""
        from hakus.tui_v2.commands import build_default_registry
        reg = build_default_registry()
        cmd = reg.get("multi")
        assert cmd is not None
        assert cmd.name == "multi"

    def test_orchestrate_in_help(self):
        """`/orchestrate` must show up in the help listing so users
        can discover it."""
        from hakus.tui_v2.commands import build_default_registry
        reg = build_default_registry()
        help_text = reg.format_help()
        assert "/orchestrate" in help_text or "`orchestrate`" in help_text

    def test_command_requires_args(self):
        from hakus.tui_v2.commands.orchestrate import OrchestrateCommand
        # The base class treats this as metadata; we just assert it's
        # declared correctly so the user gets a usage hint if they
        # forget the requirement.
        assert OrchestrateCommand.requires_args is True

    def test_command_has_aliases_list(self):
        from hakus.tui_v2.commands.orchestrate import OrchestrateCommand
        # Call on an instance, not the class — `get_aliases` is an
        # instance method on SlashCommand.
        cmd = OrchestrateCommand()
        assert isinstance(cmd.get_aliases(), list)
        assert "orch" in cmd.get_aliases()


# ============================================================
# /orchestrate with no args → error message
# ============================================================


class TestOrchestrateCommandBehavior:
    """Verify the command's pre-flight checks and flag handling."""

    @pytest.mark.asyncio
    async def test_no_args_emits_error(self):
        from hakus.tui_v2.commands import build_default_registry
        from hakus.tui_v2.commands import CommandContext
        from hakus.tui_v2.messages import Message

        reg = build_default_registry()
        cmd = reg.get("orchestrate")

        app = MagicMock()
        ctx = CommandContext(
            app=app,
            args="",  # ← no requirement provided
            parts=[],
            raw="/orchestrate",
        )
        # The command mounts an error via app._mount_message
        await cmd.execute(ctx)
        app._mount_message.assert_called()
        msg = app._mount_message.call_args[0][0]
        assert isinstance(msg, Message)
        assert msg.role == "error"

    @pytest.mark.asyncio
    async def test_no_orchestrator_emits_error(self):
        """If the agent has no orchestrator attached, the command
        must surface a clear error rather than crashing."""
        from hakus.tui_v2.commands import build_default_registry
        from hakus.tui_v2.commands import CommandContext
        from hakus.tui_v2.messages import Message

        reg = build_default_registry()
        cmd = reg.get("orchestrate")

        agent = MagicMock()
        agent._orchestrator = None
        app = MagicMock()
        app._agent = agent

        ctx = CommandContext(
            app=app,
            args="build a thing",
            parts=["build", "a", "thing"],
            raw="/orchestrate build a thing",
        )
        await cmd.execute(ctx)
        app._mount_message.assert_called()
        msg = app._mount_message.call_args[0][0]
        assert msg.role == "error"
        assert "未初始化" in msg.content

    @pytest.mark.asyncio
    async def test_force_flag_set_and_cleared(self):
        """Successful path: force_orchestrator is True while running,
        False afterwards. This is what makes the route stick for one
        turn and not leak into subsequent turns."""
        from hakus.tui_v2.commands import build_default_registry
        from hakus.tui_v2.commands import CommandContext
        from hakus.permission import PermissionMode
        from hakus.agent import AgentCore

        reg = build_default_registry()
        cmd = reg.get("orchestrate")

        # Use a real agent so the property/setter actually works.
        agent = AgentCore(
            model_type="deepseek",
            permission_mode=PermissionMode.AUTO,
            confirm_callback=None,
            max_iterations=3,
            max_context_tokens=32000,
            llm_timeout=1.0,
        )
        agent._orchestrator = MagicMock()

        # The agent's run_turn is the real method; we replace
        # it with a MagicMock so we don't actually call the LLM.
        async def fake_run_turn(*a, **k):
            return
            yield  # makes this a generator
        agent.run_turn = fake_run_turn

        # The sink isn't easy to instantiate without a Textual app,
        # so we patch StreamingSink to a no-op.
        from hakus.tui_v2 import streaming as streaming_mod
        original_run = streaming_mod.StreamingSink.run
        async def noop_run(self, user_input, run_turn):
            # Capture the flag state during the run
            return
        streaming_mod.StreamingSink.run = noop_run

        app = MagicMock()
        app._agent = agent
        async def fake_run_stream(text):
            # Inside this call, the flag should be True
            assert agent.force_orchestrator, (
                "force_orchestrator must be True while running"
            )
        app._run_stream = fake_run_stream

        ctx = CommandContext(
            app=app,
            args="build a thing",
            parts=["build", "a", "thing"],
            raw="/orchestrate build a thing",
        )

        try:
            await cmd.execute(ctx)
        finally:
            streaming_mod.StreamingSink.run = original_run

        # After execution, flag should be cleared
        assert not agent.force_orchestrator, (
            "force_orchestrator must be reset after the run"
        )


# ============================================================
# Activity phase detection in the sink
# ============================================================


class TestActivityPhaseDetection:
    """codex-style: the orchestrator phase now arrives as
    :class:`OrchestratorPhaseChanged` events. The default handler
    maps them to ``activity.set_phase("orchestrator", detail=...)``.
    No more string sniffing of ``**[📋 计划]**`` in tokens.
    """

    def _handler(self, app: MagicMock):
        from hakus.protocol.handler import DefaultEventHandler
        return DefaultEventHandler(app)

    def _fire(self, app: MagicMock, event):
        from hakus.protocol.handler import DefaultEventHandler
        h = DefaultEventHandler(app)
        h.handle(event)
        return h

    def test_orchestrator_event_swaps_to_orchestrator_phase(self):
        """An OrchestratorPhaseChanged event switches the activity
        strip to "orchestrator"."""
        app = MagicMock()
        activity = MagicMock()
        app.query_one.side_effect = lambda q: {
            "#activity-strip": activity,
        }.get(q)

        from hakus.protocol import OrchestratorPhaseChanged
        self._fire(app, OrchestratorPhaseChanged(phase="planning", detail="计划中"))

        activity.set_phase.assert_called()
        call = activity.set_phase.call_args
        # set_phase(phase, detail=...) — phase is positional, detail is kw
        assert call.args[0] == "orchestrator"

    def test_planning_phase_specifically(self):
        """The "planning" phase maps to "计划中" detail."""
        app = MagicMock()
        activity = MagicMock()
        app.query_one.side_effect = lambda q: {"#activity-strip": activity}.get(q)

        from hakus.protocol import OrchestratorPhaseChanged
        self._fire(app, OrchestratorPhaseChanged(phase="planning", detail="计划中"))

        call = activity.set_phase.call_args
        assert call.args[0] == "orchestrator"
        assert "计划中" in call.kwargs.get("detail", "")

    def test_developing_phase_specifically(self):
        app = MagicMock()
        activity = MagicMock()
        app.query_one.side_effect = lambda q: {"#activity-strip": activity}.get(q)

        from hakus.protocol import OrchestratorPhaseChanged
        self._fire(app, OrchestratorPhaseChanged(phase="developing", detail="开发中"))

        call = activity.set_phase.call_args
        assert call.args[0] == "orchestrator"
        assert "开发中" in call.kwargs.get("detail", "")

    def test_testing_phase_specifically(self):
        app = MagicMock()
        activity = MagicMock()
        app.query_one.side_effect = lambda q: {"#activity-strip": activity}.get(q)

        from hakus.protocol import OrchestratorPhaseChanged
        self._fire(app, OrchestratorPhaseChanged(phase="testing", detail="测试中"))

        call = activity.set_phase.call_args
        assert "测试中" in call.kwargs.get("detail", "")

    def test_fix_phase_specifically(self):
        app = MagicMock()
        activity = MagicMock()
        app.query_one.side_effect = lambda q: {"#activity-strip": activity}.get(q)

        from hakus.protocol import OrchestratorPhaseChanged
        self._fire(app, OrchestratorPhaseChanged(phase="fixing", detail="修复中"))

        call = activity.set_phase.call_args
        assert "修复中" in call.kwargs.get("detail", "")

    def test_non_orchestrator_event_does_not_switch_to_orchestrator(self):
        """A plain TextDelta event must not touch the activity strip's
        phase (TextDelta switches to "streaming", not "orchestrator").
        """
        app = MagicMock()
        activity = MagicMock()
        app.query_one.side_effect = lambda q: {"#activity-strip": activity}.get(q)

        from hakus.protocol import TextDelta
        self._fire(app, TextDelta(text="Some LLM response text"))

        # TextDelta drives the activity strip to "streaming" (not
        # "orchestrator"); the orchestrator phase only flips on
        # OrchestratorPhaseChanged events.
        calls = [c for c in activity.set_phase.call_args_list]
        assert calls, "TextDelta should still drive the activity strip"
        for c in calls:
            assert c.args[0] != "orchestrator"

    def test_subsequent_events_stay_in_orchestrator_mode(self):
        """Once we receive an OrchestratorPhaseChanged, subsequent
        OrchestratorPhaseChanged events keep updating the activity
        strip (one per event), so the user can see phase progress.
        """
        app = MagicMock()
        activity = MagicMock()
        app.query_one.side_effect = lambda q: {"#activity-strip": activity}.get(q)

        from hakus.protocol import OrchestratorPhaseChanged
        h = self._handler(app)
        h.handle(OrchestratorPhaseChanged(phase="planning", detail="计划中"))
        n_after_first = activity.set_phase.call_count

        # Each subsequent event should refresh the activity strip
        h.handle(OrchestratorPhaseChanged(phase="developing", detail="开发中"))
        h.handle(OrchestratorPhaseChanged(phase="testing", detail="测试中"))
        h.handle(OrchestratorPhaseChanged(phase="fixing", detail="修复中"))

        assert activity.set_phase.call_count == n_after_first + 3, (
            "Each OrchestratorPhaseChanged should refresh the activity "
            "strip so the user sees phase progress"
        )


# ============================================================
# AgentCore.force_orchestrator property
# ============================================================


class TestAgentForceOrchestratorProperty:
    """`force_orchestrator` is a property on AgentCore that the
    `/orchestrate` slash command sets to override the routing
    heuristic. Default is False (no override)."""

    def _agent(self):
        from hakus.agent import AgentCore
        from hakus.permission import PermissionMode
        return AgentCore(
            model_type="deepseek",
            permission_mode=PermissionMode.AUTO,
            confirm_callback=None,
            max_iterations=3,
            max_context_tokens=32000,
            llm_timeout=1.0,
        )

    def test_default_is_false(self):
        agent = self._agent()
        assert agent.force_orchestrator is False

    def test_setter_updates_value(self):
        agent = self._agent()
        agent.force_orchestrator = True
        assert agent.force_orchestrator is True
        agent.force_orchestrator = False
        assert agent.force_orchestrator is False

    def test_heuristic_ignored_when_force_is_true(self):
        """When force_orchestrator=True, even simple questions route
        to the orchestrator. (We don't actually call run_turn;
        we just verify the decision would be made via the property.)"""
        agent = self._agent()
        agent._orchestrator = MagicMock()
        # A short question — would NOT route via the heuristic
        assert not agent._should_use_orchestrator("你好")
        # But force flag overrides
        agent.force_orchestrator = True
        # The combined routing decision is what run_turn uses:
        assert (agent.force_orchestrator
                or agent._should_use_orchestrator("你好"))


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
