"""ToolExecutor — 统一的工具执行器 (借鉴 trae-agent ToolExecutor 设计).

核心职责:
  1. 名称归一化: 将模型输出的工具名映射到 canonical name
  2. 异常包装: 所有工具异常捕获后返回 ToolResult(success=False)
  3. 并行执行: 对 concurrency-safe 的工具调用使用 asyncio.gather
  4. 结果截断: 超长工具结果自动截断，防止上下文溢出

与 agent.py 的 _execute_tool_call() 关系:
  ToolExecutor 只负责「找到工具 → 执行 → 返回结果」的核心逻辑。
  路由重定向、权限检查、hook 链、harness guard 等高层逻辑
  仍留在 agent.py 中（它们需要访问 AgentCore 的状态）。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from .base import Tool, ToolCall, ToolResult
from .registry import ToolRegistry

logger = logging.getLogger(__name__)

# 工具结果最大字符数 (超过则截断)
MAX_TOOL_RESULT_LENGTH = 3000


class ToolExecutor:
    """统一的工具执行器.

    借鉴 trae-agent 的 ToolExecutor，提供:
    - 名称归一化查找
    - 异常安全执行
    - 并行执行 (asyncio.gather)
    - 结果截断
    """

    def __init__(self, registry: ToolRegistry, max_result_length: int = MAX_TOOL_RESULT_LENGTH):
        self._registry = registry
        self._max_result_length = max_result_length

    def get(self, name: str) -> Optional[Tool]:
        """按名称查找工具 (支持别名)."""
        return self._registry.get(name)

    def canonicalize(self, name: str) -> str:
        """将工具名归一化为 canonical name."""
        tool = self._registry.get(name)
        if tool:
            return tool.name
        return name

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """执行单个工具调用.

        Args:
            tool_call: 解析后的工具调用请求

        Returns:
            ToolResult: 执行结果 (异常不会抛出，而是返回 error)
        """
        tool = self._registry.get(tool_call.name)
        if not tool:
            return ToolResult(
                call_id=tool_call.call_id,
                name=tool_call.name,
                success=False,
                error=f"Unknown tool: {tool_call.name}",
            )

        try:
            result = await tool.execute(**tool_call.arguments)
            result_str = str(result)
            # 截断超长结果
            if len(result_str) > self._max_result_length:
                result_str = result_str[:self._max_result_length] + "\n...[truncated]"
            return ToolResult(
                call_id=tool_call.call_id,
                name=tool_call.name,
                success=True,
                result=result_str,
            )
        except Exception as e:
            logger.error(f"Tool '{tool_call.name}' execution failed: {e}")
            return ToolResult(
                call_id=tool_call.call_id,
                name=tool_call.name,
                success=False,
                error=f"Error: {type(e).__name__}: {e}",
            )

    async def execute_raw(self, name: str, arguments: Dict[str, Any]) -> ToolResult:
        """直接按名称和参数执行工具 (兼容旧调用方式).

        Args:
            name: 工具名 (可以是别名)
            arguments: 工具参数

        Returns:
            ToolResult: 执行结果
        """
        canonical = self.canonicalize(name)
        tool_call = ToolCall(name=canonical, arguments=arguments)
        return await self.execute(tool_call)

    async def parallel_execute(self, calls: List[ToolCall]) -> List[ToolResult]:
        """并行执行多个工具调用.

        仅对 concurrency-safe 的工具并行执行，非安全的串行执行。

        Args:
            calls: 工具调用列表

        Returns:
            与 calls 顺序对应的 ToolResult 列表
        """
        if not calls:
            return []

        # 分组: safe 的并行，unsafe 的串行
        results: List[Optional[ToolResult]] = [None] * len(calls)
        safe_indices: List[int] = []
        unsafe_indices: List[int] = []

        for i, call in enumerate(calls):
            tool = self._registry.get(call.name)
            if tool and tool.is_concurrency_safe:
                safe_indices.append(i)
            else:
                unsafe_indices.append(i)

        # 并行执行 safe 工具
        if safe_indices:
            safe_tasks = [self.execute(calls[i]) for i in safe_indices]
            safe_results = await asyncio.gather(*safe_tasks, return_exceptions=True)
            for idx, result in zip(safe_indices, safe_results):
                if isinstance(result, Exception):
                    results[idx] = ToolResult(
                        name=calls[idx].name,
                        success=False,
                        error=f"Error: {type(result).__name__}: {result}",
                    )
                else:
                    results[idx] = result

        # 串行执行 unsafe 工具
        for i in unsafe_indices:
            results[i] = await self.execute(calls[i])

        return results  # type: ignore

    def get_schemas(self, names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """获取工具的 OpenAI schema 列表."""
        if names is None:
            names = self._registry.list_tools()
        return self._registry.get_schemas(names)
