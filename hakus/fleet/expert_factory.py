"""动态专家工厂 — 根据任务需求创建专业子 Agent.

学习 Kimi Swarm 的"动态专家创建"：
  - 不再固定 Planner/Dev/Tester 角色
  - Commander 根据任务动态决定需要什么专家
  - 每个专家有自定义的 system prompt 和工具集

专家类型示例（由 Commander 动态决定，不是硬编码）:
  - 前端架构师: 擅长 HTML/CSS/JS 结构设计
  - 着色器专家: 擅长 GLSL/WebGL
  - 测试工程师: 擅长 pytest/jest
  - 数据库专家: 擅长 SQL/ORM
  - API 设计师: 擅长 REST/GraphQL
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)


def _safe_agent_type_part(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-").lower()
    return safe or "general"


@dataclass
class ExpertSpec:
    """专家规格 — Commander 输出的任务拆解单元.

    ``sub_dir`` 是 CTDE 架构的关键：每个 expert 绑定到
    ``workspace_dir/sub_dir``，这样多个 expert 可以同时在项目
    的不同子目录里工作而互不干扰（lock_keys 仍然按 file_scope
    串行写冲突，但 working_dir 隔离避免了"路径混淆"问题）。

    例如项目结构：
        workspace/
          frontend/   <- expert-1 sub_dir="frontend"
          backend/    <- expert-2 sub_dir="backend"
          docs/       <- expert-3 sub_dir="docs"

    如果 ``sub_dir`` 为空或 "."，expert 直接绑定到 workspace 根。
    """
    id: str
    role: str           # 专家角色，如"前端架构师"
    task: str           # 具体任务描述
    tools: List[str] = field(default_factory=list)
    file_scope: List[str] = field(default_factory=list)
    sub_dir: str = ""   # 相对于 workspace 的子目录，空="workspace 根"
    priority: int = 1   # 1=高, 2=中, 3=低
    timeout: int = 300

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExpertSpec":
        file_scope = d.get("file_scope") or d.get("files") or d.get("paths") or []
        if isinstance(file_scope, str):
            file_scope = [file_scope]
        elif not isinstance(file_scope, list):
            file_scope = []

        sub_dir = str(d.get("sub_dir") or d.get("subdir") or d.get("working_subdir") or "").strip()
        # 安全：sub_dir 不能是绝对路径或包含 ..
        if sub_dir and (os.path.isabs(sub_dir) or ".." in sub_dir.split("/")):
            logger.warning(
                f"Expert {d.get('id', '?')} sub_dir {sub_dir!r} is absolute or "
                f"contains '..'; ignoring"
            )
            sub_dir = ""

        return cls(
            id=d.get("id", f"expert_{hash(d.get('role', '')) % 10000}"),
            role=d.get("role", "general"),
            task=d.get("task", ""),
            tools=d.get("tools", ["read_file", "write_file", "edit_file", "glob", "grep"]),
            priority=d.get("priority", 1),
            timeout=d.get("timeout", 300),
            file_scope=[str(item) for item in file_scope if str(item).strip()],
            sub_dir=sub_dir,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for fleet run persistence / API response."""
        return {
            "id": self.id,
            "role": self.role,
            "task": self.task,
            "tools": list(self.tools),
            "file_scope": list(self.file_scope),
            "sub_dir": self.sub_dir,
            "priority": self.priority,
            "timeout": self.timeout,
        }


# 工具集预设 — Commander 可以选择或自定义
TOOL_PRESETS = {
    "dev": ["read_file", "write_file", "edit_file", "bash", "glob", "grep", "list_dir",
            "Read", "Write", "Edit", "Bash", "Glob", "Grep", "ListDir"],
    "test": ["read_file", "bash", "glob", "grep", "list_dir",
             "Read", "Bash", "Glob", "Grep", "ListDir"],
    "research": ["read_file", "glob", "grep", "web_search", "web_fetch", "list_dir",
                 "Read", "Glob", "Grep", "WebSearch", "WebFetch", "ListDir"],
    "review": ["read_file", "glob", "grep", "list_dir",
               "Read", "Glob", "Grep", "ListDir"],
    "write_only": ["read_file", "write_file", "edit_file", "glob", "grep",
                   "Read", "Write", "Edit", "Glob", "Grep"],
}


def resolve_tools(tool_names: List[str]) -> List[str]:
    """解析工具列表，支持预设名和具体工具名."""
    result: List[str] = []
    for name in tool_names:
        if name in TOOL_PRESETS:
            result.extend(TOOL_PRESETS[name])
        else:
            result.append(name)
    # 去重，保持顺序
    seen = set()
    deduped = []
    for t in result:
        if t not in seen:
            seen.add(t)
            deduped.append(t)
    return deduped


class ExpertFactory:
    """动态专家工厂 — 根据规格创建专业子 Agent."""

    def __init__(self, root_agent: Any):
        self._root_agent = root_agent
        # 缓存已创建的专家，避免重复创建
        self._experts: Dict[str, Any] = {}

    async def create_expert(self, spec: ExpertSpec, workspace_dir: str) -> Any:
        """根据规格创建专家 Agent.

        Args:
            spec: 专家规格（包含 sub_dir 字段）
            workspace_dir: 项目根目录

        Returns:
            配置好的 BaseSubAgent 实例（已调用 create）

        Notes:
            - 如果 ``spec.sub_dir`` 非空，expert 的 working_dir 是
              ``workspace_dir/spec.sub_dir``，目录不存在会自动创建
            - 否则 working_dir = workspace_dir
            - 这里不会因为 sub_dir 创建失败而崩溃 — makedirs 异常时
              回退到 workspace_dir 本身，让 expert 仍能跑（哪怕路径
              不太对），否则一个坏 sub_dir 会让整个 fleet 卡住
        """
        from ..sub_agents import BaseSubAgent

        # Resolve working_dir: workspace / sub_dir
        if spec.sub_dir:
            expert_working_dir = os.path.join(workspace_dir, spec.sub_dir)
            try:
                os.makedirs(expert_working_dir, exist_ok=True)
            except Exception as e:
                logger.warning(
                    f"Expert {spec.id}: failed to create sub_dir "
                    f"{expert_working_dir!r}: {e}; falling back to workspace root"
                )
                expert_working_dir = workspace_dir
        else:
            expert_working_dir = workspace_dir

        tools = resolve_tools(spec.tools)
        system_prompt = self._build_expert_prompt(spec)
        file_scope_text = ", ".join(spec.file_scope) if spec.file_scope else "workspace-wide"

        # 动态创建 BaseSubAgent 子类实例
        expert = BaseSubAgent(
            parent=self._root_agent,
            agent_type=f"fleet-{_safe_agent_type_part(spec.role)}",
            allowed_tools=tools,
            system_template=system_prompt,
        )

        # 设置工作目录并创建子 Agent
        context = {
            "workspace_dir": expert_working_dir,
            "extra_instructions": (
                f"You are expert '{spec.id}' with role '{spec.role}'. "
                f"Your working directory is: {expert_working_dir}. "
                f"Your file scope is: {file_scope_text}. "
                f"Work ONLY on your assigned task. Other experts are working "
                f"in parallel on different parts. Do NOT modify files outside "
                f"your task scope."
            ),
        }
        await expert.create(spec.task, context)
        self._experts[spec.id] = expert

        logger.info(
            f"ExpertFactory created expert: id={spec.id} role={spec.role} "
            f"sub_dir={spec.sub_dir or '<root>'} tools={len(tools)}"
        )
        return expert

    def _build_expert_prompt(self, spec: ExpertSpec) -> str:
        """为专家构建 system prompt."""
        file_scope_text = "\n".join(f"- {item}" for item in spec.file_scope)
        if not file_scope_text:
            file_scope_text = "- workspace-wide; keep changes tightly scoped to your task"

        working_dir_note = (
            f"Workspace root: {spec.sub_dir}"
            if spec.sub_dir
            else "Workspace root (full project)"
        )

        return f"""You are a {spec.role} in a Fleet of expert agents working in parallel.

## Your Specialization
Role: {spec.role}
Task: {spec.task}

## Working Directory
{working_dir_note}

## File Scope
{file_scope_text}

## Available Tools
{', '.join(resolve_tools(spec.tools))}

## Critical Rules
1. **Focus on YOUR task** — Do not do other experts' work
2. **Use file-operation tools** — read_file, write_file, edit_file for file tasks
3. **Read before write** — Always read existing files before modifying
4. **Self-contained work** — Your output should be complete and independent
5. **No conflicts** — Don't modify files that other experts might be working on
6. **Minimal output** — Briefly report what you created/modified, don't dump code
7. **Stay in your sub_dir** — If a working directory was assigned, keep all
   file changes inside it. Do not write to parent or sibling directories
   unless the task explicitly requires cross-directory integration.

## Workflow
1. Understand your specific task
2. Read relevant existing files (if any)
3. Implement your part
4. Verify your work (run tests if applicable)
5. Report completion status

## Parallel Awareness
You are working alongside other experts. If your task depends on another expert's
output that doesn't exist yet, create a stub/placeholder and note the dependency.
The Commander will integrate all results after everyone finishes."""

    def get_expert(self, expert_id: str) -> Optional[Any]:
        """获取已创建的专家."""
        return self._experts.get(expert_id)

    @property
    def expert_count(self) -> int:
        return len(self._experts)
