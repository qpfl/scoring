// Managers & rivalries charts (Phase 4 of docs/PLAN_qpfltok_and_charts.md).
//
// Loaded after charts-luck.js, before app.js. These read the cross-season
// blocks scripts/export_charts.py writes to data/shared/charts.json (Elo,
// fingerprints, head-to-head, streaks, scores, season arcs) plus
// hall_of_fame.json's owner stats. Everything here is pure over a plain
// input object (tests/test_manager_charts.py); managerChartInput() at the
// bottom builds it in the browser.
//
// Charts and where they live:
//   elo, head-to-head, score-distribution → Hall of Fame → Franchises
//   fingerprints, win-rings               → Hall of Fame → Owners
//   streaks                               → Hall of Fame → Records
//   nemeses, season-arcs                  → Teams → a team's Hall of Fame

/* eslint-disable no-unused-vars */

function managerName(input, code) {
    return input.names?.[code] || code;
}

function ordinal(n) {
    const tail = n % 100;
    const suffix = tail >= 11 && tail <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th');
    return `${n}${suffix}`;
}

function winPctLevel(pct) {
    return pct >= 0.7 ? 'lvl-4' : pct >= 0.55 ? 'lvl-3' : pct > 0.45 ? 'lvl-2' : pct > 0.3 ? 'lvl-1' : 'lvl-0';
}

function recordText([w, l, t]) {
    return `${w}-${l}${t ? `-${t}` : ''}`;
}

// A franchise's record against each opponent, with nemesis (worst win %)
// and favorite victim (best), each needing four games.
const NEMESIS_MIN_GAMES = 4;

function franchiseRivals(h2h, team) {
    const rows = Object.entries(h2h?.[team] || {}).map(([opp, rec]) => {
        const games = rec[0] + rec[1] + rec[2];
        return { opp, rec, games, pct: games ? (rec[0] + rec[2] / 2) / games : 0.5 };
    }).filter(r => r.games);
    const eligible = rows.filter(r => r.games >= NEMESIS_MIN_GAMES);
    const byPct = [...eligible].sort((a, b) => a.pct - b.pct || b.games - a.games);
    return {
        rows: rows.sort((a, b) => b.pct - a.pct || b.games - a.games),
        nemesis: byPct[0] || null,
        victim: byPct[byPct.length - 1] || null,
    };
}

// Which past season a team's current one most resembles, by wins through
// the same week.
function closestArc(arcs, season, week) {
    const now = arcs?.[season]?.[week - 1];
    if (now == null) return null;
    let best = null;
    for (const [other, arc] of Object.entries(arcs)) {
        if (other === String(season) || arc[week - 1] == null) continue;
        const diff = Math.abs(arc[week - 1] - now);
        if (!best || diff < best.diff || (diff === best.diff && Number(other) > Number(best.season))) {
            best = { season: other, diff, then: arc[week - 1], final: arc[arc.length - 1] };
        }
    }
    return best ? { ...best, now } : null;
}

function managerTok(entry, model, opts, extra) {
    return {
        meta: 'ALL-TIME',
        sub: entry.blurb,
        version: `${entry.id}-${model.input.version}`,
        involves: model.input.franchises,
        interest: 0.6,
        body: () => entry.render(model, { highlight: opts.spotlight, compact: true }),
        ...extra,
    };
}

function managerInputFor(ctx) {
    return ctx?.managerInput || (typeof managerChartInput === 'function' ? managerChartInput() : null);
}

const MANAGER_CHARTS = [
    {
        id: 'elo',
        family: 'managers',
        title: 'Elo ratings',
        blurb: 'Every franchise\'s strength since 2020: wins over strong teams and big margins move it most, playoff games weigh more, and each season starts a third of the way back to 1500.',
        home: { view: 'history', subview: 'records', anchor: 'chart-elo' },
        compute(ctx) {
            const input = managerInputFor(ctx);
            const elo = input?.charts?.elo;
            return elo?.labels?.length >= 2 ? { input, elo } : null;
        },
        render({ input, elo }, { highlight, compact }) {
            // Ten lines over seven seasons: with no team to follow, follow the
            // top-rated one so a line stands out (hover picks any other).
            const leader = Object.entries(elo.current).sort((a, b) => b[1] - a[1])[0]?.[0];
            return lineChart({
                title: 'Elo rating by week',
                x: elo.labels,
                refLine: 1500,
                highlight: highlight || leader,
                endLabels: 'all',
                width: compact ? 400 : 720,
                height: compact ? 380 : 300,
                yFmt: v => `${Math.round(v)}`,
                series: Object.entries(elo.series).map(([f, values]) => ({
                    id: f, label: managerName(input, f), short: f, values,
                })),
            });
        },
        tok(model, opts) {
            const { input, elo } = model;
            const ranked = Object.entries(elo.current).sort((a, b) => b[1] - a[1]);
            const spot = opts.spotlight && ranked.findIndex(([f]) => f === opts.spotlight);
            return managerTok(this, model, opts, {
                interest: 0.8,
                caption: spot != null && spot >= 0 && opts.spotlight
                    ? `📊 ${managerName(input, opts.spotlight)} is rated ${Math.round(ranked[spot][1])}, ${ordinal(spot + 1)} in the league`
                    : `👑 ${managerName(input, ranked[0][0])} is the top-rated team at ${Math.round(ranked[0][1])}`,
            });
        },
    },
    {
        id: 'head-to-head',
        family: 'managers',
        title: 'Head-to-head grid',
        blurb: 'Every franchise\'s all-time record against every other, regular season and playoffs. Read across a row.',
        home: { view: 'history', subview: 'records', anchor: 'chart-head-to-head' },
        compute(ctx) {
            const input = managerInputFor(ctx);
            const h2h = input?.charts?.head_to_head;
            if (!h2h || Object.keys(h2h).length < 2) return null;
            const teams = Object.keys(h2h).sort((a, b) => managerName(input, a).localeCompare(managerName(input, b)));
            let lopsided = null;
            for (const team of teams) {
                for (const [opp, rec] of Object.entries(h2h[team])) {
                    const games = rec[0] + rec[1] + rec[2];
                    if (games < NEMESIS_MIN_GAMES) continue;
                    const edge = rec[0] - rec[1];
                    if (!lopsided || edge > lopsided.edge) lopsided = { team, opp, rec, edge };
                }
            }
            return { input, h2h, teams, lopsided };
        },
        render({ input, h2h, teams }, { highlight }) {
            const cells = teams.flatMap(team => teams.filter(opp => opp !== team && h2h[team][opp]).map(opp => {
                const rec = h2h[team][opp];
                const games = rec[0] + rec[1] + rec[2];
                const pct = (rec[0] + rec[2] / 2) / games;
                return {
                    x: opp,
                    y: managerName(input, team),
                    cls: `${winPctLevel(pct)}${highlight && (team === highlight || opp === highlight) ? ' is-highlight' : ''}`,
                    text: recordText(rec),
                    tip: `${managerName(input, team)} vs ${managerName(input, opp)}: ${recordText(rec)}, ${Math.round(rec[3])}–${Math.round(rec[4])} in points`,
                };
            }));
            return heatGrid({
                label: 'All-time head-to-head records',
                cells,
                xDomain: teams,
                yDomain: teams.map(team => managerName(input, team)),
                cellSize: 44,
                table: {
                    caption: 'Head-to-head records',
                    head: ['', ...teams],
                    rows: teams.map(team => [managerName(input, team), ...teams.map(opp => (h2h[team][opp] ? recordText(h2h[team][opp]) : '–'))]),
                },
            });
        },
        tok(model, opts) {
            const { input, lopsided } = model;
            return managerTok(this, model, opts, {
                interest: 0.75,
                caption: lopsided
                    ? `😤 ${managerName(input, lopsided.team)} is ${recordText(lopsided.rec)} against ${managerName(input, lopsided.opp)}`
                    : '🤝 Every rivalry, every record',
            });
        },
    },
    {
        id: 'score-distribution',
        family: 'managers',
        title: 'Score distributions',
        blurb: 'Every regular-season score each franchise has posted, with its median marked.',
        home: { view: 'history', subview: 'records', anchor: 'chart-score-distribution' },
        compute(ctx) {
            const input = managerInputFor(ctx);
            const scores = input?.charts?.scores;
            if (!scores || !Object.keys(scores).length) return null;
            const rows = Object.entries(scores)
                .map(([f, values]) => ({ id: f, label: managerName(input, f), values, median: median(values) }))
                .sort((a, b) => b.median - a.median);
            return { input, rows };
        },
        render({ rows }, { highlight, compact }) {
            return stripPlot({ title: 'Regular-season scores', rows, highlight, width: compact ? 400 : 640, valueFmt: v => `${Math.round(v)}` });
        },
        tok(model, opts) {
            const { input, rows } = model;
            return managerTok(this, model, opts, {
                caption: `📦 ${managerName(input, rows[0].id)} has the highest median score, ${Math.round(rows[0].median)}`,
            });
        },
    },
    {
        id: 'fingerprints',
        family: 'managers',
        title: 'Manager fingerprints',
        blurb: 'Six traits for every owner with a full season, as a percentile among owners: 100 is the best in league history.',
        home: { view: 'history', subview: 'records', anchor: 'chart-fingerprints' },
        compute(ctx) {
            const input = managerInputFor(ctx);
            const fp = input?.charts?.fingerprints;
            return fp?.owners?.length >= 2 ? { input, fp } : null;
        },
        render({ fp }, { highlight, compact }) {
            if (compact) {
                const owner = fp.owners.find(o => o.code === highlight)
                    || [...fp.owners].sort((a, b) => b.pct.scoring - a.pct.scoring)[0];
                return `<p class="tok-fingerprint-owner">${chartEsc(owner.name)}</p>${barList({
                    max: 100,
                    valueFmt: v => `${Math.round(v)}`,
                    rows: fp.traits.filter(t => owner.pct[t.id] != null).map(t => ({
                        id: t.id, label: t.label, sub: t.about, value: owner.pct[t.id] * 100,
                    })),
                })}`;
            }
            const traits = fp.traits.map(t => t.label);
            const owners = [...fp.owners].sort((a, b) => b.games - a.games || a.name.localeCompare(b.name));
            const cells = owners.flatMap(o => fp.traits.filter(t => o.pct[t.id] != null).map(t => ({
                x: t.label,
                y: o.name,
                cls: `${winPctLevel(o.pct[t.id])}${highlight && o.code === highlight ? ' is-highlight' : ''}`,
                text: String(Math.round(o.pct[t.id] * 100)),
                tip: `${o.name}, ${t.label}: ${fingerprintValue(t.id, o.values[t.id])} (${t.about})`,
            })));
            return heatGrid({
                label: 'Manager fingerprints',
                cells,
                xDomain: traits,
                yDomain: owners.map(o => o.name),
                cellSize: 40,
                table: {
                    caption: 'Manager fingerprints',
                    head: ['', ...traits, 'Games'],
                    rows: owners.map(o => [o.name, ...fp.traits.map(t => fingerprintValue(t.id, o.values[t.id])), o.games]),
                },
            });
        },
        tok(model, opts) {
            const { fp } = model;
            const owner = fp.owners.find(o => o.code === opts.spotlight)
                || [...fp.owners].sort((a, b) => b.pct.scoring - a.pct.scoring)[0];
            const best = fp.traits.filter(t => owner.pct[t.id] != null)
                .sort((a, b) => owner.pct[b.id] - owner.pct[a.id]).slice(0, 2).map(t => t.label);
            return managerTok(this, model, opts, {
                interest: 0.75,
                involves: [owner.code],
                caption: `🧬 ${owner.name}: best at ${best.join(' and ')}`,
            });
        },
    },
    {
        id: 'win-rings',
        family: 'managers',
        title: 'Win % rings',
        blurb: 'Every owner\'s career win percentage, with record and rings.',
        home: { view: 'history', subview: 'records', anchor: 'chart-win-rings' },
        compute(ctx) {
            const input = managerInputFor(ctx);
            const rows = (input?.ownerStats || [])
                .filter(o => Number(o.Seasons) >= 2)
                .map(o => ({
                    code: o.Code,
                    name: o.Owner,
                    pct: parseFloat(o['Win%']) / 100,
                    record: o.Record,
                    rings: Number(o.Rings) || 0,
                }))
                .filter(o => Number.isFinite(o.pct))
                .sort((a, b) => b.pct - a.pct);
            return rows.length >= 2 ? { input, rows } : null;
        },
        render({ rows }, { highlight }) {
            return `<div class="chart-ring-grid">${rows.map(r => ringStat({
                id: r.code,
                highlight,
                pct: r.pct,
                center: `${Math.round(r.pct * 100)}%`,
                label: r.name,
                sub: `${r.record}${r.rings ? ` · ${'💍'.repeat(r.rings)}` : ''}`,
            })).join('')}</div>`;
        },
        tok(model, opts) {
            const { rows } = model;
            return managerTok(this, model, opts, {
                caption: `💍 ${rows[0].name} wins ${Math.round(rows[0].pct * 100)}% of games`,
            });
        },
    },
    {
        id: 'streaks',
        family: 'managers',
        title: 'Streaks',
        blurb: 'The longest regular-season winning and losing streaks, carried across seasons. Ties end a streak.',
        home: { view: 'history', subview: 'records', anchor: 'chart-streaks' },
        compute(ctx) {
            const input = managerInputFor(ctx);
            const streaks = input?.charts?.streaks;
            return streaks?.wins?.length ? { input, streaks } : null;
        },
        render({ input, streaks }, { highlight, compact }) {
            const span = r => `${r.start[0]} W${r.start[1]} – ${r.end[0] === r.start[0] ? '' : `${r.end[0]} `}W${r.end[1]}${r.active ? ' · active' : ''}`;
            const list = (rows, title) => barList({
                title,
                highlight,
                valueFmt: v => `${v}`,
                rows: rows.map(r => ({ id: r.franchise, label: managerName(input, r.franchise), sub: span(r), value: r.length })),
            });
            const wins = list(streaks.wins.slice(0, compact ? 5 : undefined), 'Longest winning streaks');
            if (compact) return wins;
            return `<div class="chart-columns">
                <div><h4 class="chart-subtitle">Winning streaks</h4>${wins}</div>
                <div><h4 class="chart-subtitle">Losing streaks</h4>${list(streaks.losses, 'Longest losing streaks')}</div>
            </div>`;
        },
        tok(model, opts) {
            const { input, streaks } = model;
            const hot = Object.entries(streaks.current || {})
                .filter(([, [kind]]) => kind === 'W')
                .sort((a, b) => b[1][1] - a[1][1])[0];
            const top = streaks.wins[0];
            return managerTok(this, model, opts, {
                interest: 0.7,
                caption: hot && hot[1][1] >= 3
                    ? `🔥 ${managerName(input, hot[0])} has won ${hot[1][1]} straight`
                    : `🏃 The record: ${managerName(input, top.franchise)}, ${top.length} straight wins`,
            });
        },
    },
    {
        id: 'nemeses',
        family: 'managers',
        title: 'Nemeses',
        blurb: 'All-time record against every franchise (nemesis and favorite victim need four games), and the opposing players who have scored the most against this team.',
        home: { view: 'teams', subview: 'history', anchor: 'chart-nemeses' },
        compute(ctx) {
            const input = managerInputFor(ctx);
            const team = ctx?.team || ctx?.spotlight;
            if (!input?.charts?.head_to_head || !team) return null;
            const rivals = franchiseRivals(input.charts.head_to_head, team);
            if (!rivals.rows.length) return null;
            return { input, team, ...rivals, players: input.charts.player_nemeses?.[team] || [] };
        },
        render({ input, rows, nemesis, victim, players }, { highlight, compact }) {
            const bars = divergingBars({
                title: 'Wins minus losses against each franchise',
                highlight: compact ? null : highlight,
                valueFmt: v => `${v > 0 ? '+' : ''}${v}`,
                rows: rows.map(r => ({
                    id: r.opp,
                    label: managerName(input, r.opp),
                    sub: r === nemesis ? 'Nemesis' : r === victim ? 'Favorite victim' : `${r.games} game${r.games === 1 ? '' : 's'}`,
                    value: r.rec[0] - r.rec[1],
                    display: recordText(r.rec),
                })),
            });
            if (compact || !players.length) return bars;
            return `${bars}
                <h4 class="chart-subtitle">Players who scored the most against them</h4>
                ${barList({
                    valueFmt: v => `${Math.round(v)}`,
                    rows: players.map(([name, position, points, starts]) => ({ label: name, sub: `${position} · ${starts} start${starts === 1 ? '' : 's'}`, value: points })),
                })}`;
        },
        tok(model, opts) {
            const { input, team, nemesis, victim } = model;
            return managerTok(this, model, opts, {
                interest: 0.85,
                involves: [team],
                version: `nemeses-${team}-${model.input.version}`,
                home: { view: 'teams', subview: `history/${encodeURIComponent(team)}`, anchor: 'chart-nemeses' },
                caption: nemesis && nemesis.pct < 0.5
                    ? `😈 ${managerName(input, team)}'s nemesis: ${managerName(input, nemesis.opp)} (${recordText(nemesis.rec)})`
                    : victim
                        ? `🍽️ ${managerName(input, team)}'s favorite victim: ${managerName(input, victim.opp)} (${recordText(victim.rec)})`
                        : `🤝 ${managerName(input, team)} against everyone`,
            });
        },
    },
    {
        id: 'season-arcs',
        family: 'managers',
        title: 'Season arcs',
        blurb: 'Wins piling up week by week in every season, this one in color.',
        home: { view: 'teams', subview: 'history', anchor: 'chart-season-arcs' },
        compute(ctx) {
            const input = managerInputFor(ctx);
            const team = ctx?.team || ctx?.spotlight;
            const arcs = team && input?.charts?.season_arcs?.[team];
            if (!arcs || Object.keys(arcs).length < 2) return null;
            const season = String(input.season);
            const week = arcs[season]?.length || 0;
            return { input, team, arcs, season, closest: week ? closestArc(arcs, season, week) : null };
        },
        render({ arcs, season }, { compact }) {
            const weeks = Math.max(...Object.values(arcs).map(a => a.length));
            return lineChart({
                title: 'Cumulative wins by week, every season',
                x: Array.from({ length: weeks }, (_, i) => `W${i + 1}`),
                highlight: arcs[season] ? season : null,
                endLabels: 'all',
                width: compact ? 400 : 640,
                height: compact ? 380 : 280,
                yFmt: v => `${v}`,
                series: Object.entries(arcs).map(([s, values]) => ({ id: s, label: s, short: s, values })),
            });
        },
        tok(model, opts) {
            const { input, team, closest } = model;
            return managerTok(this, model, opts, {
                interest: 0.7,
                involves: [team],
                version: `season-arcs-${team}-${model.input.version}`,
                home: { view: 'teams', subview: `history/${encodeURIComponent(team)}`, anchor: 'chart-season-arcs' },
                caption: closest
                    ? `📈 ${managerName(input, team)} has ${closest.now} wins, like ${closest.season} (${closest.final} by the end)`
                    : `📈 Every season ${managerName(input, team)} has played`,
            });
        },
    },
];

MANAGER_CHARTS.forEach(chart => registerChart(chart));

function fingerprintValue(trait, value) {
    if (value == null) return '–';
    if (trait === 'scoring') return `${chartNum(value)} ppg`;
    if (trait === 'consistency') return `±${chartNum(value)}`;
    if (trait === 'luck') return `${value > 0 ? '+' : ''}${chartNum(value, 2)} wins/game`;
    return `${Math.round(value * 100)}%`;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { franchiseRivals, closestArc, ordinal, winPctLevel, fingerprintValue, MANAGER_CHARTS };
}

// ---- Browser inputs ----

function managerChartInput() {
    const charts = data?.charts || sharedData?.charts;
    const hof = data?.hall_of_fame || sharedData?.hall_of_fame;
    if (!charts?.version || charts.version < 2) return hof ? { names: {}, ownerStats: hof.owner_stats || [], franchises: [], version: '0' } : null;
    return {
        charts,
        names: charts.names || {},
        ownerStats: hof?.owner_stats || [],
        franchises: Object.keys(charts.head_to_head || {}),
        season: Number(charts.season),
        version: `${charts.season}-${charts.completed_through}`,
    };
}

function managerSections(ids, ctx = {}) {
    const input = managerChartInput();
    if (!input) return '';
    const highlight = myTeamAbbrev();
    return ids.map(id => renderChartSection(id, { ...ctx, managerInput: input }, { highlight })).join('');
}
