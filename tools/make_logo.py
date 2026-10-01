#!/usr/bin/env python3
"""
make_logo.py - turns the Stick Language logo (white and green on black) into the
two small transparent versions the page header uses: white letters for the dark
theme, dark letters for the light theme. The green stays the logo's own green.

    python tools/make_logo.py assets/stick-language-source.png

Writes assets/logo-dark.png and assets/logo-light.png (build_dashboard.py bakes
them into the page), plus the icons: assets/favicon.png (browser tab) and
assets/touch-icon.png (phone home screen). The full logo is too wide to read at
icon size, so the icons use its hockey stick and puck on the logo's black.
Run again only if the logo changes.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HEIGHT = 126          # pixels; the header shows it about 42 px tall, so this stays sharp on 3x screens
INK = (16, 26, 31)    # letter color on the light theme (the page's --ink)
# A point on each piece of the stick-and-puck mark, as a fraction of the source image's width and height:
# the shaft, the toe of the blade (past the green tape) and the puck.
MARK_SEEDS = [(0.574, 0.263), (0.295, 0.596), (0.495, 0.618)]


def stick_mark(rgba: Image.Image, alpha: np.ndarray) -> Image.Image:
    """The stick and puck on their own: the shapes that contain the seed points, cut out of the full logo."""
    solid = Image.fromarray(((alpha > 0.25) * 255).astype("uint8")).copy()  # a copy, so it can be painted on
    for fx, fy in MARK_SEEDS:
        seed = (round(fx * solid.width), round(fy * solid.height))
        assert solid.getpixel(seed) == 255, f"no logo shape at {seed}; has the logo changed?"
        ImageDraw.floodfill(solid, seed, 128)
    keep = Image.fromarray(((np.asarray(solid) == 128) * 255).astype("uint8")).filter(ImageFilter.MaxFilter(7))  # + soft edges
    out = rgba.copy()
    out.putalpha(Image.fromarray(np.minimum(np.asarray(rgba.getchannel("A")), np.asarray(keep))))
    return out.crop(out.getchannel("A").point(lambda v: 255 if v > 40 else 0).getbbox())


def icon(mark: Image.Image, size: int, round_corners: bool) -> Image.Image:
    big = size * 4
    img = Image.new("RGBA", (big, big), (0, 0, 0, 255))
    h = round(big * 0.74)
    m = mark.resize((round(mark.width * h / mark.height), h), Image.LANCZOS)
    img.alpha_composite(m, ((big - m.width) // 2, (big - m.height) // 2))
    if round_corners:  # phones round the home-screen icon themselves; the browser tab doesn't
        shape = Image.new("L", (big, big), 0)
        ImageDraw.Draw(shape).rounded_rectangle((0, 0, big - 1, big - 1), radius=round(big * 0.22), fill=255)
        img.putalpha(shape)
    return img.resize((size, size), Image.LANCZOS)


def main(src: str) -> None:
    rgb = np.asarray(Image.open(src).convert("RGB"), dtype=float)
    # every pixel is black + some white + some green. The logo's green: the typical strongly colored pixel.
    spread = rgb.max(axis=2) - rgb.min(axis=2)
    green = np.median(rgb[spread > 0.8 * spread.max()], axis=0)
    g_dir = green - green.min()
    white = rgb.min(axis=2)
    g_amt = np.clip((rgb[..., 1] - white) / g_dir[1], 0, 1)
    w_amt = np.clip((white - g_amt * green.min()) / 255, 0, 1)
    alpha = np.clip(w_amt + g_amt, 0, 1)
    alpha[alpha < 0.06] = 0  # speckle in the black background
    ys, xs = np.where(alpha > 0.5)
    box = (xs.min() - 4, ys.min() - 4, xs.max() + 5, ys.max() + 5)
    total = np.maximum(w_amt + g_amt, 1e-6)[..., None]
    out = Path(src).parent
    white = Image.fromarray(np.dstack([(w_amt[..., None] * 255 + g_amt[..., None] * green) / total, alpha * 255]).round().astype("uint8"))
    mark = stick_mark(white, alpha)
    for name, size, rounded in (("favicon.png", 64, True), ("touch-icon.png", 180, False)):
        icon(mark, size, rounded).save(out / name, optimize=True)
        print(f"{out / name}: {size}x{size}, {(out / name).stat().st_size / 1024:.1f} KB")
    for name, letters in (("logo-dark.png", (255, 255, 255)), ("logo-light.png", INK)):
        color = (w_amt[..., None] * np.array(letters) + g_amt[..., None] * green) / total
        img = Image.fromarray(np.dstack([color, alpha * 255]).round().astype("uint8")).crop(box)
        img = img.resize((round(img.width * HEIGHT / img.height), HEIGHT), Image.LANCZOS)
        img.save(out / name, optimize=True)
        print(f"{out / name}: {img.width}x{img.height}, {(out / name).stat().st_size / 1024:.0f} KB, green {tuple(int(v) for v in green)}")


if __name__ == "__main__":
    main(sys.argv[1])
