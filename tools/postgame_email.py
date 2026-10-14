#!/usr/bin/env python3
"""
postgame_email.py - after each game, emails the owner two things to paste into
Substack: (1) the game's noteworthy stats as bullets, and (2) "No Filter": a
one-paragraph recap and the questions a reporter would ask the coach if they
could ask anything, each with a paragraph on why it needs asking. Claude writes
both from the page's own numbers and a few web searches (injuries, what the
coach said, how fans and local media reacted).

    # 1. pull one game's numbers out of the built page (default: the latest game)
    python tools/postgame_email.py brief _site/index.html --out postgame/brief.json [--game 2026020075]
    # 2. write the email and send it (once per game; see "When it sends" below)
    python tools/postgame_email.py send postgame/brief.json [--force] [--dry-run]

Settings come from environment variables (GitHub repo secrets in the workflow):
    CLAUDE_CODE_OAUTH_TOKEN              Claude Code on the owner's Claude subscription (from `claude setup-token`;
                                         not needed on a Mac where the `claude` command is logged in)
    SMTP_USER, SMTP_PASSWORD             the Gmail address that sends it and a Google "app password"
    EMAIL_TO                             where it goes (default: SMTP_USER)
    SMTP_HOST, SMTP_PORT                 default smtp.gmail.com, 465
If Claude or the SMTP settings are missing, `send` does nothing and says so. Needs the `claude` command
(npm install -g @anthropic-ai/claude-code).

When it sends: the workflow runs this right after each publish of the site, and it sends
once the published page has the game's final stats: the NHL has made the game official
and the on-ice numbers (the last to arrive) are in for every skater. If they still aren't
GIVE_UP_HOURS after puck drop, it sends anyway and says what was missing. Once per game
(game IDs already sent are kept in --state), and never for a game that started more than
STALE_HOURS ago. --force skips all of these checks.

Reddit's post-game thread was tried and dropped (Oct 2026): Reddit's API now only gives
new apps to moderators, and it blocks scripts that read the site without it.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import shutil
import smtplib
import subprocess
import sys
import tempfile
from email.message import EmailMessage
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

MODEL = "opus"     # Claude Code's name for the newest Opus
GIVE_UP_HOURS = 18  # send without the final stats if the NHL still hasn't posted them by then
STALE_HOURS = 48    # a game older than this never sends (protects against repeats if --state is ever lost)

SYSTEM = """\
You write post-game material for Stick Language, a Substack about the Dallas Stars. Its writer is building a name as \
"the visual storyteller": he uses stats to show how a game went, player by player. His stats site scores every Stars \
skater after every game. He pastes what you write into his drafts and edits from there.

You get the game's data (JSON) from his site: scoring, team stats, every Dallas skater ranked by player score with \
his season context, the goalies, lineup changes, and the last 10 games. You also have web search. Use it up to six \
times for what the data can't tell you: injuries, scratches and lineup decisions, what the coach and players said \
after the game, line combinations, storylines from recent games, and how Stars fans and local media (beat writers, \
fan blogs like Defending Big D) reacted. Look up who the Stars' head coach is rather than assuming.

About the player score: each stat is compared with how Stars players at the same position usually do in a game, \
weighted, and scaled like a school grade. 70 is a typical game, the 80s a B, the 90s an A, 100 is the cap. The \
median is about 68 and under 60 is a rough night. The offense score and two-way score are its two halves, on the \
same scale. vsHisAverage is the score minus the player's own season average. Early in the season the averages rest \
on few games, so say "so far" where that matters. The on-ice 5-on-5 attempt share is often called Corsi; explain it \
in plain words when you use it. PDO is 5-on-5 shooting percentage plus save percentage; 1.000 is average, and \
a game far from it was mostly about bounces and goaltending. Null means the NHL hasn't posted that number yet.

Write two things.

PART 1, NOTEWORTHY STATS: 8 to 14 bullets with the most interesting and noteworthy numbers from this game, one or \
two sentences each, leading with the fact. Favor what a fan won't get from the box score: player scores against the \
player's normal, streaks and droughts, season highs and lows, ice-time changes that show who the coach trusts, \
special teams, shot quality (slot attempts), the period where the game turned, the goalie against his season. Every \
number must come from the game data, exactly as given. Anything from web search must be fact, not opinion.

PART 2, NO FILTER: first a one-paragraph recap of the game (4 to 6 sentences). Then 4 to 6 questions a reporter \
would ask the head coach after this game if they could ask anything, with no worry about access or press \
credentials: the questions fans wish someone had the nerve to ask. Pointed, specific and \
fair. They can be about players, the team, this game, or a trend over several games: lineup and ice-time decisions, \
line combinations, the goalie, special-teams units, systems, effort and accountability. No cheap shots, nothing \
personal. Each question is one or two sentences, phrased the way you'd ask it in the room (address the coach as \
"you", name the players). Under each question, one paragraph on why it needs asking, backed by specific numbers and, \
where it helps, by what you found: what the coach said, what fans and writers are asking. When fans are angry or \
puzzled about something, check it against the numbers and say whether the numbers back them up. Pick only the best \
questions.

Put what other writers said in your own words rather than copying their sentences. Never invent quotes. If you mention something a coach or player said, it \
must come from a source you found.

Style: plain, direct American English, like a sharp beat writer. Short sentences. No hype, no clichés, no em dashes, \
no "it's not X, it's Y", no lists of three for rhythm, no closing summaries or morals. The writer is wary of anything \
that reads as AI-written.

Reply in exactly this format, with nothing after it:

=== STATS ===
- First bullet.
- Second bullet.

=== NO FILTER ===
Recap paragraph.

## First question?
Context paragraph.

## Second question?
Context paragraph.

Plain text apart from **bold** for emphasis, used sparingly. No links, no citation markers, no other headings."""


# ---------------------------------------------------------------- step 1: the game's numbers

def make_brief(page: Path, game_id: int | None = None) -> dict:
    """Runs tools/game_brief.js inside the built page, so every number matches the site. The page's code
    lives inside one closure, so the function is added at the end of that closure in a copy of the page."""
    from playwright.sync_api import sync_playwright

    src = page.read_text(encoding="utf-8")
    end = src.rindex("})();")  # the end of the page's main script
    fn = (HERE / "game_brief.js").read_text(encoding="utf-8")
    src = f"{src[:end]}window.__gameBrief = {fn.strip().rstrip(';')};\n{src[end:]}"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page()
        pg.route("**/*", lambda r: r.continue_() if r.request.url.startswith(("data:", "blob:")) else r.abort())
        pg.set_content(src)
        pg.wait_for_selector("#quad svg")
        brief = pg.evaluate("id => window.__gameBrief(id)", game_id)
        browser.close()
    if not brief:
        raise SystemExit(f"Game {game_id} isn't on the page.")
    return brief


# ---------------------------------------------------------------- step 2: write it and send it

def start_time(brief: dict) -> dt.datetime | None:
    s = brief["game"].get("start")
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def why_not_now(brief: dict, sent: list, now: dt.datetime) -> str:
    """Empty if the email is due, else the reason it isn't."""
    g = brief["game"]
    if g["id"] in sent:
        return f"game {g['id']} was already emailed"
    start = start_time(brief)
    hours = (now - start).total_seconds() / 3600 if start else None
    if hours is not None and hours > STALE_HOURS:
        return f"game {g['id']} started {hours:.0f} hours ago; too old to email"
    missing = stats_missing(brief)
    if missing and (hours is None or hours < GIVE_UP_HOURS):
        return f"waiting for the NHL's final stats ({missing})"
    return ""


def stats_missing(brief: dict) -> str:
    g = brief["game"]
    return " and ".join(x for x, ok in (("the game isn't official yet", g.get("official")),
                                        ("on-ice numbers aren't in yet", g.get("onIceStatsIn"))) if not ok)


def ask_claude(brief: dict) -> tuple[str, dict]:
    """Runs Claude Code (the `claude` command) on the owner's Claude subscription, not a paid API key.
    In GitHub Actions it signs in with CLAUDE_CODE_OAUTH_TOKEN (made once with `claude setup-token`);
    on a Mac where `claude` is logged in, it just works."""
    g = brief["game"]
    parts = [f"<game_data>\n{json.dumps(brief, indent=1, ensure_ascii=False)}\n</game_data>",
             f"Write both parts for game {g['number']} of the season, the Stars' {g['result']} against the "
             f"{g['opponent']} on {g['date']}."]
    cmd = ["claude", "-p", "--model", MODEL, "--effort", "high", "--system-prompt", SYSTEM,
           "--tools", "WebSearch,WebFetch", "--allowedTools", "WebSearch", "WebFetch",
           "--output-format", "json", "--no-session-persistence"]
    env = dict(os.environ)
    if env.get("CLAUDE_CODE_OAUTH_TOKEN"):  # a long token copied out of Terminal can pick up a line break
        env["CLAUDE_CODE_OAUTH_TOKEN"] = "".join(env["CLAUDE_CODE_OAUTH_TOKEN"].split())
    with tempfile.TemporaryDirectory() as cwd:  # an empty folder, so it doesn't pick up this repo's CLAUDE.md
        run = subprocess.run(cmd, input="\n\n".join(parts), capture_output=True, text=True, cwd=cwd, env=env, timeout=20 * 60)
    try:
        res = json.loads(run.stdout)
    except ValueError:
        raise SystemExit(f"Claude Code didn't run (exit {run.returncode}):\n{run.stderr or run.stdout}")
    if res.get("is_error") or res.get("subtype") != "success":
        raise SystemExit(f"Claude Code failed: {res.get('result') or res.get('subtype')}")
    u = res.get("usage") or {}
    usage = {"turns": res.get("num_turns", 0),
             "searches": (u.get("server_tool_use") or {}).get("web_search_requests", 0),
             "model": ", ".join(res.get("modelUsage") or {}) or MODEL}
    out = res.get("result") or ""
    if "=== STATS ===" not in out or "=== NO FILTER ===" not in out:
        raise SystemExit("Claude's answer didn't come back in the expected format:\n\n" + out)
    return out[out.index("=== STATS ==="):].strip(), usage


def split(md: str) -> tuple[str, str]:
    stats, nofilter = md.split("=== NO FILTER ===", 1)
    return stats.replace("=== STATS ===", "").strip(), nofilter.strip()


def inline(s: str) -> str:
    s = html.escape(s, quote=False)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    return re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<em>\1</em>", s)


def md_html(md: str) -> str:
    """Just the markdown Claude is asked for: "- " bullets, "## " headings, paragraphs, **bold**, *italics*."""
    out, items = [], []
    for block in re.split(r"\n\s*\n", md.strip()):
        for line in block.strip().splitlines():
            line = line.strip()
            if line.startswith(("- ", "* ")):
                items.append(f"<li>{inline(line[2:])}</li>")
                continue
            if items:
                out.append("<ul>" + "".join(items) + "</ul>")
                items = []
            if line.startswith("#"):
                out.append(f"<h2>{inline(line.lstrip('#').strip())}</h2>")
            elif line:
                out.append(f"<p>{inline(line)}</p>")
    if items:
        out.append("<ul>" + "".join(items) + "</ul>")
    return "\n".join(out)


def subject(brief: dict) -> str:
    g = brief["game"]
    res = {"W": "W", "L": "L", "OTL": f"{'SO' if g['decidedIn'] == 'SO' else 'OT'}L"}[g["result"]]
    where = "vs" if g["homeOrAway"] == "home" else "at"
    return f"Game {g['number']}: {res} {g['score']['DAL']}-{g['score'][g['opponentAbbrev']]} {where} {g['opponent']} · stats + No Filter"


def email_bodies(brief: dict, md: str, notes: list[str]) -> tuple[str, str]:
    stats, nofilter = split(md)
    g = brief["game"]
    head = f"{brief['game']['siteHeadline']} ({g['date']}, record {g['recordAfter']})"
    text = f"{head}\n\nNOTEWORTHY STATS\n\n{stats}\n\n\nNO FILTER\n\n{nofilter}\n\n--\n" + "\n".join(notes)
    style = ("font-family: Georgia, serif; font-size: 17px; line-height: 1.55; color: #1a1a1a; max-width: 680px")
    page = f"""<!doctype html><html><body style="{style}">
<p style="font-family: Arial, sans-serif; font-size: 13px; color: #666">{html.escape(head)}</p>
<h1>Noteworthy stats</h1>
{md_html(stats)}
<hr>
<h1>No Filter</h1>
{md_html(nofilter)}
<hr>
<p style="font-family: Arial, sans-serif; font-size: 12px; color: #888">{'<br>'.join(html.escape(n) for n in notes)}</p>
</body></html>"""
    return text, page


def send_mail(subj: str, text: str, page: str) -> str:
    # Google shows app passwords in groups of four ("abcd efgh ijkl mnop"); the spaces aren't part of it
    user, pw = os.environ["SMTP_USER"].strip(), "".join(os.environ["SMTP_PASSWORD"].split())
    to = os.environ.get("EMAIL_TO") or user
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subj, user, to
    msg.set_content(text)
    msg.add_alternative(page, subtype="html")
    with smtplib.SMTP_SSL(os.environ.get("SMTP_HOST") or "smtp.gmail.com", int(os.environ.get("SMTP_PORT") or 465), timeout=60) as s:
        s.login(user, pw)
        s.send_message(msg)
    return to


def send(brief_path: Path, state_path: Path, out_dir: Path, force: bool, dry_run: bool) -> bool:
    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    sent = json.loads(state_path.read_text()) if state_path.exists() else []
    g = brief["game"]
    reason = "" if force else why_not_now(brief, sent, dt.datetime.now(dt.timezone.utc))
    if reason:
        print(f"Post-game email not sent: {reason}.")
        return False
    needed = () if dry_run else ("SMTP_USER", "SMTP_PASSWORD")
    missing = [k for k in needed if not os.environ.get(k)]
    if not shutil.which("claude"):
        missing.append("the claude command")
    elif os.environ.get("GITHUB_ACTIONS") and not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        missing.append("CLAUDE_CODE_OAUTH_TOKEN")
    if missing:
        print(f"Post-game email isn't set up yet (missing {', '.join(missing)}); skipping.")
        return False

    md, usage = ask_claude(brief)
    missing = stats_missing(brief)
    notes = [f"Sent without the NHL's final stats: {missing}." if missing else "Written from the NHL's final stats.",
             f"Written by Claude ({usage['model']}) on your subscription: {usage['searches']} web searches, {usage['turns']} turns."]
    text, page = email_bodies(brief, md, notes)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "email.md").write_text(md + "\n", encoding="utf-8")
    (out_dir / "email.html").write_text(page, encoding="utf-8")
    print(f"Wrote {out_dir / 'email.html'}  ({'; '.join(notes)})")
    if dry_run:
        print("Dry run: not emailed.")
        return False
    to = send_mail(subject(brief), text, page)
    print(f"Emailed game {g['number']} to {to}.")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(sorted(set(sent) | {g["id"]})))
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("brief", help="pull one game's numbers out of the built page")
    b.add_argument("page")
    b.add_argument("--out", default="postgame/brief.json")
    b.add_argument("--game", type=int, help="game ID (default: the latest game)")
    s = sub.add_parser("send", help="write the email with Claude and send it, if it's due")
    s.add_argument("brief")
    s.add_argument("--state", default=".postgame_state/sent.json", help="game IDs already emailed")
    s.add_argument("--out-dir", default="postgame", help="where to save a copy of the email")
    s.add_argument("--force", action="store_true", help="send even if already sent, too early or too old")
    s.add_argument("--dry-run", action="store_true", help="write the email but don't send it (needs only Claude)")
    a = ap.parse_args(argv)

    if a.cmd == "brief":
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        brief = make_brief(Path(a.page), a.game)
        out.write_text(json.dumps(brief, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"Brief: {out}  (game {brief['game']['number']} vs {brief['game']['opponentAbbrev']})")
        return
    did = send(Path(a.brief), Path(a.state), Path(a.out_dir), a.force, a.dry_run)
    if os.environ.get("GITHUB_OUTPUT"):  # tells the workflow to save the "already sent" list
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"sent={'true' if did else 'false'}\n")


if __name__ == "__main__":
    main()
