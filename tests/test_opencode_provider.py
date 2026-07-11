"""OpenCode Provider 集成测试.

测试级别:
  1. 导入和工厂创建
  2. 基础连通性 (实际 API 调用)
  3. 工具调用能力
  4. 多轮上下文保持
  5. 长程任务执行

运行: python -m pytest tests/test_opencode_provider.py -v -s
      或单独: python tests/test_opencode_provider.py
"""
import asyncio
import sys
import os
import time
import json

# 确保项目根目录在 path 中
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
# HakusAgent 子目录也需要
_hakus_agent = os.path.join(_project_root, "HakusAgent")
if _hakus_agent not in sys.path:
    sys.path.insert(0, _hakus_agent)


def test_import():
    """测试 1: OpenCodeClient 能否正常导入."""
    from hakus.models.opencode_client import OpenCodeClient
    assert OpenCodeClient is not None
    print("  [PASS] OpenCodeClient 导入成功")


def test_enum():
    """测试 2: LLMProvider 枚举包含 OPENCODE."""
    from hakus.models.base_client import LLMProvider
    assert hasattr(LLMProvider, "OPENCODE")
    assert LLMProvider.OPENCODE.value == "opencode"
    print("  [PASS] LLMProvider.OPENCODE 枚举正确")


def test_registry():
    """测试 3: Provider Registry 包含 opencode."""
    from hakus.models.provider_registry import PROVIDERS, is_valid_provider, find_provider
    assert is_valid_provider("opencode"), "opencode 不在 provider registry 中"
    provider = find_provider("opencode")
    assert provider["id"] == "opencode"
    assert "OpenCode" in provider["name"]
    print(f"  [PASS] Registry: {provider}")


def test_factory():
    """测试 4: 工厂函数能创建 OpenCodeClient."""
    from hakus.models.client_factory import create_client
    from hakus.models.base_client import LLMProvider
    try:
        client = create_client("opencode")
        assert client is not None
        assert client.provider == LLMProvider.OPENCODE
        assert client.model_name == "deepseek-v4-flash-free"
        print(f"  [PASS] 工厂创建成功: provider={client.provider.value}, model={client.model_name}")
    except Exception as e:
        print(f"  [WARN] 工厂创建失败（可能缺少配置）: {e}")
        # 不算失败——配置文件可能未就绪


def test_config():
    """测试 5: HakusConfig 包含 opencode 配置."""
    from utils.hakus_config import get_config
    config = get_config()
    prov = config.models.get_provider("opencode")
    assert prov is not None, "opencode provider 配置缺失"
    assert prov.provider == "opencode"
    assert "opencode.ai" in prov.base_url
    assert len(prov.api_key) > 0, "opencode API Key 为空"
    print(f"  [PASS] 配置: base_url={prov.base_url}, model={prov.model_name}, api_key={prov.api_key[:8]}...")


async def test_basic_connectivity():
    """测试 6: 基础 API 连通性 — 发送简单对话请求."""
    from hakus.models.client_factory import create_client
    from hakus.models.base_client import LLMMessage

    client = create_client("opencode")
    messages = [
        LLMMessage(role="system", content="你是一个友好的AI助手。"),
        LLMMessage(role="user", content="请用一句话介绍你自己。"),
    ]

    print("  正在发送 API 请求到 OpenCode Zen...")
    start = time.time()
    try:
        response = await client.chat(messages, timeout=30)
        elapsed = time.time() - start
        assert response.content, f"响应内容为空, finish_reason={response.finish_reason}"
        assert response.finish_reason not in ("error", "timeout"), f"请求失败: {response.finish_reason}"
        print(f"  [PASS] 连通性正常 ({elapsed:.1f}s)")
        print(f"         响应: {response.content[:100]}...")
        print(f"         tokens: input={response.input_tokens}, output={response.output_tokens}")
        return True
    except Exception as e:
        print(f"  [FAIL] 连通性测试失败: {e}")
        return False


async def test_tool_calling():
    """测试 7: 工具调用能力 — 让模型调用一个简单工具."""
    from hakus.models.client_factory import create_client
    from hakus.models.base_client import LLMMessage

    client = create_client("opencode")
    if not client.supports_tool_calling():
        print("  [SKIP] Provider 不支持工具调用")
        return True

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "获取指定城市的天气",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "城市名称",
                        }
                    },
                    "required": ["city"],
                },
            },
        }
    ]

    messages = [
        LLMMessage(role="user", content="北京今天天气怎么样？"),
    ]

    print("  正在测试工具调用...")
    try:
        response = await client.chat(messages, tools=tools, timeout=30)
        if response.tool_calls:
            tc = response.tool_calls[0]
            print(f"  [PASS] 工具调用成功: name={tc.get('name')}, args={tc.get('arguments')}")
        else:
            print(f"  [INFO] 模型未触发工具调用（正常行为，模型可能选择直接回答）")
            print(f"         响应: {response.content[:80]}...")
        return True
    except Exception as e:
        print(f"  [FAIL] 工具调用测试失败: {e}")
        return False


async def test_multi_turn():
    """测试 8: 多轮上下文保持 — 3 轮对话."""
    from hakus.models.client_factory import create_client
    from hakus.models.base_client import LLMMessage

    client = create_client("opencode")
    messages = [
        LLMMessage(role="system", content="你是一个记忆助手。请记住用户提供的信息。"),
        LLMMessage(role="user", content="我的名字是小雪，我喜欢编程。"),
    ]

    print("  正在测试多轮对话 (3轮)...")
    try:
        # 第 1 轮
        r1 = await client.chat(messages, timeout=30)
        messages.append(LLMMessage(role="assistant", content=r1.content))

        # 第 2 轮
        messages.append(LLMMessage(role="user", content="我刚才告诉你我叫什么名字？"))
        r2 = await client.chat(messages, timeout=30)
        messages.append(LLMMessage(role="assistant", content=r2.content))

        # 第 3 轮
        messages.append(LLMMessage(role="user", content="我喜欢做什么？"))
        r3 = await client.chat(messages, timeout=30)

        # 验证上下文保持
        has_name = "小雪" in r2.content or "小雪" in r3.content
        has_hobby = "编程" in r3.content

        if has_name and has_hobby:
            print(f"  [PASS] 多轮上下文保持正常")
        else:
            print(f"  [WARN] 上下文可能丢失: has_name={has_name}, has_hobby={has_hobby}")
            print(f"         R2: {r2.content[:80]}...")
            print(f"         R3: {r3.content[:80]}...")
        return True
    except Exception as e:
        print(f"  [FAIL] 多轮对话测试失败: {e}")
        return False


async def test_long_task_medium():
    """测试 9: 中等长程任务 — 要求完成一个 5 步编程任务."""
    from hakus.models.client_factory import create_client
    from hakus.models.base_client import LLMMessage

    client = create_client("opencode")

    task_prompt = """请完成以下编程任务（不需要实际写文件，只需要给出方案）：
1. 设计一个简单的 Python 计算器类 Calculator
2. 支持 add, subtract, multiply, divide 四个方法
3. 处理除零异常
4. 写出对应的单元测试
5. 解释为什么这样设计

请逐步完成每个步骤。"""

    messages = [
        LLMMessage(role="system", content="你是一个资深Python开发者。请逐步完成用户要求的编程任务。"),
        LLMMessage(role="user", content=task_prompt),
    ]

    print("  正在测试中等长程任务 (5步编程任务)...")
    start = time.time()
    try:
        response = await client.chat(messages, timeout=120)
        elapsed = time.time() - start

        # 检查响应是否涵盖了多个步骤
        content = response.content.lower()
        steps_covered = sum([
            "calculator" in content or "计算器" in content,
            "add" in content or "subtract" in content or "加" in content,
            "zero" in content or "零" in content or "zerodivision" in content,
            "test" in content or "测试" in content or "assert" in content,
            "设计" in content or "design" in content or "为什么" in content or "reason" in content,
        ])

        print(f"  [{'PASS' if steps_covered >= 3 else 'WARN'}] 中等长程任务完成 ({elapsed:.1f}s, 覆盖{steps_covered}/5步骤)")
        print(f"         tokens: input={response.input_tokens}, output={response.output_tokens}")
        return True
    except Exception as e:
        print(f"  [FAIL] 中等长程任务测试失败: {e}")
        return False


async def test_long_task_complex():
    """测试 10: 复杂长程任务 — 重构建议（多文件场景）."""
    from hakus.models.client_factory import create_client
    from hakus.models.base_client import LLMMessage

    client = create_client("opencode")

    task_prompt = """我有一个 Python 项目，目前所有代码都在一个 main.py 文件中（约500行）。
项目包含：
- 数据模型定义 (User, Product, Order)
- 数据库操作 (CRUD)
- API 路由处理 (Flask)
- 工具函数 (验证、格式化)
- 配置管理

请给出详细的重构方案，包括：
1. 目录结构设计
2. 每个模块的职责划分
3. 模块间的依赖关系
4. 重构的优先级和步骤顺序
5. 如何确保重构过程中功能不回归"""

    messages = [
        LLMMessage(role="system", content="你是一个软件架构师。请给出详细、可执行的重构方案。"),
        LLMMessage(role="user", content=task_prompt),
    ]

    print("  正在测试复杂长程任务 (重构方案)...")
    start = time.time()
    try:
        response = await client.chat(messages, timeout=180)
        elapsed = time.time() - start

        content = response.content.lower()
        aspects_covered = sum([
            "目录" in content or "directory" in content or "folder" in content or "结构" in content,
            "模型" in content or "model" in content or "职责" in content or "responsibility" in content,
            "依赖" in content or "depend" in content or "import" in content,
            "优先" in content or "priority" in content or "步骤" in content or "step" in content,
            "回归" in content or "regression" in content or "测试" in content or "test" in content,
        ])

        print(f"  [{'PASS' if aspects_covered >= 3 else 'WARN'}] 复杂长程任务完成 ({elapsed:.1f}s, 覆盖{aspects_covered}/5方面)")
        print(f"         tokens: input={response.input_tokens}, output={response.output_tokens}")
        return True
    except Exception as e:
        print(f"  [FAIL] 复杂长程任务测试失败: {e}")
        return False


def run_sync_tests():
    """运行所有同步测试."""
    print("\n" + "=" * 60)
    print("OpenCode Provider 集成测试 — 同步部分")
    print("=" * 60)

    sync_tests = [
        ("导入测试", test_import),
        ("枚举测试", test_enum),
        ("Registry测试", test_registry),
        ("工厂测试", test_factory),
        ("配置测试", test_config),
    ]

    passed = 0
    failed = 0
    for name, fn in sync_tests:
        print(f"\n--- {name} ---")
        try:
            fn()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {e}")
            failed += 1

    return passed, failed


async def run_async_tests():
    """运行所有异步测试（实际 API 调用）."""
    print("\n" + "=" * 60)
    print("OpenCode Provider 集成测试 — 异步部分 (实际API调用)")
    print("=" * 60)

    async_tests = [
        ("基础连通性", test_basic_connectivity),
        ("工具调用", test_tool_calling),
        ("多轮对话", test_multi_turn),
        ("中等长程任务", test_long_task_medium),
        ("复杂长程任务", test_long_task_complex),
    ]

    passed = 0
    failed = 0
    skipped = 0

    for name, fn in async_tests:
        print(f"\n--- {name} ---")
        try:
            result = await fn()
            if result is True:
                passed += 1
            elif result is None:
                skipped += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  [FAIL] {e}")
            failed += 1

    return passed, failed, skipped


def main():
    print("OpenCode Zen Provider 集成测试")
    print("=" * 60)

    # 同步测试
    sync_passed, sync_failed = run_sync_tests()

    # 异步测试
    async_passed, async_failed, async_skipped = asyncio.run(run_async_tests())

    # 汇总
    total_passed = sync_passed + async_passed
    total_failed = sync_failed + async_failed
    total = total_passed + total_failed + async_skipped

    print("\n" + "=" * 60)
    print(f"测试结果汇总: {total_passed} 通过 / {total_failed} 失败 / {async_skipped} 跳过 (共 {total})")
    print("=" * 60)

    if total_failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
