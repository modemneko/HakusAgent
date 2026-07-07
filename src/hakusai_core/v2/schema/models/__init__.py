"""
核心数据模型 - 借鉴 OpenCode 的 Schema 设计
使用 Pydantic v2 实现运行时验证和类型安全
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class AgentMode(str, Enum):
    """Agent 模式"""
    BUILD = "build"  # 全能开发模式
    PLAN = "plan"    # 规划模式（只读）


class PermissionLevel(str, Enum):
    """权限级别"""
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class PermissionRule(BaseModel):
    """权限规则"""
    tool: str
    level: PermissionLevel
    condition: Optional[str] = None  # 可选条件，如路径匹配


class AgentConfig(BaseModel):
    """Agent 配置"""
    name: str
    mode: AgentMode = AgentMode.BUILD
    permissions: dict[str, PermissionLevel] = Field(default_factory=dict)
    max_iterations: int = 15
    system_prompt: Optional[str] = None


class AgentState(BaseModel):
    """Agent 运行状态"""
    session_id: str
    mode: AgentMode
    step_count: int = 0
    is_running: bool = False
    current_tool: Optional[str] = None
    error_count: int = 0


class Message(BaseModel):
    """消息模型"""
    id: str
    role: str  # "system", "user", "assistant", "tool"
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolDefinition(BaseModel):
    """工具定义"""
    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)
    category: Optional[str] = None


class ToolResult(BaseModel):
    """工具执行结果"""
    success: bool
    output: Any = None
    error: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionConfig(BaseModel):
    """会话配置"""
    project_id: str
    agent_config: AgentConfig
    model_provider: str = "openai"
    model_name: str = "gpt-4"
    created_at: datetime = Field(default_factory=datetime.now)


class SessionState(BaseModel):
    """会话状态"""
    id: str
    config: SessionConfig
    messages: list[Message] = Field(default_factory=list)
    agent_state: AgentState
    is_active: bool = True
    updated_at: datetime = Field(default_factory=datetime.now)


class ModelConfig(BaseModel):
    """模型配置"""
    provider: str
    model: str
    temperature: float = 0.7
    max_tokens: int = 4096
    stream: bool = True


class AudioData(BaseModel):
    """音频数据"""
    data: bytes
    sample_rate: int = 16000
    channels: int = 1
    format: str = "wav"


class Text(BaseModel):
    """文本数据"""
    content: str
    language: str = "zh-CN"


class AvatarState(BaseModel):
    """虚拟形象状态"""
    expression: Optional[str] = None
    motion: Optional[str] = None
    mouth_open: float = 0.0  # 0.0 - 1.0
    timestamp: datetime = Field(default_factory=datetime.now)


class PlatformEvent(BaseModel):
    """平台事件"""
    platform: str  # "bilibili", "discord", "youtube"
    event_type: str  # "message", "gift", "follow"
    user_id: str
    user_name: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    TESTING = "testing"
    COMPLETED = "completed"
    FAILED = "failed"


class Task(BaseModel):
    """任务模型"""
    id: str
    name: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    dependencies: list[str] = Field(default_factory=list)
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ProjectConfig(BaseModel):
    """项目配置"""
    id: str
    name: str
    root_path: str
    created_at: datetime = Field(default_factory=datetime.now)
    metadata: dict[str, Any] = Field(default_factory=dict)