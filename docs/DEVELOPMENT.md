# HakusAgent 开发指南

## 1. 环境要求

| 组件 | 最低要求 |
| --- | --- |
| Python | 3.11+ |
| Node.js | 20+，并带 npm |
| Rust | 1.88+，stable toolchain |
| 桌面壳 | Tauri 2 对应平台依赖 |

Windows 开发 Tauri 还需要 Microsoft C++ Build Tools 和 WebView2；Linux/macOS 需要
Tauri 官方列出的系统库。

## 2. Python 环境

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[server,dev]"
```

macOS/Linux：

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[server,dev]'
```

准备 `config.yaml`，或从 `config.example.yaml` 复制后配置 Provider。不要提交真实 API Key。

单独启动 Python 后台：

```powershell
python -m hakusai_server.server
```

默认监听 `127.0.0.1:48081`。桌面 Tauri 在非 Android 平台也会尝试自动启动该命令，因此
它使用的 `python` 必须能导入当前项目。

## 3. 桌面端

```powershell
cd HakusAgent/frontend/desktop-tauri
npm ci
npm run tauri:dev
```

只调 React UI、并且后台已经单独运行时：

```powershell
npm run dev
```

生产前端构建：

```powershell
npm run build
```

桌面安装包构建：

```powershell
npm run tauri:build
```

当前发布约束：Tauri 配置没有打包 Python sidecar。生成安装包成功不代表目标机器无需 Python
即可启动 Agent 后台。修改发布流程时需要同时验证 Python 模块、模型依赖和资源定位。

## 4. Rust HakusCLI

```powershell
cd frontend/terminal
cargo build --release --bin hakuscli
cargo test -p hakus-tui
```

开发运行：

```powershell
cargo run -p hakus-cli --bin hakuscli
```

Rust 专项配置和测试见 `frontend/terminal/docs/`。

## 5. 测试与检查

Python Skills 快速测试：

```powershell
python -m pytest tests/test_desktop_skills.py -q
```

Python 全量测试：

```powershell
python -m pytest
```

桌面 TypeScript 与打包检查：

```powershell
cd HakusAgent/frontend/desktop-tauri
npm run build
npx vitest run
```

Rust 变更至少运行受影响 crate 的测试；共享 Runtime/API 改动应运行：

```powershell
cd frontend/terminal
cargo test -p hakus-tui
cargo test -p hakus-cli
```

## 6. 常见修改入口

| 需求 | 首选位置 |
| --- | --- |
| 桌面设置页 | `desktop-tauri/src/components/settings/` |
| 聊天输入和 `@` 菜单 | `desktop-tauri/src/components/chat/Composer.tsx` |
| 桌面 API 类型/请求 | `desktop-tauri/src/api/types.ts`、`client.ts` |
| Python REST/SSE | `src/hakusai_server/server.py` |
| Python AgentCore 适配 | `src/hakusai_server/agent_bridge.py` |
| Python 工具/权限/模型 | `hakus/` |
| Rust Runtime API | `frontend/terminal/crates/tui/src/runtime_api.rs` |
| Rust TUI | `frontend/terminal/crates/tui/src/tui/` |
| Skills 生命周期 | Python `skills.py`；Rust `crates/tui/src/skills/` |

## 7. 变更纪律

- API 增加或响应形状改变时，同步更新 Python sidecar 版本和桌面
  `EXPECTED_BACKEND_API_VERSION_INT`。
- 桌面共享组件必须同时检查窄屏/触摸布局；Android 使用同一份 React UI。
- 新功能优先接入 Tauri 主界面，不要默认修改 `webui/` 或 `editor/`。
- 用户数据写入 `~/.hakus/` 或项目 `.hakus/`，不要写入源码资源目录。
- 第三方 Skill、模型和大型资产不应作为仓库默认内容提交。
