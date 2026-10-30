# stars-viz

Dallas Stars data tools built on the NHL's free public API:

1. **Player rankings** (`build_dashboard.py`): one web page built around a **player score** for every skater in every game.
   - Pick any game from the strip at the top. The rest of the schedule follows the games already played, with start times in the reader's own time zone (and the TV channel when you hover).
   - A quadrant chart plots each player's offense against how much he tilted the ice (Corsi, plus-minus, takeaways, hits, blocks, penalties and faceoffs): did it all, strong support, strong offense, room for more.
   - A **team score** grades the whole team's game on the same scale, with a breakdown of where it came from and a chart of every game this season (see below).
   - Forwards and defensemen are ranked by score, with every stat color-coded against that player's season average. Goalies follow. A **This Game / Season Stats** switch flips all three tables to season totals, and clicking any column heading sorts by it (best first, then worst first on a second click).
   - Tap any player for his card: score trend, production, role and shot profile, or switch to **One game** for his night against his normal.
   - **Share image** buttons (beside the game score, and in every player card) make a 1200×675 picture sized for X, Reddit and Substack: a game card (headline, quadrant, top performers), a rankings card (every skater's score), a player's game, or a player's season, in light or dark. On a phone, **Share…** opens the normal share menu; on a computer, **Copy image** pastes straight into an X post or a Substack draft, or use **Download**.
   - **The player score**: each stat is compared with how Stars players at the same position usually do in a game, weighted, and scaled like a school grade: 70 is a typical game, the 80s are a B, the 90s an A. It mixes what a player did himself (goals, assists, shots, hits, blocks, penalties drawn and taken, faceoffs) with what happened while he was on the ice (plus-minus and on-ice shot attempts, often called Corsi). Forwards weigh goals, primary assists, slot shots and on-ice shot attempts most heavily. Defensemen weigh on-ice shot attempts, ice time, goals, primary assists, plus-minus and blocks most heavily. Both land on the same scale. The weights are at the top of the `player score` section in `dashboard_template.html` if you want to tune them.
   - **The team score**: half the scoreboard (goal difference, not counting empty-net goals or the shootout) and half how the team played: **expected goals** (every unblocked shot rated by how often a shot like it goes in, from its distance, angle, type, and whether it was a rebound, off the rush or on the power play) and **5-on-5 shot attempts, adjusted for the score** (teams that are ahead sit back, teams that are behind press). It's measured against the whole NHL, not just the Stars: 70 is an average NHL game. The weights come from every game of the 2025-26 season, all 32 teams, so a game's team score never changes once it's final. On 2025-26, a team's average team score over half its games predicted its goal difference in the other half (r 0.68) better than its goal difference (0.56), wins (0.47) or shot attempts (0.59) did, and a little better than expected goals alone (0.67). Hits, faceoffs, takeaways, giveaways and penalties were tested and left out, because across the league they said nothing about which teams were good (teams that out-hit their opponents actually tend to be worse: you hit when you don't have the puck).
2. **Static graphics** (`stars_viz.py`): a game card PNG and a trend PNG for dropping straight into a Substack post, plus a notes file with the key facts.

## It updates itself

The page is published with GitHub Pages and rebuilt by GitHub Actions (`.github/workflows/publish.yml`):

- **right after each game**, as soon as the NHL makes the game's stats official: a quick check (**Actions → Check for a finished game**, started every 5 minutes by cron-job.org) starts the rebuild the moment they're in, and the post-game email follows right after;
- every night at about 3:30 am Central, as a backup;
- whenever you press **Run workflow** on the repo's **Actions** tab;
- whenever new code is pushed.

A finished game never goes up early. The page waits until the NHL has made the game official and posted every skater's on-ice numbers (the last stats to arrive). Until then the game sits in the schedule strip as **Stats soon**. If the NHL still hasn't finished 18 hours after puck drop, the game goes up anyway, and the post-game email says what was missing.

Each run tests the code, downloads any new games, builds the page, takes a fresh share-preview image (the picture Substack and X show when you post the link), checks the finished page in a real browser, and only then publishes it. **If any step fails, nothing is published: the last good page stays up and GitHub emails you.** Open the failed run on the Actions tab to see which step broke.

To change the footer credit, go to the repo's **Settings → Secrets and variables → Actions → Variables** and edit `CREDIT` (for example `yourname.substack.com`). It takes effect on the next run.

The season switches over on its own: until the Stars play a regular-season game, the page shows last season.

## Being found on Google

Everything a search engine needs is built with the page, every run, and none of it changes how the page looks:

- The browser-tab title and the grey line under it in a Google result: **"Dallas Stars Player Rankings 2026-27 | Stick Language Stats"** and a sentence that ends with the latest score, so the result reads as current.
- `robots.txt` and `sitemap.xml` beside the page, which is the first thing a crawler looks for.
- A hidden description of the page in the code (schema.org): who publishes it, that it's about the Dallas Stars of the NHL, and which game it's showing. It's what lets Google connect the site to the team rather than to the word "stars".
- The latest game written into the page as a plain table (the result, every skater's line, the goalies, and every game played so far). The page replaces it with the real thing the instant it loads, so no reader ever sees it — but search engines that don't run JavaScript, and most of the AI crawlers, read that instead of an empty page.
- A heading that says what the page is, read by search engines and screen readers but not shown on screen.
- **A page of its own for every game**, at addresses like `sticklanguagestats.com/game/2026-10-20-stars-vs-bruins/`. Each one opens on that game and carries its own title and description ("Dallas Stars vs Bruins, Oct 20, 2026: player ratings"), so someone searching for one night's game can land on it instead of on the latest one. They're all in the sitemap, and the date chips at the top of the page are now links to them: click as before and the page switches instantly, and the address bar follows along, so the link in it is always the game you're looking at — copy it straight into a post, and the Back button walks you back through the games you looked at. On a game's page there's a small "All 2026-27 games" link back to the top.

**What you have to do once** (10 minutes, and it's the part that matters most):

1. Open [Google Search Console](https://search.google.com/search-console) and add **sticklanguagestats.com** as a *Domain* property. Google gives you a TXT record; add it at Namecheap (Advanced DNS → Add New Record → TXT, host `@`), then press Verify.
   If you'd rather not touch DNS, choose *URL prefix* with `https://sticklanguagestats.com/` instead, pick the **HTML tag** method, copy the `content="..."` code out of it, and put that code in the repo variable `GOOGLE_VERIFY` (Settings → Secrets and variables → Actions → Variables). Run the workflow once and press Verify.
2. In Search Console, go to **Sitemaps** and submit `sitemap.xml`. Then **URL Inspection** → paste the site address → **Request indexing**.
3. [Bing Webmaster Tools](https://www.bing.com/webmasters) can import the whole thing from Search Console in two clicks. Worth doing: ChatGPT's search is built on Bing.

After that, Search Console tells you what people typed to find you — which is the number a portfolio wants.

**What helps most from here** isn't code: links. Every Substack post that links to the page, and anywhere the link gets shared (r/DallasStars, X, a reply on a Stars thread), is a vote Google counts. The site is new, so expect weeks, not days.

## Bugs / Requests form and "Buy me a beer"

A small **Bugs / Requests** button sits in the bottom-right corner of the page. It opens a little form; each message is emailed to you by [Web3Forms](https://web3forms.com) (free up to 250 messages a month), along with the game the reader was looking at and their screen size and browser. The key that sends it is the repo **variable** `FEEDBACK_KEY` (Settings → Secrets and variables → Actions → Variables). The key is safe to have in the page: all it can do is send mail to you. Without it, the button doesn't show.

Your Buy Me a Coffee page (https://buymeacoffee.com/essjayjay, `SUPPORT_URL` in `build_dashboard.py`) is linked as "Buy me a beer" in two places: the thank-you after someone sends the form, and a button centered at the end of the page.

## The post-game email

After each game, the workflow also emails you a draft of that game's **No Filter** post, in the order it runs:

1. **Subject line ideas**: five options for the post's email subject.
2. **The summary**: two or three sentences on the game at a high level.
3. **Story of the Stats**: the line "Let's count down the 10 most telling stats from the game.", then the 10 stats that best tell the game's story, from #10 to #1, each a one-sentence heading with two or three sentences under it.
4. **No Filter**: the line "Here are the "No Filter" questions I would have liked to see at the postgame presser.", then the questions a reporter would want answered if they could ask anything, each followed by a paragraph on why it needs asking.
5. **Some stats that stood out**: every interesting and noteworthy stat from the game, one sentence each (it may repeat stats from the countdown),, then "Check out the player grades, performance charts, and full stats for each skater at the Stick Language Stats page." with a link to the site.

The three fixed lines are added exactly as written; Claude writes the rest.

Claude writes it from the page's own numbers and a few web searches for things like injuries, what the coach said, and how fans and local media reacted. The site's player scores are left out of the email, since they shift as more games come in. It sends once per game, right after the site update that brings in the game's final stats: when the NHL has made the game official and the on-ice numbers (the last stats to arrive) are on the page. That can be late at night or with the 3:30 am run. If the NHL still hasn't posted everything 18 hours after puck drop, it sends anyway and says what was missing. Each email ends with a note on that and on how much work Claude did.

(Reading the r/DallasStars post-game thread was tried and dropped: Reddit now gives its API only to moderators and blocks scripts that read the site without it.)

To switch it on, add these on the repo's **Settings → Secrets and variables → Actions → Secrets** page (**New repository secret**):

| Secret | What it is |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | Lets the workflow use Claude on **your Claude subscription** (no API key, no extra bill; each game uses a little of your plan's usage). To make it, open the Terminal app and run `claude setup-token`, sign in when the browser opens, and paste the long token it prints (it starts with `sk-ant-oat`) in as this secret. If the token ever expires, the email step fails, GitHub emails you, and you make a new one the same way. |
| `SMTP_USER` | The Gmail address that sends the email. |
| `SMTP_PASSWORD` | A Google **app password** for that address (myaccount.google.com/apppasswords; needs 2-Step Verification). Not your normal password. |
| `EMAIL_TO` | Optional: where to send it, if not to `SMTP_USER`. |

Until `CLAUDE_CODE_OAUTH_TOKEN`, `SMTP_USER` and `SMTP_PASSWORD` are all set, the email step just skips.

To get an email right now (to test it, or to re-send one), open **Actions → Publish player rankings → Run workflow**, tick **Email the latest game's post-game notes now**, and run it. If an email ever goes missing, a copy is on that run's page under **Artifacts** (`postgame-email`).

## The daily team score picks

A separate workflow (**Actions → Team score picks**) runs the betting system every day of the season: in every game, pick the team that had the higher team score in its previous game.

- **Every morning after 6 am Central** it grades last night's picks and finds the rule (a range of lines, a range of differentials, home/away/either) that would have made the most units this season so far. That rule decides the day's picks.
- **Two hours before the day's first game** it picks every game at DraftKings' line right then and emails you today's picks that fit the rule, the rule, and every game of the day, with the spreadsheet attached. Units are graded on the line in that email.
- The spreadsheet's **Dynamic Bet Results** tab is your real record: only the picks that were emailed under each day's rule, at the emailed line.
- Its data lives on the repo's `picks-data` branch, never on the site. The email uses the same `SMTP_USER` / `SMTP_PASSWORD` secrets as the post-game email.

To re-send today's email, open **Actions → Team score picks → Run workflow**, tick **Pick today's games and send the email now**, and run it.

### The timer (cron-job.org), one-time setup

GitHub's own timer runs hours late on this repo, so a free cron-job.org account starts the workflow every 15 minutes instead. Each run only does what's due, so the extra runs are harmless.

1. **Make a GitHub token** at github.com/settings/personal-access-tokens/new: name it "cron-job picks", set **Resource owner** to `starsviz`, pick an expiration (up to a year), choose **Only select repositories** → `starsviz.github.io`, and under **Repository permissions** set **Actions** to **Read and write**. Generate it and copy it. (If GitHub says the token is pending approval, approve it at github.com/organizations/starsviz/settings/personal-access-token-requests.)
2. **Make the job** at cron-job.org (sign up, then **Create cronjob**):
   - URL: `https://api.github.com/repos/starsviz/starsviz.github.io/actions/workflows/picks.yml/dispatches`
   - Schedule: every 15 minutes
   - Under **Advanced**: request method **POST**; headers `Authorization: Bearer YOUR_TOKEN`, `Accept: application/vnd.github+json` and `X-GitHub-Api-Version: 2022-11-28`; request body `{"ref":"main"}`
3. Save it and use **Test run**. A response of **204** means it worked, and a new run shows up under **Actions → Team score picks**.

When the token expires, cron-job.org's runs start failing (it emails you), and the workflow falls back to GitHub's hourly timer until you make a new token and paste it into the job.

### The post-game timer (cron-job.org)

A second cron-job.org job, set up like the picks one and using the same token, calls `https://api.github.com/repos/starsviz/starsviz.github.io/actions/workflows/site-check.yml/dispatches` every 5 minutes with the same headers and body.

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
- The team score's constants (the expected-goals model, the score adjustment and the weights) come from `tools/fit_team_score.py`, run on a full season of every team's games. It's worth rerunning once a season ends: `python tools/fit_team_score.py --season 20262027` (the first run downloads every game, about an hour, into `.league_cache/`), then paste what it prints into `stars_viz.py` and `dashboard_template.html`. Scores from before the change shift a little when you do.
- The API is unofficial and undocumented. If the NHL changes a field, a script may break; the nightly run will then fail and email you instead of publishing a broken page.
