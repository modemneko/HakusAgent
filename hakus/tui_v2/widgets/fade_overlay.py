from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static


class FadeOverlay(Widget):
    """A gradient fade overlay that creates an OpenClaw-style fading effect.

    Renders at the top or bottom of a scrollable area, making text
    appear to fade into the background color.
    """

    DEFAULT_CSS = """
    FadeOverlay {
        width: 100%;
        height: 3;
        dock: top;  /* overridden by position parameter */
        background: transparent;
    }
    FadeOverlay.-top {
        dock: top;
    }
    FadeOverlay.-bottom {
        dock: bottom;
    }
    FadeOverlay.-hidden {
        display: none;
    }
    """

    def __init__(
        self,
        position: str = "top",
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._position = position
        self._visible = False

    def on_mount(self) -> None:
        self.set_class(True, f"-{self._position}")
        self.set_class(True, "-hidden")

    def show(self) -> None:
        if not self._visible:
            self._visible = True
            self.set_class(False, "-hidden")
            self.refresh()

    def hide(self) -> None:
        if self._visible:
            self._visible = False
            self.set_class(True, "-hidden")

    def render(self):
        """Render the fade effect using Rich colored spaces."""
        if not self._visible:
            return ""

        from rich.text import Text
        from rich.style import Style

        # Background color: #0a0a0a (OpenCode base)
        bg_r, bg_g, bg_b = 0x0a, 0x0a, 0x0a

        # Foreground (normal text) color: #eeeeee (OpenCode text)
        fg_r, fg_g, fg_b = 0xee, 0xee, 0xee

        # Number of fade lines (matches height: 3)
        fade_lines = 3

        if self._position == "top":
            # Top: fully opaque bg at top, gradually transparent toward bottom
            # Line 0: 90% bg, Line 1: 60% bg, Line 2: 30% bg
            opacities = [0.90, 0.60, 0.30]
        else:
            # Bottom: 30% bg at top, 60% bg, fully opaque at bottom
            opacities = [0.30, 0.60, 0.90]

        # Get terminal width
        try:
            width = self.size.width
        except Exception:
            width = 80

        if width <= 0:
            width = 80

        lines = []
        for opacity in opacities:
            # Blend foreground and background based on opacity
            r = int(fg_r * (1 - opacity) + bg_r * opacity)
            g = int(fg_g * (1 - opacity) + bg_g * opacity)
            b = int(fg_b * (1 - opacity) + bg_b * opacity)

            # Use a block character that matches the blended color
            # This creates a "fog" effect over the text underneath
            color = f"#{r:02x}{g:02x}{b:02x}"
            style = Style(color=color, bgcolor=f"#{bg_r:02x}{bg_g:02x}{bg_b:02x}")

            # Fill the line with block characters
            line = Text("█" * width, style=style)
            lines.append(line)

        # Combine lines with newlines
        result = Text()
        for i, line in enumerate(lines):
            if i > 0:
                result.append("\n")
            result.append(line)

        return result
