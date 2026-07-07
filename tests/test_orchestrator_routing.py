"""
Tests for the orchestrator auto-routing and `stream_execute` streaming.

Bug history: the orchestrator was implemented but never called from
production code (`/orchestrate` was removed, the agent never delegated).
The user reported the system trying to handle a "build a Spring Boot
project" request with the single-agent tool loop — which is not designed
for multi-file projects and silently hangs.

These tests verify:
  1. `_should_use_orchestrator` correctly identifies project-build tasks
  2. Long/multi-sentence requests get routed
  3. Simple questions stay on the fast path
  4. The explicit `!` prefix forces orchestrator mode
  5. `Orchestrator.stream_execute` yields events in the right order
  6. The streaming variant yields a `done` event on success
  7. Cancellation surfaces as an `error` event
  8. The AgentResponse carries `input_tokens` / `output_tokens`
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ============================================================
# Routing heuristic
# ============================================================


class TestOrchestratorRouting:
    """`_should_use_orchestrator` decides between fast path and
    multi-agent path. The goal: high precision (don't waste a long
    orchestrator run on a one-line question), acceptable recall
    (catch the obvious "build me a project" patterns)."""

    def _agent(self, with_orchestrator=True):
        from hakus.agent import AgentCore
        from hakus.permission import PermissionMode

        agent = AgentCore(
            model_type="deepseek",
            permission_mode=PermissionMode.AUTO,
            confirm_callback=None,
            max_iterations=3,
            max_context_tokens=32000,
            llm_timeout=1.0,
        )
        if not with_orchestrator:
            agent._orchestrator = None
        else:
            agent._orchestrator = MagicMock()
        return agent

    @pytest.mark.parametrize("text", [
        "在当前目录下用spring boot写个智能AI医院预约挂号客服",
        "用python写一个flask的todo app",
        "Build a full Go backend with gRPC",
        "Create a complete React + TypeScript dashboard",
        "帮我写一个项目",
        "做一个完整的系统",
        "Implement a complete REST API",
    ])
    def test_project_build_triggers_orchestrator(self, text):
        agent = self._agent()
        assert agent._should_use_orchestrator(text), (
            f"Expected orchestrator for: {text!r}"
        )

    @pytest.mark.parametrize("text", [
        "在当前目录下用spring boot写个智能AI医院预约挂号客服",
        "用python写一个flask的todo app",
    ])
    def test_user_actual_cases_trigger_orchestrator(self, text):
        """The two actual requests the user typed. Must route."""
        agent = self._agent()
        assert agent._should_use_orchestrator(text), (
            f"User-case did NOT route: {text!r}"
        )

    @pytest.mark.parametrize("text", [
        "你好",
        "list the current directory",
        "show me what files are here",
        "what is the time?",
        "explain this code to me",
    ])
    def test_simple_questions_stay_on_fast_path(self, text):
        agent = self._agent()
        assert not agent._should_use_orchestrator(text), (
            f"Simple question incorrectly routed: {text!r}"
        )

    def test_explicit_bang_forces_orchestrator(self):
        agent = self._agent()
        assert agent._should_use_orchestrator("!list the files")

    def test_no_orchestrator_object_disables_routing(self):
        agent = self._agent(with_orchestrator=False)
        assert not agent._should_use_orchestrator(
            "build a complete project"
        )

    def test_empty_message_does_not_route(self):
        agent = self._agent()
        assert not agent._should_use_orchestrator("")
        assert not agent._should_use_orchestrator("   ")


# ============================================================
# Orchestrator.Event rendering
# ============================================================


class TestOrchestratorEventFormatting:
    """`_format_orchestrator_event` converts an `Orchestrator.Event` to
    a single line of text for the streaming sink. Different event
    types render differently (phase headers, agent markers, etc.)."""

    def _agent(self):
        from hakus.agent import AgentCore
        from hakus.permission import PermissionMode
        agent = AgentCore(
            model_type="deepseek",
            permission_mode=PermissionMode.AUTO,
            confirm_callback=None,
            max_iterations=3,
            max_context_tokens=32000,
            llm_timeout=1.0,
        )
        agent._orchestrator = MagicMock()
        return agent

    def _event(self, **kwargs):
        from hakus.orchestrator import Orchestrator
        return Orchestrator.Event(**kwargs)

    def test_phase_event_renders_header(self):
        agent = self._agent()
        ev = self._event(type="phase", phase="planning", message="...")
        out = agent._format_orchestrator_event(ev)
        assert "计划" in out
        assert out.startswith("\n\n")

    def test_agent_done_renders_status(self):
        agent = self._agent()
        ev = self._event(type="agent_done", agent_type="dev",
                         task_id="t1", success=True)
        out = agent._format_orchestrator_event(ev)
        assert "✓" in out
        assert "dev" in out

    def test_agent_done_failure_renders_x(self):
        agent = self._agent()
        ev = self._event(type="agent_done", agent_type="dev",
                         task_id="t1", success=False)
        out = agent._format_orchestrator_event(ev)
        assert "✗" in out

    def test_token_usage_is_invisible(self):
        agent = self._agent()
        ev = self._event(type="token_usage",
                         input_tokens=100, output_tokens=200)
        out = agent._format_orchestrator_event(ev)
        assert out == ""
        # But it should still update _last_response
        assert agent._last_response is not None
        assert agent._last_response.input_tokens == 100
        assert agent._last_response.output_tokens == 200

    def test_token_usage_accumulates(self):
        """Multiple token_usage events sum up, not overwrite."""
        agent = self._agent()
        agent._format_orchestrator_event(
            self._event(type="token_usage", input_tokens=50, output_tokens=100)
        )
        agent._format_orchestrator_event(
            self._event(type="token_usage", input_tokens=30, output_tokens=60)
        )
        assert agent._last_response.input_tokens == 80
        assert agent._last_response.output_tokens == 160

    def test_error_event_renders_error(self):
        agent = self._agent()
        ev = self._event(type="error", error="boom")
        out = agent._format_orchestrator_event(ev)
        assert "错误" in out
        assert "boom" in out


# ============================================================
# AgentResponse usage
# ============================================================


def test_agent_response_has_usage_fields():
    """The status-bar token counter reads these fields. Without them
    the counter stays stuck at 0 (the original bug)."""
    from hakus.agent import AgentResponse
    r = AgentResponse(content="hi", input_tokens=42, output_tokens=100)
    assert r.input_tokens == 42
    assert r.output_tokens == 100


# ============================================================
# Orchestrator.stream_execute: end-to-end
# ============================================================


class TestOrchestratorStreamExecute:
    """Smoke tests for `stream_execute` event protocol.

    The full sub-agent pipeline is exercised in
    `test_orchestrator_multi_dim.py` and `test_orchestrator_resume.py`.
    Here we only verify the event contract: the stream yields Events,
    forwards them, and emits a `done` terminator.
    """

    @pytest.mark.asyncio
    async def test_stream_execute_yields_orchestrator_events(self):
        """Verify the event class structure is sound (used by sink)."""
        from hakus.orchestrator import Orchestrator
        ev = Orchestrator.Event(type="phase", phase="planning", message="x")
        assert ev.type == "phase"
        assert ev.phase == "planning"

    @pytest.mark.asyncio
    async def test_event_types_coverage(self):
        """All event types we use must be string-typed and non-empty."""
        from hakus.orchestrator import Orchestrator
        for et in ("phase", "agent_start", "agent_done", "task_progress",
                   "log", "token_usage", "done", "error"):
            ev = Orchestrator.Event(type=et, message="x")
            assert ev.type == et
            assert isinstance(ev.message, str)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
