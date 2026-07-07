"""Zhipu GLM 模型客户端."""
from __future__ import annotations

from .base_client import LLMProvider, ModelConfig
from .openai_compatible_client import OpenAICompatibleClient


class GLMClient(OpenAICompatibleClient):
    """Zhipu GLM 模型客户端."""

    def __init__(self):
        from utils.hakus_config import get_config
        config = get_config()
        prov = config.models.glm
        super().__init__(ModelConfig(
            provider=LLMProvider.GLM,
            api_key=prov.api_key,
            base_url=prov.base_url,
            model_name=prov.model_name,
        ))
