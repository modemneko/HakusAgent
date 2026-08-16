"""Fleet 编排器 — 指挥官 + 专业舰船的自组织蜂群.

核心流程:
  1. 查经验库 → 获取策略建议（替代 PARL 的"学习"）
  2. Commander 分析任务 → 输出 JSON 专家列表（自组织）
  3. ExpertFactory 创建专家
  4. ParallelScheduler 全局并行执行
  5. Commander 汇总结果
  6. 记录经验 → 更新经验库

与 Deep 模式的区别:
  - Deep: 固定 Planner→Dev→Test 串行流水线
  - Fleet: Commander 动态拆解 → N 个专家全局并行 → Commander 汇总
  - Deep: 5-15 子任务串行
  - Fleet: 30+ 专家并行（Semaphore 限速）
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

from utils.logger import get_logger
from ..protocol.events import TextDelta, ToolCallFinished, TurnCompleted
from ..sub_agents import BaseSubAgent
from .experience_store import ExperienceStore, Strategy
from .expert_factory import ExpertFactory, ExpertSpec
from .scheduler import ParallelScheduler, ScheduledTask, TaskStatus

logger = get_logger(__name__)


COMMANDER_DECOMPOSE_PROMPT = """\
You are the Commander (Planner) of a Fleet of expert agents working in parallel
using a CTDE (Centralized Training, Distributed Execution) architecture.

## Your Mission
Analyze the user's task and decompose it into INDEPENDENT expert assignments.
Each expert will work in parallel on its own subdirectory of the project.

## Output Format (MUST be valid JSON)
Respond with ONLY a JSON block (use ```json fences):

```json
{
  "analysis": "Brief analysis of the task and decomposition strategy",
  "experts": [
    {
      "id": "expert-1",
      "role": "Frontend Architect",
      "task": "Specific task description for this expert",
      "tools": ["dev"],
      "file_scope": ["path/or/glob"],
      "sub_dir": "frontend",
      "priority": 1,
      "timeout": 300
    }
  ]
}
```

## Tool Presets (use these names in "tools")
- "dev": read_file, write_file, edit_file, bash, glob, grep, list_dir (full dev)
- "test": read_file, bash, glob, grep, list_dir (testing only)
- "research": read_file, glob, grep, web_search, web_fetch (research)
- "review": read_file, glob, grep, list_dir (code review)
- "write_only": read_file, write_file, edit_file, glob, grep (no bash)

## sub_dir — KEY for parallel work
- Each expert MUST be assigned a sub_dir relative to the project root.
- Sub_dir isolates experts: expert-A working in "frontend/" cannot accidentally
  overwrite files expert-B is writing in "backend/".
- Use "" or "." only for experts that genuinely need full-project access
  (e.g. a reviewer or orchestrator role).
- Prefer granular sub_dirs: "frontend/src/components", "backend/api/routes",
  "docs/api" — not just "frontend" / "backend".
- Sub_dirs do NOT need to exist yet — the runtime will create them.
- NEVER use absolute paths, "..", or leading "/" in sub_dir.

## Decomposition Rules
1. Each expert MUST have an INDEPENDENT task (no cross-dependencies)
2. Aim for 5-30 experts based on task complexity
3. Break large files into logical units (e.g., "HTML structure" + "CSS styles" + "JS logic")
4. Assign priority 1 to foundational tasks, 2 to secondary, 3 to polish
5. Set reasonable timeout (60-600s) per expert based on task size
6. Each expert should produce a COMPLETE, SELF-CONTAINED deliverable
7. Include file_scope for every expert. File scopes that can write must be disjoint.
8. If two experts need to edit the same file, merge them into one expert.
9. Prefer giving each expert a distinct sub_dir. Two experts with overlapping
   sub_dirs MUST have disjoint file_scope.

## Critical
- Output ONLY the JSON block, no prose before/after
- Every expert must be able to work without waiting for others
- If tasks have dependencies, merge them into one expert"""


COMMANDER_SYNTHHESIZE_PROMPT = """\
You are the Commander synthesizing results from a Fleet of expert agents.

## Your Mission
Review all expert results (delivered in the user message below) and produce
a final summary for the user.

## Output
Produce a concise summary that:
1. Lists what was accomplished (files created/modified, per expert)
2. Notes any failures or incomplete work
3. Provides next steps if any integration is needed
Keep it under 500 words."""


REVIEWER_PROMPT = """\
You are the Reviewer of a Fleet of expert agents. Your job is to assess the
quality of each expert's work and decide whether the run can be considered
complete, or whether specific experts need to be re-run with feedback.

## Your Inputs
You will receive (in the user message, not here):
- The original task description
- The workspace path
- A list of expert results, each with: id, role, sub_dir, status, and a
  preview of the expert's output

## Output Format (MUST be valid JSON, fenced with ```json)
```json
{
  "approved": true,
  "summary": "One-paragraph overall assessment",
  "issues": [
    {
      "expert_id": "expert-3",
      "severity": "high",
      "fix_hint": "The CSS file references a font that doesn't exist; replace with system-ui"
    }
  ]
}
```

## Rules
1. ``approved`` is true ONLY if the run meets the original task's goals. If any
   high-severity issue exists, approved MUST be false.
2. ``issues`` is empty when approved. For non-approved runs, list each expert
   that needs a re-run with a CONCRETE fix_hint that expert can act on.
3. Severity values: "high" (broken/missing), "medium" (works but has flaws),
   "low" (polish). Only re-run experts with high or medium severity.
4. Do NOT suggest re-running experts whose status is "failed" or "timeout" —
   those will be re-tried automatically. Focus on experts whose output exists
   but is incorrect.
5. Keep fix_hint under 100 words. Be specific about what file/line/behavior
   needs to change. Vague hints like "improve quality" are useless.

## Critical
- Output ONLY the JSON block, no prose before/after.
- If you can't decide (e.g. outputs are too short to judge), set approved=false
  with a single issue asking for more detail from the relevant expert.
"""


@dataclass
class FleetResult:
    """Fleet 模式执行结果."""
    success: bool
    partial_success: bool = False
    expert_count: int = 0
    completed: int = 0
    failed: int = 0
    timeout: int = 0
    elapsed: float = 0.0
    tokens_estimate: int = 0
    summary: str = ""
    expert_results: List[Dict[str, Any]] = field(default_factory=list)
    strategy_used: Optional[Strategy] = None
    # CTDE v2 additions — Reviewer gate
    reviewer_approved: Optional[bool] = None
    reviewer_summary: str = ""
    reviewer_issues: List[Dict[str, Any]] = field(default_factory=list)
    # run_id — set by run_with_events() so the frontend can address
    # individual experts for counterfactual re-runs.
    run_id: str = ""


@dataclass
class ExpertRunStatus:
    """One expert's status in a fleet run (for the frontend roster)."""
    id: str
    role: str
    sub_dir: str
    status: str  # "pending" | "running" | "completed" | "failed" | "timeout"
    elapsed: float = 0.0
    output_preview: str = ""
    error: Optional[str] = None
    rerun_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "sub_dir": self.sub_dir,
            "status": self.status,
            "elapsed": round(self.elapsed, 1),
            "output_preview": self.output_preview[:500],
            "error": self.error,
            "rerun_count": self.rerun_count,
        }


class FleetOrchestrator:
    """Fleet 编排器 — 指挥官 + 专业舰船.

    CTDE v2 architecture (run_with_events):
      [Planner] → experts[] parallel (each with sub_dir) → [Reviewer]
                       ↑__________________________________|
                          (reviewer can request re-runs)

    The legacy ``run()`` method is kept for backward compatibility.
    """

    def __init__(
        self,
        root_agent: Any,
        workspace_dir: str,
        concurrency: int = 10,
        commander_timeout: int = 180,
    ):
        self._root_agent = root_agent
        self._workspace_dir = workspace_dir
        self._commander_timeout = commander_timeout
        self._scheduler = ParallelScheduler(concurrency=concurrency)
        self._experience = ExperienceStore()
        self._factory = ExpertFactory(root_agent)
        self._cancelled = False
        # v2 state — persisted for counterfactual reruns
        self._run_id: str = ""
        self._expert_specs: List[ExpertSpec] = []
        self._expert_results: Dict[str, ScheduledTask] = {}
        self._rerun_counts: Dict[str, int] = {}

    def cancel(self) -> None:
        """取消执行."""
        self._cancelled = True

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def expert_specs(self) -> List[ExpertSpec]:
        """Current run's expert specs (empty before planner runs)."""
        return list(self._expert_specs)

    def get_expert_status(self, expert_id: str) -> Optional[ExpertRunStatus]:
        """Get a snapshot of one expert's status for the frontend."""
        if expert_id not in self._expert_results:
            return None
        spec = next((s for s in self._expert_specs if s.id == expert_id), None)
        if not spec:
            return None
        r = self._expert_results[expert_id]
        return ExpertRunStatus(
            id=r.id,
            role=r.role,
            sub_dir=spec.sub_dir,
            status=r.status.value,
            elapsed=r.elapsed,
            output_preview=r.result or "",
            error=r.error,
            rerun_count=self._rerun_counts.get(expert_id, 0),
        )

    def all_expert_statuses(self) -> List[ExpertRunStatus]:
        """All expert statuses for the current run."""
        out: List[ExpertRunStatus] = []
        for spec in self._expert_specs:
            r = self._expert_results.get(spec.id)
            if r is None:
                out.append(ExpertRunStatus(
                    id=spec.id, role=spec.role, sub_dir=spec.sub_dir,
                    status="pending",
                ))
            else:
                out.append(ExpertRunStatus(
                    id=r.id, role=r.role, sub_dir=spec.sub_dir,
                    status=r.status.value, elapsed=r.elapsed,
                    output_preview=r.result or "", error=r.error,
                    rerun_count=self._rerun_counts.get(spec.id, 0),
                ))
        return out

    def _lock_keys_for_spec(self, spec: ExpertSpec) -> List[str]:
        keys: List[str] = []
        for item in spec.file_scope:
            scope = str(item).strip()
            if not scope:
                continue
            normalized = os.path.normpath(scope).replace("\\", "/")
            if normalized in ("", "."):
                continue
            keys.append(normalized.lower() if os.name == "nt" else normalized)

        if keys:
            return sorted(set(keys))

        tools = {tool.lower() for tool in spec.tools}
        write_tools = {
            "dev",
            "write_only",
            "write_file",
            "edit_file",
            "write",
            "edit",
            "bash",
        }
        if tools & write_tools:
            return ["__workspace_write__"]
        return []

    async def run(self, task_description: str) -> FleetResult:
        """主流程: Commander 分析 → 查经验库 → 并行调度 → 汇总 → 记经验."""
        start = time.time()
        logger.info(
            f"FleetOrchestrator started: task='{task_description[:80]}...' "
            f"workspace={self._workspace_dir}"
        )

        # 1. 查经验库
        cached_strategy = self._experience.lookup(task_description)
        if cached_strategy:
            logger.info(
                f"Experience hit: {cached_strategy.expert_count} experts, "
                f"parallelism={cached_strategy.parallelism}"
            )

        # 2. Commander 分析任务
        expert_specs = await self._commander_decompose(task_description, cached_strategy)
        if self._cancelled:
            return FleetResult(
                success=False,
                elapsed=time.time() - start,
                summary="Fleet cancelled before scheduling experts",
            )

        if not expert_specs:
            # 回退：Commander 失败，用简单拆解
            logger.warning("Commander decompose failed, using fallback")
            expert_specs = self._fallback_decompose(task_description)

        if not expert_specs:
            return FleetResult(
                success=False,
                elapsed=time.time() - start,
                summary="Fleet failed: Commander could not decompose task",
            )

        logger.info(f"Commander decomposed into {len(expert_specs)} experts")

        # 3. 创建调度任务
        scheduled_tasks: List[ScheduledTask] = []
        for spec in expert_specs:
            scheduled_tasks.append(ScheduledTask(
                id=spec.id,
                role=spec.role,
                description=spec.task,
                tools=spec.tools,
                file_scope=spec.file_scope,
                lock_keys=self._lock_keys_for_spec(spec),
                priority=spec.priority,
                timeout=spec.timeout,
            ))

        # 4. 并行调度
        results = await self._scheduler.schedule_all(
            scheduled_tasks,
            self._execute_expert,
        )
        if self._cancelled:
            return FleetResult(
                success=False,
                expert_count=len(expert_specs),
                completed=sum(1 for r in results if r.status == TaskStatus.COMPLETED),
                failed=sum(1 for r in results if r.status == TaskStatus.FAILED),
                timeout=sum(1 for r in results if r.status == TaskStatus.TIMEOUT),
                elapsed=round(time.time() - start, 1),
                summary="Fleet cancelled",
            )

        # 5. Commander 汇总
        summary = await self._commander_synthesize(task_description, results)

        # 6. 记录经验
        elapsed = time.time() - start
        completed = sum(1 for r in results if r.status == TaskStatus.COMPLETED)
        failed = sum(1 for r in results if r.status == TaskStatus.FAILED)
        timeout = sum(1 for r in results if r.status == TaskStatus.TIMEOUT)
        success_strict = bool(results) and completed == len(results)
        success_lenient = completed >= len(results) * 0.8 if results else False

        tokens_estimate = self._estimate_tokens(expert_specs, elapsed)
        strategy = Strategy(
            expert_count=len(expert_specs),
            expert_roles=[s.role for s in expert_specs],
            parallelism=self._scheduler._concurrency,
            avg_timeout=int(sum(s.timeout for s in expert_specs) / len(expert_specs)),
        )
        self._experience.record(
            task_description, strategy, success_strict, elapsed, tokens_estimate
        )

        result = FleetResult(
            success=success_strict,
            partial_success=success_lenient,
            expert_count=len(expert_specs),
            completed=completed,
            failed=failed,
            timeout=timeout,
            elapsed=round(elapsed, 1),
            tokens_estimate=tokens_estimate,
            summary=summary,
            expert_results=[
                {
                    "id": r.id,
                    "role": r.role,
                    "status": r.status.value,
                    "elapsed": round(r.elapsed, 1),
                    "result": (r.result or "")[:500],
                    "error": r.error,
                }
                for r in results
            ],
            strategy_used=strategy,
        )

        logger.info(
            f"FleetOrchestrator completed: {completed}/{len(results)} experts "
            f"succeeded, {elapsed:.1f}s, ~{tokens_estimate} tokens"
        )

        return result

    async def _commander_decompose(
        self,
        task_description: str,
        cached_strategy: Optional[Strategy],
    ) -> List[ExpertSpec]:
        """Commander 分析任务，输出 JSON 拆解."""
        commander = BaseSubAgent(
            parent=self._root_agent,
            agent_type="fleet-commander",
            allowed_tools=["read_file", "glob", "grep", "list_dir",
                          "Read", "Glob", "Grep", "ListDir"],
            system_template=COMMANDER_DECOMPOSE_PROMPT,
        )

        # 构建分析 prompt
        prompt_parts = [f"## Task to Decompose\n{task_description}"]
        prompt_parts.append(f"\n## Workspace\n{self._workspace_dir}")
        if cached_strategy:
            prompt_parts.append(
                f"\n## Experience Hint\n"
                f"Similar past tasks used {cached_strategy.expert_count} experts "
                f"with parallelism={cached_strategy.parallelism}. "
                f"Consider this as a reference."
            )
        prompt = "\n".join(prompt_parts)

        await commander.create(prompt, {"workspace_dir": self._workspace_dir})

        logger.info("Commander analyzing task...")
        output = await commander.run(timeout=self._commander_timeout)

        if not output.success or not output.content:
            logger.warning(f"Commander failed: {output.error}")
            return []

        return self._parse_expert_json(output.content)

    def _parse_expert_json(self, content: str) -> List[ExpertSpec]:
        """从 Commander 输出中解析 JSON 专家列表."""
        # 尝试提取 ```json ... ``` 块
        match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                experts = data.get("experts", [])
                if isinstance(experts, list):
                    specs = [ExpertSpec.from_dict(e) for e in experts]
                    if specs:
                        return specs
            except json.JSONDecodeError:
                pass

        # 尝试直接解析整个内容
        try:
            data = json.loads(content)
            experts = data.get("experts", [])
            if isinstance(experts, list):
                return [ExpertSpec.from_dict(e) for e in experts]
        except json.JSONDecodeError:
            pass

        # 尝试找到 JSON 对象 { ... }
        start = content.find('{')
        end = content.rfind('}')
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(content[start:end + 1])
                experts = data.get("experts", [])
                if isinstance(experts, list):
                    return [ExpertSpec.from_dict(e) for e in experts]
            except json.JSONDecodeError:
                pass

        logger.warning(
            f"Failed to parse expert JSON from Commander output "
            f"(len={len(content)})"
        )
        return []

    def _fallback_decompose(self, task_description: str) -> List[ExpertSpec]:
        """回退拆解：Commander 失败时的简单策略."""
        logger.info("Using fallback decomposition")
        return [
            ExpertSpec(
                id="expert-fallback",
                role="General Developer",
                task=task_description,
                tools=["dev"],
                priority=1,
                timeout=600,
            ),
        ]

    async def _execute_expert(self, task: ScheduledTask) -> str:
        """执行单个专家任务（被 ParallelScheduler 调用）.

        Returns:
            专家的输出内容

        Notes:
            - Looks up the ExpertSpec saved during run_with_events() so the
              sub_dir is propagated correctly. Falls back to constructing
              a spec from the ScheduledTask fields if none is registered
              (legacy code path).
            - On completion, stores the result in self._expert_results so
              the reviewer stage and counterfactual re-runs can read it.
        """
        if self._cancelled:
            raise asyncio.CancelledError()

        spec = next((s for s in self._expert_specs if s.id == task.id), None)
        if spec is None:
            spec = ExpertSpec(
                id=task.id, role=task.role, task=task.description,
                tools=task.tools, file_scope=task.file_scope,
                priority=task.priority, timeout=task.timeout,
            )

        # 创建专家
        expert = await self._factory.create_expert(spec, self._workspace_dir)

        # 执行
        logger.info(f"Expert {task.id} ({task.role}) starting...")
        output = await expert.run(timeout=task.timeout)

        # Persist result so reviewer / rerun can read it
        self._expert_results[task.id] = task

        if output.success:
            logger.info(
                f"Expert {task.id} ({task.role}) completed in "
                f"{output.execution_time:.1f}s"
            )
        else:
            logger.warning(
                f"Expert {task.id} ({task.role}) failed: {output.error}"
            )
            raise RuntimeError(output.error or output.content or "Expert failed")

        return output.content or output.error or ""

    async def _commander_synthesize(
        self,
        task_description: str,
        results: List[ScheduledTask],
    ) -> str:
        """Commander 汇总所有专家的结果."""
        # 构建专家结果摘要
        expert_summaries = []
        for r in results:
            status_icon = {
                TaskStatus.COMPLETED: "✓",
                TaskStatus.FAILED: "✗",
                TaskStatus.TIMEOUT: "⏱",
                TaskStatus.RUNNING: "→",
                TaskStatus.PENDING: "○",
            }.get(r.status, "?")
            result_preview = (r.result or r.error or "no output")[:200]
            expert_summaries.append(
                f"[{status_icon}] {r.id} ({r.role}): {result_preview}"
            )

        results_text = "\n".join(expert_summaries)

        # 如果结果少，直接返回摘要，不再调用 LLM
        if len(results) <= 3:
            return f"Fleet completed with {len(results)} experts:\n{results_text}"

        # 用 Commander 汇总
        commander = BaseSubAgent(
            parent=self._root_agent,
            agent_type="fleet-commander-synth",
            allowed_tools=["read_file", "glob", "list_dir",
                          "Read", "Glob", "ListDir"],
            system_template=COMMANDER_SYNTHHESIZE_PROMPT,
        )

        prompt = (
            f"## Original Task\n{task_description}\n\n"
            f"## Expert Results\n{results_text}"
        )
        await commander.create(prompt, {"workspace_dir": self._workspace_dir})

        try:
            output = await commander.run(timeout=120)
            if output.success and output.content:
                return output.content
        except Exception as e:
            logger.warning(f"Commander synthesize failed: {e}")

        return f"Fleet completed with {len(results)} experts:\n{results_text}"

    def _estimate_tokens(
        self, specs: List[ExpertSpec], elapsed: float
    ) -> int:
        """估算 token 消耗."""
        # 粗略估算：每个专家平均 5K tokens
        # + Commander 两次调用约 10K
        base = len(specs) * 5000 + 10000
        # 根据耗时调整（更长 = 更多轮次）
        time_factor = max(1.0, elapsed / 60.0 * 0.5)
        return int(base * time_factor)

    @property
    def experience_stats(self) -> Dict[str, Any]:
        """获取经验库统计."""
        return self._experience.get_stats()

    # ============================================================
    # CTDE v2 — event-driven run + reviewer gate + counterfactual rerun
    # ============================================================

    async def run_with_events(
        self, task_description: str, run_id: str
    ) -> "AsyncIterator[Dict[str, Any]]":
        """Event-driven fleet run yielding structured events for SSE.

        Yields dict events with ``event_type`` field:
          - orchestrator_phase_changed (planner_started, planner_completed, ...)
          - task_progress (expert roster update)
          - text_delta (human-readable progress messages)
          - turn_completed (final, success=True/False)

        Each event is a plain dict so the caller (agent_bridge) can wrap
        it in the legacy chunk shape without conversion.

        Phase order:
          planner_started → planner_completed →
          workers_started → worker_status (multiple) → workers_completed →
          reviewer_started → reviewer_completed →
          (if rejected & retries left) workers_started again → ...
          turn_completed
        """
        import uuid

        from .scheduler import TaskStatus as _TS

        self._run_id = run_id
        self._cancelled = False
        start = time.time()

        def phase_event(to_phase: str, detail: str = "") -> Dict[str, Any]:
            return {
                "event_type": "orchestrator_phase_changed",
                "from_phase": "idle",
                "to_phase": to_phase,
                "phase": to_phase,
                "detail": detail,
            }

        def progress_event(completed: int, total: int, current: str, phase: str) -> Dict[str, Any]:
            return {
                "event_type": "task_progress",
                "completed": completed,
                "total": total,
                "current_task": current,
                "phase": phase,
                "detail": "",
            }

        def text_event(text: str) -> Dict[str, Any]:
            return {"event_type": "text_delta", "text": text}

        # ── Phase 1: Planner ──────────────────────────────────────────
        yield phase_event("planning", "Planner analyzing task")
        yield text_event("🧠 Planner 正在拆解任务...\n\n")

        cached_strategy = self._experience.lookup(task_description)
        if cached_strategy:
            yield text_event(
                f"📚 经验匹配：{cached_strategy.expert_count} 专家 / "
                f"并行度 {cached_strategy.parallelism}\n"
            )

        try:
            expert_specs = await self._commander_decompose(
                task_description, cached_strategy
            )
        except Exception as e:
            logger.warning(f"Planner crashed: {e}", exc_info=True)
            expert_specs = []

        if self._cancelled:
            yield {
                "event_type": "cancelled",
                "reason": "user_interrupted",
                "partial_content": "Fleet cancelled during planning",
            }
            return

        if not expert_specs:
            logger.warning("Planner returned no experts, using fallback")
            expert_specs = self._fallback_decompose(task_description)

        # Save specs so _execute_expert can read sub_dir + counterfactual
        # reruns can find them later.
        self._expert_specs = list(expert_specs)
        self._expert_results = {}
        self._rerun_counts = {s.id: 0 for s in expert_specs}

        yield text_event(
            f"✓ Planner 拆解完成：{len(expert_specs)} 个专家\n"
        )
        # Emit one progress event per expert so the frontend roster
        # appears immediately (all "pending") before execution starts.
        for spec in expert_specs:
            yield {
                "event_type": "task_progress",
                "completed": 0,
                "total": len(expert_specs),
                "current_task": spec.id,
                "phase": "workers_pending",
                "detail": f"{spec.role} @ {spec.sub_dir or '<root>'}",
            }

        # ── Phase 2: Workers parallel ────────────────────────────────
        max_review_rounds = int(os.environ.get("HAKUS_FLEET_MAX_ROUNDS", "2"))
        review: Dict[str, Any] = {"approved": True, "summary": "", "issues": []}
        reviewer_issues: List[Dict[str, Any]] = []
        for review_round in range(max_review_rounds + 1):
            yield phase_event(
                "developing",
                f"Workers round {review_round + 1}/{max_review_rounds + 1}"
            )
            if review_round == 0:
                yield text_event(
                    f"\n⚙️ 启动 {len(expert_specs)} 个专家并行执行...\n\n"
                )
            else:
                yield text_event(
                    f"\n🔄 第 {review_round + 1} 轮：根据 Reviewer 反馈重跑问题专家...\n\n"
                )

            # Build scheduled tasks for experts that need to (re)run.
            # On round 0 this is all specs. On later rounds, only the
            # experts the reviewer flagged.
            if review_round == 0:
                to_run = list(expert_specs)
            else:
                flagged_ids = {iss.get("expert_id") for iss in reviewer_issues}
                to_run = [s for s in expert_specs if s.id in flagged_ids]
                if not to_run:
                    yield text_event("✓ Reviewer 没有要求重跑任何专家\n")
                    break

            scheduled_tasks: List[ScheduledTask] = []
            for spec in to_run:
                scheduled_tasks.append(ScheduledTask(
                    id=spec.id, role=spec.role, description=spec.task,
                    tools=spec.tools, file_scope=spec.file_scope,
                    lock_keys=self._lock_keys_for_spec(spec),
                    priority=spec.priority, timeout=spec.timeout,
                ))

            # Wire progress callbacks to emit events
            progress_q: asyncio.Queue = asyncio.Queue()
            last_status: Dict[str, str] = {}

            def _on_progress(task: ScheduledTask) -> None:
                try:
                    progress_q.put_nowait({
                        "id": task.id, "role": task.role,
                        "status": task.status.value,
                        "elapsed": task.elapsed, "error": task.error,
                    })
                except Exception:
                    pass

            # Reset scheduler callbacks so we don't double-emit from prior rounds
            self._scheduler._progress_callbacks = [_on_progress]

            # Run scheduler in background so we can pump progress events
            sched_task = asyncio.create_task(
                self._scheduler.schedule_all(scheduled_tasks, self._execute_expert)
            )

            completed_count = 0
            total_count = len(scheduled_tasks)
            while not sched_task.done():
                if getattr(self._root_agent, "_cancelled", False) or self._cancelled:
                    sched_task.cancel()
                    yield {
                        "event_type": "cancelled",
                        "reason": "user_interrupted",
                        "partial_content": "Fleet cancelled during workers",
                    }
                    return
                try:
                    update = await asyncio.wait_for(progress_q.get(), timeout=0.5)
                    eid = update["id"]
                    new_status = update["status"]
                    if last_status.get(eid) != new_status:
                        last_status[eid] = new_status
                        # Find spec to get sub_dir
                        sp = next((s for s in expert_specs if s.id == eid), None)
                        sub_dir = sp.sub_dir if sp else ""
                        icon = {
                            "running": "▶", "completed": "✓",
                            "failed": "✗", "timeout": "⏱",
                        }.get(new_status, "?")
                        yield text_event(
                            f"{icon} {eid} ({update['role']}) "
                            f"@ {sub_dir or '<root>'} → {new_status}\n"
                        )
                        # Update task_progress with the latest counts
                        if new_status in ("completed", "failed", "timeout"):
                            completed_count += 1
                        yield progress_event(
                            completed_count, total_count, eid,
                            f"workers_{new_status}",
                        )
                except asyncio.TimeoutError:
                    continue

            results = await sched_task
            # Merge results into _expert_results (keep prior round results
            # for experts that didn't re-run)
            for r in results:
                self._expert_results[r.id] = r

            # ── Phase 3: Reviewer ────────────────────────────────────
            yield phase_event("reviewing", "Reviewer assessing expert outputs")
            yield text_event("\n📋 Reviewer 正在审查专家产出...\n\n")

            try:
                review = await self._review_experts(task_description)
            except Exception as e:
                logger.warning(f"Reviewer crashed: {e}", exc_info=True)
                review = {
                    "approved": True,
                    "summary": f"Reviewer crashed ({e}); auto-approving",
                    "issues": [],
                }

            reviewer_issues = review.get("issues", [])
            approved = bool(review.get("approved", True))

            yield {
                "event_type": "task_progress",
                "completed": total_count,
                "total": total_count,
                "current_task": "reviewer",
                "phase": "review_completed",
                "detail": review.get("summary", "")[:300],
            }

            if approved or review_round >= max_review_rounds:
                if not approved:
                    yield text_event(
                        f"⚠️ Reviewer 仍未通过，但已达到最大重跑轮次 "
                        f"({max_review_rounds})，结束\n"
                    )
                else:
                    yield text_event(
                        f"✓ Reviewer 通过：{review.get('summary', '')[:200]}\n"
                    )
                break

            # Not approved — emit issues and re-loop
            yield text_event(
                f"✗ Reviewer 未通过，{len(reviewer_issues)} 个问题需要修复：\n"
            )
            for iss in reviewer_issues:
                yield text_event(
                    f"  - {iss.get('expert_id')}: [{iss.get('severity')}] "
                    f"{iss.get('fix_hint', '')[:100]}\n"
                )
                # Bump rerun_count for flagged experts
                eid = iss.get("expert_id")
                if eid in self._rerun_counts:
                    self._rerun_counts[eid] += 1

        # ── Phase 4: Synthesize + finish ────────────────────────────
        yield phase_event("synthesizing", "Commander synthesizing final summary")
        all_results = list(self._expert_results.values())
        summary = await self._commander_synthesize(task_description, all_results)

        elapsed = time.time() - start
        completed = sum(1 for r in all_results if r.status == _TS.COMPLETED)
        failed = sum(1 for r in all_results if r.status == _TS.FAILED)
        timeout = sum(1 for r in all_results if r.status == _TS.TIMEOUT)
        success_strict = bool(all_results) and failed == 0 and timeout == 0

        # Record experience
        tokens_estimate = self._estimate_tokens(expert_specs, elapsed)
        strategy = Strategy(
            expert_count=len(expert_specs),
            expert_roles=[s.role for s in expert_specs],
            parallelism=self._scheduler._concurrency,
            avg_timeout=int(sum(s.timeout for s in expert_specs) / len(expert_specs)),
        )
        self._experience.record(
            task_description, strategy, success_strict, elapsed, tokens_estimate
        )

        # Build final result
        result = FleetResult(
            success=success_strict,
            partial_success=completed >= len(expert_specs) * 0.8,
            expert_count=len(expert_specs),
            completed=completed,
            failed=failed,
            timeout=timeout,
            elapsed=round(elapsed, 1),
            tokens_estimate=tokens_estimate,
            summary=summary,
            expert_results=[self.get_expert_status(s.id).to_dict()
                           for s in expert_specs
                           if self.get_expert_status(s.id)],
            strategy_used=strategy,
            reviewer_approved=review.get("approved"),
            reviewer_summary=review.get("summary", ""),
            reviewer_issues=reviewer_issues,
            run_id=run_id,
        )

        yield text_event(
            f"\n📊 Fleet 完成：{completed}/{len(expert_specs)} 专家成功，"
            f"耗时 {elapsed:.1f}s\n\n"
        )

        yield {
            "event_type": "turn_completed",
            "content": summary,
            "total_time": elapsed,
            "output_tokens": tokens_estimate,
            "fleet_result": {
                "success": result.success,
                "expert_count": result.expert_count,
                "completed": result.completed,
                "failed": result.failed,
                "reviewer_approved": result.reviewer_approved,
                # Surface reviewer issues so the frontend can render
                # per-expert fix hints and offer one-click rerun.
                "reviewer_summary": result.reviewer_summary,
                "reviewer_issues": result.reviewer_issues,
                "experts": result.expert_results,
                "run_id": run_id,
            },
        }

    async def _review_experts(
        self, task_description: str
    ) -> Dict[str, Any]:
        """Run the reviewer agent over current expert results.

        Returns the parsed JSON dict:
            {approved: bool, summary: str, issues: [{expert_id, severity, fix_hint}]}
        """
        from ..sub_agents import BaseSubAgent

        # Build expert results digest for reviewer
        lines = []
        for spec in self._expert_specs:
            r = self._expert_results.get(spec.id)
            status = r.status.value if r else "pending"
            output = (r.result if r else "") or (r.error if r else "") or "no output"
            lines.append(
                f"- id={spec.id} role={spec.role} sub_dir={spec.sub_dir or '<root>'} "
                f"status={status}\n  output: {output[:300]}"
            )
        expert_results_text = "\n".join(lines)

        reviewer = BaseSubAgent(
            parent=self._root_agent,
            agent_type="fleet-reviewer",
            allowed_tools=["read_file", "glob", "grep", "list_dir",
                          "Read", "Glob", "Grep", "ListDir"],
            system_template=REVIEWER_PROMPT,
        )

        prompt = (
            f"## Task\n{task_description}\n\n"
            f"## Workspace\n{self._workspace_dir}\n\n"
            f"## Expert Results\n{expert_results_text}"
        )
        await reviewer.create(prompt, {"workspace_dir": self._workspace_dir})

        output = await reviewer.run(timeout=120)
        if not output.success or not output.content:
            logger.warning(
                f"Reviewer failed: {output.error}; auto-approving"
            )
            return {"approved": True, "summary": "Reviewer unavailable", "issues": []}

        return self._parse_reviewer_json(output.content)

    def _parse_reviewer_json(self, content: str) -> Dict[str, Any]:
        """Parse reviewer's JSON output. Tolerates ```json fences / extra prose."""
        # Try ```json ... ``` fenced block first
        match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        # Try whole content
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        # Try substring { ... }
        start = content.find('{')
        end = content.rfind('}')
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(content[start:end + 1])
            except json.JSONDecodeError:
                pass
        logger.warning(
            f"Failed to parse reviewer JSON (len={len(content)}); auto-approving"
        )
        return {
            "approved": True,
            "summary": "Reviewer output unparseable; auto-approving",
            "issues": [],
        }

    async def rerun_expert(
        self,
        expert_id: str,
        fix_hint: Optional[str] = None,
    ) -> ExpertRunStatus:
        """Counterfactually re-run a single expert.

        Keeps all other experts' outputs unchanged. Optionally injects a
        ``fix_hint`` from the reviewer/user into the expert's task
        description so the new run addresses the specific issue.

        Returns the updated ExpertRunStatus for the re-run expert.
        """
        from .scheduler import TaskStatus as _TS

        spec = next((s for s in self._expert_specs if s.id == expert_id), None)
        if spec is None:
            raise ValueError(f"Unknown expert_id: {expert_id}")

        self._rerun_counts[expert_id] = self._rerun_counts.get(expert_id, 0) + 1

        # Augment task with fix_hint if provided
        effective_task = spec.task
        if fix_hint:
            effective_task = (
                f"{spec.task}\n\n"
                f"## Reviewer Feedback (please address)\n{fix_hint}"
            )

        # Build a fresh ScheduledTask — _execute_expert will pick up the
        # spec from self._expert_specs (same id), so sub_dir is preserved.
        task = ScheduledTask(
            id=spec.id, role=spec.role, description=effective_task,
            tools=spec.tools, file_scope=spec.file_scope,
            lock_keys=self._lock_keys_for_spec(spec),
            priority=spec.priority, timeout=spec.timeout,
        )

        # Clear the cached expert so ExpertFactory creates a fresh one
        # with the augmented task.
        if expert_id in self._factory._experts:
            del self._factory._experts[expert_id]

        # Single-task schedule
        self._scheduler._progress_callbacks = []
        results = await self._scheduler.schedule_all([task], self._execute_expert)
        r = results[0] if results else None
        if r is None:
            raise RuntimeError(f"Scheduler returned no result for {expert_id}")

        self._expert_results[expert_id] = r
        return self.get_expert_status(expert_id)
