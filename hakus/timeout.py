"""
超时处理模块 - 借鉴 OpenCode 的分级超时体系
提供工具级、Provider级、连接级的分层超时控制
"""

import asyncio
import time
from typing import Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class TimeoutLevel(str, Enum):
    """超时级别"""
    TOOL = "tool"           # 工具级超时
    PROVIDER = "provider"   # Provider 级超时
    CONNECTION = "connection"  # 连接级超时


@dataclass
class TimeoutConfig:
    """超时配置"""
    # 工具级超时（默认 2 分钟，最大 10 分钟）
    tool_timeout: float = 120.0
    tool_timeout_max: float = 600.0
    
    # Provider 级超时（LLM API 调用）
    provider_timeout: float = 120.0      # 完整请求超时
    header_timeout: float = 30.0         # 响应头超时
    chunk_timeout: float = 60.0          # SSE chunk 间超时
    
    # 连接级超时
    connection_timeout: float = 30.0     # TCP 连接超时
    read_timeout: float = 60.0           # 读取超时
    
    # 重试配置
    retry_enabled: bool = True
    retry_max_attempts: int = 3
    retry_initial_delay: float = 2.0     # 初始 2 秒
    retry_backoff_factor: float = 2.0    # 指数退避因子
    retry_max_delay: float = 30.0        # 最大 30 秒


class TimeoutError(Exception):
    """超时错误"""
    
    def __init__(
        self,
        level: TimeoutLevel,
        timeout: float,
        operation: str = "",
        message: str = "",
    ):
        self.level = level
        self.timeout = timeout
        self.operation = operation
        super().__init__(message or f"{level.value} timeout after {timeout}s: {operation}")


class TimeoutManager:
    """超时管理器"""
    
    def __init__(self, config: Optional[TimeoutConfig] = None):
        self.config = config or TimeoutConfig()
        self._active_timers: dict[str, asyncio.TimerHandle] = {}
    
    async def with_timeout(
        self,
        coro,
        timeout: float,
        level: TimeoutLevel = TimeoutLevel.TOOL,
        operation: str = "",
        fallback: Optional[Any] = None,
    ) -> Any:
        """
        带超时的异步执行
        
        Args:
            coro: 协程
            timeout: 超时时间（秒）
            level: 超时级别
            operation: 操作描述
            fallback: 超时后的回退值
            
        Returns:
            执行结果或回退值
        """
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"Timeout ({level.value}): {operation} after {timeout}s")
            if fallback is not None:
                return fallback
            raise TimeoutError(level, timeout, operation)
    
    def create_timeout_task(
        self,
        coro,
        timeout: float,
        level: TimeoutLevel = TimeoutLevel.TOOL,
        operation: str = "",
        on_timeout: Optional[Callable] = None,
    ) -> asyncio.Task:
        """
        创建带超时的任务
        
        Args:
            coro: 协程
            timeout: 超时时间
            level: 超时级别
            operation: 操作描述
            on_timeout: 超时回调
            
        Returns:
            asyncio.Task
        """
        async def wrapped():
            try:
                return await asyncio.wait_for(coro, timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(f"Timeout ({level.value}): {operation} after {timeout}s")
                if on_timeout:
                    on_timeout()
                raise TimeoutError(level, timeout, operation)
        
        return asyncio.create_task(wrapped())
    
    def get_timeout(self, level: TimeoutLevel, tool_name: str = "") -> float:
        """获取指定级别的超时时间"""
        if level == TimeoutLevel.TOOL:
            # 特殊工具可以有自定义超时
            if "bash" in tool_name.lower() or "shell" in tool_name.lower():
                return self.config.tool_timeout_max  # Shell 工具使用最大超时
            return self.config.tool_timeout
        elif level == TimeoutLevel.PROVIDER:
            return self.config.provider_timeout
        elif level == TimeoutLevel.CONNECTION:
            return self.config.connection_timeout
        return self.config.read_timeout


class SSEChunkTimeout:
    """SSE Chunk 超时监控
    
    防止 LLM 流式响应卡死的专用机制
    参考 OpenCode 的 aisdk.ts 实现
    """
    
    def __init__(self, chunk_timeout: float = 60.0):
        self.chunk_timeout = chunk_timeout
        self._last_chunk_time: float = 0
        self._timer: Optional[asyncio.TimerHandle] = None
        self._on_timeout: Optional[Callable] = None
        self._aborted = False
    
    def start(self, on_timeout: Optional[Callable] = None):
        """开始监控"""
        self._last_chunk_time = time.time()
        self._on_timeout = on_timeout
        self._aborted = False
        self._reset_timer()
    
    def update(self):
        """更新最后收到 chunk 的时间"""
        self._last_chunk_time = time.time()
        self._reset_timer()
    
    def _reset_timer(self):
        """重置超时计时器"""
        if self._timer:
            self._timer.cancel()
        
        loop = asyncio.get_event_loop()
        self._timer = loop.call_later(
            self.chunk_timeout,
            self._on_timeout_callback,
        )
    
    def _on_timeout_callback(self):
        """超时回调"""
        if self._aborted:
            return
        
        elapsed = time.time() - self._last_chunk_time
        if elapsed >= self.chunk_timeout:
            self._aborted = True
            logger.error(f"SSE chunk timeout after {elapsed:.1f}s")
            if self._on_timeout:
                self._on_timeout()
    
    def stop(self):
        """停止监控"""
        if self._timer:
            self._timer.cancel()
            self._timer = None
    
    @property
    def is_aborted(self) -> bool:
        """是否已超时中止"""
        return self._aborted


class RetryManager:
    """重试管理器
    
    参考 OpenCode 的 session/retry.ts 实现
    支持指数退避和 Retry-After header
    """
    
    def __init__(self, config: Optional[TimeoutConfig] = None):
        self.config = config or TimeoutConfig()
    
    def calculate_delay(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """
        计算重试延迟
        
        Args:
            attempt: 当前重试次数（从 1 开始）
            retry_after: 服务端返回的 Retry-After 时间（秒）
            
        Returns:
            延迟时间（秒）
        """
        # 优先使用服务端的 Retry-After
        if retry_after and retry_after > 0:
            return min(retry_after, self.config.retry_max_delay)
        
        # 指数退避
        delay = self.config.retry_initial_delay * (
            self.config.retry_backoff_factor ** (attempt - 1)
        )
        
        # 加入随机抖动（jitter）
        import random
        jitter = random.uniform(0.8, 1.2)
        delay *= jitter
        
        return min(delay, self.config.retry_max_delay)
    
    def is_retryable(self, error: Exception) -> bool:
        """
        判断错误是否可重试
        
        Args:
            error: 异常对象
            
        Returns:
            是否可重试
        """
        if not self.config.retry_enabled:
            return False
        
        error_msg = str(error).lower()
        
        # 不可重试的错误
        non_retryable = [
            "context_length_exceeded",
            "invalid_api_key",
            "permission denied",
            "quota exceeded",
        ]
        for pattern in non_retryable:
            if pattern in error_msg:
                return False
        
        # 可重试的错误
        retryable = [
            "timeout",
            "timed out",
            "connection",
            "network",
            "econnreset",
            "econnrefused",
            "temporary",
            "rate limit",
            "500",
            "502",
            "503",
            "504",
        ]
        for pattern in retryable:
            if pattern in error_msg:
                return True
        
        return False
    
    def parse_retry_after(self, headers: dict) -> Optional[float]:
        """
        解析 Retry-After header
        
        Args:
            headers: 响应头
            
        Returns:
            重试延迟时间（秒）或 None
        """
        retry_after = headers.get("retry-after") or headers.get("Retry-After")
        if not retry_after:
            return None
        
        # 尝试解析为数字（秒）
        try:
            return float(retry_after)
        except ValueError:
            pass
        
        # 尝试解析为 HTTP 日期
        from email.utils import parsedate_to_datetime
        try:
            from datetime import datetime, timezone
            dt = parsedate_to_datetime(retry_after)
            now = datetime.now(timezone.utc)
            delta = (dt - now).total_seconds()
            return max(0, delta)
        except Exception:
            pass
        
        return None


class DoomLoopDetector:
    """Doom Loop 检测器
    
    参考 OpenCode 的 processor.ts 实现
    检测连续相同工具调用形成的无限循环
    """
    
    def __init__(self, window_size: int = 3, threshold: int = 3):
        """
        Args:
            window_size: 滑动窗口大小
            threshold: 触发检测的相同调用次数
        """
        self.window_size = window_size
        self.threshold = threshold
        self._history: list[tuple[str, str]] = []  # [(tool_name, input_hash)]
    
    def record(self, tool_name: str, tool_input: dict):
        """记录工具调用"""
        import json
        input_hash = json.dumps(tool_input, sort_keys=True, default=str)
        self._history.append((tool_name, input_hash))
        
        # 保持窗口大小
        if len(self._history) > self.window_size * 2:
            self._history = self._history[-self.window_size * 2:]
    
    def is_loop_detected(self) -> tuple[bool, Optional[str]]:
        """
        检测是否形成循环
        
        Returns:
            (是否检测到循环, 触发的工具名)
        """
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


# 全局实例
timeout_manager = TimeoutManager()
retry_manager = RetryManager()
doom_loop_detector = DoomLoopDetector()