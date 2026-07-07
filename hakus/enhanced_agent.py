"""
Agent 增强模块 - 整合超时、重试、循环控制、恢复等功能
"""

import asyncio
import time
from typing import Optional, Any, AsyncIterator, Dict, List
from dataclasses import dataclass
import logging

from .timeout import (
    TimeoutManager,
    TimeoutConfig,
    TimeoutLevel,
    TimeoutError,
    SSEChunkTimeout,
    RetryManager,
    DoomLoopDetector as BaseDoomLoopDetector,
)
from .improved_loop import (
    ImprovedAgentLoop,
    AgentLoopConfig,
    DoomLoopDetector,
    ContextMonitor,
)
from .recovery import (
    RecoveryManager,
    SessionSnapshot,
    ToolState,
    recovery_manager,
)

logger = logging.getLogger(__name__)


@dataclass
class EnhancedAgentConfig:
    """增强的 Agent 配置"""
    # 超时配置
    llm_timeout: float = 120.0
    tool_timeout: float = 60.0
    connection_timeout: float = 30.0
    
    # 迭代控制
    max_iterations: int = 50
    soft_stop_threshold: int = 40
    
    # 重试配置
    max_retries: int = 3
    retry_delay: float = 2.0
    
    # 上下文保护
    context_max_tokens: int = 128000
    context_overflow_threshold: float = 0.7
    
    # Doom Loop 检测
    doom_loop_enabled: bool = True
    doom_loop_window: int = 3
    
    # 恢复配置
    autosave_enabled: bool = True
    autosave_interval: int = 5  # 每 5 次迭代自动保存


class EnhancedAgent:
    """增强的 Agent"""
    
    def __init__(self, config: Optional[EnhancedAgentConfig] = None):
        self.config = config or EnhancedAgentConfig()
        
        # 初始化各组件
        self.timeout_manager = TimeoutManager(TimeoutConfig(
            tool_timeout=self.config.tool_timeout,
            tool_timeout_max=600.0,
            provider_timeout=self.config.llm_timeout,
            connection_timeout=self.config.connection_timeout,
            retry_enabled=True,
            retry_max_attempts=self.config.max_retries,
            retry_initial_delay=self.config.retry_delay,
        ))
        
        self.retry_manager = RetryManager(TimeoutConfig(
            retry_enabled=True,
            retry_max_attempts=self.config.max_retries,
            retry_initial_delay=self.config.retry_delay,
        ))
        
        self.agent_loop = ImprovedAgentLoop(AgentLoopConfig(
            max_iterations=self.config.max_iterations,
            soft_stop_threshold=self.config.soft_stop_threshold,
            llm_timeout=self.config.llm_timeout,
            tool_timeout=self.config.tool_timeout,
            context_overflow_threshold=self.config.context_overflow_threshold,
            doom_loop_enabled=self.config.doom_loop_enabled,
            doom_loop_window=self.config.doom_loop_window,
        ))
        
        self.recovery_manager = recovery_manager
        
        # 状态
        self._session_id: Optional[str] = None
        self._messages: List[Dict] = []
        self._tool_states: Dict[str, ToolState] = {}
        self._last_autosave_iteration = 0
    
    async def run_with_enhancements(
        self,
        messages: List[Dict],
        llm_caller: Any,
        tool_executor: Any,
        session_id: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        带增强功能的运行
        
        Args:
            messages: 消息列表
            llm_caller: LLM 调用函数
            tool_executor: 工具执行函数
            session_id: 会话 ID
            
        Yields:
            事件字典
        """
        self._session_id = session_id or f"session_{int(time.time())}"
        self._messages = messages.copy()
        self.agent_loop.reset()
        
        # 尝试恢复之前的会话
        await self._try_resume_session()
        
        yield {"type": "session_started", "session_id": self._session_id}
        
        try:
            while True:
                # 检查是否应该继续
                should_continue, stop_reason = self.agent_loop.should_continue()
                if not should_continue:
                    yield {"type": "loop_stopped", "reason": stop_reason}
                    break
                
                # 增加迭代计数
                self.agent_loop.increment()
                iteration = self.agent_loop.current_iteration
                
                yield {"type": "iteration_start", "iteration": iteration}
                
                # 自动保存
                if (self.config.autosave_enabled and 
                    iteration - self._last_autosave_iteration >= self.config.autosave_interval):
                    await self._autosave()
                    self._last_autosave_iteration = iteration
                
                # 构建系统提示词（包含软停止提示）
                system_prompt_suffix = self.agent_loop.get_system_prompt_suffix()
                iteration_hint = self.agent_loop.get_iteration_hint()
                
                # 调用 LLM
                try:
                    llm_response = await self.timeout_manager.with_timeout(
                        llm_caller(
                            self._messages,
                            system_prompt_suffix=system_prompt_suffix + iteration_hint,
                        ),
                        timeout=self.config.llm_timeout,
                        level=TimeoutLevel.PROVIDER,
                        operation="LLM call",
                    )
                except TimeoutError as e:
                    yield {"type": "llm_timeout", "error": str(e)}
                    # 超时后尝试重试
                    if not self.retry_manager.is_retryable(e):
                        break
                    continue
                
                yield {"type": "llm_response", "content": llm_response.get("content", "")}
                
                # 检查是否有工具调用
                tool_calls = llm_response.get("tool_calls", [])
                if not tool_calls:
                    yield {"type": "turn_completed", "content": llm_response.get("content", "")}
                    break
                
                # 执行工具调用
                for tool_call in tool_calls:
                    tool_name = tool_call.get("name", "")
                    tool_input = tool_call.get("arguments", {})
                    tool_call_id = tool_call.get("id", "")
                    
                    # 记录工具调用（用于 Doom Loop 检测）
                    self.agent_loop.record_tool_call(tool_name, tool_input)
                    
                    # 创建工具状态
                    tool_state = ToolState(
                        tool_call_id=tool_call_id,
                        tool_name=tool_name,
                        status="running",
                        input_data=tool_input,
                        start_time=time.time(),
                    )
                    self._tool_states[tool_call_id] = tool_state
                    
                    yield {"type": "tool_call_started", "tool_name": tool_name, "tool_call_id": tool_call_id}
                    
                    # 执行工具（带超时）
                    try:
                        tool_result = await self.timeout_manager.with_timeout(
                            tool_executor(tool_name, tool_input),
                            timeout=self.config.tool_timeout,
                            level=TimeoutLevel.TOOL,
                            operation=f"Tool {tool_name}",
                        )
                        
                        tool_state.status = "completed"
                        tool_state.output_data = tool_result
                        tool_state.end_time = time.time()
                        
                        yield {"type": "tool_call_completed", "tool_call_id": tool_call_id, "result": tool_result}
                        
                    except TimeoutError as e:
                        tool_state.status = "timeout"
                        tool_state.error = str(e)
                        tool_state.end_time = time.time()
                        
                        yield {"type": "tool_timeout", "tool_call_id": tool_call_id, "error": str(e)}
                        
                    except Exception as e:
                        tool_state.status = "failed"
                        tool_state.error = str(e)
                        tool_state.end_time = time.time()
                        
                        yield {"type": "tool_error", "tool_call_id": tool_call_id, "error": str(e)}
                    
                    # 保存工具状态
                    self.recovery_manager.save_tool_state(self._session_id, tool_state)
                    
                    # 将工具结果添加到消息
                    self._messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": json.dumps(tool_state.output_data) if tool_state.output_data else tool_state.error,
                    })
                
                yield {"type": "iteration_completed", "iteration": iteration}
            
            # 最终保存
            await self._final_save()
            
            yield {"type": "session_completed", "session_id": self._session_id}
            
        except Exception as e:
            logger.error(f"Session error: {e}")
            yield {"type": "session_error", "error": str(e)}
            
            # 错误时也尝试保存
            await self._error_save()
    
    async def _try_resume_session(self):
        """尝试恢复之前的会话"""
        try:
            snapshot = self.recovery_manager.get_latest_snapshot(self._session_id)
            if snapshot:
                logger.info(f"Resuming session from snapshot at iteration {snapshot.iteration}")
                self._messages = snapshot.messages
                self.agent_loop._iteration = snapshot.iteration
                
                # 检查被中断的工具
                interrupted_tools = self.recovery_manager.get_interrupted_tools(self._session_id)
                if interrupted_tools:
                    logger.warning(f"Found {len(interrupted_tools)} interrupted tools")
                    # 可以在这里处理被中断的工具
        except Exception as e:
            logger.warning(f"Failed to resume session: {e}")
    
    async def _autosave(self):
        """自动保存"""
        try:
            # 更新上下文 token 数
            # 这里应该计算实际的 token 数
            context_tokens = len(str(self._messages)) // 4  # 粗略估计
            
            self.agent_loop.update_context(context_tokens)
            
            self.recovery_manager.create_autosave(
                session_id=self._session_id,
                iteration=self.agent_loop.current_iteration,
                messages=self._messages,
                tool_states=self._tool_states,
                context_tokens=context_tokens,
            )
            logger.debug(f"Autosave at iteration {self.agent_loop.current_iteration}")
        except Exception as e:
            logger.warning(f"Autosave failed: {e}")
    
    async def _final_save(self):
        """最终保存"""
        try:
            snapshot = SessionSnapshot(
                session_id=self._session_id,
                iteration=self.agent_loop.current_iteration,
                messages=self._messages,
                tool_states=self._tool_states,
                context_tokens=0,
                timestamp=time.time(),
                metadata={"type": "final"},
            )
            self.recovery_manager.save_snapshot(snapshot)
        except Exception as e:
            logger.warning(f"Final save failed: {e}")
    
    async def _error_save(self):
        """错误保存"""
        try:
            # 清理被中断的工具
            self.recovery_manager.cleanup_interrupted_tools(self._session_id)
            
            snapshot = SessionSnapshot(
                session_id=self._session_id,
                iteration=self.agent_loop.current_iteration,
                messages=self._messages,
                tool_states=self._tool_states,
                context_tokens=0,
                timestamp=time.time(),
                metadata={"type": "error_save"},
            )
            self.recovery_manager.save_snapshot(snapshot)
        except Exception as e:
            logger.warning(f"Error save failed: {e}")
    
    def cancel(self):
        """取消当前执行"""
        self.recovery_manager.cleanup_interrupted_tools(self._session_id)
    
    def get_status(self) -> Dict[str, Any]:
        """获取当前状态"""
        return {
            "session_id": self._session_id,
            "iteration": self.agent_loop.current_iteration,
            "max_iterations": self.config.max_iterations,
            "soft_stopped": self.agent_loop.is_soft_stopped,
            "doom_loop": self.agent_loop.is_doom_loop,
            "context_usage": self.agent_loop.context_monitor.get_usage_percentage(),
            "tool_states": {
                k: {"status": v.status, "name": v.tool_name}
                for k, v in self._tool_states.items()
            },
        }


# 导入 json
import json