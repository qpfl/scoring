// Luck & what-if charts (Phase 3 of docs/PLAN_qpfltok_and_charts.md).
//
// Loaded after charts-standings.js, before app.js. The math is pure over a
// flat list of finished games (tests/test_luck_charts.py runs it in node);
// luckChartInput() at the bottom builds that list from app.js at runtime.
//
// Charts and where they live:
//   all-play-luck, pythag-wins, wrong-opponent → Standings → Alternate
//     standings → All-play
//   perfect-rate   → Alternate standings → Perfect lineups
//   schedule-swap  → Alternate standings → Schedule swap
//   projection-luck → Stats → Team Stats

/* eslint-disable no-unused-vars */

// games: [{ week, a, b, sa, sb, pa?, pb?, proja?, projb? }]: one per
// matchup, sa/sb the final scores, pa/pb the best lineups the rosters
// allowed, proja/projb the pregame projections.

function weeksOf(games) {
    const byWeek = new Map();
    for (const g of games) {
        if (!byWeek.has(g.week)) byWeek.set(g.week, []);
        byWeek.get(g.week).push(g);
    }
    return [...byWeek.entries()].sort((x, y) => x[0] - y[0]);
}

function teamRecords(games) {
    const rec = {};
    const row = t => (rec[t] ??= { wins: 0, losses: 0, ties: 0, pf: 0, pa: 0, games: 0 });
    for (const g of games) {
        const a = row(g.a);
        const b = row(g.b);
        a.pf += g.sa; a.pa += g.sb; b.pf += g.sb; b.pa += g.sa;
        a.games += 1; b.games += 1;
        if (g.sa > g.sb) { a.wins += 1; b.losses += 1; }
        else if (g.sb > g.sa) { b.wins += 1; a.losses += 1; }
        else { a.ties += 1; b.ties += 1; }
    }
    return rec;
}

// Wins minus all-play expected wins: each week is worth the share of the
// rest of the league a team outscored.
function allPlayLuck(games) {
    const rec = teamRecords(games);
    const expected = {};
    for (const [, week] of weeksOf(games)) {
        const scores = week.flatMap(g => [[g.a, g.sa], [g.b, g.sb]]);
        for (const [team, score] of scores) {
            let beat = 0;
            for (const [other, otherScore] of scores) {
                if (other === team) continue;
                beat += score > otherScore ? 1 : score === otherScore ? 0.5 : 0;
            }
            expected[team] = (expected[team] || 0) + beat / Math.max(1, scores.length - 1);
        }
    }
    return Object.keys(rec).map(team => {
        const wins = rec[team].wins + rec[team].ties / 2;
        return { id: team, wins, expected: expected[team] || 0, luck: wins - (expected[team] || 0), record: rec[team] };
    }).sort((x, y) => y.luck - x.luck);
}

// Pythagorean wins: games × PF^k / (PF^k + PA^k). k = 4.1 is the exponent
// that best fits QPFL's 2020–2025 final standings (56 team-seasons, about
// one win of error); football's usual 2.37 misses by a third more.
const PYTHAG_EXPONENT = 4.1;

function pythagWins(games, k = PYTHAG_EXPONENT) {
    const rec = teamRecords(games);
    return Object.entries(rec).map(([team, r]) => {
        const share = r.pf + r.pa > 0 ? r.pf ** k / (r.pf ** k + r.pa ** k) : 0.5;
        const expected = share * r.games;
        const wins = r.wins + r.ties / 2;
        return { id: team, wins, expected, luck: wins - expected, record: r };
    }).sort((x, y) => y.luck - x.luck);
}

// Losses with a score that beat most of the league that week: the right
// game against the wrong opponent.
function wrongOpponentLosses(games) {
    const out = {};
    for (const [week, list] of weeksOf(games)) {
        const scores = list.flatMap(g => [[g.a, g.sa], [g.b, g.sb]]);
        for (const g of list) {
            for (const [team, mine, opp, theirs] of [[g.a, g.sa, g.b, g.sb], [g.b, g.sb, g.a, g.sa]]) {
                if (mine >= theirs) continue;
                const beaten = scores.filter(([other, s]) => other !== team && other !== opp && mine > s).length;
                const field = scores.length - 2;
                if (field > 0 && beaten > field / 2) {
                    (out[team] ??= []).push({ week, score: mine, oppScore: theirs, opp, beaten, field });
                }
            }
        }
    }
    return Object.entries(out)
        .map(([team, losses]) => ({ id: team, losses }))
        .sort((x, y) => y.losses.length - x.losses.length || x.id.localeCompare(y.id));
}

// How often each team started its best possible lineup, and the points the
// rest of the time left on the bench.
function perfectLineupRates(games) {
    const out = {};
    for (const g of games) {
        for (const [team, score, best] of [[g.a, g.sa, g.pa], [g.b, g.sb, g.pb]]) {
            if (typeof best !== 'number') continue;
            const r = (out[team] ??= { id: team, perfect: 0, weeks: 0, left: 0 });
            r.weeks += 1;
            const gap = Math.max(0, best - score);
            if (gap < 0.5) r.perfect += 1;
            r.left += gap;
        }
    }
    return Object.values(out)
        .map(r => ({ ...r, rate: r.weeks ? r.perfect / r.weeks : 0 }))
        .sort((x, y) => y.rate - x.rate || x.left - y.left);
}

// Points scored beyond (or short of) the pregame projection, by week and in
// total, for weeks that had one. Projections run low or high for everyone
// some weeks, so each week is measured against the league's average beat:
// the chart shows who outran their projection more than the rest did.
function projectionLuck(games) {
    const weeks = weeksOf(games).filter(([, list]) => list.some(g => typeof g.proja === 'number'));
    const teams = {};
    let leagueBeat = 0;
    weeks.forEach(([, list], index) => {
        const beats = list.flatMap(g => [[g.a, g.sa, g.proja], [g.b, g.sb, g.projb]])
            .filter(([, , proj]) => typeof proj === 'number')
            .map(([team, score, proj]) => [team, score - proj]);
        const average = beats.reduce((sum, [, beat]) => sum + beat, 0) / Math.max(1, beats.length);
        leagueBeat += average;
        for (const [team, beat] of beats) {
            const t = (teams[team] ??= { id: team, total: 0, raw: 0, cumulative: Array(weeks.length).fill(null) });
            t.raw += beat;
            t.total += beat - average;
            t.cumulative[index] = Math.round(t.total * 10) / 10;
        }
    });
    return {
        weeks: weeks.map(([week]) => week),
        leagueBeat,
        rows: Object.values(teams).sort((x, y) => y.total - x.total),
    };
}

// The schedule-swap grid (computeWhatIf's) as heat-grid cells: each cell is
// a team's rank points on another team's schedule, colored by the change.
function scheduleSwapCells(teams, grid, label) {
    const level = diff => (diff >= 2 ? 'lvl-4' : diff >= 0.5 ? 'lvl-3' : diff <= -2 ? 'lvl-0' : diff <= -0.5 ? 'lvl-1' : 'lvl-2');
    const cells = [];
    let best = null;
    for (const team of teams) {
        const own = grid[team][team];
        for (const owner of teams) {
            const cell = grid[team][owner];
            const diff = cell.rp - own.rp;
            if (owner !== team && (!best || diff > best.diff)) best = { team, owner, diff };
            cells.push({
                x: owner,
                y: team,
                cls: owner === team ? 'is-actual' : level(diff),
                text: `${cell.wins}-${cell.losses}`,
                tip: `${label(team)} with ${label(owner)}'s schedule: ${cell.wins}-${cell.losses}${cell.ties ? `-${cell.ties}` : ''}, ${chartNum(cell.rp)} RP (${diff >= 0 ? '+' : ''}${chartNum(diff)})`,
            });
        }
    }
    return { cells, best };
}

// ---- Registry ----

function luckInputFor(ctx) {
    return ctx?.luckInput || (typeof luckChartInput === 'function' ? luckChartInput() : null);
}

function luckTok(entry, model, { spotlight }, extra) {
    const { input } = model;
    return {
        meta: `${input.season} · THRU WK ${input.completedThrough}`,
        sub: entry.blurb,
        version: `${input.season}-${entry.id}-${input.completedThrough}`,
        involves: input.teams,
        interest: 0.65,
        body: () => entry.render(model, { highlight: spotlight, compact: true }),
        ...extra,
    };
}

const luckPlural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
const luckWins = v => `${chartNum(Math.abs(v))} win${Math.abs(v) === 1 ? '' : 's'}`;

const LUCK_CHARTS = [
    {
        id: 'all-play-luck',
        family: 'luck',
        title: 'Schedule luck',
        blurb: 'Actual wins minus all-play wins: what a team\'s scores would have earned against an average opponent each week.',
        home: { view: 'standings', subview: 'table', anchor: 'chart-all-play-luck' },
        whatIf: 'allplay',
        compute(ctx) {
            const input = luckInputFor(ctx);
            if (!input?.games.length) return null;
            return { input, rows: allPlayLuck(input.games) };
        },
        render({ input, rows }, { highlight }) {
            return divergingBars({
                title: 'Wins above all-play pace',
                highlight,
                rows: rows.map(r => ({
                    id: r.id,
                    label: input.label(r.id),
                    sub: `${chartNum(r.wins)} wins, all-play pace ${chartNum(Math.round(r.expected * 10) / 10)}`,
                    value: Math.round(r.luck * 10) / 10,
                })),
            });
        },
        tok(model, opts) {
            const { input, rows } = model;
            const who = abbrev => chartWho(opts, input, abbrev);
            const lucky = rows[0];
            const robbed = rows[rows.length - 1];
            return luckTok(this, model, opts, {
                interest: 0.8,
                caption: Math.abs(robbed.luck) > lucky.luck
                    ? `😭 ${who(robbed.id)} has been robbed of ${luckWins(Math.round(robbed.luck * 10) / 10)}`
                    : `🍀 ${who(lucky.id)} has ${luckWins(Math.round(lucky.luck * 10) / 10)} more than their scores deserve`,
            });
        },
    },
    {
        id: 'pythag-wins',
        family: 'luck',
        title: 'Pythagorean wins',
        blurb: `Wins a team's points for and against usually produce (PF^${PYTHAG_EXPONENT} ÷ (PF^${PYTHAG_EXPONENT} + PA^${PYTHAG_EXPONENT}), fitted to QPFL history), against its real wins.`,
        home: { view: 'standings', subview: 'table', anchor: 'chart-pythag-wins' },
        whatIf: 'allplay',
        compute(ctx) {
            const input = luckInputFor(ctx);
            if (!input?.games.length) return null;
            return { input, rows: pythagWins(input.games) };
        },
        render({ input, rows }, { highlight }) {
            return divergingBars({
                title: 'Wins above Pythagorean expectation',
                highlight,
                rows: rows.map(r => ({
                    id: r.id,
                    label: input.label(r.id),
                    sub: `${chartNum(r.wins)} wins, expected ${chartNum(Math.round(r.expected * 10) / 10)} (${Math.round(r.record.pf)}–${Math.round(r.record.pa)})`,
                    value: Math.round(r.luck * 10) / 10,
                })),
            });
        },
        tok(model, opts) {
            const { input, rows } = model;
            const who = abbrev => chartWho(opts, input, abbrev);
            const top = rows[0];
            return luckTok(this, model, opts, {
                caption: `🧮 ${who(top.id)} is ${luckWins(Math.round(top.luck * 10) / 10)} ahead of the math`,
            });
        },
    },
    {
        id: 'wrong-opponent',
        family: 'luck',
        title: 'Wrong opponent',
        blurb: 'Losses with a score that beat most of the rest of the league that week.',
        home: { view: 'standings', subview: 'table', anchor: 'chart-wrong-opponent' },
        whatIf: 'allplay',
        compute(ctx) {
            const input = luckInputFor(ctx);
            const rows = input ? wrongOpponentLosses(input.games) : [];
            return rows.length ? { input, rows } : null;
        },
        render({ input, rows }, { highlight }) {
            return barList({
                title: 'Losses that would have beaten most teams',
                highlight,
                valueFmt: v => `${v}`,
                rows: rows.map(r => ({
                    id: r.id,
                    label: input.label(r.id),
                    value: r.losses.length,
                    sub: r.losses.map(l => `W${l.week}: ${chartNum(l.score)}–${chartNum(l.oppScore)} vs ${input.label(l.opp)}, beat ${l.beaten} of ${l.field}`).join(' · '),
                })),
            });
        },
        tok(model, opts) {
            const { input, rows } = model;
            const who = abbrev => chartWho(opts, input, abbrev);
            const top = rows[0];
            return luckTok(this, model, opts, {
                interest: 0.75,
                caption: `🤬 ${who(top.id)} lost ${luckPlural(top.losses.length, 'game')} that would have beaten most of the league`,
            });
        },
    },
    {
        id: 'perfect-rate',
        family: 'luck',
        title: 'Perfect lineups',
        blurb: 'How often each team started the best lineup its roster allowed, and the points left on the bench the rest of the time.',
        home: { view: 'standings', subview: 'table', anchor: 'chart-perfect-rate' },
        whatIf: 'perfect',
        compute(ctx) {
            const input = luckInputFor(ctx);
            const rows = input ? perfectLineupRates(input.games) : [];
            return rows.length ? { input, rows } : null;
        },
        render({ input, rows }, { highlight }) {
            return `<div class="chart-ring-grid">${rows.map(r => ringStat({
                id: r.id,
                highlight,
                pct: r.rate,
                label: input.label(r.id),
                sub: `${r.perfect} of ${r.weeks} weeks · ${Math.round(r.left)} pts left on the bench`,
            })).join('')}</div>`;
        },
        tok(model, opts) {
            const { input, rows } = model;
            const who = abbrev => chartWho(opts, input, abbrev);
            const top = rows[0];
            const worst = [...rows].sort((x, y) => y.left - x.left)[0];
            return luckTok(this, model, opts, {
                caption: top.perfect
                    ? `🧠 ${who(top.id)} set a perfect lineup ${top.perfect} of ${top.weeks} weeks`
                    : `🪑 ${who(worst.id)} has left ${Math.round(worst.left)} points on the bench`,
            });
        },
    },
    {
        id: 'schedule-swap',
        family: 'luck',
        title: 'Schedule swap',
        blurb: 'Each row is a team\'s record on every other team\'s schedule. Green is better than what happened, red worse; the outlined square is reality.',
        home: { view: 'standings', subview: 'table', anchor: 'chart-schedule-swap' },
        whatIf: 'schedule',
        compute(ctx) {
            const input = luckInputFor(ctx);
            const swap = input?.scheduleSwap?.();
            if (!swap?.teams?.length) return null;
            return { input, ...swap, ...scheduleSwapCells(swap.teams, swap.grid, input.label) };
        },
        render({ input, teams, cells }, { highlight }) {
            return heatGrid({
                label: 'Records on every schedule',
                cells: cells.map(c => (highlight && c.y === highlight ? { ...c, cls: `${c.cls} is-highlight` } : c)),
                xDomain: teams,
                yDomain: teams,
                cellSize: 32,
                xLabel: 'Schedule of',
            });
        },
        tok(model, opts) {
            const { input, best } = model;
            const who = abbrev => chartWho(opts, input, abbrev);
            return luckTok(this, model, opts, {
                interest: 0.7,
                caption: best && best.diff > 0
                    ? `🗓️ ${who(best.team)} would have ${chartNum(best.diff)} more RP with ${who(best.owner)}'s schedule`
                    : '🗓️ Every schedule, every team',
            });
        },
    },
    {
        id: 'projection-luck',
        family: 'luck',
        title: 'Beating the projections',
        blurb: 'Points scored beyond the pregame projection, compared with how far the whole league beat (or missed) its projections each week.',
        home: { view: 'stats', subview: 'team', anchor: 'chart-projection-luck' },
        compute(ctx) {
            const input = luckInputFor(ctx);
            const result = input ? projectionLuck(input.games) : null;
            return result?.weeks.length >= 2 ? { input, ...result } : null;
        },
        render({ input, weeks, rows }, { highlight, compact }) {
            const bars = divergingBars({
                title: 'Points above projection',
                highlight,
                valueFmt: v => `${v > 0 ? '+' : ''}${Math.round(v)}`,
                rows: rows.map(r => ({ id: r.id, label: input.label(r.id), value: Math.round(r.total) })),
            });
            if (compact) return bars;
            return bars + lineChart({
                title: 'Points above projection, season to date',
                x: weeks.map(w => `W${w}`),
                highlight,
                endLabels: 'all',
                refLine: 0,
                yFmt: v => `${v > 0 ? '+' : ''}${Math.round(v)}`,
                series: rows.map(r => ({ id: r.id, label: input.label(r.id), short: r.id, values: r.cumulative })),
            });
        },
        tok(model, opts) {
            const { input, rows } = model;
            const who = abbrev => chartWho(opts, input, abbrev);
            const top = rows[0];
            const bottom = rows[rows.length - 1];
            return luckTok(this, model, opts, {
                interest: 0.7,
                caption: Math.abs(bottom.total) > top.total
                    ? `📉 ${who(bottom.id)} trails their projections ${Math.round(Math.abs(bottom.total))} points more than the league does`
                    : `🎯 ${who(top.id)} has outrun their projections by ${Math.round(top.total)} points more than the league`,
            });
        },
    },
];

LUCK_CHARTS.forEach(chart => registerChart(chart));

// Which Alternate standings tab shows which charts.
function luckChartsFor(view) {
    return LUCK_CHARTS.filter(chart => chart.whatIf === view).map(chart => chart.id);
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        weeksOf, teamRecords, allPlayLuck, PYTHAG_EXPONENT, pythagWins, wrongOpponentLosses,
        perfectLineupRates, projectionLuck, scheduleSwapCells, LUCK_CHARTS, luckChartsFor,
    };
}

// ---- Browser inputs ----

let luckInputCache = null;

// Finished regular-season games of the season on screen.
function luckChartInput() {
    if (!data?.standings?.length) return null;
    const context = getPostseasonStatusContext();
    const completedThrough = context.completedThrough;
    const key = `${data.season}|${completedThrough}|${data.updated_at || ''}|${(data.weeks || []).length}`;
    if (luckInputCache?.key === key) return luckInputCache.input;
    const weeks = whatIfWeeks(completedThrough);
    const projection = team => (typeof team.pregame_total === 'number' ? team.pregame_total : undefined);
    const games = weeks.flatMap(w => w.games.map(g => ({
        week: w.week,
        a: g.a.abbrev,
        b: g.b.abbrev,
        sa: whatIfScore(g.a),
        sb: whatIfScore(g.b),
        pa: perfectScore(g.a),
        pb: perfectScore(g.b),
        proja: projection(g.a),
        projb: projection(g.b),
    })));
    let swap;
    const input = {
        season: Number(data.season),
        completedThrough,
        teams: context.standings.map(t => t.abbrev),
        label: standingsTeamLabel,
        games,
        scheduleSwap: () => {
            if (swap === undefined) swap = weeks.length ? computeWhatIf('schedule', weeks) : null;
            return swap;
        },
    };
    luckInputCache = { key, input };
    return input;
}

// The luck charts for one Alternate standings tab, under its table.
function whatIfChartsHtml(view) {
    const ids = luckChartsFor(view);
    if (!ids.length) return '';
    const ctx = { luckInput: luckChartInput() };
    const highlight = myTeamAbbrev();
    return `<div class="whatif-charts">${ids.map(id => renderChartSection(id, ctx, { highlight })).join('')}</div>`;
}

// A link to one of these charts (?section=chart-…) opens Alternate
// standings on the tab that holds it.
function whatIfViewForSection(section) {
    const chart = LUCK_CHARTS.find(c => `chart-${c.id}` === section);
    return chart?.whatIf || null;
}

function renderTeamStatsCharts() {
    const slot = document.getElementById('team-stats-charts');
    if (!slot) return;
    slot.innerHTML = renderChartSection('projection-luck', { luckInput: luckChartInput() }, { highlight: myTeamAbbrev() });
}
