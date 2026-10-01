# CLAUDE.md: Stars player rankings

Read this before touching anything. It records what was built, why, what has been verified and what hasn't.

## What this is and who it's for

The owner writes a Substack for Dallas Stars fans and is building a brand as "the visual storyteller": the person who uses stats to show how a game went, player by player. The long-term goal is a portfolio good enough to get noticed by the team. He has a full-time job, so everything should run with little or no manual work.

The main product is **one web page of player rankings**, rebuilt after every game from the NHL's free public API and hosted as a static page that his posts link to.

## Status: live-tested, automated (Sep 2026)

- Built against the live API for the full 2025-26 season (82 games). Fixed: blocked shots were credited to the wrong team (see the API notes), players who left mid-season had no bio (now filled from `player/{id}/landing`), and faceoff % was rounded one digit too early.
- Verified 3 games (regulation 2025021285, OT 2025021239, shootout 2025021301) against the NHL's official HTML game sheets with `tools/check_game.py`: 813 of 814 checks match. The one miss is an NHL-side inconsistency (play-by-play credits Hyry with a shot the official sheet doesn't), not a parsing bug.
- **Advanced stats added Sep 30, 2026** (owner asked for "the right mix of advanced and regular metrics" on the page and in the score): on-ice shot attempts (Corsi), penalties drawn/taken, faceoffs won/lost, ice time by situation, goalie saves by situation. Checked on the whole 2025-26 season: the NHL's per-game on-ice rows add up to its season totals for all 28 skaters; recomputing one game's 5-on-5 on-ice attempts from raw shifts + play-by-play matched 16 of 18 skaters exactly (the other two off by one, a shift-change boundary); penalties and faceoffs counted from play-by-play match the NHL's own reports in all 1,476 player-games; EV + PP + SH ice time equals boxscore TOI everywhere. `tools/check_game.py` on the same 3 games: 1,030 of 1,031 checks match (same Hyry shot as before). **Not yet seen live:** how long after a game the NHL adds it to the stats reports. Until it does, that game's on-ice fields are null and the page says so.
- **Quadrant chart changed Sep 30, 2026** to offense vs. two-way play, after a reader pointed out the old chart's dots fell on a line (they had to: y was x minus the player's average, correlation about 0.85). The owner picked this over keeping the old chart and over "his usual vs. this game". The two halves correlate about 0.2, so the dots use the whole chart.
- pytest suite in `tests/` (sample-season fixture + Playwright smoke tests) runs before every publish.
- Published nightly to GitHub Pages by `.github/workflows/publish.yml`, from the repo `starsviz/starsviz.github.io` (a free org the owner created) to **https://starsviz.github.io/**. It is deliberately *not* on the owner's personal account: his user Pages site (`SJJ363.github.io`) is Insurtech Daily with the custom domain insurtechdaily.io, and GitHub would serve any project site on that account under that domain. Keep his other projects (Insurtech Daily, the `warriorlog` workout app) untouched. The footer credit is the repo Actions variable `CREDIT` (blank for now).

## Files

| File | Role |
|---|---|
| `build_dashboard.py` | Main entry point. Fetches the season, parses every game, bakes compact JSON into the template, writes one self-contained `dashboard.html`. `--site-url` adds the Open Graph/Twitter image tags and copies `apple-touch-icon.png` next to the page. |
| `dashboard_template.html` | The whole page: a full HTML document (head with title, meta, fonts, CSS; body with markup and vanilla JS; no libraries except Google Fonts). The builder fills `__DASHBOARD_TITLE__`, `__DASHBOARD_DESCRIPTION__`, `__DASHBOARD_FAVICON__` (PNG data URI), the two `__DASHBOARD_LOGO_*__` images, `<!--share-->` (OG/Twitter tags) and `__DASHBOARD_DATA__`. |
| `stars_viz.py` | Shared NHL API client with cache (`Api`), URL builders, and `parse_game()`, which the dashboard builder imports. Also a CLI that makes static PNG graphics (game card and trend), an earlier deliverable the owner may still use in posts. |
| `tools/make_sample_season.py` | Writes a fake full season into a cache folder, so everything can be built offline. Used by the tests. |
| `tools/check_game.py` | Compares one game on a built page with the NHL's official Event Summary / Game Summary HTML reports (`nhl.com/scores/htmlreports/{season}/ES0xxxxx.HTM`, uppercase `.HTM`). |
| `assets/`, `tools/make_logo.py` | The owner's brand is **Stick Language**; this page is its stats offshoot (Oct 2026). `assets/stick-language-source.png` is the logo he supplied (white and green on black). `make_logo.py` turns it into `logo-dark.png` (white letters) and `logo-light.png` (dark letters), both transparent, plus `favicon.png` and `touch-icon.png` (the logo's hockey stick and puck on black, because the full wordmark is unreadable at icon size). The builder bakes the logos and favicon into the page (`__DASHBOARD_LOGO_LIGHT__`, `__DASHBOARD_LOGO_DARK__`, `__DASHBOARD_FAVICON__`) and copies the touch icon next to it. Where the brand shows: the header (logo, a small "STATS" pill, then "Stars 2025-26" and the record; CSS tokens `--logo-l` / `--logo-d` pick the logo for the theme), the browser tab and home-screen icons, and the footer of every share image (logo, pill, site host). On share images the logo is painted onto the canvas in `cardPng()` rather than nested in the SVG, since Safari can skip nested pictures on the first draw. The owner found the first pill (14px) too big; it's 11px. |
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
- `api.nhle.com/stats/rest/en/skater/{summaryshooting|timeonice}?isAggregate=false&isGame=true&start=0&limit=-1&cayenneExp=teamId=25 and seasonId=... and gameTypeId=2`: one row per skater per game for the whole season in one request (`limit=-1` = all rows; `stars_viz.load_skater_reports()` pages through if that ever stops working). `summaryshooting`: `satFor`, `satAgainst` = shot attempts for/against at 5-on-5 while he was on the ice (also `usatFor/Against`, `satRelative`). `timeonice`: `evTimeOnIce`, `ppTimeOnIce`, `shTimeOnIce` (seconds). The same URL with `isGame=false` gives season totals; the page uses `percentages` that way for `satRelative`, `zoneStartPct5v5`, `shootingPct5v5`, `skaterSavePct5v5`. Refreshed every 30 minutes like other unfinished data (not cached for good). Other reports that exist but aren't used: `penalties`, `faceoffwins`, `powerplay`, `penaltykill`, `scoringRates`, `goalsForAgainst`, `realtime`, `shottype`, `goalie/savesByStrength`; `.../shiftcharts?cayenneExp=gameId=...` has every shift. `api-web.nhle.com/v1/edge/skater-detail/{id}/{season}/2` has tracking data (speed, distance, zone time), season-level only. Nobody at the NHL publishes expected goals.
- Play-by-play `penalty` plays carry `committedByPlayerId` and `drawnByPlayerId` (bench minors have neither a committer; misconducts have no drawer), and `faceoff` plays carry `winningPlayerId` / `losingPlayerId`. `parse_game()` counts both per player. Boxscore goalies have `evenStrengthShotsAgainst` / `powerPlayShotsAgainst` as "saves/shots" strings.
- `api.nhle.com/stats/rest/en/team/{summary|powerplay|penaltykill|percentages}?isAggregate=false&isGame=true&cayenneExp=teamId=25 and seasonId=... and gameTypeId=2`: per-game team stats (`satPct` = 5v5 shot share, `shootingPlusSavePct5v5` = PDO). Fetched by `stars_viz.load_trend()`. The current page no longer shows them, but the game list comes through that function.

Caching: finished games are cached forever in `.nhl_cache/`; everything else refreshes after 30 minutes. There is a 0.25 s pause between network calls.

## Compact data shape baked into the page (array indexes matter)

`build_dashboard.py` writes `{meta, players, games}`. Per game:

- `sk` (Dallas skaters): `[pid, goals, assists, plusMinus, pim, sog, hits, blocks, toiSeconds, ppGoals, giveaways, takeaways, faceoffPct, shifts, penaltiesTaken, penaltiesDrawn, faceoffsWon, faceoffsLost, onIceAttemptsFor, onIceAttemptsAgainst, evSeconds, ppSeconds, shSeconds]`. The last five (indexes 18-22) come from the stats reports and are null until the NHL posts the game there. The page works FO% out from won/lost (index 12 is the boxscore's figure, kept for `check_game.py`).
- `gk` (Dallas goalies who played): `[pid, shotsAgainst, saves, goalsAgainst, toiSeconds, starter(0/1), decision "W"/"L"/"OTL"/"", evSaves, evShots, pkSaves, pkShots]` (pk = opponent on the power play)
- `players[pid].oi` (skaters, season to date): `{rel, zs, sh, sv}` = shot share relative to when he's off the ice, offensive-zone start share, on-ice shooting % and save % at 5-on-5
- `shots` (both teams, all attempts): `[gameMinute, ours(0/1), kind(0 goal, 1 on goal, 2 missed, 3 blocked), x, y, shooterPid (ours only, else 0), strength "EV"/"PP"/"SH"/"EN"/"EA"]`
- `goals`: `[gameMinute, ours, period, clock, scorerPid (ours only), scorerName, [assistNames], strength, [assistPids in order: primary first]]`
- also `st` (team stat pairs [DAL, OPP]), `oppGk`, `adv`, `takeaway`, `res` ("W"/"L"/"OTL"), `sfx` ("OT"/"SO"/"")

## The page (what the owner approved; keep it)

The owner rejected "stat dumps" and asked for **player rankings only**. He removed the Season tab, the Players tab, the team view and the scoring summary. Don't bring them back unless he asks.

Top to bottom:
1. Game picker strip (every game, W/L color-coded), defaulting to the latest game.
2. A headline written by rules from the data (e.g. "Johnston's big night lifts the Stars past the Lightning, 6-3", from `gameStory()`), plus the score line.
3. **Quadrant chart:** x = offense score, y = two-way score, both 0 to 100 and split at 50 (see "Player score"). Corners: Did it all / Quietly solid / Offense only / Off night. Forwards are green circles, defensemen blue squares. The axes fit each game's dots (rounded out to the nearest 10) so the dots spread out; zoom buttons zoom toward the dots. Tap a dot to open that player's card. Everything the chart plots comes from the `QUAD` config above `quadChart()`; the share card's `cardQuad()` reads the same config. "Compared with his own average" is no longer on the chart: it lives in the tables (the % beside the score, the small numbers under each stat) and in the player card, which shows his offense and two-way scores against his averages.
   Right under the chart card is a collapsed **"See the shot chart"** section (`details.more#shotmap`, added Oct 2026 at the owner's request): the whole game's goals, shots on goal and misses for both teams on one rink, Dallas shooting right. It starts closed on every page load; once a reader opens it, it stays open while he flips between games (`state.shots`). It's drawn on open, because the dot size depends on the rink's width.
4. **Forwards ranked by player score**, then **defensemen**. Each row shows the score, the change from his average, then G, A, P, SOG, ATT (attempts), CF% (Dallas's share of 5-on-5 shot attempts while he was on the ice), +/-, PEN (penalties drawn minus taken), HIT, BLK, TK, GV, TOI and FO% (centers). Under every stat is the change from that player's season average per game: green is better, red is worse, and it's shaded when the gap is at least 1 standard deviation. Under 0.35 SD it's gray. For giveaways, lower counts as better.
5. Goalies: save % and shots against compared with his season average, plus even-strength save % and penalty-kill saves/shots.
   The Forwards, Defensemen and In goal cards have a label and the table only, no headline: the owner removed those (Sep 2026) as redundant with the stats right below. The Forwards card keeps a two-sentence note he wrote himself; don't lengthen it.
6. **Share images** (added Sep 2026 at the owner's request; he wants readers to have them too, no auto-posting). A "Share image" button beside the score line opens a dialog with **Game card** (headline, static quadrant, top 3, biggest drop, goalie) and **Rankings** (every skater's score as bars); the button in a player card offers **This game** and **His season** (skater and goalie variants). Light/Dark toggle (remembered in localStorage). Cards are 1200x675 SVG strings built in the `share cards` section of the template, fonts fetched from Google Fonts and embedded as data URIs (falls back to system fonts offline), drawn to a 2x canvas -> PNG. Actions: Web Share with files (phones), Copy image (ClipboardItem), Download. Headlines come from the same `*Story()` functions as the page. No NHL logos; the footer shows the Stick Language logo, a STATS pill, the site host from `meta.siteUrl`, and "Data: NHL.com".
7. Player card (a pop-up, not a tab): "His season" (score by game, production, **with him on the ice**: 10-game on-ice shot share plus three plain-language lines for relative share, zone starts and luck (PDO); points by game, ice time, shot map) or "One game" (compared with his normal, **with him on the ice**: attempts for/against bar, ice time by situation, penalties and faceoffs; a timeline of when he showed up, his shots). Advanced stats are always explained in plain words where they appear ("often called Corsi"), never left as bare abbreviations.

## Player score (the core idea; keep the method, weights can be tuned)

In `dashboard_template.html`, section `/* player score */`:
1. For each position group (forwards = C/L/R, defensemen = D), compute the mean and SD of every stat across **all Dallas player-games of that group this season**.
2. Game composite = the sum of weight × z-score.
3. Rescale the composite within the group: `score = 50 + 15 * (comp - mean) / sd`, clamped to 0-100. **This makes forwards and defensemen land on the same scale by construction** (on the sample season, both average 50 and the 10th-90th percentile is about 34-69).
4. `dScore` is the score minus the player's season-average score (all games in the dataset so far); the tables and cards show it.
5. The chart's two halves are made the same way from subsets of the weights (`AXES`): **offense** = goals, both assists, slot attempts, shots on goal (F) or shot attempts (D); **two-way** = on-ice shot attempts, +/-, takeaways minus giveaways, penalties, hits, blocks (D), faceoffs (F). Ice time is in the full score only. Each half is rescaled to mean 50, SD 15 within its position group, so forwards and defensemen share both axes. Offense is lopsided: a game with no points or shots sits at about 36 and the median is 44.

Weights (changed Sep 30, 2026 to add on-ice shot attempts, net penalties and faceoffs; PIM was dropped in favor of penalties drawn minus taken):
- **Forwards:** goals .22, primary assists .13, slot attempts .10, on-ice shot attempts for minus against (5-on-5) .10, shots on goal .08, TOI .07, +/- .06, secondary assists .06, takeaways minus giveaways .06, penalties drawn minus taken .05, hits .04, faceoffs won minus lost .03
- **Defensemen:** on-ice shot attempts for minus against .14, TOI .12, goals .11, primary assists .11, +/- .10, blocks .10, takeaways minus giveaways .09, shot attempts .08, secondary assists .05, penalties drawn minus taken .05, hits .05

On 2025-26 the new score correlates 0.96 with the old one; the average player-game moved 3.4 points, 44 of 1,476 moved 10 or more, and the top forward changed in 10 of 82 games. A stat that is missing for a game (on-ice numbers not posted yet) counts as average, so scores shift slightly when it arrives.

The "slot" is x 69-89, |y| ≤ 22 in NHL coordinates (between the faceoff dots, in front of the net). Primary and secondary assists come from the goal's assist order in play-by-play.

Known limits: no expected goals (the NHL doesn't publish it; slot attempts stand in for shot quality). On-ice shot attempts are raw, not adjusted for teammates, opponents or zone starts. The scale is relative to *this team's* season, not the league. The z-scores use the whole dataset, so early-season scores shift as games are added. That's acceptable, but be aware of it.

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

Season changeover (checked Sep 29, 2026):
- `club-schedule-season/DAL/now` is a 307 redirect to the current season (requests follows it). It already reports 20262027; the builder falls back to `previousSeason` until the first *regular-season* game is final (preseason games are ignored). 2026-27 opens Fri Oct 2 vs STL and has **84 games**, not 82 (the static trend PNG in `stars_viz.py` still uses an 82-game points pace; the page doesn't show pace).
- The page shows one season at a time: when 2026-27 starts, 2025-26 disappears from the page (its data stays in `.nhl_cache/`).
- Game 1 of a season: every player's score equals his season average, so the quadrant's y values are all 0 and every table delta reads "even". Deltas become meaningful from game 2 and settle after ~10 games. The owner hasn't asked to change this.
- Games are cached for good only at gameState `OFF` (official), not `FINAL` (just ended), so post-game stat corrections are picked up.

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

Share-image notes (Sep 2026):
- **Design rule: cards are judged at thumbnail size** (~350px wide, i.e. ~0.3x, how a text message or feed shows them). The owner rejected the first, detailed version as unreadable there. Nothing meant to be read under ~24px at 1200x675; key numbers 60-150px; one idea per card; name only the players the story is about. Check changes by shrinking the PNGs to 350px, not just at full size.
- Tested in Chromium and WebKit (Safari's engine) via Playwright; `test_share_cards_in_safari_engine` runs in CI. A real iPhone hasn't been tested. Web Share can't be exercised headlessly, so the "Share…" button only appears where `navigator.canShare({files})` is true.
- Tests block the network but must allow `blob:`/`data:` URLs (the `offline` route helper), or WebKit blocks the preview image.
- The preview sets `aria-busy` while drawing; wait for `.share-prev[aria-busy=false]` before reading it.
