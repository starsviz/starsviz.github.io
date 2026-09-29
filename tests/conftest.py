"""Shared fixtures: one fake 82-game season (tools/make_sample_season.py) and
the dashboard built from it, both made once per test run in a temp folder."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import build_dashboard  # noqa: E402
import stars_viz as sv  # noqa: E402


def page_data(html: str) -> dict:
    blob = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1)
    return json.loads(blob.replace("<\\/", "</"))


@pytest.fixture(scope="session")
def sample_cache(tmp_path_factory) -> Path:
    cache = tmp_path_factory.mktemp("sample_cache")
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_sample_season.py"), str(cache)],
                   check=True, capture_output=True)
    return cache


@pytest.fixture(scope="session")
def sample_api(sample_cache) -> sv.Api:
    return sv.Api(sample_cache, offline=True)


@pytest.fixture(scope="session")
def sample_page(sample_cache, tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("site") / "index.html"
    build_dashboard.main(["--offline", "--cache", str(sample_cache), "--season", "20252026", "--sample",
                          "--credit", "test.substack.com", "--site-url", "https://example.com/stars",
                          "--out", str(out)])
    return out


@pytest.fixture(scope="session")
def sample_data(sample_page) -> dict:
    return page_data(sample_page.read_text(encoding="utf-8"))


def pytest_addoption(parser):
    parser.addoption("--page", default=None,
                     help="run the browser smoke tests on this built page instead of the sample season")


@pytest.fixture(scope="session")
def built_page(request) -> Path:
    """The page the browser tests open: the sample season, or --page (the nightly job's real page)."""
    given = request.config.getoption("--page")
    return Path(given).resolve() if given else request.getfixturevalue("sample_page")


@pytest.fixture(scope="session")
def built_data(built_page) -> dict:
    return page_data(built_page.read_text(encoding="utf-8"))
