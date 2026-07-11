# Build & Package Guide

完整的构建 / 打包指南，覆盖三种场景：

1. **开发调试** — Vite dev server + Electron 主进程
2. **前端生产构建** — Vite build 输出静态资源
3. **完整打包** — electron-builder 输出安装程序（含可选 Python sidecar）

---

## 📋 环境要求

| 工具 | 版本 | 用途 |
|---|---|---|
| Node.js | ≥ 18 (推荐 20+) | 前端 + Electron 构建 |
| npm | ≥ 9 | 包管理 |
| Python | ≥ 3.10 | 仅 sidecar 打包需要 |
| PyInstaller | ≥ 6.0 | 仅 sidecar 打包需要 |

可选（如需 Tauri 路线）：Rust + Cargo。**本客户端不依赖 Rust。**

---

## 1️⃣ 开发调试

### 仅前端（浏览器）

```bash
cd frontend/client
npm install
npm run dev
# 浏览器访问 http://localhost:1421
# 注意: 此时 electron API 不可用, 设置会回落到 localStorage
```

### Electron + 前端（推荐）

```bash
npm run dev:electron
# 等价于:
#   concurrently -k "vite" "wait-on tcp:1421 && electron ."
```

Vite 启动后，Electron 主进程会自动启动并加载 `http://localhost:1421`。代码改动会触发热重载。

> 💡 **首次启动需要 HakusAI 后端在运行**：
> ```bash
> # 在 HakusAgent 仓库根目录
> python -m hakusai_server.server
> # 或 python run.py
> ```
> 默认监听 `http://localhost:8080`。如果端口被占用，server 会自动尝试 +1。

---

## 2️⃣ 前端生产构建

```bash
npm run build:electron
```

输出：

```
dist/                      # 前端静态资源 (HTML/CSS/JS)
├── index.html
└── assets/
    ├── index-XXXX.css
    └── index-XXXX.js

dist-electron/             # Electron 主进程产物
├── main.js                # 主进程入口
└── preload.js             # 预加载脚本 (contextBridge)
```

验证构建结果（不开 Electron 窗口）：

```bash
npm run preview            # 仅预览前端 (浏览器)
```

---

## 3️⃣ 完整打包（分发安装程序）

### 3.1 不带 Python sidecar（推荐用于快速分发）

客户端启动后，用户需自行启动 HakusAI 后端（或连接远程服务器）。

```bash
# 当前平台
npm run dist

# 指定平台
npm run dist:win           # Windows NSIS (.exe)
npm run dist:mac           # macOS DMG (.dmg) — 需在 macOS 上构建
npm run dist:linux         # Linux AppImage + .deb
```

产物在 `frontend/client/release/`：

| 平台 | 产物 | 大小（预估） |
|---|---|---|
| Windows | `HakusAI-Setup-0.1.0.exe` | ~85 MB |
| macOS | `HakusAI-0.1.0.dmg`, `HakusAI-0.1.0-arm64.dmg` | ~95 MB |
| Linux | `HakusAI-0.1.0.AppImage`, `HakusAI-0.1.0.deb` | ~90 MB |

### 3.2 带 Python sidecar（整体打包，开箱即用）

#### 步骤 A：构建 sidecar

```bash
# 在 HakusAgent 仓库根目录安装 Python 依赖
pip install -r requirements.txt
pip install pyinstaller

# 构建 sidecar
cd frontend/client
bash scripts/build-sidecar.sh
```

构建成功后，`frontend/client/sidecar/dist/` 下会出现 `hakusai-server`（或 `.exe`）。

> ⚠️ **跨平台限制**：PyInstaller 不能交叉编译。要打 Windows 包就在 Windows 上跑；要打 macOS 包就在 macOS 上跑。

#### 步骤 B：打包 Electron 应用

```bash
npm run dist
```

`electron-builder` 会通过 `package.json` 中的 `extraResources` 字段把 `sidecar/` 整个目录拷贝到最终安装包的 `Resources/sidecar/` 下。

#### 步骤 C：验证

打包后启动应用，主进程日志会打印：

```
[main] Bundled sidecar detected — starting...
[sidecar] HAKUSAI_PORT=8080
[main] Sidecar URL: http://127.0.0.1:8080
```

客户端会自动把服务器 URL 设为 `http://127.0.0.1:8080` 并发起健康检查。

---

## 4️⃣ 跨平台构建矩阵

| 目标平台 | 构建宿主 | 命令 | 备注 |
|---|---|---|---|
| Windows x64 | Windows | `npm run dist:win` | 输出 NSIS 安装程序 |
| macOS x64 | macOS (Intel) | `npm run dist:mac` | 输出 .dmg |
| macOS arm64 | macOS (Apple Silicon) | `npm run dist:mac` | 同上，自动 arm64 |
| Linux x64 | Linux | `npm run dist:linux` | AppImage + .deb |

> electron-builder 支持在 macOS 上交叉编译 Windows 包（需要 Wine），但建议在目标平台原生构建以保证稳定性。

### GitHub Actions 自动构建

参考以下 workflow（保存到 `.github/workflows/release.yml`）：

```yaml
name: Release

on:
  push:
    tags: ['v*']

jobs:
  build:
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 20
      - run: cd frontend/client && npm ci
      - run: cd frontend/client && npm run dist
      - uses: actions/upload-artifact@v4
        with:
          name: hakusai-${{ matrix.os }}
          path: frontend/client/release/*
```

---

## 5️⃣ 常见问题

### Q: 构建时提示 `Cannot find module 'electron'`

A: Electron 是 dev dependency，确保 `npm install` 没有加 `--production`。

### Q: macOS 上打包报错 `xcrun: error: invalid active developer path`

A: 安装 Xcode Command Line Tools：`xcode-select --install`

### Q: Windows 上 Defender 把 .exe 标记为病毒

A: 这是 electron-builder 默认 NSIS 模式的常见误报。解决方法：
1. 给 exe 签名（需要代码签名证书）
2. 或在 `package.json` 的 `build.nsis` 中改用 `oneClick: true`（_portable 模式）

### Q: sidecar 启动失败，日志显示 `ModuleNotFoundError: No module named 'hakusai_core'`

A: PyInstaller spec 的 `datas` 和 `hidden_imports` 可能不完整。检查 `sidecar/hakusai_server.spec` 是否包含所有需要的模块。运行 sidecar 时加 `--debug` 可以看到 import 错误。

### Q: 客户端连不上后端

A: 检查清单：
1. 后端是否在运行？`curl http://localhost:8080/health` 应返回 `{"status":"healthy",...}`
2. 客户端设置中的服务器 URL 是否正确？
3. CORS 是否允许？后端 `config.yaml` 中 `server.cors_origins` 应包含 `["*"]` 或具体来源。
4. 防火墙是否拦截端口？

### Q: 想换图标

A: 替换 `build-resources/icon.png`（建议 512×512 PNG），重新 `npm run dist`。electron-builder 会自动生成各平台所需尺寸。

或者用脚本重新生成：
```bash
python3 scripts/make-icon.py
```

---

## 6️⃣ 开发工作流建议

```
1. 修改代码
2. npm run dev:electron  # 实时预览
3. npx tsc --noEmit      # 类型检查
4. npm run build:electron # 完整构建验证
5. git commit & push
6. CI 跑 dist:* 产出安装包
```
