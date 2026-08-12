"""
HakusAI 2.0 短期记忆实现
基于内存的循环缓冲区
"""

import os
import json
from typing import List, Optional, Dict, Any
from collections import deque
from datetime import datetime
import logging

from .base import BaseMemory, MemoryEntry, MemoryStorage, MemoryType

logger = logging.getLogger(__name__)


class ShortTermMemory(BaseMemory):
    """
    短期记忆
    
    特点：
    - 基于内存存储，访问速度快
    - 循环缓冲区，自动丢弃旧记忆
    - 支持持久化到本地文件
    """
    
    def __init__(self, config: MemoryStorage):
        super().__init__(config)
        self._buffer: deque = deque(maxlen=config.max_short_term)
        self._index: Dict[str, MemoryEntry] = {}  # ID索引
        self._storage_file = os.path.join(config.data_dir, "short_term.json")
    
    async def initialize(self):
        """初始化短期记忆"""
        # 确保目录存在
        os.makedirs(self.config.data_dir, exist_ok=True)
        
        # 加载已有数据
        await self._load()
        
        self._initialized = True
        logger.info(f"Short-term memory initialized (capacity: {self.config.max_short_term})")
    
    async def add(self, entry: MemoryEntry) -> str:
        """
        添加记忆
        
        Args:
            entry: 记忆条目
            
        Returns:
            记忆ID
        """
        # 添加到缓冲区
        self._buffer.append(entry)
        
        # 更新索引
        self._index[entry.id] = entry
        
        # 清理过期索引
        self._cleanup_index()
        
        # 持久化
        await self._save()
        
        return entry.id
    
    async def get(self, memory_id: str) -> Optional[MemoryEntry]:
        """
        获取记忆
        
        Args:
            memory_id: 记忆ID
            
        Returns:
            记忆条目或None
        """
        return self._index.get(memory_id)
    
    async def search(
        self,
        query: str,
        limit: int = 10,
        memory_type: Optional[MemoryType] = None
    ) -> List[MemoryEntry]:
        """
        搜索记忆（简单文本匹配）
        
        Args:
            query: 搜索查询
            limit: 返回数量限制
            memory_type: 记忆类型过滤
            
        Returns:
            记忆条目列表
        """
        query_lower = query.lower()
        results = []
        
        for entry in reversed(self._buffer):  # 从新到旧搜索
            # 类型过滤
            if memory_type and entry.memory_type != memory_type:
                continue
            
            # 内容匹配
            if query_lower in entry.content.lower():
                results.append(entry)
                
                if len(results) >= limit:
                    break
        
        return results
    
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
        results = []
        
        for entry in reversed(self._buffer):
            if memory_type and entry.memory_type != memory_type:
                continue
            
            results.append(entry)
            
            if len(results) >= limit:
                break
        
        return results
    
    async def get_context_for_model(
        self,
        max_messages: int = 20,
        include_system: bool = True
    ) -> List[Dict[str, str]]:
        """
        获取用于模型对话的上下文
        
        Args:
            max_messages: 最大消息数
            include_system: 是否包含系统消息
            
        Returns:
            消息列表，格式为 [{"role": "user", "content": "..."}, ...]
        """
        messages = []
        count = 0
        
        for entry in reversed(self._buffer):
            if entry.memory_type == MemoryType.MESSAGE:
                # 跳过系统消息（如果不需要）
                if entry.role == "system" and not include_system:
                    continue
                
                messages.insert(0, {
                    "role": entry.role,
                    "content": entry.content,
                })
                
                count += 1
                if count >= max_messages:
                    break
        
        return messages
    
    async def delete(self, memory_id: str) -> bool:
        """
        删除记忆
        
        Args:
            memory_id: 记忆ID
            
        Returns:
            是否成功
        """
        if memory_id not in self._index:
            return False
        
        # 从索引中移除
        del self._index[memory_id]
        
        # 重建缓冲区
        new_buffer = deque(maxlen=self.config.max_short_term)
        for entry in self._buffer:
            if entry.id != memory_id:
                new_buffer.append(entry)
        
        self._buffer = new_buffer
        
        # 持久化
        await self._save()
        
        return True
    
    async def clear(self):
        """清空所有记忆"""
        self._buffer.clear()
        self._index.clear()
        await self._save()
        logger.info("Short-term memory cleared")
    
    async def close(self):
        """关闭存储连接"""
        await self._save()
        self._initialized = False
        logger.debug("Short-term memory closed")
    
    def _cleanup_index(self):
        """清理过期索引"""
        valid_ids = {entry.id for entry in self._buffer}
        self._index = {k: v for k, v in self._index.items() if k in valid_ids}
    
    async def _save(self):
        """保存到文件"""
        try:
            data = [entry.to_dict() for entry in self._buffer]
            
            # 使用临时文件保证原子性
            temp_file = self._storage_file + ".tmp"
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            # 原子替换
            if os.path.exists(self._storage_file):
                os.replace(temp_file, self._storage_file)
            else:
                os.rename(temp_file, self._storage_file)
                
        except Exception as e:
            logger.error(f"Failed to save short-term memory: {e}")
    
    async def _load(self):
        """从文件加载"""
        if not os.path.exists(self._storage_file):
            return
        
        try:
            with open(self._storage_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            for item in data:
                entry = MemoryEntry.from_dict(item)
                self._buffer.append(entry)
                self._index[entry.id] = entry
            
            logger.info(f"Loaded {len(self._buffer)} entries from short-term memory")
            
        except Exception as e:
            logger.error(f"Failed to load short-term memory: {e}")
    
    @property
    def size(self) -> int:
        """当前记忆数量"""
        return len(self._buffer)
    
    @property
    def is_full(self) -> bool:
        """是否已满"""
        return len(self._buffer) >= self.config.max_short_term
