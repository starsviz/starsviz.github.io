"""The post-game email (tools/postgame_email.py, tools/game_brief.js).
Nothing here calls Claude or sends mail: those are replaced with stand-ins."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import postgame_email as pe  # noqa: E402

ANSWER = """Let me check a couple of things first.

=== STATS ===
- **Seguin** scored a 100, his best game so far.
- Dallas took 56% of the 5-on-5 shot attempts & still lost.

=== NO FILTER ===
The Stars outshot Colorado and lost anyway.

## Why was Johnston *not* in the lineup?
He'd played every game. Fans wanted to know.

## What's wrong with the power play?
It's 2 for 14."""


@pytest.fixture(scope="module")
def brief(sample_page) -> dict:
    return pe.make_brief(sample_page)


def test_brief_matches_the_page(brief, sample_data):
    g = sample_data["games"][-1]
    assert brief["game"]["id"] == g["id"] and brief["game"]["number"] == len(sample_data["games"])
    assert brief["game"]["start"] and brief["game"]["siteHeadline"]
    assert brief["game"]["official"] is True and brief["game"]["onIceStatsIn"] is True  # the sample season is complete
    assert brief["game"]["score"] == {"DAL": g["gf"], g["opp"]: g["ga"]}
    sk = brief["dallasSkatersRankedByPlayerScore"]
    assert len(sk) == len(g["sk"]) and len(brief["dallasGoalies"]) == len(g["gk"])
    scores = [s["playerScore"] for s in sk]
    assert scores == sorted(scores, reverse=True) and all(0 <= x <= 100 for x in scores)
    assert sum(s["tonight"]["goals"] for s in sk) == g["gf"] == sum(x["team"] == "DAL" for x in brief["goals"])
    assert len(brief["recentGames"]) == 10 and brief["recentGames"][-1]["game"] == brief["game"]["number"]
    json.dumps(brief)  # plain JSON all the way down


def test_brief_for_an_earlier_game(sample_page, sample_data):
    g = sample_data["games"][9]
    b = pe.make_brief(sample_page, g["id"])
    assert b["game"]["number"] == 10 and b["season"]["gamesPlayed"] == 10 and b["season"]["teamForm"] is None


def _brief(start: dt.datetime, gid: int = 2026020100, official=True, on_ice=True) -> dict:
    return {"game": {"id": gid, "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "official": official, "onIceStatsIn": on_ice}}


def test_when_it_sends():
    """After the final stats are on the published page, not after a set time."""
    now = dt.datetime(2026, 10, 14, 5, 0, tzinfo=dt.timezone.utc)
    hours = lambda h: now - dt.timedelta(hours=h)
    assert pe.why_not_now(_brief(hours(3)), [], now) == ""
    assert "isn't official" in pe.why_not_now(_brief(hours(3), official=False), [], now)
    assert "on-ice" in pe.why_not_now(_brief(hours(8), on_ice=False), [], now)
    assert pe.why_not_now(_brief(hours(20), on_ice=False), [], now) == "", "gives up waiting after 18 hours"
    assert "too old" in pe.why_not_now(_brief(hours(50)), [], now)
    assert "already" in pe.why_not_now(_brief(hours(3)), [2026020100], now)


def test_email_format(brief):
    md = ANSWER[ANSWER.index("=== STATS ==="):]
    stats, nofilter = pe.split(md)
    assert stats.startswith("- **Seguin**") and nofilter.startswith("The Stars")
    h = pe.md_html(stats)
    assert h.count("<li>") == 2 and "<strong>Seguin</strong>" in h and "&amp;" in h and "<ul>" in h
    h = pe.md_html(nofilter)
    assert h.count("<h2>") == 2 and h.count("<p>") == 3 and "<em>not</em>" in h
    text, page = pe.email_bodies(brief, md, ["note one", "note two"])
    assert "NO FILTER" in text and "<h1>No Filter</h1>" in page and "note two" in page
    assert pe.subject(brief).startswith(f"Game {brief['game']['number']}: ")


def test_send_once_per_game(brief, tmp_path, monkeypatch):
    path = tmp_path / "brief.json"
    path.write_text(json.dumps(dict(brief, game=dict(brief["game"], start=None))))  # stats complete, no start time: due now
    for k in ("CLAUDE_CODE_OAUTH_TOKEN", "SMTP_USER", "SMTP_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(pe.shutil, "which", lambda name: "/usr/bin/" + name)
    state, out = tmp_path / "state" / "sent.json", tmp_path / "out"
    assert pe.send(path, state, out, force=False, dry_run=False) is False and not out.exists(), "skips until set up"

    monkeypatch.setenv("SMTP_USER", "me@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "test")
    assert pe.send(path, state, out, force=False, dry_run=False) is False, "no Claude token in GitHub Actions: skips"
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "test")
    calls = []
    monkeypatch.setattr(pe, "ask_claude", lambda b: (calls.append(b["game"]["id"]) or ANSWER[ANSWER.index("=== STATS ==="):],
                                                        {"turns": 3, "searches": 2, "model": "claude-opus-5-5"}))
    mails = []
    monkeypatch.setattr(pe, "send_mail", lambda *a: mails.append(a) or "me@example.com")
    assert pe.send(path, state, out, force=False, dry_run=False) is True
    assert calls == [brief["game"]["id"]]
    assert len(mails) == 1 and json.loads(state.read_text()) == [brief["game"]["id"]]
    assert (out / "email.md").exists() and (out / "email.html").exists()
    assert pe.send(path, state, out, force=False, dry_run=False) is False and len(mails) == 1, "only once per game"
    assert pe.send(path, state, out, force=True, dry_run=False) is True and len(mails) == 2, "--force resends"


def test_ask_claude_runs_claude_code(brief, monkeypatch):
    seen = {}

    def fake_run(cmd, input, cwd, **kw):
        seen.update(cmd=cmd, input=input, cwd=cwd)
        res = {"type": "result", "subtype": "success", "is_error": False, "num_turns": 4, "result": ANSWER,
               "usage": {"server_tool_use": {"web_search_requests": 3}}, "modelUsage": {"claude-opus-5-5": {}}}
        return pe.subprocess.CompletedProcess(cmd, 0, json.dumps(res), "")
    monkeypatch.setattr(pe.subprocess, "run", fake_run)
    md, usage = pe.ask_claude(brief)
    assert md.startswith("=== STATS ===") and "Let me check" not in md
    assert usage == {"turns": 4, "searches": 3, "model": "claude-opus-5-5"}
    assert seen["cmd"][:2] == ["claude", "-p"] and "--system-prompt" in seen["cmd"] and "WebSearch,WebFetch" in seen["cmd"]
    assert '"siteHeadline"' in seen["input"]
    assert not Path(seen["cwd"]).exists(), "ran in a throwaway folder"

    monkeypatch.setattr(pe.subprocess, "run", lambda cmd, **kw: pe.subprocess.CompletedProcess(cmd, 1, json.dumps(
        {"type": "result", "subtype": "success", "is_error": True, "result": "Failed to authenticate"}), ""))
    with pytest.raises(SystemExit, match="Failed to authenticate"):
        pe.ask_claude(brief)
