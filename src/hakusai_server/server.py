"""
HakusAI 2.0 FastAPI服务器
提供REST API和WebSocket接口
"""

import asyncio
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

logger = logging.getLogger(__name__)


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
        
        @app.get("/")
        async def root():
            """根路径"""
            return {
                "name": "HakusAI",
                "version": "2.0.0",
                "status": "running"
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
            """
            # Phase 1: 如果还在初始化中，先等一下（最多 10s）
            if not await self._ensure_ready(timeout=10.0):
                raise HTTPException(
                    status_code=503,
                    detail="AI still initializing, please retry in a few seconds"
                )
            # 初始化已结束但 agent 仍为 None → 一定是关键组件失败
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
            
            返回SSE流
            """
            # Phase 1: 等初始化完成，否则发 503
            if not await self._ensure_ready(timeout=10.0):
                raise HTTPException(
                    status_code=503,
                    detail="AI still initializing, please retry in a few seconds"
                )
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
        
        # ========== 角色API ==========
        
        @app.get("/api/character")
        async def get_character():
            """获取角色信息"""
            char = config_manager.config.character
            return {
                "name": char.name,
                "nickname": char.nickname,
                "personality": char.personality,
                "scenario": char.scenario,
                "first_message": char.first_message,
                "avatar_type": config_manager.config.avatar.type,
            }
        
        @app.post("/api/character/update")
        async def update_character(request: dict):
            """更新角色信息"""
            # TODO: 实现配置更新
            return {"message": "Character updated"}
        
        # ========== 记忆API ==========
        
        @app.get("/api/memory/stats")
        async def get_memory_stats():
            """获取记忆统计"""
            if not self.memory:
                return {"error": "Memory not initialized"}
            
            return self.memory.stats
        
        @app.post("/api/memory/clear")
        async def clear_memory():
            """清空记忆"""
            if self.memory:
                await self.memory.clear()
                # 同时清空Agent历史
                if self.agent:
                    self.agent.clear_history()
            
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
            """WebSocket聊天接口"""
            await self.websocket_manager.connect(websocket)
            try:
                while True:
                    data = await websocket.receive_json()
                    
                    message_type = data.get("type", "message")
                    
                    if message_type == "message":
                        content = data.get("content", "")
                        session_id = data.get("session_id", "default")
                        
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
