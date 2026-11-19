// Standings & outlook charts (Phase 2 of docs/PLAN_qpfltok_and_charts.md).
//
// Loaded after charts.js and tok.js, before app.js. The math is pure and
// takes plain inputs (tests/test_standings_charts.py runs it in node);
// standingsChartInput() at the bottom gathers those inputs from app.js's
// globals at runtime, for the Standings view and for QPFLTok alike.
//
// Charts and where they live:
//   playoff-odds-trend, power-rankings, projected-wins, schedule-ahead,
//   standings-replay  → Standings → Table (#standings-charts)
//   clinch-tracker    → Standings → Playoff Machine (#machine-charts)
//   finish-history    → League → Hall of Fame → Franchises

/* eslint-disable no-unused-vars */

// Standard normal CDF (Abramowitz-Stegun 7.1.26), for game win odds.
function chartNormalCdf(z) {
    const t = 1 / (1 + 0.3275911 * Math.abs(z) / Math.SQRT2);
    const poly = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429))));
    const erf = 1 - poly * Math.exp(-(z * z) / 2);
    return z >= 0 ? (1 + erf) / 2 : (1 - erf) / 2;
}

// ---- Power rankings ----
//
// weeks: [{ week, games: [{ a, b, sa, sb }] }], scored and in order.
// Each week, a team's power score blends what it has earned and how it is
// playing: 40% season all-play win % (vs every team, every week), 30% actual
// win %, 30% where its last three weeks' scoring ranks in the league (0-1).
const POWER_WEIGHTS = { allPlay: 0.4, record: 0.3, recent: 0.3 };
const POWER_RECENT_WEEKS = 3;

function computePowerRankings(weeks, teams) {
    const totals = {};
    teams.forEach(t => { totals[t] = { apWins: 0, apGames: 0, wins: 0, games: 0, pf: 0, scores: [] }; });
    const out = [];
    for (const week of weeks) {
        const scores = [];
        for (const g of week.games || []) {
            if (!totals[g.a] || !totals[g.b]) continue;
            scores.push([g.a, g.sa], [g.b, g.sb]);
            const result = g.sa > g.sb ? 1 : g.sa < g.sb ? 0 : 0.5;
            totals[g.a].wins += result;
            totals[g.b].wins += 1 - result;
            totals[g.a].games += 1;
            totals[g.b].games += 1;
        }
        if (!scores.length) continue;
        for (const [team, score] of scores) {
            const t = totals[team];
            for (const [other, otherScore] of scores) {
                if (other === team) continue;
                t.apWins += score > otherScore ? 1 : score === otherScore ? 0.5 : 0;
                t.apGames += 1;
            }
            t.pf += score;
            t.scores.push(score);
        }
        const recent = Object.fromEntries(teams.map(team => {
            const last = totals[team].scores.slice(-POWER_RECENT_WEEKS);
            return [team, last.length ? last.reduce((s, v) => s + v, 0) / last.length : 0];
        }));
        const recentOrder = [...teams].sort((x, y) => recent[x] - recent[y]);
        const recentPct = team => (teams.length > 1 ? recentOrder.indexOf(team) / (teams.length - 1) : 0.5);
        const score = Object.fromEntries(teams.map(team => {
            const t = totals[team];
            const allPlay = t.apGames ? t.apWins / t.apGames : 0.5;
            const record = t.games ? t.wins / t.games : 0.5;
            return [team, POWER_WEIGHTS.allPlay * allPlay + POWER_WEIGHTS.record * record + POWER_WEIGHTS.recent * recentPct(team)];
        }));
        const ranked = [...teams].sort((x, y) => score[y] - score[x] || totals[y].pf - totals[x].pf || x.localeCompare(y));
        out.push({
            week: week.week,
            ranks: Object.fromEntries(ranked.map((team, i) => [team, i + 1])),
            scores: score,
        });
    }
    return out;
}

// Rank series for bumpChart from [{ week, ranks: { team: rank } }].
function rankSeries(history, teams, label) {
    return teams.map(team => ({
        id: team,
        label: label(team),
        short: team,
        ranks: history.map(h => h.ranks[team] ?? null),
    }));
}

// The team that moved the most in the latest week, and by how much.
function biggestMove(history) {
    if (history.length < 2) return null;
    const [prev, last] = history.slice(-2);
    let best = null;
    for (const [team, rank] of Object.entries(last.ranks)) {
        const before = prev.ranks[team];
        if (before == null) continue;
        const move = before - rank;
        if (!best || Math.abs(move) > Math.abs(best.move) || (Math.abs(move) === Math.abs(best.move) && move > best.move)) {
            best = { team, move, rank };
        }
    }
    return best && best.move !== 0 ? best : null;
}

// ---- Projected wins ----
//
// model: { teamMean, meanUncertaintySD, leagueStd } (preparePlayoffSim's).
// A game's win chance: the chance one normal score beats the other, each
// with the league's game-to-game spread plus the uncertainty in the team's
// own level.
function gameWinProbability(model, a, b) {
    const ma = model.teamMean[a] ?? model.leagueMean;
    const mb = model.teamMean[b] ?? model.leagueMean;
    const sd = Math.sqrt(2 * model.leagueStd ** 2
        + (model.meanUncertaintySD?.[a] ?? 0) ** 2
        + (model.meanUncertaintySD?.[b] ?? 0) ** 2);
    return sd > 0 ? chartNormalCdf((ma - mb) / sd) : 0.5;
}

function expectedRemainingWins(remaining, model) {
    const out = {};
    for (const game of remaining) {
        const p = gameWinProbability(model, game.a, game.b);
        out[game.a] = (out[game.a] || 0) + p;
        out[game.b] = (out[game.b] || 0) + (1 - p);
    }
    return out;
}

// ---- Clinch tracker ----
//
// Rank points can grow at most 1.5 a week (a win plus a top-half finish).
// Each team's bar runs from what it has to the most it can reach; the
// status comes from computePlayoffStatus.
const MAX_RP_PER_WEEK = 1.5;

function clinchRows(standings, status, weeksLeft, slots) {
    const cutline = standings[slots - 1]?.rank_points ?? 0;
    return standings.map((team, i) => {
        const rp = team.rank_points || 0;
        const max = rp + MAX_RP_PER_WEEK * weeksLeft;
        const s = status[team.abbrev] || {};
        let label;
        if (s.clinched) label = 'Clinched';
        else if (s.eliminated) label = 'Out';
        else if (i < slots && rp > (standings[slots]?.rank_points ?? 0)) label = `In by ${chartNum(rp - standings[slots].rank_points)}`;
        else if (rp === cutline) label = 'Tied at the line';
        else label = `${chartNum(cutline - rp)} back`;
        return { id: team.abbrev, rp, max, label, clinched: Boolean(s.clinched), eliminated: Boolean(s.eliminated) };
    });
}

// ---- Finish history ----
//
// teamHof: hall_of_fame.team_hall_of_fame ({ code: { seasons: [{ season,
// seasonFinishes: [{ type, label }] }] } }). A finish is its place (1 for
// the champion); a Toilet Bowl badge with no place counts as last.
function finishPlace(finishes, leagueSize) {
    for (const f of finishes || []) {
        if (f.type === 'champion') return 1;
        const m = String(f.label || '').match(/^(\d+)(?:st|nd|rd|th) Place/);
        if (m) return Number(m[1]);
    }
    if ((finishes || []).some(f => f.type === 'toilet-bowl')) return leagueSize;
    return null;
}

function finishHistory(teamHof, label, leagueSize = 10) {
    const rows = [];
    const seasons = new Set();
    for (const [code, team] of Object.entries(teamHof || {})) {
        const places = {};
        for (const s of team.seasons || []) {
            const place = finishPlace(s.seasonFinishes, leagueSize);
            if (place == null) continue;
            places[s.season] = place;
            seasons.add(s.season);
        }
        const values = Object.values(places);
        if (!values.length) continue;
        rows.push({
            id: code,
            label: label(code),
            places,
            titles: values.filter(p => p === 1).length,
            avg: values.reduce((s, v) => s + v, 0) / values.length,
        });
    }
    rows.sort((a, b) => b.titles - a.titles || a.avg - b.avg || a.label.localeCompare(b.label));
    return { rows, seasons: [...seasons].sort((a, b) => a - b) };
}

function finishLevel(place, size) {
    if (place === 1) return 'lvl-4 is-title';
    const t = (place - 1) / Math.max(1, size - 1);
    return t <= 0.25 ? 'lvl-4' : t <= 0.45 ? 'lvl-3' : t <= 0.6 ? 'lvl-2' : t <= 0.8 ? 'lvl-1' : 'lvl-0';
}

// ---- Registry ----

function standingsTok(entry, model, { ctx, spotlight }, extra) {
    const input = model.input;
    return {
        meta: `${input.season} · THRU WK ${input.completedThrough}`,
        sub: entry.blurb,
        version: `${input.season}-${entry.id}-${input.completedThrough}`,
        involves: input.teams,
        interest: 0.6,
        body: () => entry.render(model, { highlight: spotlight, compact: true }),
        ...extra,
    };
}

function standingsInputFor(ctx) {
    return ctx?.standingsInput || (typeof standingsChartInput === 'function' ? standingsChartInput() : null);
}

const STANDINGS_CHARTS = [
    {
        id: 'playoff-odds-trend',
        family: 'standings',
        title: 'Playoff odds over time',
        blurb: 'Each team\'s chance of a top-four finish after every week, from the same simulation as the odds above.',
        home: { view: 'standings', subview: 'table', anchor: 'chart-playoff-odds-trend' },
        compute(ctx) {
            const input = standingsInputFor(ctx);
            const series = input?.live ? input.oddsSeries() : null;
            if (!series || series.length < 2) return null;
            return { input, series };
        },
        render({ input, series }, { highlight, compact }) {
            return lineChart({
                title: 'Playoff odds by week',
                x: series.map(s => (s.week === 0 ? 'Start' : `W${s.week}`)),
                yDomain: [0, 1],
                yTicks: [0, 0.25, 0.5, 0.75, 1],
                yFmt: v => `${Math.round(v * 100)}%`,
                highlight,
                endLabels: 'all',
                width: compact ? 400 : 640,
                height: compact ? 360 : 280,
                series: input.teams.map(team => ({
                    id: team,
                    label: input.label(team),
                    short: team,
                    values: series.map(s => s.odds[team] ?? null),
                })),
            });
        },
        tok(model, opts) {
            const { input, series } = model;
            const first = series[series.length - 2].odds;
            const last = series[series.length - 1].odds;
            const swing = input.teams
                .map(team => ({ team, delta: (last[team] ?? 0) - (first[team] ?? 0) }))
                .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))[0];
            const pp = Math.round(Math.abs(swing.delta) * 100);
            return standingsTok(this, model, opts, {
                interest: 0.85,
                caption: pp >= 1
                    ? `${swing.delta > 0 ? '📈' : '📉'} ${input.label(swing.team)} ${swing.delta > 0 ? 'gained' : 'lost'} ${pp} points of playoff odds last week`
                    : '📊 Nobody\'s odds moved last week',
            });
        },
    },
    {
        id: 'power-rankings',
        family: 'standings',
        title: 'Power rankings',
        blurb: 'Weekly rank from all-play record (40%), actual record (30%) and the last three weeks of scoring (30%).',
        home: { view: 'standings', subview: 'table', anchor: 'chart-power-rankings' },
        compute(ctx) {
            const input = standingsInputFor(ctx);
            if (!input || input.weeks.length < 2) return null;
            const history = computePowerRankings(input.weeks, input.teams);
            return history.length >= 2 ? { input, history } : null;
        },
        render({ input, history }, { highlight, compact }) {
            return bumpChart({
                title: 'Power rankings by week',
                x: history.map(h => `W${h.week}`),
                series: rankSeries(history, input.teams, input.label),
                highlight,
                width: compact ? 400 : 640,
                height: compact ? 380 : 300,
            });
        },
        tok(model, opts) {
            const { input, history } = model;
            const last = history[history.length - 1];
            const top = Object.entries(last.ranks).find(([, r]) => r === 1)[0];
            const move = biggestMove(history);
            return standingsTok(this, model, opts, {
                interest: 0.8,
                caption: move
                    ? `${move.move > 0 ? '🚀' : '🪂'} ${input.label(move.team)} ${move.move > 0 ? 'jumped' : 'fell'} ${Math.abs(move.move)} spot${Math.abs(move.move) === 1 ? '' : 's'} to No. ${move.rank}`
                    : `👑 ${input.label(top)} is No. 1`,
            });
        },
    },
    {
        id: 'projected-wins',
        family: 'standings',
        title: 'Projected wins',
        blurb: 'Wins so far, plus the wins each team should add from its remaining games given how everyone has scored.',
        home: { view: 'standings', subview: 'table', anchor: 'chart-projected-wins' },
        compute(ctx) {
            const input = standingsInputFor(ctx);
            if (!input?.live || !input.model || !input.remaining.length) return null;
            const extra = expectedRemainingWins(input.remaining, input.model);
            const rows = input.standings.map(t => ({
                id: t.abbrev,
                wins: t.wins || 0,
                losses: t.losses || 0,
                extra: extra[t.abbrev] || 0,
            })).sort((a, b) => (b.wins + b.extra) - (a.wins + a.extra));
            return { input, rows };
        },
        render({ input, rows }, { highlight }) {
            const top = Math.max(...rows.map(r => r.wins + r.extra));
            return barList({
                title: 'Projected wins',
                highlight,
                max: top,
                rows: rows.map(r => ({
                    id: r.id,
                    label: input.label(r.id),
                    sub: `${r.wins}-${r.losses} now · about ${chartNum(r.extra)} more`,
                    value: r.wins + r.extra,
                    display: chartNum(r.wins + r.extra),
                    segments: [
                        { value: r.wins, label: 'Wins' },
                        { value: r.extra, cls: 'is-projected', label: 'Projected' },
                    ],
                })),
            });
        },
        tok(model, opts) {
            const { input, rows } = model;
            return standingsTok(this, model, opts, {
                interest: 0.7,
                caption: `🔮 ${input.label(rows[0].id)} projects to ${chartNum(rows[0].wins + rows[0].extra)} wins`,
            });
        },
    },
    {
        id: 'schedule-ahead',
        family: 'standings',
        title: 'Strength of schedule ahead',
        blurb: 'How much more (or less) the remaining opponents score than the league average, per game.',
        home: { view: 'standings', subview: 'table', anchor: 'chart-schedule-ahead' },
        compute(ctx) {
            const input = standingsInputFor(ctx);
            if (!input?.live || !input.sos) return null;
            const avg = input.leaguePpg;
            const rows = Object.entries(input.sos)
                .map(([team, ppg]) => ({ id: team, ppg, value: ppg - avg }))
                .sort((a, b) => b.value - a.value);
            return rows.length ? { input, rows } : null;
        },
        render({ input, rows }, { highlight }) {
            return divergingBars({
                title: 'Remaining opponents vs league average',
                highlight,
                flip: true,
                rows: rows.map(r => ({
                    id: r.id,
                    label: input.label(r.id),
                    sub: `Opponents average ${chartNum(r.ppg)}`,
                    value: Math.round(r.value * 10) / 10,
                })),
            });
        },
        tok(model, opts) {
            const { input, rows } = model;
            return standingsTok(this, model, opts, {
                caption: `😰 ${input.label(rows[0].id)} has the toughest road left`,
            });
        },
    },
    {
        id: 'standings-replay',
        family: 'standings',
        title: 'Standings replay',
        blurb: 'Every team\'s place in the standings after each week, with the standings\' tiebreakers.',
        home: { view: 'standings', subview: 'table', anchor: 'chart-standings-replay' },
        compute(ctx) {
            const input = standingsInputFor(ctx);
            const history = (input?.history || []).map(h => ({ week: h.week, ranks: h.rankings }));
            return history.length >= 2 ? { input, history } : null;
        },
        render({ input, history }, { highlight, compact }) {
            return bumpChart({
                title: 'Standings by week',
                x: history.map(h => `W${h.week}`),
                series: rankSeries(history, input.teams, input.label),
                highlight,
                table: false,
                width: compact ? 400 : 640,
                height: compact ? 380 : 300,
            });
        },
        tok(model, opts) {
            const { input, history } = model;
            const leaderWeeks = {};
            history.forEach(h => {
                const leader = Object.entries(h.ranks).find(([, r]) => r === 1)?.[0];
                if (leader) leaderWeeks[leader] = (leaderWeeks[leader] || 0) + 1;
            });
            const [leader, weeks] = Object.entries(leaderWeeks).sort((a, b) => b[1] - a[1])[0];
            return standingsTok(this, model, opts, {
                interest: 0.65,
                caption: `🎢 ${input.label(leader)} has led the league ${weeks} week${weeks === 1 ? '' : 's'}`,
            });
        },
    },
    {
        id: 'clinch-tracker',
        family: 'standings',
        title: 'Clinch tracker',
        blurb: 'Rank points now (solid) and the most each team can still reach (faded). The top four make the playoffs.',
        home: { view: 'standings', subview: 'machine', anchor: 'chart-clinch-tracker' },
        compute(ctx) {
            const input = standingsInputFor(ctx);
            if (!input?.live || !input.weeksLeft) return null;
            return { input, rows: clinchRows(input.standings, input.status, input.weeksLeft, input.slots) };
        },
        render({ input, rows }, { highlight }) {
            return barList({
                title: 'Clinch tracker',
                className: 'chart-clinch',
                highlight,
                max: Math.max(...rows.map(r => r.max)),
                rows: rows.map(r => ({
                    id: r.id,
                    label: input.label(r.id),
                    sub: `${chartNum(r.rp)} RP now · can reach ${chartNum(r.max)}`,
                    value: r.max,
                    display: r.label,
                    segments: [
                        { value: r.rp, label: 'Now', cls: r.clinched ? 'is-clinched' : r.eliminated ? 'is-out' : '' },
                        { value: r.max - r.rp, cls: 'is-projected', label: 'Still possible' },
                    ],
                })),
            });
        },
        tok(model, opts) {
            const { input, rows } = model;
            const clinched = rows.filter(r => r.clinched).length;
            const out = rows.filter(r => r.eliminated).length;
            return standingsTok(this, model, opts, {
                interest: 0.75,
                caption: clinched || out
                    ? `🔒 ${clinched} clinched, ${out} out, ${input.weeksLeft} week${input.weeksLeft === 1 ? '' : 's'} left`
                    : `⏳ Nobody's in or out yet, ${input.weeksLeft} weeks left`,
            });
        },
    },
    {
        id: 'finish-history',
        family: 'standings',
        title: 'Finish history',
        blurb: 'Where every franchise finished each season. 🏆 marks a title.',
        home: { view: 'history', subview: 'records', anchor: 'chart-finish-history' },
        compute(ctx) {
            const input = ctx?.finishInput || (typeof finishChartInput === 'function' ? finishChartInput() : null);
            if (!input) return null;
            const history = finishHistory(input.teamHof, input.label, input.leagueSize);
            return history.rows.length && history.seasons.length >= 2 ? { ...history, size: input.leagueSize } : null;
        },
        render({ rows, seasons, size }, { highlight }) {
            const yDomain = rows.map(r => r.label);
            const cells = rows.flatMap(r => seasons.filter(s => r.places[s] != null).map(s => ({
                x: String(s),
                y: r.label,
                cls: `${finishLevel(r.places[s], size)}${highlight && r.id === highlight ? ' is-highlight' : ''}`,
                text: r.places[s] === 1 ? '🏆' : String(r.places[s]),
                tip: `${r.label}, ${s}: ${r.places[s] === 1 ? 'Champion' : `${r.places[s]}${['th', 'st', 'nd', 'rd'][r.places[s] % 10 > 3 || [11, 12, 13].includes(r.places[s] % 100) ? 0 : r.places[s] % 10]} place`}`,
            })));
            return heatGrid({
                label: 'Finish history by franchise and season',
                cells,
                xDomain: seasons.map(String),
                yDomain,
                cellSize: 30,
                table: {
                    caption: 'Finish history',
                    head: ['', ...seasons.map(String), 'Titles'],
                    rows: rows.map(r => [r.label, ...seasons.map(s => r.places[s] ?? '–'), r.titles]),
                },
            });
        },
        tok(model, { spotlight }) {
            const top = model.rows[0];
            return {
                meta: `${model.seasons[0]}–${model.seasons[model.seasons.length - 1]}`,
                sub: this.blurb,
                version: `finish-history-${model.seasons[model.seasons.length - 1]}-${model.rows.length}`,
                involves: model.rows.map(r => r.id),
                interest: 0.55,
                caption: top.titles
                    ? `🏆 ${top.label} has ${top.titles} title${top.titles === 1 ? '' : 's'}`
                    : '🏆 Every season, every finish',
                body: () => this.render(model, { highlight: spotlight }),
            };
        },
    },
];

STANDINGS_CHARTS.forEach(chart => registerChart(chart));

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        chartNormalCdf, computePowerRankings, rankSeries, biggestMove, gameWinProbability,
        expectedRemainingWins, clinchRows, finishPlace, finishHistory, finishLevel, STANDINGS_CHARTS,
    };
}

// ---- Browser inputs ----

const ODDS_TREND_TRIALS = 1500;
let oddsTrendCache = null;

function standingsTeamLabel(abbrev) {
    const team = (data?.teams || []).find(t => t.abbrev === abbrev)
        || (data?.standings || []).find(t => t.abbrev === abbrev);
    return team?.name || abbrev;
}

// Everything the standings charts read, from the season on screen.
function standingsChartInput() {
    if (!data?.standings?.length) return null;
    const context = getPostseasonStatusContext();
    const standings = context.standings;
    const completedThrough = context.completedThrough;
    const format = seasonFormat();
    const live = data.season === LIVE_SEASON && !data.is_offseason && !data.is_historical;
    const teams = standings.map(t => t.abbrev);
    const weeks = (data.weeks || [])
        .filter(w => w.has_scores && w.games_final !== false && w.week <= format.lastWeek && w.week <= completedThrough)
        .sort((a, b) => a.week - b.week)
        .map(w => ({
            week: w.week,
            games: (w.matchups || []).filter(m => m.team1?.abbrev && m.team2?.abbrev).map(m => ({
                a: m.team1.abbrev,
                b: m.team2.abbrev,
                sa: whatIfScore(m.team1),
                sb: whatIfScore(m.team2),
            })),
        }));
    const model = live ? preparePlayoffSim() : null;
    const games = standings.reduce((s, t) => s + (t.wins || 0) + (t.losses || 0) + (t.ties || 0), 0);
    const points = standings.reduce((s, t) => s + (t.points_for || 0), 0);
    const remaining = live
        ? getRemainingMatchups(weeks.map(w => w.week)).map(m => ({ week: m.week, a: m.team1Abbrev, b: m.team2Abbrev }))
        : [];
    const weeksLeft = new Set(remaining.map(m => m.week)).size;
    const season = Number(data.season);
    return {
        season,
        live,
        completedThrough,
        slots: format.slots,
        standings,
        teams,
        label: standingsTeamLabel,
        weeks,
        remaining,
        weeksLeft,
        model,
        leaguePpg: games ? points / games : 0,
        history: computeWeeklyStandings(completedThrough, standings),
        status: computePlayoffStatus(standings, weeksLeft),
        sos: live ? computeRemainingSOS(completedThrough, standings) : null,
        oddsSeries: () => {
            const key = `${season}|${completedThrough}|${data.updated_at || ''}`;
            if (oddsTrendCache?.key === key) return oddsTrendCache.series;
            const series = [];
            for (let week = 0; week <= completedThrough; week += 1) {
                const ctx = preparePlayoffSim(week);
                if (!ctx) continue;
                const summary = summarizePlayoffSim(ctx, runPlayoffSim(ctx, { trials: ODDS_TREND_TRIALS }));
                series.push({
                    week,
                    odds: Object.fromEntries(Object.values(summary.byTeam).map(t => [
                        t.abbrev,
                        t.clinched ? 1 : t.eliminated ? 0 : t.odds,
                    ])),
                });
            }
            oddsTrendCache = { key, series };
            return series;
        },
    };
}

function finishChartInput() {
    const teamHof = data?.hall_of_fame?.team_hall_of_fame || sharedData?.hall_of_fame?.team_hall_of_fame;
    if (!teamHof) return null;
    const ownerOf = code => teamHof[code]?.ownerStats?.[0]?.owner
        || teamHof[code]?.seasons?.[0]?.owner
        || code;
    return { teamHof, label: ownerOf, leagueSize: Object.keys(teamHof).length || 10 };
}

// Standings → Table charts, below the playoff odds card.
function renderStandingsCharts() {
    const slot = document.getElementById('standings-charts');
    if (!slot) return;
    const highlight = myTeamAbbrev();
    const input = standingsChartInput();
    const ctx = { standingsInput: input };
    slot.innerHTML = ['playoff-odds-trend', 'power-rankings', 'projected-wins', 'schedule-ahead', 'standings-replay']
        .map(id => renderChartSection(id, ctx, { highlight }))
        .join('');
}

// Standings → Playoff Machine: the clinch tracker under the machine.
function renderMachineCharts() {
    const slot = document.getElementById('machine-charts');
    if (!slot) return;
    slot.innerHTML = renderChartSection('clinch-tracker', { standingsInput: standingsChartInput() }, { highlight: myTeamAbbrev() });
}
