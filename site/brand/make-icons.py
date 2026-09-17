"""Cut the site's icons from the artwork: site/brand/icon.png -> site/static.

    uv run python site/brand/make-icons.py

Run it only when the artwork changes; the results are committed, so building the site needs no
image library. Pillow comes with the dev environment (matplotlib pulls it).
"""

from pathlib import Path

from PIL import Image, ImageDraw

BRAND = Path(__file__).resolve().parent
STATIC = BRAND.parent / "static"
# The jackal sits left of centre in a 710x774 frame. This square drops the empty right edge and
# the black margin under the body, so the head still reads at 16 px in a tab.
CROP = (0, 60, 640, 700)


def rounded(square: Image.Image, size: int, ratio: float = 0.18) -> Image.Image:
    """The icon at `size`, its corners rounded like the app icons it sits beside."""
    icon = square.resize((size, size), Image.LANCZOS).convert("RGBA")
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size * 4 - 1, size * 4 - 1), radius=int(size * 4 * ratio), fill=255
    )
    icon.putalpha(mask.resize((size, size), Image.LANCZOS))  # 4x then down: smooth corners
    return icon


def main() -> None:
    art = Image.open(BRAND / "icon.png").convert("RGB")
    side = max(CROP[2] - CROP[0], CROP[3] - CROP[1])
    square = Image.new("RGB", (side, side), (0, 0, 0))  # the artwork's own field
    square.paste(art.crop(CROP), (0, 0))

    icon = rounded(square, 512)
    icon.save(STATIC / "icon.png", optimize=True)
    # the tab icons are icon.png itself, scaled down, so every size is the same picture
    icon.resize((64, 64), Image.LANCZOS).save(STATIC / "favicon.png", optimize=True)
    icon.save(STATIC / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    # iOS applies its own mask, so the touch icon stays a full square
    square.resize((180, 180), Image.LANCZOS).save(STATIC / "apple-touch-icon.png", optimize=True)
    for name in ("icon.png", "favicon.png", "favicon.ico", "apple-touch-icon.png"):
        path = STATIC / name
        print(
            f"{path.relative_to(BRAND.parent.parent)}  {Image.open(path).size[0]} px  "
            f"{path.stat().st_size // 1024} KiB"
        )


if __name__ == "__main__":
    main()
