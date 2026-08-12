"""Ollama 本地模型封装（单例模式）"""
from __future__ import annotations

import threading
from typing import Any

import httpx
import openai

from utils.config import BASE_CONFIG
from utils.logger import get_logger

logger = get_logger(__name__)

_GLOBAL_INSTANCE: OllamaModel | None = None
_LOCK = threading.Lock()


class OllamaModel:
    """Ollama 本地模型封装类（单例模式）

    提供 openai.AsyncOpenAI 客户端，供 AgentCore._call_model_via_client 使用。
    Ollama 不需要真实 API Key，使用 "ollama" 作为占位符。
    初始化时会检测 Ollama 服务是否可达。
    """

    def __new__(cls) -> OllamaModel:
        global _GLOBAL_INSTANCE
        if _GLOBAL_INSTANCE is not None:
            return _GLOBAL_INSTANCE
        with _LOCK:
            if _GLOBAL_INSTANCE is None:
                instance = super().__new__(cls)
                instance.base_url = BASE_CONFIG.get(
                    "OLLAMA_BASE_URL", "http://localhost:11434/v1"
                )
                instance.model_name = BASE_CONFIG.get(
                    "OLLAMA_MODEL_NAME", "qwen3:8b"
                )
                instance.api_key = "ollama"

                # 检测 Ollama 服务是否可达
                check_url = instance.base_url.replace("/v1", "")
                try:
                    resp = httpx.get(check_url, timeout=5.0)
                    resp.raise_for_status()
                except Exception:
                    raise ConnectionError(
                        f"Ollama server not running at {check_url} "
                        "Start it with: ollama serve"
                    )

                instance.client = openai.AsyncOpenAI(
                    api_key=instance.api_key,
                    base_url=instance.base_url,
                )
                _GLOBAL_INSTANCE = instance
                logger.info(
                    f"OllamaModel initialized: {instance.model_name} @ {instance.base_url}"
                )
        return _GLOBAL_INSTANCE
