"""
HakusAI Plan 模式
对标 Claude Code 的 EnterPlanMode / ExitPlanMode

流程:
  /plan         → 进入 plan 模式
  AI 分析任务, 输出计划
  ExitPlanMode  → 退出 plan 模式, 开始执行
"""
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)


class PlanStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"


@dataclass
class PlanStep:
    id: str
    title: str
    description: str
    tools: List[str] = field(default_factory=list)
    status: str = "pending"
    result: Optional[str] = None


@dataclass
class Plan:
    id: str
    title: str
    goal: str
    steps: List[PlanStep] = field(default_factory=list)
    status: PlanStatus = PlanStatus.DRAFT
    created_at: float = field(default_factory=time.time)
    approved_at: Optional[float] = None
    completed_at: Optional[float] = None

    def to_markdown(self) -> str:
        lines = [f"# 📋 {self.title}", "", f"**目标:** {self.goal}", "", "## 步骤"]
        for i, step in enumerate(self.steps, 1):
            icon = {
                "pending": "[ ]",
                "in_progress": "[~]",
                "completed": "[x]",
                "skipped": "[-]"
            }.get(step.status, "[ ]")
            lines.append(f"{i}. {icon} **{step.title}**")
            if step.description:
                lines.append(f"   {step.description}")
            if step.tools:
                tools_str = ", ".join(f"`{t}`" for t in step.tools)
                lines.append(f"   🔧 工具: {tools_str}")
        lines.append(f"\n**状态:** {self.status.value}")
        return chr(10).join(lines)


class PlanManager:
    """管理 plan 模式状态"""

    SYSTEM_PROMPT_SUFFIX = """

## 当前工作模式: PLAN MODE

你正在计划模式中。用户要求你**先制定计划**, 而不立即执行。

你的任务:
1. **深入分析用户请求**: 阅读相关文件, 理解代码结构
2. **列出清晰的步骤**: 每步具体、可执行、依赖关系明确
3. **标注工具使用**: 每步会用到哪些工具 (Read/Edit/Bash 等)
4. **识别风险**: 可能出错的地方, 备选方案
5. **等待用户批准**: 计划提交后, 用户会决定是否执行

输出格式:
```
## 计划: <简短标题>

**目标:** <一句话目标>

### 步骤

1. **[步骤名]** [工具: Read, Edit, ...]
   - <具体做什么>
   - <具体做什么>

2. **[步骤名]** [工具: Bash, ...]
   - <具体做什么>

### 风险评估

- <风险 1>: <应对>

### 预期结果

<完成后系统会变成什么样>
```

在用户批准计划之前, **不要**执行任何写操作 (Write/Edit/Bash 修改命令)。
只可以使用 Read/Glob/Grep 等只读工具来调研。
"""

    EXECUTION_PROMPT_SUFFIX = """

## 当前工作模式: PLAN EXECUTION

你正在执行一个已批准的计划。按计划逐步执行, 每步完成后更新 TodoWrite 状态。
如发现计划不完整, 立即告知用户而非擅自改动。
"""

    def __init__(self):
        self._mode: str = "default"
        self._current_plan: Optional[Plan] = None
        self._plan_history: List[Plan] = []

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def current_plan(self) -> Optional[Plan]:
        return self._current_plan

    def enter_plan_mode(self) -> str:
        """进入计划模式"""
        self._mode = "plan"
        return (
            "✓ 已进入 **Plan 模式**\n\n"
            "现在你可以调研代码、阅读文件, 然后输出一个详细的执行计划。\n"
            "用户在批准计划后才会开始执行。"
        )

    def exit_plan_mode(self, plan_id: Optional[str] = None) -> str:
        """退出计划模式, 提交计划等待批准"""
        if not self._current_plan:
            self._mode = "default"
            return "✓ 已退出 Plan 模式 (无计划)"

        self._current_plan.status = PlanStatus.PENDING_APPROVAL
        self._current_plan.approved_at = time.time()
        self._mode = "execution"

        return (
            f"✓ 计划已提交: **{self._current_plan.title}**\n\n"
            f"{self._current_plan.to_markdown()}\n\n"
            "用户可使用 `/approve` 批准, `/reject` 拒绝, 或回复修改意见。"
        )

    def approve(self) -> str:
        """用户批准计划"""
        if not self._current_plan:
            return "✗ 无计划可批准"
        self._current_plan.status = PlanStatus.APPROVED
        self._mode = "execution"
        return f"✓ 计划已批准, 开始执行: **{self._current_plan.title}**"

    def reject(self, reason: str = "") -> str:
        """用户拒绝计划"""
        if not self._current_plan:
            return "✗ 无计划可拒绝"
        self._current_plan.status = PlanStatus.REJECTED
        self._plan_history.append(self._current_plan)
        self._current_plan = None
        self._mode = "default"
        msg = "✓ 计划已拒绝"
        if reason:
            msg += f": {reason}"
        return msg

    def set_plan(self, plan: Plan) -> None:
        """设置当前计划 (由 AI 生成)"""
        if self._current_plan and self._current_plan.status != PlanStatus.DRAFT:
            self._plan_history.append(self._current_plan)
        self._current_plan = plan

    def update_step(self, step_id: str, status: str, result: Optional[str] = None) -> None:
        """更新步骤状态"""
        if not self._current_plan:
            return
        for step in self._current_plan.steps:
            if step.id == step_id:
                step.status = status
                if result is not None:
                    step.result = result
                break

        if all(s.status == "completed" for s in self._current_plan.steps):
            self._current_plan.status = PlanStatus.COMPLETED
            self._current_plan.completed_at = time.time()
            self._plan_history.append(self._current_plan)
            self._current_plan = None
            self._mode = "default"

    def is_plan_mode(self) -> bool:
        return self._mode == "plan"

    def is_executing(self) -> bool:
        return self._mode == "execution"

    def get_system_prompt_suffix(self) -> str:
        if self._mode == "plan":
            return self.SYSTEM_PROMPT_SUFFIX
        if self._mode == "execution":
            return self.EXECUTION_PROMPT_SUFFIX
        return ""

    def cancel(self) -> str:
        """取消计划模式"""
        if self._current_plan and self._current_plan.status != PlanStatus.COMPLETED:
            self._plan_history.append(self._current_plan)
        self._current_plan = None
        self._mode = "default"
        return "✓ 已退出 Plan 模式"

    def list_plans(self) -> str:
        if not self._plan_history and not self._current_plan:
            return "*暂无计划*"
        lines = ["# 📋 计划历史", ""]
        if self._current_plan:
            lines.append(f"**当前:** {self._current_plan.title} ({self._current_plan.status.value})")
        for p in self._plan_history[-5:]:
            lines.append(f"- {p.title} — {p.status.value}")
        return chr(10).join(lines)