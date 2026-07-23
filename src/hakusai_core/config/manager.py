"""
HakusAI 2.0 配置管理器
支持YAML配置文件加载、验证和热重载
"""

import os
import yaml
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any, Callable
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import logging

from .schema import HakusAIConfig, default_config

logger = logging.getLogger(__name__)


class ConfigFileHandler(FileSystemEventHandler):
    """配置文件变更处理器"""
    
    def __init__(self, callback: Callable):
        self.callback = callback
        self._last_modified = 0
        
    def on_modified(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith(('.yaml', '.yml')):
            # 防抖处理
            import time
            current_time = time.time()
            if current_time - self._last_modified < 1.0:
                return
            self._last_modified = current_time
            logger.info(f"Config file changed: {event.src_path}")
            asyncio.create_task(self.callback())


class ConfigManager:
    """
    配置管理器 - 单例模式
    
    功能：
    - 加载和保存YAML配置文件
    - 配置验证（使用Pydantic）
    - 配置热重载
    - 环境变量覆盖
    """
    
    _instance: Optional['ConfigManager'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self._config: HakusAIConfig = default_config
        self._config_path: Optional[Path] = None
        self._observer: Optional[Observer] = None
        self._change_callbacks: list = []
        self._lock = asyncio.Lock()
        
    @property
    def config(self) -> HakusAIConfig:
        """获取当前配置"""
        return self._config
    
    def register_change_callback(self, callback: Callable):
        """注册配置变更回调"""
        self._change_callbacks.append(callback)
    
    def unregister_change_callback(self, callback: Callable):
        """取消注册配置变更回调"""
        if callback in self._change_callbacks:
            self._change_callbacks.remove(callback)
    
    async def _notify_change(self):
        """通知配置变更"""
        for callback in self._change_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback()
                else:
                    callback()
            except Exception as e:
                logger.error(f"Error in config change callback: {e}")
    
    def _sync_models_to_model(self, config_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        同步 UI 保存的 models.* 配置到顶层 model.*。

        桌面端把 provider 配置保存在 ~/.hakus/config.yaml 的 `models` 节点下：
            models:
              default_model: opencode
              opencode:
                model_name: deepseek-v4-flash-free
                base_url: https://api.opencode.ai/v1
            api_keys:
              opencode_api_key: sk-xxx

        但后端初始化时读取的是 schema.ModelConfig（model.provider / model.api_key / ...），
        两者没有自动打通，导致 UI 设置了 OpenCode 后端仍用默认 deepseek 启动。
        这里根据 models.default_model 把对应 provider 的配置同步到顶层 model.*。
        """
        import os

        models_cfg = config_dict.get("models") or {}
        default_provider = models_cfg.get("default_model")
        if not default_provider:
            return config_dict

        # 如果用户通过环境变量明确指定了 provider，尊重环境变量。
        if os.getenv("HAKUSAI_MODEL_PROVIDER"):
            return config_dict

        provider_cfg = models_cfg.get(default_provider) or {}
        api_keys = config_dict.get("api_keys") or {}
        key_name = f"{default_provider}_api_key"

        model_cfg = config_dict.setdefault("model", {})
        model_cfg["provider"] = default_provider
        if provider_cfg.get("model_name"):
            model_cfg["model_name"] = provider_cfg["model_name"]
        if provider_cfg.get("base_url"):
            model_cfg["base_url"] = provider_cfg["base_url"]
        if api_keys.get(key_name):
            model_cfg["api_key"] = api_keys[key_name]

        logger.info(
            f"Synced default provider '{default_provider}' from models.* to model.*"
        )
        return config_dict

    def _apply_env_overrides(self, config_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        应用环境变量覆盖
        
        环境变量命名规则：
        - HAKUSAI_SERVER_HOST -> server.host
        - HAKUSAI_MODEL_API_KEY -> model.api_key
        - HAKUSAI_VOICE_TTS_VOICE -> voice.tts.voice
        """
        env_mappings = {
            'HAKUSAI_SERVER_HOST': ['server', 'host'],
            'HAKUSAI_SERVER_PORT': ['server', 'port'],
            'HAKUSAI_MODEL_PROVIDER': ['model', 'provider'],
            'HAKUSAI_MODEL_NAME': ['model', 'model_name'],
            'HAKUSAI_MODEL_API_KEY': ['model', 'api_key'],
            'HAKUSAI_MODEL_BASE_URL': ['model', 'base_url'],
            'HAKUSAI_VOICE_ENABLED': ['voice', 'enabled'],
            'HAKUSAI_VOICE_ASR_PROVIDER': ['voice', 'asr', 'provider'],
            'HAKUSAI_VOICE_TTS_PROVIDER': ['voice', 'tts', 'provider'],
            'HAKUSAI_VOICE_TTS_VOICE': ['voice', 'tts', 'voice'],
            'HAKUSAI_AVATAR_ENABLED': ['avatar', 'enabled'],
            'HAKUSAI_AVATAR_TYPE': ['avatar', 'type'],
            'HAKUSAI_AVATAR_NAME': ['avatar', 'name'],
            'HAKUSAI_MEMORY_ENABLED': ['memory', 'enabled'],
            'HAKUSAI_PLATFORM_BILIBILI_ENABLED': ['platform', 'bilibili', 'enabled'],
            'HAKUSAI_PLATFORM_BILIBILI_ROOM_ID': ['platform', 'bilibili', 'room_id'],
            'HAKUSAI_PLATFORM_DISCORD_ENABLED': ['platform', 'discord', 'enabled'],
            'HAKUSAI_LOGGING_LEVEL': ['logging', 'level'],
        }
        
        for env_var, path in env_mappings.items():
            value = os.getenv(env_var)
            if value is not None:
                # 类型转换
                if value.lower() in ('true', 'false'):
                    value = value.lower() == 'true'
                elif value.isdigit():
                    value = int(value)
                elif value.replace('.', '').isdigit():
                    value = float(value)
                
                # 设置嵌套值
                current = config_dict
                for key in path[:-1]:
                    if key not in current:
                        current[key] = {}
                    current = current[key]
                current[path[-1]] = value
                logger.debug(f"Applied env override: {env_var}={value}")
        
        return config_dict
    
    async def load(self, config_path: str = "configs/default.yaml") -> HakusAIConfig:
        """
        加载配置文件
        
        Args:
            config_path: 配置文件路径
            
        Returns:
            加载的配置对象
        """
        async with self._lock:
            self._config_path = Path(config_path)
            
            # 如果配置文件不存在，创建默认配置
            if not self._config_path.exists():
                logger.info(f"Config file not found, creating default: {config_path}")
                self._config_path.parent.mkdir(parents=True, exist_ok=True)
                # 直接写入默认配置（不能调 self.save()，会再次获取 _lock 死锁）
                try:
                    # model_dump(mode='json') 确保枚举等类型转成纯 JSON 兼容值
                    # 避免 yaml.dump 产生 !!python/object tag
                    config_dict = self._config.model_dump(mode='json')
                    with open(self._config_path, 'w', encoding='utf-8') as f:
                        yaml.dump(config_dict, f, default_flow_style=False, allow_unicode=True, Dumper=yaml.SafeDumper)
                    logger.info(f"Default config saved to: {config_path}")
                except Exception as e:
                    logger.warning(f"Failed to save default config: {e}")
                return self._config
            
            # 读取配置文件
            try:
                with open(self._config_path, 'r', encoding='utf-8') as f:
                    config_dict = yaml.safe_load(f) or {}
                
                # 把 UI 保存的 models.* 同步到顶层 model.*
                config_dict = self._sync_models_to_model(config_dict)

                # 应用环境变量覆盖
                config_dict = self._apply_env_overrides(config_dict)
                
                # 验证并创建配置对象
                self._config = HakusAIConfig(**config_dict)
                logger.info(f"Config loaded from: {config_path}")
                
            except Exception as e:
                logger.error(f"Failed to load config: {e}")
                logger.warning("Using default config")
                self._config = default_config
        
        return self._config
    
    async def save(self, config_path: Optional[str] = None):
        """
        保存配置到文件
        
        Args:
            config_path: 配置文件路径，默认使用加载时的路径
        """
        async with self._lock:
            save_path = Path(config_path) if config_path else self._config_path
            if save_path is None:
                save_path = Path("configs/default.yaml")
            
            save_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 转换为字典并保存
            config_dict = self._config.model_dump(mode='json')
            
            with open(save_path, 'w', encoding='utf-8') as f:
                yaml.dump(
                    config_dict, 
                    f, 
                    allow_unicode=True, 
                    sort_keys=False,
                    default_flow_style=False,
                    Dumper=yaml.SafeDumper,
                    width=80
                )
            
            logger.info(f"Config saved to: {save_path}")
    
    async def reload(self) -> HakusAIConfig:
        """重新加载配置"""
        if self._config_path is None:
            raise ValueError("Config path not set")
        
        async with self._lock:
            old_config = self._config
            
            try:
                with open(self._config_path, 'r', encoding='utf-8') as f:
                    config_dict = yaml.safe_load(f) or {}

                # 把 UI 保存的 models.* 同步到顶层 model.*
                config_dict = self._sync_models_to_model(config_dict)
                
                # 应用环境变量覆盖
                config_dict = self._apply_env_overrides(config_dict)
                
                # 验证并创建配置对象
                self._config = HakusAIConfig(**config_dict)
                logger.info("Config reloaded successfully")
                
                # 通知变更
                await self._notify_change()
                
            except Exception as e:
                logger.error(f"Failed to reload config: {e}")
                self._config = old_config
                raise
        
        return self._config
    
    def update(self, updates: Dict[str, Any]):
        """
        更新配置（部分更新）
        
        Args:
            updates: 更新字典
        """
        config_dict = self._config.model_dump()
        self._deep_update(config_dict, updates)
        self._config = HakusAIConfig(**config_dict)
        logger.debug("Config updated")
    
    def _deep_update(self, base_dict: Dict, update_dict: Dict):
        """深度更新字典"""
        for key, value in update_dict.items():
            if key in base_dict and isinstance(base_dict[key], dict) and isinstance(value, dict):
                self._deep_update(base_dict[key], value)
            else:
                base_dict[key] = value
    
    def start_watching(self):
        """开始监视配置文件变更"""
        if self._observer is not None:
            return
        
        if self._config_path is None:
            logger.warning("Config path not set, cannot watch for changes")
            return
        
        self._observer = Observer()
        handler = ConfigFileHandler(self.reload)
        self._observer.schedule(handler, str(self._config_path.parent), recursive=False)
        self._observer.start()
        logger.info(f"Started watching config file: {self._config_path}")
    
    def stop_watching(self):
        """停止监视配置文件变更"""
        if self._observer is not None:
            self._observer.stop()
            self._observer.join()
            self._observer = None
            logger.info("Stopped watching config file")
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """
        通过路径获取配置值
        
        Args:
            key_path: 点分隔的路径，如 "server.port"
            default: 默认值
            
        Returns:
            配置值
        """
        keys = key_path.split('.')
        value = self._config.model_dump()
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        
        return value
    
    def set(self, key_path: str, value: Any):
        """
        通过路径设置配置值
        
        Args:
            key_path: 点分隔的路径，如 "server.port"
            value: 要设置的值
        """
        config_dict = self._config.model_dump()
        keys = key_path.split('.')
        
        current = config_dict
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
        
        current[keys[-1]] = value
        self._config = HakusAIConfig(**config_dict)


# 全局配置管理器实例
config_manager = ConfigManager()
