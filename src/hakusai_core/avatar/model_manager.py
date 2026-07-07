"""
Live2D 模型管理器
借鉴 Open-LLM-VTuber 的模型配置系统，支持多模型切换和情感映射
"""

import json
import chardet
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from loguru import logger


@dataclass
class ModelInfo:
    """模型信息"""
    name: str
    description: str
    url: str
    kScale: float = 0.5
    initialXshift: float = 0
    initialYshift: float = 0
    kXOffset: float = 1150
    idleMotionGroupName: str = "Idle"
    emotionMap: Dict[str, int] = None
    tapMotions: Dict[str, Dict[str, int]] = None

    def __post_init__(self):
        if self.emotionMap is None:
            self.emotionMap = {}
        if self.tapMotions is None:
            self.tapMotions = {}


class Live2DModelManager:
    """
    Live2D 模型管理器
    
    功能：
    - 加载 model_dict.json 配置文件
    - 管理多个 Live2D 模型
    - 提供情感映射功能
    - 支持模型热切换
    """

    def __init__(self, model_dict_path: Optional[str] = None):
        """
        初始化模型管理器
        
        Args:
            model_dict_path: 模型字典文件路径，默认为 avatar/model_dict.json
        """
        if model_dict_path is None:
            model_dict_path = Path(__file__).parent / "model_dict.json"

        self.model_dict_path = Path(model_dict_path)
        self._models: Dict[str, ModelInfo] = {}
        self._current_model_name: Optional[str] = None
        self._emo_map: Dict[str, int] = {}
        self._emo_str: str = ""

        self._load_models()

    def _load_file_content(self, file_path: Path) -> str:
        """加载文件内容，自动检测编码"""
        encodings = ["utf-8", "utf-8-sig", "gbk", "gb2312", "ascii"]

        for encoding in encodings:
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue

        try:
            with open(file_path, "rb") as f:
                raw_data = f.read()
            detected = chardet.detect(raw_data)
            if detected["encoding"]:
                return raw_data.decode(detected["encoding"])
        except Exception as e:
            logger.error(f"Error detecting encoding for {file_path}: {e}")

        raise UnicodeError(f"Failed to decode {file_path} with any encoding")

    def _load_models(self):
        """加载所有模型配置"""
        try:
            file_content = self._load_file_content(self.model_dict_path)
            model_list = json.loads(file_content)

            for model_data in model_list:
                model_info = ModelInfo(**model_data)
                self._models[model_info.name] = model_info
                logger.info(f"Loaded Live2D model: {model_info.name}")

            if self._models:
                first_model = list(self._models.keys())[0]
                self.set_model(first_model)

        except FileNotFoundError:
            logger.warning(f"Model dictionary not found: {self.model_dict_path}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in model dictionary: {e}")
        except Exception as e:
            logger.error(f"Failed to load models: {e}")

    def set_model(self, model_name: str) -> bool:
        """
        设置当前模型
        
        Args:
            model_name: 模型名称
            
        Returns:
            是否成功
        """
        if model_name not in self._models:
            logger.error(f"Model not found: {model_name}")
            return False

        self._current_model_name = model_name
        model_info = self._models[model_name]

        # 初始化情感映射（转小写以便匹配）
        self._emo_map = {k.lower(): v for k, v in model_info.emotionMap.items()}
        # 生成情感标签字符串，例如 "[fear], [anger], [joy]"
        self._emo_str = " ".join([f"[{key}]" for key in self._emo_map.keys()])

        logger.info(f"Current model set to: {model_name}")
        logger.info(f"Available emotions: {self._emo_str}")
        return True

    @property
    def current_model(self) -> Optional[ModelInfo]:
        """获取当前模型信息"""
        if self._current_model_name:
            return self._models.get(self._current_model_name)
        return None

    @property
    def model_names(self) -> List[str]:
        """获取所有可用模型名称"""
        return list(self._models.keys())

    def get_model_info(self, model_name: str) -> Optional[ModelInfo]:
        """获取指定模型信息"""
        return self._models.get(model_name)

    @property
    def emo_map(self) -> Dict[str, int]:
        """获取情感映射表"""
        return self._emo_map

    @property
    def emo_str(self) -> str:
        """获取情感标签字符串"""
        return self._emo_str

    def extract_emotions(self, text: str) -> List[int]:
        """
        从文本中提取情感索引
        
        Args:
            text: 包含情感标签的文本，如 "Hello [joy] I'm happy!"
            
        Returns:
            情感索引列表，如 [3]
        """
        expression_list = []
        text_lower = text.lower()

        i = 0
        while i < len(text_lower):
            if text_lower[i] != "[":
                i += 1
                continue

            for key in self._emo_map.keys():
                emo_tag = f"[{key}]"
                if text_lower[i:i + len(emo_tag)] == emo_tag:
                    expression_list.append(self._emo_map[key])
                    i += len(emo_tag) - 1
                    break

            i += 1

        return expression_list

    def remove_emotion_tags(self, text: str) -> str:
        """
        移除文本中的情感标签
        
        Args:
            text: 包含情感标签的文本
            
        Returns:
            清理后的文本
        """
        lower_text = text.lower()

        for key in self._emo_map.keys():
            lower_key = f"[{key}]".lower()
            while lower_key in lower_text:
                start_index = lower_text.find(lower_key)
                end_index = start_index + len(lower_key)
                text = text[:start_index] + text[end_index:]
                lower_text = lower_text[:start_index] + lower_text[end_index:]

        return text

    def get_model_config(self, model_name: str = None) -> Dict[str, Any]:
        """
        获取模型配置字典（用于发送到前端）
        
        Args:
            model_name: 模型名称，默认使用当前模型
            
        Returns:
            配置字典
        """
        model = self.get_model_info(model_name) if model_name else self.current_model

        if not model:
            return {}

        return {
            "name": model.name,
            "description": model.description,
            "url": model.url,
            "kScale": model.kScale,
            "initialXshift": model.initialXshift,
            "initialYshift": model.initialYshift,
            "kXOffset": model.kXOffset,
            "idleMotionGroupName": model.idleMotionGroupName,
            "emotionMap": model.emotionMap,
            "tapMotions": model.tapMotions,
        }

    def reload(self):
        """重新加载模型配置"""
        self._models.clear()
        self._current_model_name = None
        self._emo_map = {}
        self._emo_str = ""
        self._load_models()
        logger.info("Model configurations reloaded")


# 全局单例实例
live2d_model_manager = Live2DModelManager()
