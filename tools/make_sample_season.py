"""
Builds a fake but schema-faithful NHL API cache (a full 82-game season) so the
dashboard can be built and tested offline. SAMPLE DATA ONLY: real player names,
made-up numbers.

    python tools/make_sample_season.py .sample_cache
    python build_dashboard.py --offline --cache .sample_cache --sample --out sample.html
"""
import json, random, sys, datetime as dt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stars_viz as sv

random.seed(11)
rng = random.Random(23)  # for everything added after the first version, so the original season stays the same
SKATER_ROWS = {"summaryshooting": [], "timeonice": []}  # the NHL's per-skater, per-game stats reports
CACHE = Path(sys.argv[1]); CACHE.mkdir(parents=True, exist_ok=True)
api = sv.Api(CACHE)
put = lambda url, data: api._path(url).write_text(json.dumps(data))
SEASON = 20252026

# name, pos, num, shoots, born, goal weight, assist weight, toi (min)
ROSTER = [
    ("Jason Robertson", "L", 21, "L", "1999-07-22", 15, 12, 19.5), ("Wyatt Johnston", "C", 53, "L", "2003-05-14", 12, 10, 19),
    ("Mikko Rantanen", "R", 96, "L", "1996-10-29", 12, 14, 20), ("Roope Hintz", "C", 24, "L", "1996-11-17", 9, 9, 18),
    ("Tyler Seguin", "C", 91, "R", "1992-01-31", 8, 8, 16.5), ("Jamie Benn", "L", 14, "L", "1989-07-18", 5, 7, 15),
    ("Matt Duchene", "C", 95, "L", "1991-01-16", 6, 8, 15.5), ("Sam Steel", "C", 18, "L", "1998-02-03", 3, 3, 13),
    ("Oskar Bäck", "C", 10, "L", "2000-03-06", 2, 2, 11.5), ("Colin Blackwell", "C", 15, "R", "1993-03-28", 2, 2, 11),
    ("Joel Kiviranta", "L", 25, "L", "1996-03-23", 3, 2, 11.5), ("Radek Faksa", "C", 12, "L", "1994-01-09", 2, 3, 12.5),
    ("Miro Heiskanen", "D", 4, "L", "1999-07-18", 3, 12, 25), ("Thomas Harley", "D", 55, "L", "2001-08-19", 4, 10, 23.5),
    ("Esa Lindell", "D", 23, "L", "1994-05-23", 1, 5, 22), ("Nils Lundkvist", "D", 5, "R", "2000-07-27", 2, 5, 18),
    ("Lian Bichsel", "D", 6, "L", "2004-05-18", 1, 3, 16), ("Ilya Lyubushkin", "D", 46, "R", "1994-04-06", 0.5, 2, 16.5),
]
GOALIES = [("Jake Oettinger", 29, "L", "1998-12-18", 0.66), ("Casey DeSmith", 1, "L", "1991-08-13", 0.34)]
OPP_NAMES = ["Larsen", "Kowalski", "Brandt", "Novak", "Dupuis", "Mäkelä", "Garrison", "Holt", "Rask", "Ferreira",
             "Lindqvist", "Morrow", "Keller", "Aho", "Bennett", "Chase"]
OPPS = [(30, "MIN", "Wild"), (21, "COL", "Avalanche"), (52, "WPG", "Jets"), (19, "STL", "Blues"), (18, "NSH", "Predators"),
        (16, "CHI", "Blackhawks"), (68, "UTA", "Mammoth"), (26, "LAK", "Kings"), (22, "EDM", "Oilers"), (20, "CGY", "Flames"),
        (23, "VAN", "Canucks"), (54, "VGK", "Golden Knights"), (28, "SJS", "Sharks"), (24, "ANA", "Ducks"), (55, "SEA", "Kraken"),
        (10, "TOR", "Maple Leafs"), (8, "MTL", "Canadiens"), (6, "BOS", "Bruins"), (3, "NYR", "Rangers"), (4, "PHI", "Flyers"),
        (14, "TBL", "Lightning"), (13, "FLA", "Panthers")]

pid_iter = iter(range(8470000, 8499999))
stars = []
for name, pos, num, sh, born, gw, aw, toi in ROSTER:
    stars.append(dict(id=next(pid_iter), name=name, pos=pos, num=num, sh=sh, born=born, gw=gw, aw=aw, toi=toi))
goalies = [dict(id=next(pid_iter), name=n, num=num, sh=sh, born=b, share=s) for n, num, sh, b, s in GOALIES]
short = lambda full: f"{full.split()[0][0]}. {' '.join(full.split()[1:])}"


def roster_entry(p, pos):
    first, last = p["name"].split(" ", 1)
    return {"id": p["id"], "firstName": {"default": first}, "lastName": {"default": last}, "sweaterNumber": p["num"],
            "positionCode": pos, "shootsCatches": p["sh"], "heightInInches": random.randint(70, 77),
            "weightInPounds": random.randint(180, 225), "birthDate": p["born"], "birthCity": {"default": "Somewhere"},
            "birthCountry": random.choice(["CAN", "USA", "FIN", "SWE"])}


put(f"{sv.WEB}/roster/DAL/{SEASON}", {
    "forwards": [roster_entry(p, p["pos"]) for p in stars if p["pos"] != "D"],
    "defensemen": [roster_entry(p, "D") for p in stars if p["pos"] == "D"],
    "goalies": [roster_entry(g, "G") for g in goalies]})


def clock(sec):
    return f"{sec // 60:02d}:{sec % 60:02d}"


def pick(weights_key, exclude=()):
    pool = [p for p in stars if p["id"] not in exclude]
    return random.choices(pool, weights=[p[weights_key] for p in pool])[0]


def gen_game(gid, date, opp, us_home, gf, ga, last, form):
    opp_id, opp_ab, opp_name = opp
    home_id = 25 if us_home else opp_id
    opp_players = [(next(pid_iter), f"{random.choice('ABCDEFGHJKLMNOPRST')}. {n}") for n in random.sample(OPP_NAMES, 12)]
    opp_goalie = (next(pid_iter), f"{random.choice('ABCDJKMS')}. {random.choice(OPP_NAMES)}")
    plays, ev = [], 100

    def add(period, sec, kind, team, sc="1551", details=None):
        nonlocal ev
        ev += 1
        plays.append({"eventId": ev, "periodDescriptor": {"number": period, "periodType": {4: "OT", 5: "SO"}.get(period, "REG"),
                      "maxRegulationPeriods": 3}, "timeInPeriod": clock(sec), "typeDescKey": kind, "situationCode": sc,
                      "homeTeamDefendingSide": "right" if period % 2 == 1 else "left", "details": details or {}})

    def xy(team, period, near=False):
        home_attacks_left = period % 2 == 1
        left = home_attacks_left if team == home_id else not home_attacks_left
        if near:
            x, y = random.uniform(62, 86), random.gauss(0, 9)
        else:
            x = random.uniform(30, 87) if random.random() < 0.92 else random.uniform(5, 30)
            y = random.gauss(0, 12 if x > 60 else 17)
        y = max(-38, min(38, y))
        return (-round(x), -round(y)) if left else (round(x), round(y))

    def pp_code(team):
        return "1451" if team == home_id else "1541"

    dressed = list(stars)
    if random.random() < 0.3:
        dressed.remove(random.choice([p for p in stars if p["pos"] != "D"]))
    dressed_ids = {p["id"] for p in dressed}

    def pick(key, exclude=()):
        pool = [p for p in dressed if p["id"] not in exclude]
        return random.choices(pool, weights=[p[key] for p in pool])[0]

    # goals: regulation tied portion + winner's extra
    reg_us, reg_them = gf, ga
    extra = None
    if last in ("OT", "SO"):
        if gf > ga:
            reg_us -= 1; extra = 25
        else:
            reg_them -= 1; extra = opp_id
    goal_events = [(25, None) for _ in range(reg_us)] + [(opp_id, None) for _ in range(reg_them)]
    random.shuffle(goal_events)
    times = sorted(random.sample(range(30, 3590), len(goal_events)))
    pp_counts = {25: 0, opp_id: 0}
    en_used = False
    for (team, _), t in zip(goal_events, times):
        period, sec = t // 1200 + 1, t % 1200
        sc = "1551"
        if random.random() < 0.2:
            sc = pp_code(team); pp_counts[team] += 1
        elif t > 3480 and not en_used and random.random() < 0.5:
            sc = ("1560" if team == home_id else "0651") if team == home_id else ("0651" if home_id == 25 else "1560")
            # scorer's opponent has pulled its goalie
            sc = "0651" if team == home_id else "1560"
            en_used = True
        x, y = xy(team, period, near=sc[0] != "0" and sc[-1] != "0")
        if team == 25:
            sc_p = pick("gw")
            a = []
            for _ in range(random.choices([0, 1, 2], [8, 30, 62])[0]):
                a.append(pick("aw", exclude=[sc_p["id"]] + [q["id"] for q in a]))
            det = {"scoringPlayerId": sc_p["id"], **{k: q["id"] for k, q in zip(("assist1PlayerId", "assist2PlayerId"), a)}}
        else:
            sp = random.choice(opp_players)
            others = [p for p in opp_players if p != sp]
            det = {"scoringPlayerId": sp[0], "assist1PlayerId": random.choice(others)[0]}
        det.update(xCoord=x, yCoord=y, zoneCode="O", shotType="wrist", eventOwnerTeamId=team,
                   scoringPlayerTotal=random.randint(1, 30))
        add(period, sec, "goal", team, sc, det)
    if extra:
        if last == "OT":
            sec = random.randint(20, 290)
            team = extra
            x, y = xy(team, 4, near=True)
            if team == 25:
                sc_p = pick("gw"); det = {"scoringPlayerId": sc_p["id"], "assist1PlayerId": pick("aw", [sc_p["id"]])["id"]}
            else:
                det = {"scoringPlayerId": random.choice(opp_players)[0]}
            det.update(xCoord=x, yCoord=y, zoneCode="O", eventOwnerTeamId=team)
            add(4, sec, "goal", team, "1331", det)
        else:
            add(4, 300, "period-end", 25)
            for k in range(3):
                for team in (25, opp_id):
                    add(5, 0, "goal" if (team == extra and k == 2) else "shot-on-goal", team, "0101",
                        {"xCoord": 80, "yCoord": 0, "eventOwnerTeamId": team,
                         ("scoringPlayerId" if team == extra and k == 2 else "shootingPlayerId"):
                             (pick("gw")["id"] if team == 25 else opp_players[0][0])})

    # shot attempts
    base_us = random.gauss(56 + (form - 0.55) * 30, 8)
    for team, n in ((25, int(base_us)), (opp_id, int(random.gauss(53, 8)))):
        for _ in range(max(30, n)):
            end = 3600 if not extra or last == "SO" else 3600
            t = random.randint(0, end - 1)
            period, sec = t // 1200 + 1, t % 1200
            if last in ("OT", "SO") and random.random() < 0.04:
                period, sec = 4, random.randint(0, 280)
            kind = random.choices(["shot-on-goal", "missed-shot", "blocked-shot"], [49, 26, 25])[0]
            sc = pp_code(team) if random.random() < 0.1 else ("1331" if period == 4 else "1551")
            x, y = xy(team, period)
            shooter = pick("gw")["id"] if team == 25 else random.choice(opp_players)[0]
            if kind == "blocked-shot":
                # 2025-26 API: the owner is the shooting team (older seasons used the blocking team)
                blocker = random.choice(opp_players)[0] if team == 25 else pick("toi")["id"]
                det = {"xCoord": x, "yCoord": y, "zoneCode": "D", "eventOwnerTeamId": team,
                       "shootingPlayerId": shooter, "blockingPlayerId": blocker, "reason": "blocked"}
            else:
                det = {"xCoord": x, "yCoord": y, "zoneCode": "O", "eventOwnerTeamId": team, "shootingPlayerId": shooter}
            add(period, sec, kind, team, sc, det)
    centers = [p for p in dressed if p["pos"] == "C"]
    for _ in range(58):
        t = random.randint(0, 3599)
        add(t // 1200 + 1, t % 1200, "faceoff", random.choice([25, opp_id]), "1551", {"eventOwnerTeamId": random.choice([25, opp_id])})
        d = plays[-1]["details"]
        ours = rng.choices(centers, [p["toi"] for p in centers])[0]["id"]
        theirs = rng.choice(opp_players)[0]
        d["winningPlayerId"], d["losingPlayerId"] = (ours, theirs) if d["eventOwnerTeamId"] == 25 else (theirs, ours)
    plays.sort(key=lambda p: (p["periodDescriptor"]["number"], p["timeInPeriod"]))
    # OT: drop anything after the winning goal
    if last == "OT":
        wt = [p["timeInPeriod"] for p in plays if p["periodDescriptor"]["number"] == 4 and p["typeDescKey"] == "goal"][0]
        plays = [p for p in plays if not (p["periodDescriptor"]["number"] == 4 and p["timeInPeriod"] > wt)]

    # boxscore from plays
    reg = [p for p in plays if p["periodDescriptor"]["periodType"] != "SO"]
    sog = {25: 0, opp_id: 0}; ind = {}
    en_against = {25: 0, opp_id: 0}
    for p in reg:
        d = p["details"]; k = p["typeDescKey"]
        if k in ("goal", "shot-on-goal"):
            t = d["eventOwnerTeamId"]; sog[t] += 1
            sid = d.get("scoringPlayerId") or d.get("shootingPlayerId")
            st = ind.setdefault(sid, dict(g=0, a=0, sog=0)); st["sog"] += 1
            if k == "goal":
                st["g"] += 1
                if p["situationCode"] in ("0651", "1560"):
                    en_against[25 if t != 25 else opp_id] += 1
                for key in ("assist1PlayerId", "assist2PlayerId"):
                    if key in d:
                        ind.setdefault(d[key], dict(g=0, a=0, sog=0))["a"] += 1
    starter = random.choices(goalies, [g["share"] for g in goalies])[0]
    ga_reg = sum(1 for p in reg if p["typeDescKey"] == "goal" and p["details"]["eventOwnerTeamId"] == opp_id)
    gf_reg = sum(1 for p in reg if p["typeDescKey"] == "goal" and p["details"]["eventOwnerTeamId"] == 25)
    game_len = 60 + (5 if last == "SO" else (int(plays[-1]["timeInPeriod"][:2]) + 1 if last == "OT" else 0))

    def sk(p):
        st = ind.get(p["id"], dict(g=0, a=0, sog=0))
        toi = max(6, random.gauss(p["toi"], 2.2)) * 60
        return {"playerId": p["id"], "sweaterNumber": p["num"], "name": {"default": short(p["name"])}, "position": p["pos"],
                "goals": st["g"], "assists": st["a"], "points": st["g"] + st["a"], "plusMinus": random.choice([-2, -1, -1, 0, 0, 0, 1, 1, 2]),
                "pim": random.choices([0, 2, 4], [85, 13, 2])[0], "hits": random.randint(0, 5), "powerPlayGoals": 0,
                "sog": st["sog"], "faceoffWinningPctg": round(random.uniform(0.35, 0.62), 3) if p["pos"] == "C" else 0.0,
                "toi": clock(int(toi)), "blockedShots": random.randint(0, 4 if p["pos"] == "D" else 2),
                "shifts": random.randint(16, 30), "giveaways": random.randint(0, 2), "takeaways": random.randint(0, 2)}

    us_box = {"forwards": [sk(p) for p in dressed if p["pos"] != "D"], "defense": [sk(p) for p in dressed if p["pos"] == "D"],
              "goalies": [{"playerId": g["id"], "sweaterNumber": g["num"], "name": {"default": short(g["name"])}, "position": "G",
                           "starter": g is starter, "shotsAgainst": sog[opp_id] if g is starter else 0,
                           "saves": sog[opp_id] - (ga_reg - en_against[25]) if g is starter else 0,
                           "goalsAgainst": ga_reg - en_against[25] if g is starter else 0,
                           "toi": clock(game_len * 60 - (60 if en_against[25] else 0)) if g is starter else "00:00"} for g in goalies]}
    opp_box = {"forwards": [{"playerId": pid, "name": {"default": nm}, "position": "C", "goals": ind.get(pid, {}).get("g", 0),
                             "assists": ind.get(pid, {}).get("a", 0), "points": 0, "sog": ind.get(pid, {}).get("sog", 0), "toi": "15:00",
                             "hits": random.randint(0, 4), "blockedShots": random.randint(0, 2), "pim": 0, "giveaways": 1, "takeaways": 1}
                            for pid, nm in opp_players[:8]],
               "defense": [], "goalies": [{"playerId": opp_goalie[0], "name": {"default": opp_goalie[1]}, "starter": True,
                                           "shotsAgainst": sog[25], "saves": sog[25] - (gf_reg - en_against[opp_id]), "toi": "60:00"}]}
    # extras the first version didn't have: penalties (matching each skater's PIM), faceoff % from the faceoff
    # plays, goalie saves by situation, and the stats-report rows (on-ice shot attempts, ice time by situation)
    us_skaters = us_box["forwards"] + us_box["defense"]
    for b in us_skaters:
        for _ in range(b["pim"] // 2):
            t = rng.randint(0, 3599)
            add(t // 1200 + 1, t % 1200, "penalty", 25, "1551", {
                "eventOwnerTeamId": 25, "typeCode": "MIN", "duration": 2, "descKey": "tripping",
                "committedByPlayerId": b["playerId"], "drawnByPlayerId": rng.choice(opp_players)[0]})
    for _ in range(rng.randint(1, 4)):
        t = rng.randint(0, 3599)
        det = {"eventOwnerTeamId": opp_id, "typeCode": "MIN", "duration": 2, "descKey": "hooking",
               "committedByPlayerId": rng.choice(opp_players)[0]}
        if rng.random() < 0.85:
            det["drawnByPlayerId"] = rng.choices(dressed, [p["gw"] + 2 for p in dressed])[0]["id"]
        add(t // 1200 + 1, t % 1200, "penalty", opp_id, "1551", det)
    plays.sort(key=lambda p: (p["periodDescriptor"]["number"], p["timeInPeriod"]))
    won, lost = {}, {}
    for p in plays:
        if p["typeDescKey"] == "faceoff":
            won[p["details"]["winningPlayerId"]] = won.get(p["details"]["winningPlayerId"], 0) + 1
            lost[p["details"]["losingPlayerId"]] = lost.get(p["details"]["losingPlayerId"], 0) + 1
    att5 = {25: 0, opp_id: 0}
    for p in reg:
        if p["situationCode"] == "1551" and p["typeDescKey"] in ("goal", "shot-on-goal", "missed-shot", "blocked-shot"):
            att5[p["details"]["eventOwnerTeamId"]] += 1
    for b, p in zip(us_skaters, [q for q in dressed if q["pos"] != "D"] + [q for q in dressed if q["pos"] == "D"]):
        w, l = won.get(b["playerId"], 0), lost.get(b["playerId"], 0)
        b["faceoffWinningPctg"] = round(w / (w + l), 6) if w + l else 0.0
        mm, ss = b["toi"].split(":")
        toi = int(mm) * 60 + int(ss)
        pp = min(toi // 3, max(0, int(rng.gauss(150, 50)))) if p["toi"] >= 15 else rng.choice([0, 0, 0, 20, 45])
        sh = min(toi // 4, max(0, int(rng.gauss(95, 40)))) if p["pos"] == "D" or p["toi"] < 14 else rng.choice([0, 0, 15])
        share = (toi - pp - sh) / 3600 * rng.gauss(1 + (p["gw"] - 5) * 0.006, 0.16)
        base = dict(gameId=gid, playerId=b["playerId"], gameDate=date, gamesPlayed=1)
        SKATER_ROWS["summaryshooting"].append(dict(base, satFor=max(0, round(att5[25] * share)),
                                                   satAgainst=max(0, round(att5[opp_id] * share * rng.gauss(1, 0.16)))))
        SKATER_ROWS["timeonice"].append(dict(base, timeOnIce=toi, evTimeOnIce=toi - pp - sh, ppTimeOnIce=pp, shTimeOnIce=sh))
    for b in us_box["goalies"]:
        pk_sa = min(b["shotsAgainst"], rng.randint(2, 7))
        pk_ga = min(b["goalsAgainst"], pp_counts[opp_id], pk_sa)
        ev_sa, ev_ga = b["shotsAgainst"] - pk_sa, b["goalsAgainst"] - pk_ga
        if ev_ga > ev_sa:  # keep both splits possible
            pk_ga += ev_ga - ev_sa; ev_ga = ev_sa
        b.update(evenStrengthShotsAgainst=f"{ev_sa - ev_ga}/{ev_sa}", powerPlayShotsAgainst=f"{pk_sa - pk_ga}/{pk_sa}",
                 shorthandedShotsAgainst="0/0")
    # names for opponent players via rosterSpots
    spots = [{"playerId": pid, "teamId": opp_id, "firstName": {"default": nm.split(". ")[0]},
              "lastName": {"default": nm.split(". ")[1]}} for pid, nm in opp_players]
    spots += [{"playerId": p["id"], "teamId": 25, "firstName": {"default": p["name"].split(" ", 1)[0]},
               "lastName": {"default": p["name"].split(" ", 1)[1]}} for p in dressed + goalies]
    team_obj = lambda t: ({"id": 25, "abbrev": "DAL", "commonName": {"default": "Stars"}} if t == 25
                          else {"id": opp_id, "abbrev": opp_ab, "commonName": {"default": opp_name}})
    home_t, away_t = (25, opp_id) if us_home else (opp_id, 25)
    score = {25: gf, opp_id: ga}
    common = {"id": gid, "season": SEASON, "gameType": 2, "gameDate": date, "gameState": "OFF",
              "venue": {"default": "American Airlines Center" if us_home else f"{opp_name} Arena"},
              "homeTeam": dict(team_obj(home_t), score=score[home_t], sog=sog[home_t]),
              "awayTeam": dict(team_obj(away_t), score=score[away_t], sog=sog[away_t]),
              "gameOutcome": {"lastPeriodType": last}}
    box = dict(common, playerByGameStats={"homeTeam": us_box if us_home else opp_box, "awayTeam": opp_box if us_home else us_box})
    pbp = dict(common, plays=plays, rosterSpots=spots)
    ppo = {25: pp_counts[25] + random.randint(1, 3), opp_id: pp_counts[opp_id] + random.randint(1, 3)}
    hv = lambda t: {25: us_box, opp_id: opp_box}[t]
    tsum = lambda t, k: sum(p.get(k, 0) for g in ("forwards", "defense") for p in hv(t)[g])
    rail = {"gameState": "OFF", "teamGameStats": [
        {"category": "sog", "homeValue": sog[home_t], "awayValue": sog[away_t]},
        {"category": "powerPlay", "homeValue": f"{pp_counts[home_t]}/{ppo[home_t]}", "awayValue": f"{pp_counts[away_t]}/{ppo[away_t]}"}]
        + [{"category": c, "homeValue": tsum(home_t, k), "awayValue": tsum(away_t, k)}
           for c, k in (("pim", "pim"), ("hits", "hits"), ("blockedShots", "blockedShots"), ("giveaways", "giveaways"), ("takeaways", "takeaways"))]}
    for part, dat in (("boxscore", box), ("play-by-play", pbp), ("right-rail", rail)):
        put(sv.url_game(gid, part), dat)
    us5 = sum(1 for p in reg if p["situationCode"] == "1551" and p["typeDescKey"] in ("goal", "shot-on-goal", "missed-shot", "blocked-shot")
              and p["details"]["eventOwnerTeamId"] == 25)
    all5 = sum(1 for p in reg if p["situationCode"] == "1551" and p["typeDescKey"] in ("goal", "shot-on-goal", "missed-shot", "blocked-shot"))
    return dict(sat=us5 / all5 if all5 else 0.5, ppg=pp_counts[25], ppo=ppo[25], ppga=pp_counts[opp_id], tsh=ppo[opp_id])


games, reports = [], {k: [] for k in ("summary", "powerplay", "penaltykill", "percentages")}
d = dt.date(2025, 10, 9)
for n in range(1, 83):
    form = 0.6 if n < 20 else (0.44 if n < 36 else (0.66 if n < 66 else 0.52))
    opp = random.choice(OPPS)
    home = random.random() < 0.5
    last = "REG"
    if random.random() < form:
        ga = random.choice([0, 1, 1, 2, 2, 2, 3, 3, 4]); gf = ga + random.choice([1, 1, 1, 2, 2, 3, 4])
        if gf - ga == 1 and random.random() < 0.3: last = random.choice(["OT", "OT", "SO"])
    else:
        gf = random.choice([0, 1, 1, 2, 2, 3, 3, 4]); ga = gf + random.choice([1, 1, 1, 2, 2, 3])
        if ga - gf == 1 and random.random() < 0.4: last = random.choice(["OT", "OT", "SO"])
    gid = 2025020000 + n * 7
    g_home = {"id": 25, "abbrev": "DAL", "commonName": {"default": "Stars"}, "score": gf}
    g_opp = {"id": opp[0], "abbrev": opp[1], "commonName": {"default": opp[2]}, "score": ga}
    games.append({"id": gid, "season": SEASON, "gameType": 2, "gameDate": d.isoformat(), "startTimeUTC": d.isoformat() + "T01:00:00Z",
                  "gameState": "OFF", "homeTeam": g_home if home else g_opp, "awayTeam": g_opp if home else g_home,
                  "gameOutcome": {"lastPeriodType": last}})
    adv = gen_game(gid, d.isoformat(), opp, home, gf, ga, last, form)
    base = dict(gameId=gid, gameDate=d.isoformat(), opponentTeamAbbrev=opp[1], homeRoad="H" if home else "R", teamId=25, gamesPlayed=1)
    reports["summary"].append(dict(base, goalsFor=gf, goalsAgainst=ga))
    reports["powerplay"].append(dict(base, powerPlayGoalsFor=adv["ppg"], ppOpportunities=adv["ppo"]))
    reports["penaltykill"].append(dict(base, ppGoalsAgainst=adv["ppga"], timesShorthanded=adv["tsh"]))
    reports["percentages"].append(dict(base, satPct=adv["sat"], shootingPlusSavePct5v5=random.gauss(1.0 + (form - 0.55) * 0.08, 0.035)))
    d += dt.timedelta(days=random.choice([1, 2, 2, 2, 3]))
    if d.month == 2 and 6 <= d.day <= 24:
        d = dt.date(2026, 2, 25)

put(sv.url_schedule("DAL", str(SEASON)), {"previousSeason": 20242025, "currentSeason": SEASON, "nextSeason": 20262027, "games": games})
for rep, rows in reports.items():
    random.shuffle(rows)
    put(sv.url_team_report(rep, 25, SEASON), {"data": rows, "total": len(rows)})
for rep, rows in SKATER_ROWS.items():
    put(sv.url_skater_report(rep, 25, SEASON), {"data": rows, "total": len(rows)})
put(sv.url_skater_report("percentages", 25, SEASON, by_game=False), {"total": len(stars), "data": [
    dict(playerId=p["id"], satRelative=round(rng.gauss(0, 0.03), 3), zoneStartPct5v5=round(rng.uniform(0.38, 0.62), 3),
         shootingPct5v5=round(rng.uniform(0.07, 0.12), 3), skaterSavePct5v5=round(rng.uniform(0.895, 0.93), 3)) for p in stars]})
put(sv.url_schedule("DAL"), {"previousSeason": SEASON, "currentSeason": 20262027, "nextSeason": 20272028, "games": []})
print("sample season ok:", len(games), "games")
