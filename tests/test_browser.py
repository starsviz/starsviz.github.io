"""Headless-browser smoke tests: the built page loads cleanly, draws what it
should, fits a phone screen, and the player score lands on its intended scale.

Needs Playwright's Chromium:  python -m playwright install chromium
"""
from __future__ import annotations

import statistics

import pytest

playwright = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def pw():
    with playwright.sync_playwright() as p:
        yield p


@pytest.fixture(scope="module")
def browser(pw):
    b = pw.chromium.launch()
    yield b
    b.close()


@pytest.fixture(scope="module")
def webkit(pw):
    """Safari's engine, which iPhones use: python -m playwright install webkit"""
    try:
        b = pw.webkit.launch()
    except Exception as e:
        pytest.skip(f"WebKit not installed: {e}")
    yield b
    b.close()


def offline(route):
    """Tests run offline: allow the page itself and in-memory images (blob:/data:), block the web (Google Fonts)."""
    route.continue_() if route.request.url.startswith(("file:", "blob:", "data:")) else route.abort()


def open_page(browser, path, width=1280, height=900, scheme="light"):
    page = browser.new_page(viewport={"width": width, "height": height}, color_scheme=scheme)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    # font requests are blocked to keep tests offline; their "failed to load" notices aren't page bugs
    page.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text and errors.append(m.text))
    page.route("**/*", offline)
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
    page.route("**/*", offline)
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


def axis_labels(page):
    return page.eval_on_selector_all("#quad .axis text", "ts => ts.map(t => t.textContent)")


def test_quadrant_pan_by_scrolling(browser, built_page):
    """Zoomed in, a trackpad/wheel scroll over the chart moves the view; at the chart's edge the page scrolls."""
    page, errors = open_page(browser, built_page)
    page.locator("#quad").scroll_into_view_if_needed()
    page.click('[data-z="in"]')
    page.click('[data-z="in"]')
    assert page.locator(".zhint").is_visible()
    box = page.locator("#quad svg").bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    y0, ticks0 = page.evaluate("scrollY"), axis_labels(page)
    page.mouse.wheel(120, 0)  # sideways
    page.wait_for_timeout(80)
    ticks1 = axis_labels(page)
    assert ticks1 != ticks0 and page.evaluate("scrollY") == y0, "sideways scroll pans the chart, page stays put"
    page.mouse.wheel(0, 80)  # down
    page.wait_for_timeout(80)
    assert axis_labels(page) != ticks1 and page.evaluate("scrollY") == y0, "downward scroll pans the chart"
    for _ in range(30):  # keep going: once the chart's bottom edge is reached, the page takes over
        page.mouse.wheel(0, 200)
        page.wait_for_timeout(20)
    assert page.evaluate("scrollY") > y0, "at the edge, scrolling goes back to the page"
    assert errors == []
    page.close()


def test_quadrant_pan_by_dragging_on_phone(browser, built_page):
    """Zoomed in on a phone, one finger drags the view around; a tap still opens a player card."""
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.route("**/*", offline)
    page.goto(built_page.as_uri())
    page.wait_for_selector("#quad svg")
    page.locator("#quad").scroll_into_view_if_needed()
    page.locator('[data-z="in"]').tap()
    page.locator('[data-z="in"]').tap()
    box = page.locator("#quad svg").bounding_box()
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    y0, ticks0 = page.evaluate("scrollY"), axis_labels(page)
    cdp = ctx.new_cdp_session(page)

    def touch(kind, pts):
        cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": [{"x": x, "y": y, "id": i} for i, (x, y) in enumerate(pts)]})

    touch("touchStart", [(cx, cy)])
    for k in range(1, 11):
        touch("touchMove", [(cx - 8 * k, cy - 6 * k)])
        page.wait_for_timeout(15)
    touch("touchEnd", [])
    page.wait_for_timeout(150)
    assert axis_labels(page) != ticks0, "the view moved"
    assert page.evaluate("scrollY") == y0, "the page didn't scroll"
    assert page.locator(".sheet").count() == 0, "a drag isn't a tap"
    dot = page.locator("#quad .qd").first.bounding_box()
    page.touchscreen.tap(dot["x"] + dot["width"] / 2, dot["y"] + dot["height"] / 2)
    page.wait_for_selector(".sheet")
    assert errors == []
    ctx.close()


def open_share_page(browser, path, **ctx_opts):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True, **ctx_opts)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and "Failed to load resource" not in m.text and errors.append(m.text))
    page.route("**/*", offline)  # fonts fall back offline
    page.goto(path.as_uri())
    page.wait_for_selector("#quad svg")
    return ctx, page, errors


def preview_size(page):
    page.wait_for_selector(".share-prev[aria-busy=false] img:not([hidden])", timeout=20000)
    return page.evaluate("(() => { const i = document.querySelector('.share-prev img'); return [i.naturalWidth, i.naturalHeight]; })()")


def pick(page, group, value):
    page.click(f'[data-{group}] [data-{"k" if group == "kinds" else "t"}="{value}"]')
    return preview_size(page)


def test_share_game_cards(browser, built_page):
    """Game card and rankings card, light and dark, render as 2400x1350 PNGs; download names the file; Esc closes."""
    ctx, page, errors = open_share_page(browser, built_page)
    page.click("#share-game")
    assert preview_size(page) == [2400, 1350]
    for theme in ("light", "dark"):
        pick(page, "themes", theme)
        for kind in ("game", "rank"):
            assert pick(page, "kinds", kind) == [2400, 1350], (theme, kind)
    with page.expect_download() as dl:
        page.click('[data-a="download"]')
    assert dl.value.suggested_filename.endswith("-rankings.png")
    page.keyboard.press("Escape")
    assert page.locator(".sharebox").count() == 0
    assert errors == []
    ctx.close()


def test_share_player_cards(browser, built_page):
    """From a skater's and a goalie's card: this-game and season images; Esc closes the share dialog, not the player card."""
    ctx, page, errors = open_share_page(browser, built_page)
    for table in ("Forwards", "In goal"):
        page.locator(f".card:has(.chapter-label:text-matches('^{table}')) tr[data-pid] .linkish").first.click()
        page.wait_for_selector(".sheet")
        page.click("#share-player")
        assert page.locator('[data-kinds] [data-k="pgame"]').get_attribute("aria-pressed") == "true", "opened from a game: that game"
        assert preview_size(page) == [2400, 1350]
        assert pick(page, "kinds", "pseason") == [2400, 1350]
        page.keyboard.press("Escape")
        assert page.locator(".sharebox").count() == 0 and page.locator(".sheet").count() == 1
        page.keyboard.press("Escape")
    assert errors == []
    ctx.close()


def test_share_copy_image(browser, built_page):
    ctx, page, errors = open_share_page(browser, built_page, permissions=["clipboard-read", "clipboard-write"])
    page.click("#share-game")
    preview_size(page)
    page.click('[data-a="copy"]')
    page.wait_for_function("document.querySelector('.share-status').textContent.startsWith('Copied')")
    assert page.evaluate("navigator.clipboard.read().then(items => items[0].types)") == ["image/png"]
    assert errors == []
    ctx.close()


@pytest.mark.parametrize("n", [1, 3])
def test_share_cards_early_season(browser, sample_page, tmp_path, n):
    """Every card type still draws with only one or three games played."""
    ctx, page, errors = open_share_page(browser, page_with_first_games(sample_page, n, tmp_path / f"first{n}.html"))
    page.click("#share-game")
    for kind in ("game", "rank"):
        assert pick(page, "kinds", kind) == [2400, 1350]
    page.keyboard.press("Escape")
    for table in ("Forwards", "Defensemen", "In goal"):
        page.locator(f".card:has(.chapter-label:text-matches('^{table}')) tr[data-pid] .linkish").first.click()
        page.click("#share-player")
        for kind in ("pgame", "pseason"):
            assert pick(page, "kinds", kind) == [2400, 1350], (table, kind)
        page.keyboard.press("Escape")
        page.keyboard.press("Escape")
    assert errors == []
    ctx.close()


def test_share_cards_in_safari_engine(webkit, built_page):
    """iPhones draw with WebKit (Safari's engine), not Chrome's: the card must turn into a PNG there too."""
    ctx, page, errors = open_share_page(webkit, built_page)
    page.click("#share-game")
    assert preview_size(page) == [2400, 1350]
    assert pick(page, "kinds", "rank") == [2400, 1350]
    page.keyboard.press("Escape")
    page.locator("tr[data-pid] .linkish").first.click()
    page.click("#share-player")
    assert preview_size(page) == [2400, 1350]
    assert pick(page, "kinds", "pseason") == [2400, 1350]
    assert errors == []
    ctx.close()
