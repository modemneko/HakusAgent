import os
import logging
import shutil
from pathlib import Path
from typing import Dict, Any, Optional

import yaml

logger = logging.getLogger(__name__)

# 配置文件搜索路径（优先级从高到低）
_CONFIG_SEARCH_PATHS = [
    Path(os.path.expanduser("~/.hakus/config.yaml")),   # 用户级配置
    Path(__file__).parent.parent / "config.yaml",        # 项目级配置
]

# 模板路径（用于首次运行生成默认配置)
_CONFIG_TEMPLATE = Path(__file__).parent.parent / "config.example.yaml"


def _find_config() -> Optional[Path]:
    """按优先级查找配置文件."""
    for path in _CONFIG_SEARCH_PATHS:
        if path.exists():
            return path
    return None


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """深度合并两个字典，override 的值覆盖 base."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_yaml_config() -> Dict[str, Any]:
    """加载 YAML 配置文件.

    加载优先级:
      1. ~/.hakus/config.yaml  (用户个人配置，最高优先级)
      2. ./config.yaml         (项目配置)

    如果两个都存在，会深度合并（用户配置覆盖项目配置）.
    """
    user_config_path = _CONFIG_SEARCH_PATHS[0]
    project_config_path = _CONFIG_SEARCH_PATHS[1]
    config: Dict[str, Any] = {}

    # 先加载项目级配置（如果有）
    if project_config_path.exists():
        with open(project_config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

    # 再用用户级配置覆盖（如果有）
    if user_config_path.exists():
        with open(user_config_path, "r", encoding="utf-8") as f:
            user_config = yaml.safe_load(f) or {}
        config = _deep_merge(config, user_config)

    if not config:
        raise FileNotFoundError(
            f"找不到配置文件。请执行以下任一操作:\n"
            f"  1. cp config.example.yaml ~/.hakus/config.yaml  (推荐)\n"
            f"  2. cp config.example.yaml config.yaml\n"
            f"  或运行: hakusai --setup"
        )

    return config


def ensure_user_config_dir() -> Path:
    """确保用户配置目录存在，返回目录路径."""
    config_dir = Path(os.path.expanduser("~/.hakus"))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def init_user_config_from_template() -> Path:
    """从模板初始化用户配置文件.

    Returns:
        生成的配置文件路径

    Raises:
        FileNotFoundError: 模板不存在
    """
    if not _CONFIG_TEMPLATE.exists():
        raise FileNotFoundError(f"配置模板不存在: {_CONFIG_TEMPLATE}")

    config_dir = ensure_user_config_dir()
    target = config_dir / "config.yaml"

    if not target.exists():
        shutil.copy2(_CONFIG_TEMPLATE, target)
        logger.info(f"已从模板生成用户配置: {target}")

    return target


def resolve_env_vars(value: Any) -> Any:
    """解析环境变量，支持 ${ENV_VAR:default_value} 格式."""
    import re

    if isinstance(value, str):
        pattern = r"\$\{([^}:]+)(?::([^}]*))?\}"

        def replace_env_var(match):
            env_var = match.group(1)
            default_val = match.group(2) if match.group(2) is not None else ""
            return os.environ.get(env_var, default_val)

        return re.sub(pattern, replace_env_var, value)
    elif isinstance(value, dict):
        return {k: resolve_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [resolve_env_vars(item) for item in value]
    return value


def flatten_config(config: Dict[str, Any], parent_key: str = "") -> Dict[str, Any]:
    """将嵌套配置扁平化为 BASE_CONFIG 格式."""
    items = {}
    for k, v in config.items():
        new_key = f"{parent_key}_{k.upper()}" if parent_key else k.upper()
        if isinstance(v, dict):
            items.update(flatten_config(v, new_key))
        else:
            items[new_key] = v
    return items


def convert_value(value: str, key: str) -> Any:
    """根据 key 转换配置值为正确的类型."""
    bool_keys = [
        "ENABLED", "AUDIO_OUTPUT", "ENABLE_IMAGE_GENERATION",
        "STREAMING", "DEBUG", "MEMORY_ENABLED",
    ]
    if any(key.endswith(bk) for bk in bool_keys):
        return str(value).lower() in ("true", "1", "yes", "on")

    int_keys = [
        "THREAD_COUNT", "BATCH_SIZE", "SHORT_TERM_MAX_LENGTH",
        "LONG_TERM_MAX_LENGTH", "SAMPLE_RATE", "WIDTH", "HEIGHT",
    ]
    if any(key.endswith(ik) for ik in int_keys):
        try:
            return int(value)
        except (ValueError, TypeError):
            return value

    float_keys = ["SPEED", "VOLUME", "PITCH", "SCALE", "OPACITY", "MAX_OPEN"]
    if any(key.endswith(fk) for fk in float_keys):
        try:
            return float(value)
        except (ValueError, TypeError):
            return value

    return value


def get_provider_config(provider_name: str) -> Dict[str, str]:
    """获取指定模型商的配置 (api_key, base_url, model_name).

    用于动态添加/切换模型商时快速读取配置。
    """
    keys = _resolved_config.get("api_keys", {})
    models = _resolved_config.get("models", {})
    provider_cfg = models.get(provider_name, {})

    # API key 映射
    key_map = {
        "openai": "openai_api_key",
        "anthropic": "anthropic_api_key",
        "deepseek": "deepseek_api_key",
        "qwen": "dashscope_api_key",       # Qwen 用 dashscope key
        "gemini": "gemini_api_key",
        "glm": "glm_api_key",
        "mimo": "mimo_api_key",
        "ollama": "",                      # Ollama 不需要 key
        "custom": "custom_api_key",
    }
    key_name = key_map.get(provider_name, "")
    api_key = keys.get(key_name, "") if key_name else ""

    return {
        "api_key": api_key,
        "base_url": provider_cfg.get("base_url", ""),
        "model_name": provider_cfg.get("model_name", ""),
    }


# ============================================================
# 加载并解析配置（模块加载时执行一次）
# ============================================================
_raw_config = load_yaml_config()
_resolved_config = resolve_env_vars(_raw_config)

# 构建 BASE_CONFIG
BASE_CONFIG: Dict[str, Any] = {
    # ---- API Keys ----
    "OPENAI_API_KEY": _resolved_config["api_keys"].get("openai_api_key", ""),
    "ANTHROPIC_API_KEY": _resolved_config["api_keys"].get("anthropic_api_key", ""),
    "GEMINI_API_KEY": _resolved_config["api_keys"].get("gemini_api_key", ""),
    "GOOGLE_API_KEY": _resolved_config["api_keys"].get("google_api_key", ""),
    "GOOGLE_CSE_ID": _resolved_config["api_keys"].get("google_cse_id", ""),
    "DASHSCOPE_API_KEY": _resolved_config["api_keys"].get("dashscope_api_key", ""),
    "DEEPSEEK_API_KEY": _resolved_config["api_keys"].get("deepseek_api_key", ""),
    "GLM_API_KEY": _resolved_config["api_keys"].get("glm_api_key", ""),
    "MIMO_API_KEY": _resolved_config["api_keys"].get("mimo_api_key", ""),
    "CUSTOM_API_KEY": _resolved_config["api_keys"].get("custom_api_key", ""),

    # ---- Models ----
    "DEFAULT_MODEL": _resolved_config["models"].get("default_model", "opencode"),

    # OpenAI
    "OPENAI_MODEL_NAME": _resolved_config["models"].get("openai", {}).get("model_name", "gpt-4o"),
    "OPENAI_BASE_URL": _resolved_config["models"].get("openai", {}).get("base_url", "https://api.openai.com/v1"),

    # Anthropic
    "ANTHROPIC_MODEL_NAME": _resolved_config["models"].get("anthropic", {}).get("model_name", "claude-sonnet-4-20250514"),
    "ANTHROPIC_BASE_URL": _resolved_config["models"].get("anthropic", {}).get("base_url", "https://api.anthropic.com"),

    # Gemini
    "GEMINI_MODEL_NAME": _resolved_config["models"].get("gemini", {}).get("model_name", "gemini-2.5-flash"),

    # Qwen
    "QWEN_MODEL_NAME": _resolved_config["models"].get("qwen", {}).get("model_name", "qwen-flash"),

    # DeepSeek
    "DEEPSEEK_MODEL_NAME": _resolved_config["models"].get("deepseek", {}).get("model_name", "deepseek-chat"),
    "DEEPSEEK_BASE_URL": _resolved_config["models"].get("deepseek", {}).get("base_url", "https://api.deepseek.com/v1"),

    # GLM
    "GLM_MODEL_NAME": _resolved_config["models"].get("glm", {}).get("model_name", "glm-4-flash"),

    # MiMo
    "MIMO_MODEL_NAME": _resolved_config["models"].get("mimo", {}).get("model_name", "mimo-v2.5-pro"),
    "MIMO_BASE_URL": _resolved_config["models"].get("mimo", {}).get("base_url", "https://api.xiaomimimo.com/v1"),

    # Ollama
    "OLLAMA_MODEL_NAME": _resolved_config["models"].get("ollama", {}).get("model_name", "gemma4"),
    "OLLAMA_BASE_URL": _resolved_config["models"].get("ollama", {}).get("base_url", "http://localhost:11434/v1"),

    # Custom (OpenAI 兼容)
    "CUSTOM_MODEL_NAME": _resolved_config["models"].get("custom", {}).get("model_name", ""),
    "CUSTOM_BASE_URL": _resolved_config["models"].get("custom", {}).get("base_url", ""),

    # ---- Embedding ----
    "EMBEDDING_TYPE": _resolved_config.get("embedding", {}).get("type", "google"),
    "EMBEDDING_MODEL_PATH": _resolved_config.get("embedding", {}).get("model_path", "shibing624/text2vec-base-chinese"),
    "LOCAL_EMBEDDING_MODEL_PATH": _resolved_config.get("embedding", {}).get("local_model_path", "./embedding_models/text2vec-base-chinese"),
    "EMBEDDING_DEVICE": _resolved_config.get("embedding", {}).get("device", "cpu"),
    "CPU_THREAD_COUNT": convert_value(_resolved_config.get("embedding", {}).get("thread_count", 4), "THREAD_COUNT"),
    "EMBEDDING_BATCH_SIZE": convert_value(_resolved_config.get("embedding", {}).get("batch_size", 8), "BATCH_SIZE"),

    # ---- Memory ----
    "MEMORY_ENABLED": convert_value(
        _resolved_config.get("memory", {}).get("enabled", False), "MEMORY_ENABLED"
    ),
    "SHORT_TERM_MEMORY_MAX_LENGTH": convert_value(
        _resolved_config.get("memory", {}).get("short_term_max_length", 20), "SHORT_TERM_MAX_LENGTH"
    ),
    "LONG_TERM_MEMORY_MAX_LENGTH": convert_value(
        _resolved_config.get("memory", {}).get("long_term_max_length", 100), "LONG_TERM_MAX_LENGTH"
    ),
    "STATE_DIR": os.path.abspath(os.path.expanduser(_resolved_config.get("memory", {}).get("state_dir", "./state"))),
    "MEMORY_DB_DIR": os.path.abspath(os.path.expanduser(_resolved_config.get("memory", {}).get("db_dir", "./data/memory_db"))),

    # ---- TTS ----
    "ENABLE_TTS": convert_value(_resolved_config.get("tts", {}).get("enabled", False), "ENABLED"),
    "ENABLE_TTS_AUDIO_OUTPUT": convert_value(_resolved_config.get("tts", {}).get("audio_output", True), "AUDIO_OUTPUT"),
    "TTS_TYPE": _resolved_config.get("tts", {}).get("type", "sherpa_onnx"),
    "TTS_API_TYPE": _resolved_config.get("tts", {}).get("api", {}).get("api_type", "gemini"),
    "TTS_VOICE_ID": _resolved_config.get("tts", {}).get("api", {}).get("voice_id", ""),
    "SHERPA_ONNX_MODEL_DIR": _resolved_config.get("tts", {}).get("sherpa_onnx", {}).get("model_dir", "./models/tts/sherpa_onnx"),
    "SHERPA_ONNX_VOICE": _resolved_config.get("tts", {}).get("sherpa_onnx", {}).get("voice", ""),
    "SHERPA_ONNX_SPEED": convert_value(_resolved_config.get("tts", {}).get("sherpa_onnx", {}).get("speed", 1.0), "SPEED"),
    "SHERPA_ONNX_VOLUME": convert_value(_resolved_config.get("tts", {}).get("sherpa_onnx", {}).get("volume", 1.0), "VOLUME"),
    "SHERPA_ONNX_PITCH": convert_value(_resolved_config.get("tts", {}).get("sherpa_onnx", {}).get("pitch", 1.0), "PITCH"),
    "SHERPA_ONNX_AUDIO_FORMAT": _resolved_config.get("tts", {}).get("sherpa_onnx", {}).get("audio_format", "wav"),
    "SHERPA_ONNX_SAMPLE_RATE": convert_value(_resolved_config.get("tts", {}).get("sherpa_onnx", {}).get("sample_rate", 22050), "SAMPLE_RATE"),
    "SHERPA_ONNX_DEVICE": _resolved_config.get("tts", {}).get("sherpa_onnx", {}).get("device", "cpu"),

    # CosyVoice
    "COSYVOICE_MODEL": _resolved_config.get("tts", {}).get("cosyvoice", {}).get("model", "cosyvoice-v2"),
    "COSYVOICE_VOICE_ID": _resolved_config.get("tts", {}).get("cosyvoice", {}).get("voice_id", "longxiaochun"),
    "COSYVOICE_REF_AUDIO_URL": _resolved_config.get("tts", {}).get("cosyvoice", {}).get("ref_audio_url", ""),
    "COSYVOICE_LANGUAGE_HINTS": _resolved_config.get("tts", {}).get("cosyvoice", {}).get("language_hints", ""),
    "COSYVOICE_STREAMING": convert_value(_resolved_config.get("tts", {}).get("cosyvoice", {}).get("streaming", False), "STREAMING"),
    "COSYVOICE_FORMAT": _resolved_config.get("tts", {}).get("cosyvoice", {}).get("format", "wav"),
    "COSYVOICE_SAMPLE_RATE": convert_value(_resolved_config.get("tts", {}).get("cosyvoice", {}).get("sample_rate", 22050), "SAMPLE_RATE"),
    "COSYVOICE_VOICE_PREFIX": _resolved_config.get("tts", {}).get("cosyvoice", {}).get("voice_prefix", ""),

    # ---- Features ----
    "ENABLE_IMAGE_GENERATION": convert_value(
        _resolved_config.get("features", {}).get("enable_image_generation", False), "ENABLE_IMAGE_GENERATION"
    ),

    # ---- Logging ----
    "LOG_LEVEL": getattr(logging, _resolved_config.get("logging", {}).get("level", "INFO").upper(), logging.INFO),

    # ---- Debug ----
    "DEBUG": convert_value(_resolved_config.get("debug", False), "DEBUG"),

    # ---- Voice ----
    "VOICE": _resolved_config.get("voice", {}),
    "BERT_VITS2_MODEL_DIR": _resolved_config.get("voice", {}).get("tts", {}).get("model_dir", "./models/tts/bert_vits2"),
    "BERT_VITS2_GEN_CONFIG": _resolved_config.get("voice", {}).get("tts", {}).get("gen_config", "./configs/gen_config.json"),
    "VOICE_OUTPUT_DIR": _resolved_config.get("voice", {}).get("tts", {}).get("output_dir", "./output"),
}

# 工具配置
TOOLS_CONFIG = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "搜索互联网获取实时信息。当需要查找最新信息、新闻、事实时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索查询词，应该简洁明确"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "使用AI生成图像。当需要创建图片、艺术作品或视觉内容时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "图像生成提示词，应该详细描述想要生成的图像内容"}
                },
                "required": ["prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_reminder",
            "description": "设置定时提醒。当用户要求提醒、闹钟、定时通知时使用。支持自然语言时间表达。",
            "parameters": {
                "type": "object",
                "properties": {
                    "time_expr": {"type": "string", "description": "时间表达式，如：10分钟后、明天早上8点、今天下午3点、1小时后"},
                    "content": {"type": "string", "description": "提醒的内容，如：开会、吃药、休息一下"}
                },
                "required": ["time_expr", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_reminders",
            "description": "列出用户设置的所有待执行提醒。当用户想查看自己的提醒列表时使用。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_reminder",
            "description": "取消指定序号的提醒。当用户想删除某个提醒时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_index": {"type": "integer", "description": "要取消的提醒序号（从1开始）"}
                },
                "required": ["task_index"]
            }
        }
    }
]

# 创建必要的目录
for dir_path in [BASE_CONFIG.get("STATE_DIR", "./state"), BASE_CONFIG.get("MEMORY_DB_DIR", "./data/memory_db")]:
    os.makedirs(dir_path, exist_ok=True)
