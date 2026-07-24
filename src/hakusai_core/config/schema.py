"""
HakusAI 2.0 配置模式定义
使用Pydantic进行配置验证

安全说明:
- 默认绑定 127.0.0.1 (仅本地访问)，可通过配置覆盖为 0.0.0.0
- 默认 CORS 仅允许本地开发服务器
- API Key 鉴权默认禁用（空字符串），生产环境必须设置
- 命令执行默认启用白名单模式（空列表=禁止所有命令）
"""

import secrets
from typing import List, Optional, Dict, Any, Literal, Set
from pydantic import BaseModel, Field, field_validator
from enum import Enum


class LogLevel(str, Enum):
    """日志级别"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ModelProvider(str, Enum):
    """AI模型提供商"""
    DEEPSEEK = "deepseek"
    GEMINI = "gemini"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    QWEN = "qwen"
    GLM = "glm"
    OLLAMA = "ollama"
    OPENCODE = "opencode"


class ASRProvider(str, Enum):
    """ASR提供商"""
    SHERPA_ONNX = "sherpa_onnx"
    WHISPER = "whisper"
    FUNASR = "funasr"
    AZURE = "azure"


class TTSProvider(str, Enum):
    """TTS提供商"""
    EDGE = "edge"
    SHERPA_ONNX = "sherpa_onnx"
    COSYVOICE = "cosyvoice"
    GPT_SOVITS = "gpt_sovits"
    ELEVENLABS = "elevenlabs"


class VADProvider(str, Enum):
    """VAD提供商"""
    SILERO = "silero"


class AvatarType(str, Enum):
    """虚拟形象类型"""
    LIVE2D = "live2d"
    VRM = "vrm"
    NONE = "none"


# ==================== 模型配置 ====================

class ModelConfig(BaseModel):
    """AI模型配置"""
    provider: ModelProvider = Field(default=ModelProvider.DEEPSEEK, description="模型提供商")
    model_name: str = Field(default="deepseek-chat", description="模型名称")
    api_key: Optional[str] = Field(default=None, description="API密钥")
    base_url: Optional[str] = Field(default=None, description="自定义API基础URL")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="温度参数")
    max_tokens: int = Field(default=2048, ge=1, description="最大生成token数")
    timeout: int = Field(default=60, ge=1, description="请求超时时间(秒)")


# ==================== 语音配置 ====================

class ASRConfig(BaseModel):
    """语音识别配置"""
    provider: ASRProvider = Field(default=ASRProvider.SHERPA_ONNX, description="ASR提供商")
    model_path: Optional[str] = Field(default=None, description="本地模型路径")
    language: str = Field(default="zh", description="识别语言")
    sample_rate: int = Field(default=16000, description="采样率")
    
    # Sherpa-ONNX特定配置
    sherpa_onnx_model: Optional[str] = Field(default=None, description="Sherpa-ONNX模型路径")
    tokens_path: Optional[str] = Field(default=None, description="tokens文件路径")


class TTSConfig(BaseModel):
    """语音合成配置"""
    provider: TTSProvider = Field(default=TTSProvider.EDGE, description="TTS提供商")
    voice: str = Field(default="zh-CN-XiaoxiaoNeural", description="语音名称")
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="语速")
    volume: float = Field(default=1.0, ge=0.0, le=2.0, description="音量")
    
    # Edge TTS配置
    edge_voice: str = Field(default="zh-CN-XiaoxiaoNeural", description="Edge TTS语音")
    
    # CosyVoice/GPT-SoVITS配置
    reference_audio: Optional[str] = Field(default=None, description="参考音频路径")
    
    # 缓存配置
    cache_enabled: bool = Field(default=True, description="是否启用缓存")
    cache_dir: str = Field(default="data/cache/tts", description="缓存目录")


class VADConfig(BaseModel):
    """语音活动检测配置"""
    provider: VADProvider = Field(default=VADProvider.SILERO, description="VAD提供商")
    threshold: float = Field(default=0.5, ge=0.0, le=1.0, description="检测阈值")
    min_speech_duration_ms: int = Field(default=250, description="最小语音持续时间(ms)")
    min_silence_duration_ms: int = Field(default=500, description="最小静音持续时间(ms)")
    speech_pad_ms: int = Field(default=100, description="语音前后填充(ms)")


class VoiceConfig(BaseModel):
    """语音系统总配置"""
    enabled: bool = Field(default=True, description="是否启用语音")
    asr: ASRConfig = Field(default_factory=ASRConfig, description="ASR配置")
    tts: TTSConfig = Field(default_factory=TTSConfig, description="TTS配置")
    vad: VADConfig = Field(default_factory=VADConfig, description="VAD配置")
    auto_play: bool = Field(default=True, description="是否自动播放TTS")


# ==================== 虚拟形象配置 ====================

class Live2DConfig(BaseModel):
    """Live2D配置"""
    model_path: str = Field(default="models/live2d/shizuku", description="模型路径")
    scale: float = Field(default=1.0, description="缩放比例")
    x: float = Field(default=0.5, ge=0.0, le=1.0, description="X位置(0-1)")
    y: float = Field(default=0.5, ge=0.0, le=1.0, description="Y位置(0-1)")
    auto_blink: bool = Field(default=True, description="自动眨眼")
    auto_breath: bool = Field(default=True, description="自动呼吸")


class VRMConfig(BaseModel):
    """VRM配置"""
    model_path: Optional[str] = Field(default=None, description="VRM模型路径")
    auto_blink: bool = Field(default=True, description="自动眨眼")
    look_at_mouse: bool = Field(default=True, description="注视鼠标")


class LipSyncConfig(BaseModel):
    """嘴型同步配置"""
    enabled: bool = Field(default=True, description="是否启用")
    sensitivity: float = Field(default=1.0, ge=0.1, le=3.0, description="灵敏度")
    smoothing: float = Field(default=0.3, ge=0.0, le=1.0, description="平滑系数")


class AvatarConfig(BaseModel):
    """虚拟形象总配置"""
    enabled: bool = Field(default=True, description="是否启用")
    type: AvatarType = Field(default=AvatarType.LIVE2D, description="形象类型")
    name: str = Field(default="小雪", description="角色名称")
    live2d: Live2DConfig = Field(default_factory=Live2DConfig, description="Live2D配置")
    vrm: VRMConfig = Field(default_factory=VRMConfig, description="VRM配置")
    lip_sync: LipSyncConfig = Field(default_factory=LipSyncConfig, description="嘴型同步配置")


# ==================== 记忆配置 ====================

class MemoryConfig(BaseModel):
    """记忆系统配置"""
    enabled: bool = Field(default=True, description="是否启用")
    short_term_max: int = Field(default=50, ge=10, description="短期记忆最大条数")
    long_term_enabled: bool = Field(default=True, description="是否启用长期记忆")
    vector_db_path: str = Field(default="data/memories/vectors", description="向量数据库路径")
    auto_summary: bool = Field(default=True, description="自动总结")
    summary_interval: int = Field(default=10, ge=5, description="总结间隔(条对话)")


# ==================== 平台配置 ====================

class BilibiliConfig(BaseModel):
    """Bilibili直播配置"""
    enabled: bool = Field(default=False, description="是否启用")
    room_id: Optional[int] = Field(default=None, description="直播间ID")
    sessdata: Optional[str] = Field(default=None, description="SESSDATA Cookie")
    auto_reply: bool = Field(default=True, description="自动回复弹幕")
    reply_rate: float = Field(default=0.5, ge=0.0, le=1.0, description="回复概率")


class DiscordConfig(BaseModel):
    """Discord配置"""
    enabled: bool = Field(default=False, description="是否启用")
    bot_token: Optional[str] = Field(default=None, description="Bot Token")
    guild_id: Optional[str] = Field(default=None, description="服务器ID")
    voice_channel_id: Optional[str] = Field(default=None, description="语音频道ID")


class PlatformConfig(BaseModel):
    """平台总配置"""
    bilibili: BilibiliConfig = Field(default_factory=BilibiliConfig, description="Bilibili配置")
    discord: DiscordConfig = Field(default_factory=DiscordConfig, description="Discord配置")


# ==================== 系统配置 ====================

# ==================== 安全配置 ====================

class SecurityConfig(BaseModel):
    """
    安全配置 - 控制服务器的安全行为
    
    ⚠️ 重要安全提示:
    - host 默认为 127.0.0.1，仅允许本地访问
    - 如需远程访问，请确保设置了 api_key 并配置防火墙
    - cors_origins 使用 ["*"] 时会自动禁用 allow_credentials
    - 生产环境务必设置强密码作为 api_key
    """
    # 绑定地址 - 默认仅本地访问
    host: str = Field(
        default="127.0.0.1",
        description=
        "监听地址。默认 127.0.0.1 (仅本地)。"
        "设为 0.0.0.0 允许所有网卡访问，但需配合 api_key 使用"
    )
    port: int = Field(default=8080, ge=1, le=65535, description="监听端口")
    
    # CORS 配置
    cors_origins: List[str] = Field(
        default=["http://localhost:1421", "http://127.0.0.1:1421"],
        description=
        "CORS 允许的来源列表。默认仅允许本地前端。"
        "使用 [\"*\"] 将自动禁用 credentials (安全限制)"
    )
    cors_allow_credentials: bool = Field(
        default=True,
        description="是否允许 CORS 携带凭证。当 origins 为 [*] 时强制 False"
    )
    
    # API 鉴权配置
    api_key: str = Field(
        default="",
        description=
        "API 密钥。空字符串表示禁用鉴权（仅限开发环境）。"
        "生产环境必须设置。可通过 HAKUSAI_API_KEY 环境变量覆盖"
    )
    api_key_header: str = Field(
        default="X-API-Key",
        description=
        "API Key 的 HTTP 头名称。"
        "使用自定义头避免浏览器拦截 Authorization 头"
    )
    
    # WebSocket 鉴权
    ws_auth_query_param: str = Field(
        default="token",
        description="WebSocket 鉴权的 query parameter 名称"
    )
    ws_auth_enabled: bool = Field(
        default=True,
        description="是否要求 WebSocket 连接携带鉴权 token"
    )
    
    # 命令执行安全
    allow_commands: List[str] = Field(
        default=[],
        description=
        "允许执行的命令白名单（基本命令名）。"
        "空列表表示禁止所有 shell 命令执行。"
        "示例: ['git', 'npm', 'python', 'pip', 'cat', 'ls', 'find']"
    )
    block_commands: List[str] = Field(
        default=[r"rm -rf /", r"mkfs", r"format", r"> /dev/sda", r"curl.*\|.*sh", r"wget.*\|.*sh"],
        description="永远禁止的危险命令模式（正则）"
    )
    require_confirmation_for_shell: bool = Field(
        default=True,
        description="是否需要用户确认才能执行 shell 命令"
    )
    
    # 审计日志
    audit_log_enabled: bool = Field(
        default=True,
        description="是否启用操作审计日志"
    )
    audit_log_path: str = Field(
        default="logs/audit.log",
        description="审计日志文件路径"
    )
    
    # 速率限制
    rate_limit_enabled: bool = Field(
        default=True,
        description="是否启用速率限制"
    )
    rate_limit_requests_per_minute: int = Field(
        default=60,
        ge=1,
        description="每分钟最大请求数"
    )
    
    @field_validator('api_key', mode='before')
    @classmethod
    def resolve_api_key(cls, v: str) -> str:
        """优先从环境变量读取 API Key"""
        if not v or v.strip() == '':
            env_key = os.environ.get('HAKUSAI_API_KEY', '')
            if env_key:
                return env_key
        return v
    
    @field_validator('cors_allow_credentials', mode='after')
    @classmethod
    def validate_cors_credentials(cls, v: bool, info) -> bool:
        """当 allow_origins 为 [*] 时，强制禁用 credentials"""
        # 这个验证会在实例化后由 server.py 再次检查
        return v
    
    def generate_api_key(self) -> str:
        """生成随机 API Key"""
        self.api_key = secrets.token_urlsafe(32)
        return self.api_key
    
    def is_command_allowed(self, command: str) -> tuple[bool, str]:
        """
        检查命令是否被允许执行
        
        Returns:
            (allowed, reason) - 是否允许及原因
        """
        import re
        
        # 提取基本命令名
        cmd_parts = command.strip().split()
        if not cmd_parts:
            return False, "空命令"
        
        base_cmd = cmd_parts[0].lower()
        
        # 检查黑名单
        for pattern in self.block_commands:
            try:
                if re.search(pattern, command, re.IGNORECASE):
                    return False, f"命令匹配危险模式: {pattern}"
            except re.error:
                pass
        
        # 检查白名单
        if not self.allow_commands:
            return False, "命令执行已禁用（allow_commands 为空）"
        
        if base_cmd not in [c.lower() for c in self.allow_commands]:
            return False, f"命令 '{base_cmd}' 不在允许列表中"
        
        return True, "OK"


# 为了在 validator 中使用 os
import os


class ServerConfig(BaseModel):
    """服务器配置 (保留向后兼容)"""
    
    # 向后兼容字段 - 实际使用时请迁移到 SecurityConfig
    host: Optional[str] = Field(default=None, description="监听地址 (已废弃，请使用 security.host)")
    port: Optional[int] = Field(default=None, ge=1, le=65535, description="监听端口 (已废弃)")
    cors_origins: Optional[List[str]] = Field(default=None, description="CORS允许来源 (已废弃)")
    websocket_enabled: bool = Field(default=True, description="是否启用WebSocket")


class LoggingConfig(BaseModel):
    """日志配置"""
    level: LogLevel = Field(default=LogLevel.INFO, description="日志级别")
    file_enabled: bool = Field(default=True, description="是否写入文件")
    file_path: str = Field(default="logs/hakusai.log", description="日志文件路径")
    max_bytes: int = Field(default=10*1024*1024, description="单个日志文件最大大小")
    backup_count: int = Field(default=5, description="备份文件数量")


# ==================== 主配置 ====================

class CharacterConfig(BaseModel):
    """角色配置"""
    name: str = Field(default="小雪", description="角色名称")
    nickname: Optional[str] = Field(default=None, description="昵称")
    personality: str = Field(default="你是一个温柔善良的AI助手", description="性格描述")
    scenario: Optional[str] = Field(default=None, description="场景设定")
    system_prompt: Optional[str] = Field(default=None, description="系统提示词")
    first_message: Optional[str] = Field(default=None, description="首次消息")
    tags: List[str] = Field(default_factory=list, description="标签")



class HakusAIConfig(BaseModel):
    """
    HakusAI 2.0 主配置类
    
    这是配置文件的根模式，包含所有子配置。
    
    安全相关配置已迁移到 security 字段，旧的 server 字段保留向后兼容。
    建议新配置使用 security 字段进行安全设置。
    """
    version: str = Field(default="0.1.0", description="配置版本")
    
    # 安全配置 (新增 - 推荐使用)
    security: SecurityConfig = Field(default_factory=SecurityConfig, description="安全配置")
    
    # 服务器配置 (向后兼容 - 安全相关设置请迁移到 security)
    server: ServerConfig = Field(default_factory=ServerConfig, description="服务器配置 (兼容模式)")
    
    # 日志配置
    logging: LoggingConfig = Field(default_factory=LoggingConfig, description="日志配置")
    
    # 角色配置
    character: CharacterConfig = Field(default_factory=CharacterConfig, description="角色配置")
    
    # AI模型配置
    model: ModelConfig = Field(default_factory=ModelConfig, description="AI模型配置")
    
    # 语音配置
    voice: VoiceConfig = Field(default_factory=VoiceConfig, description="语音配置")
    
    # 虚拟形象配置
    avatar: AvatarConfig = Field(default_factory=AvatarConfig, description="虚拟形象配置")
    
    # 记忆配置
    memory: MemoryConfig = Field(default_factory=MemoryConfig, description="记忆配置")
    
    # 平台配置
    platform: PlatformConfig = Field(default_factory=PlatformConfig, description="平台配置")
    
    # 额外配置（保留字段）
    extra: Dict[str, Any] = Field(default_factory=dict, description="额外配置")
    
    def get_effective_host(self) -> str:
        """获取有效的监听地址 (security > server)"""
        return self.security.host or self.server.host or "127.0.0.1"
    
    def get_effective_port(self) -> int:
        """获取有效的监听端口 (security > server)"""
        return self.security.port or self.server.port or 8080
    
    def get_effective_cors_origins(self) -> List[str]:
        """获取有效的 CORS origins (security > server)"""
        return self.security.cors_origins or self.server.cors_origins or ["http://localhost:1421"]
    
    def get_effective_api_key(self) -> str:
        """获取 API Key"""
        return self.security.api_key or ""
    
    def is_auth_enabled(self) -> bool:
        """检查是否启用了鉴权"""
        return bool(self.get_effective_api_key())


# 默认配置实例
default_config = HakusAIConfig()
