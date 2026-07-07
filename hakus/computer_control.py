import base64
import io
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger(__name__)

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.1
    _HAS_PYAUTOGUI = True
except ImportError:
    pyautogui = None
    _HAS_PYAUTOGUI = False

try:
    from PIL import ImageGrab, Image
    _HAS_PIL = True
except ImportError:
    ImageGrab = None
    Image = None
    _HAS_PIL = False

try:
    import mss
    _HAS_MSS = True
except ImportError:
    mss = None
    _HAS_MSS = False

try:
    import cv2
    import numpy as np
    _HAS_CV2 = True
except ImportError:
    cv2 = None
    np = None
    _HAS_CV2 = False


class ComputerController:
    ACTION_DELAY = 0.1

    def __init__(self, action_delay: float = 0.1):
        self._delay = action_delay
        if _HAS_PYAUTOGUI:
            pyautogui.PAUSE = action_delay

    def _safe_delay(self) -> None:
        time.sleep(self._delay)

    def screenshot(self, region: Optional[Tuple[int, int, int, int]] = None) -> Optional[bytes]:
        if _HAS_PIL:
            try:
                if region:
                    img = ImageGrab.grab(bbox=region)
                else:
                    img = ImageGrab.grab()
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                return buf.getvalue()
            except Exception as e:
                logger.warning(f"PIL screenshot failed: {e}")

        if _HAS_MSS:
            try:
                with mss.mss() as sct:
                    if region:
                        monitor = {
                            "left": region[0], "top": region[1],
                            "width": region[2] - region[0], "height": region[3] - region[1],
                        }
                    else:
                        monitor = sct.monitors[1]
                    shot = sct.grab(monitor)
                    return mss.tools.to_png(shot.rgb, shot.size)
            except Exception as e:
                logger.warning(f"mss screenshot failed: {e}")

        logger.error("No screenshot library available (PIL or mss required)")
        return None

    def screenshot_base64(self, region: Optional[Tuple[int, int, int, int]] = None) -> Optional[str]:
        data = self.screenshot(region)
        if data:
            return base64.b64encode(data).decode("utf-8")
        return None

    def screenshot_size(self, region: Optional[Tuple[int, int, int, int]] = None) -> Optional[Tuple[int, int]]:
        if _HAS_PIL:
            try:
                img = ImageGrab.grab(bbox=region)
                return (img.width, img.height)
            except Exception:
                pass
        if _HAS_MSS:
            try:
                with mss.mss() as sct:
                    monitor = sct.monitors[1] if not region else {
                        "left": region[0], "top": region[1],
                        "width": region[2] - region[0], "height": region[3] - region[1],
                    }
                    shot = sct.grab(monitor)
                    return (shot.width, shot.height)
            except Exception:
                pass
        return None

    def click(self, x: int, y: int, button: str = "left") -> str:
        if not _HAS_PYAUTOGUI:
            return "Error: pyautogui not available"
        try:
            pyautogui.click(x=x, y=y, button=button)
            self._safe_delay()
            return f"Clicked at ({x}, {y}) with {button} button"
        except Exception as e:
            return f"Error clicking: {e}"

    def double_click(self, x: int, y: int) -> str:
        if not _HAS_PYAUTOGUI:
            return "Error: pyautogui not available"
        try:
            pyautogui.doubleClick(x=x, y=y)
            self._safe_delay()
            return f"Double-clicked at ({x}, {y})"
        except Exception as e:
            return f"Error double-clicking: {e}"

    def right_click(self, x: int, y: int) -> str:
        if not _HAS_PYAUTOGUI:
            return "Error: pyautogui not available"
        try:
            pyautogui.rightClick(x=x, y=y)
            self._safe_delay()
            return f"Right-clicked at ({x}, {y})"
        except Exception as e:
            return f"Error right-clicking: {e}"

    def type_text(self, text: str, interval: float = 0.02) -> str:
        if not _HAS_PYAUTOGUI:
            return "Error: pyautogui not available"
        try:
            pyautogui.typewrite(text, interval=interval)
            self._safe_delay()
            return f"Typed text ({len(text)} chars)"
        except Exception as e:
            return f"Error typing text: {e}"

    def press_key(self, key: str) -> str:
        if not _HAS_PYAUTOGUI:
            return "Error: pyautogui not available"
        try:
            pyautogui.press(key)
            self._safe_delay()
            return f"Pressed key: {key}"
        except Exception as e:
            return f"Error pressing key: {e}"

    def hotkey(self, *keys: str) -> str:
        if not _HAS_PYAUTOGUI:
            return "Error: pyautogui not available"
        try:
            pyautogui.hotkey(*keys)
            self._safe_delay()
            return f"Pressed hotkey: {'+'.join(keys)}"
        except Exception as e:
            return f"Error pressing hotkey: {e}"

    def scroll(self, direction: str = "down", clicks: int = 3) -> str:
        if not _HAS_PYAUTOGUI:
            return "Error: pyautogui not available"
        try:
            amount = clicks if direction == "down" else -clicks
            pyautogui.scroll(amount)
            self._safe_delay()
            return f"Scrolled {direction} {clicks} clicks"
        except Exception as e:
            return f"Error scrolling: {e}"

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int,
             duration: float = 0.5, button: str = "left") -> str:
        if not _HAS_PYAUTOGUI:
            return "Error: pyautogui not available"
        try:
            pyautogui.moveTo(start_x, start_y)
            pyautogui.drag(
                end_x - start_x, end_y - start_y,
                duration=duration, button=button,
            )
            self._safe_delay()
            return f"Dragged from ({start_x}, {start_y}) to ({end_x}, {end_y})"
        except Exception as e:
            return f"Error dragging: {e}"

    def move_mouse(self, x: int, y: int, duration: float = 0.3) -> str:
        if not _HAS_PYAUTOGUI:
            return "Error: pyautogui not available"
        try:
            pyautogui.moveTo(x, y, duration=duration)
            self._safe_delay()
            return f"Moved mouse to ({x}, {y})"
        except Exception as e:
            return f"Error moving mouse: {e}"

    def get_screen_size(self) -> Optional[Tuple[int, int]]:
        if not _HAS_PYAUTOGUI:
            return None
        try:
            return pyautogui.size()
        except Exception:
            return None

    def find_on_screen(self, template_path: str, confidence: float = 0.9) -> Optional[Tuple[int, int]]:
        if not _HAS_PYAUTOGUI:
            logger.error("pyautogui not available for image matching")
            return None
        if not _HAS_CV2:
            try:
                location = pyautogui.locateOnScreen(template_path, confidence=confidence)
                if location:
                    center = pyautogui.center(location)
                    return (center.x, center.y)
                return None
            except Exception as e:
                logger.warning(f"pyautogui image match failed: {e}")
                return None
        try:
            screenshot_data = self.screenshot()
            if not screenshot_data:
                return None
            img_arr = cv2.imdecode(np.frombuffer(screenshot_data, np.uint8), cv2.IMREAD_COLOR)
            template = cv2.imread(template_path, cv2.IMREAD_COLOR)
            if template is None:
                logger.error(f"Template not found: {template_path}")
                return None
            result = cv2.matchTemplate(img_arr, template, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
            if max_val >= confidence:
                h, w = template.shape[:2]
                center_x = max_loc[0] + w // 2
                center_y = max_loc[1] + h // 2
                return (center_x, center_y)
            return None
        except Exception as e:
            logger.error(f"CV2 image matching failed: {e}")
            return None

    def get_mouse_pos(self) -> Optional[Tuple[int, int]]:
        if not _HAS_PYAUTOGUI:
            return None
        try:
            return pyautogui.position()
        except Exception:
            return None

    @staticmethod
    def check_dependencies() -> Dict[str, bool]:
        return {
            "pyautogui": _HAS_PYAUTOGUI,
            "PIL": _HAS_PIL,
            "mss": _HAS_MSS,
            "cv2": _HAS_CV2,
        }
