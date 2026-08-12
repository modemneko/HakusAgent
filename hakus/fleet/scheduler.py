"""Parallel scheduler for Fleet expert tasks."""
from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class ScheduledTask:
    """A task managed by the parallel scheduler."""

    id: str
    role: str
    description: str
    tools: List[str] = field(default_factory=list)
    file_scope: List[str] = field(default_factory=list)
    lock_keys: List[str] = field(default_factory=list)
    timeout: int = 300
    priority: int = 1
    max_retries: int = 2
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    elapsed: float = 0.0
    retries: int = 0


@dataclass
class SchedulerStats:
    """Execution statistics for one scheduler run."""

    total: int = 0
    completed: int = 0
    failed: int = 0
    timeout: int = 0
    total_elapsed: float = 0.0
    parallelism_used: int = 0


class ParallelScheduler:
    """Run independent expert tasks with concurrency and file-scope locks."""

    def __init__(
        self,
        concurrency: int = 10,
        default_timeout: int = 300,
    ):
        self._concurrency = max(1, concurrency)
        self._default_timeout = default_timeout
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._stats = SchedulerStats()
        self._progress_callbacks: List[Callable[[ScheduledTask], None]] = []
        self._locks: Dict[str, asyncio.Lock] = {}
        self._running_count = 0

    def on_progress(self, callback: Callable[[ScheduledTask], None]) -> None:
        self._progress_callbacks.append(callback)

    def _notify(self, task: ScheduledTask) -> None:
        for callback in self._progress_callbacks:
            try:
                callback(task)
            except Exception:
                pass

    @contextlib.asynccontextmanager
    async def _task_locks(self, task: ScheduledTask) -> AsyncIterator[None]:
        keys = sorted({key for key in task.lock_keys if key})
        if not keys:
            yield
            return

        async with contextlib.AsyncExitStack() as stack:
            for key in keys:
                lock = self._locks.setdefault(key, asyncio.Lock())
                await stack.enter_async_context(lock)
            yield

    async def _execute_one(
        self,
        task: ScheduledTask,
        executor: Callable[[ScheduledTask], Awaitable[str]],
    ) -> ScheduledTask:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._concurrency)

        if task.timeout <= 0:
            task.timeout = self._default_timeout

        for attempt in range(task.max_retries + 1):
            retry_delay: Optional[int] = None
            async with self._task_locks(task):
                async with self._semaphore:
                    task.status = TaskStatus.RUNNING
                    task.retries = attempt
                    self._notify(task)

                    start = time.time()
                    self._running_count += 1
                    self._stats.parallelism_used = max(
                        self._stats.parallelism_used,
                        self._running_count,
                    )

                    try:
                        result = await asyncio.wait_for(
                            executor(task),
                            timeout=task.timeout,
                        )
                    except asyncio.TimeoutError:
                        task.elapsed = time.time() - start
                        task.error = f"Timeout after {task.timeout}s"
                        if attempt < task.max_retries:
                            logger.warning(
                                f"Task {task.id} ({task.role}) timeout, "
                                f"retrying ({attempt + 1}/{task.max_retries})"
                            )
                            retry_delay = 2 ** attempt
                        else:
                            task.status = TaskStatus.TIMEOUT
                            self._stats.timeout += 1
                            self._notify(task)
                            return task
                    except Exception as exc:
                        task.elapsed = time.time() - start
                        task.error = str(exc)
                        if attempt < task.max_retries:
                            logger.warning(
                                f"Task {task.id} ({task.role}) failed: {exc}, "
                                f"retrying ({attempt + 1}/{task.max_retries})"
                            )
                            retry_delay = 2 ** attempt
                        else:
                            task.status = TaskStatus.FAILED
                            self._stats.failed += 1
                            self._notify(task)
                            return task
                    else:
                        task.result = result
                        task.status = TaskStatus.COMPLETED
                        task.elapsed = time.time() - start
                        self._stats.completed += 1
                        self._notify(task)
                        return task
                    finally:
                        self._running_count -= 1

            if retry_delay is not None:
                await asyncio.sleep(retry_delay)

        return task

    async def schedule_all(
        self,
        tasks: List[ScheduledTask],
        executor: Callable[[ScheduledTask], Awaitable[str]],
    ) -> List[ScheduledTask]:
        self._stats = SchedulerStats(total=len(tasks))
        self._semaphore = asyncio.Semaphore(self._concurrency)
        self._running_count = 0

        logger.info(
            f"ParallelScheduler: scheduling {len(tasks)} tasks, "
            f"concurrency={self._concurrency}"
        )

        sorted_tasks = sorted(tasks, key=lambda task: task.priority)
        results = await asyncio.gather(
            *[self._execute_one(task, executor) for task in sorted_tasks],
            return_exceptions=False,
        )

        self._stats.total_elapsed = sum(task.elapsed for task in results)
        logger.info(
            f"ParallelScheduler done: {self._stats.completed} completed, "
            f"{self._stats.failed} failed, {self._stats.timeout} timeout, "
            f"peak_parallelism={self._stats.parallelism_used}, "
            f"total {self._stats.total_elapsed:.1f}s"
        )

        return list(results)

    @property
    def stats(self) -> SchedulerStats:
        return self._stats
