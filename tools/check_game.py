#!/usr/bin/env python3
"""
check_game.py - compare what the dashboard shows for one game with the NHL's
official game sheets (the Event Summary and Game Summary reports on nhl.com,
which are produced separately from the JSON API the dashboard reads).

    python tools/check_game.py dashboard.html 2025021285 [more game ids...]

Checks the score, every Dallas skater's line (G, A, +/-, PIM, penalties, SOG,
shot attempts, hits, blocks, giveaways, takeaways, TOI and its even-strength /
power-play / penalty-kill split, shifts, faceoffs won and lost), the goalies, each goal's scorer, assists (in order) and strength, and that the
shot map has Dallas shooting right in every period. Prints MATCH or DIFF for
each check.
"""
from __future__ import annotations

import html as htmlmod
import json
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stars_viz as sv  # noqa: E402

REPORT = "https://www.nhl.com/scores/htmlreports/{season}/{kind}{game}.HTM"
ES_COLS = ["num", "pos", "name", "g", "a", "p", "pm", "pn", "pim", "toi", "shf", "avg", "pp", "sh", "ev",
           "s", "ab", "ms", "ht", "gv", "tk", "bs", "fw", "fl", "fpct"]


def rows_of(page: str) -> list[list[str]]:
    out = []
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = [re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", "", c))).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
        out.append(cells)
    return out


def fetch_report(kind: str, game_id: int) -> str:
    s = str(game_id)
    url = REPORT.format(season=f"{s[:4]}{int(s[:4]) + 1}", kind=kind, game=s[4:])
    r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 stars-viz"})
    r.raise_for_status()
    return r.text


def n(v: str) -> int:
    v = (v or "").strip()
    return int(v) if re.fullmatch(r"[+-]?\d+", v) else 0


def mmss(v: str) -> int:
    mm, ss = (v or "0:00").split(":")
    return int(mm) * 60 + int(ss)


def load_page_data(path: Path) -> dict:
    blob = re.search(r'<script id="data" type="application/json">(.*?)</script>', path.read_text(), re.S).group(1)
    return json.loads(blob.replace("<\\/", "</"))


class Report:
    def __init__(self, label):
        self.label, self.diffs, self.matches = label, [], 0

    def check(self, what, ours, theirs):
        if ours == theirs:
            self.matches += 1
        else:
            self.diffs.append(f"{what}: page {ours!r} vs sheet {theirs!r}")


def check(data: dict, game_id: int, api: sv.Api) -> Report:
    g = next(x for x in data["games"] if x["id"] == game_id)
    P = data["players"]
    rep = Report(f"Game {g['n']} {g['date']} {'vs' if g['home'] else 'at'} {g['opp']} "
                 f"{g['gf']}-{g['ga']}{' ' + g['sfx'] if g['sfx'] else ''}")
    box = api.get(sv.url_game(game_id, "boxscore"), final_only_cache=True)
    pbp = api.get(sv.url_game(game_id, "play-by-play"), final_only_cache=True)
    us_side = "homeTeam" if g["home"] else "awayTeam"
    num_of = {p["playerId"]: p["sweaterNumber"] for grp in ("forwards", "defense", "goalies")
              for p in box["playerByGameStats"][us_side][grp]}

    es, gs = rows_of(fetch_report("ES", game_id)), rows_of(fetch_report("GS", game_id))

    # ---- final score (sheet header: VISITOR, its score, ..., HOME, its score) ----
    scores = [int(r[1]) for r in gs[:40] if len(r) == 3 and r[0] == r[2] == "" and r[1].isdigit()][:2]
    rep.check("final score (DAL-OPP)", (g["gf"], g["ga"]), tuple(scores[::-1] if g["home"] else scores))

    # ---- skaters (Event Summary: visitor's block first, each block ends with TEAM TOTALS) ----
    block, sheet = 1, {}
    dal_block = 2 if g["home"] else 1
    for r in es:
        if r and r[0] == "TEAM TOTALS":
            block += 1
        elif len(r) == len(ES_COLS) and r[0].isdigit() and r[1] in ("C", "L", "R", "D") and block == dal_block:
            sheet[int(r[0])] = dict(zip(ES_COLS, r))
    ours = {num_of[r[0]]: r for r in g["sk"]}
    rep.check("Dallas skaters dressed", sorted(ours), sorted(sheet))
    att = {}
    for s in g["shots"]:
        if s[1] and s[5]:
            att[s[5]] = att.get(s[5], 0) + 1
    for num, r in sorted(ours.items()):
        e = sheet.get(num)
        if not e:
            continue
        who = f"#{num} {P[str(r[0])]['last']}"
        pid, gl, a, pmv, pim, sog, hits, blk, toi, ppg, gv, tk, fo, shf, pen_t, pen_d, fo_w, fo_l, sat_f, sat_a, ev, pp, sh = r
        for key, mine in (("g", gl), ("a", a), ("pm", pmv), ("pim", pim), ("pn", pen_t), ("s", sog), ("ht", hits),
                          ("bs", blk), ("gv", gv), ("tk", tk), ("shf", shf), ("fw", fo_w), ("fl", fo_l)):
            rep.check(f"{who} {key.upper()}", mine, n(e[key]))
        rep.check(f"{who} TOI", toi, mmss(e["toi"]))
        if ev is not None:  # the on-ice shot attempts (sat_f, sat_a) aren't on the official sheets
            rep.check(f"{who} TOI EV/PP/SH", (ev, pp, sh), (mmss(e["ev"]), mmss(e["pp"]), mmss(e["sh"])))
        rep.check(f"{who} shot attempts", att.get(pid, 0), n(e["s"]) + n(e["ab"]) + n(e["ms"]))
        fw, fl = n(e["fw"]), n(e["fl"])
        rep.check(f"{who} FO%", round(fo or 0, 2), round(fw / (fw + fl), 2) if fw + fl else 0)

    # ---- goalies (Game Summary goaltender table: "GA-SA" in the TOT column) ----
    gk_sheet, gk_team = {}, 0
    for r in gs:
        if r[:4] == ["EV", "PP", "SH", "TOT"]:
            gk_team += 1
        if len(r) >= 11 and r[1] == "G" and r[0].isdigit() and r[-1]:  # OT games add a column
            ga, sa = (int(x) for x in r[-1].split("-"))
            gk_sheet[(gk_team, int(r[0]))] = (sa, sa - ga, ga)
    for r in g["gk"]:
        who = f"#{num_of[r[0]]} {P[str(r[0])]['last']}"
        rep.check(f"{who} shots/saves/GA", (r[1], r[2], r[3]), gk_sheet.get((dal_block, num_of[r[0]])))

    # ---- goals (Game Summary scoring table) ----
    sheet_goals = []
    for r in gs:
        if len(r) == 10 and r[0].isdigit() and re.fullmatch(r"\d+:\d\d", r[2] or "") and r[1] != "SO":
            nums = [int(x.split()[0]) if x and x[0].isdigit() else None for x in r[5:8]]
            sheet_goals.append(dict(per=r[1], clock=r[2], str=r[3], team=r[4], scorer=nums[0],
                                    assists=[x for x in nums[1:] if x is not None]))
    rep.check("goals in regulation/OT", len(g["goals"]), len(sheet_goals))
    str_map = {"EV": "EV", "EA": "EV", "EN": "EV", "PP": "PP", "SH": "SH"}
    for mine, theirs in zip(g["goals"], sheet_goals):
        label = f"goal {theirs['per']} {theirs['clock']} {theirs['team']}"
        per = {"1": 1, "2": 2, "3": 3, "OT": 4}.get(theirs["per"], theirs["per"])
        rep.check(f"{label} period+time", (mine[2], mine[3].lstrip("0")), (per, theirs["clock"].zfill(4).lstrip("0")))
        rep.check(f"{label} team", "DAL" if mine[1] else g["opp"], theirs["team"])
        rep.check(f"{label} strength", str_map[mine[7]], theirs["str"].split("-")[0])
        if mine[1]:
            rep.check(f"{label} scorer #", num_of.get(mine[4]), theirs["scorer"])
            rep.check(f"{label} assists # (in order)", [num_of.get(x) for x in mine[8]], theirs["assists"])

    # ---- shot map direction: the NHL tags each shot's zone ("O" = shooter's attacking zone) ----
    us_id = box[us_side]["id"]
    wrong = total = 0
    for p in pbp["plays"]:
        d = p.get("details") or {}
        if p.get("typeDescKey") not in ("goal", "shot-on-goal", "missed-shot") or d.get("zoneCode") != "O":
            continue
        if (p.get("periodDescriptor") or {}).get("periodType") == "SO" or d.get("xCoord") is None:
            continue
        total += 1
        ours_shot = d.get("eventOwnerTeamId") == us_id
        mine = next((s for s in g["shots"] if abs(s[0] - sv.game_minute(p["periodDescriptor"]["number"], p["timeInPeriod"])) < 0.01
                     and s[1] == (1 if ours_shot else 0) and s[2] in (0, 1, 2) and abs(abs(s[3]) - abs(d["xCoord"])) == 0), None)
        if mine is None or (mine[3] < 25 if ours_shot else mine[3] > -25):  # blue line is x = ±25
            wrong += 1
    rep.check("attacking-zone shots drawn on the correct side", f"{total - wrong}/{total}", f"{total}/{total}")
    return rep


def main(argv):
    page, ids = Path(argv[0]), [int(x) for x in argv[1:]]
    data = load_page_data(page)
    api = sv.Api(Path(".nhl_cache"))
    all_ok = True
    for gid in ids:
        rep = check(data, gid, api)
        print(f"\n{rep.label}: {rep.matches} checks match, {len(rep.diffs)} differ")
        for d in rep.diffs:
            print("  DIFF", d)
        all_ok &= not rep.diffs
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
