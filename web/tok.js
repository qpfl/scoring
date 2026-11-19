// QPFLTok: a full-screen, swipe-one-card-at-a-time feed of league charts.
//
// Loaded after charts.js and before app.js. The feed is every registered
// chart that has a `tok()` card and something to say this week. Cards about
// the week (recap, record watch, holiday slates) come first, then cards about
// the spotlighted team, then the rest; cards already seen sink to the end.
//
// The top half of this file is pure (feed order, NEW state, holiday and
// milestone parsing, the week cards' compute/tok) so tests load it in node.
// The DOM controller at the bottom runs in the browser and calls into app.js
// (myTeamAbbrev, loadWeeklyFacts, loadPregameNotes, ...) only at runtime.
//
// See docs/PLAN_qpfltok_and_charts.md.

/* eslint-disable no-unused-vars */

const TOK_STORAGE = {
    seen: 'qpfl.tok.seen',
    spotlight: 'qpfl.tok.spotlight',
    hinted: 'qpfl.tok.hinted',
};

// Small, stable string hash (FNV-1a) for the per-day shuffle.
function tokHash(text) {
    let hash = 2166136261;
    for (let i = 0; i < text.length; i += 1) {
        hash ^= text.charCodeAt(i);
        hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0) / 4294967295;
}

function tokIsNew(card, seen) {
    return !seen || seen[card.id] !== card.version;
}

// Feed order. cards: [{ id, version, timely, interest, involves }].
// Unseen cards first, then seen ones; within each, by score: interest (0-1),
// +2 for this week's cards, +0.75 when the spotlight team is involved, plus a
// little jitter seeded by the date so the order changes daily but holds
// steady within a day.
function buildTokFeed(cards, { spotlight = null, seen = {}, dateKey = '' } = {}) {
    const score = card => (card.interest || 0)
        + (card.timely ? 2 : 0)
        + (spotlight && (card.involves || []).includes(spotlight) ? 0.75 : 0)
        + tokHash(`${dateKey}|${card.id}`) * 0.3;
    return [...cards]
        .map(card => ({ card, fresh: tokIsNew(card, seen), score: score(card) }))
        .sort((a, b) => (b.fresh - a.fresh) || (b.score - a.score) || a.card.id.localeCompare(b.card.id))
        .map(entry => ({ ...entry.card, isNew: entry.fresh }));
}

// The date part (YYYY-MM-DD) of a timestamp in US Eastern time, when NFL
// holidays happen.
function tokEasternDate(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return null;
    const parts = new Intl.DateTimeFormat('en-US', {
        timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit',
    }).formatToParts(date);
    const get = type => parts.find(p => p.type === type)?.value;
    return `${get('year')}-${get('month')}-${get('day')}`;
}

function tokThanksgiving(year) {
    const first = new Date(Date.UTC(year, 10, 1)).getUTCDay(); // Nov 1
    const day = 1 + ((4 - first + 7) % 7) + 21; // 4th Thursday
    return `${year}-11-${String(day).padStart(2, '0')}`;
}

const TOK_HOLIDAYS = [
    { key: 'thanksgiving', label: 'Thanksgiving', emoji: '🦃', date: year => tokThanksgiving(year) },
    { key: 'christmas', label: 'Christmas', emoji: '🎄', date: year => `${year}-12-25` },
];

// NFL games on a holiday within `days` of now, from live.json's game_times
// ({ week: { NFL team: kickoff } }). Returns the soonest:
// { key, label, emoji, date, week, teams: [NFL teams playing that day] }.
function tokUpcomingHoliday(gameTimes, now = new Date(), days = 10) {
    const today = tokEasternDate(now.toISOString());
    const horizon = tokEasternDate(new Date(now.getTime() + days * 86400000).toISOString());
    const found = [];
    for (const [week, kickoffs] of Object.entries(gameTimes || {})) {
        for (const [team, kickoff] of Object.entries(kickoffs || {})) {
            const day = tokEasternDate(kickoff);
            if (!day || day < today || day > horizon) continue;
            const year = Number(day.slice(0, 4));
            const holiday = TOK_HOLIDAYS.find(h => h.date(year) === day);
            if (!holiday) continue;
            let entry = found.find(f => f.date === day);
            if (!entry) {
                entry = { key: holiday.key, label: holiday.label, emoji: holiday.emoji, date: day, week: Number(week), teams: [] };
                found.push(entry);
            }
            if (!entry.teams.includes(team)) entry.teams.push(team);
        }
    }
    found.sort((a, b) => a.date.localeCompare(b.date));
    return found[0] || null;
}

// "needs 10 points for 5,000 career points" → { need: 10, target: 5000 }.
function tokParseMilestone(template) {
    const match = String(template || '').match(/needs ([\d,.]+) [a-zA-Z ]*?for ([\d,.]+)/);
    if (!match) return null;
    const need = Number(match[1].replace(/,/g, ''));
    const target = Number(match[2].replace(/,/g, ''));
    if (!Number.isFinite(need) || !Number.isFinite(target) || target <= 0 || need > target) return null;
    return { need, target, pct: (target - need) / target };
}

// ---- Week cards ----
//
// ctx (built by buildTokContext in the browser, by hand in tests):
//   season, completedWeek, upcomingWeek, live (bool),
//   names: { abbrev: owner short name }, teams: { abbrev: { name, owner } },
//   recapWeek: the completed week's { matchups } with total_score per team,
//   facts: loadWeeklyFacts() result or null,
//   pregame: loadPregameNotes() result or null,
//   gameTimes, gameOpponents, rosters, now,
//   rooting(team) → html | null (lazy; runs the playoff sim)

function tokOwner(ctx, abbrev) {
    return ctx.names?.[abbrev] || ctx.teams?.[abbrev]?.owner || abbrev;
}

function tokRenderFact(source) {
    return source?.renderFact || (text => chartEsc(text));
}

function tokSpotlightFirst(items, spotlight, teamsOf) {
    if (!spotlight) return items;
    return [...items].sort((a, b) => teamsOf(b).includes(spotlight) - teamsOf(a).includes(spotlight));
}

const TOK_WEEK_CARDS = [
    {
        id: 'week-recap',
        family: 'week',
        title: 'Last week recap',
        home: { view: 'matchups', subview: 'week' },
        compute(ctx) {
            if (!ctx.live || !ctx.completedWeek) return null;
            const games = (ctx.recapWeek?.matchups || []).map(m => {
                const a = m.team1;
                const b = m.team2;
                if (typeof a?.total_score !== 'number' || typeof b?.total_score !== 'number') return null;
                const [win, lose] = a.total_score >= b.total_score ? [a, b] : [b, a];
                const recap = (ctx.facts?.facts?.recaps || []).find(r =>
                    (r.team1 === a.abbrev && r.team2 === b.abbrev) || (r.team1 === b.abbrev && r.team2 === a.abbrev));
                return {
                    winner: win.abbrev,
                    loser: lose.abbrev,
                    ws: win.total_score,
                    ls: lose.total_score,
                    margin: Math.round((win.total_score - lose.total_score) * 10) / 10,
                    tie: win.total_score === lose.total_score,
                    note: recap?.notes?.[0]?.template || null,
                };
            }).filter(Boolean);
            if (!games.length) return null;
            return { week: ctx.completedWeek, games: games.sort((x, y) => y.margin - x.margin) };
        },
        tok(model, { ctx, spotlight }) {
            const fact = tokRenderFact(ctx.facts);
            const games = tokSpotlightFirst(model.games, spotlight, g => [g.winner, g.loser]);
            const closest = [...model.games].sort((x, y) => x.margin - y.margin)[0];
            const blowout = model.games[0];
            const caption = closest.margin < 5
                ? `😬 ${tokOwner(ctx, closest.winner)} survived by ${closest.margin}`
                : `💥 ${tokOwner(ctx, blowout.winner)} won by ${blowout.margin}`;
            return {
                pill: 'THIS WEEK',
                meta: `${ctx.season} · WK ${model.week}`,
                title: `Week ${model.week} recap`,
                sub: 'Every game from last week.',
                caption,
                timely: true,
                interest: 0.9,
                version: `${ctx.season}-recap-${model.week}`,
                involves: model.games.flatMap(g => [g.winner, g.loser]),
                body: () => `<ol class="tok-games">${games.map(g => `
                    <li class="tok-game${spotlight && (g.winner === spotlight || g.loser === spotlight) ? ' is-highlight' : ''}">
                        <div class="tok-game-row is-winner"><span>${chartEsc(tokOwner(ctx, g.winner))}</span><strong>${chartEsc(chartNum(g.ws))}</strong></div>
                        <div class="tok-game-row"><span>${chartEsc(tokOwner(ctx, g.loser))}</span><span>${chartEsc(chartNum(g.ls))}</span></div>
                        ${g.note ? `<p class="tok-game-note">${fact(g.note)}</p>` : ''}
                    </li>`).join('')}</ol>`,
            };
        },
    },
    {
        id: 'week-numbers',
        family: 'week',
        title: 'By the numbers',
        home: { view: 'history', subview: 'records' },
        compute(ctx) {
            if (!ctx.live) return null;
            const facts = ctx.facts;
            const notes = [...(facts?.headline || []), ...(facts?.rest || [])];
            if (!notes.length) return null;
            return { week: ctx.completedWeek, notes: notes.slice(0, 8), total: notes.length };
        },
        tok(model, { ctx, spotlight }) {
            const fact = tokRenderFact(ctx.facts);
            const notes = tokSpotlightFirst(model.notes, spotlight, n => n.subjects || []);
            return {
                pill: 'THIS WEEK',
                meta: `${ctx.season} · WK ${model.week}`,
                title: `Week ${model.week} by the numbers`,
                sub: 'What made history last week.',
                caption: `📜 ${model.total} note${model.total === 1 ? '' : 's'} for the record book`,
                timely: true,
                interest: 0.8,
                version: `${ctx.season}-numbers-${model.week}`,
                involves: [...new Set(model.notes.flatMap(n => n.subjects || []))],
                body: () => `<ul class="tok-notes">${notes.map(n => `
                    <li class="${spotlight && (n.subjects || []).includes(spotlight) ? 'is-highlight' : ''}">${fact(n.template)}</li>`).join('')}</ul>`,
            };
        },
    },
    {
        id: 'week-storylines',
        family: 'week',
        title: 'Matchup storylines',
        home: { view: 'matchups', subview: 'preview' },
        compute(ctx) {
            const matchups = ctx.live ? ctx.pregame?.notes?.matchups || [] : [];
            const games = matchups.map(m => ({
                team1: m.team1,
                team2: m.team2,
                lines: [...(m.storylines || []), ...(m.revenge || [])]
                    .sort((a, b) => b.notability - a.notability).slice(0, 2).map(n => n.template),
            })).filter(g => g.lines.length);
            if (!games.length) return null;
            return { week: ctx.upcomingWeek, games };
        },
        tok(model, { ctx, spotlight }) {
            const fact = tokRenderFact(ctx.pregame);
            const games = tokSpotlightFirst(model.games, spotlight, g => [g.team1, g.team2]);
            const lines = model.games.reduce((sum, g) => sum + g.lines.length, 0);
            return {
                pill: 'THIS WEEK',
                meta: `${ctx.season} · WK ${model.week}`,
                title: `Week ${model.week} storylines`,
                sub: 'What to watch in every game.',
                caption: `🍿 ${model.games.length} games, ${lines} storylines`,
                timely: true,
                interest: 0.85,
                version: `${ctx.season}-storylines-${model.week}`,
                involves: model.games.flatMap(g => [g.team1, g.team2]),
                body: () => `<ol class="tok-games">${games.map(g => `
                    <li class="tok-game${spotlight && (g.team1 === spotlight || g.team2 === spotlight) ? ' is-highlight' : ''}">
                        <div class="tok-game-head">${chartEsc(tokOwner(ctx, g.team1))} <span>vs</span> ${chartEsc(tokOwner(ctx, g.team2))}</div>
                        ${g.lines.map(line => `<p class="tok-game-note">${fact(line)}</p>`).join('')}
                    </li>`).join('')}</ol>`,
            };
        },
    },
    {
        id: 'week-records',
        family: 'week',
        title: 'Record watch',
        home: { view: 'matchups', subview: 'preview' },
        compute(ctx) {
            const notes = ctx.live
                ? (ctx.pregame?.notes?.matchups || []).flatMap(m => m.records || [])
                    .sort((a, b) => b.notability - a.notability)
                : [];
            return notes.length ? { week: ctx.upcomingWeek, notes } : null;
        },
        tok(model, { ctx, spotlight }) {
            const fact = tokRenderFact(ctx.pregame);
            const notes = tokSpotlightFirst(model.notes, spotlight, n => n.subjects || []);
            const n = model.notes.length;
            return {
                pill: 'THIS WEEK',
                meta: `${ctx.season} · WK ${model.week}`,
                title: 'Record watch',
                sub: 'League records that could fall this week.',
                caption: `👀 ${n} record${n === 1 ? '' : 's'} in reach`,
                timely: true,
                interest: 0.9,
                version: `${ctx.season}-records-${model.week}`,
                involves: [...new Set(model.notes.flatMap(note => note.subjects || []))],
                body: () => `<ul class="tok-notes tok-notes-cards">${notes.map(note => `
                    <li class="${spotlight && (note.subjects || []).includes(spotlight) ? 'is-highlight' : ''}">
                        <span class="tok-note-kicker">👑 ${chartEsc(tokOwner(ctx, (note.subjects || [])[0]))}</span>
                        ${fact(note.template)}
                    </li>`).join('')}</ul>`,
            };
        },
    },
    {
        id: 'week-milestones',
        family: 'week',
        title: 'Milestones',
        home: { view: 'matchups', subview: 'preview' },
        compute(ctx) {
            const notes = ctx.live
                ? (ctx.pregame?.notes?.matchups || []).flatMap(m => m.milestones || [])
                    .map(note => ({ ...note, progress: tokParseMilestone(note.template) }))
                    .sort((a, b) => (b.progress?.pct ?? 0) - (a.progress?.pct ?? 0) || b.notability - a.notability)
                : [];
            return notes.length ? { week: ctx.upcomingWeek, notes } : null;
        },
        tok(model, { ctx, spotlight }) {
            const fact = tokRenderFact(ctx.pregame);
            const notes = tokSpotlightFirst(model.notes, spotlight, n => n.subjects || []);
            return {
                pill: 'THIS WEEK',
                meta: `${ctx.season} · WK ${model.week}`,
                title: 'Milestones',
                sub: 'Round numbers coming up.',
                caption: '📸 Screenshot this for the group chat',
                timely: true,
                interest: 0.6,
                version: `${ctx.season}-milestones-${model.week}`,
                involves: [...new Set(model.notes.flatMap(n => n.subjects || []))],
                body: () => `<ul class="tok-milestones">${notes.map(note => `
                    <li class="${spotlight && (note.subjects || []).includes(spotlight) ? 'is-highlight' : ''}">
                        ${note.progress ? ringStat({ pct: note.progress.pct, size: 52 }) : '<span class="tok-ring-blank" aria-hidden="true">🎯</span>'}
                        <div>
                            <span class="tok-note-kicker">${chartEsc(tokOwner(ctx, (note.subjects || [])[0]))}</span>
                            <span>${fact(note.template)}</span>
                        </div>
                    </li>`).join('')}</ul>`,
            };
        },
    },
    {
        id: 'week-rooting',
        family: 'week',
        title: 'Rooting guide',
        home: { view: 'standings', subview: 'machine' },
        compute(ctx) {
            if (!ctx.live || !ctx.spotlight || !ctx.upcomingWeek || typeof ctx.rooting !== 'function') return null;
            return { team: ctx.spotlight, week: ctx.upcomingWeek };
        },
        tok(model, { ctx }) {
            return {
                pill: 'THIS WEEK',
                meta: `${ctx.season} · WK ${model.week}`,
                title: 'Who to root for',
                sub: `Every other game, ranked by what it means for ${tokOwner(ctx, model.team)}.`,
                caption: '🙏 Your playoff odds, game by game',
                timely: true,
                interest: 0.8,
                version: `${ctx.season}-rooting-${model.week}-${model.team}`,
                involves: [model.team],
                body: () => ctx.rooting(model.team) || '<p class="tok-empty">Nothing left to root for.</p>',
            };
        },
    },
    {
        id: 'week-holiday',
        family: 'week',
        title: 'Holiday slate',
        home: { view: 'matchups', subview: 'week' },
        compute(ctx) {
            if (!ctx.live) return null;
            const holiday = tokUpcomingHoliday(ctx.gameTimes, ctx.now || new Date());
            if (!holiday) return null;
            const playing = new Set(holiday.teams);
            const rows = Object.entries(ctx.rosters || {}).map(([abbrev, roster]) => {
                const players = (roster || []).filter(p => !p.taxi && playing.has(p.nfl_team));
                return { id: abbrev, label: tokOwner(ctx, abbrev), value: players.length, players: players.map(p => p.name) };
            }).filter(row => row.value > 0).sort((a, b) => b.value - a.value || a.label.localeCompare(b.label));
            if (!rows.length) return null;
            const opponents = ctx.gameOpponents?.[String(holiday.week)] || {};
            const games = holiday.teams
                .filter(team => opponents[team]?.is_home === false)
                .map(team => `${team} @ ${opponents[team].opponent}`);
            return { holiday, rows, games };
        },
        tok(model, { ctx, spotlight }) {
            const { holiday } = model;
            const [, month, day] = holiday.date.split('-');
            return {
                pill: 'HOLIDAY',
                pillCls: 'is-holiday',
                meta: `${ctx.season}`,
                title: `Who plays on ${holiday.label}`,
                sub: `${model.rows.length} teams have players in action.`,
                caption: `${holiday.emoji} ${holiday.label.toUpperCase()}, ${Number(month)}/${Number(day)}${model.games.length ? `: ${model.games.join(', ')}` : ''}`,
                timely: true,
                interest: 0.95,
                version: `${ctx.season}-${holiday.key}`,
                involves: model.rows.map(r => r.id),
                body: () => barList({
                    highlight: spotlight,
                    valueFmt: v => `${v}`,
                    rows: model.rows.map(r => ({ id: r.id, label: r.label, value: r.value, sub: r.players.join(', ') })),
                }),
            };
        },
    },
];

TOK_WEEK_CARDS.forEach(card => registerChart(card));

// Every registered chart's card for this context, ready for the feed.
function collectTokCards(ctx, spotlight) {
    const cards = [];
    for (const entry of CHARTS) {
        if (typeof entry.tok !== 'function') continue;
        const model = computeChart(entry, { ...ctx, spotlight });
        if (model == null) continue;
        let out;
        try {
            out = entry.tok(model, { ctx: { ...ctx, spotlight }, spotlight });
        } catch (error) {
            if (typeof console !== 'undefined') console.warn(`Tok card ${entry.id} failed`, error);
            continue;
        }
        if (!out) continue;
        cards.push({
            id: entry.id,
            family: entry.family,
            title: out.title || entry.title,
            home: entry.home || null,
            version: out.version || `${ctx.season}-${ctx.completedWeek}`,
            ...out,
        });
    }
    return cards;
}

function tokFullChartRoute(home) {
    if (!home?.view) return '#home';
    const path = home.subview ? `${home.view}/${home.subview}` : home.view;
    return `#${path}${home.anchor ? `?section=${encodeURIComponent(home.anchor)}` : ''}`;
}

function tokCardHtml(card, index, { spotlight = null, teams = {}, names = {} } = {}) {
    const family = CHART_FAMILIES[card.family];
    const spotlightName = spotlight ? (names[spotlight] || teams[spotlight]?.owner || spotlight) : '';
    return `
        <article class="tok-card" data-tok-id="${chartEsc(card.id)}" data-index="${index}" aria-roledescription="clip" aria-label="${chartEsc(card.title)}">
            <div class="tok-pills">
                <span class="tok-pill tok-pill-family ${chartEsc(card.pillCls || `is-${card.family}`)}">${chartEsc(card.pill || family?.pill || '')}</span>
                ${card.meta ? `<span class="tok-pill tok-pill-meta">${chartEsc(card.meta)}</span>` : ''}
                ${spotlight && (card.involves || []).includes(spotlight) ? `<span class="tok-pill tok-pill-spotlight">📍 ${chartEsc(spotlightName)}</span>` : ''}
                ${card.isNew ? '<span class="tok-pill tok-pill-new">NEW</span>' : ''}
            </div>
            <h2 class="tok-title">${chartEsc(card.title)}</h2>
            ${card.sub ? `<p class="tok-sub">${chartEsc(card.sub)}</p>` : ''}
            <div class="tok-body" data-tok-body></div>
            <div class="tok-foot">
                ${card.caption ? `<p class="tok-caption">${chartEsc(card.caption)}</p>` : '<span></span>'}
                <div class="tok-rail">
                    <button type="button" class="tok-rail-btn" data-tok-action="share" aria-label="Share ${chartEsc(card.title)}">
                        <span class="tok-rail-icon" aria-hidden="true">➤</span><span>Share</span>
                    </button>
                    <a class="tok-rail-btn" href="${chartEsc(tokFullChartRoute(card.home))}" data-tok-action="full" aria-label="Open ${chartEsc(card.title)} on the site">
                        <span class="tok-rail-icon" aria-hidden="true">⤢</span><span>Full chart</span>
                    </a>
                </div>
            </div>
            ${index === 0 ? '<p class="tok-hint" aria-hidden="true">⌃<br>Swipe up for more</p>' : ''}
        </article>`;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        tokHash, tokIsNew, buildTokFeed, tokEasternDate, tokThanksgiving, tokUpcomingHoliday,
        tokParseMilestone, TOK_WEEK_CARDS, collectTokCards, tokFullChartRoute, tokCardHtml,
    };
}

// ---- Browser controller ----

function tokStorageGet(key, fallback) {
    try {
        const raw = localStorage.getItem(key);
        return raw == null ? fallback : JSON.parse(raw);
    } catch {
        return fallback;
    }
}

function tokStorageSet(key, value) {
    try {
        if (value == null) localStorage.removeItem(key);
        else localStorage.setItem(key, JSON.stringify(value));
    } catch {
        // Private mode or blocked storage: NEW badges just won't stick.
    }
}

function tokSpotlight() {
    const stored = tokStorageGet(TOK_STORAGE.spotlight, null);
    if (stored && (data?.teams || []).some(t => t.abbrev === stored)) return stored;
    return typeof myTeamAbbrev === 'function' ? myTeamAbbrev() : null;
}

function tokDateKey(now = new Date()) {
    return tokEasternDate(now.toISOString()) || '';
}

// Everything the cards read, gathered once per render.
async function buildTokContext() {
    const live = Boolean(data) && data.season === LIVE_SEASON && !data.is_offseason && !data.is_historical;
    const season = Number(data?.season);
    const completedWeek = live ? completedThroughWeek() : 0;
    const upcomingWeek = live ? previewWeek() : 0;
    const [facts, pregame] = live ? await Promise.all([
        completedWeek ? loadWeeklyFacts(season, completedWeek).catch(() => null) : null,
        upcomingWeek ? loadPregameNotes(season, upcomingWeek).catch(() => null) : null,
    ]) : [null, null];
    const teams = Object.fromEntries((data?.teams || []).map(t => [t.abbrev, { name: t.name, owner: t.owner }]));
    let machine;
    const rooting = team => {
        if (machine === undefined) machine = preparePlayoffSim();
        if (!machine || machine.teamMean?.[team] === undefined) return null;
        return rootingGuideHtml(
            computeRootingGuide(machine, new Map(), team),
            playoffMachineSummary(machine, new Map(), ROOTING_GUIDE_TRIALS),
        );
    };
    return {
        live,
        season,
        completedWeek,
        upcomingWeek,
        names: { ...(pregame?.notes?.names || {}), ...(facts?.facts?.names || {}) },
        teams,
        recapWeek: (data?.weeks || []).find(w => Number(w.week) === Number(completedWeek)) || null,
        facts,
        pregame,
        gameTimes: data?.game_times || sharedData?.game_times || {},
        gameOpponents: data?.game_opponents || sharedData?.game_opponents || {},
        rosters: data?.rosters || sharedData?.rosters || {},
        charts: sharedData?.charts || null,
        now: new Date(),
        rooting,
    };
}

async function buildTokFeedForPage() {
    const ctx = await buildTokContext();
    const spotlight = tokSpotlight();
    const seen = tokStorageGet(TOK_STORAGE.seen, {});
    const cards = buildTokFeed(collectTokCards(ctx, spotlight), { spotlight, seen, dateKey: tokDateKey(ctx.now) });
    return { ctx, spotlight, cards };
}

const tokState = {
    cards: [],
    ctx: null,
    spotlight: null,
    current: 0,
    pending: null,
    pendingTimer: null,
    observer: null,
    filled: new Set(),
    keysBound: false,
};

function tokShellHtml() {
    return `
        <div class="tok-stage">
            <aside class="tok-aside">
                <div class="tok-brand"><img src="images/league_logo.png" alt="" class="tok-logo"> QPFLTok</div>
                <p>Made for your phone: open the site there. Here, scroll or use ↑ ↓ to swipe.</p>
                <a href="#home" class="tok-back" data-tok-action="exit">Back to QPFL</a>
            </aside>
            <div class="tok-phone">
                <div class="tok-topbar">
                    <button type="button" class="tok-top-btn" data-tok-action="browse" aria-haspopup="dialog">▦ Browse</button>
                    <a href="#home" class="tok-brand" data-tok-action="exit" aria-label="Back to QPFL"><img src="images/league_logo.png" alt="" class="tok-logo"> QPFLTok</a>
                    <button type="button" class="tok-top-btn tok-gear" data-tok-action="settings" aria-haspopup="dialog" aria-label="QPFLTok settings">⚙</button>
                </div>
                <div class="tok-feed" id="tok-feed" tabindex="0" aria-label="QPFLTok clips"></div>
                <div class="tok-sheet" id="tok-sheet" role="dialog" aria-modal="true" hidden></div>
                <div class="tok-toast" id="tok-toast" role="status" aria-live="polite" hidden></div>
            </div>
        </div>`;
}

async function renderTok(subview) {
    const view = document.getElementById('tok-view');
    if (!view) return;
    if (!view.querySelector('.tok-stage')) view.innerHTML = tokShellHtml();
    const feed = view.querySelector('#tok-feed');
    feed.innerHTML = '<p class="tok-empty">Loading clips…</p>';
    const { ctx, spotlight, cards } = await buildTokFeedForPage();
    Object.assign(tokState, { ctx, spotlight, cards, current: 0, filled: new Set() });
    if (!cards.length) {
        feed.innerHTML = '<p class="tok-empty">Nothing new to swipe yet. Check back on game day.</p>';
        return;
    }
    feed.innerHTML = cards.map((card, i) => tokCardHtml(card, i, { spotlight, teams: ctx.teams, names: ctx.names })).join('');
    if (tokStorageGet(TOK_STORAGE.hinted, false)) feed.querySelector('.tok-hint')?.remove();
    feed.scrollTop = 0;
    bindTokFeed(view, feed);
    const start = Math.max(0, cards.findIndex(card => card.id === subview));
    tokFill(start);
    if (start > 0) feed.querySelector(`[data-index="${start}"]`)?.scrollIntoView({ block: 'start' });
    tokSetCurrent(start, { replaceRoute: false });
}

// Card bodies are drawn only near the current card.
function tokFill(index) {
    const feed = document.getElementById('tok-feed');
    for (let i = index - 2; i <= index + 2; i += 1) {
        const card = tokState.cards[i];
        if (!card || tokState.filled.has(i)) continue;
        const slot = feed?.querySelector(`[data-index="${i}"] [data-tok-body]`);
        if (!slot) continue;
        tokState.filled.add(i);
        try {
            slot.innerHTML = typeof card.body === 'function' ? card.body() : (card.body || '');
        } catch (error) {
            console.warn(`Tok card ${card.id} failed to draw`, error);
            slot.innerHTML = '<p class="tok-empty">This clip could not be drawn.</p>';
        }
    }
}

function tokSetCurrent(index, { replaceRoute = true } = {}) {
    const card = tokState.cards[index];
    if (!card) return;
    tokState.current = index;
    tokFill(index);
    const seen = tokStorageGet(TOK_STORAGE.seen, {});
    if (seen[card.id] !== card.version) {
        seen[card.id] = card.version;
        tokStorageSet(TOK_STORAGE.seen, seen);
    }
    if (index > 0 && !tokStorageGet(TOK_STORAGE.hinted, false)) tokStorageSet(TOK_STORAGE.hinted, true);
    if (replaceRoute && getActiveView() === 'tok') history.replaceState(null, '', `#tok/${encodeURIComponent(card.id)}`);
}

function tokScrollTo(index) {
    const feed = document.getElementById('tok-feed');
    const target = feed?.querySelector(`[data-index="${index}"]`);
    if (!target) return;
    tokFill(index);
    // The observer only reports the new card once the smooth scroll lands, so
    // remember where we're headed: a second key press continues from there.
    tokState.pending = index;
    clearTimeout(tokState.pendingTimer);
    tokState.pendingTimer = setTimeout(() => { tokState.pending = null; }, 800);
    feed.scrollTo({ top: target.offsetTop, behavior: 'smooth' });
}

function bindTokFeed(view, feed) {
    tokState.observer?.disconnect();
    tokState.observer = new IntersectionObserver(entries => {
        for (const entry of entries) {
            if (entry.isIntersecting) tokSetCurrent(Number(entry.target.dataset.index));
        }
    }, { root: feed, threshold: 0.6 });
    feed.querySelectorAll('.tok-card').forEach(card => tokState.observer.observe(card));

    if (view.dataset.bound) return;
    view.dataset.bound = 'true';
    view.addEventListener('click', event => {
        const control = event.target.closest('[data-tok-action]');
        if (!control) {
            if (event.target.closest('.tok-sheet-backdrop')) tokCloseSheet();
            return;
        }
        const action = control.dataset.tokAction;
        if (action === 'share') {
            event.preventDefault();
            tokShare(control.closest('.tok-card')?.dataset.tokId);
        } else if (action === 'full' || action === 'exit') {
            event.preventDefault();
            tokCloseSheet();
            history.pushState(null, '', control.getAttribute('href'));
            applyHash();
        } else if (action === 'browse') {
            tokOpenBrowse();
        } else if (action === 'settings') {
            tokOpenSettings();
        } else if (action === 'close-sheet') {
            tokCloseSheet();
        } else if (action === 'jump') {
            tokCloseSheet();
            tokScrollTo(Number(control.dataset.index));
        } else if (action === 'reset') {
            tokStorageSet(TOK_STORAGE.seen, null);
            tokStorageSet(TOK_STORAGE.hinted, null);
            tokCloseSheet();
            tokToast('Every clip is new again');
            renderTok();
        }
    });
    view.addEventListener('change', event => {
        if (event.target.id !== 'tok-spotlight') return;
        tokStorageSet(TOK_STORAGE.spotlight, event.target.value || null);
        tokCloseSheet();
        renderTok();
    });
    view.addEventListener('input', event => {
        if (event.target.id !== 'tok-browse-filter') return;
        const query = event.target.value.trim().toLowerCase();
        view.querySelectorAll('.tok-browse-item').forEach(item => {
            item.hidden = Boolean(query) && !item.textContent.toLowerCase().includes(query);
        });
    });
    if (!tokState.keysBound) {
        tokState.keysBound = true;
        document.addEventListener('keydown', tokKeydown);
    }
}

function tokKeydown(event) {
    if (getActiveView() !== 'tok') return;
    const sheet = document.getElementById('tok-sheet');
    if (event.key === 'Escape' && sheet && !sheet.hidden) {
        tokCloseSheet();
        return;
    }
    if (sheet && !sheet.hidden) return;
    if (event.target.closest?.('input, select, textarea')) return;
    const next = ['ArrowDown', 'PageDown', 'j'].includes(event.key);
    const prev = ['ArrowUp', 'PageUp', 'k'].includes(event.key);
    if (!next && !prev) return;
    event.preventDefault();
    const from = tokState.pending ?? tokState.current;
    tokScrollTo(Math.max(0, Math.min(tokState.cards.length - 1, from + (next ? 1 : -1))));
}

function tokToast(message) {
    const toast = document.getElementById('tok-toast');
    if (!toast) return;
    toast.textContent = message;
    toast.hidden = false;
    clearTimeout(tokToast.timer);
    tokToast.timer = setTimeout(() => { toast.hidden = true; }, 2200);
}

async function tokShare(id) {
    const card = tokState.cards.find(c => c.id === id);
    if (!card) return;
    const url = `${location.origin}${location.pathname}#tok/${encodeURIComponent(id)}`;
    try {
        if (navigator.share) {
            await navigator.share({ title: `${card.title} · QPFLTok`, text: card.caption || card.title, url });
            return;
        }
        await navigator.clipboard.writeText(url);
        tokToast('Link copied');
    } catch (error) {
        if (error?.name !== 'AbortError') tokToast('Copy the address bar to share');
    }
}

function tokOpenSheet(html, label) {
    const sheet = document.getElementById('tok-sheet');
    if (!sheet) return;
    sheet.setAttribute('aria-label', label);
    sheet.innerHTML = `
        <div class="tok-sheet-backdrop"></div>
        <div class="tok-sheet-panel">
            <div class="tok-sheet-head">
                <h2>${chartEsc(label)}</h2>
                <button type="button" class="tok-top-btn" data-tok-action="close-sheet" aria-label="Close">✕</button>
            </div>
            ${html}
        </div>`;
    sheet.hidden = false;
    sheet.querySelector('input, select, button')?.focus();
}

function tokCloseSheet() {
    const sheet = document.getElementById('tok-sheet');
    if (!sheet || sheet.hidden) return;
    sheet.hidden = true;
    sheet.innerHTML = '';
    document.getElementById('tok-feed')?.focus({ preventScroll: true });
}

function tokOpenBrowse() {
    const groups = Object.entries(CHART_FAMILIES).map(([family, meta]) => {
        const items = tokState.cards
            .map((card, index) => ({ card, index }))
            .filter(({ card }) => card.family === family);
        if (!items.length) return '';
        return `
            <section class="tok-browse-group">
                <h3>${chartEsc(meta.label)}</h3>
                <ul>${items.map(({ card, index }) => `
                    <li class="tok-browse-item">
                        <button type="button" data-tok-action="jump" data-index="${index}">
                            <span>${chartEsc(card.title)}</span>
                            ${card.isNew ? '<span class="tok-pill tok-pill-new">NEW</span>' : ''}
                        </button>
                    </li>`).join('')}</ul>
            </section>`;
    }).join('');
    tokOpenSheet(`
        <label class="visually-hidden" for="tok-browse-filter">Jump to a chart</label>
        <input type="search" id="tok-browse-filter" class="tok-input" placeholder="Jump to a chart…" autocomplete="off">
        ${groups || '<p class="tok-empty">No clips yet.</p>'}
        <a href="#home" class="tok-back" data-tok-action="exit">← Back to QPFL</a>`, 'Browse');
}

function tokOpenSettings() {
    const teams = [...(data?.teams || [])].sort((a, b) => String(a.owner).localeCompare(String(b.owner)));
    const spotlight = tokState.spotlight;
    const options = teams.map(team => `
        <option value="${chartEsc(team.abbrev)}" ${team.abbrev === spotlight ? 'selected' : ''}>${chartEsc(tokOwner(tokState.ctx || {}, team.abbrev))} · ${chartEsc(team.name)}</option>`).join('');
    tokOpenSheet(`
        <div class="tok-setting">
            <label for="tok-spotlight">Spotlight a team</label>
            <select id="tok-spotlight" class="tok-input">
                <option value="">No one</option>
                ${options}
            </select>
            <p>Highlights them in every chart and builds the feed around their games and stats.</p>
        </div>
        <div class="tok-setting">
            <span class="tok-setting-label">Feed</span>
            <button type="button" class="tok-wide-btn" data-tok-action="reset">Reset my feed</button>
            <p>Every clip plays as new again on this device.</p>
        </div>`, 'Settings');
}

// Home teaser: how many clips are NEW right now. Hidden at zero.
async function renderHomeTokTeaser() {
    const slot = document.getElementById('home-tok-teaser');
    if (!slot) return;
    slot.hidden = true;
    try {
        // Rosters feed the holiday slate, so the count matches the feed.
        if (data?.season === LIVE_SEASON) await ensureCurrentSeasonFiles({ rosters: true });
        const { cards } = await buildTokFeedForPage();
        const fresh = cards.filter(card => card.isNew).length;
        if (!fresh || !slot.isConnected) return;
        slot.innerHTML = `
            <span class="home-tok-brand">QPFLTok</span>
            <span class="home-tok-text">${fresh} new clip${fresh === 1 ? '' : 's'}: ${chartEsc(cards.find(c => c.isNew)?.title || '')}</span>
            <span class="home-tok-arrow" aria-hidden="true">→</span>`;
        slot.hidden = false;
    } catch (error) {
        console.warn('QPFLTok teaser failed', error);
    }
}
