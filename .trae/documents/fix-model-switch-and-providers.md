# Plan: 模型切换 Bug 修复 + 模型商扩展 + 全面测试

## Summary

修复 3 个核心问题：
1. **模型切换 Bug**：选 openai 后状态栏显示 openai 但实际回退到 deepseek，且无法切回
2. **模型商支持不足**：缺 OpenAI/Anthropic 实际客户端，模型列表三处不一致
3. **全面测试**：建立可复现的 debug 方法论，覆盖所有操作路径

---

## 一、Bug 根因分析

### 问题现象（用户截图）
- 状态栏显示 `openai` ✓
- 但 Overlay 中 DeepSeek 标记为 `(当前)` ✗
- 再切换也无效

### 根因链路追踪

```
用户在 ModelOverlay 选 "openai"
  → app.py:540  self._agent._model_type = "openai"
  → app.py:541  self._agent._init_model()
    → client_factory.py:76  create_client("openai")
      → LLMProvider("openai") 枚举值存在 ✓
      → _PROVIDER_CLIENT_MAP.get(LLMProvider.OPENAI) → None ✗ **没有 OpenAI 客户端实现!**
    → 进入 fallback 链 → 最终落到 DeepSeek
    → agent.py:494  self._model_type = self._llm_client.provider.value → **被覆写为 "deepseek"**
  → app.py:542  self._session.model_name = "openai"  ← 还在用旧值!
  → app.py:543  self._status_bar.model_name = "openai"  ← 还在用旧值!
```

### 三处模型列表不一致

| 位置 | 列表 | 缺失 |
|------|------|------|
| [model_overlay.py:15](hakus/tui_v2/overlays/model_overlay.py#L15) MODELS | `deepseek, openai, ollama` | 缺 qwen/gemini/glm/mimo/anthropic |
| [model.py:17](hakus/tui_v2/commands/model.py#L17) 白名单 | `deepseek, qwen, gemini, glm, mimo` | 缺 openai/ollama/anthropic |
| [client_factory.py:21](hakus/models/client_factory.py#L21) 工厂映射 | `DEEPSEEK,QWEN,GEMINI,GLM,MIMO,OLLAMA` | 缺 OPENAI/ANTHROPIC |
| [base_client.py:17](hakus/models/base_client.py#L17) 枚举 | 全部 8 个都有 | 枚举完整但客户端缺失 |

---

## 二、修复方案

### Task 1: 新增 OpenAI 客户端 + 统一模型列表

**文件：`hakus/models/openai_client.py`（新建）**

基于已有的 `OpenAICompatibleClient` 创建 OpenAI 官方客户端：
- 复用 `OpenAICompatibleClient` 作为基类（OpenAI 就是参考实现）
- 从 `BASE_CONFIG` 读取 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`OPENAI_MODEL_NAME`
- 注册到 `client_factory.py` 的 `_PROVIDER_CLIENT_MAP`

**文件：`hakus/models/client_factory.py`（修改）**
- 导入 `OpenAIClient`
- 在 `_PROVIDER_CLIENT_MAP` 添加 `LLMProvider.OPENAI: OpenAIClient`
- 在 `_FALLBACK_ORDER` 中添加合理位置

**文件：`hakus/models/__init__.py`（修改）**
- 导出 `OpenAIClient`

### Task 2: 统一三处模型列表为同一数据源

**核心思路**：定义一份权威的模型列表，三处引用同一份数据。

**新建 `hakus/models/provider_registry.py`**：
```python
# 权威模型提供商列表 — 所有 UI 和命令都从这里读取
PROVIDERS = [
    {"id": "deepseek",   "name": "DeepSeek",     "desc": "默认 · 性价比高"},
    {"id": "openai",     "name": "OpenAI",       "desc": "GPT-4o / o3"},
    {"id": "anthropic",  "name": "Anthropic",    "desc": "Claude Sonnet / Opus"},
    {"id": "qwen",       "name": "通义千问",      "desc": "阿里百炼 · 中文优化"},
    {"id": "gemini",     "name": "Gemini",       "desc": "Google 2.5 Flash"},
    {"id": "glm",        "name": "智谱 GLM",      "desc": "GLM-4 Flash"},
    {"id": "mimo",       "name": "MiMo",         "desc": "小米多模态"},
    {"id": "ollama",     "name": "Ollama",       "desc": "本地模型"},
]

def get_provider_ids() -> list[str]:
    return [p["id"] for p in PROVIDERS]
```

**修改文件**：
- [model_overlay.py](hakus/tui_v2/overlays/model_overlay.py) — 从 `provider_registry.PROVIDERS` 读取
- [model.py](hakus/tui_v2/commands/model.py) — 白名单从 `provider_registry.get_provider_ids()` 读取
- [setup_wizard.py](hakus/tui_v2/screens/setup_wizard.py) — 向导也从这里读取

### Task 3: 修复模型切换的状态同步 Bug

**文件：[app.py](hakus/tui_v2/app.py) `action_show_model_overlay()` 的 `on_select` 回调**

当前问题：
```python
# 当前代码（有 bug）
self._agent._model_type = model      # 设为 "openai"
self._agent._init_model()             # fallback 后变成 "deepseek"
self._session.model_name = model      # ← 用了旧的 "openai"，不同步！
self._status_bar.model_name = model   # ← 同上
```

修复后：
```python
self._agent._model_type = model
self._agent._init_model()
# 用 _agent._model_type 的实际值（可能被 fallback 改变）
actual = self._agent._model_type
self._session.model_name = actual
self._status_bar.model_name = actual
if actual != model:
    self._mount_message(Message.command(
        "model", f"⚠ {model} 不可用，已回退到 **{actual}**"))
else:
    self._mount_message(Message.command("model", f"✓ 已切换到 **{actual}**"))
```

同样修复 [model.py](hakus/tui_v2/commands/model.py) 第 20-26 行的同步逻辑。

### Task 4: 集成 LiteLLM 扩展模型商支持

**调研结论**：

| 框架 | 特点 | 适用性 |
|------|------|--------|
| **LiteLLM** | Python 库，100+ 提供商，统一 OpenAI 格式，支持流式+tool calling | ⭐⭐⭐ 最佳选择 |
| OpenRouter | 托管服务，非本地库 | 不适合集成 |
| OneAPI | 自托管网关，需单独部署 | 太重 |

**方案**：新增 `LitellmClient`，作为可选依赖。

**文件：`hakus/models/litellm_client.py`（新建）**
- 包装 LiteLLM 的 `completion()` / `stream()` 调用
- 继承 `BaseLLMClient` 接口
- 支持 LiteLLM 所有 100+ 提供商（Groq、Together、Mistral、Cohere、Fireworks 等）
- 用户只需配置 `custom` 类型 + base_url 即可使用任何 OpenAI 兼容服务

**文件：`client_factory.py`（修改）**
- 添加 `LITELLM` provider（可选，try/except 导入）

**文件：`pyproject.toml`（修改）**
- 添加 `litellm>=1.0.0` 为可选依赖 `[extras]`

**注意**：现有的 `OpenAICompatibleClient` 已经能覆盖大部分 OpenAI 兼容 API（通过 custom 配置）。LiteLLM 的价值在于它内置了各提供商的特殊处理（如 Anthropic 的 cache control、Gemini 的 safety settings 等）。作为增强而非必需。

### Task 5: 全面 Debug 测试方法论

#### 5.1 单元级验证脚本

**新建 `tests/test_model_switch.py`**：
```python
# 测试覆盖：
# 1. 每个 provider 能否成功 create_client()
# 2. 切换模型后 _model_type 是否一致
# 3. Fallback 链是否正常工作
# 4. 无 API Key 时是否优雅报错
# 5. status_bar / session / agent 三处状态是否同步
```

#### 5.2 TUI 操作路径测试清单

| # | 操作 | 预期结果 | 验证点 |
|---|------|----------|--------|
| 1 | 启动 → 状态栏显示默认模型 | 显示 config.yaml 中的 default_model | StatusBar.model_name |
| 2 | `/model` → 弹出 Overlay | 显示所有 8 个提供商，当前项标记 | ModelOverlay.MODELS |
| 3 | Overlay ↑↓ 选择 → Enter | 切换成功，消息提示 + 状态栏更新 | Message + StatusBar |
| 4 | `/model deepseek` 命令行直接切 | 同上 | Command execute |
| 5 | 切换到未配置 Key 的提供商 | 优雅降级/fallback + 提示 | Error message |
| 6 | 连续切换 A→B→C→A | 每次状态正确 | State consistency |
| 7 | `/model invalid` | 报错"未知模型" | Error handling |
| 8 | 切换后发送消息 | 使用新模型的 client | Agent._llm_client |

#### 5.3 Debug 日志增强

在关键节点添加结构化日志：
- `_init_model()` 入参和出参（含 fallback 信息）
- `on_select()` 回调中 model 变化前后对比
- `create_client_from_config()` 每次尝试的结果

---

## 三、涉及文件清单

| 文件 | 操作 | 内容 |
|------|------|------|
| `hakus/models/openai_client.py` | **新建** | OpenAI 客户端实现 |
| `hakus/models/provider_registry.py` | **新建** | 权威提供商列表（单一数据源）|
| `hakus/models/client_factory.py` | 修改 | 注册 OpenAIClient + 可选 Litellm |
| `hakus/models/__init__.py` | 修改 | 导出新客户端 |
| `hakus/tui_v2/overlays/model_overlay.py` | 修改 | 从 provider_registry 读取列表 |
| `hakus/tui_v2/commands/model.py` | 修改 | 白名单从 registry 读取 + 修复状态同步 |
| `hakus/tui_v2/app.py` | 修改 | on_select 回调修复状态同步 |
| `hakus/tui_v2/screens/setup_wizard.py` | 修改 | 向导从 registry 读取 |
| `pyproject.toml` | 修改 | litellm 可选依赖 |
| `tests/test_model_switch.py` | **新建** | 模型切换测试套件 |

---

## 四、验证步骤

1. **导入测试**：`python -c "from hakus.models.openai_client import OpenAIClient; from hakus.models.provider_registry import PROVIDERS; print(len(PROVIDERS), 'providers')"`
2. **工厂测试**：`python -c "from hakus.models.client_factory import create_client; c = create_client('openai'); print(c.provider, c.model_name)"`
3. **一致性测试**：确认 overlay 列表 == command 白名单 == factory 映射键
4. **切换测试**：启动 TUI → `/model` → 选不同提供商 → 验证状态栏和消息
5. **Fallback 测试**：清空某提供商 API Key → 切换到该提供商 → 验证降级提示
