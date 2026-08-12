"""
验证 ToolRegistry.get_schemas() 在 Tool + ToolPlugin 混合注册时正常工作。
"""
import sys
import os
import asyncio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_get_schemas_mixed_tools():
    from hakus.tools import ToolRegistry
    from hakus.tools.builtin import ReadFile
    from hakus.dev_tools import (
        ReadTool, WriteTool, AskUserQuestionTool, BashTool, TreeTool,
    )

    registry = ToolRegistry()
    registry.register_builtin()
    n = 0
    for t in [ReadTool(), WriteTool(), AskUserQuestionTool(), BashTool(), TreeTool()]:
        registry.register(t)
        n += 1
    print(f"已注册: builtin + {n} dev_tool_plugin")

    schemas = registry.get_schemas()
    print(f"get_schemas() 返回 {len(schemas)} 个 schema")
    assert len(schemas) > 0, "应能拿到至少一个 schema"

    for s in schemas[:3]:
        assert s.get("type") == "function", f"schema 缺 type=function: {s}"
        assert "function" in s
        assert "name" in s["function"]
        assert "parameters" in s["function"]
        print(f"  - {s['function']['name']}")

    ask = next((s for s in schemas if s["function"]["name"] == "AskUserQuestion"), None)
    assert ask is not None, "AskUserQuestion schema 必须存在"
    assert "question" in ask["function"]["parameters"]["properties"]
    assert "options" in ask["function"]["parameters"]["properties"]
    print(f"✓ AskUserQuestion schema: {list(ask['function']['parameters']['properties'].keys())}")


def test_to_openai_schema_alias():
    from hakus.dev_tools import AskUserQuestionTool, BashTool

    for instance in [AskUserQuestionTool(), BashTool()]:
        assert hasattr(instance, "to_openai_schema"), \
            f"{type(instance).__name__} 必须有 to_openai_schema"
        s = instance.to_openai_schema()
        assert s["type"] == "function"
        assert s["function"]["name"] == instance.get_metadata().name
    print("✓ ToolPlugin.to_openai_schema 通用接口正常")


def test_specific_tool_with_real_agent():
    """直接模拟 entry.py 注册路径"""
    from hakus.tools import ToolRegistry
    from hakus.dev_tools import register_dev_tools

    registry = ToolRegistry()
    registry.register_builtin()
    n = register_dev_tools(registry)
    print(f"register_dev_tools 注册了 {n} 个")

    schemas = registry.get_schemas()
    names = sorted([s["function"]["name"] for s in schemas])
    print(f"全部 schema 名称 ({len(names)}): {names}")
    assert "AskUserQuestion" in names
    assert "Read" in names
    assert "Bash" in names
    print(f"✅ 混合注册后所有 schema 正常生成，共 {len(schemas)} 个")


def test_entry_tool_registration_no_snake_case_duplicates():
    from hakus.tools import ToolRegistry
    from hakus.dev_tools import register_dev_tools

    registry = ToolRegistry()
    n = register_dev_tools(registry)
    assert n > 0

    schemas = registry.get_schemas()
    names = [s["function"]["name"] for s in schemas]
    assert "Read" in names
    assert "Bash" in names
    assert "AskUserQuestion" in names
    assert "read_file" not in names
    print(f"✓ entry 风格注册: {len(names)} 工具, 无 snake_case 文件工具重复")


def test_websearch_import_path():
    """WebSearch should not use search_web_aggregator."""
    import inspect
    from hakus.tools.builtin.web import WebSearch

    source = inspect.getsource(WebSearch.execute)
    assert "search_web_aggregator" not in source
    assert "_duckduckgo_search" in source
    print("✓ WebSearch uses _duckduckgo_search (single backend)")


if __name__ == "__main__":
    test_to_openai_schema_alias()
    test_get_schemas_mixed_tools()
    test_specific_tool_with_real_agent()
    test_entry_tool_registration_no_snake_case_duplicates()
    test_websearch_import_path()
    print("\n🎉 ToolRegistry 混合 Tool/ToolPlugin 验证通过")
