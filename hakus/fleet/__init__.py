"""Fleet 模式 — 自组织多专家并行协作.

学习 Kimi Agent Swarm 的自组织蜂群架构，结合 HakusAI 的工程实践：
  - Commander（指挥官）：主 Agent，动态拆解任务、分配专家
  - Expert Ship（专业舰船）：动态创建的子 Agent，各有专业领域
  - ParallelScheduler：大规模并行调度，Semaphore 限速 + 失败重试
  - ExperienceStore：经验库，替代 PARL 的"学习"能力

三种模式对比：
  Swift  — 单 Agent + 规则 Tester，省 token，日常任务
  Deep   — 多 Agent 流水线（Planner→Dev→Test 串行），质量高
  Fleet  — 自组织蜂群（动态专家 + 全局并行），大规模复杂任务
"""
from .orchestrator import FleetOrchestrator, FleetResult
from .experience_store import ExperienceStore, TaskPattern, Strategy
from .scheduler import ParallelScheduler, TaskStatus
from .expert_factory import ExpertFactory, ExpertSpec

__all__ = [
    "FleetOrchestrator",
    "FleetResult",
    "ExperienceStore",
    "TaskPattern",
    "Strategy",
    "ParallelScheduler",
    "TaskStatus",
    "ExpertFactory",
    "ExpertSpec",
]
