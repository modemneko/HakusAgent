import os
import json
import time
import threading
import math
import numpy as np
import asyncio
import re
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
from pathlib import Path

from langchain_core.documents import Document
from langchain_chroma import Chroma

# 检查Faiss是否可用
faiss_available = False
try:
    import faiss
    faiss_available = True
except ImportError:
    faiss_available = False

# 导入jieba并初始化
_has_jieba = False
try:
    import jieba
    import jieba.analyse
    _has_jieba = True
except ImportError:
    _has_jieba = False

# 尝试导入各种Embedding模型
has_google_embedding = False
has_openai_embedding = False
has_glm_embedding = False
has_dashscope_embedding = False

try:
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
    has_google_embedding = True
except ImportError:
    pass

try:
    from langchain_openai import OpenAIEmbeddings
    has_openai_embedding = True
except ImportError:
    pass

try:
    from langchain_community.embeddings import ZhipuAIEmbeddings
    has_glm_embedding = True
except ImportError:
    pass

try:
    from langchain_community.embeddings import DashScopeEmbeddings
    has_dashscope_embedding = True
except ImportError:
    pass

from utils.config import BASE_CONFIG
from utils.logger import get_logger

logger = get_logger(__name__)

# 全局嵌入模型单例
_GLOBAL_EMBEDDING = None
_EMBEDDING_LOCK = threading.Lock()


def get_embedding() -> Any:
    """获取全局嵌入模型实例 - 支持多平台"""
    global _GLOBAL_EMBEDDING

    if not BASE_CONFIG.get("MEMORY_ENABLED", False):
        logger.debug("Memory disabled; skipping embedding initialization")
        raise ImportError("Memory system is disabled in config")

    with _EMBEDDING_LOCK:
        if _GLOBAL_EMBEDDING is None:
            embedding_type = BASE_CONFIG.get("EMBEDDING_TYPE", "google").lower()
            logger.info(f"正在加载 Embedding 模型，类型: {embedding_type}")
            start_time = time.time()

            try:
                if embedding_type == "google":
                    _GLOBAL_EMBEDDING = _init_google_embedding()
                elif embedding_type == "openai":
                    _GLOBAL_EMBEDDING = _init_openai_embedding()
                elif embedding_type == "glm":
                    _GLOBAL_EMBEDDING = _init_glm_embedding()
                elif embedding_type == "dashscope":
                    _GLOBAL_EMBEDDING = _init_dashscope_embedding()
                else:
                    # 默认使用Google
                    logger.warning(f"未知的Embedding类型: {embedding_type}，使用默认的Google Embedding")
                    _GLOBAL_EMBEDDING = _init_google_embedding()

                elapsed = time.time() - start_time
                logger.info(f"✓ Embedding 模型加载完成 (类型: {embedding_type}, 耗时: {elapsed:.2f}秒)")
            except Exception as e:
                logger.debug(f"Embedding 模型加载失败: {e}")
                raise ImportError(f"无法加载 Embedding 模型: {e}")

    return _GLOBAL_EMBEDDING


def _init_google_embedding():
    """初始化 Google Embedding"""
    if not has_google_embedding:
        raise ImportError("Google Embedding库未安装，请安装 langchain_google_genai")
    
    if not BASE_CONFIG.get("GEMINI_API_KEY"):
        raise ImportError("GEMINI_API_KEY 未配置")
    
    logger.info("正在加载 Google Generative AI Embeddings 模型...")
    embedding = GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        google_api_key=BASE_CONFIG["GEMINI_API_KEY"]
    )
    logger.info("成功加载 Google Generative AI Embeddings 模型")
    return embedding


def _init_openai_embedding():
    """初始化 OpenAI Embedding"""
    if not has_openai_embedding:
        raise ImportError("OpenAI Embedding库未安装，请安装 langchain_openai")
    
    if not BASE_CONFIG.get("OPENAI_API_KEY"):
        raise ImportError("OPENAI_API_KEY 未配置")
    
    logger.info("正在加载 OpenAI Embeddings 模型...")
    embedding = OpenAIEmbeddings(
        model=BASE_CONFIG.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
        api_key=BASE_CONFIG["OPENAI_API_KEY"],
        base_url=BASE_CONFIG.get("OPENAI_BASE_URL")
    )
    logger.info("成功加载 OpenAI Embeddings 模型")
    return embedding


def _init_glm_embedding():
    """初始化 GLM (智谱AI) Embedding"""
    if not has_glm_embedding:
        raise ImportError("GLM Embedding库未安装，请安装 langchain-community")
    
    if not BASE_CONFIG.get("GLM_API_KEY"):
        raise ImportError("GLM_API_KEY 未配置")
    
    logger.info("正在加载 GLM (智谱AI) Embeddings 模型...")
    embedding = ZhipuAIEmbeddings(
        model=BASE_CONFIG.get("GLM_EMBEDDING_MODEL", "embedding-3"),
        api_key=BASE_CONFIG["GLM_API_KEY"]
    )
    logger.info("成功加载 GLM Embeddings 模型")
    return embedding


def _init_dashscope_embedding():
    """初始化 DashScope (阿里) Embedding"""
    if not has_dashscope_embedding:
        raise ImportError("DashScope Embedding库未安装，请安装 langchain-community")
    
    if not BASE_CONFIG.get("DASHSCOPE_API_KEY"):
        raise ImportError("DASHSCOPE_API_KEY 未配置")
    
    logger.info("正在加载 DashScope (阿里) Embeddings 模型...")
    embedding = DashScopeEmbeddings(
        model=BASE_CONFIG.get("DASHSCOPE_EMBEDDING_MODEL", "text-embedding-v2"),
        dashscope_api_key=BASE_CONFIG["DASHSCOPE_API_KEY"]
    )
    logger.info("成功加载 DashScope Embeddings 模型")
    return embedding



class PageStore:
    """Stores complete conversation pages with semantic headers.

    Each page preserves the full original conversation text alongside
    a header (semantic summary) for efficient retrieval. This avoids
    the information loss of compressing conversations into 80-120 char
    diary summaries.

    Storage: ~/.hakus/pages/{uid}/{session_id}.json
    """

    def __init__(self, uid: str):
        self._uid = uid
        self._pages_dir = Path(os.path.expanduser("~")) / ".hakus" / "pages" / uid
        self._pages_dir.mkdir(parents=True, exist_ok=True)
        # In-memory index: {session_id: {"header": str, "timestamp": str}}
        self._index: Dict[str, Dict] = {}
        self._load_index()

    def _load_index(self):
        """Load the header index from disk."""
        index_path = self._pages_dir / "_index.json"
        if index_path.exists():
            try:
                with open(index_path, "r", encoding="utf-8") as f:
                    self._index = json.load(f)
            except Exception:
                self._index = {}

    def _save_index(self):
        """Save the header index to disk."""
        index_path = self._pages_dir / "_index.json"
        try:
            with open(index_path, "w", encoding="utf-8") as f:
                json.dump(self._index, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def add_page(self, session_id: str, header: str, content: str, timestamp: str = None):
        """Add a page to the store.

        Args:
            session_id: Unique session/conversation identifier
            header: Semantic summary (50-80 chars) for retrieval
            content: Full original conversation text
            timestamp: ISO format timestamp (default: now)
        """
        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        page_data = {
            "session_id": session_id,
            "header": header,
            "content": content,
            "timestamp": timestamp,
        }

        # Save full page
        page_path = self._pages_dir / f"{session_id}.json"
        try:
            with open(page_path, "w", encoding="utf-8") as f:
                json.dump(page_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save page {session_id}: {e}")
            return

        # Update index
        self._index[session_id] = {
            "header": header,
            "timestamp": timestamp,
        }
        self._save_index()

    def get_page(self, session_id: str) -> Optional[Dict]:
        """Get a full page by session_id."""
        page_path = self._pages_dir / f"{session_id}.json"
        if not page_path.exists():
            return None
        try:
            with open(page_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def search_headers(self, query: str, top_k: int = 5) -> List[Dict]:
        """Search pages by header text using keyword matching.

        Returns list of dicts with keys: session_id, header, timestamp, score
        """
        if _has_jieba:
            query_tokens = set(jieba.cut(query))
        else:
            query_tokens = set(query.lower().split())

        results = []
        for sid, info in self._index.items():
            header = info.get("header", "")
            if _has_jieba:
                header_tokens = set(jieba.cut(header))
            else:
                header_tokens = set(header.lower().split())

            # Simple token overlap score
            overlap = len(query_tokens & header_tokens)
            if overlap > 0:
                score = overlap / max(len(query_tokens), 1)
                results.append({
                    "session_id": sid,
                    "header": header,
                    "timestamp": info.get("timestamp", ""),
                    "score": score,
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def get_page_content(self, session_id: str, max_chars: int = 500) -> Optional[str]:
        """Get truncated page content for context injection."""
        page = self.get_page(session_id)
        if not page:
            return None
        content = page.get("content", "")
        if len(content) > max_chars:
            return content[:max_chars] + "..."
        return content


class MemoryManager:
    """记忆管理类，处理短期记忆和长期记忆"""
    
    def __init__(self, uid: str, lazy_init: bool = True):
        self.uid = uid
        self.short_term_memory: List[Dict[str, str]] = []
        
        # 延迟初始化标志
        self._lazy_init = lazy_init
        self._initialized = False
        
        # 长期记忆相关
        self.long_term_memory = None
        self.long_term_memory_ready = False
        
        # Faiss索引相关
        self.faiss_index = None
        self.faiss_embeddings = None
        self.faiss_documents = []
        self._faiss_doc_ids = set()  # 跟踪已同步到Faiss的文档ID
        
        # 后台搜索相关
        self._background_search_cache = {}  # 缓存搜索结果，避免重复搜索
        self._last_search_time = 0  # 上次搜索时间
        self._search_cooldown = 300  # 搜索冷却时间（秒）
        
        # PageStore（延迟初始化）
        self._page_store: Optional[PageStore] = None
        
        # 如果不是延迟初始化，立即初始化
        if not lazy_init:
            self._ensure_initialized()
        
        # 短期记忆立即加载（轻量级）
        self._load_short_term_memory()
    
    @property
    def page_store(self) -> PageStore:
        """懒加载 PageStore 实例"""
        if self._page_store is None:
            self._page_store = PageStore(self.uid)
        return self._page_store
    
    def _ensure_initialized(self):
        """确保已初始化（延迟初始化用）"""
        if self._initialized:
            return
        
        try:
            self.long_term_memory = self._init_long_term_memory()
            self.long_term_memory_ready = True
        except Exception as e:
            logger.error(f"UID:{self.uid} - 初始化长期记忆失败: {e}")
            self.long_term_memory = None
            self.long_term_memory_ready = False
        
        # 初始化Faiss索引
        if faiss_available:
            self._init_faiss_index()
        
        self._initialized = True
    
    def _init_long_term_memory(self):
        """初始化长期记忆（向量数据库）"""
        persist_dir = os.path.join(BASE_CONFIG["MEMORY_DB_DIR"], f"user_{self.uid}")
        os.makedirs(persist_dir, exist_ok=True)
        
        return Chroma(
            collection_name=f"user_{self.uid}_memory",
            embedding_function=get_embedding(),
            persist_directory=persist_dir
        )
    
    def _init_faiss_index(self):
        """初始化Faiss索引 - 不立即同步，延迟到后台"""
        if not faiss_available:
            return
            
        try:
            # 获取嵌入维度
            embedding_model = get_embedding()
            dummy_embedding = embedding_model.embed_query("测试")
            embedding_dim = len(dummy_embedding)
            
            # 创建Faiss索引
            self.faiss_index = faiss.IndexFlatL2(embedding_dim)
            
            # 不立即同步，标记为需要同步
            self._faiss_needs_sync = True
            self._faiss_sync_in_progress = False
                
            logger.info(f"UID:{self.uid} - Faiss索引初始化成功（延迟同步）")
        except Exception as e:
            logger.error(f"UID:{self.uid} - Faiss索引初始化失败: {e}")
            self.faiss_index = None
            self._faiss_needs_sync = False
    
    def _delete_from_chroma(self, doc_id: str) -> bool:
        """通过文档ID从Chroma中删除文档"""
        try:
            self.long_term_memory.delete(ids=[doc_id])
            return True
        except Exception as e:
            logger.warning(f"UID:{self.uid} - 从Chroma删除文档 {doc_id} 失败: {e}")
            return False

    async def _sync_faiss_async(self):
        """后台异步同步Faiss索引"""
        if (not self._faiss_needs_sync or 
            self._faiss_sync_in_progress or 
            not self.faiss_index or
            not self.long_term_memory_ready):
            return
        
        self._faiss_sync_in_progress = True
        try:
            # 在后台线程中执行同步
            import asyncio
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._sync_with_long_term_memory)
            self._faiss_needs_sync = False
            logger.info(f"UID:{self.uid} - Faiss索引后台同步完成")
        except Exception as e:
            logger.error(f"UID:{self.uid} - Faiss索引后台同步失败: {e}")
        finally:
            self._faiss_sync_in_progress = False
    
    def _sync_with_long_term_memory(self):
        """将长期记忆增量同步到Faiss索引"""
        if not self.long_term_memory_ready or not self.long_term_memory or not self.faiss_index:
            return

        try:
            # 获取Chroma中所有文档
            all_docs = self.long_term_memory.get()
            if not all_docs or not all_docs["ids"]:
                # Chroma为空，清空Faiss索引
                self.faiss_index.reset()
                self.faiss_documents = []
                self.faiss_embeddings = None
                self._faiss_doc_ids = set()
                return

            chroma_ids = set(all_docs["ids"])

            # 1. 移除Faiss中已不存在于Chroma的文档
            ids_to_remove = self._faiss_doc_ids - chroma_ids
            if ids_to_remove:
                # Faiss IndexFlatL2不支持按ID删除，需要重建
                # 但只在有删除时才重建，避免频繁全量重建
                remaining_ids = self._faiss_doc_ids & chroma_ids
                # 收集仍需保留的文档
                new_faiss_documents = []
                new_embeddings = []
                for i, doc_id in enumerate(all_docs["ids"]):
                    if doc_id in remaining_ids:
                        doc = Document(
                            page_content=all_docs["documents"][i],
                            metadata=all_docs["metadatas"][i]
                        )
                        new_faiss_documents.append(doc)
                        embedding = get_embedding().embed_query(doc.page_content)
                        new_embeddings.append(embedding)

                # 重建Faiss索引
                self.faiss_documents = new_faiss_documents
                if new_embeddings:
                    self.faiss_embeddings = np.array(new_embeddings).astype('float32')
                    self.faiss_index.reset()
                    self.faiss_index.add(self.faiss_embeddings)
                else:
                    self.faiss_index.reset()
                    self.faiss_embeddings = None

                self._faiss_doc_ids = remaining_ids
                logger.info(f"UID:{self.uid} - Faiss索引移除 {len(ids_to_remove)} 个过期文档")

            # 2. 添加Chroma中有但Faiss中没有的新文档
            ids_to_add = chroma_ids - self._faiss_doc_ids
            if ids_to_add:
                new_docs = []
                new_embeddings = []
                for i, doc_id in enumerate(all_docs["ids"]):
                    if doc_id in ids_to_add:
                        doc = Document(
                            page_content=all_docs["documents"][i],
                            metadata=all_docs["metadatas"][i]
                        )
                        new_docs.append(doc)
                        embedding = get_embedding().embed_query(doc.page_content)
                        new_embeddings.append(embedding)

                if new_embeddings:
                    self.faiss_documents.extend(new_docs)
                    new_embeddings_np = np.array(new_embeddings).astype('float32')
                    self.faiss_index.add(new_embeddings_np)
                    if self.faiss_embeddings is not None:
                        self.faiss_embeddings = np.vstack([self.faiss_embeddings, new_embeddings_np])
                    else:
                        self.faiss_embeddings = new_embeddings_np

                self._faiss_doc_ids.update(ids_to_add)
                logger.info(f"UID:{self.uid} - Faiss索引增量添加 {len(ids_to_add)} 个新文档")

            if not ids_to_remove and not ids_to_add:
                logger.debug(f"UID:{self.uid} - Faiss索引无需同步，已是最新")

        except Exception as e:
            logger.error(f"UID:{self.uid} - 同步Faiss索引失败: {e}")
    
    def _load_short_term_memory(self):
        """加载短期记忆（对话历史）"""
        filepath = os.path.join(BASE_CONFIG["STATE_DIR"], f"user_{self.uid}.json")
        
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.short_term_memory = data.get("history", [])
            except Exception as e:
                logger.warning(f"UID:{self.uid} - 加载短期记忆失败: {e}")
                self.short_term_memory = []
    
    def _save_short_term_memory(self):
        """保存短期记忆"""
        try:
            filepath = os.path.join(BASE_CONFIG["STATE_DIR"], f"user_{self.uid}.json")
            data = {
                "uid": self.uid,
                "history": self.short_term_memory[-BASE_CONFIG["SHORT_TERM_MEMORY_MAX_LENGTH"]:],
                "timestamp": time.time()
            }
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"UID:{self.uid} - 保存短期记忆失败: {e}")
    
    def add_short_term_memory(self, query: str, response: str):
        """添加短期记忆"""
        memory_item = {
            "query": query,
            "response": response,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "archived": False  # 标记是否已归档总结
        }
        
        self.short_term_memory.append(memory_item)
        
        # 限制短期记忆长度
        if len(self.short_term_memory) > BASE_CONFIG["SHORT_TERM_MEMORY_MAX_LENGTH"]:
            self.short_term_memory = self.short_term_memory[-BASE_CONFIG["SHORT_TERM_MEMORY_MAX_LENGTH"]:]
        
        self._save_short_term_memory()
    
    def add_long_term_memory(self, query: str, response: str, key_info: str = ""):
        """添加长期记忆，并限制最大数量 - 支持记忆更新"""
        # 延迟初始化
        self._ensure_initialized()
        
        try:
            if not self.long_term_memory_ready or self.long_term_memory is None:
                logger.warning(f"UID:{self.uid} - 长期记忆功能不可用，跳过添加长期记忆")
                return
            
            # 检查是否需要更新现有记忆而不是创建新记忆
            existing_docs = self.long_term_memory.similarity_search(query, k=3)
            
            # 定义相似度阈值（如果找到高度相似的记忆，则更新）
            UPDATE_THRESHOLD = 0.8
            doc_to_update = None
            
            if existing_docs:
                # 计算与查询的相似度
                from sklearn.metrics.pairwise import cosine_similarity
                import numpy as np
                
                # 只计算一次查询的嵌入
                query_embedding = get_embedding().embed_query(query)
                query_embedding_np = np.array(query_embedding).reshape(1, -1)
                
                for doc in existing_docs:
                    # 计算文档的嵌入
                    doc_content = doc.page_content
                    doc_embedding = get_embedding().embed_query(doc_content)
                    doc_embedding_np = np.array(doc_embedding).reshape(1, -1)
                    
                    # 计算余弦相似度
                    similarity = cosine_similarity(query_embedding_np, doc_embedding_np)[0][0]
                    
                    if similarity >= UPDATE_THRESHOLD:
                        doc_to_update = doc
                        logger.debug(f"UID:{self.uid} - 找到相似记忆，将进行更新 (相似度: {similarity:.2f})")
                        break
            
            if doc_to_update:
                # 更新现有记忆
                dialogue = f"用户: {query}\n羽汐: {response}"

                # 提取关键信息
                if not key_info or key_info == "无":
                    key_info = self.extract_key_info(dialogue)

                # 计算新的重要性评分
                importance = self._calculate_importance_score(query, response, key_info)

                # 合并新旧关键信息
                old_key_info = doc_to_update.metadata.get("key_info", "无")
                if old_key_info and old_key_info != "无" and old_key_info != key_info:
                    # 合并不重复的关键信息 - 统一使用英文分号分隔
                    # 先处理旧关键信息
                    if "；" in old_key_info:
                        old_parts = old_key_info.split("；")
                    elif ";" in old_key_info:
                        old_parts = old_key_info.split(";")
                    else:
                        old_parts = [old_key_info]

                    # 再处理新关键信息
                    if "；" in key_info:
                        new_parts = key_info.split("；")
                    elif ";" in key_info:
                        new_parts = key_info.split(";")
                    else:
                        new_parts = [key_info]

                    # 合并去重
                    merged_parts = list(set(old_parts + new_parts))
                    # 过滤掉空字符串
                    merged_parts = [part.strip() for part in merged_parts if part.strip()]
                    key_info = "; ".join(merged_parts)

                # 生成标签
                tags = self._generate_tags(key_info, query, response)

                # 确定记忆类型
                memory_type = self._determine_memory_type(key_info, query, response)

                # 收集所有需要删除的旧文档ID（内容与doc_to_update匹配的文档）
                old_doc_ids = []
                all_chroma_docs = self.long_term_memory.get()
                if all_chroma_docs and all_chroma_docs["ids"]:
                    for i, chroma_id in enumerate(all_chroma_docs["ids"]):
                        if all_chroma_docs["documents"][i] == doc_to_update.page_content:
                            old_doc_ids.append(chroma_id)

                # 先删除旧文档，再添加新合并的文档
                for old_id in old_doc_ids:
                    if self._delete_from_chroma(old_id):
                        logger.debug(f"UID:{self.uid} - 已删除旧记忆文档: {old_id}")
                        # 同时从Faiss索引中移除
                        if old_id in self._faiss_doc_ids:
                            self._faiss_doc_ids.discard(old_id)

                # 更新文档
                updated_doc = Document(
                    page_content=dialogue,
                    metadata={
                        "type": "dialogue",
                        "memory_type": memory_type,  # 添加记忆类型
                        "timestamp": time.time(),  # 更新时间戳
                        "importance": max(importance, doc_to_update.metadata.get("importance", 0.5)),  # 保留最高重要性
                        "key_info": key_info,
                        "user_query": query,
                        "agent_response": response,
                        "updated_count": doc_to_update.metadata.get("updated_count", 0) + 1,  # 增加更新次数
                        "tags": "; ".join(tags)  # 将标签列表转换为字符串
                    }
                )

                self.long_term_memory.add_documents([updated_doc])
                logger.info(f"UID:{self.uid} - 更新长期记忆成功 (重要性: {importance:.2f}, 删除旧文档: {len(old_doc_ids)})")
            else:
                # 创建新记忆
                dialogue = f"用户: {query}\n羽汐: {response}"
                
                # 提取关键信息
                if not key_info or key_info == "无":
                    key_info = self.extract_key_info(dialogue)
                
                # 计算记忆重要性评分
                importance = self._calculate_importance_score(query, response, key_info)
                
                # 生成标签
                tags = self._generate_tags(key_info, query, response)
                
                # 确定记忆类型
                memory_type = self._determine_memory_type(key_info, query, response)
                
                doc = Document(
                    page_content=dialogue,
                    metadata={
                        "type": "dialogue",
                        "memory_type": memory_type,  # 添加记忆类型
                        "timestamp": time.time(),
                        "importance": importance,
                        "key_info": key_info,
                        "user_query": query,
                        "agent_response": response,
                        "updated_count": 0,
                        "tags": "; ".join(tags)  # 将标签列表转换为字符串
                    }
                )
                
                self.long_term_memory.add_documents([doc])
                logger.info(f"UID:{self.uid} - 添加长期记忆成功 (重要性: {importance:.2f})")
            
            # 检查并限制长期记忆数量
            self._limit_long_term_memory()
            
            # Also save full conversation to page-store
            try:
                timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S")
                self.page_store.add_page(
                    session_id=f"session_{int(time.time())}",
                    header=key_info[:80] if key_info and key_info != "无" else query[:80],
                    content=f"User: {query}\nAgent: {response}",
                    timestamp=timestamp_str,
                )
            except Exception:
                pass  # Don't fail the main flow if page-store fails
            
            # 标记Faiss需要同步（不立即同步，由后台异步处理）
            if self.faiss_index:
                self._faiss_needs_sync = True
                logger.debug(f"UID:{self.uid} - 标记Faiss索引需要同步")
        except Exception as e:
            logger.error(f"UID:{self.uid} - 添加长期记忆失败: {e}")
    
    def _limit_long_term_memory(self):
        """限制长期记忆数量，当超过最大值时删除最不重要的记忆（优先删除临时记忆）"""
        try:
            # 检查长期记忆是否可用
            if not self.long_term_memory_ready or self.long_term_memory is None:
                logger.warning(f"UID:{self.uid} - 长期记忆功能不可用，跳过限制记忆数量")
                return
            
            # 获取当前所有记忆
            all_docs = self.long_term_memory.get()
            total_docs = len(all_docs["ids"])
            
            max_length = BASE_CONFIG["LONG_TERM_MEMORY_MAX_LENGTH"]
            if total_docs <= max_length:
                return
            
            # 需要删除的记忆数量
            to_remove = total_docs - max_length
            
            # 获取所有文档及其元数据
            docs_with_metadata = []
            for i, doc_id in enumerate(all_docs["ids"]):
                doc = Document(
                    page_content=all_docs["documents"][i],
                    metadata=all_docs["metadatas"][i]
                )
                docs_with_metadata.append((doc, doc_id))
            
            # 按记忆类型（优先保留核心记忆）、重要性和时间排序
            # 临时记忆排在前面，相同类型内按重要性低、时间旧排序
            sorted_docs = sorted(docs_with_metadata, key=lambda x: (
                x[0].metadata.get("memory_type", "temporary"),  # 先按记忆类型排序
                x[0].metadata.get("importance", 0.5),  # 再按重要性
                x[0].metadata.get("timestamp", 0)  # 最后按时间
            ))
            
            # 删除最不重要的记忆
            deleted_count = 0
            for doc, doc_id in sorted_docs:
                if deleted_count >= to_remove:
                    break
                
                self.long_term_memory.delete([doc_id])
                deleted_count += 1
            
            logger.info(f"UID:{self.uid} - 长期记忆已清理，保留 {max_length} 条记录")
            
            # 同步到Faiss索引
            if self.faiss_index:
                self._sync_with_long_term_memory()
        except Exception as e:
            logger.error(f"UID:{self.uid} - 限制长期记忆数量失败: {e}")
    
    def extract_key_info(self, dialogue: str) -> str:
        """从对话中提取关键信息（增强版）"""
        # 增强的关键信息提取逻辑
        
        key_info = []
        
        # 提取个人信息
        person_patterns = [
            (r"(?:我是|我叫|名字是|你可以叫我)[\s]*([\u4e00-\u9fa5a-zA-Z·]+)", "姓名"),
            (r"(?:我今年|我多大|年龄|岁)[\s]*([0-9]+)", "年龄"),
            (r"(?:我生日|出生在|出生日期)[\s]*(\d{4}年\d{1,2}月\d{1,2}日)", "生日"),
            (r"(?:我是|来自|家乡|老家)[\s]*([\u4e00-\u9fa5]+(?:市|省|区|县|镇|村)?)", "家乡")
        ]
        
        # 提取职业信息
        career_patterns = [
            (r"(?:我是|我从事|我做|我的职业)[\s]*([\u4e00-\u9fa5a-zA-Z]+)", "职业"),
            (r"(?:我在|工作单位|公司)[\s]*([\u4e00-\u9fa5a-zA-Z]+)", "工作单位")
        ]
        
        # 提取兴趣爱好（使用非贪婪匹配，避免包含下一行的内容）
        interest_patterns = [
            (r"(?:喜欢|爱好|感兴趣|擅长)[\s]*([\u4e00-\u9fa5a-zA-Z,，、\s]+?)(?:\n|$)", "兴趣"),
            (r"(?:讨厌|不喜欢)[\s]*([\u4e00-\u9fa5a-zA-Z,，、\s]+?)(?:\n|$)", "讨厌")
        ]
        
        # 提取日期时间
        datetime_patterns = [
            (r"(?:今天|明天|后天|大后天|昨天|前天|大前天|\d{4}年\d{1,2}月\d{1,2}日)", "日期"),
            (r"(?:早上|上午|中午|下午|晚上|\d{1,2}:\d{2})", "时间")
        ]
        
        # 提取地点
        place_patterns = [
            (r"(?:在|去|来自|前往)[\s]*([\u4e00-\u9fa5]+(?:市|省|区|县|街|路|道|巷|大厦|小区))", "地点"),
            (r"(?:地址|位置)[\s]*([\u4e00-\u9fa50-9,，、\s]+)", "地址")
        ]
        
        # 提取事件
        event_patterns = [
            (r"(?:要|准备|计划)[\s]*([\u4e00-\u9fa5a-zA-Z,，、\s]+?)(?:\n|$)", "计划"),
            (r"(?:做了|完成|去过)[\s]*([\u4e00-\u9fa5a-zA-Z,，、\s]+?)(?:\n|$)", "经历")
        ]
        
        # 合并所有模式（包括事件模式）
        all_patterns = [
            (person_patterns, "个人信息"),
            (career_patterns, "职业信息"),
            (interest_patterns, "兴趣爱好"),
            (datetime_patterns, "日期时间"),
            (place_patterns, "地点"),
            (event_patterns, "事件")
        ]
        
        # 提取关键信息
        for pattern_group, group_name in all_patterns:
            group_info = []
            for pattern, field_name in pattern_group:
                match = re.search(pattern, dialogue)
                if match:
                    value = match.group(1) if len(match.groups()) > 0 else match.group(0)
                    # 去除可能的多余空格和特殊字符
                    value = re.sub(r'\s+', ' ', value).strip()
                    group_info.append(f"{field_name}: {value}")
            
            if group_info:
                key_info.append(f"{group_name}: {'; '.join(group_info)}")
        
        # 去重
        unique_key_info = []
        seen_info = set()
        for info in key_info:
            if info not in seen_info:
                seen_info.add(info)
                unique_key_info.append(info)
        
        return "; ".join(unique_key_info) if unique_key_info else "无"
        
    def _generate_tags(self, key_info: str, query: str, response: str) -> List[str]:
        """自动生成记忆标签"""
        tags = set()
        
        # 从关键信息中提取标签
        if key_info and key_info != "无":
            # 提取关键信息类型作为标签
            info_types = re.findall(r'([\u4e00-\u9fa5]+):', key_info)
            tags.update(info_types)
            
            # 提取具体内容作为标签
            if "个人信息" in key_info:
                if re.search(r'姓名:', key_info):
                    tags.add("姓名")
                if re.search(r'年龄:', key_info):
                    tags.add("年龄")
                if re.search(r'生日:', key_info):
                    tags.add("生日")
                if re.search(r'家乡:', key_info):
                    tags.add("家乡")
            
            if "职业信息" in key_info:
                if re.search(r'职业:', key_info):
                    tags.add("职业")
                if re.search(r'工作单位:', key_info):
                    tags.add("工作")
            
            if "兴趣爱好" in key_info:
                if re.search(r'兴趣:', key_info):
                    tags.add("兴趣")
                if re.search(r'讨厌:', key_info):
                    tags.add("讨厌")
            
            if "日期时间" in key_info:
                tags.add("时间")
            
            if "地点" in key_info:
                tags.add("地点")
            
            if "事件" in key_info:
                if re.search(r'计划:', key_info):
                    tags.add("计划")
                if re.search(r'经历:', key_info):
                    tags.add("经历")
        
        # 从对话内容中提取标签
        combined_content = f"{query} {response}"
        
        # 常见标签模式
        tag_patterns = [
            (r"(?:电影|音乐|体育|游戏|阅读)", "爱好"),
            (r"(?:工作|职业|公司|项目)", "工作"),
            (r"(?:计划|打算|想要|准备)", "计划"),
            (r"(?:过去|曾经|之前|已经)", "经历"),
            (r"(?:问题|帮助|需要|请求)", "请求"),
            (r"(?:感谢|谢谢|感激)", "感谢"),
        ]
        
        for pattern, tag in tag_patterns:
            if re.search(pattern, combined_content):
                tags.add(tag)
        
        # jieba关键词提取改为后台异步执行，不阻塞主流程
        # 标签将在后台任务中补充
        self._pending_jieba_tags = (combined_content, tags.copy())
        
        return list(tags) if tags else []
    
    async def _extract_jieba_tags_async(self):
        """后台异步提取jieba关键词"""
        if not _has_jieba or not hasattr(self, '_pending_jieba_tags') or not self._pending_jieba_tags:
            return []
        
        combined_content, existing_tags = self._pending_jieba_tags
        self._pending_jieba_tags = None  # 清空待处理标记
        
        try:
            # 在后台线程中执行jieba提取
            import asyncio
            loop = asyncio.get_event_loop()
            
            def _do_jieba_extract():
                try:
                    keywords = jieba.analyse.extract_tags(combined_content, topK=5, withWeight=False)
                    keywords = [word for word in keywords if len(word) > 1]
                    return keywords
                except Exception as e:
                    logger.error(f"UID:{self.uid} - jieba关键词提取失败: {e}")
                    return []
            
            keywords = await loop.run_in_executor(None, _do_jieba_extract)
            
            # 合并到现有标签
            existing_tags.update(keywords)
            logger.debug(f"UID:{self.uid} - jieba后台提取关键词完成: {keywords}")
            return list(existing_tags)
            
        except Exception as e:
            logger.error(f"UID:{self.uid} - jieba异步提取失败: {e}")
            return list(existing_tags)
    
    def _determine_memory_type(self, key_info: str, query: str, response: str) -> str:
        """确定记忆类型（核心记忆或临时记忆）"""
        
        # 核心记忆包含的关键信息类型
        core_memory_patterns = [
            r"(?:个人信息|职业信息)",  # 基本身份信息
            r"(?:姓名|年龄|生日|家乡|地址|电话|邮箱)",  # 重要个人信息
            r"(?:职业|工作|公司|学校)",  # 重要职业信息
            r"(?:长期|永久|一直|始终)",  # 长期性质的信息
        ]
        
        # 检查关键信息
        if key_info and key_info != "无":
            for pattern in core_memory_patterns:
                if re.search(pattern, key_info):
                    return "core"
        
        # 检查对话内容
        combined_content = f"{query} {response}"
        for pattern in core_memory_patterns:
            if re.search(pattern, combined_content):
                return "core"
        
        # 默认是临时记忆
        return "temporary"
    
    def _calculate_importance_score(self, query: str, response: str, key_info: str) -> float:
        """计算记忆的重要性评分 (0-1) - 增强版"""
        score = 0.4  # 基础分降低，让其他因素影响更大
        

        
        # 1. 关键信息的丰富程度 (0.0-0.3)
        if key_info and key_info != "无":
            # 根据提取的关键信息数量和类型加权
            # 统一使用英文分号分隔，然后计算非空部分数量
            key_info_parts = re.split(r'[；;]', key_info)
            key_info_count = len([part for part in key_info_parts if part.strip()])
            score += min(0.3, key_info_count * 0.05)
        
        # 2. 对话内容的语义重要性 (0.0-0.3)
        importance_patterns = {
            # 高重要性关键词 (0.15)
            r"(?:姓名|年龄|生日|家乡|地址|电话|邮箱)": 0.15,
            # 中重要性关键词 (0.10)
            r"(?:职业|工作|公司|学校|爱好|需求|计划)": 0.10,
            # 低重要性关键词 (0.05)
            r"(?:喜欢|讨厌|想去|想做)": 0.05
        }
        
        for pattern, weight in importance_patterns.items():
            if re.search(pattern, query) or re.search(pattern, response):
                score += weight
                break  # 每个类别只加一次分
        
        # 3. 对话长度 (0.0-0.15)
        total_length = len(query) + len(response)
        if 30 <= total_length <= 100:
            score += 0.05
        elif 100 < total_length <= 300:
            score += 0.10
        elif total_length > 300:
            score += 0.15
        
        # 4. 对话类型 (0.0-0.10)
        # 陈述性对话（包含事实信息）
        if re.search(r"(?:是|在|有|为了|因为|所以)", query):
            score += 0.05
        # 疑问性对话（可能需要记住的问题）
        if re.search(r"(?:吗|呢|\?|？)", query):
            score += 0.03
        # 命令性对话（需要执行的任务）
        if re.search(r"(?:帮我|请|要|想让)", query):
            score += 0.10
        
        # 5. 重复提及的信息 (0.0-0.10)
        # 检查是否有重复出现的关键词
        words = re.findall(r"[\u4e00-\u9fa5a-zA-Z]+", query)
        unique_words = set(words)
        if len(words) / len(unique_words) if unique_words else 0 > 1.5:
            score += 0.10
        
        # 确保分数在0-1之间
        return max(0.0, min(score, 1.0))
    
    def _preprocess_text(self, text: str) -> List[str]:
        """预处理文本：jieba中文分词，英文按空格分词"""
        if not text:
            return []
        if _has_jieba:
            try:
                jieba.setLogLevel(20)  # 抑制jieba日志
                tokens = list(jieba.cut(text))
                # 过滤空白和纯标点，保留有意义的词
                tokens = [t.strip().lower() for t in tokens if t.strip() and re.search(r'[\u4e00-\u9fa5a-zA-Z0-9]', t)]
                return tokens
            except Exception:
                pass
        # fallback: 空格分词
        return [t.lower() for t in text.split() if t.strip()]
    
    def _calculate_bm25(self, query: str, docs: List[Document]) -> List[Tuple[Document, float]]:
        """计算查询与文档的BM25相似度
        
        Args:
            query: 查询文本
            docs: 文档列表
            
        Returns:
            文档与BM25分数的列表
        """
        # 预处理查询
        query_tokens = self._preprocess_text(query)
        if not query_tokens:
            return [(doc, 0.0) for doc in docs]
        
        # 计算文档的词频
        doc_terms = []
        doc_freq = {}
        
        for doc in docs:
            terms = self._preprocess_text(doc.page_content)
            doc_terms.append(terms)
            
            # 更新文档频率
            unique_terms = set(terms)
            for term in unique_terms:
                doc_freq[term] = doc_freq.get(term, 0) + 1
        
        # BM25参数
        k1 = 1.5
        b = 0.75
        
        # 计算平均文档长度
        avg_doc_len = sum(len(terms) for terms in doc_terms) / len(docs) if docs else 0
        
        # 计算每个文档的BM25分数
        results = []
        for i, (doc, terms) in enumerate(zip(docs, doc_terms)):
            # 计算词频
            term_freq = {}
            for term in terms:
                term_freq[term] = term_freq.get(term, 0) + 1
            
            # 计算BM25分数
            score = 0.0
            doc_len = len(terms)
            
            for term in query_tokens:
                if term not in term_freq:
                    continue
                
                # 计算逆文档频率
                if term not in doc_freq:
                    continue
                idf = math.log((len(docs) - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5) + 1.0)
                
                # 计算词频调整
                tf = term_freq[term]
                numerator = tf * (k1 + 1)
                denominator = tf + k1 * (1 - b + b * doc_len / avg_doc_len)
                
                # 累加BM25分数
                score += idf * (numerator / denominator)
            
            results.append((doc, score))
        
        return results
    
    def retrieve_relevant_memory(self, query: str, k: int = 3, include_importance: bool = False) -> str:
        """检索相关长期记忆 - 增强版"""
        # 延迟初始化
        self._ensure_initialized()
        
        try:
            if not query.strip():
                return ""
            
            # 检查长期记忆是否可用
            if not self.long_term_memory_ready or self.long_term_memory is None:
                logger.warning(f"UID:{self.uid} - 长期记忆功能不可用，跳过记忆检索")
                return ""
            
            import re
            now = time.time()
            
            # 1. 获取所有文档
            all_docs = self.long_term_memory.get()
            if not all_docs or not all_docs["ids"]:
                return ""
            
            # 转换为Document对象列表
            docs = []
            for i, doc_id in enumerate(all_docs["ids"]):
                doc = Document(
                    page_content=all_docs["documents"][i],
                    metadata=all_docs["metadatas"][i]
                )
                docs.append(doc)
            
            # 2. BM25检索
            bm25_results = self._calculate_bm25(query, docs)
            bm25_results.sort(key=lambda x: x[1], reverse=True)
            
            # 3. 向量检索
            if self.faiss_index and self.faiss_documents:
                # 使用Faiss进行向量检索
                try:
                    query_embedding = get_embedding().embed_query(query)
                    query_embedding_np = np.array([query_embedding]).astype('float32')
                    
                    # 搜索Faiss索引
                    distances, indices = self.faiss_index.search(query_embedding_np, k=k * 5)
                    
                    # 转换为与Chroma相同的格式: [(Document, score), ...]
                    vector_results = []
                    for i in range(len(indices[0])):
                        idx = indices[0][i]
                        if idx >= 0 and idx < len(self.faiss_documents):
                            doc = self.faiss_documents[idx]
                            # 将L2距离转换为相似度分数（1/(1+距离)）
                            score = 1.0 / (1.0 + distances[0][i])
                            vector_results.append((doc, score))
                    
                    logger.info(f"UID:{self.uid} - 使用Faiss进行向量检索成功")
                except Exception as e:
                    logger.error(f"UID:{self.uid} - Faiss向量检索失败: {e}")
                    # 回退到Chroma检索
                    vector_results = self.long_term_memory.similarity_search_with_score(query, k=k * 5)
            else:
                # 使用Chroma进行向量检索
                vector_results = self.long_term_memory.similarity_search_with_score(query, k=k * 5)
            
            # 4. RRF融合
            def rrf_fusion(bm25_results, vector_results, k=60):
                """使用RRF算法融合BM25和向量检索结果"""
                # 为每个文档分配排名
                doc_ranks = {}
                
                # BM25排名
                for rank, (doc, score) in enumerate(bm25_results, 1):
                    doc_id = doc.page_content  # 使用内容作为唯一标识
                    if doc_id not in doc_ranks:
                        doc_ranks[doc_id] = {"doc": doc, "scores": []}
                    doc_ranks[doc_id]["scores"].append(1.0 / (k + rank))
                
                # 向量检索排名
                for rank, (doc, score) in enumerate(vector_results, 1):
                    doc_id = doc.page_content  # 使用内容作为唯一标识
                    if doc_id not in doc_ranks:
                        doc_ranks[doc_id] = {"doc": doc, "scores": []}
                    doc_ranks[doc_id]["scores"].append(1.0 / (k + rank))
                
                # 计算融合分数
                fused_results = []
                for doc_id, data in doc_ranks.items():
                    total_score = sum(data["scores"])
                    fused_results.append((data["doc"], total_score))
                
                # 按分数排序
                fused_results.sort(key=lambda x: x[1], reverse=True)
                
                return [doc for doc, score in fused_results]
            
            # 融合结果
            fused_docs = rrf_fusion(bm25_results, vector_results)
            
            # 5. 关键词匹配增强相关性评分
            def calculate_relevance_score(doc, query):
                # 基础向量相似度得分（Chroma返回的默认分数在metadata中没有，我们需要重新计算）
                doc_content = doc.page_content.lower()
                query_lower = query.lower()
                
                # 关键词匹配得分（使用jieba分词）
                query_words = self._preprocess_text(query_lower)
                matching_words = sum(1 for word in query_words if word in doc_content)
                keyword_score = matching_words / len(query_words) if query_words else 0
                
                # 关键信息匹配得分
                key_info = doc.metadata.get("key_info", "").lower()
                key_info_score = sum(1 for word in query_words if word in key_info) / len(query_words) if query_words and key_info else 0
                
                # 标签匹配得分
                doc_tags = doc.metadata.get("tags", [])
                query_tags = self._generate_tags("无", query, "")  # 从查询中生成可能的标签
                if doc_tags and query_tags:
                    common_tags = set(doc_tags) & set(query_tags)
                    tag_score = len(common_tags) / max(len(doc_tags), len(query_tags))
                else:
                    tag_score = 0
                
                # 重要性和时间因素
                importance = doc.metadata.get("importance", 0.5)
                timestamp = doc.metadata.get("timestamp", now)
                recency = (now - timestamp) / (30 * 24 * 3600)  # 转换为月数
                recency_score = max(0, 1 - recency)  # 最近的记忆得分更高
                
                # 综合得分 - 增加标签匹配的权重
                total_score = (
                    keyword_score * 0.25 +
                    key_info_score * 0.2 +
                    importance * 0.25 +
                    recency_score * 0.15 +
                    tag_score * 0.15  # 标签匹配权重
                )
                
                return total_score
            
            # 6. 根据综合相关性得分排序
            sorted_docs = sorted(fused_docs, key=lambda doc: calculate_relevance_score(doc, query), reverse=True)
            
            # 7. 去重 - 避免返回过于相似的记忆
            unique_docs = []
            seen_contents = set()
            
            for doc in sorted_docs:
                content = doc.page_content[:100]  # 使用内容片段作为去重依据
                if content not in seen_contents:
                    seen_contents.add(content)
                    unique_docs.append(doc)
                    if len(unique_docs) >= k:
                        break
            
            # 5. 格式化结果
            formatted_docs = []
            for doc in unique_docs:
                # 对于 memo 类型，优先返回 page-store 中的完整内容
                doc_type = doc.metadata.get("type", "")
                if doc_type == "memo":
                    page_content = self._resolve_memo_to_page(doc)
                    if page_content:
                        if include_importance:
                            importance = doc.metadata.get("importance", 0.5)
                            key_info = doc.metadata.get("key_info", "无")
                            timestamp = doc.metadata.get("timestamp", now)
                            time_str = time.strftime("%Y-%m-%d", time.localtime(timestamp))
                            formatted_docs.append(f"[{importance:.1f}] [{time_str}] {key_info} | {page_content}")
                        else:
                            formatted_docs.append(page_content)
                        continue
                    # fallback: 继续使用 memo 原文

                content = doc.page_content[:500]
                if include_importance:
                    importance = doc.metadata.get("importance", 0.5)
                    key_info = doc.metadata.get("key_info", "无")
                    timestamp = doc.metadata.get("timestamp", now)
                    time_str = time.strftime("%Y-%m-%d", time.localtime(timestamp))
                    formatted_docs.append(f"[{importance:.1f}] [{time_str}] {key_info} | {content}")
                else:
                    formatted_docs.append(content)
            
            # 8. 冷存储搜索（作为补充回退）
            cold_results = self._search_cold_storage(query, max_results=2)
            if cold_results:
                for cold_text in cold_results:
                    formatted_docs.append(cold_text)
            
            # 9. PageStore 搜索（语义 header 匹配）
            try:
                page_results = self.page_store.search_headers(query, top_k=2)
                for pr in page_results:
                    page_content = self.page_store.get_page_content(pr["session_id"], max_chars=500)
                    if page_content:
                        formatted_docs.append(f"[Page] {page_content}")
            except Exception:
                pass  # Don't fail retrieval if page-store search fails

            return "\n\n".join(formatted_docs)
        except Exception as e:
            logger.error(f"UID:{self.uid} - 记忆检索失败: {e}")
            return ""
    
    def _search_cold_storage(self, query: str, max_results: int = 2, min_overlap: float = 0.3) -> List[str]:
        """搜索冷存储中的相关记忆

        Args:
            query: 查询文本
            max_results: 最大返回数量
            min_overlap: 最小重叠比率阈值

        Returns:
            格式化的冷存储记忆列表，带 [Cold] 前缀
        """
        try:
            cold_dir = os.path.join(
                BASE_CONFIG.get("MEMORY_DB_DIR", os.path.join(os.path.expanduser("~"), ".hakus", "memory_db")),
                f"user_{self.uid}_cold"
            )

            if not os.path.exists(cold_dir):
                return []

            # 预处理查询文本
            query_tokens = self._preprocess_text(query)
            if not query_tokens:
                return []

            scored_memories = []

            # 遍历冷存储目录中的JSON文件
            for filename in os.listdir(cold_dir):
                if not filename.endswith(".json"):
                    continue

                filepath = os.path.join(cold_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except (json.JSONDecodeError, OSError):
                    continue

                # 构建用于匹配的文本：合并内容和关键信息
                content = data.get("content", "")
                metadata = data.get("metadata", {})
                key_info = metadata.get("key_info", "")
                user_query = metadata.get("user_query", "")
                agent_response = metadata.get("agent_response", "")

                # 将所有可搜索文本合并
                searchable_text = f"{content} {key_info} {user_query} {agent_response}"
                doc_tokens = self._preprocess_text(searchable_text)

                if not doc_tokens:
                    continue

                # 计算关键词重叠比率
                query_token_set = set(query_tokens)
                doc_token_set = set(doc_tokens)
                overlap = query_token_set & doc_token_set
                overlap_ratio = len(overlap) / len(query_token_set) if query_token_set else 0

                if overlap_ratio >= min_overlap:
                    scored_memories.append((data, overlap_ratio))

            if not scored_memories:
                return []

            # 按重叠比率降序排序，取 top N
            scored_memories.sort(key=lambda x: x[1], reverse=True)
            top_memories = scored_memories[:max_results]

            results = []
            for data, score in top_memories:
                content = data.get("content", "")
                metadata = data.get("metadata", {})
                doc_id = data.get("doc_id", "")
                importance = metadata.get("importance", 0.5)
                key_info = metadata.get("key_info", "无")

                # 格式化输出，带 [Cold] 前缀
                formatted = f"[Cold] [{importance:.1f}] {key_info} | {content[:500]}"
                results.append(formatted)

            logger.debug(f"UID:{self.uid} - 冷存储搜索命中 {len(results)} 条记忆")
            return results

        except Exception as e:
            logger.error(f"UID:{self.uid} - 冷存储搜索失败: {e}")
            return []

    def promote_cold_memory(self, memory_id: str) -> bool:
        """将冷存储记忆提升回活跃记忆库

        Args:
            memory_id: 冷存储记忆的doc_id

        Returns:
            是否成功提升
        """
        cold_dir = os.path.join(
            BASE_CONFIG.get("MEMORY_DB_DIR", os.path.join(os.path.expanduser("~"), ".hakus", "memory_db")),
            f"user_{self.uid}_cold"
        )
        cold_file = os.path.join(cold_dir, f"{memory_id}.json")
        if not os.path.exists(cold_file):
            return False

        try:
            with open(cold_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            metadata = data.get("metadata", {})

            # 添加回活跃记忆
            self.add_long_term_memory(
                user_query=metadata.get("user_query", ""),
                agent_response=metadata.get("agent_response", ""),
                memory_type=metadata.get("memory_type", "temporary"),
            )

            # 从冷存储中移除
            os.remove(cold_file)
            logger.info(f"UID:{self.uid} - 冷存储记忆 {memory_id} 已提升回活跃记忆")
            return True
        except Exception as e:
            logger.warning(f"UID:{self.uid} - 提升冷存储记忆 {memory_id} 失败: {e}")
            return False

    def get_recent_conversations(self, k: int = 5) -> List[Dict[str, str]]:
        """获取最近的对话历史"""
        if not self.short_term_memory:
            return []
        
        return self.short_term_memory[-k:]
    
    async def summarize_conversation_history(self, agent) -> str:
        """使用LLM总结对话历史，生成日记体记忆（改进版：只总结未归档的对话）
        
        Args:
            agent: Agent实例，用于访问LLM模型
            
        Returns:
            生成的日记体总结
        """
        try:
            # 获取未归档的对话
            unarchived = [conv for conv in self.short_term_memory if not conv.get("archived", False)]
            
            # 检查是否有足够的未归档对话
            if len(unarchived) < 4:  # 少于4条不总结
                return ""
            
            # 检查最后对话时间（Engram风格：对话结束后一段时间再总结）
            if len(unarchived) < 10:  # 不足10条时，检查时间间隔
                last_conv_time = self._parse_timestamp(unarchived[-1].get("timestamp", ""))
                if last_conv_time:
                    time_since_last = time.time() - last_conv_time
                    if time_since_last < 600:  # 最后对话10分钟内不总结
                        return ""
            
            # 取最近10条未归档对话
            conversations_to_summarize = unarchived[-10:]
            
            conversation_text = "\n".join([
                f"Q:{conv['query'][:80]} A:{conv['response'][:80]}"
                for conv in conversations_to_summarize
            ])
            
            current_time = time.strftime("%m月%d日")
            
            search_context = ""
            recent_searches = self.get_recent_search_results(limit=2)
            if recent_searches:
                search_context = "\n\n【后台搜索发现】\n" + "\n".join([
                    f"- {s['query']}: {s['result'][:100]}..."
                    for s in recent_searches
                ])
            
            summarize_prompt = f"""将以下对话转为日记体总结（80-120字）：

{conversation_text}
{search_context}

要求：
1. 用第一人称"咱"写日记
2. 描述用户的情绪/状态
3. 记录聊了什么主题
4. 写1-2个印象深刻的细节
5. 描述整体氛围/关系感受
6. 如果有搜索发现，可以融入日记中

格式：{current_time}。今天用户...（日记内容）...感觉..."""
            
            # 调用LLM生成总结（不使用工具）
            summary = await agent.model.generate_response_no_tools(
                system_prompt="你是羽汐，14岁少女，写日记记录和网友的对话。语气活泼、有情感。",
                messages=[{"role": "user", "content": summarize_prompt}]
            )
            
            # 如果生成了有效总结，保存为日记体记忆
            if summary and summary.strip():
                # 生成唯一ID用于关联原文
                memory_id = f"diary_{int(time.time())}"
                
                # 保存日记体记忆（带原文指针）
                self._save_diary_memory(
                    memory_id=memory_id,
                    diary_content=summary,
                    raw_conversations=conversations_to_summarize
                )
                
                # 标记这些对话为已归档
                self._mark_conversations_archived(conversations_to_summarize)
                
                logger.info(f"UID:{self.uid} - 日记体记忆生成成功，归档{len(conversations_to_summarize)}条对话: {summary[:50]}...")
                return summary
            
            return ""
        except Exception as e:
            logger.error(f"UID:{self.uid} - 生成日记体记忆失败: {e}")
            return ""
    
    def _parse_timestamp(self, timestamp_str: str) -> Optional[float]:
        """解析时间戳字符串为时间戳数值"""
        try:
            if not timestamp_str:
                return None
            parsed_time = time.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
            return time.mktime(parsed_time)
        except Exception:
            return None
    
    def _mark_conversations_archived(self, conversations: List[Dict]):
        """标记对话为已归档
        
        Args:
            conversations: 已总结的对话列表
        """
        try:
            # 创建查找集合
            archived_queries = {conv.get("query") for conv in conversations}
            
            # 标记短期记忆中的对应项
            archived_count = 0
            for conv in self.short_term_memory:
                if conv.get("query") in archived_queries and not conv.get("archived", False):
                    conv["archived"] = True
                    archived_count += 1
            
            # 保存更新后的短期记忆
            if archived_count > 0:
                self._save_short_term_memory()
                logger.debug(f"UID:{self.uid} - 已标记{archived_count}条对话为已归档")
                
        except Exception as e:
            logger.error(f"UID:{self.uid} - 标记归档状态失败: {e}")
    
    def _resolve_memo_to_page(self, doc: Document, max_chars: int = 300) -> Optional[str]:
        """将 memo 类型的记忆解析为 page-store 中的完整页面内容

        Memo 是轻量级索引，用于引导检索到 page-store 中的完整内容。
        通过 memory_id 或时间戳匹配对应的 page-store 页面。

        Args:
            doc: memo 类型的 Document
            max_chars: 返回内容的最大字符数

        Returns:
            截断的页面内容，找不到则返回 None（回退到 memo 原文）
        """
        try:
            metadata = doc.metadata
            memory_id = metadata.get("memory_id", "")

            # 策略1: 通过 memory_id 直接匹配 page-store 的 session_id
            # memory_id 格式为 "diary_{timestamp}"，page-store session_id 格式为 "session_{timestamp}"
            if memory_id and memory_id.startswith("diary_"):
                ts_part = memory_id[len("diary_"):]
                candidate_session_id = f"session_{ts_part}"
                page_content = self.page_store.get_page_content(candidate_session_id, max_chars=max_chars)
                if page_content:
                    return page_content

            # 策略2: 通过时间戳范围匹配（memo 的 raw_start_time / raw_end_time 对应的页面）
            raw_start_time = metadata.get("raw_start_time", "")
            if raw_start_time:
                parsed = self._parse_timestamp(raw_start_time)
                if parsed:
                    # 尝试在 page-store 索引中查找时间接近的页面
                    for sid, info in self.page_store._index.items():
                        page_ts = info.get("timestamp", "")
                        if page_ts:
                            page_parsed = self._parse_timestamp(page_ts)
                            if page_parsed and abs(page_parsed - parsed) < 600:  # 10分钟内
                                page_content = self.page_store.get_page_content(sid, max_chars=max_chars)
                                if page_content:
                                    return page_content

            # 找不到对应页面，返回 None 让调用方回退到 memo 原文
            return None

        except Exception:
            return None
    
    def _save_diary_memory(self, memory_id: str, diary_content: str, raw_conversations: List[Dict]):
        """保存日记体记忆，包含原文指针
        
        Args:
            memory_id: 记忆唯一ID
            diary_content: 日记内容
            raw_conversations: 原始对话列表
        """
        try:
            # 构建日记体记忆文档
            diary_doc = Document(
                page_content=diary_content,
                metadata={
                    "type": "memo",
                    "memory_id": memory_id,
                    "timestamp": time.time(),
                    "raw_count": len(raw_conversations),
                    "raw_start_time": raw_conversations[0].get("timestamp", ""),
                    "raw_end_time": raw_conversations[-1].get("timestamp", ""),
                    "importance": 0.7,  # 日记体记忆重要性较高
                    "key_info": self.extract_key_info(diary_content),
                    "tags": "日记;总结"
                }
            )
            
            # 保存到长期记忆
            if self.long_term_memory_ready and self.long_term_memory:
                self.long_term_memory.add_documents([diary_doc])
                
                # 同时保存原文到独立文件（便于回溯）
                self._save_raw_conversations(memory_id, raw_conversations)
                
                logger.info(f"UID:{self.uid} - 日记体记忆已保存，ID: {memory_id}")
        except Exception as e:
            logger.error(f"UID:{self.uid} - 保存日记体记忆失败: {e}")
    
    def _save_raw_conversations(self, memory_id: str, conversations: List[Dict]):
        """保存原始对话到独立文件
        
        Args:
            memory_id: 关联的记忆ID
            conversations: 原始对话列表
        """
        try:
            # 创建raw_conversations目录
            raw_dir = os.path.join(BASE_CONFIG["MEMORY_DB_DIR"], f"user_{self.uid}_raw")
            os.makedirs(raw_dir, exist_ok=True)
            
            # 保存为JSON文件
            filepath = os.path.join(raw_dir, f"{memory_id}.json")
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump({
                    "memory_id": memory_id,
                    "uid": self.uid,
                    "timestamp": time.time(),
                    "conversations": conversations
                }, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logger.error(f"UID:{self.uid} - 保存原始对话失败: {e}")
    
    def get_diary_memories(self, limit: int = 5) -> List[str]:
        """获取日记体记忆列表
        
        Args:
            limit: 返回的最大数量
            
        Returns:
            日记体记忆内容列表
        """
        try:
            self._ensure_initialized()
            
            if not self.long_term_memory_ready or self.long_term_memory is None:
                return []
            
            all_docs = self.long_term_memory.get()
            if not all_docs or not all_docs["ids"]:
                return []
            
            diary_memories = []
            for i, metadata in enumerate(all_docs["metadatas"]):
                if metadata.get("type") == "memo":
                    content = all_docs["documents"][i]
                    diary_memories.append({
                        "content": content,
                        "timestamp": metadata.get("timestamp", 0),
                        "memory_id": metadata.get("memory_id", "")
                    })
            
            diary_memories.sort(key=lambda x: x["timestamp"], reverse=True)
            
            return [m["content"] for m in diary_memories[:limit]]
            
        except Exception as e:
            logger.error(f"UID:{self.uid} - 获取日记体记忆失败: {e}")
            return []
    
    def get_diary_memory_with_raw(self, memory_id: str) -> Optional[Dict]:
        """获取日记体记忆及其关联的原始对话
        
        Args:
            memory_id: 记忆ID
            
        Returns:
            包含日记内容和原始对话的字典
        """
        try:
            # 读取原始对话文件
            raw_dir = os.path.join(BASE_CONFIG["MEMORY_DB_DIR"], f"user_{self.uid}_raw")
            filepath = os.path.join(raw_dir, f"{memory_id}.json")
            
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            
            return None
        except Exception as e:
            logger.error(f"UID:{self.uid} - 获取原始对话失败: {e}")
            return None
    
    def _should_trigger_background_search(self, query: str, response: str) -> Optional[str]:
        """判断是否应该触发后台搜索，返回搜索关键词或None
        
        触发条件：
        1. 用户提到网络梗、流行语
        2. 用户提到最近的热点事件
        3. 用户提到自己感兴趣的话题（游戏、动漫、音乐等）
        4. 用户提到时间敏感的信息（新闻、天气等）
        5. AI自己感兴趣的话题
        """
        current_time = time.time()
        
        if current_time - self._last_search_time < self._search_cooldown:
            return None
        
        combined_text = f"{query} {response}"
        
        meme_patterns = [
            r"(?:梗|流行语|网络用语|什么意思|出处|来源)",
            r"(?:yyds|绝绝子|栓Q|芭比Q|破防|整活|摸鱼|内卷|躺平|摆烂)",
            r"(?:什么梗|怎么火|为什么火)",
        ]
        
        hot_patterns = [
            r"(?:最近|最新|今天|热点|热搜|热门|火了|火了)",
            r"(?:新闻|事件|发生了什么)",
            r"(?:大家都在说|网上都在)",
        ]
        
        interest_patterns = [
            r"(?:新番|动漫|动画|番剧|追番)",
            r"(?:游戏|新游|手游|端游|主机)",
            r"(?:音乐|新歌|专辑|歌手)",
            r"(?:电影|电视剧|综艺|节目)",
            r"(?:主播|直播|UP主|视频)",
        ]
        
        time_sensitive_patterns = [
            r"(?:天气|气温|下雨|下雪)",
            r"(?:今天|明天|本周|最近)",
            r"(?:现在|目前|当前)",
        ]
        
        ai_interest_patterns = [
            r"(?:虚拟主播|VUP|VTuber)",
            r"(?:B站|bilibili)",
            r"(?:原神|崩坏|明日方舟|王者荣耀)",
            r"(?:二次元|ACG|动漫)",
        ]
        
        search_query = None
        
        for pattern in meme_patterns:
            match = re.search(pattern, combined_text)
            if match:
                context = combined_text[max(0, match.start()-20):match.end()+20]
                search_query = f"{context[:30]} 梗 出处"
                break
        
        if not search_query:
            for pattern in hot_patterns:
                match = re.search(pattern, combined_text)
                if match:
                    keywords = re.findall(r"[\u4e00-\u9fa5]+", combined_text[:50])
                    if keywords:
                        search_query = f"{' '.join(keywords[:3])} 最新"
                    break
        
        if not search_query:
            for pattern in interest_patterns:
                match = re.search(pattern, combined_text)
                if match:
                    topic_match = re.search(r"(?:新番|动漫|游戏|音乐|电影|主播)[\s:：]*([\u4e00-\u9fa5a-zA-Z0-9]+)", combined_text)
                    if topic_match:
                        search_query = f"{topic_match.group(1)} {match.group(0)} 最新"
                    else:
                        search_query = f"{match.group(0)} 2025 推荐"
                    break
        
        if not search_query:
            for pattern in time_sensitive_patterns:
                match = re.search(pattern, combined_text)
                if match:
                    location_match = re.search(r"(?:在|去|来)([\u4e00-\u9fa5]+)(?:的|天气)", combined_text)
                    if location_match:
                        search_query = f"{location_match.group(1)} 天气"
                    else:
                        search_query = f"{match.group(0)} 最新消息"
                    break
        
        if not search_query:
            for pattern in ai_interest_patterns:
                match = re.search(pattern, combined_text)
                if match:
                    search_query = f"{match.group(0)} 最新 热门"
                    break
        
        if search_query and search_query in self._background_search_cache:
            cache_time, _ = self._background_search_cache[search_query]
            if current_time - cache_time < 3600:
                return None
        
        return search_query
    
    def get_recent_search_results(self, limit: int = 3) -> List[Dict]:
        """获取最近的搜索结果
        
        Args:
            limit: 返回的最大数量
            
        Returns:
            搜索结果列表
        """
        try:
            if not self._background_search_cache:
                return []
            
            sorted_cache = sorted(
                self._background_search_cache.items(),
                key=lambda x: x[1][0],
                reverse=True
            )
            
            results = []
            for query, (timestamp, result) in sorted_cache[:limit]:
                results.append({
                    "query": query,
                    "result": result[:500] if len(result) > 500 else result,
                    "timestamp": timestamp
                })
            
            return results
            
        except Exception as e:
            logger.error(f"UID:{self.uid} - 获取搜索结果失败: {e}")
            return []
