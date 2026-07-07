import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncIterator, Dict, List, Optional, Any, Tuple

from .protocol.events import AgentEvent, ToolCallFinished
from .sub_agents import (
    DimensionTesterAgent,
    LayoutTesterAgent,
    BeautyTesterAgent,
    AnimationTesterAgent,
    SecurityTesterAgent,
    PerformanceTesterAgent,
    AccessibilityTesterAgent,
    SubAgentOutput,
    TestDimension,
)
from utils.logger import get_logger

logger = get_logger(__name__)


DIMENSION_AGENT_CLASSES: Dict[str, type] = {
    TestDimension.LAYOUT: LayoutTesterAgent,
    TestDimension.BEAUTY: BeautyTesterAgent,
    TestDimension.ANIMATION: AnimationTesterAgent,
    TestDimension.SECURITY: SecurityTesterAgent,
    TestDimension.PERFORMANCE: PerformanceTesterAgent,
    TestDimension.ACCESSIBILITY: AccessibilityTesterAgent,
}


@dataclass
class DimensionResult:
    dimension: str
    status: str = "PENDING"
    report_path: str = ""
    issues: List[str] = field(default_factory=list)
    issue_count: int = 0
    agent_id: Optional[str] = None
    elapsed: float = 0.0
    raw_output: str = ""
    error: Optional[str] = None

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    @property
    def failed(self) -> bool:
        return self.status == "FAIL"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension,
            "status": self.status,
            "report_path": self.report_path,
            "issues": list(self.issues),
            "issue_count": self.issue_count,
            "agent_id": self.agent_id,
            "elapsed": self.elapsed,
            "error": self.error,
        }


class MultiDimTestCoordinator:
    def __init__(
        self,
        parent_agent,
        dimensions: Optional[List[str]] = None,
        max_concurrent: int = 3,
        per_test_timeout: int = 600,
    ):
        self._parent = parent_agent
        self._dimensions = dimensions or TestDimension.DEFAULT_TRIPLE
        self._max_concurrent = max(1, min(max_concurrent, len(self._dimensions)))
        self._per_test_timeout = per_test_timeout
        self._semaphore = asyncio.Semaphore(self._max_concurrent)
        self._live_agents: Dict[str, DimensionTesterAgent] = {}
        self._dim_agents: Dict[str, DimensionTesterAgent] = {}

    @property
    def dimensions(self) -> List[str]:
        return list(self._dimensions)

    def stamp_now(self) -> str:
        return datetime.now().strftime("%y%m%d %H:%M")

    def log(self, message: str, level: str = "INFO") -> None:
        log_fn = {
            "INFO": logger.info,
            "WARNING": logger.warning,
            "ERROR": logger.error,
            "DEBUG": logger.debug,
        }.get(level, logger.info)
        log_fn(message)

    def make_agent(self, dimension: str) -> DimensionTesterAgent:
        cls = DIMENSION_AGENT_CLASSES.get(dimension)
        if cls is None:
            raise ValueError(f"No agent class for dimension: {dimension}")
        return cls(self._parent)

    async def _run_one(
        self,
        dimension: str,
        task_description: str,
        context: Dict[str, Any],
    ) -> DimensionResult:
        result = DimensionResult(dimension=dimension)
        async with self._semaphore:
            tester = self.make_agent(dimension)
            try:
                agent_id = await tester.create(task_description, context)
                result.agent_id = agent_id
                self._live_agents[agent_id] = tester
                self._dim_agents[dimension] = tester

                start = time.time()
                output = await tester.run(timeout=self._per_test_timeout)
                result.elapsed = time.time() - start
                result.raw_output = output.content if output.success else ""

                if not output.success:
                    result.status = "ERROR"
                    result.error = output.error
                    self.log(f"[{dimension}] agent error: {output.error}", "ERROR")
                    return result

                parsed = tester.parse_result(output.content)
                result.status = parsed.get("status", "UNKNOWN")
                result.report_path = parsed.get("report_path", "")
                result.issue_count = parsed.get("issue_count", 0)
                result.issues = parsed.get("issues", [])
                self.log(
                    f"[{dimension}] {result.status} issues={result.issue_count} "
                    f"elapsed={result.elapsed:.1f}s report={result.report_path}"
                )
                return result
            except Exception as e:
                result.status = "ERROR"
                result.error = str(e)
                self.log(f"[{dimension}] exception: {e}", "ERROR")
                return result
            finally:
                if result.agent_id and result.agent_id in self._live_agents:
                    del self._live_agents[result.agent_id]

    async def run_parallel(
        self,
        task_description: str,
        context: Dict[str, Any],
    ) -> Dict[str, DimensionResult]:
        context = dict(context)
        context.setdefault("concurrency_limit", self._max_concurrent)
        context.setdefault("test_dimensions", self._dimensions)

        coros = [
            self._run_one(d, task_description, context) for d in self._dimensions
        ]
        results = await asyncio.gather(*coros, return_exceptions=False)
        return {r.dimension: r for r in results}

    async def resume_failed_dimensions(
        self,
        previous: Dict[str, DimensionResult],
        task_description: str,
        context: Dict[str, Any],
    ) -> Dict[str, DimensionResult]:
        failed = [d for d, r in previous.items() if r.failed or r.status == "ERROR"]
        if not failed:
            return previous

        new_results: Dict[str, DimensionResult] = dict(previous)
        for dim in failed:
            old_agent = self._dim_agents.get(dim)
            if old_agent is None:
                old_agent = self.make_agent(dim)
            try:
                prompt = self._build_resume_prompt(dim, previous[dim], context)
                await old_agent.resume(prompt, context)
                start = time.time()
                out = await old_agent.run(timeout=self._per_test_timeout)
                elapsed = time.time() - start

                dr = DimensionResult(dimension=dim)
                dr.agent_id = old_agent.agent_id
                dr.elapsed = elapsed
                dr.raw_output = out.content if out.success else ""
                if not out.success:
                    dr.status = "ERROR"
                    dr.error = out.error
                else:
                    parsed = old_agent.parse_result(out.content)
                    dr.status = parsed.get("status", "UNKNOWN")
                    dr.report_path = parsed.get("report_path", "")
                    dr.issue_count = parsed.get("issue_count", 0)
                    dr.issues = parsed.get("issues", [])
                new_results[dim] = dr
                self.log(
                    f"[{dim}] resume -> {dr.status} issues={dr.issue_count} "
                    f"elapsed={dr.elapsed:.1f}s"
                )
            except Exception as e:
                dr = DimensionResult(dimension=dim)
                dr.status = "ERROR"
                dr.error = str(e)
                new_results[dim] = dr
                self.log(f"[{dim}] resume exception: {e}", "ERROR")
        return new_results

    def _build_resume_prompt(
        self,
        dimension: str,
        previous: DimensionResult,
        context: Dict[str, Any],
    ) -> str:
        issues_text = "\n".join(f"- {i}" for i in previous.issues) or "- (无明确条目)"
        return (
            f"第 {context.get('fix_round', 1)} 轮修正：开发智能体已根据 {dimension} 维度的反馈修改代码。\n"
            f"请重新测试 {context.get('target', '')} 并验证上轮问题是否已修复。\n\n"
            f"上轮问题清单：\n{issues_text}\n\n"
            f"测试报告路径: {previous.report_path or '(待写入)'}\n"
            f"输出格式: RESULT: PASS/FAIL，报告路径: <path>，问题数: N"
        )

    def summarize(
        self,
        results: Dict[str, DimensionResult],
    ) -> Tuple[bool, List[str], List[str], List[str]]:
        passed: List[str] = []
        failed: List[str] = []
        errored: List[str] = []
        for d, r in results.items():
            if r.passed:
                passed.append(d)
            elif r.status == "ERROR":
                errored.append(d)
            else:
                failed.append(d)
        all_pass = len(failed) == 0 and len(errored) == 0
        return all_pass, passed, failed, errored

    # ---- Streaming variants ----

    async def _stream_run_one(
        self,
        dimension: str,
        task_description: str,
        context: Dict[str, Any],
        event_queue: asyncio.Queue,
    ) -> None:
        """Run a single dimension tester with stream_run, put events into *event_queue*.

        Queue items are tuples:
            ("event", dimension, AgentEvent)   – forwarded stream event
            ("done",  dimension, DimensionResult) – tester finished
        """
        tester = self.make_agent(dimension)
        result = DimensionResult(dimension=dimension)
        try:
            agent_id = await tester.create(task_description, context)
            result.agent_id = agent_id
            self._live_agents[agent_id] = tester
            self._dim_agents[dimension] = tester

            start = time.time()
            final_output: Optional[SubAgentOutput] = None
            async for event in tester.stream_run(timeout=self._per_test_timeout):
                await event_queue.put(("event", dimension, event))
                if isinstance(event, ToolCallFinished):
                    final_output = SubAgentOutput(
                        agent_type=tester.agent_type,
                        agent_id=tester.agent_id or "",
                        task_id="",
                        content=event.result or "",
                        success=event.success,
                        execution_time=event.duration,
                    )

            result.elapsed = time.time() - start
            result.raw_output = (
                final_output.content if final_output and final_output.success else ""
            )

            if not final_output or not final_output.success:
                result.status = "ERROR"
                result.error = (
                    final_output.error if final_output else "No output"
                )
                self.log(
                    f"[{dimension}] agent error: {result.error}", "ERROR"
                )
            else:
                parsed = tester.parse_result(final_output.content)
                result.status = parsed.get("status", "UNKNOWN")
                result.report_path = parsed.get("report_path", "")
                result.issue_count = parsed.get("issue_count", 0)
                result.issues = parsed.get("issues", [])
                self.log(
                    f"[{dimension}] {result.status} issues={result.issue_count} "
                    f"elapsed={result.elapsed:.1f}s report={result.report_path}"
                )
        except Exception as e:
            result.status = "ERROR"
            result.error = str(e)
            self.log(f"[{dimension}] exception: {e}", "ERROR")
        finally:
            if result.agent_id and result.agent_id in self._live_agents:
                del self._live_agents[result.agent_id]

        await event_queue.put(("done", dimension, result))

    async def stream_run_parallel(
        self,
        task_description: str,
        context: Dict[str, Any],
        results_out: Dict[str, DimensionResult],
    ) -> AsyncIterator[AgentEvent]:
        """Run all dimension testers concurrently, yield AgentEvent objects.

        Populates *results_out* with ``{dimension: DimensionResult}`` when
        each tester finishes.
        """
        context = dict(context)
        context.setdefault("concurrency_limit", self._max_concurrent)
        context.setdefault("test_dimensions", self._dimensions)

        event_queue: asyncio.Queue = asyncio.Queue()
        tasks = []

        async def _guarded(d: str) -> None:
            async with self._semaphore:
                await self._stream_run_one(
                    d, task_description, context, event_queue
                )

        for d in self._dimensions:
            tasks.append(asyncio.create_task(_guarded(d)))

        done_count = 0
        total = len(tasks)

        while done_count < total:
            item = await event_queue.get()
            if item[0] == "event":
                yield item[2]  # AgentEvent
            elif item[0] == "done":
                _, dimension, result = item
                results_out[dimension] = result
                done_count += 1

        await asyncio.gather(*tasks, return_exceptions=True)

    async def stream_resume_failed_dimensions(
        self,
        previous: Dict[str, DimensionResult],
        task_description: str,
        context: Dict[str, Any],
        results_out: Dict[str, DimensionResult],
    ) -> AsyncIterator[AgentEvent]:
        """Resume failed dimensions with streaming.

        Yields AgentEvent objects from the re-run testers.
        Populates *results_out* with updated results (passed dimensions
        are copied from *previous*).
        """
        failed = [
            d for d, r in previous.items() if r.failed or r.status == "ERROR"
        ]
        # Copy passed results directly
        results_out.update(
            {d: r for d, r in previous.items() if d not in failed}
        )

        if not failed:
            return

        event_queue: asyncio.Queue = asyncio.Queue()
        tasks = []

        for dim in failed:
            old_agent = self._dim_agents.get(dim)
            if old_agent is None:
                old_agent = self.make_agent(dim)

            async def _resume_one(
                d: str = dim, agent: DimensionTesterAgent = old_agent
            ) -> None:
                prompt = self._build_resume_prompt(d, previous[d], context)
                await agent.resume(prompt, context)

                start = time.time()
                final_output: Optional[SubAgentOutput] = None
                async for event in agent.stream_run(
                    timeout=self._per_test_timeout
                ):
                    await event_queue.put(("event", d, event))
                    if isinstance(event, ToolCallFinished):
                        final_output = SubAgentOutput(
                            agent_type=agent.agent_type,
                            agent_id=agent.agent_id or "",
                            task_id="",
                            content=event.result or "",
                            success=event.success,
                            execution_time=event.duration,
                        )

                dr = DimensionResult(dimension=d)
                dr.agent_id = agent.agent_id
                dr.elapsed = time.time() - start
                dr.raw_output = (
                    final_output.content
                    if final_output and final_output.success
                    else ""
                )

                if not final_output or not final_output.success:
                    dr.status = "ERROR"
                    dr.error = (
                        final_output.error if final_output else "No output"
                    )
                else:
                    parsed = agent.parse_result(final_output.content)
                    dr.status = parsed.get("status", "UNKNOWN")
                    dr.report_path = parsed.get("report_path", "")
                    dr.issue_count = parsed.get("issue_count", 0)
                    dr.issues = parsed.get("issues", [])

                self.log(
                    f"[{d}] resume -> {dr.status} issues={dr.issue_count} "
                    f"elapsed={dr.elapsed:.1f}s"
                )
                await event_queue.put(("done", d, dr))

            tasks.append(asyncio.create_task(_resume_one()))

        done_count = 0
        total = len(tasks)

        while done_count < total:
            item = await event_queue.get()
            if item[0] == "event":
                yield item[2]  # AgentEvent
            elif item[0] == "done":
                _, dimension, result = item
                results_out[dimension] = result
                done_count += 1

        await asyncio.gather(*tasks, return_exceptions=True)
