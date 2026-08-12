"""Orchestrator fix 环 resume_failed_dimensions 调用测试."""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hakus.orchestrator import Orchestrator, OrchestratorConfig
from hakus.multi_dim_test import DimensionResult


class _FakeAgent:
    def __init__(self):
        self._context = MagicMock()


@pytest.mark.asyncio
async def test_fix_loop_uses_resume_after_first_round(tmp_path):
    orch = Orchestrator(
        root_agent=_FakeAgent(),
        workspace_dir=str(tmp_path),
        config=OrchestratorConfig(max_fix_rounds=2, use_multi_dim_test=True),
    )

    run_parallel = AsyncMock(return_value={
        "layout": DimensionResult(dimension="layout", status="FAIL", issues=["a"]),
        "beauty": DimensionResult(dimension="beauty", status="PASS"),
    })
    resume_failed = AsyncMock(return_value={
        "layout": DimensionResult(dimension="layout", status="PASS"),
        "beauty": DimensionResult(dimension="beauty", status="PASS"),
    })

    dev_agent = MagicMock()
    dev_agent.resume = AsyncMock()
    dev_agent.run = AsyncMock(return_value=MagicMock(success=True, content="ok"))

    from hakus.task_board import Task, TaskStatus
    task = Task(id="t1", title="Test task", description="desc", status=TaskStatus.PENDING)

    with patch("hakus.orchestrator.MultiDimTestCoordinator") as MockCoord:
        coord = MockCoord.return_value
        coord.run_parallel = run_parallel
        coord.resume_failed_dimensions = resume_failed
        coord.summarize.side_effect = [
            (False, ["beauty"], ["layout"], []),
            (True, ["layout", "beauty"], [], []),
        ]

        ok = await orch._test_and_fix_loop_multi_dim(task, dev_agent)

    assert ok is True
    run_parallel.assert_called_once()
    resume_failed.assert_called_once()
    dev_agent.resume.assert_called_once()
