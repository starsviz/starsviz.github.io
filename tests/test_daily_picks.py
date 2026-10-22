"""The daily team score picks (tools/daily_picks.py). Offline: the NHL schedule, the odds and the email are stand-ins."""
from __future__ import annotations

import datetime as dt
import itertools
import json
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import daily_picks as dp  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")


def test_team_score_constants_come_from_the_page():
    page = (ROOT / "dashboard_template.html").read_text()
    assert f"goal: {dp.TEAM['goal']}" in page and f"xg: {dp.TEAM['xg']}" in page and f"cf: {dp.TEAM['cf']}" in page
    even = dict(gf=2, ga=2, xgf=2.5, xga=2.5, cf=40, ca=40)
    assert dp.team_score(even) == dp.MID == 70
    assert dp.team_score(dict(even, gf=3)) == pytest.approx(70 + dp.TEAM["goal"])
    assert dp.team_score(dict(even, gf=40)) == 100 and dp.team_score(dict(even, ga=40)) == 0


def test_units_follow_the_owners_rule():
    assert dp.units(-120, True) == 1 and dp.units(240, True) == 2.4
    assert dp.units(-240, False) == -2.4 and dp.units(130, False) == -1


def _row(i, line, diff, home_pick, won, day="2026-10-10"):
    return dict(id=i, date=day, start=f"{day}T23:00:00Z", away="AAA", home="HHH", away_prev=70.0, home_prev=70.0 + diff,
                pick="HHH" if home_pick else "AAA", line=line, source="x", fits=None, result="W" if won else "L", final="")


def _brute(rows):
    lines, diffs, best = sorted({r["line"] for r in rows}), sorted({dp.diff_of(r) for r in rows}), None
    for (lo, hi), (dlo, dhi), v in itertools.product(itertools.combinations_with_replacement(lines, 2),
                                                     itertools.combinations_with_replacement(diffs, 2), ("either", "home", "away")):
        hit = [r for r in rows if lo <= r["line"] <= hi and dlo <= dp.diff_of(r) <= dhi
               and (v == "either" or (r["pick"] == r["home"]) == (v == "home"))]
        if hit:
            k = (round(sum(dp.units(r["line"], r["result"] == "W") for r in hit), 6), len(hit))
            best = k if best is None or k > best else best
    return best


@pytest.mark.parametrize("seed", range(6))
def test_best_rule_is_the_true_maximum(seed):
    rnd = random.Random(seed)
    rows = [_row(i, rnd.choice([-250, -180, -150, -125, -110, 100, 115, 140, 190]), round(rnd.uniform(0, 30), 2),
                 rnd.random() < .5, rnd.random() < .55) for i in range(30)]
    rule = dp.best_rule(rows)
    assert (rule["units"], rule["bets"]) == _brute(rows)
    hits = [r for r in rows if dp.fits(rule, r)]
    assert len(hits) == rule["bets"] and round(sum(dp.units(r["line"], r["result"] == "W") for r in hits), 2) == rule["units"]


def test_open_ended_bounds_and_plain_words():
    rows = [_row(1, -150, 5, True, True), _row(2, 120, 10, True, True), _row(3, 200, 20, False, False)]
    rule = dp.best_rule(rows)
    assert rule["lo"] is None and rule["hi"] == 120 and rule["dlo"] == 0 and rule["dhi"] == 10
    assert dp.fits(rule, _row(4, -900, 1, False, True))  # a bigger favorite than any so far still counts
    assert dp.describe(rule) == "Bet the pick when it has any line up to +120 and a differential of 10 or less; home or away."


# ---------------------------------------------------------------- a whole day, with stand-ins for the NHL and ESPN
def _game(gid, day, hour, away, home, ag=None, hg=None, ats=None, hts=None):
    start = f"{day}T{hour:02d}:00:00Z"
    return dict(id=gid, date=day, start=start, away=away, home=home, away_goals=ag, home_goals=hg, away_ts=ats, home_ts=hts)


@pytest.fixture
def season(tmp_path, monkeypatch):
    """Four teams. Oct 20: past games (team scores AAA 80, BBB 60, CCC 75, DDD 65). Oct 22: AAA @ BBB, CCC @ DDD."""
    data = tmp_path / "data"; data.mkdir()
    past = [_game(1, "2026-10-20", 23, "AAA", "BBB", 4, 1, 80.0, 60.0), _game(2, "2026-10-20", 23, "CCC", "DDD", 3, 2, 75.0, 65.0)]
    picks = [dict(dp.new_row(g, past), result="W", final="", line=-130, source="DraftKings closing") for g in past]
    (data / "games.json").write_text(json.dumps(past)); (data / "picks.json").write_text(json.dumps(picks))
    tonight = {3: ("AAA", "BBB", 23), 4: ("CCC", "DDD", 1)}  # game 4 starts 1:00 UTC Oct 23 (8 pm CT Oct 22)
    finals = {}  # game id -> scored game, once "played"

    def schedule(day):
        out = []
        for gid, (a, h, hour) in tonight.items():
            start = f"2026-10-{22 if hour > 12 else 23}T{hour:02d}:00:00Z"
            out.append(dict(id=gid, date="2026-10-22", startTimeUTC=start, gameType=2, gameState="OFF" if gid in finals else "FUT",
                            awayTeam={"abbrev": a}, homeTeam={"abbrev": h}))
        return out

    def score_new_games(st, now, api):
        have = {g["id"] for g in st["games"]}
        st["games"] += [g for gid, g in finals.items() if gid not in have]

    lines = {"now": {("AAA", "BBB"): (-150, 130), ("CCC", "DDD"): (110, -130)},
             "close": {("AAA", "BBB"): (-170, 150), ("CCC", "DDD"): (105, -125)}}

    def espn_lines(day):
        return {k: {side: {"DraftKings": {"now": lines["now"].get(k, (None, None))[i], "close": v[i]}}
                    for i, side in enumerate(("away", "home"))} for k, v in lines["close"].items()}

    monkeypatch.setattr(dp, "schedule", schedule)
    monkeypatch.setattr(dp, "score_new_games", score_new_games)
    monkeypatch.setattr(dp, "espn_lines", espn_lines)
    sent = []
    monkeypatch.setattr(dp, "send_mail", lambda *a: sent.append(a) or "owner@example.com")
    monkeypatch.setenv("SMTP_USER", "x"); monkeypatch.setenv("SMTP_PASSWORD", "y")
    return dict(data=data, finals=finals, lines=lines, sent=sent)


def at(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def _sheet(data, tab):
    return [r for r in openpyxl.load_workbook(data / dp.XLSX)[tab].iter_rows(min_row=9, values_only=True) if r[0]]


def test_a_day_of_picks(season):
    data, finals, sent = season["data"], season["finals"], season["sent"]
    assert dp.run(data, at("2026-10-22T10:00:00Z")).startswith("nothing due")      # 5 am CT: too early for the morning
    assert dp.run(data, at("2026-10-22T11:30:00Z")).startswith("morning")           # 6:30 am CT
    assert dp.run(data, at("2026-10-22T20:30:00Z")).startswith("nothing due")      # 3:30 pm: not 2 hours out yet
    out = dp.run(data, at("2026-10-22T21:05:00Z"))                                  # 4:05 pm: 2 hours before 6 pm
    assert "pre-game" in out and len(sent) == 1
    subj, text, page, xlsx = sent[0]
    assert "AAA" in text and "CCC @ DDD" in text and xlsx.name == dp.XLSX
    picks = {r["id"]: r for r in json.loads((data / "picks.json").read_text())}
    assert picks[3]["pick"] == "AAA" and picks[3]["line"] == -150 and "at pick time" in picks[3]["source"]
    assert picks[4]["pick"] == "CCC" and picks[4]["line"] == 110
    emailed = {i for i, r in picks.items() if r.get("emailed")}
    assert emailed == {i for i, r in picks.items() if r["fits"]} and emailed <= {3, 4}
    assert dp.run(data, at("2026-10-22T21:20:00Z")).startswith("nothing due") and len(sent) == 1  # once a day

    # a re-send keeps the lines that were emailed, even if they've moved
    season["lines"]["now"][("AAA", "BBB")] = (-200, 170)
    dp.run(data, at("2026-10-22T22:00:00Z"), send_now=True)
    assert json.loads((data / "picks.json").read_text())[2]["line"] == -150 and len(sent) == 2

    # the games are played; next morning they're graded on the emailed line
    finals[3] = _game(3, "2026-10-22", 23, "AAA", "BBB", 2, 3, 55.0, 85.0)
    finals[4] = _game(4, "2026-10-22", 1, "CCC", "DDD", 5, 1, 90.0, 50.0) | {"start": "2026-10-23T01:00:00Z"}
    assert dp.run(data, at("2026-10-23T11:30:00Z")).startswith("morning")
    picks = {r["id"]: r for r in json.loads((data / "picks.json").read_text())}
    assert picks[3]["result"] == "L" and picks[4]["result"] == "W"
    dyn = _sheet(data, dp.DYNAMIC)
    assert [(r[1], r[2], r[3], r[6]) for r in dyn] == [(f'{picks[i]["away"]} @ {picks[i]["home"]}', picks[i]["pick"], picks[i]["line"],
                                                        picks[i]["result"]) for i in sorted(emailed)]
    assert len(_sheet(data, "2026-27")) == 4 and len(_sheet(data, "Daily rule")) >= 0


def test_a_missed_day_is_filled_in_with_closing_lines_and_never_counts_as_emailed(season):
    data, finals, sent = season["data"], season["finals"], season["sent"]
    finals[3] = _game(3, "2026-10-22", 23, "AAA", "BBB", 2, 3, 55.0, 85.0)
    finals[4] = _game(4, "2026-10-22", 1, "CCC", "DDD", 5, 1, 90.0, 50.0) | {"start": "2026-10-23T01:00:00Z"}
    assert "pre-game" not in dp.run(data, at("2026-10-23T03:00:00Z"))  # 10 pm CT: every game has started, no email
    dp.run(data, at("2026-10-23T11:30:00Z"))
    picks = {r["id"]: r for r in json.loads((data / "picks.json").read_text())}
    assert picks[3]["line"] == -170 and picks[3]["source"] == "DraftKings closing (missed the pick-time run)"
    assert not sent and not any(r.get("emailed") for r in picks.values()) and _sheet(data, dp.DYNAMIC) == []
