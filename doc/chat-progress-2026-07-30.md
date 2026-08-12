# HakusAI 迭代聊天记录与进度计划

记录时间：2026-07-30 20:50:58 +08:00

## 背景

本轮讨论从 Benchmark 与三种 Agent 模式开始，逐步推进到桌面端产品化与 UI 工程化。核心目标是把 HakusAI 从“能跑的实验项目”推进到“真正可用、可测、可维护的桌面 Agent 产品”。

用户明确希望：

- Benchmark 不要只做“看起来能跑”的假测试，而是接近严格 SWE 测试。
- Swift、Deep、Fleet 三种模式需要真实可用，尤其 Swift 是产品主力，需要立刻打磨。
- Deep 是质量档，但当前流程太重，需要减肥。
- Fleet 是新模式，需要纳入评估和工程化。
- 前端桌面端需要完善为类似 Codex/macOS 的清爽高级风格。
- Windows 桌面端仍然保留 Windows 的最小化、最大化、关闭逻辑，不做 macOS 红绿灯。
- 输入框需要浮空、圆角、自适应高度，支持图片粘贴、多模态发送、消息队列、任务清单实时显示。
- 新增语音通话能力，暂时复用 `D:\项目\Celia` 的实现测试。
- 设置中把“语音 TTS”改为“语音通话与播报”，支持语音通话配置与任务播报配置。

## 模式判断

### Swift

定位：产品主力模式。

判断：值得优先打磨。Swift 应该承担默认日常任务、前端交互、快速修复、轻量工程任务。它的关键不是把流程堆满，而是把决策路径变短、反馈更快、可中断、可继续。

已推进方向：

- 减少不必要的重型流程。
- 强化快速执行与轻量验证。
- 让 Swift 成为默认可用体验，而不是 Benchmark 里的演示模式。

### Deep

定位：质量档、复杂任务档。

判断：方向对，但当前容易被流程拖死。Deep 不应该等于“无限思考和无限工具调用”，而应该是“更强的诊断、更严格的验证、更好的分阶段收敛”。

已推进方向：

- 给 Deep 减肥，降低流程阻尼。
- 让 Deep 更适合复杂修复、跨模块任务、严肃 Benchmark。
- 避免为了显得深而牺牲可交付速度。

### Fleet

定位：并行协作、多 Agent 工程模式。

判断：概念有潜力，但只有在任务拆分、状态汇总、冲突控制、结果验证都工程化后才真正有价值。否则 Fleet 很容易变成多个 Agent 一起制造噪声。

已推进方向：

- 纳入模式测试。
- 开始引入工程化文件与测试覆盖。
- 后续需要重点补齐调度、汇总、冲突解决和失败恢复。

## 已完成的主要改动

### Benchmark 与后端工程化

相关文件包括：

- `benchmark_swe.py`
- `hakus/modes.py`
- `hakus/fleet/`
- `tests/test_run_modes.py`
- `tests/test_deep_mode_budget.py`
- `tests/test_fleet_mode.py`
- `src/hakusai_server/server.py`
- `src/hakusai_server/agent_bridge.py`

已推进内容：

- 增加更接近 SWE 风格的测试入口。
- 引入或调整 Swift、Deep、Fleet 模式相关逻辑。
- 给三种模式补充测试文件。
- 对 `hakusai_server.server` 跑 Benchmark 的真实性提出质疑，并开始往严格任务验证方向改。

### Electron 桌面端修复

相关文件：

- `frontend/client/package.json`
- `frontend/client/vite.config.ts`
- `frontend/client/electron/main.ts`
- `frontend/client/electron/preload.ts`
- `frontend/client/electron/sidecar.ts`
- `frontend/client/src/components/layout/TopBar.tsx`
- `frontend/client/src/index.css`

已完成：

- 修复桌面端黑屏问题。
- `dev:electron` 改为使用 `vite --mode electron`。
- Electron 插件只在 build 或 electron mode 下启用，避免普通浏览器开发模式被 Electron 插件干扰。
- sidecar 在开发模式下提前输出 `HAKUSAI_PORT`，避免后端重 import 导致前端拿不到端口。
- renderer URL 增加 `http://127.0.0.1:1421/` fallback。
- 增加窗口控制 IPC。
- preload 暴露窗口控制 API。
- Windows 下顶部显示最小化、最大化、关闭按钮。
- 顶栏拖拽区域加大，`--titlebar-height` 调整到 `3rem`。

### 前端 UI 与输入框

相关文件：

- `frontend/client/src/components/chat/Composer.tsx`
- `frontend/client/src/components/chat/ChatView.tsx`
- `frontend/client/src/components/chat/MessageBubble.tsx`
- `frontend/client/src/components/chat/ToolCallStack.tsx`
- `frontend/client/src/components/layout/BottomStatusBar.tsx`
- `frontend/client/src/components/sidebar/Sidebar.tsx`
- `frontend/client/src/index.css`

已完成：

- 输入框改为更浮空、更圆角的样式。
- 模型选择、模式选择、权限选择从复杂顶栏下沉到输入框区域。
- 输入框支持更扁的默认态，并随文本行数自适应高度，超过限制后滚动。
- 支持图片粘贴和图片预览。
- 支持多模态模型图片发送约束。
- 支持正在执行时继续输入，形成消息发送队列。
- 支持在输入框附近显示任务清单或任务进度。
- 整体风格开始朝 Codex/macOS 的轻量玻璃感、圆角、浮层方向调整。

### 语音通话与播报

相关文件：

- `frontend/client/electron/main.ts`
- `frontend/client/electron/preload.ts`
- `frontend/client/src/vite-env.d.ts`
- `frontend/client/src/api/types.ts`
- `frontend/client/src/store/settings.ts`
- `frontend/client/src/components/settings/SettingsDialog.tsx`
- `frontend/client/src/components/settings/panels/TtsPanel.tsx`
- `frontend/client/src/components/chat/Composer.tsx`
- `frontend/client/src/components/chat/ChatView.tsx`
- `frontend/client/src/lib/voiceNotifications.ts`

已完成：

- 设置项从“语音 TTS”改为“语音通话与播报”。
- 新增语音通话配置：
  - 是否启用语音通话。
  - Celia 路径。
  - Celia 配置文件路径。
  - Python 命令。
  - 是否在终端打开。
- Electron 主进程新增 Celia 进程控制 IPC：
  - `voice:status`
  - `voice:startCelia`
  - `voice:stopCelia`
- preload 暴露 `window.electron.voice`。
- 输入框发送按钮旁边加入语音通话按钮。
- Settings 中加入启动/停止 Celia 的测试按钮。
- 新增播报配置：
  - 默认关闭。
  - 可选 TTS 播报。
  - 可选“咚咚”提示音。
  - 可预览提示音。
- 新增 `voiceNotifications.ts`：
  - 任务完成时可播报。
  - 需要提问人类时可播报。
  - TTS 模式调用现有 TTS API。
  - 提示音模式使用 Web Audio 生成，不依赖外部音频资产。

## 当前验证情况

已通过：

- `frontend/client` 下执行过 `npm run build`，构建通过。
- 桌面端开发服务曾成功启动。
- sidecar 健康检查曾返回 healthy。
- gateway 曾运行在 `23980`。

仍需继续验证：

- Electron 主进程和 preload 改动后，需要重启桌面端才能生效，热更新不可靠。
- Windows 最小化、最大化、关闭按钮需要在真实桌面窗口中再次确认。
- 顶栏拖拽区域是否足够大，需要实际拖动窗口验证。
- 语音通话按钮是否能正常启动 Celia，需要确认本机 `D:\项目\Celia` 路径和 Python 环境。
- 播报在“权限请求”场景下还没有独立事件，只能先覆盖 `question_asked` 类事件。

## 已知问题

1. 语音通话当前只是启动 Celia 的独立 voice 进程，还没有真正接入 HakusAI 当前聊天会话。
2. 权限请求播报缺少明确前端事件，需要后端或事件协议补充。
3. Electron 桌面端窗口控制曾多次出现按钮不可见或不可点击，需要最终回归验证。
4. UI 已经开始接近 Apple/Codex 风格，但还没有完成系统性设计统一。
5. 代码中存在大量未提交改动和新增文件，需要后续整理成清晰 commit。
6. 部分历史中文文本可能存在乱码，需要单独清理。

## 下一步计划

### P0：桌面端可用性闭环

- 重启 Electron 桌面端。
- 验证窗口可拖拽、可最小化、可最大化、可关闭。
- 验证黑屏不复现。
- 验证主进程、preload、renderer 的开发模式切换稳定。

### P1：输入框与任务体验

- 继续打磨浮空输入框尺寸、圆角、阴影、间距。
- 检查无图片、单行文字、多行文字、粘贴图片、长队列等状态。
- 确保消息队列和任务清单显示不会挤压或遮挡输入区域。
- 把模型、模式、权限选择做成更像 Codex 的紧凑控件。

### P2：语音通话集成

- 先保证一键启动和停止 Celia 稳定。
- 增加错误信息展示，避免用户只看到“没反应”。
- 后续把 Celia 的 ASR 文本桥接进 HakusAI 当前会话。
- 把 HakusAI 助手回复接入 TTS 播放，形成真正“和当前 Agent 打电话”。
- 再决定是否保留独立 Celia 进程，或将 Celia 能力抽成 HakusAI 内部 voice service。

### P3：播报事件工程化

- 明确事件类型：
  - `task_completed`
  - `permission_requested`
  - `human_input_requested`
  - `error_blocked`
- 前后端统一事件协议。
- 设置中支持不同事件的不同声音策略。
- 默认关闭，避免打扰用户。

### P4：三种模式工程化

- Swift：
  - 保持默认主力。
  - 优先优化速度、成功率、可恢复性。
- Deep：
  - 保留质量优势。
  - 控制预算、工具调用和流程长度。
- Fleet：
  - 强化任务拆分、并发调度、状态汇总、冲突处理。
  - 只有在能稳定提升复杂任务完成率后才默认开放。

### P5：Benchmark 真实化

- 使用更严格 SWE 风格任务。
- 每个任务需要有明确 patch、测试、评分标准。
- Benchmark 不只看“有没有输出”，而要看：
  - 是否真正修改正确文件。
  - 是否通过测试。
  - 是否避免破坏无关代码。
  - 是否能从失败中恢复。
  - 是否能给出可审计日志。

## 对项目的锐评

HakusAI 的方向是有野心的，而且已经不是一个普通聊天壳子。它在尝试把 Agent 模式、桌面端、工具执行、任务板、语音、Benchmark 都揉成一个真实工作台。

但问题也很明显：现在的复杂度已经超过“靠感觉继续堆功能”的阶段了。继续往前走，关键不是再加更多模式，而是把每个模式的边界、事件协议、验证方式、UI 状态机和失败恢复做扎实。

最值得立刻打磨的是 Swift 和桌面端体验。Swift 决定用户每天愿不愿意打开它；桌面端决定用户会不会觉得这是一个真正的产品。Deep 和 Fleet 可以很强，但它们必须被工程纪律驯服，否则会变成成本很高的演示功能。

一句话：这个项目有产品气质，也有系统野心，但现在最缺的是“收敛”。把默认路径做顺，把真实测试做硬，把 UI 做得轻而稳，它就会开始像一个真正能长期使用的 AI 工作台。

