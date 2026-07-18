"""
HakusAI 2.0 FastAPI服务器
提供REST API和WebSocket接口
"""

import asyncio
import os
import time
from contextlib import asynccontextmanager
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import logging
import json
from pathlib import Path

from hakusai_core.utils.events import event_bus, EventType
from hakusai_core.config import config_manager
from hakusai_core.models import model_registry, BaseModelAdapter, Message, MessageRole
from hakusai_core.agent import BaseAgent, AgentContext
from hakusai_core.memory import MemoryManager, MemoryStorage
from hakusai_core.voice.tts import tts_registry
from .vtuber_websocket import vtuber_handler
from .agent_bridge import (
    run_turn_stream as agentcore_run_turn_stream,
    run_turn_collect as agentcore_run_turn_collect,
    clear_session_history as agentcore_clear_session,
    get_or_create_agent as agentcore_get_or_create,
)
from . import session_store

logger = logging.getLogger(__name__)


# ========== 服务器 API 版本 ==========
# 每次 sidecar 新增/变更 API 端点时，必须 bump 此版本号。
# 桌面客户端启动时会 GET /api/version 检查 sidecar 是否过旧；
# 如果版本不匹配，会提示用户重新下载最新版（而不是显示莫名其妙的 404）。
#
# 历史: v0.1.0-beta.3 用户报告 "Get providers failed:404"，根因是用户安装的
# sidecar.exe 还是 beta.2 时期的（没有 /api/config/providers 等新端点）。
# 加这个版本号后，客户端能直接告诉用户 "sidecar 版本过旧" 而不是让用户
# 对着 404 一头雾水。
SIDECAR_API_VERSION = "0.5.0"
SIDECAR_API_VERSION_INT = 5  # 整数版本，便于客户端比较
# v0.5.0: + MCP 客户端支持 (/api/config/mcp-servers* + /api/mcp/servers/*)
# v0.4.0: + SQLite 会话持久化 + 聊天记录导出/导入
# v0.3.0: + 提供商配置 API (test connection / fetch models / multi-key / headers)

# Toggle: when True, /api/chat* endpoints use hakus.AgentCore (24 tools,
# permissions, AgentEvent stream). When False, fall back to the old
# BaseAgent chat-only path (useful for debugging / bisecting).
# Default True — the BaseAgent path is now considered legacy.
USE_AGENTCORE_FOR_CHAT = os.environ.get("HAKUSAI_USE_AGENTCORE", "1") != "0"


# ========== 服务器状态机 ==========
# /health 在 lifespan 起飞后立即返回 200，并通过 status 字段告诉客户端当前真实状态。
# 这样 sidecar 健康检查不再因 AI 组件初始化失败而 30s 超时。

class ServerState(str, Enum):
    """服务器生命周期状态"""
    STARTING = "starting"           # 进程刚启动，lifespan 还没跑
    INITIALIZING = "initializing"   # lifespan 已 yield，AI 组件正在后台初始化
    HEALTHY = "healthy"             # 所有关键组件就绪
    DEGRADED = "degraded"           # 关键组件就绪，但部分可选组件（TTS/Memory）失败
    FAILED = "failed"               # 关键组件（model/agent）初始化失败，但 HTTP 仍可响应


# ========== 请求/响应模型 ==========

class ChatRequest(BaseModel):
    """聊天请求"""
    message: str
    session_id: Optional[str] = "default"
    stream: bool = True
    # Per-request provider override. If set (e.g. "opencode"), the
    # agent_bridge creates/reuses an AgentCore bound to this provider
    # instead of the global default_model from config.yaml. This lets
    # the user switch providers from the TopBar dropdown mid-session.
    # If None, falls back to config.yaml's models.default_model.
    provider: Optional[str] = None


class ChatResponse(BaseModel):
    """聊天响应"""
    content: str
    emotion: Optional[str] = None
    actions: list = []
    done: bool = False


class ConfigUpdateRequest(BaseModel):
    """配置更新请求"""
    section: str
    key: str
    value: Any


# ========== Session persistence (SQLite) 请求模型 ==========

class SessionCreateRequest(BaseModel):
    """创建 session 请求"""
    id: str
    title: str = "New Chat"
    remote_session_id: Optional[str] = None
    provider: Optional[str] = None
    pinned: bool = False
    created_at: Optional[int] = None
    updated_at: Optional[int] = None


class SessionUpdateRequest(BaseModel):
    """更新 session 请求 — 所有字段可选"""
    title: Optional[str] = None
    remote_session_id: Optional[str] = None
    provider: Optional[str] = None
    pinned: Optional[bool] = None


class MessageCreateRequest(BaseModel):
    """追加 message 请求"""
    id: str
    role: str = "user"  # user / assistant / system / tool
    content: str = ""
    reasoning: Optional[str] = None
    tool_calls: Optional[list] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    error: Optional[str] = None
    streaming: bool = False
    created_at: Optional[int] = None
    updated_at: Optional[int] = None


class MessageUpdateRequest(BaseModel):
    """更新 message 请求 — 所有字段可选"""
    content: Optional[str] = None
    reasoning: Optional[str] = None
    tool_calls: Optional[list] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    error: Optional[str] = None
    streaming: Optional[bool] = None


class BulkImportRequest(BaseModel):
    """批量导入 (用于 localStorage -> SQLite 迁移)"""
    sessions: list
    messages: Dict[str, list] = {}  # session_id -> [messages]


# ========== 服务器类 ==========

class HakusAIServer:
    """
    HakusAI服务器
    
    管理FastAPI应用生命周期和WebSocket连接
    """
    
    def __init__(self):
        self.app: Optional[FastAPI] = None
        self.config = config_manager.config
        self.websocket_manager = WebSocketManager()
        
        # AI组件
        self.model_adapter: Optional[BaseModelAdapter] = None
        self.agent: Optional[BaseAgent] = None
        self.memory: Optional[MemoryManager] = None
        
        # TTS组件
        self.tts_engine = None
        
        # ---- 服务器状态机（Phase 1: /health 异步化）----
        # /health 在 lifespan yield 后立即可用，并通过 self._state 暴露真实状态。
        # AI 组件在后台 task 中初始化，失败不会阻塞 HTTP 服务。
        self._state: ServerState = ServerState.STARTING
        self._init_error: Optional[str] = None
        self._init_started_at: Optional[float] = None
        self._init_finished_at: Optional[float] = None
        # 每个组件的初始化状态: {"model_adapter": "ok"|"failed: <msg>", "agent": "...", ...}
        self._component_status: Dict[str, str] = {}
        # 后台初始化任务
        self._init_task: Optional[asyncio.Task] = None
        # init 完成事件（无论成功失败都会 set），供 chat 端点等待
        self._init_event: asyncio.Event = asyncio.Event()
        
    async def _init_ai_components(self):
        """
        初始化 AI 组件 — 故障容忍版本。
        
        Phase 1 关键改动：
        - 每个组件单独 try/except，失败只记录不抛
        - 关键组件（model_adapter / agent）失败 → state=FAILED
        - 可选组件（memory / TTS / vtuber）失败 → state=DEGRADED
        - 全部成功 → state=HEALTHY
        - 无论结果如何，最后一定 set _init_event（让 chat 端点能感知"初始化已结束"）
        """
        self._init_started_at = time.time()
        self._state = ServerState.INITIALIZING
        logger.info("Starting AI components initialization (background)")
        
        critical_failure: Optional[str] = None
        
        try:
            # 获取模型配置
            model_config = self.config.model.model_dump()
            provider_value = model_config.get("provider", "deepseek")
            # 处理枚举类型
            provider = provider_value.value if hasattr(provider_value, 'value') else str(provider_value)
            
            logger.info(f"Initializing AI model: {provider}")
            
            # 从环境变量或配置文件获取API key
            import os
            import yaml
            api_key = model_config.get("api_key")
            
            # 如果新配置中没有api_key，尝试从旧的config.yaml格式读取
            if not api_key:
                try:
                    with open("config.yaml", "r", encoding="utf-8") as f:
                        old_config = yaml.safe_load(f)
                    
                    api_keys_map = {
                        "deepseek": "deepseek_api_key",
                        "gemini": "gemini_api_key",
                        "qwen": "dashscope_api_key",
                        "glm": "glm_api_key",
                    }
                    key_name = api_keys_map.get(provider)
                    logger.info(f"Looking for API key: {key_name}")
                    if key_name and old_config and "api_keys" in old_config:
                        api_key_value = old_config["api_keys"].get(key_name, "")
                        logger.info(f"Found API key value: {api_key_value[:20]}...")
                        # 处理环境变量格式 ${ENV_VAR:default_value}
                        if api_key_value and api_key_value.startswith("${") and ":" in api_key_value:
                            # 提取默认值
                            default_start = api_key_value.find(":") + 1
                            default_end = api_key_value.find("}")
                            api_key = api_key_value[default_start:default_end]
                            logger.info(f"Extracted default value: {api_key[:20]}...")
                        else:
                            api_key = api_key_value
                        
                        if api_key:
                            logger.info(f"Using API key from config.yaml: {key_name}")
                except Exception as e:
                    logger.warning(f"Failed to read old config format: {e}")
            
            # 如果还是没有，尝试从环境变量获取
            if not api_key:
                env_var_map = {
                    "deepseek": "DEEPSEEK_API_KEY",
                    "gemini": "GEMINI_API_KEY",
                    "openai": "OPENAI_API_KEY",
                    "qwen": "DASHSCOPE_API_KEY",
                    "glm": "GLM_API_KEY",
                }
                env_var = env_var_map.get(provider)
                if env_var:
                    api_key = os.environ.get(env_var)
                    if api_key:
                        logger.info(f"Using API key from environment variable: {env_var}")
            
            # Phase 1: 缺 API key 不再让 lifespan 失败，而是优雅降级到 FAILED 状态
            # HTTP /health 仍然能响应，前端可以读到具体错误并提示用户配置
            if not api_key:
                env_var_map = {
                    "deepseek": "DEEPSEEK_API_KEY",
                    "gemini": "GEMINI_API_KEY",
                    "openai": "OPENAI_API_KEY",
                    "qwen": "DASHSCOPE_API_KEY",
                    "glm": "GLM_API_KEY",
                }
                critical_failure = (
                    f"Missing API key for provider '{provider}'. "
                    f"Set {env_var_map.get(provider, 'API_KEY')} env var "
                    f"or add api_keys.{provider}_api_key to config.yaml."
                )
                self._component_status["model_adapter"] = "failed: missing API key"
                self._component_status["agent"] = "skipped: model_adapter unavailable"
                self._component_status["memory"] = "skipped: not yet initialized"
                self._component_status["tts_engine"] = "skipped: not yet initialized"
                self._component_status["vtuber_handler"] = "skipped: agent unavailable"
                self._component_status["agent_hooks"] = "skipped: agent or memory unavailable"
                logger.error(critical_failure)
                # 直接跳到收尾，不再尝试创建 model_adapter
                raise RuntimeError(critical_failure)
            
            model_config["api_key"] = api_key
            
            # 创建模型适配器
            self.model_adapter = model_registry.create_adapter(provider, model_config)
            await self.model_adapter.initialize()
            self._component_status["model_adapter"] = "ok"
            logger.info(f"Model adapter initialized: {provider}")
            
            # 创建Agent
            self.agent = BaseAgent(self.model_adapter)
            self._component_status["agent"] = "ok"
            logger.info("BaseAgent initialized")
            
            # 初始化记忆系统
            try:
                memory_config = MemoryStorage(
                    max_short_term=self.config.memory.short_term_max,
                    enable_long_term=self.config.memory.long_term_enabled,
                    auto_summary=self.config.memory.auto_summary,
                    summary_interval=self.config.memory.summary_interval,
                )
                self.memory = MemoryManager(memory_config)
                await self.memory.initialize()
                self._component_status["memory"] = "ok"
                logger.info("Memory system initialized")
            except Exception as e:
                self._component_status["memory"] = f"failed: {e}"
                logger.warning(f"Memory init failed (degraded mode): {e}")
            
            # 初始化TTS引擎
            try:
                if self.config.voice.enabled and str(self.config.voice.tts.provider) == "edge":
                    tts_config = self.config.voice.tts.model_dump()
                    self.tts_engine = tts_registry.create_engine("edge", tts_config)
                    await self.tts_engine.initialize()
                    self._component_status["tts_engine"] = "ok"
                    logger.info("TTS engine initialized")
                else:
                    self._component_status["tts_engine"] = "skipped: not edge provider or disabled"
            except Exception as e:
                self._component_status["tts_engine"] = f"failed: {e}"
                logger.warning(f"TTS init failed (degraded mode): {e}")
            
            # 初始化 VTuber handler
            try:
                tts_config = {
                    "type": str(self.config.voice.tts.provider) if self.config.voice.enabled else "edge",
                }
                try:
                    import yaml
                    import re
                    import os

                    def _resolve_env_vars(obj):
                        if isinstance(obj, str):
                            def _replacer(m):
                                var_name = m.group(1)
                                default_val = m.group(2)
                                return os.environ.get(var_name, default_val or '')
                            return re.sub(r'\$\{(\w+)(?::([^}]*))?\}', _replacer, obj)
                        elif isinstance(obj, dict):
                            return {k: _resolve_env_vars(v) for k, v in obj.items()}
                        elif isinstance(obj, list):
                            return [_resolve_env_vars(item) for item in obj]
                        return obj

                    with open("config.yaml", "r", encoding="utf-8") as f:
                        old_config = yaml.safe_load(f)
                    old_config = _resolve_env_vars(old_config)
                    if old_config and "tts" in old_config:
                        tts_config.update(old_config["tts"])
                        tts_type = tts_config.get("type", "")
                        if tts_type == "cosyvoice" and old_config.get("tts", {}).get("cosyvoice"):
                            tts_config.update(old_config["tts"]["cosyvoice"])
                        elif tts_type == "voxcpm":
                            logger.info("TTS config: using VoxCPM engine")
                except Exception as e:
                    logger.warning(f"Failed to load TTS config: {e}")

                await vtuber_handler.initialize(
                    agent=self.agent,
                    model_adapter=self.model_adapter,
                    tts_config=tts_config
                )
                self._component_status["vtuber_handler"] = "ok"
                logger.info("VTuber WebSocket handler initialized")
            except Exception as e:
                self._component_status["vtuber_handler"] = f"failed: {e}"
                logger.warning(f"VTuber handler init failed (degraded mode): {e}")
            
            # 设置Agent记忆钩子
            if self.memory and self.agent:
                try:
                    self.agent.add_hook("before_chat", self._before_chat_hook)
                    self.agent.add_hook("after_chat", self._after_chat_hook)
                    self._component_status["agent_hooks"] = "ok"
                except Exception as e:
                    self._component_status["agent_hooks"] = f"failed: {e}"
                    logger.warning(f"Agent hook setup failed: {e}")
            else:
                self._component_status["agent_hooks"] = "skipped: agent or memory unavailable"
            
        except Exception as e:
            # 关键组件失败 — 记录但不抛
            if not critical_failure:
                critical_failure = f"AI init critical failure: {e}"
                logger.error(f"AI init critical failure: {e}", exc_info=True)
        finally:
            # 状态收尾
            if critical_failure is not None:
                self._state = ServerState.FAILED
                self._init_error = critical_failure
                logger.error(f"AI initialization FAILED (critical): {critical_failure}")
            elif any(v.startswith("failed") for v in self._component_status.values()):
                self._state = ServerState.DEGRADED
                failed_optional = [
                    name for name, st in self._component_status.items()
                    if st.startswith("failed") and name not in ("model_adapter", "agent")
                ]
                self._init_error = (
                    f"Some optional components failed: {', '.join(failed_optional)}. "
                    f"Core chat is available."
                ) if failed_optional else None
                logger.warning(f"AI initialization DEGRADED: {self._init_error}")
            else:
                self._state = ServerState.HEALTHY
                self._init_error = None
                logger.info("AI initialization HEALTHY — all components ready")
            
            self._init_finished_at = time.time()
            duration = self._init_finished_at - (self._init_started_at or self._init_finished_at)
            logger.info(f"AI init finished in {duration:.2f}s — state={self._state.value}")
            # 无论成功失败都 set，让 chat 端点能感知初始化已结束
            self._init_event.set()
    
    async def _ensure_ready(self, timeout: float = 10.0) -> bool:
        """
        等待 AI 初始化完成（成功或失败）。
        
        - 返回 True: 初始化已结束（不代表成功，调用方需再检查 self.agent）
        - 返回 False: 超时仍未结束
        """
        try:
            await asyncio.wait_for(self._init_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False
    
    def _build_health_payload(self) -> Dict[str, Any]:
        """构造 /health 响应体（lifespan 起飞后任何时刻都可调用）"""
        ready = self.agent is not None
        duration = None
        if self._init_started_at and self._init_finished_at:
            duration = round(self._init_finished_at - self._init_started_at, 2)
        elif self._init_started_at:
            duration = round(time.time() - self._init_started_at, 2)
        return {
            "status": self._state.value,
            "ready": ready,
            "version": "2.0.0",
            "model_loaded": self.model_adapter is not None,
            "agent_ready": self.agent is not None,
            "memory_ready": self.memory is not None,
            "tts_ready": self.tts_engine is not None,
            "error": self._init_error,
            "init_duration_s": duration,
        }
    
    async def _before_chat_hook(self, user_input: str, context: AgentContext):
        """对话前钩子 - 加载记忆上下文"""
        if not self.memory:
            return
        
        # 获取相关记忆
        memory_context = await self.memory.get_context_for_model(
            max_short_term=10,
            max_long_term=3,
            query=user_input
        )
        
        if memory_context:
            # 将记忆添加到Agent的历史中
            for msg in memory_context:
                if msg["role"] != "system":  # 避免重复添加系统消息
                    self.agent._message_history.append(Message(
                        role=MessageRole(msg["role"]),
                        content=msg["content"]
                    ))
    
    async def _after_chat_hook(self, user_input: str, context: AgentContext):
        """对话后钩子 - 保存到记忆"""
        if not self.memory:
            return
        
        # 保存用户消息
        await self.memory.add_message("user", user_input)
        
        # 保存助手回复（从Agent历史中获取最后一条）
        if self.agent._message_history:
            last_msg = self.agent._message_history[-1]
            if last_msg.role == MessageRole.ASSISTANT:
                await self.memory.add_message("assistant", last_msg.content)
    
    def create_app(self) -> FastAPI:
        """创建FastAPI应用"""
        
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            """
            应用生命周期管理 — Phase 1 异步化版本。
            
            关键改动：AI 组件初始化不再阻塞 lifespan。我们：
            1. 启动 event_bus
            2. 把 _init_ai_components 丢到后台 task
            3. 立即 yield，让 FastAPI 开始服务（/health 此刻可响应 status=initializing）
            4. 关闭时：先等/取消后台 task，再优雅关闭组件
            """
            # 启动时
            logger.info("Starting HakusAI Server...")
            await event_bus.start()
            # 标记进入初始化中（_init_ai_components 内部也会设）
            self._state = ServerState.INITIALIZING
            # 后台启动 AI 初始化 — 不阻塞 lifespan
            self._init_task = asyncio.create_task(self._init_ai_components())
            # 添加 done 回调，记录未捕获异常
            def _log_init_failure(fut: asyncio.Task):
                if fut.cancelled():
                    logger.warning("AI init task was cancelled.")
                    return
                exc = fut.exception()
                if exc is not None:
                    # _init_ai_components 内部已 try/except，这里只是兜底
                    logger.error(f"AI init task crashed unexpectedly: {exc}", exc_info=exc)
            self._init_task.add_done_callback(_log_init_failure)
            
            # Start MCP servers from ~/.hakus/config.yaml (Phase 2 round 2).
            # Non-blocking: failures don't crash the sidecar unless fail_fast=True
            # in the global mcp: config section.
            try:
                from hakus.mcp.manager import get_mcp_manager
                mcp_mgr = get_mcp_manager()
                if mcp_mgr is not None:
                    logger.info("[MCP] starting servers from config...")
                    await mcp_mgr.start_all_from_config()
                    statuses = mcp_mgr.list_servers_status()
                    running = sum(1 for s in statuses if s.get("status") == "running")
                    failed = sum(1 for s in statuses if s.get("status") == "failed")
                    logger.info(
                        f"[MCP] startup complete: {running} running, "
                        f"{failed} failed, {len(statuses)} total"
                    )
            except Exception as e:
                logger.warning(f"[MCP] startup failed (non-blocking): {e}", exc_info=True)
            
            yield
            
            # 关闭时
            logger.info("Shutting down HakusAI Server...")
            # 如果 init 还没完成，等它结束（最多 5s），避免资源没释放
            if self._init_task is not None and not self._init_task.done():
                logger.info("Waiting for in-flight AI init to finish before shutdown...")
                try:
                    await asyncio.wait_for(self._init_task, timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning("AI init still running after 5s, cancelling...")
                    self._init_task.cancel()
                    try:
                        await self._init_task
                    except asyncio.CancelledError:
                        pass
                except Exception as e:
                    logger.warning(f"AI init task raised during shutdown: {e}")
            
            # 优雅关闭已初始化的组件
            if self.memory:
                try:
                    await self.memory.close()
                except Exception as e:
                    logger.warning(f"Memory close failed: {e}")
            if self.model_adapter:
                try:
                    await self.model_adapter.close()
                except Exception as e:
                    logger.warning(f"Model adapter close failed: {e}")
            try:
                await event_bus.stop()
            except Exception as e:
                logger.warning(f"Event bus stop failed: {e}")
            
            # Stop all MCP servers (Phase 2 round 2)
            try:
                from hakus.mcp.manager import get_mcp_manager
                mcp_mgr = get_mcp_manager()
                if mcp_mgr is not None:
                    logger.info("[MCP] stopping all servers...")
                    await mcp_mgr.stop_all()
                    logger.info("[MCP] all servers stopped")
            except Exception as e:
                logger.warning(f"[MCP] stop_all failed: {e}")
        
        app = FastAPI(
            title="HakusAI API",
            description="HakusAI 2.0 AI虚拟助手API",
            version="2.0.0",
            lifespan=lifespan
        )
        
        # CORS中间件
        app.add_middleware(
            CORSMiddleware,
            allow_origins=self.config.server.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        # 注册路由
        self._register_routes(app)
        
        # 挂载静态文件（前端）- 优先使用新的 React 前端
        stage_web_dist = Path(__file__).parent.parent.parent / "stage-web" / "dist"
        webui_dist = Path(__file__).parent.parent.parent / "webui" / "dist"

        if stage_web_dist.exists():
            app.mount("/assets", StaticFiles(directory=stage_web_dist / "assets"), name="assets")

            @app.get("/{full_path:path}")
            async def serve_spa(full_path: str):
                file_path = stage_web_dist / full_path
                if file_path.exists() and file_path.is_file():
                    return FileResponse(file_path)
                return FileResponse(stage_web_dist / "index.html")

            logger.info(f"Stage-Web mounted from {stage_web_dist}")
        elif webui_dist.exists():
            app.mount("/assets", StaticFiles(directory=webui_dist / "assets"), name="assets")

            @app.get("/{full_path:path}")
            async def serve_spa(full_path: str):
                file_path = webui_dist / full_path
                if file_path.exists() and file_path.is_file():
                    return FileResponse(file_path)
                return FileResponse(webui_dist / "index.html")

            logger.info(f"WebUI mounted from {webui_dist}")
        
        self.app = app
        return app
    
    def _register_routes(self, app: FastAPI):
        """注册API路由"""
        
        # 中间件：记录所有 /api/ 请求的耗时和状态码，方便诊断"卡住"问题
        @app.middleware("http")
        async def log_api_requests(request, call_next):
            path = request.url.path
            if path.startswith("/api/") or path == "/health":
                t0 = time.time()
                try:
                    response = await call_next(request)
                    dt = (time.time() - t0) * 1000
                    if dt > 1000:  # 超过 1s 的请求记 warning
                        logger.warning(f"SLOW {request.method} {path} -> {response.status_code} in {dt:.0f}ms")
                    else:
                        logger.info(f"{request.method} {path} -> {response.status_code} in {dt:.0f}ms")
                    return response
                except Exception as e:
                    dt = (time.time() - t0) * 1000
                    logger.error(f"ERROR {request.method} {path} -> {e} in {dt:.0f}ms")
                    raise
            return await call_next(request)
        
        @app.get("/")
        async def root():
            """根路径"""
            return {
                "name": "HakusAI",
                "version": "2.0.0",
                "status": "running"
            }

        @app.get("/api/version")
        async def get_version():
            """
            返回 sidecar API 版本 — 客户端用来检测 sidecar 是否过旧。

            场景：用户更新了客户端 (electron app)，但 Windows NSIS 安装时
            sidecar.exe 可能因为旧进程仍占用、杀软拦截、用户覆盖安装时
            选了"保留旧文件"等原因没被替换。这时客户端会向旧 sidecar 发
            请求，遇到一堆莫名其妙的 404。

            客户端启动时调 /api/version，如果 version < 期望版本，直接
            提示用户「sidecar 版本过旧，请重新下载最新版客户端」。
            """
            return {
                "sidecar_api_version": SIDECAR_API_VERSION,
                "sidecar_api_version_int": SIDECAR_API_VERSION_INT,
                "server_version": "2.0.0",
                "use_agentcore_for_chat": USE_AGENTCORE_FOR_CHAT,
                "agentcore_tools_count": 24,  # hakus/tools/builtin — kept in sync manually
                "endpoints": [
                    "/api/config/providers",
                    "/api/character",
                    "/api/memory/details",
                    "/api/tools",
                    "/api/permission",
                    "/api/config/export",
                    "/api/diagnostics",
                    "/api/agentcore/status",
                    "/api/sessions",
                    "/api/sessions/{id}/messages",
                ],
            }

        @app.get("/api/agentcore/status")
        async def agentcore_status():
            """Return AgentCore integration status.

            Lets the desktop client verify that the sidecar is using
            the new AgentCore path (24 tools + permissions + AgentEvent
            stream) vs. the legacy BaseAgent chat-only path.
            """
            from .agent_bridge import _agent_cache
            return {
                "use_agentcore_for_chat": USE_AGENTCORE_FOR_CHAT,
                "active_sessions": list(_agent_cache.keys()),
                "session_count": len(_agent_cache),
                "tools_available": USE_AGENTCORE_FOR_CHAT,
                "permission_mode_default": "ask",
                "auto_approve_in_sidecar": True,  # no UI to prompt
                "stream_event_types": [
                    "text_delta", "reasoning_delta",
                    "tool_call_started", "tool_call_finished",
                    "token_usage",
                    "turn_completed", "turn_failed", "cancelled",
                ],
            }

        @app.get("/health")
        async def health_check():
            """
            健康检查 — Phase 1 三态版本。
            
            始终返回 200（只要 FastAPI 起来了就返回），通过 status 字段告诉客户端真实状态：
            - starting:      进程刚启动
            - initializing:  AI 组件正在后台初始化
            - healthy:       所有关键组件就绪，可正常对话
            - degraded:      关键组件就绪，TTS/Memory 等可选组件部分失败
            - failed:        关键组件初始化失败（如 API key 缺失），chat 不可用
            
            sidecar.ts 应当：
            - status == healthy 或 degraded: 视为可用，停止轮询
            - status == starting 或 initializing: 继续轮询
            - status == failed: 立即停止轮询，向用户展示 error
            """
            return self._build_health_payload()
        
        @app.get("/api/diagnostics")
        async def diagnostics():
            """
            诊断端点 — 返回详细的初始化状态，方便前端展示具体错误。
            
            用于 sidecar 健康检查失败时，UI 可以直接拉这个端点告诉用户
            "你的 DeepSeek API key 没配" 而不是只显示 "sidecar 30s 超时"。
            """
            payload = self._build_health_payload()
            payload["components"] = dict(self._component_status)
            payload["init_started_at"] = self._init_started_at
            payload["init_finished_at"] = self._init_finished_at
            # 列出已注册的模型 provider
            try:
                payload["registered_providers"] = model_registry.list_providers()
            except Exception:
                payload["registered_providers"] = []
            # 当前 provider 配置
            try:
                model_config = self.config.model.model_dump()
                provider_value = model_config.get("provider", "deepseek")
                provider = provider_value.value if hasattr(provider_value, 'value') else str(provider_value)
                payload["configured_provider"] = provider
                payload["configured_model_name"] = model_config.get("model_name")
            except Exception as e:
                payload["configured_provider"] = f"<error: {e}>"
            return payload
        
        # ========== 聊天API ==========
        
        @app.post("/api/chat")
        async def chat(request: ChatRequest):
            """
            聊天接口（非流式）

            请求体:
            {
                "message": "你好",
                "session_id": "default",
                "stream": false
            }

            当 USE_AGENTCORE_FOR_CHAT=True 时，走 hakus.AgentCore
            (24 工具 + 权限流 + AgentEvent 协议); 否则回退到旧
            BaseAgent 单轮聊天路径。
            """
            # Phase 1: 如果还在初始化中，先等一下（最多 10s）
            if not await self._ensure_ready(timeout=10.0):
                raise HTTPException(
                    status_code=503,
                    detail="AI still initializing, please retry in a few seconds"
                )

            # AgentCore 路径 — 不需要 self.agent (BaseAgent) 就绪，
            # 它自己会 lazy-init LLM client。但要求 model_adapter 至少
            # 初始化过（说明 API key 配了）—— 否则给具体错误。
            if USE_AGENTCORE_FOR_CHAT:
                if not self.model_adapter:
                    raise HTTPException(
                        status_code=503,
                        detail=f"Model not initialized: {self._init_error or 'unknown reason'}"
                    )
                try:
                    logger.info(f"Chat (AgentCore): {request.message[:80]} provider={request.provider or 'default'}")
                    result = await agentcore_run_turn_collect(
                        request.message, request.session_id,
                        provider=request.provider,
                    )
                    logger.info(
                        f"Chat response: {result['content'][:100]}... "
                        f"(iter={result.get('iterations')}, "
                        f"in_tok={result.get('input_tokens')}, "
                        f"out_tok={result.get('output_tokens')})"
                    )
                    return result
                except Exception as e:
                    logger.error(f"AgentCore chat error: {e}", exc_info=True)
                    raise HTTPException(status_code=500, detail=str(e))

            # 旧路径 (BaseAgent)
            if not self.agent:
                raise HTTPException(
                    status_code=503,
                    detail=f"Agent not initialized: {self._init_error or 'unknown reason'}"
                )

            try:
                logger.info(f"Chat request: {request.message}")
                context = AgentContext(
                    session_id=request.session_id,
                    user_id="default"
                )

                # 收集完整响应
                full_content = ""
                emotion = None
                actions = []

                async for response in self.agent.chat(request.message, context, stream=False):
                    full_content = response.content
                    emotion = response.emotion
                    actions = response.actions
                    logger.debug(f"Response chunk: {response.content[:50]}...")

                logger.info(f"Chat response: {full_content[:100]}...")

                return {
                    "content": full_content,
                    "emotion": emotion,
                    "actions": actions,
                    "session_id": request.session_id
                }

            except Exception as e:
                logger.error(f"Chat error: {e}")
                import traceback
                logger.error(traceback.format_exc())
                raise HTTPException(status_code=500, detail=str(e))

        @app.post("/api/chat/stream")
        async def chat_stream(request: ChatRequest):
            """
            聊天接口（流式）

            返回SSE流。每个事件是 ``data: {json}\\n\\n``。

            AgentCore 路径会发更丰富的事件类型 (event_type 字段):
              - text_delta / reasoning_delta / tool_call_started /
                tool_call_finished / token_usage / turn_completed /
                turn_failed / cancelled

            旧前端只看 content + done, 这些字段在所有事件里都保留。
            新前端可以按 event_type 路由渲染。
            """
            # Phase 1: 等初始化完成，否则发 503
            if not await self._ensure_ready(timeout=10.0):
                raise HTTPException(
                    status_code=503,
                    detail="AI still initializing, please retry in a few seconds"
                )

            if USE_AGENTCORE_FOR_CHAT:
                if not self.model_adapter:
                    raise HTTPException(
                        status_code=503,
                        detail=f"Model not initialized: {self._init_error or 'unknown reason'}"
                    )

                async def generate_agentcore():
                    try:
                        async for chunk in agentcore_run_turn_stream(
                            request.message, request.session_id,
                            provider=request.provider,
                        ):
                            yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                    except Exception as e:
                        logger.error(f"AgentCore stream error: {e}", exc_info=True)
                        err = {
                            "content": "",
                            "emotion": None,
                            "actions": [],
                            "done": True,
                            "event_type": "turn_failed",
                            "error": str(e),
                            "code": "stream_error",
                        }
                        yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"

                return StreamingResponse(
                    generate_agentcore(),
                    media_type="text/event-stream",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                    }
                )

            # 旧路径
            if not self.agent:
                raise HTTPException(
                    status_code=503,
                    detail=f"Agent not initialized: {self._init_error or 'unknown reason'}"
                )

            async def generate():
                try:
                    context = AgentContext(
                        session_id=request.session_id,
                        user_id="default"
                    )

                    async for response in self.agent.chat(request.message, context, stream=True):
                        data = {
                            "content": response.content,
                            "emotion": response.emotion,
                            "actions": response.actions,
                            "done": False
                        }
                        yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

                    # 发送结束标记
                    yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"

                except Exception as e:
                    logger.error(f"Stream chat error: {e}")
                    yield f"data: {json.dumps({'error': str(e), 'done': True}, ensure_ascii=False)}\n\n"

            return StreamingResponse(
                generate(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                }
            )
        
        @app.post("/api/chat/message")
        async def chat_message(request: ChatRequest):
            """
            简单聊天接口（兼容前端）
            返回JSON格式
            """
            # Phase 1: 等初始化完成
            if not await self._ensure_ready(timeout=10.0):
                return {
                    "error": "AI still initializing, please retry in a few seconds",
                    "success": False,
                    "retry_after_s": 2,
                }

            # AgentCore 路径
            if USE_AGENTCORE_FOR_CHAT:
                if not self.model_adapter:
                    return {
                        "error": f"Model not initialized: {self._init_error or 'unknown reason'}",
                        "success": False,
                    }
                try:
                    result = await agentcore_run_turn_collect(
                        request.message, request.session_id,
                        provider=request.provider,
                    )
                    return {
                        "success": not result.get("failed", False),
                        "data": {
                            "content": result["content"],
                            "role": "assistant",
                            "iterations": result.get("iterations", 0),
                            "input_tokens": result.get("input_tokens", 0),
                            "output_tokens": result.get("output_tokens", 0),
                        },
                        "error": result.get("error"),
                    }
                except Exception as e:
                    logger.error(f"AgentCore chat_message error: {e}", exc_info=True)
                    return {"success": False, "error": str(e)}

            # 旧路径
            if not self.agent:
                return {
                    "error": f"Agent not initialized: {self._init_error or 'unknown reason'}",
                    "success": False,
                }

            try:
                context = AgentContext(
                    session_id=request.session_id,
                    user_id="default"
                )

                # 收集完整响应
                full_content = ""

                async for response in self.agent.chat(request.message, context, stream=False):
                    full_content = response.content

                return {
                    "success": True,
                    "data": {
                        "content": full_content,
                        "role": "assistant"
                    }
                }

            except Exception as e:
                logger.error(f"Chat error: {e}")
                return {
                    "success": False,
                    "error": str(e)
                }

        # ========== Session 持久化 API (SQLite) ==========
        # 替代前端 localStorage 的会话存储. 用户在桌面客户端看到的所有
        # chat 历史 (sessions + messages) 都持久化在 ~/.hakus/sessions.db.
        #
        # 设计:
        #   - Sessions / messages 通过 REST CRUD 接口管理
        #   - Streaming 期间前端只更新 in-memory state, stream 结束时
        #     一次性 PATCH 最终 message (content + reasoning + tool_calls)
        #   - User 消息在 send 时立即 POST (它已经是 final 状态)
        #   - 跨设备同步留 Phase 3 (现在只解决"localStorage 5MB 上限 +
        #     浏览器缓存清空就丢"的问题)

        @app.get("/api/sessions")
        async def list_sessions_api():
            """列出所有 sessions (按 updated_at 倒序, pinned 优先).
            不返回 messages — 客户端按需 GET /api/sessions/{id} 拉详情."""
            try:
                return {"sessions": session_store.list_sessions()}
            except Exception as e:
                logger.error(f"list_sessions failed: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @app.post("/api/sessions")
        async def create_session_api(req: SessionCreateRequest):
            """创建 session. 客户端生成 UUID (s_xxx), 服务端只负责持久化."""
            try:
                return session_store.create_session(
                    session_id=req.id,
                    title=req.title,
                    remote_session_id=req.remote_session_id,
                    provider=req.provider,
                    pinned=req.pinned,
                    created_at=req.created_at,
                    updated_at=req.updated_at,
                )
            except Exception as e:
                logger.error(f"create_session failed: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        # -----------------------------------------------------------------
        # 注意路由注册顺序: 字面量路径 (export / migrate) 必须在
        # /api/sessions/{session_id} 之前注册, 否则 FastAPI 会把 "export"
        # 当成 session_id 匹配到 {session_id} 路由, 返回 404.
        # -----------------------------------------------------------------

        @app.get("/api/sessions/export")
        async def export_sessions_api():
            """导出全部 sessions + messages 为单个 JSON.
            用于「备份聊天记录」按钮 — 用户下载后可保存到任意位置,
            下次重装/换机时通过 POST /api/sessions/migrate 恢复.

            返回格式与 /api/sessions/migrate 的请求体一致 (schema_version +
            exported_at + sessions + messages), 所以导出文件可以直接喂给
            导入端点, 不需要前端做格式转换.
            """
            try:
                return session_store.export_all()
            except Exception as e:
                logger.error(f"export_sessions failed: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @app.post("/api/sessions/migrate")
        async def migrate_sessions_api(req: BulkImportRequest):
            """批量导入 sessions + messages. 用于把前端 localStorage 里
            已有的历史一次性导入 SQLite. 幂等 (INSERT OR REPLACE)."""
            try:
                counts = session_store.bulk_import(req.sessions, req.messages)
                return {"imported": counts}
            except Exception as e:
                logger.error(f"migrate_sessions failed: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @app.get("/api/sessions/{session_id}")
        async def get_session_api(session_id: str):
            """获取单个 session + 其所有 messages (按 created_at 升序)."""
            try:
                sess = session_store.get_session(session_id)
                if not sess:
                    raise HTTPException(status_code=404, detail="session not found")
                msgs = session_store.list_messages(session_id)
                return {**sess, "messages": msgs}
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"get_session failed: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @app.patch("/api/sessions/{session_id}")
        async def update_session_api(session_id: str, req: SessionUpdateRequest):
            """更新 session 的 title / pinned / provider / remote_session_id."""
            try:
                result = session_store.update_session(
                    session_id,
                    title=req.title,
                    remote_session_id=req.remote_session_id,
                    provider=req.provider,
                    pinned=req.pinned,
                )
                if not result:
                    raise HTTPException(status_code=404, detail="session not found")
                return result
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"update_session failed: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @app.delete("/api/sessions/{session_id}")
        async def delete_session_api(session_id: str):
            """删除 session + 级联删除其所有 messages."""
            try:
                ok = session_store.delete_session(session_id)
                if not ok:
                    raise HTTPException(status_code=404, detail="session not found")
                # 同时清掉 agent_bridge 里这个 session 的 AgentCore 缓存
                try:
                    agentcore_clear_session(session_id)
                except Exception as _e:
                    logger.warning(f"clear_session_history failed: {_e}")
                return {"deleted": True, "id": session_id}
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"delete_session failed: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @app.get("/api/sessions/{session_id}/messages")
        async def list_messages_api(session_id: str):
            """列出某 session 的所有 messages."""
            try:
                if not session_store.get_session(session_id):
                    raise HTTPException(status_code=404, detail="session not found")
                return {"messages": session_store.list_messages(session_id)}
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"list_messages failed: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @app.post("/api/sessions/{session_id}/messages")
        async def add_message_api(session_id: str, req: MessageCreateRequest):
            """追加 message. 用于:
              - user 消息 (send 时立即写)
              - assistant 消息占位 (stream 开始时建空 row, 结束时 PATCH)
            """
            try:
                if not session_store.get_session(session_id):
                    raise HTTPException(status_code=404, detail="session not found")
                return session_store.add_message(
                    session_id=session_id,
                    message_id=req.id,
                    role=req.role,
                    content=req.content,
                    reasoning=req.reasoning,
                    tool_calls=req.tool_calls,
                    input_tokens=req.input_tokens,
                    output_tokens=req.output_tokens,
                    error=req.error,
                    streaming=req.streaming,
                    created_at=req.created_at,
                    updated_at=req.updated_at,
                )
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"add_message failed: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @app.patch("/api/sessions/{session_id}/messages/{message_id}")
        async def update_message_api(session_id: str, message_id: str, req: MessageUpdateRequest):
            """更新 message. 用于 stream 完成时把最终 content / tool_calls /
            tokens 一次性写入."""
            try:
                result = session_store.update_message(
                    message_id,
                    content=req.content,
                    reasoning=req.reasoning,
                    tool_calls=req.tool_calls,
                    input_tokens=req.input_tokens,
                    output_tokens=req.output_tokens,
                    error=req.error,
                    streaming=req.streaming,
                )
                if not result:
                    raise HTTPException(status_code=404, detail="message not found")
                return result
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"update_message failed: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @app.delete("/api/sessions/{session_id}/messages/{message_id}")
        async def delete_message_api(session_id: str, message_id: str):
            """删除单个 message."""
            try:
                ok = session_store.delete_message(message_id)
                if not ok:
                    raise HTTPException(status_code=404, detail="message not found")
                return {"deleted": True, "id": message_id}
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"delete_message failed: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @app.delete("/api/sessions/{session_id}/messages")
        async def clear_session_messages_api(session_id: str):
            """清空某 session 的所有 messages (保留 session 行).
            用于 TopBar '清空对话' — 用户想在同一个 session 里重新开始."""
            try:
                if not session_store.get_session(session_id):
                    raise HTTPException(status_code=404, detail="session not found")
                n = session_store.clear_session_messages(session_id)
                # 同时清掉 AgentCore 的 in-memory context, 让 LLM 也"忘记"
                try:
                    agentcore_clear_session(session_id)
                except Exception as _e:
                    logger.warning(f"clear_session_history failed: {_e}")
                return {"deleted_messages": n, "session_id": session_id}
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"clear_session_messages failed: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @app.delete("/api/sessions")
        async def wipe_all_sessions_api():
            """删除所有 sessions + messages. 危险操作 — 前端必须二次确认."""
            try:
                n = session_store.wipe_all()
                return {"deleted_sessions": n}
            except Exception as e:
                logger.error(f"wipe_all_sessions failed: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        # ========== 配置API ==========
        
        @app.get("/api/config")
        async def get_config():
            """获取配置（安全版本，隐藏敏感信息）"""
            config = config_manager.config
            return {
                "version": config.version,
                "character": {
                    "name": config.character.name,
                    "personality": config.character.personality,
                },
                "model": {
                    "provider": config.model.provider,
                    "model_name": config.model.model_name,
                },
                "voice": {
                    "enabled": config.voice.enabled,
                    "asr_provider": config.voice.asr.provider,
                    "tts_provider": config.voice.tts.provider,
                },
                "avatar": {
                    "enabled": config.avatar.enabled,
                    "type": config.avatar.type,
                    "name": config.avatar.name,
                },
            }
        
        @app.get("/api/config/full")
        async def get_full_config():
            """获取完整配置（需要认证）"""
            # TODO: 添加认证
            return config_manager.config.model_dump()
        
        @app.post("/api/config/reload")
        async def reload_config():
            """重新加载配置"""
            await config_manager.reload()
            return {"message": "Config reloaded"}

        # ========== 模型 provider 配置 API ==========
        # 这些端点让桌面客户端能编辑 ~/.hakus/config.yaml 里的 model_name / base_url / api_key,
        # 不需要用户手动改文件。对应 TUI 的 ModelConfigOverlay。

        @app.get("/api/config/providers")
        async def list_providers():
            """列出所有支持的 AI provider 及当前配置状态（隐藏 api_key 明文）"""
            # 与 TUI model_config_overlay.py 的 _PROVIDER_META 保持一致
            PROVIDER_META = {
                "opencode":   {"key_name": "opencode_api_key",   "has_url": True,  "display": "OpenCode"},
                "deepseek":   {"key_name": "deepseek_api_key",   "has_url": True,  "display": "DeepSeek"},
                "openai":     {"key_name": "openai_api_key",     "has_url": True,  "display": "OpenAI"},
                "anthropic":  {"key_name": "anthropic_api_key",  "has_url": True,  "display": "Anthropic Claude"},
                "qwen":       {"key_name": "dashscope_api_key",  "has_url": False, "display": "Qwen (通义千问)"},
                "gemini":     {"key_name": "gemini_api_key",     "has_url": False, "display": "Gemini"},
                "glm":        {"key_name": "glm_api_key",        "has_url": False, "display": "GLM (智谱)"},
                "mimo":       {"key_name": "mimo_api_key",       "has_url": True,  "display": "MiMo (小米)"},
                "ollama":     {"key_name": "",                  "has_url": True,  "display": "Ollama (本地)"},
            }
            # 读取 ~/.hakus/config.yaml
            import os, yaml as _yaml
            from pathlib import Path as _Path
            config_path = _Path(os.path.expanduser("~/.hakus/config.yaml"))
            raw: dict = {}
            if config_path.exists():
                try:
                    raw = _yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                except Exception:
                    raw = {}
            api_keys = raw.get("api_keys", {}) or {}
            models_cfg = raw.get("models", {}) or {}
            default_model = models_cfg.get("default_model", "deepseek")

            # Resolve ${VAR:default} env-var placeholders so the UI shows
            # actual values (e.g. "deepseek-chat") rather than the raw
            # template string. The placeholder format follows shell
            # parameter expansion: ${VAR:-default} or ${VAR:default}.
            #
            # Applied to base_url / model_name / api_key uniformly so the
            # masked_api_key is the real resolved key, not the literal
            # "${OPENAI_API_KEY:sk-xxx}" template.
            from .provider_ops import resolve_placeholder, looks_like_placeholder, _mask_key

            providers = []
            for pid, meta in PROVIDER_META.items():
                prov_cfg = models_cfg.get(pid, {}) or {}
                key_name = meta["key_name"]
                raw_key = api_keys.get(key_name, "") if key_name else ""
                resolved_key = resolve_placeholder(raw_key) if raw_key else ""
                # If the placeholder couldn't be resolved (no env, no default),
                # has_api_key should be False so the UI shows the "未配置" state
                # rather than a misleading masked string.
                unresolved = looks_like_placeholder(resolved_key)
                has_key = bool(resolved_key) and not unresolved
                # _mask_key returns "<未设置环境变量>" if val still looks like
                # a ${VAR} placeholder, otherwise the standard "sk-xx...yyyy"
                # mask. We always show the mask (even when unresolved) so the
                # user understands "yes I do have a template here, but the env
                # var isn't set".
                masked = _mask_key(resolved_key) if resolved_key else ""
                raw_model = prov_cfg.get("model_name", "")
                raw_url = prov_cfg.get("base_url", "")
                providers.append({
                    "id": pid,
                    "display_name": meta["display"],
                    "has_url": meta["has_url"],
                    "has_api_key": has_key,
                    "masked_api_key": masked,
                    "model_name": resolve_placeholder(raw_model),
                    "base_url": resolve_placeholder(raw_url),
                    "is_default": pid == default_model,
                })
            return {"providers": providers, "default_model": default_model}

        @app.post("/api/config/providers")
        async def update_provider(request: dict):
            """
            更新某个 provider 的配置（model_name / base_url / api_key），并热重载。

            请求体:
            {
                "provider": "deepseek",
                "model_name": "deepseek-chat",   // 可选, 留空不变
                "base_url": "https://...",       // 可选, 留空不变
                "api_key": "sk-xxx",             // 可选, 留空表示清除
                "set_as_default": true           // 可选, 把这个 provider 设为默认
            }
            """
            import os, yaml as _yaml
            from pathlib import Path as _Path

            provider_id = request.get("provider", "").lower()
            if not provider_id:
                raise HTTPException(status_code=400, detail="provider is required")

            PROVIDER_META = {
                "opencode": "opencode_api_key", "deepseek": "deepseek_api_key",
                "openai": "openai_api_key", "anthropic": "anthropic_api_key",
                "qwen": "dashscope_api_key", "gemini": "gemini_api_key",
                "glm": "glm_api_key", "mimo": "mimo_api_key", "ollama": "",
            }
            if provider_id not in PROVIDER_META:
                raise HTTPException(status_code=400, detail=f"unknown provider: {provider_id}")

            config_dir = _Path(os.path.expanduser("~/.hakus"))
            config_dir.mkdir(parents=True, exist_ok=True)
            config_path = config_dir / "config.yaml"

            # 读取现有配置
            raw: dict = {}
            if config_path.exists():
                try:
                    raw = _yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                except Exception:
                    raw = {}
            raw.setdefault("api_keys", {})
            raw.setdefault("models", {})

            # 应用 model_name / base_url
            prov_raw: dict = raw["models"].setdefault(provider_id, {})
            if "model_name" in request and request["model_name"]:
                prov_raw["model_name"] = request["model_name"]
            if "base_url" in request:
                if request["base_url"]:
                    prov_raw["base_url"] = request["base_url"]
                else:
                    prov_raw.pop("base_url", None)

            # 应用 api_key
            key_name = PROVIDER_META[provider_id]
            if key_name and "api_key" in request:
                if request["api_key"]:
                    raw["api_keys"][key_name] = request["api_key"]
                else:
                    raw["api_keys"].pop(key_name, None)

            # 设为默认
            if request.get("set_as_default"):
                raw["models"]["default_model"] = provider_id

            # 写回
            try:
                config_path.write_text(
                    _yaml.dump(raw, allow_unicode=True, default_flow_style=False, sort_keys=False),
                    encoding="utf-8",
                )
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"failed to write config: {e}")

            # 热重载
            try:
                await config_manager.reload()
            except Exception as e:
                logger.warning(f"Config saved but reload failed: {e}")
            return {"message": "Provider config saved", "provider": provider_id}

        @app.post("/api/config/default-model")
        async def set_default_model(request: dict):
            """切换默认模型 provider"""
            import os, yaml as _yaml
            from pathlib import Path as _Path

            provider_id = request.get("provider", "").lower()
            if not provider_id:
                raise HTTPException(status_code=400, detail="provider is required")

            config_path = _Path(os.path.expanduser("~/.hakus/config.yaml"))
            raw: dict = {}
            if config_path.exists():
                try:
                    raw = _yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                except Exception:
                    raw = {}
            raw.setdefault("models", {})
            raw["models"]["default_model"] = provider_id
            try:
                config_path.write_text(
                    _yaml.dump(raw, allow_unicode=True, default_flow_style=False, sort_keys=False),
                    encoding="utf-8",
                )
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"failed to write config: {e}")
            try:
                await config_manager.reload()
            except Exception as e:
                logger.warning(f"Default model saved but reload failed: {e}")
            return {"message": "Default model updated", "default_model": provider_id}

        # ========== Provider 运维操作 API ==========
        # 这些端点让桌面客户端能在 Provider 设置页里:
        #   - 测试连接 (POST /api/providers/{id}/test)
        #   - 获取可用模型列表 (POST /api/providers/{id}/fetch-models)
        #   - 多 API Key 轮换管理 (GET/POST/DELETE /api/providers/{id}/keys[/{key_id}])
        #   - 自定义 HTTP Header (GET/PUT /api/providers/{id}/headers)
        #   - 列出所有 provider 的元数据 + 分组 (GET /api/providers/meta)
        # 对应前端 ModelPanel 里的「测试」「获取模型列表」「多 Key 管理」「自定义 Header」按钮.
        # 实现细节在 hakusai_server.provider_ops 模块.
        from . import provider_ops as _pops  # noqa: WPS433

        @app.get("/api/providers/meta")
        async def get_providers_meta():
            """返回所有 provider 的元数据 + 分组信息 (不含 API Key).

            前端用这个渲染 Provider 列表的分组 + 搜索建议. 与 list_providers 区别:
              - list_providers 返回的是「当前配置状态」(含 masked_api_key / model_name)
              - get_providers_meta 返回的是「元数据」(display_name / group / default_url)
            前端会同时调两个, list_providers 提供运行时状态, meta 提供静态分组.
            """
            return {
                "providers": _pops.list_known_providers(),
                "groups": [g[0] for g in _pops.PROVIDER_GROUPS],
            }

        @app.post("/api/providers/{provider_id}/test")
        async def test_provider(provider_id: str, request: dict):
            """测试 provider 连接 + 认证.

            请求体 (全部可选, 留空使用 config 里的当前值):
            {
                "api_key": "sk-xxx",       // 覆盖测试用的 Key
                "base_url": "https://...", // 覆盖测试用的 Base URL
                "model": "deepseek-chat",  // 覆盖测试用的模型名
                "timeout": 15              // 超时秒数 (默认 15)
            }
            """
            result = await _pops.test_provider_connection(
                provider_id,
                override_api_key=request.get("api_key") or None,
                override_base_url=request.get("base_url") or None,
                override_model=request.get("model") or None,
                timeout=float(request.get("timeout", 15.0)),
            )
            return {
                "ok": result.ok,
                "message": result.message,
                "detail": result.detail,
                "latency_ms": result.latency_ms,
            }

        @app.post("/api/providers/{provider_id}/fetch-models")
        async def fetch_models(provider_id: str, request: dict):
            """从 provider 的 /models 端点拉取可用模型列表.

            请求体 (全部可选):
            {
                "api_key": "sk-xxx",
                "base_url": "https://...",
                "timeout": 20
            }

            返回:
            {
                "ok": true,
                "models": [{"id": "...", "name": "...", "owned_by": "..."}],
                "message": "获取到 N 个可用模型",
                "detail": null
            }
            """
            result = await _pops.fetch_provider_models(
                provider_id,
                override_api_key=request.get("api_key") or None,
                override_base_url=request.get("base_url") or None,
                timeout=float(request.get("timeout", 20.0)),
            )
            return {
                "ok": result.ok,
                "models": result.models,
                "message": result.message,
                "detail": result.detail,
            }

        @app.get("/api/providers/{provider_id}/keys")
        async def list_provider_keys(provider_id: str):
            """列出某个 provider 的所有 API Key (masked)."""
            try:
                keys = _pops.list_provider_keys(provider_id)
                return {"keys": keys}
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))

        @app.post("/api/providers/{provider_id}/keys")
        async def add_provider_key(provider_id: str, request: dict):
            """添加一个额外的 API Key (不影响主 Key).

            请求体: { "key": "sk-xxx", "label": "主号" }
            """
            try:
                entry = _pops.add_provider_key(
                    provider_id,
                    request.get("key", ""),
                    request.get("label", ""),
                )
                return entry
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

        @app.delete("/api/providers/{provider_id}/keys/{key_id}")
        async def delete_provider_key(provider_id: str, key_id: str):
            """删除一个额外的 API Key (不能删主 Key)."""
            try:
                ok = _pops.delete_provider_key(provider_id, key_id)
                if not ok:
                    raise HTTPException(status_code=404, detail=f"Key not found: {key_id}")
                return {"message": "Key deleted", "key_id": key_id}
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

        @app.get("/api/providers/{provider_id}/headers")
        async def get_provider_headers(provider_id: str):
            """获取 provider 的自定义 HTTP Headers."""
            return {"headers": _pops.get_provider_custom_headers(provider_id)}

        @app.put("/api/providers/{provider_id}/headers")
        async def set_provider_headers(provider_id: str, request: dict):
            """设置 provider 的自定义 HTTP Headers.

            请求体: { "headers": {"X-Custom-Header": "value"} }
            传空字典会清除所有自定义 Header.
            """
            try:
                _pops.set_provider_custom_headers(
                    provider_id,
                    request.get("headers", {}) or {},
                )
                return {"message": "Headers saved", "provider": provider_id}
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        # =====================================================================
        # MCP (Model Context Protocol) — Phase 2 round 2
        # =====================================================================
        # Two groups of endpoints:
        #   1. /api/config/mcp-servers* — config CRUD (read/write ~/.hakus/config.yaml)
        #   2. /api/mcp/servers/{name}/* — runtime ops (start/stop/test/tools/invoke)
        #
        # Implementation delegates to hakusai_server.mcp_ops, which wraps
        # the McpClientManager singleton in hakus/mcp/manager.py.
        # =====================================================================

        @app.get("/api/config/mcp-servers")
        async def list_mcp_servers_endpoint():
            """List all configured MCP servers with current runtime status."""
            from . import mcp_ops as _mcp
            return _mcp.list_mcp_servers()

        @app.post("/api/config/mcp-servers")
        async def save_mcp_server_endpoint(request: dict):
            """Add or replace an MCP server config. Does NOT auto-start.

            Body: {"name": "filesystem", "config": {McpServerConfig fields}}
            """
            from . import mcp_ops as _mcp
            name = request.get("name", "").strip()
            config = request.get("config", {}) or {}
            if not name:
                raise HTTPException(status_code=400, detail="'name' is required")
            try:
                return _mcp.save_mcp_server(name, config)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.patch("/api/config/mcp-servers/{name}")
        async def update_mcp_server_endpoint(name: str, request: dict):
            """Patch an existing MCP server config (e.g. toggle enabled)."""
            from . import mcp_ops as _mcp
            try:
                return _mcp.update_mcp_server(name, request)
            except KeyError:
                raise HTTPException(status_code=404, detail=f"MCP server {name!r} not found")
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.delete("/api/config/mcp-servers/{name}")
        async def delete_mcp_server_endpoint(name: str):
            """Remove an MCP server from config. Stops it first if running."""
            from . import mcp_ops as _mcp
            try:
                return _mcp.delete_mcp_server(name)
            except KeyError:
                raise HTTPException(status_code=404, detail=f"MCP server {name!r} not found")
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.patch("/api/config/mcp")
        async def update_mcp_global_endpoint(request: dict):
            """Patch the top-level mcp: section (auto_start / fail_fast / tool_naming)."""
            from . import mcp_ops as _mcp
            try:
                return _mcp.update_mcp_global_config(request)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.post("/api/mcp/servers/{name}/start")
        async def start_mcp_server_endpoint(name: str):
            """Start a server. Spawns subprocess, does MCP handshake, fetches tools."""
            from . import mcp_ops as _mcp
            try:
                return await _mcp.start_mcp_server(name)
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.post("/api/mcp/servers/{name}/stop")
        async def stop_mcp_server_endpoint(name: str):
            """Stop a running server."""
            from . import mcp_ops as _mcp
            try:
                return await _mcp.stop_mcp_server(name)
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.post("/api/mcp/servers/{name}/test")
        async def test_mcp_server_endpoint(name: str, request: dict):
            """One-shot test spawn: start → list_tools → kill.

            Body (all optional): {"override_command": "...", "override_args": [...], "timeout": 15}
            """
            from . import mcp_ops as _mcp
            try:
                # Map frontend field names to McpServerConfig override keys
                overrides = {}
                if "command" in request:
                    overrides["command"] = request["command"]
                if "args" in request:
                    overrides["args"] = request["args"]
                if "env" in request:
                    overrides["env"] = request["env"]
                if "cwd" in request:
                    overrides["cwd"] = request["cwd"]
                return await _mcp.test_mcp_server(name, overrides or None)
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.get("/api/mcp/servers/{name}/tools")
        async def list_mcp_server_tools_endpoint(name: str):
            """Return the cached tool list for a running server."""
            from . import mcp_ops as _mcp
            return _mcp.list_server_tools(name)

        @app.post("/api/mcp/servers/{name}/tools/{tool_name}/invoke")
        async def invoke_mcp_tool_endpoint(name: str, tool_name: str, request: dict):
            """Call a tool on a running MCP server (for UI testing only)."""
            from . import mcp_ops as _mcp
            arguments = request.get("arguments", {}) or {}
            try:
                return await _mcp.invoke_server_tool(name, tool_name, arguments)
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))

        @app.post("/api/character/update")
        async def update_character_full(request: dict):
            """
            更新角色信息。请求体可包含 name / nickname / personality / scenario / first_message / system_prompt。
            写入 ~/.hakus/config.yaml 并热重载。
            """
            import os, yaml as _yaml
            from pathlib import Path as _Path

            config_path = _Path(os.path.expanduser("~/.hakus/config.yaml"))
            raw: dict = {}
            if config_path.exists():
                try:
                    raw = _yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                except Exception:
                    raw = {}
            char = raw.setdefault("character", {})
            for field in ("name", "nickname", "personality", "scenario", "first_message", "system_prompt"):
                if field in request:
                    char[field] = request[field]
            try:
                config_path.write_text(
                    _yaml.dump(raw, allow_unicode=True, default_flow_style=False, sort_keys=False),
                    encoding="utf-8",
                )
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"failed to write config: {e}")
            try:
                await config_manager.reload()
            except Exception as e:
                logger.warning(f"Character saved but reload failed: {e}")
            return {"message": "Character updated"}

        # ========== 记忆系统扩展 API ==========

        @app.get("/api/memory/details")
        async def get_memory_details():
            """获取记忆系统详细状态（短期/长期条数、配置开关等）"""
            cfg = config_manager.config.memory
            data = {
                "enabled": cfg.enabled,
                "long_term_enabled": cfg.long_term_enabled,
                "short_term_max": cfg.short_term_max,
                "auto_summary": cfg.auto_summary,
                "summary_interval": cfg.summary_interval,
                "stats": {},
            }
            if self.memory:
                try:
                    data["stats"] = self.memory.stats or {}
                except Exception:
                    pass
            return data

        # ========== 工具与权限 API ==========

        @app.get("/api/tools")
        async def list_tools():
            """列出 hakus/tools/builtin/ 下所有内置工具及开关状态"""
            import os
            from pathlib import Path as _Path
            tools_dir = _Path(os.path.dirname(__file__)).parent.parent / "hakus" / "tools" / "builtin"
            tools = []
            # 静态清单（与 hakus/tools/builtin/ 下的 .py 文件对应）
            builtin = [
                {"id": "shell",    "name": "Shell 命令",      "desc": "执行 shell 命令（受权限模式控制）",   "dangerous": True},
                {"id": "file",     "name": "文件读写",        "desc": "读取/写入/编辑本地文件",            "dangerous": False},
                {"id": "directory","name": "目录浏览",        "desc": "列目录、查找文件",                  "dangerous": False},
                {"id": "web",      "name": "网页抓取",        "desc": "抓取网页内容",                      "dangerous": False},
                {"id": "search",   "name": "网络搜索",        "desc": "搜索引擎查询",                      "dangerous": False},
                {"id": "browser",  "name": "浏览器自动化",    "desc": "Playwright 浏览器操作",             "dangerous": True},
                {"id": "task",     "name": "任务管理",        "desc": "创建/查看子任务",                   "dangerous": False},
                {"id": "task_done","name": "任务完成",        "desc": "标记任务完成",                      "dangerous": False},
            ]
            # 读 ~/.hakus/config.yaml 里的 tools 段, 看哪些被禁用
            import os as _os, yaml as _yaml
            from pathlib import Path as _Path2
            config_path = _Path2(_os.path.expanduser("~/.hakus/config.yaml"))
            raw: dict = {}
            if config_path.exists():
                try:
                    raw = _yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                except Exception:
                    raw = {}
            disabled = set(raw.get("tools", {}).get("disabled", []) or [])
            for t in builtin:
                t["enabled"] = t["id"] not in disabled
                tools.append(t)
            return {"tools": tools}

        @app.post("/api/tools/toggle")
        async def toggle_tool(request: dict):
            """开关某个工具。请求体: {tool_id: "shell", enabled: false}"""
            import os, yaml as _yaml
            from pathlib import Path as _Path
            tool_id = request.get("tool_id")
            enabled = request.get("enabled")
            if not tool_id or enabled is None:
                raise HTTPException(status_code=400, detail="tool_id and enabled are required")
            config_path = _Path(os.path.expanduser("~/.hakus/config.yaml"))
            raw: dict = {}
            if config_path.exists():
                try:
                    raw = _yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                except Exception:
                    raw = {}
            tools_cfg = raw.setdefault("tools", {})
            disabled = set(tools_cfg.get("disabled", []) or [])
            if enabled:
                disabled.discard(tool_id)
            else:
                disabled.add(tool_id)
            tools_cfg["disabled"] = sorted(disabled)
            try:
                config_path.write_text(
                    _yaml.dump(raw, allow_unicode=True, default_flow_style=False, sort_keys=False),
                    encoding="utf-8",
                )
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"failed to write config: {e}")
            return {"tool_id": tool_id, "enabled": enabled}

        @app.get("/api/permission")
        async def get_permission():
            """获取当前权限模式"""
            import os, yaml as _yaml
            from pathlib import Path as _Path
            config_path = _Path(os.path.expanduser("~/.hakus/config.yaml"))
            raw: dict = {}
            if config_path.exists():
                try:
                    raw = _yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                except Exception:
                    raw = {}
            mode = raw.get("permission", {}).get("mode", "ask")
            return {"mode": mode, "available_modes": ["auto", "ask", "bypass"]}

        @app.post("/api/permission")
        async def set_permission(request: dict):
            """设置权限模式。请求体: {mode: "auto"|"ask"|"bypass"}"""
            import os, yaml as _yaml
            from pathlib import Path as _Path
            mode = request.get("mode")
            if mode not in ("auto", "ask", "bypass"):
                raise HTTPException(status_code=400, detail="mode must be auto/ask/bypass")
            config_path = _Path(os.path.expanduser("~/.hakus/config.yaml"))
            raw: dict = {}
            if config_path.exists():
                try:
                    raw = _yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                except Exception:
                    raw = {}
            perm_cfg = raw.setdefault("permission", {})
            perm_cfg["mode"] = mode
            try:
                config_path.write_text(
                    _yaml.dump(raw, allow_unicode=True, default_flow_style=False, sort_keys=False),
                    encoding="utf-8",
                )
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"failed to write config: {e}")
            return {"mode": mode}

        # ========== 配置导出/导入 ==========

        @app.get("/api/config/export")
        async def export_config():
            """导出完整配置（脱敏：api_key 用 mask 显示）"""
            import os, yaml as _yaml, copy as _copy
            from pathlib import Path as _Path
            config_path = _Path(os.path.expanduser("~/.hakus/config.yaml"))
            if not config_path.exists():
                return {"config": {}}
            try:
                raw = _yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"failed to read config: {e}")
            # 脱敏
            safe = _copy.deepcopy(raw)
            api_keys = safe.get("api_keys", {}) or {}
            for k, v in list(api_keys.items()):
                if v and isinstance(v, str):
                    api_keys[k] = (v[:4] + "..." + v[-4:]) if len(v) > 8 else "*" * len(v)
            return {"config": safe}

        @app.post("/api/config/import")
        async def import_config(request: dict):
            """导入配置（覆盖 ~/.hakus/config.yaml）。请求体: {config: {...}}"""
            import os, yaml as _yaml
            from pathlib import Path as _Path
            new_config = request.get("config")
            if not isinstance(new_config, dict):
                raise HTTPException(status_code=400, detail="config must be an object")
            config_path = _Path(os.path.expanduser("~/.hakus/config.yaml"))
            config_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                config_path.write_text(
                    _yaml.dump(new_config, allow_unicode=True, default_flow_style=False, sort_keys=False),
                    encoding="utf-8",
                )
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"failed to write config: {e}")
            try:
                await config_manager.reload()
            except Exception as e:
                logger.warning(f"Config imported but reload failed: {e}")
            return {"message": "Config imported"}

        # ========== 角色API ==========
        
        @app.get("/api/character")
        async def get_character():
            """获取角色信息 — 直接从 ~/.hakus/config.yaml 读取，确保返回用户实际配置而非默认值"""
            import os, yaml as _yaml
            from pathlib import Path as _Path
            config_path = _Path(os.path.expanduser("~/.hakus/config.yaml"))
            raw: dict = {}
            if config_path.exists():
                try:
                    raw = _yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                except Exception:
                    raw = {}
            char = raw.get("character", {}) or {}
            # 同时获取 avatar_type（兼容旧逻辑）
            avatar_type = "live2d"
            try:
                av = config_manager.config.avatar.type
                avatar_type = av.value if hasattr(av, "value") else str(av)
            except Exception:
                pass
            return {
                "name": char.get("name", "小雪"),
                "nickname": char.get("nickname"),
                "personality": char.get("personality", "你是一个温柔善良的AI助手"),
                "scenario": char.get("scenario"),
                "first_message": char.get("first_message"),
                "avatar_type": avatar_type,
            }
        
        # ========== 记忆API ==========
        
        @app.get("/api/memory/stats")
        async def get_memory_stats():
            """获取记忆统计"""
            if not self.memory:
                return {"error": "Memory not initialized"}
            
            return self.memory.stats
        
        @app.post("/api/memory/clear")
        async def clear_memory(request: dict = None):
            """清空记忆。

            请求体 (可选):
            {
                "session_id": "default"  // 不传则清所有 session 的 AgentCore cache
            }
            """
            session_id = (request or {}).get("session_id")
            if self.memory:
                await self.memory.clear()
                # 同时清空 BaseAgent 历史（旧路径）
                if self.agent:
                    try:
                        self.agent.clear_history()
                    except Exception as e:
                        logger.warning(f"BaseAgent clear_history failed: {e}")

            # 清空 AgentCore session cache（新路径）
            if USE_AGENTCORE_FOR_CHAT:
                if session_id:
                    agentcore_clear_session(session_id)
                else:
                    # 没指定 session — 清所有缓存的 agent
                    from .agent_bridge import _agent_cache, _agent_cache_lock
                    with _agent_cache_lock:
                        _agent_cache.clear()

            return {"message": "Memory cleared"}
        
        # ========== TTS API ==========
        
        @app.post("/api/tts")
        async def text_to_speech(request: dict):
            """
            文本转语音
            
            请求体:
            {
                "text": "要合成的文本",
                "voice": "xiaoxiao",  // 可选
                "speed": 1.0          // 可选
            }
            
            返回音频文件 (MP3)
            """
            if not self.tts_engine:
                raise HTTPException(status_code=503, detail="TTS not initialized")
            
            text = request.get("text", "")
            voice = request.get("voice")
            speed = request.get("speed", 1.0)
            
            if not text:
                raise HTTPException(status_code=400, detail="Text is required")
            
            try:
                from fastapi.responses import Response
                
                # 合成语音
                result = await self.tts_engine.synthesize(text, voice=voice, speed=speed)
                
                if result is None:
                    raise HTTPException(status_code=500, detail="TTS synthesis returned no audio")
                
                return Response(
                    content=result.audio_data,
                    media_type="audio/mpeg",
                    headers={
                        "Content-Disposition": f"attachment; filename=tts.mp3",
                        "X-Sample-Rate": str(result.sample_rate),
                    }
                )
            except Exception as e:
                logger.error(f"TTS error: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        
        @app.get("/api/tts/voices")
        async def list_tts_voices():
            """列出可用的TTS语音"""
            from hakusai_core.voice.tts.edge import EdgeTTS
            return {
                "voices": EdgeTTS.list_voices()
            }
        
        # ========== WebSocket路由 ==========
        
        @app.websocket("/ws/chat")
        async def websocket_chat(websocket: WebSocket):
            """WebSocket聊天接口。

            AgentCore 路径下，stream 事件携带 event_type 字段
            (text_delta / tool_call_started / ... / turn_completed)，
            旧客户端只看 content + done 即可。
            """
            await self.websocket_manager.connect(websocket)
            try:
                while True:
                    data = await websocket.receive_json()

                    message_type = data.get("type", "message")

                    if message_type == "message":
                        content = data.get("content", "")
                        session_id = data.get("session_id", "default")
                        # WebSocket clients can also pass a per-message
                        # provider override (same semantics as the REST
                        # ChatRequest.provider field).
                        ws_provider = data.get("provider")

                        await event_bus.emit(
                            EventType.CHAT_MESSAGE_RECEIVED,
                            {"content": content, "websocket_id": id(websocket)}
                        )

                        # Phase 1: 等 AI 初始化完成（最多 10s），仍没好就发 init_pending
                        if not await self._ensure_ready(timeout=10.0):
                            await websocket.send_json({
                                "type": "error",
                                "message": "AI still initializing, please retry in a few seconds",
                                "code": "init_pending",
                                "retry_after_s": 2,
                            })
                            continue

                        # AgentCore 路径
                        if USE_AGENTCORE_FOR_CHAT:
                            if not self.model_adapter:
                                await websocket.send_json({
                                    "type": "error",
                                    "message": f"Model not initialized: {self._init_error or 'unknown reason'}",
                                    "code": "init_failed",
                                    "diagnostics_url": "/api/diagnostics",
                                })
                                continue
                            try:
                                async for chunk in agentcore_run_turn_stream(content, session_id, provider=ws_provider):
                                    await websocket.send_json({
                                        "type": "stream",
                                        **chunk,
                                    })
                            except Exception as e:
                                logger.error(f"WS AgentCore stream error: {e}", exc_info=True)
                                await websocket.send_json({
                                    "type": "error",
                                    "message": str(e),
                                    "code": "stream_error",
                                })
                            continue

                        # 旧路径
                        if not self.agent:
                            await websocket.send_json({
                                "type": "error",
                                "message": f"Agent not initialized: {self._init_error or 'unknown reason'}",
                                "code": "init_failed",
                                "diagnostics_url": "/api/diagnostics",
                            })
                            continue

                        context = AgentContext(session_id=session_id)

                        async for response in self.agent.chat(content, context, stream=True):
                            await websocket.send_json({
                                "type": "stream",
                                "content": response.content,
                                "emotion": response.emotion,
                                "done": False
                            })

                        await websocket.send_json({
                            "type": "stream",
                            "content": "",
                            "done": True
                        })

                    elif message_type == "ping":
                        await websocket.send_json({"type": "pong"})

            except WebSocketDisconnect:
                self.websocket_manager.disconnect(websocket)
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                self.websocket_manager.disconnect(websocket)
        
        @app.websocket("/ws/vtuber")
        async def websocket_vtuber(websocket: WebSocket):
            """
            虚拟主播 WebSocket 接口
            
            全双工通信，支持:
            - 文本消息 -> LLM -> 流式TTS -> 音频流
            - 实时口型同步数据
            - 语音打断
            """
            await vtuber_handler.handle_connection(websocket, session_id="vtuber_main")
        
        @app.websocket("/ws/vtuber/{session_id}")
        async def websocket_vtuber_session(websocket: WebSocket, session_id: str):
            """虚拟主播 WebSocket 接口（支持多会话）"""
            await vtuber_handler.handle_connection(websocket, session_id=session_id)

        # ========== 自定义 404 / 500 JSON 处理器 ==========
        # FastAPI 默认 404 返回 HTML ("{\"detail\":\"Not Found\"}")，前端 fetch
        # 解析 JSON 会失败。这里改成统一返回 JSON，并加上 sidecar_api_version
        # 字段，方便前端检测 "sidecar 版本过旧"（旧 sidecar 没有某个端点 → 404）。

        @app.exception_handler(404)
        async def not_found_handler(request, exc):
            path = request.url.path
            # SPA 路径（无 /api/ 前缀）依然返回 index.html，让前端路由处理
            # 但因为我们在 mount 静态文件时已经注册了 catch-all，这里基本不会触发。
            # /api/ 路径返回 JSON 404，附带 sidecar 版本提示。
            return JSONResponse(
                status_code=404,
                content={
                    "detail": "Not Found",
                    "path": path,
                    "sidecar_api_version": SIDECAR_API_VERSION,
                    "sidecar_api_version_int": SIDECAR_API_VERSION_INT,
                    "hint": (
                        "This endpoint does not exist on the running sidecar. "
                        "If you upgraded the desktop client but see this, the bundled "
                        "sidecar.exe may be outdated. Reinstall the latest client "
                        "to get a matching sidecar."
                    ),
                },
            )

        @app.exception_handler(500)
        async def server_error_handler(request, exc):
            logger.exception(f"500 error on {request.url.path}: {exc}")
            return JSONResponse(
                status_code=500,
                content={
                    "detail": str(exc) if exc else "Internal Server Error",
                    "path": request.url.path,
                    "sidecar_api_version": SIDECAR_API_VERSION,
                },
            )
    
    async def start(self):
        """启动服务器"""
        if self.app is None:
            self.create_app()
        
        config = uvicorn.Config(
            self.app,
            host=self.config.server.host,
            port=self.config.server.port,
            log_level="info"
        )
        server = uvicorn.Server(config)
        await server.serve()
    
    def run(self):
        """运行服务器（阻塞）"""
        if self.app is None:
            self.create_app()
        
        # 尝试使用配置的端口，如果被占用则尝试其他端口
        port = self.config.server.port
        import socket
        for _ in range(10):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.bind((self.config.server.host, port))
                    break
            except OSError:
                logger.warning(f"Port {port} is in use, trying {port + 1}")
                port += 1
        
        logger.info(f"Starting server on port {port}")
        uvicorn.run(
            self.app,
            host=self.config.server.host,
            port=port,
            log_level="info"
        )


class WebSocketManager:
    """
    WebSocket连接管理器
    """
    
    def __init__(self):
        self.active_connections: list = []
    
    async def connect(self, websocket: WebSocket):
        """接受新连接"""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        """断开连接"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total: {len(self.active_connections)}")
    
    async def broadcast(self, message: dict):
        """广播消息到所有连接"""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)
        
        # 清理断开的连接
        for conn in disconnected:
            self.disconnect(conn)


# 全局服务器实例
server = HakusAIServer()


if __name__ == "__main__":
    server.run()
