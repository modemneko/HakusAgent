"""Xiaomi MiMo 模型客户端."""
from __future__ import annotations

from .base_client import LLMProvider, ModelConfig
from .openai_compatible_client import OpenAICompatibleClient


class MiMoClient(OpenAICompatibleClient):
    """Xiaomi MiMo 模型客户端."""

    def __init__(self):
        from utils.hakus_config import get_config
        config = get_config()
        prov = config.models.mimo
        super().__init__(ModelConfig(
            provider=LLMProvider.MIMO,
            api_key=prov.api_key,
            base_url=prov.base_url,
            model_name=prov.model_name,
        ))
