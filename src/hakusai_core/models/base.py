"""
HakusAI 2.0 AI模型适配器基类
定义统一的模型接口
"""

from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class MessageRole(str, Enum):
    """消息角色"""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class Message:
    """对话消息"""
    role: MessageRole
    content: str
    name: Optional[str] = None
    tool_calls: Optional[List[Dict]] = None
    tool_call_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        result = {
            "role": self.role.value,
            "content": self.content,
        }
        if self.name:
            result["name"] = self.name
        if self.tool_calls:
            result["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        return result


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    parameters: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为OpenAI格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }


@dataclass
class ChatOptions:
    """聊天选项"""
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    stream: bool = True
    tools: Optional[List[ToolDefinition]] = None
    tool_choice: Optional[str] = None


@dataclass
class ChatResponse:
    """聊天响应"""
    content: str
    tool_calls: Optional[List[Dict]] = None
    usage: Optional[Dict[str, int]] = None
    model: Optional[str] = None
    finish_reason: Optional[str] = None


class BaseModelAdapter(ABC):
    """
    AI模型适配器基类
    
    所有模型适配器必须继承此类并实现抽象方法
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化适配器
        
        Args:
            config: 模型配置字典
        """
        self.config = config
        self.model_name = config.get("model_name", "unknown")
        self.api_key = config.get("api_key")
        self.base_url = config.get("base_url")
        self.temperature = config.get("temperature", 0.7)
        self.max_tokens = config.get("max_tokens", 2048)
        self.timeout = config.get("timeout", 60)
        
        self._client = None
        
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """提供商名称"""
        pass
    
    @abstractmethod
    async def initialize(self):
        """初始化模型客户端"""
        pass
    
    @abstractmethod
    async def chat(
        self,
        messages: List[Message],
        options: Optional[ChatOptions] = None
    ) -> ChatResponse:
        """
        非流式对话
        
        Args:
            messages: 消息列表
            options: 聊天选项
            
        Returns:
            聊天响应
        """
        pass
    
    @abstractmethod
    async def chat_stream(
        self,
        messages: List[Message],
        options: Optional[ChatOptions] = None
    ) -> AsyncIterator[str]:
        """
        流式对话
        
        Args:
            messages: 消息列表
            options: 聊天选项
            
        Yields:
            生成的文本片段
        """
        pass
    
    async def close(self):
        """关闭客户端连接"""
        if self._client:
            await self._client.close()
    
    def supports_tools(self) -> bool:
        """是否支持工具调用"""
        return False
    
    def supports_vision(self) -> bool:
        """是否支持视觉输入"""
        return False
    
    def supports_streaming(self) -> bool:
        """是否支持流式输出"""
        return True
    
    def format_messages(self, messages: List[Message]) -> List[Dict[str, Any]]:
        """
        格式化消息列表
        
        Args:
            messages: 消息列表
            
        Returns:
            格式化后的消息列表
        """
        return [msg.to_dict() for msg in messages]
    
    def format_tools(self, tools: List[ToolDefinition]) -> List[Dict[str, Any]]:
        """
        格式化工具定义
        
        Args:
            tools: 工具定义列表
            
        Returns:
            格式化后的工具列表
        """
        return [tool.to_dict() for tool in tools]


class ModelRegistry:
    """
    模型适配器注册表 - 单例模式
    """
    _instance: Optional['ModelRegistry'] = None
    _adapters: Dict[str, type] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def register(self, provider: str, adapter_class: type):
        """
        注册模型适配器
        
        Args:
            provider: 提供商名称
            adapter_class: 适配器类
        """
        if not issubclass(adapter_class, BaseModelAdapter):
            raise ValueError(f"Adapter class must inherit from BaseModelAdapter")
        self._adapters[provider] = adapter_class
        logger.debug(f"Registered model adapter: {provider}")
    
    def get_adapter(self, provider: str) -> Optional[type]:
        """
        获取模型适配器类
        
        Args:
            provider: 提供商名称
            
        Returns:
            适配器类或None
        """
        return self._adapters.get(provider)
    
    def create_adapter(self, provider: str, config: Dict[str, Any]) -> BaseModelAdapter:
        """
        创建模型适配器实例
        
        Args:
            provider: 提供商名称
            config: 配置字典
            
        Returns:
            适配器实例
        """
        adapter_class = self.get_adapter(provider)
        if adapter_class is None:
            raise ValueError(f"Unknown model provider: {provider}")
        return adapter_class(config)
    
    def list_providers(self) -> List[str]:
        """列出所有已注册的提供商"""
        return list(self._adapters.keys())


# 全局注册表实例
model_registry = ModelRegistry()


def register_model(provider: str):
    """
    模型适配器注册装饰器
    
    用法:
        @register_model("deepseek")
        class DeepSeekAdapter(BaseModelAdapter):
            ...
    """
    def decorator(cls: type):
        model_registry.register(provider, cls)
        return cls
    return decorator
