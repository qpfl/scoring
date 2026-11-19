// This week in history and Season Wrapped.
//
// Loaded after charts-players.js, before app.js. Both read charts.json
// (scripts/export_charts.py): `week_history` (each week number's top score,
// low score, blowout, nail-biter and MVP in every past season) and `wrapped`
// (a year in review per franchise per season). The pure parts are tested in
// tests/test_season_charts.py.
//
//   week-in-history → Matchups → Preview, for the week ahead, and a
//                     QPFLTok "This week" clip
//   season-wrapped  → the top of each team's Hall of Fame (any season, with
//                     season chips), a QPFLTok clip for the spotlight team,
//                     and a Home banner once the live season's title game is in

/* eslint-disable no-unused-vars */

const HISTORY_AWARDS = {
    high_score: { label: 'Top score', emoji: '👑' },
    low_score: { label: 'Low score', emoji: '🧊' },
    blowout: { label: 'Biggest blowout', emoji: '⚔️' },
    nail_biter: { label: 'Closest game', emoji: '😬' },
    mvp: { label: 'MVP', emoji: '⭐' },
};
const HISTORY_ORDER = ['high_score', 'low_score', 'blowout', 'nail_biter', 'mvp'];

// Past seasons' entries for one week number, newest first.
function weekInHistory(weekHistory, week, beforeSeason) {
    return (weekHistory?.[String(week)] || [])
        .filter(entry => entry.season < beforeSeason)
        .sort((a, b) => b.season - a.season);
}

// The single most remarkable thing that ever happened in this week: the
// highest top score.
function weekRecord(entries) {
    let best = null;
    for (const entry of entries) {
        const top = entry.awards.find(a => a.id === 'high_score');
        if (top && (!best || top.value > best.award.value)) best = { season: entry.season, award: top };
    }
    return best;
}

function historyAwardText(a, name) {
    if (a.id === 'mvp') return { who: a.player, sub: `${a.position} for ${name(a.team)}`, value: chartNum(a.value) };
    if (a.id === 'blowout' || a.id === 'nail_biter') {
        return { who: name(a.team), sub: `${chartNum(a.score[0])}–${chartNum(a.score[1])} over ${name(a.opp)}`, value: `+${chartNum(a.value)}` };
    }
    return { who: name(a.team), sub: a.opp ? `vs ${name(a.opp)}` : '', value: chartNum(a.value) };
}

// Each past season's low and high score for this week as a dumbbell: the
// spread of the week at a glance, with who posted each end.
function weekRangeChart(entries, name, { highlight = null, franchiseOf = null, compact = false } = {}) {
    const rows = entries.map(e => ({
        season: e.season,
        high: e.awards.find(a => a.id === 'high_score'),
        low: e.awards.find(a => a.id === 'low_score'),
    })).filter(r => r.high && r.low);
    if (!rows.length) return '';
    const mine = a => highlight && (a.team === highlight || franchiseOf?.(a.team) === highlight);
    const width = compact ? 400 : 640;
    const rowH = compact ? 44 : 36;
    const pad = { left: 44, right: compact ? 70 : 96, top: 6, bottom: 24 };
    const plotW = width - pad.left - pad.right;
    const height = pad.top + rows.length * rowH + pad.bottom;
    const minLow = Math.min(...rows.map(r => r.low.value));
    const maxHigh = Math.max(...rows.map(r => r.high.value));
    // Room left of the lowest score for its label.
    const lo = Math.max(0, Math.floor((minLow - (maxHigh - minLow) * (compact ? 0.2 : 0.45)) / 10) * 10);
    const hi = Math.ceil(maxHigh / 10) * 10;
    const xs = v => pad.left + ((v - lo) / (hi - lo || 1)) * plotW;
    const best = Math.max(...rows.map(r => r.high.value));
    const grid = chartTicks(lo, hi, 5).map(v => `
        <line class="chart-gridline" x1="${chartRound(xs(v))}" y1="${pad.top}" x2="${chartRound(xs(v))}" y2="${pad.top + rows.length * rowH}"/>
        <text class="chart-tick" x="${chartRound(xs(v))}" y="${height - 8}" text-anchor="middle">${v}</text>`).join('');
    const body = rows.map((r, i) => {
        const cy = pad.top + i * rowH + rowH / 2;
        const end = (a, cls, anchor, dx) => `
            <circle class="chart-range-dot ${cls}${mine(a) ? ' is-highlight' : ''}" cx="${chartRound(xs(a.value))}" cy="${chartRound(cy)}" r="6"
                data-tip="${chartEsc(`${r.season}: ${name(a.team)} ${chartNum(a.value)}${a.opp ? ` vs ${name(a.opp)}` : ''}`)}"/>
            <text class="chart-range-label${mine(a) ? ' is-highlight' : ''}" x="${chartRound(xs(a.value) + dx)}" y="${chartRound(cy + 4)}" text-anchor="${anchor}">${chartEsc(compact ? chartNum(a.value) : `${name(a.team)} ${chartNum(a.value)}`)}</text>`;
        return `
            <g class="chart-range-row">
                <text class="chart-tick chart-range-year" x="${pad.left - 10}" y="${chartRound(cy + 4)}" text-anchor="end">${r.season}</text>
                <line class="chart-range-bar" x1="${chartRound(xs(r.low.value))}" y1="${chartRound(cy)}" x2="${chartRound(xs(r.high.value))}" y2="${chartRound(cy)}"/>
                ${end(r.low, 'is-low', 'end', -10)}
                ${end(r.high, `is-high${r.high.value === best ? ' is-record' : ''}`, 'start', 10)}
            </g>`;
    }).join('');
    const svg = chartSvg({ className: 'chart-range', width, height, label: 'Low and high score of this week in every past season', body: grid + body });
    return `<figure class="chart-figure">${svg}<figcaption class="chart-legend"><span class="chart-key is-low"></span>Low score <span class="chart-key is-high"></span>High score</figcaption></figure>`;
}

// The place a franchise finished in a season, from the Hall of Fame's
// season badges (finishPlace, charts-standings.js).
function wrappedFinish(teamHof, team, season, leagueSize) {
    const row = (teamHof?.[team]?.seasons || []).find(s => Number(s.season) === Number(season));
    return row ? finishPlace(row.seasonFinishes, leagueSize) : null;
}

function wrappedSeasons(wrapped, team) {
    return Object.entries(wrapped || {})
        .filter(([, s]) => s.teams?.[team])
        .map(([season, s]) => ({ season: Number(season), complete: Boolean(s.complete) }))
        .sort((a, b) => b.season - a.season);
}

// The season Wrapped opens on: the newest finished one.
function defaultWrappedSeason(wrapped, team) {
    const seasons = wrappedSeasons(wrapped, team);
    return (seasons.find(s => s.complete) || seasons[0])?.season ?? null;
}

function placeText(place) {
    if (place === 1) return 'Champion 🏆';
    if (!place) return '';
    const tail = place % 100;
    const suffix = tail >= 11 && tail <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[place % 10] || 'th');
    return `${place}${suffix} place`;
}

function seasonsInputFor(ctx) {
    return ctx?.seasonsInput || (typeof seasonsChartInput === 'function' ? seasonsChartInput() : null);
}

const SEASON_CHARTS = [
    {
        id: 'week-in-history',
        family: 'week',
        scope: 'alltime',
        scopeText: model => `Week ${model.week}, every season`,
        title: 'This week in history',
        blurb: 'What happened in this week of every past season.',
        home: { view: 'matchups', subview: 'preview', anchor: 'chart-week-in-history' },
        compute(ctx) {
            const input = seasonsInputFor(ctx);
            const week = ctx?.week || ctx?.upcomingWeek || input?.week;
            if (!input?.weekHistory || !week) return null;
            const entries = weekInHistory(input.weekHistory, week, input.season);
            return entries.length ? { input, week, entries } : null;
        },
        render({ input, entries }, { highlight, compact }) {
            const name = code => input.names[code] || code;
            const range = weekRangeChart(entries, name, { highlight, franchiseOf: input.franchiseOf, compact });
            if (compact) return range;
            return `${range}<details class="chart-more"><summary>Every award, every year</summary><ol class="chart-history">${entries.map(entry => `
                <li class="chart-history-season">
                    <h4 class="chart-history-year">${chartEsc(entry.season)} <span>${chartEsc(entry.label)}</span></h4>
                    <ul class="chart-awards">${HISTORY_ORDER.map(id => entry.awards.find(a => a.id === id)).filter(Boolean)
                        .filter(a => !compact || a.id !== 'mvp')
                        .map(a => {
                            const meta = HISTORY_AWARDS[a.id];
                            const t = historyAwardText(a, name);
                            return `
                                <li class="chart-award${highlight && (a.team === highlight || input.franchiseOf?.(a.team) === highlight) ? ' is-highlight' : ''}">
                                    <span class="chart-award-emoji" aria-hidden="true">${meta.emoji}</span>
                                    <span class="chart-award-text">
                                        <span class="chart-award-label">${chartEsc(meta.label)}</span>
                                        <span class="chart-award-who">${chartEsc(t.who)}</span>
                                        <span class="chart-award-sub">${chartEsc(t.sub)}</span>
                                    </span>
                                    <span class="chart-award-value">${chartEsc(t.value)}</span>
                                </li>`;
                        }).join('')}</ul>
                </li>`).join('')}</ol></details>`;
        },
        tok(model, opts) {
            const { input, week, entries } = model;
            const best = weekRecord(entries);
            const name = code => input.names[code] || code;
            return {
                pill: 'THIS WEEK',
                title: `Week ${week} in history`,
                sub: `What happened in Week ${week} of every past season.`,
                version: `week-history-${input.season}-${week}`,
                timely: true,
                interest: 0.8,
                involves: entries.flatMap(e => e.awards.map(a => a.team)),
                caption: best
                    ? `📜 Week ${week}'s best ever: ${name(best.award.team)}'s ${chartNum(best.award.value)} in ${best.season}`
                    : `📜 ${entries.length} seasons of Week ${week}`,
                body: () => this.render(model, { highlight: opts.spotlight, compact: true }),
            };
        },
    },
    {
        id: 'season-wrapped',
        family: 'managers',
        scope: 'season',
        title: 'Season Wrapped',
        blurb: 'A season in review: record and finish, best and worst weeks, MVP, luck, lineup IQ and nemesis.',
        home: { view: 'teams', subview: 'history', anchor: 'chart-season-wrapped' },
        compute(ctx) {
            const input = seasonsInputFor(ctx);
            const team = ctx?.team || ctx?.spotlight;
            if (!input?.wrapped || !team) return null;
            const season = ctx?.wrappedSeason ?? defaultWrappedSeason(input.wrapped, team);
            const year = input.wrapped[String(season)];
            const data_ = year?.teams?.[team];
            if (!data_) return null;
            return {
                input,
                team,
                season: Number(season),
                complete: Boolean(year.complete),
                seasons: wrappedSeasons(input.wrapped, team),
                place: wrappedFinish(input.teamHof, team, season, Object.keys(year.teams).length),
                w: data_,
            };
        },
        render(model, { compact }) {
            const { input, team, season, complete, seasons, place, w } = model;
            const name = code => input.names[code] || code;
            const [wins, losses, ties] = w.record;
            const game = (g, verb) => (g ? `${chartNum(g.score)}–${chartNum(g.opp_score)} ${verb} ${name(g.opp)}, ${g.label}` : '–');
            const tile = (label, value, sub = '', cls = '') => `
                <div class="wrapped-tile ${cls}">
                    <span class="wrapped-label">${chartEsc(label)}</span>
                    <span class="wrapped-value">${chartEsc(value)}</span>
                    ${sub ? `<span class="wrapped-sub">${chartEsc(sub)}</span>` : ''}
                </div>`;
            const finish = w.champion ? 'Champion 🏆' : placeText(place) || (complete ? (w.playoffs ? 'Playoffs' : 'Missed the playoffs') : 'In progress');
            const chips = compact || seasons.length < 2 ? '' : `
                <div class="wrapped-seasons" role="group" aria-label="Wrapped season">
                    ${seasons.map(s => `<button type="button" class="filter-chip${s.season === season ? ' active' : ''}" aria-pressed="${s.season === season}" data-wrapped-team="${chartEsc(team)}" data-wrapped-season="${s.season}">${s.season}</button>`).join('')}
                </div>`;
            return `${chips}
                <div class="wrapped${w.champion ? ' is-champion' : ''}">
                    <div class="wrapped-hero">
                        <span class="wrapped-year">${season} Wrapped${complete ? '' : ' (so far)'}</span>
                        <span class="wrapped-team">${chartEsc(name(team))}</span>
                        <span class="wrapped-record">${wins}-${losses}${ties ? `-${ties}` : ''}</span>
                        <span class="wrapped-finish">${chartEsc(finish)}</span>
                    </div>
                    <div class="wrapped-grid">
                        ${w.mvp ? tile('MVP', w.mvp.name, `${w.mvp.position} · ${chartNum(w.mvp.points)} pts in ${w.mvp.starts} starts`, 'is-mvp') : ''}
                        ${tile('Points per game', chartNum(w.ppg), `${placeText(w.ppg_rank).replace(' place', '')} in the league`)}
                        ${tile('Best week', w.best_week ? chartNum(w.best_week.score) : '–', game(w.best_week, 'vs'))}
                        ${tile('Worst week', w.worst_week ? chartNum(w.worst_week.score) : '–', game(w.worst_week, 'vs'))}
                        ${w.biggest_win ? tile('Biggest win', `+${chartNum(w.biggest_win.score - w.biggest_win.opp_score)}`, game(w.biggest_win, 'over')) : ''}
                        ${w.worst_loss ? tile('Worst loss', `−${chartNum(w.worst_loss.opp_score - w.worst_loss.score)}`, game(w.worst_loss, 'to')) : ''}
                        ${w.lineup_iq != null ? tile('Lineup IQ', `${Math.round(w.lineup_iq * 100)}%`, `${Math.round(w.left_on_bench)} pts left on the bench`) : ''}
                        ${tile('Luck', `${w.luck > 0 ? '+' : ''}${chartNum(w.luck)} wins`, w.luck >= 0 ? 'more than an average schedule' : 'fewer than an average schedule')}
                        ${w.nemesis ? tile('Nemesis', name(w.nemesis.opp), `${w.nemesis.record[0]}-${w.nemesis.record[1]} against them`) : ''}
                        ${w.workhorse ? tile('Workhorse', w.workhorse.name, `${w.workhorse.position} · ${w.workhorse.starts} starts`) : ''}
                    </div>
                </div>`;
        },
        tok(model, opts) {
            const { input, team, season, complete, w } = model;
            const name = code => input.names[code] || code;
            const [wins, losses] = w.record;
            return {
                pill: 'WRAPPED',
                pillCls: 'is-wrapped',
                title: `${name(team)}'s ${season}`,
                sub: complete ? 'The season in review.' : 'The season so far.',
                version: `wrapped-${team}-${season}-${complete}`,
                timely: complete && season === input.liveSeason,
                interest: 0.85,
                involves: [team],
                home: { view: 'teams', subview: `history/${encodeURIComponent(team)}`, anchor: 'chart-season-wrapped' },
                caption: w.champion
                    ? `🏆 ${season}: ${wins}-${losses} and a title`
                    : w.mvp
                        ? `🎁 ${season}: ${wins}-${losses}, carried by ${w.mvp.name} (${Math.round(w.mvp.points)})`
                        : `🎁 ${season}: ${wins}-${losses}`,
                body: () => this.render(model, { compact: true }),
            };
        },
    },
];

SEASON_CHARTS.forEach(chart => registerChart(chart));

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        weekRangeChart,
        HISTORY_AWARDS, weekInHistory, weekRecord, historyAwardText, wrappedFinish, wrappedSeasons,
        defaultWrappedSeason, placeText, SEASON_CHARTS,
    };
}

// ---- Browser inputs ----

function seasonsChartInput() {
    const charts = data?.charts || sharedData?.charts;
    if (!charts?.week_history && !charts?.wrapped) return null;
    const hof = data?.hall_of_fame || sharedData?.hall_of_fame;
    return {
        season: Number(data?.season || charts.season),
        liveSeason: Number(LIVE_SEASON),
        week: typeof previewWeek === 'function' ? previewWeek() : 0,
        names: charts.names || {},
        weekHistory: charts.week_history,
        wrapped: charts.wrapped,
        teamHof: hof?.team_hall_of_fame || {},
    };
}

// Matchups → Preview: the week ahead in past seasons.
function weekHistorySectionHtml(week) {
    return renderChartSection('week-in-history', { week }, { highlight: myTeamAbbrev() });
}

// A team's Wrapped, for its Hall of Fame page.
function wrappedSectionHtml(team, season = null) {
    const ctx = { team };
    if (season != null) ctx.wrappedSeason = season;
    return renderChartSection('season-wrapped', ctx);
}

// Season chips swap the Wrapped card in place.
if (typeof document !== 'undefined') {
    document.addEventListener('click', event => {
        const chip = event.target.closest?.('[data-wrapped-season]');
        if (!chip) return;
        const section = chip.closest('.chart-section');
        if (!section) return;
        const html = wrappedSectionHtml(chip.dataset.wrappedTeam, Number(chip.dataset.wrappedSeason));
        if (html) section.outerHTML = html;
    });
}

// Home: once the live season's title game is in, a banner to each
// manager's Wrapped until they open it.
async function renderHomeWrappedBanner() {
    const slot = document.getElementById('home-wrapped-banner');
    if (!slot) return;
    slot.hidden = true;
    if (!data || data.season !== LIVE_SEASON || completedThroughWeek() < seasonFormat().lastWeek) return;
    try {
        await ensureSharedResource('charts');
    } catch {
        return;
    }
    const year = sharedData.charts?.wrapped?.[String(LIVE_SEASON)];
    if (!year?.complete) return;
    const key = `qpfl.wrapped.seen.${LIVE_SEASON}`;
    try {
        if (localStorage.getItem(key)) return;
    } catch {
        // Storage blocked: show the banner anyway.
    }
    const team = myTeamAbbrev();
    const route = team ? `#teams/history/${encodeURIComponent(team)}?section=chart-season-wrapped` : '#teams/history?section=chart-season-wrapped';
    slot.href = route;
    slot.dataset.route = route;
    slot.innerHTML = `<span class="home-tok-brand">🎁 ${LIVE_SEASON} Wrapped is here</span><span class="home-tok-text">${team ? 'Your season in review' : 'Every team\'s season in review'}</span><span class="home-tok-arrow" aria-hidden="true">→</span>`;
    slot.hidden = false;
    slot.addEventListener('click', () => {
        try {
            localStorage.setItem(key, '1');
        } catch {
            // Fine: it just shows again next time.
        }
    }, { once: true });
}
