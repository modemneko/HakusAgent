"""DeepSeek 模型客户端."""
from __future__ import annotations

from .base_client import LLMProvider, ModelConfig
from .openai_compatible_client import OpenAICompatibleClient


class DeepSeekClient(OpenAICompatibleClient):
    """DeepSeek 模型客户端.

    优先从 HakusConfig 获取配置，回退到 BASE_CONFIG。
    """

    def __init__(self):
        from utils.hakus_config import get_config
        config = get_config()
        prov = config.models.deepseek
        super().__init__(ModelConfig(
            provider=LLMProvider.DEEPSEEK,
            api_key=prov.api_key,
            base_url=prov.base_url,
            model_name=prov.model_name,
        ))
