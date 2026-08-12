 HakusAI TUI 重构计划

## 目标
参考 OpenCode 的界面设计，重构 HakusAI TUI，解决滚动问题，保留 yuxi.png 图标布局。

## 问题分析

### 当前问题
1. **滚动问题** - 虚拟化实现有 bug，滚动时可能出现渲染异常
2. **布局问题** - 与 OpenCode 相比，缺少一些关键功能
3. **样式问题** - 需要更现代化的设计

### OpenCode 参考
- 使用 SolidJS + @opentui/core 实现
- 虚拟化消息列表（ScrollBoxRenderable）
- 插件系统支持自定义组件
- 丰富的键盘绑定

## 改进计划

### Phase 1: 修复滚动问题 (优先级: 高)
1. 修复 `message_list.py` 的虚拟化逻辑
2. 改进滚动事件处理
3. 添加平滑滚动支持

### Phase 2: 布局优化 (优先级: 中)
1. 优化 StatusBar 布局
2. 改进消息气泡样式
3. 添加工具结果折叠功能

### Phase 3: 功能增强 (优先级: 中)
1. 添加键盘快捷键
2. 改进流式输出处理
3. 添加消息复制功能

## 文件结构

```
hakus/tui_v2/
├── app.py              # 主应用 (保持)
├── theme.tcss          # 样式表 (优化)
├── widgets/
│   ├── message_list.py # 消息列表 (重写)
│   ├── assistant_text.py # 助手消息 (优化)
│   ├── user_bubble.py  # 用户消息 (优化)
│   ├── tool_result.py  # 工具结果 (优化)
│   └── status_bar.py   # 状态栏 (优化)
└── assets/
    └── yuxi.png        # 图标 (保持)
```

## 实现步骤

### Step 1: 修复 message_list.py 的滚动
```python
# 关键修复点：
1. 修复 _evict_distant() 的边界条件
2. 改进 _remount_near_viewport() 的性能
3. 添加防抖处理避免频繁重渲染
```

### Step 2: 优化 CSS 样式
```css
/* 关键改进： */
1. 添加滚动条样式
2. 优化消息间距
3. 改进颜色对比度
```

### Step 3: 改进流式输出
```python
# 关键改进：
1. 优化 TextDelta 处理
2. 添加 chunk 合并减少渲染次数
3. 改进中断处理
```

## 验证清单
- [ ] 滚动流畅无卡顿
- [ ] 消息正确显示
- [ ] 流式输出正常
- [ ] 键盘快捷键工作
- [ ] 图标正确显示
