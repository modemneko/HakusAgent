"""
HakusAI 2.0 记忆系统基类
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import uuid
import logging

logger = logging.getLogger(__name__)


class MemoryType(str, Enum):
    """记忆类型"""
    MESSAGE = "message"  # 对话消息
    SUMMARY = "summary"  # 总结
    FACT = "fact"        # 事实
    EMOTION = "emotion"  # 情感
    EVENT = "event"      # 事件


@dataclass
class MemoryEntry:
    """记忆条目"""
    content: str
    role: str  # user / assistant / system
    memory_type: MemoryType = MemoryType.MESSAGE
    timestamp: datetime = field(default_factory=datetime.now)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    importance: float = 1.0  # 重要性评分 (0-1)
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None  # 向量嵌入
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "content": self.content,
            "role": self.role,
            "memory_type": self.memory_type.value,
            "timestamp": self.timestamp.isoformat(),
            "importance": self.importance,
            "metadata": self.metadata,
            "embedding": self.embedding,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryEntry":
        """从字典创建"""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            content=data["content"],
            role=data["role"],
            memory_type=MemoryType(data.get("memory_type", "message")),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            importance=data.get("importance", 1.0),
            metadata=data.get("metadata", {}),
            embedding=data.get("embedding"),
        )


@dataclass
class MemoryStorage:
    """记忆存储配置"""
    storage_type: str = "local"  # local, redis, etc.
    data_dir: str = "data/memories"
    max_short_term: int = 50
    enable_long_term: bool = True
    vector_db_path: str = "data/memories/vectors"
    auto_summary: bool = True
    summary_interval: int = 10


class BaseMemory(ABC):
    """记忆基类"""
    
    def __init__(self, config: MemoryStorage):
        self.config = config
        self._initialized = False
    
    @abstractmethod
    async def initialize(self):
        """初始化存储"""
        pass
    
    @abstractmethod
    async def add(self, entry: MemoryEntry) -> str:
        """
        添加记忆
        
        Args:
            entry: 记忆条目
            
        Returns:
            记忆ID
        """
        pass
    
    @abstractmethod
    async def get(self, memory_id: str) -> Optional[MemoryEntry]:
        """
        获取记忆
        
        Args:
            memory_id: 记忆ID
            
        Returns:
            记忆条目或None
        """
        pass
    
    @abstractmethod
    async def search(
        self,
        query: str,
        limit: int = 10,
        memory_type: Optional[MemoryType] = None
    ) -> List[MemoryEntry]:
        """
        搜索记忆
        
        Args:
            query: 搜索查询
            limit: 返回数量限制
            memory_type: 记忆类型过滤
            
        Returns:
            记忆条目列表
        """
        pass
    
    @abstractmethod
    async def get_recent(
        self,
        limit: int = 10,
        memory_type: Optional[MemoryType] = None
    ) -> List[MemoryEntry]:
        """
        获取最近的记忆
        
        Args:
            limit: 返回数量限制
            memory_type: 记忆类型过滤
            
        Returns:
            记忆条目列表
        """
        pass
    
    @abstractmethod
    async def delete(self, memory_id: str) -> bool:
        """
        删除记忆
        
        Args:
            memory_id: 记忆ID
            
        Returns:
            是否成功
        """
        pass
    
    @abstractmethod
    async def clear(self):
        """清空所有记忆"""
        pass
    
    @abstractmethod
    async def close(self):
        """关闭存储连接"""
        pass
    
    async def update_importance(self, memory_id: str, importance: float):
        """
        更新记忆重要性
        
        Args:
            memory_id: 记忆ID
            importance: 新的重要性评分
        """
        entry = await self.get(memory_id)
        if entry:
            entry.importance = max(0.0, min(1.0, importance))
            # 重新保存
            await self.add(entry)
