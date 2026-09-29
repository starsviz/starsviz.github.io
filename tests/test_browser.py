"""Headless-browser smoke tests: the built page loads cleanly, draws what it
should, fits a phone screen, and the player score lands on its intended scale.

Needs Playwright's Chromium:  python -m playwright install chromium
"""
from __future__ import annotations

import statistics

import pytest

playwright = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def browser():
    with playwright.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def open_page(browser, path, width=1280, height=900, scheme="light"):
    page = browser.new_page(viewport={"width": width, "height": height}, color_scheme=scheme)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    # font requests are blocked to keep tests offline; their "failed to load" notices aren't page bugs
    page.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text and errors.append(m.text))
    page.route("**/*", lambda r: r.continue_() if r.request.url.startswith("file:") else r.abort())
    page.goto(path.as_uri())
    page.wait_for_selector("#quad svg")
    return page, errors


def skater_rows(page):
    return page.locator("tr[data-pid]:has(.scv)")


@pytest.mark.parametrize("width,scheme", [(1280, "light"), (390, "light"), (390, "dark")])
def test_page_loads_and_draws(browser, built_page, built_data, width, scheme):
    page, errors = open_page(browser, built_page, width=width, scheme=scheme)
    assert page.locator(".headline").first.inner_text().strip()
    assert page.locator(".chip").count() == len(built_data["games"])
    latest = built_data["games"][-1]
    n = skater_rows(page).count()
    assert n == len(latest["sk"]) >= 17, "every dressed skater gets a row"
    assert page.locator("#quad .qd").count() == n, "one quadrant dot per skater"
    rows = page.locator("tr[data-pid]").count()
    assert page.locator("tr[data-pid] .linkish.who .go").count() == rows, "every clickable name shows the open-card icon"
    assert page.locator("#banner").is_visible() == built_data["meta"]["sample"], "sample banner only on sample data"
    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 0, f"page scrolls sideways by {overflow}px"
    assert errors == []
    page.close()


def test_game_picker_and_player_card(browser, built_page):
    page, errors = open_page(browser, built_page)
    page.locator(".chip").first.click()
    assert page.locator(".chip").first.get_attribute("aria-pressed") == "true"
    assert page.locator("#quad .qd").count() == skater_rows(page).count()
    page.locator("tr[data-pid] .linkish").first.click()
    page.wait_for_selector(".sheet")
    assert page.locator("#pname").inner_text().strip()
    page.locator('#scopeseg button[data-k="season"]').click()
    page.wait_for_selector("#pc0 svg")
    page.keyboard.press("Escape")
    assert page.locator(".sheet").count() == 0
    assert errors == []
    page.close()


def test_every_game_renders_and_score_scale(browser, sample_page):
    """Walk all 82 games; scores for forwards and defensemen should each average
    about 50 with a spread (SD) of about 15."""
    page, errors = open_page(browser, sample_page)
    scores = {"F": [], "D": []}
    for gid in page.eval_on_selector_all(".chip", "cs => cs.map(c => c.dataset.id)"):
        page.click(f'.chip[data-id="{gid}"]')
        for grp, label in (("F", "Forwards"), ("D", "Defensemen")):
            scores[grp] += page.eval_on_selector_all(
                f'.card:has(.chapter-label:text-matches("^{label}", "i")) .scv', "els => els.map(e => +e.textContent)")
    assert errors == []
    for grp, vals in scores.items():
        assert len(vals) > 300, grp
        assert all(0 <= v <= 100 for v in vals)
        assert 48 <= statistics.mean(vals) <= 52, (grp, statistics.mean(vals))
        assert 12.5 <= statistics.pstdev(vals) <= 16, (grp, statistics.pstdev(vals))
    page.close()


def page_with_first_games(src, n, out):
    """Copy of a built page keeping only its first n games: what the site shows early in a season."""
    import json
    import re

    html = src.read_text(encoding="utf-8")
    m = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S)
    data = json.loads(m.group(1).replace("<\\/", "</"))
    data["games"] = data["games"][:n]
    blob = json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    out.write_text(html[:m.start(1)] + blob + html[m.end(1):], encoding="utf-8")
    return out


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 82])
def test_every_player_card_opens(browser, sample_page, tmp_path, n):
    """Open each player's card, season and one-game views, with only n games played.
    Early-season data once hung a chart axis (a 3-game average equal to a 3-game season)."""
    path = sample_page if n == 82 else page_with_first_games(sample_page, n, tmp_path / f"first{n}.html")
    page, errors = open_page(browser, path)
    for pid in page.eval_on_selector_all("tr[data-pid]", "rs => rs.map(r => r.dataset.pid)"):
        page.locator(f'tr[data-pid="{pid}"] .linkish').click()
        page.wait_for_selector(".sheet")
        page.locator('#scopeseg button[data-k="season"]').click()
        page.locator('#scopeseg button[data-k="game"]').click()
        page.keyboard.press("Escape")
        assert errors == [], (n, pid, errors)
    page.close()


DOTS_JS = """() => [...document.querySelectorAll('#quad .qd')].map(n => ({
  x: +(n.getAttribute('cx') ?? +n.getAttribute('x') + 6), y: +(n.getAttribute('cy') ?? +n.getAttribute('y') + 6),
  size: +(n.getAttribute('r') ?? n.getAttribute('width')) }))"""


def median_gap(dots):
    import math
    import statistics
    return statistics.median(min(math.hypot(a["x"] - b["x"], a["y"] - b["y"]) for b in dots if b is not a) for a in dots)


def test_quadrant_zoom_buttons_and_trackpad(browser, built_page):
    """Zooming spreads the dots apart but keeps them the same size; Reset restores the original chart."""
    page, errors = open_page(browser, built_page)
    page.locator("#quad").scroll_into_view_if_needed()
    start = page.evaluate(DOTS_JS)
    assert page.locator('[data-z="out"]').is_disabled() and not page.locator('[data-z="reset"]').is_visible()
    page.click('[data-z="in"]')
    page.click('[data-z="in"]')
    zoomed = page.evaluate(DOTS_JS)
    assert {d["size"] for d in zoomed} == {d["size"] for d in start}, "dots keep their size"
    assert median_gap(zoomed) > 2 * median_gap(start), "crowded dots spread apart"
    page.click('[data-z="reset"]')
    assert page.evaluate(DOTS_JS) == start
    box = page.locator("#quad svg").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.wheel(0, 200)  # plain scrolling is left to the page
    page.wait_for_timeout(100)
    assert page.evaluate(DOTS_JS) == start
    page.locator("#quad").scroll_into_view_if_needed()  # the wheel scrolled the page; aim at the chart again
    box = page.locator("#quad svg").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.keyboard.down("Control")  # a trackpad pinch arrives as ctrl+wheel
    page.mouse.wheel(0, -60)
    page.keyboard.up("Control")
    page.wait_for_timeout(100)
    assert median_gap(page.evaluate(DOTS_JS)) > median_gap(start)
    assert errors == []
    page.close()


def test_quadrant_pinch_on_phone(browser, built_page):
    """A two-finger pinch zooms the chart, not the page, and a tap afterwards still opens a player card."""
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route("**/*", lambda r: r.continue_() if r.request.url.startswith("file:") else r.abort())
    page.goto(built_page.as_uri())
    page.wait_for_selector("#quad svg")
    page.locator("#quad").scroll_into_view_if_needed()
    start = page.evaluate(DOTS_JS)
    box = page.locator("#quad svg").bounding_box()
    cx, cy = box["x"] + box["width"] * .55, box["y"] + box["height"] * .5
    cdp = ctx.new_cdp_session(page)

    def touch(kind, pts):
        cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": [{"x": x, "y": y, "id": i} for i, (x, y) in enumerate(pts)]})

    touch("touchStart", [(cx - 30, cy), (cx + 30, cy)])
    for k in range(1, 9):
        touch("touchMove", [(cx - 30 - 5 * k, cy), (cx + 30 + 5 * k, cy)])
        page.wait_for_timeout(15)
    touch("touchEnd", [])
    page.wait_for_timeout(150)
    assert page.evaluate("visualViewport.scale") == 1, "the page itself didn't zoom"
    assert median_gap(page.evaluate(DOTS_JS)) > 1.5 * median_gap(start)
    assert page.locator(".sheet").count() == 0 and page.locator('[data-z="reset"]').is_visible()
    dot = page.locator("#quad .qd").first.bounding_box()
    page.touchscreen.tap(dot["x"] + dot["width"] / 2, dot["y"] + dot["height"] / 2)
    page.wait_for_selector(".sheet")
    assert errors == []
    ctx.close()
