"""
改进的 LLM 客户端
"""

import asyncio
import time
from typing import Optional, Any, AsyncIterator, Dict
from dataclasses import dataclass
import logging

from .timeout import (
    TimeoutManager,
    TimeoutConfig,
    TimeoutLevel,
    TimeoutError,
    SSEChunkTimeout,
    RetryManager,
)

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """LLM 响应"""
    content: str = ""
    finish_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    provider: str = ""
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class ImprovedLLMClient:
    """改进的 LLM 客户端"""
    
    def __init__(
        self,
        api_key: str,
        base_url: str = "",
        provider: str = "openai",
        timeout_config: Optional[TimeoutConfig] = None,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.provider = provider
        self.timeout_manager = TimeoutManager(timeout_config)
        self.retry_manager = RetryManager(timeout_config)
        self.sse_monitor: Optional[SSEChunkTimeout] = None
    
    async def chat(
        self,
        messages: list[dict],
        model: str = "gpt-4",
        stream: bool = True,
        tools: Optional[list] = None,
        timeout: Optional[float] = None,
        max_retries: int = 3,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        流式对话（带超时和重试）
        
        Args:
            messages: 消息列表
            model: 模型名称
            stream: 是否流式
            tools: 工具定义
            timeout: 超时时间（秒）
            max_retries: 最大重试次数
            
        Yields:
            流式响应块
        """
        timeout = timeout or self.timeout_manager.config.provider_timeout
        
        for attempt in range(1, max_retries + 1):
            try:
                async for chunk in self._stream_with_timeout(
                    messages, model, tools, timeout
                ):
                    yield chunk
                return  # 成功，退出重试循环
                
            except TimeoutError as e:
                logger.warning(f"LLM timeout (attempt {attempt}/{max_retries}): {e}")
                
                if attempt < max_retries:
                    delay = self.retry_manager.calculate_delay(attempt)
                    logger.info(f"Retrying in {delay:.1f}s...")
                    await asyncio.sleep(delay)
                else:
                    raise
                    
            except Exception as e:
                logger.error(f"LLM error (attempt {attempt}/{max_retries}): {e}")
                
                if self.retry_manager.is_retryable(e) and attempt < max_retries:
                    delay = self.retry_manager.calculate_delay(attempt)
                    logger.info(f"Retrying in {delay:.1f}s...")
                    await asyncio.sleep(delay)
                else:
                    raise
    
    async def _stream_with_timeout(
        self,
        messages: list[dict],
        model: str,
        tools: Optional[list],
        timeout: float,
    ) -> AsyncIterator[Dict[str, Any]]:
        """带 SSE chunk 超时的流式处理"""
        self.sse_monitor = SSEChunkTimeout(
            chunk_timeout=self.timeout_manager.config.chunk_timeout
        )
        
        async def on_sse_timeout():
            logger.error("SSE chunk timeout - stream may be stalled")
        
        self.sse_monitor.start(on_timeout=on_sse_timeout)
        
        try:
            # 这里应该调用实际的 LLM API
            # 暂时使用占位符
            import aiohttp
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            
            payload = {
                "model": model,
                "messages": messages,
                "stream": True,
            }
            if tools:
                payload["tools"] = tools
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise Exception(f"API error {response.status}: {error_text}")
                    
                    async for line in response.content:
                        if self.sse_monitor.is_aborted:
                            raise TimeoutError(
                                TimeoutLevel.PROVIDER,
                                self.sse_monitor.chunk_timeout,
                                "SSE stream",
                                "Stream stalled - no chunks received",
                            )
                        
                        line_str = line.decode('utf-8').strip()
                        if not line_str or not line_str.startswith('data: '):
                            continue
                        
                        data = line_str[6:]
                        if data == '[DONE]':
                            break
                        
                        # 更新 SSE chunk 计时器
                        self.sse_monitor.update()
                        
                        try:
                            import json
                            chunk = json.loads(data)
                            yield chunk
                        except json.JSONDecodeError:
                            continue
                            
        finally:
            self.sse_monitor.stop()
    
    async def chat_completion(
        self,
        messages: list[dict],
        model: str = "gpt-4",
        tools: Optional[list] = None,
        timeout: Optional[float] = None,
        max_retries: int = 3,
    ) -> LLMResponse:
        """
        非流式对话（带重试）
        
        Args:
            messages: 消息列表
            model: 模型名称
            tools: 工具定义
            timeout: 超时时间
            max_retries: 最大重试次数
            
        Returns:
            LLMResponse
        """
        timeout = timeout or self.timeout_manager.config.provider_timeout
        
        for attempt in range(1, max_retries + 1):
            try:
                return await self._completion_with_timeout(
                    messages, model, tools, timeout
                )
                
            except TimeoutError as e:
                logger.warning(f"LLM timeout (attempt {attempt}/{max_retries}): {e}")
                
                if attempt < max_retries:
                    delay = self.retry_manager.calculate_delay(attempt)
                    await asyncio.sleep(delay)
                else:
                    raise
                    
            except Exception as e:
                logger.error(f"LLM error (attempt {attempt}/{max_retries}): {e}")
                
                if self.retry_manager.is_retryable(e) and attempt < max_retries:
                    delay = self.retry_manager.calculate_delay(attempt)
                    await asyncio.sleep(delay)
                else:
                    raise
        
        # 不应该到达这里
        raise Exception("Max retries exceeded")
    
    async def _completion_with_timeout(
        self,
        messages: list[dict],
        model: str,
        tools: Optional[list],
        timeout: float,
    ) -> LLMResponse:
        """带超时的非流式请求"""
        import aiohttp
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"API error {response.status}: {error_text}")
                
                result = await response.json()
                
                # 解析 Retry-After header
                retry_after = None
                if "Retry-After" in response.headers:
                    retry_after = self.retry_manager.parse_retry_after(dict(response.headers))
                    if retry_after:
                        logger.info(f"Server requested retry after {retry_after:.1f}s")
                
                choice = result.get("choices", [{}])[0]
                usage = result.get("usage", {})
                
                return LLMResponse(
                    content=choice.get("message", {}).get("content", ""),
                    finish_reason=choice.get("finish_reason", ""),
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    model=result.get("model", model),
                    provider=self.provider,
                    metadata={"retry_after": retry_after},
                )