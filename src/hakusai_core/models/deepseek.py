"""
HakusAI 2.0 DeepSeek 模型适配器
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


@register_model("deepseek")
class DeepSeekAdapter(BaseModelAdapter):
    """
    DeepSeek 模型适配器
    
    支持模型：
    - deepseek-chat
    - deepseek-reasoner
    - deepseek-coder
    """
    
    DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get("base_url") or self.DEFAULT_BASE_URL
        
    @property
    def provider_name(self) -> str:
        return "deepseek"
    
    async def initialize(self):
        """初始化DeepSeek客户端"""
        if not self.api_key:
            raise ValueError("DeepSeek API key is required")
        logger.info(f"DeepSeek adapter initialized with model: {self.model_name}")
    
    async def chat(
        self,
        messages: List[Message],
        options: Optional[ChatOptions] = None
    ) -> ChatResponse:
        """
        非流式对话
        """
        if options is None:
            options = ChatOptions()
        
        # 构建请求体
        payload = {
            "model": self.model_name,
            "messages": self.format_messages(messages),
            "temperature": options.temperature or self.temperature,
            "max_tokens": options.max_tokens or self.max_tokens,
            "stream": False,
        }
        
        # 添加工具调用
        if options.tools:
            payload["tools"] = self.format_tools(options.tools)
        if options.tool_choice:
            payload["tool_choice"] = options.tool_choice
        
        # 在后台线程中执行同步HTTP请求
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, self._sync_chat, payload)
        
        choice = data["choices"][0]
        message = choice["message"]
        
        return ChatResponse(
            content=message.get("content", ""),
            tool_calls=message.get("tool_calls"),
            usage=data.get("usage"),
            model=data.get("model"),
            finish_reason=choice.get("finish_reason"),
        )
    
    def _sync_chat(self, payload: Dict) -> Dict:
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
        """
        流式对话
        """
        if options is None:
            options = ChatOptions()
        
        # 构建请求体
        payload = {
            "model": self.model_name,
            "messages": self.format_messages(messages),
            "temperature": options.temperature or self.temperature,
            "max_tokens": options.max_tokens or self.max_tokens,
            "stream": True,
        }
        
        # 添加工具调用
        if options.tools:
            payload["tools"] = self.format_tools(options.tools)
        
        # 在后台线程中执行
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
        
        # 启动后台线程
        import threading
        thread = threading.Thread(target=stream_worker)
        thread.start()
        
        # 从队列中读取数据
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
        """DeepSeek支持工具调用"""
        return True
    
    def supports_streaming(self) -> bool:
        """DeepSeek支持流式输出"""
        return True
