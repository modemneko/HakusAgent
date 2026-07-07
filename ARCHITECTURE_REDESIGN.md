# HakusAI 2.0 架构重构设计

## 一、重构目标

借鉴 OpenCode 的架构设计理念，对 HakusAI 进行架构级重构：

1. **增强代码开发能力** - 提升代码编辑、调试、重构能力
2. **统一工具系统** - 合并双工具系统，消除历史包袱
3. **提升可维护性** - 拆分臃肿的 agent.py，建立清晰的模块边界
4. **借鉴 OpenCode 架构** - 引入严格分层、类型安全、依赖注入等设计

同时**完全保留** HakusAI 的特色功能：
- 语音交互系统（TTS/ASR/VAD）
- 虚拟形象（Live2D/VRM）
- 直播集成（B站/Discord）
- 记忆系统（ChromaDB）
- 多智能体编排

---

## 二、架构设计

### 2.1 Monorepo 结构（Python 风格）

采用 **Hatch Workspaces** 或 **Poetry Workspaces** 实现 Python Monorepo：

```
hakusai/
├── packages/                      # 核心包（严格分层）
│   ├── schema/                    # Schema 层 - 数据类型定义
│   │   ├── models/                # Pydantic 模型
│   │   ├── events/                # 事件定义
│   │   └── errors/                # 错误类型
│   │
│   ├── core/                      # Core 层 - 核心业务逻辑
│   │   ├── agent/                 # Agent 系统
│   │   │   ├── base.py            # BaseAgent 基类
│   │   │   ├── orchestrator.py    # 多智能体编排器
│   │   │   ├── sub_agents.py      # 子智能体
│   │   │   └── permissions.py     # 权限管理
│   │   │
│   │   ├── tools/                 # 工具系统
│   │   │   ├── registry.py        # 工具注册表
│   │   │   ├── executor.py        # 工具执行器
│   │   │   ├── builtin/           # 内置工具
│   │   │   │   ├── file.py        # 文件操作
│   │   │   │   ├── shell.py       # Shell 执行
│   │   │   │   ├── search.py      # 搜索工具
│   │   │   │   ├── git.py         # Git 操作
│   │   │   │   └── web.py         # Web 工具
│   │   │   └── mcp/               # MCP 集成
│   │   │
│   │   ├── session/               # 会话管理
│   │   │   ├── store.py           # SQLite 持久化
│   │   │   ├── context.py         # 上下文管理
│   │   │   └── memory.py          # 记忆系统
│   │   │
│   │   ├── models/                # LLM 客户端
│   │   │   ├── client.py          # 统一客户端
│   │   │   ├── providers/         # 提供商适配器
│   │   │   └── streaming.py       # 流式处理
│   │   │
│   │   └── project/               # 项目管理
│   │       ├── workspace.py       # 工作空间
│   │       ├── task_board.py      # 任务看板
│   │       └── checkpoint.py      # 检查点
│   │
│   ├── voice/                     # 语音系统（特色功能）
│   │   ├── asr/                   # 语音识别
│   │   ├── tts/                   # 语音合成
│   │   ├── vad/                   # 语音检测
│   │   └── pipeline.py            # 语音管线
│   │
│   ├── avatar/                    # 虚拟形象（特色功能）
│   │   ├── live2d/                # Live2D 支持
│   │   ├── vrm/                   # VRM 支持
│   │   └── sync.py                # 口型同步
│   │
│   ├── platform/                  # 平台集成（特色功能）
│   │   ├── bilibili/              # B站直播
│   │   ├── discord/               # Discord
│   │   └── youtube/               # YouTube
│   │
│   └── server/                    # Server 层 - HTTP 服务
│       ├── app.py                 # FastAPI 应用
│       ├── routes/                # API 路由
│       └── middleware/            # 中间件
│
├── apps/                          # 应用层
│   ├── tui/                       # 终端界面
│   ├── web/                       # Web 前端
│   ├── desktop/                   # 桌面应用
│   └── cli/                       # CLI 工具
│
├── plugins/                       # 插件系统
│   ├── plugin.py                  # 插件基类
│   └── builtin/                   # 内置插件
│
├── pyproject.toml                 # 根配置
├── hatch.toml                     # Hatch 配置
├── Makefile                       # 构建脚本
└── README.md                      # 项目文档
```

### 2.2 依赖方向（严格单向）

```
Schema → Core → Voice/Avatar/Platform → Server → Apps
   ↓
Plugins（可选，松散耦合）
```

**关键原则**：
- 禁止循环依赖
- 上层可依赖下层，下层不可依赖上层
- 跨模块通信通过事件总线

### 2.3 类型安全设计（Pydantic v2）

借鉴 OpenCode 的 Effect Schema，使用 Pydantic v2 实现全链路类型安全：

```python
# schema/models/agent.py
from pydantic import BaseModel, Field
from enum import Enum

class AgentMode(str, Enum):
    BUILD = "build"
    PLAN = "plan"

class AgentConfig(BaseModel):
    name: str
    mode: AgentMode
    permissions: dict[str, PermissionRule]
    max_iterations: int = 15

class AgentState(BaseModel):
    session_id: str
    mode: AgentMode
    step_count: int = 0
    context: list[Message] = Field(default_factory=list)

# 运行时验证
def validate_agent_config(data: dict) -> AgentConfig:
    return AgentConfig.model_validate(data)
```

### 2.4 依赖注入（DI Container）

使用 `dependency-injector` 或自定义 DI 容器：

```python
# core/container.py
from dependency_injector import containers, providers

class Container(containers.DeclarativeContainer):
    # 配置
    config = providers.Configuration()
    
    # 基础设施
    database = providers.Singleton(Database, config.database)
    event_bus = providers.Singleton(EventBus)
    
    # 核心服务
    session_store = providers.Singleton(SessionStore, database)
    tool_registry = providers.Singleton(ToolRegistry)
    permission_manager = providers.Singleton(PermissionManager)
    
    # Agent 系统
    agent_factory = providers.Factory(AgentFactory, tool_registry, permission_manager)
    orchestrator = providers.Singleton(Orchestrator, agent_factory)
    
    # 语音系统
    asr_engine = providers.Singleton(ASREngine, config.asr)
    tts_engine = providers.Singleton(TTSEngine, config.tts)
    voice_pipeline = providers.Singleton(VoicePipeline, asr_engine, tts_engine)
    
    # 服务器
    server = providers.Singleton(Server, orchestrator, voice_pipeline)
```

---

## 三、核心模块设计

### 3.1 Agent 系统重构

**拆分 agent.py（1200行）→ 多个专注模块**：

```
core/agent/
├── base.py              # BaseAgent 基类（~200行）
├── build_agent.py       # Build Agent（~300行）
├── plan_agent.py        # Plan Agent（~200行）
├── orchestrator.py      # 多智能体编排器（~400行）
├── sub_agents.py        # 子智能体（~200行）
├── permissions.py       # 权限管理（~150行）
├── context.py           # 上下文管理（~200行）
└── events.py            # Agent 事件（~100行）
```

**设计模式**：

```python
# core/agent/base.py
from abc import ABC, abstractmethod
from ..schema.models import AgentConfig, AgentState, ToolResult

class BaseAgent(ABC):
    """Agent 基类 - 借鉴 OpenCode 的 Agent 设计"""
    
    def __init__(self, config: AgentConfig):
        self.config = config
        self.state = AgentState(session_id="", mode=config.mode)
        self.tools: ToolRegistry = None
        self.permissions: PermissionManager = None
    
    @abstractmethod
    async def execute(self, task: str) -> str:
        """执行任务 - 子类实现"""
        pass
    
    async def call_llm(self, messages: list[Message]) -> AsyncIterator[str]:
        """调用 LLM - 统一流式输出"""
        pass
    
    async def execute_tool(self, tool_name: str, args: dict) -> ToolResult:
        """执行工具 - 权限检查"""
        if not self.permissions.check(tool_name, args):
            return ToolResult(success=False, error="Permission denied")
        return await self.tools.execute(tool_name, args)

# core/agent/build_agent.py
class BuildAgent(BaseAgent):
    """Build Agent - 全能开发 Agent（借鉴 OpenCode 的 build）"""
    
    def __init__(self, config: AgentConfig):
        super().__init__(config)
        self.config.permissions = {
            "read": "allow",
            "write": "ask",
            "edit": "ask",
            "shell": "ask",
            "git": "ask",
        }
    
    async def execute(self, task: str) -> str:
        # 1. 规划任务
        plan = await self.plan(task)
        
        # 2. 执行计划
        for step in plan.steps:
            result = await self.execute_step(step)
            if not result.success:
                # 尝试修复
                result = await self.fix_error(step, result.error)
        
        return "任务完成"
```

### 3.2 工具系统统一

**合并双工具系统，统一到 `core/tools/`**：

```python
# core/tools/registry.py
from typing import Callable, Any
from ..schema.models import ToolDefinition, ToolResult

class ToolRegistry:
    """统一工具注册表 - 借鉴 OpenCode 的 Tool Registry"""
    
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._aliases: dict[str, str] = {}
    
    def register(self, name: str, tool: ToolDefinition, aliases: list[str] = None):
        """注册工具"""
        self._tools[name] = tool
        if aliases:
            for alias in aliases:
                self._aliases[alias] = name
    
    def get(self, name: str) -> ToolDefinition:
        """获取工具（支持别名）"""
        actual_name = self._aliases.get(name, name)
        return self._tools.get(actual_name)
    
    def list_tools(self) -> list[ToolDefinition]:
        """列出所有工具"""
        return list(self._tools.values())

# core/tools/builtin/file.py
from ...schema.models import ToolDefinition
from ..registry import ToolRegistry

class ReadTool:
    """读取文件工具 - 借鉴 OpenCode 的 Read"""
    
    definition = ToolDefinition(
        name="read",
        description="Read a file from the filesystem",
        parameters={
            "filePath": {"type": "string", "description": "Absolute path to file"},
            "offset": {"type": "integer", "description": "Line number to start from"},
            "limit": {"type": "integer", "description": "Maximum lines to read"},
        },
    )
    
    async def execute(self, args: dict) -> dict:
        # 实现文件读取
        pass

# 注册工具
def register_file_tools(registry: ToolRegistry):
    registry.register("read", ReadTool.definition, aliases=["read_file"])
    registry.register("write", WriteTool.definition, aliases=["write_file"])
    registry.register("edit", EditTool.definition, aliases=["edit_file"])
```

### 3.3 会话管理（SQLite 持久化）

借鉴 OpenCode 的 SQLite 持久化设计：

```python
# core/session/store.py
import sqlite3
from datetime import datetime
from ..schema.models import Session, Message

class SessionStore:
    """会话存储 - 借鉴 OpenCode 的 SQLite 持久化"""
    
    def __init__(self, db_path: str = "hakusai.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                updated_at TIMESTAMP NOT NULL,
                config TEXT,
                state TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)
        conn.commit()
        conn.close()
    
    def create_session(self, project_id: str, config: dict) -> Session:
        """创建会话"""
        session = Session(
            id=str(uuid.uuid4()),
            project_id=project_id,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            config=config,
        )
        # 持久化到 SQLite
        return session
    
    def get_session(self, session_id: str) -> Session:
        """获取会话"""
        # 从 SQLite 恢复
        pass
    
    def save_message(self, session_id: str, message: Message):
        """保存消息"""
        # 持久化消息
        pass
```

### 3.4 LLM 客户端（统一接口）

借鉴 OpenCode 的 4 轴路由架构，但简化为 Python 风格：

```python
# core/models/client.py
from abc import ABC, abstractmethod
from ..schema.models import Message, ModelConfig

class LLMClient(ABC):
    """LLM 客户端基类"""
    
    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        config: ModelConfig,
    ) -> AsyncIterator[str]:
        """流式对话"""
        pass

class OpenAIClient(LLMClient):
    """OpenAI 客户端"""
    
    async def chat(self, messages: list[Message], config: ModelConfig) -> AsyncIterator[str]:
        # 实现 OpenAI API 调用
        pass

class AnthropicClient(LLMClient):
    """Anthropic 客户端"""
    
    async def chat(self, messages: list[Message], config: ModelConfig) -> AsyncIterator[str]:
        # 实现 Anthropic API 调用
        pass

# core/models/factory.py
class ClientFactory:
    """客户端工厂 - 统一创建 LLM 客户端"""
    
    _clients = {
        "openai": OpenAIClient,
        "anthropic": AnthropicClient,
        "deepseek": DeepSeekClient,
        "qwen": QwenClient,
        # ... 更多提供商
    }
    
    @classmethod
    def create(cls, provider: str, config: dict) -> LLMClient:
        client_class = cls._clients.get(provider)
        if not client_class:
            raise ValueError(f"Unsupported provider: {provider}")
        return client_class(config)
```

---

## 四、保留特色功能

### 4.1 语音系统（core/voice/）

保持现有语音系统，但重构接口：

```python
# core/voice/pipeline.py
from ..schema.models import AudioData, Text

class VoicePipeline:
    """语音管线 - 统一语音处理"""
    
    def __init__(self, asr: ASREngine, tts: TTSEngine, vad: VADEngine):
        self.asr = asr
        self.tts = tts
        self.vad = vad
    
    async def process_audio(self, audio: AudioData) -> Text:
        """音频转文本"""
        # VAD 检测
        segments = await self.vad.detect(audio)
        # ASR 识别
        text = await self.asr.transcribe(segments)
        return text
    
    async def generate_audio(self, text: Text) -> AudioData:
        """文本转音频"""
        return await self.tts.synthesize(text)
```

### 4.2 虚拟形象（core/avatar/）

保持现有虚拟形象系统，但统一接口：

```python
# core/avatar/manager.py
from ..schema.models import AvatarState, Expression, Motion

class AvatarManager:
    """虚拟形象管理器"""
    
    def __init__(self, live2d: Live2DRenderer, vrm: VRMRenderer):
        self.renderers = {"live2d": live2d, "vrm": vrm}
        self.current_renderer = None
    
    async def update(self, state: AvatarState):
        """更新虚拟形象状态"""
        if self.current_renderer:
            await self.current_renderer.render(state)
```

### 4.3 平台集成（core/platform/）

保持现有平台集成，但统一接口：

```python
# core/platform/base.py
from abc import ABC, abstractmethod
from ..schema.models import PlatformEvent

class PlatformAdapter(ABC):
    """平台适配器基类"""
    
    @abstractmethod
    async def connect(self):
        """连接平台"""
        pass
    
    @abstractmethod
    async def send_message(self, message: str):
        """发送消息"""
        pass
    
    @abstractmethod
    async def receive_events(self) -> AsyncIterator[PlatformEvent]:
        """接收事件"""
        pass

# core/platform/bilibili.py
class BilibiliAdapter(PlatformAdapter):
    """B站直播适配器"""
    
    async def connect(self):
        # 连接 B站直播间
        pass
    
    async def receive_events(self) -> AsyncIterator[PlatformEvent]:
        # 接收弹幕、礼物等事件
        pass
```

---

## 五、重构计划

### Phase 1：基础设施搭建（1-2 周）

1. **创建 Monorepo 结构**
   - 配置 Hatch Workspaces
   - 创建包目录结构
   - 设置 CI/CD

2. **Schema 层实现**
   - 定义核心数据模型
   - 建立错误类型体系
   - 实现事件定义

3. **DI 容器搭建**
   - 配置依赖注入
   - 建立服务注册机制

### Phase 2：核心模块重构（2-3 周）

4. **工具系统统一**
   - 合并双工具系统
   - 实现统一 ToolRegistry
   - 迁移内置工具

5. **Agent 系统重构**
   - 拆分 agent.py
   - 实现 BaseAgent 基类
   - 迁移 Build/Plan Agent

6. **会话管理**
   - 实现 SQLite 持久化
   - 迁移会话数据

### Phase 3：特色功能迁移（2-3 周）

7. **语音系统迁移**
   - 重构语音管线接口
   - 迁移 ASR/TTS/VAD

8. **虚拟形象迁移**
   - 重构形象管理器
   - 迁移 Live2D/VRM

9. **平台集成迁移**
   - 重构平台适配器
   - 迁移 B站/Discord

### Phase 4：应用层重构（1-2 周）

10. **Server 层重构**
    - 迁移 FastAPI 路由
    - 集成新核心

11. **前端重构**
    - 迁移 React 前端
    - 适配新 API

12. **CLI/TUI 重构**
    - 迁移命令行工具
    - 适配新架构

### Phase 5：测试与优化（1-2 周）

13. **单元测试**
    - 为核心模块编写测试
    - 建立测试覆盖率

14. **集成测试**
    - 端到端测试
    - 性能测试

15. **文档完善**
    - API 文档
    - 架构文档

---

## 六、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 重构周期过长 | 高 | 分阶段实施，每阶段交付可用版本 |
| 破坏现有功能 | 高 | 建立完整测试套件，重构前先写测试 |
| 性能下降 | 中 | 基准测试，持续监控性能指标 |
| 团队学习成本 | 中 | 渐进式引入，提供培训和文档 |

---

## 七、成功指标

1. **架构质量**
   - 模块耦合度 < 0.3
   - 循环依赖 = 0
   - 测试覆盖率 > 80%

2. **开发效率**
   - 新工具开发时间 < 2 小时
   - 新 Agent 开发时间 < 1 天
   - Bug 修复时间 < 4 小时

3. **功能完整性**
   - 所有现有功能可用
   - 代码开发能力提升 50%
   - 语音交互延迟 < 500ms

---

## 八、总结

本次重构借鉴 OpenCode 的架构设计理念，对 HakusAI 进行架构级升级：

1. **严格分层** - 建立清晰的模块边界
2. **类型安全** - 使用 Pydantic v2 实现全链路类型安全
3. **依赖注入** - 建立松耦合的服务架构
4. **统一工具** - 合并双工具系统，消除历史包袱
5. **保留特色** - 完全保留语音、形象、直播等特色功能

重构完成后，HakusAI 将具备：
- 更强的代码开发能力
- 更好的可维护性
- 更清晰的架构设计
- 更容易扩展的新功能

预计总工期：8-12 周