# TUI v2 界面重构 — Claude Code 风格布局 + 赛博朋克配色 + 彩色 ASCII 角色

## Why
当前 TUI v2 界面布局较为简单（状态栏 + 消息列表 + 输入框），缺少 Claude Code 风格的欢迎面板、通知栏和底部状态行。用户希望将界面重构成类似 Claude Code 的框式布局，并加入赛博朋克/动漫风格配色和羽汐角色的彩色 ASCII 艺术。

## What Changes
- **欢迎面板重构**：从简单的 Markdown 欢迎文本改为 Claude Code 风格的双栏框式布局（左侧角色 ASCII 艺术 + 模型/目录信息，右侧 Tips + What's new）
- **新增通知栏**：在消息列表和输入框之间添加可关闭的通知横幅（如模型更新提示）
- **输入框样式**：添加 `> ` 前缀标识符，类似 Claude Code 的 prompt 样式
- **底部状态行**：重新设计 Footer，左侧显示快捷键提示，右侧显示 effort 等级
- **配色方案**：从 Catppuccin Mocha 切换为赛博朋克/动漫风格配色（高饱和度霓虹色、深色背景）
- **彩色 ASCII 角色**：将羽汐角色图转换为彩色 ASCII 艺术，用于欢迎面板展示

## Impact
- Affected specs: TUI v2 布局、主题系统
- Affected code:
  - `hakus/tui_v2/app.py` — 欢迎面板逻辑、compose 布局
  - `hakus/tui_v2/theme.tcss` — 全面配色和布局样式
  - `hakus/tui_v2/theme.py` — 颜色常量更新
  - `hakus/tui_v2/widgets/prompt_input.py` — 输入框前缀样式
  - `hakus/tui_v2/widgets/status_bar.py` — 状态栏样式调整
  - `hakus/tui_v2/widgets/welcome_panel.py` — **新建** 欢迎面板组件
  - `hakus/tui_v2/widgets/notification_bar.py` — **新建** 通知栏组件

## ADDED Requirements

### Requirement: 欢迎面板 (Welcome Panel)
系统 SHALL 提供一个 Claude Code 风格的欢迎面板，在应用启动时显示。

#### Scenario: 启动时显示欢迎面板
- **WHEN** 用户启动 HakusAI TUI
- **THEN** 消息列表区域显示一个带边框的面板，包含：
  - 左侧：彩色 ASCII 角色艺术 + "Welcome back!" 标题 + 模型名/目录信息
  - 右侧："Tips for getting started" 和 "What's new" 两个子区域
  - 面板使用圆角边框，配色为赛博朋克风格

### Requirement: 通知栏 (Notification Bar)
系统 SHALL 提供可关闭的通知横幅。

#### Scenario: 显示通知
- **WHEN** 有模型更新或重要通知
- **THEN** 在消息列表底部显示一行通知（如 "Opus 4.8 is now available! · /model to switch"），带左侧竖线标识

### Requirement: 输入框前缀
系统 SHALL 在输入框前显示 `> ` 提示符。

#### Scenario: 输入框样式
- **WHEN** 用户查看输入框
- **THEN** 输入框左侧显示 `> ` 前缀，颜色为主题强调色

### Requirement: 底部状态行
系统 SHALL 重新设计底部状态行。

#### Scenario: 底部状态行布局
- **WHEN** 用户查看界面底部
- **THEN** 左侧显示 "? for shortcuts · ← for agents"，右侧显示 "● high · /effort"

### Requirement: 彩色 ASCII 角色
系统 SHALL 将羽汐角色转换为彩色 ASCII 艺术。

#### Scenario: ASCII 艺术展示
- **WHEN** 欢迎面板渲染
- **THEN** 显示羽汐角色的彩色 ASCII 艺术（去除背景，保留角色轮廓和关键色彩：白发、紫眼、黑色女仆装）

#### ASCII 艺术设计

基于角色图片特征（白发猫耳、紫色眼睛、黑色女仆装+白色荷叶边、黑色蝴蝶结发带），使用 Textual markup 语法 `[color]text[/]` 实现彩色 ASCII：

```
         [bold #f0e8ff]──╮  ╭──[/]        ← 白色猫耳
        [bold #e8e0ff]╭┤  ├╭  ├╮[/]
       [bold #e0d8ff]╭┤│ [bold #a855f7][/] │├┤│ [bold #a855f7]◉[/] │├╮[/]  ← 紫色眼睛
       [bold #d8d0ff]│├╯  ╰─╯  ╰┤│[/]
       [bold #d0c8ff]│──────────┤│[/]
       [bold #c8c0ff]│  ╭────╮╭┤│[/]
       [bold #c0b8ff]│├┤  │[bold #1a1030]▓▓▓[/]│├┤│[/]  ← 黑色女仆装
       [bold #b8b0ff]│├┤  │[bold #1a1030]▓▓▓[/]│├┤│[/]
       [bold #b0a8ff]│├┤  ╰────╯├┤│[/]
       [bold #a8a0ff]│├┤ [bold #f0f0ff]──┐[/]  ├┤│[/]  ← 白色荷叶边
       [bold #a098ff]│├┤ [bold #f0f0ff]│  │[/]  ├┤│[/]
       [bold #9890ff]╰┴─┴──────┴┴╯[/]
```

ASCII 艺术将定义在 `welcome_panel.py` 中作为模块级常量，使用 Textual markup 语法着色。

## MODIFIED Requirements

### Requirement: 配色方案
当前使用 Catppuccin Mocha 配色，修改为赛博朋克/动漫风格配色。

**新配色方案**（参考 iTerm2-Color-Schemes 动漫风格）：
- 背景色：`#0a0a1a`（深空蓝黑）
- 面板背景：`#12122a`（深蓝紫）
- 边框色：`#ff006e`（霓虹粉）/ `#8338ec`（霓虹紫）
- 主文字：`#e0e0ff`（淡蓝白）
- 强调色：`#00f5ff`（霓虹青）、`#ff006e`（霓虹粉）、`#8338ec`（霓虹紫）、`#ffbe0b`（霓虹黄）
- 成功色：`#00f5ff`（霓虹青替代绿色）
- 错误色：`#ff006e`（霓虹粉替代红色）

### Requirement: 状态栏
状态栏 SHALL 保持一行式布局，但配色更新为赛博朋克风格。
