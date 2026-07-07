"""LiteLLM 客户端（可选依赖）.

通过 pip install litellm 启用后，支持 100+ 额外模型商:
  Groq, Together AI, Mistral, Cohere, Fireworks, Perplexity,
  Voyage, Replicate, HuggingFace, 等等

用法:
  1. pip install litellm
  2. 在 config.yaml 中设置 models.custom.base_url 和 api_key
     （或使用任何 litellm 支持的 provider 前缀）

无需 litellm 时: 此模块导入安全，create_client("litellm") 会优雅降级.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from .base_client import BaseLLMClient, LLMMessage, LLMProvider, LLMResponse, ModelConfig

logger = logging.getLogger(__name__)

# 检测 litellm 是否可用
try:
    import litellm
    _LITELLM_AVAILABLE = True
except ImportError:
    _LITELLM_AVAILABLE = False


class LitellmClient(BaseLLMClient):
    """LiteLLM 统一客户端 — 覆盖 100+ 提供商.

    使用方式:
      config.yaml:
        models:
          default_model: litellm
          litellm:
            model_name: "groq/llama3-70b-8192"
            base_url: ""  # litellm 自动路由
            api_key: "gsk_..."
            # 或使用 openai 兼容格式:
            # model_name: "openai/gpt-4o"
            # base_url: "https://api.openai.com/v1"
    """

    def __init__(self):
        if not _LITELLM_AVAILABLE:
            raise ImportError(
                "litellm 未安装。运行: pip install litellm\n"
                "或使用 'custom' 类型对接 OpenAI 兼容 API。"
            )
        from utils.hakus_config import get_config
        from utils.config import BASE_CONFIG

        config = get_config()
        prov = getattr(config.models, 'litellm', None)

        model_name = prov.model_name if prov else BASE_CONFIG.get("CUSTOM_MODEL_NAME", "")
        api_key = prov.api_key if prov else BASE_CONFIG.get("CUSTOM_API_KEY", "")
        base_url = prov.base_url if prov else BASE_CONFIG.get("CUSTOM_BASE_URL", "")

        super().__init__(ModelConfig(
            provider=LLMProvider.OPENAI,  # litellm 用 openai 兼容格式
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
        ))

        # 配置 litellm
        if api_key:
            litellm.api_key = api_key
        self._model = model_name

    async def chat(
        self,
        messages: Sequence[LLMMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[float] = None,
    ) -> LLMResponse:
        import asyncio

        oa_messages = [self._to_oa(m) for m in messages]
        kwargs: Dict[str, Any] = {
            "model": self._model,
            "messages": oa_messages,
        }
        if tools:
            kwargs["tools"] = tools

        try:
            if timeout and timeout > 0:
                response = await asyncio.wait_for(
                    litellm.acompletion(**kwargs),
                    timeout=timeout,
                )
            else:
                response = await litellm.acompletion(**kwargs)
        except asyncio.TimeoutError:
            return LLMResponse(
                content=f"[Error: 超时 ({timeout:.0f}s)]",
                finish_reason="timeout",
            )
        except Exception as e:
            logger.error(f"LiteLLM call failed: {e}")
            return LLMResponse(content=f"Error: {type(e).__name__}: {e}", finish_reason="error")

        return self._parse_litellm_response(response)

    @staticmethod
    def _to_oa(msg: LLMMessage) -> Dict[str, Any]:
        m: Dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.tool_call_id:
            m["tool_call_id"] = msg.tool_call_id
        if msg.tool_calls is not None:
            m["tool_calls"] = msg.tool_calls
        return m

    @staticmethod
    def _parse_litellm_response(response) -> LLMResponse:
        import json

        content = ""
        tool_calls: List[Dict[str, Any]] = []
        finish_reason = ""

        try:
            choice = response.choices[0]
            message = choice.message
            content = message.content or ""
            finish_reason = choice.finish_reason or ""
            if hasattr(message, 'tool_calls') and message.tool_calls:
                for tc in message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    except (json.JSONDecodeError, AttributeError):
                        args = {}
                    tool_calls.append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": args,
                    })
        except (AttributeError, IndexError, TypeError):
            pass

        usage = getattr(response, 'usage', None)
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            input_tokens=getattr(usage, 'prompt_tokens', 0) if usage else 0,
            output_tokens=getattr(usage, 'completion_tokens', 0) if usage else 0,
        )


def is_litellm_available() -> bool:
    """检查 litellm 是否已安装."""
    return _LITELLM_AVAILABLE
