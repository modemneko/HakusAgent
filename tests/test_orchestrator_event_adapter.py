"""SubTask 9.4: OrchestratorEventAdapter 事件映射单元测试.

覆盖:
- "phase" 内部事件 → OrchestratorPhaseChanged
- "checkpoint" 内部事件 → CheckpointSaved 含正确字段
- task_progress 事件 → TaskProgressEvent 含 completed/total/current_task
- "message"/"log" 内部事件 → TextDelta
- "done" 内部事件 → TurnCompleted
- "error" 内部事件 → TurnFailed
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hakus.orchestrator import Orchestrator, OrchestratorEventAdapter
from hakus.protocol.events import (
    OrchestratorPhaseChanged,
    CheckpointSaved,
    TaskProgressEvent,
    TextDelta,
    TurnCompleted,
    TurnFailed,
    ToolCallStarted,
    ToolCallFinished,
    TokenUsage,
)


def _make_event(**kwargs):
    """Helper to create an Orchestrator.Event."""
    return Orchestrator.Event(**kwargs)


class TestPhaseEventMapping:
    """'phase' 内部事件 → OrchestratorPhaseChanged."""

    def test_phase_maps_to_orchestrator_phase_changed(self):
        adapter = OrchestratorEventAdapter()
        ev = _make_event(type="phase", phase="planning", message="计划中")
        result = adapter.adapt(ev)
        assert isinstance(result, OrchestratorPhaseChanged)

    def test_phase_event_carries_from_and_to(self):
        adapter = OrchestratorEventAdapter(previous_phase="idle")
        ev = _make_event(type="phase", phase="planning", message="开始计划")
        result = adapter.adapt(ev)
        assert result.from_phase == "idle"
        assert result.to_phase == "planning"

    def test_phase_event_updates_previous_phase(self):
        adapter = OrchestratorEventAdapter(previous_phase="idle")
        # First phase change
        ev1 = _make_event(type="phase", phase="planning", message="计划中")
        result1 = adapter.adapt(ev1)
        assert result1.from_phase == "idle"
        assert result1.to_phase == "planning"

        # Second phase change — from_phase should now be "planning"
        ev2 = _make_event(type="phase", phase="developing", message="开发中")
        result2 = adapter.adapt(ev2)
        assert result2.from_phase == "planning"
        assert result2.to_phase == "developing"

    def test_phase_event_carries_detail(self):
        adapter = OrchestratorEventAdapter()
        ev = _make_event(type="phase", phase="testing", message="测试中")
        result = adapter.adapt(ev)
        assert result.detail == "测试中"


class TestCheckpointEventMapping:
    """'checkpoint' 内部事件 → CheckpointSaved 含正确字段."""

    def test_checkpoint_maps_to_checkpoint_saved(self):
        adapter = OrchestratorEventAdapter()
        ev = _make_event(
            type="checkpoint",
            payload={
                "checkpoint_path": "/workspace/.orchestrator-checkpoint.json",
                "phase": "developing",
                "task_id": "orch_001",
                "completed_tasks": 2,
                "total_tasks": 5,
                "timestamp": "260606 1430",
            },
        )
        result = adapter.adapt(ev)
        assert isinstance(result, CheckpointSaved)

    def test_checkpoint_event_fields(self):
        adapter = OrchestratorEventAdapter()
        ev = _make_event(
            type="checkpoint",
            payload={
                "checkpoint_path": "/ws/.checkpoint.json",
                "phase": "planning",
                "task_id": "t1",
                "completed_tasks": 3,
                "total_tasks": 10,
                "timestamp": "260606 1200",
            },
        )
        result = adapter.adapt(ev)
        assert result.checkpoint_path == "/ws/.checkpoint.json"
        assert result.phase == "planning"
        assert result.task_id == "t1"
        assert result.completed_tasks == 3
        assert result.total_tasks == 10
        assert result.timestamp == "260606 1200"


class TestTaskProgressEventMapping:
    """task_progress 事件 → TaskProgressEvent 含 completed/total/current_task."""

    def test_task_progress_maps_correctly(self):
        adapter = OrchestratorEventAdapter()
        ev = _make_event(
            type="task_progress",
            message="2/5 done",
            payload={
                "completed": 2,
                "total": 5,
                "current_task": "Implement login",
            },
        )
        result = adapter.adapt(ev)
        assert isinstance(result, TaskProgressEvent)
        assert result.completed == 2
        assert result.total == 5
        assert result.current_task == "Implement login"

    def test_task_progress_includes_phase(self):
        adapter = OrchestratorEventAdapter(previous_phase="developing")
        ev = _make_event(
            type="task_progress",
            payload={"completed": 1, "total": 3, "current_task": "Task 2"},
        )
        result = adapter.adapt(ev)
        assert result.phase == "developing"

    def test_task_progress_defaults(self):
        adapter = OrchestratorEventAdapter()
        ev = _make_event(type="task_progress", payload={})
        result = adapter.adapt(ev)
        assert result.completed == 0
        assert result.total == 0
        assert result.current_task == ""


class TestLogEventMapping:
    """'message'/'log' 内部事件 → TextDelta."""

    def test_log_maps_to_text_delta(self):
        adapter = OrchestratorEventAdapter()
        ev = _make_event(type="log", message="Starting planner")
        result = adapter.adapt(ev)
        assert isinstance(result, TextDelta)
        assert result.text == "Starting planner"

    def test_log_with_empty_message(self):
        adapter = OrchestratorEventAdapter()
        ev = _make_event(type="log", message="")
        result = adapter.adapt(ev)
        assert isinstance(result, TextDelta)
        assert result.text == ""


class TestDoneEventMapping:
    """'done' 内部事件 → TurnCompleted."""

    def test_done_maps_to_turn_completed(self):
        adapter = OrchestratorEventAdapter()
        ev = _make_event(type="done", message="All tasks completed")
        result = adapter.adapt(ev)
        assert isinstance(result, TurnCompleted)
        assert result.content == "All tasks completed"

    def test_done_with_empty_message(self):
        adapter = OrchestratorEventAdapter()
        ev = _make_event(type="done", message="")
        result = adapter.adapt(ev)
        assert isinstance(result, TurnCompleted)
        assert result.content == ""


class TestErrorEventMapping:
    """'error' 内部事件 → TurnFailed."""

    def test_error_maps_to_turn_failed(self):
        adapter = OrchestratorEventAdapter()
        ev = _make_event(type="error", error="Something went wrong")
        result = adapter.adapt(ev)
        assert isinstance(result, TurnFailed)
        assert result.error == "Something went wrong"

    def test_error_code_is_orchestrator_error(self):
        adapter = OrchestratorEventAdapter()
        ev = _make_event(type="error", error="boom")
        result = adapter.adapt(ev)
        assert result.code == "orchestrator_error"

    def test_error_with_no_message(self):
        adapter = OrchestratorEventAdapter()
        ev = _make_event(type="error", error="")
        result = adapter.adapt(ev)
        assert isinstance(result, TurnFailed)
        assert result.error == "Unknown error"  # fallback


class TestOtherEventMappings:
    """agent_start, agent_done, token_usage 事件映射."""

    def test_agent_start_maps_to_tool_call_started(self):
        adapter = OrchestratorEventAdapter()
        ev = _make_event(type="agent_start", agent_type="dev", task_id="t1")
        result = adapter.adapt(ev)
        assert isinstance(result, ToolCallStarted)
        assert result.name == "dev"

    def test_agent_done_maps_to_tool_call_finished(self):
        adapter = OrchestratorEventAdapter()
        ev = _make_event(
            type="agent_done", agent_type="dev", task_id="t1",
            success=True, message="Done",
        )
        result = adapter.adapt(ev)
        assert isinstance(result, ToolCallFinished)
        assert result.success is True

    def test_token_usage_maps_correctly(self):
        adapter = OrchestratorEventAdapter()
        ev = _make_event(type="token_usage", input_tokens=100, output_tokens=200)
        result = adapter.adapt(ev)
        assert isinstance(result, TokenUsage)
        assert result.input_tokens == 100
        assert result.output_tokens == 200

    def test_unknown_type_falls_back_to_text_delta(self):
        adapter = OrchestratorEventAdapter()
        ev = _make_event(type="unknown_type", message="fallback text")
        result = adapter.adapt(ev)
        assert isinstance(result, TextDelta)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
