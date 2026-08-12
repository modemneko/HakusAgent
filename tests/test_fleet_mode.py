from __future__ import annotations

import asyncio

import pytest

from hakus.fleet.experience_store import ExperienceStore
from hakus.fleet.expert_factory import ExpertSpec
from hakus.fleet.scheduler import ParallelScheduler, ScheduledTask, TaskStatus


def test_expert_spec_accepts_timeout_and_file_scope_aliases() -> None:
    spec = ExpertSpec.from_dict(
        {
            "id": "expert-1",
            "role": "Frontend/Dev",
            "task": "Update the chat view",
            "tools": ["dev"],
            "timeout": 42,
            "files": "frontend/client/src/components/chat/ChatView.tsx",
        }
    )

    assert spec.timeout == 42
    assert spec.file_scope == ["frontend/client/src/components/chat/ChatView.tsx"]


@pytest.mark.asyncio
async def test_scheduler_serializes_tasks_with_same_lock() -> None:
    scheduler = ParallelScheduler(concurrency=2)

    async def executor(task: ScheduledTask) -> str:
        await asyncio.sleep(0.01)
        return task.id

    results = await scheduler.schedule_all(
        [
            ScheduledTask(id="a", role="dev", description="one", lock_keys=["same"]),
            ScheduledTask(id="b", role="dev", description="two", lock_keys=["same"]),
        ],
        executor,
    )

    assert [result.status for result in results] == [
        TaskStatus.COMPLETED,
        TaskStatus.COMPLETED,
    ]
    assert scheduler.stats.parallelism_used == 1


@pytest.mark.asyncio
async def test_scheduler_runs_different_locks_in_parallel() -> None:
    scheduler = ParallelScheduler(concurrency=2)

    async def executor(task: ScheduledTask) -> str:
        await asyncio.sleep(0.01)
        return task.id

    results = await scheduler.schedule_all(
        [
            ScheduledTask(id="a", role="dev", description="one", lock_keys=["one"]),
            ScheduledTask(id="b", role="dev", description="two", lock_keys=["two"]),
        ],
        executor,
    )

    assert [result.status for result in results] == [
        TaskStatus.COMPLETED,
        TaskStatus.COMPLETED,
    ]
    assert scheduler.stats.parallelism_used == 2


@pytest.mark.asyncio
async def test_scheduler_counts_executor_failure_as_failed() -> None:
    scheduler = ParallelScheduler(concurrency=2)

    async def executor(task: ScheduledTask) -> str:
        raise RuntimeError("boom")

    results = await scheduler.schedule_all(
        [ScheduledTask(id="a", role="dev", description="one", max_retries=0)],
        executor,
    )

    assert results[0].status == TaskStatus.FAILED
    assert results[0].error == "boom"
    assert scheduler.stats.failed == 1


def test_experience_store_respects_hakus_home(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("HAKUS_HOME", str(tmp_path))

    store = ExperienceStore()

    assert store._path == str(tmp_path / "fleet_experience.json")
