# TUI 交互修复 + OpenClaw 风格视觉增强 + Harness 命令修复

## Why
当前 TUI 存在三个严重问题：(1) 斜杠命令弹窗无法用上下键滚动选择（CSS 选择器 bug），(2) `/harness` 命令提示"未知命令"（缺少命令处理器文件），(3) 消息列表区域缺少 OpenClaw 风格的上下边缘渐变淡出效果，视觉体验粗糙。同时，Harness 系统需要按照 Agent Harness Engineering 的最佳实践（Mock 工具、轨迹分析、LLM-as-Judge）进行深度改造。

## What Changes
- 修复斜杠命令弹窗的 CSS 选择器 `--highlight` → `-highlight`，使上下键滚动视觉反馈生效
- 将 `_show_slash_popup` 改为 async 并 await DOM 操作
- 创建 `/harness` 命令处理器文件并注册到命令注册表
- 新增 `FadeOverlay` Widget：在 MessageList 上下边缘渲染渐变淡出遮罩
- 新增 `/harness test` 子命令：使用 Mock 工具运行确定性测试
- 新增 `MockToolRegistry`：Harness 专用的 Mock 工具注册表
- 新增 `HarnessTestCase` / `HarnessSuite`：结构化测试用例定义

## Impact
- Affected specs: TUI 交互、斜杠命令系统、Harness 评估框架
- Affected code:
  - `hakus/tui_v2/widgets/prompt_input.py` — CSS 修复 + async 改造
  - `hakus/tui_v2/widgets/message_list.py` — 添加 FadeOverlay
  - `hakus/tui_v2/commands/harness_cmd.py` — **新建** 命令处理器
  - `hakus/tui_v2/commands/__init__.py` — 注册 HarnessCommand
  - `hakus/harness.py` — 新增 MockToolRegistry、HarnessTestCase、HarnessSuite
  - `hakus/tui_v2/theme.tcss` — FadeOverlay 样式

## ADDED Requirements

### Requirement: 斜杠命令弹窗滚动修复
系统 SHALL 允许用户在斜杠命令弹窗中使用上下键滚动选择命令，且选中项有明显的视觉高亮。

#### Scenario: 上下键滚动选择
- **WHEN** 用户输入 `/` 后弹窗出现，按上/下方向键
- **THEN** 弹窗中的选中项随按键移动，高亮样式（霓虹粉前景 + 深蓝紫背景）清晰可见

#### Scenario: 鼠标点击选择
- **WHEN** 用户点击弹窗中的某个命令项
- **THEN** 该命令被选中并补全到输入框，弹窗关闭，焦点回到输入框

### Requirement: OpenClaw 风格渐变淡出效果
系统 SHALL 在消息列表区域的上下边缘显示渐变淡出遮罩，使文字从完全不透明渐变到背景色，营造深度感。

#### Scenario: 消息列表可滚动时显示渐变
- **WHEN** 消息列表内容超出可视区域（可滚动）
- **THEN** 消息列表顶部和底部各显示 2-3 行高度的渐变遮罩，文字从正常色渐变到背景色 `#0a0a1a`

#### Scenario: 消息列表不可滚动时
- **WHEN** 消息列表内容未超出可视区域
- **THEN** 不显示渐变遮罩

### Requirement: /harness 命令
系统 SHALL 提供 `/harness` 斜杠命令，用于控制 Agent Harness 评估框架。

#### Scenario: 切换 Harness 开关
- **WHEN** 用户输入 `/harness`
- **THEN** 切换 Harness Guard 的启用/禁用状态，显示当前状态

#### Scenario: 查看状态
- **WHEN** 用户输入 `/harness status`
- **THEN** 显示 Harness 当前状态：是否启用、校准因子、循环检测阈值、上下文阈值

#### Scenario: 运行测试
- **WHEN** 用户输入 `/harness test`
- **THEN** 使用内置的 Mock 工具注册表运行一个简单的确定性测试，显示测试结果（工具准确率、循环率、迭代效率）

### Requirement: MockToolRegistry — Harness 专用 Mock 工具
系统 SHALL 提供 `MockToolRegistry`，在 Harness 测试模式下替代真实工具注册表，返回预设的模拟响应，不产生任何真实副作用。

#### Scenario: Mock 工具调用
- **WHEN** Harness 测试模式下 Agent 调用 `read_file` 工具
- **THEN** 返回预设的模拟文件内容，不读取真实文件系统

#### Scenario: Mock 工具故障注入
- **WHEN** 测试用例配置了故障注入（如返回错误）
- **THEN** Mock 工具返回指定的错误响应，用于测试 Agent 的错误恢复能力

### Requirement: HarnessTestCase / HarnessSuite — 结构化测试
系统 SHALL 提供结构化的测试用例定义和执行框架。

#### Scenario: 定义测试用例
- **WHEN** 开发者创建 `HarnessTestCase`
- **THEN** 可以指定：提示词、预期关键词/正则、最大步数、Mock 响应映射、故障注入配置

#### Scenario: 执行测试套件
- **WHEN** 调用 `HarnessSuite.run()`
- **THEN** 依次执行所有测试用例，收集轨迹，计算指标（工具准确率、循环率、迭代效率、任务成功率），生成 `HarnessReport`

## MODIFIED Requirements

### Requirement: HarnessGuard 集成
当前 HarnessGuard 已集成到 agent.py 的工具循环中，但缺少 Mock 工具支持和测试用例框架。修改为：HarnessGuard 在 Harness 测试模式下使用 MockToolRegistry 替代真实工具注册表。

## REMOVED Requirements
无
