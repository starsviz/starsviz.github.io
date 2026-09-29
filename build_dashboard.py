#!/usr/bin/env python3
"""
build_dashboard.py - builds the self-contained, interactive player-rankings
page from the NHL's public API.

    python build_dashboard.py                        # current season (last season until games start)
    python build_dashboard.py --season 20252026
    python build_dashboard.py --credit "yourname.substack.com"

Writes dashboard.html: one file with the data baked in. Open it in a browser,
or upload it anywhere that serves web pages. Re-run after each game to refresh.
The first run downloads every game (a minute or two); after that only new
games are fetched.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html as htmlmod
import json
import re
from pathlib import Path
from urllib.parse import quote

import stars_viz as sv

HERE = Path(__file__).resolve().parent
KIND = {"goal": 0, "shot-on-goal": 1, "missed-shot": 2, "blocked-shot": 3}


def toi_sec(s) -> int:
    try:
        mm, ss = (s or "0:00").split(":")
        return int(mm) * 60 + int(ss)
    except ValueError:
        return 0


def player_from_roster(p: dict) -> dict:
    first, last = sv.txt(p.get("firstName")), sv.txt(p.get("lastName"))
    return dict(
        name=f"{first} {last}".strip(), last=last, num=p.get("sweaterNumber"),
        pos=p.get("positionCode"), shoots=p.get("shootsCatches"), born=p.get("birthDate"),
        ht=p.get("heightInInches"), wt=p.get("weightInPounds"),
        home=", ".join(x for x in (sv.txt(p.get("birthCity")), sv.txt(p.get("birthStateProvince")),
                                   p.get("birthCountry")) if x),
    )


def fill_from_landing(api: sv.Api, pid: int, p: dict) -> None:
    """Players who left mid-season (trades, waivers, injuries) aren't on the
    end-of-season roster. Fill their full name and bio from their player page,
    but keep the sweater number and position they had in Dallas."""
    try:
        d = api.get(f"{sv.WEB}/player/{pid}/landing")
    except (Exception, SystemExit):  # SystemExit: --offline and not cached
        return
    info = player_from_roster(dict(d, positionCode=d.get("position")))
    info.update(num=p.get("num") or info["num"], pos=p.get("pos") or info["pos"])
    p.update({k: v for k, v in info.items() if v})


def build_data(api: sv.Api, team: str, season: str, color: str, credit: str, sample: bool = False) -> dict:
    rows, season_id, team_name = sv.load_trend(api, team, season)
    sched = api.get(sv.url_schedule(team, str(season_id)))
    by_id = {g["id"]: g for g in sched.get("games", [])}

    players: dict[int, dict] = {}
    try:
        roster = api.get(f"{sv.WEB}/roster/{team}/{season_id}")
        for grp in ("forwards", "defensemen", "goalies"):
            for p in roster.get(grp, []):
                players[p["id"]] = player_from_roster(p)
    except Exception as e:  # roster is nice-to-have; boxscores fill the gaps
        print(f"Roster unavailable ({e}); using boxscore names.")

    games = []
    for i, r in enumerate(rows, 1):
        gid = r["id"]
        print(f"\r  fetching game {i}/{len(rows)}", end="", flush=True)
        box = api.get(sv.url_game(gid, "boxscore"), final_only_cache=True)
        pbp = api.get(sv.url_game(gid, "play-by-play"), final_only_cache=True)
        try:
            rail = api.get(sv.url_game(gid, "right-rail"), official=box.get("gameState") == sv.OFFICIAL)
        except Exception:
            rail = {}
        g = sv.parse_game(box, pbp, rail, team)
        us_side, them_side = ("homeTeam", "awayTeam") if g["us_home"] else ("awayTeam", "homeTeam")
        pbg = box.get("playerByGameStats", {})

        skaters = []
        for grp in ("forwards", "defense"):
            for p in pbg.get(us_side, {}).get(grp, []):
                pid = p["playerId"]
                if pid not in players:
                    nm = sv.txt(p.get("name"))
                    players[pid] = dict(name=nm, last=nm.split(". ")[-1], num=p.get("sweaterNumber"),
                                        pos=p.get("position"))
                fo = p.get("faceoffWinningPctg")
                skaters.append([pid, p.get("goals", 0), p.get("assists", 0), p.get("plusMinus", 0),
                                p.get("pim", 0), p.get("sog", 0), p.get("hits", 0), p.get("blockedShots", 0),
                                toi_sec(p.get("toi")), p.get("powerPlayGoals", 0), p.get("giveaways", 0),
                                p.get("takeaways", 0), None if fo is None else round(fo, 4), p.get("shifts", 0)])
        goalies = []
        for p in pbg.get(us_side, {}).get("goalies", []):
            pid = p["playerId"]
            if pid not in players:
                nm = sv.txt(p.get("name"))
                players[pid] = dict(name=nm, last=nm.split(". ")[-1], num=p.get("sweaterNumber"), pos="G")
            if toi_sec(p.get("toi")) == 0:
                continue
            goalies.append([pid, p.get("shotsAgainst", 0), p.get("saves", 0), p.get("goalsAgainst", 0),
                            toi_sec(p.get("toi")), 1 if p.get("starter") else 0])
        if goalies:  # decision goes to the goalie with the most ice time
            top = max(goalies, key=lambda x: x[4])
            for gk in goalies:
                gk.append(r["res"] if gk is top else "")

        s = g["stats"]
        sched_g = by_id.get(gid, {})
        opp_obj = sched_g.get("homeTeam" if not g["us_home"] else "awayTeam", g["them"])
        games.append(dict(
            id=gid, n=r["n"], date=r["date"], opp=r["opp"],
            oppName=sv.txt(opp_obj.get("commonName"), r["opp"]),
            home=g["us_home"], gf=r["gf"], ga=r["ga"], res=r["res"], sfx=r["suffix"], venue=g["venue"],
            takeaway=sv.game_takeaway(g),
            st=dict(sog=list(s["sog"]), att=list(s["attempts"]), att5=list(s["attempts5v5"]),
                    fo=list(s["faceoffs"]), hits=list(s["hits"]), blk=list(s["blockedShots"]),
                    tk=list(s["takeaways"]), gv=list(s["giveaways"]), pim=list(s["pim"]),
                    pp=list(s["powerPlay"]) if s["powerPlay"] else None),
            shots=[[round(x["minute"], 2), 1 if x["ours"] else 0, KIND[x["kind"]], x["x"], x["y"],
                    (x["pid"] or 0) if x["ours"] else 0, x["strength"]] for x in g["shots"]],
            goals=[[round(x["minute"], 2), 1 if x["ours"] else 0, x["period"], x["clock"],
                    (x["pid"] or 0) if x["ours"] else 0, x["scorer"], x["assists"], x["strength"],
                    x["assist_ids"] if x["ours"] else []] for x in g["goals"]],
            sk=skaters, gk=goalies,
            oppGk=[[x["name"], x["sa"], x["saves"]] for x in g["them_goalies"]],
            adv=dict(sat=r["sat"], pdo=r["pdo"], ppg=r["ppg"], ppo=r["ppo"], ppga=r["ppga"], tsh=r["tsh"]),
        ))
    print()

    for pid, p in players.items():
        if "born" not in p:
            fill_from_landing(api, pid, p)
    for p in players.values():
        if p.get("born"):
            b = dt.date.fromisoformat(p["born"])
            today = dt.date.today()
            p["age"] = today.year - b.year - ((today.month, today.day) < (b.month, b.day))

    return dict(meta=dict(team=team, teamName=team_name, season=season_id, seasonLabel=sv.season_label(season_id),
                          built=dt.datetime.now().strftime("%b %-d, %Y %-I:%M %p"), color=color,
                          credit=credit, sample=sample),
                players={str(k): v for k, v in players.items()}, games=games)


def clean(o):
    """NaN isn't valid JSON; turn it into null."""
    if isinstance(o, float) and o != o:
        return None
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [clean(v) for v in o]
    return o


SHARE_IMAGE = "og-image.png"      # made by tools/make_share_image.py after the build
TOUCH_ICON = "apple-touch-icon.png"
STAR = "32,9 38.2,25.5 55.8,25.8 41.9,36.5 46.8,53.4 32,43.5 17.2,53.4 22.1,36.5 8.2,25.8 25.8,25.5"


def favicon_svg(color: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" '
            f'fill="{color}"/><polygon points="{STAR}" fill="#fff"/></svg>')


def write_touch_icon(path: Path, color: str) -> None:
    """180x180 home-screen icon (iPhone/iPad), same design as the favicon."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch, Polygon

    fig = plt.figure(figsize=(1.8, 1.8), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 64)
    ax.set_ylim(64, 0)
    ax.axis("off")
    ax.add_patch(FancyBboxPatch((0, 0), 64, 64, boxstyle="square,pad=0", facecolor=color, edgecolor="none"))
    pts = [tuple(map(float, p.split(","))) for p in STAR.split()]
    ax.add_patch(Polygon([(x, y + 1) for x, y in pts], closed=True, facecolor="white", edgecolor="none"))
    fig.savefig(path, dpi=100)
    plt.close(fig)


def latest_line(data: dict) -> str:
    if not data["games"]:
        return ""
    g, m = data["games"][-1], data["meta"]
    home, away = (m["team"], g["opp"]) if g["home"] else (g["opp"], m["team"])
    hs, as_ = (g["gf"], g["ga"]) if g["home"] else (g["ga"], g["gf"])
    date = dt.date.fromisoformat(g["date"]).strftime("%b %-d, %Y")
    return f" Latest: {away} {as_}, {home} {hs}{' (' + g['sfx'] + ')' if g['sfx'] else ''} on {date}."


def share_tags(title: str, desc: str, site_url: str, data: dict) -> str:
    e = lambda s: htmlmod.escape(s, quote=True)
    tags = [f'<meta property="og:type" content="website">',
            f'<meta property="og:title" content="{e(title)}">',
            f'<meta property="og:description" content="{e(desc)}">',
            f'<meta name="twitter:title" content="{e(title)}">',
            f'<meta name="twitter:description" content="{e(desc)}">']
    if data["meta"].get("credit"):
        tags.append(f'<meta property="og:site_name" content="{e(data["meta"]["credit"])}">')
    if site_url:
        base = site_url.rstrip("/") + "/"
        # a new image URL after every game, so Substack and X don't show yesterday's cached preview
        version = data["games"][-1]["id"] if data["games"] else 0
        img = f"{base}{SHARE_IMAGE}?v={version}"
        tags += [f'<link rel="canonical" href="{e(base)}">',
                 f'<meta property="og:url" content="{e(base)}">',
                 f'<meta property="og:image" content="{e(img)}">',
                 '<meta property="og:image:width" content="1200">',
                 '<meta property="og:image:height" content="630">',
                 f'<meta property="og:image:alt" content="{e(data["meta"]["teamName"])} player rankings for the latest game">',
                 '<meta name="twitter:card" content="summary_large_image">',
                 f'<meta name="twitter:image" content="{e(img)}">',
                 f'<link rel="apple-touch-icon" href="{TOUCH_ICON}">']
    else:
        tags.append('<meta name="twitter:card" content="summary">')
    return "\n".join(tags)


def render(data: dict, template: Path, out: Path, fragment: bool = False, site_url: str = "") -> Path:
    blob = json.dumps(clean(data), separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    html = template.read_text(encoding="utf-8")
    assert "__DASHBOARD_DATA__" in html, "template is missing its data placeholder"
    m = data["meta"]
    title = f"{m['teamName']} Player Rankings {m['seasonLabel']}"
    desc = f"Every {m['teamName']} skater, scored and ranked after every game.{latest_line(data)}"
    html = (html.replace("__DASHBOARD_TITLE__", htmlmod.escape(title))
                .replace("__DASHBOARD_DESCRIPTION__", htmlmod.escape(desc, quote=True))
                .replace("__DASHBOARD_FAVICON__", quote(favicon_svg(m["color"])))
                .replace("<!--share-->", share_tags(title, desc, site_url, data))
                .replace("__DASHBOARD_DATA__", blob))
    if fragment:  # no html/head/body wrapper: title, fonts and styles, then the page body
        head = re.search(r"<head>(.*?)</head>", html, re.S).group(1)
        body = re.search(r"<body>(.*?)</body>", html, re.S).group(1)
        html = head[head.index("<title>"):] + body
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    if site_url and not fragment:
        write_touch_icon(out.parent / TOUCH_ICON, m["color"])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--team", default="DAL")
    ap.add_argument("--season", default="now", help="e.g. 20252026 (default: current)")
    ap.add_argument("--color", default=sv.TEAM_COLOR, help="accent color")
    ap.add_argument("--credit", default="", help='shown in the footer, e.g. "yourname.substack.com"')
    ap.add_argument("--out", default="dashboard.html")
    ap.add_argument("--site-url", default="", help="where the page is published, e.g. https://you.github.io/stars/ "
                                                   "(turns on the share preview image for Substack and X)")
    ap.add_argument("--template", default=str(HERE / "dashboard_template.html"))
    ap.add_argument("--cache", default=".nhl_cache")
    ap.add_argument("--offline", action="store_true", help="use cached data only")
    ap.add_argument("--sample", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--fragment", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    api = sv.Api(Path(args.cache), offline=args.offline)
    data = build_data(api, args.team.upper(), args.season, args.color, args.credit, sample=args.sample)
    out = render(data, Path(args.template), Path(args.out), fragment=args.fragment, site_url=args.site_url)
    kb = out.stat().st_size / 1024
    print(f"Dashboard: {out}  ({len(data['games'])} games, {len(data['players'])} players, {kb:.0f} KB)")


if __name__ == "__main__":
    main()
