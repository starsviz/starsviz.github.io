# stars-viz

Dallas Stars data tools built on the NHL's free public API:

1. **Player rankings** (`build_dashboard.py`): one web page built around a **player score** for every skater in every game.
   - Pick any game from the strip at the top.
   - A quadrant chart plots each player's offense against his two-way play: did it all, strong two-way, strong offense, room for more.
   - Forwards and defensemen are ranked by score, with every stat color-coded against that player's season average. Goalies follow.
   - Tap any player for his card: score trend, production, role and shot profile, or switch to **One game** for his night against his normal.
   - **Share image** buttons (beside the game score, and in every player card) make a 1200×675 picture sized for X, Reddit and Substack: a game card (headline, quadrant, top performers), a rankings card (every skater's score), a player's game, or a player's season, in light or dark. On a phone, **Share…** opens the normal share menu; on a computer, **Copy image** pastes straight into an X post or a Substack draft, or use **Download**.
   - **The player score**: each stat is compared with how Stars players at the same position usually do in a game, weighted, and scaled like a school grade: 70 is a typical game, the 80s are a B, the 90s an A. It mixes what a player did himself (goals, assists, shots, hits, blocks, penalties drawn and taken, faceoffs) with what happened while he was on the ice (plus-minus and on-ice shot attempts, often called Corsi). Forwards weigh goals, primary assists, slot shots and on-ice shot attempts most heavily. Defensemen weigh on-ice shot attempts, ice time, goals, primary assists, plus-minus and blocks most heavily. Both land on the same scale. The weights are at the top of the `player score` section in `dashboard_template.html` if you want to tune them.
2. **Static graphics** (`stars_viz.py`): a game card PNG and a trend PNG for dropping straight into a Substack post, plus a notes file with the key facts.

## It updates itself

The page is published with GitHub Pages and rebuilt by GitHub Actions (`.github/workflows/publish.yml`):

- every night at about 3:30 am Central, and every 30 minutes from about 9 pm to 1 am Central, so a finished game appears the same night;
- whenever you press **Run workflow** on the repo's **Actions** tab;
- whenever new code is pushed.

Each run tests the code, downloads any new games, builds the page, takes a fresh share-preview image (the picture Substack and X show when you post the link), checks the finished page in a real browser, and only then publishes it. **If any step fails, nothing is published: the last good page stays up and GitHub emails you.** Open the failed run on the Actions tab to see which step broke.

To change the footer credit, go to the repo's **Settings → Secrets and variables → Actions → Variables** and edit `CREDIT` (for example `yourname.substack.com`). It takes effect on the next run.

The season switches over on its own: until the Stars play a regular-season game, the page shows last season.

## Running it on your own computer (optional)

You need Python 3.9 or newer.

```bash
pip install -r requirements.txt
python build_dashboard.py --credit "yourname.substack.com"
```

This writes `dashboard.html`. Double-click it to open it in your browser. The first run downloads every game of the season (a minute or two); after that, finished games come from the cache and only new ones are fetched. Use `--season 20252026` to pick a season yourself.

## Checking the numbers against NHL.com

```bash
python tools/check_game.py dashboard.html 2025021285
```

Compares one game on the page with the NHL's official game sheets (the Event Summary and Game Summary on nhl.com): the score, every Dallas skater's line, the goalies, each goal and its assists, and which way the shots are drawn. The game ID is in the nhl.com gamecenter URL. Use it if a number ever looks wrong.

## Tests

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium
python -m pytest
```

The tests build a fake 82-game season (`tools/make_sample_season.py`), check the data, and open the page in a headless browser at desktop and phone sizes. They run automatically before every publish.

## Static graphics

```bash
python stars_viz.py game                        # latest completed game
python stars_viz.py trend                       # season-to-date trends
python stars_viz.py both --credit "yourname.substack.com"
```

Images land in `output/`. Other options: `--id 2025020054` (a specific game; the ID is in the nhl.com gamecenter URL), `--season 20252026`, `--window 10`, `--playoff-line 96`, `--team COL`.

## Notes

- Shot maps are flipped so the Stars always shoot right and the opponent shoots left.
- Blocked shots count in shot attempts but are left off the rink, since the NHL records where the block happened, not where the shot came from.
- Shot attempts come from the NHL's play-by-play, which very occasionally credits a shot to a different player than the official game sheet does. Shots on goal come from the box score and always match NHL.com.
- Rolling lines start after game 5 so a 1-for-1 power play night doesn't show up as 100%.
- Player cards use sweater numbers instead of NHL headshots and logos, which belong to the NHL.
- Cached data lives in `.nhl_cache/`. Delete that folder to force a fresh download.
- The API is unofficial and undocumented. If the NHL changes a field, a script may break; the nightly run will then fail and email you instead of publishing a broken page.
