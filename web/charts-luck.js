// Luck & what-if charts (Phase 3 of docs/PLAN_qpfltok_and_charts.md).
//
// Loaded after charts-standings.js, before app.js. The math is pure over a
// flat list of finished games (tests/test_luck_charts.py runs it in node);
// luckChartInput() at the bottom builds that list from app.js at runtime.
//
// Charts and where they live:
//   all-play-luck  → Standings → Alternate standings → All-play: one
//     scatter of actual vs all-play wins; Pythagorean wins and wrong-opponent
//     losses ride along in each dot's tooltip
//   perfect-rate   → Alternate standings → Perfect lineups (team × week grid)
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

// Each team's score and best possible score, week by week:
// { team: { week: { score, best, pct } } }.
function lineupWeeks(games) {
    const out = {};
    for (const g of games) {
        for (const [team, score, best] of [[g.a, g.sa, g.pa], [g.b, g.sb, g.pb]]) {
            if (typeof best !== 'number' || best <= 0) continue;
            (out[team] ??= {})[g.week] = { score, best, pct: Math.min(1, score / best) };
        }
    }
    return out;
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
        meta: `THRU WK ${input.completedThrough}`,
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
        scope: 'season',
        title: 'Luck',
        blurb: 'Wins your scores earned against the whole league (across) vs wins you got (up). Above the line is lucky.',
        home: { view: 'standings', subview: 'table', anchor: 'chart-all-play-luck' },
        whatIf: 'allplay',
        compute(ctx) {
            const input = luckInputFor(ctx);
            if (!input?.games.length) return null;
            const pythag = Object.fromEntries(pythagWins(input.games).map(r => [r.id, r.expected]));
            const wrong = Object.fromEntries(wrongOpponentLosses(input.games).map(r => [r.id, r.losses.length]));
            return { input, rows: allPlayLuck(input.games), pythag, wrong };
        },
        render({ input, rows, pythag, wrong }, { highlight, compact }) {
            const one = v => chartNum(Math.round(v * 10) / 10);
            return scatterPlot({
                title: 'Actual wins vs all-play wins',
                xLabel: 'Wins earned (all-play)',
                yLabel: 'Actual wins',
                diagonal: true,
                aboveLabel: '🍀 Lucky',
                belowLabel: 'Robbed 😭',
                highlight,
                width: compact ? 400 : 520,
                height: compact ? 400 : 380,
                fmt: v => chartNum(v),
                points: rows.map(r => ({
                    id: r.id,
                    label: input.label(r.id),
                    x: Math.round(r.expected * 10) / 10,
                    y: r.wins,
                    tip: `${input.label(r.id)}: ${chartNum(r.wins)} wins, ${one(r.expected)} earned (${r.luck >= 0 ? '+' : ''}${one(r.luck)}) · points for and against say ${one(pythag[r.id] ?? 0)}${wrong[r.id] ? ` · ${wrong[r.id]} loss${wrong[r.id] === 1 ? '' : 'es'} that would have beaten most teams` : ''}`,
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
        id: 'perfect-rate',
        family: 'luck',
        scope: 'season',
        title: 'Lineup efficiency',
        blurb: 'Each week\'s score as a share of the best possible lineup. Darker is closer; ★ is perfect.',
        home: { view: 'standings', subview: 'table', anchor: 'chart-perfect-rate' },
        whatIf: 'perfect',
        compute(ctx) {
            const input = luckInputFor(ctx);
            const rows = input ? perfectLineupRates(input.games) : [];
            return rows.length ? { input, rows, weeks: lineupWeeks(input.games) } : null;
        },
        render({ input, rows, weeks }, { highlight }) {
            const weekNums = [...new Set(Object.values(weeks).flatMap(w => Object.keys(w).map(Number)))].sort((a, b) => a - b);
            // Magnitude, so one hue light to dark; a perfect week is gold.
            const level = pct => (pct >= 0.995 ? 'is-perfect' : pct >= 0.9 ? 'seq-3' : pct >= 0.8 ? 'seq-2' : pct >= 0.7 ? 'seq-1' : 'seq-0');
            const cells = rows.flatMap(r => weekNums.filter(w => weeks[r.id]?.[w]).map(w => {
                const g = weeks[r.id][w];
                return {
                    x: `W${w}`,
                    y: input.label(r.id),
                    cls: `${level(g.pct)}${highlight && r.id === highlight ? ' is-highlight' : ''}`,
                    text: g.pct >= 0.995 ? '★' : null,
                    tip: `${input.label(r.id)}, Week ${w}: ${chartNum(g.score)} of ${chartNum(g.best)} possible (${Math.round(g.pct * 100)}%)`,
                };
            }));
            return heatGrid({
                label: 'Lineup efficiency by week',
                cells,
                xDomain: weekNums.map(w => `W${w}`),
                yDomain: rows.map(r => input.label(r.id)),
                cellSize: 30,
                table: {
                    caption: 'Perfect lineups',
                    head: ['', 'Perfect weeks', 'Points left on the bench'],
                    rows: rows.map(r => [input.label(r.id), `${r.perfect} of ${r.weeks}`, Math.round(r.left)]),
                },
            });
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
        scope: 'season',
        title: 'Schedule swap',
        blurb: 'Each row\'s record on every other team\'s schedule. Green is better than reality (outlined).',
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
        scope: 'season',
        title: 'Beating the projections',
        blurb: 'Running points above pregame projections, net of the league\'s weekly miss.',
        home: { view: 'stats', subview: 'team', anchor: 'chart-projection-luck' },
        compute(ctx) {
            const input = luckInputFor(ctx);
            const result = input ? projectionLuck(input.games) : null;
            return result?.weeks.length >= 2 ? { input, ...result } : null;
        },
        render({ input, weeks, rows }, { highlight, compact }) {
            return lineChart({
                title: 'Points above projection, season to date',
                x: weeks.map(w => `W${w}`),
                highlight,
                endLabels: 'all',
                refLine: 0,
                width: compact ? 400 : 640,
                height: compact ? 380 : 280,
                yFmt: v => `${v > 0 ? '+' : ''}${Math.round(v)}`,
                series: rows.map(r => ({ id: r.id, label: input.label(r.id), values: r.cumulative })),
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
        perfectLineupRates, lineupWeeks, projectionLuck, scheduleSwapCells, LUCK_CHARTS, luckChartsFor,
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
        label: chartShortName,
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
