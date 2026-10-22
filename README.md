# picks-data

Data for the team score picks (`tools/daily_picks.py` on `main`, run by `.github/workflows/picks.yml`).
The workflow commits here; nothing on this branch is published to the site.

- `team_score_picks.xlsx`: the spreadsheet (also attached to each pre-game email)
- `games.json`: every finished 2026-27 regular-season game with both teams' team scores
- `picks.json`: one row per game from Oct 6, 2026 (pick, line, result, whether it was emailed under that day's rule)
- `rules.json`: each day's rule and whether that day's email went out
- `backtest_2025_26.json`: last season's backtest (fixed)
