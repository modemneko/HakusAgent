# 架构灵魂问题：Python + 前端 vs 纯 Node.js — 老实回答 + Cherry Studio 源码深扒

> 背景: 用户问「我这个 Python + 前端的架构做这种不太适合? 我发现 Hermes、Cherry Studio 都是纯 nodejs 的」,
> 同时让我下载 Cherry Studio 源码扒一遍. 本文分两部分:
>   **第一部分** — 老实回答架构问题 (不偏袒任何一方)
>   **第二部分** — Cherry Studio 源码深扒 + HakusAI 应该学什么/不学什么

---

## 一、先泼一盆冷水: 你看到的「纯 Node.js」是表象

Cherry Studio、Hermes 这些项目从外部看「纯 Node.js」是因为它们最终交付物是 `.exe` / `.dmg` / `.AppImage`,
里面打包的是 Electron. 但如果你真的去看 Cherry Studio 源码 (我已 clone 在 `/home/z/my-project/analysis/cherry-studio`),
会发现它的内部其实也是**多语言混合**的:

| 子系统 | 语言 | 文件 / 目录 |
|---|---|---|
| Electron main / renderer | TypeScript | `src/main/`, `src/renderer/` |
| **编码 Agent 后端 (OpenClaw)** | **Rust 二进制** | `src/main/services/OpenClawService.ts` spawn 的 `cherry-claw` 可执行文件 |
| 本地模型推理后端 (Ollama / LM Studio / OVMS) | Go / C / Rust | 通过 child_process spawn |
| OCR | C++ (Tesseract) + Python (PaddleOCR) | `OcrSettings.tsx` 配置, 由 BinaryManager 拉起 |
| Python 沙箱 | Pyodide (WASM) | `src/renderer/workers/pyodide.worker.ts` — Python 在浏览器跑 |
| MCP 服务 | 任何语言 | MCP 协议本身是 JSON-RPC over stdio/SSE |
| 文档处理 | Tesseract / Pandoc / 各种外部二进制 | `DependenciesSettings` 让用户装 |
| 数据备份 | TS + S3 SDK + WebDAV 客户端 | `DataSettings/` |

**真相**: Cherry Studio 主程序是 TS, 但「能用的桌面 AI 工具」一定会在某些子模块用其他语言.
区别只是 — **Python 是不是核心 agent runtime**.

Cherry Studio 把编码 Agent 的核心 (推理循环、工具调用、上下文管理) **外包给了 Rust 二进制 `cherry-claw`**,
TS 只负责 UI 和 IPC 编排. 这不是「纯 Node」, 这是「Node + Rust」.

而 HakusAI 把编码 Agent 核心放在 **Python sidecar** 里 (PyInstaller 打包). 这是「Node + Python」.

所以问题不是「Python + 前端是不是不适合」, 真正的问题是 —
**「Python 作为 Agent runtime, 比 Rust / 纯 TS 是不是更差?」**

---

## 二、Python 作为 Agent runtime 的真实定位

### Python 的优势 (诚实版)

1. **AI 生态原生** — LangChain / LlamaIndex / smolagents / Anthropic SDK / OpenAI SDK 都 Python 优先.
   最新论文里的 agent 框架 99% Python. 你想抄任何前沿实现, 抄过来就是 Python.

2. **subprocess / asyncio 混合写起来自然** — HakusAI 现在的 `hakus/agent.py` 里同时跑 LLM 流式响应、
   工具调用、checkpoint 持久化, Python 的 `asyncio.gather` + `async for` 写起来比 Node 的
   `Promise.all` + `ReadableStream` 直观.

3. **PyInstaller 打包出来的 exe 双击能跑** — 不依赖用户机器装 Python. 这是 HakusAI 现在能用的关键前提.

4. **TUI / CLI 复用同一份代码** — `hakus/tui_v2/` (Textual) 和 sidecar 共享 `hakus/agent.py` 一份核心,
   Node 生态没有这种 1:1 对应物 (Ink / blessed 远不如 Textual).

### Python 的劣势 (诚实版)

1. **打包体积大** — HakusAI sidecar 用 PyInstaller 打出来 ~80 MB,
   Cherry Studio 的 cherry-claw Rust 二进制估计 ~15 MB. 用户首次下载多等 60 秒.

2. **跨进程 IPC 复杂** — Electron ↔ Python sidecar 走 HTTP+WebSocket, 多一层序列化.
   Cherry Studio 的 OpenClaw 走 socket + JSON-RPC, 也多一层, 但 Rust ↔ TS 的边界比 Python ↔ TS 干净
   (类型对齐用 zod / Pydantic 双向同步, 容易漏, 见 HakusAI 的 `EXPECTED_SIDECAR_API_VERSION_INT`).

3. **冷启动慢** — Python 启动 + import 整个依赖树要 1-3 秒,
   Rust 二进制启动 < 100ms. HakusAI 现在用户开 app 等 sidecar 起来明显有感知.

4. **Windows 杀软误杀率高** — PyInstaller exe 因为自带 Python 解释器 + 进程注入特征,
   被 360 / 火绒 / Defender 误判概率显著高于 Rust 二进制. 这是 HakusAI 已经踩过的坑
   (参考之前 commit `c03fc8f` 修 sidecar 启动崩溃的注释).

5. **调试链路长** — 前端报错 → 查 TS → IPC 调用 → Python sidecar → 第三方 API,
   中间任何一个环节断点都需要切 IDE. Cherry Studio 全 TS, 一个 VSCode 窗口搞定.

6. **Node 生态 GUI 工具更顺手** — electron-store / electron-updater / electron-builder
   都是 TS-first. HakusAI 现在配置文件还得 Python 端 `pydantic-settings` 解析 + TS 端 `electron-store` 缓存,
   两套配置同步逻辑容易出 bug (参考 `52017b4` 的 provider 切换 bug 根因).

### 客观结论

**用 Python 做 Agent runtime 不是错误选择, 但也不是最优选择.**

- 如果你团队 Python 经验 > Rust 经验 → 用 Python (HakusAI 现状)
- 如果你团队 TS 经验 > Python 经验 → 用 TS + ai-sdk (Cherry Studio 路线)
- 如果你追求极致性能 / 体积 → 用 Rust 写 agent core (Cherry Studio 的 OpenClaw)

**HakusAI 当前架构 (Python sidecar + Electron) 的真正问题不是「Python」, 而是下面 3 个具体设计债**:

1. sidecar 通过 HTTP 跟前端通信 → 强耦合 + 双向类型同步地狱
   (本可以走 stdio JSON-RPC, 像 Claude Code / Cursor 那样)
2. sidecar 内嵌 PyInstaller exe 跟着客户端一起分发 → 体积 + 杀软问题
   (本可以让用户选「用本地 Python」or「下载预编译 sidecar」, 像 Cherry Studio 装 Ollama 那样可选)
3. 前端没有完整的 IPC 抽象层, 直接 fetch → 业务逻辑跟传输层混在一起
   (Cherry Studio 有完整的 `ipcApi.ts`, renderer 完全不知道背后是 IPC 还是 HTTP)

**这三个问题都可以在不换语言的前提下修. 不要为了「像 Cherry Studio」就推倒重来.**

---

## 三、Cherry Studio 源码深扒

### 3.1 整体规模 (让人倒吸一口凉气)

| 指标 | Cherry Studio 2.0-dev | HakusAI 当前 |
|---|---|---|
| 总源码 LOC (不含测试) | ~363,000 | ~52,000 |
| 测试文件数 | **1,416 个 `.test.ts*`** | < 30 |
| 工作区包 (pnpm workspace) | 6 个 (`@cherrystudio/ui`, `@cherrystudio/ai-core`, `provider-registry`, `aiCore`, `mcp-trace`, `extension-table-plus`) | 0 (单体) |
| 内置 Provider 数 | **68 个** (`packages/provider-registry/src/providers/`) | 13 个 (`hakus/models/*_client.py`) |
| 设置子页面数 | **20 个** (见下文) | 9 个 |
| 主进程服务 | 31 个 (`src/main/services/`) | 0 (sidecar 全包) |
| 依赖总数 | **343** | ~50 |
| 团队规模估计 | 5-10 人专职 | 1-2 人业余 |

**第一个结论: 不要直接对标 Cherry Studio 的功能广度, 那是 5-10 人团队两年的积累.**

### 3.2 设置页 20 个子页面 — 你提到的 9 大功能来源

`src/renderer/pages/settings/SettingsPage.tsx` 左侧菜单:

| 分组 | 子页面 | HakusAI 对应 |
|---|---|---|
| **capabilities** | Provider (模型服务) | ModelPanel.tsx (有, 但简陋) |
| capabilities | Model (模型管理) | ❌ 无 |
| capabilities | Local Models (本地模型) | ❌ 无 |
| capabilities | API Gateway (API 网关) | ❌ 无 |
| **tools** | MCP (MCP 服务器) | ❌ 无 — **重大缺失** |
| tools | Web Search (网络搜索) | ❌ 无 — **重大缺失** |
| tools | File Processing (文档处理) | ❌ 无 |
| tools | OCR (图像识别) | ❌ 无 |
| **personal** | Appearance (外观) | AppearancePanel.tsx ✓ |
| personal | Notification (通知) | ❌ 无 |
| personal | Data (数据设置 / 备份 / 同步) | AdvancedPanel 部分 |
| **automation** | Channels (频道: 微信/QQ/TG/Slack/Discord/飞书) | ❌ 无 — 大特色 |
| automation | Scheduled Tasks (定时任务) | ❌ 无 |
| automation | Shortcuts (快捷键) | ❌ 无 |
| automation | Quick Assistant (快速助手) | ❌ 无 |
| automation | Selection Assistant (划词助手) | ❌ 无 |
| **system** | System (常规设置) | ChatPanel.tsx 部分 |
| system | Dependencies (依赖管理) | ❌ 无 |
| system | About | ❌ 无 |

**HakusAI 比 Cherry Studio 多的:**
- CharacterPanel (角色 / 人格) — Cherry Studio 用 Agents 概念代替, 但 HakusAI 这种 VTuber 风格的角色配置 Cherry Studio 没有
- TtsPanel (语音 TTS) — Cherry Studio 没有内建 VTuber TTS, 它走系统 TTS
- ToolsPanel (工具与权限) — Cherry Studio 的工具是分散到 MCP / WebSearch 各子页的, HakusAI 集中在一处更直观

### 3.3 Provider 设置的工程深度 — HakusAI 应该学的

Cherry Studio `ProviderSettings/` 目录总 LOC: **10,770 行** (HakusAI ModelPanel.tsx 377 行, 差 28 倍).

为什么差这么多? 因为 Cherry Studio 把 Provider 设置拆成 7 个子模块:

```
ProviderSettings/
├── ProviderList/              # 左侧 provider 列表 (搜索/分组/添加/删除)
├── ConnectionSettings/        # API Key / Host / 多 Key 管理 / 连接测试
│   ├── ApiKey.tsx
│   ├── ApiHost.tsx
│   ├── AuthenticationSection.tsx
│   ├── ProviderApiKeyListDrawer.tsx     # 一个 provider 配多个 Key 轮换/负载均衡
│   ├── ProviderConnectionCheckDrawer.tsx # 点「检查」按钮测连通性, 显示具体错误
│   └── ProviderCustomHeaderDrawer.tsx   # 自定义 HTTP Header (兼容某些代理)
├── ModelList/                 # 「获取模型列表」按钮 + 模型同步 UI
│   ├── ModelList.tsx
│   ├── ModelListSyncDrawer.tsx          # 拉取远程模型列表, 勾选要启用的
│   └── ModelSyncPreviewPanel.tsx
├── ProviderSpecific/          # 特定 provider 专属配置 (12 个)
│   ├── AwsBedrockSettings.tsx           # AWS Bedrock ARN 配置
│   ├── VertexAiSettings.tsx             # GCP Vertex AI 服务账号 JSON
│   ├── GithubCopilotSettings.tsx        # Copilot OAuth 登录
│   ├── ClaudeCodeSettings.tsx           # Claude Code 模式
│   ├── LmStudioSettings.tsx             # LM Studio 本地发现
│   ├── OvmsSettings.tsx                 # OpenVINO Model Server
│   ├── GpuStackSettings.tsx             # GPUStack
│   ├── DmxapiSettings.tsx               # DMXAPI 中转
│   ├── CherryInSettings.tsx             # Cherry 自己的聚合 API
│   ├── CherryInOauth.tsx                # OAuth 流程
│   ├── LoginOauthPanel.tsx
│   └── ProviderOauth.tsx
├── components/                # 通用组件 (Header / Avatar / FreeTrialTag)
├── primitives/                # 设计系统原子组件
└── utils/                     # modelSync / healthCheck 等纯函数
```

**HakusAI 缺失的具体功能 (按优先级):**

1. **「获取模型列表」按钮** — 用户配好 API Key + Base URL, 点一下能从 provider 的 `/v1/models` 端点
   拉真实可用模型列表, 不需要用户手抄模型名. Cherry Studio 的实现:
   - `packages/provider-registry/src/providers/<provider>.ts` 里每个 provider 声明 `fetchModels: () => Promise<{id: string}[]>`
   - 走 IPC → main → ai-sdk → provider `/models` 端点
   - 返回后在 `ModelListSyncDrawer` 里勾选, 写入 SQLite
   
   **HakusAI 现状**: ModelPanel 让用户手输 `model_name` 字符串. 用户不知道 deepseek 还有 `deepseek-reasoner`,也不知道 OpenCode Zen 有哪些免费模型. 这是最该补的 UX.

2. **连接测试按钮** — 配完 Key 立即测一下, 别等用户发消息才发现 Key 错.
   Cherry Studio `ProviderConnectionCheckDrawer` 显示: 选用哪个模型测试 / 选用哪个 Key / 错误详情 / 重试.

3. **多 API Key 轮换** — 一个 provider 配多个 Key, 自动 fallback / 负载均衡.
   HakusAI 现在一个 provider 只能一个 Key, Key 用超限了得手动改.

4. **自定义 HTTP Header** — 兼容第三方中转 (DMXAPI / OpenRouter 等). HakusAI 没这个, 用中转服务会失败.

5. **Provider 分组 + 搜索** — 68 个 provider 不分组没法用. Cherry Studio 分:
   - 国内 (DeepSeek / Qwen / 智谱 / 月之暗面 / 百川 / 文心 / Hunyuan / Doubao)
   - 国际 (OpenAI / Anthropic / Gemini / Groq / Mistral / Cohere)
   - 本地 (Ollama / LM Studio / vLLM / GPUStack / OVMS)
   - 聚合 (OpenRouter / DMXAPI / Together / Fireworks / Hyperbolic)
   
   HakusAI 现在 13 个 provider 平铺, 未来加到 30+ 就乱了.

### 3.4 Cherry Studio 主进程服务 — HakusAI 完全没有的概念

Cherry Studio 的 `src/main/services/` 31 个服务, 每个都是一个 `@Injectable` 装饰器的 class:

| 服务 | 行数 | HakusAI 对应 |
|---|---|---|
| `OpenClawService` | 950 | HakusAI 整个 sidecar |
| `FileStorage` | 1218 | sidecar 内嵌 |
| `LegacyBackupManager` | 1412 | ❌ 无 — 用户数据没法备份 |
| `OvmsManager` | 568 | ❌ 无 |
| `BinaryManager` | 722 | ❌ 无 — 不下载外部二进制 |
| `MainWindowService` | 561 | frontend/client/src/main/main.ts (~300 行) |
| `AppUpdaterService` | 537 | ❌ 无 — 没自动更新 |
| `QuickAssistantService` | 521 | ❌ 无 |
| `TopicNamingService` | 420 | sidecar 内嵌 |
| `ExportService` | 408 | ❌ 无 |
| `CopilotService` | 328 | ❌ 无 |
| `ShortcutService` | 304 | ❌ 无 |
| `PrintService` | 347 | ❌ 无 |
| `CitationPreviewService` | 255 | ❌ 无 |
| `ObsidianVaultService` | 224 | ❌ 无 |
| `SubWindowService` | 250 | ❌ 无 |
| `AppMenuService` | 217 | ❌ 无 |
| `WebviewService` | 275 | ❌ 无 |
| `VersionService` | 280 | ❌ 无 |
| `PythonService` | ~100 | ❌ 无 — 但 Cherry Studio 这个 Python 是 Pyodide (WASM), 跑在 renderer |
| `NotificationService` | - | ❌ 无 |
| `TrayService` | - | electron 自带 Tray, HakusAI 用了一点点 |
| `ThemeService` | - | AppearancePanel.tsx 内嵌 |
| `S3Storage` | - | ❌ 无 |
| `FileSystemService` | - | sidecar 内嵌 |
| `StorageMonitorService` | - | ❌ 无 |
| `RegionService` | - | ❌ 无 |
| `ExternalAppsService` | - | ❌ 无 |
| `ContextMenu` | - | electron 自带 |
| `AnalyticsService` | - | ❌ 无 |
| `CommandService` | - | ❌ 无 |

**Cherry Studio 在 main 进程做了大量「桌面应用该有但 sidecar 不该管」的事**:
自动更新 / 系统托盘 / 全局快捷键 / 多窗口管理 / 数据备份到 S3/WebDAV/Obsidian/Notion / 系统通知 /
菜单栏 / 命令面板 / 引用预览 / 打印 / 区域设置 / 外部应用拉起 / 上下文菜单 / 遥测.

**HakusAI 现状**: 这些事要么 sidecar 顺手做了 (不该做), 要么根本没做.
正确架构应该是 — sidecar 只管 agent runtime, 所有桌面壳相关功能在 Electron main 进程做.

### 3.5 Provider 抽象层 — 数据驱动 vs 代码驱动

**HakusAI 方式 (代码驱动)**:
```
hakus/models/
├── base_client.py             # 抽象基类
├── openai_compatible_client.py
├── deepseek_client.py         # 继承 openai_compatible
├── opencode_client.py         # 继承 openai_compatible
├── anthropic_client.py
├── glm_client.py
├── gemini_client.py
├── qwen_client.py
├── mimo_client.py
├── ollama_client.py
├── litellm_client.py
├── openai_client.py
├── client_factory.py          # if-else 工厂
└── provider_registry.py       # 列表硬编码
```

每加一个 provider 就新建一个 .py 文件, 改 client_factory 的 if-else, 改 provider_registry 的列表.
**13 个 provider 已经出现了 3 处需要同步修改的地方**, 上次 OpenCode 加得漏了 base_url 配置才出 bug.

**Cherry Studio 方式 (数据驱动)**:
```
packages/provider-registry/src/providers/
├── deepseek.ts                # 声明式: id + baseUrl + adapterFamily + website + overrides
├── anthropic.ts
├── ... 65 more
└── types.ts                   # defineProvider / openaiCompatible 工厂函数
```

每个 provider 文件就是一份**声明式配置**:
```typescript
// deepseek.ts — 全文
export default defineProvider({
  id: 'deepseek',
  name: 'deepseek',
  defaultChatEndpoint: 'openai-chat-completions',
  endpointConfigs: {
    'openai-chat-completions': { adapterFamily: 'deepseek', baseUrl: 'https://api.deepseek.com' },
    'anthropic-messages': { adapterFamily: 'anthropic', baseUrl: 'https://api.deepseek.com/anthropic' }
  },
  metadata: { website: { apiKey: '...', docs: '...', models: '...', official: '...' } },
  overrides: [{ modelId: 'deepseek-chat' }, { modelId: 'deepseek-reasoner' }]
})
```

加一个新 provider 不需要碰任何工厂代码, 不需要改 client_factory 的 if-else, 只需要新建一个 .ts 文件.
运行时 `registry-loader.ts` 自动扫描所有 provider 文件注册.

**这个差距是巨大的**: HakusAI 加一个 provider 涉及 5-7 个文件修改 (参考 `.trae/documents/opencode-provider-and-architecture-review.md` 里列的 8 步), Cherry Studio 只需要 1 个新文件.

### 3.6 数据层 — SQLite vs YAML

**HakusAI**: `~/.hakus/config.yaml` + sidecar 内存里的会话状态. 没有真正的数据库.
- 历史会话存哪? 内存 + JSON dump
- 跨设备同步? 没有
- 多窗口共享状态? 没有
- 模型 metadata (价格 / 能力 / 上下文长度)? 散落在 config.yaml

**Cherry Studio**: `better-sqlite3` 主数据库 + Redux 状态管理.
- 所有会话 / 消息 / Topic / Agent / Provider / Model / MCP 服务器 / 快捷键 都是表里的行
- 支持复杂查询 (按 provider 统计 token 消耗 / 按时间范围导出 / 全文搜索历史消息)
- 备份就是 dump 整个 .db 文件到 S3 / WebDAV / Obsidian / Notion
- 多窗口 (主窗口 + Quick Assistant + Translate) 共享同一份数据

**HakusAI 该学什么**: 至少把会话历史从内存迁到 SQLite. 不然 app 一崩, 用户历史全没.

### 3.7 IPC 抽象层

**HakusAI 现状**: 前端 `frontend/client/src/api/client.ts` 直接 `fetch('http://127.0.0.1:port/api/chat')`.
HTTP 路径硬编码在业务代码里, 切换传输层 (HTTP → stdio IPC) 要改 N 处.

**Cherry Studio**: `src/renderer/ipc/ipcApi.ts` 提供统一抽象:
```typescript
// renderer 业务代码
const models = await ipcApi.request('ai.list_models', { providerId })
```

`ipcApi.request` 内部可以走:
- Electron IPC (主进程 → renderer)
- HTTP (调用 sidecar)
- WebSocket (流式响应)
- MCP 协议 (调用外部 MCP 服务器)

业务代码完全不关心传输层. 想从 HTTP 切到 stdio, 改 `ipcApi.ts` 一处即可.

---

## 四、HakusAI 应该学什么 / 不该学什么

### ✅ 该学 (优先级从高到低)

#### P0: Provider 设置 UI 升级
- 「获取模型列表」按钮 — 调用 provider 的 `/v1/models` 端点拉真实模型
- 「连接测试」按钮 — 配完 Key 立即测, 别等用户发消息才发现错
- 多 API Key 轮换 — 一个 provider 配多个 Key, 失败自动切下一个
- 自定义 HTTP Header — 兼容第三方中转
- Provider 分组 + 搜索 — 准备扩到 30+ provider

#### P0: 历史会话持久化迁到 SQLite
- 不用 sidecar 内嵌的 dict + JSON dump
- 用 `better-sqlite3` (Electron 主进程) 或 sidecar 内嵌 `sqlite3` (Python)
- 表结构参考 Cherry Studio: sessions / messages / topics / agents

#### P1: IPC 抽象层
- 前端不直接 fetch, 走 `ipcApi.request(channel, params)` 抽象
- 把传输层 (HTTP / stdio / WebSocket) 隐藏起来
- 为未来「sidecar 走 stdio」或者「干掉 sidecar 走 main 进程」留口子

#### P1: MCP 服务器支持
- Cherry Studio `McpSettings/` 整套 (列表 / 详情 / 市场 / 内建)
- MCP 是 2025 年事实标准, 不支持等于自绝生态
- HakusAI 的 `hakus/tools/` 是私有协议, 应该改成 MCP 客户端 + 内置工具 MCP 化

#### P1: 数据备份 / 同步
- 至少支持本地导出 / 导入 (整个 `.db` 文件)
- 进阶: WebDAV / S3 / Obsidian 同步

#### P2: 自动更新
- `electron-updater` + GitHub Releases
- Cherry Studio 的 `AppUpdaterService` 是参考

#### P2: 系统托盘 + 全局快捷键
- 最小化到托盘
- 全局快捷键唤起 (Cherry Studio `ShortcutService`)

#### P2: 文档处理 (PDF / Word / Excel → Markdown)
- 现在用户粘 PDF 进对话框 HakusAI 是不解析的
- 用 `pandoc` / `markitdown` (Python 库) 在 sidecar 里跑

#### P3: 多窗口 (Quick Assistant / 划词助手)
- 选中文本按快捷键弹小窗
- Cherry Studio `QuickAssistantService` + `SelectionAssistantSettings`

### ❌ 不该学 (坚持 HakusAI 自己的路)

1. **不要把 sidecar 拆成 31 个 main 进程服务**
   - Cherry Studio 那种粒度需要 5-10 人团队维护
   - HakusAI 现在的 sidecar 单进程 + 模块化 Python package 已经够用
   - 学习「服务化思想」(单一职责) 即可, 不要照搬粒度

2. **不要追求 68 个 provider**
   - 13 个已经覆盖国内主流 + 国际主流 + 本地
   - 加到 20 个就够 (再加 Grok / Mistral / Cohere / OpenRouter / Together)
   - 多了维护成本指数级上升 (每个 provider 的模型列表 / 价格 / 能力都要跟)

3. **不要学 Pyodide (WASM Python)**
   - Cherry Studio 用 Pyodide 是因为它的 renderer 需要跑用户写的 Python 代码片段 (Notebook 功能)
   - HakusAI 的 Python 是 agent runtime, 跑在系统 Python (PyInstaller) 里, 性能比 WASM 高 10 倍
   - 不要倒退

4. **不要学 OpenClaw (Rust 二进制) — 至少现在不要**
   - 重写 agent core 到 Rust 需要 3-6 个月
   - HakusAI Python agent 已经能跑, 性能瓶颈不在语言
   - 等 HakusAI 真正有性能瓶颈 (用户量 10K+) 再考虑

5. **不要照搬 Cherry Studio 的设置页 20 项**
   - HakusAI 现在的 9 项面板 (Model / Character / Chat / TTS / Memory / Tools / Appearance / Connection / Advanced) 已经覆盖核心
   - 加 4-5 项就够 (MCP / WebSearch / Data Backup / Shortcuts / About)
   - 加太多反而让用户找不到东西

6. **不要学 Cherry Studio 的「Channels」(微信/QQ/TG/Slack/Discord/飞书)**
   - 这是 Cherry Studio 的差异化功能, 但需要每个平台单独申请 bot token + 维护 API 兼容
   - HakusAI 是个人 AI 助手定位, 不需要 IM 多渠道分发
   - 除非你想转型成客服机器人, 否则是 6 个月工作量打水漂

7. **不要学 Cherry Studio 的「Paintings」(图像生成)**
   - 图像生成是另一个赛道, 跟编码助手无关
   - 加这个会让 HakusAI 失焦

8. **不要学 Cherry Studio 的「Notes」(笔记)**
   - Obsidian / Notion 已经做得很好
   - 集成不如做对接 (Export to Obsidian 这种)

---

## 五、给 HakusAI 的 90 天路线建议

### Phase 1 (第 1-30 天) — 补 UX 短板
**目标: 让现有功能更好用, 不加新功能**

1. Provider 设置加「获取模型列表」+「连接测试」按钮 (P0)
2. 多 API Key 轮换 + 自定义 Header (P0)
3. 历史会话迁到 SQLite, 防止崩溃丢数据 (P0)
4. Provider 列表分组 + 搜索 (P1)

**预期成果**: 用户首次配置时间从 10 分钟降到 2 分钟, 配置出错率降 80%.

### Phase 2 (第 31-60 天) — 接入生态
**目标: 让 HakusAI 能用上 MCP 生态**

5. MCP 客户端实现 (P1)
6. 内置工具 MCP 化 (file / shell / git / search 全部包成 MCP server)
7. MCP 服务器管理 UI (列表 / 添加 / 启停 / 调试)
8. IPC 抽象层 `ipcApi.ts` (P1)

**预期成果**: 用户能装社区 MCP server (GitHub / Slack / Notion / 数据库 等), HakusAI 立刻获得新能力.

### Phase 3 (第 61-90 天) — 桌面化
**目标: 让 HakusAI 真的像个桌面 app 而不是带壳的 CLI**

9. 系统托盘 + 全局快捷键 (P2)
10. 自动更新 (`electron-updater` + GitHub Releases)
11. 数据备份 / 导入导出 (本地 + WebDAV)
12. 文档处理 (PDF / Word 粘贴自动转 Markdown)

**预期成果**: 留存率提升, 用户不再因为「重启就丢历史」流失.

### 不要做的事 (90 天内)
- ❌ 重写 agent core 到 Rust / TS
- ❌ 加 IM Channels
- ❌ 加图像生成
- ❌ 加笔记功能
- ❌ 追求 68 个 provider
- ❌ 学 Cherry Studio 把 main 进程拆成 31 个服务

---

## 六、最后回答用户最初的问题

> 「我这个 Python + 前端的架构做这种不太适合?」

**不适合, 但不是因为 Python, 是因为 sidecar 通过 HTTP 跟前端通信 + 没有完整 IPC 抽象层 + 主进程太薄**.
这三个问题都可以在不换语言的前提下修. 不要为了「像 Cherry Studio」就推倒重来.

> 「我发现 Hermes、Cherry Studio 都是纯 nodejs的」

**它们的「纯 Node」是表象**:
- Cherry Studio 主程序 TS, 但编码 agent 核心是 Rust 二进制 `cherry-claw`, OCR 是 C++ Tesseract + Python PaddleOCR, Python 沙箱是 Pyodide WASM
- Hermes (假设你说的是开源版本) 同样有外部二进制依赖

**真正区别不是「Python vs Node」, 是「单进程 vs 多进程」「代码驱动 vs 数据驱动」「内嵌分发 vs 外部依赖」**.
Cherry Studio 选了多进程 + 数据驱动 + 外部依赖, HakusAI 选了单 sidecar + 代码驱动 + 内嵌分发.
两条路都能走通, 但 HakusAI 的路需要修上面 3 个具体设计债才能走远.

> 「你再看看cherry studio的设置界面有那么多的功能, 你可以多下载扒拉这些优秀开源项目的源码」

**Cherry Studio 值得学的我都列在第四节「该学」里了**, 总共 8 项, P0 优先级 2 项, P1 优先级 3 项, P2 优先级 3 项.
**不值得学的我也列了**, 8 项, 包括不要照搬 31 个服务 / 不要 68 个 provider / 不要 IM Channels / 不要图像生成.

**核心建议: 学 Cherry Studio 的工程方法 (数据驱动 / IPC 抽象 / SQLite 持久化 / Provider UI 工程化), 不学它的功能广度.**

---

## 附: 关键源码位置参考

### Cherry Studio (本次新 clone)
- 仓库: `/home/z/my-project/analysis/cherry-studio/` (depth=1, 2.0.0-dev)
- 设置页主入口: `src/renderer/pages/settings/SettingsPage.tsx`
- Provider 设置主目录: `src/renderer/pages/settings/ProviderSettings/` (10,770 LOC)
- Provider 注册表: `packages/provider-registry/src/providers/` (68 个 provider 声明式文件)
- MCP 设置: `src/renderer/pages/settings/McpSettings/` (16 个组件)
- 主进程服务: `src/main/services/` (31 个 @Injectable 服务)
- 编码 agent 后端: `src/main/services/OpenClawService.ts` (950 行, spawn cherry-claw Rust 二进制)
- 数据层: `better-sqlite3` + Redux
- 总 LOC: ~363,000 + 1,416 个测试

### HakusAI
- 设置主入口: `frontend/client/src/components/settings/SettingsDialog.tsx`
- 设置面板: `frontend/client/src/components/settings/panels/` (9 个, 2,043 LOC)
- Provider 实现: `hakus/models/` (13 个 client.py, 962 LOC)
- Agent 核心: `hakus/agent.py` + `hakus/engine/` + `hakus/tools/builtin/` (10 个工具, 2,556 LOC)
- Sidecar API: `src/hakusai_server/server.py` (1,767 LOC) + `agent_bridge.py` (414 LOC)
- 总 Python LOC: ~52,000
- 总前端 LOC: ~6,000
