#!/usr/bin/env python3
"""
make_share_image.py - snapshots the top of the built page (latest game's
headline, score and quadrant chart) as the 1200x630 preview image that
Substack, X and iMessage show when someone shares the link.

    python tools/make_share_image.py site/index.html site/og-image.png

Needs Playwright's Chromium:  pip install playwright && python -m playwright install chromium
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

# screenshot-only tweak: the game-picker strip is busy at thumbnail size
HIDE = ".picker { display: none !important; }"


def main(page_path: str, out_path: str) -> None:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1200, "height": 630}, device_scale_factor=1, color_scheme="light")
        page.goto(Path(page_path).resolve().as_uri(), wait_until="networkidle")
        page.add_style_tag(content=HIDE)
        page.wait_for_selector("#quad svg")
        page.evaluate("document.fonts.ready")
        page.screenshot(path=str(out))
        browser.close()
    print(f"Share image: {out}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
