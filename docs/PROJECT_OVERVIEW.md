# HakusAgent 使用总览

> 本文是 HakusAgent 项目文档入口。
>
> 文档目标：说明产品由哪些运行形态组成、各端如何使用、平台之间有什么区别，以及应该到哪一份用户文档继续阅读。
>
> 本文只描述当前仓库中已经存在的实现。实验性功能和待补齐的文档会明确标注，不把规划内容写成已完成能力。

## 1. 项目定位

HakusAgent 是一个多端 AI Agent 平台，用户可以根据使用场景选择以下产品形态：

1. **HakusAI 桌面端**：适合日常使用，提供图形界面、项目管理、聊天、设置、托盘和桌面集成。
2. **HakusCLI**：适合终端用户、自动化任务、服务器和开发板环境，提供交互式终端和命令行执行能力。
3. **桌面端后台服务**：桌面端运行所需的本地后台组件，用户通常不需要单独启动或管理。

桌面端和 HakusCLI 是两个独立的使用入口。可以按需安装其中一个，也可以同时使用。

## 2. 组件关系

```text
用户
 ├─ HakusAI 桌面端
 │   ├─ 图形界面
 │   ├─ 项目、聊天和设置
 │   └─ 本地后台服务
 │       ├─ 模型请求
 │       ├─ 工具与 MCP
 │       ├─ 用户安装的 Skills
 │       ├─ 语音与扩展能力
 │       └─ 本地数据
 │
 └─ HakusCLI
     ├─ 交互式终端
     ├─ 非交互命令
     ├─ 文件、Shell、Git 和任务能力
     ├─ MCP、工作流和扩展能力
     └─ 会话、配置和本地数据
```

两个入口的关系：

- 桌面端启动时会自动启动自己的本地后台服务。
- 桌面端可在 **设置 > Skills** 安装、启停和删除 Skills，并在聊天输入框的 `@` 菜单中调用已启用项。
- HakusCLI 可以独立运行，不需要打开桌面端。
- 两者的安装包、启动方式和部分数据位置不同，不能混用安装说明。

## 3. 选择哪个版本

| 产品部分 | 用户能接触到的形态 | 主要用途 |
|---|---|---|
| HakusAI 桌面端 | Windows、macOS、Linux 桌面应用 | 图形界面、项目管理、聊天、设置、托盘和桌面集成 |
| HakusCLI | Windows、macOS、Linux、Android Termux 命令行程序 | 交互式终端使用、自动化执行和服务器/开发板环境 |
| 桌面端后台服务 | 随桌面端自动运行 | 为桌面端提供模型请求、工具、MCP、语音和扩展能力 |

如果主要在 Windows、macOS 或 Linux 桌面上使用，优先选择 HakusAI 桌面端。如果需要 SSH、服务器、Termux、脚本或自动化任务，选择 HakusCLI。

## 4. 产品形态与支持矩阵

### 4.1 桌面端

桌面端产品名为 `HakusAI`。

| 平台 | 可下载的安装形式 |
|---|---|---|
| Windows | 安装程序、MSI |
| macOS Apple Silicon | DMG、应用程序 |
| macOS Intel | DMG、应用程序 |
| Linux | deb、AppImage |
| Android | APK（arm64 真机 / x86_64 模拟器） |

Linux 的 AppImage 只适用于 HakusAI 桌面端。桌面端与 Android 端首次启动都会进入初始化设置向导（选择模型供应商、配置 API Key），配置完成后才能正常对话。

### 4.2 HakusCLI

HakusCLI 的程序名为 `hakuscli`。Linux 和 macOS 下载后通常是没有扩展名的可执行文件，Windows 下载后是 `.exe` 文件。

| 平台 | 程序形式 |
|---|---|---|
| Linux x64 / ARM64 | 直接运行的程序文件 |
| macOS Apple Silicon / Intel | 直接运行的程序文件 |
| Windows x64 / ARM64 | `.exe` 程序文件 |
| Android / Termux ARM64 | tar.gz 压缩包中的直接运行程序 |

Linux ARM64 版本不是 AppImage，适用于 64 位 Ubuntu、Debian、服务器和开发板系统。Termux 必须使用 Android 专用版本，不能使用 Linux ARM64 版本。

### 4.3 压缩包说明

Android / Termux 压缩包解压后应直接得到 `hakuscli` 文件。若从 GitHub Actions 下载，GitHub 可能会在外面再包一层 Artifact 压缩包，这是下载平台的封装，不是程序本身的目录结构。

## 5. 数据位置

HakusCLI 的数据位置遵循以下规则：

1. 设置了绝对路径 `HAKUS_HOME` 时，使用该路径。
2. `HAKUS_INSTALL_MODE=installed` 时，使用用户 HOME 下的 `.hakus/`。
3. 便携模式优先使用 `HAKUS_DATA_DIR` 或当前工作目录，再使用 `.hakus/`。

因此：

- 免安装版本可以把程序和 `.hakus/` 放在同一目录，便于整体复制和删除。
- 安装版本可以把程序放在系统路径，把数据放在用户 HOME 下的 `.hakus/`。
- `HAKUS_HOME` 可以把数据和程序完全分离到指定目录。
- 当前 Rust 路径实现不再通过旧 `~/.deepseek/` home API 进行运行时回退。

配置文件、凭据、会话、日志和缓存的具体位置见 [CLI 安装与配置文档](../frontend/terminal/docs/INSTALL.md) 和 [配置参考](../frontend/terminal/docs/CONFIGURATION.md)。

## 6. 用户文档导航

### 用户文档

| 主题 | 文档 |
|---|---|
| 安装、运行和数据位置 | [INSTALL.md](../frontend/terminal/docs/INSTALL.md) |
| Android / Termux | [TERMUX.md](../frontend/terminal/docs/TERMUX.md) |
| 配置和环境变量 | [CONFIGURATION.md](../frontend/terminal/docs/CONFIGURATION.md) |
| 模型和 provider | [PROVIDERS.md](../frontend/terminal/docs/PROVIDERS.md) |
| TUI 快捷键 | [KEYBINDINGS.md](../frontend/terminal/docs/KEYBINDINGS.md) |
| 运行模式 | [MODES.md](../frontend/terminal/docs/MODES.md) |
| MCP 外部工具服务器 | [MCP.md](../frontend/terminal/docs/MCP.md) |
| 桌面端 Skills 管理与 `@` 调用 | [SKILLS.md](SKILLS.md) |
| CLI Skills 和插件 | [SKILLS.md](../frontend/terminal/docs/SKILLS.md)、[PLUGINS.md](../frontend/terminal/docs/PLUGINS.md) |
| 沙箱和授权 | [SANDBOX.md](../frontend/terminal/docs/SANDBOX.md) |

后续用户专题文档将补齐以下目前缺少统一说明的内容：卸载数据清理细节、桌面端后台服务、微信 ClawBot 配置、跨平台故障排查和数据管理。

## 7. 文档状态

本文是第一份面向普通用户的使用总览，不包含开发、构建和源码维护说明。后续用户专题文档会继续核对现有说明，修正过时的平台、安装、数据路径和功能状态描述。
