"""Build the transparent icon used by the app, tray and installer.

The source asset deliberately has an alpha channel.  Never flatten it onto a
black or white card: Windows uses these outputs on light and dark surfaces.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "unlock-mask-transparent-4k.png"
PNG_OUT = ROOT / "assets" / "unlock-mask.png"
ICO_OUT = ROOT / "assets" / "unlock-mask.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> int:
    source = Image.open(SOURCE).convert("RGBA")
    if source.getchannel("A").getextrema()[0] != 0:
        raise RuntimeError(f"{SOURCE} must have a transparent background")
    source.save(PNG_OUT)
    frames = [source.resize((size, size), Image.Resampling.LANCZOS) for size in SIZES]
    frames[-1].save(
        ICO_OUT,
        format="ICO",
        sizes=[(size, size) for size in SIZES],
        append_images=frames[:-1],
    )
    print(f"wrote transparent {PNG_OUT} and {ICO_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
