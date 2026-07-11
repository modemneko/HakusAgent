"""Generate a simple HakusAI app icon (512x512 PNG) for electron-builder.
Uses Pillow to draw a violet→fuchsia gradient with a white "H" letter.
"""
from PIL import Image, ImageDraw, ImageFont
import os

SIZE = 512

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

def main():
    out_dir = os.path.join(os.path.dirname(__file__), "..", "build-resources")
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    # Violet (#8b5cf6) -> Fuchsia (#d946ef)
    img = gradient(SIZE, SIZE, (139, 92, 246), (217, 70, 239))

    # Draw a rounded rectangle mask for the icon shape
    mask = Image.new("L", (SIZE, SIZE), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([20, 20, SIZE - 20, SIZE - 20], radius=110, fill=255)
    bg = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    bg.paste(img, (0, 0), mask)

    # Draw a white "H" letter in the center
    draw = ImageDraw.Draw(bg)
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 280
        )
    except Exception:
        font = ImageFont.load_default()

    # Center the text
    bbox = draw.textbbox((0, 0), "H", font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (SIZE - tw) // 2 - bbox[0]
    y = (SIZE - th) // 2 - bbox[1]
    draw.text((x, y), "H", fill=(255, 255, 255, 255), font=font)

    out_path = os.path.join(out_dir, "icon.png")
    bg.save(out_path, "PNG")
    print(f"Icon written: {out_path}")

    # Also create 512x512 and 256x256 variants
    for size in [16, 32, 64, 128, 256]:
        small = bg.resize((size, size), Image.LANCZOS)
        small.save(os.path.join(out_dir, f"icon-{size}.png"), "PNG")

if __name__ == "__main__":
    main()
