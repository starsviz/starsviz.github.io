"""Parsing and page-data tests, run against the fake sample season."""
from __future__ import annotations

import math

import pytest

import build_dashboard
import stars_viz as sv

SK_LEN, GK_LEN, SHOT_LEN, GOAL_LEN = 23, 11, 7, 9
FO = 12  # faceoff % can be null
ON_ICE = range(18, 23)  # so can the stats-report fields (on-ice attempts for/against, EV/PP/SH seconds), until the NHL posts them
PEN_T, PEN_D, FO_W, FO_L, SAT_F, SAT_A, EV, PP, SH = range(14, 23)


def first_game_id(api):
    rows, _, _ = sv.load_trend(api, "DAL", "20252026")
    return rows[0]["id"]


def test_parse_game(sample_api):
    gid = first_game_id(sample_api)
    box = sample_api.get(sv.url_game(gid, "boxscore"))
    pbp = sample_api.get(sv.url_game(gid, "play-by-play"))
    rail = sample_api.get(sv.url_game(gid, "right-rail"))
    g = sv.parse_game(box, pbp, rail, "DAL")
    assert g["id"] == gid
    assert g["us"]["abbrev"] == "DAL"
    assert {s["kind"] for s in g["shots"]} <= {"goal", "shot-on-goal", "missed-shot", "blocked-shot"}
    # Dallas always shoots right, the opponent left (blocked shots aren't drawn, so skip them)
    drawn = [s for s in g["shots"] if s["kind"] != "blocked-shot" and s["x"] is not None]
    assert all(s["x"] > 0 for s in drawn if s["ours"])
    assert all(s["x"] < 0 for s in drawn if not s["ours"])
    # goals in the play-by-play match the score (shootout winners aren't plays we keep)
    ours = sum(1 for x in g["goals"] if x["ours"])
    theirs = sum(1 for x in g["goals"] if not x["ours"])
    so = g["suffix"] == "SO"
    assert ours == g["us_score"] - (so and g["us_score"] > g["them_score"])
    assert theirs == g["them_score"] - (so and g["them_score"] > g["us_score"])


def _blocked_game(owner_is_shooter: bool) -> tuple[dict, dict]:
    """A one-play game: a Dallas shot (player 1) blocked by an opponent (player 2)."""
    team = lambda i, ab: {"id": i, "abbrev": ab, "commonName": {"default": ab}, "score": 0, "sog": 0}
    box = {"id": 1, "homeTeam": team(25, "DAL"), "awayTeam": team(20, "CGY"), "playerByGameStats": {}}
    play = {"typeDescKey": "blocked-shot", "periodDescriptor": {"number": 1, "periodType": "REG"},
            "timeInPeriod": "05:00", "situationCode": "1551", "homeTeamDefendingSide": "left",
            "details": {"xCoord": 60, "yCoord": 5, "shootingPlayerId": 1, "blockingPlayerId": 2,
                        "eventOwnerTeamId": 25 if owner_is_shooter else 20, "reason": "blocked"}}
    pbp = {"plays": [play], "rosterSpots": [{"playerId": 1, "teamId": 25}, {"playerId": 2, "teamId": 20}]}
    return box, pbp


@pytest.mark.parametrize("owner_is_shooter", [True, False], ids=["2025-26 convention", "older convention"])
def test_blocked_shot_goes_to_shooter(owner_is_shooter):
    """The NHL has recorded blocked shots under the shooting team and under the
    blocking team at different times; either way it's a Dallas attempt."""
    box, pbp = _blocked_game(owner_is_shooter)
    g = sv.parse_game(box, pbp, {}, "DAL")
    (shot,) = g["shots"]
    assert shot["ours"] and shot["pid"] == 1
    assert g["stats"]["attempts"] == (1, 0)


def test_page_shape(sample_data):
    D = sample_data
    assert set(D) == {"meta", "players", "games"}
    assert D["meta"]["team"] == "DAL" and D["meta"]["sample"] is True
    assert len(D["games"]) == 82
    assert [g["n"] for g in D["games"]] == list(range(1, 83))
    for g in D["games"]:
        assert g["res"] in ("W", "L", "OTL") and g["sfx"] in ("", "OT", "SO")
        assert g["sk"] and g["gk"] and g["shots"]
        assert all(len(r) == SK_LEN for r in g["sk"])
        assert all(len(r) == GK_LEN for r in g["gk"])
        assert all(len(s) == SHOT_LEN for s in g["shots"])
        assert all(len(x) == GOAL_LEN for x in g["goals"])
        assert all(str(r[0]) in D["players"] for r in g["sk"] + g["gk"])
        assert sum(1 for r in g["gk"] if r[6]) == 1, "exactly one goalie gets the decision"


def _numbers_ok(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def test_no_missing_numbers(sample_data):
    for g in sample_data["games"]:
        for r in g["sk"]:
            assert all(_numbers_ok(v) for i, v in enumerate(r) if i != FO and i not in ON_ICE), r
            assert all(r[i] is None or _numbers_ok(r[i]) for i in (FO, *ON_ICE)), r
        for r in g["gk"]:
            assert all(_numbers_ok(v) for v in r[:6] + r[7:]), r
        for s in g["shots"]:
            assert _numbers_ok(s[0]) and s[1] in (0, 1) and s[2] in (0, 1, 2, 3)
            assert s[3] is None or _numbers_ok(s[3])
        for k, pair in g["st"].items():
            if k != "pp":
                assert len(pair) == 2 and all(_numbers_ok(v) for v in pair), (k, pair)


def test_new_stats_add_up(sample_data):
    """Ice time by situation adds up to total ice time, faceoffs won by players match the team's count,
    penalties match penalty minutes (the sample season only has minors), and goalie splits fit inside the totals."""
    for g in sample_data["games"]:
        for r in g["sk"]:
            assert r[EV] + r[PP] + r[SH] == r[8], r
            assert r[SAT_F] >= 0 and r[SAT_A] >= 0
            assert r[PEN_T] * 2 == r[4], r
        assert sum(r[FO_W] for r in g["sk"]) == g["st"]["fo"][0]
        assert sum(r[FO_L] for r in g["sk"]) == g["st"]["fo"][1]
        for r in g["gk"]:
            ev_sv, ev_sa, pk_sv, pk_sa = r[7:11]
            assert 0 <= ev_sv <= ev_sa and 0 <= pk_sv <= pk_sa and ev_sa + pk_sa <= r[1] and ev_sv + pk_sv <= r[2], r
    assert sum(r[PEN_D] for g in sample_data["games"] for r in g["sk"]) > 50
    assert all("oi" in p for p in sample_data["players"].values() if p["pos"] != "G")


def test_penalties_and_faceoffs_per_player():
    team = lambda i, ab: {"id": i, "abbrev": ab, "commonName": {"default": ab}, "score": 0, "sog": 0}
    box = {"id": 1, "homeTeam": team(25, "DAL"), "awayTeam": team(20, "CGY"), "playerByGameStats": {}}
    play = lambda kind, per_type="REG", **d: {"typeDescKey": kind, "periodDescriptor": {"number": 1, "periodType": per_type},
                                              "timeInPeriod": "05:00", "situationCode": "1551", "details": d}
    pbp = {"rosterSpots": [], "plays": [
        play("penalty", eventOwnerTeamId=25, committedByPlayerId=1, drawnByPlayerId=9),
        play("penalty", eventOwnerTeamId=20, committedByPlayerId=9, drawnByPlayerId=1),
        play("penalty", eventOwnerTeamId=20, committedByPlayerId=8, drawnByPlayerId=1),
        play("penalty", eventOwnerTeamId=25, servedByPlayerId=2),             # bench minor: nobody's penalty
        play("penalty", eventOwnerTeamId=25, committedByPlayerId=3),          # misconduct: nobody drew it
        play("faceoff", eventOwnerTeamId=25, winningPlayerId=1, losingPlayerId=9),
        play("faceoff", eventOwnerTeamId=20, winningPlayerId=9, losingPlayerId=1),
        play("faceoff", eventOwnerTeamId=25, winningPlayerId=1, losingPlayerId=8),
        play("faceoff", "SO", eventOwnerTeamId=25, winningPlayerId=1, losingPlayerId=8)]}  # shootout plays don't count
    g = sv.parse_game(box, pbp, {}, "DAL")
    assert g["pen"][1] == [1, 2] and g["pen"][3] == [1, 0] and 2 not in g["pen"]
    assert g["fo"][1] == [2, 1] and g["fo"][9] == [1, 1]
    assert g["stats"]["faceoffs"] == (2, 1)


def test_skater_reports_page_through_and_merge():
    """The stats reports are asked for in one request; if the NHL ever caps the page size, keep asking."""
    class FakeApi:
        def __init__(self): self.urls = []
        def get(self, url):
            self.urls.append(url)
            start = int(url.split("start=")[1].split("&")[0])
            if "isGame=false" in url:
                return {"total": 1, "data": [{"playerId": 7, "satRelative": .02}] if start == 0 else []}
            rows = [{"gameId": 1, "playerId": 7, "satFor": 10, "satAgainst": 8}, {"gameId": 2, "playerId": 7, "satFor": 5, "satAgainst": 9}] \
                if "summaryshooting" in url else [{"gameId": 1, "playerId": 7, "evTimeOnIce": 600}, {"gameId": 2, "playerId": 7, "evTimeOnIce": 700}]
            return {"total": 2, "data": rows[start:start + 1]}  # one row per page

    api = FakeApi()
    by_game, season = sv.load_skater_reports(api, 25, 20252026)
    assert by_game[(1, 7)] == {"gameId": 1, "playerId": 7, "satFor": 10, "satAgainst": 8, "evTimeOnIce": 600}
    assert by_game[(2, 7)]["satAgainst"] == 9 and by_game[(2, 7)]["evTimeOnIce"] == 700
    assert season[7]["satRelative"] == .02
    assert len(api.urls) == 5 and all("teamId%3D25" in u and "limit=-1" in u for u in api.urls)


def test_players_have_names(sample_data):
    for pid, p in sample_data["players"].items():
        assert p["name"] and p["last"] and p["pos"] in ("C", "L", "R", "D", "G"), (pid, p)


def test_landing_fills_players_missing_from_roster():
    class FakeApi:
        def get(self, url):
            assert url.endswith("/player/8473994/landing")
            return {"firstName": {"default": "Jamie"}, "lastName": {"default": "Benn"}, "sweaterNumber": 99,
                    "position": "L", "shootsCatches": "L", "birthDate": "1989-07-18",
                    "birthCity": {"default": "Victoria"}, "birthCountry": "CAN", "heightInInches": 75}

    p = dict(name="J. Benn", last="Benn", num=14, pos="L")
    build_dashboard.fill_from_landing(FakeApi(), 8473994, p)
    assert p["name"] == "Jamie Benn" and p["born"] == "1989-07-18" and p["home"] == "Victoria, CAN"
    assert p["num"] == 14, "keeps the number he wore in Dallas"


def test_landing_offline_miss_is_harmless(sample_api):
    p = dict(name="J. Doe", last="Doe", num=7, pos="C")
    build_dashboard.fill_from_landing(sample_api, 1, p)  # not cached, --offline
    assert p == dict(name="J. Doe", last="Doe", num=7, pos="C")


def test_page_head_and_share_tags(sample_page):
    html = sample_page.read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    assert html.count("<head>") == html.count("</head>") == html.count("<body>") == html.count("</body>") == 1
    head = html.split("</head>")[0]
    assert "<style>" in head and "<title>Stars Player Rankings 2025-26</title>" in head
    assert "__DASHBOARD_" not in html and "<!--share-->" not in html, "every placeholder is filled"
    for tag in ('property="og:title"', 'property="og:description"', 'name="twitter:card" content="summary_large_image"',
                'rel="icon" href="data:image/svg+xml,', 'rel="apple-touch-icon"'):
        assert tag in head, tag
    assert 'property="og:image" content="https://example.com/stars/og-image.png?v=' in head
    assert (sample_page.parent / "apple-touch-icon.png").stat().st_size > 500


def test_fragment_has_no_wrapper(sample_cache, tmp_path):
    out = tmp_path / "frag.html"
    build_dashboard.main(["--offline", "--cache", str(sample_cache), "--season", "20252026", "--fragment", "--out", str(out)])
    html = out.read_text(encoding="utf-8")
    assert html.startswith("<title>") and "<head>" not in html and "<body>" not in html
    assert '<script id="data"' in html


def test_cache_keeps_only_official_games(tmp_path, monkeypatch):
    """A game fetched right at the horn (FINAL) is re-fetched until its stats are official (OFF)."""
    import os
    import time

    api = sv.Api(tmp_path, ttl=60)
    calls = []

    class Resp:
        def __init__(self, data): self.data = data
        def raise_for_status(self): pass
        def json(self): return self.data

    states = iter(["FINAL", "OFF", "OFF"])
    monkeypatch.setattr(sv.requests, "get", lambda url, **kw: calls.append(url) or Resp({"gameState": next(states)}))
    monkeypatch.setattr(sv.time, "sleep", lambda s: None)
    url = sv.url_game(1, "boxscore")
    age = lambda: os.utime(api._path(url), (time.time() - 3600,) * 2)  # pretend the saved copy is an hour old

    assert api.get(url, final_only_cache=True)["gameState"] == "FINAL"
    age()
    assert api.get(url, final_only_cache=True)["gameState"] == "OFF"   # re-fetched: FINAL isn't kept
    age()
    assert api.get(url, final_only_cache=True)["gameState"] == "OFF"   # kept for good now
    assert len(calls) == 2

    rail = sv.url_game(1, "right-rail")
    monkeypatch.setattr(sv.requests, "get", lambda url, **kw: calls.append(url) or Resp({"teamGameStats": []}))
    api.get(rail, official=True)
    os.utime(api._path(rail), (time.time() - 3600,) * 2)
    api.get(rail, official=True)
    assert calls.count(rail) == 1, "right-rail of an official game isn't re-fetched"
