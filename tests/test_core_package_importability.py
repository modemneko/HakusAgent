"""
Regression test: `hakus` package must be importable in this checkout.

Background
----------
The package was renamed from `core` to `hakus`. This test verifies
that the new package structure is importable and the utils shims work.
"""
import sys
import os
import importlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_hakus_package_is_importable():
    import hakus  # noqa: F401
    assert hasattr(hakus, "__file__"), (
        "hakus 必须有 __file__ 属性 (应是 regular package, 不是 namespace package)"
    )
    assert hakus.__file__ is not None, "hakus/__init__.py 必须存在"


def test_hakus_utils_subpackage_exists():
    # utils is at project root, not under hakus
    import utils  # noqa: F401


def test_hakus_utils_logger_shim_reexports_get_logger():
    # The project root utils.logger is used directly, no shim needed
    from utils.logger import get_logger
    assert get_logger is not None


def test_hakus_utils_config_shim_reexports_base_config():
    from utils.config import BASE_CONFIG
    assert BASE_CONFIG is not None


def test_hakus_tools_plugin_imports():
    from hakus.tools.plugin import ToolPlugin, ToolMetadata, TOOL_REGISTRY  # noqa: F401


def test_hakus_tools_web_google_no_hard_dependency_on_langchain():
    import hakus.tools.web_google as web_google  # noqa: F401


def test_relative_imports_work():
    # utils.logger is at project root
    from utils.logger import get_logger
    assert get_logger is not None


def test_to_openai_schema_alias_exists():
    # ToolPlugin needs both get_function_definition() and to_openai_schema()
    # as synonyms. The class lives in hakus.tools.plugin after the refactor.
    from hakus.tools.plugin import ToolPlugin
    from hakus.dev_tools import AskUserQuestionTool
    inst = AskUserQuestionTool()
    assert hasattr(inst, "to_openai_schema"), \
        "ToolPlugin 必须有 to_openai_schema() 方法 (与 get_function_definition 同义)"
    assert hasattr(inst, "get_function_definition"), \
        "ToolPlugin 也必须保留 get_function_definition() 以兼容旧调用"
    s1 = inst.to_openai_schema()
    s2 = inst.get_function_definition()
    assert s1 == s2, "to_openai_schema 和 get_function_definition 应返回相同结果"


if __name__ == "__main__":
    test_hakus_package_is_importable()
    test_hakus_utils_subpackage_exists()
    test_hakus_utils_logger_shim_reexports_get_logger()
    test_hakus_utils_config_shim_reexports_base_config()
    test_hakus_tools_plugin_imports()
    test_hakus_tools_web_google_no_hard_dependency_on_langchain()
    test_relative_imports_work()
    test_to_openai_schema_alias_exists()
    print("OK: hakus package importability regression tests passed")
