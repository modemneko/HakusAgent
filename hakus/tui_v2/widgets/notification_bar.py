"""
NotificationBar — 通知横幅 (Claude Code 风格)

- 显示单行通知消息 (例如: "Opus 4.8 is now available! · /model to switch")
- 左侧粉色竖线指示器
- 按任意键或点击可关闭
- 默认隐藏, 调用 show() 时显示
"""
from __future__ import annotations

from textual.widgets import Static


class NotificationBar(Static):
    """通知横幅 (固定 1 行, 默认隐藏).

    使用方式:
        bar = NotificationBar()
        bar.show("[bold #ff006e]Opus 4.8 is now available![/] · /model to switch")
        bar.dismiss()
    """

    DEFAULT_CSS = """
    NotificationBar {
        background: #1e1e1e;
        border-left: thick #fab283;
        color: #eeeeee;
        height: 1;
        padding: 0 2;
        display: none;
    }

    NotificationBar.visible {
        display: block;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(markup=True, **kwargs)

    def show(self, message: str) -> None:
        """显示通知.

        Args:
            message: 通知内容, 支持 Rich markup 格式
        """
        self.update(message)
        self.add_class("visible")

    def dismiss(self) -> None:
        """隐藏通知."""
        self.remove_class("visible")

    def on_key(self, event) -> None:
        """按任意键关闭通知 (修饰键除外).

        修饰键 (ctrl, alt, shift 等) 不触发关闭, 避免误操作.
        """
        # 跳过修饰键
        if event.key in ("ctrl", "alt", "shift", "super", "hyper", "meta"):
            return
        # 跳过组合键 (例如 ctrl+c)
        if hasattr(event, "is_modifier") and event.is_modifier:
            return
        self.dismiss()

    def on_click(self, event) -> None:
        """点击关闭通知."""
        self.dismiss()
