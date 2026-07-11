"""HakusConfig — 结构化配置类 (借鉴 trae-agent Config 设计).

替代扁平的 BASE_CONFIG 字典，提供:
  1. 类型安全的属性访问 (config.models.deepseek.model_name)
  2. 环境变量覆盖 (CLI > 环境变量 > 配置文件 > 默认值)
  3. Provider 配置的标准化 (get_provider_config())
  4. 向后兼容 (BASE_CONFIG 仍可使用)

用法:
  from utils.config import HakusConfig, get_config
  config = get_config()
  print(config.models.deepseek.model_name)
  print(config.default_model)
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

# 向后兼容: 同步更新旧版 BASE_CONFIG (如果存在)
try:
    from utils.config import BASE_CONFIG
except Exception:
    BASE_CONFIG = None  # type: ignore

logger = logging.getLogger(__name__)


# ── 数据类: 各配置段 ──────────────────────────────────────────

@dataclass
class ProviderConfig:
    """单个 LLM Provider 的配置."""
    model_name: str = ""
    base_url: str = ""
    api_key: str = ""
    provider: str = ""  # 对应 LLMProvider 枚举值

    def to_model_config_dict(self) -> Dict[str, Any]:
        """转换为 ModelConfig 所需的字典."""
        return {
            "provider": self.provider,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model_name": self.model_name,
        }


@dataclass
class ModelsConfig:
    """模型配置段."""
    default_model: str = "opencode"
    deepseek: ProviderConfig = field(default_factory=lambda: ProviderConfig(
        provider="deepseek",
        model_name="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
    ))
    qwen: ProviderConfig = field(default_factory=lambda: ProviderConfig(
        provider="qwen",
        model_name="qwen-flash",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    ))
    gemini: ProviderConfig = field(default_factory=lambda: ProviderConfig(
        provider="gemini",
        model_name="gemini-2.5-flash",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    ))
    glm: ProviderConfig = field(default_factory=lambda: ProviderConfig(
        provider="glm",
        model_name="glm-4-flash",
        base_url="https://open.bigmodel.cn/api/paas/v4/",
    ))
    mimo: ProviderConfig = field(default_factory=lambda: ProviderConfig(
        provider="mimo",
        model_name="mimo-v2.5-pro",
        base_url="https://api.xiaomimimo.com/v1",
    ))
    ollama: ProviderConfig = field(default_factory=lambda: ProviderConfig(
        provider="ollama",
        model_name="gemma4",
        base_url="http://localhost:11434/v1",
        api_key="ollama",
    ))
    openai: ProviderConfig = field(default_factory=lambda: ProviderConfig(
        provider="openai",
        model_name="gpt-4o",
        base_url="https://api.openai.com/v1",
    ))
    anthropic: ProviderConfig = field(default_factory=lambda: ProviderConfig(
        provider="anthropic",
        model_name="claude-sonnet-4-20250514",
        base_url="https://api.anthropic.com",
    ))
    opencode: ProviderConfig = field(default_factory=lambda: ProviderConfig(
        provider="opencode",
        model_name="deepseek-v4-flash-free",
        base_url="https://opencode.ai/zen/v1",
    ))

    def get_provider(self, name: str) -> Optional[ProviderConfig]:
        """按名称获取 Provider 配置."""
        return getattr(self, name.lower(), None)


@dataclass
class MemoryConfig:
    """记忆系统配置."""
    short_term_max_length: int = 50
    long_term_max_length: int = 500
    state_dir: str = "~/.hakus/user_states"
    db_dir: str = "~/.hakus/memory_db"


@dataclass
class TTSConfig:
    """TTS 语音配置."""
    enabled: bool = True
    audio_output: bool = True
    type: str = "voxcpm"


@dataclass
class LoggingConfig:
    """日志配置."""
    level: str = "INFO"


@dataclass
class HakusConfig:
    """HakusAI 全局配置 — 结构化访问.

    借鉴 trae-agent 的 Config 类设计，将扁平的 YAML 配置
    映射到类型安全的 dataclass 属性。
    """
    models: ModelsConfig = field(default_factory=ModelsConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    debug: bool = False
    features: Dict[str, Any] = field(default_factory=dict)

    # 原始配置 (用于向后兼容)
    _raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    def get_provider_config(self, provider_name: str) -> Optional[ProviderConfig]:
        """获取指定 Provider 的配置 (便捷方法)."""
        return self.models.get_provider(provider_name)


# ── 配置加载 ──────────────────────────────────────────────────

def _resolve_env_vars(value: Any) -> Any:
    """解析环境变量，支持 ${ENV_VAR:default_value} 格式."""
    if isinstance(value, str):
        import re
        pattern = r'\$\{([^}:]+)(?::([^}]*))?\}'

        def replace_env_var(match):
            env_var = match.group(1)
            default_val = match.group(2) if match.group(2) is not None else ""
            return os.environ.get(env_var, default_val)

        return re.sub(pattern, replace_env_var, value)
    elif isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_resolve_env_vars(item) for item in value]
    return value


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """深度合并两个字典，override 的值覆盖 base."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_yaml() -> Dict[str, Any]:
    """加载并解析 config.yaml.

    优先级: ~/.hakus/config.yaml 覆盖项目目录 config.yaml > 默认值.
    用户配置与项目配置深度合并，确保 save_default_model 写入的局部
    配置不会丢失 api_keys 等其他项目级设置.
    """
    project_config = Path(__file__).parent.parent / "config.yaml"
    project_raw: Dict[str, Any] = {}
    if project_config.exists():
        with open(project_config, "r", encoding="utf-8") as f:
            project_raw = yaml.safe_load(f) or {}

    user_config = Path(os.path.expanduser("~/.hakus/config.yaml"))
    if user_config.exists():
        with open(user_config, "r", encoding="utf-8") as f:
            user_raw = yaml.safe_load(f) or {}
        return _deep_merge(project_raw, user_raw)

    if project_raw:
        return project_raw

    logger.warning("config.yaml not found, using defaults")
    return {}


def _build_config(raw: Dict[str, Any]) -> HakusConfig:
    """从原始 YAML 字典构建 HakusConfig."""
    resolved = _resolve_env_vars(raw)

    # API Keys
    api_keys = resolved.get("api_keys", {})

    # Models
    models_raw = resolved.get("models", {})
    models = ModelsConfig(
        default_model=models_raw.get("default_model", "opencode"),
    )

    # 填充各 Provider 配置
    _provider_defaults = {
        "deepseek": {"base_url": "https://api.deepseek.com/v1"},
        "openai": {"base_url": "https://api.openai.com/v1", "model_name": "gpt-4o"},
        "anthropic": {"base_url": "https://api.anthropic.com", "model_name": "claude-sonnet-4-20250514"},
        "qwen": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
        "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/"},
        "glm": {"base_url": "https://open.bigmodel.cn/api/paas/v4/"},
        "mimo": {"base_url": "https://api.xiaomimimo.com/v1"},
        "ollama": {"base_url": "http://localhost:11434/v1", "api_key": "ollama"},
        "opencode": {"base_url": "https://opencode.ai/zen/v1"},
    }
    _api_key_map = {
        "deepseek": api_keys.get("deepseek_api_key", ""),
        "openai": api_keys.get("openai_api_key", ""),
        "anthropic": api_keys.get("anthropic_api_key", ""),
        "qwen": api_keys.get("dashscope_api_key", ""),
        "gemini": api_keys.get("gemini_api_key", ""),
        "glm": api_keys.get("glm_api_key", ""),
        "mimo": api_keys.get("mimo_api_key", ""),
        "ollama": "ollama",
        "opencode": api_keys.get("opencode_api_key", ""),
    }

    for name, defaults in _provider_defaults.items():
        prov_raw = models_raw.get(name, {})
        setattr(models, name, ProviderConfig(
            provider=name,
            model_name=prov_raw.get("model_name", defaults.get("model_name", "")),
            base_url=prov_raw.get("base_url", defaults.get("base_url", "")),
            api_key=_api_key_map.get(name, ""),
        ))

    # Memory
    mem_raw = resolved.get("memory", {})
    memory = MemoryConfig(
        short_term_max_length=int(mem_raw.get("short_term_max_length", 50)),
        long_term_max_length=int(mem_raw.get("long_term_max_length", 500)),
        state_dir=os.path.abspath(os.path.expanduser(mem_raw.get("state_dir", "~/.hakus/user_states"))),
        db_dir=os.path.abspath(os.path.expanduser(mem_raw.get("db_dir", "~/.hakus/memory_db"))),
    )

    # TTS
    tts_raw = resolved.get("tts", {})
    tts = TTSConfig(
        enabled=str(tts_raw.get("enabled", "true")).lower() in ("true", "1", "yes"),
        audio_output=str(tts_raw.get("audio_output", "true")).lower() in ("true", "1", "yes"),
        type=tts_raw.get("type", "voxcpm"),
    )

    # Logging
    log_raw = resolved.get("logging", {})
    logging_cfg = LoggingConfig(level=log_raw.get("level", "INFO"))

    # Debug
    debug = str(resolved.get("debug", "false")).lower() in ("true", "1", "yes")

    return HakusConfig(
        models=models,
        memory=memory,
        tts=tts,
        logging=logging_cfg,
        debug=debug,
        features=resolved.get("features", {}),
        _raw=resolved,
    )


# ── 全局单例 ──────────────────────────────────────────────────

_config: Optional[HakusConfig] = None


def get_config() -> HakusConfig:
    """获取全局 HakusConfig 实例 (懒加载)."""
    global _config
    if _config is None:
        raw = _load_yaml()
        _config = _build_config(raw)
    return _config


def reload_config() -> HakusConfig:
    """重新加载配置 (用于测试或运行时配置变更)."""
    global _config, BASE_CONFIG
    _config = None
    config = get_config()
    # 同步更新 BASE_CONFIG 以保持向后兼容
    _sync_base_config(config)
    return config


def save_default_model(provider_id: str) -> None:
    """将默认模型持久化到 ~/.hakus/config.yaml 并热重载.

    用于 /model 命令或 ModelOverlay 切换模型后, 确保重启仍保持选择.
    """
    import yaml
    config_dir = Path(os.path.expanduser("~/.hakus"))
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"

    raw: Dict[str, Any] = {}
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        except Exception:
            raw = {}

    raw.setdefault("models", {})
    raw["models"]["default_model"] = provider_id

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(raw, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    reload_config()


def _sync_base_config(config: HakusConfig) -> None:
    """将 HakusConfig 同步回 BASE_CONFIG (向后兼容)."""
    global BASE_CONFIG
    if BASE_CONFIG is None:
        return
    BASE_CONFIG["DEFAULT_MODEL"] = config.models.default_model
    BASE_CONFIG["DEBUG"] = config.debug

    for name in ["deepseek", "openai", "anthropic", "qwen", "gemini", "glm", "mimo", "ollama", "opencode"]:
        prov = config.models.get_provider(name)
        if prov:
            if name == "qwen":
                # Qwen uses DASHSCOPE for API key, QWEN for model info
                BASE_CONFIG["DASHSCOPE_API_KEY"] = prov.api_key
                BASE_CONFIG["QWEN_MODEL_NAME"] = prov.model_name
                continue
            elif name == "deepseek":
                BASE_CONFIG["DEEPSEEK_API_KEY"] = prov.api_key
                BASE_CONFIG["DEEPSEEK_BASE_URL"] = prov.base_url
                BASE_CONFIG["DEEPSEEK_MODEL_NAME"] = prov.model_name
                continue
            elif name == "openai":
                BASE_CONFIG["OPENAI_API_KEY"] = prov.api_key
                BASE_CONFIG["OPENAI_BASE_URL"] = prov.base_url
                BASE_CONFIG["OPENAI_MODEL_NAME"] = prov.model_name
                continue
            elif name == "anthropic":
                BASE_CONFIG["ANTHROPIC_API_KEY"] = prov.api_key
                BASE_CONFIG["ANTHROPIC_BASE_URL"] = prov.base_url
                BASE_CONFIG["ANTHROPIC_MODEL_NAME"] = prov.model_name
                continue
            elif name == "glm":
                BASE_CONFIG["GLM_API_KEY"] = prov.api_key
                BASE_CONFIG["GLM_MODEL_NAME"] = prov.model_name
                continue
            elif name == "gemini":
                BASE_CONFIG["GEMINI_API_KEY"] = prov.api_key
                BASE_CONFIG["GEMINI_MODEL_NAME"] = prov.model_name
                continue
            elif name == "mimo":
                BASE_CONFIG["MIMO_API_KEY"] = prov.api_key
                BASE_CONFIG["MIMO_BASE_URL"] = prov.base_url
                BASE_CONFIG["MIMO_MODEL_NAME"] = prov.model_name
                continue
            elif name == "ollama":
                BASE_CONFIG["OLLAMA_BASE_URL"] = prov.base_url
                BASE_CONFIG["OLLAMA_MODEL_NAME"] = prov.model_name
                continue
            elif name == "opencode":
                BASE_CONFIG["OPENCODE_API_KEY"] = prov.api_key
                BASE_CONFIG["OPENCODE_BASE_URL"] = prov.base_url
                BASE_CONFIG["OPENCODE_MODEL_NAME"] = prov.model_name
                continue
