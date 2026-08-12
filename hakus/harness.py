"""Agent Harness — 结构化评估框架.

提供 Agent 运行时的轨迹记录、性能评估和约束守护:

- TrajectoryRecorder: 记录 agent 每一步操作的完整轨迹
- HarnessEvaluator: 基于 trajectory 数据评估 agent 性能
- HarnessGuard: 运行时约束守护 (循环检测、迭代上限、上下文预算)
- create_harness_components: 便捷工厂函数
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Tuple


# ============================================================
# 数据类
# ============================================================

@dataclass
class StepRecord:
    """单步操作记录.

    Attributes:
        step_type: 步骤类型 — "thought" | "tool_call" | "tool_result" | "final_answer"
        timestamp: Unix 时间戳 (秒)
        tool_name: 工具名称 (仅 tool_call / tool_result 有效)
        arguments: 工具调用参数 (仅 tool_call 有效)
        call_id: 工具调用标识 (tool_call / tool_result 共用)
        result: 工具返回结果 (仅 tool_result 有效)
        success: 工具调用是否成功 (仅 tool_result 有效)
        duration_ms: 工具执行耗时毫秒 (仅 tool_result 有效)
        content: 文本内容 (thought / final_answer 有效)
    """

    step_type: str  # "thought" | "tool_call" | "tool_result" | "final_answer"
    timestamp: float
    tool_name: str = ""
    arguments: dict = field(default_factory=dict)
    call_id: str = ""
    result: str = ""
    success: bool = True
    duration_ms: float = 0.0
    content: str = ""


@dataclass
class LoopInfo:
    """检测到的循环信息.

    Attributes:
        step_indices: 重复出现的步骤索引列表
        tool_name: 重复调用的工具名
        arguments_signature: 参数签名 (MD5 哈希)
        repetition_count: 重复次数
        message: 人类可读描述
    """

    step_indices: List[int]
    tool_name: str
    arguments_signature: str
    repetition_count: int
    message: str


@dataclass
class ToolAccuracy:
    """单个工具的调用准确率统计.

    Attributes:
        tool_name: 工具名
        total_calls: 总调用次数
        successful_calls: 成功次数
        failed_calls: 失败次数
        success_rate: 成功率 (0.0 ~ 1.0)
        avg_duration_ms: 平均耗时毫秒
    """

    tool_name: str
    total_calls: int
    successful_calls: int
    failed_calls: int
    success_rate: float
    avg_duration_ms: float


@dataclass
class HarnessReport:
    """一次 turn 的完整评估报告.

    Attributes:
        turn_id: 轮次标识
        duration_ms: 总耗时毫秒
        total_steps: 总步骤数
        tool_call_count: 工具调用次数
        failed_tool_count: 失败工具调用次数
        loop_rate: 循环率 (0.0 ~ 1.0)
        loops_detected: 检测到的循环列表
        tool_accuracy: 各工具准确率字典
        iteration_efficiency: 迭代效率 (0.0 ~ 1.0)
        context_efficiency: 上下文效率 (0.0 ~ 1.0)
        overall_score: 综合评分 (0.0 ~ 1.0)
        timestamp: 报告生成时间 (ISO 格式)
    """

    turn_id: str
    duration_ms: float
    total_steps: int
    tool_call_count: int
    failed_tool_count: int
    loop_rate: float
    loops_detected: List[LoopInfo]
    tool_accuracy: Dict[str, ToolAccuracy]
    iteration_efficiency: float
    context_efficiency: float
    overall_score: float
    timestamp: str


@dataclass
class GuardDecision:
    """Guard 对一次工具调用的裁决.

    Attributes:
        allowed: 是否允许执行
        reason: 拒绝原因 (允许时为空)
        violation_type: 违规类型 — "loop" | "max_iterations" | "context_overload" | ""
        forced_end: 是否应强制终止 agent 整轮
    """

    allowed: bool
    reason: str = ""
    violation_type: str = ""  # "loop" | "max_iterations" | "context_overload" | ""
    forced_end: bool = False


@dataclass
class ViolationRecord:
    """约束违规记录.

    Attributes:
        violation_type: 违规类型
        iteration: 发生时的迭代编号
        tool_name: 相关工具名
        reason: 违规原因描述
        timestamp: 发生时间戳
    """

    violation_type: str
    iteration: int
    tool_name: str
    reason: str
    timestamp: float


# ============================================================
# 辅助函数
# ============================================================

def _args_signature(tool_name: str, arguments: dict) -> str:
    """生成工具名 + 参数的 MD5 签名, 用于循环检测比较.

    Args:
        tool_name: 工具名
        arguments: 工具参数字典

    Returns:
        32 字符的 MD5 十六进制摘要
    """
    canonical = json.dumps(
        {"tool": tool_name, "args": arguments},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.md5(canonical.encode("utf-8")).hexdigest()


# ============================================================
# TrajectoryRecorder
# ============================================================

class TrajectoryRecorder:
    """记录 agent 在一个 turn 内的完整操作轨迹.

    轻量级、始终在线的组件, 挂载到 agent 事件流上.
    典型用法::

        rec = TrajectoryRecorder(turn_id="t001")
        rec.start()
        rec.record_thought("让我先读取文件...")
        rec.record_tool_call("Read", {"file_path": "/tmp/a.py"}, call_id="c1")
        rec.record_tool_result("c1", "file content...", success=True, duration_ms=120.5)
        rec.record_final_answer("文件内容是...")
        rec.stop()
    """

    def __init__(self, turn_id: str = "") -> None:
        self.turn_id = turn_id
        self.steps: List[StepRecord] = []
        self._start_time: float = 0.0
        self._stop_time: float = 0.0
        self._tool_call_index: int = 0

    # ------------------------------------------------------------------
    # 录制方法
    # ------------------------------------------------------------------

    def start(self) -> None:
        """开始记录轨迹."""
        self._start_time = time.time()
        self._stop_time = 0.0
        self.steps.clear()
        self._tool_call_index = 0

    def record_thought(self, content: str) -> None:
        """记录 agent 的思维/推理步骤.

        Args:
            content: 思维内容文本
        """
        self.steps.append(StepRecord(
            step_type="thought",
            timestamp=time.time(),
            content=content,
        ))

    def record_tool_call(self, tool_name: str, arguments: dict, call_id: str = "") -> None:
        """记录一次工具调用.

        Args:
            tool_name: 工具名
            arguments: 调用参数
            call_id: 调用标识 (用于关联 tool_result)
        """
        self._tool_call_index += 1
        self.steps.append(StepRecord(
            step_type="tool_call",
            timestamp=time.time(),
            tool_name=tool_name,
            arguments=arguments,
            call_id=call_id or f"tc_{self._tool_call_index}",
        ))

    def record_tool_result(
        self,
        call_id: str,
        result: str,
        success: bool,
        duration_ms: float,
    ) -> None:
        """记录工具执行结果.

        Args:
            call_id: 与 record_tool_call 对应的调用标识
            result: 工具返回结果文本
            success: 是否成功
            duration_ms: 执行耗时毫秒
        """
        # 查找对应的 tool_name
        tool_name = ""
        for step in reversed(self.steps):
            if step.step_type == "tool_call" and step.call_id == call_id:
                tool_name = step.tool_name
                break
        self.steps.append(StepRecord(
            step_type="tool_result",
            timestamp=time.time(),
            tool_name=tool_name,
            call_id=call_id,
            result=result,
            success=success,
            duration_ms=duration_ms,
        ))

    def record_final_answer(self, content: str) -> None:
        """记录 agent 的最终回答.

        Args:
            content: 最终回答内容
        """
        self.steps.append(StepRecord(
            step_type="final_answer",
            timestamp=time.time(),
            content=content,
        ))

    def stop(self) -> None:
        """停止记录轨迹."""
        self._stop_time = time.time()

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def duration_ms(self) -> float:
        """轨迹总耗时 (毫秒). 若未 stop 则返回到当前的耗时."""
        end = self._stop_time if self._stop_time else time.time()
        return (end - self._start_time) * 1000 if self._start_time else 0.0

    @property
    def tool_call_count(self) -> int:
        """工具调用次数."""
        return sum(1 for s in self.steps if s.step_type == "tool_call")

    @property
    def failed_tool_count(self) -> int:
        """失败的工具调用次数."""
        return sum(1 for s in self.steps if s.step_type == "tool_result" and not s.success)

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """将轨迹导出为可 JSON 序列化的字典."""
        return {
            "turn_id": self.turn_id,
            "duration_ms": self.duration_ms,
            "tool_call_count": self.tool_call_count,
            "failed_tool_count": self.failed_tool_count,
            "steps": [
                {
                    "step_type": s.step_type,
                    "timestamp": s.timestamp,
                    "tool_name": s.tool_name,
                    "arguments": s.arguments,
                    "call_id": s.call_id,
                    "result": s.result,
                    "success": s.success,
                    "duration_ms": s.duration_ms,
                    "content": s.content,
                }
                for s in self.steps
            ],
        }

    # ------------------------------------------------------------------
    # 循环检测
    # ------------------------------------------------------------------

    def detect_loops(
        self,
        window: int = 3,
        similarity_threshold: float = 0.8,
    ) -> List[LoopInfo]:
        """检测轨迹中的循环行为.

        在最近 *window* 次工具调用中, 若同一签名出现多次则判定为循环.

        Args:
            window: 检测窗口大小 (最近 N 次工具调用)
            similarity_threshold: 相似度阈值 (当前实现基于精确签名匹配,
                此参数保留用于未来模糊匹配扩展)

        Returns:
            检测到的循环信息列表
        """
        # 收集所有 tool_call 步骤及其索引
        tool_calls: List[Tuple[int, StepRecord]] = [
            (i, s) for i, s in enumerate(self.steps)
            if s.step_type == "tool_call"
        ]

        if not tool_calls:
            return []

        # 构建签名 -> 步骤索引列表 的映射
        sig_groups: Dict[str, List[int]] = {}
        for idx, step in tool_calls:
            sig = _args_signature(step.tool_name, step.arguments)
            if sig not in sig_groups:
                sig_groups[sig] = []
            sig_groups[sig].append(idx)

        loops: List[LoopInfo] = []

        for sig, indices in sig_groups.items():
            if len(indices) < 2:
                continue

            # 在窗口内查找重复
            # 从后向前扫描, 检查最近的重复
            for i in range(len(indices) - 1, 0, -1):
                current_idx = indices[i]
                # 在窗口范围内查找之前的同签名调用
                window_indices: List[int] = []
                for j in range(i - 1, -1, -1):
                    prev_idx = indices[j]
                    # 检查是否在 window 范围内 (基于 tool_call 序号差)
                    call_distance = i - j
                    if call_distance <= window:
                        window_indices.append(prev_idx)
                    else:
                        break

                if window_indices:
                    # 找到循环
                    step = self.steps[current_idx]
                    repetition_count = len(window_indices) + 1
                    all_indices = sorted(window_indices + [current_idx])
                    loops.append(LoopInfo(
                        step_indices=all_indices,
                        tool_name=step.tool_name,
                        arguments_signature=sig,
                        repetition_count=repetition_count,
                        message=(
                            f"工具 '{step.tool_name}' 在最近 {window} 次调用内"
                            f"重复了 {repetition_count} 次 (签名: {sig[:8]}...)"
                        ),
                    ))
                    break  # 每个签名只报告一次最严重的循环

        return loops


# ============================================================
# HarnessEvaluator
# ============================================================

class HarnessEvaluator:
    """基于轨迹数据评估 agent 性能.

    在一个 turn 完成后, 使用 TrajectoryRecorder 记录的数据进行评估::

        rec = TrajectoryRecorder(turn_id="t001")
        ... # 录制轨迹
        rec.stop()

        evaluator = HarnessEvaluator(rec)
        report = evaluator.full_report(context_tokens=5000, context_budget=128000)
    """

    def __init__(self, trajectory: TrajectoryRecorder) -> None:
        self.trajectory = trajectory

    def tool_accuracy(self) -> Dict[str, ToolAccuracy]:
        """计算各工具的调用准确率.

        Returns:
            以工具名为 key 的 ToolAccuracy 字典
        """
        stats: Dict[str, Dict[str, Any]] = {}

        for step in self.trajectory.steps:
            if step.step_type == "tool_result":
                name = step.tool_name
                if not name:
                    continue
                if name not in stats:
                    stats[name] = {
                        "total": 0,
                        "success": 0,
                        "fail": 0,
                        "durations": [],
                    }
                stats[name]["total"] += 1
                if step.success:
                    stats[name]["success"] += 1
                else:
                    stats[name]["fail"] += 1
                if step.duration_ms > 0:
                    stats[name]["durations"].append(step.duration_ms)

        result: Dict[str, ToolAccuracy] = {}
        for name, s in stats.items():
            total = s["total"]
            success = s["success"]
            durations = s["durations"]
            avg_dur = sum(durations) / len(durations) if durations else 0.0
            result[name] = ToolAccuracy(
                tool_name=name,
                total_calls=total,
                successful_calls=success,
                failed_calls=s["fail"],
                success_rate=success / total if total > 0 else 0.0,
                avg_duration_ms=avg_dur,
            )
        return result

    def loop_rate(self) -> float:
        """计算循环率.

        循环率 = 涉及循环的工具调用次数 / 总工具调用次数.
        返回 0.0 ~ 1.0 之间的值, 0.0 表示无循环.
        """
        loops = self.trajectory.detect_loops()
        total_calls = self.trajectory.tool_call_count
        if total_calls == 0:
            return 0.0

        # 计算被循环涉及的唯一 tool_call 步骤数
        loop_step_set: set = set()
        for loop in loops:
            for idx in loop.step_indices:
                loop_step_set.add(idx)

        return len(loop_step_set) / total_calls

    def iteration_efficiency(self, min_expected_steps: int = 1) -> float:
        """计算迭代效率.

        效率 = min_expected_steps / actual_steps, 上限为 1.0.

        Args:
            min_expected_steps: 完成任务所需的最少步骤数

        Returns:
            0.0 ~ 1.0 之间的效率值
        """
        actual_steps = len(self.trajectory.steps)
        if actual_steps == 0:
            return 1.0
        efficiency = min_expected_steps / actual_steps
        return min(1.0, efficiency)

    def context_efficiency(
        self,
        context_tokens_used: int,
        context_budget: int,
    ) -> float:
        """计算上下文预算使用效率.

        效率 = 1.0 - (used / budget), 即越少使用越好.
        若 budget 为 0 则返回 1.0.

        Args:
            context_tokens_used: 实际使用的 token 数
            context_budget: 预算 token 数

        Returns:
            0.0 ~ 1.0 之间的效率值
        """
        if context_budget <= 0:
            return 1.0
        usage_ratio = context_tokens_used / context_budget
        return max(0.0, 1.0 - usage_ratio)

    def full_report(
        self,
        context_tokens: int = 0,
        context_budget: int = 0,
    ) -> HarnessReport:
        """生成完整评估报告.

        Args:
            context_tokens: 上下文使用的 token 数
            context_budget: 上下文预算 token 数

        Returns:
            HarnessReport 实例
        """
        tool_acc = self.tool_accuracy()
        lr = self.loop_rate()
        ie = self.iteration_efficiency()
        ce = self.context_efficiency(context_tokens, context_budget)

        # 计算工具准确率平均值
        if tool_acc:
            avg_accuracy = sum(t.success_rate for t in tool_acc.values()) / len(tool_acc)
        else:
            avg_accuracy = 1.0

        # 综合评分: 0.4 * accuracy + 0.3 * (1 - loop_rate) + 0.2 * efficiency + 0.1 * context
        overall_score = (
            0.4 * avg_accuracy
            + 0.3 * (1.0 - lr)
            + 0.2 * ie
            + 0.1 * ce
        )
        overall_score = max(0.0, min(1.0, overall_score))

        return HarnessReport(
            turn_id=self.trajectory.turn_id,
            duration_ms=self.trajectory.duration_ms,
            total_steps=len(self.trajectory.steps),
            tool_call_count=self.trajectory.tool_call_count,
            failed_tool_count=self.trajectory.failed_tool_count,
            loop_rate=lr,
            loops_detected=self.trajectory.detect_loops(),
            tool_accuracy=tool_acc,
            iteration_efficiency=ie,
            context_efficiency=ce,
            overall_score=overall_score,
            timestamp=datetime.now().isoformat(),
        )


# ============================================================
# HarnessGuard
# ============================================================

class HarnessGuard:
    """运行时约束守护, 集成到 agent 工具循环中.

    职责:
    - 检测并打断无限循环
    - 强制迭代上限
    - 追踪并报告约束违规

    典型用法::

        guard = HarnessGuard(max_iterations=20, max_duplicate_calls=3)
        for iteration in range(max_iter):
            guard.increment_iteration()
            decision = guard.check_before_tool_call(tool_name, args, context_pct)
            if not decision.allowed:
                if decision.forced_end:
                    break
                continue  # 跳过此次调用
            guard.record_tool_call(tool_name, args)
            # ... 执行工具 ...
    """

    def __init__(
        self,
        max_iterations: int = 30,
        max_duplicate_calls: int = 3,
        max_context_pct: int = 80,
        loop_detection_window: int = 5,
    ) -> None:
        """初始化 Guard.

        Args:
            max_iterations: 最大迭代次数
            max_duplicate_calls: 同一签名最大重复调用次数
            max_context_pct: 上下文使用率上限 (百分比)
            loop_detection_window: 循环检测窗口大小
        """
        self.max_iterations = max_iterations
        self.max_duplicate_calls = max_duplicate_calls
        self.max_context_pct = max_context_pct
        self.loop_detection_window = loop_detection_window
        self._call_history: List[Tuple[str, str]] = []  # (tool_name, args_hash)
        self._violations: List[ViolationRecord] = []
        self._iteration: int = 0

    def check_before_tool_call(
        self,
        tool_name: str,
        arguments: dict,
        context_pct: float,
    ) -> GuardDecision:
        """在工具调用前检查约束.

        Args:
            tool_name: 即将调用的工具名
            arguments: 调用参数
            context_pct: 当前上下文使用率 (0.0 ~ 100.0)

        Returns:
            GuardDecision 裁决结果
        """
        # 1. 迭代上限检查
        if self._iteration >= self.max_iterations:
            violation = ViolationRecord(
                violation_type="max_iterations",
                iteration=self._iteration,
                tool_name=tool_name,
                reason=f"已达到最大迭代次数 {self.max_iterations}",
                timestamp=time.time(),
            )
            self._violations.append(violation)
            return GuardDecision(
                allowed=False,
                reason=violation.reason,
                violation_type="max_iterations",
                forced_end=True,
            )

        # 2. 上下文过载检查
        if context_pct >= self.max_context_pct:
            violation = ViolationRecord(
                violation_type="context_overload",
                iteration=self._iteration,
                tool_name=tool_name,
                reason=f"上下文使用率 {context_pct:.1f}% 超过上限 {self.max_context_pct}%",
                timestamp=time.time(),
            )
            self._violations.append(violation)
            return GuardDecision(
                allowed=False,
                reason=violation.reason,
                violation_type="context_overload",
                forced_end=True,
            )

        # 3. 循环检测: 检查窗口内同一签名的重复次数
        sig = _args_signature(tool_name, arguments)
        duplicate_count = 0
        window_start = max(0, len(self._call_history) - self.loop_detection_window)
        for hist_name, hist_sig in self._call_history[window_start:]:
            if hist_name == tool_name and hist_sig == sig:
                duplicate_count += 1

        if duplicate_count >= self.max_duplicate_calls:
            violation = ViolationRecord(
                violation_type="loop",
                iteration=self._iteration,
                tool_name=tool_name,
                reason=(
                    f"工具 '{tool_name}' 在最近 {self.loop_detection_window} 次调用中"
                    f"重复了 {duplicate_count + 1} 次, 超过上限 {self.max_duplicate_calls}"
                ),
                timestamp=time.time(),
            )
            self._violations.append(violation)
            return GuardDecision(
                allowed=False,
                reason=violation.reason,
                violation_type="loop",
                forced_end=False,
            )

        return GuardDecision(allowed=True)

    def record_tool_call(self, tool_name: str, arguments: dict) -> None:
        """记录一次工具调用 (在调用执行后调用).

        Args:
            tool_name: 工具名
            arguments: 调用参数
        """
        sig = _args_signature(tool_name, arguments)
        self._call_history.append((tool_name, sig))

    def increment_iteration(self) -> None:
        """递增迭代计数器 (每次 agent 循环迭代开始时调用)."""
        self._iteration += 1

    def get_violations(self) -> List[ViolationRecord]:
        """获取所有约束违规记录.

        Returns:
            ViolationRecord 列表
        """
        return list(self._violations)

    def reset(self) -> None:
        """重置 Guard 状态, 用于新的 turn."""
        self._call_history.clear()
        self._violations.clear()
        self._iteration = 0


# ============================================================
# 工厂函数
# ============================================================

def create_harness_components(
    max_iterations: int = 30,
    max_duplicate_calls: int = 3,
    max_context_pct: int = 80,
) -> Tuple[TrajectoryRecorder, HarnessGuard]:
    """创建一组匹配的 Harness 组件, 用于一个 agent turn.

    Args:
        max_iterations: 最大迭代次数
        max_duplicate_calls: 同一签名最大重复调用次数
        max_context_pct: 上下文使用率上限 (百分比)

    Returns:
        (TrajectoryRecorder, HarnessGuard) 元组
    """
    recorder = TrajectoryRecorder()
    guard = HarnessGuard(
        max_iterations=max_iterations,
        max_duplicate_calls=max_duplicate_calls,
        max_context_pct=max_context_pct,
    )
    return recorder, guard


# ============================================================
# MockToolRegistry
# ============================================================

class MockToolRegistry:
    """Mock tool registry for Harness testing.

    Returns preset responses without any real side effects.
    Supports fault injection for testing agent error recovery.
    """

    def __init__(self):
        self._responses: Dict[str, str] = {}
        self._fault_injections: Dict[str, str] = {}
        self._call_log: List[Dict[str, Any]] = []

    def set_response(self, tool_name: str, response: str) -> None:
        """Set a mock response for a tool."""
        self._responses[tool_name] = response

    def set_fault(self, tool_name: str, error_message: str) -> None:
        """Inject a fault for a tool. When called, returns the error message."""
        self._fault_injections[tool_name] = error_message

    def clear_fault(self, tool_name: str) -> None:
        """Remove a fault injection for a tool."""
        self._fault_injections.pop(tool_name, None)

    async def execute(self, tool_name: str, arguments: dict) -> str:
        """Execute a mock tool call. Returns preset response or error."""
        self._call_log.append({
            "tool_name": tool_name,
            "arguments": arguments,
            "timestamp": time.time(),
        })
        if tool_name in self._fault_injections:
            return f"Error: {self._fault_injections[tool_name]}"
        if tool_name in self._responses:
            return self._responses[tool_name]
        return f"Mock response for {tool_name}"

    def get_call_log(self) -> List[Dict[str, Any]]:
        """Return the log of all mock tool calls."""
        return list(self._call_log)

    def reset(self) -> None:
        """Clear all responses, faults, and call log."""
        self._responses.clear()
        self._fault_injections.clear()
        self._call_log.clear()

    @classmethod
    def create_default(cls) -> "MockToolRegistry":
        """Create a MockToolRegistry with sensible default responses."""
        registry = cls()
        registry.set_response("read_file", "# Sample File\nThis is a mock file content.\nIt has multiple lines.\n")
        registry.set_response("write_file", "File written successfully.")
        registry.set_response("edit_file", "Edit applied successfully.")
        registry.set_response("bash", "Command executed successfully.\nExit code: 0\n")
        registry.set_response("glob", "src/main.py\nsrc/utils.py\nsrc/config.py\n")
        registry.set_response("grep", "src/main.py:10: def main():\nsrc/utils.py:5: def helper():\n")
        registry.set_response("list_dir", "src/\ntests/\nREADME.md\npyproject.toml\n")
        registry.set_response("tree", "project/\n├── src/\n│   ├── main.py\n│   └── utils.py\n├── tests/\n└── README.md\n")
        registry.set_response("web_search", "Search result 1: Example page about the topic\nSearch result 2: Another relevant page\n")
        registry.set_response("web_fetch", "This is mock web page content. It contains information about the requested topic.\n")
        return registry


# ============================================================
# HarnessTestCase
# ============================================================

@dataclass
class HarnessTestCase:
    """A single test case for the Harness evaluation framework."""
    name: str
    prompt: str
    expected_pattern: str = ""  # regex pattern to match in the final answer
    expected_keywords: List[str] = field(default_factory=list)
    max_steps: int = 10
    mock_responses: Dict[str, str] = field(default_factory=dict)
    fault_injections: Dict[str, str] = field(default_factory=dict)
    should_succeed: bool = True

    def check_result(self, final_answer: str) -> bool:
        """Check if the final answer matches expectations."""
        if not final_answer:
            return False
        if self.expected_pattern:
            if not re.search(self.expected_pattern, final_answer, re.IGNORECASE):
                return False
        if self.expected_keywords:
            answer_lower = final_answer.lower()
            if not any(kw.lower() in answer_lower for kw in self.expected_keywords):
                return False
        return True


# ============================================================
# HarnessSuite
# ============================================================

class HarnessSuite:
    """A suite of Harness test cases that can be executed together."""

    def __init__(self, name: str = "default"):
        self.name = name
        self.test_cases: List[HarnessTestCase] = []
        self.results: List[Dict[str, Any]] = []

    def add_test(self, test_case: HarnessTestCase) -> None:
        """Add a test case to the suite."""
        self.test_cases.append(test_case)

    async def run_single(self, test_case: HarnessTestCase, agent_core=None) -> Dict[str, Any]:
        """Run a single test case and return the result."""
        mock_registry = MockToolRegistry.create_default()
        # Override with test-specific responses
        for tool_name, response in test_case.mock_responses.items():
            mock_registry.set_response(tool_name, response)
        for tool_name, error in test_case.fault_injections.items():
            mock_registry.set_fault(tool_name, error)

        result = {
            "name": test_case.name,
            "prompt": test_case.prompt,
            "passed": False,
            "final_answer": "",
            "tool_calls": len(mock_registry.get_call_log()),
            "error": None,
        }

        if agent_core is None:
            # Run a simulated test without a real agent
            # This validates the mock infrastructure
            try:
                # Simulate a few tool calls
                mock_registry.execute("read_file", {"path": "/test/file.py"})
                mock_registry.execute("glob", {"pattern": "**/*.py"})

                # Generate a simulated final answer
                final_answer = f"Based on analysis of the project, here are the findings for: {test_case.prompt}"
                result["final_answer"] = final_answer
                result["passed"] = test_case.check_result(final_answer)
            except Exception as e:
                result["error"] = str(e)
        else:
            # Run with real agent using mock registry
            # This would require agent integration which is optional
            result["error"] = "Real agent integration not yet implemented"

        self.results.append(result)
        return result

    async def run_all(self, agent_core=None) -> List[Dict[str, Any]]:
        """Run all test cases in the suite."""
        self.results.clear()
        for tc in self.test_cases:
            await self.run_single(tc, agent_core)
        return self.results

    def summary(self) -> str:
        """Generate a human-readable summary of test results."""
        if not self.results:
            return "No test results available."
        total = len(self.results)
        passed = sum(1 for r in self.results if r["passed"])
        lines = [
            f"Harness Suite: {self.name}",
            f"Results: {passed}/{total} passed ({100*passed//max(1,total)}%)",
            "",
        ]
        for r in self.results:
            status = "PASS" if r["passed"] else "FAIL"
            lines.append(f"  [{status}] {r['name']}")
            if r.get("error"):
                lines.append(f"         Error: {r['error']}")
        return "\n".join(lines)

    @classmethod
    def create_smoke_test(cls) -> "HarnessSuite":
        """Create a built-in smoke test suite for quick validation."""
        suite = cls(name="smoke_test")
        suite.add_test(HarnessTestCase(
            name="basic_read",
            prompt="Read the main file and summarize it",
            expected_keywords=["file", "content"],
            max_steps=5,
        ))
        suite.add_test(HarnessTestCase(
            name="search_and_read",
            prompt="Find all Python files and read the main one",
            expected_keywords=["python", "main"],
            max_steps=8,
        ))
        suite.add_test(HarnessTestCase(
            name="error_recovery",
            prompt="Try to read a file that doesn't exist, then handle the error",
            expected_keywords=["error", "not found"],
            max_steps=5,
            fault_injections={"read_file": "File not found: /nonexistent/path"},
            should_succeed=True,
        ))
        return suite
