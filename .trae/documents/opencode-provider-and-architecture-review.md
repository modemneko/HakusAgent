# 架构评估 & OpenCode 模型商支持方案

## 一、FrontierSWE 评估结论

### FrontierSWE 是什么？
**FrontierSWE 是一个超长程编码智能体基准测试（Benchmark），不是可复用的框架。**
- 由 Proximal Labs + 学术/工业界联合构建
- 测试 17 道人类能力极限级技术挑战（20小时/任务），覆盖实现类(5)、研究类(3)、性能优化类(9)
- 评分机制：0-1 连续分数，正确性门控，5次取均值
- 当前未饱和——大多数模型在几乎所有任务上几乎无法取得进展

### 有用吗？——有参考价值，但不可直接复用

| 维度 | 价值 | 说明 |
|------|------|------|
| **架构设计理念** | 高 | Harness 无关设计、Provider 适配器模式、运行时隔离 |
| **安全模型** | 高 | 三层纵深防御：权限声明→网络白名单→进程安全壳 |
| **评测方法论** | 中高 | 长程任务评分体系、反作弊审计 |
| **代码直接复用** | 低 | 基于 Harbor 框架 + Modal 云执行环境，与本项目技术栈不匹配 |
| **作为测试套件** | 中 | 可参考任务设计思路，但需适配 |

### 对本项目的具体启示
1. **已有良好基础**：HakusAI_chat 已具备多模型 Provider 抽象层、Agent 核心循环、工具系统、记忆系统等核心能力
2. **可借鉴的改进点**：
   - 运行时状态隔离（多会话间避免污染）
   - 上下文压缩/关键信息持久化（长程对话中防止信息丢失）
   - 验证-再提交工作流（减少模型过度自信导致的错误提交）
   - MCP 协议兼容性考虑
   - Reasoning Effort 参数归一化

---

## 二、OpenCode 模型商支持方案

### 背景
OpenCode (opencode.ai) 提供了 **OpenCode Zen** 服务——一组经过验证的精选模型，通过 OpenAI 兼容 API 提供。用户提供了 API Key 和指定使用免费模型 `deepseek-v4-flash-free`。

### API 端点分析
- OpenCode Zen 使用 **OpenAI 兼容 API 格式**
- Base URL: `https://api.opencode.ai/v1`（或类似端点）
- 模型名格式：`deepseek-v4-flash-free`
- 认证方式：Bearer Token (API Key)

### 实现步骤

#### Step 1: 修改 `config.yaml` — 添加 OpenCode 配置段

在 [config.yaml](config.yaml) 的以下位置添加配置：

**api_keys 段** (~L21 后):
```yaml
  # OpenCode Zen API
  opencode_api_key: ${OPENCODE_API_KEY:***REMOVED***}
```

**models 段** (~L48 后):
```yaml
  # OpenCode Zen 模型设置 (免费模型)
  opencode:
    model_name: ${OPENCODE_MODEL_NAME:deepseek-v4-flash-free}
    base_url: ${OPENCODE_BASE_URL:https://api.opencode.ai/v1}
```

#### Step 2: 修改 `base_client.py` — 添加 OPENCODE 枚举值

在 [LLMProvider](HakusAgent/hakus/models/base_client.py) 枚举中添加:
```python
OPENCODE = "opencode"
```

文件: `HakusAgent/hakus/models/base_client.py` L26 后

#### Step 3: 创建 `opencode_client.py` — OpenCode 客户端实现

新建文件: `HakusAgent/hakus/models/opencode_client.py`

继承 `OpenAICompatibleClient`（因为 OpenCode Zen 是 OpenAI 兼容 API）：
```python
class OpenCodeClient(OpenAICompatibleClient):
    def __init__(self):
        from utils.hakus_config import get_config
        config = get_config()
        prov = config.models.opencode
        super().__init__(ModelConfig(
            provider=LLMProvider.OPENCODE,
            api_key=prov.api_key,
            base_url=prov.base_url,
            model_name=prov.model_name,
        ))
```

#### Step 4: 修改 `client_factory.py` — 注册 OpenCode 到工厂和 Fallback 链

文件: `HakusAgent/hakus/models/client_factory.py`

- 导入 `OpenCodeClient`
- 在 `_PROVIDER_CLIENT_MAP` 中添加: `LLMProvider.OPENCODE: OpenCodeClient`
- 在 `_FALLBACK_ORDER` 中适当位置添加 `LLMProvider.OPENCODE`

#### Step 5: 修改 `provider_registry.py` — 注册到 UI 提供商列表

文件: `HakusAgent/hakus/models/provider_registry.py`

在 `PROVIDERS` 列表中添加:
```python
{"id": "opencode", "name": "OpenCode Zen", "desc": "免费 · DeepSeek V4 Flash"},
```

#### Step 6: 修改 `__init__.py` — 更新导出

文件: `HakusAgent/hakus/models/__init__.py`

确保 `OpenCodeClient` 被正确导出。

#### Step 7: 修改 `utils/hakus_config.py` — 配置加载支持 opencode

文件: `utils/hakus_config.py`

在 `_provider_defaults` 字典和 `_api_key_map` 中添加 opencode 条目。
在 `ModelsConfig` dataclass 中添加 `opencode: ProviderConfig` 默认值。
在 `_sync_base_config` 函数中添加 opencode 同步逻辑。

---

## 三、长程任务测试计划

### 测试目标
验证 OpenCode provider 集成正确性，并测试长程任务处理能力。

### 测试方法
使用提供的免费模型 `deepseek-v4-flash-free` 通过 OpenCode Zen API 进行实际调用测试。

### 测试用例设计

| # | 测试类型 | 描述 | 预期结果 |
|---|---------|------|---------|
| 1 | 基础连通性 | 发送简单对话请求 | 正常返回响应 |
| 2 | 工具调用 | 让 Agent 执行文件读写操作 | 正确调用工具并返回结果 |
| 3 | 多轮对话 | 3-5 轮上下文保持 | 上下文正确传递 |
| 4 | 长程任务-中等 | 要求完成一个需要 5-10 步操作的编程任务（如创建模块+写测试+运行） | 任务完整执行完毕 |
| 5 | 长程任务-复杂 | 要求重构一个现有模块（涉及多文件修改） | 重构正确且无回归 |

### 测试脚本位置
创建: `tests/test_opencode_provider.py`

---

## 四、涉及的文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `config.yaml` | 编辑 | 添加 opencode API Key 和模型配置 |
| `HakusAgent/hakus/models/base_client.py` | 编辑 | 添加 OPENCODE 枚举值 |
| `HakusAgent/hakus/models/opencode_client.py` | 新建 | OpenCode 客户端实现 |
| `HakusAgent/hakus/models/client_factory.py` | 编辑 | 注册到工厂和 fallback |
| `HakusAgent/hakus/models/provider_registry.py` | 编辑 | 注册到 UI 列表 |
| `HakusAgent/hakus/models/__init__.py` | 编辑 | 更新导出 |
| `utils/hakus_config.py` | 编辑 | 配置加载支持 opencode |
| `tests/test_opencode_provider.py` | 新建 | 集成测试脚本 |

---

## 五、假设与决策

1. **API 格式假设**: OpenCode Zen 使用标准 OpenAI Chat Completions API 格式（基于文档确认）
2. **Base URL**: 使用 `https://api.opencode.ai/v1`，如不通则根据实际错误调整
3. **模型名称**: 用户指定的 `deepseek-v4-flash-free`
4. **Fallback 策略**: 将 OpenCode 加入 fallback 链末尾（作为备选而非首选）
5. **默认模型不切换**: 不改变 `default_model: deepseek`，用户可通过 `/model opencode` 手动切换

## 六、验证步骤

1. 运行 Python 导入测试: `from hakus.models.opencode_client import OpenCodeClient` 无报错
2. 运行工厂创建测试: `create_client("opencode")` 返回 `OpenCodeClient` 实例
3. 发送实际 API 请求验证连通性和响应质量
4. 运行长程任务测试脚本，检查完整执行链路
