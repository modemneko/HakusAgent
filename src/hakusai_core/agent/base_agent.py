"""
HakusAI 2.0 Agent基类
实现AI对话的核心逻辑
"""

from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum, auto
import asyncio
import logging

from ..models.base import (
    BaseModelAdapter,
    Message,
    MessageRole,
    ChatOptions,
    ChatResponse,
    ToolDefinition,
)
from ..utils.events import EventType, emit
from ..config import config_manager

logger = logging.getLogger(__name__)


class AgentState(Enum):
    """Agent状态"""
    IDLE = auto()
    THINKING = auto()
    SPEAKING = auto()
    TOOL_CALLING = auto()
    ERROR = auto()


@dataclass
class AgentContext:
    """Agent上下文"""
    session_id: str
    user_id: str = "default"
    metadata: Dict[str, Any] = field(default_factory=dict)
    

@dataclass
class AgentResponse:
    """Agent响应"""
    content: str
    emotion: Optional[str] = None
    actions: List[str] = field(default_factory=list)
    audio_url: Optional[str] = None
    tool_calls: Optional[List[Dict]] = None
    

class BaseAgent(ABC):
    """
    Agent基类
    
    实现AI对话的核心逻辑，包括：
    - 对话管理
    - 工具调用
    - 记忆集成
    - 事件触发
    """
    
    def __init__(
        self,
        model_adapter: BaseModelAdapter,
        system_prompt: Optional[str] = None,
    ):
        """
        初始化Agent
        
        Args:
            model_adapter: 模型适配器
            system_prompt: 系统提示词
        """
        self.model = model_adapter
        self.system_prompt = system_prompt or self._default_system_prompt()
        self.state = AgentState.IDLE
        self.context: Optional[AgentContext] = None
        self._message_history: List[Message] = []
        self._tools: List[ToolDefinition] = []
        self._tool_handlers: Dict[str, Callable] = {}
        
        # 钩子函数
        self._before_chat_hooks: List[Callable] = []
        self._after_chat_hooks: List[Callable] = []
        self._on_token_hooks: List[Callable] = []
        
    def _default_system_prompt(self) -> str:
        """默认系统提示词"""
        config = config_manager.config
        character = config.character
        
        prompt = f"""你是{character.name}，{character.personality}

重要提示：
1. 保持友好、自然的对话风格
2. 回答要简洁明了，避免过长
3. 可以适当使用表情符号增加亲和力
4. 如果不确定，诚实地说不知道
"""
        if character.system_prompt:
            prompt += f"\n\n{character.system_prompt}"
        
        return prompt
    
    def register_tool(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable
    ):
        """
        注册工具
        
        Args:
            name: 工具名称
            description: 工具描述
            parameters: 参数定义（JSON Schema）
            handler: 处理函数
        """
        tool = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters
        )
        self._tools.append(tool)
        self._tool_handlers[name] = handler
        logger.debug(f"Registered tool: {name}")
    
    def add_hook(self, hook_type: str, handler: Callable):
        """
        添加钩子函数
        
        Args:
            hook_type: 钩子类型 (before_chat, after_chat, on_token)
            handler: 处理函数
        """
        if hook_type == "before_chat":
            self._before_chat_hooks.append(handler)
        elif hook_type == "after_chat":
            self._after_chat_hooks.append(handler)
        elif hook_type == "on_token":
            self._on_token_hooks.append(handler)
    
    async def _run_hooks(self, hook_type: str, *args, **kwargs):
        """运行钩子函数"""
        hooks = []
        if hook_type == "before_chat":
            hooks = self._before_chat_hooks
        elif hook_type == "after_chat":
            hooks = self._after_chat_hooks
        elif hook_type == "on_token":
            hooks = self._on_token_hooks
        
        for hook in hooks:
            try:
                if asyncio.iscoroutinefunction(hook):
                    await hook(*args, **kwargs)
                else:
                    hook(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in {hook_type} hook: {e}")
    
    def _build_messages(self, user_input: str) -> List[Message]:
        """
        构建消息列表
        
        Args:
            user_input: 用户输入
            
        Returns:
            消息列表
        """
        messages = []
        
        # 系统提示词
        if self.system_prompt:
            messages.append(Message(
                role=MessageRole.SYSTEM,
                content=self.system_prompt
            ))
        
        # 历史消息
        messages.extend(self._message_history)
        
        # 用户输入
        messages.append(Message(
            role=MessageRole.USER,
            content=user_input
        ))
        
        return messages
    
    async def chat(
        self,
        user_input: str,
        context: Optional[AgentContext] = None,
        stream: bool = True
    ) -> AsyncIterator[AgentResponse]:
        """
        对话入口
        
        Args:
            user_input: 用户输入
            context: 对话上下文
            stream: 是否流式输出
            
        Yields:
            Agent响应
        """
        self.context = context or AgentContext(session_id="default")
        
        try:
            # 触发开始事件
            await emit(EventType.CHAT_STREAM_START, {
                "session_id": self.context.session_id,
                "user_input": user_input
            })
            
            # 运行前置钩子
            await self._run_hooks("before_chat", user_input, self.context)
            
            # 构建消息
            messages = self._build_messages(user_input)
            
            # 设置选项
            options = ChatOptions(
                temperature=self.model.temperature,
                max_tokens=self.model.max_tokens,
                stream=stream,
                tools=self._tools if self._tools else None
            )
            
            if stream:
                # 流式对话
                async for response in self._chat_stream(messages, options):
                    yield response
            else:
                # 非流式对话
                response = await self._chat_once(messages, options)
                yield response
            
            # 运行后置钩子
            await self._run_hooks("after_chat", user_input, self.context)
            
        except Exception as e:
            logger.error(f"Error in chat: {e}")
            self.state = AgentState.ERROR
            yield AgentResponse(
                content=f"抱歉，我遇到了一些问题：{str(e)}"
            )
    
    async def _chat_stream(
        self,
        messages: List[Message],
        options: ChatOptions
    ) -> AsyncIterator[AgentResponse]:
        """
        流式对话实现
        
        Args:
            messages: 消息列表
            options: 聊天选项
            
        Yields:
            Agent响应片段
        """
        self.state = AgentState.THINKING
        
        full_content = ""
        
        async for token in self.model.chat_stream(messages, options):
            full_content += token
            
            # 触发token事件
            await emit(EventType.CHAT_STREAM_TOKEN, {
                "session_id": self.context.session_id,
                "token": token
            })
            
            # 运行token钩子
            await self._run_hooks("on_token", token)
            
            # 提取表情和动作
            emotion = self._extract_emotion(full_content)
            actions = self._extract_actions(full_content)
            
            yield AgentResponse(
                content=token,
                emotion=emotion,
                actions=actions
            )
        
        # 保存到历史
        self._message_history.append(Message(
            role=MessageRole.USER,
            content=messages[-1].content
        ))
        self._message_history.append(Message(
            role=MessageRole.ASSISTANT,
            content=full_content
        ))
        
        # 限制历史长度
        max_history = config_manager.config.memory.short_term_max
        if len(self._message_history) > max_history * 2:
            self._message_history = self._message_history[-max_history * 2:]
        
        self.state = AgentState.IDLE
        
        # 触发结束事件
        await emit(EventType.CHAT_STREAM_END, {
            "session_id": self.context.session_id,
            "full_content": full_content
        })
    
    async def _chat_once(
        self,
        messages: List[Message],
        options: ChatOptions
    ) -> AgentResponse:
        """
        非流式对话实现
        
        Args:
            messages: 消息列表
            options: 聊天选项
            
        Returns:
            Agent响应
        """
        self.state = AgentState.THINKING
        
        response = await self.model.chat(messages, options)
        
        # 处理工具调用
        if response.tool_calls:
            self.state = AgentState.TOOL_CALLING
            tool_results = await self._execute_tool_calls(response.tool_calls)
            
            # 将工具结果添加到消息
            messages.append(Message(
                role=MessageRole.ASSISTANT,
                content=response.content,
                tool_calls=response.tool_calls
            ))
            
            for result in tool_results:
                messages.append(Message(
                    role=MessageRole.TOOL,
                    content=result["content"],
                    tool_call_id=result["tool_call_id"]
                ))
            
            # 再次调用模型
            response = await self.model.chat(messages, options)
        
        # 保存到历史
        self._message_history.append(Message(
            role=MessageRole.USER,
            content=messages[-1].content
        ))
        self._message_history.append(Message(
            role=MessageRole.ASSISTANT,
            content=response.content
        ))
        
        self.state = AgentState.IDLE
        
        # 提取表情和动作
        emotion = self._extract_emotion(response.content)
        actions = self._extract_actions(response.content)
        
        return AgentResponse(
            content=response.content,
            emotion=emotion,
            actions=actions,
            tool_calls=response.tool_calls
        )
    
    async def _execute_tool_calls(
        self,
        tool_calls: List[Dict]
    ) -> List[Dict]:
        """
        执行工具调用
        
        Args:
            tool_calls: 工具调用列表
            
        Returns:
            工具执行结果
        """
        results = []
        
        for call in tool_calls:
            function = call.get("function", {})
            name = function.get("name")
            arguments = function.get("arguments", "{}")
            call_id = call.get("id")
            
            if name in self._tool_handlers:
                try:
                    import json
                    args = json.loads(arguments)
                    handler = self._tool_handlers[name]
                    
                    if asyncio.iscoroutinefunction(handler):
                        result = await handler(**args)
                    else:
                        result = handler(**args)
                    
                    results.append({
                        "tool_call_id": call_id,
                        "content": str(result)
                    })
                except Exception as e:
                    logger.error(f"Error executing tool {name}: {e}")
                    results.append({
                        "tool_call_id": call_id,
                        "content": f"Error: {str(e)}"
                    })
            else:
                results.append({
                    "tool_call_id": call_id,
                    "content": f"Tool {name} not found"
                })
        
        return results
    
    def _extract_emotion(self, text: str) -> Optional[str]:
        """
        从文本中提取表情
        
        Args:
            text: 文本内容
            
        Returns:
            表情名称
        """
        # 简单的表情提取逻辑
        emotion_map = {
            "开心": "joy",
            "高兴": "joy",
            "难过": "sadness",
            "伤心": "sadness",
            "生气": "anger",
            "愤怒": "anger",
            "惊讶": "surprise",
            "害怕": "fear",
        }
        
        for keyword, emotion in emotion_map.items():
            if keyword in text:
                return emotion
        
        return "neutral"
    
    def _extract_actions(self, text: str) -> List[str]:
        """
        从文本中提取动作
        
        Args:
            text: 文本内容
            
        Returns:
            动作列表
        """
        actions = []
        
        # 简单的动作提取逻辑（括号内的内容）
        import re
        action_pattern = r'[（(]([^)）]+)[)）]'
        matches = re.findall(action_pattern, text)
        
        for match in matches:
            if any(keyword in match for keyword in ["动作", "表情", "微笑", "点头", "摇头"]):
                actions.append(match)
        
        return actions
    
    def clear_history(self):
        """清空对话历史"""
        self._message_history.clear()
        logger.debug("Cleared chat history")
    
    def get_history(self) -> List[Message]:
        """获取对话历史"""
        return self._message_history.copy()
    
    def set_history(self, history: List[Message]):
        """设置对话历史"""
        self._message_history = history.copy()
