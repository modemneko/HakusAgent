# HakusAI 巨型文件重构计划

> **状态**: 规划中 | **目标版本**: v0.3.0  
> **创建日期**: 2025-01-XX  
> **预计工作量**: 3-5 天

---

## 📋 概述

本文档记录了 HakusAI 项目中需要拆分的巨型文件及其重构方案。  
**目标**: 将所有文件控制在 500 行以内，提高代码可维护性和可读性。

---

## 🔴 优先级 P0 (立即处理)

### 1. `hakus/agent.py` (3871 行)

| 属性 | 值 |
|------|-----|
| **当前行数** | ~3871 |
| **目标行数** | <500/文件 |
| **风险等级** | 高 (核心模块) |

#### 拆分方案

```
hakus/
├── agent/                    # 新建包
│   ├── __init__.py           # 导出公共 API
│   ├── core.py               # Agent 核心类 (~400 行)
│   │   # - Agent 基类定义
│   │   # - 生命周期管理
│   │   # - 状态机
│   ├── tools.py              # 工具管理 (~350 行)
│   │   # - 工具注册
│   │   # - 工具调用逻辑
│   │   # - 结果解析
│   ├── memory.py             # 记忆集成 (~300 行)
│   │   # - 上下文组装
│   │   # - 记忆读写
│   │   # - 会话历史
│   └── execution.py          # 执行引擎 (~350 行)
│       # - LLM 调用
│       # - 流式响应
│       # - 错误重试
└── agent.py                  # 保留为向后兼容的薄包装层
    # from hakus.agent.core import Agent
    # Agent = Agent  # re-export
```

#### 迁移步骤

1. [ ] 创建 `hakus/agent/` 包目录结构
2. [ ] 提取 `Agent.__init__` 和基础属性 → `core.py`
3. [ ] 提取工具相关方法 (`_execute_tool`, `register_tool` 等) → `tools.py`
4. [ ] 提取记忆相关方法 (`get_context`, `_build_prompt` 等) → `memory.py`
5. [ ] 提取执行逻辑 (`run`, `_call_llm`, `_process_stream`) → `execution.py`
6. [ ] 更新 `agent.py` 为兼容层，添加 deprecation warning
7. [ ] 更新所有 `from hakus.agent import Agent` 的导入

---

### 2. `src/hakusai_server/server.py` (3035 行)

| 属性 | 值 |
|------|-----|
| **当前行数** | ~3035 |
| **目标行数** | <500/文件 |
| **风险等级** | 高 (API 服务) |

#### 拆分方案

```
src/hakusai_server/
├── routes/                   # 新建路由包
│   ├── __init__.py
│   ├── chat.py               # 聊天端点 (~200 行)
│   ├── session.py            # 会话管理 (~150 行)
│   ├── tool.py               # 工具调用 (~150 行)
│   ├── config.py             # 配置接口 (~100 行)
│   └── health.py             # 健康检查 (~50 行)
├── middleware/                # 中间件 (已有部分)
│   ├── __init__.py
│   ├── auth.py               # 认证中间件
│   ├── cors.py               # CORS 处理
│   ├── error_handler.py      # 统一错误处理
│   └── logging.py            # 请求日志
├── main.py                   # 应用工厂 + 启动入口 (~200 行)
│   # - create_app()
│   # - lifespan context
│   # - mount routes
└── server.py                 # 保留为兼容层
```

#### 迁移步骤

1. [ ] 创建 `routes/` 和扩展 `middleware/` 目录
2. [ ] 按 URL 前缀提取路由函数:
   - `/api/chat/*` → `chat.py`
   - `/api/sessions/*` → `session.py`
   - `/api/tools/*` → `tool.py`
3. [ ] 提取中间件到独立文件
4. [ ] 创建 `create_app()` 工厂函数
5. [ ] 更新启动脚本引用

---

## 🟡 优先级 P1 (本周处理)

### 3. `hakus/tui.py` (2202 行)

| 属性 | 值 |
|------|-----|
| **当前行数** | ~2202 |
| **目标行数** | N/A (标记 legacy) |
| **风险等级** | 中 |

#### 处理方案: **标记为 Legacy**

```python
# hakus/tui.py 文件顶部添加
"""
Legacy TUI Module (Deprecated)
===============================

此模块已被 `hakus.tui_v2` 替代。

- 新功能开发请在 tui_v2/ 进行
- 此文件仅维护，不新增功能
- 预计移除时间: v0.4.0

迁移指南:
  旧: from hakus.tui import TUIApp
  新: from hakus.tui_v2.app import TUIApp_v2
"""

import warnings
warnings.warn(
    "hakus.tui is deprecated, use hakus.tui_v2 instead",
    DeprecationWarning,
    stacklevel=2
)
```

#### 可选拆分 (如果需要继续维护)

```
hakus/
├── tui/
│   ├── __init__.py
│   ├── app.py              # 主应用类
│   ├── widgets.py          # UI 组件
│   ├── commands.py         # 命令处理
│   └── theme.py            # 主题配置
```

---

### 4. `hakus/memory_vector.py` (1899 行)

| 属性 | 值 |
|------|-----|
| **当前行数** | ~1899 |
| **目标行数** | <500/文件 |
| **风险等级** | 中 |

#### 拆分方案

```
hakus/
├── memory/                    # 重构为包
│   ├── __init__.py
│   ├── vector_store.py        # 向量存储核心 (~400 行)
│   │   # - VectorStore 类
│   │   # - 增删改查操作
│   │   # - 相似度搜索
│   ├── embeddings.py          # 嵌入计算 (~300 行)
│   │   # - EmbeddingModel 抽象
│   │   # - 本地嵌入实现
│   │   # - API 嵌入调用
│   ├── storage.py             # 持久化层 (~250 行)
│   │   # - JSON 序列化
│   │   # - 文件 I/O
│   │   # - 缓存机制
│   └── index.py               # 索引优化 (~200 行)
│       # - IVF 索引
│       # - 分块策略
└── memory_vector.py           # 兼容层
```

---

### 5. `hakus/orchestrator.py` (1838 行)

| 属性 | 值 |
|------|-----|
| **当前行数** | ~1838 |
| **目标行数** | <500/文件 |
| **风险等级** | 中 |

#### 拆分方案

```
hakus/
├── orchestrator/              # 重构为包
│   ├── __init__.py
│   ├── core.py                # 编排器核心 (~400 行)
│   │   # - Orchestrator 类
│   │   # - 任务调度循环
│   │   # - 状态管理
│   ├── dispatcher.py          # 任务分发 (~350 行)
│   │   # - 子任务创建
│   │   # - Agent 选择
│   │   # - 结果收集
│   ├── planner.py             # 规划器 (~300 行)
│   │   # - 任务分解
│   │   # - 依赖分析
│   │   # - 执行计划生成
│   └── monitors.py            # 监控 (~200 行)
│       # - 进度跟踪
│       # - 超时处理
│       # - 错误恢复
└── orchestrator.py             # 兼容层
```

---

## 📊 当前文件规模统计

| 文件名 | 当前行数 | 目标行数 | 状态 | 优先级 |
|--------|----------|----------|------|--------|
| `hakus/agent.py` | 3871 | <500 | ⏳ 待拆分 | P0 |
| `src/hakusai_server/server.py` | 3035 | <500 | ⏳ 待拆分 | P0 |
| `hakus/tui.py` | 2202 | Legacy | ⏳ 标记废弃 | P1 |
| `hakus/memory_vector.py` | 1899 | <500 | ⏳ 待拆分 | P1 |
| `hakus/orchestrator.py` | 1838 | <500 | ⏳ 待拆分 | P1 |

---

## 🛠️ 重构工具和辅助

### 自动化检查脚本

在 CI 中已配置 `.github/workflows/quality.yml` 的 `file-size-check` job，会在每次 PR 时检测超过 500 行的文件。

### 手动检查命令

```bash
# 查找所有超过 500 行的 Python 文件
find . -name "*.py" -not -path "./.git/*" -not -path "./node_modules/*" \
  -not -path "./tts_engines/*" -exec wc -l {} \; | awk '$1 > 500 {print}' | sort -rn

# 统计前 20 大文件
find . -name "*.py" -not -path "./.git/*" -exec wc -l {} \; | sort -rn | head -20
```

---

## ✅ 完成标准

每个文件重构完成后应满足:

- [ ] 所有单元测试通过
- [ ] 无新增 warnings
- [ ] 向后兼容 (旧导入仍可用)
- [ ] 添加了适当的 docstrings
- [ ] 更新了 `DEAD_CODE_CLEANUP.md` (如有死代码)
- [ ] 在下方表格更新状态

---

## 📝 变更日志

| 日期 | 操作 | 执行人 | 备注 |
|------|------|--------|------|
| 2025-01-XX | 创建文档 | - | 初始版本 |
| | | | |
| | | | |

---

## 🔄 相关文档

- [DEAD_CODE_CLEANUP.md](./DEAD_CODE_CLEANUP.md) - 死代码清理清单
- [CHANGELOG.md](./CHANGELOG.md) - 版本变更记录
- [.pre-commit-config.yaml](./.pre-commit-config.yaml) - 代码风格自动化
