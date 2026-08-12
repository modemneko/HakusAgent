"""OpenAI 官方客户端.

基于 OpenAICompatibleClient，对接 OpenAI GPT-4o / o3 系列 API.
"""
from __future__ import annotations

from .base_client import LLMProvider, ModelConfig
from .openai_compatible_client import OpenAICompatibleClient


class OpenAIClient(OpenAICompatibleClient):
    """OpenAI 官方 API 客户端."""

    def __init__(self):
        from utils.hakus_config import get_config
        config = get_config()
        prov = config.models.openai
        super().__init__(ModelConfig(
            provider=LLMProvider.OPENAI,
            api_key=prov.api_key,
            base_url=prov.base_url,
            model_name=prov.model_name,
        ))
