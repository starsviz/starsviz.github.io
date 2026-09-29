#!/usr/bin/env python3
"""
stars_viz.py - Dallas Stars game cards and season trend dashboards from the
NHL's public (free, unofficial, no key needed) API.

    python stars_viz.py game                     # latest completed game
    python stars_viz.py game --id 2025020054     # a specific game
    python stars_viz.py trend                    # season-to-date trends
    python stars_viz.py trend --season 20252026  # a past season
    python stars_viz.py both                     # both graphics

Each run writes a PNG (ready to drop into Substack) and a short notes .md
with the key facts, which you can write from or hand to Claude.

Works for any team: --team COL. Change the accent color with --color.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import logging
import sys
import time
from pathlib import Path
from urllib.parse import quote

import matplotlib
import matplotlib.ticker

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.gridspec import GridSpec  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Arc, Circle, FancyBboxPatch, Rectangle  # noqa: E402

try:
    import requests
except ImportError:  # only needed when fetching
    requests = None

WEB = "https://api-web.nhle.com/v1"
STATS = "https://api.nhle.com/stats/rest/en"
FINAL_STATES = ("FINAL", "OFF")   # game over (FINAL = just ended, OFF = stats made official)
OFFICIAL = "OFF"                  # only then is a game cached for good; FINAL stats can still be corrected

# ---- palette (validated: team green vs neutral gray passes CVD + contrast) ----
TEAM_COLOR = "#00754a"     # Stars green, stepped to clear the chroma floor
OPP = "#8a8984"            # opponent / de-emphasis gray
OPP_LIGHT = "#c9c8c2"      # OT/SO losses
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#8f8e89"
GRID = "#ebeae6"
RINK = "#d6d5cf"

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
plt.rcParams.update({
    "font.family": ["Inter", "Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID,
    "axes.labelcolor": INK2,
    "xtick.color": INK2,
    "ytick.color": INK2,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
})


# --------------------------------------------------------------------------
# Fetching + cache
# --------------------------------------------------------------------------
def url_schedule(team: str, season: str = "now") -> str:
    return f"{WEB}/club-schedule-season/{team}/{season}"


def url_game(game_id: int, part: str) -> str:
    return f"{WEB}/gamecenter/{game_id}/{part}"  # boxscore | play-by-play | right-rail


def url_team_report(report: str, team_id: int, season: int) -> str:
    exp = f"teamId={team_id} and seasonId={season} and gameTypeId=2"
    return (f"{STATS}/team/{report}?isAggregate=false&isGame=true&start=0&limit=100"
            f"&cayenneExp={quote(exp)}")


class Api:
    """Tiny cached client. Games whose stats are official are cached for good;
    everything else refreshes after `ttl` seconds. --offline reads only from cache.
    `final_only_cache`: keep for good once the response itself says the game is OFF.
    `official`: the caller already knows the game is OFF (for responses without a
    gameState, like right-rail)."""

    def __init__(self, cache_dir: Path, offline: bool = False, ttl: int = 1800):
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self.ttl = ttl

    def _path(self, url: str) -> Path:
        return self.dir / (hashlib.sha1(url.encode()).hexdigest()[:20] + ".json")

    def get(self, url: str, final_only_cache: bool = False, official: bool = False) -> dict:
        path = self._path(url)
        if path.exists():
            data = json.loads(path.read_text())
            fresh = time.time() - path.stat().st_mtime < self.ttl
            done = official or (final_only_cache and data.get("gameState") == OFFICIAL)
            if self.offline or fresh or done:
                return data
        if self.offline:
            raise SystemExit(f"--offline: not in cache: {url}")
        if requests is None:
            raise SystemExit("Install requests first:  pip install requests matplotlib")
        resp = requests.get(url, timeout=20, headers={"User-Agent": "stars-viz/1.0"})
        resp.raise_for_status()
        data = resp.json()
        path.write_text(json.dumps(data))
        time.sleep(0.25)  # be polite
        return data


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def txt(v, default=""):
    """NHL API wraps many strings as {"default": "..."}."""
    if isinstance(v, dict):
        return v.get("default", default)
    return default if v is None else v


def game_minute(period: int, clock: str) -> float:
    mm, ss = (clock or "00:00").split(":")
    return (period - 1) * 20 + int(mm) + int(ss) / 60


def season_label(season: int | str) -> str:
    s = str(season)
    return f"{s[:4]}-{s[6:]}"


def completed(games, types=(2, 3)):
    out = [g for g in games if g.get("gameType") in types and g.get("gameState") in FINAL_STATES]
    return sorted(out, key=lambda g: g.get("startTimeUTC", g.get("gameDate", "")))


def team_id_from_schedule(sched: dict, team: str) -> int:
    for g in sched.get("games", []):
        for side in ("homeTeam", "awayTeam"):
            if g[side].get("abbrev") == team:
                return g[side]["id"]
    raise SystemExit(f"Couldn't find team {team} in schedule")


def outcome_suffix(g: dict) -> str:
    last = (g.get("gameOutcome") or {}).get("lastPeriodType", "REG")
    return {"OT": "OT", "SO": "SO"}.get(last, "")


def pct(x, digits=0):
    return "-" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x * 100:.{digits}f}%"


def fmt_date(iso: str, long=False) -> str:
    d = dt.date.fromisoformat(iso[:10])
    return d.strftime("%a, %b %-d, %Y" if long else "%b %-d")


def swatch(fig, x, y, color, size=0.012):
    """A small colored identity chip placed next to ink text (text stays ink)."""
    fig.patches.append(FancyBboxPatch((x, y), size, size * 0.8, boxstyle="round,pad=0,rounding_size=0.002",
                                      transform=fig.transFigure, facecolor=color, edgecolor="none"))


# --------------------------------------------------------------------------
# Single game
# --------------------------------------------------------------------------
def parse_game(box: dict, pbp: dict, rail: dict, team: str) -> dict:
    home, away = box["homeTeam"], box["awayTeam"]
    us_home = home["abbrev"] == team
    us, them = (home, away) if us_home else (away, home)
    us_id, them_id = us["id"], them["id"]

    # player names: boxscore first, play-by-play rosterSpots as backup
    names, team_of = {}, {}
    for spot in pbp.get("rosterSpots", []) or []:
        first, last = txt(spot.get("firstName")), txt(spot.get("lastName"))
        names[spot["playerId"]] = f"{first[:1]}. {last}".strip()
        team_of[spot["playerId"]] = spot.get("teamId")
    pbg = box.get("playerByGameStats", {})
    for side in ("homeTeam", "awayTeam"):
        for grp in ("forwards", "defense", "goalies"):
            for p in pbg.get(side, {}).get(grp, []):
                names[p["playerId"]] = txt(p.get("name"), names.get(p["playerId"], "?"))

    shots, goals, faceoffs = [], [], {us_id: 0, them_id: 0}
    for p in pbp.get("plays", []):
        kind = p.get("typeDescKey")
        pd = p.get("periodDescriptor", {}) or {}
        if pd.get("periodType") == "SO":
            continue
        d = p.get("details", {}) or {}
        owner = d.get("eventOwnerTeamId")
        if kind == "faceoff" and owner in faceoffs:
            faceoffs[owner] += 1
            continue
        if kind not in ("goal", "shot-on-goal", "missed-shot", "blocked-shot"):
            continue
        # Blocked shots: the NHL has flipped eventOwnerTeamId between the blocking team (older
        # seasons) and the shooting team (2025-26), so trust the shooter's own team instead.
        shooter = owner
        if kind == "blocked-shot":
            shooter = team_of.get(d.get("shootingPlayerId")) or owner
        ours = shooter == us_id
        period = pd.get("number", 1)
        minute = game_minute(period, p.get("timeInPeriod"))
        x, y = d.get("xCoord"), d.get("yCoord")
        if x is not None and y is not None:
            side = p.get("homeTeamDefendingSide")
            shooter_home = shooter == home["id"]
            if side in ("left", "right"):
                home_attacks_right = side == "left"
                attacks_right = home_attacks_right if shooter_home else not home_attacks_right
            else:
                attacks_right = x >= 0
            # normalize: we always shoot to the right, they shoot to the left
            if ours != attacks_right:
                x, y = -x, -y
        sc = p.get("situationCode") or ""
        strength = "EV"
        five_on_five = sc == "1551"
        if len(sc) == 4 and sc.isdigit():
            a_g, a_s, h_s, h_g = (int(c) for c in sc)
            shooter_home = shooter == home["id"]
            own_s, opp_s = (h_s, a_s) if shooter_home else (a_s, h_s)
            opp_g = a_g if shooter_home else h_g
            own_g = h_g if shooter_home else a_g
            if own_s > opp_s:
                strength = "EA" if own_g == 0 else "PP"
            elif own_s < opp_s:
                strength = "SH"
            if kind == "goal" and opp_g == 0:
                strength = "EN"
        rec = dict(kind=kind, ours=ours, minute=minute, period=period, x=x, y=y,
                   five=five_on_five, strength=strength, clock=p.get("timeInPeriod"),
                   pid=d.get("scoringPlayerId") if kind == "goal" else d.get("shootingPlayerId"))
        shots.append(rec)
        if kind == "goal":
            scorer = d.get("scoringPlayerId")
            assists = [names.get(d.get(k), "?") for k in ("assist1PlayerId", "assist2PlayerId") if d.get(k)]
            goals.append(dict(rec, scorer=names.get(scorer, "?"), total=d.get("scoringPlayerTotal"),
                              assists=assists, period_type=pd.get("periodType", "REG"),
                              assist_ids=[d.get(k) for k in ("assist1PlayerId", "assist2PlayerId") if d.get(k)]))

    # team stats: right-rail when available, boxscore sums as fallback
    tgs = {s["category"]: s for s in (rail or {}).get("teamGameStats", [])}

    def rail_pair(cat):
        s = tgs.get(cat)
        if not s:
            return None
        return (s["homeValue"], s["awayValue"]) if us_home else (s["awayValue"], s["homeValue"])

    def box_sum(key):
        vals = []
        for side in (("homeTeam", "awayTeam") if us_home else ("awayTeam", "homeTeam")):
            grp = pbg.get(side, {})
            vals.append(sum(p.get(key, 0) or 0 for g in ("forwards", "defense") for p in grp.get(g, [])))
        return tuple(vals)

    stats = {}
    for cat, key in (("sog", "sog"), ("hits", "hits"), ("blockedShots", "blockedShots"),
                     ("pim", "pim"), ("giveaways", "giveaways"), ("takeaways", "takeaways")):
        stats[cat] = rail_pair(cat) or box_sum(key)
    stats["sog"] = (us.get("sog", stats["sog"][0]), them.get("sog", stats["sog"][1]))
    stats["faceoffs"] = (faceoffs[us_id], faceoffs[them_id])
    pp = rail_pair("powerPlay")
    stats["powerPlay"] = pp if pp else None
    att = lambda ours, five=False: sum(1 for s in shots if s["ours"] == ours and (s["five"] or not five))
    stats["attempts"] = (att(True), att(False))
    stats["attempts5v5"] = (att(True, True), att(False, True))

    # goalies + top skaters
    def goalies(side):
        out = []
        for g in pbg.get(side, {}).get("goalies", []):
            sa = g.get("shotsAgainst") or 0
            if not sa and not g.get("starter"):
                continue
            out.append(dict(name=txt(g.get("name")), saves=g.get("saves", 0), sa=sa, toi=g.get("toi", "")))
        return out

    us_side, them_side = ("homeTeam", "awayTeam") if us_home else ("awayTeam", "homeTeam")
    skaters = [p for g in ("forwards", "defense") for p in pbg.get(us_side, {}).get(g, [])]
    skaters.sort(key=lambda p: (p.get("points", 0), p.get("goals", 0), p.get("sog", 0),
                                p.get("toi", "0:00").zfill(5)), reverse=True)
    top = [dict(name=txt(p.get("name")), g=p.get("goals", 0), a=p.get("assists", 0),
                pts=p.get("points", 0), sog=p.get("sog", 0), toi=p.get("toi", ""),
                pm=p.get("plusMinus", 0)) for p in skaters[:4]]

    return dict(
        id=box["id"], date=box.get("gameDate"), venue=txt(box.get("venue")),
        game_type=box.get("gameType"), us=us, them=them, us_home=us_home,
        us_score=us.get("score", 0), them_score=them.get("score", 0),
        suffix={"OT": "OT", "SO": "SO"}.get((box.get("gameOutcome") or {}).get("lastPeriodType"), ""),
        shots=shots, goals=goals, stats=stats, top=top,
        us_goalies=goalies(us_side), them_goalies=goalies(them_side),
    )


def game_takeaway(g: dict) -> str:
    s = g["stats"]
    won = g["us_score"] > g["them_score"]
    us_sog, them_sog = s["sog"]
    a_us, a_them = s["attempts5v5"]
    share = a_us / (a_us + a_them) if a_us + a_them else 0.5
    pp_goals = sum(1 for x in g["goals"] if x["ours"] and x["strength"] == "PP")
    if won and them_sog - us_sog >= 6:
        return f"Won despite being outshot {us_sog}-{them_sog}."
    if not won and us_sog - them_sog >= 6:
        return f"Lost despite outshooting them {us_sog}-{them_sog}."
    if pp_goals >= 2:
        return f"The power play scored {pp_goals}."
    if share >= 0.56:
        return f"Controlled {share:.0%} of 5-on-5 shot attempts."
    if share <= 0.44:
        return f"Held to {share:.0%} of 5-on-5 shot attempts."
    return f"Shots {us_sog}-{them_sog}; 5-on-5 attempts split {a_us}-{a_them}."


def draw_rink(ax):
    ax.set_xlim(-101, 101)
    ax.set_ylim(-43.5, 43.5)
    ax.set_aspect("equal")
    ax.axis("off")
    lw = 1.1
    ax.add_patch(FancyBboxPatch((-100, -42.5), 200, 85, boxstyle="round,pad=0,rounding_size=28",
                                facecolor="white", edgecolor=RINK, lw=1.6, zorder=0))
    ax.plot([0, 0], [-42.5, 42.5], color=RINK, lw=2.2, zorder=1)
    for bx in (-25, 25):
        ax.plot([bx, bx], [-42.5, 42.5], color=RINK, lw=1.6, zorder=1)
    gy = 14.5 + np.sqrt(28 ** 2 - (89 - 72) ** 2)
    for gx in (-89, 89):
        ax.plot([gx, gx], [-gy, gy], color=RINK, lw=lw, zorder=1)
    ax.add_patch(Arc((89, 0), 12, 12, theta1=90, theta2=270, color=RINK, lw=lw, zorder=1))
    ax.add_patch(Arc((-89, 0), 12, 12, theta1=-90, theta2=90, color=RINK, lw=lw, zorder=1))
    ax.add_patch(Rectangle((89, -3), 3.5, 6, facecolor="none", edgecolor=RINK, lw=lw, zorder=1))
    ax.add_patch(Rectangle((-92.5, -3), 3.5, 6, facecolor="none", edgecolor=RINK, lw=lw, zorder=1))
    ax.add_patch(Circle((0, 0), 15, fill=False, color=RINK, lw=lw, zorder=1))
    for cx in (-69, 69):
        for cy in (-22, 22):
            ax.add_patch(Circle((cx, cy), 15, fill=False, color=RINK, lw=lw, zorder=1))
            ax.add_patch(Circle((cx, cy), 0.9, color=RINK, zorder=1))
    for cx in (-20, 20):
        for cy in (-22, 22):
            ax.add_patch(Circle((cx, cy), 0.9, color=RINK, zorder=1))


def render_game(g: dict, team_color: str, credit: str, out: Path) -> Path:
    us_ab, them_ab = g["us"]["abbrev"], g["them"]["abbrev"]
    fig = plt.figure(figsize=(12, 15.2))
    gs = GridSpec(5, 2, figure=fig, height_ratios=[1.75, 4.6, 2.9, 4.1, 0.25],
                  width_ratios=[1.35, 1], hspace=0.42, wspace=0.12,
                  left=0.06, right=0.95, top=0.975, bottom=0.03)

    # ---- header ----
    fig.text(0.06, 0.955, "FINAL" + (f" / {g['suffix']}" if g["suffix"] else "") +
             f"   ·   {fmt_date(g['date'], long=True)}   ·   {g['venue']}",
             fontsize=11, color=INK2, fontweight="bold")
    score = f"{us_ab} {g['us_score']}  –  {g['them_score']} {them_ab}"
    fig.text(0.075, 0.915, score, fontsize=38, color=INK, fontweight="bold", va="center")
    swatch(fig, 0.06, 0.910, team_color)
    fig.text(0.06, 0.878, game_takeaway(g), fontsize=15, color=INK2)

    # ---- shot map ----
    ax = fig.add_subplot(gs[1, :])
    draw_rink(ax)
    for ours, col in ((False, OPP), (True, team_color)):
        pts = [s for s in g["shots"] if s["ours"] == ours and s["x"] is not None and s["kind"] != "blocked-shot"]
        miss = [s for s in pts if s["kind"] == "missed-shot"]
        sog = [s for s in pts if s["kind"] == "shot-on-goal"]
        gl = [s for s in pts if s["kind"] == "goal"]
        ax.scatter([s["x"] for s in miss], [s["y"] for s in miss], s=46, facecolor="white",
                   edgecolor=col, linewidth=1.6, zorder=3)
        ax.scatter([s["x"] for s in sog], [s["y"] for s in sog], s=46, color=col,
                   edgecolor="white", linewidth=1.0, zorder=4)
        ax.scatter([s["x"] for s in gl], [s["y"] for s in gl], s=260, marker="*", color=col,
                   edgecolor=INK, linewidth=0.9, zorder=5)
    ax.text(97, -48.5, f"{us_ab} shooting  →", ha="right", fontsize=11, color=INK, fontweight="bold")
    ax.text(-97, -48.5, f"←  {them_ab} shooting", ha="left", fontsize=11, color=INK, fontweight="bold")
    handles = [
        Line2D([], [], marker="*", ls="", ms=15, color=MUTED, mec=INK, mew=0.9, label="Goal"),
        Line2D([], [], marker="o", ls="", ms=8, color=MUTED, mec="white", label="Shot on goal"),
        Line2D([], [], marker="o", ls="", ms=8, mfc="white", mec=MUTED, mew=1.6, label="Missed"),
        Line2D([], [], marker="s", ls="", ms=9, color=team_color, label=us_ab),
        Line2D([], [], marker="s", ls="", ms=9, color=OPP, label=them_ab),
    ]
    ax.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=5, frameon=False,
              fontsize=10.5, labelcolor=INK2, handletextpad=0.4, columnspacing=1.6)
    ax.set_title("Where the shots came from (blocked shots not shown)", loc="left", fontsize=13,
                 color=INK, fontweight="bold", pad=30)

    # ---- shot flow ----
    ax = fig.add_subplot(gs[2, :])
    end = max([60] + [s["minute"] for s in g["shots"]])
    end = 60 if end <= 60 else (65 if g["game_type"] != 3 else 20 * int(np.ceil(end / 20)))
    pos = ax.get_position()
    ax.set_position([pos.x0, pos.y0, pos.width - 0.06, pos.height])
    for ours, col, ab in ((True, team_color, us_ab), (False, OPP, them_ab)):
        mins = sorted(s["minute"] for s in g["shots"] if s["ours"] == ours)
        xs = [0] + mins + [end]
        ys = [0] + list(range(1, len(mins) + 1)) + [len(mins)]
        ax.step(xs, ys, where="post", color=col, lw=2.2, zorder=3, label=ab)
        ax.text(end + 0.6, ys[-1], f"{ab} {ys[-1]}", va="center", fontsize=11, color=INK, fontweight="bold")
        for k, gl in enumerate([x for x in g["goals"] if x["ours"] == ours]):
            yv = sum(1 for m in mins if m <= gl["minute"])
            ax.scatter([gl["minute"]], [yv], s=90, color=col, edgecolor=SURFACE, linewidth=2, zorder=5)
            last = gl["scorer"].split(". ")[-1]
            ax.annotate(last, (gl["minute"], yv), xytext=(0, 9 if ours else -14), textcoords="offset points",
                        ha="center", fontsize=8.5, color=INK2)
    for p in range(20, int(end), 20):
        ax.axvline(p, color=GRID, lw=1, zorder=0)
    ax.set_xlim(0, end)
    ax.set_ylim(bottom=0)
    ax.set_xticks([10, 30, 50] + ([62.5] if end == 65 else []))
    ax.set_xticklabels(["1st", "2nd", "3rd"] + (["OT"] if end == 65 else []))
    ax.tick_params(axis="x", length=0)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.legend(loc="upper left", frameon=False, fontsize=10, labelcolor=INK2)
    ax.set_title("Game flow: running total of shot attempts, goals marked", loc="left", fontsize=13,
                 color=INK, fontweight="bold", pad=10)

    # ---- stat comparison ----
    ax = fig.add_subplot(gs[3, 0])
    s = g["stats"]
    rows = [
        ("Shots on goal", *s["sog"]),
        ("Shot attempts", *s["attempts"]),
        ("5-on-5 shot attempts", *s["attempts5v5"]),
        ("Faceoffs won", *s["faceoffs"]),
        ("Hits", *s["hits"]),
        ("Blocked shots", *s["blockedShots"]),
        ("Takeaways", *s["takeaways"]),
        ("Giveaways", *s["giveaways"]),
    ]
    ax.set_xlim(0, 1)
    ax.set_ylim(len(rows) + (0.9 if s["powerPlay"] else 0), -0.8)
    ax.axis("off")
    ax.text(0, -0.75, us_ab, fontsize=11, fontweight="bold", color=INK)
    ax.text(1, -0.75, them_ab, fontsize=11, fontweight="bold", color=INK, ha="right")
    gap = 0.004
    for i, (label, a, b) in enumerate(rows):
        a, b = float(a or 0), float(b or 0)
        share = a / (a + b) if a + b else 0.5
        y = i + 0.35
        ax.barh(y, share - gap, left=0, height=0.26, color=team_color)
        ax.barh(y, 1 - share - gap, left=share + gap, height=0.26, color=OPP)
        ax.text(0.5, y - 0.3, label, ha="center", fontsize=10, color=INK2)
        ax.text(0, y - 0.3, f"{a:g}", fontsize=11, color=INK, fontweight="bold")
        ax.text(1, y - 0.3, f"{b:g}", fontsize=11, color=INK, fontweight="bold", ha="right")
        ax.plot([0.5, 0.5], [y - 0.13, y + 0.13], color=SURFACE, lw=1.5, zorder=4)
    if s["powerPlay"]:
        a, b = s["powerPlay"]
        y = len(rows) + 0.2
        ax.text(0.5, y, "Power play", ha="center", fontsize=10, color=INK2)
        ax.text(0, y, str(a), fontsize=11, color=INK, fontweight="bold")
        ax.text(1, y, str(b), fontsize=11, color=INK, fontweight="bold", ha="right")
    ax.set_title("Head to head", loc="left", fontsize=13, color=INK, fontweight="bold", pad=12)

    # ---- performers ----
    ax = fig.add_subplot(gs[3, 1])
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(10, 0)
    ax.set_title(f"{us_ab} standouts", loc="left", fontsize=13, color=INK, fontweight="bold", pad=12)
    y = 0.6
    for p in g["top"]:
        line = f"{p['g']}G {p['a']}A" if p["pts"] else f"{p['sog']} SOG"
        ax.text(0.04, y, p["name"], fontsize=12, color=INK, fontweight="bold")
        ax.text(0.04, y + 0.75, f"{line}  ·  {p['sog']} shots  ·  {p['toi']} TOI  ·  {p['pm']:+d}",
                fontsize=10, color=INK2)
        y += 1.75
    y += 0.35
    ax.text(0.04, y, "In net", fontsize=13, color=INK, fontweight="bold")
    y += 1.0
    for ab, gl_list in ((us_ab, g["us_goalies"]), (them_ab, g["them_goalies"])):
        for gk in gl_list:
            sv = gk["saves"] / gk["sa"] if gk["sa"] else 0
            ax.text(0.04, y, f"{ab}  {gk['name']}", fontsize=11, color=INK, fontweight="bold")
            ax.text(0.04, y + 0.7, f"{gk['saves']} saves on {gk['sa']}  ·  {sv:.3f}".replace("0.", "."),
                    fontsize=10, color=INK2)
            y += 1.55

    fig.text(0.06, 0.012, f"Data: NHL.com public API   {credit}".rstrip(), fontsize=9, color=MUTED)
    fig.text(0.95, 0.012, f"Game {g['id']}", fontsize=9, color=MUTED, ha="right")

    path = out / f"game_{g['id']}_{us_ab}_vs_{them_ab}.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def game_notes(g: dict) -> str:
    us_ab, them_ab = g["us"]["abbrev"], g["them"]["abbrev"]
    s = g["stats"]
    lines = [f"# {us_ab} {g['us_score']}-{g['them_score']} {them_ab}"
             f"{' (' + g['suffix'] + ')' if g['suffix'] else ''} · {fmt_date(g['date'], True)}", "",
             f"- Takeaway: {game_takeaway(g)}",
             f"- Shots on goal: {s['sog'][0]}-{s['sog'][1]}",
             f"- Shot attempts: {s['attempts'][0]}-{s['attempts'][1]} (5-on-5: {s['attempts5v5'][0]}-{s['attempts5v5'][1]})",
             f"- Faceoffs: {s['faceoffs'][0]}-{s['faceoffs'][1]}"]
    if s["powerPlay"]:
        lines.append(f"- Power play: {us_ab} {s['powerPlay'][0]}, {them_ab} {s['powerPlay'][1]}")
    lines += ["", "## Goals"]
    for x in g["goals"]:
        per = {1: "1st", 2: "2nd", 3: "3rd"}.get(x["period"], "OT")
        tag = {"EV": "", "PP": " (PP)", "SH": " (SH)", "EN": " (empty net)",
               "EA": " (6-on-5, goalie pulled)"}.get(x["strength"], "")
        ast = ", ".join(x["assists"]) or "unassisted"
        lines.append(f"- {per} {x['clock']} · {us_ab if x['ours'] else them_ab} · {x['scorer']}"
                     f" ({x['total']}){tag}, from {ast}")
    lines += ["", "## Goalies"]
    for ab, gl in ((us_ab, g["us_goalies"]), (them_ab, g["them_goalies"])):
        for gk in gl:
            lines.append(f"- {ab} {gk['name']}: {gk['saves']}/{gk['sa']}")
    lines += ["", f"## {us_ab} top skaters"]
    for p in g["top"]:
        lines.append(f"- {p['name']}: {p['g']}G {p['a']}A, {p['sog']} SOG, {p['toi']} TOI, {p['pm']:+d}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Season trend
# --------------------------------------------------------------------------
def load_trend(api: Api, team: str, season: str) -> tuple[list[dict], int, int]:
    sched = api.get(url_schedule(team, season))
    season_id = int(sched.get("currentSeason") if season == "now" else season)
    games = completed([g for g in sched.get("games", []) if g.get("season", season_id) == season_id], types=(2,))
    if season == "now" and not games and sched.get("previousSeason"):
        prev = str(sched["previousSeason"])
        print(f"No regular-season games yet in {season_label(season_id)}; showing {season_label(prev)}.")
        return load_trend(api, team, prev)
    if not games:
        raise SystemExit("No completed regular-season games found for that season.")
    team_id = team_id_from_schedule(sched, team)
    g0 = games[0]
    side = g0["homeTeam"] if g0["homeTeam"]["abbrev"] == team else g0["awayTeam"]
    team_name = txt(side.get("commonName"), team)

    reports = {}
    for rep in ("summary", "powerplay", "penaltykill", "percentages"):
        for row in api.get(url_team_report(rep, team_id, season_id)).get("data", []):
            reports.setdefault(row["gameId"], {}).update(row)

    rows = []
    for n, g in enumerate(games, 1):
        home = g["homeTeam"]["abbrev"] == team
        us, them = (g["homeTeam"], g["awayTeam"]) if home else (g["awayTeam"], g["homeTeam"])
        gf, ga = us.get("score", 0), them.get("score", 0)
        if gf > ga:
            res, pts = "W", 2
        elif outcome_suffix(g):
            res, pts = "OTL", 1
        else:
            res, pts = "L", 0
        r = reports.get(g["id"], {})
        rows.append(dict(
            n=n, id=g["id"], date=g["gameDate"], opp=them["abbrev"], home=home, gf=gf, ga=ga, res=res, pts=pts,
            suffix=outcome_suffix(g),
            sat=r.get("satPct", np.nan), pdo=r.get("shootingPlusSavePct5v5", np.nan),
            ppg=r.get("powerPlayGoalsFor", np.nan), ppo=r.get("ppOpportunities", np.nan),
            ppga=r.get("ppGoalsAgainst", np.nan), tsh=r.get("timesShorthanded", np.nan),
        ))
    return rows, season_id, team_name


def has(arr) -> bool:
    return bool(np.any(~np.isnan(np.asarray(arr, dtype=float))))


def too_early(ax, window):
    ax.text(0.5, 0.82, f"Rolling line starts after game {min(5, window)}", transform=ax.transAxes,
            ha="center", va="center", fontsize=10, color=MUTED)


def warmup(arr, window):
    """Blank the first few points so tiny samples (1-4 games) don't spike the line."""
    arr = np.array(arr, dtype=float)
    arr[: min(5, window) - 1] = np.nan
    return arr


def rolling(values, window, fn):
    out = []
    for i in range(len(values)):
        out.append(fn(values[max(0, i - window + 1): i + 1]))
    return warmup(out, window)


def ratio(num, den):
    num, den = np.array(num, float), np.array(den, float)
    ok = ~np.isnan(num) & ~np.isnan(den)
    d = den[ok].sum()
    return num[ok].sum() / d if d else np.nan


def trend_summary(rows, window, playoff_line):
    w = sum(r["res"] == "W" for r in rows)
    l_ = sum(r["res"] == "L" for r in rows)
    otl = sum(r["res"] == "OTL" for r in rows)
    pts = sum(r["pts"] for r in rows)
    gp = len(rows)
    last = rows[-window:]
    lw, ll, lo = (sum(r["res"] == k for r in last) for k in ("W", "L", "OTL"))
    gd = sum(r["gf"] - r["ga"] for r in rows)
    return dict(gp=gp, w=w, l=l_, otl=otl, pts=pts, ptspct=pts / (2 * gp), pace=round(pts / gp * 82),
                last=f"{lw}-{ll}-{lo}", gd=gd, line=playoff_line,
                pp=ratio([r["ppg"] for r in rows], [r["ppo"] for r in rows]),
                pk=1 - ratio([r["ppga"] for r in rows], [r["tsh"] for r in rows]),
                sat=np.nanmean([r["sat"] for r in rows]),
                sat_recent=np.nanmean([r["sat"] for r in last]),
                pp_recent=ratio([r["ppg"] for r in last], [r["ppo"] for r in last]),
                pk_recent=1 - ratio([r["ppga"] for r in last], [r["tsh"] for r in last]),
                pdo_recent=np.nanmean([r["pdo"] for r in last]))


def style_line_ax(ax, title, n):
    ax.set_title(title, loc="left", fontsize=12.5, color=INK, fontweight="bold", pad=10)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.spines["left"].set_visible(False)
    ax.tick_params(length=0)
    ax.set_xlim(0.5, max(n, 10) + 0.5)
    ax.set_xlabel("Game number", fontsize=9.5)


def end_label(ax, x, y, text):
    ax.annotate(text, (x, y), xytext=(6, 0), textcoords="offset points", va="center",
                fontsize=10, color=INK, fontweight="bold", annotation_clip=False)


def render_trend(rows, season_id, team, team_name, team_color, window, playoff_line, credit, out: Path) -> Path:
    S = trend_summary(rows, window, playoff_line)
    n = len(rows)
    x = np.array([r["n"] for r in rows])
    fig = plt.figure(figsize=(12, 15.2))
    gs = GridSpec(5, 2, figure=fig, height_ratios=[1.75, 2.9, 3.1, 3.1, 0.2], hspace=0.55, wspace=0.2,
                  left=0.06, right=0.93, top=0.975, bottom=0.03)

    # ---- header + stat tiles ----
    fig.text(0.06, 0.957, f"{team} · {season_label(season_id)} REGULAR SEASON · THROUGH {fmt_date(rows[-1]['date']).upper()}",
             fontsize=11, color=INK2, fontweight="bold")
    swatch(fig, 0.06, 0.918, team_color)
    fig.text(0.075, 0.922, f"How the {team_name} are trending", fontsize=30, color=INK, fontweight="bold", va="center")
    tiles = [
        ("Record", f"{S['w']}-{S['l']}-{S['otl']}"),
        ("Points", f"{S['pts']}  ({S['ptspct']:.3f})".replace("0.", ".")),
        ("82-game pace", f"{S['pace']} pts"),
        (f"Last {min(window, n)}", S["last"]),
        ("Goal diff", f"{S['gd']:+d}"),
    ]
    for i, (lab, val) in enumerate(tiles):
        xx = 0.06 + i * 0.178
        fig.text(xx, 0.885, lab.upper(), fontsize=9, color=MUTED, fontweight="bold")
        fig.text(xx, 0.862, val, fontsize=19, color=INK, fontweight="bold", va="center")

    # ---- goal differential by game ----
    ax = fig.add_subplot(gs[1, :])
    colors = {"W": team_color, "OTL": OPP_LIGHT, "L": OPP}
    gd = np.array([r["gf"] - r["ga"] for r in rows])
    # OT/SO losses are one-goal losses; draw them at -1 so they're visible
    ax.bar(x, gd, width=0.72, color=[colors[r["res"]] for r in rows], zorder=3)
    ax.axhline(0, color=INK2, lw=0.8, zorder=4)
    lim = max(3, int(np.abs(gd).max()) + 1)
    ax.set_ylim(-lim, lim)
    ax.set_yticks(range(-lim + (lim % 2), lim + 1, 2))
    style_line_ax(ax, "Every game: goal differential", n)
    ax.legend(handles=[Rectangle((0, 0), 1, 1, color=team_color, label="Win"),
                       Rectangle((0, 0), 1, 1, color=OPP_LIGHT, label="OT/SO loss"),
                       Rectangle((0, 0), 1, 1, color=OPP, label="Regulation loss")],
              loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=3, frameon=False, fontsize=10,
              labelcolor=INK2, handlelength=1.0)
    ax.set_title("Every game: goal differential", loc="left", fontsize=12.5, color=INK, fontweight="bold", pad=24)
    # month markers along the top
    prev_month, last_label_n = None, -99
    for r in rows:
        m = r["date"][:7]
        if m != prev_month:
            if prev_month and r["n"] - last_label_n < 4:
                prev_month = m
                continue
            last_label_n = r["n"]
            ax.text(r["n"] - 0.4, lim * 0.93, dt.date.fromisoformat(r["date"]).strftime("%b"),
                    fontsize=8.5, color=MUTED, va="top")
            if prev_month:
                ax.axvline(r["n"] - 0.5, color=GRID, lw=1, zorder=0)
            prev_month = m

    # ---- points pace ----
    ax = fig.add_subplot(gs[2, 0])
    cum = np.cumsum([r["pts"] for r in rows])
    ref = x * playoff_line / 82
    ax.plot(np.r_[0, x], np.r_[0, ref], color=MUTED, lw=1.2, zorder=2)
    ax.plot(np.r_[0, x], np.r_[0, cum], color=team_color, lw=2.2, zorder=3)
    ax.scatter([x[-1]], [cum[-1]], s=60, color=team_color, edgecolor=SURFACE, lw=2, zorder=4)
    end_label(ax, x[-1], cum[-1], f"{cum[-1]}")
    ax.annotate(f"{playoff_line}-pt pace", (x[-1], ref[-1]), xytext=(6, -12 if cum[-1] >= ref[-1] else 12),
                textcoords="offset points", fontsize=9, color=INK2, annotation_clip=False)
    diff = cum[-1] - ref[-1]
    style_line_ax(ax, f"Points vs. playoff pace ({diff:+.0f})", n)
    ax.set_xlim(0, max(n, 10) + 0.5)
    ax.set_ylim(bottom=0)
    ax.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))

    # ---- 5v5 shot share ----
    ax = fig.add_subplot(gs[2, 1])
    sat = np.array([r["sat"] for r in rows], float)
    roll = rolling(sat, window, np.nanmean) * 100
    ax.axhline(50, color=MUTED, lw=1.2, zorder=2)
    ax.scatter(x, sat * 100, s=14, color=OPP_LIGHT, zorder=2)
    ax.plot(x, roll, color=team_color, lw=2.2, zorder=3)
    if has(roll):
        end_label(ax, x[-1], roll[-1], f"{roll[-1]:.1f}%")
    else:
        too_early(ax, window)
    ax.set_ylim(min(30, np.nanmin(sat * 100) - 2) if has(sat) else 30,
                max(70, np.nanmax(sat * 100) + 2) if has(sat) else 70)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    style_line_ax(ax, f"5-on-5 shot share, {window}-game avg", n)
    ax.text(0.99, 0.02, "dots = single games · line at 50% = even", transform=ax.transAxes,
            ha="right", fontsize=8.5, color=MUTED)

    # ---- PP / PK ----
    for col, (key_n, key_d, title, invert) in enumerate((
            ("ppg", "ppo", "Power play %", False),
            ("ppga", "tsh", "Penalty kill %", True))):
        ax = fig.add_subplot(gs[3, col])
        num = [r[key_n] for r in rows]
        den = [r[key_d] for r in rows]
        idx = list(range(n))
        rr = np.array([ratio([num[j] for j in idx[max(0, i - window + 1): i + 1]],
                             [den[j] for j in idx[max(0, i - window + 1): i + 1]]) for i in idx])
        rr = warmup(rr, window)
        season_avg = ratio(num, den)
        if invert:
            rr, season_avg = 1 - rr, 1 - season_avg
        if not np.isnan(season_avg):
            ax.axhline(season_avg * 100, color=MUTED, lw=1.2, zorder=2)
            ax.annotate(f"season {season_avg * 100:.1f}%", (1, season_avg * 100), xytext=(2, 5),
                        textcoords="offset points", fontsize=9, color=INK2, zorder=5,
                        bbox=dict(boxstyle="round,pad=0.2", fc=SURFACE, ec="none", alpha=0.9))
        ax.plot(x, rr * 100, color=team_color, lw=2.2, zorder=3)
        if has(rr):
            end_label(ax, x[-1], rr[-1] * 100, f"{rr[-1] * 100:.1f}%")
            lo, hi = np.nanmin(rr * 100), np.nanmax(rr * 100)
            ax.set_ylim(max(0, lo - 5), min(100, hi + 5))
        else:
            too_early(ax, window)
            ax.set_ylim((0, 50) if not invert else (50, 100))
        ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
        style_line_ax(ax, f"{title}, {window}-game rolling", n)

    fig.text(0.06, 0.012, f"Data: NHL.com public API   {credit}".rstrip(), fontsize=9, color=MUTED)
    path = out / f"trend_{team}_{season_id}_through_{rows[-1]['date']}.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def trend_notes(rows, season_id, team, window, playoff_line) -> str:
    S = trend_summary(rows, window, playoff_line)
    lw = min(window, len(rows))
    best = max(rows, key=lambda r: r["gf"] - r["ga"])
    worst = min(rows, key=lambda r: r["gf"] - r["ga"])
    streak_k, streak_n = rows[-1]["res"], 0
    for r in reversed(rows):
        if r["res"] != streak_k:
            break
        streak_n += 1
    return "\n".join([
        f"# {team} trend · {season_label(season_id)} through {fmt_date(rows[-1]['date'], True)}", "",
        f"- Record {S['w']}-{S['l']}-{S['otl']}, {S['pts']} pts in {S['gp']} GP ({S['ptspct']:.3f}), pace {S['pace']}",
        f"- vs {playoff_line}-pt playoff pace: {S['pts'] - rows[-1]['n'] * playoff_line / 82:+.1f}",
        f"- Last {min(window, S['gp'])}: {S['last']} · current streak: {streak_n} {streak_k}",
        f"- Goal differential {S['gd']:+d}",
        f"- 5v5 shot share: season {pct(S['sat'], 1)}, last {lw} {pct(S['sat_recent'], 1)}",
        f"- Power play: season {pct(S['pp'], 1)}, last {lw} {pct(S['pp_recent'], 1)}",
        f"- Penalty kill: season {pct(S['pk'], 1)}, last {lw} {pct(S['pk_recent'], 1)}",
        f"- 5v5 PDO, last {lw}: {S['pdo_recent']:.3f} (1.000 is neutral; well above = running hot)",
        f"- Biggest win: {best['gf']}-{best['ga']} vs {best['opp']} ({fmt_date(best['date'])})",
        f"- Worst loss: {worst['gf']}-{worst['ga']} vs {worst['opp']} ({fmt_date(worst['date'])})",
    ]) + "\n"


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def latest_game_id(api: Api, team: str) -> int:
    sched = api.get(url_schedule(team))
    games = completed(sched.get("games", []))
    if not games and sched.get("previousSeason"):
        games = completed(api.get(url_schedule(team, str(sched["previousSeason"]))).get("games", []))
    if not games:
        raise SystemExit("No completed games found.")
    return games[-1]["id"]


def run_game(api, args, out):
    gid = args.id or latest_game_id(api, args.team)
    box = api.get(url_game(gid, "boxscore"), final_only_cache=True)
    pbp = api.get(url_game(gid, "play-by-play"), final_only_cache=True)
    try:
        rail = api.get(url_game(gid, "right-rail"), official=box.get("gameState") == OFFICIAL)
    except Exception:
        rail = {}
    if box.get("gameState") not in FINAL_STATES:
        print(f"Note: game {gid} isn't final yet (state {box.get('gameState')}); numbers are live.")
    g = parse_game(box, pbp, rail, args.team)
    png = render_game(g, args.color, args.credit, out)
    notes = out / (png.stem + "_notes.md")
    notes.write_text(game_notes(g))
    print(f"Game card: {png}\nNotes:     {notes}")


def run_trend(api, args, out):
    rows, season_id, team_name = load_trend(api, args.team, args.season)
    png = render_trend(rows, season_id, args.team, team_name, args.color, args.window, args.playoff_line, args.credit, out)
    notes = out / (png.stem + "_notes.md")
    notes.write_text(trend_notes(rows, season_id, args.team, args.window, args.playoff_line))
    print(f"Trend:     {png}\nNotes:     {notes}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["game", "trend", "both"])
    ap.add_argument("--team", default="DAL", help="team abbreviation (default DAL)")
    ap.add_argument("--id", type=int, help="game id, e.g. 2025020054 (default: latest completed)")
    ap.add_argument("--season", default="now", help="season id like 20252026 (default: current)")
    ap.add_argument("--window", type=int, default=10, help="rolling window in games (default 10)")
    ap.add_argument("--playoff-line", type=int, default=96, help="points pace reference (default 96)")
    ap.add_argument("--color", default=TEAM_COLOR, help="accent color for your team")
    ap.add_argument("--credit", default="", help='footer credit, e.g. "yourname.substack.com"')
    ap.add_argument("--out", default="output", help="output folder")
    ap.add_argument("--cache", default=".nhl_cache", help="cache folder")
    ap.add_argument("--offline", action="store_true", help="use cached data only")
    args = ap.parse_args(argv)
    args.team = args.team.upper()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    api = Api(Path(args.cache), offline=args.offline)
    if args.mode in ("game", "both"):
        run_game(api, args, out)
    if args.mode in ("trend", "both"):
        run_trend(api, args, out)


if __name__ == "__main__":
    sys.exit(main())
