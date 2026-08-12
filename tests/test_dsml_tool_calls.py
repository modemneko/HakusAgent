"""
Regression test for DSML tool-call handling.

Bug: DeepSeek models stream raw DSML XML in the content (e.g.
`<｜｜DSML｜｜invoke name="Tree">...`) instead of using the OpenAI
`tools` field. The agent must (1) hide this XML from the user and
(2) convert it to structured tool_calls that get executed.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hakus.agent import (
    _parse_dsml_calls,
    _strip_dsml_xml,
    _strip_tool_directives,
)


# Sample DSML block as produced by DeepSeek
SAMPLE = (
    "我来探索当前项目并分析改进点。\n\n"
    '<｜｜DSML｜｜tool_calls>\n'
    '<｜｜DSML｜｜invoke name="Tree">\n'
    '<｜｜DSML｜｜parameter name="dir_path" string="true">'
    'C:\\Users\\Think\\Desktop\\HakusAI_chat'
    '</｜｜DSML｜｜parameter>\n'
    '<｜｜DSML｜｜parameter name="depth" string="true">2</｜｜DSML｜｜parameter>\n'
    '</｜｜DSML｜｜invoke>\n'
    '<｜｜DSML｜｜invoke name="Glob">\n'
    '<｜｜DSML｜｜parameter name="pattern" string="true">**/*.py</｜｜DSML｜｜parameter>\n'
    '<｜｜DSML｜｜parameter name="path" string="true">'
    'C:\\Users\\Think\\Desktop\\HakusAI_chat'
    '</｜｜DSML｜｜parameter>\n'
    '</｜｜DSML｜｜invoke>\n'
    '</｜｜DSML｜｜tool_calls>'
)


def test_parse_dsml_calls_basic():
    calls, leftover = _parse_dsml_calls(SAMPLE)
    assert len(calls) == 2, f"Expected 2 calls, got {len(calls)}"
    assert calls[0]["name"] == "Tree"
    assert calls[0]["arguments"]["dir_path"] == "C:\\Users\\Think\\Desktop\\HakusAI_chat"
    assert calls[0]["arguments"]["depth"] == "2"
    assert calls[1]["name"] == "Glob"
    assert calls[1]["arguments"]["pattern"] == "**/*.py"
    assert "DSML" not in leftover, f"DSML leaked into leftover: {leftover!r}"
    assert "我来探索" in leftover, f"Original text missing: {leftover!r}"


def test_parse_dsml_calls_empty():
    calls, leftover = _parse_dsml_calls("")
    assert calls == []
    assert leftover == ""


def test_parse_dsml_calls_no_dsml():
    text = "Hello world, no tool calls here."
    calls, leftover = _parse_dsml_calls(text)
    assert calls == []
    assert leftover == text


def test_strip_tool_directives_removes_dsml():
    text = (
        "Hello\n"
        '<｜｜DSML｜｜tool_calls>\n<｜｜DSML｜｜invoke name="X">'
        '</｜｜DSML｜｜invoke>\n</｜｜DSML｜｜tool_calls>\n'
        "World"
    )
    out = _strip_tool_directives(text)
    assert "DSML" not in out
    assert "Hello" in out
    assert "World" in out


def test_strip_dsml_xml_passes_clean_text():
    """Plain text without any DSML tokens should pass through unchanged."""
    delta = "Hello world"
    full = "Hello world"
    out = _strip_dsml_xml(delta, full)
    assert out == delta


def test_strip_dsml_xml_hides_unclosed_block():
    """While the DSML block is still open, suppress output entirely."""
    full = 'partial response <｜｜DSML｜｜tool_calls>in-progress'
    out = _strip_dsml_xml("more", full)
    assert out == "", f"Expected empty, got {out!r}"


def test_strip_dsml_xml_emits_after_close():
    """After the DSML block closes, emit the trailing text."""
    full = "before <｜｜DSML｜｜tool_calls>XML</｜｜DSML｜｜tool_calls>after"
    out = _strip_dsml_xml("ignored", full)
    assert "after" in out
    assert "DSML" not in out
    assert "before" not in out, "Trailing before-DSML text should not re-emit"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
