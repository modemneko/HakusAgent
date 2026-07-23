"""
HakusAI 2.0 AI模型适配器模块

支持的模型提供商：
- DeepSeek: DeepSeek-V3, DeepSeek-R1
- Gemini: Google Gemini系列
- Qwen: 阿里通义千问
- GLM: 智谱AI GLM系列
- OpenAI: GPT系列
- Ollama: 本地模型
"""

from .base import (
    BaseModelAdapter,
    Message,
    MessageRole,
    ChatOptions,
    ChatResponse,
    ToolDefinition,
    ModelRegistry,
    model_registry,
    register_model,
)

# 导入并注册所有模型适配器
try:
    from .deepseek import DeepSeekAdapter
except ImportError as e:
    import logging
    logging.getLogger(__name__).debug(f"DeepSeek adapter not available: {e}")

try:
    from .gemini import GeminiAdapter
except ImportError as e:
    import logging
    logging.getLogger(__name__).debug(f"Gemini adapter not available: {e}")

try:
    from .openai_compatible import (
        OpenAIAdapter,
        QwenAdapter,
        GLMAdapter,
        OllamaAdapter,
        OpenCodeAdapter,
    )
except ImportError as e:
    import logging
    logging.getLogger(__name__).debug(f"OpenAI compatible adapters not available: {e}")


__all__ = [
    # 基类
    "BaseModelAdapter",
    "Message",
    "MessageRole",
    "ChatOptions",
    "ChatResponse",
    "ToolDefinition",
    "ModelRegistry",
    "model_registry",
    "register_model",
    # 适配器
    "DeepSeekAdapter",
    "GeminiAdapter",
    "OpenAIAdapter",
    "QwenAdapter",
    "GLMAdapter",
    "OllamaAdapter",
    "OpenCodeAdapter",
]
