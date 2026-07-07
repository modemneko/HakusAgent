"""
HakusAI 2.0 Agent模块

提供AI对话能力：
- BaseAgent: 基础对话Agent
- VoiceAgent: 语音对话Agent（整合语音管道和记忆系统）
"""

from .base_agent import (
    BaseAgent,
    AgentContext,
    AgentResponse,
    AgentState,
)
from .voice_agent import (
    VoiceAgent,
    VoiceAgentConfig,
)

__all__ = [
    # 基础Agent
    "BaseAgent",
    "AgentContext",
    "AgentResponse",
    "AgentState",
    # 语音Agent
    "VoiceAgent",
    "VoiceAgentConfig",
]
