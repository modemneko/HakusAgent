"""
HakusAI 2.0 OpenAI兼容模型适配器
支持Qwen、GLM、Ollama等兼容OpenAI API的模型
使用标准库实现
"""

import logging
from typing import AsyncIterator, Dict, List, Optional, Any
import asyncio
import json
import urllib.request
import urllib.error

from .base import (
    BaseModelAdapter,
    Message,
    ChatOptions,
    ChatResponse,
    ToolDefinition,
    register_model,
)

logger = logging.getLogger(__name__)


class OpenAICompatibleAdapter(BaseModelAdapter):
    """
    OpenAI兼容API适配器基类
    
    适用于任何兼容OpenAI API格式的服务
    """
    
    DEFAULT_BASE_URL = "https://api.openai.com/v1"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get("base_url") or self.DEFAULT_BASE_URL
        
    @property
    def provider_name(self) -> str:
        return "openai_compatible"
    
    async def initialize(self):
        """初始化客户端"""
        if not self.api_key:
            raise ValueError(f"API key is required for {self.provider_name}")
        logger.info(f"{self.provider_name} adapter initialized with model: {self.model_name}")
    
    async def chat(
        self,
        messages: List[Message],
        options: Optional[ChatOptions] = None
    ) -> ChatResponse:
        """非流式对话"""
        if options is None:
            options = ChatOptions()
        
        payload = {
            "model": self.model_name,
            "messages": self.format_messages(messages),
            "temperature": options.temperature or self.temperature,
            "max_tokens": options.max_tokens or self.max_tokens,
            "stream": False,
        }
        
        if options.tools:
            payload["tools"] = self.format_tools(options.tools)
        if options.tool_choice:
            payload["tool_choice"] = options.tool_choice
        
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, self._sync_request, payload)
        
        choice = data["choices"][0]
        message = choice["message"]
        
        return ChatResponse(
            content=message.get("content", ""),
            tool_calls=message.get("tool_calls"),
            usage=data.get("usage"),
            model=data.get("model"),
            finish_reason=choice.get("finish_reason"),
        )
    
    def _sync_request(self, payload: Dict) -> Dict:
        """同步HTTP请求"""
        url = f"{self.base_url}/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        data = json.dumps(payload).encode('utf-8')
        
        req = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method='POST'
        )
        
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return json.loads(response.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            logger.error(f"HTTP Error: {e.code}, {error_body}")
            raise
    
    async def chat_stream(
        self,
        messages: List[Message],
        options: Optional[ChatOptions] = None
    ) -> AsyncIterator[str]:
        """流式对话"""
        if options is None:
            options = ChatOptions()
        
        payload = {
            "model": self.model_name,
            "messages": self.format_messages(messages),
            "temperature": options.temperature or self.temperature,
            "max_tokens": options.max_tokens or self.max_tokens,
            "stream": True,
        }
        
        if options.tools:
            payload["tools"] = self.format_tools(options.tools)
        
        loop = asyncio.get_event_loop()
        queue = asyncio.Queue()
        
        def stream_worker():
            try:
                url = f"{self.base_url}/chat/completions"
                
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                }
                
                data = json.dumps(payload).encode('utf-8')
                
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers=headers,
                    method='POST'
                )
                
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    for line in response:
                        line = line.decode('utf-8').strip()
                        if line.startswith("data: "):
                            data_str = line[6:]
                            if data_str == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_str)
                                delta = chunk["choices"][0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    asyncio.run_coroutine_threadsafe(
                                        queue.put(content), loop
                                    )
                            except (json.JSONDecodeError, KeyError):
                                continue
            except Exception as e:
                logger.error(f"Stream error: {e}")
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(None), loop)
        
        import threading
        thread = threading.Thread(target=stream_worker)
        thread.start()
        
        while True:
            content = await queue.get()
            if content is None:
                break
            yield content
        
        thread.join()
    
    async def close(self):
        """关闭客户端"""
        pass
    
    def supports_tools(self) -> bool:
        return True
    
    def supports_streaming(self) -> bool:
        return True


@register_model("qwen")
class QwenAdapter(OpenAICompatibleAdapter):
    """
    阿里云通义千问适配器
    
    支持模型：
    - qwen-turbo
    - qwen-plus
    - qwen-max
    - qwen-coder-plus
    """
    
    DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get("base_url") or self.DEFAULT_BASE_URL
    
    @property
    def provider_name(self) -> str:
        return "qwen"


@register_model("glm")
class GLMAdapter(OpenAICompatibleAdapter):
    """
    智谱AI GLM适配器
    
    支持模型：
    - glm-4
    - glm-4-plus
    - glm-4-air
    - glm-4-flash
    - glm-4v
    """
    
    DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get("base_url") or self.DEFAULT_BASE_URL
    
    @property
    def provider_name(self) -> str:
        return "glm"
    
    def supports_vision(self) -> bool:
        """GLM-4V支持视觉输入"""
        return "v" in self.model_name.lower() or "vision" in self.model_name.lower()


@register_model("ollama")
class OllamaAdapter(OpenAICompatibleAdapter):
    """
    Ollama本地模型适配器
    
    支持所有Ollama托管的模型
    """
    
    DEFAULT_BASE_URL = "http://localhost:11434/v1"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get("base_url") or self.DEFAULT_BASE_URL
        # Ollama通常不需要API key
        if not self.api_key:
            self.api_key = "ollama"
    
    @property
    def provider_name(self) -> str:
        return "ollama"


@register_model("openai")
class OpenAIAdapter(OpenAICompatibleAdapter):
    """
    OpenAI官方适配器
    
    支持模型：
    - gpt-4o
    - gpt-4o-mini
    - gpt-4-turbo
    - gpt-3.5-turbo
    """
    
    DEFAULT_BASE_URL = "https://api.openai.com/v1"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get("base_url") or self.DEFAULT_BASE_URL
    
    @property
    def provider_name(self) -> str:
        return "openai"
    
    def supports_vision(self) -> bool:
        """GPT-4o支持视觉输入"""
        return "vision" in self.model_name.lower() or "gpt-4o" in self.model_name.lower()


@register_model("opencode")
class OpenCodeAdapter(OpenAICompatibleAdapter):
    """
    OpenCode适配器
    
    支持OpenCode平台托管的OpenAI兼容模型
    """
    
    DEFAULT_BASE_URL = "https://api.opencode.ai/v1"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get("base_url") or self.DEFAULT_BASE_URL
    
    @property
    def provider_name(self) -> str:
        return "opencode"
