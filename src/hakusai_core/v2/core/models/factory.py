"""
LLM 客户端工厂 - 负责创建不同提供商的客户端
"""

from typing import Optional
from .base import LLMClient
from .openai import OpenAIClient


class ClientFactory:
    """客户端工厂"""
    
    _clients = {
        "openai": OpenAIClient,
        "deepseek": OpenAIClient,  # DeepSeek 兼容 OpenAI API
        "qwen": OpenAIClient,  # 通义千问兼容 OpenAI API
        "glm": OpenAIClient,  # 智谱兼容 OpenAI API
    }
    
    @classmethod
    def create(
        cls,
        provider: str,
        api_key: str,
        base_url: Optional[str] = None,
        **kwargs,
    ) -> LLMClient:
        """创建客户端"""
        client_class = cls._clients.get(provider)
        if not client_class:
            raise ValueError(f"Unsupported provider: {provider}")
        
        # 设置默认 base_url
        if base_url is None:
            base_url = cls._get_default_base_url(provider)
        
        return client_class(
            api_key=api_key,
            base_url=base_url,
            **kwargs,
        )
    
    @classmethod
    def _get_default_base_url(cls, provider: str) -> str:
        """获取默认 base_url"""
        defaults = {
            "openai": "https://api.openai.com/v1",
            "deepseek": "https://api.deepseek.com/v1",
            "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "glm": "https://open.bigmodel.cn/api/paas/v4",
        }
        return defaults.get(provider, "https://api.openai.com/v1")
    
    @classmethod
    def register(cls, name: str, client_class: type):
        """注册客户端"""
        cls._clients[name] = client_class
    
    @classmethod
    def list_providers(cls) -> list[str]:
        """列出所有支持的提供商"""
        return list(cls._clients.keys())