# Checklist

- [x] 主题配色已更新为赛博朋克风格（深空蓝黑背景 #0a0a1a，霓虹粉/紫/青强调色）
- [x] `theme.py` 中 COLORS 和 SEMANTIC 字典全部使用新配色值
- [x] WelcomePanel 组件已创建并正确渲染双栏布局
- [x] ASCII 角色艺术由图片自动转换生成，显示在欢迎面板左侧
- [x] 欢迎面板右侧显示 "Tips for getting started" 和 "What's new" 两个子区域
- [x] WelcomePanel 限高 height: 20, max-height: 22（不做自适应）
- [x] NotificationBar 组件已创建并可正常显示/关闭通知
- [x] HakusApp.compose() 已集成 WelcomePanel 和 NotificationBar
- [x] Footer 显示内容已更新
- [x] PromptInput 输入框左侧显示 `> ` 前缀标识符
- [x] theme.tcss 中所有颜色值已替换为赛博朋克配色
- [x] StatusBar 配色已更新为霓虹风格
- [x] 所有组件 inline DEFAULT_CSS 颜色已更新（assistant_text, tool_result, command_result, error_block, user_bubble, prompt_input, status_bar, activity, message_list）
- [x] 所有 overlay 颜色已更新（diff_overlay, help_overlay, model_overlay）
- [x] PermissionDialog 和 risk badge 颜色已更新
- [x] Grep 验证无 Catppuccin Mocha 旧颜色残留
- [x] Python 导入验证通过（WelcomePanel, NotificationBar, HakusApp）
