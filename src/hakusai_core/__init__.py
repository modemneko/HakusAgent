"""
HakusAI 2.0 核心模块

HakusAI是一个AI虚拟助手平台，提供：
- 多模型AI对话（DeepSeek/Gemini/Qwen/GLM/OpenAI）
- 语音识别与合成（ASR/TTS/VAD）
- 虚拟形象（Live2D/VRM）
- 记忆系统（短期/长期记忆）
- 工具调用（MCP）
"""

__version__ = "0.1.0"

# 配置
from .config import config_manager, HakusAIConfig

# 模型
from .models import (
    BaseModelAdapter,
    Message,
    MessageRole,
    ChatOptions,
    ChatResponse,
    model_registry,
)

# Agent
from .agent import (
    BaseAgent,
    VoiceAgent,
    AgentContext,
    AgentResponse,
    AgentState,
)

# 语音
from .voice import (
    VoicePipeline,
    VoicePipelineConfig,
)

# 记忆
from .memory import (
    MemoryManager,
    MemoryEntry,
    MemoryType,
)

# 事件
from .utils.events import EventType, emit, on_event

__all__ = [
    # 版本
    "__version__",
    # 配置
    "config_manager",
    "HakusAIConfig",
    # 模型
    "BaseModelAdapter",
    "Message",
    "MessageRole",
    "ChatOptions",
    "ChatResponse",
    "model_registry",
    # Agent
    "BaseAgent",
    "VoiceAgent",
    "AgentContext",
    "AgentResponse",
    "AgentState",
    # 语音
    "VoicePipeline",
    "VoicePipelineConfig",
    # 记忆
    "MemoryManager",
    "MemoryEntry",
    "MemoryType",
    # 事件
    "EventType",
    "emit",
    "on_event",
]
