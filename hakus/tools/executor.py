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
import json
import logging
import os
import shutil
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .base import Tool, ToolCall, ToolResult
from .registry import ToolRegistry

# 使用 haku.tools.logger 路由到 tools.log (而非 hakus.tools.executor)
try:
    from utils.logger import get_logger as _get_haku_logger
    logger = _get_haku_logger("haku.tools.executor")
except Exception:
    logger = logging.getLogger(__name__)

# #region debug-point helper
_DEBUG_ENV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".dbg", "agent-stalls-after-tools.env",
)
_DEBUG_URL = "http://127.0.0.1:7777/event"
_DEBUG_SESSION = "agent-stalls-after-tools"


def _debug_log(hypothesis_id: str, location: str, msg: str, data: Optional[Dict[str, Any]] = None) -> None:
    try:
        url = _DEBUG_URL
        session = _DEBUG_SESSION
        try:
            with open(_DEBUG_ENV_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("DEBUG_SERVER_URL="):
                        url = line.split("=", 1)[1].strip()
                    elif line.startswith("DEBUG_SESSION_ID="):
                        session = line.split("=", 1)[1].strip()
        except Exception:
            pass
        payload = {
            "sessionId": session,
            "runId": "pre",
            "hypothesisId": hypothesis_id,
            "location": location,
            "msg": f"[DEBUG] {msg}",
            "data": data or {},
            "ts": time.time(),
        }
        body = json.dumps(payload).encode("utf-8")
        try:
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=1).read()
        except Exception:
            pass
        try:
            local_log = os.path.join(
                os.path.dirname(_DEBUG_ENV_PATH),
                f"trae-debug-log-{session}.ndjson.local",
            )
            with open(local_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception:
            pass
    except Exception:
        pass


# #endregion

# 工具结果最大字符数 (超过则截断)
MAX_TOOL_RESULT_LENGTH = 3000
# ACI 输出最大行数 (对齐 SWE-Agent: 简洁反馈原则)
MAX_TOOL_RESULT_LINES = 100

# 参数/元数据里可能包含文件路径的键名
_PATH_KEYS = ("file_path", "directory", "path", "dir", "source", "destination")


class ToolExecutor:
    """统一的工具执行器.

    借鉴 trae-agent 的 ToolExecutor，提供:
    - 名称归一化查找
    - 异常安全执行
    - 并行执行 (asyncio.gather)
    - 结果截断
    - 临时文件路径追踪与清理
    """

    def __init__(self, registry: ToolRegistry, max_result_length: int = MAX_TOOL_RESULT_LENGTH):
        self._registry = registry
        self._max_result_length = max_result_length
        self._temp_paths: Set[str] = set()

    def _is_temp_path(self, path: str) -> bool:
        """判断路径是否位于系统临时目录下。"""
        try:
            resolved = Path(path).resolve()
            temp_dirs = [
                Path(tempfile.gettempdir()).resolve(),
                Path(os.environ.get("TEMP", "") or tempfile.gettempdir()).resolve(),
                Path(os.environ.get("TMP", "") or tempfile.gettempdir()).resolve(),
            ]
            if os.name == "nt":
                temp_dirs.append(Path("C:/Temp").resolve())
                temp_dirs.append(Path("C:/Windows/Temp").resolve())
            return any(
                resolved == td or str(resolved).lower().startswith(str(td).lower() + os.sep)
                for td in temp_dirs
                if td.exists() or str(td).startswith(str(temp_dirs[0]))
            )
        except Exception:
            return False

    def _register_temp_path(self, result: ToolResult, arguments: Dict[str, Any]) -> None:
        """从工具结果元数据和参数中识别并登记临时文件/目录。"""
        paths: List[str] = []
        # 1) 优先读取 metadata 里声明的路径
        metadata = getattr(result, "metadata", None) or {}
        for key in _PATH_KEYS:
            val = metadata.get(key)
            if isinstance(val, str) and val:
                paths.append(val)
        # 2) 回退到参数中的路径（如 write_file 的 path 参数）
        for key in _PATH_KEYS:
            val = arguments.get(key)
            if isinstance(val, str) and val:
                paths.append(val)
        # 3) 去重并过滤为系统临时目录
        seen: Set[str] = set()
        for p in paths:
            if p in seen:
                continue
            seen.add(p)
            if self._is_temp_path(p):
                self._temp_paths.add(p)

    def cleanup_temp_paths(self) -> List[str]:
        """清理本回合登记的临时路径，返回成功删除的列表。"""
        # #region debug-point C:cleanup-start
        _debug_log("C", "executor.py:cleanup_temp_paths", "start", {"count": len(self._temp_paths), "paths": list(self._temp_paths)})
        # #endregion
        removed: List[str] = []
        remaining: Set[str] = set()
        for p in self._temp_paths:
            try:
                path = Path(p)
                if path.exists():
                    if path.is_file() or path.is_symlink():
                        path.unlink()
                    elif path.is_dir():
                        shutil.rmtree(path)
                removed.append(p)
            except Exception as e:
                # 清理失败不阻塞主流程，记录后保留以便调试
                remaining.add(p)
                logger.warning(f"Failed to clean up temp path {p}: {e}")
        self._temp_paths = remaining
        # #region debug-point C:cleanup-done
        _debug_log("C", "executor.py:cleanup_temp_paths", "done", {"removed": removed, "remaining": list(remaining)})
        # #endregion
        return removed

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
            logger.error(f"[tool.unknown] call_id={tool_call.call_id} name={tool_call.name}")
            return ToolResult(
                call_id=tool_call.call_id,
                name=tool_call.name,
                success=False,
                error=f"Unknown tool: {tool_call.name}",
            )

        _exec_started = time.time()
        _arg_keys = list(tool_call.arguments.keys())
        logger.info(
            f"[tool.start] call_id={tool_call.call_id} name={tool_call.name} "
            f"args_keys={_arg_keys}"
        )
        # #region debug-point C:tool-execute-start
        _debug_log("C", "executor.py:execute", "tool execute start", {"tool": tool_call.name, "call_id": tool_call.call_id})
        # #endregion
        try:
            result = await tool.execute(**tool_call.arguments)
            if not isinstance(result, ToolResult):
                result = ToolResult(
                    call_id=tool_call.call_id,
                    name=tool_call.name,
                    success=True,
                    result=str(result),
                )
            # 截断超长结果 (ACI: 简洁反馈原则 — 先按行数截断，再按字符截断)
            result_str = result.result or ""
            _was_truncated = False
            # 行数限制 (SWE-Agent ACI: ≤100 行)
            lines = result_str.split("\n")
            if len(lines) > MAX_TOOL_RESULT_LINES:
                _total_lines = len(lines)
                lines = lines[:MAX_TOOL_RESULT_LINES]
                result_str = "\n".join(lines)
                result_str += f"\n...[{_total_lines - MAX_TOOL_RESULT_LINES} more lines truncated (ACI)]"
                _was_truncated = True
            # 字符限制 (兜底)
            if len(result_str) > self._max_result_length:
                result_str = result_str[:self._max_result_length] + "\n...[truncated]"
                _was_truncated = True
            result.result = result_str
            self._register_temp_path(result, tool_call.arguments)
            _elapsed_ms = int((time.time() - _exec_started) * 1000)
            logger.info(
                f"[tool.done] call_id={tool_call.call_id} name={tool_call.name} "
                f"success={result.success} elapsed_ms={_elapsed_ms} "
                f"result_len={len(result.result or '')} truncated={_was_truncated}"
            )
            # #region debug-point C:tool-execute-done
            _debug_log("C", "executor.py:execute", "tool execute done", {"tool": tool_call.name, "call_id": tool_call.call_id, "success": result.success})
            # #endregion
            return result
        except Exception as e:
            _elapsed_ms = int((time.time() - _exec_started) * 1000)
            # #region debug-point C:tool-execute-error
            _debug_log("C", "executor.py:execute", "tool execute error", {"tool": tool_call.name, "call_id": tool_call.call_id, "error": f"{type(e).__name__}: {e}"})
            # #endregion
            logger.error(
                f"[tool.error] call_id={tool_call.call_id} name={tool_call.name} "
                f"error={type(e).__name__} elapsed_ms={_elapsed_ms}: {e}"
            )
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
