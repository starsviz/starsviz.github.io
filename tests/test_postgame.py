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

COUNTDOWN = "\n\n".join(f"## #{n}: Stat number {n} tells the story.\nWhy it mattered.\nMore on it." for n in range(10, 0, -1))
ANSWER = f"""Let me check a couple of things first.

=== SUMMARY ===
The Stars outshot Colorado and lost anyway.

=== COUNTDOWN ===
{COUNTDOWN}

=== NO FILTER ===
## Why was Johnston *not* in the lineup?
He'd played every game. Fans wanted to know.

## What's wrong with the power play?
It's 2 for 14.

=== STATS ===
- **Seguin** scored a 100, his best game so far.
- Dallas took 56% of the 5-on-5 shot attempts & still lost.

=== SUBJECT LINES ===
1. Three shots in the third
2. Seguin's perfect night wasn't enough
3. Who sat Johnston?
4. The power play is 2 for 14
5. Outshot, outplayed, out of luck"""
START = ANSWER.index("=== SUMMARY ===")


@pytest.fixture(scope="module")
def brief(sample_page) -> dict:
    return pe.make_brief(sample_page)


def test_brief_matches_the_page(brief, sample_data):
    g = sample_data["games"][-1]
    assert brief["game"]["id"] == g["id"] and brief["game"]["number"] == len(sample_data["games"])
    assert brief["game"]["start"] and brief["game"]["siteHeadline"]
    assert brief["game"]["official"] is True and brief["game"]["onIceStatsIn"] is True  # the sample season is complete
    assert brief["game"]["score"] == {"DAL": g["gf"], g["opp"]: g["ga"]}
    sk = brief["dallasSkatersByIceTime"]
    assert len(sk) == len(g["sk"]) and len(brief["dallasGoalies"]) == len(g["gk"])
    assert "score" not in json.dumps(sk).lower(), "no player scores in the email: they shift as games come in"
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
    md = ANSWER[START:]
    sec = pe.split(md)
    assert sec["STATS"].startswith("- **Seguin**") and sec["SUMMARY"].startswith("The Stars")
    items = pe.countdown(sec["COUNTDOWN"])
    assert [n for n, _, _ in items] == list(range(10, 0, -1))
    assert items[0][1:] == ("Stat number 10 tells the story.", "Why it mattered. More on it.")
    with pytest.raises(ValueError, match="#10 to #1"):
        pe.countdown(sec["COUNTDOWN"].replace("## #4:", "## #11:"))
    assert len(pe.countdown(sec["COUNTDOWN"].replace("## #", "## "))) == 10, "takes the number with or without #"
    h = pe.md_html(sec["STATS"])
    assert h.count("<li>") == 2 and "<strong>Seguin</strong>" in h and "&amp;" in h and "<ul>" in h
    h = pe.md_html(sec["NO FILTER"])
    assert h.count("<h2>") == 2 and h.count("<p>") == 2 and "<em>not</em>" in h
    assert pe.md_html(sec["SUBJECT LINES"]).count("<li>") == 5 and "<ol>" in pe.md_html(sec["SUBJECT LINES"])
    with pytest.raises(ValueError, match="SUBJECT LINES"):
        pe.split(md[:md.index("=== SUBJECT LINES ===")])

    text, page = pe.email_bodies(dict(brief, site="https://example.com/"), md, ["note one", "note two"])
    order = ["Subject line ideas", "Three shots in the third", "<p>The Stars outshot",
             "<p>Let's count down the 10 most telling stats from the game.</p>",
             "<h2>#10: Stat number 10 tells the story.</h2>\n<p>Why it mattered. More on it.</p>", "<h2>#1: ", "<h1>No Filter</h1>",
             '<p>Here are the "No Filter" questions I would have liked to see at the postgame presser.</p>',
             "Why was Johnston", "<h1>Some stats that stood out</h1>", "<strong>Seguin</strong> scored",
             "Check out the player grades", "note two"]
    at = [page.index(x) for x in order]
    assert at == sorted(at), "subject ideas, summary, countdown, No Filter, stats, site link, notes"
    assert ('at the <a href="https://example.com/">Stick Language Stats page</a>.' in page)
    assert "Stick Language Stats page (https://example.com/)" in text and text.index("NO FILTER") < text.index("SOME STATS")
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
    monkeypatch.setattr(pe, "ask_claude", lambda b: (calls.append(b["game"]["id"]) or ANSWER[START:],
                                                        {"turns": 3, "model": "claude-opus-5-5"}))
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

    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-abc\ndef ")

    def fake_run(cmd, input, cwd, env, **kw):
        seen.update(cmd=cmd, input=input, cwd=cwd, token=env["CLAUDE_CODE_OAUTH_TOKEN"])
        res = {"type": "result", "subtype": "success", "is_error": False, "num_turns": 4, "result": ANSWER,
               "modelUsage": {"claude-opus-5-5": {}, "claude-haiku-5-5": {}}}
        return pe.subprocess.CompletedProcess(cmd, 0, json.dumps(res), "")
    monkeypatch.setattr(pe.subprocess, "run", fake_run)
    md, usage = pe.ask_claude(brief)
    assert md.startswith("=== SUMMARY ===") and "Let me check" not in md
    assert usage == {"turns": 4, "model": "claude-opus-5-5"}
    assert seen["cmd"][:2] == ["claude", "-p"] and "--system-prompt" in seen["cmd"] and "WebSearch,WebFetch" in seen["cmd"]
    assert '"siteHeadline"' in seen["input"]
    assert not Path(seen["cwd"]).exists(), "ran in a throwaway folder"
    assert seen["token"] == "sk-ant-oat01-abcdef", "line breaks from copying the token are dropped"

    monkeypatch.setattr(pe.subprocess, "run", lambda cmd, **kw: pe.subprocess.CompletedProcess(cmd, 1, json.dumps(
        {"type": "result", "subtype": "success", "is_error": True, "result": "Failed to authenticate"}), ""))
    with pytest.raises(SystemExit, match="Failed to authenticate"):
        pe.ask_claude(brief)


def test_the_email_gives_up_waiting_when_the_page_does():
    sys.path.insert(0, str(ROOT))
    import stars_viz as sv
    assert pe.GIVE_UP_HOURS == sv.STATS_WAIT_HOURS
