"""Build transparent application icons from the supplied shield-and-Wi-Fi mark.

Run ``python tools/make_icon.py`` after changing ``assets/icon.png``.  The source
image is a presentation card; the generated PNG and ICO retain only its black
logo with clean alpha edges.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "icon.png"
PNG_OUT = ROOT / "assets" / "unlock.png"
ICO_OUT = ROOT / "assets" / "unlock.ico"
WHITE_PNG_OUT = ROOT / "assets" / "unlock-white.png"
WHITE_ICO_OUT = ROOT / "assets" / "unlock-white.ico"
FILL_OUT = ROOT / "assets" / "unlock-fill.png"
RENDER = 1024
SIZES = (16, 24, 32, 48, 64, 128, 256)


def extract_mark() -> Image.Image:
    source = Image.open(SOURCE).convert("RGBA")
    luminance = source.convert("RGB").convert("L")
    # The source card is near-white; convert the dark anti-aliased logo into a
    # soft alpha mask rather than keeping any card pixels in the output.
    alpha = luminance.point(
        lambda value: 0 if value >= 235 else round((235 - value) * 255 / 235)
    )
    # Ignore the pale decorative sparkle that sits away from the logo card.
    # Only the solid black shield is allowed to determine the crop bounds.
    solid = luminance.point(lambda value: 255 if value < 100 else 0)
    bbox = solid.getbbox()
    if bbox is None:
        raise RuntimeError(f"No shield mark found in {SOURCE}")

    left, top, right, bottom = bbox
    pad = round(max(right - left, bottom - top) * 0.075)
    alpha = alpha.crop((
        max(0, left - pad), max(0, top - pad),
        min(source.width, right + pad), min(source.height, bottom + pad),
    ))
    mark = Image.new("RGBA", alpha.size, (0, 0, 0, 0))
    mark.putalpha(alpha)

    canvas = Image.new("RGBA", (RENDER, RENDER), (0, 0, 0, 0))
    scale = min((RENDER * 0.92) / mark.width, (RENDER * 0.92) / mark.height)
    target = (round(mark.width * scale), round(mark.height * scale))
    mark = mark.resize(target, Image.Resampling.LANCZOS)
    canvas.alpha_composite(mark, ((RENDER - target[0]) // 2, (RENDER - target[1]) // 2))
    return canvas


def white_mark(icon: Image.Image) -> Image.Image:
    """White transparent variant for dark window chrome and the system tray."""
    white = Image.new("RGBA", icon.size, (255, 255, 255, 0))
    white.putalpha(icon.convert("RGBA").getchannel("A"))
    return white


def interior_mask(icon: Image.Image) -> Image.Image:
    """Transparent PNG mask for the area enclosed by the outer shield line."""
    alpha = icon.convert("RGBA").getchannel("A")
    walkable = alpha.point(lambda value: 0 if value > 8 else 255)
    ImageDraw.floodfill(walkable, (0, 0), 128)
    inside = walkable.point(lambda value: 255 if value == 255 else 0)
    # Contract then feather at source resolution: this gives the animated
    # interior a sub-pixel antialiased boundary while remaining under the
    # icon's black outline at every scaled button size.
    inside = inside.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.GaussianBlur(1.4))
    mask = Image.new("RGBA", icon.size, (255, 255, 255, 0))
    mask.putalpha(inside)
    return mask


def main() -> int:
    if not SOURCE.exists():
        raise FileNotFoundError(f"Icon source is missing: {SOURCE}")
    icon = extract_mark()
    icon.save(PNG_OUT)
    interior_mask(icon).save(FILL_OUT)
    frames = [icon.resize((size, size), Image.Resampling.LANCZOS) for size in SIZES]
    frames[-1].save(
        ICO_OUT, format="ICO", sizes=[(size, size) for size in SIZES],
        append_images=frames[:-1],
    )
    white = white_mark(icon)
    white.save(WHITE_PNG_OUT)
    white_frames = [white.resize((size, size), Image.Resampling.LANCZOS) for size in SIZES]
    white_frames[-1].save(
        WHITE_ICO_OUT, format="ICO", sizes=[(size, size) for size in SIZES],
        append_images=white_frames[:-1],
    )
    print(f"wrote {PNG_OUT}, {FILL_OUT}, {ICO_OUT}, {WHITE_PNG_OUT} and {WHITE_ICO_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
