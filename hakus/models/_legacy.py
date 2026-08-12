"""Legacy model adapter module — preserved for backward compatibility.

Original single-file implementation before refactoring to package structure.
All public names are re-exported via __init__.py so existing imports
(from hakus.models import DeepSeekModel, etc.) continue to work.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import openai

from utils.config import BASE_CONFIG

logger = logging.getLogger(__name__)


class _BaseModel:
    """Shared logic for all OpenAI-compatible model adapters."""

    def __init__(self, api_key: str, base_url: str, model_name: str):
        if not api_key:
            raise ValueError(f"API key is empty for {self.__class__.__name__}")
        self.client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model_name = model_name

    async def generate_response(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """Call the model with optional tool support.

        Returns (content, tool_calls_list) where tool_calls_list is a
        list of ``{id, name, arguments}`` dicts.
        """
        full_messages: List[Dict[str, Any]] = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        kwargs: Dict[str, Any] = {
            "model": self.model_name,
            "messages": full_messages,
        }
        if tools:
            kwargs["tools"] = tools

        response = await self.client.chat.completions.create(**kwargs)

        content = ""
        tool_calls_list: List[Dict[str, Any]] = []
        if response.choices:
            message = response.choices[0].message
            content = message.content or ""
            if message.tool_calls:
                for tc in message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    except json.JSONDecodeError:
                        args = {}
                    tool_calls_list.append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": args,
                    })

        return content, tool_calls_list

    async def generate_response_no_tools(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
    ) -> str:
        """Call the model without tools. Returns content string only."""
        content, _ = await self.generate_response(system_prompt, messages, tools=None)
        return content


class DeepSeekModel(_BaseModel):
    """DeepSeek model adapter."""

    def __init__(self):
        super().__init__(
            api_key=BASE_CONFIG["DEEPSEEK_API_KEY"],
            base_url=BASE_CONFIG["DEEPSEEK_BASE_URL"],
            model_name=BASE_CONFIG["DEEPSEEK_MODEL_NAME"],
        )


class QwenModel(_BaseModel):
    """Qwen (DashScope) model adapter."""

    def __init__(self):
        super().__init__(
            api_key=BASE_CONFIG["DASHSCOPE_API_KEY"],
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model_name=BASE_CONFIG["QWEN_MODEL_NAME"],
        )


class GeminiModel(_BaseModel):
    """Google Gemini model adapter (OpenAI-compatible endpoint)."""

    def __init__(self):
        super().__init__(
            api_key=BASE_CONFIG["GEMINI_API_KEY"],
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            model_name=BASE_CONFIG["GEMINI_MODEL_NAME"],
        )


class GLMModel(_BaseModel):
    """Zhipu GLM model adapter."""

    def __init__(self):
        super().__init__(
            api_key=BASE_CONFIG["GLM_API_KEY"],
            base_url="https://open.bigmodel.cn/api/paas/v4/",
            model_name=BASE_CONFIG["GLM_MODEL_NAME"],
        )


class MiMoModel(_BaseModel):
    """Xiaomi MiMo model adapter."""

    def __init__(self):
        super().__init__(
            api_key=BASE_CONFIG["MIMO_API_KEY"],
            base_url=BASE_CONFIG["MIMO_BASE_URL"],
            model_name=BASE_CONFIG["MIMO_MODEL_NAME"],
        )


class OllamaModel(_BaseModel):
    """Ollama local model adapter."""

    def __init__(self):
        super().__init__(
            api_key="ollama",  # Ollama doesn't require a real API key
            base_url=BASE_CONFIG["OLLAMA_BASE_URL"],
            model_name=BASE_CONFIG["OLLAMA_MODEL_NAME"],
        )
