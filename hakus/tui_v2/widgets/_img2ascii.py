"""
将图片转为终端半块字符像素艺术
- 每个终端字符位置 = 2个垂直像素 (上▀ + 下▄ 用单字符前景/背景色)
- 分辨率: 70列宽 × ~36行高
"""
from PIL import Image
import numpy as np
import os

IMG_PATH = r"C:\Users\Think\Desktop\ChatGPT Image 2026年6月20日 23_40_20.png"


def _hex(r, g, b):
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"


def image_to_rich_pixels_text(img_path, max_width=70):
    """将图片转为 rich markup 格式的半块字符像素艺术.

    核心: 每个终端列用单个 ▀ 字符, 前景色=上像素, 背景色=下像素.
    这样 70 列宽 = 70 像素宽 (不是 140).
    """
    img = Image.open(img_path).convert("RGBA")
    w, h = img.size

    # 终端字符宽高比约 1:2, 高度需除以2
    new_w = max_width
    pixel_h = int(new_w * (h / w) * 0.5)
    if pixel_h % 2 != 0:
        pixel_h += 1  # 确保偶数行

    img = img.resize((new_w, pixel_h), Image.LANCZOS)
    arr = np.array(img)

    # 判断是否有透明通道
    has_alpha = arr[:, :, 3].mean() < 250

    def is_bg(r, g, b, a):
        """判断是否为背景像素 (透明或白色)."""
        if has_alpha and a < 128:
            return True
        if not has_alpha:
            brightness = (int(r) + int(g) + int(b)) / 3
            max_c = max(int(r), int(g), int(b))
            min_c = min(int(r), int(g), int(b))
            sat = (max_c - min_c) / (max_c + 1) if max_c > 0 else 0
            if brightness > 220 and sat < 0.15:
                return True
        return False

    lines = []
    for y in range(0, pixel_h, 2):
        line_parts = []
        for x in range(new_w):
            r1, g1, b1, a1 = arr[y, x]
            if y + 1 < pixel_h:
                r2, g2, b2, a2 = arr[y + 1, x]
            else:
                r2, g2, b2, a2 = r1, g1, b1, a1

            bg1 = is_bg(r1, g1, b1, a1)
            bg2 = is_bg(r2, g2, b2, a2)

            if bg1 and bg2:
                # 两个都是背景 → 空格
                line_parts.append(" ")
            elif bg1 and not bg2:
                # 只有下半有色 → ▄ (下半块, 前景色)
                c = _hex(r2, g2, b2)
                line_parts.append(f"[{c}]▄[/]")
            elif not bg1 and bg2:
                # 只有上半有色 → ▀ (上半块, 前景色)
                c = _hex(r1, g1, b1)
                line_parts.append(f"[{c}]▀[/]")
            else:
                # 两个都有色 → 单个 ▀, 前景=上, 背景=下
                fg = _hex(r1, g1, b1)
                bg = _hex(r2, g2, b2)
                line_parts.append(f"[{fg} on {bg}]▀[/]")

        lines.append("".join(line_parts))

    # 去除空行
    lines = [line.rstrip() for line in lines]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    return "\n".join(lines)


if __name__ == "__main__":
    result = image_to_rich_pixels_text(IMG_PATH, max_width=70)
    print(result)
    print(f"\n--- Lines: {result.count(chr(10)) + 1} ---")
    out_path = os.path.join(os.path.dirname(__file__), "yuxi_pixels.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(result)
