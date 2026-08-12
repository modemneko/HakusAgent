# HakusAI Desktop Client

A Cherry Studio–inspired AI chat client for [HakusAgent](https://github.com/modemneko/HakusAgent). Built with **Electron + Vite + React + TypeScript + Tailwind CSS + shadcn/ui**.

> 该客户端是 HakusAgent 仓库 `frontend/client/` 下的全新独立客户端，参考 Cherry Studio / ChatBox / LobeChat 等开源 AI 客户端的设计，专注于「与 HakusAI 后端对话」的纯聊天体验。已有的 `frontend/desktop/` 是 VTuber（Live2D）专注客户端，二者并存。

## ✨ 特性

- **多会话管理** — 侧边栏创建 / 重命名 / 删除 / 置顶 / 搜索会话，全部本地持久化（electron-store + localStorage fallback）。
- **流式聊天** — 通过 SSE（`/api/chat/stream`）或 WebSocket（`/ws/chat`）接收实时增量。
- **AgentEvent 协议就绪** — 客户端已实现 `hakus/protocol/events.py` 中所有事件类型的解析：
  - `TextDelta` / `ReasoningDelta` — 流式文本 & 思维链
  - `ToolCallStarted` / `ToolCallFinished` — 可折叠工具调用卡片
  - `TokenUsage` / `TurnCompleted` — Token 计数 & 回合完成
  - `OrchestratorPhaseChanged` / `ActivityChanged` — 多智能体阶段
  - `PatchApplied` — 文件 Diff（预留）
- **Markdown 渲染** — GitHub-flavored，集成 `rehype-highlight` 代码高亮（github-dark 主题）。
- **工具调用可视化** — 每个工具调用都渲染为可折叠卡片，显示参数、结果、耗时、成功/失败状态。
- **取消请求** — 通过 `AbortController` 中断 SSE 流；WebSocket 模式下可发送 `interrupt` 信号。
- **会话设置** — 服务器 URL、超时、主题（light/dark/system）、字体大小、Enter 行为、是否显示思维链等。
- **打包** — electron-builder 一键产出 Windows NSIS、macOS DMG、Linux AppImage/deb。
- **可选 sidecar** — 通过 PyInstaller 把 HakusAI Python 服务端打包进安装包，实现「整体打包，开箱即用」。

## 🚀 快速开始

### 1. 安装依赖

```bash
cd frontend/client
npm install
```

### 2. 开发模式（仅前端，热重载）

```bash
npm run dev
# 浏览器访问 http://localhost:1421
```

### 3. 开发模式（Electron + 前端）

```bash
npm run dev:electron
# Vite 启动后, Electron 主进程自动拉起并加载 localhost:1421
```

### 4. 生产构建

```bash
npm run build:electron
```

输出：
- `dist/` — 前端静态资源
- `dist-electron/main.js` + `dist-electron/preload.js` — Electron 主进程

### 5. 打包安装程序

```bash
# 当前平台
npm run dist

# 指定平台
npm run dist:win    # → release/HakusAI-Setup-x.y.z.exe (NSIS)
npm run dist:mac    # → release/HakusAI-x.y.z.dmg
npm run dist:linux  # → release/HakusAI-x.y.z.AppImage + .deb
```

产物位于 `frontend/client/release/`。

### 6. 自定义图标

替换 `build-resources/icon.png`（建议 ≥ 512×512 PNG，带透明背景），然后重新生成多尺寸：

```bash
python3 scripts/make-icon.py
```

脚本支持三种模式：
- **从源图生成**（默认）：检测到 `icon.png` 存在时，自动用 LANCZOS 重采样生成 16/32/64/128/256/512/1024 七个尺寸
- **强制占位符**：`--generate` 参数，画一个 violet→fuchsia 渐变 + 白色 "H" 字母的占位图标
- **指定源图**：`--from path/to/master.png`，从指定文件生成

> ⚠️ macOS 要求图标必须是带圆角的方形，不能是全透明圆形，否则 Dock 上会显示异常。

### 7. GitHub Actions 自动构建（推荐）

仓库已配置 `.github/workflows/release.yml`，支持三平台自动打包：

```bash
# 触发正式发布 (会自动创建 GitHub Release)
git tag v0.1.0
git push origin v0.1.0

# 或在 Actions 页面手动 "Run workflow" (仅构建, 不发布 Release)
```

构建矩阵：
| 平台 | Runner | 产物 |
|---|---|---|
| Windows | `windows-latest` | `HakusAI-Setup-x.y.z.exe` |
| macOS | `macos-latest` | `HakusAI-x.y.z.dmg` (x64 + arm64) |
| Linux | `ubuntu-latest` | `HakusAI-x.y.z.AppImage` + `.deb` |

每个平台 job 的流程：
1. checkout 代码
2. setup Node 20 + Python 3.11
3. `pip install -r requirements.txt pyinstaller`
4. `bash scripts/build-sidecar.sh` — 构建 PyInstaller sidecar
5. `npm ci` — 装前端依赖
6. `python3 scripts/make-icon.py` — 生成图标集
7. `npm run dist:PLATFORM` — electron-builder 打包

产物先上传到 Actions artifacts（保留 30 天），推 tag 时还会自动汇总到 GitHub Release。

## 🔌 连接 HakusAI 后端

客户端默认连接 `http://localhost:8080`（HakusAI server 默认端口）。两种运行模式：

### 模式 A：后端独立运行（开发推荐）

```bash
# 终端 1: 启动 HakusAI 服务端
cd /path/to/HakusAgent
python -m hakusai_server.server
# 或 python run.py
```

```bash
# 终端 2: 启动客户端
cd frontend/client
npm run dev:electron
```

### 模式 B：整体打包（生产推荐）

1. **构建 Python sidecar**：

   ```bash
   # 先在 HakusAgent 根目录装好 Python 依赖
   pip install -r requirements.txt
   pip install pyinstaller

   # 构建 sidecar (会生成 frontend/client/sidecar/dist/hakusai-server)
   cd frontend/client
   bash scripts/build-sidecar.sh
   ```

2. **打包 Electron 应用**：

   ```bash
   npm run dist
   ```

3. **结果**：单个安装包（Windows .exe / macOS .dmg / Linux .AppImage），用户双击即可使用，无需额外安装 Python。

   客户端启动时会自动拉起 sidecar，并通过 stdout 协议（`HAKUSAI_PORT=8080`）发现实际监听端口。

## 🎨 UI 设计参考

| 客户端 | 借鉴点 |
|--------|--------|
| **Cherry Studio** | 整体布局（侧边栏 + 主区域 + 顶部栏）、会话管理、Markdown 渲染风格 |
| **ChatBox** | 工具调用卡片设计、Composer 自动调整高度 |
| **LobeChat** | 暗色主题配色（violet → fuchsia 渐变 brand）、消息气泡圆角 |
| **Open WebUI** | 模型信息展示在顶部栏、连接状态徽章 |

## 📁 项目结构

```
frontend/client/
├── electron/                # Electron 主进程
│   ├── main.ts             # 主进程入口（窗口、IPC、store）
│   ├── preload.ts          # 预加载脚本（contextBridge）
│   └── sidecar.ts          # Python 后端 sidecar 管理
├── src/
│   ├── api/
│   │   ├── client.ts       # HakusAI REST + SSE + WS 客户端
│   │   └── types.ts        # 与 server.py 对应的 TypeScript 类型
│   ├── store/
│   │   ├── session.ts      # 会话/消息 store (zustand + localStorage)
│   │   ├── settings.ts     # 设置 store (electron-store 持久化)
│   │   ├── connection.ts   # 连接健康检查
│   │   └── app.ts          # 应用级运行时状态
│   ├── components/
│   │   ├── ui/             # shadcn/ui 基础组件 (Button, Dialog, ...)
│   │   ├── sidebar/        # 会话侧边栏
│   │   ├── chat/           # 聊天视图、消息气泡、Markdown、工具卡片、输入框
│   │   ├── settings/       # 设置对话框
│   │   └── layout/         # 顶部栏
│   ├── lib/
│   │   └── utils.ts        # cn(), generateId(), 时间格式化, 剪贴板
│   ├── App.tsx             # 应用根组件
│   ├── main.tsx            # React 入口
│   └── index.css           # Tailwind + 全局样式 + Markdown 样式
├── scripts/
│   ├── build-sidecar.sh    # PyInstaller 打包 HakusAI 服务端
│   └── make-icon.py        # 生成应用图标
├── build-resources/        # electron-builder 资源（图标等）
├── sidecar/                # PyInstaller 输出目录（构建后生成）
├── package.json
├── electron-builder.yml    # 打包配置（内嵌于 package.json 的 build 字段）
├── vite.config.ts
├── tailwind.config.js
└── tsconfig.json
```

## 🛠️ 技术栈

| 层 | 技术 | 选型理由 |
|---|---|---|
| 桌面框架 | Electron 33 | 无需 Rust 工具链，开发者更友好；与 Cherry Studio / ChatBox 同栈 |
| 构建工具 | Vite 6 + vite-plugin-electron | 极速 HMR，主/preload/renderer 一体化构建 |
| UI 框架 | React 18 + TypeScript | 生态丰富，shadcn/ui 原生支持 |
| 样式 | Tailwind CSS 3 + shadcn/ui | 原子化 CSS + 可定制组件库 |
| 状态管理 | Zustand 5 | 轻量、无 boilerplate、支持 selector |
| Markdown | react-markdown + remark-gfm + rehype-highlight | GFM 语法 + 代码高亮 |
| 持久化 | electron-store (主进程) + localStorage fallback | 跨平台、支持 Electron 沙盒 |
| 打包 | electron-builder 25 | 跨平台安装程序（NSIS/DMG/AppImage/deb） |

## 📋 与现有 frontend/desktop 的差异

| 维度 | `frontend/desktop`（VTuber 客户端） | `frontend/client`（本客户端） |
|---|---|---|
| 定位 | Live2D 虚拟形象 + 聊天 | 纯聊天，参考 Cherry Studio |
| 框架 | Vue 3 + Element Plus + Tauri 2 | React 18 + shadcn/ui + Electron |
| 多会话 | ❌ 单会话 | ✅ 多会话 + 搜索 + 置顶 |
| Markdown | ❌ 纯文本 | ✅ GFM + 代码高亮 |
| 工具调用展示 | ❌ | ✅ 可折叠卡片 |
| AgentEvent 协议 | ❌ | ✅ 全部事件类型 |
| 整体打包 | 需 Rust 工具链 | 无需 Rust，npm 一键打包 |
| Live2D 头像 | ✅ | ❌（未来可作为可选模块） |

## 📄 许可证

MIT
