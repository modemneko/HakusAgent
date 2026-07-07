"""
LLM 客户端 - 统一的 LLM 调用接口
"""

from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional
from ...schema.models import Message, ModelConfig


class LLMClient(ABC):
    """LLM 客户端基类"""
    
    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        config: ModelConfig,
    ) -> AsyncIterator[str]:
        """流式对话"""
        pass
    
    @abstractmethod
    async def chat_completion(
        self,
        messages: list[Message],
        config: ModelConfig,
    ) -> str:
        """非流式对话"""
        pass