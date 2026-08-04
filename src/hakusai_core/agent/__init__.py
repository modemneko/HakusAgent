"""
HakusAI 2.0 Agent模块

提供AI对话能力：
- BaseAgent: 基础对话Agent
- VoiceAgent: 语音通话专用Agent（轻量级，通过AgentBridge共享状态）
"""

from .base_agent import (
    BaseAgent,
    AgentContext,
    AgentResponse,
    AgentState,
)
from .voice_agent import (
    VoiceAgent,
    DEFAULT_VOICE_SYSTEM_PROMPT,
)

__all__ = [
    # 基础Agent
    "BaseAgent",
    "AgentContext",
    "AgentResponse",
    "AgentState",
    # 语音Agent
    "VoiceAgent",
    "DEFAULT_VOICE_SYSTEM_PROMPT",
]
