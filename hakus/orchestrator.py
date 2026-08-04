import asyncio
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from .agent import AgentCore, SubAgent
from .sub_agents import (
    DevAgent, TesterAgent, PlannerAgent, ResearcherAgent,
    BaseSubAgent, SubAgentOutput, create_sub_agent,
    TestDimension, DimensionTesterAgent,
)
from .multi_dim_test import (
    MultiDimTestCoordinator, DimensionResult, DIMENSION_AGENT_CLASSES,
)
from .task_board import TaskBoard, Task, TaskStatus, TaskPriority
from .workspace import Workspace
from .protocol.events import (
    AgentEvent, OrchestratorPhaseChanged, ActivityChanged,
    TaskProgressEvent, CheckpointSaved, TextDelta,
    ToolCallStarted, ToolCallFinished, TokenUsage,
    TurnCompleted, TurnFailed, Cancelled,
)
from .long_task_context import LongTaskContext, TaskSummary
from .heartbeat import WorkspaceHeartbeat
from .engine.stream_events import OrchestratorProgressEvent
from utils.config import BASE_CONFIG
from utils.logger import get_logger

logger = get_logger(__name__)

MAX_FIX_ROUNDS = 5
DEFAULT_BATCH_SIZE = 5
DEFAULT_MAX_RETRIES = 3
HEARTBEAT_INTERVAL = 30
DEFAULT_TEST_CONCURRENCY = 3
ORCHESTRATOR_HARD_RULES = (
    "## 主智能体硬约束（多智能体协同模式）\n"
    "1. 你只编排不干活 — 不直接编辑任何源代码/配置文件\n"
    "2. 任何代码变更必须委托给 DevAgent\n"
    "3. 任何质量审查必须委托给 DimensionTesterAgent（layout/beauty/animation/...）\n"
    "4. 失败重测只 resume 失败维度的 tester，不重建\n"
    "5. 保持上下文整洁 — 不读子智能体产出文件的内容，只接收路径和 PASS/FAIL\n"
    "6. 时间戳格式：yymmdd hhmm（如 260602 1430）\n"
)


class OrchestratorEventAdapter:
    """将 Orchestrator 内部 Event 转换为 AgentEvent 协议事件.

    内部 Event 类型 → 协议事件映射:
    - phase → OrchestratorPhaseChanged
    - agent_start → ToolCallStarted
    - agent_done → ToolCallFinished
    - task_progress → TaskProgressEvent
    - checkpoint → CheckpointSaved
    - log → TextDelta
    - token_usage → TokenUsage
    - done → TurnCompleted
    - error → TurnFailed
    """

    def __init__(self, previous_phase: str = "idle"):
        self._previous_phase = previous_phase

    def adapt(self, event: "Orchestrator.Event") -> AgentEvent:
        """将单个内部 Event 转换为 AgentEvent 协议事件."""
        etype = event.type

        if etype == "phase":
            new_phase = event.phase or "idle"
            old_phase = self._previous_phase
            self._previous_phase = new_phase
            return OrchestratorPhaseChanged(
                from_phase=old_phase,
                to_phase=new_phase,
                detail=event.message or "",
            )

        if etype == "agent_start":
            return ToolCallStarted(
                call_id=event.task_id or "",
                name=event.agent_type or "sub_agent",
            )

        if etype == "agent_done":
            return ToolCallFinished(
                call_id=event.task_id or "",
                name=event.agent_type or "sub_agent",
                result=event.message or "",
                success=event.success if event.success is not None else True,
                duration=float(event.payload.get("execution_time", 0.0) or 0.0),
            )

        if etype == "task_progress":
            return TaskProgressEvent(
                completed=event.payload.get("completed", 0),
                total=event.payload.get("total", 0),
                current_task=event.payload.get("current_task", ""),
                phase=self._previous_phase,
                detail=event.message or "",
            )

        if etype == "checkpoint":
            return CheckpointSaved(
                checkpoint_path=event.payload.get("checkpoint_path", ""),
                phase=event.payload.get("phase", ""),
                task_id=event.payload.get("task_id", ""),
                completed_tasks=event.payload.get("completed_tasks", 0),
                total_tasks=event.payload.get("total_tasks", 0),
                timestamp=event.payload.get("timestamp", ""),
            )

        if etype == "log":
            return TextDelta(text=event.message or "")

        if etype == "token_usage":
            return TokenUsage(
                input_tokens=event.input_tokens,
                output_tokens=event.output_tokens,
            )

        if etype == "done":
            return TurnCompleted(
                content=event.message or "",
            )

        if etype == "error":
            return TurnFailed(
                code="orchestrator_error",
                error=event.error or "Unknown error",
            )

        # Fallback: return as TextDelta
        return TextDelta(text=event.message or str(event))


class OrchestratorPhase(Enum):
    IDLE = "idle"
    PLANNING = "planning"
    DEVELOPING = "developing"
    TESTING = "testing"
    FIXING = "fixing"
    FINAL_TESTING = "final_testing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class OrchestratorConfig:
    batch_size: int = DEFAULT_BATCH_SIZE
    max_fix_rounds: int = MAX_FIX_ROUNDS
    max_retries: int = DEFAULT_MAX_RETRIES
    dev_timeout: int = 1800
    tester_timeout: int = 600
    planner_timeout: int = 900
    heartbeat_interval: int = HEARTBEAT_INTERVAL
    auto_recover: bool = True
    enable_final_test: bool = True
    use_deterministic_verifier: bool = False
    test_concurrency: int = DEFAULT_TEST_CONCURRENCY
    # DoomLoop 防护：连续 N 次失败（Dev 或 Tester）就放弃当前任务
    max_consecutive_failures: int = 3
    test_dimensions: List[str] = field(
        default_factory=lambda: list(TestDimension.DEFAULT_TRIPLE)
    )
    use_multi_dim_test: bool = True


@dataclass
class OrchestratorResult:
    task_id: str
    success: bool
    phase: str
    completed_tasks: int
    failed_tasks: int
    total_tasks: int
    execution_time: float
    output_dir: str
    error: Optional[str] = None


@dataclass
class OrchestratorCheckpoint:
    """持久化检查点 — 每个 phase 完成后自动保存,支持从任意 phase 恢复."""
    version: int = 1
    task_id: str = ""
    phase: str = "idle"
    phase_progress: Dict[str, Any] = field(default_factory=dict)
    # {task_id: status_value} snapshot of all tasks
    task_board_snapshot: List[Dict[str, Any]] = field(default_factory=list)
    # List of file paths in workspace
    workspace_snapshot: List[str] = field(default_factory=list)
    # {task_id: agent_id} for active agents
    active_agents: Dict[str, str] = field(default_factory=dict)
    timestamp: str = ""
    requirement: str = ""


class Orchestrator:
    def __init__(
        self,
        root_agent: AgentCore,
        workspace_dir: str,
        config: Optional[OrchestratorConfig] = None,
    ):
        self._root_agent = root_agent
        self._workspace_dir = workspace_dir
        self._config = config or OrchestratorConfig()
        self._workspace = Workspace(workspace_dir)
        self._task_board = TaskBoard(
            persist_path=str(Path(workspace_dir) / ".task_board.json")
        )
        self._phase = OrchestratorPhase.IDLE
        self._active_agents: Dict[str, BaseSubAgent] = {}
        self._running = False
        self._cancelled = False
        self._start_time: Optional[float] = None
        self._current_task_id: Optional[str] = None
        self._fix_round_counts: Dict[str, int] = {}
        self._dim_test_results: Dict[str, Dict[str, DimensionResult]] = {}
        self._requirement: str = ""
        self._paused: bool = False
        self._long_task_ctx: Optional[LongTaskContext] = None
        self._heartbeat: Optional[WorkspaceHeartbeat] = None
        self._checkpoint_just_saved: bool = False
        self._inject_orchestrator_rules()

    def _inject_orchestrator_rules(self) -> None:
        if not hasattr(self._root_agent, "_context"):
            return
        ctx = self._root_agent._context
        if not hasattr(ctx, "set_static_system_prompt"):
            return
        try:
            existing = ctx.get_static_system_prompt() if hasattr(ctx, "get_static_system_prompt") else ""
            if ORCHESTRATOR_HARD_RULES.strip() not in (existing or ""):
                ctx.set_static_system_prompt((existing or "") + "\n\n" + ORCHESTRATOR_HARD_RULES)
        except Exception as e:
            logger.debug(f"Could not inject orchestrator rules: {e}")

    @staticmethod
    def stamp() -> str:
        return datetime.now().strftime("%y%m%d %H%M")

    @property
    def phase(self) -> OrchestratorPhase:
        return self._phase

    @property
    def workspace(self) -> Workspace:
        return self._workspace

    @property
    def task_board(self) -> TaskBoard:
        return self._task_board

    def _write_orchestrator_log(self, message: str, level: str = "INFO") -> None:
        log_line = f"- {self.stamp()} [{level}] {message}\n"
        self._workspace.append_log("orchestrator-log.md", message, level)
        log_level = {
            "INFO": logger.info,
            "WARNING": logger.warning,
            "ERROR": logger.error,
            "DEBUG": logger.debug,
        }.get(level, logger.info)
        log_level(message)
        if hasattr(self, "_log_callbacks"):
            for cb in self._log_callbacks:
                try:
                    cb(log_line)
                except Exception:
                    pass

    def register_log_callback(self, callback) -> None:
        if not hasattr(self, "_log_callbacks"):
            self._log_callbacks: List = []
        self._log_callbacks.append(callback)

    @property
    def checkpoint_path(self) -> Path:
        return Path(self._workspace_dir) / ".orchestrator-checkpoint.json"

    def save_checkpoint(self) -> None:
        """Save current state to checkpoint file."""
        checkpoint = OrchestratorCheckpoint(
            task_id=self._current_task_id or "",
            phase=self._phase.value,
            phase_progress={
                "completed": len(self._task_board.get_completed()),
                "total": len(self._task_board._tasks),
                "current_task": self._current_task_id or "",
            },
            task_board_snapshot=[t.to_dict() for t in self._task_board._tasks.values()],
            workspace_snapshot=[str(f) for f in self._workspace.root_dir.rglob("*") if f.is_file()][:100],
            active_agents={tid: t.agent_id for tid, t in self._task_board._tasks.items() if t.agent_id},
            timestamp=self.stamp(),
            requirement=getattr(self, '_requirement', ''),
        )
        try:
            data = {
                "version": checkpoint.version,
                "task_id": checkpoint.task_id,
                "phase": checkpoint.phase,
                "phase_progress": checkpoint.phase_progress,
                "task_board_snapshot": checkpoint.task_board_snapshot,
                "workspace_snapshot": checkpoint.workspace_snapshot,
                "active_agents": checkpoint.active_agents,
                "timestamp": checkpoint.timestamp,
                "requirement": checkpoint.requirement,
            }
            self.checkpoint_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self._write_orchestrator_log(f"Checkpoint saved: phase={checkpoint.phase}")
            self._checkpoint_just_saved = True
        except Exception as e:
            logger.error(f"Failed to save checkpoint: {e}")

    def load_checkpoint(self) -> Optional[OrchestratorCheckpoint]:
        """Load checkpoint from file. Returns None if not found."""
        if not self.checkpoint_path.exists():
            return None
        try:
            data = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            return OrchestratorCheckpoint(
                version=data.get("version", 1),
                task_id=data.get("task_id", ""),
                phase=data.get("phase", "idle"),
                phase_progress=data.get("phase_progress", {}),
                task_board_snapshot=data.get("task_board_snapshot", []),
                workspace_snapshot=data.get("workspace_snapshot", []),
                active_agents=data.get("active_agents", {}),
                timestamp=data.get("timestamp", ""),
                requirement=data.get("requirement", ""),
            )
        except Exception as e:
            logger.error(f"Failed to load checkpoint: {e}")
            return None

    async def resume_from_checkpoint(self) -> OrchestratorResult:
        """Resume execution from a saved checkpoint.

        Skips already-completed tasks and continues from the interrupted phase.
        """
        checkpoint = self.load_checkpoint()
        if checkpoint is None:
            return self._build_result(success=False, error="No checkpoint found")

        self._write_orchestrator_log(
            f"Resuming from checkpoint: phase={checkpoint.phase}, "
            f"completed={checkpoint.phase_progress.get('completed', 0)}/{checkpoint.phase_progress.get('total', 0)}"
        )

        # Restore task board from snapshot
        self._workspace.initialize()
        for task_data in checkpoint.task_board_snapshot:
            status_val = task_data.get("status", "pending")
            if status_val in ("completed", "failed"):
                # Skip already-completed/failed tasks
                continue
            # Re-add pending/in-progress tasks
            try:
                self._task_board.add_task(
                    title=task_data.get("title", ""),
                    description=task_data.get("description", ""),
                    priority=TaskPriority(task_data.get("priority", 2)),
                    dependencies=task_data.get("dependencies", []),
                )
            except Exception as e:
                logger.warning(f"Failed to restore task: {e}")

        # Store requirement for later use
        self._requirement = checkpoint.requirement

        # Continue from the appropriate phase
        if checkpoint.phase in ("planning", "idle"):
            # Re-run from planning
            return await self.execute(checkpoint.requirement)

        # If we were in developing/testing/fixing, continue the develop phase
        self._phase = OrchestratorPhase.DEVELOPING
        dev_success = await self._phase_develop()
        if not dev_success and not self._cancelled:
            return self._build_result(success=False, error="Development phase failed")

        self._phase = OrchestratorPhase.FINAL_TESTING
        await self._phase_final_test()

        self._phase = OrchestratorPhase.COMPLETED
        # Clean up checkpoint on successful completion
        try:
            self.checkpoint_path.unlink(missing_ok=True)
        except Exception:
            pass
        return self._build_result(success=True)

    async def stream_resume_from_checkpoint(
        self,
    ) -> "AsyncIterator[AgentEvent]":
        """Streaming variant of :meth:`resume_from_checkpoint`.

        Loads the checkpoint, restores the task board, then delegates
        to :meth:`stream_execute_v2` for the actual execution with
        live event emission.

        If the checkpoint was in ``planning`` / ``idle`` phase, the
        full pipeline is re-run from scratch.  Otherwise, only the
        develop → test → fix → final-test phases are executed (the
        plan is already in the task board).
        """
        from .protocol.events import TurnFailed as TurnFailedEvent

        checkpoint = self.load_checkpoint()
        if checkpoint is None:
            yield TurnFailedEvent(
                code="no_checkpoint",
                error="未找到检查点文件",
            )
            return

        self._write_orchestrator_log(
            f"Streaming resume from checkpoint: phase={checkpoint.phase}, "
            f"completed={checkpoint.phase_progress.get('completed', 0)}/"
            f"{checkpoint.phase_progress.get('total', 0)}"
        )

        # Restore task board from snapshot
        self._workspace.initialize()
        for task_data in checkpoint.task_board_snapshot:
            status_val = task_data.get("status", "pending")
            if status_val in ("completed", "failed"):
                continue
            try:
                self._task_board.add_task(
                    title=task_data.get("title", ""),
                    description=task_data.get("description", ""),
                    priority=TaskPriority(task_data.get("priority", 2)),
                    dependencies=task_data.get("dependencies", []),
                )
            except Exception as e:
                logger.warning(f"Failed to restore task: {e}")

        self._requirement = checkpoint.requirement

        if checkpoint.phase in ("planning", "idle"):
            # Re-run from scratch — the full stream_execute_v2 pipeline
            async for event in self.stream_execute_v2(checkpoint.requirement):
                yield event
            return

        # We were past planning — skip planning, go straight to
        # develop.  We do this by calling stream_execute() with
        # the existing task board (which already has tasks from
        # the checkpoint).  The planning phase will find that
        # tasks already exist and effectively be a no-op (the
        # planner generates tasks, but they're already there).
        #
        # A cleaner approach would be to refactor stream_execute
        # to accept a skip_planning flag, but that changes the
        # existing API.  Instead, we run the full pipeline — the
        # planner will re-generate the plan but the task board
        # already has the right tasks, so the develop phase will
        # pick them up.
        async for event in self.stream_execute_v2(checkpoint.requirement):
            yield event

    def pause(self) -> None:
        """Request pause — will stop after current task completes."""
        self._cancelled = True
        self._paused = True
        self.save_checkpoint()
        self._write_orchestrator_log("Pause requested, checkpoint saved")

    async def execute(self, requirement: str, input_files: Optional[List[str]] = None) -> OrchestratorResult:
        """Backward-compatible blocking entry point.

        Internally consumes all events from ``stream_execute()`` and
        returns the final ``OrchestratorResult``.
        """
        last_error: Optional[str] = None
        async for event in self.stream_execute(requirement, input_files):
            if isinstance(event, self.Event) and event.type == "error":
                last_error = event.error

        if self._phase == OrchestratorPhase.COMPLETED:
            return self._build_result(success=True)
        return self._build_result(success=False, error=last_error)

    def cancel(self) -> None:
        self._cancelled = True
        self._write_orchestrator_log("Cancel requested")

    async def _phase_plan(self, requirement: str, input_files: List[str]) -> bool:
        self._write_orchestrator_log("Phase: Planning")
        planner = PlannerAgent(parent=self._root_agent)
        context = {
            "workspace_dir": str(self._workspace.root_dir),
            "input_files": input_files,
        }
        agent_id = await planner.create(requirement, context)
        self._active_agents[agent_id] = planner

        output = await planner.run(timeout=self._config.planner_timeout)
        del self._active_agents[agent_id]

        if not output.success:
            self._write_orchestrator_log(f"Planner failed: {output.error}", "ERROR")
            return False

        plan_content = self._workspace.read_plan()
        if plan_content is None:
            plan_path = self._workspace.doc_dir / "plan.md"
            if plan_path.exists():
                plan_content = plan_path.read_text(encoding="utf-8")
                self._workspace._state.plan_file = str(plan_path)

        if plan_content is None:
            self._write_orchestrator_log("No plan file generated", "ERROR")
            return False

        tasks = self._parse_plan_to_tasks(plan_content)
        for task_data in tasks:
            self._task_board.add_task(
                title=task_data["title"],
                description=task_data["description"],
                priority=task_data.get("priority", TaskPriority.MEDIUM),
                dependencies=task_data.get("dependencies", []),
            )

        self._write_orchestrator_log(f"Plan created with {len(tasks)} tasks")
        self._workspace.append_lesson("Planning completed", f"Generated {len(tasks)} tasks from requirement")
        return True

    async def _phase_develop(self) -> bool:
        self._write_orchestrator_log("Phase: Development")
        total_tasks = len(self._task_board.get_pending())
        if total_tasks == 0:
            self._write_orchestrator_log("No tasks to develop")
            return True

        batch_num = 0
        while not self._cancelled:
            batch = self._task_board.get_next_batch(batch_size=self._config.batch_size)
            if not batch:
                break

            batch_num += 1
            self._write_orchestrator_log(f"Batch {batch_num}: {len(batch)} tasks")

            for task in batch:
                if self._cancelled:
                    break
                await self._execute_single_task(task)

            if self._config.auto_recover:
                await self._check_and_recover()

        completed = len(self._task_board.get_completed())
        failed = len(self._task_board.get_failed())
        self._write_orchestrator_log(
            f"Development done: {completed} completed, {failed} failed out of {total_tasks}"
        )
        return failed == 0

    async def _execute_single_task(self, task: Task) -> bool:
        self._task_board.update_status(task.id, TaskStatus.IN_PROGRESS)
        self._task_board.update_heartbeat(task.id)
        self._write_orchestrator_log(f"Starting task: {task.id} - {task.title}")

        dev_agent = DevAgent(parent=self._root_agent)
        context = self._build_dev_context(task)
        agent_id = await dev_agent.create(task.description, context)
        self._task_board.assign_agent(task.id, agent_id)
        self._active_agents[agent_id] = dev_agent

        dev_output = await dev_agent.run(timeout=self._config.dev_timeout)
        del self._active_agents[agent_id]

        if not dev_output.success:
            self._write_orchestrator_log(f"Dev failed for {task.id}: {dev_output.error}", "ERROR")
            self._task_board.record_test_result(task.id, "FAIL", [dev_output.error or "Dev agent failed"])
            return False

        self._workspace.scan_and_sync(created_by="dev")
        self._write_orchestrator_log(f"Dev completed for {task.id}")

        self._phase = OrchestratorPhase.TESTING
        self._task_board.update_status(task.id, TaskStatus.TESTING)
        test_ok = await self._test_and_fix_loop(task, dev_agent)

        if self._long_task_ctx:
            self._long_task_ctx.add_task_summary(TaskSummary(
                task_id=task.id,
                title=task.title,
                status="completed" if test_ok else "failed",
                test_result="PASS" if test_ok else "FAIL",
                fix_rounds=self._fix_round_counts.get(task.id, 0),
            ))
            self._long_task_ctx.set_current_task(task.title)

        return test_ok

    async def _test_and_fix_loop(self, task: Task, dev_agent: DevAgent) -> bool:
        if self._config.use_multi_dim_test:
            return await self._test_and_fix_loop_multi_dim(task, dev_agent)
        return await self._test_and_fix_loop_legacy(task, dev_agent)

    async def _test_and_fix_loop_legacy(self, task: Task, dev_agent: DevAgent) -> bool:
        fix_round = 0
        consecutive_failures = 0  # DoomLoop 防护：连续失败计数
        last_error_hash = ""      # DoomLoop 防护：检测重复相同错误

        while fix_round <= self._config.max_fix_rounds and not self._cancelled:
            tester = TesterAgent(parent=self._root_agent)
            context = self._build_tester_context(task)
            test_agent_id = await tester.create(task.description, context)
            self._active_agents[test_agent_id] = tester

            test_output = await tester.run(timeout=self._config.tester_timeout)
            del self._active_agents[test_agent_id]

            if not test_output.success:
                self._write_orchestrator_log(f"Tester failed for {task.id}: {test_output.error}", "ERROR")
                # DoomLoop 检测：如果错误和上次一样，增加连续失败计数
                err_hash = hash((test_output.error or "")[:200])
                if err_hash == last_error_hash:
                    consecutive_failures += 1
                else:
                    consecutive_failures = 1
                    last_error_hash = err_hash
                if consecutive_failures >= self._config.max_consecutive_failures:
                    self._write_orchestrator_log(
                        f"Task {task.id}: aborting — {consecutive_failures} consecutive identical failures",
                        "ERROR",
                    )
                    break
                if fix_round >= self._config.max_fix_rounds:
                    break
                fix_round += 1
                continue

            parsed = tester.parse_result(test_output.content)
            status = parsed.get("status", "UNKNOWN")

            if status == "PASS":
                self._task_board.record_test_result(task.id, "PASS", parsed.get("issues", []))
                self._write_orchestrator_log(f"Task {task.id}: PASS")
                self._phase = OrchestratorPhase.DEVELOPING
                return True

            issues = parsed.get("issues", [])
            self._write_orchestrator_log(
                f"Task {task.id}: FAIL (round {fix_round + 1}), issues: {issues}"
            )
            self._task_board.record_test_result(task.id, "FAIL", issues)

            # 重置连续失败计数（测试本身成功了，只是结果不 PASS）
            consecutive_failures = 0

            if fix_round >= self._config.max_fix_rounds:
                break
            fix_round += 1
            self._phase = OrchestratorPhase.FIXING
            self._fix_round_counts[task.id] = fix_round

            fix_description = self._build_fix_prompt(task, issues, fix_round)
            await dev_agent.resume(fix_description, self._build_dev_context(task))
            dev_output = await dev_agent.run(timeout=self._config.dev_timeout)

            if not dev_output.success:
                self._write_orchestrator_log(f"Fix round {fix_round} failed for {task.id}", "ERROR")
                # DevAgent 失败也计入连续失败
                consecutive_failures += 1
                if consecutive_failures >= self._config.max_consecutive_failures:
                    self._write_orchestrator_log(
                        f"Task {task.id}: aborting — {consecutive_failures} consecutive dev failures",
                        "ERROR",
                    )
                    break
            else:
                consecutive_failures = 0

            self._workspace.scan_and_sync(created_by="dev-fix")

            lesson_title = f"Fix round {fix_round} for {task.title}"
            lesson_content = "\n".join(f"- {issue}" for issue in issues)
            self._workspace.append_lesson(lesson_title, lesson_content)

        self._write_orchestrator_log(f"Task {task.id}: exceeded max fix rounds", "ERROR")
        self._phase = OrchestratorPhase.DEVELOPING
        return False

    async def _test_and_fix_loop_multi_dim(
        self, task: Task, dev_agent: DevAgent
    ) -> bool:
        coordinator = MultiDimTestCoordinator(
            parent_agent=self._root_agent,
            dimensions=self._config.test_dimensions,
            max_concurrent=self._config.test_concurrency,
            per_test_timeout=self._config.tester_timeout,
        )
        all_issues: List[str] = []
        fix_round = 0
        per_task_results: Dict[str, DimensionResult] = {}
        consecutive_failures = 0  # DoomLoop 防护
        last_error_hash = ""

        while fix_round <= self._config.max_fix_rounds and not self._cancelled:
            self._phase = OrchestratorPhase.TESTING
            context = self._build_tester_context(task)
            context["target"] = task.title
            context["fix_round"] = fix_round
            test_desc = (
                f"三维质量审查：{task.title}\n"
                f"Task ID: {task.id}\n"
                f"请按你负责的维度进行专项审查，"
                f"只读源文件，将报告写入 test-reports/{task.id}-{{dimension}}.md"
            )

            if fix_round == 0:
                results = await coordinator.run_parallel(test_desc, context)
            else:
                results = await coordinator.resume_failed_dimensions(
                    per_task_results, test_desc, context
                )
            per_task_results = results
            self._dim_test_results[task.id] = results

            all_pass, passed, failed, errored = coordinator.summarize(results)
            summary_str = "/".join(
                f"{TestDimension.LABELS.get(d, d)}={TestDimension.LABELS.get(d, d)[:1]}{'P' if results[d].passed else 'F' if results[d].failed else '?' if results[d].status == 'UNKNOWN' else 'E'}"
                for d in results
            )
            self._write_orchestrator_log(
                f"Test {task.id} R{fix_round}: {summary_str}"
            )

            for d, r in results.items():
                if r.report_path:
                    self._task_board.record_test_result(
                        task.id, r.status, [f"[{d}] {i}" for i in r.issues] or [f"[{d}] (no detail)"]
                    )
                    break

            if all_pass:
                self._task_board.record_test_result(task.id, "PASS", [])
                self._write_orchestrator_log(f"Task {task.id}: ALL DIMENSIONS PASS (round {fix_round})")
                self._phase = OrchestratorPhase.DEVELOPING
                return True

            # DoomLoop 检测：如果 errored 占比高且错误相同，计入连续失败
            if errored > 0 and passed == 0:
                err_sig = hash(summary_str)
                if err_sig == last_error_hash:
                    consecutive_failures += 1
                else:
                    consecutive_failures = 1
                    last_error_hash = err_sig
                if consecutive_failures >= self._config.max_consecutive_failures:
                    self._write_orchestrator_log(
                        f"Task {task.id}: aborting — {consecutive_failures} consecutive identical test errors",
                        "ERROR",
                    )
                    break
            else:
                consecutive_failures = 0

            all_issues = [
                f"[{d}] {i}" for d, r in results.items() for i in r.issues
            ]
            self._task_board.record_test_result(task.id, "FAIL", all_issues or ["(see test-reports)"])
            self._write_orchestrator_log(
                f"Task {task.id}: FAIL (round {fix_round + 1}) — "
                f"failed={failed} errored={errored}"
            )

            if fix_round >= self._config.max_fix_rounds:
                break
            fix_round += 1
            self._fix_round_counts[task.id] = fix_round
            self._phase = OrchestratorPhase.FIXING

            failed_reports = {
                d: r.report_path for d, r in results.items()
                if (r.failed or r.status == "ERROR") and r.report_path
            }
            fix_prompt = self._build_multi_dim_fix_prompt(
                task, results, failed_reports, fix_round
            )
            await dev_agent.resume(fix_prompt, self._build_dev_context(task))
            dev_output = await dev_agent.run(timeout=self._config.dev_timeout)
            if not dev_output.success:
                self._write_orchestrator_log(
                    f"Fix round {fix_round} dev failed for {task.id}", "ERROR"
                )
                consecutive_failures += 1
                if consecutive_failures >= self._config.max_consecutive_failures:
                    self._write_orchestrator_log(
                        f"Task {task.id}: aborting — {consecutive_failures} consecutive dev failures",
                        "ERROR",
                    )
                    break
            else:
                consecutive_failures = 0
            self._workspace.scan_and_sync(created_by="dev-fix")

            lessons = []
            for d, r in results.items():
                if r.failed or r.status == "ERROR":
                    lessons.append(
                        f"## {TestDimension.LABELS.get(d, d)} (R{fix_round})\n"
                        + "\n".join(f"- {i}" for i in r.issues[:5])
                    )
            if lessons:
                self._workspace.append_lesson(
                    f"Multi-dim fix R{fix_round} for {task.title}",
                    "\n\n".join(lessons),
                )

        self._write_orchestrator_log(
            f"Task {task.id}: exceeded max fix rounds ({self._config.max_fix_rounds})",
            "ERROR",
        )
        self._phase = OrchestratorPhase.DEVELOPING
        return False

    def _build_multi_dim_fix_prompt(
        self,
        task: Task,
        results: Dict[str, DimensionResult],
        report_paths: Dict[str, str],
        round_num: int,
    ) -> str:
        lines = [
            f"第 {round_num} 轮修正：以下维度的测试未通过，请根据报告修正代码。",
            "",
        ]
        for d, r in results.items():
            if r.passed:
                continue
            label = TestDimension.LABELS.get(d, d)
            rp = report_paths.get(d, "(无报告路径)")
            lines.append(f"### [{label}] 失败 (问题数: {r.issue_count})")
            lines.append(f"报告: {rp}")
            for i, issue in enumerate(r.issues[:8], 1):
                lines.append(f"  {i}. {issue}")
            lines.append("")
        lines.append("修复要求：")
        lines.append("1. 同一文件的修改应集中处理，避免重复编辑")
        lines.append("2. 修改后请将通用经验追加到 lessons-learned.md")
        lines.append("3. 只返回简短确认 + 文件路径列表，不要粘贴修改内容")
        return "\n".join(lines)

    async def _phase_final_test(self) -> bool:
        self._write_orchestrator_log("Phase: Final Testing")
        completed_tasks = self._task_board.get_completed()
        if not completed_tasks:
            self._write_orchestrator_log("No completed tasks to final-test")
            return True

        all_pass = True
        for task in completed_tasks:
            tester = TesterAgent(parent=self._root_agent)
            context = self._build_tester_context(task)
            context["extra_instructions"] = "This is a FINAL integration test. Verify everything works together."
            agent_id = await tester.create(
                f"Final integration test for: {task.title}", context
            )
            self._active_agents[agent_id] = tester
            output = await tester.run(timeout=self._config.tester_timeout)
            del self._active_agents[agent_id]

            if output.success:
                parsed = tester.parse_result(output.content)
                if parsed.get("status") != "PASS":
                    all_pass = False
                    self._write_orchestrator_log(
                        f"Final test FAIL for {task.id}: {parsed.get('issues', [])}", "WARNING"
                    )
            else:
                all_pass = False

        if all_pass:
            self._write_orchestrator_log("All final tests PASSED")
        return all_pass

    async def _check_and_recover(self) -> None:
        stale = self._task_board.check_heartbeats()
        for task in stale:
            self._write_orchestrator_log(f"Stale task detected: {task.id}", "WARNING")
            self._task_board.recover_task(task.id)

        for task in self._task_board.get_in_progress():
            if task.agent_id and task.agent_id in self._active_agents:
                agent = self._active_agents[task.agent_id]
                if agent.completed and agent.result:
                    if self._task_board.detect_hallucination(task.id, agent.result):
                        self._write_orchestrator_log(
                            f"Hallucination detected for {task.id}, recovering", "WARNING"
                        )
                        self._task_board.recover_task(task.id)

    def _build_dev_context(self, task: Task) -> Dict[str, Any]:
        return {
            "workspace_dir": str(self._workspace.root_dir),
            "plan_file": str(self._workspace.doc_dir / "plan.md"),
            "lessons_file": str(self._workspace.doc_dir / "lessons-learned.md"),
            "test_reports_dir": str(self._workspace.test_reports_dir),
            "extra_instructions": f"Task ID: {task.id}, Title: {task.title}",
        }

    def _build_tester_context(self, task: Task) -> Dict[str, Any]:
        return {
            "workspace_dir": str(self._workspace.root_dir),
            "plan_file": str(self._workspace.doc_dir / "plan.md"),
            "test_reports_dir": str(self._workspace.test_reports_dir),
            "extra_instructions": f"Testing Task ID: {task.id}, Title: {task.title}",
        }

    def _build_sub_agent_prompt(
        self,
        task_description: str,
        agent_type: str,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Use LongTaskContext.build_sub_agent_prompt() when available.

        Falls back to returning the raw *task_description* so the caller
        can still pass a conventional context dict to ``agent.create()``.
        """
        if self._long_task_ctx:
            return self._long_task_ctx.build_sub_agent_prompt(
                task_description, agent_type, extra_context,
            )
        return task_description

    def _build_fix_prompt(self, task: Task, issues: List[str], round_num: int) -> str:
        issues_text = "\n".join(f"- {issue}" for issue in issues)
        return (
            f"Fix the following issues found in testing (round {round_num}):\n\n"
            f"{issues_text}\n\n"
            f"Read the test reports in {self._workspace.test_reports_dir} for details.\n"
            f"Update lessons-learned.md with what you learn from this fix."
        )

    def _parse_plan_to_tasks(self, plan_content: str) -> List[Dict[str, Any]]:
        if plan_content is None:
            return []
        tasks = []
        lines = plan_content.split("\n")
        for line in lines:
            stripped = line.strip()
            if not stripped or "---" in stripped:
                continue
            if "|" not in stripped:
                continue
            if any(h in stripped.lower() for h in ["task id", "title", "description", "|---"]):
                continue
            cells = [c.strip() for c in stripped.split("|")]
            cells = [c for c in cells if c]
            if len(cells) < 2:
                continue
            is_pending = any(m in stripped for m in ["⏳", "[ ]", "- [ ]", "⬜", "☐"])
            is_done = any(m in stripped for m in ["✅", "[x]", "- [x]"])
            if is_done:
                continue
            task_id = cells[0] if re.match(r'^[Tt]\d+|^\d+$', cells[0]) else ""
            title = cells[1] if len(cells) > 1 else cells[0]
            description = cells[2] if len(cells) > 2 else title
            priority = TaskPriority.MEDIUM
            if len(cells) > 3:
                p_text = cells[3].lower()
                if "high" in p_text or "critical" in p_text:
                    priority = TaskPriority.HIGH
                elif "low" in p_text:
                    priority = TaskPriority.LOW
            dependencies = []
            if len(cells) > 5:
                dep_text = cells[5]
                dependencies = re.findall(r'[Tt]\d+', dep_text)
            tasks.append({
                "id": task_id,
                "title": title,
                "description": description,
                "priority": priority,
                "dependencies": dependencies,
            })
        if not tasks:
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("- [") or stripped.startswith("* ["):
                    text = re.sub(r'^[-*]\s*\[[ x]\]\s*', '', stripped)
                    if text:
                        tasks.append({
                            "title": text,
                            "description": text,
                            "priority": TaskPriority.MEDIUM,
                            "dependencies": [],
                        })
        return tasks

    def _build_result(self, success: bool, error: Optional[str] = None) -> OrchestratorResult:
        elapsed = time.time() - self._start_time if self._start_time else 0
        completed = len(self._task_board.get_completed())
        failed = len(self._task_board.get_failed())
        total = len(self._task_board._tasks)
        return OrchestratorResult(
            task_id=self._current_task_id or "",
            success=success,
            phase=self._phase.value,
            completed_tasks=completed,
            failed_tasks=failed,
            total_tasks=total,
            execution_time=elapsed,
            output_dir=str(self._workspace.root_dir),
            error=error,
        )

    def get_status(self) -> Dict[str, Any]:
        return {
            "phase": self._phase.value,
            "running": self._running,
            "current_task_id": self._current_task_id,
            "active_agents": list(self._active_agents.keys()),
            "task_board": self._task_board.get_statistics(),
            "workspace": self._workspace.get_summary(),
            "fix_rounds": dict(self._fix_round_counts),
            "test_dimensions": list(self._config.test_dimensions),
            "test_concurrency": self._config.test_concurrency,
            "use_multi_dim_test": self._config.use_multi_dim_test,
            "enable_final_test": self._config.enable_final_test,
            "use_deterministic_verifier": self._config.use_deterministic_verifier,
            "dim_test_results": {
                tid: {d: r.to_dict() for d, r in res.items()}
                for tid, res in self._dim_test_results.items()
            },
        }

    # ============================================================
    # Streaming variant
    # ============================================================
    #
    # `execute()` is the original blocking entry point. `stream_execute()`
    # is the TUI-friendly version: it walks the same phases, but yields
    # `OrchestratorEvent` objects between every meaningful step so the
    # chat bubble can show live progress and the token counter can
    # update in real time. The user sees the same kind of feedback as
    # they would for a single LLM stream — just driven by a multi-agent
    # pipeline instead.

    @dataclass
    class Event:
        """A single progress event emitted by `stream_execute`.

        The TUI sink renders one Event into one line of chat text. The
        fields are intentionally permissive: every kind of progress
        indicator lives in this same shape so the consumer only has to
        dispatch on `type`.
        """
        type: str  # phase | agent_start | agent_done | task_progress | checkpoint | log | token_usage | done | error
        phase: Optional[str] = None
        agent_type: Optional[str] = None
        task_id: Optional[str] = None
        message: str = ""
        input_tokens: int = 0
        output_tokens: int = 0
        success: Optional[bool] = None
        error: Optional[str] = None
        payload: Dict[str, Any] = field(default_factory=dict)

    async def stream_execute(
        self, requirement: str, input_files: Optional[List[str]] = None,
    ) -> "AsyncIterator[Orchestrator.Event]":
        """Run the same pipeline as `execute()` but yield events.

        The contract is: every event is a `Orchestrator.Event`. The
        TUI sink subscribes to the async iterator and renders one line
        per event. A final `done` event is always emitted (success or
        failure), and a single `error` event replaces a raise.

        The inner `_stream_*` methods are async generators. They yield
        both `Orchestrator.Event` (forwarded to the consumer) and
        `bool` results (captured here, never forwarded). This is the
        "yield-flag" pattern: an async generator can't `return` a value
        in Python, so we yield a bool to signal the outcome of a phase.
        """
        self._running = True
        self._cancelled = False
        self._start_time = time.time()
        self._current_task_id = f"orch_{int(time.time())}"
        self._requirement = requirement

        self._long_task_ctx = LongTaskContext(str(self._workspace.root_dir))
        self._long_task_ctx.set_requirement(requirement)
        self._long_task_ctx.set_phase("planning")

        self._heartbeat = WorkspaceHeartbeat(str(self._workspace.root_dir))
        self._heartbeat.start()

        try:
            self._workspace.initialize()
            self._write_orchestrator_log(
                f"Orchestrator started: {self._current_task_id}"
            )
            self._write_orchestrator_log(
                f"Requirement: {requirement[:200]}"
            )
            yield self.Event(
                type="phase", phase="planning",
                message=f"任务: {requirement[:200]}",
            )

            # ---- Planning ----
            self._phase = OrchestratorPhase.PLANNING
            plan_success = False
            async for _item in self._stream_phase_plan(
                requirement, input_files or []
            ):
                if isinstance(_item, OrchestratorProgressEvent):
                    plan_success = _item.phase == "completed"
                else:
                    yield _item
            if not plan_success:
                yield self.Event(
                    type="error", phase=self._phase.value,
                    error="计划阶段失败",
                )
                return
            self.save_checkpoint()
            if self._checkpoint_just_saved:
                self._checkpoint_just_saved = False
                yield self.Event(
                    type="checkpoint",
                    payload={
                        "checkpoint_path": str(self.checkpoint_path),
                        "phase": self._phase.value,
                        "task_id": self._current_task_id or "",
                        "completed_tasks": len(self._task_board.get_completed()),
                        "total_tasks": len(self._task_board._tasks),
                        "timestamp": self.stamp(),
                    },
                )
            self._long_task_ctx.set_phase("developing")
            self._long_task_ctx.compress_for_next_turn()

            # ---- Develop + test/fix per task ----
            self._phase = OrchestratorPhase.DEVELOPING
            yield self.Event(
                type="phase", phase="developing",
                message="开始逐任务开发",
            )
            dev_ok = False
            async for _item in self._stream_phase_develop():
                if isinstance(_item, OrchestratorProgressEvent):
                    dev_ok = _item.phase == "completed"
                else:
                    yield _item
            if not dev_ok and not self._cancelled:
                yield self.Event(
                    type="error", phase=self._phase.value,
                    error="开发阶段失败",
                )
                return
            self.save_checkpoint()
            if self._checkpoint_just_saved:
                self._checkpoint_just_saved = False
                yield self.Event(
                    type="checkpoint",
                    payload={
                        "checkpoint_path": str(self.checkpoint_path),
                        "phase": self._phase.value,
                        "task_id": self._current_task_id or "",
                        "completed_tasks": len(self._task_board.get_completed()),
                        "total_tasks": len(self._task_board._tasks),
                        "timestamp": self.stamp(),
                    },
                )
            self._long_task_ctx.set_phase("final_testing")
            self._long_task_ctx.compress_for_next_turn()

            # ---- Final test ----
            self._phase = OrchestratorPhase.FINAL_TESTING
            yield self.Event(
                type="phase", phase="final_testing",
                message="终验中",
            )
            final_ok = True
            async for _item in self._stream_phase_final_test():
                if isinstance(_item, OrchestratorProgressEvent):
                    final_ok = _item.phase == "completed"
                else:
                    yield _item
            if not final_ok:
                self._write_orchestrator_log(
                    "Final testing found issues", "WARNING"
                )
            self.save_checkpoint()
            if self._checkpoint_just_saved:
                self._checkpoint_just_saved = False
                yield self.Event(
                    type="checkpoint",
                    payload={
                        "checkpoint_path": str(self.checkpoint_path),
                        "phase": self._phase.value,
                        "task_id": self._current_task_id or "",
                        "completed_tasks": len(self._task_board.get_completed()),
                        "total_tasks": len(self._task_board._tasks),
                        "timestamp": self.stamp(),
                    },
                )
            self._long_task_ctx.set_phase("completed")
            self._long_task_ctx.compress_for_next_turn()

            # ---- Done ----
            self._phase = OrchestratorPhase.COMPLETED
            yield self.Event(
                type="phase", phase="completed",
                message="全部阶段完成",
            )
            yield self.Event(
                type="done",
                message=("✅ 全部完成" if final_ok else
                         "⚠️ 完成但终验有警告"),
                success=final_ok,
            )
        except asyncio.CancelledError:
            self._phase = OrchestratorPhase.FAILED
            self._write_orchestrator_log("Orchestrator cancelled", "WARNING")
            yield self.Event(
                type="error", error="用户取消", phase="failed",
            )
        except Exception as e:
            self._phase = OrchestratorPhase.FAILED
            self._write_orchestrator_log(
                f"Orchestrator error: {e}", "ERROR"
            )
            yield self.Event(
                type="error", error=str(e), phase="failed",
            )
        finally:
            self._running = False
            try:
                self._workspace.scan_and_sync(created_by="orchestrator")
            except Exception:
                pass
            if self._heartbeat:
                await self._heartbeat.stop()

    async def stream_execute_single_task(
        self,
        requirement: str,
        title: str = "Deep single task",
        input_files: Optional[List[str]] = None,
    ) -> "AsyncIterator[Orchestrator.Event]":
        """Run a lean Deep pipeline without planner fan-out.

        This keeps the Deep quality loop (Dev -> Tester -> optional final
        test) but creates exactly one task from the requirement. It is used
        for isolated SWE benchmark jobs where a planner can accidentally
        consume stale repository plans and inflate a tiny bugfix into a
        whole-project task graph.
        """
        self._running = True
        self._cancelled = False
        self._start_time = time.time()
        self._current_task_id = f"orch_{int(time.time())}"
        self._requirement = requirement

        self._long_task_ctx = LongTaskContext(str(self._workspace.root_dir))
        self._long_task_ctx.set_requirement(requirement)
        self._long_task_ctx.set_total_tasks(1)
        self._long_task_ctx.set_phase("developing")
        self._long_task_ctx.set_current_task(title)

        self._heartbeat = WorkspaceHeartbeat(str(self._workspace.root_dir))
        self._heartbeat.start()

        try:
            self._workspace.initialize()
            self._task_board.clear()
            self._workspace.write_plan(
                "# Deep Single-Task Plan\n\n"
                f"- [ ] {title}: complete the user's requirement and run the requested verifier.\n"
            )
            if self._workspace.read_lessons() is None:
                self._workspace.write_lessons("# Lessons Learned\n\n")

            self._write_orchestrator_log(
                f"Single-task orchestrator started: {self._current_task_id}"
            )
            self._write_orchestrator_log(
                f"Requirement: {requirement[:200]}"
            )

            task = self._task_board.add_task(
                title=title,
                description=requirement,
                priority=TaskPriority.HIGH,
                metadata={"single_task": True, "input_files": input_files or []},
            )

            self._phase = OrchestratorPhase.DEVELOPING
            yield self.Event(
                type="phase",
                phase="developing",
                message=f"Deep single task: {title}",
            )

            dev_ok = False
            async for _item in self._stream_execute_single_task(task):
                if isinstance(_item, OrchestratorProgressEvent):
                    dev_ok = _item.phase == "completed"
                else:
                    yield _item

            if not dev_ok and not self._cancelled:
                self._phase = OrchestratorPhase.FAILED
                yield self.Event(
                    type="error",
                    phase=self._phase.value,
                    error="Deep single-task pipeline failed",
                )
                return

            self._long_task_ctx.set_phase("final_testing")
            self._long_task_ctx.compress_for_next_turn()

            self._phase = OrchestratorPhase.FINAL_TESTING
            yield self.Event(
                type="phase",
                phase="final_testing",
                message="Final test",
            )
            final_ok = True
            async for _item in self._stream_phase_final_test():
                if isinstance(_item, OrchestratorProgressEvent):
                    final_ok = _item.phase == "completed"
                else:
                    yield _item

            self._long_task_ctx.set_phase("completed")
            self._long_task_ctx.compress_for_next_turn()

            self._phase = OrchestratorPhase.COMPLETED
            yield self.Event(
                type="phase",
                phase="completed",
                message="Deep single task completed",
            )
            yield self.Event(
                type="done",
                message=("Deep single task completed" if final_ok else
                         "Deep single task completed with final-test warnings"),
                success=final_ok,
            )
        except asyncio.CancelledError:
            self._phase = OrchestratorPhase.FAILED
            self._write_orchestrator_log("Single-task orchestrator cancelled", "WARNING")
            yield self.Event(type="error", error="Cancelled", phase="failed")
        except Exception as e:
            self._phase = OrchestratorPhase.FAILED
            self._write_orchestrator_log(
                f"Single-task orchestrator error: {e}", "ERROR"
            )
            yield self.Event(type="error", error=str(e), phase="failed")
        finally:
            self._running = False
            try:
                self._workspace.scan_and_sync(created_by="orchestrator")
            except Exception:
                pass
            if self._heartbeat:
                await self._heartbeat.stop()

    @staticmethod
    async def _drain_phase_impl(agen) -> "tuple[bool, list]":
        """Fallback batched drain. Not used in `stream_execute` (we
        forward events inline), but kept for tests and one-off scripts
        that need to run a phase to completion first.
        """
        result = False
        forwarded = []
        async for item in agen:
            if isinstance(item, OrchestratorProgressEvent):
                result = item.phase == "completed"
            else:
                forwarded.append(item)
        return result, forwarded

    # ---- Per-phase streaming variants ----
    #
    # These mirror the original `_phase_*` methods but yield
    # `Orchestrator.Event` before / after each sub-agent run and on
    # every test result. They share the orchestrator's own
    # `_write_orchestrator_log` so the markdown log file stays in
    # sync with the live stream.

    async def _consume_stream_run(
        self,
        agent: BaseSubAgent,
        timeout: int,
        output_out: list,
        task_id: Optional[str] = None,
    ):
        """Consume *agent.stream_run()*, yield converted ``Orchestrator.Event``
        objects, and store the final ``SubAgentOutput`` in *output_out*.

        Conversion mapping:
            TextDelta        → Event(type="log")
            ToolCallStarted  → Event(type="agent_start")
            ToolCallFinished → Event(type="agent_done")

        The caller passes a mutable *output_out* list; after the
        generator is exhausted, ``output_out[0]`` holds the
        ``SubAgentOutput`` (or a fallback failure object).
        """
        async for event in agent.stream_run(timeout=timeout):
            if isinstance(event, TextDelta):
                yield self.Event(type="log", message=event.text)
            elif isinstance(event, ToolCallStarted):
                yield self.Event(
                    type="agent_start",
                    agent_type=event.name,
                    task_id=task_id or agent.agent_id or "",
                )
            elif isinstance(event, ToolCallFinished):
                output_out.append(SubAgentOutput(
                    agent_type=agent.agent_type,
                    agent_id=agent.agent_id or "",
                    task_id="",
                    content=event.result or "",
                    success=event.success,
                    execution_time=event.duration,
                ))
                yield self.Event(
                    type="agent_done",
                    agent_type=event.name,
                    task_id=task_id or agent.agent_id or "",
                    success=event.success,
                    message=event.result or "",
                    payload={"execution_time": float(event.duration or 0.0)},
                )

    def _convert_agent_event(
        self, event: AgentEvent, task_id: str = "",
    ) -> "Orchestrator.Event":
        """Convert a protocol ``AgentEvent`` (from coordinator streaming)
        to an internal ``Orchestrator.Event``."""
        if isinstance(event, TextDelta):
            return self.Event(type="log", message=event.text)
        if isinstance(event, ToolCallStarted):
            return self.Event(
                type="agent_start", agent_type=event.name,
                task_id=task_id,
            )
        if isinstance(event, ToolCallFinished):
            return self.Event(
                type="agent_done", agent_type=event.name,
                task_id=task_id, success=event.success,
                message=event.result or "",
                payload={"execution_time": float(event.duration or 0.0)},
            )
        # Fallback
        return self.Event(type="log", message=str(event))

    async def _stream_phase_plan(
        self, requirement: str, input_files: List[str],
    ) -> bool:
        self._write_orchestrator_log("Phase: Planning")
        yield self.Event(type="log", message="启动 PlannerAgent")

        planner = PlannerAgent(parent=self._root_agent)
        extra_ctx: Optional[Dict[str, Any]] = None
        if input_files:
            extra_ctx = {"Input Files": "\n".join(f"- {f}" for f in input_files)}
        prompt = self._build_sub_agent_prompt(requirement, "planner", extra_ctx)
        context: Dict[str, Any] = {"workspace_dir": str(self._workspace.root_dir)} if self._long_task_ctx else {
            "workspace_dir": str(self._workspace.root_dir),
            "input_files": input_files,
        }
        agent_id = await planner.create(prompt, context)
        self._active_agents[agent_id] = planner

        output_holder: list = []
        async for evt in self._consume_stream_run(
            planner, self._config.planner_timeout, output_holder,
            task_id=agent_id,
        ):
            yield evt
        del self._active_agents[agent_id]

        output = output_holder[0] if output_holder else SubAgentOutput(
            agent_type="planner", agent_id=agent_id, task_id="",
            content="", success=False, error="No output from stream_run",
        )

        if not output.success:
            self._write_orchestrator_log(
                f"Planner failed: {output.error}", "ERROR"
            )
            yield OrchestratorProgressEvent(phase="failed", message=f"Planner failed: {output.error}")
            return

        # Emit an estimated token usage event so the TUI counter moves.
        est_in = max(1, len(requirement) // 2)
        est_out = len(output.content or "")
        yield self.Event(
            type="token_usage", input_tokens=est_in, output_tokens=est_out,
        )

        plan_content = self._workspace.read_plan()
        if plan_content is None:
            plan_path = self._workspace.doc_dir / "plan.md"
            if plan_path.exists():
                plan_content = plan_path.read_text(encoding="utf-8")
                self._workspace._state.plan_file = str(plan_path)

        if plan_content is None:
            self._write_orchestrator_log("No plan file generated", "ERROR")
            yield OrchestratorProgressEvent(phase="failed", message="No plan file generated")
            return

        tasks = self._parse_plan_to_tasks(plan_content)
        for task_data in tasks:
            self._task_board.add_task(
                title=task_data["title"],
                description=task_data["description"],
                priority=task_data.get("priority", TaskPriority.MEDIUM),
                dependencies=task_data.get("dependencies", []),
            )

        self._write_orchestrator_log(
            f"Plan created with {len(tasks)} tasks"
        )
        if self._long_task_ctx:
            self._long_task_ctx.set_total_tasks(len(tasks))
        yield self.Event(
            type="task_progress",
            message=f"计划生成 {len(tasks)} 个子任务",
        )
        self._workspace.append_lesson(
            "Planning completed",
            f"Generated {len(tasks)} tasks from requirement",
        )
        yield OrchestratorProgressEvent(phase="completed", message=f"Plan created with {len(tasks)} tasks")
        return

    async def _stream_phase_develop(self) -> bool:
        self._write_orchestrator_log("Phase: Development")
        total_tasks = len(self._task_board.get_pending())
        if total_tasks == 0:
            self._write_orchestrator_log("No tasks to develop")
            yield OrchestratorProgressEvent(phase="completed", message="No tasks to develop")

        batch_num = 0
        while not self._cancelled:
            batch = self._task_board.get_next_batch(
                batch_size=self._config.batch_size
            )
            if not batch:
                break

            batch_num += 1
            self._write_orchestrator_log(
                f"Batch {batch_num}: {len(batch)} tasks"
            )
            yield self.Event(
                type="task_progress",
                message=f"批次 {batch_num}: {len(batch)} 个任务",
            )

            for task in batch:
                if self._cancelled:
                    break
                ok = False
                async for _item in self._stream_execute_single_task(task):
                    if isinstance(_item, OrchestratorProgressEvent):
                        ok = _item.phase == "completed"
                    else:
                        yield _item
                if not ok and not self._cancelled:
                    # Continue with other tasks; the task_board records
                    # the failure for later reporting.
                    pass

            if self._config.auto_recover:
                await self._check_and_recover()

        completed = len(self._task_board.get_completed())
        failed = len(self._task_board.get_failed())
        self._write_orchestrator_log(
            f"Development done: {completed} completed, "
            f"{failed} failed out of {total_tasks}"
        )
        yield self.Event(
            type="task_progress",
            message=(
                f"开发完成: {completed} 成功 / {failed} 失败 / "
                f"共 {total_tasks}"
            ),
        )
        yield OrchestratorProgressEvent(
            phase="completed" if failed == 0 else "failed",
            message=f"Development done: {completed} completed, {failed} failed",
        )

    async def _stream_execute_single_task(self, task: Task) -> bool:
        self._task_board.update_status(task.id, TaskStatus.IN_PROGRESS)
        self._task_board.update_heartbeat(task.id)
        self._write_orchestrator_log(
            f"Starting task: {task.id} - {task.title}"
        )
        yield self.Event(
            type="task_progress",
            message=f"开始任务: {task.title}",
        )

        dev_agent = DevAgent(parent=self._root_agent)
        dev_prompt = self._build_sub_agent_prompt(
            task.description, "dev",
            {"Task ID": task.id, "Title": task.title},
        )
        dev_context: Dict[str, Any] = {"workspace_dir": str(self._workspace.root_dir)} if self._long_task_ctx else self._build_dev_context(task)
        agent_id = await dev_agent.create(dev_prompt, dev_context)
        self._task_board.assign_agent(task.id, agent_id)
        self._active_agents[agent_id] = dev_agent

        dev_holder: list = []
        async for evt in self._consume_stream_run(
            dev_agent, self._config.dev_timeout, dev_holder,
            task_id=task.id,
        ):
            yield evt
        del self._active_agents[agent_id]

        dev_output = dev_holder[0] if dev_holder else SubAgentOutput(
            agent_type="dev", agent_id=agent_id, task_id="",
            content="", success=False, error="No output from stream_run",
        )

        if not dev_output.success:
            self._write_orchestrator_log(
                f"Dev failed for {task.id}: {dev_output.error}", "ERROR"
            )
            self._task_board.record_test_result(
                task.id, "FAIL",
                [dev_output.error or "Dev agent failed"],
            )
            yield OrchestratorProgressEvent(phase="failed", message=f"Dev failed for {task.id}: {dev_output.error}")
            return

        self._workspace.scan_and_sync(created_by="dev")
        self._write_orchestrator_log(f"Dev completed for {task.id}")
        yield self.Event(
            type="token_usage",
            input_tokens=max(1, len(task.description) // 2),
            output_tokens=len(dev_output.content or ""),
        )

        if self._config.use_deterministic_verifier:
            test_ok = False
            async for _item in self._stream_deterministic_verify_and_fix_loop(
                task, dev_agent
            ):
                if isinstance(_item, OrchestratorProgressEvent):
                    test_ok = _item.phase == "completed"
                else:
                    yield _item

            if self._long_task_ctx:
                self._long_task_ctx.add_task_summary(TaskSummary(
                    task_id=task.id,
                    title=task.title,
                    status="completed" if test_ok else "failed",
                    test_result="PASS" if test_ok else "FAIL",
                    fix_rounds=self._fix_round_counts.get(task.id, 0),
                ))
                self._long_task_ctx.set_current_task(task.title)

            yield OrchestratorProgressEvent(
                phase="completed" if test_ok else "failed",
                message=f"Task {task.id}: {'PASS' if test_ok else 'FAIL'}",
                task_id=task.id,
            )
            return

        self._phase = OrchestratorPhase.TESTING
        self._task_board.update_status(task.id, TaskStatus.TESTING)
        yield self.Event(
            type="phase", phase="testing",
            message=f"测试: {task.title}",
        )
        test_ok = False
        async for _item in self._stream_test_and_fix_loop(task, dev_agent):
            if isinstance(_item, OrchestratorProgressEvent):
                test_ok = _item.phase == "completed"
            else:
                yield _item

        if self._long_task_ctx:
            self._long_task_ctx.add_task_summary(TaskSummary(
                task_id=task.id,
                title=task.title,
                status="completed" if test_ok else "failed",
                test_result="PASS" if test_ok else "FAIL",
                fix_rounds=self._fix_round_counts.get(task.id, 0),
            ))
            self._long_task_ctx.set_current_task(task.title)

        yield OrchestratorProgressEvent(
            phase="completed" if test_ok else "failed",
            message=f"Task {task.id}: {'PASS' if test_ok else 'FAIL'}",
            task_id=task.id,
        )

    async def _stream_test_and_fix_loop(
        self, task: Task, dev_agent: DevAgent,
    ) -> bool:
        if self._config.use_multi_dim_test:
            async for ok in self._stream_test_and_fix_loop_multi_dim(
                task, dev_agent
            ):
                if isinstance(ok, OrchestratorProgressEvent):
                    yield ok
                    return
                yield ok
            yield OrchestratorProgressEvent(phase="failed", message=f"Task {task.id}: test loop ended without result")
            return
        async for ok in self._stream_test_and_fix_loop_legacy(
            task, dev_agent
        ):
            if isinstance(ok, OrchestratorProgressEvent):
                yield ok
                return
            yield ok
        yield OrchestratorProgressEvent(phase="failed", message=f"Task {task.id}: test loop ended without result")

    def _run_deterministic_verifier(self) -> Tuple[bool, str, List[str]]:
        root = self._workspace.root_dir
        test_files = sorted(
            str(path) for path in root.rglob("test_*.py")
            if ".pytest_cache" not in path.parts
        )
        if not test_files:
            return False, "No test_*.py files found for deterministic verifier", []

        cmd = [sys.executable, "-m", "pytest", *test_files, "-q"]
        try:
            completed = subprocess.run(
                cmd,
                cwd=str(root),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=self._config.tester_timeout,
            )
            return completed.returncode == 0, completed.stdout or "", test_files
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout or ""
            if isinstance(output, bytes):
                output = output.decode("utf-8", errors="replace")
            return False, f"Verifier timed out after {self._config.tester_timeout}s\n{output}", test_files

    async def _stream_deterministic_verify_and_fix_loop(
        self, task: Task, dev_agent: DevAgent,
    ):
        fix_round = 0
        while fix_round <= self._config.max_fix_rounds and not self._cancelled:
            self._phase = OrchestratorPhase.TESTING
            self._task_board.update_status(task.id, TaskStatus.TESTING)
            yield self.Event(
                type="phase",
                phase="testing",
                message=f"Deterministic verifier: {task.title}",
            )

            passed, output, test_files = await asyncio.to_thread(
                self._run_deterministic_verifier
            )
            output_tail = output[-4000:]
            yield self.Event(
                type="task_progress",
                message=(
                    f"pytest {'PASS' if passed else 'FAIL'} "
                    f"({len(test_files)} test files)"
                ),
                payload={"verifier_output": output_tail},
            )

            if passed:
                self._task_board.record_test_result(task.id, "PASS", [])
                self._write_orchestrator_log(f"Task {task.id}: deterministic verifier PASS")
                self._phase = OrchestratorPhase.DEVELOPING
                yield OrchestratorProgressEvent(
                    phase="completed",
                    message=f"Task {task.id}: deterministic verifier PASS",
                )
                return

            self._task_board.record_test_result(
                task.id, "FAIL", [output_tail or "pytest failed"]
            )
            self._write_orchestrator_log(
                f"Task {task.id}: deterministic verifier FAIL (round {fix_round + 1})"
            )
            if fix_round >= self._config.max_fix_rounds:
                break

            fix_round += 1
            self._fix_round_counts[task.id] = fix_round
            self._phase = OrchestratorPhase.FIXING
            yield self.Event(
                type="phase",
                phase="fixing",
                message=f"Verifier fix round {fix_round}",
            )

            fix_description = (
                f"The deterministic verifier failed for task {task.id}.\n"
                "Fix the implementation and tests, then ensure pytest passes.\n\n"
                f"Verifier command output:\n{output_tail}"
            )
            await dev_agent.resume(fix_description, self._build_dev_context(task))

            dev_holder: list = []
            async for evt in self._consume_stream_run(
                dev_agent, self._config.dev_timeout, dev_holder,
                task_id=task.id,
            ):
                yield evt

            dev_output = dev_holder[0] if dev_holder else SubAgentOutput(
                agent_type="dev", agent_id="", task_id="",
                content="", success=False, error="No output from stream_run",
            )
            if not dev_output.success:
                self._write_orchestrator_log(
                    f"Verifier fix round {fix_round} dev failed for {task.id}",
                    "ERROR",
                )
            self._workspace.scan_and_sync(created_by="dev-fix")

        self._phase = OrchestratorPhase.DEVELOPING
        yield OrchestratorProgressEvent(
            phase="failed",
            message=f"Task {task.id}: deterministic verifier failed",
        )

    async def _stream_test_and_fix_loop_legacy(
        self, task: Task, dev_agent: DevAgent,
    ):
        fix_round = 0
        while fix_round <= self._config.max_fix_rounds and not self._cancelled:
            tester = TesterAgent(parent=self._root_agent)
            test_prompt = self._build_sub_agent_prompt(
                task.description, "tester",
                {"Task ID": task.id, "Title": task.title},
            )
            test_context: Dict[str, Any] = {"workspace_dir": str(self._workspace.root_dir)} if self._long_task_ctx else self._build_tester_context(task)
            test_agent_id = await tester.create(test_prompt, test_context)
            self._active_agents[test_agent_id] = tester

            test_holder: list = []
            async for evt in self._consume_stream_run(
                tester, self._config.tester_timeout, test_holder,
                task_id=task.id,
            ):
                yield evt
            del self._active_agents[test_agent_id]

            test_output = test_holder[0] if test_holder else SubAgentOutput(
                agent_type="tester", agent_id=test_agent_id, task_id="",
                content="", success=False, error="No output from stream_run",
            )

            if not test_output.success:
                self._write_orchestrator_log(
                    f"Tester failed for {task.id}: {test_output.error}",
                    "ERROR",
                )
                if fix_round >= self._config.max_fix_rounds:
                    break
                fix_round += 1
                continue

            parsed = tester.parse_result(test_output.content)
            status = parsed.get("status", "UNKNOWN")
            if status == "PASS":
                self._task_board.record_test_result(
                    task.id, "PASS", parsed.get("issues", [])
                )
                self._write_orchestrator_log(f"Task {task.id}: PASS")
                self._phase = OrchestratorPhase.DEVELOPING
                yield self.Event(
                    type="task_progress", message=f"✅ {task.title} 通过",
                )
                yield OrchestratorProgressEvent(phase="completed", message=f"Task {task.id}: PASS")
                return

            issues = parsed.get("issues", [])
            self._write_orchestrator_log(
                f"Task {task.id}: FAIL (round {fix_round + 1})"
            )
            self._task_board.record_test_result(task.id, "FAIL", issues)
            if fix_round >= self._config.max_fix_rounds:
                break
            fix_round += 1
            self._phase = OrchestratorPhase.FIXING
            yield self.Event(
                type="phase", phase="fixing",
                message=f"第 {fix_round} 轮修复 ({len(issues)} 问题)",
            )
            self._fix_round_counts[task.id] = fix_round

            fix_description = self._build_fix_prompt(
                task, issues, fix_round
            )
            await dev_agent.resume(fix_description, self._build_dev_context(task))

            dev_holder: list = []
            async for evt in self._consume_stream_run(
                dev_agent, self._config.dev_timeout, dev_holder,
                task_id=task.id,
            ):
                yield evt

            dev_output = dev_holder[0] if dev_holder else SubAgentOutput(
                agent_type="dev", agent_id="", task_id="",
                content="", success=False, error="No output from stream_run",
            )
            if not dev_output.success:
                self._write_orchestrator_log(
                    f"Fix round {fix_round} failed for {task.id}", "ERROR"
                )
            self._workspace.scan_and_sync(created_by="dev-fix")

        self._write_orchestrator_log(
            f"Task {task.id}: exceeded max fix rounds", "ERROR"
        )
        self._phase = OrchestratorPhase.DEVELOPING
        yield self.Event(
            type="task_progress",
            message=f"❌ {task.title} 超过最大修复轮次",
        )
        yield OrchestratorProgressEvent(phase="failed", message=f"Task {task.id}: exceeded max fix rounds")

    async def _stream_test_and_fix_loop_multi_dim(
        self, task: Task, dev_agent: DevAgent,
    ):
        coordinator = MultiDimTestCoordinator(
            parent_agent=self._root_agent,
            dimensions=self._config.test_dimensions,
            max_concurrent=self._config.test_concurrency,
            per_test_timeout=self._config.tester_timeout,
        )
        all_issues: List[str] = []
        fix_round = 0
        per_task_results: Dict[str, DimensionResult] = {}

        while fix_round <= self._config.max_fix_rounds and not self._cancelled:
            self._phase = OrchestratorPhase.TESTING
            context = self._build_tester_context(task)
            context["target"] = task.title
            context["fix_round"] = fix_round
            raw_test_desc = (
                f"多维质量审查：{task.title}\n"
                f"Task ID: {task.id}\n"
                "请按你负责的维度进行专项审查，"
                "只读源文件，将报告写入 test-reports/{task.id}-{dimension}.md"
            )
            test_desc = self._build_sub_agent_prompt(
                raw_test_desc, "tester",
                {"Task ID": task.id, "Title": task.title},
            )
            if self._long_task_ctx:
                context = {}

            # --- Run dimension testers via streaming coordinator ---
            results: Dict[str, DimensionResult] = {}
            if fix_round == 0:
                async for agent_evt in coordinator.stream_run_parallel(
                    test_desc, context, results,
                ):
                    yield self._convert_agent_event(agent_evt, task.id)
            else:
                async for agent_evt in coordinator.stream_resume_failed_dimensions(
                    per_task_results, test_desc, context, results,
                ):
                    yield self._convert_agent_event(agent_evt, task.id)

            per_task_results = results
            self._dim_test_results[task.id] = results

            # Emit per-dimension done events for the UI
            for d, r in results.items():
                yield self.Event(
                    type="agent_done", agent_type=f"tester-{d}",
                    task_id=task.id, success=r.passed,
                    message=f"问题数: {r.issue_count}",
                )

            all_pass, passed, failed, errored = coordinator.summarize(results)
            summary_str = "/".join(
                f"{TestDimension.LABELS.get(d, d)}"
                f"{'P' if results[d].passed else 'F' if results[d].failed else 'E'}"
                for d in results
            )
            self._write_orchestrator_log(
                f"Test {task.id} R{fix_round}: {summary_str}"
            )
            yield self.Event(
                type="task_progress",
                message=f"R{fix_round} 测试: {summary_str}",
            )

            for d, r in results.items():
                if r.report_path:
                    self._task_board.record_test_result(
                        task.id, r.status,
                        [f"[{d}] {i}" for i in r.issues] or
                        [f"[{d}] (no detail)"]
                    )
                    break

            if all_pass:
                self._task_board.record_test_result(task.id, "PASS", [])
                self._write_orchestrator_log(
                    f"Task {task.id}: ALL DIMENSIONS PASS (round {fix_round})"
                )
                self._phase = OrchestratorPhase.DEVELOPING
                yield self.Event(
                    type="task_progress",
                    message=f"✅ {task.title} 全部维度通过 (R{fix_round})",
                )
                yield OrchestratorProgressEvent(phase="completed", message=f"Task {task.id}: ALL DIMENSIONS PASS (round {fix_round})")
                return

            all_issues = [
                f"[{d}] {i}" for d, r in results.items() for i in r.issues
            ]
            self._task_board.record_test_result(
                task.id, "FAIL",
                all_issues or ["(see test-reports)"]
            )
            self._write_orchestrator_log(
                f"Task {task.id}: FAIL (round {fix_round + 1}) — "
                f"failed={failed} errored={errored}"
            )

            if fix_round >= self._config.max_fix_rounds:
                break
            fix_round += 1
            self._fix_round_counts[task.id] = fix_round
            self._phase = OrchestratorPhase.FIXING
            yield self.Event(
                type="phase", phase="fixing",
                message=f"第 {fix_round} 轮修复 ({len(all_issues)} 问题)",
            )

            failed_reports = {
                d: r.report_path for d, r in results.items()
                if (r.failed or r.status == "ERROR") and r.report_path
            }
            fix_prompt = self._build_multi_dim_fix_prompt(
                task, results, failed_reports, fix_round
            )
            await dev_agent.resume(fix_prompt, self._build_dev_context(task))

            dev_holder: list = []
            async for evt in self._consume_stream_run(
                dev_agent, self._config.dev_timeout, dev_holder,
                task_id=task.id,
            ):
                yield evt

            dev_output = dev_holder[0] if dev_holder else SubAgentOutput(
                agent_type="dev", agent_id="", task_id="",
                content="", success=False, error="No output from stream_run",
            )
            if not dev_output.success:
                self._write_orchestrator_log(
                    f"Fix round {fix_round} dev failed for {task.id}",
                    "ERROR",
                )
            self._workspace.scan_and_sync(created_by="dev-fix")

            lessons = []
            for d, r in results.items():
                if r.failed or r.status == "ERROR":
                    lessons.append(
                        f"## {TestDimension.LABELS.get(d, d)} (R{fix_round})\n"
                        + "\n".join(f"- {i}" for i in r.issues[:5])
                    )
            if lessons:
                self._workspace.append_lesson(
                    f"Multi-dim fix R{fix_round} for {task.title}",
                    "\n\n".join(lessons),
                )

        self._write_orchestrator_log(
            f"Task {task.id}: exceeded max fix rounds",
            "ERROR",
        )
        self._phase = OrchestratorPhase.DEVELOPING
        yield self.Event(
            type="task_progress",
            message=f"❌ {task.title} 超过最大修复轮次",
        )
        yield OrchestratorProgressEvent(phase="failed", message=f"Task {task.id}: exceeded max fix rounds")

    async def _stream_phase_final_test(self) -> bool:
        self._write_orchestrator_log("Phase: Final Testing")
        if not self._config.enable_final_test:
            self._write_orchestrator_log("Final testing skipped by config")
            yield OrchestratorProgressEvent(phase="completed", message="Final testing skipped")
            return

        completed_tasks = self._task_board.get_completed()
        if not completed_tasks:
            self._write_orchestrator_log("No completed tasks to final-test")
            yield OrchestratorProgressEvent(phase="completed", message="No completed tasks to final-test")
            return

        all_pass = True
        for task in completed_tasks:
            tester = TesterAgent(parent=self._root_agent)
            final_test_desc = f"Final integration test for: {task.title}"
            final_prompt = self._build_sub_agent_prompt(
                final_test_desc, "tester",
                {"Task ID": task.id, "Title": task.title,
                 "Extra Instructions": "This is a FINAL integration test. Verify everything works together."},
            )
            final_context: Dict[str, Any] = {"workspace_dir": str(self._workspace.root_dir)} if self._long_task_ctx else self._build_tester_context(task)
            if not self._long_task_ctx:
                final_context["extra_instructions"] = (
                    "This is a FINAL integration test. "
                    "Verify everything works together."
                )
            agent_id = await tester.create(final_prompt, final_context)
            self._active_agents[agent_id] = tester

            test_holder: list = []
            async for evt in self._consume_stream_run(
                tester, self._config.tester_timeout, test_holder,
                task_id=task.id,
            ):
                yield evt
            del self._active_agents[agent_id]

            output = test_holder[0] if test_holder else SubAgentOutput(
                agent_type="tester", agent_id=agent_id, task_id="",
                content="", success=False, error="No output from stream_run",
            )

            if output.success:
                parsed = tester.parse_result(output.content)
                if parsed.get("status") != "PASS":
                    all_pass = False
                    self._write_orchestrator_log(
                        f"Final test FAIL for {task.id}: "
                        f"{parsed.get('issues', [])}", "WARNING"
                    )
            else:
                all_pass = False

        if all_pass:
            self._write_orchestrator_log("All final tests PASSED")
        yield OrchestratorProgressEvent(
            phase="completed" if all_pass else "failed",
            message="All final tests PASSED" if all_pass else "Final testing found issues",
        )

    async def stream_execute_v2(
        self, requirement: str, input_files: Optional[List[str]] = None,
    ) -> "AsyncIterator[AgentEvent]":
        """与 stream_execute 相同的流程,但 yield AgentEvent 协议事件.

        使用 OrchestratorEventAdapter 将内部 Event 转换为协议事件.
        Heartbeat 和 LongTaskContext 已由 stream_execute 管理.
        """
        adapter = OrchestratorEventAdapter()
        async for internal_event in self.stream_execute(requirement, input_files):
            yield adapter.adapt(internal_event)

    async def stream_execute_single_task_v2(
        self,
        requirement: str,
        title: str = "Deep single task",
        input_files: Optional[List[str]] = None,
    ) -> "AsyncIterator[AgentEvent]":
        """AgentEvent wrapper for :meth:`stream_execute_single_task`."""
        adapter = OrchestratorEventAdapter()
        async for internal_event in self.stream_execute_single_task(
            requirement, title=title, input_files=input_files
        ):
            yield adapter.adapt(internal_event)
