from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hakus.orchestrator import Orchestrator, OrchestratorConfig, OrchestratorProgressEvent
from hakus.protocol.events import ToolCallFinished
from hakus.task_board import TaskStatus
from src.hakusai_server.agent_bridge import _extract_benchmark_output_dir


class _FakeRootAgent:
    def __init__(self) -> None:
        self._context = MagicMock()


class _PassingTester:
    agent_type = "tester"
    agent_id = "tester-1"

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def create(self, prompt, context):
        return self.agent_id

    async def stream_run(self, timeout=None):
        yield ToolCallFinished(
            call_id=self.agent_id,
            name="tester",
            result="PASS",
            success=True,
            duration=0.1,
        )

    def parse_result(self, content):
        return {"status": "PASS", "issues": []}


class _PassingDev:
    agent_type = "dev"
    agent_id = "dev-1"

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def create(self, prompt, context):
        return self.agent_id

    async def stream_run(self, timeout=None):
        yield ToolCallFinished(
            call_id=self.agent_id,
            name="dev",
            result="development complete",
            success=True,
            duration=0.1,
        )


class _ResumableDev(_PassingDev):
    def __init__(self) -> None:
        self.resume_calls = 0

    async def resume(self, prompt, context):
        self.resume_calls += 1


class _FailThenPassTester:
    agent_type = "tester"
    agent_id = "tester-fail-then-pass"
    calls = 0

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def create(self, prompt, context):
        return self.agent_id

    async def stream_run(self, timeout=None):
        type(self).calls += 1
        result = "FAIL" if type(self).calls == 1 else "PASS"
        yield ToolCallFinished(
            call_id=self.agent_id,
            name="tester",
            result=result,
            success=True,
            duration=0.1,
        )

    def parse_result(self, content):
        if "PASS" in content:
            return {"status": "PASS", "issues": []}
        return {"status": "FAIL", "issues": ["still broken"]}


@pytest.mark.asyncio
async def test_legacy_test_loop_returns_immediately_after_pass(tmp_path) -> None:
    orch = Orchestrator(
        root_agent=_FakeRootAgent(),
        workspace_dir=str(tmp_path),
        config=OrchestratorConfig(max_fix_rounds=3, use_multi_dim_test=False),
    )
    task = orch.task_board.add_task("Implement parser", "Create parser and tests")

    with patch("hakus.orchestrator.TesterAgent", _PassingTester):
        events = [
            item
            async for item in orch._stream_test_and_fix_loop_legacy(task, dev_agent=MagicMock())
        ]

    progress = [event for event in events if isinstance(event, OrchestratorProgressEvent)]
    assert progress[-1].phase == "completed"
    assert "PASS" in progress[-1].message
    assert orch.task_board.get_task(task.id).status == TaskStatus.COMPLETED
    assert all(getattr(event, "phase", None) != "fixing" for event in events)


@pytest.mark.asyncio
async def test_legacy_test_loop_retests_after_one_fix_round(tmp_path) -> None:
    orch = Orchestrator(
        root_agent=_FakeRootAgent(),
        workspace_dir=str(tmp_path),
        config=OrchestratorConfig(max_fix_rounds=1, use_multi_dim_test=False),
    )
    task = orch.task_board.add_task("Implement parser", "Create parser and tests")
    dev_agent = _ResumableDev()
    _FailThenPassTester.calls = 0

    with patch("hakus.orchestrator.TesterAgent", _FailThenPassTester):
        events = [
            item
            async for item in orch._stream_test_and_fix_loop_legacy(task, dev_agent=dev_agent)
        ]

    progress = [event for event in events if isinstance(event, OrchestratorProgressEvent)]
    assert _FailThenPassTester.calls == 2
    assert dev_agent.resume_calls == 1
    assert progress[-1].phase == "completed"
    assert orch.task_board.get_task(task.id).status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_final_test_can_be_skipped_by_config(tmp_path) -> None:
    orch = Orchestrator(
        root_agent=_FakeRootAgent(),
        workspace_dir=str(tmp_path),
        config=OrchestratorConfig(enable_final_test=False),
    )

    events = [item async for item in orch._stream_phase_final_test()]

    assert len(events) == 1
    assert isinstance(events[0], OrchestratorProgressEvent)
    assert events[0].phase == "completed"
    assert "skipped" in events[0].message.lower()


def test_benchmark_output_dir_is_extracted_from_isolation_prompt() -> None:
    prompt = (
        "Benchmark isolation rules:\n"
        "- Only create or modify files under this output directory: E:\\Test\\benchmark\\run_x\\deep\\bugfix-01\n"
        "- Do not modify unrelated files.\n"
    )

    assert _extract_benchmark_output_dir(prompt) == "E:\\Test\\benchmark\\run_x\\deep\\bugfix-01"


@pytest.mark.asyncio
async def test_single_task_deep_clears_stale_task_board_and_finishes(tmp_path) -> None:
    orch = Orchestrator(
        root_agent=_FakeRootAgent(),
        workspace_dir=str(tmp_path),
        config=OrchestratorConfig(
            max_fix_rounds=1,
            use_multi_dim_test=False,
            enable_final_test=False,
        ),
    )
    orch.task_board.add_task("stale repo task", "must not run")

    with (
        patch("hakus.orchestrator.DevAgent", _PassingDev),
        patch("hakus.orchestrator.TesterAgent", _PassingTester),
    ):
        events = [
            item
            async for item in orch.stream_execute_single_task(
                "Fix the isolated benchmark task",
                title="Benchmark isolated task",
            )
        ]

    assert events[-1].type == "done"
    assert events[-1].success is True
    assert len(orch.task_board._tasks) == 1
    task = next(iter(orch.task_board._tasks.values()))
    assert task.title == "Benchmark isolated task"
    assert task.status == TaskStatus.COMPLETED
    assert (tmp_path / "doc" / "plan.md").exists()


@pytest.mark.asyncio
async def test_deterministic_verifier_marks_pytest_pass_as_completed(tmp_path) -> None:
    (tmp_path / "test_sample.py").write_text(
        "def test_ok():\n    assert 1 + 1 == 2\n",
        encoding="utf-8",
    )
    orch = Orchestrator(
        root_agent=_FakeRootAgent(),
        workspace_dir=str(tmp_path),
        config=OrchestratorConfig(
            max_fix_rounds=1,
            use_deterministic_verifier=True,
        ),
    )
    orch.workspace.initialize()
    task = orch.task_board.add_task("Run verifier", "Run pytest")

    events = [
        item
        async for item in orch._stream_deterministic_verify_and_fix_loop(
            task, dev_agent=_ResumableDev()
        )
    ]

    progress = [event for event in events if isinstance(event, OrchestratorProgressEvent)]
    assert progress[-1].phase == "completed"
    assert orch.task_board.get_task(task.id).status == TaskStatus.COMPLETED
