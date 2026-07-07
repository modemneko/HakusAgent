"""
Agent 基类 - 借鉴 OpenCode 的 Agent 设计
提供 Agent 的基础框架
"""

from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional
from ...schema.models import (
    AgentConfig,
    AgentState,
    AgentMode,
    Message,
    ToolResult,
)
from ...schema.events import AgentEvent, ToolEvent, MessageEvent
from ..tools import ToolRegistry, ToolExecutor


class BaseAgent(ABC):
    """Agent 基类"""
    
    def __init__(
        self,
        config: AgentConfig,
        tool_registry: ToolRegistry,
        llm_client=None,
    ):
        self.config = config
        self.tool_registry = tool_registry
        self.tool_executor = ToolExecutor()
        self.llm_client = llm_client
        
        self.state = AgentState(
            session_id="",
            mode=config.mode,
        )
        
        self.messages: list[Message] = []
        self._event_handlers: list = []
    
    @property
    def name(self) -> str:
        return self.config.name
    
    @property
    def mode(self) -> AgentMode:
        return self.config.mode
    
    def on_event(self, handler):
        """注册事件处理器"""
        self._event_handlers.append(handler)
    
    def _emit_event(self, event: AgentEvent):
        """触发事件"""
        for handler in self._event_handlers:
            handler(event)
    
    async def execute(self, task: str) -> str:
        """执行任务 - 子类实现"""
        raise NotImplementedError
    
    async def call_llm(self, messages: list[Message]) -> AsyncIterator[str]:
        """调用 LLM - 流式输出"""
        if not self.llm_client:
            raise ValueError("LLM client not configured")
        
        # 子类可以重写此方法以添加自定义逻辑
        async for chunk in self.llm_client.chat(messages):
            yield chunk
    
    async def execute_tool(self, tool_name: str, args: dict) -> ToolResult:
        """执行工具"""
        # 检查权限
        if not self._check_permission(tool_name, args):
            return ToolResult(
                success=False,
                error=f"Permission denied for tool: {tool_name}"
            )
        
        # 发送工具开始事件
        self._emit_event(ToolEvent(
            id="",
            type="tool.start",
            session_id=self.state.session_id,
            agent_name=self.name,
            tool_name=tool_name,
            tool_args=args,
        ))
        
        try:
            # 执行工具
            result = await self.tool_registry.execute(tool_name, args)
            
            # 发送工具完成事件
            self._emit_event(ToolEvent(
                id="",
                type="tool.complete",
                session_id=self.state.session_id,
                agent_name=self.name,
                tool_name=tool_name,
                tool_result=result,
            ))
            
            return result
            
        except Exception as e:
            # 发送工具错误事件
            error_result = ToolResult(success=False, error=str(e))
            self._emit_event(ToolEvent(
                id="",
                type="tool.error",
                session_id=self.state.session_id,
                agent_name=self.name,
                tool_name=tool_name,
                tool_result=error_result,
            ))
            return error_result
    
    def _check_permission(self, tool_name: str, args: dict) -> bool:
        """检查权限"""
        # 基类默认允许所有工具
        # 子类可以重写此方法以添加权限检查
        return True
    
    def add_message(self, role: str, content: str):
        """添加消息"""
        message = Message(
            id=f"{role}_{len(self.messages)}",
            role=role,
            content=content,
        )
        self.messages.append(message)
        
        # 发送消息事件
        self._emit_event(MessageEvent(
            id="",
            type="message.add",
            session_id=self.state.session_id,
            agent_name=self.name,
            message_role=role,
            message_content=content,
        ))
    
    def get_system_prompt(self) -> str:
        """获取系统提示词"""
        # 子类应该重写此方法
        return f"You are {self.name}, an AI assistant."
    
    def reset(self):
        """重置 Agent 状态"""
        self.state = AgentState(
            session_id=self.state.session_id,
            mode=self.config.mode,
        )
        self.messages.clear()