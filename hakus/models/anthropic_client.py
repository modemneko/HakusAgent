"""Anthropic (Claude) 客户端.

基于 OpenAICompatibleClient，通过 Anthropic 的 OpenAI 兼容端点调用.
Anthropic 原生 API 格式不同，但官方提供了 OpenAI 兼容端点.
"""
from __future__ import annotations

from .base_client import LLMProvider, ModelConfig
from .openai_compatible_client import OpenAICompatibleClient


class AnthropicClient(OpenAICompatibleClient):
    """Anthropic Claude 客户端.

    使用 Anthropic 官方 OpenAI 兼容端点:
      https://docs.anthropic.com/en/api/openai-sdk
    """

    def __init__(self):
        from utils.hakus_config import get_config
        config = get_config()
        prov = config.models.anthropic if hasattr(config.models, 'anthropic') else None

        # 回退到 BASE_CONFIG
        from utils.config import BASE_CONFIG
        api_key = prov.api_key if prov else BASE_CONFIG.get("ANTHROPIC_API_KEY", "")
        base_url = prov.base_url if prov else "https://api.anthropic.com"
        model_name = prov.model_name if prov else "claude-sonnet-4-20250514"

        super().__init__(ModelConfig(
            provider=LLMProvider.ANTHROPIC,
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
        ))
