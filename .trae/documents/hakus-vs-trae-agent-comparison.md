# HakusAI vs Trae-Agent 深度对比分析与改进计划

## 一、资源概述

### 1.1 Trae-Agent（字节跳动）
- **GitHub**: [bytedance/trae-agent](https://github.com/bytedance/trae-agent) — MIT 协议，289 commits
- **定位**: 面向软件工程任务的 LLM Agent，**研究友好型设计**
- **技术报告**: arXiv:2507.23370 ("Trae Agent: Test-time Scaling")
- **核心特色**: Lakeview 步骤摘要、多 LLM Provider、轨迹录制、Docker 沙箱、MCP 支持、SWE-bench 评估

### 1.2 51cto 文章 (aigc/7748)
- 该文章被腾讯云 EdgeOne 验证码保护，无法直接抓取内容
- 从搜索结果推断：属于 AI Agent 主流框架深度对比系列，涵盖 LangChain/CrewAI/AutoGen/MetaGPT 等框架的架构分析

### 1.3 HakusAI_chat（我们的项目）
- 基于 Textual 的 TUI v2 终端 AI Agent
- 核心: AgentCore + 20+ 工具 + 流式输出 + Token 校准 + Harness 测试

---

## 二、架构对比

### 2.1 整体架构

| 维度 | Trae-Agent | HakusAI_chat |
|------|-----------|-------------|
| **继承体系** | `BaseAgent(ABC)` → `TraeAgent` | `AgentCore` 单体类 |
| **主循环** | `execute_task()` → `_run_llm_step()` → `_tool_call_handler()` | `_run_streaming_loop()` → `_handle_tool_calls()` |
| **步骤状态机** | `THINKING` → `CALLING_TOOL` → `REFLECTING` → `COMPLETED` / `ERROR` | 无显式状态机，靠 phase 字符串 |
| **任务完成检测** | `task_done` 工具调用 + git diff 非空检查 | 无结构化完成机制 |
| **错误处理** | per-step try/except + `AgentStepState.ERROR` | 四级防御(NOTE/IMPORTANT/CRITICAL/硬拦截) |
| **最大步数** | 可配置(默认200) | 无硬上限 |

### 2.2 LLM 抽象层

| 维度 | Trae-Agent | HakusAI_chat |
|------|-----------|-------------|
| **Provider 数量** | 7个 (OpenAI/Anthropic/Azure/Ollama/OpenRouter/Doubao/Google) | 1个 (DeepSeek) |
| **抽象方式** | `LLMClient` → `BaseLLMClient`(ABC) + 7个具体 Client | 直接调用 OpenAI SDK |
| **Tool Calling** | 统一 `ToolCall`/`ToolResult` 数据类 | 原始 JSON 解析 |
| **并行 Tool Call** | `parallel_tool_call()` (asyncio.gather) | 顺序执行 |
| **Chat History 管理** | LLMClient 内部维护 `set_chat_history()` | ContextManager 外部管理 |
| **Usage 追踪** | `execution.total_tokens` 累加 | EMA 校准因子 |

### 2.3 工具系统

| 维度 | Trae-Agent | HakusAI_chat |
|------|-----------|-------------|
| **工具数量** | 5 核心工具 + MCP 动态扩展 | 20+ 内置工具 |
| **基类设计** | `Tool(ABC)` — `get_name()/get_description()/get_parameters()/execute()` | `BaseTool` — `name/description/parameters/execute()` |
| **Schema 生成** | `json_definition()` 自动生成 OpenAI/Anthropic 格式 | 手动构建参数字典 |
| **执行器** | `ToolExecutor` — 名称归一化 + 异常包装 | 直接调用 `tool.execute()` |
| **并行执行** | ✅ `parallel_tool_call()` | ❌ 串行 |
| **Docker 沙箱** | ✅ `DockerToolExecutor` | ❌ 无 |
| **MCP 支持** | ✅ 完整 MCP Client | ❌ 无 |

**Trae-Agent 的 5 个核心工具**:
1. `str_replace_based_edit_tool` — 字符串替换编辑（非行号）
2. `bash` — Bash 命令执行（带 session 管理）
3. `sequentialthinking` — 结构化思维链
4. `json_edit_tool` — JSON 文件编辑
5. `task_done` — 任务完成信号

### 2.4 上下文管理

| 维度 | Trae-Agent | HakusAI_chat |
|------|-----------|-------------|
| **消息存储** | `list[LLMMessage]` 简单列表 | `ContextManager` 类（消息+系统提示+工具结果） |
| **Token 估算** | 无（依赖 API 返回 usage） | `estimate_tokens()` + EMA 校准 |
| **上下文压缩** | 无 | `compact()` 命令手动触发 |
| **截断策略** | 无（依赖 max_steps 限制） | 工具结果截断 3000 字符 |
| **百分比显示** | 无 | ✅ 实时上下文百分比 |

### 2.5 UI/交互层

| 维度 | Trae-Agent | HakusAI_chat |
|------|-----------|-------------|
| **UI 框架** | Rich (CLI Console) | Textual (TUI v2) |
| **交互模式** | CLI 交互模式 (`trae-cli interactive`) | 全 TUI 应用 |
| **Lakeview** | ✅ 每步简洁摘要 | ❌ 无 |
| **斜杠命令** | ❌ 无 | ✅ 27 个命令 |
| **渐变效果** | ❌ 无 | ✅ FadeOverlay |
| **活动状态条** | CLI 状态更新 | ActivityStrip widget |

### 2.6 测试与评估

| 维度 | Trae-Agent | HakusAI_chat |
|------|-----------|-------------|
| **评估框架** | SWE-bench / SWE-bench-live / multi-SWE-bench | HarnessSuite (自建冒烟测试) |
| **轨迹录制** | ✅ `TrajectoryRecorder` — JSON 格式 | ✅ turn_debug.py — JSONL + log 双格式 |
| **Mock 工具** | ❌ 无专用 Mock | ✅ MockToolRegistry |
| **CI 集成** | GitHub Actions | ❌ 无 |
| **Docker 测试** | ✅ Docker mode for isolation | ❌ 无 |

### 2.7 配置系统

| 维度 | Trae-Agent | HakusAI_chat |
|------|-----------|-------------|
| **格式** | YAML (推荐) + JSON (legacy) + 环境变量 | YAML (config.yaml) |
| **优先级** | CLI > 配置文件 > 环境变量 > 默认值 | 配置文件 > 环境变量 > 默认值 |
| **模型配置** | 多 provider + 多 model 定义 | 单 model + base_url |
| **动态加载** | ✅ Config 类统一解析 | PyYAML 直接 load |

---

## 三、关键差距与改进方向

### 3.1 高优先级改进（直接影响稳定性）

#### H1: 缺少显式步骤状态机
**问题**: 我们的 AgentCore 没有像 trae-agent 那样的 `THINKING→TOOL_CALL→REFLECT→DONE` 状态机。当前靠 phase 字符串和事件驱动，状态转换不清晰。
**借鉴**: trae-agent 的 `AgentStep` + `AgentStepState` 枚举
**改进方案**:
```
class StepState(Enum):
    THINKING = "thinking"
    STREAMING = "streaming"       # 我们独有（流式）
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    REFLECTING = "reflecting"
    COMPLETED = "completed"
    ERROR = "error"
    ABORTED = "aborted"

@dataclass
class AgentStep:
    step_number: int
    state: StepState
    llm_response: LLMResponse | None = None
    tool_calls: list[ToolCall] = []
    tool_results: list[ToolResult] = []
    reflection: str | None = None
    error: str | None = None
    tokens_used: int = 0
    start_time: float = 0.0
    end_time: float = 0.0
```

#### H2: 缺少结构化任务完成机制
**问题**: 当前没有可靠的方式判断 Agent 是否完成了任务。trae-agent 用 `task_done` 工具调用作为显式完成信号。
**改进方案**:
- 新增 `task_done` 工具到内置工具集
- 在 system prompt 中明确指示："完成任务后必须调用 task_done 工具"
- 在主循环中检测 `task_done` 调用后正常退出

#### H3: LLM Provider 抽象不足
**问题**: 目前硬绑定 DeepSeek/OpenAI SDK。切换模型需要改多处代码。
**借鉴**: trae-agent 的 `LLMClient` + `BaseLLMClient`(ABC) + Provider Enum
**改进方案**:
```python
class LLMProvider(Enum):
    DEEPSEEK = "deepseek"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"

class BaseLLMClient(ABC):
    @abstractmethod
    async def chat(self, messages, tools=None) -> LLMResponse: ...
    @abstractmethod
    def supports_tool_calling(self) -> bool: ...

class LLMClient:
    def __init__(self, config: ModelConfig):
        match config.provider:
            case LLMProvider.DEEPSEEK: self.client = DeepSeekClient(config)
            case LLMProvider.OPENAI: self.client = OpenAIClient(config)
            # ...
```

### 3.2 中优先级改进（提升工程质量）

#### M1: 工具执行器模式
**问题**: 当前工具调用是直接 `tool.execute(args)` ，缺少归一化、异常包装、并行能力。
**借鉴**: trae-agent 的 `ToolExecutor`
**改进方案**:
```python
class ToolExecutor:
    def __init__(self, tools: list[BaseTool]):
        self._tools = {t.name.lower(): t for t in tools}

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        tool = self._tools.get(tool_call.name.lower())
        if not tool:
            return ToolResult(success=False, error=f"Unknown tool: {tool_call.name}")
        try:
            result = await tool.execute(tool_call.arguments)
            return ToolResult(success=True, result=result)
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    async def parallel_execute(self, calls: list[ToolCall]) -> list[ToolResult]:
        return await asyncio.gather(*[self.execute(c) for c in calls])
```

#### M2: 轨迹录制增强
**问题**: 当前 turn_debug.py 有基础录制，但缺少 trae-agent 那样的结构化 `AgentExecution` 对象。
**借鉴**: trae-agent 的 `TrajectoryRecorder` + `AgentExecution`/`AgentStep`
**改进方案**:
- 将 `AgentExecution` 和 `AgentStep` 引入我们的 debug 系统
- 每步自动记录: state, llm_request, llm_response, tool_calls, tool_results, tokens, timing
- 支持回放和分析

#### M3: Lakeview 式步骤摘要
**问题**: 用户反馈"不知道当前在做什么"。我们已有 activity strip 但不够简洁。
**借鉴**: trae-agent 的 Lakeview — 每一步一行简洁摘要
**改进方案**:
```
[Lakeview]
Step 1: 🔍 ReadFile(hakus/agent.py) — 500 lines loaded
Step 2: ✏️ EditFile(line 142) — Added token calibration
Step 3: 🔄 Grep("calibrate_tokens") — Found 3 matches
Step 4: 🧠 Thinking... (2.3s)
```

#### M4: 配置系统升级
**问题**: 当前 config.yaml 是扁平的 YAML，缺少 trae-agent 那样的层级结构和环境变量覆盖。
**改进方案**:
```yaml
# 新 config 结构
agents:
  hakus_ai:
    model: deepseek-chat
    max_steps: 50
    enable_lakeview: true
    tools:
      - read_file
      - edit_file
      - bash
      - grep
      - task_done          # 新增

model_providers:
  deepseek:
    api_key: ${DEEPSEEK_API_KEY}
    base_url: https://api.deepseek.com
    provider: deepseek

mcp_servers:                    # 未来支持
  playwright:
    command: npx
    args: ["@playwright/mcp"]
```

### 3.3 低优先级改进（锦上添花）

#### L1: MCP 协议支持
**借鉴**: trae-agent 已有完整 MCP Client 实现
**价值**: 接入 Playwright MCP（浏览器自动化）、数据库 MCP 等
**工作量**: 中等（需实现 MCP Client + MCP Tool 适配器）

#### L2: Docker 沙箱模式
**借鉴**: trae-agent 的 DockerManager + DockerToolExecutor
**价值**: 安全隔离 Bash 执行，防止误操作破坏宿主机
**工作量**: 较大（需 Docker SDK + 工具代理）

#### L3: SWE-bench 评估集成
**借鉴**: trae-agent 的 evaluation/ 目录（swebench 集成）
**价值**: 用标准 benchmark 衡量 Agent 能力
**工作量**: 中等

#### L4: 并行工具调用
**借鉴**: trae-agent 的 `parallel_tool_call()`
**价值**: 当多个独立工具可同时执行时（如同时读多个文件），显著提速
**工作量**: 小（asyncio.gather 即可）

---

## 四、实施计划

### Phase 1: 核心架构加固（预计改动 3 个文件）
1. **`hakus/agent.py`** — 引入 `StepState` 枚举 + `AgentStep` dataclass，重构主循环
2. **`hakus/tools/base.py`** — 增加 `ToolCall`/`ToolResult`/`ToolExecResult` 数据类
3. **`hakus/tools/builtin/task_done.py`** — 新增 `task_done` 工具

### Phase 2: LLM 抽象层重构（预计新建 3 个文件 + 改 2 个）
1. **`hakus/models/base_client.py`** — `BaseLLMClient`(ABC)
2. **`hakus/models/deepseek_client.py`** — DeepSeek 具体实现
3. **`hakus/models/client_factory.py`** — `LLMClient` 工厂类
4. **`hakus/agent.py`** — 改为使用新的 LLM 抽象
5. **`config.yaml`** — 新增 provider 配置段

### Phase 3: 工具执行器 + Lakeview（预计改 3 个文件 + 新建 1 个）
1. **`hakus/tools/executor.py`** — 新建 `ToolExecutor`
2. **`hakus/agent.py`** — 使用 ToolExecutor 替代直接调用
3. **`hakus/tui_v2/widgets/activity.py`** — Lakeview 风格的步骤摘要
4. **`hakus/tui_v2/streaming.py`** — 与 Lakeview 联动

### Phase 4: 轨迹录制增强（预计改 2 个文件）
1. **`utils/turn_debug.py`** — 引入 AgentExecution/AgentStep 结构
2. **`hakus/agent.py`** — 每步自动记录到 trajectory

### Phase 5: 配置系统升级（预计改 2 个文件）
1. **`config.yaml`** — 重构为层级结构
2. **`hakus/config.py`** — 新建 Config 解析类（如不存在则新建）

---

## 五、假设与决策

1. **保持 TUI 作为主要 UI** — 不学 trae-agent 的纯 CLI 模式，Textual TUI 是我们的差异化优势
2. **不引入 Docker 依赖** — 目标用户是个人开发者，Docker 增加使用门槛
3. **暂不实现完整 MCP** — 先预留接口，后续按需接入
4. **保留 Cyberpunk 主题** — 视觉风格是产品特色，不在此次改进范围内
5. **DeepSeek 保持默认 Provider** — 但架构上支持扩展其他 Provider

---

## 六、验证步骤

每个 Phase 完成后：
1. `python -c "from hakus.agent import AgentCore; ..."` 导入验证
2. `python -m hakus.entry` 启动应用验证 UI 正常
3. 输入 `/` 验证命令补全
4. 发送一条消息验证 Agent 循环正常运行
5. 检查 debug 日志中是否有新的结构化字段
