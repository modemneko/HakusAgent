"""LLM Client 抽象层 — 借鉴 trae-agent BaseLLMClient 设计.

定义:
- LLMProvider 枚举: 所有支持的 LLM 提供商
- LLMMessage / LLMResponse 数据类: 标准化消息和响应格式
- ModelConfig: 单个模型配置
- BaseLLMClient(ABC): 统一调用接口
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence


class LLMProvider(Enum):
    """支持的 LLM 提供商枚举."""
    DEEPSEEK = "deepseek"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    QWEN = "qwen"
    GEMINI = "gemini"
    GLM = "glm"
    MIMO = "mimo"
    OLLAMA = "ollama"
    OPENCODE = "opencode"


@dataclass
class LLMMessage:
    """标准化消息格式 (trae-agent LLMMessage 风格)."""
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None


@dataclass
class LLMResponse:
    """标准化响应格式 (trae-agent LLMResponse 风格)."""
    content: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    finish_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class ModelConfig:
    """单个模型配置."""
    provider: LLMProvider
    api_key: str
    base_url: str
    model_name: str
    timeout: float = 60.0


class BaseLLMClient(ABC):
    """LLM Client 抽象基类.

    借鉴 trae-agent 的 BaseLLMClient(ABC)，定义统一的调用接口。
    每个 Provider 实现自己的 chat()/stream_chat() 方法。
    """

    def __init__(self, config: ModelConfig):
        self.config = config
        self._provider = config.provider
        self._model_name = config.model_name

    @property
    def provider(self) -> LLMProvider:
        return self._provider

    @property
    def model_name(self) -> str:
        return self._model_name

    @abstractmethod
    async def chat(
        self,
        messages: Sequence[LLMMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[float] = None,
    ) -> LLMResponse:
        """调用 LLM，返回结构化响应."""

    async def stream_chat(
        self,
        messages: Sequence[LLMMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[str]:
        """流式调用 LLM（默认实现：回退到 chat()）.

        子类可覆写以支持真正的 SSE 流式。
        """
        response = await self.chat(messages, tools)
        yield response.content

    def supports_tool_calling(self) -> bool:
        """此 Provider 是否支持 function calling."""
        return True

    def get_openai_client(self):
        """返回底层 OpenAI 兼容客户端（如有）.

        用于 agent.py 中需要直连 client 的场景（如 thread isolation）。
        返回 None 表示非 OpenAI 兼容。
        """
        return None
