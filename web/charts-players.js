// Players, moves & awards charts (Phase 5 of docs/PLAN_qpfltok_and_charts.md).
//
// Loaded after charts-managers.js, before app.js. The math is pure over plain
// inputs (tests/test_player_charts.py); the *ChartInput() builders at the
// bottom gather them from app.js at runtime.
//
// Charts and where they live:
//   weekly-awards     → Matchups → This Week (once the week is final), and
//                       QPFLTok's "Awards night" clip
//   boom-bust         → Stats → Player Leaders
//   one-man-armies    → Stats → Team Stats
//   trade-grades      → Transactions, under Most Lopsided Trades
//   costliest-drops   → Transactions
//   draft-value       → Drafts → Draft History

/* eslint-disable no-unused-vars */

// ---- Boom or bust ----

const BOOM_MIN_STARTS = 5;
const BOOM_MIN_AVERAGE = 10;
const BOOM_SHOWN = 12;

function standardDeviation(values) {
    if (values.length < 2) return 0;
    const mean = values.reduce((s, v) => s + v, 0) / values.length;
    return Math.sqrt(values.reduce((s, v) => s + (v - mean) ** 2, 0) / values.length);
}

// starts: [{ key, name, position, team, score }], one per started game.
// The steadiest and swingiest regular starters, by spread of their weeks.
function boomBust(starts) {
    const players = new Map();
    for (const s of starts) {
        if (!players.has(s.key)) players.set(s.key, { ...s, values: [], teams: new Set() });
        const p = players.get(s.key);
        p.values.push(s.score);
        p.teams.add(s.team);
    }
    const rows = [...players.values()]
        .filter(p => p.values.length >= BOOM_MIN_STARTS)
        .map(p => {
            const mean = p.values.reduce((s, v) => s + v, 0) / p.values.length;
            return { id: p.key, name: p.name, position: p.position, teams: [...p.teams], values: p.values, mean, sd: standardDeviation(p.values) };
        })
        .filter(p => p.mean >= BOOM_MIN_AVERAGE);
    return {
        boom: [...rows].sort((a, b) => b.sd - a.sd).slice(0, BOOM_SHOWN),
        steady: [...rows].sort((a, b) => a.sd / a.mean - b.sd / b.mean).slice(0, 5),
    };
}

// ---- One-man armies ----

// Each team's top starter and his share of the team's starter points.
function oneManArmies(starts) {
    const teams = new Map();
    for (const s of starts) {
        if (!teams.has(s.team)) teams.set(s.team, { total: 0, players: new Map() });
        const t = teams.get(s.team);
        t.total += s.score;
        const p = t.players.get(s.key) || { name: s.name, position: s.position, points: 0, starts: 0 };
        p.points += s.score;
        p.starts += 1;
        t.players.set(s.key, p);
    }
    return [...teams.entries()].map(([team, t]) => {
        const top = [...t.players.values()].sort((a, b) => b.points - a.points)[0];
        return { team, player: top.name, position: top.position, points: top.points, total: t.total, share: t.total > 0 ? top.points / t.total : 0 };
    }).sort((a, b) => b.share - a.share);
}

// ---- Trade grades ----
//
// Every graded trade gives each side a margin (its haul minus the other
// side's). Grades come from where a margin falls among all sides of all
// trades, so they are on a curve: A+ is the top tenth, F the bottom 30%.
const TRADE_GRADES = [
    ['A+', 0.9, 4.3],
    ['A', 0.7, 4.0],
    ['B', 0.55, 3.0],
    ['C', 0.45, 2.0],
    ['D', 0.3, 1.0],
    ['F', 0, 0],
];

function tradeGrade(percentile) {
    return TRADE_GRADES.find(([, floor]) => percentile >= floor) || TRADE_GRADES[TRADE_GRADES.length - 1];
}

// trades: [{ id, season, sides: [{ team, total }, { team, total }] }]
function tradeGrades(trades) {
    const sides = trades.flatMap(t => {
        const [a, b] = t.sides;
        return [
            { trade: t, team: a.team, margin: a.total - b.total, other: b.team },
            { trade: t, team: b.team, margin: b.total - a.total, other: a.team },
        ];
    });
    const margins = sides.map(s => s.margin).sort((x, y) => x - y);
    const percentile = m => {
        if (margins.length < 2) return 0.5;
        const below = margins.filter(v => v < m).length;
        const equal = margins.filter(v => v === m).length - 1;
        return (below + equal / 2) / (margins.length - 1);
    };
    const graded = sides.map(s => {
        const [grade, , points] = tradeGrade(percentile(s.margin));
        return { ...s, grade, points };
    });
    const byTeam = new Map();
    for (const g of graded) {
        if (!byTeam.has(g.team)) byTeam.set(g.team, []);
        byTeam.get(g.team).push(g);
    }
    const teams = [...byTeam.entries()].map(([team, list]) => ({
        team,
        trades: list.length,
        gpa: list.reduce((s, g) => s + g.points, 0) / list.length,
        best: [...list].sort((a, b) => b.margin - a.margin)[0],
        worst: [...list].sort((a, b) => a.margin - b.margin)[0],
        grades: list.map(g => g.grade),
    })).sort((a, b) => b.gpa - a.gpa || b.trades - a.trades);
    const fleecing = [...graded].sort((a, b) => b.margin - a.margin)[0] || null;
    return { teams, fleecing };
}

// ---- Draft value over slot ----
//
// picks: [{ season, draft, overall, team, player, points }] from offseason
// drafts. Older drafts have had longer to pile up points, so each pick is
// measured against its own draft's average pick first; a slot's expected
// value is the average of that relative value at the slot and its two
// neighbours, over the graded drafts (at least two seasons old).
function draftValueOverSlot(picks, gradedThrough) {
    const byDraft = new Map();
    for (const p of picks) {
        if (!byDraft.has(p.draft)) byDraft.set(p.draft, []);
        byDraft.get(p.draft).push(p);
    }
    const rel = [];
    for (const list of byDraft.values()) {
        const mean = list.reduce((s, p) => s + p.points, 0) / list.length;
        for (const p of list) rel.push({ ...p, draftMean: mean, rel: mean > 0 ? p.points / mean : 0 });
    }
    const graded = rel.filter(p => p.season <= gradedThrough);
    const expectedRel = overall => {
        const near = graded.filter(p => Math.abs(p.overall - overall) <= 1);
        return near.length ? near.reduce((s, p) => s + p.rel, 0) / near.length : null;
    };
    const rows = graded.map(p => {
        const exp = expectedRel(p.overall);
        return { ...p, expected: exp * p.draftMean, over: (p.rel - exp) * p.draftMean };
    });
    const classes = new Map();
    for (const r of rows) {
        const c = classes.get(r.team) || { team: r.team, over: 0, picks: 0 };
        c.over += r.over;
        c.picks += 1;
        classes.set(r.team, c);
    }
    return {
        seasons: [...new Set(rows.map(r => r.season))].sort((a, b) => a - b),
        classes: [...classes.values()].sort((a, b) => b.over - a.over),
        steals: [...rows].sort((a, b) => b.over - a.over).slice(0, 5),
        busts: [...rows].sort((a, b) => a.over - b.over).slice(0, 5),
    };
}

// ---- Registry ----

function playerTok(entry, model, opts, extra) {
    return {
        meta: model.meta || null,
        sub: entry.blurb,
        version: `${entry.id}-${model.version || ''}`,
        involves: model.involves || [],
        interest: 0.6,
        body: () => entry.render(model, { highlight: opts.spotlight, compact: true }),
        ...extra,
    };
}

function playerName(model, code) {
    return model.names?.[code] || code;
}

const signed = v => `${v > 0 ? '+' : ''}${Math.round(v)}`;

const PLAYER_CHARTS = [
    {
        id: 'weekly-awards',
        family: 'players',
        scope: 'week',
        title: 'Weekly awards',
        blurb: 'MVP, high and low scores, blowout, nail-biter, upset and bench heroics.',
        home: { view: 'matchups', subview: 'week', anchor: 'chart-weekly-awards' },
        compute(ctx) {
            const awards = ctx?.awardsInput || (ctx?.facts?.facts ? {
                awards: ctx.facts.facts.awards,
                season: ctx.season,
                week: ctx.facts.facts.week ?? ctx.completedWeek,
                names: ctx.names || ctx.facts.facts.names || {},
            } : null);
            return awards?.awards?.length ? { ...awards, involves: awards.awards.map(a => a.team) } : null;
        },
        render(model, { highlight }) {
            const name = code => playerName(model, code);
            const what = a => {
                if (a.player) return { who: a.player, sub: `${a.position || ''} for ${name(a.team)}`.trim(), value: chartNum(a.value) };
                if (a.id === 'blowout' || a.id === 'nail_biter' || a.id === 'upset') {
                    return { who: name(a.team), sub: `${chartNum(a.score[0])}–${chartNum(a.score[1])} over ${name(a.opp)}${a.projected ? `, projected to lose by ${chartNum(Math.abs(a.value))}` : ''}`, value: a.id === 'upset' ? `${chartNum(a.value)}` : `+${chartNum(a.value)}` };
                }
                if (a.id === 'left_on_bench') return { who: name(a.team), sub: `Scored ${chartNum(a.score)}, could have had ${chartNum(a.optimal)}`, value: chartNum(a.value) };
                return { who: name(a.team), sub: a.opp ? `vs ${name(a.opp)}` : '', value: chartNum(a.value) };
            };
            return `<ul class="chart-awards">${model.awards.map(a => {
                const w = what(a);
                return `
                    <li class="chart-award award-${chartEsc(a.id)}${highlight && a.team === highlight ? ' is-highlight' : ''}">
                        <span class="chart-award-emoji" aria-hidden="true">${chartEsc(a.emoji)}</span>
                        <span class="chart-award-text">
                            <span class="chart-award-label">${chartEsc(a.label)}</span>
                            <span class="chart-award-who">${chartEsc(w.who)}</span>
                            ${w.sub ? `<span class="chart-award-sub">${chartEsc(w.sub)}</span>` : ''}
                        </span>
                        <span class="chart-award-value">${chartEsc(w.value)}</span>
                    </li>`;
            }).join('')}</ul>`;
        },
        tok(model, opts) {
            const mvp = model.awards.find(a => a.id === 'mvp');
            return playerTok(this, model, opts, {
                pill: 'AWARDS NIGHT',
                pillCls: 'is-awards',
                meta: `${model.season} · WK ${model.week}`,
                title: `Week ${model.week} awards`,
                timely: true,
                interest: 0.95,
                version: `${model.season}-awards-${model.week}`,
                caption: mvp
                    ? `⭐ ${chartNum(mvp.value)} · ${mvp.player}: MVP`
                    : `🏆 ${model.awards.length} awards handed out`,
            });
        },
    },
    {
        id: 'boom-bust',
        family: 'players',
        scope: 'season',
        title: 'Boom or bust',
        blurb: `The swingiest starters (${BOOM_MIN_STARTS}+ starts, ${BOOM_MIN_AVERAGE}+ a game), one dot per week.`,
        home: { view: 'stats', subview: 'leaders', anchor: 'chart-boom-bust' },
        compute(ctx) {
            const input = ctx?.playerInput || (typeof playerChartInput === 'function' ? playerChartInput() : null);
            if (!input?.starts?.length) return null;
            const result = boomBust(input.starts);
            return result.boom.length >= 3 ? { ...input, ...result, involves: [...new Set(result.boom.flatMap(r => r.teams))] } : null;
        },
        render({ boom }, { highlight, compact }) {
            const rows = boom.map(r => ({ id: r.teams.includes(highlight) ? highlight : r.id, label: `${r.name} (${r.position})`, values: r.values }));
            const strip = stripPlot({ title: 'Weekly scores of the swingiest starters', rows, highlight, width: compact ? 420 : 640, valueFmt: v => `${Math.round(v)}` });
            return strip;
        },
        tok(model, opts) {
            const top = model.boom[0];
            return playerTok(this, model, opts, {
                version: `${model.season}-boom-${model.week}`,
                interest: 0.65,
                caption: `🎢 ${top.name}: anywhere from ${Math.round(Math.min(...top.values))} to ${Math.round(Math.max(...top.values))}`,
            });
        },
    },
    {
        id: 'one-man-armies',
        family: 'players',
        scope: 'season',
        title: 'One-man armies',
        blurb: 'Each team\'s top scorer and his share of its starters\' points.',
        home: { view: 'stats', subview: 'team', anchor: 'chart-one-man-armies' },
        compute(ctx) {
            const input = ctx?.playerInput || (typeof playerChartInput === 'function' ? playerChartInput() : null);
            if (!input?.starts?.length) return null;
            const rows = oneManArmies(input.starts);
            return rows.length ? { ...input, rows, involves: rows.map(r => r.team) } : null;
        },
        render(model, { highlight }) {
            return barList({
                title: 'Top scorer\'s share of team points',
                highlight,
                max: Math.max(...model.rows.map(r => r.share)),
                valueFmt: v => `${Math.round(v * 100)}%`,
                rows: model.rows.map(r => ({
                    id: r.team,
                    label: r.player,
                    tag: playerName(model, r.team),
                    sub: `${r.position}, ${Math.round(r.points)} of ${Math.round(r.total)} points`,
                    value: r.share,
                })),
            });
        },
        tok(model, opts) {
            const top = model.rows[0];
            return playerTok(this, model, opts, {
                version: `${model.season}-armies-${model.week}`,
                caption: `💪 ${top.player} has scored ${Math.round(top.share * 100)}% of ${chartWho(opts, { label: c => playerName(model, c) }, top.team)}'s points`,
            });
        },
    },
    {
        id: 'trade-grades',
        family: 'players',
        scope: 'alltime',
        title: 'Trade report cards',
        blurb: 'Trade GPA: every trade graded on a curve by points gained over the other side.',
        home: { view: 'transactions', anchor: 'chart-trade-grades' },
        compute(ctx) {
            const input = ctx?.tradeInput || (typeof tradeChartInput === 'function' ? tradeChartInput() : null);
            if (!input || input.trades.length < 3) return null;
            const result = tradeGrades(input.trades);
            return { ...input, ...result, involves: result.teams.map(t => t.team) };
        },
        render(model, { highlight }) {
            return barList({
                title: 'Trade GPA',
                highlight,
                max: 4.3,
                valueFmt: v => v.toFixed(2),
                rows: model.teams.map(t => ({
                    id: t.team,
                    label: playerName(model, t.team),
                    sub: `${t.trades} trade${t.trades === 1 ? '' : 's'} · ${t.grades.join(' ')} · best ${signed(t.best.margin)} vs ${playerName(model, t.best.other)}`,
                    value: t.gpa,
                })),
            });
        },
        tok(model, opts) {
            const top = model.teams[0];
            const f = model.fleecing;
            return playerTok(this, model, opts, {
                interest: 0.75,
                version: `trades-${model.trades.length}`,
                caption: f && f.margin > 0
                    ? `🦊 Biggest fleecing: ${playerName(model, f.team)} won a trade with ${playerName(model, f.other)} by ${Math.round(f.margin)} points`
                    : `🎓 ${playerName(model, top.team)} has the best trade GPA (${top.gpa.toFixed(2)})`,
            });
        },
    },
    {
        id: 'costliest-drops',
        family: 'players',
        scope: 'alltime',
        title: 'Costliest drops',
        blurb: 'Points a dropped player went on to score starting for someone else.',
        home: { view: 'transactions', anchor: 'chart-costliest-drops' },
        compute(ctx) {
            const input = ctx?.dropsInput || (typeof dropsChartInput === 'function' ? dropsChartInput() : null);
            return input?.drops?.length ? { ...input, involves: input.drops.map(d => d.team) } : null;
        },
        render(model, { highlight }) {
            return barList({
                title: 'Points scored elsewhere after being dropped',
                highlight,
                valueFmt: v => `${Math.round(v)}`,
                rows: model.drops.map(d => ({
                    id: d.team,
                    label: d.player,
                    tag: playerName(model, d.team),
                    sub: `dropped Week ${d.week} ${d.season}, then ${d.starts} starts for ${d.to.map(t => playerName(model, t)).join(', ')}`,
                    value: d.points,
                })),
            });
        },
        tok(model, opts) {
            const top = model.drops[0];
            return playerTok(this, model, opts, {
                interest: 0.7,
                version: `drops-${model.version}`,
                caption: `🗑️ ${playerName(model, top.team)} dropped ${top.player}, who scored ${Math.round(top.points)} for someone else`,
            });
        },
    },
    {
        id: 'draft-value',
        family: 'players',
        scope: 'alltime',
        scopeText: model => `${model.seasons[0]}–${model.seasons[model.seasons.length - 1]} drafts`,
        title: 'Draft value over slot',
        blurb: 'Points each franchise\'s picks produced vs what those slots usually return.',
        home: { view: 'drafts', subview: 'history', anchor: 'chart-draft-value' },
        compute(ctx) {
            const input = ctx?.draftInput || (typeof draftChartInput === 'function' ? draftChartInput() : null);
            if (!input?.picks?.length) return null;
            const result = draftValueOverSlot(input.picks, input.gradedThrough);
            return result.classes.length ? { ...input, ...result, involves: result.classes.map(c => c.team) } : null;
        },
        render(model, { highlight, compact }) {
            const bars = divergingBars({
                title: 'Draft points over slot',
                highlight,
                valueFmt: signed,
                rows: model.classes.map(c => ({ id: c.team, label: playerName(model, c.team), sub: `${c.picks} graded picks`, value: Math.round(c.over) })),
            });
            if (compact) return bars;
            const pickRow = p => ({ id: p.team, label: p.player, tag: playerName(model, p.team), sub: `${p.season} pick ${p.overall}, ${Math.round(p.points)} points`, value: Math.round(p.over), display: signed(p.over) });
            return `${bars}
                <div class="chart-columns">
                    <div><h4 class="chart-subtitle">Steals</h4>${barList({ highlight, rows: model.steals.map(pickRow) })}</div>
                    <div><h4 class="chart-subtitle">Busts</h4>${barList({ highlight, rows: model.busts.map(p => ({ ...pickRow(p), value: Math.abs(Math.round(p.over)) })) })}</div>
                </div>`;
        },
        tok(model, opts) {
            const steal = model.steals[0];
            return playerTok(this, model, opts, {
                interest: 0.7,
                version: `draft-value-${model.seasons.join('-')}`,
                caption: `💎 Steal of the drafts: ${steal.player} at pick ${steal.overall} (${signed(steal.over)})`,
            });
        },
    },
];

PLAYER_CHARTS.forEach(chart => registerChart(chart));

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        standardDeviation, boomBust, oneManArmies, TRADE_GRADES, tradeGrade, tradeGrades,
        draftValueOverSlot, PLAYER_CHARTS,
    };
}

// ---- Browser inputs ----

function chartNames() {
    return (data?.charts || sharedData?.charts)?.names || {};
}

// Every started, scored game of the season on screen.
function playerChartInput() {
    if (!data?.weeks?.length) return null;
    const lastWeek = seasonFormat().lastWeek;
    const done = (data.weeks || []).filter(w => w.has_scores && w.games_final !== false && w.week <= lastWeek);
    const starts = [];
    for (const w of done) {
        for (const m of w.matchups || []) {
            for (const team of [m.team1, m.team2]) {
                if (!team?.abbrev) continue;
                for (const p of team.roster || []) {
                    if (!p.starter || typeof p.score !== 'number' || p.on_bye) continue;
                    starts.push({ key: `${p.name}|${p.position}`, name: p.name, position: p.position, team: team.abbrev, score: p.score });
                }
            }
        }
    }
    return {
        season: Number(data.season),
        week: done.at(-1)?.week || 0,
        names: chartNames(),
        starts,
    };
}

let tradeInputCache = null;

function tradeChartInput() {
    const transactions = data?.transactions || sharedData?.transactions;
    if (!transactions?.length) return null;
    if (tradeInputCache?.source === transactions) return tradeInputCache.input;
    const trades = [];
    for (const tx of transactions) {
        const verdict = tradeVerdict(tx);
        if (!verdict || verdict.unparsed || verdict.untracked || verdict.provisional) continue;
        trades.push({ id: transactionAnchorId(tx), season: tx.season, sides: verdict.sides.map(s => ({ team: s.team, total: s.total })) });
    }
    const input = { trades, names: chartNames() };
    tradeInputCache = { source: transactions, input };
    return input;
}

function dropsChartInput() {
    const charts = data?.charts || sharedData?.charts;
    if (!charts?.costliest_drops) return null;
    return { drops: charts.costliest_drops, names: charts.names || {}, version: `${charts.season}-${charts.completed_through}` };
}

let draftInputCache = null;

function draftChartInput() {
    const drafts = data?.drafts || sharedData?.drafts;
    if (!drafts?.length) return null;
    if (draftInputCache?.source === drafts) return draftInputCache.input;
    const picks = [];
    for (const draft of drafts) {
        if (!/Offseason Draft/i.test(draft.name || '') || !Number.isFinite(Number(draft.year))) continue;
        const perRound = draft.rounds?.[0]?.picks?.length || 0;
        for (const round of draft.rounds || []) {
            for (const pick of round.picks || []) {
                if (!pick.player || pick.player === 'PASS') continue;
                const team = draftTeamCode(pick.team, draft);
                const profile = getPlayerCareerProfile(pick.player, pick.position || '');
                if (!team || !profile) continue;
                picks.push({
                    season: Number(draft.year),
                    draft: draft.name,
                    overall: (Number(round.round) - 1) * perRound + Number(pick.pick),
                    team,
                    player: profile.name || pick.player,
                    points: draftPickFranchisePerformance(profile, draft, team).points || 0,
                });
            }
        }
    }
    const input = { picks, gradedThrough: Number(LIVE_SEASON) - 2, names: chartNames() };
    draftInputCache = { source: drafts, input };
    return input;
}

function playerSections(ids, ctx = {}) {
    const highlight = myTeamAbbrev();
    return ids.map(id => renderChartSection(id, ctx, { highlight })).join('');
}

function renderPlayerStatsCharts() {
    const leaders = document.getElementById('stats-leaders-charts');
    if (leaders) leaders.innerHTML = playerSections(['boom-bust']);
    const teams = document.getElementById('team-stats-player-charts');
    if (teams) teams.innerHTML = playerSections(['one-man-armies']);
}

function renderTransactionCharts() {
    const slot = document.getElementById('transactions-charts');
    if (slot) slot.innerHTML = playerSections(['trade-grades', 'costliest-drops']);
}

function renderDraftCharts() {
    const slot = document.getElementById('drafts-charts');
    if (slot) slot.innerHTML = playerSections(['draft-value']);
}
