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

如需调试旧 WebUI/兼容接口，可单独启动 Python 服务：

```powershell
python -m hakusai_server.server
```

默认监听 `127.0.0.1:48081`。Tauri 桌面端和 Android 不再启动此服务，而是在进程内运行
Rust Runtime；只有旧 WebUI 或兼容回归需要 Python 环境。

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

当前发布约束：Tauri 桌面端和 Android 均在进程内启动 Rust Runtime，不再依赖 Python
sidecar。生成安装包后应验证 Rust Runtime 的 `/v1/health`、配置目录和资源定位。

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

## 6. CI 与发布（build-all）

安装包构建只走 `.github/workflows/build-all.yml`：

- 触发：`workflow_dispatch` 手动触发，或推送 `v*` tag。
- 产物全部上传为 Actions Artifacts，不自动发 Release：桌面端 Windows
  NSIS/MSI、macOS DMG（x64/arm64）、Linux deb/AppImage、Android APK
  （arm64/x86_64），以及四端七 target 的 `hakuscli`。
- 验证修复是否真的进包，以 build-all 的最新 green run 对应的 commit 为准。

历史教训（重复踩过的坑，写死为纪律）：

1. **Tauri 插件版本必须对齐**。npm 端 `@tauri-apps/plugin-*` 与 Rust 端
   `tauri-plugin-*` crate 的 minor 版本不一致时，Tauri CLI 会在编译前直接报
   "version mismatched Tauri packages" 退出（build-all #36 即因此 6 个 job 全灭：
   updater npm 2.10.1 vs crate 2.11.0）。升级任何一侧时必须同步另一侧，并把
   `package-lock.json` 与 `Cargo.lock` 的变更一起提交。
2. **macOS 透明/圆角窗口需要私有 API**。`tauri.conf.json` 开启透明窗口后，
   `Cargo.toml` 中 tauri 必须带 `macos-private-api` feature，同时
   `macOSPrivateApi: true`；否则 macOS 构建报 E0599（build-all #37）。
3. **不要重建旁路检查工作流**。轻量 ci-check 类工作流验证不了真实产物，曾造成
   "检查通过但安装包不含修复"的误判；该工作流已删除，不要为省时间再引入。

## 7. 常见修改入口

| 需求 | 首选位置 |
| --- | --- |
| 桌面设置页 | `desktop-tauri/src/components/settings/` |
| 首启初始化向导 | `desktop-tauri/src/components/FirstRunSetup.tsx` |
| 启动 Splash（时间轴/光斑动画） | `desktop-tauri/public/splash.html` + `src-tauri/src/lib.rs` 窗口创建 |
| 弹窗/浮层（Dialog、Dropdown、Tooltip） | `desktop-tauri/src/components/ui/`（Radix 原生 portal） |
| 单实例锁与托盘 | `desktop-tauri/src-tauri/src/lib.rs`（`tauri-plugin-single-instance`） |
| 聊天输入和 `@` 菜单 | `desktop-tauri/src/components/chat/Composer.tsx` |
| 桌面 API 类型/请求 | `desktop-tauri/src/api/types.ts`、`client.ts` |
| Rust Runtime API | `frontend/terminal/crates/tui/src/runtime_api.rs` |
| 旧 Python 兼容 API | `src/hakusai_server/`（不参与 Tauri 发布包） |
| Rust TUI | `frontend/terminal/crates/tui/src/tui/` |
| Skills 生命周期 | Python `skills.py`；Rust `crates/tui/src/skills/` |

## 8. 变更纪律

- API 增加或响应形状改变时，更新 Rust Runtime API 版本和桌面
  `EXPECTED_BACKEND_API_VERSION_INT`。
- 桌面共享组件必须同时检查窄屏/触摸布局；Android 使用同一份 React UI。
- 新功能优先接入 Tauri 主界面，不要默认修改 `webui/` 或 `editor/`。
- 用户数据写入 `~/.hakus/` 或项目 `.hakus/`，不要写入源码资源目录。
- 第三方 Skill、模型和大型资产不应作为仓库默认内容提交。
- 修复直接提交 master，不长期挂 `fix/**` 分支；不另建旁路检查工作流，安装包验证以
  `build-all` 为准。
- 不要把一次性调试脚本、AI 会话状态文件（`.task_board.json` 等）提交进仓库。
