"""Tool abstraction: the single base class for all tools in HakusAI.

Replaces the three parallel Tool classes that used to live in:
  - hakus/tool_system.py      (Tool)
  - hakus/builtin_tools.py    (Tool — re-imported)
  - core/tools/base.py        (ToolPlugin — now removed)

All tools must inherit from this class. There is exactly one base.

借鉴 trae-agent (bytedance/trae-agent) 的 ToolCall/ToolResult 数据类设计,
统一工具调用的输入/输出格式, 为后续 ToolExecutor 和并行调用做准备.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


# ── 工具调用数据类型 (trae-agent 风格) ──────────────────────────

ToolCallArguments = Dict[str, Any]


@dataclass
class ToolCall:
    """表示一次解析后的工具调用请求."""
    name: str
    call_id: str = ""
    arguments: ToolCallArguments = field(default_factory=dict)


@dataclass
class ToolExecResult:
    """工具执行的中间结果 (execute() 内部使用)."""
    output: Optional[str] = None
    error: Optional[str] = None
    error_code: int = 0


@dataclass
class ToolResult:
    """工具执行的最终结果 (返回给 Agent 主循环)."""
    call_id: str = ""
    name: str = ""
    success: bool = True
    result: Optional[str] = None
    error: Optional[str] = None


# ── 步骤状态机 (trae-agent AgentStepState 风格) ───────────────────

from enum import Enum


class StepState(Enum):
    """Agent 执行步骤的状态机.

    借鉴 trae-agent 的 AgentStepState, 增加 STREAMING (流式独有)
    和 ABORTED (用户中断) 状态.
    """
    THINKING = "thinking"
    STREAMING = "streaming"       # 流式输出中 (我们独有)
    TOOL_CALL = "tool_call"       # 已发出工具调用
    TOOL_RESULT = "tool_result"   # 工具已返回结果
    REFLECTING = "reflecting"     # 反思/重试决策中
    COMPLETED = "completed"       # 步骤正常完成
    ERROR = "error"               # 步骤出错
    ABORTED = "aborted"           # 用户中断


@dataclass
class AgentStep:
    """单次 Agent 迭代的完整记录.

    借鉴 trae-agent 的 AgentStep, 每步记录完整的状态转换和耗时,
    用于 Lakeview 显示、轨迹录制、调试分析.
    """
    step_number: int = 0
    state: StepState = StepState.THINKING

    # LLM 相关
    llm_request_tokens: int = 0
    llm_response_text: str = ""
    llm_finish_reason: str = ""

    # 工具调用相关
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_results: List[ToolResult] = field(default_factory=list)

    # 反思 / 错误
    reflection: Optional[str] = None
    error: Optional[str] = None

    # 耗时统计
    start_time: float = 0.0
    end_time: float = 0.0
    tokens_used: int = 0

    @property
    def duration_ms(self) -> float:
        if self.end_time > 0:
            return (self.end_time - self.start_time) * 1000
        return 0.0


class Tool(ABC):
    """Abstract base class for all tools.

    Subclasses must define class attributes:
      - name (str): the canonical tool name (must be unique in the registry)
      - description (str): short, focused description for the model
      - parameters_schema (dict): OpenAI function-calling JSON schema

    Subclasses must implement:
      - async execute(self, **kwargs) -> str

    Optional class attributes:
      - is_concurrency_safe (bool): True if the tool can run in parallel
        with other concurrency-safe tools. Default True. File reads and
        network GETs are safe. Shell commands and writes are not.
      - is_dangerous (bool): True if the tool can mutate state or access
        the network. The PermissionManager uses this to decide whether
        to require user confirmation. Default False.
    """

    name: str = ""
    description: str = ""
    parameters_schema: Dict[str, Any] = {}
    is_concurrency_safe: bool = True
    is_dangerous: bool = False

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """Run the tool and return a string result.

        The string is fed back into the model's context. Keep it
        human-readable. Errors should be returned as strings starting
        with "Error: ..." — never raised, because raising breaks the
        agent's tool loop.
        """
        raise NotImplementedError

    def to_openai_schema(self) -> Dict[str, Any]:
        """Serialize this tool into the OpenAI function-calling format.

        The schema is what the model sees in its context. Keep
        `description` short — long descriptions waste context window
        and the model is bad at following embedded "DO NOT use for X"
        instructions. Routing corrections happen at the *system* level
        (see hakus.tools.router), not in the description.
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }
