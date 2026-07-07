# Phase 2 详细实施计划: LLM 抽象层重构

> **状态**: Phase 1 已完成 | Phase 2 待执行
> **基于**: `.trae/documents/hakus-vs-trae-agent-comparison.md` 全局对比分析
> **借鉴**: trae-agent 的 `LLMClient` + `BaseLLMClient`(ABC) + Provider Enum 架构

---

## 一、当前状态分析

### 1.1 现有架构（重构前）

```
hakus/models.py (单文件, 147 行)
├── _BaseModel          # 基类: 封装 openai.AsyncOpenAI
│   ├── generate_response()      → Tuple[str, List[Dict]]
│   └── generate_response_no_tools() → str
├── DeepSeekModel       # 继承 _BaseModel
├── QwenModel           # 继承 _BaseModel
├── GeminiModel         # 继承 _BaseModel
├── GLMModel            # 继承 _BaseModel
├── MiMoModel           # 继承 _BaseModel
└── OllamaModel         # 继承 _BaseModel

agent.py 使用方式:
_MODEL_MAP = {"deepseek": (DeepSeekModel, "DeepSeek"), ...}
_init_model() → model_cls() → self._model = instance
_call_model() → self._model.client.chat.completions.create() (首选路径)
             → self._model.generate_response() (legacy 回退)
```

### 1.2 问题识别

| # | 问题 | 影响 |
|---|------|------|
| P1 | 所有模型共用 `_BaseModel`，无法支持非 OpenAI 兼容 API（如 Anthropic） | 扩展性差 |
| P2 | 新增 Provider 需要改 `models.py` + `agent.py` 两处（加类 + 加 MAP） | 违反开闭原则 |
| P3 | `_call_model()` 用 `hasattr` duck typing 检测能力，脆弱 | 类型不安全 |
| P4 | 无 Provider 枚举，model_type 是裸字符串 | 容易拼写错 |
| P5 | 配置散落在 `BASE_CONFIG` 字典的 15+ 个 key 中 | 难以管理 |

### 1.3 外部依赖（必须保持兼容）

以下文件直接 import 了 `hakus.models`：
- `hakus/agent.py:24` — `from .models import DeepSeekModel, QwenModel, ...`
- `tts/api_tts.py:7` — `from hakus.models import GeminiModel, QwenModel`
- `test_all_modules.py:333,349` — `from hakus.models import DeepSeekModel`

---

## 二、目标架构（重构后）

```
hakus/models/ (包, 原 models.py 拆分)
├── __init__.py              # 向后兼容重导出 + ClientFactory
├── base_client.py           # BaseLLMClient(ABC) + LLMProvider(Enum)
│   ├── chat()               # 核心抽象方法
│   ├── stream_chat()        # 流式抽象方法 (可选)
│   └── supports_tool_calling()
├── deepseek_client.py       # DeepSeekClient(BaseLLMClient)
├── openai_client.py         # OpenAIClient(BaseLLMClient) — 通用 OpenAI 兼容
├── ollama_client.py         # OllamaClient(BaseLLMClient)
├── qwen_client.py           # QwenClient(BaseLLMClient)
├── gemini_client.py         # GeminiClient(BaseLLMClient) — OpenAI 兼容端点
├── glm_client.py            # GLMClient(BaseLLMClient)
├── mimo_client.py           # MiMoClient(BaseLLMClient)
└── responses.py             # LLMResponse / LLMMessage 数据类 (trae-agent 风格)

agent.py 改动:
_init_model() → ClientFactory.create(provider_config)
_call_model() → self._llm_client.chat(messages, tools)  # 类型安全
```

---

## 三、实施步骤

### Step 1: 将 `hakus/models.py` 转换为包

**操作**: 重命名 `hakus/models.py` → `hakus/models/__init__.py`（暂存旧内容）

**原因**: 需要在同一个命名空间下添加多个模块文件。Python 不允许 `models.py` 和 `models/` 共存。

**具体操作**:
1. 创建 `hakus/models/` 目录
2. 将现有 `models.py` 内容移入 `hakus/models/_legacy.py`（保留原逻辑不变）
3. 创建 `hakus/models/__init__.py`，从 `_legacy.py` 重导出所有公共名称：

```python
# hakus/models/__init__.py — 向后兼容层
from ._legacy import (
    _BaseModel,
    DeepSeekModel, QwenModel, GeminiModel,
    GLMModel, MiMoModel, OllamaModel,
)

__all__ = [
    "_BaseModel", "DeepSeekModel", "QwenModel", "Gemini",
    "GLMModel", "MiMoModel", "OllamaModel",
]
```

**验证**: `python -c "from hakus.models import DeepSeekModel; print(DeepSeekModel)"` 正常

### Step 2: 创建 `base_client.py` — 抽象基类 + 枚举

**新文件**: `hakus/models/base_client.py`

```python
"""LLM Client 抽象层 — 借鉴 trae-agent BaseLLMClient 设计."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence


class LLMProvider(Enum):
    """支持的 LLM 提供商枚举."""
    DEEPSEEK = "deepseek"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"     # 预留
    QWEN = "qwen"
    GEMINI = "gemini"
    GLM = "glm"
    MIMO = "mimo"
    OLLAMA = "ollama"


@dataclass
class LLMMessage:
    """标准化消息格式 (trae-agent LLMMessage 风格)."""
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None


@dataclass
class LLMResponse:
    """标准化响应格式 (trae-agent LLMResponse 风格)."""
    content: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    finish_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class ModelConfig:
    """单个模型配置."""
    provider: LLMProvider
    api_key: str
    base_url: str
    model_name: str
    timeout: float = 60.0


class BaseLLMClient(ABC):
    """LLM Client 抽象基类.

    借鉴 trae-agent 的 BaseLLMClient(ABC)，定义统一的调用接口。
    每个 Provider 实现自己的 chat()/stream_chat() 方法。
    """

    def __init__(self, config: ModelConfig):
        self.config = config
        self._provider = config.provider
        self._model_name = config.model_name

    @property
    def provider(self) -> LLMProvider:
        return self._provider

    @property
    def model_name(self) -> str:
        return self._model_name

    @abstractmethod
    async def chat(
        self,
        messages: Sequence[LLMMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[float] = None,
    ) -> LLMResponse:
        """同步调用 LLM，返回结构化响应."""

    async def stream_chat(
        self,
        messages: Sequence[LLMMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncIterator[str]:
        """流式调用 LLM（默认实现：回退到 chat()）.
        子类可覆写以支持真正的 SSE 流式。
        """
        response = await self.chat(messages, tools)
        yield response.content

    def supports_tool_calling(self) -> bool:
        """此 Provider 是否支持 function calling."""
        return True

    def get_openai_client(self):
        """返回底层 OpenAI 兼容客户端（如有）.
        用于 agent.py 中需要直连 client 的场景（如 thread isolation）。
        返回 None 表示非 OpenAI 兼容。
        """
        return None
```

### Step 3: 创建通用 OpenAI 兼容 Client

**新文件**: `hakus/models/openai_compatible_client.py`

核心思路：trae-agent 的 7 个 Provider 中有 6 个都是 OpenAI-compatible（OpenAI/Azure/Ollama/OpenRouter/Doubao/Google）。我们也一样——DeepSeek/Qwen/GLM/MiMo/Gemini/Ollama 全部走 OpenAI SDK。

```python
"""OpenAI 兼容 Client — 覆盖大部分 Provider."""
import json
import logging
import openai
from .base_client import BaseLLMClient, LLMResponse, LLMMessage, ModelConfig

logger = logging.getLogger(__name__)


class OpenAICompatibleClient(BaseLLMClient):
    """通用的 OpenAI 兼容客户端.

    适用于: DeepSeek, Qwen, GLM, MiMo, Ollama, Gemini(OpenAI端点)
    """

    def __init__(self, config: ModelConfig):
        super().__init__(config)
        self._client = openai.AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )

    def get_openai_client(self):
        return self._client

    async def chat(
        self,
        messages: Sequence[LLMMessage],
        tools: Optional[List[Dict]] = None,
        timeout: Optional[float] = None,
    ) -> LLMResponse:
        # 将 LLMMessage → OpenAI 格式
        oa_messages = [self._to_oa(m) for m in messages]

        kwargs = {
            "model": self._model_name,
            "messages": oa_messages,
        }
        if tools:
            kwargs["tools"] = tools

        if timeout:
            import asyncio
            response = await asyncio.wait_for(
                self._client.chat.completions.create(**kwargs),
                timeout=timeout,
            )
        else:
            response = await self._client.chat.completions.create(**kwargs)

        return self._parse_response(response)

    @staticmethod
    def _to_oa(msg: LLMMessage) -> Dict:
        m = {"role": msg.role, "content": msg.content}
        if msg.tool_call_id:
            m["tool_call_id"] = msg.tool_call_id
        if msg.tool_calls is not None:
            m["tool_calls"] = msg.tool_calls
        return m

    def _parse_response(self, response) -> LLMResponse:
        content = ""
        tool_calls = []
        if response.choices:
            msg = response.choices[0].message
            content = msg.content or ""
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    except json.JSONDecodeError:
                        args = {}
                    tool_calls.append({
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": args,
                    })
        usage = response.usage
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=response.choices[0].finish_reason if response.choices else "",
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )
```

### Step 4: 创建各 Provider 便捷封装

每个 Provider 只是一个薄包装，继承 `OpenAICompatibleClient` 并注入配置：

**文件列表**:
| 文件名 | 类名 | 对应原类 |
|--------|------|---------|
| `deepseek_client.py` | `DeepSeekClient` | `DeepSeekModel` |
| `qwen_client.py` | `QwenClient` | `QwenModel` |
| `gemini_client.py` | `GeminiClient` | `GeminiModel` |
| `glm_client.py` | `GLMClient` | `GLMModel` |
| `mimo_client.py` | `MiMoClient` | `MiMoModel` |
| `ollama_client.py` | `OllamaClient` | `OllamaModel` |

每个文件的模式相同（以 DeepSeek 为例）：

```python
# hakus/models/deepseek_client.py
from utils.config import BASE_CONFIG
from .openai_compatible_client import OpenAICompatibleClient
from .base_client import LLMProvider, ModelConfig


class DeepSeekClient(OpenAICompatibleClient):
    """DeepSeek 模型客户端."""

    def __init__(self):
        super().__init__(ModelConfig(
            provider=LLMProvider.DEEPSEEK,
            api_key=BASE_CONFIG["DEEPSEEK_API_KEY"],
            base_url=BASE_CONFIG["DEEPSEEK_BASE_URL"],
            model_name=BASE_CONFIG["DEEPSEEK_MODEL_NAME"],
        ))
```

### Step 5: 创建 ClientFactory

**新文件**: `hakus/models/client_factory.py`

```python
"""LLM Client 工厂 — 根据 provider 字符串或枚举创建对应 Client."""
from .base_client import BaseLLMClient, LLMProvider, ModelConfig
from .deepseek_client import DeepSeekClient
from .qwen_client import QwenClient
# ... 其他 imports

_PROVIDER_CLIENT_MAP: dict[LLMProvider, type[BaseLLMClient]] = {
    LLMProvider.DEEPSEEK: DeepSeekClient,
    LLMProvider.QWEN: QwenClient,
    LLMProvider.GEMINI: GeminiClient,
    LLMProvider.GLM: GLMClient,
    LLMProvider.MIMO: MiMoClient,
    LLMProvider.OLLAMA: OllamaClient,
}


def create_client(provider: LLMProvider | str) -> BaseLLMClient:
    """工厂函数: 根据创建对应的 LLM Client.

    Args:
        provider: LLMProvider 枚举值或字符串 (如 "deepseek")

    Returns:
        初始化好的 Client 实例

    Raises:
        ValueError: 不支持的 provider
    """
    if isinstance(provider, str):
        provider = LLMProvider(provider.lower())

    cls = _PROVIDER_CLIENT_MAP.get(provider)
    if not cls:
        raise ValueError(f"Unsupported LLM provider: {provider}")
    return cls()


def create_client_from_config(model_type: str) -> BaseLLMClient:
    """从 BASE_CONFIG 中的 model_type 字符串创建 Client.

    这是 agent.py _init_model() 的替代品。
    """
    return create_client(model_type)
```

### Step 6: 修改 `agent.py` 使用新抽象

**改动范围**: `hakus/agent.py`

#### 6a. 替换 import 区

```python
# 旧代码 (行 23-46):
try:
    from .models import DeepSeekModel
except ImportError:
    DeepSeekModel = None
# ... 6 个 try/except 块 ...

# 新代码:
from .models.client_factory import create_client_from_config
from .models.base_client import BaseLLMClient, LLMProvider, LLMMessage, LLMResponse
```

#### 6b. 简化 `_MODEL_MAP` 或移除

```python
# 旧的 _MODEL_MAP (行 276-283):
_MODEL_MAP = {
    "deepseek": (DeepSeekModel, "DeepSeek"),
    ...
}

# 新方案: 直接用 LLMProvider 枚举，不再需要字典映射
```

#### 6c. 重写 `_init_model()`

```python
def _init_model(self) -> None:
    """使用 ClientFactory 创建 LLM Client."""
    try:
        self._llm_client = create_client_from_config(self._model_type)
        # 保持 self._model 向后兼容 (部分代码仍访问 self._model.client)
        self._model = self._llm_client
        logger.info(f"LLM Client initialized: {self._llm_client.provider.value} / {self._llm_client.model_name}")
    except Exception as e:
        logger.error(f"Failed to init LLM client: {e}")
        # fallback 逻辑保持不变...
```

#### 6d. 适配 `_call_model()` 使用新接口

核心变化：将 `messages: List[Dict]` 转为 `Sequence[LLMMessage]` 后调用 `self._llm_client.chat()`。

保留 `_call_model_via_client()` 和 `_call_model_in_thread()` 作为性能优化路径（thread isolation for TUI mode），但它们内部改为通过 `self._llm_client.get_openai_client()` 获取底层 client。

---

## 四、不改变的（保持稳定）

1. **`_call_model_via_client()` 逻辑不变** — TUI mode thread isolation 是经过实战验证的关键优化
2. **`_call_model_in_thread()` 逻辑不变** — event loop 冲突的最后防线
3. **DSML XML tool call 解析不变** — DeepSeek 特有的 content 内嵌工具调用
4. **ContextManager 不变** — token 校准和压缩逻辑独立于 LLM 层
5. **ToolRegistry / Tool 不变** — 工具系统与 LLM 解耦
6. **根目录 `models/` 包不动** — 那 singleton 版本给 tts 等模块用，后续统一

---

## 五、文件变更清单

| 操作 | 文件路径 | 说明 |
|------|---------|------|
| **新建** | `hakus/models/base_client.py` | ABC + Enum + 数据类 (~80 行) |
| **新建** | `hakus/models/openai_compatible_client.py` | 通用 OpenAI 客户端 (~100 行) |
| **新建** | `hakus/models/deepseek_client.py` | DeepSeek 封装 (~15 行) |
| **新建** | `hakus/models/qwen_client.py` | Qwen 封装 (~15 行) |
| **新建** | `hakus/models/gemini_client.py` | Gemini 封装 (~15 行) |
| **新建** | `hakus/models/glm_client.py` | GLM 封装 (~15 行) |
| **新建** | `hakus/models/mimo_client.py` | MiMo 封装 (~15 行) |
| **新建** | `hakus/models/ollama_client.py` | Ollama 封装 (~15 行) |
| **新建** | `hakus/models/client_factory.py` | 工厂函数 (~40 行) |
| **修改** | `hakus/models/__init__.py` | 从 models.py 转换，向后兼容重导出 |
| **修改** | `hakus/agent.py` | import + _init_model + _call_model 适配 |

**总计**: 9 个新文件 + 2 个修改文件 ≈ 350 行新增代码

---

## 六、风险与缓解

| 风险 | 概率 | 缓解措施 |
|------|------|---------|
| `hakus/models.py` → 包转换导致 import 失败 | 低 | `__init__.py` 完整重导出所有公共名称 |
| TUI mode thread isolation 与新 Client 不兼容 | 中 | `get_openai_client()` 返回原始 AsyncOpenAI 实例 |
| `tts/api_tts.py` 依赖旧的 class 名 | 低 | 保持 `DeepSeekModel` 等类名在 `__init__.py` 可用 |
| 性能回退（多一层抽象） | 极低 | `OpenAICompatibleClient` 只是薄包装，无额外开销 |

---

## 七、验证步骤

每步完成后执行：

```bash
# Step 1 验证: 包转换后导入正常
python -c "from hakus.models import DeepSeekModel, QwenModel; print('OK')"

# Step 2-5 验证: 新模块可导入
python -c "from hakus.models.base_client import BaseLLMClient, LLMProvider; print('OK')"
python -c "from hakus.models.deepseek_client import DeepSeekClient; print('OK')"
python -c "from hakus.models.client_factory import create_client; print('OK')"

# Step 6 验证: AgentCore 可初始化
python -c "from hakus.agent import AgentCore; print('OK')"

# 全量验证: 应用启动
python -m hakus.entry

# 功能验证: 发送消息测试 Agent 循环
# (在 TUI 中输入消息，确认模型调用正常)
```
