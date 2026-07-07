"""
HakusAI 2.0 FastAPI服务器
提供REST API和WebSocket接口
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any
from pydantic import BaseModel

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
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
        
    async def _init_ai_components(self):
        """初始化AI组件"""
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
            
            if api_key:
                model_config["api_key"] = api_key
            
            # 创建模型适配器
            self.model_adapter = model_registry.create_adapter(provider, model_config)
            await self.model_adapter.initialize()
            logger.info(f"Model adapter initialized: {provider}")
            
            # 创建Agent
            self.agent = BaseAgent(self.model_adapter)
            logger.info("BaseAgent initialized")
            
            # 初始化记忆系统
            memory_config = MemoryStorage(
                max_short_term=self.config.memory.short_term_max,
                enable_long_term=self.config.memory.long_term_enabled,
                auto_summary=self.config.memory.auto_summary,
                summary_interval=self.config.memory.summary_interval,
            )
            self.memory = MemoryManager(memory_config)
            await self.memory.initialize()
            logger.info("Memory system initialized")
            
            # 初始化TTS引擎
            if self.config.voice.enabled and str(self.config.voice.tts.provider) == "edge":
                try:
                    tts_config = self.config.voice.tts.model_dump()
                    self.tts_engine = tts_registry.create_engine("edge", tts_config)
                    await self.tts_engine.initialize()
                    logger.info("TTS engine initialized")
                except Exception as e:
                    logger.warning(f"Failed to initialize TTS: {e}")
            
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
            logger.info("VTuber WebSocket handler initialized")
            
            # 设置Agent记忆钩子
            if self.memory:
                self.agent.add_hook("before_chat", self._before_chat_hook)
                self.agent.add_hook("after_chat", self._after_chat_hook)
                
        except Exception as e:
            logger.error(f"Failed to initialize AI components: {e}")
            raise
    
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
            """应用生命周期管理"""
            # 启动时
            logger.info("Starting HakusAI Server...")
            await event_bus.start()
            await self._init_ai_components()
            yield
            # 关闭时
            logger.info("Shutting down HakusAI Server...")
            if self.memory:
                await self.memory.close()
            if self.model_adapter:
                await self.model_adapter.close()
            await event_bus.stop()
        
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
            """健康检查"""
            return {
                "status": "healthy",
                "version": "2.0.0",
                "model_loaded": self.model_adapter is not None,
                "agent_ready": self.agent is not None,
            }
        
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
            if not self.agent:
                return {"error": "Agent not initialized"}, 503
            
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
                return {"error": str(e)}, 500
        
        @app.post("/api/chat/stream")
        async def chat_stream(request: ChatRequest):
            """
            聊天接口（流式）
            
            返回SSE流
            """
            if not self.agent:
                return {"error": "Agent not initialized"}, 503
            
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
            if not self.agent:
                return {"error": "Agent not initialized", "success": False}
            
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
                return {"error": "TTS not initialized"}, 503
            
            text = request.get("text", "")
            voice = request.get("voice")
            speed = request.get("speed", 1.0)
            
            if not text:
                return {"error": "Text is required"}, 400
            
            try:
                from fastapi.responses import Response
                
                # 合成语音
                result = await self.tts_engine.synthesize(text, voice=voice, speed=speed)
                
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
                return {"error": str(e)}, 500
        
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
                        
                        if self.agent:
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
                        else:
                            await websocket.send_json({
                                "type": "error",
                                "message": "Agent not ready"
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
