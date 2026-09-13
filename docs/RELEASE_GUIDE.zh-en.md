# HakusAI 使用教程 / User Guide

> 本说明随 **Beta（测试版）** Release 发布。构建信息见下方「构建信息 / Build info」。

---

## 构建信息 / Build info

| 项目 / Item | 说明 / Value |
| --- | --- |
| 版本 / Version | 见 Release 标题与资产文件名 |
| 渠道 / Channel | **Beta（预发布 / prerelease）** |
| 基于 / Based on | 仓库默认分支提交（commit SHA 见 Release Notes 顶部） |
| 构建来源 / Built from | GitHub Actions `build-all` / `release-beta` |
| 平台 / Platforms | Windows x64（安装器 + 应用）、macOS、Linux（视资产而定） |

> 正式版更新通道不会自动安装 Beta。测试请手动下载对应资产。

---

## 中文教程

### 1. 下载

1. 打开 GitHub Releases 页面，选择 **最新 Beta**。
2. Windows 用户优先下载：
   - `HakusAI-Installer-*-windows-x64.exe`（推荐，品牌安装向导）
   - 或 `HakusAI-*-windows-x64-setup.exe`（传统 NSIS，适合静默/企业安装）
3. macOS / Linux 用户下载对应 `.dmg` / `.AppImage` / `.deb`。

### 2. 安装（Windows 独立安装器）

1. 双击安装器，选择语言（简体中文 / English）。
2. 阅读并接受许可协议。
3. 选择安装目录（默认：`%LOCALAPPDATA%\Programs\HakusAI`）。
4. 勾选组件：
   - 桌面快捷方式
   - 开始菜单快捷方式
   - 开机启动（可选）
   - 安装完成后启动
5. 若检测到旧版本，可选择是否迁移用户数据（会话、设置、记忆）。
6. 点击 **开始安装**，等待进度完成。

静默安装（NSIS 包）：

```powershell
.\HakusAI-0.3.0-windows-x64-setup.exe /S
```

### 3. 首次启动

1. 启动后会先播放 **全屏启动动画**。
2. 进入 **首次运行向导**，按顺序完成：
   - 语言
   - 模型服务商与 API Key
   - 默认模型
   - 工作区目录
3. API Key 仅保存在本机，卸载时可选择是否删除。

### 4. 日常使用

- **对话**：在主界面输入框发送消息；支持工具调用与日志面板。
- **设置**：侧边栏或快捷键打开设置（模型、语音、技能、MCP、外观等）。
- **模型切换**：设置 → 模型，填写对应服务商密钥后即可切换。
- **更新**：设置 → 关于，检查更新（仅正式 v* 版自动更新）。

### 5. 卸载

- **安装器安装的版本**：开始菜单 →「卸载 HakusAI」，或控制面板卸载；可选择是否删除用户数据。
- **NSIS 安装的版本**：系统「应用和功能」卸载，同样会询问是否删除本机数据。

### 6. 故障排查

| 现象 | 处理 |
| --- | --- |
| 打开设置崩溃 / React #300 | 升级到本 Beta 或之后版本（已修复 Model 面板 hooks） |
| 找不到 `app-payload.zip` | 使用完整安装器资产；勿单独改名/拆包 |
| 启动黑屏 | 等待启动动画结束；仍异常则删除本地配置后重装 |
| 更新失败 | Beta 不走自动更新，请手动下载最新 Release |

---

## English guide

### 1. Download

1. Open GitHub Releases and pick the **latest Beta**.
2. On Windows prefer:
   - `HakusAI-Installer-*-windows-x64.exe` (branded wizard — recommended)
   - or `HakusAI-*-windows-x64-setup.exe` (classic NSIS, good for silent/enterprise)
3. On macOS / Linux grab the matching `.dmg` / `.AppImage` / `.deb`.

### 2. Install (Windows branded installer)

1. Launch the installer and choose language.
2. Read and accept the license.
3. Pick the install folder (default: `%LOCALAPPDATA%\Programs\HakusAI`).
4. Select components (desktop shortcut, Start menu, optional autostart, launch after install).
5. If a previous install is found, choose whether to keep user data.
6. Click **Install** and wait for progress to finish.

Silent install (NSIS package):

```powershell
.\HakusAI-0.3.0-windows-x64-setup.exe /S
```

### 3. First run

1. A **fullscreen splash animation** plays on launch.
2. Complete the in-app first-run wizard:
   - Language
   - Provider + API key
   - Default model
   - Workspace folder
3. Keys stay on your machine; you can wipe them on uninstall.

### 4. Daily use

- Chat from the main composer; open logs/tools from the side panels.
- Settings covers models, voice, skills, MCP, appearance, tray, and about/update.
- Check for updates under Settings → About (stable `v*` releases only).

### 5. Uninstall

- Branded installer builds: Start menu → “Uninstall HakusAI” (asks about user data).
- NSIS builds: Windows “Apps & features”.

### 6. Troubleshooting

| Symptom | Fix |
| --- | --- |
| Settings crash / React #300 | Upgrade to this Beta or later |
| `app-payload.zip` missing | Use the full installer asset; do not repack by hand |
| Black window at start | Wait for splash; if stuck, reset local config and reinstall |
| Update failed | Betas are not auto-installed — download manually |

---

## 反馈 / Feedback

请在 GitHub Issues 反馈，并附上：

- 版本号 / commit SHA  
- 操作系统  
- 复现步骤与日志（设置 → 关于 → 诊断）
