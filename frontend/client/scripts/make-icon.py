"""Generate HakusAI app icon set for electron-builder.

Two modes:

1. **From source** (default) — if `icon.png` already exists in build-resources/,
   generate all required sizes (16/32/64/128/256/512/1024) from it using LANCZOS
   resampling. This is the normal flow when a designer has provided the master
   icon.

2. **Fallback generator** — if `icon.png` does NOT exist, draw a violet→fuchsia
   gradient with a white "H" letter as a placeholder. Useful for first-time
   bootstrap when no custom icon is available yet.

Usage:
    python3 scripts/make-icon.py              # auto-detect mode
    python3 scripts/make-icon.py --generate   # force fallback generator
    python3 scripts/make-icon.py --from icon-master.png   # use a specific source
"""
from PIL import Image, ImageDraw, ImageFont
import argparse
import os
import sys

SIZES = [16, 32, 64, 128, 256, 512, 1024]


def lerp(a, b, t):
    return int(a + (b - a) * t)


def gradient(w, h, c1, c2):
    img = Image.new("RGB", (w, h), c1)
    px = img.load()
    for y in range(h):
        for x in range(w):
            t = (x + y) / (w + h)
            r = lerp(c1[0], c2[0], t)
            g = lerp(c1[1], c2[1], t)
            b = lerp(c1[2], c2[2], t)
            px[x, y] = (r, g, b)
    return img


def generate_placeholder(size: int = 512) -> Image.Image:
    """Violet → fuchsia gradient with a white 'H' letter."""
    img = gradient(size, size, (139, 92, 246), (217, 70, 239))

    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([20, 20, size - 20, size - 20], radius=size // 5, fill=255)
    bg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bg.paste(img, (0, 0), mask)

    draw = ImageDraw.Draw(bg)
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            int(size * 0.55),
        )
    except Exception:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), "H", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - tw) // 2 - bbox[0]
    y = (size - th) // 2 - bbox[1]
    draw.text((x, y), "H", fill=(255, 255, 255, 255), font=font)
    return bg


def resize_from_source(src: Image.Image, size: int) -> Image.Image:
    """High-quality LANCZOS resize. Preserves RGBA mode."""
    if src.mode != "RGBA":
        src = src.convert("RGBA")
    return src.resize((size, size), Image.LANCZOS)


def main():
    parser = argparse.ArgumentParser(description="Generate HakusAI icon set")
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Force fallback placeholder generator (ignore existing icon.png)",
    )
    parser.add_argument(
        "--from",
        dest="source",
        type=str,
        default=None,
        help="Use a specific source PNG instead of build-resources/icon.png",
    )
    args = parser.parse_args()

    out_dir = os.path.join(os.path.dirname(__file__), "..", "build-resources")
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    master_path = args.source or os.path.join(out_dir, "icon.png")

    # Decide source image
    if args.generate or not os.path.exists(master_path):
        print("[icon] Source not found or --generate passed → drawing placeholder")
        src = generate_placeholder(1024)
        src.save(master_path, "PNG")
        print(f"[icon] Master placeholder written: {master_path} ({src.size[0]}x{src.size[1]})")
    else:
        print(f"[icon] Using existing source: {master_path}")
        src = Image.open(master_path)
        if src.mode != "RGBA":
            src = src.convert("RGBA")
        # If the source is smaller than 512, upscale to at least 512 for sharper outputs
        if max(src.size) < 512:
            new_size = 512
            print(f"[icon] Source smaller than 512px — upscaling to {new_size}x{new_size}")
            src = src.resize((new_size, new_size), Image.LANCZOS)
        print(f"[icon] Source dimensions: {src.size[0]}x{src.size[1]} ({src.mode})")

    # Generate all sizes
    for size in SIZES:
        out_path = os.path.join(out_dir, f"icon-{size}.png")
        resized = resize_from_source(src, size)
        resized.save(out_path, "PNG", optimize=True)
        print(f"[icon] Wrote {out_path} ({size}x{size})")

    # Also make sure icon.png (master) exists at the right size — electron-builder
    # prefers a 512x512 or larger master
    if not os.path.exists(master_path) or args.generate:
        src.save(master_path, "PNG")
    elif max(src.size) > 1024:
        # Cap master at 1024 to keep repo size reasonable
        capped = src.resize((1024, 1024), Image.LANCZOS)
        capped.save(master_path, "PNG", optimize=True)
        print(f"[icon] Capped master to 1024x1024: {master_path}")

    print(f"\n[icon] Done. {len(SIZES)} sizes generated in {out_dir}")


if __name__ == "__main__":
    main()
