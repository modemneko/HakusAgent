"""OpenAI 兼容 Client — 覆盖大部分 Provider.

适用于: DeepSeek, Qwen, GLM, MiMo, Ollama, Gemini(OpenAI端点)
所有这些 Provider 都通过 openai.AsyncOpenAI SDK 调用。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Sequence

import openai

from .base_client import BaseLLMClient, LLMMessage, LLMResponse, ModelConfig

logger = logging.getLogger(__name__)


class OpenAICompatibleClient(BaseLLMClient):
    """通用的 OpenAI 兼容客户端.

    封装 openai.AsyncOpenAI，提供统一的 chat() 接口。
    同时暴露 get_openai_client() 以支持 agent.py 的
    thread isolation 优化路径。
    """

    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self._client = openai.AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )

    def get_openai_client(self):
        """返回底层 openai.AsyncOpenAI 实例."""
        return self._client

    async def chat(
        self,
        messages: Sequence[LLMMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[float] = None,
    ) -> LLMResponse:
        """调用 LLM，返回结构化响应."""
        oa_messages = [self._to_oa(m) for m in messages]

        kwargs: Dict[str, Any] = {
            "model": self._model_name,
            "messages": oa_messages,
        }
        if tools:
            kwargs["tools"] = tools

        try:
            if timeout and timeout > 0:
                response = await asyncio.wait_for(
                    self._client.chat.completions.create(**kwargs),
                    timeout=timeout,
                )
            else:
                response = await self._client.chat.completions.create(**kwargs)
        except asyncio.TimeoutError:
            logger.error(f"LLM call timed out after {timeout:.1f}s")
            return LLMResponse(
                content=f"[Error: 模型调用超时 ({timeout:.0f}秒). 可能是网络问题, 请重试.]",
                finish_reason="timeout",
            )
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return LLMResponse(
                content=f"Error: {type(e).__name__}: {e}",
                finish_reason="error",
            )

        return self._parse_response(response)

    async def generate_response_no_tools(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        max_tokens: int = 4096,
    ) -> str:
        """Call the model without tools. Returns content string only.

        This is the interface used by GuardianAI for LLM-level approval.
        The Guardian needs a simple text-in/text-out call without
        function calling or streaming.
        """
        oa_messages: List[Dict[str, Any]] = []
        if system_prompt:
            oa_messages.append({"role": "system", "content": system_prompt})
        for msg in messages:
            oa_messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
            })

        try:
            response = await self._client.chat.completions.create(
                model=self._model_name,
                messages=oa_messages,
                max_tokens=max_tokens,
                temperature=0.2,  # Low temperature for consistent Guardian decisions
            )
            if response.choices:
                message = response.choices[0].message
                # Primary: content field
                content = message.content or ""
                # Fallback for reasoning models (mimo, deepseek-r1, etc.)
                # that return content=null with reasoning_content
                if not content:
                    reasoning = getattr(message, 'reasoning_content', None) or ""
                    if reasoning:
                        # Try to extract JSON verdict from reasoning
                        import re as _re
                        json_match = _re.search(r'\{[^{}]*"verdict"[^{}]*\}', reasoning)
                        if json_match:
                            content = json_match.group(0)
                        else:
                            # Use reasoning as content (Guardian will parse it)
                            content = reasoning
                return content
            return ""
        except Exception as e:
            logger.error(f"generate_response_no_tools failed: {e}")
            raise

    @staticmethod
    def _to_oa(msg: LLMMessage) -> Dict[str, Any]:
        """将 LLMMessage 转换为 OpenAI API 消息格式."""
        m: Dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.tool_call_id:
            m["tool_call_id"] = msg.tool_call_id
        if msg.tool_calls is not None:
            m["tool_calls"] = msg.tool_calls
        # 保留 name 字段 (tool 消息需要)
        if hasattr(msg, "name") and msg.name:
            m["name"] = msg.name
        return m

    @staticmethod
    def _parse_response(response) -> LLMResponse:
        """解析 OpenAI API 响应为 LLMResponse."""
        content = ""
        tool_calls: List[Dict[str, Any]] = []
        finish_reason = ""

        if response.choices:
            choice = response.choices[0]
            message = choice.message
            content = message.content or ""
            finish_reason = choice.finish_reason or ""
            if message.tool_calls:
                for tc in message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    except json.JSONDecodeError:
                        args = {}
                    tool_calls.append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": args,
                    })

        usage = response.usage
        # DeepSeek KV cache stats — prompt_cache_hit_tokens / prompt_cache_miss_tokens
        # are DeepSeek-specific fields in usage. They're absent (or 0) on other
        # providers, so getattr with a 0 default is safe.
        cache_hit = 0
        cache_miss = 0
        if usage is not None:
            cache_hit = getattr(usage, "prompt_cache_hit_tokens", 0) or 0
            cache_miss = getattr(usage, "prompt_cache_miss_tokens", 0) or 0
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            cache_hit_tokens=cache_hit,
            cache_miss_tokens=cache_miss,
        )
