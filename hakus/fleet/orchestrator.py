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
You are the Commander of a Fleet of expert agents working in parallel.

## Your Mission
Analyze the user's task and decompose it into INDEPENDENT expert assignments.
Each expert will work in parallel on their own part.

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

## Decomposition Rules
1. Each expert MUST have an INDEPENDENT task (no cross-dependencies)
2. Aim for 5-30 experts based on task complexity
3. Break large files into logical units (e.g., "HTML structure" + "CSS styles" + "JS logic")
4. Assign priority 1 to foundational tasks, 2 to secondary, 3 to polish
5. Set reasonable timeout (60-600s) per expert based on task size
6. Each expert should produce a COMPLETE, SELF-CONTAINED deliverable
7. Include file_scope for every expert. File scopes that can write must be disjoint.
8. If two experts need to edit the same file, merge them into one expert.

## Critical
- Output ONLY the JSON block, no prose before/after
- Every expert must be able to work without waiting for others
- If tasks have dependencies, merge them into one expert"""


COMMANDER_SYNTHHESIZE_PROMPT = """\
You are the Commander synthesizing results from a Fleet of expert agents.

## Your Mission
Review all expert results and produce a final summary for the user.

## Expert Results
{expert_results}

## Output
Produce a concise summary that:
1. Lists what was accomplished (files created/modified)
2. Notes any failures or incomplete work
3. Provides next steps if any integration is needed
Keep it under 500 words."""


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


class FleetOrchestrator:
    """Fleet 编排器 — 指挥官 + 专业舰船."""

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

    def cancel(self) -> None:
        """取消执行."""
        self._cancelled = True

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
        """
        if self._cancelled:
            raise asyncio.CancelledError()

        spec = ExpertSpec(
            id=task.id,
            role=task.role,
            task=task.description,
            tools=task.tools,
            file_scope=task.file_scope,
            priority=task.priority,
            timeout=task.timeout,
        )

        # 创建专家
        expert = await self._factory.create_expert(spec, self._workspace_dir)

        # 执行
        logger.info(f"Expert {task.id} ({task.role}) starting...")
        output = await expert.run(timeout=task.timeout)

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
