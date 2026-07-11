"""OpenCode Zen Client — OpenAI 兼容端点.

OpenCode Zen API: https://opencode.ai/zen/v1/chat/completions
直接使用 OpenAICompatibleClient，仅固定 provider 为 OPENCODE.
"""
from __future__ import annotations

from .base_client import LLMProvider, ModelConfig
from .openai_compatible_client import OpenAICompatibleClient


class OpenCodeClient(OpenAICompatibleClient):
    """OpenCode Zen 模型客户端 (OpenAI 兼容)."""

    def __init__(self):
        from utils.hakus_config import get_config
        config = get_config()
        prov = config.models.opencode
        super().__init__(ModelConfig(
            provider=LLMProvider.OPENCODE,
            api_key=prov.api_key,
            base_url=prov.base_url,
            model_name=prov.model_name,
        ))
