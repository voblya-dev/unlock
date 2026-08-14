"""Rebuild the ICO used by the app, tray and installer from its PNG master."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "unlock-mask.png"
ICO_OUT = ROOT / "assets" / "unlock-mask.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> int:
    source = Image.open(SOURCE).convert("RGBA")
    if source.getchannel("A").getextrema()[0] != 0:
        raise RuntimeError(f"{SOURCE} must have a transparent background")
    frames = [source.resize((size, size), Image.Resampling.LANCZOS) for size in SIZES]
    frames[-1].save(
        ICO_OUT,
        format="ICO",
        sizes=[(size, size) for size in SIZES],
        append_images=frames[:-1],
    )
    print(f"wrote transparent {ICO_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
