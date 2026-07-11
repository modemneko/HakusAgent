import pytest
from textual.app import App, ComposeResult


class _TestApp(App[str]):
    def compose(self) -> ComposeResult:
        yield from ()


@pytest.mark.asyncio
async def test_model_overlay_keyboard_selection():
    """ModelOverlay 应支持键盘选择并返回模型 id."""
    from hakus.tui_v2.overlays.model_overlay import ModelOverlay

    result = []
    app = _TestApp()

    def on_dismiss(value: str | None) -> None:
        result.append(value)

    async with app.run_test() as pilot:
        overlay = ModelOverlay(current_model="opencode")
        pilot.app.push_screen(overlay, on_dismiss)
        await pilot.pause()
        # 按 down 移到 deepseek
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()

    assert result == ["deepseek"]


@pytest.mark.asyncio
async def test_model_overlay_filter():
    """ModelOverlay 应支持过滤."""
    from hakus.tui_v2.overlays.model_overlay import ModelOverlay

    result = []
    app = _TestApp()

    def on_dismiss(value: str | None) -> None:
        result.append(value)

    async with app.run_test() as pilot:
        overlay = ModelOverlay(current_model="opencode")
        pilot.app.push_screen(overlay, on_dismiss)
        await pilot.pause()
        await pilot.press("q", "w", "e", "n")
        await pilot.press("enter")
        await pilot.pause()

    assert result == ["qwen"]


@pytest.mark.asyncio
async def test_permission_dialog_buttons():
    """PermissionDialog 应返回中文按钮对应的内部值."""
    from hakus.tui_v2.app import PermissionDialog

    result = []
    app = _TestApp()

    def on_dismiss(value: str | None) -> None:
        result.append(value)

    async with app.run_test() as pilot:
        dialog = PermissionDialog("bash", {"reason": "Dangerous tool execution: Bash", "detail": "ls"})
        pilot.app.push_screen(dialog, on_dismiss)
        await pilot.pause()
        # 默认选中"允许一次", 按 Enter
        await pilot.press("enter")
        await pilot.pause()

    assert result == ["once"]


@pytest.mark.asyncio
async def test_permission_dialog_navigate():
    """PermissionDialog 应支持左右切换按钮."""
    from hakus.tui_v2.app import PermissionDialog

    result = []
    app = _TestApp()

    def on_dismiss(value: str | None) -> None:
        result.append(value)

    async with app.run_test() as pilot:
        dialog = PermissionDialog("tool", {"reason": "Dangerous tool execution"})
        pilot.app.push_screen(dialog, on_dismiss)
        await pilot.pause()
        await pilot.press("right", "right", "enter")
        await pilot.pause()

    assert result == ["deny"]
