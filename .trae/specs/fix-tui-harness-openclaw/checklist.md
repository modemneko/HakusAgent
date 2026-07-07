# Checklist

- [x] 斜杠命令弹窗中按上下键可滚动选择，选中项有霓虹粉前景 + 深蓝紫背景高亮
- [x] 鼠标点击弹窗选项可正确补全命令并关闭弹窗
- [x] `/harness` 命令不再提示"未知命令"，可正常切换 Harness 开关
- [x] `/harness status` 显示 Harness 当前状态（启用/校准因子/阈值）
- [x] `/harness test` 运行 Mock 测试并显示结果
- [x] MockToolRegistry 可返回预设模拟响应，不产生真实副作用
- [x] MockToolRegistry 支持故障注入（返回错误响应）
- [x] HarnessSuite 可执行测试套件并生成 HarnessReport
- [x] 消息列表可滚动时，顶部和底部显示 2-3 行渐变淡出遮罩
- [x] 渐变从正常文字色自然过渡到背景色 #0a0a1a
- [x] 消息列表不可滚动时，不显示渐变遮罩
- [x] 所有修改通过 Python 导入验证
