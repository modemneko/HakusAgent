"""
HakusAI 2.0 记忆管理器
整合短期记忆和长期记忆
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
import logging

from .base import MemoryEntry, MemoryStorage, MemoryType
from .short_term import ShortTermMemory
from .long_term import LongTermMemory

logger = logging.getLogger(__name__)


class MemoryManager:
    """
    记忆管理器
    
    负责：
    - 管理短期记忆和长期记忆
    - 自动总结和整合
    - 提供统一的记忆访问接口
    """
    
    def __init__(self, config: MemoryStorage):
        self.config = config
        self.short_term = ShortTermMemory(config)
        self.long_term = LongTermMemory(config)
        
        # 总结计数器
        self._message_count = 0
        
        # 是否已初始化
        self._initialized = False
    
    async def initialize(self):
        """初始化记忆管理器"""
        await self.short_term.initialize()
        
        if self.config.enable_long_term:
            await self.long_term.initialize()
        
        self._initialized = True
        logger.info("Memory manager initialized")
    
    async def add_message(
        self,
        role: str,
        content: str,
        importance: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        添加对话消息
        
        Args:
            role: 角色 (user/assistant/system)
            content: 内容
            importance: 重要性
            metadata: 元数据
            
        Returns:
            记忆ID
        """
        entry = MemoryEntry(
            content=content,
            role=role,
            memory_type=MemoryType.MESSAGE,
            importance=importance,
            metadata=metadata or {},
        )
        
        # 添加到短期记忆
        memory_id = await self.short_term.add(entry)
        
        # 检查是否需要总结
        if self.config.auto_summary:
            self._message_count += 1
            if self._message_count >= self.config.summary_interval:
                await self._summarize_and_consolidate()
                self._message_count = 0
        
        return memory_id
    
    async def add_fact(
        self,
        content: str,
        importance: float = 0.8,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        添加事实记忆
        
        Args:
            content: 内容
            importance: 重要性
            metadata: 元数据
            
        Returns:
            记忆ID
        """
        entry = MemoryEntry(
            content=content,
            role="system",
            memory_type=MemoryType.FACT,
            importance=importance,
            metadata=metadata or {},
        )
        
        # 直接添加到长期记忆
        if self.config.enable_long_term:
            return await self.long_term.add(entry)
        else:
            return await self.short_term.add(entry)
    
    async def add_event(
        self,
        content: str,
        importance: float = 0.9,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        添加事件记忆
        
        Args:
            content: 内容
            importance: 重要性
            metadata: 元数据
            
        Returns:
            记忆ID
        """
        entry = MemoryEntry(
            content=content,
            role="system",
            memory_type=MemoryType.EVENT,
            importance=importance,
            metadata=metadata or {},
        )
        
        # 直接添加到长期记忆
        if self.config.enable_long_term:
            return await self.long_term.add(entry)
        else:
            return await self.short_term.add(entry)
    
    async def get_context_for_model(
        self,
        max_short_term: int = 20,
        max_long_term: int = 5,
        query: Optional[str] = None
    ) -> List[Dict[str, str]]:
        """
        获取用于模型对话的上下文
        
        Args:
            max_short_term: 短期记忆数量
            max_long_term: 长期记忆数量
            query: 查询（用于检索相关长期记忆）
            
        Returns:
            消息列表
        """
        messages = []
        
        # 添加相关的长期记忆作为上下文
        if self.config.enable_long_term and max_long_term > 0:
            if query:
                # 基于查询搜索
                relevant = await self.long_term.search(query, limit=max_long_term)
            else:
                # 获取最近的
                relevant = await self.long_term.get_recent(limit=max_long_term)
            
            for entry in relevant:
                if entry.memory_type in [MemoryType.FACT, MemoryType.EVENT]:
                    messages.append({
                        "role": "system",
                        "content": f"[记忆] {entry.content}",
                    })
        
        # 添加短期记忆
        short_term_messages = await self.short_term.get_context_for_model(
            max_messages=max_short_term,
            include_system=False
        )
        messages.extend(short_term_messages)
        
        return messages
    
    async def search(
        self,
        query: str,
        limit: int = 10,
        search_long_term: bool = True
    ) -> List[MemoryEntry]:
        """
        搜索记忆
        
        Args:
            query: 查询
            limit: 数量限制
            search_long_term: 是否搜索长期记忆
            
        Returns:
            记忆条目列表
        """
        results = []
        
        # 搜索短期记忆
        short_results = await self.short_term.search(query, limit=limit)
        results.extend(short_results)
        
        # 搜索长期记忆
        if self.config.enable_long_term and search_long_term:
            long_limit = max(1, limit - len(results))
            long_results = await self.long_term.search(query, limit=long_limit)
            results.extend(long_results)
        
        # 去重并排序
        seen_ids = set()
        unique_results = []
        for entry in results:
            if entry.id not in seen_ids:
                seen_ids.add(entry.id)
                unique_results.append(entry)
        
        return unique_results[:limit]
    
    async def get_recent(
        self,
        limit: int = 10,
        memory_type: Optional[MemoryType] = None
    ) -> List[MemoryEntry]:
        """
        获取最近的记忆
        
        Args:
            limit: 数量限制
            memory_type: 记忆类型
            
        Returns:
            记忆条目列表
        """
        return await self.short_term.get_recent(limit=limit, memory_type=memory_type)
    
    async def _summarize_and_consolidate(self):
        """总结并整合记忆到长期记忆"""
        if not self.config.enable_long_term:
            return
        
        logger.info("Summarizing and consolidating memories...")
        
        # 获取需要总结的记忆
        entries = await self.short_term.get_recent(limit=self.config.summary_interval)
        
        if len(entries) < 3:
            return
        
        # 筛选重要记忆
        important_entries = [
            e for e in entries
            if e.importance >= 0.7 or e.memory_type != MemoryType.MESSAGE
        ]
        
        if important_entries:
            # 整合到长期记忆
            await self.long_term.consolidate_memories(important_entries)
            logger.info(f"Consolidated {len(important_entries)} important memories")
    
    async def clear(self, clear_long_term: bool = False):
        """
        清空记忆
        
        Args:
            clear_long_term: 是否也清空长期记忆
        """
        await self.short_term.clear()
        
        if clear_long_term and self.config.enable_long_term:
            await self.long_term.clear()
        
        self._message_count = 0
        logger.info("Memory cleared")
    
    async def close(self):
        """关闭记忆管理器"""
        await self.short_term.close()
        
        if self.config.enable_long_term:
            await self.long_term.close()
        
        self._initialized = False
        logger.debug("Memory manager closed")
    
    @property
    def stats(self) -> Dict[str, int]:
        """获取记忆统计"""
        return {
            "short_term": self.short_term.size,
            "long_term": self.long_term.size if self.config.enable_long_term else 0,
        }
