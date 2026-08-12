"""
TUI v2 — Plan 模式自然语言 yes/no 检测测试
"""
from __future__ import annotations

import pytest

from hakus.tui_v2.plan_detection import is_plan_yes, is_plan_no


class TestYesDetection:
    def test_yes(self):
        assert is_plan_yes("yes")
        assert is_plan_yes("Yes")
        assert is_plan_yes("YES")
        assert is_plan_yes(" y ")

    def test_chinese_yes(self):
        assert is_plan_yes("好")
        assert is_plan_yes("好的")
        assert is_plan_yes("可以")
        assert is_plan_yes("同意")
        assert is_plan_yes("批准")
        assert is_plan_yes("继续")
        assert is_plan_yes("做吧")
        assert is_plan_yes("没问题")
        assert is_plan_yes("确认")

    def test_emoji_yes(self):
        assert is_plan_yes("👍")
        assert is_plan_yes("✓")

    def test_english_phrases(self):
        assert is_plan_yes("ok")
        assert is_plan_yes("OK")
        assert is_plan_yes("proceed")
        assert is_plan_yes("go ahead")
        assert is_plan_yes("please proceed")
        assert is_plan_yes("please")

    def test_y_short(self):
        assert is_plan_yes("y")

    def test_no_meaning(self):
        assert not is_plan_yes("不")
        assert not is_plan_yes("no")
        assert not is_plan_yes("取消")
        assert not is_plan_yes("午餐")
        # 含义为"否"的不应被识别为 yes
        assert not is_plan_yes("don't proceed")


class TestNoDetection:
    def test_no(self):
        assert is_plan_no("no")
        assert is_plan_no("NO")
        assert is_plan_no("No")

    def test_chinese_no(self):
        assert is_plan_no("不")
        assert is_plan_no("不要")
        assert is_plan_no("拒绝")
        assert is_plan_no("取消")
        assert is_plan_no("不行")
        assert is_plan_no("不要继续")

    def test_emoji_no(self):
        assert is_plan_no("❌")
        assert is_plan_no("✗")

    def test_english_no(self):
        assert is_plan_no("stop")
        assert is_plan_no("don't")
        assert is_plan_no("do not")
        assert is_plan_no("no thanks")

    def test_n_short(self):
        assert is_plan_no("n")

    def test_yes_not_misclassified(self):
        assert not is_plan_no("yes")
        assert not is_plan_no("好")
        assert not is_plan_no("👍")


def test_yes_no_disjoint():
    """yes 和 no 不应重叠 — 一句话不可能同时被识别为两者."""
    test_inputs = [
        "yes", "no", "好", "不", "y", "n", "ok", "stop", "✓", "✗", "继续", "取消",
        "approve", "reject", "please", "don't", "👍", "❌", "做吧", "不要继续",
    ]
    for t in test_inputs:
        yes = is_plan_yes(t)
        no = is_plan_no(t)
        assert not (yes and no), f"Both yes and no matched: {t!r}"
