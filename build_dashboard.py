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
import base64
import datetime as dt
import html as htmlmod
import json
import re
import shutil
from pathlib import Path

import stars_viz as sv

HERE = Path(__file__).resolve().parent
KIND = {"goal": 0, "shot-on-goal": 1, "missed-shot": 2, "blocked-shot": 3}


def toi_sec(s) -> int:
    try:
        mm, ss = (s or "0:00").split(":")
        return int(mm) * 60 + int(ss)
    except ValueError:
        return 0


def saves_shots(v) -> tuple[int, int]:
    """Boxscore goalie splits come as "saves/shots", e.g. "19/23"."""
    try:
        sv_, sa = str(v or "0/0").split("/")
        return int(sv_), int(sa)
    except ValueError:
        return 0, 0


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


def slug(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")


def game_slug(g: dict, team_name: str) -> str:
    """The address of one game's page: "2026-10-20-stars-vs-bruins". Dated, so it sorts and can't collide."""
    return slug(f"{g['date']}-{team_name}-{'vs' if g['home'] else 'at'}-{g['oppName']}")


def team_full(side: dict, fallback: str = "") -> str:
    """"Dallas Stars": the API keeps the city and the nickname in separate fields, and anyone
    searching types both. Falls back to the nickname alone when there's no place name."""
    common = sv.txt(side.get("commonName"), fallback)
    place = sv.txt(side.get("placeName"))
    return f"{place} {common}".strip() if place and not common.startswith(place) else common


def full_team_name(sched: dict, team: str, fallback: str) -> str:
    for g in sched.get("games", []):
        for side in ("homeTeam", "awayTeam"):
            if g.get(side, {}).get("abbrev") == team:
                return team_full(g[side], fallback)
    return fallback


def build_data(api: sv.Api, team: str, season: str, color: str, credit: str, sample: bool = False) -> dict:
    rows, season_id, team_name = sv.load_trend(api, team, season)
    sched = api.get(sv.url_schedule(team, str(season_id)))
    by_id = {g["id"]: g for g in sched.get("games", [])}
    on_ice, season_on_ice = sv.load_skater_reports(api, sv.team_id_from_schedule(sched, team), season_id)

    players: dict[int, dict] = {}
    try:
        roster = api.get(f"{sv.WEB}/roster/{team}/{season_id}")
        for grp in ("forwards", "defensemen", "goalies"):
            for p in roster.get(grp, []):
                players[p["id"]] = player_from_roster(p)
    except Exception as e:  # roster is nice-to-have; boxscores fill the gaps
        print(f"Roster unavailable ({e}); using boxscore names.")

    games, held = [], set()
    for i, r in enumerate(rows, 1):
        gid = r["id"]
        print(f"\r  fetching game {i}/{len(rows)}", end="", flush=True)
        box = api.get(sv.url_game(gid, "boxscore"), final_only_cache=True)
        # A finished game goes up only once the NHL has made it official and posted the on-ice numbers (the post-game
        # email waits for the same), or STATS_WAIT_HOURS after puck drop if it never does. Until then it shows in the
        # schedule strip as "Stats soon".
        missing = sv.stats_missing(box, on_ice, team)
        if missing and sv.hours_since(by_id.get(gid, {}).get("startTimeUTC")) < sv.STATS_WAIT_HOURS:
            print(f"\n  holding back game {gid} until its stats are final: {missing}")
            held.add(gid)
            continue
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
                pen, fo_wl, oi = g["pen"].get(pid, (0, 0)), g["fo"].get(pid, (0, 0)), on_ice.get((gid, pid), {})
                skaters.append([pid, p.get("goals", 0), p.get("assists", 0), p.get("plusMinus", 0),
                                p.get("pim", 0), p.get("sog", 0), p.get("hits", 0), p.get("blockedShots", 0),
                                toi_sec(p.get("toi")), p.get("powerPlayGoals", 0), p.get("giveaways", 0),
                                p.get("takeaways", 0), None if fo is None else round(fo, 4), p.get("shifts", 0),
                                pen[0], pen[1], fo_wl[0], fo_wl[1], oi.get("satFor"), oi.get("satAgainst"),
                                oi.get("evTimeOnIce"), oi.get("ppTimeOnIce"), oi.get("shTimeOnIce")])
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
        for gk in goalies:  # saves/shots at even strength, then with the opponent on the power play
            p = next(x for x in pbg[us_side]["goalies"] if x["playerId"] == gk[0])
            gk += [*saves_shots(p.get("evenStrengthShotsAgainst")), *saves_shots(p.get("powerPlayShotsAgainst"))]

        s = g["stats"]
        sched_g = by_id.get(gid, {})
        opp_obj = sched_g.get("homeTeam" if not g["us_home"] else "awayTeam", g["them"])
        games.append(dict(
            id=gid, n=r["n"], date=r["date"], start=sched_g.get("startTimeUTC"), opp=r["opp"],
            oppName=sv.txt(opp_obj.get("commonName"), r["opp"]),
            oppFull=team_full(opp_obj, r["opp"]),  # "New Jersey Devils", for titles and search engines
            home=g["us_home"], gf=r["gf"], ga=r["ga"], res=r["res"], sfx=r["suffix"], venue=g["venue"],
            official=box.get("gameState") == sv.OFFICIAL,  # the NHL has made the stats official (the post-game email waits for this)
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
            tm=sv.team_score_inputs(g),
        ))
    print()

    for g in games:
        g["slug"] = game_slug(g, team_name)

    for pid, p in players.items():
        if "born" not in p:
            fill_from_landing(api, pid, p)
    for pid, p in players.items():  # season on-ice context for the player card
        r = season_on_ice.get(pid)
        if r:
            p["oi"] = dict(rel=r.get("satRelative"), zs=r.get("zoneStartPct5v5"),
                           sh=r.get("shootingPct5v5"), sv=r.get("skaterSavePct5v5"))
    for p in players.values():
        if p.get("born"):
            b = dt.date.fromisoformat(p["born"])
            today = dt.date.today()
            p["age"] = today.year - b.year - ((today.month, today.day) < (b.month, b.day))

    return dict(meta=dict(team=team, teamName=team_name, teamFull=full_team_name(sched, team, team_name),
                          season=season_id, seasonLabel=sv.season_label(season_id),
                          built=dt.datetime.now().strftime("%b %-d, %Y %-I:%M %p"),
                          builtIso=dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
                          color=color, credit=credit, sample=sample),
                players={str(k): v for k, v in players.items()}, games=games,
                upcoming=upcoming_games(sched, team, {g["id"] for g in games}, held))


def upcoming_games(sched: dict, team: str, done: set, held: set = frozenset()) -> list[dict]:
    """The rest of the regular season, for the game picker: every game not played yet (one in progress included),
    and any finished game held back until its stats are final (pending)."""
    out = []
    for g in sched.get("games", []):
        if g.get("gameType") != 2 or g["id"] in done or (g.get("gameState") in sv.FINAL_STATES and g["id"] not in held):
            continue
        home = g["homeTeam"]["abbrev"] == team
        opp = g["awayTeam"] if home else g["homeTeam"]
        tv = [b["network"] for b in g.get("tvBroadcasts", []) if b.get("countryCode") == "US" and b.get("network")]
        out.append(dict(id=g["id"], date=g.get("gameDate"), start=g.get("startTimeUTC"), opp=opp.get("abbrev"),
                        oppName=sv.txt(opp.get("commonName"), opp.get("abbrev")), home=home,
                        live=g.get("gameState") in ("LIVE", "CRIT"), tbd=g.get("gameScheduleState") != "OK", tv=tv,
                        pending=g["id"] in held))
    return sorted(out, key=lambda x: (x["date"] or "", x["id"]))


def clean(o):
    """NaN isn't valid JSON; turn it into null."""
    if isinstance(o, float) and o != o:
        return None
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [clean(v) for v in o]
    return o


BRAND_URL = "https://sticklanguage.substack.com"   # the owner's Substack: the header logo and Subscribe button go here
SUPPORT_URL = "https://buymeacoffee.com/essjayjay"  # the owner's Buy Me a Coffee page ("Buy me a beer"): end-of-page note, feedback thanks
SITE_NAME = "Stick Language Stats"  # the page's own name: the title's tail, og:site_name, the structured data
SHARE_IMAGE = "og-image.png"      # made by tools/make_share_image.py after the build
TOUCH_ICON = "apple-touch-icon.png"


def asset_uri(name: str) -> str:
    """A brand image baked into the page. tools/make_logo.py makes the files in assets/ from the Stick Language
    logo: logo-light.png / logo-dark.png for the header and share images, favicon.png for the browser tab."""
    return "data:image/png;base64," + base64.b64encode((HERE / "assets" / name).read_bytes()).decode()


def latest_line(data: dict) -> str:
    if not data["games"]:
        return ""
    g, m = data["games"][-1], data["meta"]
    home, away = (m["team"], g["opp"]) if g["home"] else (g["opp"], m["team"])
    hs, as_ = (g["gf"], g["ga"]) if g["home"] else (g["ga"], g["gf"])
    date = dt.date.fromisoformat(g["date"]).strftime("%b %-d, %Y")
    return f" Latest: {away} {as_}, {home} {hs}{' (' + g['sfx'] + ')' if g['sfx'] else ''} on {date}."


def page_url(site_url: str, g: dict | None) -> str:
    """Where a page lives: the site itself, or one game's page under /game/."""
    base = site_url.rstrip("/") + "/" if site_url else ""
    return base if g is None else f"{base}game/{g['slug']}/"


def scoreline(data: dict, g: dict) -> tuple[str, str]:
    """"Boston Bruins 2, Dallas Stars 3 (OT)", and the date it was played, the way a reader writes it."""
    m, them = data["meta"], g["oppFull"]
    home, away = (m["teamFull"], them) if g["home"] else (them, m["teamFull"])
    hs, as_ = (g["gf"], g["ga"]) if g["home"] else (g["ga"], g["gf"])
    line = f"{away} {as_}, {home} {hs}" + (f" ({g['sfx']})" if g["sfx"] else "")
    return line, dt.date.fromisoformat(g["date"]).strftime("%b %-d, %Y")


def page_head(data: dict, g: dict | None) -> tuple[str, str, str]:
    """The title, the description and the heading, for the site's page (g is None) or for one game's.

    A search result shows the first two, so they carry the city and the nickname both ("Dallas Stars", not
    "Stars"), and a game's carries the matchup, the date and the score. Every game page has to say something
    different here, or Google reads 80-odd near-identical pages as one and keeps whichever it likes."""
    m = data["meta"]
    if g is None:
        return (f"{m['teamFull']} Player Rankings {m['seasonLabel']} | {SITE_NAME}",
                f"{m['teamFull']} player ratings for {m['seasonLabel']}: a score for every skater from goals, "
                f"shots, Corsi and ice time.{latest_line(data)}",
                f"{m['teamFull']} player ratings, game by game")
    line, date = scoreline(data, g)
    return (f"{m['teamFull']} {'vs' if g['home'] else 'at'} {g['oppName']}, {date}: player ratings",
            f"{line} on {date}. Every {m['teamFull']} skater scored and ranked: goals, shots, Corsi and ice time.",
            f"{m['teamFull']} player ratings, {line}, {date}")


def share_tags(title: str, desc: str, site_url: str, data: dict, g: dict | None = None) -> str:
    e = lambda s: htmlmod.escape(s, quote=True)
    # max-image-preview:large asks Google to show the share image full width in search results
    tags = ['<meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1">',
            f'<meta property="og:type" content="website">',
            f'<meta property="og:site_name" content="{e(SITE_NAME)}">',
            '<meta property="og:locale" content="en_US">',
            f'<meta property="og:title" content="{e(title)}">',
            f'<meta property="og:description" content="{e(desc)}">',
            f'<meta name="twitter:title" content="{e(title)}">',
            f'<meta name="twitter:description" content="{e(desc)}">']
    if site_url:
        base, here = site_url.rstrip("/") + "/", page_url(site_url, g)
        # a new image URL after every game, so Substack and X don't show yesterday's cached preview
        version = data["games"][-1]["id"] if data["games"] else 0
        img = f"{base}{SHARE_IMAGE}?v={version}"
        tags += [f'<link rel="canonical" href="{e(here)}">',
                 f'<meta property="og:url" content="{e(here)}">',
                 f'<meta property="og:image" content="{e(img)}">',
                 '<meta property="og:image:width" content="1200">',
                 '<meta property="og:image:height" content="630">',
                 '<meta property="og:image:type" content="image/png">',
                 f'<meta property="og:image:alt" content="{e(data["meta"]["teamFull"])} player rankings for the latest game">',
                 '<meta name="twitter:card" content="summary_large_image">',
                 f'<meta name="twitter:image" content="{e(img)}">',
                 f'<link rel="apple-touch-icon" href="{e(base + TOUCH_ICON)}">']  # absolute: game pages sit a folder down
    else:
        tags.append('<meta name="twitter:card" content="summary">')
    return "\n".join(tags)


# The pages a search engine should tie the team to, so "Dallas Stars" on this site means the NHL club.
# Only used for the team the page is about; other teams simply get no sameAs.
TEAM_LINKS = {"DAL": ["https://www.nhl.com/stars", "https://en.wikipedia.org/wiki/Dallas_Stars"]}


def json_ld(data: dict, site_url: str, title: str, desc: str, g: dict | None = None) -> str:
    """Structured data (schema.org, in the head): who publishes the page, what team it's about and which game
    it's showing. Search engines read it to place the site in their index of things rather than words.
    A game's page also gets a breadcrumb back to the site, which is what Google shows above a result."""
    if not site_url or not data["games"]:
        return ""
    m, base = data["meta"], site_url.rstrip("/") + "/"
    here = page_url(site_url, g)
    org = {"@type": "Organization", "@id": f"{base}#publisher", "name": "Stick Language",
           "url": m.get("brandUrl") or base,
           "logo": {"@type": "ImageObject", "url": base + TOUCH_ICON, "width": 180, "height": 180}}
    site = {"@type": "WebSite", "@id": f"{base}#website", "url": base, "name": SITE_NAME,
            "inLanguage": "en-US", "publisher": {"@id": f"{base}#publisher"}}
    team = {"@type": "SportsTeam", "@id": f"{base}#team", "name": m["teamFull"], "sport": "Ice hockey",
            "memberOf": {"@type": "SportsOrganization", "name": "National Hockey League", "alternateName": "NHL"}}
    if TEAM_LINKS.get(m["team"]):
        team["sameAs"] = TEAM_LINKS[m["team"]]
    shown = g or data["games"][-1]
    home, away = ((m["teamFull"], shown["oppFull"]) if shown["home"] else (shown["oppFull"], m["teamFull"]))
    sports_team = lambda n: {"@type": "SportsTeam", "name": n}
    game = {"@type": "SportsEvent", "@id": f"{page_url(site_url, shown)}#event",
            "name": f"{away} at {home}, {dt.date.fromisoformat(shown['date']).strftime('%B %-d, %Y')}",
            "startDate": shown.get("start") or shown["date"], "sport": "Ice hockey",
            "location": {"@type": "Place", "name": shown["venue"]},
            "homeTeam": sports_team(home), "awayTeam": sports_team(away),
            "organizer": {"@type": "SportsOrganization", "name": "National Hockey League"}}
    page = {"@type": "WebPage", "@id": here, "url": here, "name": title, "description": desc,
            "isPartOf": {"@id": f"{base}#website"}, "inLanguage": "en-US",
            "about": [{"@id": f"{base}#team"}, {"@id": game["@id"]}],
            "primaryImageOfPage": {"@type": "ImageObject", "url": base + SHARE_IMAGE},
            "dateModified": m["builtIso"], "publisher": {"@id": f"{base}#publisher"}}
    graph = [org, site, page, team, game]
    if g is not None:
        crumb = lambda n, name, url: {"@type": "ListItem", "position": n, "name": name, "item": url}
        line, date = scoreline(data, g)
        page["breadcrumb"] = {"@id": f"{here}#crumb"}
        graph.append({"@type": "BreadcrumbList", "@id": f"{here}#crumb", "itemListElement": [
            crumb(1, f"{m['teamFull']} player rankings {m['seasonLabel']}", base),
            crumb(2, f"{'vs' if g['home'] else 'at'} the {g['oppName']}, {date}", here)]})
    blob = json.dumps({"@context": "https://schema.org", "@graph": graph},
                      separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    return f'<script type="application/ld+json">{blob}</script>'


def static_summary(data: dict, g: dict | None = None, site_url: str = "") -> str:
    """One game in plain HTML, baked into the page: the latest, or the game whose page this is.

    The page draws itself from the baked JSON, so anything that doesn't run JavaScript - some search
    engines, most AI crawlers, a reader with scripts off - would otherwise find an empty page. This fills
    <section id="games"> with the result, every skater's boxscore line, the goalies, and every game played
    (each one a link to its own page, so a crawler can walk the whole season). The page's own code replaces
    it on load, before the first paint, so nobody with JavaScript ever sees it."""
    m, games, P = data["meta"], data["games"], data["players"]
    if not games:
        return ""
    e = lambda x: htmlmod.escape(str(x))
    own_page = g is not None   # a game's own page gets the way back; the site's own page is already there
    g = g or games[-1]
    line, date = scoreline(data, g)
    nm = lambda pid: P.get(str(pid), {}).get("name") or f"#{pid}"
    pos = lambda pid: P.get(str(pid), {}).get("pos") or ""
    mmss = lambda sec: f"{sec // 60}:{sec % 60:02d}"
    plus = lambda n: f"{n:+d}" if n else "0"
    rows = sorted(g["sk"], key=lambda r: (-(r[1] + r[2]), -r[8]))
    body = "".join(f'<tr><td class="nm l">{e(nm(r[0]))}</td><td class="l">{e(pos(r[0]))}</td><td>{r[1]}</td>'
                   f"<td>{r[2]}</td><td>{r[1] + r[2]}</td><td>{r[5]}</td><td>{r[6]}</td><td>{r[7]}</td>"
                   f"<td>{r[11]}</td><td>{r[10]}</td><td>{plus(r[3])}</td><td>{mmss(r[8])}</td></tr>"
                   for r in rows)
    gk = "".join(f"<li>{e(nm(r[0]))}: {r[2]} saves on {r[1]} shots, {r[3]} against in {mmss(r[4])}</li>"
                 for r in g["gk"])
    w = sum(1 for x in games if x["res"] == "W")
    otl = sum(1 for x in games if x["res"] == "OTL")
    label = lambda x: (f"{dt.date.fromisoformat(x['date']).strftime('%b %-d')}: "
                       f"{'vs' if x['home'] else 'at'} the {e(x['oppFull'])}, "
                       f"{'won' if x['res'] == 'W' else 'lost'} {x['gf']}-{x['ga']}"
                       f"{' (' + e(x['sfx']) + ')' if x['sfx'] else ''}")
    played = "".join(f'<li><a href="{e(page_url(site_url, x))}">{label(x)}</a></li>' if site_url
                     else f"<li>{label(x)}</li>" for x in reversed(games))
    crumb = (f'<nav class="crumb" aria-label="Breadcrumb"><a href="{e(page_url(site_url, None))}">'
             f"All {e(m['seasonLabel'])} games</a></nav>" if own_page and site_url else "")
    return f"""{crumb}<div class="card">
  <p class="chapter-label">{'The game' if own_page else 'Latest game'}</p>
  <h2>{e(line)} &middot; {e(date)}</h2>
  <p class="cap">Every {e(m['teamFull'])} skater's night at {e(g['venue'])}, from the NHL's public play-by-play.
  The full page needs JavaScript: it scores and ranks these players, charts who produced and who drove the
  play, maps every shot of the game and keeps every other game of {e(m['seasonLabel'])} a tap away.</p>
  <div class="tbl-wrap"><table>
    <caption class="vh">{e(m['teamFull'])} player stats, {e(line)}, {e(date)}</caption>
    <thead><tr><th class="nm l">Player</th><th class="l">Pos</th><th>G</th><th>A</th><th>P</th><th>SOG</th>
    <th>HIT</th><th>BLK</th><th>TK</th><th>GV</th><th>+/-</th><th>TOI</th></tr></thead>
    <tbody>{body}</tbody></table></div>
  {f'<p class="cap">In goal:</p><ul class="simple">{gk}</ul>' if gk else ''}
</div>
<div class="card">
  <p class="chapter-label">The season so far</p>
  <h2>{e(m['teamFull'])} are {w}-{len(games) - w - otl}-{otl} through {len(games)} games</h2>
  <ul class="simple">{played}</ul>
</div>"""


def verify_tag(code: str) -> str:
    """The tag Google Search Console asks for to prove the site is yours (see README)."""
    code = (code or "").strip()
    return f'<meta name="google-site-verification" content="{htmlmod.escape(code, quote=True)}">\n' if code else ""


def seo_files(out: Path, site_url: str, data: dict) -> None:
    """robots.txt and sitemap.xml beside the page: the two files a crawler looks for before anything else.
    The sitemap lists the site's own page and every game page. A game's lastmod is the day it was played -
    its numbers settle within a day, and saying "everything changed again today" every night only wastes
    the crawler's time on 80-odd pages that didn't."""
    base = site_url.rstrip("/") + "/"
    (out.parent / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {base}sitemap.xml\n",
                                           encoding="utf-8")
    urls = [(base, data["meta"]["builtIso"], "daily", "1.0")]
    urls += [(page_url(site_url, g), g["date"], "monthly", "0.7") for g in reversed(data["games"])]
    body = "".join(f"  <url>\n    <loc>{loc}</loc>\n    <lastmod>{mod}</lastmod>\n"
                   f"    <changefreq>{freq}</changefreq>\n    <priority>{pri}</priority>\n  </url>\n"
                   for loc, mod, freq, pri in urls)
    (out.parent / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{body}</urlset>\n", encoding="utf-8")


def one_page(base_html: str, data: dict, site_url: str, verify: str, g: dict | None) -> str:
    """One finished page from the template with the season's data already in it: the site's own page
    (g is None) or one game's. Everything that differs between the two is in here."""
    title, desc, h1 = page_head(data, g)
    return (base_html.replace("__DASHBOARD_TITLE__", htmlmod.escape(title))
                     .replace("__DASHBOARD_DESCRIPTION__", htmlmod.escape(desc, quote=True))
                     .replace("__DASHBOARD_H1__", htmlmod.escape(h1))
                     .replace("__DASHBOARD_OPEN_GAME__", str(g["id"]) if g else "null")
                     .replace("<!--share-->", share_tags(title, desc, site_url, data, g))
                     .replace("<!--seo-->", verify_tag(verify) + json_ld(data, site_url, title, desc, g))
                     .replace("__DASHBOARD_FALLBACK__", static_summary(data, g, site_url)))


def render(data: dict, template: Path, out: Path, fragment: bool = False, site_url: str = "",
           verify: str = "") -> Path:
    """Writes the page, and - once the site has an address - a page per game beside it.

    Every game page is the same page opened on that game, with its own title, description, heading,
    canonical link and plain-HTML summary, so each one can be found and shared on its own. The season's
    data is baked in once and reused for all of them."""
    # Each game carries the title and heading of its own page, so that switching games in place can keep
    # the tab and the heading in step with the address bar. Written here, from the same page_head() the
    # served pages use, rather than rebuilt in the page's JavaScript, where the two could drift apart.
    for g in data["games"]:
        g["title"], _, g["h1"] = page_head(data, g)
    blob = json.dumps(clean(data), separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    base_html = template.read_text(encoding="utf-8")
    assert "__DASHBOARD_DATA__" in base_html, "template is missing its data placeholder"
    base_html = (base_html.replace("__DASHBOARD_FAVICON__", asset_uri("favicon.png"))
                          .replace("__DASHBOARD_LOGO_LIGHT__", asset_uri("logo-light.png"))
                          .replace("__DASHBOARD_LOGO_DARK__", asset_uri("logo-dark.png"))
                          .replace("__DASHBOARD_DATA__", blob))
    html = one_page(base_html, data, site_url, verify, None)
    if fragment:  # no html/head/body wrapper: title, fonts and styles, then the page body
        head = re.search(r"<head>(.*?)</head>", html, re.S).group(1)
        body = re.search(r"<body>(.*?)</body>", html, re.S).group(1)
        html = head[head.index("<title>"):] + body
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    if site_url and not fragment:
        shutil.copyfile(HERE / "assets" / "touch-icon.png", out.parent / TOUCH_ICON)  # phone home-screen icon
        for g in data["games"]:
            page = out.parent / "game" / g["slug"] / "index.html"
            page.parent.mkdir(parents=True, exist_ok=True)
            page.write_text(one_page(base_html, data, site_url, verify, g), encoding="utf-8")
        seo_files(out, site_url, data)
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
    ap.add_argument("--brand-url", default=BRAND_URL, help='where the logo and the Subscribe button lead ("" hides the button)')
    ap.add_argument("--support-url", default=SUPPORT_URL, help='the "Buy me a beer" link ("" hides it)')
    ap.add_argument("--feedback-key", default="", help="Web3Forms access key for the Bugs/Requests form, which emails "
                                                         "each message to the address the key was made for (blank hides the form)")
    ap.add_argument("--verify-google", default="", help="the google-site-verification code from Search "
                                                       "Console, if you verify the site with a meta tag")
    ap.add_argument("--template", default=str(HERE / "dashboard_template.html"))
    ap.add_argument("--cache", default=".nhl_cache")
    ap.add_argument("--offline", action="store_true", help="use cached data only")
    ap.add_argument("--ttl", type=int, default=1800, help="seconds before unfinished data (schedule, stats reports) is "
                                                          "fetched again; finished games are kept for good either way")
    ap.add_argument("--sample", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--fragment", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    api = sv.Api(Path(args.cache), offline=args.offline, ttl=args.ttl)
    data = build_data(api, args.team.upper(), args.season, args.color, args.credit, sample=args.sample)
    data["meta"]["brandUrl"] = args.brand_url.rstrip("/")
    data["meta"]["supportUrl"] = args.support_url
    data["meta"]["feedbackKey"] = args.feedback_key.strip()  # public by design: it can only send mail to the owner
    data["meta"]["siteUrl"] = args.site_url.rstrip("/") + "/" if args.site_url else ""  # printed on share images
    out = render(data, Path(args.template), Path(args.out), fragment=args.fragment, site_url=args.site_url,
                 verify=args.verify_google)
    kb = out.stat().st_size / 1024
    pages = f", {len(data['games'])} game pages" if args.site_url else ""
    print(f"Dashboard: {out}  ({len(data['games'])} games, {len(data['players'])} players, {kb:.0f} KB{pages})")


if __name__ == "__main__":
    main()
