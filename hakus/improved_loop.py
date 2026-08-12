"""
改进的 Agent 循环
添加软停止、Doom Loop 检测、上下文溢出保护
"""

import asyncio
import time
from typing import Optional, Any, AsyncIterator, Dict, List
from dataclasses import dataclass, field
import logging
import json

logger = logging.getLogger(__name__)


@dataclass
class AgentLoopConfig:
    """Agent 循环配置"""
    # 迭代控制
    max_iterations: int = 50
    soft_stop_threshold: int = 40  # 软停止阈值（注入提示让 LLM 总结）
    
    # 超时配置
    llm_timeout: float = 120.0
    tool_timeout: float = 60.0
    
    # 上下文保护
    context_overflow_threshold: float = 0.5  # 50% 时触发压缩 (ACI: 对齐 SWE-Agent 早期压缩)
    
    # Doom Loop 检测
    doom_loop_enabled: bool = True
    doom_loop_window: int = 3  # 滑动窗口大小
    doom_loop_threshold: int = 3  # 触发检测的相同调用次数
    
    # 重试配置
    max_retries: int = 3
    retry_delay: float = 2.0


# 软停止提示词（借鉴 OpenCode 的 MAX_STEPS_PROMPT）
SOFT_STOP_PROMPT = """CRITICAL - MAXIMUM STEPS APPROACHING

You are approaching the maximum number of steps allowed for this task. 
Tools will be disabled soon. You MUST:

1. Immediately stop using tools
2. Provide a comprehensive summary of your findings and progress
3. List any incomplete work that needs attention
4. Give your final answer or recommendation

Do NOT make any more tool calls. Your next response should be a complete summary."""

DOOM_LOOP_PROMPT = """POTENTIAL INFINITE LOOP DETECTED

You appear to be making the same tool call repeatedly. This is not productive.
Please:
1. Stop making the same tool call
2. Try a different approach or tool
3. Or provide a summary if you believe the task is complete"""


class DoomLoopDetector:
    """Doom Loop 检测器（借鉴 OpenCode 的 processor.ts）"""
    
    def __init__(self, window_size: int = 3, threshold: int = 3):
        self.window_size = window_size
        self.threshold = threshold
        self._history: List[tuple] = []  # [(tool_name, input_hash)]
    
    def record(self, tool_name: str, tool_input: dict):
        """记录工具调用"""
        input_hash = json.dumps(tool_input, sort_keys=True, default=str)
        self._history.append((tool_name, input_hash))
        
        # 保持窗口大小
        if len(self._history) > self.window_size * 2:
            self._history = self._history[-self.window_size * 2:]
    
    def is_loop_detected(self) -> tuple[bool, Optional[str]]:
        """检测是否形成循环"""
        if len(self._history) < self.threshold:
            return False, None
        
        # 检查最近 N 次调用是否完全相同
        recent = self._history[-self.threshold:]
        tool_names = [h[0] for h in recent]
        input_hashes = [h[1] for h in recent]
        
        # 所有工具名相同且所有输入相同
        if len(set(tool_names)) == 1 and len(set(input_hashes)) == 1:
            return True, tool_names[0]
        
        return False, None
    
    def reset(self):
        """重置历史"""
        self._history.clear()


class ContextMonitor:
    """上下文监控器"""
    
    def __init__(self, max_tokens: int = 128000, threshold: float = 0.7):
        self.max_tokens = max_tokens
        self.threshold = threshold
        self._current_tokens: int = 0
    
    def update(self, tokens: int):
        """更新当前 token 数"""
        self._current_tokens = tokens
    
    def get_usage_percentage(self) -> float:
        """获取上下文使用百分比"""
        return self._current_tokens / self.max_tokens if self.max_tokens > 0 else 0
    
    def is_overflow_warning(self) -> bool:
        """是否需要溢出警告"""
        return self.get_usage_percentage() >= self.threshold
    
    def is_overflow_critical(self) -> bool:
        """是否达到临界溢出"""
        return self.get_usage_percentage() >= 0.9


class ImprovedAgentLoop:
    """改进的 Agent 循环"""
    
    def __init__(self, config: Optional[AgentLoopConfig] = None):
        self.config = config or AgentLoopConfig()
        self.doom_loop_detector = DoomLoopDetector(
            window_size=self.config.doom_loop_window,
            threshold=self.config.doom_loop_threshold,
        )
        self.context_monitor = ContextMonitor()
        
        # 状态
        self._iteration = 0
        self._soft_stop_triggered = False
        self._doom_loop_detected = False
    
    def should_continue(self) -> tuple[bool, Optional[str]]:
        """
        检查是否应该继续循环
        
        Returns:
            (是否继续, 停止原因)
        """
        # 检查硬限制
        if self._iteration >= self.config.max_iterations:
            return False, f"Max iterations ({self.config.max_iterations}) reached"
        
        # 检查软停止
        if self._iteration >= self.config.soft_stop_threshold and not self._soft_stop_triggered:
            self._soft_stop_triggered = True
            logger.info(f"Soft stop triggered at iteration {self._iteration}")
            # 不立即停止，但会在下次 LLM 调用时注入提示
        
        # 检查 Doom Loop
        if self.config.doom_loop_enabled:
            is_loop, tool_name = self.doom_loop_detector.is_loop_detected()
            if is_loop:
                self._doom_loop_detected = True
                return False, f"Doom loop detected: {tool_name}"
        
        # 检查上下文溢出
        if self.context_monitor.is_overflow_critical():
            return False, "Context overflow critical (>=90%)"
        
        return True, None
    
    def get_system_prompt_suffix(self) -> str:
        """获取系统提示词后缀（用于软停止）"""
        if self._soft_stop_triggered:
            return f"\n\n{SOFT_STOP_PROMPT}"
        return ""
    
    def get_iteration_hint(self) -> str:
        """获取迭代提示（注入到系统提示词）"""
        remaining = self.config.max_iterations - self._iteration
        
        if remaining <= 5:
            return f"\n\n[CRITICAL] Only {remaining} iteration(s) remaining. Summarize and finish immediately."
        elif remaining <= 10:
            return f"\n\n[WARNING] {remaining} iterations remaining. Start wrapping up."
        return ""
    
    def record_tool_call(self, tool_name: str, tool_input: dict):
        """记录工具调用"""
        self.doom_loop_detector.record(tool_name, tool_input)
    
    def update_context(self, tokens: int):
        """更新上下文 token 数"""
        self.context_monitor.update(tokens)
    
    def increment(self):
        """增加迭代计数"""
        self._iteration += 1
    
    def reset(self):
        """重置状态"""
        self._iteration = 0
        self._soft_stop_triggered = False
        self._doom_loop_detected = False
        self.doom_loop_detector.reset()
    
    @property
    def current_iteration(self) -> int:
        return self._iteration
    
    @property
    def is_soft_stopped(self) -> bool:
        return self._soft_stop_triggered
    
    @property
    def is_doom_loop(self) -> bool:
        return self._doom_loop_detected