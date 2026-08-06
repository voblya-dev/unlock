"""Renders assets/unlock.ico: a dark rounded tile with a debossed power glyph.

    python tools/make_icon.py

Run once before packaging; unlock.spec picks the file up automatically.

The shading is derived from offset blurred copies of the glyph mask rather than
painted by hand, so every size in the .ico comes out of the same geometry.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "unlock.ico"

RENDER = 1024           # supersampled; each .ico entry is downscaled from this
SIZES = (16, 24, 32, 48, 64, 128, 256)

TILE_TOP = (60, 60, 62)
TILE_BOTTOM = (30, 30, 32)
GLYPH_FILL = (23, 23, 25)


def _rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius, fill=255)
    return mask


def _vertical_gradient(size: int, top: tuple, bottom: tuple) -> Image.Image:
    column = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        column.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return column.resize((size, size), Image.Resampling.BILINEAR)


def _glyph_mask(size: int) -> Image.Image:
    """IEC power symbol — broken ring plus vertical bar — as a white-on-black mask."""
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)

    centre = size / 2
    radius = size * 0.245
    width = int(size * 0.082)
    gap = 34                       # degrees of opening, centred on 12 o'clock

    # The ring sits slightly below centre so the bar, which sticks out above it,
    # does not push the glyph's visual mass upwards.
    ring_y = centre + size * 0.035

    # PIL measures angles clockwise from 3 o'clock with y growing downwards, so
    # 12 o'clock is 270°, not 90°.
    top = 270.0
    box = (centre - radius, ring_y - radius, centre + radius, ring_y + radius)
    draw.arc(box, top + gap / 2, top - gap / 2 + 360, fill=255, width=width)

    # PIL's arc has butt caps, which read as chipped ends; cap them by hand.
    for angle in (top + gap / 2, top - gap / 2):
        x = centre + radius * math.cos(math.radians(angle))
        y = ring_y + radius * math.sin(math.radians(angle))
        draw.ellipse((x - width / 2, y - width / 2, x + width / 2, y + width / 2), fill=255)

    draw.rounded_rectangle(
        (centre - width / 2, ring_y - radius - size * 0.075,
         centre + width / 2, ring_y - size * 0.02),
        radius=width / 2,
        fill=255,
    )
    return mask


def _emboss(base: Image.Image, mask: Image.Image, size: int) -> Image.Image:
    """Deboss the glyph: shadow on the up-left rim, highlight on the down-right."""
    blur = size * 0.012
    offset = max(1, int(size * 0.009))

    soft = mask.filter(ImageFilter.GaussianBlur(blur))
    up = ImageChops.offset(soft, -offset, -offset)
    down = ImageChops.offset(soft, offset, offset)

    # The rim is where the two shifted copies disagree, so the highlight and the
    # shadow each land on exactly one side of the stroke.
    shadow = ImageChops.subtract(up, down).filter(ImageFilter.GaussianBlur(blur))
    light = ImageChops.subtract(down, up).filter(ImageFilter.GaussianBlur(blur))

    out = base.copy()
    out.paste(Image.new("RGB", base.size, GLYPH_FILL), (0, 0), mask)
    out.paste(Image.new("RGB", base.size, (0, 0, 0)),
              (0, 0), shadow.point(lambda v: int(v * 0.85)))
    out.paste(Image.new("RGB", base.size, (155, 155, 160)),
              (0, 0), light.point(lambda v: int(v * 0.55)))
    return out


def render(size: int = RENDER) -> Image.Image:
    tile = _vertical_gradient(size, TILE_TOP, TILE_BOTTOM)

    # Faint edge highlight, the way a bevelled tile catches light.
    sheen = Image.new("L", (size, size), 0)
    ImageDraw.Draw(sheen).rounded_rectangle(
        (0, 0, size - 1, size - 1), int(size * 0.22),
        outline=255, width=max(1, int(size * 0.008)),
    )
    sheen = sheen.filter(ImageFilter.GaussianBlur(size * 0.006))
    tile.paste(Image.new("RGB", (size, size), (115, 115, 120)),
               (0, 0), sheen.point(lambda v: int(v * 0.45)))

    art = _emboss(tile, _glyph_mask(size), size).convert("RGBA")
    art.putalpha(_rounded_mask(size, int(size * 0.22)))
    return art


def main() -> int:
    art = render()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Downscale per entry: PIL's own ICO resizer is nearest-neighbour and turns
    # the 16 px glyph into noise.
    frames = [art.resize((s, s), Image.Resampling.LANCZOS) for s in SIZES]
    frames[-1].save(OUT, format="ICO", sizes=[(s, s) for s in SIZES],
                    append_images=frames[:-1])
    art.resize((256, 256), Image.Resampling.LANCZOS).save(OUT.with_suffix(".png"))
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
