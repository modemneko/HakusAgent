"""
TurnDebugLogger — 按轮数写详细调试日志到目录 (增强版)

用法:
  1. 环境变量: HAKUS_DEBUG=1
  2. config.yaml: debug: true
  3. /debug 命令切换

日志目录: ~/.hakus/debug/<session_id>/
每轮两个文件:
  - turn_001.log  人类可读文本格式
  - turn_001.jsonl  机器可解析 JSONL 格式

增强特性:
  - 双格式输出: JSONL + 文本同时写入
  - 结构化 JSONL schema, 支持多种事件类型
  - TrajectoryAnalyzer 轨迹分析 (循环检测、工具准确率、迭代效率)
  - Session 级元数据 (_session.json)
  - 自动清理过期会话 (默认 7 天)
  - 完全向后兼容现有 API
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------
_instance: Optional["TurnDebugLogger"] = None
_lock = threading.Lock()


def get_debug_logger() -> Optional["TurnDebugLogger"]:
    """获取全局 TurnDebugLogger 实例 (可能为 None)."""
    return _instance


def init_debug_logger(
    session_id: Optional[str] = None,
    cleanup_days: int = 7,
) -> "TurnDebugLogger":
    """初始化全局 TurnDebugLogger 实例."""
    global _instance
    with _lock:
        if _instance is None:
            _instance = TurnDebugLogger(
                session_id=session_id,
                cleanup_days=cleanup_days,
            )
        return _instance


def shutdown_debug_logger() -> None:
    """关闭全局 TurnDebugLogger."""
    global _instance
    with _lock:
        if _instance is not None:
            _instance.close()
            _instance = None


def is_debug_enabled() -> bool:
    """检查 debug 模式是否启用."""
    if os.environ.get("HAKUS_DEBUG", "").strip() in ("1", "true", "yes"):
        return True
    try:
        from utils.config import BASE_CONFIG
        return BASE_CONFIG.get("DEBUG", False)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JSONL 事件类型常量
# ---------------------------------------------------------------------------
EVT_ITERATION_START = "iteration_start"
EVT_API_REQUEST = "api_request"
EVT_API_RESPONSE = "api_response"
EVT_TOOL_CALL = "tool_call"
EVT_TOOL_RESULT = "tool_result"
EVT_COMPRESSION = "compression"
EVT_PERMISSION = "permission"
EVT_EVENT = "event"
EVT_ERROR = "error"
EVT_CONTEXT_STATE = "context_state"
EVT_TOKEN_USAGE = "token_usage"
EVT_TURN_END = "turn_end"
EVT_STEP_RECORD = "step_record"


# ---------------------------------------------------------------------------
# TurnDebugLogger
# ---------------------------------------------------------------------------

class TurnDebugLogger:
    """按轮数写详细调试日志 (双格式: JSONL + 文本)."""

    def __init__(
        self,
        session_id: Optional[str] = None,
        cleanup_days: int = 7,
    ) -> None:
        if session_id is None:
            session_id = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self._session_id = session_id
        self._base_dir = Path.home() / ".hakus" / "debug" / session_id
        self._base_dir.mkdir(parents=True, exist_ok=True)

        self._turn_number: int = 0
        self._current_log_file = None
        self._current_jsonl_file = None
        self._current_log_path: Optional[Path] = None
        self._current_jsonl_path: Optional[Path] = None
        self._file_lock = threading.Lock()
        self._enabled: bool = True

        # 会话级统计
        self._session_start_time: float = time.monotonic()
        self._session_start_iso: str = datetime.now().isoformat()
        self._total_iterations: int = 0
        self._total_tool_calls: int = 0
        self._total_tool_success: int = 0
        self._total_tool_fail: int = 0
        self._cumulative_input_tokens: int = 0
        self._cumulative_output_tokens: int = 0
        self._turn_start_time: float = 0.0
        self._turn_iterations: int = 0
        self._turn_tool_calls: int = 0

        # 自动清理
        self._cleanup_days = cleanup_days
        if cleanup_days > 0:
            self._cleanup_old_sessions(cleanup_days)

        # 写 session 级元数据
        self._write_session_meta()

    # ------------------------------------------------------------------
    # 公共 API (向后兼容)
    # ------------------------------------------------------------------

    def begin_turn(self, user_input: str) -> None:
        """开始新的一轮, 创建 turn_XXX.log 和 turn_XXX.jsonl 文件."""
        if not self._enabled:
            return
        self._turn_number += 1
        self._turn_start_time = time.monotonic()
        self._turn_iterations = 0
        self._turn_tool_calls = 0

        # 文本日志文件
        log_filename = f"turn_{self._turn_number:03d}.log"
        self._current_log_path = self._base_dir / log_filename
        try:
            self._current_log_file = open(
                self._current_log_path, "w", encoding="utf-8", buffering=1,
            )
        except Exception as e:
            self._current_log_file = None
            print(f"[TurnDebug] 无法创建 {self._current_log_path}: {e}", file=sys.stderr)

        # JSONL 文件
        jsonl_filename = f"turn_{self._turn_number:03d}.jsonl"
        self._current_jsonl_path = self._base_dir / jsonl_filename
        try:
            self._current_jsonl_file = open(
                self._current_jsonl_path, "w", encoding="utf-8", buffering=1,
            )
        except Exception as e:
            self._current_jsonl_file = None
            print(f"[TurnDebug] 无法创建 {self._current_jsonl_path}: {e}", file=sys.stderr)

        self._write_header(user_input)

    def end_turn(self, summary: str = "") -> None:
        """结束当前轮, 关闭文件."""
        if not self._enabled:
            return
        if self._current_log_file or self._current_jsonl_file:
            turn_duration_ms = int((time.monotonic() - self._turn_start_time) * 1000)
            final_pct = 0  # 由调用者通过 log_context_state 设置

            # 写文本日志尾部
            if self._current_log_file:
                if summary:
                    self._write_text(f"\n{'='*60}\n")
                    self._write_text(f"TURN SUMMARY: {summary}\n")
                self._write_text(f"{'='*60}\n")
                self._write_text(f"Turn ended at: {datetime.now().isoformat()}\n")
                self._write_text(f"Duration: {turn_duration_ms}ms  "
                                 f"Iterations: {self._turn_iterations}  "
                                 f"Tool calls: {self._turn_tool_calls}\n")

            # 写 JSONL turn_end 事件
            self._write_jsonl(EVT_TURN_END, {
                "summary": summary,
                "total_iterations": self._turn_iterations,
                "total_tool_calls": self._turn_tool_calls,
                "total_duration_ms": turn_duration_ms,
                "final_context_pct": final_pct,
            })

            # 关闭文件
            for f in (self._current_log_file, self._current_jsonl_file):
                if f:
                    try:
                        f.close()
                    except Exception:
                        pass
            self._current_log_file = None
            self._current_jsonl_file = None

            # 更新 session 元数据
            self._update_session_meta()

    def close(self) -> None:
        """关闭 logger, 写入会话摘要."""
        if self._current_log_file:
            try:
                self._current_log_file.close()
            except Exception:
                pass
            self._current_log_file = None
        if self._current_jsonl_file:
            try:
                self._current_jsonl_file.close()
            except Exception:
                pass
            self._current_jsonl_file = None

        # 写入最终 session 摘要
        self._write_session_summary()

    @property
    def turn_number(self) -> int:
        return self._turn_number

    @property
    def session_dir(self) -> str:
        return str(self._base_dir)

    @property
    def current_log_path(self) -> Optional[str]:
        return str(self._current_log_path) if self._current_log_path else None

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    # ------------------------------------------------------------------
    # 日志写入方法 — 各模块调用 (向后兼容)
    # ------------------------------------------------------------------

    def log_messages_to_api(
        self,
        messages: List[Dict[str, Any]],
        estimated_tokens: int = 0,
        budget: int = 0,
    ) -> None:
        """记录发送给 API 的完整 messages."""
        if not self._current_log_file and not self._current_jsonl_file:
            return

        # 文本格式
        if self._current_log_file:
            self._write_text(f"\n{'─'*60}\n")
            self._write_text("MESSAGES TO API\n")
            self._write_text(f"Estimated tokens: {estimated_tokens} / budget {budget}")
            if budget > 0:
                pct = min(100, int(estimated_tokens * 100 / budget))
                self._write_text(f" ({pct}%)")
            self._write_text("\n")
            self._write_text(f"Message count: {len(messages)}\n\n")

            for i, msg in enumerate(messages):
                role = msg.get("role", "?")
                content = msg.get("content", "")
                tool_calls = msg.get("tool_calls")
                tool_call_id = msg.get("tool_call_id", "")

                self._write_text(f"  [{i}] role={role}")
                if tool_call_id:
                    self._write_text(f" tool_call_id={tool_call_id}")
                self._write_text("\n")

                if tool_calls:
                    for tc in tool_calls:
                        tc_id = tc.get("id", "?")
                        func = tc.get("function", {})
                        name = func.get("name", "?")
                        args = func.get("arguments", "{}")
                        self._write_text(f"      tool_call: id={tc_id} name={name}\n")
                        if len(args) > 500:
                            args = args[:250] + "...[truncated]..." + args[-250:]
                        self._write_text(f"      arguments: {args}\n")

                if content:
                    display = str(content)
                    if len(display) > 2000:
                        display = display[:1000] + f"\n...[truncated {len(content)} chars]...\n" + display[-500:]
                    for line in display.split("\n"):
                        self._write_text(f"    {line}\n")
                elif not tool_calls:
                    self._write_text(f"    (empty content)\n")
                self._write_text("\n")

        # JSONL 格式
        messages_summary = []
        for msg in messages:
            role = msg.get("role", "?")
            content = msg.get("content", "") or ""
            tool_calls = msg.get("tool_calls") or []
            content_preview = content[:200].replace("\n", "\\n") if content else ""
            messages_summary.append({
                "role": role,
                "content_preview": content_preview,
                "tool_calls_count": len(tool_calls),
            })
        self._write_jsonl(EVT_API_REQUEST, {
            "message_count": len(messages),
            "estimated_tokens": estimated_tokens,
            "budget": budget,
            "messages_summary": messages_summary,
        })

    def log_api_response(
        self,
        text: str = "",
        tool_calls: Optional[List[Dict]] = None,
        finish_reason: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """记录 API 响应."""
        if not self._current_log_file and not self._current_jsonl_file:
            return

        # 更新累计 token
        self._cumulative_input_tokens += input_tokens
        self._cumulative_output_tokens += output_tokens

        # 文本格式
        if self._current_log_file:
            self._write_text(f"\n{'─'*60}\n")
            self._write_text("API RESPONSE\n")
            self._write_text(f"Finish reason: {finish_reason}\n")
            self._write_text(f"Token usage: input={input_tokens} output={output_tokens}\n")
            if text:
                display = text
                if len(display) > 3000:
                    display = display[:1500] + f"\n...[truncated {len(text)} chars]...\n" + display[-500:]
                self._write_text(f"Text ({len(text)} chars):\n")
                for line in display.split("\n"):
                    self._write_text(f"  {line}\n")
            if tool_calls:
                self._write_text(f"Tool calls ({len(tool_calls)}):\n")
                for tc in tool_calls:
                    func = tc.get("function", {})
                    name = func.get("name", "?")
                    args = func.get("arguments", "{}")
                    self._write_text(f"  - id={tc.get('id', '?')} name={name}\n")
                    if len(args) > 500:
                        args = args[:250] + "...[truncated]..." + args[-250:]
                    self._write_text(f"    args: {args}\n")

        # JSONL 格式
        tc_summaries = []
        if tool_calls:
            for tc in tool_calls:
                func = tc.get("function", {})
                args_str = func.get("arguments", "{}")
                tc_summaries.append({
                    "id": tc.get("id", "?"),
                    "name": func.get("name", "?"),
                    "args_preview": args_str[:300] if len(args_str) > 300 else args_str,
                })
        self._write_jsonl(EVT_API_RESPONSE, {
            "finish_reason": finish_reason,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "text_preview": (text[:500] if text else ""),
            "tool_calls": tc_summaries,
        })

    def log_tool_execution(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result: str = "",
        success: bool = True,
        duration: float = 0.0,
    ) -> None:
        """记录工具执行."""
        if not self._current_log_file and not self._current_jsonl_file:
            return

        self._total_tool_calls += 1
        self._turn_tool_calls += 1
        if success:
            self._total_tool_success += 1
        else:
            self._total_tool_fail += 1

        # 文本格式
        if self._current_log_file:
            self._write_text(f"\n{'─'*60}\n")
            self._write_text("TOOL EXECUTION\n")
            self._write_text(f"Tool: {tool_name}\n")
            self._write_text(f"Success: {success}  Duration: {duration:.2f}s\n")
            args_str = json.dumps(arguments, ensure_ascii=False, default=str)
            if len(args_str) > 1000:
                args_str = args_str[:500] + "...[truncated]..." + args_str[-500:]
            self._write_text(f"Arguments: {args_str}\n")
            if result:
                display = result
                if len(display) > 2000:
                    display = display[:1000] + f"\n...[truncated {len(result)} chars]...\n" + display[-500:]
                self._write_text(f"Result:\n")
                for line in display.split("\n"):
                    self._write_text(f"  {line}\n")

        # JSONL 格式 — 拆分为 tool_call 和 tool_result 两个事件
        args_summary = json.dumps(arguments, ensure_ascii=False, default=str)
        if len(args_summary) > 500:
            args_summary = args_summary[:250] + "...[truncated]..." + args_summary[-250:]

        self._write_jsonl(EVT_TOOL_CALL, {
            "tool_name": tool_name,
            "arguments_summary": args_summary,
            "started_at": datetime.now().isoformat(),
        })

        result_preview = result[:500] if result else ""
        self._write_jsonl(EVT_TOOL_RESULT, {
            "tool_name": tool_name,
            "success": success,
            "duration_ms": int(duration * 1000),
            "result_preview": result_preview,
        })

    def log_compression(
        self,
        level: str,
        before_tokens: int,
        after_tokens: int,
        before_msg_count: int,
        after_msg_count: int,
        budget: int,
    ) -> None:
        """记录上下文压缩事件."""
        if not self._current_log_file and not self._current_jsonl_file:
            return

        # 文本格式
        if self._current_log_file:
            self._write_text(f"\n{'─'*60}\n")
            self._write_text("CONTEXT COMPRESSION\n")
            self._write_text(f"Level: {level}\n")
            self._write_text(f"Tokens: {before_tokens} → {after_tokens} (budget: {budget})\n")
            self._write_text(f"Messages: {before_msg_count} → {after_msg_count}\n")
            if budget > 0:
                pct_before = min(100, int(before_tokens * 100 / budget))
                pct_after = min(100, int(after_tokens * 100 / budget))
                self._write_text(f"Usage: {pct_before}% → {pct_after}%\n")

        # JSONL 格式
        self._write_jsonl(EVT_COMPRESSION, {
            "level": level,
            "before_tokens": before_tokens,
            "after_tokens": after_tokens,
            "before_msgs": before_msg_count,
            "after_msgs": after_msg_count,
            "budget": budget,
        })

    def log_context_state(
        self,
        label: str,
        total_tokens: int,
        budget: int,
        msg_count: int,
        compression_level: str,
        compression_count: int,
        circuit_breaker: bool,
    ) -> None:
        """记录上下文状态快照."""
        if not self._current_log_file and not self._current_jsonl_file:
            return

        pct = min(100, int(total_tokens * 100 / max(1, budget))) if budget > 0 else 0

        # 文本格式
        if self._current_log_file:
            self._write_text(f"\n  [CONTEXT] {label}: "
                             f"tokens={total_tokens}/{budget} ({pct}%) "
                             f"msgs={msg_count} "
                             f"compress={compression_level}({compression_count}) "
                             f"circuit_breaker={circuit_breaker}\n")

        # JSONL 格式
        self._write_jsonl(EVT_CONTEXT_STATE, {
            "label": label,
            "total_tokens": total_tokens,
            "budget": budget,
            "pct": pct,
            "msg_count": msg_count,
            "compression_level": compression_level,
            "circuit_breaker": circuit_breaker,
        })

    def log_permission_check(
        self,
        tool_name: str,
        allowed: bool,
        mode: str = "",
        reason: str = "",
    ) -> None:
        """记录权限检查."""
        if not self._current_log_file and not self._current_jsonl_file:
            return

        # 文本格式
        if self._current_log_file:
            self._write_text(f"  [PERM] tool={tool_name} allowed={allowed} mode={mode}"
                             f"{' reason=' + reason if reason else ''}\n")

        # JSONL 格式
        self._write_jsonl(EVT_PERMISSION, {
            "tool_name": tool_name,
            "allowed": allowed,
            "mode": mode,
            "reason": reason,
        })

    def log_event(self, event_type: str, detail: str = "") -> None:
        """记录事件流."""
        if not self._current_log_file and not self._current_jsonl_file:
            return

        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        # 文本格式
        if self._current_log_file:
            self._write_text(f"  [{ts}] EVENT: {event_type}")
            if detail:
                self._write_text(f" — {detail}")
            self._write_text("\n")

        # JSONL 格式
        self._write_jsonl(EVT_EVENT, {
            "event_type": event_type,
            "detail": detail,
        })

    def log_structured_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """记录结构化事件 (支持 dict detail, 用于 AgentStep 等数据)."""
        if not self._current_log_file and not self._current_jsonl_file:
            return

        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        # 文本格式: 简洁一行
        if self._current_log_file:
            detail_str = json.dumps(data, ensure_ascii=False, default=str)
            self._write_text(f"  [{ts}] {event_type}: {detail_str[:200]}\n")

        # JSONL 格式: 完整数据
        self._write_jsonl(event_type, data)

    def log_iteration_start(
        self,
        iteration: int,
        max_iterations: int,
        msg_count: int,
        estimated_tokens: int,
        budget: int,
    ) -> None:
        """记录流式循环的每次迭代开始."""
        if not self._current_log_file and not self._current_jsonl_file:
            return

        self._total_iterations += 1
        self._turn_iterations += 1
        pct = min(100, int(estimated_tokens * 100 / max(1, budget))) if budget > 0 else 0

        # 文本格式
        if self._current_log_file:
            self._write_text(f"\n{'═'*60}\n")
            self._write_text(f"ITERATION {iteration + 1}/{max_iterations}  "
                             f"msgs={msg_count} tokens={estimated_tokens}/{budget} ({pct}%)\n")
            self._write_text(f"{'═'*60}\n")

        # JSONL 格式
        self._write_jsonl(EVT_ITERATION_START, {
            "iteration": iteration,
            "max_iterations": max_iterations,
            "msg_count": msg_count,
            "estimated_tokens": estimated_tokens,
            "budget": budget,
            "pct": pct,
        })

    def log_token_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        cumulative_input: int = 0,
        cumulative_output: int = 0,
    ) -> None:
        """记录 token 用量."""
        if not self._current_log_file and not self._current_jsonl_file:
            return

        # 文本格式
        if self._current_log_file:
            self._write_text(f"  [TOKENS] this_call: in={input_tokens} out={output_tokens}  "
                             f"cumulative: in={cumulative_input} out={cumulative_output}  "
                             f"total={cumulative_input + cumulative_output}\n")

        # JSONL 格式
        self._write_jsonl(EVT_TOKEN_USAGE, {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cumulative_input": cumulative_input,
            "cumulative_output": cumulative_output,
        })

    def log_error(self, context: str, error: Exception) -> None:
        """记录错误."""
        if not self._current_log_file and not self._current_jsonl_file:
            return

        tb_str = traceback.format_exc()

        # 文本格式
        if self._current_log_file:
            self._write_text(f"\n  [ERROR] {context}: {type(error).__name__}: {error}\n")
            for line in tb_str.split("\n"):
                self._write_text(f"    {line}\n")

        # JSONL 格式
        self._write_jsonl(EVT_ERROR, {
            "context": context,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "traceback": tb_str,
        })

    def log_raw(self, text: str) -> None:
        """写入原始文本 (仅文本日志)."""
        if not self._current_log_file:
            return
        self._write_text(text)

    def log_messages_snapshot(self, messages: List[Dict[str, Any]], label: str = "") -> None:
        """记录消息列表快照 (用于压缩前后对比)."""
        if not self._current_log_file:
            return
        self._write_text(f"\n  [SNAPSHOT] {label}: {len(messages)} messages\n")
        for i, msg in enumerate(messages):
            role = msg.get("role", "?")
            content = msg.get("content", "") or ""
            tc_count = len(msg.get("tool_calls", []))
            tc_id = msg.get("tool_call_id", "")
            content_preview = content[:80].replace("\n", "\\n") if content else "(empty)"
            extra = ""
            if tc_count:
                extra = f" tool_calls={tc_count}"
            if tc_id:
                extra += f" tc_id={tc_id}"
            self._write_text(f"    [{i}] {role}: {content_preview}{extra}\n")

    # ------------------------------------------------------------------
    # 内部方法 — 文件写入
    # ------------------------------------------------------------------

    def _write_text(self, text: str) -> None:
        """写入文本日志文件."""
        if not self._current_log_file:
            return
        with self._file_lock:
            try:
                self._current_log_file.write(text)
                self._current_log_file.flush()
            except Exception:
                pass

    def _write_jsonl(self, event_type: str, data: Dict[str, Any]) -> None:
        """写入一条 JSONL 事件."""
        if not self._current_jsonl_file:
            return
        record = {
            "ts": datetime.now().isoformat(),
            "turn": self._turn_number,
            "type": event_type,
            "data": data,
        }
        with self._file_lock:
            try:
                self._current_jsonl_file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                self._current_jsonl_file.flush()
            except Exception:
                pass

    def _write_header(self, user_input: str) -> None:
        """写轮次头部 (文本格式)."""
        self._write_text(f"{'='*60}\n")
        self._write_text(f"HakusAI Debug Log — Turn {self._turn_number}\n")
        self._write_text(f"Time: {datetime.now().isoformat()}\n")
        self._write_text(f"{'='*60}\n\n")
        display = user_input
        if len(display) > 500:
            display = display[:250] + f"...[truncated {len(user_input)} chars]..." + display[-250:]
        self._write_text(f"USER INPUT ({len(user_input)} chars):\n")
        for line in display.split("\n"):
            self._write_text(f"  {line}\n")
        self._write_text("\n")

    # ------------------------------------------------------------------
    # 内部方法 — Session 元数据
    # ------------------------------------------------------------------

    def _write_session_meta(self) -> None:
        """写 session 级 _session.json 元数据."""
        meta_path = self._base_dir / "_session.json"
        try:
            model = "unknown"
            try:
                from utils.config import BASE_CONFIG
                model = BASE_CONFIG.get("MODEL", "unknown")
            except Exception:
                pass

            meta = {
                "session_id": self._session_id,
                "created": self._session_start_iso,
                "python": sys.version,
                "cwd": os.getcwd(),
                "model": model,
                "status": "active",
                "turns": [],
                "total_iterations": 0,
                "total_tool_calls": 0,
                "total_tool_success": 0,
                "total_tool_fail": 0,
                "cumulative_input_tokens": 0,
                "cumulative_output_tokens": 0,
            }
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        # 同时写 _session.txt 保持向后兼容
        txt_path = self._base_dir / "_session.txt"
        try:
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(f"HakusAI Debug Session\n")
                f.write(f"Session ID: {self._session_id}\n")
                f.write(f"Created: {self._session_start_iso}\n")
                f.write(f"Python: {sys.version}\n")
                f.write(f"CWD: {os.getcwd()}\n")
                try:
                    from utils.config import BASE_CONFIG
                    model = BASE_CONFIG.get("MODEL", "unknown")
                    f.write(f"Model: {model}\n")
                except Exception:
                    pass
        except Exception:
            pass

    def _update_session_meta(self) -> None:
        """更新 session 元数据 (每轮结束时调用)."""
        meta_path = self._base_dir / "_session.json"
        try:
            meta = {}
            if meta_path.exists():
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)

            meta["turns"].append({
                "turn": self._turn_number,
                "iterations": self._turn_iterations,
                "tool_calls": self._turn_tool_calls,
                "ended_at": datetime.now().isoformat(),
            })
            meta["total_iterations"] = self._total_iterations
            meta["total_tool_calls"] = self._total_tool_calls
            meta["total_tool_success"] = self._total_tool_success
            meta["total_tool_fail"] = self._total_tool_fail
            meta["cumulative_input_tokens"] = self._cumulative_input_tokens
            meta["cumulative_output_tokens"] = self._cumulative_output_tokens

            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _write_session_summary(self) -> None:
        """写入最终会话摘要到 _session.json."""
        meta_path = self._base_dir / "_session.json"
        try:
            meta = {}
            if meta_path.exists():
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)

            total_duration_ms = int((time.monotonic() - self._session_start_time) * 1000)
            meta["status"] = "closed"
            meta["ended_at"] = datetime.now().isoformat()
            meta["total_duration_ms"] = total_duration_ms
            meta["total_turns"] = self._turn_number
            meta["total_iterations"] = self._total_iterations
            meta["total_tool_calls"] = self._total_tool_calls
            meta["total_tool_success"] = self._total_tool_success
            meta["total_tool_fail"] = self._total_tool_fail
            meta["cumulative_input_tokens"] = self._cumulative_input_tokens
            meta["cumulative_output_tokens"] = self._cumulative_output_tokens
            meta["total_tokens"] = self._cumulative_input_tokens + self._cumulative_output_tokens

            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        # 同时运行轨迹分析并写入报告
        try:
            analyzer = TrajectoryAnalyzer(str(self._base_dir))
            report = analyzer.analyze()
            report_path = self._base_dir / "_trajectory_report.json"
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 内部方法 — 自动清理
    # ------------------------------------------------------------------

    def _cleanup_old_sessions(self, max_age_days: int) -> None:
        """删除超过 max_age_days 天的调试会话目录."""
        debug_base = Path.home() / ".hakus" / "debug"
        if not debug_base.exists():
            return
        cutoff = datetime.now() - timedelta(days=max_age_days)
        try:
            for entry in debug_base.iterdir():
                if not entry.is_dir():
                    continue
                try:
                    # 尝试从 _session.json 读取创建时间
                    meta_path = entry / "_session.json"
                    if meta_path.exists():
                        with open(meta_path, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                        created_str = meta.get("created", "")
                        if created_str:
                            created = datetime.fromisoformat(created_str)
                            if created < cutoff:
                                import shutil
                                shutil.rmtree(entry, ignore_errors=True)
                                continue
                    # 回退: 从目录名解析日期
                    dir_name = entry.name
                    try:
                        dir_date = datetime.strptime(dir_name[:10], "%Y-%m-%d")
                        if dir_date < cutoff:
                            import shutil
                            shutil.rmtree(entry, ignore_errors=True)
                    except ValueError:
                        pass
                except Exception:
                    pass
        except Exception:
            pass


# ---------------------------------------------------------------------------
# TrajectoryAnalyzer — 轨迹分析器
# ---------------------------------------------------------------------------

class TrajectoryAnalyzer:
    """分析一个调试会话的 JSONL 日志, 生成轨迹报告.

    用法:
        analyzer = TrajectoryAnalyzer("/path/to/session_dir")
        report = analyzer.analyze()
    """

    def __init__(self, session_dir: str, loop_window: int = 5) -> None:
        """
        Args:
            session_dir: 会话目录路径
            loop_window: 循环检测窗口大小 (在最近 N 次工具调用中检测重复)
        """
        self._session_dir = Path(session_dir)
        self._loop_window = loop_window
        self._events: List[Dict[str, Any]] = []

    def analyze(self) -> Dict[str, Any]:
        """执行完整轨迹分析, 返回报告字典."""
        self._load_events()
        if not self._events:
            return {"error": "no events found", "session_dir": str(self._session_dir)}

        report: Dict[str, Any] = {
            "session_dir": str(self._session_dir),
            "total_events": len(self._events),
            "turns": self._analyze_turns(),
            "tool_accuracy": self._analyze_tool_accuracy(),
            "loop_detection": self._detect_loops(),
            "iteration_efficiency": self._analyze_iteration_efficiency(),
            "context_growth": self._analyze_context_growth(),
            "token_summary": self._analyze_tokens(),
        }
        return report

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _load_events(self) -> None:
        """从会话目录加载所有 JSONL 事件."""
        self._events = []
        if not self._session_dir.exists():
            return
        # 按文件名排序确保顺序正确
        jsonl_files = sorted(self._session_dir.glob("turn_*.jsonl"))
        for jsonl_path in jsonl_files:
            try:
                with open(jsonl_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                            event["_source_file"] = jsonl_path.name
                            self._events.append(event)
                        except json.JSONDecodeError:
                            pass
            except Exception:
                pass

    def _analyze_turns(self) -> List[Dict[str, Any]]:
        """按轮次分析事件."""
        turns: Dict[int, Dict[str, Any]] = {}
        for evt in self._events:
            turn_num = evt.get("turn", 0)
            if turn_num not in turns:
                turns[turn_num] = {
                    "turn": turn_num,
                    "iterations": 0,
                    "tool_calls": 0,
                    "tool_success": 0,
                    "tool_fail": 0,
                    "errors": 0,
                    "compressions": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "start_time": None,
                    "end_time": None,
                }
            t = turns[turn_num]
            evt_type = evt.get("type", "")
            ts = evt.get("ts", "")

            if t["start_time"] is None:
                t["start_time"] = ts
            t["end_time"] = ts

            if evt_type == EVT_ITERATION_START:
                t["iterations"] += 1
            elif evt_type == EVT_TOOL_RESULT:
                t["tool_calls"] += 1
                data = evt.get("data", {})
                if data.get("success"):
                    t["tool_success"] += 1
                else:
                    t["tool_fail"] += 1
            elif evt_type == EVT_ERROR:
                t["errors"] += 1
            elif evt_type == EVT_COMPRESSION:
                t["compressions"] += 1
            elif evt_type == EVT_API_RESPONSE:
                data = evt.get("data", {})
                t["input_tokens"] += data.get("input_tokens", 0)
                t["output_tokens"] += data.get("output_tokens", 0)

        return sorted(turns.values(), key=lambda x: x["turn"])

    def _analyze_tool_accuracy(self) -> Dict[str, Any]:
        """分析工具调用准确率."""
        tool_stats: Dict[str, Dict[str, int]] = {}
        for evt in self._events:
            if evt.get("type") != EVT_TOOL_RESULT:
                continue
            data = evt.get("data", {})
            name = data.get("tool_name", "unknown")
            if name not in tool_stats:
                tool_stats[name] = {"success": 0, "fail": 0, "total": 0}
            tool_stats[name]["total"] += 1
            if data.get("success"):
                tool_stats[name]["success"] += 1
            else:
                tool_stats[name]["fail"] += 1

        total_calls = sum(s["total"] for s in tool_stats.values())
        total_success = sum(s["success"] for s in tool_stats.values())
        total_fail = sum(s["fail"] for s in tool_stats.values())

        # 计算每个工具的成功率
        per_tool: Dict[str, Dict[str, Any]] = {}
        for name, stats in tool_stats.items():
            rate = (stats["success"] / stats["total"] * 100) if stats["total"] > 0 else 0
            per_tool[name] = {
                "total": stats["total"],
                "success": stats["success"],
                "fail": stats["fail"],
                "success_rate_pct": round(rate, 1),
            }

        overall_rate = (total_success / total_calls * 100) if total_calls > 0 else 0
        return {
            "total_calls": total_calls,
            "total_success": total_success,
            "total_fail": total_fail,
            "overall_success_rate_pct": round(overall_rate, 1),
            "per_tool": per_tool,
        }

    def _detect_loops(self) -> Dict[str, Any]:
        """检测循环: 在 N 次迭代内重复相同的工具调用+参数."""
        tool_call_events = [
            evt for evt in self._events
            if evt.get("type") == EVT_TOOL_CALL
        ]

        loops: List[Dict[str, Any]] = []
        window = self._loop_window

        for i in range(len(tool_call_events)):
            current = tool_call_events[i]
            current_data = current.get("data", {})
            current_sig = f"{current_data.get('tool_name', '')}:{current_data.get('arguments_summary', '')}"

            # 在窗口内查找重复
            for j in range(max(0, i - window), i):
                prev = tool_call_events[j]
                prev_data = prev.get("data", {})
                prev_sig = f"{prev_data.get('tool_name', '')}:{prev_data.get('arguments_summary', '')}"

                if current_sig == prev_sig and current_sig.strip(":"):
                    loops.append({
                        "tool_name": current_data.get("tool_name", ""),
                        "arguments_summary": current_data.get("arguments_summary", ""),
                        "first_at": prev.get("ts", ""),
                        "repeat_at": current.get("ts", ""),
                        "turn": current.get("turn", 0),
                        "gap_events": i - j,
                    })
                    break  # 只记录最近的一次重复

        return {
            "loop_window": window,
            "loops_detected": len(loops),
            "loops": loops,
            "has_loops": len(loops) > 0,
        }

    def _analyze_iteration_efficiency(self) -> Dict[str, Any]:
        """分析迭代效率: 使用了多少迭代 vs 最少需要多少."""
        iteration_starts = [
            evt for evt in self._events
            if evt.get("type") == EVT_ITERATION_START
        ]
        tool_results = [
            evt for evt in self._events
            if evt.get("type") == EVT_TOOL_RESULT
        ]
        turn_ends = [
            evt for evt in self._events
            if evt.get("type") == EVT_TURN_END
        ]

        total_iterations = len(iteration_starts)
        total_tool_calls = len(tool_results)
        total_turns = len(turn_ends)

        # 估算最少迭代: 每次迭代至少一个工具调用, 最后一轮迭代产生文本响应
        # 粗略估计: 最少迭代 = 成功的工具调用数 (假设每次迭代只做一个工具)
        successful_tools = sum(
            1 for evt in tool_results
            if evt.get("data", {}).get("success", False)
        )
        min_iterations = max(1, successful_tools) if successful_tools > 0 else total_iterations

        efficiency = (min_iterations / total_iterations * 100) if total_iterations > 0 else 100

        return {
            "total_iterations": total_iterations,
            "total_tool_calls": total_tool_calls,
            "total_turns": total_turns,
            "estimated_min_iterations": min_iterations,
            "efficiency_pct": round(efficiency, 1),
            "avg_iterations_per_turn": round(total_iterations / total_turns, 1) if total_turns > 0 else 0,
            "avg_tools_per_turn": round(total_tool_calls / total_turns, 1) if total_turns > 0 else 0,
        }

    def _analyze_context_growth(self) -> Dict[str, Any]:
        """分析上下文增长速率: 每次迭代的 token 增长."""
        context_states = [
            evt for evt in self._events
            if evt.get("type") == EVT_CONTEXT_STATE
        ]
        iteration_starts = [
            evt for evt in self._events
            if evt.get("type") == EVT_ITERATION_START
        ]

        if not context_states:
            return {
                "data_points": 0,
                "avg_tokens_per_iteration": 0,
                "max_context_pct": 0,
                "growth_rate": "unknown",
            }

        tokens_list = [evt.get("data", {}).get("total_tokens", 0) for evt in context_states]
        pct_list = [evt.get("data", {}).get("pct", 0) for evt in context_states]
        total_iterations = len(iteration_starts)

        if total_iterations > 1 and len(tokens_list) >= 2:
            total_growth = tokens_list[-1] - tokens_list[0]
            avg_per_iter = total_growth / max(1, total_iterations - 1)
        else:
            total_growth = 0
            avg_per_iter = 0

        return {
            "data_points": len(context_states),
            "first_tokens": tokens_list[0] if tokens_list else 0,
            "last_tokens": tokens_list[-1] if tokens_list else 0,
            "total_growth": total_growth,
            "avg_tokens_per_iteration": round(avg_per_iter, 1),
            "max_context_pct": max(pct_list) if pct_list else 0,
            "iterations": total_iterations,
        }

    def _analyze_tokens(self) -> Dict[str, Any]:
        """分析 token 用量汇总."""
        api_responses = [
            evt for evt in self._events
            if evt.get("type") == EVT_API_RESPONSE
        ]

        total_input = sum(evt.get("data", {}).get("input_tokens", 0) for evt in api_responses)
        total_output = sum(evt.get("data", {}).get("output_tokens", 0) for evt in api_responses)
        call_count = len(api_responses)

        return {
            "api_calls": call_count,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_tokens": total_input + total_output,
            "avg_input_per_call": round(total_input / call_count, 1) if call_count > 0 else 0,
            "avg_output_per_call": round(total_output / call_count, 1) if call_count > 0 else 0,
        }
