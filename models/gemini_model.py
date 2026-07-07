"""Gemini (Google) 模型封装（单例模式）"""
from __future__ import annotations

import threading
from typing import Any

import openai

from utils.config import BASE_CONFIG
from utils.logger import get_logger

logger = get_logger(__name__)

_GLOBAL_INSTANCE: GeminiModel | None = None
_LOCK = threading.Lock()


class GeminiModel:
    """Gemini (Google) 模型封装类（单例模式）

    提供 openai.AsyncOpenAI 客户端，供 AgentCore._call_model_via_client 使用。
    """

    def __new__(cls) -> GeminiModel:
        global _GLOBAL_INSTANCE
        if _GLOBAL_INSTANCE is not None:
            return _GLOBAL_INSTANCE
        with _LOCK:
            if _GLOBAL_INSTANCE is None:
                instance = super().__new__(cls)
                instance.base_url = BASE_CONFIG.get(
                    "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"
                )
                instance.model_name = BASE_CONFIG.get(
                    "GEMINI_MODEL_NAME", "gemini-2.5-flash"
                )
                api_key = BASE_CONFIG.get("GEMINI_API_KEY", "")
                if not api_key:
                    raise ValueError("GEMINI_API_KEY not configured")
                instance.api_key = api_key
                instance.client = openai.AsyncOpenAI(
                    api_key=instance.api_key,
                    base_url=instance.base_url,
                )
                _GLOBAL_INSTANCE = instance
                logger.info(
                    f"GeminiModel initialized: {instance.model_name} @ {instance.base_url}"
                )
        return _GLOBAL_INSTANCE
