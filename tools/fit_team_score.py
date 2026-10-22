#!/usr/bin/env python3
"""
tools/fit_team_score.py - sets every constant behind the team score from one full NHL regular season, all 32 teams,
and prints them to paste in, along with the checks that justify them.

    python tools/fit_team_score.py --season 20252026 --cache .league_cache

  1. The expected-goals model: how likely each unblocked shot was to go in (stars_viz.XG_COEF).
  2. Score effects: the share of 5-on-5 shot attempts a typical team takes with each lead, home and away
     (stars_viz.SCORE_STATE_CF), which the team score uses to adjust shot attempts for the score.
  3. The team score itself (TEAM in dashboard_template.html): half the scoreboard (goal difference without empty-net
     goals), half how the team played. The play half weighs expected goals against shot attempts by how well each one,
     in a single game, points to the team's goal difference in its other games. Both halves are scaled to the same
     spread, averaged, and the result scaled so 10 points is one standard deviation across every team-game.

The first run downloads the season's play-by-play and boxscores (two requests per game, about an hour; they're cached
for good). After that it takes about a minute.
"""
from __future__ import annotations

import argparse
import collections
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import stars_viz as sv  # noqa: E402

FEATURES = ["const", "dist", "log_dist", "angle", "angle2", "d10", "d20", "d30", "d45",
            *[f"type_{t}" for t in sv.XG_TYPES if t != "wrist"], "type_other", "rebound", "rush", "pp", "sh",
            "tip_close", "defl_close", "reb_close", "angle_dist", "reb_angle"]
RESULT_SHARE = .5  # the scoreboard's share of the team score; the other half is how they played


def league_games(api: sv.Api, season: int):
    """Every regular-season game of the season, parsed from the home team's side (so both teams' shots are in)."""
    n_games = 1312 if season >= 20212022 else 1271
    for n in range(1, n_games + 1):
        gid = int(f"{str(season)[:4]}02{n:04d}")
        try:
            box = api.get(sv.url_game(gid, "boxscore"), final_only_cache=True)
            pbp = api.get(sv.url_game(gid, "play-by-play"), final_only_cache=True)
        except (Exception, SystemExit):  # a game that doesn't exist, a network hiccup, or --offline and not cached
            continue
        if box.get("gameState") in sv.FINAL_STATES:
            yield sv.parse_game(box, pbp, {}, box["homeTeam"]["abbrev"])


# ---------------------------------------------------------------- 1. expected goals
def row(s: dict) -> list[float]:
    f = sv.xg_features(s, s["strength"])
    assert set(f) <= set(FEATURES), set(f) - set(FEATURES)
    return [f.get(k, 0.0) for k in FEATURES]


def logistic(X: np.ndarray, y: np.ndarray, ridge: float = 1e-4, iters: int = 50) -> np.ndarray:
    """Plain logistic regression by Newton's method (numpy only)."""
    b = np.zeros(X.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-X @ b))
        H = X.T @ (X * (p * (1 - p))[:, None]) + ridge * np.eye(X.shape[1])
        step = np.linalg.solve(H, X.T @ (y - p) - ridge * b)
        b += step
        if np.max(np.abs(step)) < 1e-9:
            break
    return b


def auc(y: np.ndarray, p: np.ndarray) -> float:
    ranks = np.empty(len(p))
    ranks[np.argsort(p)] = np.arange(1, len(p) + 1)
    pos = y == 1
    return (ranks[pos].sum() - pos.sum() * (pos.sum() + 1) / 2) / (pos.sum() * (~pos).sum())


def fit_xg(games: list[dict]) -> dict:
    shots = [s for g in games for s in g["shots"] if s["kind"] != "blocked-shot" and not s["empty_net"] and s["dist"] is not None]
    X = np.array([row(s) for s in shots])
    y = np.array([1.0 if s["kind"] == "goal" else 0.0 for s in shots])
    b = logistic(X, y)
    p = 1 / (1 + np.exp(-X @ b))
    print(f"Expected goals: {len(y):,} unblocked shots, {int(y.sum()):,} goals ({y.mean():.1%}). "
          f"AUC {auc(y, p):.3f} (0.5 = a coin flip, 1 = perfect); predicted {p.sum():,.0f} goals.")
    print("  by predicted chance:")
    for lo, hi in ((0, .03), (.03, .06), (.06, .1), (.1, .15), (.15, .25), (.25, 1)):
        m = (p >= lo) & (p < hi)
        if m.any():
            print(f"    {lo:.2f}-{hi:.2f}: {m.sum():7,} shots, predicted {p[m].mean():.3f}, went in {y[m].mean():.3f}")
    print("  by distance:")
    d = X[:, FEATURES.index("dist")]  # capped at 100 ft
    for lo, hi in ((0, 10), (10, 20), (20, 30), (30, 45), (45, 200)):
        m = (d >= lo) & (d < hi)
        print(f"    {lo:3}-{hi:<3} ft: {m.sum():7,} shots, predicted {p[m].mean():.3f}, went in {y[m].mean():.3f}")
    print("  by shot type:")
    for t in sv.XG_TYPES + ("other",):
        m = np.array([s["stype"] == t for s in shots])
        print(f"    {t:12}: {m.sum():7,} shots, predicted {p[m].mean():.3f}, went in {y[m].mean():.3f}")
    return {f: round(float(v), 5) for f, v in zip(FEATURES, b)}


# ---------------------------------------------------------------- 2. score effects
def score_state_shares(games: list[dict]) -> dict:
    num, den = collections.Counter(), collections.Counter()
    for g in games:
        lead = 0  # home team's lead
        for s in g["shots"]:
            if s["five"]:
                for home in (True, False):
                    state = (max(-3, min(3, lead if home else -lead)), home)
                    den[state] += 1
                    num[state] += s["ours"] == home
            if s["kind"] == "goal":
                lead += 1 if s["ours"] else -1
    return {k: round(num[k] / den[k], 4) for k in sorted(den)}


# ---------------------------------------------------------------- 3. the team score
def from_away(g: dict) -> dict:
    return dict(g, us_home=False, shots=[dict(s, ours=not s["ours"]) for s in g["shots"]])


def team_games(games: list[dict]) -> list[dict]:
    out = []
    for g in games:
        for side, home in ((g, True), (from_away(g), False)):
            t = sv.team_score_inputs(side)
            st = {k: v if home else v[::-1] for k, v in g["stats"].items() if isinstance(v, tuple)}
            team = (g["us"] if home else g["them"])["abbrev"]
            us, them = (g["us_score"], g["them_score"]) if home else (g["them_score"], g["us_score"])
            out.append(dict(team=team, gid=g["id"], win=us > them, gd=t["gf"] - t["ga"], xgd=t["xgf"] - t["xga"], cfd=t["cf"] - t["ca"],
                            cfd_raw=t["cfRaw"] - t["caRaw"], pend=st["penalties"][1] - st["penalties"][0], fod=st["faceoffs"][0] - st["faceoffs"][1],
                            hitd=st["hits"][0] - st["hits"][1], tkgv=(st["takeaways"][0] - st["giveaways"][0]) - (st["takeaways"][1] - st["giveaways"][1])))
    return out


def corr(a, b) -> float:
    return float(np.corrcoef(a, b)[0, 1])


def fit_team(rows: list[dict]) -> dict:
    by_team = collections.defaultdict(list)
    for i, r in enumerate(rows):
        by_team[r["team"]].append(i)
    col = lambda k: np.array([float(r[k]) for r in rows])
    gd = col("gd")
    # the team's goal difference per game in all its other games: what a single game's numbers should point to
    total = {t: gd[I].sum() for t, I in by_team.items()}
    other = np.array([(total[r["team"]] - r["gd"]) / (len(by_team[r["team"]]) - 1) for r in rows])
    X = np.column_stack([col("xgd"), col("cfd"), np.ones(len(rows))])
    b_xg, b_cf, _ = np.linalg.lstsq(X, other, rcond=None)[0]
    play = b_xg * col("xgd") + b_cf * col("cfd")
    blend = RESULT_SHARE * gd / gd.std() + (1 - RESULT_SHARE) * play / play.std()
    sd = blend.std()
    team = dict(goal=10 * RESULT_SHARE / gd.std() / sd, xg=10 * (1 - RESULT_SHARE) * b_xg / play.std() / sd,
                cf=10 * (1 - RESULT_SHARE) * b_cf / play.std() / sd)
    score = np.clip(70 + team["goal"] * gd + team["xg"] * col("xgd") + team["cf"] * col("cfd"), 0, 100)

    def split_half(v):
        """A team's average over every other game against its goal difference per game in the rest, both ways round."""
        xs, ys = [], []
        for I in by_team.values():
            I = sorted(I, key=lambda i: rows[i]["gid"])
            for a, c in ((I[0::2], I[1::2]), (I[1::2], I[0::2])):
                xs.append(v[a].mean())
                ys.append(gd[c].mean())
        return corr(xs, ys)

    n = len(rows)
    print(f"\nTeam score: {n:,} team-games, {len(by_team)} teams.")
    print("  A single game's number against the team's goal difference per game in its other games (r):")
    for k, lab in (("gd", "goal difference"), ("xgd", "expected goals difference"), ("cfd", "5-on-5 shot attempts, score-adjusted"),
                   ("cfd_raw", "5-on-5 shot attempts, raw"), ("pend", "penalties drawn minus taken"), ("fod", "faceoffs won minus lost"),
                   ("hitd", "hits"), ("tkgv", "takeaways minus giveaways")):
        print(f"    {lab:40} {corr(col(k), other):+.3f}")
    print(f"    {'team score':40} {corr(score, other):+.3f}")
    print("  Half the season predicting the other half (split-half r with goal difference per game):")
    for v, lab in ((gd, "goal difference"), (col("xgd"), "expected goals difference"), (col("cfd"), "shot attempts, adjusted"),
                   (np.array([2.0 * r["win"] for r in rows]), "wins"), (score, "team score")):
        print(f"    {lab:40} {split_half(v):+.3f}")
    win = np.array([r["win"] for r in rows])
    print(f"  Wins scored 70 or more: {np.mean(score[win] >= 70):.0%}; losses under 70: {np.mean(score[~win] < 70):.0%}")
    print(f"  Grades: A (90+) {np.mean(score >= 90):.1%}, B (80s) {np.mean((score >= 80) & (score < 90)):.1%}, "
          f"C (70s) {np.mean((score >= 70) & (score < 80)):.1%}, under 70 {np.mean(score < 70):.1%}")
    return {k: round(v, 3) for k, v in team.items()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, default=20252026)
    ap.add_argument("--cache", default=".league_cache", help="where the season's games are cached")
    ap.add_argument("--offline", action="store_true", help="use cached games only")
    args = ap.parse_args(argv)
    games = list(league_games(sv.Api(Path(args.cache), offline=args.offline), args.season))
    print(f"{len(games):,} games\n")

    sv.XG_COEF = fit_xg(games)
    for g in games:  # re-rate every shot with the new model
        for s in g["shots"]:
            if "xg" in s and not s["empty_net"]:
                s["xg"] = sv.shot_xg(s, s["strength"])
    shares = score_state_shares(games)
    sv.SCORE_STATE_CF = shares
    team = fit_team(team_games(games))

    label = sv.season_label(args.season)
    print(f"\n# stars_viz.py\nXG_COEF = {{  # fit on {label} by tools/fit_team_score.py")
    for f, v in sv.XG_COEF.items():
        print(f'    "{f}": {v},')
    print("}\n\nSCORE_STATE_CF = {  # (lead, home): share of 5-on-5 shot attempts")
    for k, v in shares.items():
        print(f"    {k}: {v},")
    print("}\n\n// dashboard_template.html")
    print(f'const TEAM = {{ goal: {team["goal"]}, xg: {team["xg"]}, cf: {team["cf"]}, season: "{label}" }};')


if __name__ == "__main__":
    main()
