#!/usr/bin/env python3
"""Generate NSIS installer BMPs matching HakusAI brand tokens."""

from __future__ import annotations

import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# Brand tokens from hakus-design-tokens.json
ACCENT = (169, 156, 255)  # #a99cff
SURFACE = (23, 23, 29)  # #17171d
SURFACE_RAISED = (32, 32, 40)  # #202028
INK = (247, 246, 251)  # #f7f6fb
MUTED = (168, 166, 180)  # #a8a6b4


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def try_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if bold:
        candidates = [
            r"C:\Windows\Fonts\seguisb.ttf",
            r"C:\Windows\Fonts\segoeuib.ttf",
            r"C:\Windows\Fonts\msyhbd.ttc",
            r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\arialbd.ttf",
            r"C:\Windows\Fonts\arial.ttf",
        ]
    else:
        candidates = [
            r"C:\Windows\Fonts\SegoeUI.ttf",
            r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\arial.ttf",
        ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def make_welcome(path: str) -> None:
    """NSIS MUI welcome sidebar: 164 x 314."""
    width, height = 164, 314
    img = Image.new("RGB", (width, height), SURFACE)
    draw = ImageDraw.Draw(img, "RGBA")

    # Vertical gradient with purple bloom near the logo.
    for y in range(height):
        t = y / (height - 1)
        base = lerp((28, 24, 48), (18, 18, 24), min(1.0, t * 1.15))
        bloom = math.exp(-((t - 0.28) ** 2) / (2 * 0.18**2))
        col = lerp(base, (72, 58, 130), bloom * 0.45)
        draw.line([(0, y), (width, y)], fill=col)

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    cx, cy = width // 2, 108
    for i, radius in enumerate((54, 78, 102, 126)):
        alpha = 28 - i * 5
        od.ellipse(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            outline=(*ACCENT, alpha),
            width=1,
        )
    for i in range(28):
        x = int(-20 + i * 7)
        od.line([(x, 0), (x + 40, height)], fill=(*ACCENT, 6), width=2)
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius=0.6))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")

    # Soft radial glow behind the monogram.
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for radius in range(48, 0, -1):
        alpha = int(18 * (1 - radius / 48) ** 2)
        gd.ellipse(
            [cx - radius, cy - radius, cx + radius, cy + radius],
            fill=(*ACCENT, alpha),
        )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=10))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")

    # Glass ring + filled disc + monogram.
    ring_r = 42
    draw.ellipse(
        [cx - ring_r, cy - ring_r, cx + ring_r, cy + ring_r],
        outline=(*ACCENT, 70),
        width=2,
    )
    draw.ellipse([cx - 36, cy - 36, cx + 36, cy + 36], fill=(40, 34, 72, 220))
    draw.ellipse(
        [cx - 34, cy - 34, cx + 34, cy + 34],
        outline=(*ACCENT, 90),
        width=1,
    )

    h_font = try_font(34, bold=True)
    bbox = draw.textbbox((0, 0), "H", font=h_font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        (cx - tw / 2 - bbox[0], cy - th / 2 - bbox[1]),
        "H",
        font=h_font,
        fill=(*INK, 255),
    )

    name_font = try_font(16, bold=True)
    nb = draw.textbbox((0, 0), "HakusAI", font=name_font)
    nw = nb[2] - nb[0]
    draw.text(
        ((width - nw) / 2 - nb[0], 168),
        "HakusAI",
        font=name_font,
        fill=(*INK, 255),
    )

    tag_font = try_font(9, bold=False)
    tb = draw.textbbox((0, 0), "AI Workspace", font=tag_font)
    tw2 = tb[2] - tb[0]
    draw.text(
        ((width - tw2) / 2 - tb[0], 192),
        "AI Workspace",
        font=tag_font,
        fill=(*MUTED, 230),
    )

    draw.line([(52, 214), (112, 214)], fill=(*ACCENT, 110), width=1)

    for yy, bar_w, alpha in ((278, 64, 40), (286, 48, 28), (294, 32, 18)):
        x0 = (width - bar_w) // 2
        draw.rounded_rectangle(
            [x0, yy, x0 + bar_w, yy + 2],
            radius=1,
            fill=(*ACCENT, alpha),
        )

    vignette = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vignette)
    for y in range(height):
        t = y / (height - 1)
        if t > 0.72:
            alpha = int(90 * ((t - 0.72) / 0.28) ** 1.4)
            vd.line([(0, y), (width, y)], fill=(8, 8, 12, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), vignette).convert("RGB")

    img.save(path, format="BMP")
    print(f"wrote {path} size={img.size} bytes={os.path.getsize(path)}")


def make_header(path: str) -> None:
    """NSIS MUI header bitmap: 150 x 57."""
    width, height = 150, 57
    himg = Image.new("RGB", (width, height), SURFACE_RAISED)

    for y in range(height):
        for x in range(width):
            tx = x / (width - 1)
            ty = y / (height - 1)
            base = lerp((42, 34, 78), (24, 24, 32), min(1.0, tx * 0.85 + ty * 0.25))
            himg.putpixel((x, y), base)

    hdraw = ImageDraw.Draw(himg, "RGBA")
    hdraw.rectangle([0, 0, 3, height - 1], fill=(*ACCENT, 200))

    mx, my = 22, height // 2
    hdraw.ellipse([mx - 14, my - 14, mx + 14, my + 14], fill=(48, 40, 90, 230))
    hdraw.ellipse(
        [mx - 14, my - 14, mx + 14, my + 14],
        outline=(*ACCENT, 100),
        width=1,
    )
    hf = try_font(14, bold=True)
    hb = hdraw.textbbox((0, 0), "H", font=hf)
    hdraw.text(
        (mx - (hb[2] - hb[0]) / 2 - hb[0], my - (hb[3] - hb[1]) / 2 - hb[1]),
        "H",
        font=hf,
        fill=(*INK, 255),
    )

    nf = try_font(12, bold=True)
    hdraw.text((44, my - 8), "HakusAI", font=nf, fill=(*INK, 245))
    hdraw.line(
        [(width - 40, height - 8), (width - 8, height - 8)],
        fill=(*ACCENT, 50),
        width=1,
    )

    himg.save(path, format="BMP")
    print(f"wrote {path} size={himg.size} bytes={os.path.getsize(path)}")


def main() -> int:
    make_welcome(os.path.join(OUT_DIR, "welcome.bmp"))
    make_header(os.path.join(OUT_DIR, "header.bmp"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
