# Tasks

- [x] Task 1: 修复斜杠命令弹窗滚动 Bug
  - [x] SubTask 1.1: 修改 `prompt_input.py` DEFAULT_CSS 中 `ListItem.--highlight` → `ListItem.-highlight`（3处选择器）
  - [x] SubTask 1.2: 将 `_show_slash_popup` 改为 async 方法，await `list_view.clear()` 和 `list_view.append(item)`
  - [x] SubTask 1.3: 将 `_check_slash_completion` 改为 async，await `_show_slash_popup()`
  - [x] SubTask 1.4: 将 `on__prompt_text_area_text_changed` 改为 async，await `_check_slash_completion()`
  - [x] SubTask 1.5: 验证上下键滚动和鼠标点击均正常工作

- [x] Task 2: 创建 `/harness` 命令处理器
  - [x] SubTask 2.1: 创建 `hakus/tui_v2/commands/harness_cmd.py`，实现 `HarnessCommand` 类（继承 `SlashCommand`）
  - [x] SubTask 2.2: 支持 `on`/`off`/`status`/`test` 子命令
  - [x] SubTask 2.3: 在 `hakus/tui_v2/commands/__init__.py` 中导入并注册 `HarnessCommand`
  - [x] SubTask 2.4: 验证 `/harness` 命令不再提示"未知命令"

- [x] Task 3: 新增 MockToolRegistry 和 HarnessTestCase
  - [x] SubTask 3.1: 在 `hakus/harness.py` 中新增 `MockToolRegistry` 类（预设模拟响应映射、故障注入支持）
  - [x] SubTask 3.2: 新增 `HarnessTestCase` 数据类（prompt、expected_pattern、max_steps、mock_responses、fault_injection）
  - [x] SubTask 3.3: 新增 `HarnessSuite` 类（run 方法执行测试套件、收集轨迹、生成 HarnessReport）
  - [x] SubTask 3.4: 在 `harness_cmd.py` 的 `test` 子命令中使用 HarnessSuite 运行内置测试

- [x] Task 4: 新增 FadeOverlay 渐变淡出效果
  - [x] SubTask 4.1: 创建 `hakus/tui_v2/widgets/fade_overlay.py`，实现 `FadeOverlay` Widget（使用 Rich Style 逐行调整颜色透明度）
  - [x] SubTask 4.2: 在 `message_list.py` 中集成 FadeOverlay（顶部和底部各一个）
  - [x] SubTask 4.3: 根据消息列表是否可滚动动态显示/隐藏 FadeOverlay
  - [x] SubTask 4.4: 在 `theme.tcss` 中添加 FadeOverlay 样式
  - [x] SubTask 4.5: 验证渐变效果在深色背景上自然过渡

# Task Dependencies
- Task 2 depends on Task 3（harness_cmd.py 的 test 子命令需要 MockToolRegistry 和 HarnessSuite）
- Task 4 独立，可与其他任务并行
- Task 1 独立，可与其他任务并行
