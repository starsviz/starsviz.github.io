// Run inside the built page (tools/postgame_email.py does this with Playwright) to pull out everything the
// post-game email needs about one game, using the page's own numbers: the player score, season averages,
// streaks and the rule-based headline all come from dashboard_template.html, so the email can't disagree with the site.
(gameId) => {
  const g = gameId ? byId.get(+gameId) : G[G.length - 1];
  if (!g) return null;
  const idx = G.indexOf(g), upto = G.slice(0, idx + 1), prev = G[idx - 1];
  const r1 = v => v == null || isNaN(v) ? null : Math.round(v * 10) / 10;
  const p1 = v => v == null || isNaN(v) ? null : Math.round(v * 1000) / 10;  // share -> percent
  const rec = arr => ({ w: arr.filter(x => x.res === "W").length, l: arr.filter(x => x.res === "L").length, otl: arr.filter(x => x.res === "OTL").length });
  const recStr = r => `${r.w}-${r.l}-${r.otl}`;
  const pair = ([us, them]) => ({ DAL: us, [g.opp]: them });
  // Dallas's share of 5-on-5 shot attempts, from play-by-play like the page's headline (the NHL's report can differ a little)
  const share5 = x => { const [u, t] = x.st.att5; return u + t ? p1(u / (u + t)) : null; };

  // shots on goal and attempts by period, and attempts from the slot (between the faceoff dots, in front of the net)
  const periods = {};
  g.shots.forEach(s => {
    const p = per(periodOf(s[0])), side = s[1] ? "DAL" : g.opp;
    const o = periods[p] ||= { DAL: { sog: 0, att: 0 }, [g.opp]: { sog: 0, att: 0 } };
    o[side].att++; if (s[2] <= 1) o[side].sog++;
  });
  const slot = { DAL: 0, [g.opp]: 0 };
  g.shots.forEach(s => { if (s[2] !== 3 && s[3] != null && inSlot(s[3], s[4], !!s[1])) slot[s[1] ? "DAL" : g.opp]++; });

  const rows = g.sk.map(r => {
    const s = skaters[r[0]], l = s.log.find(x => x.g === g);
    return { s, l };
  }).sort((a, b) => b.l.score - a.l.score);
  const skaterOut = rows.map(({ s, l }, i) => {
    const pl = P[s.pid] || {};
    const sorted = s.log.slice().sort((a, b) => b.score - a.score);
    const best = sorted[0];
    return {
      name: pname(s.pid), number: pl.num, pos: POS[pl.pos] || pl.pos, age: pl.age,
      teamRankTonight: i + 1,
      playerScore: r1(l.score), seasonAvgScore: r1(s.avgScore), vsHisAverage: r1(l.dScore),
      offenseScore: r1(l.off), tiltingTheIceScore: r1(l.two),
      thisScoreRanksAmongHisGames: `${sorted.indexOf(l) + 1} of ${s.gp}`,
      seasonBestScore: best ? { score: r1(best.score), game: best.g.n, opp: best.g.opp } : null,
      tonight: {
        goals: l.gl, primaryAssists: l.a1, secondaryAssists: l.a2, points: l.p, ppGoals: l.ppg,
        shotsOnGoal: l.sog, shotAttempts: l.att, slotAttempts: l.slot, plusMinus: l.pm,
        onIce5v5AttemptsFor: l.satF, onIce5v5AttemptsAgainst: l.satA, onIce5v5AttemptShare: p1(l.cf),
        penaltiesTaken: l.penT, penaltiesDrawn: l.penD, pim: l.pim, hits: l.hits, blocks: l.blk,
        takeaways: l.tk, giveaways: l.gv, toi: toi(l.toi), evToi: l.evT == null ? null : toi(l.evT),
        ppToi: l.ppT == null ? null : toi(l.ppT), shToi: l.shT == null ? null : toi(l.shT),
        faceoffs: l.foW + l.foL ? `${l.foW}-${l.foL}` : null, shifts: l.shifts,
      },
      seasonPerGameAverage: {
        goals: r1(s.avg.gl), assists: r1(s.avg.a), points: r1(s.avg.p), shotsOnGoal: r1(s.avg.sog), shotAttempts: r1(s.avg.att),
        onIce5v5AttemptShare: p1(s.avg.cf), plusMinus: r1(s.avg.pm), hits: r1(s.avg.hits), blocks: r1(s.avg.blk),
        takeaways: r1(s.avg.tk), giveaways: r1(s.avg.gv), toi: toi(s.toigp), faceoffPct: p1(s.avg.fo),
      },
      seasonTotals: { gp: s.gp, goals: s.gl, assists: s.a, points: s.p, plusMinus: s.pm, shotsOnGoal: s.sog,
        shootingPct: p1(s.shp), onIce5v5AttemptShare: p1(s.cf) },
      seasonOnIce5v5: pl.oi ? { attemptSharePointsBetterThanTeamWithoutHim: p1(pl.oi.rel), offensiveZoneStartPct: p1(pl.oi.zs),
        onIceShootingPct: p1(pl.oi.sh), onIceSavePct: p1(pl.oi.sv) } : null,
      form: { label: s.trend.label, why: s.trend.why, pointStreak: s.trend.streak, gamesWithoutGoal: s.trend.drought,
        pointsLast10: s.trend.p10, toiLast10: toi(s.trend.toi10) },
      last10: s.log.filter(x => x.g.n <= g.n).slice(-10).map(x => ({ game: x.g.n, opp: x.g.opp, res: x.g.res,
        score: r1(x.score), g: x.gl, a: x.a, sog: x.sog, pm: x.pm, toi: toi(x.toi) })),
    };
  });

  const goalieOut = g.gk.map(r => {
    const s = goalies[r[0]];
    return {
      name: pname(r[0]), started: !!r[5], decision: r[6] || null, toi: toi(r[4]),
      shotsAgainst: r[1], saves: r[2], goalsAgainst: r[3], savePct: r[1] ? r1(r[2] / r[1] * 100) / 100 : null,
      evenStrength: r[8] != null ? `${r[7]}/${r[8]}` : null, penaltyKill: r[10] != null ? `${r[9]}/${r[10]}` : null,
      season: { gp: s.gp, record: `${s.w}-${s.l}-${s.otl}`, savePct: s.svp && +s.svp.toFixed(3), gaa: s.gaa && +s.gaa.toFixed(2),
        shutouts: s.so, evSavePct: s.evSvp && +s.evSvp.toFixed(3), pkSavePct: s.pkSvp && +s.pkSvp.toFixed(3), form: s.trend.label + (s.trend.why ? `: ${s.trend.why}` : "") },
    };
  });

  const inLineup = new Set(g.sk.map(r => r[0]).concat(g.gk.map(r => r[0])));
  const prevLineup = prev ? new Set(prev.sk.map(r => r[0]).concat(prev.gk.map(r => r[0]))) : new Set();
  const regulars = Object.values(skaters).filter(s => s.log.filter(l => l.g.n < g.n).length >= Math.min(5, Math.max(1, g.n - 1)));
  const story = gameStory(g), team = rec(upto);
  const sumOf = (arr, k) => sum(arr.map(x => x.adv[k]).filter(v => v != null && !isNaN(v)));

  return {
    site: M.siteUrl || null,  // where the page is published (the email links to it)
    game: {
      id: g.id, number: g.n, date: g.date, start: g.start || null, opponent: g.oppName, opponentAbbrev: g.opp,
      // the NHL's last numbers to arrive: the game made official, and on-ice shot attempts and ice time by situation
      official: !!g.official, onIceStatsIn: g.sk.every(r => r[18] != null && r[20] != null),
      homeOrAway: g.home ? "home" : "away", venue: g.venue, result: g.res, decidedIn: g.sfx || "regulation",
      score: { DAL: g.gf, [g.opp]: g.ga }, recordAfter: recStr(team), points: 2 * team.w + team.otl,
      siteHeadline: story.head, siteKicker: story.kicker, siteSummary: story.dek,
    },
    goals: g.goals.map(x => ({ period: per(x[2]), clock: x[3], team: x[1] ? "DAL" : g.opp, scorer: x[1] && x[4] ? pname(x[4]) : x[5],
      assists: x[6], strength: x[7] })),
    teamStats: {
      shotsOnGoal: pair(g.st.sog), shotAttempts: pair(g.st.att), attempts5v5: pair(g.st.att5), slotAttempts: slot,
      faceoffsWon: pair(g.st.fo), hits: pair(g.st.hits), blockedShots: pair(g.st.blk), takeaways: pair(g.st.tk),
      giveaways: pair(g.st.gv), pim: pair(g.st.pim), powerPlay: g.st.pp ? pair(g.st.pp) : null,
      dallas5v5AttemptShare: share5(g), dallasPDO: g.adv.pdo == null ? null : r1(g.adv.pdo * 100) / 100,
      byPeriod: periods,
    },
    opponentGoalies: g.oppGk.map(([name, sa, sv]) => ({ name, shotsAgainst: sa, saves: sv })),
    dallasSkatersRankedByPlayerScore: skaterOut,
    dallasGoalies: goalieOut,
    lineup: {
      outSinceLastGame: prev ? [...prevLineup].filter(p => !inLineup.has(p)).map(pname) : [],
      inSinceLastGame: prev ? [...inLineup].filter(p => !prevLineup.has(p)).map(pname) : [],
      regularsNotDressed: regulars.filter(s => !inLineup.has(s.pid)).map(s => `${pname(s.pid)} (${s.log.filter(l => l.g.n < g.n).length} GP)`),
    },
    season: {
      gamesPlayed: upto.length, record: recStr(team), points: 2 * team.w + team.otl,
      goalsFor: sum(upto.map(x => x.gf)), goalsAgainst: sum(upto.map(x => x.ga)),
      powerPlay: `${sumOf(upto, "ppg")}/${sumOf(upto, "ppo")}`, penaltyKill: `goals allowed ${sumOf(upto, "ppga")} on ${sumOf(upto, "tsh")} times shorthanded`,
      teamForm: g === G[N - 1] ? (() => { const t = teamTrend(); return `${t.kicker}: ${t.head}. ${t.dek}`.trim(); })() : null,
    },
    recentGames: upto.slice(-10).map(x => ({ game: x.n, date: x.date, opp: x.opp, home: x.home, result: x.res + (x.sfx ? ` (${x.sfx})` : ""),
      score: `${x.gf}-${x.ga}`, dallas5v5AttemptShare: share5(x),
      powerPlay: x.adv.ppo == null ? null : `${x.adv.ppg}/${x.adv.ppo}` })),
  };
}
