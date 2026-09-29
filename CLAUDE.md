# CLAUDE.md: Stars player rankings

Read this before touching anything. It records what was built, why, what has been verified and what hasn't.

## What this is and who it's for

The owner writes a Substack for Dallas Stars fans and is building a brand as "the visual storyteller": the person who uses stats to show how a game went, player by player. The long-term goal is a portfolio good enough to get noticed by the team. He has a full-time job, so everything should run with little or no manual work.

The main product is **one web page of player rankings**, rebuilt after every game from the NHL's free public API and hosted as a static page that his posts link to.

## Status: live-tested, automated (Sep 2026)

- Built against the live API for the full 2025-26 season (82 games). Fixed: blocked shots were credited to the wrong team (see the API notes), players who left mid-season had no bio (now filled from `player/{id}/landing`), and faceoff % was rounded one digit too early.
- Verified 3 games (regulation 2025021285, OT 2025021239, shootout 2025021301) against the NHL's official HTML game sheets with `tools/check_game.py`: 813 of 814 checks match. The one miss is an NHL-side inconsistency (play-by-play credits Hyry with a shot the official sheet doesn't), not a parsing bug.
- pytest suite in `tests/` (sample-season fixture + Playwright smoke tests) runs before every publish.
- Published nightly to GitHub Pages by `.github/workflows/publish.yml`.

## Files

| File | Role |
|---|---|
| `build_dashboard.py` | Main entry point. Fetches the season, parses every game, bakes compact JSON into the template, writes one self-contained `dashboard.html`. `--site-url` adds the Open Graph/Twitter image tags and writes `apple-touch-icon.png` next to the page. |
| `dashboard_template.html` | The whole page: a full HTML document (head with title, meta, fonts, CSS; body with markup and vanilla JS; no libraries except Google Fonts). The builder fills `__DASHBOARD_TITLE__`, `__DASHBOARD_DESCRIPTION__`, `__DASHBOARD_FAVICON__` (inline SVG), `<!--share-->` (OG/Twitter tags) and `__DASHBOARD_DATA__`. |
| `stars_viz.py` | Shared NHL API client with cache (`Api`), URL builders, and `parse_game()`, which the dashboard builder imports. Also a CLI that makes static PNG graphics (game card and trend), an earlier deliverable the owner may still use in posts. |
| `tools/make_sample_season.py` | Writes a fake full season into a cache folder, so everything can be built offline. Used by the tests. |
| `tools/check_game.py` | Compares one game on a built page with the NHL's official Event Summary / Game Summary HTML reports (`nhl.com/scores/htmlreports/{season}/ES0xxxxx.HTM`, uppercase `.HTM`). |
| `tools/make_share_image.py` | Playwright screenshot of the top of the built page (picker hidden) as the 1200x630 `og-image.png`. |
| `tests/` | pytest: data/parse tests on the sample season, and browser smoke tests. `--page PATH` runs the browser tests on a real built page (the workflow does this). |
| `.github/workflows/publish.yml` | Tests, builds from the live API, makes the share image, smoke-tests, deploys to Pages. Schedules, caching and failure behavior are documented at the top of the file. |
| `README.md` | Owner-facing setup and usage. |

Run it:

```bash
pip install -r requirements.txt
python build_dashboard.py --credit "yourname.substack.com"          # live
python tools/make_sample_season.py .sample_cache                   # offline sample
python build_dashboard.py --offline --cache .sample_cache --sample --out sample.html
```

`--sample` shows a "sample data" banner. `--fragment` (hidden flag) writes the page without the html/head/body wrapper; it was only used to preview in claude.ai.

Tests: `pip install -r requirements-dev.txt && python -m playwright install chromium && python -m pytest`.

## NHL API (free, no key, unofficial and undocumented)

Reference: https://github.com/Zmalski/NHL-API-Reference. Endpoints used:

- `api-web.nhle.com/v1/club-schedule-season/{TEAM}/{season|now}`: games with `id, gameType (1 pre, 2 regular, 3 playoffs), gameDate, startTimeUTC, gameState (FINAL/OFF = done), homeTeam/awayTeam {id, abbrev, commonName.default, score}, gameOutcome.lastPeriodType (REG/OT/SO)`. Top level has `currentSeason`, `previousSeason`.
- `api-web.nhle.com/v1/gamecenter/{id}/boxscore`: `playerByGameStats.{homeTeam,awayTeam}.{forwards,defense,goalies}[]`. Skaters: `playerId, name.default, position, goals, assists, plusMinus, pim, hits, powerPlayGoals, sog, faceoffWinningPctg, toi "MM:SS", blockedShots, shifts, giveaways, takeaways`. Goalies: `shotsAgainst, saves, goalsAgainst, toi, starter`.
- `.../gamecenter/{id}/play-by-play`: `plays[]` with `typeDescKey` (goal, shot-on-goal, missed-shot, blocked-shot, faceoff, ...), `periodDescriptor {number, periodType}`, `timeInPeriod`, `situationCode` (4 digits: away goalie, away skaters, home skaters, home goalie; "1551" = 5v5), `homeTeamDefendingSide`, `details {xCoord, yCoord, eventOwnerTeamId, shootingPlayerId, scoringPlayerId, assist1PlayerId, assist2PlayerId}`. Also `rosterSpots[]` for names.
  - **Blocked shots:** in 2025-26 `eventOwnerTeamId` is the *shooting* team (checked on all 2,442 blocks that season); older seasons used the blocking team. The parser ignores it and takes the shooting team from `shootingPlayerId` via `rosterSpots[].teamId`, falling back to the owner. The coordinates are where the block happened, so blocks stay off shot maps. `details.zoneCode` ("O" = shooter's attacking zone) is a handy independent check of shot-map direction.
  - Coordinates are normalized so Dallas always shoots right (x > 0).
- `.../gamecenter/{id}/right-rail`: `teamGameStats[] {category, homeValue, awayValue}` (power play "2/4", pim, hits, etc.). Optional; the parser falls back to boxscore sums.
- `api-web.nhle.com/v1/roster/{TEAM}/{season}`: names, numbers, positions, birth info. It lists only the end-of-season roster (21 players for 2025-26), so anyone traded, waived or hurt at season's end is filled from `api-web.nhle.com/v1/player/{id}/landing`, keeping the Dallas sweater number and position from the boxscore.
- `api.nhle.com/stats/rest/en/team/{summary|powerplay|penaltykill|percentages}?isAggregate=false&isGame=true&cayenneExp=teamId=25 and seasonId=... and gameTypeId=2`: per-game team stats (`satPct` = 5v5 shot share, `shootingPlusSavePct5v5` = PDO). Fetched by `stars_viz.load_trend()`. The current page no longer shows them, but the game list comes through that function.

Caching: finished games are cached forever in `.nhl_cache/`; everything else refreshes after 30 minutes. There is a 0.25 s pause between network calls.

## Compact data shape baked into the page (array indexes matter)

`build_dashboard.py` writes `{meta, players, games}`. Per game:

- `sk` (Dallas skaters): `[pid, goals, assists, plusMinus, pim, sog, hits, blocks, toiSeconds, ppGoals, giveaways, takeaways, faceoffPct, shifts]`
- `gk` (Dallas goalies who played): `[pid, shotsAgainst, saves, goalsAgainst, toiSeconds, starter(0/1), decision "W"/"L"/"OTL"/""]`
- `shots` (both teams, all attempts): `[gameMinute, ours(0/1), kind(0 goal, 1 on goal, 2 missed, 3 blocked), x, y, shooterPid (ours only, else 0), strength "EV"/"PP"/"SH"/"EN"/"EA"]`
- `goals`: `[gameMinute, ours, period, clock, scorerPid (ours only), scorerName, [assistNames], strength, [assistPids in order: primary first]]`
- also `st` (team stat pairs [DAL, OPP]), `oppGk`, `adv`, `takeaway`, `res` ("W"/"L"/"OTL"), `sfx` ("OT"/"SO"/"")

## The page (what the owner approved; keep it)

The owner rejected "stat dumps" and asked for **player rankings only**. He removed the Season tab, the Players tab, the team view and the scoring summary. Don't bring them back unless he asks.

Top to bottom:
1. Game picker strip (every game, W/L color-coded), defaulting to the latest game.
2. A headline written by rules from the data (e.g. "Johnston's big night lifts the Stars past the Lightning, 6-3", from `gameStory()`), plus the score line.
3. **Quadrant chart:** x = player score for this game (0 to 100, split at 50); y = player score minus **that player's own season average** (split at 0). Corners: Big night / Better than usual / Below his usual / Off night. Forwards are green circles, defensemen blue squares. Tap a dot to open that player's card. The owner offered "vs team average" as an alternative y-axis; we chose the player's own average because x already compares players to a typical Stars game, so team average would mostly repeat it.
4. **Forwards ranked by player score**, then **defensemen**. Each row shows the score, a bar, the change from his average, then G, A, P, SOG, ATT (attempts), +/-, HIT, BLK, TK, GV, TOI and FO% (centers). Under every stat is the change from that player's season average per game: green is better, red is worse, and it's shaded when the gap is at least 1 standard deviation. Under 0.35 SD it's gray. For giveaways, lower counts as better.
5. Goalies: save % and shots against compared with his season average.
6. Player card (a pop-up, not a tab): "His season" (score by game, production, points by game, ice time, shot map) or "One game" (compared with his normal, a timeline of when he showed up, his shots).

## Player score (the core idea; keep the method, weights can be tuned)

In `dashboard_template.html`, section `/* player score */`:
1. For each position group (forwards = C/L/R, defensemen = D), compute the mean and SD of every stat across **all Dallas player-games of that group this season**.
2. Game composite = the sum of weight × z-score.
3. Rescale the composite within the group: `score = 50 + 15 * (comp - mean) / sd`, clamped to 0-100. **This makes forwards and defensemen land on the same scale by construction** (on the sample season, both average 50 and the 10th-90th percentile is about 34-69).
4. The y-axis delta is the score minus the player's season-average score (all games in the dataset so far).

Weights (negative counts against):
- **Forwards:** goals .24, primary assists .14, slot attempts .11, shots on goal .10, TOI .09, +/- .08, secondary assists .07, takeaways minus giveaways .07, hits .05, PIM −.05
- **Defensemen:** +/- .14, TOI .14, goals .12, primary assists .12, blocks .12, shot attempts .10, takeaways minus giveaways .10, secondary assists .06, hits .05, PIM −.05

The "slot" is x 69-89, |y| ≤ 22 in NHL coordinates (between the faceoff dots, in front of the net). Primary and secondary assists come from the goal's assist order in play-by-play.

Known limits: the public API has no on-ice shot data, so there is no Corsi-for% per player; +/- stands in for it and is noisy. The scale is relative to *this team's* season, not the league. The z-scores use the whole dataset, so early-season scores shift as games are added. That's acceptable, but be aware of it.

## Design decisions to keep

- Stars green `#00754a` (light) / `#20a36b` (dark) for forwards and Dallas; defense blue `#2a78d6` / `#3987e5`; opponent gray. Checked for color-blind separation and contrast. Better/worse colors are separate tokens (`--good`, `--bad`) and always come with ▲/▼ arrows, never color alone.
- Light and dark themes via CSS tokens (`prefers-color-scheme` plus `data-theme`). Works at 390 px phone width with no sideways page scroll; the tables scroll inside their own containers, and names shorten to last name on phones.
- No NHL logos or headshots (they belong to the NHL). Sweater numbers stand in for photos. Keep "Data: NHL.com public API" in the footer.
- Headlines are rule-based on purpose (accurate, and they don't read as AI prose). The owner is wary of content that reads as AI-written.

## Getting it ready for the real world

Steps 1-6 were done in Sep 2026 (see Status). Notes from doing them:
- Goalie shots against can be less than team shots against: empty-net goals count as team shots. Not a bug.
- About 2% of shots sit in the shooter's own end: long clears scored as shots, and shots at an empty net. No period is flipped.
- `details.more` CSS is still used (the collapsible "Game log" on player season cards), and `rankOf()` is still used (team rank in the player card). Both were kept. `spark()`, `when`, `rollingRatio()` and 29 unused CSS classes were removed; the page renders pixel-identical before and after.
- GitHub pauses scheduled workflows after 60 days without repo activity; the workflow re-enables itself via the API after each scheduled deploy.

Original checklist:

1. **Run against the live API.** `python build_dashboard.py --season 20252026`, then `--season now` once the 2026-27 season starts. Fix any schema mismatches. Watch for: games where `right-rail` 404s, players traded mid-season (not on the roster endpoint, so they fall back to boxscore names), missing `faceoffWinningPctg`, shootout plays (period 5) and playoff games (gameType 3, excluded from the regular-season list).
2. **Check the numbers against NHL.com** for 3 games (one regulation, one OT, one shootout): score, each player's G/A/SOG/TOI, goalie saves, and that shot map sides are right (Dallas shooting right in every period).
3. **Tests.** Add pytest tests using `tools/make_sample_season.py` as the fixture: parse a game, build the page, check the JSON shape, check the score scale (F and D means ≈ 50, SD ≈ 15), and check there are no NaN/None where numbers are expected. Add a headless-browser smoke test (Playwright): the page loads with no console errors, the quadrant draws one dot per skater, and there's no horizontal overflow at 390 px.
4. **Clean up the page wrapper.** The builder currently wraps the template in `<html><head>…</head><body>` with `<title>`, `<link>` and `<style>` inside body (it works, but it's untidy). Split the template so those go in `<head>`, and add Open Graph/Twitter meta (title, description, a preview image) so links look good when shared on Substack and X. Add a favicon.
5. **Remove dead code** left over from removed views: `spark()`, `rankOf()` if unused, the `when` helper, and CSS for `.people`/`.person`, `.chipx`, `.periods`/`.period`, `.duel`, `.goals`/`.goal-row`, `details.more`, and the season-only chart classes. (`teamTrend`, `skaterTrend`, `goalieTrend`, `starsOfGame`, `lineText`, `vsRows` and `timeline` are still used by the header, headline and player card.) Keep `stars_viz.py`'s PNG CLI unless the owner says otherwise.
6. **Automate and host** (the owner wants zero manual work): a GitHub repo + GitHub Actions workflow that runs nightly during the season (e.g. 3:30 am Central, and optionally every 30 min from 9 pm to 1 am on game nights), builds `dashboard.html` → `index.html`, and deploys to GitHub Pages. Cache `.nhl_cache/` between runs with `actions/cache` so finished games aren't re-fetched. If the build fails, keep the last good page live and fail loudly (a GitHub email is fine).
7. **Nice-to-haves once live:** a custom domain; privacy-friendly analytics (Plausible or GoatCounter) so he can show reach in a portfolio; a per-game shareable link using `#<gameId>` (only plain `#token` anchors work when embedded; a normal host also supports query strings); an exportable PNG of the quadrant chart for posts.

## Working with the owner

He's not a developer. Explain what you did in plain words, ask before big changes to what the page shows, and keep the visual story first. The tables support the chart; they don't replace it.
