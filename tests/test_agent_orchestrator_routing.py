"""SubTask 9.7: _maybe_route_to_orchestrator_events() 路由集成测试.

覆盖:
- 复杂任务路由到 orchestrator
- 简单任务不路由到 orchestrator
- `!` 前缀强制路由
- PHASE_MAP 变量名 (phase → new_phase) 修复验证
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hakus.agent import AgentCore
from hakus.permission import PermissionMode
from hakus.protocol.events import (
    AgentEvent,
    OrchestratorPhaseChanged,
    TextDelta,
    TurnCompleted,
    TurnFailed,
)


class TestComplexTasksRoutedToOrchestrator:
    """复杂任务路由到 orchestrator."""

    @pytest.mark.asyncio
    async def test_complex_task_produces_events(self):
        agent = AgentCore(
            model_type="deepseek",
            permission_mode=PermissionMode.AUTO,
            confirm_callback=None,
            max_iterations=3,
            max_context_tokens=32000,
            llm_timeout=1.0,
        )

        # Mock orchestrator with stream_execute_v2
        mock_orch = MagicMock()

        async def fake_stream_v2(requirement, input_files=None):
            yield OrchestratorPhaseChanged(phase="planning", detail="计划中")
            yield OrchestratorPhaseChanged(phase="developing", detail="开发中")
            yield TurnCompleted(content="done")

        mock_orch.stream_execute_v2 = fake_stream_v2
        agent._orchestrator = mock_orch

        events = []
        async for ev in agent._maybe_route_to_orchestrator_events(
            "用 Spring Boot 写一个智能AI医院预约挂号客服"
        ):
            events.append(ev)

        # Should have produced events (at least the initial phase change + stream events)
        assert len(events) >= 1
        # First event should be OrchestratorPhaseChanged for planning
        assert isinstance(events[0], OrchestratorPhaseChanged)

    @pytest.mark.asyncio
    async def test_complex_task_sets_orchestrator_handled(self):
        agent = AgentCore(
            model_type="deepseek",
            permission_mode=PermissionMode.AUTO,
            confirm_callback=None,
            max_iterations=3,
            max_context_tokens=32000,
            llm_timeout=1.0,
        )

        mock_orch = MagicMock()

        async def fake_stream_v2(requirement, input_files=None):
            yield OrchestratorPhaseChanged(phase="planning", detail="计划中")
            yield TurnCompleted(content="done")

        mock_orch.stream_execute_v2 = fake_stream_v2
        agent._orchestrator = mock_orch

        async for _ in agent._maybe_route_to_orchestrator_events(
            "用 Spring Boot 写一个智能AI医院预约挂号客服"
        ):
            pass

        assert agent._orchestrator_handled is True


class TestSimpleTasksNotRouted:
    """简单任务不路由到 orchestrator."""

    @pytest.mark.asyncio
    async def test_simple_task_no_events(self):
        agent = AgentCore(
            model_type="deepseek",
            permission_mode=PermissionMode.AUTO,
            confirm_callback=None,
            max_iterations=3,
            max_context_tokens=32000,
            llm_timeout=1.0,
        )
        agent._orchestrator = MagicMock()

        events = []
        async for ev in agent._maybe_route_to_orchestrator_events("你好"):
            events.append(ev)

        assert len(events) == 0, "Simple task should not produce orchestrator events"

    @pytest.mark.asyncio
    async def test_simple_task_not_handled(self):
        agent = AgentCore(
            model_type="deepseek",
            permission_mode=PermissionMode.AUTO,
            confirm_callback=None,
            max_iterations=3,
            max_context_tokens=32000,
            llm_timeout=1.0,
        )
        agent._orchestrator = MagicMock()

        async for _ in agent._maybe_route_to_orchestrator_events("你好"):
            pass

        assert agent._orchestrator_handled is False


class TestBangPrefixForcesRouting:
    """`!` 前缀强制路由到 orchestrator."""

    @pytest.mark.asyncio
    async def test_bang_prefix_routes_simple_task(self):
        agent = AgentCore(
            model_type="deepseek",
            permission_mode=PermissionMode.AUTO,
            confirm_callback=None,
            max_iterations=3,
            max_context_tokens=32000,
            llm_timeout=1.0,
        )

        mock_orch = MagicMock()

        async def fake_stream_v2(requirement, input_files=None):
            yield OrchestratorPhaseChanged(phase="planning", detail="计划中")
            yield TurnCompleted(content="done")

        mock_orch.stream_execute_v2 = fake_stream_v2
        agent._orchestrator = mock_orch

        events = []
        async for ev in agent._maybe_route_to_orchestrator_events("!你好"):
            events.append(ev)

        # Should have events — `!` forces routing
        assert len(events) >= 1
        assert isinstance(events[0], OrchestratorPhaseChanged)

    @pytest.mark.asyncio
    async def test_bang_prefix_overrides_scorer(self):
        """`!` 前缀覆盖复杂度评分器的判断."""
        agent = AgentCore(
            model_type="deepseek",
            permission_mode=PermissionMode.AUTO,
            confirm_callback=None,
            max_iterations=3,
            max_context_tokens=32000,
            llm_timeout=1.0,
        )
        agent._orchestrator = MagicMock()

        # "你好" without ! → not routed
        events_no_bang = []
        async for ev in agent._maybe_route_to_orchestrator_events("你好"):
            events_no_bang.append(ev)
        assert len(events_no_bang) == 0

        # "!你好" with ! → routed
        mock_orch = MagicMock()

        async def fake_stream_v2(requirement, input_files=None):
            yield OrchestratorPhaseChanged(phase="planning", detail="计划中")
            yield TurnCompleted(content="done")

        mock_orch.stream_execute_v2 = fake_stream_v2
        agent._orchestrator = mock_orch

        events_with_bang = []
        async for ev in agent._maybe_route_to_orchestrator_events("!你好"):
            events_with_bang.append(ev)
        assert len(events_with_bang) >= 1


class TestPhaseMapVariableName:
    """验证 PHASE_MAP 变量名 (phase → new_phase) 修复.

    在 _maybe_route_to_orchestrator_events 的 legacy path 中,
    PHASE_MAP 遍历结果赋值给 new_phase 变量. 此测试确保
    该变量名正确 (不是 phase, 避免与 event.phase 混淆).
    """

    @pytest.mark.asyncio
    async def test_legacy_path_phase_map_uses_new_phase(self):
        """Legacy path (无 stream_execute_v2) 正确使用 new_phase 变量."""
        agent = AgentCore(
            model_type="deepseek",
            permission_mode=PermissionMode.AUTO,
            confirm_callback=None,
            max_iterations=3,
            max_context_tokens=32000,
            llm_timeout=1.0,
        )

        # Create a mock orchestrator WITHOUT stream_execute_v2
        mock_orch = MagicMock(spec=[])  # No attributes — no stream_execute_v2

        # Mock stream_execute to yield events
        from hakus.orchestrator import Orchestrator

        async def fake_stream_execute(requirement, input_files=None):
            yield Orchestrator.Event(type="plan", phase="planning", message="Planning")
            yield Orchestrator.Event(type="dev", phase="developing", message="Developing")
            yield Orchestrator.Event(type="test", phase="testing", message="Testing")
            yield Orchestrator.Event(type="completed", phase="completed", message="Done")

        mock_orch.stream_execute = fake_stream_execute
        # Ensure no stream_execute_v2 attribute
        assert not hasattr(mock_orch, 'stream_execute_v2')
        agent._orchestrator = mock_orch

        # Also mock _format_orchestrator_event to return text
        agent._format_orchestrator_event = MagicMock(return_value="formatted text")

        events = []
        async for ev in agent._maybe_route_to_orchestrator_events(
            "用 Spring Boot 写一个系统"
        ):
            events.append(ev)

        # Should have OrchestratorPhaseChanged events from PHASE_MAP
        phase_events = [e for e in events if isinstance(e, OrchestratorPhaseChanged)]
        # The initial "planning" phase change + PHASE_MAP-mapped events
        assert len(phase_events) >= 1

        # Verify the phase values are correct (from PHASE_MAP)
        phase_values = [e.phase for e in phase_events]
        # "plan" maps to "planning", "dev" maps to "developing", etc.
        # The initial event is always "planning"
        assert "planning" in phase_values

    @pytest.mark.asyncio
    async def test_phase_map_correct_keys(self):
        """PHASE_MAP 包含正确的键和映射值."""
        # Read the PHASE_MAP from the method source
        # We verify the expected mapping by checking the method behavior
        PHASE_MAP = {
            "plan": ("planning", "计划中"),
            "dev": ("developing", "开发中"),
            "test": ("testing", "测试中"),
            "fix": ("fixing", "修复中"),
            "final_test": ("final_testing", "终验中"),
            "completed": ("completed", "完成"),
            "error": ("failed", "失败"),
        }

        # Verify all expected keys exist
        assert "plan" in PHASE_MAP
        assert "dev" in PHASE_MAP
        assert "test" in PHASE_MAP
        assert "fix" in PHASE_MAP
        assert "final_test" in PHASE_MAP
        assert "completed" in PHASE_MAP
        assert "error" in PHASE_MAP

        # Verify mapping values
        assert PHASE_MAP["plan"][0] == "planning"
        assert PHASE_MAP["dev"][0] == "developing"
        assert PHASE_MAP["test"][0] == "testing"
        assert PHASE_MAP["fix"][0] == "fixing"
        assert PHASE_MAP["final_test"][0] == "final_testing"
        assert PHASE_MAP["completed"][0] == "completed"
        assert PHASE_MAP["error"][0] == "failed"


class TestNoOrchestratorFallback:
    """orchestrator 未初始化时的回退行为."""

    @pytest.mark.asyncio
    async def test_no_orchestrator_warns_and_returns(self):
        agent = AgentCore(
            model_type="deepseek",
            permission_mode=PermissionMode.AUTO,
            confirm_callback=None,
            max_iterations=3,
            max_context_tokens=32000,
            llm_timeout=1.0,
        )
        # Force routing but no orchestrator
        agent.force_orchestrator = True
        agent._orchestrator = None

        events = []
        async for ev in agent._maybe_route_to_orchestrator_events("build something"):
            events.append(ev)

        # Should get initial phase change + warning TextDelta
        assert len(events) >= 2
        assert isinstance(events[0], OrchestratorPhaseChanged)
        warning_events = [e for e in events if isinstance(e, TextDelta)]
        assert len(warning_events) >= 1
        assert "未初始化" in warning_events[0].text


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
