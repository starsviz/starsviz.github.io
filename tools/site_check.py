#!/usr/bin/env python3
"""
site_check.py - should the site be rebuilt right now? Run every 5 minutes by .github/workflows/site-check.yml
(started by cron-job.org), so a game goes up minutes after the NHL finishes its stats, not hours later.

    python tools/site_check.py --site https://example.com/ [--team DAL]

Yes when the Stars' latest finished regular-season game isn't on the published page yet and the NHL has made it
official and posted every skater's on-ice numbers (stars_viz.stats_missing), or STATS_WAIT_HOURS have passed since
puck drop. The builder makes the same check and holds a game back until then, so a publish never puts a game up
early, and the post-game email (which runs right after each publish) waits for the same two things.

Prints the reason, and writes publish=true/false to $GITHUB_OUTPUT when it's set.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import stars_viz as sv  # noqa: E402


def published_game_ids(site: str) -> set[int]:
    """The game IDs on the live page (fetched fresh, past the CDN's cache)."""
    r = requests.get(site, params={"check": int(time.time())}, timeout=30,
                     headers={"Cache-Control": "no-cache", "User-Agent": "stars-viz site check"})
    r.raise_for_status()
    blob = re.search(r'<script id="data" type="application/json">(.*?)</script>', r.text, re.S)
    if not blob:
        return set()
    return {g["id"] for g in json.loads(blob.group(1).replace("<\\/", "</")).get("games", [])}


def decide(api: sv.Api, site: str, team: str) -> tuple[bool, str]:
    sched = api.get(sv.url_schedule(team, "now"))
    done = [g for g in sched.get("games", []) if g.get("gameType") == 2 and g.get("gameState") in sv.FINAL_STATES]
    if not done:
        return False, "no finished regular-season game yet"
    g = max(done, key=lambda g: (g.get("startTimeUTC") or "", g["id"]))
    label = f'game {g["id"]} ({g["awayTeam"]["abbrev"]} @ {g["homeTeam"]["abbrev"]}, {g.get("gameDate")})'
    if g["id"] in published_game_ids(site):
        return False, f"the latest game, {label}, is already on the site"
    box = api.get(sv.url_game(g["id"], "boxscore"))
    on_ice, _ = sv.load_skater_reports(api, sv.team_id_from_schedule(sched, team), g.get("season") or sched["currentSeason"])
    missing = sv.stats_missing(box, on_ice, team)
    hours = sv.hours_since(g.get("startTimeUTC"))
    if not missing:
        return True, f"{label} is official with every on-ice number in: publish"
    if hours >= sv.STATS_WAIT_HOURS:
        return True, f"{label} still isn't complete ({missing}) {hours:.0f} hours after puck drop: publish anyway"
    return False, f"{label} is over, waiting for the NHL: {missing}"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", required=True, help="the published page's address")
    ap.add_argument("--team", default="DAL")
    a = ap.parse_args(argv)
    with tempfile.TemporaryDirectory() as cache:
        publish, why = decide(sv.Api(Path(cache), ttl=0), a.site, a.team.upper())
    print(why)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"publish={'true' if publish else 'false'}\n")


if __name__ == "__main__":
    main()
