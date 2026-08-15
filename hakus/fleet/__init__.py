"""Fleet 模式 — CTDE 多专家并行协作.

CTDE v2 architecture (借鉴 LangGraph + DeepSeek Harness):
  - Planner (Commander)：分析任务、拆解、为每个 expert 指定 sub_dir
  - Workers (Experts)：并行执行，每个绑定到 workspace/sub_dir
  - Reviewer：审查所有 expert 产出，可拒绝并要求重跑特定 expert
  - Counterfactual rerun：保留其他 expert 输出，单独重跑某个 expert

三种模式对比：
  Swift  — 单 Agent + 规则 Tester，省 token，日常任务
  Deep   — 多 Agent 流水线（Planner→Dev→Test 串行），质量高
  Fleet  — CTDE 蜂群（Planner + 并行 Workers + Reviewer），大规模复杂任务
"""
from .orchestrator import FleetOrchestrator, FleetResult, ExpertRunStatus
from .experience_store import ExperienceStore, TaskPattern, Strategy
from .scheduler import ParallelScheduler, TaskStatus
from .expert_factory import ExpertFactory, ExpertSpec

__all__ = [
    "FleetOrchestrator",
    "FleetResult",
    "ExpertRunStatus",
    "ExperienceStore",
    "TaskPattern",
    "Strategy",
    "ParallelScheduler",
    "TaskStatus",
    "ExpertFactory",
    "ExpertSpec",
]
