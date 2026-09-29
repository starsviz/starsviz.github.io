Paste this into Claude Code as your first message, from inside the stars-viz folder:

---

Read CLAUDE.md and README.md first. This project is a working Dallas Stars player-rankings page built from the NHL's public API, but it has never been run against the live API. Get it ready for the real world, following the "Getting it ready for the real world" list in CLAUDE.md in order:

1. Run the build against the live API for the 2025-26 season and fix anything that breaks.
2. Check 3 games against NHL.com (regulation, overtime, shootout) and show me what matched and what didn't.
3. Add tests (sample-season fixture + a headless browser smoke test).
4. Clean up the HTML head, add share previews (Open Graph) and a favicon.
5. Remove the dead code listed in CLAUDE.md.
6. Set up a GitHub repo with a GitHub Actions workflow that rebuilds nightly and publishes to GitHub Pages, and walk me through anything I need to click.

Don't change what the page shows or how the player score works without asking me first. I'm not a developer, so explain each step in plain English and tell me when you need me to do something.
