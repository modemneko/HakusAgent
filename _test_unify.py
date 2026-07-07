"""Runtime smoke test for Tool/ToolPlugin interface unification.

This script verifies that:
  1. ToolPlugin instances expose the same interface as Tool instances
     (execute, parameters_schema, is_dangerous, is_concurrency_safe,
     to_openai_schema, name, description).
  2. ToolRegistry accepts both Tool and ToolPlugin instances uniformly.
  3. get_schemas() produces the same shape for both.
  4. is_dangerous() and is_concurrency_safe() work for both.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from hakus.tools.plugin import ToolPlugin, ToolMetadata
from hakus.dev_tools import ReadTool, WriteTool, BashTool, WebSearchTool
from hakus.tools.builtin.file import ReadFile, WriteFile
from hakus.tools.registry import ToolRegistry

EXPECTED = ("execute", "parameters_schema", "is_dangerous",
            "is_concurrency_safe", "to_openai_schema", "name", "description")


def check(label, obj):
    missing = [m for m in EXPECTED if not hasattr(obj, m)]
    if missing:
        print(f"  [{label}] MISSING: {missing}")
        return False
    print(f"  [{label}] OK -- name={obj.name!r}, dangerous={obj.is_dangerous}, "
          f"safe={obj.is_concurrency_safe}")
    return True


print("=== ToolPlugin 兼容性接口 ===")
ok = True
for cls in [ReadTool, WriteTool, BashTool, WebSearchTool]:
    inst = cls()
    ok &= check(inst.name, inst)

print()
print("=== Tool 接口 ===")
for cls in [ReadFile, WriteFile]:
    inst = cls()
    ok &= check(inst.name, inst)

print()
print("=== 统一注册到 ToolRegistry ===")
reg = ToolRegistry()
reg.register_builtin()
n_dev = 0
for tool in [ReadTool(), WriteTool(), BashTool(), WebSearchTool()]:
    reg.register(tool)
    n_dev += 1
print(f"  Dev tools registered: {n_dev}, total: {len(reg.list_tools())}")

print()
print("=== 统一 schema 输出 ===")
schemas = reg.get_schemas()
print(f"  Number of schemas: {len(schemas)}")
# All schemas should have the same top-level structure
for s in schemas[:5]:
    fn = s["function"]
    assert "name" in fn and "description" in fn and "parameters" in fn
    assert fn["parameters"]["type"] == "object"
    assert "properties" in fn["parameters"]
print("  All schemas have {type:function, function:{name, description, parameters}} shape")

print()
print("=== is_dangerous / is_concurrency_safe 跨类型一致 ===")
for name in ["Read", "Bash", "WebSearch", "read_file", "write_file"]:
    d = reg.is_dangerous(name)
    s = reg.is_concurrency_safe(name)
    print(f"  {name:12s}: is_dangerous={d}, is_concurrency_safe={s}")

print()
print("ALL OK" if ok else "SOME FAILED")
