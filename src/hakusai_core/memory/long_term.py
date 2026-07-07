"""
HakusAI 2.0 长期记忆实现
基于向量数据库的语义搜索
"""

import os
import json
from typing import List, Optional, Dict, Any
from datetime import datetime
import logging
import numpy as np

from .base import BaseMemory, MemoryEntry, MemoryStorage, MemoryType

logger = logging.getLogger(__name__)


class LongTermMemory(BaseMemory):
    """
    长期记忆
    
    特点：
    - 基于向量数据库，支持语义搜索
    - 持久化存储
    - 支持记忆重要性评分
    """
    
    def __init__(self, config: MemoryStorage):
        super().__init__(config)
        self._memories: Dict[str, MemoryEntry] = {}
        self._embeddings: Dict[str, List[float]] = {}
        self._storage_file = os.path.join(config.data_dir, "long_term.json")
        self._embeddings_file = os.path.join(config.vector_db_path, "embeddings.json")
        
        # 嵌入模型
        self._embedding_model = None
    
    async def initialize(self):
        """初始化长期记忆"""
        # 确保目录存在
        os.makedirs(self.config.data_dir, exist_ok=True)
        os.makedirs(self.config.vector_db_path, exist_ok=True)
        
        # 加载已有数据
        await self._load()
        
        self._initialized = True
        logger.info(f"Long-term memory initialized ({len(self._memories)} entries)")
    
    async def add(self, entry: MemoryEntry) -> str:
        """
        添加记忆
        
        Args:
            entry: 记忆条目
            
        Returns:
            记忆ID
        """
        # 生成嵌入向量
        if not entry.embedding:
            entry.embedding = await self._generate_embedding(entry.content)
        
        # 存储记忆
        self._memories[entry.id] = entry
        self._embeddings[entry.id] = entry.embedding
        
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
        return self._memories.get(memory_id)
    
    async def search(
        self,
        query: str,
        limit: int = 10,
        memory_type: Optional[MemoryType] = None
    ) -> List[MemoryEntry]:
        """
        语义搜索记忆
        
        Args:
            query: 搜索查询
            limit: 返回数量限制
            memory_type: 记忆类型过滤
            
        Returns:
            记忆条目列表
        """
        if not self._memories:
            return []
        
        # 生成查询向量
        query_embedding = await self._generate_embedding(query)
        
        # 计算相似度
        similarities = []
        for memory_id, entry in self._memories.items():
            # 类型过滤
            if memory_type and entry.memory_type != memory_type:
                continue
            
            # 计算余弦相似度
            embedding = self._embeddings.get(memory_id)
            if embedding:
                similarity = self._cosine_similarity(query_embedding, embedding)
                # 结合重要性评分
                score = similarity * (0.7 + 0.3 * entry.importance)
                similarities.append((memory_id, score))
        
        # 按相似度排序
        similarities.sort(key=lambda x: x[1], reverse=True)
        
        # 返回结果
        results = []
        for memory_id, _ in similarities[:limit]:
            results.append(self._memories[memory_id])
        
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
        entries = list(self._memories.values())
        
        # 类型过滤
        if memory_type:
            entries = [e for e in entries if e.memory_type == memory_type]
        
        # 按时间排序
        entries.sort(key=lambda x: x.timestamp, reverse=True)
        
        return entries[:limit]
    
    async def delete(self, memory_id: str) -> bool:
        """
        删除记忆
        
        Args:
            memory_id: 记忆ID
            
        Returns:
            是否成功
        """
        if memory_id not in self._memories:
            return False
        
        del self._memories[memory_id]
        del self._embeddings[memory_id]
        
        await self._save()
        return True
    
    async def clear(self):
        """清空所有记忆"""
        self._memories.clear()
        self._embeddings.clear()
        await self._save()
        logger.info("Long-term memory cleared")
    
    async def close(self):
        """关闭存储连接"""
        await self._save()
        self._initialized = False
        logger.debug("Long-term memory closed")
    
    async def _generate_embedding(self, text: str) -> List[float]:
        """
        生成文本嵌入向量
        
        Args:
            text: 输入文本
            
        Returns:
            嵌入向量
        """
        # 尝试使用sentence-transformers
        try:
            if self._embedding_model is None:
                from sentence_transformers import SentenceTransformer
                self._embedding_model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
            
            embedding = self._embedding_model.encode(text)
            return embedding.tolist()
        except ImportError:
            logger.warning("sentence-transformers not available, using simple embedding")
            return self._simple_embedding(text)
        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            return self._simple_embedding(text)
    
    def _simple_embedding(self, text: str) -> List[float]:
        """
        简单的词袋嵌入（备用方案）
        
        Args:
            text: 输入文本
            
        Returns:
            简单的嵌入向量
        """
        # 创建一个简单的哈希嵌入
        import hashlib
        
        # 归一化文本
        text = text.lower().strip()
        
        # 使用多个哈希函数创建向量
        vector_size = 384  # 与MiniLM相同维度
        embedding = np.zeros(vector_size)
        
        # 分词并哈希
        words = text.split()
        for word in words:
            # 使用MD5哈希
            hash_val = int(hashlib.md5(word.encode()).hexdigest(), 16)
            for i in range(vector_size):
                if (hash_val >> (i % 32)) & 1:
                    embedding[i] += 1
        
        # 归一化
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        
        return embedding.tolist()
    
    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """
        计算余弦相似度
        
        Args:
            a: 向量a
            b: 向量b
            
        Returns:
            相似度 (0-1)
        """
        a = np.array(a)
        b = np.array(b)
        
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return float(np.dot(a, b) / (norm_a * norm_b))
    
    async def _save(self):
        """保存到文件"""
        try:
            # 保存记忆
            memories_data = {
                memory_id: entry.to_dict()
                for memory_id, entry in self._memories.items()
            }
            
            temp_file = self._storage_file + ".tmp"
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(memories_data, f, ensure_ascii=False, indent=2)
            
            if os.path.exists(self._storage_file):
                os.replace(temp_file, self._storage_file)
            else:
                os.rename(temp_file, self._storage_file)
            
            # 保存嵌入向量
            temp_emb_file = self._embeddings_file + ".tmp"
            with open(temp_emb_file, 'w', encoding='utf-8') as f:
                json.dump(self._embeddings, f)
            
            if os.path.exists(self._embeddings_file):
                os.replace(temp_emb_file, self._embeddings_file)
            else:
                os.rename(temp_emb_file, self._embeddings_file)
                
        except Exception as e:
            logger.error(f"Failed to save long-term memory: {e}")
    
    async def _load(self):
        """从文件加载"""
        # 加载记忆
        if os.path.exists(self._storage_file):
            try:
                with open(self._storage_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                for memory_id, item in data.items():
                    self._memories[memory_id] = MemoryEntry.from_dict(item)
                
                logger.info(f"Loaded {len(self._memories)} memories from long-term storage")
            except Exception as e:
                logger.error(f"Failed to load long-term memories: {e}")
        
        # 加载嵌入向量
        if os.path.exists(self._embeddings_file):
            try:
                with open(self._embeddings_file, 'r', encoding='utf-8') as f:
                    self._embeddings = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load embeddings: {e}")
    
    @property
    def size(self) -> int:
        """当前记忆数量"""
        return len(self._memories)
    
    async def consolidate_memories(self, entries: List[MemoryEntry]):
        """
        整合短期记忆到长期记忆
        
        Args:
            entries: 要整合的记忆条目
        """
        for entry in entries:
            # 检查是否已存在
            existing = await self._find_similar(entry.content)
            if existing:
                # 更新重要性
                existing.importance = min(1.0, existing.importance + 0.1)
                await self.add(existing)
            else:
                await self.add(entry)
        
        logger.info(f"Consolidated {len(entries)} memories to long-term storage")
    
    async def _find_similar(self, content: str, threshold: float = 0.95) -> Optional[MemoryEntry]:
        """
        查找相似的记忆
        
        Args:
            content: 内容
            threshold: 相似度阈值
            
        Returns:
            相似的记忆或None
        """
        embedding = await self._generate_embedding(content)
        
        for memory_id, existing_embedding in self._embeddings.items():
            similarity = self._cosine_similarity(embedding, existing_embedding)
            if similarity >= threshold:
                return self._memories.get(memory_id)
        
        return None
