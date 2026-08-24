// Populated from data/index.json on first load — no hardcoded year needed at season transition.
let LIVE_SEASON = null;

let data = null;
let sharedData = {};
let manualHonorsData = null;
let currentWeek = 1;
let currentSeason = null;
let availableSeasons = [];  // Populated on load
let dataIndex = null;
let activeRouteParams = new URLSearchParams();

const resourceCache = new Map();

async function fetchJsonResource(path, { forceRefresh = false, optional = false } = {}) {
    if (forceRefresh) resourceCache.delete(path);
    if (!forceRefresh && resourceCache.has(path)) return resourceCache.get(path);

    const request = fetch(path, { cache: forceRefresh ? 'no-store' : 'default' })
        .then(response => {
            if (!response.ok) {
                if (optional && response.status === 404) return null;
                throw new Error(`Could not load ${path} (${response.status})`);
            }
            return response.json();
        });
    resourceCache.set(path, request);
    try {
        return await request;
    } catch (error) {
        resourceCache.delete(path);
        throw error;
    }
}

function unwrapStandings(payload) {
    if (Array.isArray(payload)) return payload;
    return payload?.standings || [];
}

function latestTimestamp(...values) {
    return values.filter(Boolean).sort().at(-1) || null;
}

async function loadSeasonBase(season, { forceRefresh = false } = {}) {
    const base = `data/seasons/${season}`;
    const isLive = season === LIVE_SEASON;
    const [meta, standingsPayload, live] = await Promise.all([
        fetchJsonResource(`${base}/meta.json`, { forceRefresh }),
        fetchJsonResource(`${base}/standings.json`, { forceRefresh }),
        isLive
            ? fetchJsonResource(`${base}/live.json`, { forceRefresh, optional: true })
            : Promise.resolve(null),
    ]);
    const standings = unwrapStandings(standingsPayload);
    const seasonData = {
        ...meta,
        ...(live || {}),
        season,
        standings,
        teams: meta.teams || [],
        schedule: meta.schedule || [],
        weeks: [],
        rosters: {},
        draft_picks: [],
        drafts: [],
        transactions: [],
        team_stats: live?.team_stats || {},
        is_historical: !isLive,
        updated_at: latestTimestamp(live?.updated_at, standingsPayload?.updated_at, meta.updated_at),
    };
    seasonData.current_week = Number(live?.current_week ?? meta.current_week ?? 0);
    seasonData.lineup_week = Number(
        live?.lineup_week ?? meta.lineup_week ?? seasonData.current_week
    );
    seasonData.is_offseason = isLive
        ? Boolean(live?.is_offseason ?? meta.is_offseason ?? seasonData.current_week === 0)
        : true;
    return seasonData;
}

// Escape user-controlled strings before interpolating them into innerHTML.
// Managers can set free-text team names, trade comments, and trade-block notes,
// so these must be escaped to prevent stored HTML/script injection.
function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// Days a pending trade lives before the expire-trades.yml workflow auto-cancels
// it. Keep in sync with TRADE_EXPIRY_DAYS in .github/workflows/expire-trades.yml.
const TRADE_EXPIRY_DAYS = 7;

const ROSTER_POSITION_ORDER = ['QB', 'RB', 'WR', 'TE', 'K', 'D/ST', 'HC', 'OL'];

// --- Fantasy-app UI primitives: position badges + team avatars -------------- #
// Map a roster position to a CSS-safe class suffix (e.g. "D/ST" -> "DST").
function posClassKey(position) {
    return String(position || '').replace(/[^A-Za-z]/g, '').toUpperCase() || 'NA';
}

// Colored position pill, like Sleeper/Yahoo. Colors live in styles.css (.pos-badge).
function posBadge(position) {
    const label = position || '';
    return `<span class="pos-badge pos-${posClassKey(label)}">${escapeHtml(label)}</span>`;
}

function playerProfileButton(name, className = '', displayName = null, position = '') {
    const playerName = String(name || '').trim();
    const label = displayName === null ? playerName : String(displayName);
    const extraClass = className ? ` ${className}` : '';
    const positionAttr = position ? ` data-player-position="${escapeHtml(position)}"` : '';
    return `<button type="button" class="player-name player-profile-trigger${extraClass}" data-player-name="${escapeHtml(playerName)}"${positionAttr} aria-label="View ${escapeHtml(playerName)} player profile">${escapeHtml(label)}</button>`;
}

function emptyStateHtml(title, message, actions = []) {
    const actionHtml = actions.map(action => {
        if (action.route) {
            return `<a class="empty-state-action" href="${escapeHtml(action.route)}" data-route="${escapeHtml(action.route)}">${escapeHtml(action.label)}</a>`;
        }
        return `<button type="button" class="empty-state-action" data-empty-action="${escapeHtml(action.action)}">${escapeHtml(action.label)}</button>`;
    }).join('');
    return `
        <div class="empty-state">
            <h3>${escapeHtml(title)}</h3>
            ${message ? `<p>${escapeHtml(message)}</p>` : ''}
            ${actionHtml ? `<div class="empty-state-actions">${actionHtml}</div>` : ''}
        </div>
    `;
}

function teamProfileButton(abbrev, name, className = '') {
    const teamCode = String(abbrev || '').trim();
    const label = String(name || teamCode);
    const extraClass = className ? ` ${className}` : '';
    if (!teamCode) return `<span class="${escapeHtml(className)}">${escapeHtml(label)}</span>`;
    return `<button type="button" class="team-profile-trigger${extraClass}" data-team-abbrev="${escapeHtml(teamCode)}" aria-label="View ${escapeHtml(label)} roster">${escapeHtml(label)}</button>`;
}

// Deterministic avatar background color from a team key, so a team without an
// uploaded image always gets a stable colored initials circle.
const AVATAR_PALETTE = [
    '#5b9bff', '#34d399', '#f472b6', '#fbbf24', '#a78bfa',
    '#22d3ee', '#fb923c', '#4ade80', '#e879f9', '#60a5fa',
];
function avatarColor(key) {
    const s = String(key || '');
    let h = 0;
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
    return AVATAR_PALETTE[h % AVATAR_PALETTE.length];
}

// Up-to-3-letter initials for the fallback circle, derived from the abbrev.
function teamInitials(abbrev, name) {
    if (abbrev) return String(abbrev).replace(/[^A-Za-z0-9]/g, '').slice(0, 3).toUpperCase();
    if (name) {
        return String(name).split(/\s+/).filter(Boolean).slice(0, 2)
            .map(w => w[0]).join('').toUpperCase();
    }
    return '?';
}

// Circular team avatar: an uploaded image layered over a colored initials circle.
// Avatars are point-in-time (see qpfl/avatars.py): the exporter stamps each team
// object with the `avatar` URL in effect for that week, so historical views keep
// their old image. Pass that stamped URL as `src`. With no src (team has no avatar
// at that point) the initials circle shows through. If the image 404s, onerror
// removes it and the initials show through too.
function teamAvatar(abbrev, name, sizeClass, src) {
    const cls = sizeClass ? ` ${sizeClass}` : '';
    const initials = teamInitials(abbrev, name);
    const color = avatarColor(abbrev || name);
    const img = src
        ? `<img class="team-avatar-img" src="${encodeURI(src)}" alt="" loading="lazy" onerror="this.remove()">`
        : '';
    return `<span class="team-avatar${cls}" style="--avatar-color: ${color}" aria-hidden="true"><span class="team-avatar-initials">${escapeHtml(initials)}</span>${img}</span>`;
}

// Current (latest) avatar URL for a team, from the exporter-stamped data.teams.
// Use for present/future surfaces (standings, rosters, pending matchups). Per-week
// historical surfaces should instead read the point-in-time `avatar` field already
// stamped on their week team objects. Returns null when the team has no avatar.
function currentTeamAvatar(abbrev) {
    const t = data?.teams?.find(t => t.abbrev === abbrev);
    return t?.avatar || null;
}
function sortRosterByPosition(roster) {
    return [...roster].sort((a, b) => {
        const ai = ROSTER_POSITION_ORDER.indexOf(a.position);
        const bi = ROSTER_POSITION_ORDER.indexOf(b.position);
        const aIdx = ai === -1 ? ROSTER_POSITION_ORDER.length : ai;
        const bIdx = bi === -1 ? ROSTER_POSITION_ORDER.length : bi;
        return aIdx - bIdx;
    });
}

function txPlayerRowHtml(player) {
    return `
        <div class="tx-player" data-name="${escapeHtml(player.name)}" data-position="${escapeHtml(player.position)}">
            <button type="button" class="tx-player-select" aria-label="Select ${escapeHtml(player.name)}" aria-pressed="false">
                <span class="position-tag">${escapeHtml(player.position)}</span>
            </button>
            ${playerProfileButton(player.name, '', null, player.position)}
            <span class="player-team">${escapeHtml(player.nfl_team || '')}</span>
        </div>
    `;
}

// Trade-specific variant: adds season total points beside the player name.
function tradePlayerRowHtml(player, selected = false) {
    const leaders = getStatsLeaders();
    const posPlayers = leaders[player.position] || [];
    const entry = posPlayers.find(p => p.name === player.name);
    const pts = entry ? entry.total_points : null;
    const ptsHtml = pts != null
        ? `<span class="trade-player-pts">${pts.toFixed(1)}</span>`
        : '';
    const taxiHtml = player.taxi ? '<span class="trade-player-taxi">Taxi</span>' : '';
    return `
        <div class="tx-player ${selected ? 'selected' : ''}" data-name="${escapeHtml(player.name)}" data-position="${escapeHtml(player.position)}">
            <button type="button" class="tx-player-select" aria-label="Select ${escapeHtml(player.name)} for trade" aria-pressed="${selected}">
                <span class="position-tag">${escapeHtml(player.position)}</span>
            </button>
            ${playerProfileButton(player.name, '', null, player.position)}
            ${taxiHtml}
            <span class="player-team">${escapeHtml(player.nfl_team || '')}</span>
            ${ptsHtml}
        </div>
    `;
}

function showAppLoading() {
    document.body.classList.add('app-loading');
    document.body.classList.remove('app-load-error');
    const loading = document.querySelector('.app-spinner-loading');
    const errorPanel = document.getElementById('app-load-error-panel');
    if (loading) loading.hidden = false;
    if (errorPanel) errorPanel.hidden = true;
    document.querySelector('.container')?.setAttribute('inert', '');
    document.getElementById('main-content')?.setAttribute('aria-busy', 'true');
}

function showInitialLoadError() {
    document.body.classList.remove('app-loading');
    document.body.classList.add('app-load-error');
    const loading = document.querySelector('.app-spinner-loading');
    const errorPanel = document.getElementById('app-load-error-panel');
    if (loading) loading.hidden = true;
    if (errorPanel) errorPanel.hidden = false;
    document.getElementById('main-content')?.setAttribute('aria-busy', 'false');
    document.getElementById('app-load-retry')?.focus();
}

async function loadData(season = null, { forceRefresh = false } = {}) {
    if (season !== null) currentSeason = season;
    if (season !== null || !data) showAppLoading();

    try {
        if (forceRefresh) {
            resourceCache.clear();
            dataIndex = null;
            sharedData = {};
            manualHonorsData = null;
        }

        if (!dataIndex) {
            dataIndex = await fetchJsonResource('data/index.json', { forceRefresh });
            LIVE_SEASON = Number(dataIndex.current_season);
            availableSeasons = (dataIndex.seasons || [])
                .map(Number)
                .filter(Number.isFinite)
                .sort((a, b) => b - a);
            if (currentSeason === null) currentSeason = LIVE_SEASON;
        }

        if (!availableSeasons.includes(Number(currentSeason))) {
            throw new Error(`Season ${currentSeason} not available`);
        }

        data = await loadSeasonBase(Number(currentSeason), { forceRefresh });
        if (currentSeason === LIVE_SEASON) {
            for (const key of [
                'season', 'teams', 'current_week', 'lineup_week', 'is_offseason', 'updated_at',
                'fa_pool', 'game_times', 'kickoffs', 'lineups', 'pending_trades',
                'trade_blocks', 'recent_transactions', 'team_stats', 'upcoming_drafts',
            ]) {
                if (data[key] !== undefined) sharedData[key] = data[key];
            }
        }

        // Cap currentWeek at 17 for display (offseason shows week 17)
        // During pre-season (week 0), use week 1 for display purposes
        currentWeek = data.current_week === 0 ? 1 : Math.min(data.current_week, 17);

        // Standings order (rank_points -> wins -> points_for -> head-to-head,
        // per the constitution) is computed and persisted server-side by
        // qpfl/json_scorer.py:update_standings_json - re-deriving it here
        // would drop the head-to-head tiebreaker. Only apply a defensive sort
        // by the persisted `seed` field so a shuffled feed can't silently
        // corrupt playoff seeding; entries without a seed (older historical
        // seasons) keep their existing order. See docs/ROADMAP_2026.md P0.4.
        if (Array.isArray(data.standings) && data.standings.every(t => t.seed != null)) {
            data.standings.sort((a, b) => a.seed - b.seed);
        }
        
        render();
        renderSeasonSelector();
    } catch (error) {
        console.error('Error loading data:', error);
        const failedSeason = currentSeason ? `${currentSeason} season` : 'season data';
        document.getElementById('updated-time').textContent = `Error loading ${failedSeason}`;
        
        // If historical season failed to load, fall back to current
        if (LIVE_SEASON !== null && currentSeason !== LIVE_SEASON) {
            await loadData(LIVE_SEASON);
            return;
        }
        if (!data) {
            showInitialLoadError();
        } else {
            document.body.classList.remove('app-loading');
            document.querySelector('.container')?.removeAttribute('inert');
            document.getElementById('main-content')?.setAttribute('aria-busy', 'false');
        }
    }
}

document.getElementById('app-load-retry')?.addEventListener('click', () => {
    loadData(null, { forceRefresh: true });
});

async function switchToSeasonHome(season) {
    await loadData(season);
    history.pushState(null, '', '#home');
    await navigateToView('home');
    focusMainContentOnMobile();
}

function renderSeasonSelector() {
    const dropdown = document.getElementById('season-dropdown');
    const badge = document.getElementById('season-badge');
    const selector = document.getElementById('season-selector');
    
    badge.textContent = `${currentSeason} Season`;
    
    // Build dropdown options
    dropdown.innerHTML = availableSeasons.map(season => `
        <button class="season-option ${season === currentSeason ? 'active' : ''}"
                ${season === currentSeason ? 'aria-current="true"' : ''}
                data-season="${season}">${season}</button>
    `).join('');
    
    // Add click handlers
    dropdown.querySelectorAll('.season-option').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.stopPropagation();
            const season = parseInt(btn.dataset.season);
            if (season !== currentSeason) {
                if (!confirmManageNavigation('season')) return;
                selector.classList.remove('open');
                badge.setAttribute('aria-expanded', 'false');
                await switchToSeasonHome(season);
            }
            selector.classList.remove('open');
            badge.setAttribute('aria-expanded', 'false');
        });
    });
    
    // Toggle dropdown on badge click
    badge.onclick = (e) => {
        e.stopPropagation();
        const isOpen = selector.classList.toggle('open');
        badge.setAttribute('aria-expanded', String(isOpen));
        if (isOpen) dropdown.querySelector('.season-option.active, .season-option')?.focus();
    };
    
    // Close dropdown when clicking outside
    document.addEventListener('click', () => {
        selector.classList.remove('open');
        badge.setAttribute('aria-expanded', 'false');
    });

    selector.onkeydown = event => {
        if (event.key !== 'Escape' || !selector.classList.contains('open')) return;
        event.preventDefault();
        selector.classList.remove('open');
        badge.setAttribute('aria-expanded', 'false');
        badge.focus();
    };
}

function formatDate(isoString) {
    if (!isoString) return '—';
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return '—';
    return date.toLocaleString('en-US', {
        weekday: 'short',
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        timeZoneName: 'short'
    });
}

function formatRelativeTime(isoString, now = new Date()) {
    const timestamp = new Date(isoString);
    if (Number.isNaN(timestamp.getTime())) return '';
    const seconds = Math.max(0, Math.round((now.getTime() - timestamp.getTime()) / 1000));
    if (seconds < 60) return 'just now';
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 48) return `${hours}h ago`;
    const days = Math.round(hours / 24);
    return `${days}d ago`;
}

function renderUpdatedTime() {
    const element = document.getElementById('updated-time');
    if (!element || !data) return;
    const isHistorical = data.is_historical || data.season !== LIVE_SEASON;
    element.hidden = isHistorical;
    if (isHistorical) return;

    const timestamp = new Date(data.updated_at);
    if (Number.isNaN(timestamp.getTime())) {
        element.textContent = 'Update time unavailable';
        element.classList.remove('stale');
        return;
    }
    const age = Date.now() - timestamp.getTime();
    const staleAfter = data.is_offseason
        ? 14 * 24 * 60 * 60 * 1000
        : 48 * 60 * 60 * 1000;
    const isStale = age > staleAfter;
    const relative = formatRelativeTime(data.updated_at);
    element.textContent = `Updated ${relative}${isStale ? ' · Data may be stale' : ''}`;
    element.title = `Last updated ${formatDate(data.updated_at)}`;
    element.classList.toggle('stale', isStale);
}

setInterval(renderUpdatedTime, 60 * 1000);

// Format transaction message to match: "Added QB Name (TEAM) from FA Pool, released QB Name (TEAM)"
function formatTransactionMessage(tx) {
    const txType = tx.type || '';
    const added = tx.added || tx.activated;
    const released = tx.released;
    
    // Extract player details
    const getPlayerStr = (player) => {
        if (!player) return '';
        if (typeof player === 'object') {
            const pos = player.position || '';
            const name = player.name || '';
            const team = player.nfl_team || '';
            return (pos && team) ? `${pos} ${name} (${team})` : name;
        }
        return player;
    };
    
    // Format pick string for display (e.g., "2027-R3-CWR" -> "CWR 2027 3rd")
    const formatPick = (pick) => {
        if (typeof pick === 'string') {
            const parts = pick.split('-');
            if (parts.length >= 3) {
                const year = parts[0];
                const round = parts[1].replace('R', '');
                const team = parts[2];
                const suffix = round === '1' ? 'st' : round === '2' ? 'nd' : round === '3' ? 'rd' : 'th';
                return `${team} ${year} ${round}${suffix}`;
            }
        }
        return pick;
    };
    
    const addedStr = getPlayerStr(added);
    const releasedStr = getPlayerStr(released);
    
    let msg = '';
    if (txType === 'trade') {
        // New trade format with proposer/partner
        const proposer = tx.proposer || 'Unknown';
        const partner = tx.partner || 'Unknown';
        const gives = tx.proposer_gives || {};
        const receives = tx.proposer_receives || {};
        
        const proposerName = data.teams?.find(t => t.abbrev === proposer)?.name || proposer;
        const partnerName = data.teams?.find(t => t.abbrev === partner)?.name || partner;
        
        const givesPlayers = (gives.players || []).map(p => getPlayerStr(p)).filter(Boolean);
        const givesPicks = (gives.picks || []).map(p => formatPick(p));
        const receivesPlayers = (receives.players || []).map(p => getPlayerStr(p)).filter(Boolean);
        const receivesPicks = (receives.picks || []).map(p => formatPick(p));
        
        const givesAll = [...givesPlayers, ...givesPicks];
        const receivesAll = [...receivesPlayers, ...receivesPicks];
        
        msg = `${proposerName} sends ${givesAll.join(', ') || 'nothing'}; ${partnerName} sends ${receivesAll.join(', ') || 'nothing'}`;
    } else if (txType === 'fa_activation') {
        msg = addedStr ? `Added ${addedStr} from FA Pool` : '';
        if (releasedStr) msg += `, released ${releasedStr}`;
    } else if (txType === 'taxi_activation') {
        msg = addedStr ? `Activated ${addedStr}` : '';
        if (releasedStr) msg += `, released ${releasedStr}`;
    } else if (txType === 'release') {
        msg = releasedStr ? `Released ${releasedStr}` : '';
    } else {
        // Generic format for other types
        msg = txType.replace(/_/g, ' ');
        if (addedStr) msg += `: Added ${addedStr}`;
        if (releasedStr) msg += `, released ${releasedStr}`;
    }
    
    return msg;
}

const SHARED_RESOURCES = {
    hall_of_fame: {
        path: 'data/shared/hall_of_fame.json',
        read: payload => payload || {},
    },
    banners: {
        path: 'data/shared/banners.json',
        read: payload => Array.isArray(payload) ? payload : (payload?.banners || []),
    },
    constitution: {
        path: 'data/shared/constitution.json',
        read: payload => Array.isArray(payload) ? payload : (payload?.articles || []),
    },
    rule_changes_history: {
        path: 'data/shared/rule_changes_history.json',
        read: payload => Array.isArray(payload) ? payload : (payload?.seasons || []),
    },
    transactions: {
        path: 'data/shared/transactions.json',
        read: payload => Array.isArray(payload) ? payload : (payload?.transactions || []),
    },
    drafts: {
        path: 'data/shared/drafts.json',
        read: payload => Array.isArray(payload) ? payload : (payload?.drafts || []),
    },
};

async function ensureSharedResource(name) {
    if (Object.prototype.hasOwnProperty.call(sharedData, name) && sharedData[name] != null) {
        if (data) data[name] = sharedData[name];
        return sharedData[name];
    }
    const config = SHARED_RESOURCES[name];
    if (!config) throw new Error(`Unknown shared resource: ${name}`);
    const value = config.read(await fetchJsonResource(config.path));
    sharedData[name] = value;
    if (data) data[name] = value;
    return value;
}

async function ensureManualHonors() {
    if (manualHonorsData) return manualHonorsData;
    manualHonorsData = await fetchJsonResource('data/shared/manual_honors.json');
    return manualHonorsData;
}

async function ensureCurrentSeasonFiles({ rosters = false, draftPicks = false } = {}) {
    const target = data;
    const base = `data/seasons/${LIVE_SEASON}`;
    const requests = [];
    if (rosters && Object.keys(sharedData.rosters || {}).length === 0) {
        requests.push(fetchJsonResource(`${base}/rosters.json`).then(payload => {
            const value = payload?.rosters || payload || {};
            if (data === target && target.season === LIVE_SEASON) target.rosters = value;
            sharedData.rosters = value;
        }));
    } else if (rosters && target.season === LIVE_SEASON) {
        target.rosters = sharedData.rosters || {};
    }
    if (draftPicks && (sharedData.draft_picks || []).length === 0) {
        requests.push(fetchJsonResource(`${base}/draft_picks.json`).then(payload => {
            const value = payload?.picks || payload || [];
            if (data === target && target.season === LIVE_SEASON) target.draft_picks = value;
            sharedData.draft_picks = value;
        }));
    } else if (draftPicks && target.season === LIVE_SEASON) {
        target.draft_picks = sharedData.draft_picks || [];
    }
    await Promise.all(requests);
}

async function ensureSeasonWeek(week, target = data) {
    const weekNumber = Number(week);
    if (!target || !Number.isFinite(weekNumber)) return null;
    const existing = (target.weeks || []).find(item => item.week === weekNumber);
    if (existing) return existing;

    const weekData = await fetchJsonResource(
        `data/seasons/${target.season}/weeks/week_${weekNumber}.json`,
        { optional: true }
    );
    if (!weekData) return null;
    target.weeks = [...(target.weeks || []), weekData]
        .sort((a, b) => a.week - b.week);
    _statsLeadersCache.dataRef = null;
    return weekData;
}

function seasonWeekNumbers(seasonData) {
    const numbers = new Set(
        (seasonData.weeks_available || []).map(Number).filter(Number.isFinite)
    );
    const lastWeek = Math.min(17, Number(seasonData.current_week) || 0);
    for (let week = 1; week <= lastWeek; week++) numbers.add(week);
    return [...numbers].sort((a, b) => a - b);
}

function calculateTeamStatsFromWeeks(seasonData) {
    const rows = {};
    for (const standing of (seasonData.standings || [])) {
        rows[standing.abbrev] = {
            abbrev: standing.abbrev,
            name: standing.name || standing.team_name || standing.abbrev,
            wins: standing.wins || 0,
            losses: standing.losses || 0,
            ties: standing.ties || 0,
            total_points_for: standing.points_for || 0,
            total_points_against: standing.points_against || 0,
            scores: [],
            ranks: [],
            margins: [],
            results: [],
        };
    }
    for (const week of (seasonData.weeks || []).filter(item => item.has_scores)) {
        const weeklyScores = [];
        for (const matchup of (week.matchups || [])) {
            const sides = [matchup.team1, matchup.team2];
            for (const [index, team] of sides.entries()) {
                if (!team?.abbrev) continue;
                if (!rows[team.abbrev]) {
                    rows[team.abbrev] = {
                        abbrev: team.abbrev, name: team.name || team.team_name || team.abbrev,
                        wins: 0, losses: 0, ties: 0, total_points_for: 0,
                        total_points_against: 0, scores: [], ranks: [], margins: [], results: [],
                    };
                }
                const opponent = sides[index === 0 ? 1 : 0] || {};
                const score = Number(team.total_score) || 0;
                const opponentScore = Number(opponent.total_score) || 0;
                rows[team.abbrev].scores.push({ week: week.week, score });
                rows[team.abbrev].margins.push(score - opponentScore);
                rows[team.abbrev].results.push(score > opponentScore ? 'W' : score < opponentScore ? 'L' : 'T');
                weeklyScores.push({ abbrev: team.abbrev, score });
            }
        }
        weeklyScores.sort((a, b) => b.score - a.score);
        weeklyScores.forEach((team, index) => rows[team.abbrev]?.ranks.push(index + 1));
    }
    const stats = {};
    for (const row of Object.values(rows)) {
        const games = row.scores.length || row.wins + row.losses + row.ties;
        const scoreValues = row.scores.map(item => item.score);
        const average = games ? row.total_points_for / games : 0;
        const variance = scoreValues.length
            ? scoreValues.reduce((sum, score) => sum + (score - average) ** 2, 0) / scoreValues.length
            : 0;
        const best = row.scores.reduce((value, item) => !value || item.score > value.score ? item : value, null);
        const worst = row.scores.reduce((value, item) => !value || item.score < value.score ? item : value, null);
        const lastResult = row.results.at(-1);
        let streakCount = 0;
        for (let index = row.results.length - 1; index >= 0 && row.results[index] === lastResult; index--) streakCount++;
        const winPct = games ? (row.wins + row.ties * 0.5) / games : 0;
        const opr = games ? (5 * average + 2 * ((best?.score || 0) + (worst?.score || 0)) + 3 * winPct * 100) / 10 : 0;
        stats[row.abbrev] = {
            abbrev: row.abbrev,
            name: row.name,
            wins: row.wins,
            losses: row.losses,
            ties: row.ties,
            streak: { type: lastResult || '', count: streakCount },
            total_points_for: row.total_points_for,
            total_points_against: row.total_points_against,
            point_differential: row.total_points_for - row.total_points_against,
            ppg: average,
            ppg_against: games ? row.total_points_against / games : 0,
            avg_margin: row.margins.length ? row.margins.reduce((a, b) => a + b, 0) / row.margins.length : 0,
            avg_rank: row.ranks.length ? row.ranks.reduce((a, b) => a + b, 0) / row.ranks.length : 0,
            std_dev: Math.sqrt(variance),
            best_week: best?.score || 0,
            worst_week: worst?.score || 0,
            best_week_num: best?.week || null,
            worst_week_num: worst?.week || null,
            largest_win: row.margins.length ? Math.max(...row.margins) : 0,
            largest_loss: row.margins.length ? Math.min(...row.margins) : 0,
            win_pct: winPct,
            games_above_500: row.wins - row.losses,
            record: `${row.wins}-${row.losses}${row.ties ? `-${row.ties}` : ''}`,
            opr,
        };
    }
    const values = Object.values(stats);
    const leagueAvgOpr = values.length ? values.reduce((sum, row) => sum + row.opr, 0) / values.length : 0;
    values.forEach(row => {
        row.league_avg_opr = leagueAvgOpr;
        row.adjusted_opr = leagueAvgOpr ? row.opr / leagueAvgOpr : 0;
    });
    return stats;
}

async function ensureAllSeasonWeeks(target = data) {
    if (!target) return;
    await Promise.all(seasonWeekNumbers(target).map(week => ensureSeasonWeek(week, target)));
    target.all_weeks_loaded = true;
    if (!target.team_stats || Object.keys(target.team_stats).length === 0) {
        target.team_stats = calculateTeamStatsFromWeeks(target);
    }
}

async function ensureHomeWeekData() {
    if (!data || data.is_offseason || data.is_historical) return;
    const available = seasonWeekNumbers(data);
    const recapWeek = available.filter(week => week < currentWeek).at(-1);
    await Promise.all([
        ensureSeasonWeek(currentWeek),
        recapWeek ? ensureSeasonWeek(recapWeek) : Promise.resolve(),
    ]);
}

async function prepareViewData(view, subview) {
    if (!data) return;
    if (view === 'home') {
        if (data.is_historical || data.is_offseason) {
            await Promise.all([
                ensurePreviousSeasonLoaded(),
                ensureSharedResource('banners'),
                ensureSharedResource('transactions'),
            ]);
        } else {
            await ensureHomeWeekData();
        }
    } else if (view === 'matchups' || view === 'standings') {
        await Promise.all([
            ensureAllSeasonWeeks(),
            ensureSharedResource('hall_of_fame'),
        ]);
    } else if (view === 'teams') {
        const requests = [ensureAllSeasonWeeks()];
        if (data.season === LIVE_SEASON) {
            requests.push(ensureCurrentSeasonFiles({ rosters: true, draftPicks: true }));
        }
        if (['history', 'activity', 'compare'].includes(subview)) {
            requests.push(ensureSharedResource('hall_of_fame'));
        }
        if (subview === 'activity') {
            requests.push(ensureSharedResource('transactions'));
        }
        if (subview === 'history') {
            requests.push(ensureSharedResource('banners'), ensureManualHonors());
        }
        await Promise.all(requests);
    } else if (view === 'stats') {
        await ensureAllSeasonWeeks();
    } else if (view === 'history') {
        if (subview === 'banners') await ensureSharedResource('banners');
        else if (subview === 'rules') {
            await Promise.all([
                ensureSharedResource('constitution'),
                ensureSharedResource('rule_changes_history'),
            ]);
        } else {
            await Promise.all([
                ensureSharedResource('hall_of_fame'),
                ensureManualHonors(),
            ]);
        }
    } else if (view === 'transactions') {
        await Promise.all([
            ensureSharedResource('transactions'),
            ensureSharedResource('hall_of_fame'),
        ]);
    } else if (view === 'drafts' && subview !== 'challenge') {
        await Promise.all([
            ensureSharedResource('drafts'),
            ensureSharedResource('hall_of_fame'),
            ensureCurrentSeasonFiles({ rosters: true, draftPicks: true }),
        ]);
    } else if (view === 'manage') {
        await Promise.all([
            ensureCurrentSeasonFiles({ rosters: true, draftPicks: true }),
            ensureHomeWeekData(),
        ]);
    }
}

// Map of view name to its render function. Views not listed here
// (manage) are initialized in navigateToView via init*().
// Each entry renders all content reachable from that top-level nav item;
// per-subview lazy-rendering happens inside the per-view renderer.
const VIEW_RENDERERS = {
    home: () => renderHome(),
    matchups: () => { renderWeekSelector(); renderMatchups(); renderSchedule(); },
    standings: () => renderStandings(),
    teams: async subview => {
        if (subview === 'all-rosters') await renderAllRosters();
        renderTeams();
        renderActiveTeamSubview(subview);
    },
    stats: () => { renderStatsLeaders(); renderTeamStats(); },
    history: subview => {
        if (subview === 'banners') renderBanners();
        else if (subview === 'rules') { renderConstitution(); renderRuleChanges(); }
        else renderHallOfFame();
    },
    transactions: () => renderTransactions(),
    drafts: subview => { if (subview !== 'challenge') renderDrafts(); },
};

// Maps from old hash paths (pre-restructure) to the new path. Bookmarked URLs
// keep working.
const LEGACY_HASH_REDIRECTS = {
    'all-rosters': 'teams/all-rosters',
    'compare': 'teams/compare',
    'schedule': 'matchups/schedule',
    'team-stats': 'stats/team',
    'hof': 'history/records',
    'hof/records': 'history/records',
    'hof/teams': 'teams/history',
    'hof/banners': 'history/banners',
    'hof/constitution': 'history/rules',
    'hof/rule-changes': 'history/rules',
    'history/constitution': 'history/rules',
    'history/rule-changes': 'history/rules',
    'history/lore': 'history/records',
    'history/transactions': 'transactions',
    'history/teams': 'teams/history',
    'drafts': 'drafts/history',
    'history/drafts': 'drafts/history',
    'nfl-draft': 'drafts/challenge',
    'commissioner': 'manage/commissioner',
};

// Default subview for each view that has subviews. Used when the URL is
// just `#view` without a subview portion.
const DEFAULT_SUBVIEW = {
    matchups: 'week',
    teams: 'all-rosters',
    stats: 'leaders',
    history: 'records',
    drafts: 'history',
};

const PAGE_DESCRIPTIONS = {
    home: 'The latest QPFL matchups, standings, performances, and league activity.',
    matchups: 'View weekly QPFL matchups, scores, rosters, and the season schedule.',
    standings: 'Track the QPFL standings, rank points, records, and playoff outlook.',
    teams: 'Explore every QPFL franchise, roster, Hall of Fame, and transaction.',
    stats: 'Explore QPFL player leaders and team performance across the season.',
    transactions: 'Review QPFL trades, free-agent moves, taxi activations, and releases.',
    history: 'Browse QPFL records, champions, rivalries, and league rules.',
    drafts: 'Review QPFL draft history, expansion drafts, and the NFL Draft Challenge.',
    manage: 'Manage your QPFL lineup, depth chart, roster moves, and trades.',
};

function pageTitleFor(view, subview, detail) {
    const season = currentSeason || data?.season;
    if (view === 'matchups') {
        return subview === 'schedule'
            ? `${season} Schedule · QPFL`
            : `Week ${detail || currentWeek} Matchups · QPFL`;
    }
    if (view === 'standings') return `${season} Standings · QPFL`;
    if (view === 'transactions') return `${season} Transactions · QPFL`;
    if (view === 'teams') {
        if (['roster', 'history', 'activity'].includes(subview)) {
            const abbrev = decodeURIComponent(detail || currentTeam || '');
            const team = data?.teams?.find(candidate => candidate.abbrev === abbrev)
                || data?.standings?.find(candidate => candidate.abbrev === abbrev);
            const teamName = team?.name || team?.team_name || abbrev || 'Team';
            const labels = {
                roster: 'Roster',
                history: 'Hall of Fame',
                activity: 'Activity',
            };
            return `${teamName} ${labels[subview]} · QPFL`;
        }
        if (subview === 'compare') return 'Compare Teams · QPFL';
        return 'All Rosters · QPFL';
    }
    if (view === 'stats') return `${subview === 'team' ? 'Team Stats' : 'Player Leaders'} · QPFL`;
    if (view === 'history') {
        const labels = {
            records: 'League Hall of Fame',
            teams: 'Team Halls',
            banners: 'Champions',
            rules: 'Constitution & Rules',
        };
        return `${labels[subview] || 'League History'} · QPFL`;
    }
    if (view === 'drafts') return `${subview === 'challenge' ? 'NFL Draft Challenge' : 'Draft History'} · QPFL`;
    if (view === 'manage') return `${subview === 'commissioner' ? 'Commissioner' : 'My Team'} · QPFL`;
    return `${season ? `${season} Season` : 'Dynasty Fantasy Football'} · QPFL`;
}

function updatePageMetadata(view, subview, detail) {
    const title = pageTitleFor(view, subview || DEFAULT_SUBVIEW[view], detail);
    const description = PAGE_DESCRIPTIONS[view] || PAGE_DESCRIPTIONS.home;
    document.title = title;
    document.querySelector('meta[name="description"]')?.setAttribute('content', description);
    document.querySelector('meta[property="og:title"]')?.setAttribute('content', title);
    document.querySelector('meta[property="og:description"]')?.setAttribute('content', description);
    document.querySelector('meta[property="og:url"]')?.setAttribute('content', location.href);
    document.querySelector('meta[name="twitter:title"]')?.setAttribute('content', title);
    document.querySelector('meta[name="twitter:description"]')?.setAttribute('content', description);
}

const viewFresh = new Set();

async function ensureViewRendered(view, subview = DEFAULT_SUBVIEW[view]) {
    if (!data) return;
    const renderer = VIEW_RENDERERS[view];
    if (!renderer) return;
    if (viewFresh.has(view)) return;
    const viewElement = document.getElementById(`${view}-view`);
    viewElement?.setAttribute('aria-busy', 'true');
    try {
        await prepareViewData(view, subview);
        await renderer(subview);
        viewFresh.add(view);
    } catch (error) {
        console.error(`Error loading ${view} data:`, error);
        const activePanel = viewElement?.querySelector('.subview.active, .team-subview.active') || viewElement;
        activePanel?.insertAdjacentHTML(
            'afterbegin',
            '<p class="view-load-error" role="alert">This section could not be loaded. Please try again.</p>'
        );
    } finally {
        viewElement?.setAttribute('aria-busy', 'false');
    }
}

function getActiveView() {
    const active = document.querySelector('.view-container.active');
    if (!active) return 'home';
    return active.id.replace(/-view$/, '');
}

function render() {
    document.body.classList.remove('app-loading');
    document.body.classList.remove('app-load-error');
    const loadErrorPanel = document.getElementById('app-load-error-panel');
    if (loadErrorPanel) loadErrorPanel.hidden = true;
    document.querySelector('.container')?.removeAttribute('inert');
    document.getElementById('main-content')?.setAttribute('aria-busy', 'false');
    document.getElementById('season-badge').textContent = `${data.season} Season`;
    renderUpdatedTime();

    const isHistorical = data.is_historical || data.season !== LIVE_SEASON;

    // Hide the Schedule subview tab for historical seasons (no upcoming schedule).
    const matchupsScheduleBtn = document.querySelector(
        '#matchups-view .subnav-btn[data-subview="schedule"]'
    );
    if (matchupsScheduleBtn) matchupsScheduleBtn.style.display = isHistorical ? 'none' : '';
    const matchupsSubviewNav = document.querySelector('#matchups-view > .subnav');
    if (matchupsSubviewNav) matchupsSubviewNav.hidden = isHistorical;

    // If currently on My Team when switching to a historical season, redirect to Matchups.
    if (isHistorical) {
        const activeView = document.querySelector('.nav-btn.active');
        if (activeView && activeView.dataset.view === 'manage') {
            document.querySelector('.nav-btn[data-view="matchups"]').click();
        }
    }

    // Data changed: every view is now stale.
    viewFresh.clear();
    renderLineupReminder();

    if (!render._hashApplied) {
        render._hashApplied = true;
        applyHash();
        initGlobalAuth();
    } else {
        // Subsequent calls (season switch): render whatever is currently active.
        const activeView = getActiveView();
        const route = parseHashRoute();
        const activeSubview = route.subview || DEFAULT_SUBVIEW[activeView];
        const activeDetail = route.detail;
        updatePageMetadata(activeView, activeSubview, activeDetail);
        ensureViewRendered(activeView, activeSubview);

        // Re-init My Team so its dashboard and tools reflect the latest data.
        if (activeView === 'manage') {
            prepareViewData('manage').then(() => initManageRoster());
        }

        // Re-init compare if the Teams → Compare subview is currently visible
        // so its selectors refresh against the new season's data.
        const compareSubviewActive = document.getElementById('team-compare-subview')?.classList.contains('active');
        if (compareSubviewActive) initCompareView();
    }
}

function centerActiveScrollableItem(container, selector) {
    const activeItem = container?.querySelector(selector);
    if (!activeItem) return;
    requestAnimationFrame(() => {
        if (!container.clientWidth) return;
        const centeredLeft = activeItem.offsetLeft
            - (container.clientWidth - activeItem.offsetWidth) / 2;
        container.scrollTo({ left: Math.max(0, centeredLeft), behavior: 'auto' });
    });
}

function renderWeekSelector() {
    const container = document.getElementById('week-selector');
    
    // Collect all weeks from both weeks data and schedule (for playoffs)
    const allWeeks = new Set([
        ...(data.weeks || []).map(week => week.week),
        ...(data.weeks_available || []).map(Number),
    ]);
    if (data.current_week > 0 && data.current_week <= 17) allWeeks.add(data.current_week);
    if (data.schedule) {
        data.schedule.forEach(w => allWeeks.add(w.week));
    }
    const weekNumbers = Array.from(allWeeks).sort((a, b) => a - b);
    
    container.innerHTML = `
        <span class="week-label">WEEK</span>
        ${weekNumbers.map(weekNum => {
            const scheduleWeek = data.schedule?.find(w => w.week === weekNum);
            const isPlayoffs = scheduleWeek?.is_playoffs;
            const playoffClass = isPlayoffs ? 'playoff' : '';
            return `
                <button class="week-btn ${weekNum === currentWeek ? 'active' : ''} ${playoffClass}"
                        id="matchups-week-${weekNum}-tab" role="tab"
                        aria-selected="${weekNum === currentWeek}" aria-controls="matchups-container"
                        tabindex="${weekNum === currentWeek ? '0' : '-1'}"
                        data-week="${weekNum}">${weekNum}</button>
            `;
        }).join('')}
    `;

    document.getElementById('matchups-container')?.setAttribute(
        'aria-labelledby', `matchups-week-${currentWeek}-tab`
    );

    container.querySelectorAll('.week-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            currentWeek = parseInt(btn.dataset.week);
            renderWeekSelector();
            const matchupsContainer = document.getElementById('matchups-container');
            matchupsContainer?.setAttribute('aria-busy', 'true');
            try {
                await ensureSeasonWeek(currentWeek);
                renderMatchups();
            } finally {
                matchupsContainer?.setAttribute('aria-busy', 'false');
            }
            history.replaceState(null, '', `#matchups/week/${currentWeek}`);
            updatePageMetadata('matchups', 'week', String(currentWeek));
        });
    });

    centerActiveScrollableItem(container, '.week-btn.active');
}

function renderHome() {
    // Offseason: current_week is 0 (pre-season), 18+ (post-season), or explicit flag
    const isOffseason = data.is_offseason || data.current_week === 0 || data.current_week >= 17 || data.is_historical;
    
    const seasonContent = document.getElementById('home-season-content');
    const offseasonContent = document.getElementById('home-offseason-content');
    
    if (isOffseason) {
        seasonContent.style.display = 'none';
        offseasonContent.style.display = 'block';
        renderHomeOffseason();
    } else {
        seasonContent.style.display = 'block';
        offseasonContent.style.display = 'none';
        renderHomeSeason();
    }
}

// Assemble the previous season from its split metadata, standings, and week files.
async function ensurePreviousSeasonLoaded() {
    if (data.previous_season) return;
    const prev = (data.season || LIVE_SEASON) - 1;
    const target = data;
    if (!availableSeasons.includes(prev)) {
        await ensureAllSeasonWeeks(target);
        return;
    }
    try {
        const previous = await loadSeasonBase(prev);
        await ensureAllSeasonWeeks(previous);
        if (data === target) target.previous_season = previous;
    } catch (e) {
        if (data === target) await ensureAllSeasonWeeks(target);
    }
}

function renderHomeSeason() {
    // Render current week matchups
    const matchupsContainer = document.getElementById('home-matchups');
    const weekData = data.weeks.find(w => w.week === currentWeek);
    
    if (weekData && weekData.matchups) {
        matchupsContainer.innerHTML = weekData.matchups.map(m => {
            const t1 = m.team1 || {};
            const t2 = m.team2 || {};
            const t1Name = typeof t1 === 'string' ? t1 : (t1.team_name || t1.abbrev || 'TBD');
            const t2Name = typeof t2 === 'string' ? t2 : (t2.team_name || t2.abbrev || 'TBD');
            const t1Code = typeof t1 === 'string' ? t1 : t1.abbrev;
            const t2Code = typeof t2 === 'string' ? t2 : t2.abbrev;
            const t1Score = typeof t1 === 'object' ? (t1.total_score ?? '-') : '-';
            const t2Score = typeof t2 === 'object' ? (t2.total_score ?? '-') : '-';
            
            const t1Winner = t1Score > t2Score ? 'winner' : (t1Score < t2Score ? 'loser' : '');
            const t2Winner = t2Score > t1Score ? 'winner' : (t2Score < t1Score ? 'loser' : '');
            
            return `
                <div class="home-matchup" data-route="#matchups/week/${currentWeek}">
                    <div class="home-matchup-team ${t1Winner}">
                        ${teamProfileButton(t1Code, t1Name)}
                        <span class="home-matchup-score">${t1Score}</span>
                    </div>
                    <span class="home-matchup-vs">vs</span>
                    <div class="home-matchup-team ${t2Winner}" style="justify-content: flex-end; text-align: right;">
                        <span class="home-matchup-score">${t2Score}</span>
                        ${teamProfileButton(t2Code, t2Name)}
                    </div>
                </div>
            `;
        }).join('');
    } else {
        matchupsContainer.innerHTML = emptyStateHtml(
            'No matchups available yet',
            'The full season view may have more scheduling information.',
            [{ label: 'View schedule', route: '#matchups/schedule' }]
        );
    }
    
    // Render standings
    const standingsContainer = document.getElementById('home-standings');
    standingsContainer.innerHTML = data.standings.map((team, i) => `
        <div class="home-standing-row" data-route="#teams/roster/${encodeURIComponent(team.abbrev)}">
            <span class="home-standing-rank">${i + 1}.</span>
            ${teamProfileButton(team.abbrev, team.team_name || team.name || team.abbrev, 'home-standing-team')}
            <span class="home-standing-rp">${team.rank_points?.toFixed(1) || 0} RP</span>
            <span class="home-standing-record">${team.wins || 0}-${team.losses || 0}</span>
        </div>
    `).join('');

    setHomeCardLink('home-matchups-footer', 'View All Matchups →', `#matchups/week/${currentWeek}`);
    setHomeCardLink('home-current-standings-footer', 'View Full Standings →', '#standings');
    setHomeCardLink('home-current-transactions-footer', 'View All Transactions →', '#transactions');
    
    // Render transactions from the last seven days (capped at five).
    renderHomeTransactions();

    // Render last completed week's recap
    renderWeeklyRecap();
}

function setHomeCardLink(footerId, label, route) {
    const footer = document.getElementById(footerId);
    if (!footer) return;
    footer.innerHTML = `<a class="home-card-link" href="${escapeHtml(route)}" data-route="${escapeHtml(route)}">${escapeHtml(label)}</a>`;
}

// Sums the scores of starters in a roster.
function sumStarterScores(roster) {
    if (!Array.isArray(roster)) return 0;
    return roster.reduce((sum, p) => sum + (p.starter ? (p.score || 0) : 0), 0);
}

// Returns the highest-scoring starter (or null if none).
function topStarter(roster) {
    if (!Array.isArray(roster)) return null;
    let best = null;
    for (const p of roster) {
        if (!p.starter) continue;
        if (!best || (p.score || 0) > (best.score || 0)) best = p;
    }
    return best;
}

// Picks the worst bench mistake on a team for one week:
// a non-starter player whose score exceeded the starter at their position
// by the largest margin. (Compares within position group only.)
function worstBenchMistake(roster) {
    if (!Array.isArray(roster)) return null;
    const byPos = {};
    for (const p of roster) {
        const pos = p.position || '';
        if (!byPos[pos]) byPos[pos] = { starters: [], bench: [] };
        if (p.starter) byPos[pos].starters.push(p);
        else byPos[pos].bench.push(p);
    }
    let worst = null;
    for (const pos in byPos) {
        const { starters, bench } = byPos[pos];
        if (!starters.length || !bench.length) continue;
        // Lowest-scoring starter is the candidate to be replaced.
        const weakStarter = starters.reduce((min, p) =>
            (p.score || 0) < (min.score || 0) ? p : min
        );
        const topBench = bench.reduce((max, p) =>
            (p.score || 0) > (max.score || 0) ? p : max
        );
        const margin = (topBench.score || 0) - (weakStarter.score || 0);
        if (margin > 0 && (!worst || margin > worst.margin)) {
            worst = { benched: topBench, started: weakStarter, margin, position: pos };
        }
    }
    return worst;
}

// Computes optimal lineup from a roster array. Returns null if no starters have scores.
// Uses the actual starter slot counts from the submitted lineup.
function computeOptimalLineup(roster) {
    if (!Array.isArray(roster)) return null;

    // Count starter slots per position from the submitted lineup
    const slotCounts = {};
    for (const p of roster) {
        if (p.taxi || !p.starter || !Number.isFinite(p.score)) continue;
        slotCounts[p.position] = (slotCounts[p.position] || 0) + 1;
    }
    if (Object.keys(slotCounts).length === 0) return null;

    // Group all players by position (only scored players)
    const byPos = {};
    for (const p of roster) {
        if (p.taxi || !Number.isFinite(p.score)) continue;
        if (!byPos[p.position]) byPos[p.position] = [];
        byPos[p.position].push(p);
    }

    let optimalTotal = 0;
    let actualStarterTotal = 0;
    const mistakes = []; // bench players who outscored a starter at same position

    for (const [pos, count] of Object.entries(slotCounts)) {
        const players = byPos[pos] || [];
        const sorted = [...players].sort((a, b) => (b.score || 0) - (a.score || 0));
        for (let i = 0; i < Math.min(count, sorted.length); i++) {
            optimalTotal += sorted[i].score || 0;
        }
        const starters = players.filter(p => p.starter);
        for (const p of starters) actualStarterTotal += p.score || 0;

        // Flag bench players that beat the worst starter
        if (starters.length > 0) {
            const worstScore = Math.min(...starters.map(p => p.score || 0));
            const worstStarter = starters.find(p => (p.score || 0) === worstScore);
            for (const bp of players.filter(p => !p.starter)) {
                if ((bp.score || 0) > worstScore) {
                    mistakes.push({ benched: bp, started: worstStarter, margin: (bp.score || 0) - worstScore });
                }
            }
        }
    }

    return {
        optimalTotal,
        actualStarterTotal,
        leftOnBench: Math.max(0, optimalTotal - actualStarterTotal),
        mistakes
    };
}

function calculateOwnerSuccessByTeam() {
    const totals = {};
    const regularSeasonGames = Object.fromEntries((data.standings || []).map(team => [
        team.abbrev,
        (team.wins || 0) + (team.losses || 0) + (team.ties || 0)
    ]));

    for (const week of data.weeks || []) {
        for (const matchup of week.matchups || []) {
            for (const team of [matchup.team1, matchup.team2]) {
                if (!team?.abbrev || (week.week || 0) > (regularSeasonGames[team.abbrev] || 0)) continue;
                const lineup = computeOptimalLineup(team.roster);
                if (!lineup || lineup.optimalTotal <= 0) continue;

                const stats = totals[team.abbrev] || {
                    lineup_actual_points: 0,
                    lineup_optimal_points: 0,
                    points_left_on_table: 0,
                    lineup_weeks: 0
                };
                stats.lineup_actual_points += lineup.actualStarterTotal;
                stats.lineup_optimal_points += lineup.optimalTotal;
                stats.points_left_on_table += lineup.leftOnBench;
                stats.lineup_weeks += 1;
                totals[team.abbrev] = stats;
            }
        }
    }

    Object.values(totals).forEach(stats => {
        stats.owner_success_rate = stats.lineup_actual_points / stats.lineup_optimal_points * 100;
        stats.points_left_on_table_pct = stats.points_left_on_table / stats.lineup_optimal_points * 100;
    });
    return totals;
}

// Returns HTML snippet showing optimal lineup summary for a roster.
// Returns empty string when there are no scores or no improvement possible.
function renderOptimalSummary(roster) {
    const opt = computeOptimalLineup(roster);
    if (!opt || opt.leftOnBench < 0.5) return '';

    const mistakeLines = opt.mistakes
        .sort((a, b) => b.margin - a.margin)
        .slice(0, 3)
        .map(m => `<span class="bench-mistake-item">${escapeHtml(m.benched.name)} (${m.benched.position}) +${m.margin.toFixed(0)} pts</span>`)
        .join('');

    return `
        <div class="optimal-summary">
            <div class="optimal-row">
                <span class="optimal-label">Optimal</span>
                <span class="optimal-score">${opt.optimalTotal.toFixed(0)} pts</span>
                <span class="optimal-delta">+${opt.leftOnBench.toFixed(0)} left on bench</span>
            </div>
            ${mistakeLines ? `<div class="bench-mistakes-list">${mistakeLines}</div>` : ''}
        </div>
    `;
}

function renderWeeklyRecap() {
    const card = document.getElementById('home-recap-card');
    const container = document.getElementById('home-recap');
    const weekLabel = document.getElementById('home-recap-week');
    if (!card || !container) return;

    // Find the most recent completed week (has_scores or starter scores present)
    const completed = (data.weeks || [])
        .filter(w => w.has_scores && w.matchups && w.matchups.length)
        .sort((a, b) => b.week - a.week);
    if (!completed.length) {
        card.style.display = 'none';
        document.getElementById('home-recap-footer')?.replaceChildren();
        return;
    }
    const week = completed[0];
    weekLabel.textContent = `Week ${week.week}`;

    let topPlayer = null;       // { player, team }
    let topTeamTotal = null;    // { team, total }
    let biggestBlowout = null;  // { winner, loser, margin }
    let closestGame = null;     // { team1, team2, margin }
    let worstMistake = null;    // { benched, started, margin, team }

    for (const m of week.matchups) {
        const t1 = m.team1, t2 = m.team2;
        if (!t1 || !t2) continue;

        const teamTotal = (t) => (typeof t.total_score === 'number')
            ? t.total_score
            : sumStarterScores(t.roster);
        const t1Total = teamTotal(t1);
        const t2Total = teamTotal(t2);

        if (!topTeamTotal || t1Total > topTeamTotal.total) {
            topTeamTotal = { team: t1, total: t1Total };
        }
        if (t2Total > topTeamTotal.total) {
            topTeamTotal = { team: t2, total: t2Total };
        }

        const margin = Math.abs(t1Total - t2Total);
        const winner = t1Total >= t2Total ? t1 : t2;
        const loser = t1Total >= t2Total ? t2 : t1;
        if (!biggestBlowout || margin > biggestBlowout.margin) {
            biggestBlowout = { winner, loser, margin };
        }
        if (!closestGame || margin < closestGame.margin) {
            closestGame = { team1: t1, team2: t2, margin, t1Total, t2Total };
        }

        for (const team of [t1, t2]) {
            const ts = topStarter(team.roster);
            if (ts && (!topPlayer || (ts.score || 0) > (topPlayer.player.score || 0))) {
                topPlayer = { player: ts, team };
            }
            const m2 = worstBenchMistake(team.roster);
            if (m2 && (!worstMistake || m2.margin > worstMistake.margin)) {
                worstMistake = { ...m2, team };
            }
        }
    }

    const teamLabel = (t) => t?.team_name || t?.name || t?.abbrev || 'TBD';
    const fmt = (n) => (n ?? 0).toFixed(1);

    const items = [];
    if (topTeamTotal) {
        items.push({
            label: 'Top Team',
            value: `${teamLabel(topTeamTotal.team)} (${fmt(topTeamTotal.total)})`,
        });
    }
    if (topPlayer) {
        items.push({
            label: 'Top Player',
            value: `${topPlayer.player.name} — ${fmt(topPlayer.player.score)} pts (${teamLabel(topPlayer.team)})`,
        });
    }
    if (biggestBlowout && biggestBlowout.margin > 0) {
        items.push({
            label: 'Biggest Blowout',
            value: `${teamLabel(biggestBlowout.winner)} over ${teamLabel(biggestBlowout.loser)} by ${fmt(biggestBlowout.margin)}`,
        });
    }
    if (closestGame) {
        items.push({
            label: 'Closest Game',
            value: `${teamLabel(closestGame.team1)} ${fmt(closestGame.t1Total)} – ${fmt(closestGame.t2Total)} ${teamLabel(closestGame.team2)} (margin ${fmt(closestGame.margin)})`,
        });
    }
    if (worstMistake) {
        items.push({
            label: 'Bench Mistake',
            value: `${teamLabel(worstMistake.team)} sat ${worstMistake.benched.name} (${fmt(worstMistake.benched.score)}) over ${worstMistake.started.name} (${fmt(worstMistake.started.score)}) at ${worstMistake.position}`,
        });
    }

    if (!items.length) {
        card.style.display = 'none';
        return;
    }

    card.style.display = '';
    container.innerHTML = items.map(it => `
        <div class="home-recap-row">
            <span class="home-recap-label">${it.label}</span>
            <span class="home-recap-value">${it.value}</span>
        </div>
    `).join('');
    setHomeCardLink(
        'home-recap-footer',
        `Open Week ${week.week} →`,
        `#matchups/week/${week.week}`
    );
}

function extractDateFromMessage(message) {
    // Extract date from beginning of message if present
    // Format: "MM/DD/YY | rest of message" or "MM/DD/YYYY | rest of message"
    if (!message) return { date: null, cleanMessage: message };

    const dateMatch = message.match(/^(\d{1,2}\/\d{1,2}\/(?:\d{2}|\d{4}))\s*\|\s*(.*)$/);
    if (dateMatch) {
        return {
            date: dateMatch[1],
            cleanMessage: dateMatch[2].trim()
        };
    }

    const approximateMatch = message.match(/^(approximate week)\s*\|\s*(.*)$/i);
    if (approximateMatch) {
        return {
            date: approximateMatch[1],
            cleanMessage: approximateMatch[2].trim()
        };
    }

    return { date: null, cleanMessage: message };
}

function getTransactionDate(tx) {
    // Try to get date from message first, then timestamp, then show "Date missing"
    let dateStr = '';
    let cleanMessage = tx.message;

    // First check if date is in the message
    if (tx.message) {
        const extracted = extractDateFromMessage(tx.message);
        if (extracted.date) {
            dateStr = extracted.date;
            cleanMessage = extracted.cleanMessage;
        }
    }

    // Fall back to timestamp if no date in message
    if (!dateStr && tx.timestamp) {
        const d = new Date(tx.timestamp);
        dateStr = `${d.getMonth()+1}/${d.getDate()}/${d.getFullYear()}`;
    }

    // Show "Date missing" if still no date
    if (!dateStr) {
        dateStr = 'Date missing';
    }

    return { dateStr, cleanMessage };
}

function parseOldTradeMessage(message) {
    // Parse old pipe-separated trade format
    // Format: "Date | To Team1: | item | item | To Team2: | item | Corresponding moves | ..."
    // Or: "Date | Team1 | item | item | Team2 | item | Corresponding moves | ..."
    if (!message || !message.includes('|')) return null;

    const parts = message.split('|').map(s => s.trim());
    const result = { teams: [], correspondingMoves: [] };
    let currentTeam = null;
    let inCorrespondingMoves = false;
    const isDate = (part) => /^\d{1,2}\/\d{1,2}\/(?:\d{2}|\d{4})$/.test(part);
    const hasExplicitTeamHeaders = parts.some(part =>
        /^to\s+.+/i.test(part) || /\s+gets?:?$/i.test(part)
    );

    const getExplicitTeamName = (part) => {
        if (!/^to\s+.+/i.test(part) && !/\s+gets?:?$/i.test(part)) return null;

        return part
            .replace(/^to\s+/i, '')
            .replace(/:$/, '')
            .replace(/\s+gets?$/i, '')
            .trim();
    };

    // Helper to detect if a part is likely a team name vs an item
    const looksLikeTeamName = (part) => {
        // Skip empty or very long parts
        if (!part || part.length > 30) return false;

        // Skip dates
        if (isDate(part)) return false;

        // Skip draft pick formats (e.g., "3.03", "1.05", "2.10")
        if (part.match(/^\d+\.\d+$/)) return false;

        // Skip if contains draft pick pattern anywhere (e.g., "Taxi 1.07", "Pick 3.07")
        if (part.match(/\d+\.\d+/)) return false;

        // Skip if mostly numbers and dots (likely a pick reference)
        const nonNumericDot = part.replace(/[0-9.]/g, '');
        if (nonNumericDot.length === 0) return false;

        // Skip if contains "taxi" or "pick" (common in draft pick references)
        if (/\b(taxi|pick)\b/i.test(part)) return false;

        // Skip if it contains typical item indicators
        const itemIndicators = /\b(?:RB|WR|TE|QB|K|D\/ST|DST)\b|202[0-9]|\b(?:round|1st|2nd|3rd|4th)\b|[()]/i;
        if (itemIndicators.test(part)) return false;

        // Team names are typically short (1-3 words)
        const wordCount = part.split(/\s+/).length;
        return wordCount <= 3;
    };

    for (let part of parts) {
        // Skip empty parts
        if (!part) continue;

        // Check for corresponding-roster-move headers used by the historical records.
        if (/^(in )?corresponding( moves?)?:?$/i.test(part)) {
            inCorrespondingMoves = true;
            currentTeam = null;
            continue;
        }

        // Skip dates and historical entries that only provide an approximate date.
        if (isDate(part) || /^approximate week$/i.test(part)) {
            continue;
        }

        // Check for "To Team:" and "Team gets:" formats.
        const explicitTeamName = getExplicitTeamName(part);
        if (explicitTeamName) {
            currentTeam = { name: explicitTeamName, items: [] };
            result.teams.push(currentTeam);
            inCorrespondingMoves = false;
            continue;
        }

        // If we're in corresponding moves section, add to that
        if (inCorrespondingMoves) {
            result.correspondingMoves.push(part);
            continue;
        }

        // Detect team names without "To " prefix
        if (!hasExplicitTeamHeaders && (!currentTeam || looksLikeTeamName(part))) {
            // Start a new team if this looks like a team name
            // But only if we don't have 2 teams yet (most trades are 2-way)
            if (!currentTeam || result.teams.length < 2) {
                currentTeam = { name: part, items: [] };
                result.teams.push(currentTeam);
                continue;
            }
        }

        // Otherwise, it's an item for the current team
        if (currentTeam) {
            currentTeam.items.push(part);
        }
    }

    // In every stored format ("To Team:", "Team gets:", and bare "Team | …"),
    // the items listed after a team name are what that team RECEIVES, which is
    // exactly how the renderer labels them ("<team> receives:"). So no swap.

    result.teams.forEach(team => {
        team.name = normalizeCoOwnerLabel(team.name);
    });
    return result;
}

function normalizeCoOwnerLabel(label) {
    if (!label) return label;

    const legacyCoOwnerLabels = {
        'Tim/Redacted Yoder': 'Redacted Yoder & Tim Grazier',
        'Tim/Spencer Yoder': 'Spencer Yoder & Tim Grazier',
        'Spencer/Tim': 'Spencer Yoder & Tim Grazier',
        'Tim/Spencer': 'Spencer Yoder & Tim Grazier',
        'Tim/Redacted': 'Redacted Yoder & Tim Grazier',
        'Joe Kuhl/Joe Ward': 'Joe Kuhl & Joe Ward',
        'Joe Kuhl/Censored Ward': 'Joe Kuhl & Censored Ward',
        'Joe Censored/Censored Ward': 'Joe Censored & Censored Ward',
        'Joe/Censored': 'Joe Censored & Censored Ward'
    };
    const currentJoeOwner = data?.teams?.find(team => team.abbrev === 'J/J')?.owner;
    const joeOwnerLabel = legacyCoOwnerLabels[currentJoeOwner]
        || currentJoeOwner
        || 'Joe Kuhl & Censored Ward';

    let normalized = String(label);
    Object.entries(legacyCoOwnerLabels).forEach(([legacy, canonical]) => {
        normalized = normalized.replaceAll(legacy, canonical);
    });
    return normalized.replaceAll('Joe/Joe', joeOwnerLabel);
}

function compactOwnerLabel(owner) {
    const normalizedOwner = normalizeCoOwnerLabel(owner);
    const names = normalizedOwner
        .split(/\s*(?:&|\/)\s*/)
        .filter(Boolean);
    if (names.length > 1) return names.join(' & ');
    return names[0]?.split(/\s+/)[0] || normalizedOwner;
}

function teamLabel(abbrev) {
    const owner = data.teams?.find(t => t.abbrev === abbrev)?.owner;
    return owner ? compactOwnerLabel(owner) : abbrev;
}

const OWNER_TEAM_CODES = {
    jrw: 'JRW',
    jdk: 'JDK',
    rcp: 'RCP',
    mpa: 'MPA',
    griff: 'GSA',
    griffin: 'GSA',
    'griffin ansel': 'GSA',
    kaminska: 'CGK',
    'connor kaminska': 'CGK',
    'connor k': 'CGK',
    'connor k.': 'CGK',
    redacted: 'CGK',
    'redacted kaminska': 'CGK',
    connor: 'CWR',
    'connor r': 'CWR',
    reardon: 'CWR',
    'connor reardon': 'CWR',
    'jack reardon': 'CWR',
    'redacted reardon': 'CWR',
    bocki: 'RCP',
    diana: 'RCP',
    'ryan przybocki': 'RCP',
    miles: 'MPA',
    'miles agus': 'MPA',
    bill: 'WJK',
    'bill kuhl': 'WJK',
    ryan: 'RPA',
    'ryan ansel': 'RPA',
    spencer: 'S/T',
    tim: 'S/T',
    'spencer/tim': 'S/T',
    'tim/spencer': 'S/T',
    'tim/redacted': 'S/T',
    'redacted/spencer': 'S/T',
    'spencer yoder & tim grazier': 'S/T',
    'redacted yoder & tim grazier': 'S/T',
    joe: 'J/J',
    censored: 'J/J',
    'joe/joe': 'J/J',
    'joe/censored': 'J/J',
    'joe censored': 'J/J',
    'joe kuhl': 'J/J',
    'joe k': 'JDK',
    'joe k.': 'JDK',
    'joe w': 'JRW',
    'joe w.': 'JRW',
    'censored ward': 'JRW',
    'joe censored & censored ward': 'J/J',
    stephen: 'SLS',
    schmidt: 'SLS',
    'stephen schmidt': 'SLS',
    arnav: 'AYP',
    'arnav patel': 'AYP',
    anagh: 'AST',
    'anagh tiwary': 'AST',
    't/s': 'S/T',
};

function ownerTeamCode(label) {
    const rawLabel = String(label || '').trim();
    const primaryLabel = rawLabel.split(/\s+\((?:via|vía)\b/i)[0].trim();
    const normalizedLabel = normalizeCoOwnerLabel(primaryLabel);
    const key = String(normalizedLabel || '').toLowerCase().replace(/\s+/g, ' ');
    const teams = sharedData?.teams || data?.teams || [];
    const directTeam = teams.find(team =>
        String(team.abbrev).toLowerCase() === key
        || String(normalizeCoOwnerLabel(team.owner) || '').toLowerCase().replace(/\s+/g, ' ') === key
    );
    return directTeam?.abbrev || OWNER_TEAM_CODES[key] || null;
}

function formatTradeTitle(labelA, labelB) {
    const [x, y] = [normalizeCoOwnerLabel(labelA), normalizeCoOwnerLabel(labelB)]
        .sort((a, b) => a.localeCompare(b));
    return `Trade between ${x} and ${y}`;
}

const HOME_TRANSACTION_LIMIT = 5;
const HOME_TRANSACTION_WINDOW_MS = 7 * 24 * 60 * 60 * 1000;

function transactionTime(tx) {
    const extractedDate = extractDateFromMessage(tx.message).date;
    if (extractedDate && /^\d/.test(extractedDate)) {
        const [month, day, rawYear] = extractedDate.split('/').map(Number);
        const year = rawYear < 100 ? 2000 + rawYear : rawYear;
        const messageTime = new Date(year, month - 1, day).getTime();
        if (Number.isFinite(messageTime)) return messageTime;
    }

    const timestampTime = new Date(tx.timestamp || '').getTime();
    return Number.isFinite(timestampTime) ? timestampTime : null;
}

function recentHomeTransactions({ offseason, now = Date.now() }) {
    const transactions = data.transactions || data.recent_transactions || [];
    const currentSeason = Number(data.season);

    return transactions
        .filter(tx => Number(tx.season) === currentSeason)
        .filter(tx => {
            if (offseason) {
                const week = String(tx.week ?? '').trim().toLowerCase();
                return week === 'offseason' || week === '0';
            }

            const time = transactionTime(tx);
            if (time === null) return false;
            const age = now - time;
            return age >= 0 && age <= HOME_TRANSACTION_WINDOW_MS;
        })
        .sort((a, b) => (transactionTime(b) || 0) - (transactionTime(a) || 0))
        .slice(0, HOME_TRANSACTION_LIMIT);
}

function renderHomeTransactions() {
    const container = document.getElementById('home-transactions');
    const transactions = recentHomeTransactions({ offseason: false });

    if (transactions.length === 0) {
        container.innerHTML = emptyStateHtml(
            'No moves in the last 7 days',
            'Older trades and roster moves are still available in league history.',
            [{ label: 'View transaction history', route: '#transactions' }]
        );
        return;
    }

    container.innerHTML = transactions.map(tx => {
        const isNewTrade = tx.type === 'trade' && tx.proposer && tx.partner;
        const isOldTrade = tx.type === 'trade' && tx.message && tx.message.includes('|');
        let teamName, type, details;

        // Extract date from message or timestamp
        const { dateStr, cleanMessage } = getTransactionDate(tx);

        if (isNewTrade) {
            // New trade format with proposer/partner - format with bullet points
            // Prefer the point-in-time label stamped by the exporter (name-battle
            // changeover); fall back to the current owner's first name.
            const a = normalizeCoOwnerLabel(tx.proposer_label || teamLabel(tx.proposer));
            const b = normalizeCoOwnerLabel(tx.partner_label || teamLabel(tx.partner));
            const title = formatTradeTitle(a, b);

            const getPlayerStr = (p) => typeof p === 'object' ? `${p.position || ''} ${p.name || ''}`.trim() : p;
            const gives = tx.proposer_gives || {};
            const receives = tx.proposer_receives || {};
            const givesItems = [...(gives.players || []).map(getPlayerStr), ...(gives.picks || [])];
            const receivesItems = [...(receives.players || []).map(getPlayerStr), ...(receives.picks || [])];

            return `
                <div class="home-transaction" data-route="#transactions" role="link" tabindex="0" aria-label="View transaction history">
                    <div class="home-transaction-header">
                        <span class="home-transaction-team">${title}</span>
                        <span class="home-transaction-date">${dateStr}</span>
                    </div>
                    <div class="home-transaction-text" style="line-height: 1.8;">
                        <div style="margin-top: 0.25rem;"><strong>${a} receives:</strong></div>
                        ${receivesItems.length ? receivesItems.map(item => `<div style="margin-left: 1rem;">• ${item}</div>`).join('') : '<div style="margin-left: 1rem; color: var(--text-muted);">nothing</div>'}
                        <div style="margin-top: 0.5rem;"><strong>${b} receives:</strong></div>
                        ${givesItems.length ? givesItems.map(item => `<div style="margin-left: 1rem;">• ${item}</div>`).join('') : '<div style="margin-left: 1rem; color: var(--text-muted);">nothing</div>'}
                    </div>
                </div>
            `;
        } else if (isOldTrade) {
            // Old trade format - parse and display (using cleaned message)
            const parsed = parseOldTradeMessage(cleanMessage);
            if (parsed && parsed.teams.length >= 2) {
                const team1 = parsed.teams[0];
                const team2 = parsed.teams[1];
                teamName = formatTradeTitle(team1.name, team2.name);

                return `
                    <div class="home-transaction" data-route="#transactions" role="link" tabindex="0" aria-label="View transaction history">
                        <div class="home-transaction-header">
                            <span class="home-transaction-team">${teamName}</span>
                            <span class="home-transaction-date">${dateStr}</span>
                        </div>
                        <div class="home-transaction-text" style="line-height: 1.8;">
                            ${parsed.teams.map(team => `
                                <div style="margin-top: 0.5rem;"><strong>${team.name} receives:</strong></div>
                                ${team.items.map(item => `<div style="margin-left: 1rem;">• ${item}</div>`).join('')}
                            `).join('')}
                            ${parsed.correspondingMoves.length ? `
                                <div style="margin-top: 0.5rem;"><strong>Corresponding moves:</strong></div>
                                ${parsed.correspondingMoves.map(move => `<div style="margin-left: 1rem;">• ${move}</div>`).join('')}
                            ` : ''}
                        </div>
                    </div>
                `;
            } else {
                // Fallback if parsing fails
                return `
                    <div class="home-transaction" data-route="#transactions" role="link" tabindex="0" aria-label="View transaction history">
                        <div class="home-transaction-header">
                            <span class="home-transaction-team">${normalizeCoOwnerLabel(tx.team) || 'Trade'}</span>
                            <span class="home-transaction-date">${dateStr}</span>
                        </div>
                        <div class="home-transaction-text">${cleanMessage}</div>
                    </div>
                `;
            }
        } else {
            teamName = data.teams?.find(t => t.abbrev === tx.team)?.name || normalizeCoOwnerLabel(tx.team);
            type = tx.type?.replace(/_/g, ' ') || 'Transaction';
            const added = tx.added || tx.activated;
            const released = tx.released;

            if (cleanMessage) {
                details = cleanMessage;
            } else if (added) {
                const addedName = typeof added === 'object' ? added.name : added;
                const addedPos = typeof added === 'object' ? added.position : '';
                const addedTeam = typeof added === 'object' ? added.nfl_team : '';
                details = addedPos && addedTeam ? `${addedPos} ${addedName} (${addedTeam})` : addedName;
                if (released) {
                    const relName = typeof released === 'object' ? released.name : released;
                    details += `, released ${relName}`;
                }
            } else {
                details = '';
            }

            return `
                <div class="home-transaction" data-route="#transactions" role="link" tabindex="0" aria-label="View transaction history">
                    <div class="home-transaction-header">
                        <span class="home-transaction-team">${teamName}</span>
                        <span class="home-transaction-date">${dateStr}</span>
                    </div>
                    <div class="home-transaction-text">${type}: ${details}</div>
                </div>
            `;
        }
    }).join('');
}

function renderHomeOffseason() {
    // Each season homepage looks back at the previous season's championship.
    // The inaugural season falls back to its own results because no earlier data exists.
    const prevSeason = data.previous_season;
    const displaySeason = prevSeason ? prevSeason.season : data.season;
    const displayWeeks = prevSeason ? prevSeason.weeks : data.weeks;
    const displayStandings = prevSeason ? prevSeason.standings : data.standings;
    [
        'home-championship-footer',
        'home-champion-footer',
        'home-standings-footer',
        'home-draft-footer',
        'home-txn-footer',
    ].forEach(id => document.getElementById(id)?.replaceChildren());
    
    // Render champion banner (previous season's banner)
    const bannerContainer = document.getElementById('home-banner');
    const bannersData = data.banners || {};
    const banners = bannersData.banners || bannersData || [];
    const currentBanner = Array.isArray(banners) ? banners.find(b => b.includes(`${displaySeason}`)) : null;
    
    if (currentBanner) {
        bannerContainer.innerHTML = `<img src="images/banners/${currentBanner}" alt="${displaySeason} Champion Banner" loading="lazy" decoding="async">`;
    }
    
    // The first matchup in the final scored week is the championship. The league's
    // title game was Week 16 in 2020 and 2021, then moved to Week 17.
    const championshipWeek = [...displayWeeks]
        .filter(week => week?.matchups?.length)
        .sort((a, b) => Number(b.week) - Number(a.week))[0];
    const championshipContainer = document.getElementById('home-championship');
    const champScorersContainer = document.getElementById('home-champ-scorers');
    const championName = document.getElementById('home-champion-name');
    
    let championAbbrev = null;
    
    if (championshipWeek) {
        // First matchup is the championship - winner is the champion
        const champ = championshipWeek.matchups[0];
        const t1 = champ.team1 || {};
        const t2 = champ.team2 || {};
        const t1Name = typeof t1 === 'object' ? (t1.team_name || t1.abbrev) : t1;
        const t2Name = typeof t2 === 'object' ? (t2.team_name || t2.abbrev) : t2;
        const t1Score = typeof t1 === 'object' ? t1.total_score : 0;
        const t2Score = typeof t2 === 'object' ? t2.total_score : 0;
        
        const t1Winner = t1Score > t2Score;
        const t2Winner = t2Score > t1Score;
        
        championshipContainer.innerHTML = `
            <div class="home-championship-matchup">
                <div class="home-championship-team">
                    <div class="home-championship-name ${t1Winner ? 'winner' : ''}">${t1Name}</div>
                    <div class="home-championship-score ${t1Winner ? 'winner' : ''}">${t1Score}</div>
                </div>
                <span class="home-championship-vs">vs</span>
                <div class="home-championship-team">
                    <div class="home-championship-name ${t2Winner ? 'winner' : ''}">${t2Name}</div>
                    <div class="home-championship-score ${t2Winner ? 'winner' : ''}">${t2Score}</div>
                </div>
            </div>
            <span class="home-championship-label">CHAMPIONSHIP</span>
        `;
        
        // Determine champion from game result
        const winnerTeam = t1Winner ? t1 : t2;
        championAbbrev = winnerTeam.abbrev;
        
        // Set champion name
        if (championName) {
            championName.textContent = `${displaySeason} Champion: ${winnerTeam.team_name || winnerTeam.name || winnerTeam.abbrev}`;
        }
        
        // Get top 3 scorers from championship game for the winner
        if (winnerTeam.roster) {
            const starters = winnerTeam.roster.filter(p => p.starter);
            const topScorers = starters.sort((a, b) => (b.score || 0) - (a.score || 0)).slice(0, 3);
            
            champScorersContainer.innerHTML = `
                <div class="home-scorers-title">Championship Top Scorers</div>
                ${topScorers.map(p => `
                    <div class="home-scorer-row">
                        <span class="home-scorer-pos">${escapeHtml(p.position)}</span>
                        ${playerProfileButton(p.name, 'home-scorer-name', null, p.position)}
                        <span class="home-scorer-pts">${(p.score || 0).toFixed(1)}</span>
                    </div>
                `).join('')}
            `;
        }
    }
    
    // Calculate season-long top scorers for champion
    const seasonScorersContainer = document.getElementById('home-season-scorers');
    if (championAbbrev) {
        const playerTotals = {};
        
        for (const week of displayWeeks) {
            for (const matchup of (week.matchups || [])) {
                for (const teamKey of ['team1', 'team2']) {
                    const team = matchup[teamKey];
                    if (team?.abbrev === championAbbrev && team.roster) {
                        for (const player of team.roster) {
                            if (player.starter && player.name) {
                                if (!playerTotals[player.name]) {
                                    playerTotals[player.name] = {
                                        name: player.name,
                                        position: player.position,
                                        total: 0,
                                        games: 0
                                    };
                                }
                                playerTotals[player.name].total += (player.score || 0);
                                playerTotals[player.name].games += 1;
                            }
                        }
                    }
                }
            }
        }
        
        const topSeasonScorers = Object.values(playerTotals)
            .sort((a, b) => b.total - a.total)
            .slice(0, 3);
        
        seasonScorersContainer.innerHTML = `
            <div class="home-scorers-title">Season Leaders</div>
            ${topSeasonScorers.map(p => `
                <div class="home-scorer-row">
                    <span class="home-scorer-pos">${escapeHtml(p.position)}</span>
                    ${playerProfileButton(p.name, 'home-scorer-name', null, p.position)}
                    <span class="home-scorer-pts">${p.total.toFixed(1)} pts</span>
                </div>
            `).join('')}
        `;
    }
    
    // Render final standings
    const standingsContainer = document.getElementById('home-final-standings');
    standingsContainer.innerHTML = (displayStandings || []).map((team, i) => `
        <div class="home-standing-row">
            <span class="home-standing-rank">${i + 1}.</span>
            ${teamProfileButton(team.abbrev, team.team_name || team.name || team.abbrev, 'home-standing-team')}
            <span class="home-standing-rp">${team.rank_points?.toFixed(1) || 0} RP</span>
            <span class="home-standing-record">${team.wins || 0}-${team.losses || 0}</span>
        </div>
    `).join('');
    
    // Render draft order (reverse of standings for next season)
    const draftOrderTitle = document.getElementById('home-draft-order-title');
    draftOrderTitle.textContent = `${displaySeason + 1} Draft Order`;
    
    const draftOrderContainer = document.getElementById('home-draft-order');
    const draftOrder = [...(displayStandings || [])].reverse();
    draftOrderContainer.innerHTML = draftOrder.map((team, i) => `
        <div class="home-draft-pick">
            <span class="home-draft-pick-num">${i + 1}</span>
            <span class="home-draft-pick-team">${team.team_name || team.abbrev}</span>
        </div>
    `).join('');
    
    // Render recent transactions
    renderHomeOffseasonTransactions();

    // Card footer links
    function addCardLink(footerId, text, href, onClick) {
        const footer = document.getElementById(footerId);
        if (!footer) return;
        const a = document.createElement('a');
        a.href = href;
        a.className = 'home-card-link';
        a.textContent = text;
        a.addEventListener('click', (e) => { e.preventDefault(); onClick(); });
        footer.appendChild(a);
    }

    if (championshipWeek) {
        const championshipWeekNumber = String(championshipWeek.week);
        addCardLink('home-championship-footer', 'View Championship Matchup →', `#matchups/week/${championshipWeekNumber}`, () => {
            loadData(displaySeason).then(() => {
                history.pushState(null, '', `#matchups/week/${championshipWeekNumber}`);
                navigateToView('matchups', 'week', championshipWeekNumber);
            });
        });
    }
    addCardLink(
        'home-championship-footer',
        `View the ${displaySeason} Hall of Fame →`,
        '#history/records',
        () => {
            history.pushState(null, '', '#history/records');
            navigateToView('history', 'records');
        }
    );

    if (championAbbrev) {
        addCardLink('home-champion-footer', "View Champion's Hall of Fame →", `#teams/history/${championAbbrev}`, () => {
            loadData(displaySeason).then(() => {
                history.pushState(null, '', `#teams/history/${championAbbrev}`);
                navigateToView('teams', 'history', championAbbrev);
            });
        });
    }
    addCardLink('home-champion-footer', 'View Season Leaders →', '#stats/leaders', () => {
        loadData(displaySeason).then(() => {
            history.pushState(null, '', '#stats/leaders');
            navigateToView('stats', 'leaders');
        });
    });

    addCardLink('home-standings-footer', 'View Full Standings →', '#standings', () => {
        loadData(displaySeason).then(() => {
            history.pushState(null, '', '#standings');
            navigateToView('standings');
        });
    });

    addCardLink('home-draft-footer', 'View All Drafts →', '#drafts/history', () => {
        history.pushState(null, '', '#drafts/history');
        navigateToView('drafts', 'history');
    });

    addCardLink('home-txn-footer', 'View All Transactions →', '#transactions', () => {
        history.pushState(null, '', '#transactions');
        navigateToView('transactions');
    });
}

function renderHomeOffseasonTransactions() {
    const container = document.getElementById('home-offseason-transactions');
    const transactions = recentHomeTransactions({ offseason: true });
    
    if (transactions.length === 0) {
        container.innerHTML = emptyStateHtml(
            'No offseason moves yet',
            'Review the complete transaction history while the market is quiet.',
            [{ label: 'View transaction history', route: '#transactions' }]
        );
        return;
    }

    container.innerHTML = transactions.map(tx => {
        const isNewTrade = tx.type === 'trade' && tx.proposer && tx.partner;
        const isOldTrade = tx.type === 'trade' && tx.message && tx.message.includes('|');

        // Extract date from message or timestamp
        const { dateStr, cleanMessage } = getTransactionDate(tx);

        if (isNewTrade) {
            // Build trade details with bullet points
            // Prefer the point-in-time label stamped by the exporter (name-battle
            // changeover); fall back to the current owner's first name.
            const a = normalizeCoOwnerLabel(tx.proposer_label || teamLabel(tx.proposer));
            const b = normalizeCoOwnerLabel(tx.partner_label || teamLabel(tx.partner));
            const title = formatTradeTitle(a, b);
            const getPlayerStr = (p) => typeof p === 'object' ? `${p.position || ''} ${p.name || ''}`.trim() : p;
            const gives = tx.proposer_gives || {};
            const receives = tx.proposer_receives || {};
            const givesItems = [...(gives.players || []).map(getPlayerStr), ...(gives.picks || [])];
            const receivesItems = [...(receives.players || []).map(getPlayerStr), ...(receives.picks || [])];

            return `
                <div class="home-transaction-item">
                    <div class="home-tx-header">
                        <span class="home-tx-team">${title}</span>
                        <span class="home-tx-type" style="font-family: 'JetBrains Mono', monospace; font-size: 0.75rem;">${dateStr}</span>
                    </div>
                    <div class="home-tx-details" style="line-height: 1.8;">
                        <div style="margin-top: 0.25rem;"><strong>${a} receives:</strong></div>
                        ${receivesItems.length ? receivesItems.map(item => `<div style="margin-left: 1rem;">• ${item}</div>`).join('') : '<div style="margin-left: 1rem; color: var(--text-muted);">nothing</div>'}
                        <div style="margin-top: 0.5rem;"><strong>${b} receives:</strong></div>
                        ${givesItems.length ? givesItems.map(item => `<div style="margin-left: 1rem;">• ${item}</div>`).join('') : '<div style="margin-left: 1rem; color: var(--text-muted);">nothing</div>'}
                    </div>
                </div>
            `;
        } else if (isOldTrade) {
            // Old trade format - parse and display (using cleaned message)
            const parsed = parseOldTradeMessage(cleanMessage);
            if (parsed && parsed.teams.length >= 2) {
                return `
                    <div class="home-transaction-item">
                        <div class="home-tx-header">
                            <span class="home-tx-team">${normalizeCoOwnerLabel(tx.team) || 'Trade'}</span>
                            <span class="home-tx-type" style="font-family: 'JetBrains Mono', monospace; font-size: 0.75rem;">${dateStr}</span>
                        </div>
                        <div class="home-tx-details" style="line-height: 1.8;">
                            ${parsed.teams.map(team => `
                                <div style="margin-top: 0.5rem;"><strong>${team.name} receives:</strong></div>
                                ${team.items.map(item => `<div style="margin-left: 1rem;">• ${item}</div>`).join('')}
                            `).join('')}
                            ${parsed.correspondingMoves.length ? `
                                <div style="margin-top: 0.5rem;"><strong>Corresponding moves:</strong></div>
                                ${parsed.correspondingMoves.map(move => `<div style="margin-left: 1rem;">• ${move}</div>`).join('')}
                            ` : ''}
                        </div>
                    </div>
                `;
            }
            // Fallback if parsing fails
            const teamDisplay = normalizeCoOwnerLabel(tx.team);
            const details = cleanMessage;
            return `
                <div class="home-transaction-item">
                    <div class="home-tx-header">
                        <span class="home-tx-team">${teamDisplay}</span>
                        <span class="home-tx-type">${dateStr}</span>
                    </div>
                    <div class="home-tx-details">${details}</div>
                </div>
            `;
        } else {
            const teamDisplay = normalizeCoOwnerLabel(tx.team);
            const type = tx.type?.replace(/_/g, ' ') || 'Transaction';
            const added = tx.added || tx.activated;
            const released = tx.released;
            let details;

            if (cleanMessage) {
                details = cleanMessage;
            } else if (added) {
                const addedName = typeof added === 'object' ? added.name : added;
                details = `<span class="tx-add">+ ${addedName}</span>`;
                if (released) {
                    const releasedName = typeof released === 'object' ? released.name : released;
                    details += ` <span class="tx-drop">- ${releasedName}</span>`;
                }
            } else {
                details = '';
            }

            return `
                <div class="home-transaction-item">
                    <div class="home-tx-header">
                        <span class="home-tx-team">${teamDisplay}</span>
                        <span class="home-tx-type">${dateStr ? dateStr : type}</span>
                    </div>
                    <div class="home-tx-details">${details}</div>
                </div>
            `;
        }
    }).join('');
}

function renderTeamProjection(team, projectedTotal, finalTie = false) {
    if (!team || !Object.prototype.hasOwnProperty.call(team, 'projection_ready')) return '';
    if (!team.projection_ready || !Number.isFinite(projectedTotal) || !Number.isFinite(team.win_probability)) {
        return '<div class="team-projection unavailable">Awaiting lineups</div>';
    }

    const probability = Math.round(team.win_probability * 100);
    const allFinal = Number(team.starters_remaining) === 0;
    const probabilityLabel = finalTie
        ? 'Final tie'
        : allFinal
            ? `Final · ${probability}%`
            : `${probability}% win`;
    return `
        <div class="team-projection" aria-label="Projected ${projectedTotal.toFixed(1)} points, ${probabilityLabel}">
            <span>Proj ${projectedTotal.toFixed(1)}</span>
            <span class="team-win-probability">${probabilityLabel}</span>
        </div>
    `;
}

function renderMatchups() {
    const weekData = data.weeks.find(w => w.week === currentWeek);
    const scheduleWeek = data.schedule?.find(w => w.week === currentWeek);
    const container = document.getElementById('matchups-container');
    
    // If no week data exists, show the schedule matchups (for playoffs or upcoming weeks)
    if (!weekData || !weekData.matchups || weekData.matchups.length === 0) {
        if (scheduleWeek && scheduleWeek.matchups) {
            const isPlayoffs = scheduleWeek.is_playoffs;
            const playoffRound = scheduleWeek.playoff_round || '';
            
            // Group matchups by bracket for playoffs
            const bracketLabels = {
                'playoffs': '🏆 Playoffs',
                'championship': '🏆 Championship',
                'consolation_cup': '🥉 Consolation Cup',
                'mid_bowl': '🥣 Mid Bowl',
                'sewer_series': '🚿 Sewer Series',
                'toilet_bowl': '🚽 Toilet Bowl',
                'jamboree': '🎪 Jamboree'
            };
            
            let matchupsHtml = '';
            
            if (isPlayoffs) {
                // Group by bracket
                const matchupsByBracket = {};
                scheduleWeek.matchups.forEach(m => {
                    const bracket = m.bracket || 'other';
                    if (!matchupsByBracket[bracket]) matchupsByBracket[bracket] = [];
                    matchupsByBracket[bracket].push(m);
                });
                
                // Helper to get team info and roster for upcoming matchups
                const getTeamData = (abbrev) => {
                    // Get team info from standings or teams
                    const teamInfo = data.standings?.find(t => t.abbrev === abbrev) || 
                                   data.teams?.find(t => t.abbrev === abbrev) || 
                                   { abbrev, name: abbrev, owner: '' };
                    
                    // Check if there's lineup data for this week from JSON submissions
                    let roster = [];
                    let hasLineupData = false;
                    
                    // Check if lineup was submitted for this week
                    if (data.lineups?.[abbrev]) {
                        hasLineupData = true;
                    }
                    
                    // Get roster from rosters data (base roster) - exclude taxi players
                    const baseRoster = (data.rosters?.[abbrev] || []).filter(p => !p.taxi);
                    
                    if (hasLineupData && baseRoster.length > 0) {
                        // If lineup was submitted, mark starters based on lineup data
                        const lineupStarters = data.lineups[abbrev];
                        roster = baseRoster.map(p => {
                            const posStarters = lineupStarters[p.position] || [];
                            const isStarter = posStarters.some(s => 
                                s.toLowerCase() === p.name.toLowerCase() ||
                                p.name.toLowerCase().includes(s.toLowerCase())
                            );
                            return { ...p, starter: isStarter };
                        });
                    } else {
                        // No lineup data - show all players as bench (not starters)
                        roster = baseRoster.map(p => ({ ...p, starter: false }));
                    }
                    
                    return { ...teamInfo, roster };
                };
                
                let matchupIdx = 0;
                const bracketOrder = ['playoffs', 'championship', 'consolation_cup', 'mid_bowl', 'sewer_series', 'toilet_bowl', 'jamboree', 'other'];
                matchupsHtml = bracketOrder
                    .filter(bracket => matchupsByBracket[bracket])
                    .map(bracket => {
                        const label = bracketLabels[bracket] || '';
                        return `
                            ${label ? `<div class="playoff-bracket-header ${bracket}">${label}</div>` : ''}
                            ${matchupsByBracket[bracket].map(m => {
                                const seed1 = m.seed1 ? `<span class="matchup-seed">#${m.seed1}</span>` : '';
                                const seed2 = m.seed2 ? `<span class="matchup-seed">#${m.seed2}</span>` : '';
                                const t1 = getTeamData(m.team1);
                                const t2 = getTeamData(m.team2);
                                const idx = matchupIdx++;
                                const hasRosters = t1.roster.length > 0 && t2.roster.length > 0;
                                
                                return `
                                    <div class="matchup-card pending playoff bracket-${bracket}">
                                        <div class="matchup-header">
                                            <div class="team">
                                                ${seed1}
                                                ${teamAvatar(t1.abbrev || m.team1, t1.name, '', currentTeamAvatar(t1.abbrev || m.team1))}
                                                ${teamProfileButton(t1.abbrev || m.team1, t1.name || m.team1, 'team-name')}
                                                <div class="team-owner">${escapeHtml(normalizeCoOwnerLabel(t1.owner) || '')}</div>
                                            </div>
                                            <div class="vs-container">
                                                <span class="vs-text">vs</span>
                                            </div>
                                            <div class="team right">
                                                ${seed2}
                                                ${teamAvatar(t2.abbrev || m.team2, t2.name, '', currentTeamAvatar(t2.abbrev || m.team2))}
                                                ${teamProfileButton(t2.abbrev || m.team2, t2.name || m.team2, 'team-name')}
                                                <div class="team-owner">${escapeHtml(normalizeCoOwnerLabel(t2.owner) || '')}</div>
                                            </div>
                                        </div>
                                        ${hasRosters ? `
                                            <button class="expand-btn" data-matchup="pending-${idx}">Show Rosters ▼</button>
                                            <div class="roster-panel" id="roster-pending-${idx}">
                                                <div class="roster-grid">
                                                    <div class="roster-column">
                                                        <h4>${t1.abbrev}</h4>
                                                        ${renderRoster(t1.roster, currentWeek)}
                                                    </div>
                                                    <div class="roster-column">
                                                        <h4>${t2.abbrev}</h4>
                                                        ${renderRoster(t2.roster, currentWeek)}
                                                    </div>
                                                </div>
                                            </div>
                                        ` : ''}
                                    </div>
                                `;
                            }).join('')}
                        `;
                    }).join('');
            } else {
                matchupsHtml = scheduleWeek.matchups.map(m => `
                    <div class="matchup-card pending">
                        <div class="matchup-header">
                            <div class="team">
                                ${teamAvatar(m.team1, m.team1, '', currentTeamAvatar(m.team1))}
                                ${teamProfileButton(m.team1, m.team1, 'team-name')}
                            </div>
                            <div class="vs-container">
                                <span class="vs-text">vs</span>
                            </div>
                            <div class="team right">
                                ${teamAvatar(m.team2, m.team2, '', currentTeamAvatar(m.team2))}
                                ${teamProfileButton(m.team2, m.team2, 'team-name')}
                            </div>
                        </div>
                    </div>
                `).join('');
            }
            
            const headerText = isPlayoffs 
                ? `<span class="playoff-round-badge">${playoffRound}</span> Scores not yet available`
                : `Scores not yet available for Week ${currentWeek}`;
            
            container.innerHTML = `
                <div class="no-scores-message ${isPlayoffs ? 'playoffs' : ''}">
                    <p>${headerText}</p>
                </div>
                ${matchupsHtml}
            `;
            
            // Add expand/collapse functionality for pending matchups
            container.querySelectorAll('.expand-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const panel = document.getElementById(`roster-${btn.dataset.matchup}`);
                    if (panel) {
                        const isExpanded = panel.classList.toggle('expanded');
                        btn.textContent = isExpanded ? 'Hide Rosters ▲' : 'Show Rosters ▼';
                    }
                });
            });
        } else if (data.is_offseason) {
            // Offseason - schedule not yet available
            container.innerHTML = `
                <div class="no-scores-message offseason">
                    <p>The ${currentSeason} schedule has not been released yet</p>
                    <p class="offseason-subtitle">Matchups will be available once the regular season begins</p>
                </div>
            `;
        } else {
            container.innerHTML = emptyStateHtml(
                `Week ${currentWeek} matchups are not available`,
                'Check the season schedule or jump back to the live season.',
                currentSeason === LIVE_SEASON
                    ? [{ label: 'View schedule', route: '#matchups/schedule' }]
                    : [{ label: 'Return to current season', action: 'current-season' }]
            );
        }
        return;
    }
    
    // Check if this is a playoff week and get bracket info
    const isPlayoffWeek = scheduleWeek?.is_playoffs;
    
    // Special handling for 2020 Jamboree - show scoreboard instead of matchups
    const hasJamboree = data.jamboree && weekData.matchups.some(m => m.bracket === 'jamboree');
    
    // Separate jamboree matchups from regular matchups
    const regularMatchups = hasJamboree 
        ? weekData.matchups.filter(m => m.bracket !== 'jamboree')
        : weekData.matchups;
    const jamboreeMatchups = hasJamboree 
        ? weekData.matchups.filter(m => m.bracket === 'jamboree')
        : [];
    
    // Build jamboree scoreboard HTML
    let jamboreeHtml = '';
    if (hasJamboree && jamboreeMatchups.length > 0) {
        // Collect all jamboree teams and their scores for this week
        const jamboreeTeams = [];
        jamboreeMatchups.forEach(m => {
            jamboreeTeams.push({
                name: m.team1.name,
                abbrev: m.team1.abbrev,
                owner: m.team1.owner,
                week_score: m.team1.total_score
            });
            jamboreeTeams.push({
                name: m.team2.name,
                abbrev: m.team2.abbrev,
                owner: m.team2.owner,
                week_score: m.team2.total_score
            });
        });
        
        // Get cumulative totals from jamboree data
        const jamboreeData = data.jamboree || [];
        jamboreeTeams.forEach(team => {
            const jData = jamboreeData.find(j => j.abbrev === team.abbrev);
            if (jData) {
                team.week_15 = jData.week_15;
                team.week_16 = jData.week_16;
                team.total = currentWeek >= 16 ? jData.total : jData.week_15;
            }
        });
        
        // Sort by total (or week_15 if only week 15)
        jamboreeTeams.sort((a, b) => (b.total || 0) - (a.total || 0));
        
        const isWeek16 = currentWeek >= 16;
        jamboreeHtml = `
            <div class="playoff-bracket-header jamboree">🎪 Jamboree</div>
            <div class="jamboree-scoreboard">
                <div class="jamboree-title">2-Week Total Points Contest${isWeek16 ? ' - Final' : ' - Week 1 of 2'}</div>
                <table class="jamboree-table">
                    <thead>
                        <tr>
                            <th class="jamboree-place"></th>
                            <th>Team</th>
                            <th>Owner</th>
                            <th>Wk 15</th>
                            ${isWeek16 ? '<th>Wk 16</th><th>Total</th>' : ''}
                        </tr>
                    </thead>
                    <tbody>
                        ${jamboreeTeams.map((t, i) => `
                            <tr>
                                <td class="jamboree-place ${i === 0 && isWeek16 ? 'first' : ''}">${i === 0 && isWeek16 ? '🏆' : (i + 1)}</td>
                                <td>${t.name}</td>
                                <td>${escapeHtml(normalizeCoOwnerLabel(t.owner))}</td>
                                <td>${(t.week_15 || 0).toFixed(0)}</td>
                                ${isWeek16 ? `<td>${(t.week_16 || 0).toFixed(0)}</td><td class="total">${(t.total || 0).toFixed(0)}</td>` : ''}
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
        `;
    }
    
    // Get week 16 mid bowl scores for cumulative display in week 17
    let week16MidBowlScores = {};
    if (currentWeek === 17) {
        const week16Data = data.weeks.find(w => w.week === 16);
        if (week16Data) {
            const midBowlMatchup = week16Data.matchups.find(m => m.bracket === 'mid_bowl');
            if (midBowlMatchup) {
                week16MidBowlScores[midBowlMatchup.team1.abbrev] = midBowlMatchup.team1.total_score;
                week16MidBowlScores[midBowlMatchup.team2.abbrev] = midBowlMatchup.team2.total_score;
            }
        }
    }
    
    const matchupsHtml = regularMatchups.map((matchup, idx) => {
        const t1 = matchup.team1;
        const t2 = matchup.team2;
        
        // Find the bracket for this matchup
        // First check if bracket is directly on the matchup (historical seasons)
        // Then fall back to looking in the schedule data
        let bracketClass = '';
        let isMidBowl = false;
        if (matchup.bracket) {
            bracketClass = `bracket-${matchup.bracket}`;
            isMidBowl = matchup.bracket === 'mid_bowl';
        } else if (isPlayoffWeek && scheduleWeek?.matchups) {
            // Try exact matchup first
            let scheduleMatchup = scheduleWeek.matchups.find(m => 
                (m.team1 === t1.abbrev && m.team2 === t2.abbrev) ||
                (m.team1 === t2.abbrev && m.team2 === t1.abbrev)
            );
            
            // If no exact match, find which bracket team1 is in
            if (!scheduleMatchup) {
                scheduleMatchup = scheduleWeek.matchups.find(m => 
                    m.team1 === t1.abbrev || m.team2 === t1.abbrev
                );
            }
            
            if (scheduleMatchup?.bracket) {
                bracketClass = `bracket-${scheduleMatchup.bracket}`;
                isMidBowl = scheduleMatchup.bracket === 'mid_bowl';
            }
        }
        
        // Calculate scores - for Mid Bowl in week 17, show cumulative
        let t1Score = t1.total_score;
        let t2Score = t2.total_score;
        let t1Projected = t1.projected_total;
        let t2Projected = t2.projected_total;
        let midBowlSubtitle = '';
        
        if (isMidBowl) {
            if (currentWeek === 17 && week16MidBowlScores[t1.abbrev] !== undefined) {
                const t1Week16 = week16MidBowlScores[t1.abbrev] || 0;
                const t2Week16 = week16MidBowlScores[t2.abbrev] || 0;
                const t1Week17 = t1.total_score;
                const t2Week17 = t2.total_score;
                t1Score = t1Week16 + t1Week17;
                t2Score = t2Week16 + t2Week17;
                if (Number.isFinite(t1Projected)) t1Projected += t1Week16;
                if (Number.isFinite(t2Projected)) t2Projected += t2Week16;
                midBowlSubtitle = `
                    <div class="mid-bowl-breakdown">
                        <span>${t1.abbrev}: ${t1Week16.toFixed(0)} + ${t1Week17.toFixed(0)} = ${t1Score.toFixed(0)}</span>
                        <span>${t2.abbrev}: ${t2Week16.toFixed(0)} + ${t2Week17.toFixed(0)} = ${t2Score.toFixed(0)}</span>
                    </div>
                `;
            } else if (currentWeek === 16) {
                midBowlSubtitle = '<div class="mid-bowl-note">Week 1 of 2</div>';
            }
        }
        
        const t1Winning = t1Score > t2Score;
        const t2Winning = t2Score > t1Score;
        const matchupFinal = t1.projection_ready && t2.projection_ready
            && Number(t1.starters_remaining) === 0
            && Number(t2.starters_remaining) === 0;
        const finalTie = matchupFinal && t1Projected === t2Projected;

        return `
            <div class="matchup-card ${bracketClass}">
                <div class="matchup-header">
                    <div class="team">
                        ${teamAvatar(t1.abbrev, t1.name, 'avatar-lg', t1.avatar)}
                        ${teamProfileButton(t1.abbrev, t1.name, 'team-name')}
                        <div class="team-owner">${escapeHtml(normalizeCoOwnerLabel(t1.owner))}</div>
                        ${renderTeamProjection(t1, t1Projected, finalTie)}
                    </div>
                    <div class="vs-container">
                        <div class="score-display">
                            <span class="score ${t1Winning ? 'winning' : 'losing'}">${t1Score.toFixed(0)}</span>
                            <span class="score-divider">—</span>
                            <span class="score ${t2Winning ? 'winning' : 'losing'}">${t2Score.toFixed(0)}</span>
                        </div>
                        ${renderH2HBadge(t1.abbrev, t2.abbrev, currentSeason)}
                        ${midBowlSubtitle}
                    </div>
                    <div class="team right">
                        ${teamAvatar(t2.abbrev, t2.name, 'avatar-lg', t2.avatar)}
                        ${teamProfileButton(t2.abbrev, t2.name, 'team-name')}
                        <div class="team-owner">${escapeHtml(normalizeCoOwnerLabel(t2.owner))}</div>
                        ${renderTeamProjection(t2, t2Projected, finalTie)}
                    </div>
                </div>
                <button class="expand-btn" data-matchup="${idx}">Show Rosters ▼</button>
                <div class="roster-panel" id="roster-${idx}">
                    <div class="roster-grid">
                        <div class="roster-column">
                            <h4>${t1.abbrev}</h4>
                            ${renderRoster(t1.roster, currentWeek)}
                            ${renderOptimalSummary(t1.roster)}
                        </div>
                        <div class="roster-column">
                            <h4>${t2.abbrev}</h4>
                            ${renderRoster(t2.roster, currentWeek)}
                            ${renderOptimalSummary(t2.roster)}
                        </div>
                    </div>
                </div>
            </div>
        `;
    }).join('');
    
    // Combine regular matchups with jamboree scoreboard
    container.innerHTML = matchupsHtml + jamboreeHtml;

    // Add expand/collapse functionality
    container.querySelectorAll('.expand-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const panel = document.getElementById(`roster-${btn.dataset.matchup}`);
            const isExpanded = panel.classList.toggle('expanded');
            btn.textContent = isExpanded ? 'Hide Rosters ▲' : 'Show Rosters ▼';
        });
    });
}

function getPlayerStatus(player, weekNum) {
    const hasProjectionContext = Object.prototype.hasOwnProperty.call(player, 'on_bye');
    if (player.on_bye === true) return { status: 'bye', label: 'BYE' };
    if (player.game_final === true) return { status: 'played', label: '' };

    const weekKey = String(weekNum);
    const gameTimes = data.game_times && data.game_times[weekKey];
    if (!hasProjectionContext && !gameTimes) return { status: 'unknown', label: '' };
    const currentKickoffs = hasProjectionContext ? (data.kickoffs || {}) : {};
    
    // Normalize team codes (some sources use different abbreviations)
    const teamAliases = {
        'LAR': 'LA',   // Rams
        'JAC': 'JAX', // Jaguars
        'WSH': 'WAS', // Commanders
    };
    
    const playerTeam = player.nfl_team;
    let gameTime = player.kickoff || currentKickoffs[playerTeam] || gameTimes?.[playerTeam];
    if (!gameTime && teamAliases[playerTeam]) {
        gameTime = currentKickoffs[teamAliases[playerTeam]] || gameTimes?.[teamAliases[playerTeam]];
    }
    // Also try reverse lookup (if game_times uses LAR but player has LA)
    if (!gameTime) {
        const reverseAliases = { 'LA': 'LAR', 'JAX': 'JAC', 'WAS': 'WSH' };
        if (reverseAliases[playerTeam]) {
            gameTime = currentKickoffs[reverseAliases[playerTeam]] || gameTimes?.[reverseAliases[playerTeam]];
        }
    }
    
    // No game time = BYE week
    if (!gameTime) {
        return hasProjectionContext
            ? { status: 'unknown', label: '' }
            : { status: 'bye', label: 'BYE' };
    }
    
    const kickoff = new Date(gameTime);
    const now = new Date();
    
    // Game hasn't started yet - show game time
    if (now < kickoff) {
        // Format: "Mon 8:15p" or "Sun 1:00p"
        const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
        const dayName = days[kickoff.getDay()];
        let hours = kickoff.getHours();
        const minutes = kickoff.getMinutes();
        const ampm = hours >= 12 ? 'p' : 'a';
        hours = hours % 12 || 12;
        const timeStr = minutes === 0 
            ? `${hours}${ampm}`
            : `${hours}:${String(minutes).padStart(2, '0')}${ampm}`;
        
        // Determine color class based on game day/time
        let colorClass = 'game-time-default';
        const dayOfWeek = kickoff.getDay();
        const hourOfDay = kickoff.getHours();
        
        if (dayOfWeek === 4) { // Thursday
            colorClass = 'game-time-thursday';
        } else if (dayOfWeek === 5 || dayOfWeek === 6) { // Friday/Saturday
            colorClass = 'game-time-frisat';
        } else                 if (dayOfWeek === 0) { // Sunday
            if (hourOfDay < 12) { // Before noon = morning games (10am-11:59am PT / 1pm ET)
                colorClass = 'game-time-sun-morning';
            } else if (hourOfDay < 17) { // Noon to 5pm = afternoon games (12pm-4:59pm PT / 4pm ET)
                colorClass = 'game-time-sun-afternoon';
            } else { // 5 PM+ = night (5pm+ PT / 8pm ET SNF)
                colorClass = 'game-time-sun-night';
            }
        } else if (dayOfWeek === 1) { // Monday
            colorClass = 'game-time-monday';
        }
        
        return { status: 'not-played', label: `${dayName} ${timeStr}`, colorClass };
    }
    
    // Game has started or finished - show actual score
    return { status: 'played', label: '' };
}

// Render roster from rosters data (for upcoming weeks without scores)
function renderRosterFromData(roster) {
    if (!roster || roster.length === 0) return '<p>No roster data</p>';

    return sortRosterByPosition(roster).map(p => `
        <div class="player-row">
            <div class="player-info">
                <span class="position-tag pos-${posClassKey(p.position)}">${escapeHtml(p.position)}</span>
                ${playerProfileButton(p.name, '', null, p.position)}
                <span class="player-team">${escapeHtml(p.nfl_team || '')}</span>
            </div>
        </div>
    `).join('');
}

const BREAKDOWN_LABELS = {
    passing_yards: 'Pass Yds', rushing_yards: 'Rush Yds', receiving_yards: 'Rec Yds',
    touchdowns: 'TD', turnovers: 'TO', turnover_tds: 'TO-TD', two_point_conversions: '2PT',
    pat_made: 'PAT', pat_missed: 'PAT Miss', pat_blocked: 'PAT Blk',
    fg_1_29: 'FG 1-29', fg_30_39: 'FG 30-39', fg_40_49: 'FG 40-49',
    fg_50_59: 'FG 50-59', 'fg_60+': 'FG 60+', fg_missed: 'FG Miss', fg_blocked: 'FG Blk',
    points_allowed: 'Pts Allow', sacks: 'Sacks', turnovers_forced: 'TOs', safeties: 'Safety',
    blocked_kicks: 'Blk Kick', defensive_tds: 'Def TD',
    win_margin: 'Win Mar', loss_margin: 'Loss Mar',
    pass_yards: 'OL Pass', rush_yards: 'OL Rush', sacks_allowed: 'Sacks Allow',
    adjustment: 'Adjustment',
};

function renderBreakdown(breakdown) {
    const parts = Object.entries(breakdown)
        .filter(([, v]) => v !== 0)
        .map(([k, v]) => {
            const label = BREAKDOWN_LABELS[k] || k.replace(/_/g, ' ');
            const pts = v > 0 ? `+${v}` : String(v);
            return `<span class="bd-item"><span class="bd-label">${label}</span><span class="bd-pts">${pts}</span></span>`;
        });
    return parts.length ? `<div class="breakdown-content">${parts.join('')}</div>` : '';
}

function renderRoster(roster, weekNum) {
    // Use current week if not specified
    const week = weekNum || data.current_week;

    // Sort: starters first by position order, then bench
    const sorted = [...roster].sort((a, b) => {
        if (a.starter !== b.starter) return b.starter - a.starter;
        return ROSTER_POSITION_ORDER.indexOf(a.position) - ROSTER_POSITION_ORDER.indexOf(b.position);
    });

    return sorted.map(p => {
        const status = getPlayerStatus(p, week);
        let scoreDisplay;
        const projectionDisplay = Number.isFinite(p.projected_points)
            ? `<span class="player-projection">Proj ${p.projected_points.toFixed(1)}</span>`
            : '';

        if (status.status === 'bye') {
            scoreDisplay = `<span class="player-status bye">BYE</span>`;
        } else if (status.status === 'not-played') {
            const colorClass = status.colorClass || '';
            scoreDisplay = `<span class="player-status not-played ${colorClass}">${status.label}</span>`;
        } else {
            const score = p.score ?? 0;
            if (p.breakdown && Object.keys(p.breakdown).length > 0) {
                const bdHtml = renderBreakdown(p.breakdown);
                scoreDisplay = `<details class="score-breakdown">
                    <summary class="player-score has-breakdown">${score.toFixed(0)}</summary>
                    ${bdHtml}
                </details>`;
            } else {
                scoreDisplay = `<span class="player-score">${score.toFixed(0)}</span>`;
            }
        }

        // A started player whose game has completed but whose stats were
        // never matched (stale nfl_team, name drift) scores a silent 0 -
        // flag it rather than letting it look like a legitimate zero.
        // See docs/ROADMAP_2026.md P1.4.
        const gameShouldBeFinal = Object.prototype.hasOwnProperty.call(p, 'game_final')
            ? p.game_final === true
            : status.status === 'played';
        const notFoundBadge = (p.starter && gameShouldBeFinal && p.found === false)
            ? `<span class="player-status not-found" title="No stats matched for this player - check nfl_team/name">⚠ no stats matched</span>`
            : '';

        return `
        <div class="player-row ${p.starter ? '' : 'bench'}">
            <div class="player-info">
                <span class="position-tag pos-${posClassKey(p.position)}">${escapeHtml(p.position)}</span>
                ${playerProfileButton(p.name, '', null, p.position)}
                <span class="player-team">${escapeHtml(p.nfl_team || '')}</span>
            </div>
                ${notFoundBadge}
                <div class="player-points">${scoreDisplay}${projectionDisplay}</div>
        </div>
        `;
    }).join('');
}

// ====== WEEK-BY-WEEK STANDINGS HISTORY ======

// Returns [{ week, rankings: {abbrev: rank} }, ...] for all scored regular-season weeks.
// Rankings are based on cumulative rank points (H2H win + top-half bonus) with PF tiebreaker.
function computeWeeklyStandings() {
    const teams = (data.standings || []).map(t => t.abbrev);
    if (!teams.length) return [];

    const cumRP = {}, cumPF = {};
    teams.forEach(a => { cumRP[a] = 0; cumPF[a] = 0; });

    const result = [];
    const scoredWeeks = (data.weeks || [])
        .filter(w => w.has_scores && w.week <= REGULAR_SEASON_LAST_WEEK)
        .sort((a, b) => a.week - b.week);

    for (const w of scoredWeeks) {
        // Collect week scores
        const weekScores = [];
        for (const m of (w.matchups || [])) {
            for (const t of [m.team1, m.team2]) {
                if (!t?.abbrev) continue;
                const score = typeof t.total_score === 'number' ? t.total_score : sumStarterScores(t.roster);
                weekScores.push({ abbrev: t.abbrev, score });
            }
        }
        if (!weekScores.length) continue;

        // Top-half scorers
        const half = Math.ceil(weekScores.length / 2);
        const topHalf = new Set(
            [...weekScores].sort((a, b) => b.score - a.score).slice(0, half).map(t => t.abbrev)
        );

        // Update cumulative rank points from H2H results
        for (const m of (w.matchups || [])) {
            const t1 = m.team1, t2 = m.team2;
            if (!t1?.abbrev || !t2?.abbrev) continue;
            const s1 = typeof t1.total_score === 'number' ? t1.total_score : sumStarterScores(t1.roster);
            const s2 = typeof t2.total_score === 'number' ? t2.total_score : sumStarterScores(t2.roster);
            if (s1 > s2) cumRP[t1.abbrev] = (cumRP[t1.abbrev] || 0) + 1;
            else if (s2 > s1) cumRP[t2.abbrev] = (cumRP[t2.abbrev] || 0) + 1;
            else { cumRP[t1.abbrev] = (cumRP[t1.abbrev] || 0) + 0.5; cumRP[t2.abbrev] = (cumRP[t2.abbrev] || 0) + 0.5; }
        }
        for (const ts of weekScores) {
            if (topHalf.has(ts.abbrev)) cumRP[ts.abbrev] = (cumRP[ts.abbrev] || 0) + 0.5;
            cumPF[ts.abbrev] = (cumPF[ts.abbrev] || 0) + ts.score;
        }

        // Rank by cumulative RP, PF tiebreaker
        const ranked = [...teams].sort((a, b) => {
            const rp = (cumRP[b] || 0) - (cumRP[a] || 0);
            return rp !== 0 ? rp : (cumPF[b] || 0) - (cumPF[a] || 0);
        });
        const rankings = {};
        ranked.forEach((a, i) => { rankings[a] = i + 1; });
        result.push({ week: w.week, rankings });
    }
    return result;
}

function renderWeeklyRankHistory() {
    const card = document.getElementById('weekly-rank-history-card');
    if (!card) return;

    const history = computeWeeklyStandings();
    if (history.length === 0) { card.style.display = 'none'; return; }

    const teams = (data.standings || []).map(t => t.abbrev);
    const teamName = {};
    (data.standings || []).forEach(t => { teamName[t.abbrev] = t.name; });

    const headerCells = history.map(h => `<th class="wsr-wk">W${h.week}</th>`).join('');
    const bodyRows = teams.map(abbrev => {
        const cells = history.map(h => {
            const rank = h.rankings[abbrev];
            if (!rank) return '<td></td>';
            const tier = rank <= 4 ? 'hi' : rank <= 6 ? 'mid' : 'lo';
            return `<td class="wsr-cell wsr-${tier}">${rank}</td>`;
        }).join('');
        return `<tr><td class="wsr-team">${escapeHtml(teamName[abbrev] || abbrev)}</td>${cells}</tr>`;
    }).join('');

    card.style.display = '';
    card.innerHTML = `
        <div class="wsr-header">
            <h3 class="wsr-title">Weekly Rank History</h3>
            <span class="wsr-note">Rank based on cumulative rank points through each week</span>
        </div>
        <div class="wsr-scroll">
            <table class="wsr-table">
                <thead><tr><th>Team</th>${headerCells}</tr></thead>
                <tbody>${bodyRows}</tbody>
            </table>
        </div>
    `;
}

// ====== REMAINING STRENGTH OF SCHEDULE ======

// Returns { abbrev: avgOpponentPPG } for each team's remaining regular-season games.
// Returns null if no schedule or no remaining games.
function computeRemainingSOS() {
    const schedule = data.schedule || [];
    const teamStats = data.team_stats || {};
    const currentWeek = data.current_week || 0;

    // Collect remaining regular-season matchups (future weeks only)
    const remaining = {}; // abbrev -> [opponent abbrevs]
    for (const w of schedule) {
        if (w.is_playoffs) continue;
        if (w.week > REGULAR_SEASON_LAST_WEEK) continue;
        if (w.week <= currentWeek) continue; // already played
        for (const m of (w.matchups || [])) {
            const a1 = typeof m.team1 === 'string' ? m.team1 : m.team1?.abbrev;
            const a2 = typeof m.team2 === 'string' ? m.team2 : m.team2?.abbrev;
            if (!a1 || !a2) continue;
            if (!remaining[a1]) remaining[a1] = [];
            if (!remaining[a2]) remaining[a2] = [];
            remaining[a1].push(a2);
            remaining[a2].push(a1);
        }
    }

    if (Object.keys(remaining).length === 0) return null;

    const result = {};
    for (const [abbrev, opponents] of Object.entries(remaining)) {
        if (!opponents.length) continue;
        const ppgs = opponents.map(opp => teamStats[opp]?.ppg).filter(v => v != null);
        if (ppgs.length) result[abbrev] = ppgs.reduce((s, v) => s + v, 0) / ppgs.length;
    }
    return Object.keys(result).length ? result : null;
}

// Returns { abbrev: { xWins, xLosses } } computed from all scored regular-season weeks.
// Each week a team earns the fraction of the rest of the field it outscored (0..1),
// so xWins is on the same scale as actual wins (one matchup per week). Summed across
// completed weeks, xWins + xLosses equals games played. Ties split as 0.5.
function computeExpectedWins() {
    const result = {};
    for (const w of (data.weeks || [])) {
        if (!w.has_scores) continue;
        const weekScores = [];
        for (const m of (w.matchups || [])) {
            for (const t of [m.team1, m.team2]) {
                if (!t || !t.abbrev) continue;
                const score = typeof t.total_score === 'number' ? t.total_score : sumStarterScores(t.roster);
                weekScores.push({ abbrev: t.abbrev, score });
            }
        }
        const n = weekScores.length;
        if (n < 2) continue;
        for (const team of weekScores) {
            if (!result[team.abbrev]) result[team.abbrev] = { xWins: 0, xLosses: 0 };
            let beats = 0, ties = 0;
            for (const other of weekScores) {
                if (other.abbrev === team.abbrev) continue;
                if (team.score > other.score) beats++;
                else if (team.score === other.score) ties++;
            }
            const opponents = n - 1;
            // Normalize to one game per week so xWins is on the same scale as actual
            // wins (you only play one matchup): the fraction of the field beaten.
            const expected = (beats + ties * 0.5) / opponents;
            result[team.abbrev].xWins += expected;
            result[team.abbrev].xLosses += 1 - expected;
        }
    }
    return result;
}

function renderStandings() {
    const tbody = document.getElementById('standings-body');
    const totalTeams = data.standings.length;
    const expectedWins = computeExpectedWins();
    const sos = computeRemainingSOS(); // null when no schedule / offseason
    const postseasonContext = getPostseasonStatusContext();
    const postseasonStatus = computePlayoffStatus(
        postseasonContext.standings,
        postseasonContext.remainingWeeks
    );

    // Toggle SOS header visibility
    const sosHeader = document.getElementById('standings-sos-header');
    if (sosHeader) sosHeader.style.display = sos ? '' : 'none';

    tbody.innerHTML = data.standings.map((team, idx) => {
        const rank = idx + 1;
        const isPlayoffs = rank <= 4;
        const isToiletBowl = rank > totalTeams - 4;
        const rankClass = isPlayoffs ? 'playoffs' : (isToiletBowl ? 'toilet-bowl' : '');
        const status = postseasonStatus[team.abbrev] || {};
        const label = status.clinched
            ? '<span class="playoff-label playoffs">Playoffs</span>'
            : (status.toiletBowlClinched
                ? '<span class="playoff-label toilet">Toilet Bowl</span>'
                : '');
        const rowClass = rank === totalTeams - 3 ? 'toilet-cutoff' : '';

        const xw = expectedWins[team.abbrev];
        let xwCell = '<td class="num xwl">—</td><td class="num luck">—</td>';
        if (xw) {
            const luck = (team.wins ?? 0) - xw.xWins;
            const luckStr = (luck >= 0 ? '+' : '') + luck.toFixed(1);
            const luckClass = luck > 0.5 ? 'luck-pos' : (luck < -0.5 ? 'luck-neg' : '');
            xwCell = `<td class="num xwl">${xw.xWins.toFixed(1)}-${xw.xLosses.toFixed(1)}</td>` +
                     `<td class="num luck ${luckClass}">${luckStr}</td>`;
        }

        const sosCell = sos
            ? `<td class="num sos" title="Avg remaining opponent PPG">${(sos[team.abbrev] ?? 0).toFixed(1)}</td>`
            : '';

        return `
            <tr class="${rowClass}">
                <td class="rank ${rankClass}">${rank}</td>
                <td>
                    <div class="standings-team-cell">
                        ${teamAvatar(team.abbrev, team.name, '', team.avatar || currentTeamAvatar(team.abbrev))}
                        <div class="standings-team-text">
                            <div class="team-name-row">
                                <button type="button" class="team-profile-trigger team-name" data-team-abbrev="${escapeHtml(team.abbrev)}" aria-label="View ${escapeHtml(team.name)} roster">${escapeHtml(team.name)}<span class="team-code">${escapeHtml(team.abbrev)}</span></button>
                                ${label}
                            </div>
                            <div class="team-owner">${escapeHtml(normalizeCoOwnerLabel(team.owner))}</div>
                        </div>
                    </div>
                </td>
                <td class="num rank-points">${(team.rank_points ?? 0).toFixed(1)}</td>
                <td class="num record">${team.wins ?? 0}-${team.losses ?? 0}${team.ties ? `-${team.ties}` : ''}</td>
                <td class="num top-half">${team.top_half || 0}</td>
                <td class="num points-for">${(team.points_for ?? 0).toFixed(0)}</td>
                <td class="num points-against">${(team.points_against ?? 0).toFixed(0)}</td>
                ${xwCell}
                ${sosCell}
            </tr>
        `;
    }).join('');

    renderPlayoffOdds();
    renderWeeklyRankHistory();
}

// ====== PLAYOFF PROBABILITY SIMULATOR ======
// Monte Carlo over remaining regular-season matchups. Top 4 by rank points,
// then wins and points for, make the playoffs.
const PLAYOFF_TRIALS = 5000;
const PLAYOFF_SLOTS = 4;
const TOILET_BOWL_SLOTS = 4;
const REGULAR_SEASON_LAST_WEEK = 15;

function buildCompletedStandingsSnapshot(completedThrough) {
    const snapshot = {};
    for (const team of (data.standings || [])) {
        snapshot[team.abbrev] = {
            ...team,
            rank_points: 0,
            wins: 0,
            points_for: 0,
        };
    }

    for (const week of (data.weeks || [])) {
        if (!week.has_scores || Number(week.week) > completedThrough) continue;

        const weekScores = new Map();
        for (const matchup of (week.matchups || [])) {
            const team1 = matchup.team1;
            const team2 = matchup.team2;
            if (!team1?.abbrev || !team2?.abbrev) continue;

            const score1 = typeof team1.total_score === 'number'
                ? team1.total_score
                : sumStarterScores(team1.roster);
            const score2 = typeof team2.total_score === 'number'
                ? team2.total_score
                : sumStarterScores(team2.roster);
            weekScores.set(team1.abbrev, score1);
            weekScores.set(team2.abbrev, score2);

            if (!snapshot[team1.abbrev] || !snapshot[team2.abbrev]) continue;
            snapshot[team1.abbrev].points_for += score1;
            snapshot[team2.abbrev].points_for += score2;
            if (score1 > score2) {
                snapshot[team1.abbrev].rank_points += 1;
                snapshot[team1.abbrev].wins += 1;
            } else if (score2 > score1) {
                snapshot[team2.abbrev].rank_points += 1;
                snapshot[team2.abbrev].wins += 1;
            } else {
                snapshot[team1.abbrev].rank_points += 0.5;
                snapshot[team2.abbrev].rank_points += 0.5;
            }
        }

        const sortedScores = Array.from(weekScores.entries())
            .sort(([, scoreA], [, scoreB]) => scoreB - scoreA);
        const topHalfCutoff = Math.floor(sortedScores.length / 2);
        let index = 0;
        while (index < sortedScores.length) {
            const score = sortedScores[index][1];
            let groupEnd = index + 1;
            while (groupEnd < sortedScores.length && sortedScores[groupEnd][1] === score) {
                groupEnd++;
            }
            const topHalfPlaces = Math.max(0, Math.min(groupEnd, topHalfCutoff) - index);
            const bonus = topHalfPlaces > 0
                ? (0.5 * topHalfPlaces) / (groupEnd - index)
                : 0;
            for (let i = index; i < groupEnd; i++) {
                const abbrev = sortedScores[i][0];
                if (snapshot[abbrev]) snapshot[abbrev].rank_points += bonus;
            }
            index = groupEnd;
        }
    }

    return (data.standings || []).map(team => snapshot[team.abbrev] || team);
}

function getPostseasonStatusContext() {
    if (data.is_historical) {
        return { standings: data.standings, remainingWeeks: 0 };
    }

    const season = Number(data.season ?? currentSeason);
    const lastWeek = season <= 2021 ? 14 : REGULAR_SEASON_LAST_WEEK;
    const marker = Number(
        data.hall_of_fame?.completed_through?.[String(season)]
    );
    const fallback = Math.max(0, Number(data.current_week || 1) - 1);
    const completedThrough = Math.min(lastWeek, Number.isFinite(marker) ? marker : fallback);
    return {
        standings: completedThrough >= lastWeek
            ? data.standings
            : buildCompletedStandingsSnapshot(completedThrough),
        remainingWeeks: lastWeek - completedThrough,
    };
}

function gaussianSample(mean, std) {
    // Box-Muller. std is clamped to a small positive number to avoid 0-variance.
    const s = Math.max(std, 1);
    let u = 0, v = 0;
    while (u === 0) u = Math.random();
    while (v === 0) v = Math.random();
    const z = Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
    return mean + z * s;
}

function getCompletedWeekScoresByTeam() {
    // Returns { abbrev: [scores...] } from data.weeks where has_scores is true
    // and the week is in the regular season.
    const out = {};
    for (const w of (data.weeks || [])) {
        if (!w.has_scores) continue;
        if (w.week > REGULAR_SEASON_LAST_WEEK) continue;
        for (const m of (w.matchups || [])) {
            for (const t of [m.team1, m.team2]) {
                if (!t || !t.abbrev) continue;
                const score = (typeof t.total_score === 'number')
                    ? t.total_score
                    : sumStarterScores(t.roster);
                if (!out[t.abbrev]) out[t.abbrev] = [];
                out[t.abbrev].push(score);
            }
        }
    }
    return out;
}

function getRemainingMatchups(completedWeeks) {
    // Returns [{ week, team1Abbrev, team2Abbrev }, ...] for regular-season weeks
    // in data.schedule that aren't already in `weeks` (completed).
    const completedSet = new Set(completedWeeks);
    const out = [];
    for (const w of (data.schedule || [])) {
        if (w.is_playoffs) continue;
        if (w.week > REGULAR_SEASON_LAST_WEEK) continue;
        if (completedSet.has(w.week)) continue;
        for (const m of (w.matchups || [])) {
            const a1 = typeof m.team1 === 'string' ? m.team1 : (m.team1?.abbrev || '');
            const a2 = typeof m.team2 === 'string' ? m.team2 : (m.team2?.abbrev || '');
            if (!a1 || !a2) continue;
            out.push({ week: w.week, team1Abbrev: a1, team2Abbrev: a2 });
        }
    }
    return out;
}

// Mathematical postseason status check. A playoff berth is clinched only when
// no possible finish puts the team below fourth. A Toilet Bowl berth is clinched
// only when no possible finish puts the team above the bottom four.
//
// Bound used: in any single remaining week a team can gain at most 1.5 RP
// (1.0 H2H win + 0.5 top-half scoring), one win, and an unbounded amount of PF.
// Ties in the possible ranges are therefore uncertain until all games finish.
// Once no weeks remain, the already-sorted standings supply the head-to-head or
// commissioner tiebreak result.
function computePlayoffStatus(standings, remainingWeeksCount) {
    const MAX_RP_PER_WEEK = 1.5;
    const order = new Map(standings.map((team, index) => [team.abbrev, index]));
    const result = {};
    for (const a of standings) {
        const aRP = a.rank_points || 0;
        const aWins = a.wins || 0;
        const aMinRP = aRP;
        const aMaxRP = aRP + MAX_RP_PER_WEEK * remainingWeeksCount;
        const aMinWins = aWins;
        const aMaxWins = aWins + remainingWeeksCount;
        let canPassA = 0;
        let definitelyAboveA = 0;
        for (const b of standings) {
            if (b.abbrev === a.abbrev) continue;
            const bRP = b.rank_points || 0;
            const bWins = b.wins || 0;
            const bMinRP = bRP;
            const bMaxRP = bRP + MAX_RP_PER_WEEK * remainingWeeksCount;
            const bMinWins = bWins;
            const bMaxWins = bWins + remainingWeeksCount;

            let couldPass = bMaxRP > aMinRP;
            if (bMaxRP === aMinRP) {
                couldPass = bMaxWins > aMinWins;
                if (bMaxWins === aMinWins) {
                    couldPass = remainingWeeksCount > 0
                        || (order.get(b.abbrev) ?? Infinity) < (order.get(a.abbrev) ?? Infinity);
                }
            }
            if (couldPass) canPassA++;

            let guaranteedAbove = bMinRP > aMaxRP;
            if (bMinRP === aMaxRP) {
                guaranteedAbove = bMinWins > aMaxWins;
                if (bMinWins === aMaxWins && remainingWeeksCount === 0) {
                    guaranteedAbove = (order.get(b.abbrev) ?? Infinity)
                        < (order.get(a.abbrev) ?? Infinity);
                }
            }
            if (guaranteedAbove) definitelyAboveA++;
        }
        result[a.abbrev] = {
            clinched: canPassA < PLAYOFF_SLOTS,
            eliminated: definitelyAboveA >= PLAYOFF_SLOTS,
            toiletBowlClinched: definitelyAboveA >= standings.length - TOILET_BOWL_SLOTS,
        };
    }
    return result;
}

function simulatePlayoffOdds() {
    // Returns { byTeam: { abbrev: { name, odds, clinched, mean } }, weeksRemaining, weeksCompleted }
    // or null if the simulation isn't applicable (offseason, no schedule, no scores yet).
    if (!data.standings || data.standings.length === 0) return null;
    if (data.is_offseason || data.is_historical) return null;

    const completedScoresByTeam = getCompletedWeekScoresByTeam();
    const completedWeeks = (data.weeks || [])
        .filter(w => w.has_scores && w.week <= REGULAR_SEASON_LAST_WEEK)
        .map(w => w.week);
    const remaining = getRemainingMatchups(completedWeeks);
    if (remaining.length === 0) return null;

    // Need at least one team with completed scores to estimate distributions.
    // If we have none, fall back to a league-default distribution.
    const allScores = Object.values(completedScoresByTeam).flat();
    const leagueMean = allScores.length
        ? allScores.reduce((s, x) => s + x, 0) / allScores.length
        : 110;
    const leagueStd = (() => {
        if (allScores.length < 2) return 22;
        const m = leagueMean;
        const v = allScores.reduce((s, x) => s + (x - m) * (x - m), 0) / (allScores.length - 1);
        return Math.sqrt(v);
    })();

    // Per-team means default to leagueMean when no samples yet.
    const teamMean = {};
    for (const t of data.standings) {
        const samples = completedScoresByTeam[t.abbrev];
        teamMean[t.abbrev] = samples && samples.length
            ? samples.reduce((s, x) => s + x, 0) / samples.length
            : leagueMean;
    }

    // Group remaining matchups by week, so top-half RP can be assigned weekly.
    const weeksRemaining = {};
    for (const m of remaining) {
        if (!weeksRemaining[m.week]) weeksRemaining[m.week] = [];
        weeksRemaining[m.week].push(m);
    }
    const remainingWeekNums = Object.keys(weeksRemaining).map(Number).sort((a, b) => a - b);

    // Initial standings snapshot
    const initialRP = {};
    const initialWins = {};
    const initialPF = {};
    const teamLabel = {};
    for (const t of data.standings) {
        initialRP[t.abbrev] = t.rank_points || 0;
        initialWins[t.abbrev] = t.wins || 0;
        initialPF[t.abbrev] = t.points_for || 0;
        teamLabel[t.abbrev] = t.name || t.abbrev;
    }

    const playoffCount = {};
    for (const t of data.standings) playoffCount[t.abbrev] = 0;

    const numTeams = data.standings.length;
    const topHalfCutoff = Math.floor(numTeams / 2);

    for (let trial = 0; trial < PLAYOFF_TRIALS; trial++) {
        const rp = { ...initialRP };
        const wins = { ...initialWins };
        const pf = { ...initialPF };

        for (const wk of remainingWeekNums) {
            const matchups = weeksRemaining[wk];
            const weekScores = {};
            const teamsThisWeek = new Set();

            for (const m of matchups) {
                teamsThisWeek.add(m.team1Abbrev);
                teamsThisWeek.add(m.team2Abbrev);
            }
            for (const ab of teamsThisWeek) {
                weekScores[ab] = gaussianSample(teamMean[ab] ?? leagueMean, leagueStd);
                pf[ab] = (pf[ab] || 0) + weekScores[ab];
            }
            // H2H rank points
            for (const m of matchups) {
                const s1 = weekScores[m.team1Abbrev];
                const s2 = weekScores[m.team2Abbrev];
                if (s1 > s2) {
                    rp[m.team1Abbrev] += 1;
                    wins[m.team1Abbrev] += 1;
                } else if (s2 > s1) {
                    rp[m.team2Abbrev] += 1;
                    wins[m.team2Abbrev] += 1;
                }
                else { rp[m.team1Abbrev] += 0.5; rp[m.team2Abbrev] += 0.5; }
            }
            // Top-half scoring (top half of teams that played this week get +0.5 RP)
            const sortedThisWeek = Array.from(teamsThisWeek).sort(
                (a, b) => weekScores[b] - weekScores[a]
            );
            const halfCutoff = Math.floor(sortedThisWeek.length / 2);
            for (let i = 0; i < halfCutoff; i++) {
                rp[sortedThisWeek[i]] += 0.5;
            }
        }

        // Final ranking follows the constitution: RP, wins, then PF.
        const finalOrder = data.standings.map(t => t.abbrev).sort((a, b) => {
            if (rp[b] !== rp[a]) return rp[b] - rp[a];
            if (wins[b] !== wins[a]) return wins[b] - wins[a];
            return pf[b] - pf[a];
        });
        for (let i = 0; i < PLAYOFF_SLOTS && i < finalOrder.length; i++) {
            playoffCount[finalOrder[i]] += 1;
        }
    }

    const statusContext = getPostseasonStatusContext();
    const statusMap = computePlayoffStatus(
        statusContext.standings,
        statusContext.remainingWeeks
    );
    const byTeam = {};
    for (const t of data.standings) {
        const count = playoffCount[t.abbrev];
        const status = statusMap[t.abbrev] || { clinched: false, eliminated: false };
        byTeam[t.abbrev] = {
            name: teamLabel[t.abbrev],
            abbrev: t.abbrev,
            odds: count / PLAYOFF_TRIALS,
            clinched: status.clinched,
            eliminated: status.eliminated,
            mean: teamMean[t.abbrev],
        };
    }
    return {
        byTeam,
        weeksRemaining: remainingWeekNums.length,
        weeksCompleted: completedWeeks.length,
    };
}

function renderPlayoffOdds() {
    const card = document.getElementById('playoff-odds-card');
    const grid = document.getElementById('playoff-odds-grid');
    const meta = document.getElementById('playoff-odds-meta');
    if (!card || !grid) return;

    const sim = simulatePlayoffOdds();
    if (!sim) {
        card.style.display = 'none';
        return;
    }

    meta.textContent = `${sim.weeksCompleted} week${sim.weeksCompleted === 1 ? '' : 's'} played · ${sim.weeksRemaining} to go · ${PLAYOFF_TRIALS.toLocaleString()} simulations`;

    const sorted = Object.values(sim.byTeam).sort((a, b) => b.odds - a.odds);
    grid.innerHTML = sorted.map(team => {
        // Cap odds at 1–99% until a team is mathematically certain — either
        // clinched (can't fall out of top 4 even with 0 more RP) or eliminated
        // (can't reach top 4 even with max RP from here). Keeps tight races
        // readable instead of showing 100%/0% on Monte Carlo confidence alone.
        const rawPct = Math.round(team.odds * 100);
        let displayPct;
        let cls;
        let badge = '';
        if (team.clinched) {
            displayPct = 100;
            cls = 'clinched';
            badge = '<span class="playoff-odds-clinch">Clinched</span>';
        } else if (team.eliminated) {
            displayPct = 0;
            cls = 'eliminated';
            badge = '<span class="playoff-odds-elim">Eliminated</span>';
        } else {
            displayPct = Math.min(99, Math.max(1, rawPct));
            cls = displayPct >= 70 ? 'likely' : displayPct >= 30 ? 'bubble' : 'longshot';
        }
        return `
            <div class="playoff-odds-row ${cls}">
                <span class="playoff-odds-team">${team.name}${badge}</span>
                <span class="playoff-odds-bar-wrap">
                    <span class="playoff-odds-bar" style="width: ${displayPct}%;"></span>
                </span>
                <span class="playoff-odds-pct">${displayPct}%</span>
            </div>
        `;
    }).join('');
    card.style.display = '';
}

function renderSchedule() {
    const container = document.getElementById('schedule-container');

    if (!data.schedule || data.schedule.length === 0) {
        // Check if we're in the offseason
        if (data.is_offseason) {
            container.innerHTML = `
                <div class="no-scores-message offseason">
                    <p>The ${data.season || currentSeason} schedule has not been released yet</p>
                    <p class="offseason-subtitle">The schedule will be available once the regular season begins</p>
                </div>
            `;
        } else {
            container.innerHTML = emptyStateHtml(
                'Schedule not available',
                'Return to the live season for the latest matchup information.',
                currentSeason === LIVE_SEASON
                    ? [{ label: 'View current matchup', route: `#matchups/week/${currentWeek}` }]
                    : [{ label: 'Return to current season', action: 'current-season' }]
            );
        }
        return;
    }

    // Build a lookup for week scores from the weeks data
    const weekScores = {};
    if (data.weeks) {
        data.weeks.forEach(week => {
            if (week.has_scores) {
                weekScores[week.week] = {};
                week.matchups.forEach(matchup => {
                    // Calculate total from starter scores
                    const team1Total = matchup.team1.roster
                        .filter(p => p.starter)
                        .reduce((sum, p) => sum + p.score, 0);
                    const team2Total = matchup.team2.roster
                        .filter(p => p.starter)
                        .reduce((sum, p) => sum + p.score, 0);
                    weekScores[week.week][matchup.team1.abbrev] = team1Total;
                    weekScores[week.week][matchup.team2.abbrev] = team2Total;
                });
            }
        });
    }

    container.innerHTML = data.schedule.map(week => {
        const isCurrent = week.week === data.current_week;
        const hasScores = weekScores[week.week];
        const isCompleted = hasScores !== undefined;
        const isRivalry = week.is_rivalry;
        const isPlayoffs = week.is_playoffs;
        
        const cardClasses = [
            'schedule-week',
            isRivalry ? 'rivalry' : '',
            isPlayoffs ? 'playoffs' : '',
            isCurrent ? 'current' : '',
            isCompleted ? 'completed' : ''
        ].filter(Boolean).join(' ');
        
        const badge = isCurrent ? '<span class="schedule-week-badge current">Current</span>' :
                      (isCompleted ? '<span class="schedule-week-badge completed">Done</span>' : '');
        
        let weekTitle = isRivalry ? `Rivalry Week` : `Week ${week.week}`;
        if (isPlayoffs) {
            weekTitle = week.playoff_round || `Playoffs Week ${week.week}`;
        }
        const titleClass = isRivalry ? 'rivalry' : (isPlayoffs ? 'playoffs' : '');
        
        // Group playoff matchups by bracket
        const matchupsByBracket = {};
        if (isPlayoffs) {
            week.matchups.forEach(m => {
                const bracket = m.bracket || 'other';
                if (!matchupsByBracket[bracket]) {
                    matchupsByBracket[bracket] = [];
                }
                matchupsByBracket[bracket].push(m);
            });
        }
        
        const bracketLabels = {
            'playoffs': '🏆 Playoffs',
            'championship': '🏆 Championship',
            'consolation_cup': '🥉 Consolation Cup',
            'mid_bowl': '🥣 Mid Bowl',
            'sewer_series': '🚿 Sewer Series',
            'toilet_bowl': '🚽 Toilet Bowl',
            'jamboree': '🎪 Jamboree'
        };
        
        const renderMatchup = (m) => {
            const team1 = m.team1;
            const team2 = m.team2;
            const score1 = hasScores ? weekScores[week.week]?.[team1] : undefined;
            const score2 = hasScores ? weekScores[week.week]?.[team2] : undefined;
            
            // Show seed info for playoff matchups
            const seed1 = m.seed1 ? `<span class="seed">#${m.seed1}</span>` : '';
            const seed2 = m.seed2 ? `<span class="seed">#${m.seed2}</span>` : '';
            
            if (score1 !== undefined && score2 !== undefined) {
                const winner1 = score1 > score2 ? 'winner' : (score1 < score2 ? 'loser' : '');
                const winner2 = score2 > score1 ? 'winner' : (score2 < score1 ? 'loser' : '');
                return `
                    <div class="schedule-matchup with-scores ${isPlayoffs ? 'playoff-matchup' : ''}">
                        ${seed1}<span class="schedule-team ${winner1}">${team1}</span>
                        <span class="schedule-score ${winner1}">${score1.toFixed(0)}</span>
                        <span class="schedule-vs">-</span>
                        <span class="schedule-score ${winner2}">${score2.toFixed(0)}</span>
                        <span class="schedule-team ${winner2}">${team2}</span>${seed2}
                    </div>
                `;
            }
            return `
                <div class="schedule-matchup ${isPlayoffs ? 'playoff-matchup' : ''}">
                    ${seed1}<span class="schedule-team">${team1}</span>
                    <span class="schedule-vs">vs</span>
                    <span class="schedule-team">${team2}</span>${seed2}
                </div>
            `;
        };
        
        // Render regular season week
        if (!isPlayoffs) {
            return `
                <div class="${cardClasses}">
                    <div class="schedule-week-header">
                        <span class="schedule-week-title ${titleClass}">${weekTitle}</span>
                        ${badge}
                    </div>
                    ${week.matchups.map(renderMatchup).join('')}
                </div>
            `;
        }
        
        // Render playoff week with brackets
        const bracketOrder = ['playoffs', 'championship', 'consolation_cup', 'mid_bowl', 'sewer_series', 'toilet_bowl', 'jamboree', 'other'];
        
        // Check if this is the final week of a Jamboree (2020 week 16)
        const hasJamboree = matchupsByBracket['jamboree'] && data.jamboree && week.week === 16;
        
        const bracketHtml = bracketOrder
            .filter(bracket => matchupsByBracket[bracket])
            .map(bracket => {
                // For Jamboree, show the scoreboard instead of matchups in week 16
                if (bracket === 'jamboree' && hasJamboree) {
                    return `
                        <div class="bracket-label ${bracket}">${bracketLabels[bracket]}</div>
                        <div class="jamboree-scoreboard">
                            <div class="jamboree-title">2-Week Total Points Contest</div>
                            <table class="jamboree-table">
                                <thead>
                                    <tr>
                                        <th class="jamboree-place"></th>
                                        <th>Team</th>
                                        <th>Owner</th>
                                        <th>Wk 15</th>
                                        <th>Wk 16</th>
                                        <th>Total</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    ${data.jamboree.map(t => `
                                        <tr>
                                            <td class="jamboree-place ${t.place === 1 ? 'first' : ''}">${t.place === 1 ? '🏆' : t.place}</td>
                                            <td>${t.name}</td>
                                            <td>${escapeHtml(normalizeCoOwnerLabel(t.owner))}</td>
                                            <td>${(t.week_15 ?? 0).toFixed(0)}</td>
                                            <td>${(t.week_16 ?? 0).toFixed(0)}</td>
                                            <td class="total">${(t.total ?? 0).toFixed(0)}</td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        </div>
                    `;
                }
                // Skip Jamboree matchups in week 15 (they're shown in week 16 as scoreboard)
                if (bracket === 'jamboree' && week.week === 15 && data.jamboree) {
                    return `
                        <div class="bracket-label ${bracket}">${bracketLabels[bracket]}</div>
                        <div class="jamboree-scoreboard">
                            <div class="jamboree-title">2-Week Total Points Contest</div>
                            <p style="text-align: center; color: var(--text-muted);">Week 1 of 2 - Final standings after Week 16</p>
                        </div>
                    `;
                }
                const label = bracketLabels[bracket] || '';
                return `
                    ${label ? `<div class="bracket-label ${bracket}">${label}</div>` : ''}
                    ${matchupsByBracket[bracket].map(renderMatchup).join('')}
                `;
            }).join('');
        
        return `
            <div class="${cardClasses}">
                <div class="schedule-week-header">
                    <span class="schedule-week-title ${titleClass}">${weekTitle}</span>
                    ${badge}
                </div>
                ${bracketHtml}
            </div>
        `;
    }).join('');
}

let currentTeam = null;
let teamRouteSubview = null;

const TEAM_HUB_SUBVIEWS = new Set(['roster', 'history', 'activity']);

function teamDirectoryTeams() {
    if (sharedData?.teams?.length) return sharedData.teams;
    if (data?.teams?.length) return data.teams;
    return data?.standings || [];
}

function renderTeamHubHeader(teamInfo) {
    const container = document.getElementById('team-hub-header');
    if (!container || !teamInfo) return;
    const standingIndex = (data.standings || []).findIndex(team => team.abbrev === currentTeam);
    const standing = standingIndex >= 0 ? data.standings[standingIndex] : null;
    const games = (standing?.wins || 0) + (standing?.losses || 0) + (standing?.ties || 0);
    const record = games
        ? `${standing.wins || 0}–${standing.losses || 0}${standing.ties ? `–${standing.ties}` : ''}`
        : 'Preseason';
    const rank = standingIndex >= 0 && games ? `No. ${standingIndex + 1}` : 'Season ahead';

    container.innerHTML = `
        <section class="team-hub-hero" aria-labelledby="team-hub-name">
            ${teamAvatar(teamInfo.abbrev, teamInfo.name, 'avatar-2xl', teamInfo.avatar || currentTeamAvatar(teamInfo.abbrev))}
            <div class="team-hub-identity">
                <h2 id="team-hub-name">${escapeHtml(teamInfo.name || teamInfo.abbrev)}</h2>
                <p>${escapeHtml(normalizeCoOwnerLabel(teamInfo.owner) || teamInfo.abbrev)}</p>
            </div>
            <div class="team-hub-season-summary" aria-label="Current season summary">
                <div><strong>${escapeHtml(rank)}</strong><span>standing</span></div>
                <div><strong>${escapeHtml(record)}</strong><span>record</span></div>
                <div><strong>${standing?.points_for != null ? Number(standing.points_for).toFixed(0) : '—'}</strong><span>points</span></div>
            </div>
        </section>
    `;
}

function renderTeams() {
    // Get teams from standings, or fall back to data.teams during offseason
    let teams = data.standings;
    if (!teams || teams.length === 0) teams = data.teams || [];
    if (!teams || teams.length === 0) return;

    if (!currentTeam || !teams.some(team => team.abbrev === currentTeam)) {
        currentTeam = teams[0].abbrev;
    }
    
    // Render team selector buttons
    const selectorContainer = document.getElementById('team-selector');
    selectorContainer.innerHTML = teams.map(team => `
        <button class="team-btn ${team.abbrev === currentTeam ? 'active' : ''}"
                data-team="${escapeHtml(team.abbrev)}">${escapeHtml(team.abbrev)}</button>
    `).join('');
    
    // Add click handlers
    selectorContainer.querySelectorAll('.team-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            currentTeam = btn.dataset.team;
            // Stay on the current subview when switching teams
            const activeSubviewBtn = document.querySelector('.team-subnav-btn.active');
            const activeSubview = activeSubviewBtn?.dataset.subview || 'history';
            renderTeams();
            renderActiveTeamSubview(activeSubview);
            history.replaceState(null, '', `#teams/${activeSubview}/${encodeURIComponent(currentTeam)}`);
            updatePageMetadata('teams', activeSubview, currentTeam);
        });
    });
    centerActiveScrollableItem(selectorContainer, '.team-btn.active');
    
    // Find team info
    const teamInfo = teams.find(t => t.abbrev === currentTeam);
    if (!teamInfo) return;
    renderTeamHubHeader(teamInfo);
    
    // Get all weeks with scores
    const weeksWithScores = (data.weeks || []).filter(w => w.has_scores);
    
    // Build player data across all weeks
    const playerMap = new Map(); // player key -> {name, team, position, weeks: {weekNum: {score, starter}}}
    
    weeksWithScores.forEach(week => {
        // Find this team in the week's matchups
        let teamData = null;
        for (const matchup of week.matchups) {
            if (matchup.team1.abbrev === currentTeam) {
                teamData = matchup.team1;
                break;
            }
            if (matchup.team2.abbrev === currentTeam) {
                teamData = matchup.team2;
                break;
            }
        }
        if (!teamData || !teamData.roster) return;
        
        teamData.roster.forEach(player => {
            const key = `${player.position}-${player.name}`;
            if (!playerMap.has(key)) {
                playerMap.set(key, {
                    name: player.name,
                    nfl_team: player.nfl_team,
                    position: player.position,
                    weeks: {}
                });
            }
            playerMap.get(key).weeks[week.week] = {
                score: player.score,
                starter: player.starter
            };
        });
    });
    
    // Get final roster player names (to identify former players)
    // For past seasons, use the last week's roster; for current season, use data.rosters
    const finalRosterNames = new Set();
    if (currentSeason === LIVE_SEASON && data.rosters && data.rosters[currentTeam]) {
        // Current season: use the live roster
        data.rosters[currentTeam].forEach(p => finalRosterNames.add(p.name.toLowerCase()));
        
        // Also add any players from the current roster who aren't in matchup history yet
        // (e.g., recently activated players who haven't had a scored week)
        data.rosters[currentTeam].forEach(player => {
            if (player.taxi) return; // Skip taxi squad players
            const key = `${player.position}-${player.name}`;
            if (!playerMap.has(key)) {
                playerMap.set(key, {
                    name: player.name,
                    nfl_team: player.nfl_team,
                    position: player.position,
                    weeks: {},
                    isNewlyActivated: true // Flag to indicate no history yet
                });
            }
        });
    } else if (weeksWithScores.length > 0) {
        // Past season: use the roster from the last week of the season
        const lastWeek = weeksWithScores[weeksWithScores.length - 1];
        const lastWeekMatchup = lastWeek.matchups?.find(m => 
            m.team1.abbrev === currentTeam || m.team2.abbrev === currentTeam
        );
        if (lastWeekMatchup) {
            const teamData = lastWeekMatchup.team1.abbrev === currentTeam 
                ? lastWeekMatchup.team1 : lastWeekMatchup.team2;
            teamData.roster?.forEach(p => finalRosterNames.add(p.name.toLowerCase()));
        }
    }
    
    // Group by position
    const positions = ROSTER_POSITION_ORDER;
    const playersByPosition = {};
    positions.forEach(pos => playersByPosition[pos] = []);

    playerMap.forEach((player, key) => {
        if (playersByPosition[player.position]) {
            // Check if player finished the season on the roster
            player.isOnCurrentRoster = finalRosterNames.has(player.name.toLowerCase());
            playersByPosition[player.position].push(player);
        }
    });
    
    // Sort each position: current roster first, then former players (maintain original order within each group)
    positions.forEach(pos => {
        // Use stable sort - only move former players to bottom, don't reorder within groups
        const current = playersByPosition[pos].filter(p => p.isOnCurrentRoster);
        const former = playersByPosition[pos].filter(p => !p.isOnCurrentRoster);
        playersByPosition[pos] = [...current, ...former];
    });
    
    // Build a global lookup of player scores across all teams for each week
    // This lets us show scores for players who were on other teams
    const globalPlayerScores = {}; // {weekNum: {playerName: {score, nfl_team}}}
    weeksWithScores.forEach(week => {
        globalPlayerScores[week.week] = {};
        for (const matchup of week.matchups) {
            [matchup.team1, matchup.team2].forEach(team => {
                if (team && team.roster) {
                    team.roster.forEach(p => {
                        globalPlayerScores[week.week][p.name.toLowerCase()] = {
                            score: p.score,
                            nfl_team: p.nfl_team
                        };
                    });
                }
                if (team && team.taxi_squad) {
                    team.taxi_squad.forEach(p => {
                        globalPlayerScores[week.week][p.name.toLowerCase()] = {
                            score: p.score || 0,
                            nfl_team: p.nfl_team
                        };
                    });
                }
            });
        }
    });
    
    // Build table
    const weekHeaders = weeksWithScores.map(w => 
        `<th class="week-col">W${w.week}</th>`
    ).join('');
    
    let tableRows = '';
    const weekTotals = {};
    weeksWithScores.forEach(w => weekTotals[w.week] = 0);
    
    positions.forEach(pos => {
        const players = playersByPosition[pos];
        if (players.length === 0) return;
        
        // Position header row
        tableRows += `<tr class="position-group"><td colspan="${weeksWithScores.length + 4}">${pos}</td></tr>`;
        
        players.forEach(player => {
            let rosterTotal = 0;  // Points scored while on this roster
            let fullTotal = 0;    // All points including when on other teams
            
            const weekScores = weeksWithScores.map(w => {
                const weekData = player.weeks[w.week];
                const status = getPlayerStatus({ nfl_team: player.nfl_team }, w.week);
                
                if (weekData) {
                    // Player was on this roster this week
                const cls = weekData.starter ? 'starter' : 'bench';
                if (weekData.starter) weekTotals[w.week] += weekData.score;
                    rosterTotal += weekData.score;
                    fullTotal += weekData.score;
                    
                    if (status.status === 'bye') {
                        return `<td class="week-score ${cls}"><span class="player-status bye">BYE</span></td>`;
                    } else if (status.status === 'not-played' && weekData.score === 0) {
                        const colorClass = status.colorClass || '';
                        return `<td class="week-score ${cls}"><span class="player-status not-played ${colorClass}">${status.label}</span></td>`;
                    }
                return `<td class="week-score ${cls}">${weekData.score.toFixed(0)}</td>`;
                } else {
                    // Player wasn't on this roster - check if they have a score elsewhere
                    const globalScore = globalPlayerScores[w.week]?.[player.name.toLowerCase()];
                    if (globalScore && globalScore.score !== undefined) {
                        fullTotal += globalScore.score;
                        if (status.status === 'bye') {
                            return `<td class="week-score not-on-roster"><span class="player-status bye">(BYE)</span></td>`;
                        }
                        return `<td class="week-score not-on-roster">(${(globalScore.score ?? 0).toFixed(0)})</td>`;
                    }
                    return '<td class="week-score not-on-roster">-</td>';
                }
            }).join('');
            
            const rowClass = player.isOnCurrentRoster ? '' : 'former-player';
            const nameDisplay = player.isOnCurrentRoster ? player.name : `${player.name} *`;
            
            // Show roster total, and full total in parentheses if different
            const totalDisplay = rosterTotal === fullTotal 
                ? `${rosterTotal.toFixed(0)}`
                : `${rosterTotal.toFixed(0)} (${fullTotal.toFixed(0)})`;
            
            tableRows += `
                <tr class="${rowClass}">
                    <td>${playerProfileButton(player.name, '', nameDisplay, player.position)}</td>
                    <td class="player-team">${player.nfl_team}</td>
                    ${weekScores}
                    <td class="week-score season-total">${totalDisplay}</td>
                </tr>
            `;
        });
    });
    
    // Total row
    const totalScores = weeksWithScores.map(w => 
        `<td class="week-score">${weekTotals[w.week].toFixed(0)}</td>`
    ).join('');
    const starterSeasonTotal = Object.values(weekTotals).reduce((a, b) => a + b, 0);
    tableRows += `
        <tr class="total-row">
            <td colspan="2"><strong>TOTAL</strong></td>
            ${totalScores}
            <td class="week-score">${starterSeasonTotal.toFixed(0)}</td>
        </tr>
    `;
    
    // Build taxi squad section with weekly scores - collect ALL taxi players from all weeks
    let taxiHtml = '';
    const taxiPlayerMap = new Map(); // player key -> {name, nfl_team, position, weeks: {weekNum: score}}
    
    // Get current taxi squad from most recent week (to identify who's still on squad)
    const mostRecentWeek = weeksWithScores[weeksWithScores.length - 1];
    const currentTaxiNames = new Set();
    if (mostRecentWeek) {
        for (const matchup of mostRecentWeek.matchups) {
            const team = matchup.team1.abbrev === currentTeam ? matchup.team1 : 
                        (matchup.team2.abbrev === currentTeam ? matchup.team2 : null);
            if (team && team.taxi_squad) {
                team.taxi_squad.forEach(tp => currentTaxiNames.add(tp.name));
            }
        }
    }
    
    // Collect ALL taxi players from ALL weeks
    weeksWithScores.forEach(weekData => {
        for (const matchup of weekData.matchups) {
            const team = matchup.team1.abbrev === currentTeam ? matchup.team1 : 
                        (matchup.team2.abbrev === currentTeam ? matchup.team2 : null);
            if (team && team.taxi_squad) {
                team.taxi_squad.forEach(tp => {
                    const key = `${tp.position}-${tp.name}`;
                    if (!taxiPlayerMap.has(key)) {
                        taxiPlayerMap.set(key, {
                            name: tp.name,
                            nfl_team: tp.nfl_team,
                            position: tp.position,
                            weeks: {}
                        });
                    }
                    taxiPlayerMap.get(key).weeks[weekData.week] = tp.score || 0;
                });
            }
        }
    });
    
    if (taxiPlayerMap.size > 0) {
        // Sort taxi players: current squad first, then former players
        const taxiPlayers = Array.from(taxiPlayerMap.values());
        taxiPlayers.sort((a, b) => {
            const aOnSquad = currentTaxiNames.has(a.name);
            const bOnSquad = currentTaxiNames.has(b.name);
            if (aOnSquad !== bOnSquad) return bOnSquad - aOnSquad;
            return a.name.localeCompare(b.name);
        });
        
        // Build taxi table rows
        const taxiRows = taxiPlayers.map(playerData => {
            const isOnCurrentSquad = currentTaxiNames.has(playerData.name);
            let taxiTotal = 0;   // Points while on taxi squad
            let fullTotal = 0;   // All points including when not on taxi
            
            const weekScores = weeksWithScores.map(w => {
                const score = playerData.weeks[w.week];
                const status = getPlayerStatus({ nfl_team: playerData.nfl_team }, w.week);
                
                if (score !== undefined) {
                    // Player was on taxi squad this week
                    taxiTotal += score;
                    fullTotal += score;
                    
                    if (status.status === 'bye') {
                        return `<td class="week-score"><span class="player-status bye">BYE</span></td>`;
                    } else if (status.status === 'not-played' && score === 0) {
                        const colorClass = status.colorClass || '';
                        return `<td class="week-score"><span class="player-status not-played ${colorClass}">${status.label}</span></td>`;
                    }
                    return `<td class="week-score">${score.toFixed(0)}</td>`;
                } else {
                    // Player wasn't on taxi squad - check if they have a score elsewhere
                    const globalScore = globalPlayerScores[w.week]?.[playerData.name.toLowerCase()];
                    if (globalScore && globalScore.score !== undefined) {
                        fullTotal += globalScore.score;
                        if (status.status === 'bye') {
                            return `<td class="week-score not-on-roster"><span class="player-status bye">(BYE)</span></td>`;
                        }
                        return `<td class="week-score not-on-roster">(${(globalScore.score ?? 0).toFixed(0)})</td>`;
                    }
                    return '<td class="week-score not-on-roster">-</td>';
                }
            }).join('');
            
            const rowClass = isOnCurrentSquad ? '' : 'former-player';
            const nameDisplay = isOnCurrentSquad ? playerData.name : `${playerData.name} *`;
            
            // Show taxi total, and full total in parentheses if different
            const totalDisplay = taxiTotal === fullTotal
                ? `${taxiTotal.toFixed(0)}`
                : `${taxiTotal.toFixed(0)} (${fullTotal.toFixed(0)})`;
            
            return `
                <tr class="${rowClass}">
                    <td class="taxi-pos-cell">${playerData.position}</td>
                    <td>${playerProfileButton(playerData.name, '', nameDisplay, playerData.position)}</td>
                    <td class="player-team">${playerData.nfl_team}</td>
                    ${weekScores}
                    <td class="week-score season-total">${totalDisplay}</td>
                </tr>
            `;
        }).join('');
        
            taxiHtml = `
                <div class="taxi-squad-section">
                    <h3>Taxi Squad</h3>
                <p class="taxi-description">Exclusive development players - cannot be started without promotion to active roster. <span class="former-note">* = no longer on taxi squad</span></p>
                <div class="team-roster-scroll taxi-roster-scroll" role="region" aria-label="Taxi squad weekly scores" tabindex="0">
                    <table class="roster-table taxi-table">
                        <thead>
                            <tr>
                                <th>Pos</th>
                                <th>Player</th>
                                <th>Team</th>
                                ${weeksWithScores.map(w => `<th class="week-col">W${w.week}</th>`).join('')}
                                <th class="week-col">Total</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${taxiRows}
                        </tbody>
                    </table>
                    </div>
                </div>
            `;
    }
    
    // Build draft picks section - new flat array format
    let picksHtml = '';
    if (data.draft_picks && Array.isArray(data.draft_picks)) {
        // Filter picks owned by current team OR where team has conditional claim
        const teamPicks = data.draft_picks.filter(p => 
            p.current_owner === currentTeam || p.conditional_claim === currentTeam
        );
        
        if (teamPicks.length > 0) {
            const seasons = ['2026', '2027', '2028', '2029'];
            const draftTypes = [
                { key: 'offseason', label: 'Offseason Draft' },
                { key: 'offseason_taxi', label: 'Offseason Taxi' },
                { key: 'waiver', label: 'Waiver Draft' },
                { key: 'waiver_taxi', label: 'Waiver Taxi' }
            ];
            
            picksHtml = `
                <div class="draft-picks-section">
                    <h3>Draft Picks</h3>
                    <div class="picks-grid">
                        ${seasons.map(season => {
                            const seasonPicks = teamPicks.filter(p => p.year === season);
                            if (seasonPicks.length === 0) return '';
                            return `
                                <div class="picks-season">
                                    <div class="picks-season-header">${season}</div>
                                    ${draftTypes.map(dt => {
                                        const picks = seasonPicks
                                            .filter(p => p.draft_type === dt.key)
                                            .sort((a, b) => a.round - b.round);
                                        if (picks.length === 0) return '';
                                        return `
                                            <div class="picks-draft-type">
                                                <div class="picks-type-label">${dt.label}</div>
                                                <div class="picks-list">
                                                    ${picks.map(p => {
                                                        const isOwn = p.original_team === currentTeam;
                                                        const isConditionalClaim = p.conditional_claim === currentTeam && p.current_owner !== currentTeam;
                                                        const fromLabel = isOwn ? '' : ` <span class="pick-from">(${p.original_team})</span>`;
                                                        // Show "via" if previous_owners has more owners than just the original (intermediaries)
                                                        const prevOwners = p.previous_owners || [];
                                                        const lastPrevOwner = prevOwners.length > 0 ? prevOwners[prevOwners.length - 1] : null;
                                                        const hasVia = lastPrevOwner && lastPrevOwner !== p.original_team;
                                                        const viaLabel = hasVia ? ` <span class="pick-via">via ${lastPrevOwner}</span>` : '';
                                                        // For conditional claims, show who currently holds the pick
                                                        const conditionalLabel = isConditionalClaim ? ` <span class="pick-conditional-from">from ${p.current_owner}</span>` : '';
                                                        const conditionIcon = p.condition ? `<span class="pick-condition-icon">⚡</span>` : '';
                                                        const conditionAttr = p.condition ? ` data-condition="${p.condition.replace(/"/g, '&quot;')}"` : '';
                                                        const pickClass = isConditionalClaim ? 'conditional' : (isOwn ? 'own' : 'acquired');
                                                        // Show pick number if available (e.g., "1.01" instead of just "R1")
                                                        const pickLabel = p.pick_number ? p.pick_number : `R${p.round}`;
                                                        return `<span class="pick-item ${pickClass}"${conditionAttr}>${pickLabel}${fromLabel}${conditionalLabel}${viaLabel}${conditionIcon}</span>`;
                                                    }).join('')}
                                                </div>
                                            </div>
                                        `;
                                    }).join('')}
                                </div>
                            `;
                        }).join('')}
                    </div>
                </div>
            `;
        }
    }
    
    // Render
    const rosterContainer = document.getElementById('team-roster-container');
    rosterContainer.innerHTML = `
        <div class="team-hub-section-heading">
            <div><h2>Roster</h2></div>
            <a href="#teams/activity/${encodeURIComponent(currentTeam)}" data-route="#teams/activity/${encodeURIComponent(currentTeam)}">View activity →</a>
        </div>
        <p class="horizontal-scroll-hint">Swipe to see weekly scores →</p>
        <div class="team-roster-scroll" role="region" aria-label="Weekly roster scores" tabindex="0">
            <table class="roster-table">
                <thead>
                    <tr>
                        <th>Player</th>
                        <th>Team</th>
                        ${weekHeaders}
                        <th class="week-col season-col">Season</th>
                    </tr>
                </thead>
                <tbody>
                    ${tableRows}
                </tbody>
            </table>
        </div>
        ${taxiHtml}
        ${picksHtml}
    `;
}

function renderTeamHistory() {
    if (!data) return;

    const container = document.getElementById('team-history-container');
    const teamInfo = teamDirectoryTeams().find(team => team.abbrev === currentTeam);
    if (!container || !teamInfo) {
        if (!container) return;
        container.innerHTML = '<p class="no-banners">No team data available</p>';
        return;
    }
    
    const teamRingOfHonor = manualHonorsData?.team_ring_of_honor || {};
    const teamHistory = data.hall_of_fame?.team_hall_of_fame?.[currentTeam];
    if (!teamHistory) {
        container.innerHTML = '<p class="no-banners">Team history is not available in this data export.</p>';
        return;
    }

    const allSeasonData = teamHistory.seasons || [];
    const allTime = teamHistory.allTime || {};
    const allTimeTotalPoints = allTime.totalPoints || 0;
    const allTimeGamesPlayed = allTime.gamesPlayed || 0;
    const allTimeWins = allTime.wins || 0;
    const allTimeLosses = allTime.losses || 0;
    const allTimeTies = allTime.ties || 0;
    const allTimeBiggestWin = allTime.biggestWin || { margin: 0 };
    const topPlayersByTotalPoints = teamHistory.topPlayersByTotalPoints || [];
    const topAllTimeGames = teamHistory.topAllTimeGames || [];
    const topAllTimeGamesNonQB = teamHistory.topAllTimeGamesNonQB || [];
    const topScoringWeeks = teamHistory.topScoringWeeks || [];
    const ownerStats = teamHistory.ownerStats || [];
    const ownerHeadToHead = [...(teamHistory.ownerHeadToHead || [])]
        .sort((a, b) => (b.wins + b.losses + b.ties) - (a.wins + a.losses + a.ties));

    const teamBanners = allSeasonData
        .filter(season => season.seasonFinishes?.some(finish => finish.type === 'champion'))
        .map(season => ({
            year: String(season.season),
            file: data.banners?.find(file => file.includes(String(season.season)))
        }))
        .filter(banner => banner.file);
    
    // Build HTML
    let html = `
        <div class="team-hub-section-heading">
            <div><h2>Franchise Hall of Fame</h2></div>
            <a href="#teams/roster/${encodeURIComponent(currentTeam)}" data-route="#teams/roster/${encodeURIComponent(currentTeam)}">View roster →</a>
        </div>
    `;
    
    if (teamBanners.length > 0) {
        html += `
            <div class="team-hof-section">
                <div class="team-hof-section-title">Championship Banners</div>
                <div class="team-banners-grid">
                    ${teamBanners.map(b => `
                        <div class="team-banner-item">
                            <img src="images/banners/${b.file}" alt="${b.year} Championship" loading="lazy" decoding="async">
                            <div style="text-align: center; margin-top: 0.5rem; color: var(--text-secondary);">${b.year}</div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }
    
    // Team Ring of Honor (if data exists for this team)
    const ringOfHonor = teamRingOfHonor[currentTeam];
    if (ringOfHonor) {
        // Helper to render rings as asterisks
        const renderRings = (count) => '*'.repeat(count || 0);
        
        html += `
            <div class="team-hof-section ring-of-honor">
                <div class="team-hof-section-title">Team Ring of Honor</div>
                <p style="color: var(--text-muted); font-size: 0.85rem; margin-bottom: 1rem; font-style: italic;">
                    Each * signifies a ring won with the franchise
                </p>
                
                ${ringOfHonor.owners && ringOfHonor.owners.length > 0 ? `
                    <div class="ring-of-honor-category">
                        <div class="ring-of-honor-category-title">Team Owners</div>
                        ${ringOfHonor.owners.map(o => `
                            <div class="ring-of-honor-entry">
                                <span class="ring-years">${o.years}:</span>
                                <span class="ring-name">${o.name}</span>
                                <span class="ring-stars">${renderRings(o.rings)}</span>
                            </div>
                        `).join('')}
                    </div>
                ` : ''}
                
                ${ringOfHonor.players && ringOfHonor.players.length > 0 ? `
                    <div class="ring-of-honor-category">
                        <div class="ring-of-honor-category-title">Players</div>
                        ${ringOfHonor.players.map(p => `
                            <div class="ring-of-honor-entry">
                                ${playerProfileButton(p.name, 'ring-name', `${p.position} ${p.name} (${p.team})`, p.position)}
                                <span class="ring-stars">${renderRings(p.rings)}</span>
                            </div>
                        `).join('')}
                    </div>
                ` : ''}
                
                ${ringOfHonor.team_names && ringOfHonor.team_names.length > 0 ? `
                    <div class="ring-of-honor-category">
                        <div class="ring-of-honor-category-title">Team Names</div>
                        ${ringOfHonor.team_names.map(t => `
                            <div class="ring-of-honor-entry">
                                <span class="ring-years">${t.years}</span>
                                <span class="ring-name">- ${t.name}${t.note ? ` (${t.note})` : ''}</span>
                                <span class="ring-stars">${renderRings(t.rings)}</span>
                            </div>
                        `).join('')}
                    </div>
                ` : ''}
            </div>
        `;
    }

    if (ownerStats.length > 0) {
        const formatSeasons = (seasons) => {
            const sorted = [...seasons].sort((a, b) => a - b);
            if (sorted.length > 1 && sorted.every((year, index) => index === 0 || year === sorted[index - 1] + 1)) {
                return `${sorted[0]}–${sorted[sorted.length - 1]}`;
            }
            return sorted.join(', ');
        };

        html += `
            <div class="team-hof-section">
                <div class="team-hof-section-title">Owner Statistics</div>
                <div class="table-scroll-wrapper">
                    <table class="owner-stats-table">
                        <thead>
                            <tr>
                                <th>Owner</th>
                                <th>Seasons</th>
                                <th>Record</th>
                                <th>Win%</th>
                                <th>Points</th>
                                <th>PPG</th>
                                <th>Rings</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${ownerStats.map(owner => `
                                <tr>
                                    <td>${escapeHtml(normalizeCoOwnerLabel(owner.owner) || '')}</td>
                                    <td>${formatSeasons(owner.seasons || [])}</td>
                                    <td>${owner.wins || 0}-${owner.losses || 0}${owner.ties ? `-${owner.ties}` : ''}</td>
                                    <td>${(owner.winPct || 0).toFixed(1)}%</td>
                                    <td>${(owner.totalPoints || 0).toFixed(0)}</td>
                                    <td>${(owner.ppg || 0).toFixed(1)}</td>
                                    <td class="rings">${'🏆'.repeat(owner.rings || 0) || '—'}</td>
                                </tr>
                            `).join('')}
                        </tbody>
                    </table>
                </div>
            </div>
        `;
    }
    
    // Franchise records
    if (allSeasonData.length > 0) {
        html += `
            <div class="team-hof-section">
                <div class="team-hof-section-title">Franchise Records</div>
                <div class="team-hof-record">
                    <span class="team-hof-record-label">Overall Record</span>
                    <span class="team-hof-record-value">${allTimeWins}-${allTimeLosses}${allTimeTies > 0 ? `-${allTimeTies}` : ''}</span>
                </div>
                <div class="team-hof-record">
                    <span class="team-hof-record-label">Total Points Scored</span>
                    <span class="team-hof-record-value">${allTimeTotalPoints.toFixed(0)} pts (${allTimeGamesPlayed} games)</span>
                </div>
                <div class="team-hof-record">
                    <span class="team-hof-record-label">Points Per Game</span>
                    <span class="team-hof-record-value">${(allTimeTotalPoints / allTimeGamesPlayed).toFixed(1)} PPG</span>
                </div>
                ${allTimeBiggestWin.margin > 0 ? `
                    <div class="team-hof-record">
                        <span class="team-hof-record-label">Largest Margin of Victory</span>
                        <span class="team-hof-record-value">+${allTimeBiggestWin.margin.toFixed(0)} pts (${allTimeBiggestWin.season} Week ${allTimeBiggestWin.week} vs ${allTimeBiggestWin.opponent}, ${allTimeBiggestWin.score})</span>
                    </div>
                ` : ''}
            </div>
        `;
    }

    if (ownerHeadToHead.length > 0) {
        html += `
            <div class="team-hof-section">
                <div class="team-hof-section-title">Head-to-Head Records</div>
                <div class="team-series-grid">
                    ${ownerHeadToHead.map(record => {
                        const games = record.wins + record.losses + record.ties;
                        const result = record.wins > record.losses ? 'leading' : record.wins < record.losses ? 'trailing' : 'even';
                        return `
                            <div class="team-series-card ${result}">
                                <span>${escapeHtml(normalizeCoOwnerLabel(record.owner) || record.ownerId)} vs. ${escapeHtml(normalizeCoOwnerLabel(record.opponent) || record.opponentId)}</span>
                                <strong>${record.wins}–${record.losses}${record.ties ? `–${record.ties}` : ''}</strong>
                                <small>${games} games · ${result}</small>
                            </div>
                        `;
                    }).join('')}
                </div>
            </div>
        `;
    }
    
    // Top players by total starter points
    if (topPlayersByTotalPoints.length > 0) {
        html += `
            <div class="team-hof-section">
                <div class="team-hof-section-title">Most Total Points as Starter</div>
                ${topPlayersByTotalPoints.map((p, i) => `
                    <div class="team-hof-record">
                        ${playerProfileButton(p.name, 'team-hof-record-label', `${i + 1}. ${p.position} ${p.name} (${p.nfl_team || 'N/A'})`, p.position)}
                        <span class="team-hof-record-value">${p.totalPoints.toFixed(0)} pts (${p.gamesStarted} starts)</span>
                    </div>
                `).join('')}
            </div>
        `;
    }
    
    // Finishes by Year header and season-by-season records
    if (allSeasonData.length > 0) {
        html += `<h3 style="text-align: center; margin: 2rem 0 1rem; color: var(--text-primary);">Finishes by Year</h3>`;
        
        allSeasonData.forEach(s => {
            const finishBadges = s.seasonFinishes?.map(f => {
                let badgeClass = 'playoff-finish-badge';
                if (f.type === 'champion') badgeClass += ' champion';
                else if (f.type === 'toilet-bowl') badgeClass += ' toilet-bowl';
                else if (f.type === 'jambo') badgeClass += ' jambo';
                return `<span class="${badgeClass}">${f.label}</span>`;
            }).join(' ') || '';
            
            html += `
                <div class="team-hof-section">
                    <div class="team-hof-section-title">${s.season} Season ${finishBadges}</div>
                    <div class="team-hof-record">
                        <span class="team-hof-record-label">Record</span>
                        <span class="team-hof-record-value">${s.wins}-${s.losses}${s.ties > 0 ? `-${s.ties}` : ''}</span>
                    </div>
                    <div class="team-hof-record">
                        <span class="team-hof-record-label">Total Points</span>
                        <span class="team-hof-record-value">${s.totalPoints.toFixed(0)}</span>
                    </div>
                    <div class="team-hof-record">
                        <span class="team-hof-record-label">Points Per Game</span>
                        <span class="team-hof-record-value">${s.ppg.toFixed(1)}</span>
                    </div>
                    <div class="team-hof-record">
                        <span class="team-hof-record-label">Highest Score</span>
                        <span class="team-hof-record-value">${s.highestScore.score.toFixed(0)} (Week ${s.highestScore.week} vs ${s.highestScore.opponent})</span>
                    </div>
                    ${s.lowestScore ? `
                        <div class="team-hof-record">
                            <span class="team-hof-record-label">Lowest Score</span>
                            <span class="team-hof-record-value">${s.lowestScore.score.toFixed(0)} (Week ${s.lowestScore.week} vs ${s.lowestScore.opponent})</span>
                        </div>
                    ` : ''}
                    ${s.biggestWin ? `
                        <div class="team-hof-record">
                            <span class="team-hof-record-label">Biggest Win</span>
                            <span class="team-hof-record-value">+${s.biggestWin.margin.toFixed(0)} (Week ${s.biggestWin.week} vs ${s.biggestWin.opponent}, ${s.biggestWin.score})</span>
                        </div>
                    ` : ''}
                    ${s.biggestLoss ? `
                        <div class="team-hof-record">
                            <span class="team-hof-record-label">Biggest Loss</span>
                            <span class="team-hof-record-value">-${s.biggestLoss.margin.toFixed(0)} (Week ${s.biggestLoss.week} vs ${s.biggestLoss.opponent}, ${s.biggestLoss.score})</span>
                        </div>
                    ` : ''}
                </div>
            `;
        });
    }
    
    // Highest Scoring Weeks
    if (topScoringWeeks.length > 0) {
        html += `
            <div class="team-hof-section">
                <div class="team-hof-section-title">Highest Scoring Weeks</div>
                ${topScoringWeeks.map((w, i) => `
                    <div class="team-hof-record">
                        <span class="team-hof-record-label">${i + 1}. ${w.season} Week ${w.week} vs ${w.opponent}</span>
                        <span class="team-hof-record-value">${w.score.toFixed(0)} pts (${w.result})</span>
                    </div>
                `).join('')}
            </div>
        `;
    }
    
    // Top starter performances
    if (topAllTimeGames.length > 0) {
        html += `
            <div class="team-hof-section">
                <div class="team-hof-section-title">Top Starter Performances</div>
                ${topAllTimeGames.map((p, i) => `
                    <div class="team-hof-record">
                        ${playerProfileButton(p.name, 'team-hof-record-label', `${i + 1}. ${p.position} ${p.name} (${p.nfl_team || 'N/A'})`, p.position)}
                        <span class="team-hof-record-value">${p.score.toFixed(0)} pts (${p.season} Week ${p.week})</span>
                    </div>
                `).join('')}
            </div>
        `;
    }
    
    // Top non-QB starter performances
    if (topAllTimeGamesNonQB.length > 0) {
        html += `
            <div class="team-hof-section">
                <div class="team-hof-section-title">Top Starter Performances — Non-QB</div>
                ${topAllTimeGamesNonQB.map((p, i) => `
                    <div class="team-hof-record">
                        ${playerProfileButton(p.name, 'team-hof-record-label', `${i + 1}. ${p.position} ${p.name} (${p.nfl_team || 'N/A'})`, p.position)}
                        <span class="team-hof-record-value">${p.score.toFixed(0)} pts (${p.season} Week ${p.week})</span>
                    </div>
                `).join('')}
            </div>
        `;
    }
    
    container.innerHTML = html;
}

function teamHistoryData() {
    return data.hall_of_fame?.team_hall_of_fame?.[currentTeam] || null;
}

function teamTransactions() {
    return (sharedData.transactions || data.transactions || []).filter(transaction =>
        txInvolvesTeam(transaction, currentTeam)
    );
}


function transactionAssets(bundle) {
    if (!bundle) return [];
    return [
        ...(bundle.players || []).map(player => typeof player === 'string' ? player : player.name),
        ...(bundle.picks || []),
    ].filter(Boolean);
}

function teamTransactionSummary(transaction) {
    const isStructuredTrade = transaction.type === 'trade'
        && transaction.proposer
        && transaction.partner;
    if (isStructuredTrade) {
        const isProposer = transaction.proposer === currentTeam;
        const partner = isProposer ? transaction.partner : transaction.proposer;
        const received = transactionAssets(
            isProposer ? transaction.proposer_receives : transaction.proposer_gives
        );
        const sent = transactionAssets(
            isProposer ? transaction.proposer_gives : transaction.proposer_receives
        );
        return `Trade with ${partner}: received ${received.join(', ') || 'nothing'}; sent ${sent.join(', ') || 'nothing'}.`;
    }

    const { cleanMessage } = extractDateFromMessage(
        transaction.message || formatTransactionMessage(transaction)
    );
    if (transaction.type !== 'trade') return cleanMessage;

    const parsed = parseOldTradeMessage(cleanMessage);
    const currentSide = parsed?.teams.find(team => ownerTeamCode(team.name) === currentTeam);
    const partnerSide = parsed?.teams.find(team => team !== currentSide);
    if (!currentSide || !partnerSide) return cleanMessage;

    const received = currentSide.items.join(', ') || 'nothing';
    const sent = partnerSide.items.join(', ') || 'nothing';
    return `Trade with ${partnerSide.name}: received ${received}; sent ${sent}.`;
}

function teamTransactionDateLabel(transaction) {
    const { date } = extractDateFromMessage(transaction.message);
    return date || formatDate(transaction.timestamp);
}

function teamTransactionHtml(transaction) {
    const label = String(transaction.type || 'move').replace(/_/g, ' ');
    return `
        <article class="team-activity-item">
            <div><span>${escapeHtml(label)}</span><time>${escapeHtml(teamTransactionDateLabel(transaction))}</time></div>
            <p>${escapeHtml(teamTransactionSummary(transaction))}</p>
        </article>
    `;
}

function renderTeamActivity() {
    const container = document.getElementById('team-activity-container');
    if (!container) return;
    const transactions = teamTransactions();
    const route = `#transactions?teams=${encodeURIComponent(currentTeam)}`;

    container.innerHTML = `
        <div class="team-hub-section-heading">
            <div><h2>Activity</h2></div>
            <a href="${route}" data-route="${route}">Filtered transaction history →</a>
        </div>
        <div class="team-activity-grid">
            <section class="team-activity-panel">
                <div class="team-activity-panel-heading"><h3>Trade Block</h3></div>
                <div class="trade-block-content" id="team-tradeblock-container"></div>
            </section>
            <section class="team-activity-panel">
                <div class="team-activity-panel-heading"><h3>Transaction Log</h3></div>
                <div class="team-activity-list">
                    ${transactions.slice(0, 12).map(teamTransactionHtml).join('') || '<p class="team-card-empty">No transactions are recorded for this franchise.</p>'}
                </div>
                ${transactions.length > 12 ? `<a class="team-card-link" href="${route}" data-route="${route}">View all ${transactions.length} moves →</a>` : ''}
            </section>
        </div>
    `;
    renderTeamTradeBlock();
}

function renderActiveTeamSubview(subview) {
    if (!TEAM_HUB_SUBVIEWS.has(subview)) return;
    if (subview === 'history') renderTeamHistory();
    else if (subview === 'activity') renderTeamActivity();
}

function renderTeamTradeBlock() {
    if (!currentTeam || !data) return;
    
    const container = document.getElementById('team-tradeblock-container');
    if (!container) return;
    const tradeBlocks = data.trade_blocks || {};
    const teamBlock = tradeBlocks[currentTeam] || {};
    
    const seeking = teamBlock.seeking || [];
    const tradingAway = teamBlock.trading_away || [];
    const playersAvailable = teamBlock.players_available || [];
    const notes = teamBlock.notes || '';
    
    // Check if trade block is empty
    if (!seeking.length && !tradingAway.length && !playersAvailable.length && !notes) {
        container.innerHTML = `
            <div class="trade-block-empty">
                <div class="trade-block-empty-icon"></div>
                <p>This team hasn't set up their trade block yet.</p>
            </div>
        `;
        return;
    }
    
    let html = '';
    
    // Seeking positions
    if (seeking.length) {
        html += `
            <div class="trade-block-section">
                <h3 class="trade-block-section-title seeking">Looking For</h3>
                <div class="trade-block-positions">
                    ${seeking.map(pos => `<span class="trade-block-position seeking">${pos}</span>`).join('')}
                </div>
            </div>
        `;
    }
    
    // Trading away positions
    if (tradingAway.length) {
        html += `
            <div class="trade-block-section">
                <h3 class="trade-block-section-title trading">Willing to Trade</h3>
                <div class="trade-block-positions">
                    ${tradingAway.map(pos => `<span class="trade-block-position trading">${pos}</span>`).join('')}
                </div>
            </div>
        `;
    }
    
    // Players available
    if (playersAvailable.length) {
        // Get player details from roster
        const roster = data.rosters?.[currentTeam] || [];
        const allPlayers = Array.isArray(roster) ? roster : [...(roster.roster || []), ...(roster.taxi_squad || [])];

        const availableWithPos = playersAvailable.map(playerName => {
            const player = allPlayers.find(p => p.name === playerName);
            return { name: playerName, position: player?.position || '' };
        });

        html += `
            <div class="trade-block-section">
                <h3 class="trade-block-section-title trading">Players Available</h3>
                <div class="trade-block-players">
                    ${sortRosterByPosition(availableWithPos).map(p => `
                        <div class="trade-block-player">
                            <span class="trade-block-player-pos">${escapeHtml(p.position)}</span>
                            ${playerProfileButton(p.name, 'trade-block-player-name', null, p.position)}
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }
    
    // Notes
    if (notes) {
        html += `
            <div class="trade-block-section">
                <h3 class="trade-block-section-title">Notes</h3>
                <div class="trade-block-notes">${escapeHtml(notes)}</div>
            </div>
        `;
    }
    
    container.innerHTML = html;
}

// ====== HEAD-TO-HEAD RECORDS ======

// All-time H2H from data.hall_of_fame.rivalry_records (pre-computed in export).
// Returns { wins1, wins2, ties } from abbrev1's perspective, or null if not found.
function getH2HRecord(abbrev1, abbrev2) {
    const records = data.hall_of_fame?.rivalry_records?.records;
    if (!records) return null;
    const rec = records.find(r =>
        (r.team1 === abbrev1 && r.team2 === abbrev2) ||
        (r.team1 === abbrev2 && r.team2 === abbrev1)
    );
    if (!rec) return null;
    const wins1 = rec.team1 === abbrev1 ? rec.team1_wins : rec.team2_wins;
    const wins2 = rec.team1 === abbrev1 ? rec.team2_wins : rec.team1_wins;
    return { wins1, wins2, ties: rec.ties, games: rec.games };
}

// Current-viewing-season H2H from data.weeks.
// Returns { wins1, wins2, ties } from abbrev1's perspective.
function getSeasonH2H(abbrev1, abbrev2) {
    if (!data.all_weeks_loaded) return null;
    let wins1 = 0, wins2 = 0, ties = 0;
    for (const w of (data.weeks || [])) {
        if (!w.has_scores) continue;
        for (const m of (w.matchups || [])) {
            const t1 = m.team1, t2 = m.team2;
            if (!t1?.abbrev || !t2?.abbrev) continue;
            let teamA, teamB;
            if (t1.abbrev === abbrev1 && t2.abbrev === abbrev2) { teamA = t1; teamB = t2; }
            else if (t1.abbrev === abbrev2 && t2.abbrev === abbrev1) { teamA = t2; teamB = t1; }
            else continue;
            const sA = typeof teamA.total_score === 'number' ? teamA.total_score : sumStarterScores(teamA.roster);
            const sB = typeof teamB.total_score === 'number' ? teamB.total_score : sumStarterScores(teamB.roster);
            if (sA > sB) wins1++;
            else if (sB > sA) wins2++;
            else ties++;
        }
    }
    return { wins1, wins2, ties };
}

// Builds H2H badge HTML for a matchup between abbrev1 and abbrev2.
function renderH2HBadge(abbrev1, abbrev2, currentSeason) {
    const allTime = getH2HRecord(abbrev1, abbrev2);
    const season = getSeasonH2H(abbrev1, abbrev2);
    const seasonGames = season ? season.wins1 + season.wins2 + season.ties : 0;

    if (!allTime && seasonGames === 0) return '';

    let parts = [];
    if (allTime) {
        const tiesStr = allTime.ties ? ` · ${allTime.ties}T` : '';
        parts.push(`All-time: ${allTime.wins1}–${allTime.wins2}${tiesStr}`);
    }
    if (season && seasonGames > 0) {
        const tStr = season.ties ? `·${season.ties}T` : '';
        parts.push(`${currentSeason}: ${season.wins1}–${season.wins2}${tStr}`);
    }
    return `<div class="h2h-badge">${parts.join('<span class="h2h-sep">·</span>')}</div>`;
}

// For historical seasons, data.rosters is empty — reconstruct from the last scored week.
function buildRostersFromWeeks() {
    const scored = (data.weeks || []).filter(w => w.matchups?.length).sort((a, b) => a.week - b.week);
    if (!scored.length) return {};
    const lastWeek = scored[scored.length - 1];
    const result = {};
    for (const m of lastWeek.matchups) {
        for (const t of [m.team1, m.team2]) {
            if (!t?.abbrev) continue;
            result[t.abbrev] = (t.roster || []).map(p => ({
                name: p.name,
                nfl_team: p.nfl_team,
                position: p.position,
            }));
        }
    }
    return result;
}

let allRostersSearchQuery = '';
let allRostersSearchEntries = [];
let allRostersSearchBound = false;
const allRostersHiddenRows = new Set();

function updateAllRostersSearch() {
    const input = document.getElementById('all-rosters-search');
    const results = document.getElementById('all-rosters-search-results');
    const table = document.querySelector('.all-rosters-table');
    if (!input || !results) return;

    const query = allRostersSearchQuery.trim().toLowerCase();
    input.value = allRostersSearchQuery;
    if (table) {
        table.classList.toggle('searching', Boolean(query));
        table.querySelectorAll('.ar-player-cell').forEach(cell => {
            cell.classList.toggle(
                'search-match',
                Boolean(query) && cell.dataset.playerSearch.includes(query)
            );
        });
    }
    if (!query) {
        results.innerHTML = '';
        return;
    }

    const allMatches = allRostersSearchEntries.filter(entry => entry.searchText.includes(query));
    const matches = allMatches.slice(0, 8);
    if (allMatches.length === 0) {
        results.innerHTML = emptyStateHtml(
            'No rostered players match',
            'Try a different player, position, NFL team, or QPFL team.',
            [{ label: 'Clear search', action: 'clear-roster-search' }]
        );
        return;
    }

    results.innerHTML = `
        <p class="results-summary">${allMatches.length} ${allMatches.length === 1 ? 'player' : 'players'} found${allMatches.length > matches.length ? ` · showing ${matches.length}` : ''}</p>
        ${matches.map(entry => `
        <div class="roster-search-result">
            ${playerProfileButton(entry.player.name, '', null, entry.player.position)}
            <span class="roster-search-result-meta">${escapeHtml(entry.player.position)} · ${escapeHtml(entry.player.nfl_team || 'No NFL team')}</span>
            <span class="roster-search-owner">${teamProfileButton(entry.abbrev, entry.teamName)}</span>
        </div>
        `).join('')}`;
}

function updateAllRostersRowVisibility(container) {
    const rows = [...container.querySelectorAll('.all-rosters-player-row')];
    rows.forEach(row => {
        row.hidden = allRostersHiddenRows.has(row.dataset.rowKey);
    });

    container.querySelectorAll('.roster-position-toggle').forEach(button => {
        const positionRows = rows.filter(row => row.dataset.position === button.dataset.position);
        const allHidden = positionRows.length > 0 && positionRows.every(row => row.hidden);
        const actionLabel = `${allHidden ? 'Show' : 'Hide'} ${button.dataset.position} rows`;
        button.setAttribute('aria-label', actionLabel);
        button.title = actionLabel;
        button.setAttribute('aria-pressed', String(!allHidden));
        button.classList.toggle('is-hidden', allHidden);
    });

    const hiddenCount = rows.filter(row => row.hidden).length;
    const status = container.querySelector('.roster-row-status');
    const reset = container.querySelector('.roster-rows-reset');
    if (status) {
        status.textContent = hiddenCount
            ? `${hiddenCount} ${hiddenCount === 1 ? 'row' : 'rows'} hidden`
            : 'All rows shown';
    }
    if (reset) reset.disabled = hiddenCount === 0;
}

function bindAllRostersRowControls(container) {
    container.querySelectorAll('.roster-row-hide').forEach(button => {
        button.addEventListener('click', () => {
            allRostersHiddenRows.add(button.dataset.rowKey);
            updateAllRostersRowVisibility(container);
        });
    });

    container.querySelectorAll('.roster-position-toggle').forEach(button => {
        button.addEventListener('click', () => {
            const positionRows = [...container.querySelectorAll(
                `.all-rosters-player-row[data-position="${button.dataset.position}"]`
            )];
            const allHidden = positionRows.every(row => allRostersHiddenRows.has(row.dataset.rowKey));
            positionRows.forEach(row => {
                if (allHidden) allRostersHiddenRows.delete(row.dataset.rowKey);
                else allRostersHiddenRows.add(row.dataset.rowKey);
            });
            updateAllRostersRowVisibility(container);
        });
    });

    container.querySelector('.roster-rows-reset')?.addEventListener('click', () => {
        allRostersHiddenRows.clear();
        updateAllRostersRowVisibility(container);
    });
}

function bindAllRostersSearch() {
    const input = document.getElementById('all-rosters-search');
    if (!input || allRostersSearchBound) return;
    input.addEventListener('input', () => {
        allRostersSearchQuery = input.value;
        updateAllRostersSearch();
    });
    input.addEventListener('search', () => {
        allRostersSearchQuery = input.value;
        updateAllRostersSearch();
    });
    allRostersSearchBound = true;
}

async function renderAllRosters() {
    const container = document.getElementById('all-rosters-container');
    if (!container) return;

    // Ensure previous season is loaded for the offseason rank fallback
    const hasGamesPlayedCheck = (data.standings || []).some(t => (t.wins || 0) + (t.losses || 0) > 0);
    if (!hasGamesPlayedCheck && !data.previous_season && !data.is_historical) {
        await ensurePreviousSeasonLoaded();
    }

    // Use live rosters when available; fall back to reconstructing from week data
    let rosters = data?.rosters;
    if (!rosters || typeof rosters !== 'object' || Object.keys(rosters).length === 0) {
        rosters = buildRostersFromWeeks();
    }
    if (!rosters || Object.keys(rosters).length === 0) {
        container.innerHTML = emptyStateHtml(
            'No roster data available',
            'The current season may have newer roster information.',
            currentSeason === LIVE_SEASON ? [] : [{ label: 'Return to current season', action: 'current-season' }]
        );
        return;
    }

    // Build a flat name → total_points lookup from the stats leaders data
    const leaders = getStatsLeaders();
    const playerPts = {};
    for (const players of Object.values(leaders)) {
        for (const p of players) playerPts[p.name] = p.total_points;
    }

    // Order teams by standings rank when available, otherwise alphabetical
    const standingsOrder = (data.standings || []).map(t => t.abbrev);
    const allAbbrevs = Object.keys(rosters);
    const teamAbbrevs = [
        ...standingsOrder.filter(a => allAbbrevs.includes(a)),
        ...allAbbrevs.filter(a => !standingsOrder.includes(a)).sort()
    ];

    if (teamAbbrevs.length === 0) {
        container.innerHTML = emptyStateHtml(
            'No teams to display',
            'Return to the current season to view active league rosters.',
            currentSeason === LIVE_SEASON ? [] : [{ label: 'Return to current season', action: 'current-season' }]
        );
        return;
    }

    const teamInfoFor = (abbrev) =>
        data.teams?.find(t => t.abbrev === abbrev) ||
        data.standings?.find(t => t.abbrev === abbrev) ||
        { abbrev, name: abbrev, owner: '' };

    allRostersSearchEntries = teamAbbrevs.flatMap(abbrev => {
        const teamName = teamInfoFor(abbrev).name || abbrev;
        return (rosters[abbrev] || []).map(player => ({
            player,
            abbrev,
            teamName,
            searchText: `${player.name} ${player.position} ${player.nfl_team || ''} ${abbrev} ${teamName}`.toLowerCase(),
        }));
    });

    const positions = ROSTER_POSITION_ORDER;

    // Group each team's roster by position
    const teamPlayersByPos = {};
    teamAbbrevs.forEach(abbrev => {
        const sorted = sortRosterByPosition(rosters[abbrev] || []);
        const grouped = {};
        positions.forEach(p => grouped[p] = []);
        sorted.forEach(p => {
            if (grouped[p.position]) grouped[p.position].push(p);
        });
        teamPlayersByPos[abbrev] = grouped;
    });

    // For each position, find the max # of players across teams (so rows align)
    const posMax = {};
    positions.forEach(pos => {
        posMax[pos] = Math.max(0, ...teamAbbrevs.map(a => teamPlayersByPos[a][pos].length));
    });

    const SEP = '<th class="ar-sep"></th>';
    const hasAnyPts = Object.keys(playerPts).length > 0;
    const teamStatsMap = data.team_stats || {};

    // Determine rank source: use current standings when games have been played,
    // otherwise fall back to the previous season's final standings.
    const hasGamesPlayed = (data.standings || []).some(t => (t.wins || 0) + (t.losses || 0) > 0);
    const rankStandings = hasGamesPlayed
        ? (data.standings || [])
        : (data.previous_season?.standings || []);
    const rankMap = {};
    rankStandings.forEach((t, i) => { rankMap[t.abbrev] = i + 1; });

    const headerCells = teamAbbrevs.map((abbrev, i) => {
        const info = teamInfoFor(abbrev);
        const owner = info.owner ? `<div class="team-header-owner">${escapeHtml(normalizeCoOwnerLabel(info.owner))}</div>` : '';
        const sep = i < teamAbbrevs.length - 1 ? SEP : '';
        const colspan = hasAnyPts ? ' colspan="2"' : '';
        const ts = teamStatsMap[abbrev];
        let statsHtml = '';
        if (ts && (ts.wins || ts.losses || ts.ties)) {
            const rec = `${ts.wins ?? 0}-${ts.losses ?? 0}${ts.ties ? `-${ts.ties}` : ''}`;
            const streak = ts.streak?.count ? `${ts.streak.type}${ts.streak.count}` : null;
            const recLine = streak ? `Record: ${rec} &nbsp;Streak: ${streak}` : `Record: ${rec}`;
            const ppgLine = ts.ppg != null ? `Avg Pts: ${ts.ppg.toFixed(1)}` : '';
            statsHtml = `<div class="team-header-stats">${recLine}${ppgLine ? `<br>${ppgLine}` : ''}</div>`;
        }
        const rank = rankMap[abbrev];
        const rankClass = rank === 1 ? ' ar-rank-gold' : rank === 2 ? ' ar-rank-silver' : rank === 3 ? ' ar-rank-bronze' : rank === 4 ? ' ar-rank-green' : '';
        const rankBadge = rank != null ? `<span class="ar-rank-badge${rankClass}">${rank}</span>` : '';
        return `<th${colspan}>${rankBadge}<div class="team-header-cell">${teamAvatar(abbrev, info.name, '', info.avatar || currentTeamAvatar(abbrev))}${teamProfileButton(abbrev, info.name || abbrev, 'team-header-name')}</div>${owner}${statsHtml}</th>${sep}`;
    }).join('');

    const colsPerTeam = hasAnyPts ? 2 : 1;
    const totalCols = teamAbbrevs.length * colsPerTeam + (teamAbbrevs.length - 1) + 1;

    const bodyRows = positions.map(pos => {
        if (posMax[pos] === 0) return '';
        let rows = `<tr class="position-group"><td class="ar-row-control-cell ar-position-control-cell"><button type="button" class="roster-position-toggle pos-${posClassKey(pos)}" data-position="${escapeHtml(pos)}" aria-label="Hide ${escapeHtml(pos)} rows" title="Hide ${escapeHtml(pos)} rows" aria-pressed="true">${escapeHtml(pos)}</button></td><td colspan="${totalCols - 1}"><span class="ar-pos-label pos-${posClassKey(pos)}">${escapeHtml(pos)}</span></td></tr>`;
        for (let i = 0; i < posMax[pos]; i++) {
            const rowKey = `${pos}-${i}`;
            rows += `<tr class="all-rosters-player-row" data-position="${escapeHtml(pos)}" data-row-key="${escapeHtml(rowKey)}"><td class="ar-row-control-cell"><button type="button" class="roster-row-hide" data-row-key="${escapeHtml(rowKey)}" aria-label="Hide ${escapeHtml(pos)} row ${i + 1}" title="Hide this row">−</button></td>`;
            teamAbbrevs.forEach((abbrev, j) => {
                const player = teamPlayersByPos[abbrev][pos][i];
                if (player) {
                    const pts = playerPts[player.name];
                    const ptsCell = hasAnyPts
                        ? `<td class="ar-pts-cell">${pts !== undefined ? pts.toFixed(0) : '—'}</td>`
                        : '';
                    rows += `<td class="ar-player-cell" data-player-search="${escapeHtml(`${player.name} ${player.position} ${player.nfl_team || ''} ${abbrev} ${teamInfoFor(abbrev).name || ''}`.toLowerCase())}">
                        ${playerProfileButton(player.name, 'ar-player-name', null, player.position)}
                        <span class="ar-player-team">${escapeHtml(player.nfl_team || '')}</span>
                    </td>${ptsCell}`;
                } else {
                    const emptyPtsCell = hasAnyPts ? '<td class="ar-pts-cell empty-slot"></td>' : '';
                    rows += `<td class="empty-slot"></td>${emptyPtsCell}`;
                }
                if (j < teamAbbrevs.length - 1) rows += '<td class="ar-sep"></td>';
            });
            rows += '</tr>';
        }
        return rows;
    }).join('');

    const colgroup = '<colgroup><col class="ar-col-row-control">' + teamAbbrevs.map((_, i) =>
        `<col class="ar-col-player">${hasAnyPts ? '<col class="ar-col-pts">' : ''}${i < teamAbbrevs.length - 1 ? '<col class="ar-col-sep">' : ''}`
    ).join('') + '</colgroup>';

    container.innerHTML = `
        <div class="roster-row-toolbar">
            <span class="roster-row-status" aria-live="polite">All rows shown</span>
            <button type="button" class="roster-rows-reset" disabled>Show all rows</button>
        </div>
        <div class="all-rosters-spreadsheet" role="region" aria-label="League rosters spreadsheet" tabindex="0">
            <table class="all-rosters-table">
                ${colgroup}
                <thead><tr><th class="ar-row-controls-header">Rows</th>${headerCells}</tr></thead>
                <tbody>${bodyRows}</tbody>
            </table>
        </div>
    `;
    bindAllRostersRowControls(container);
    updateAllRostersRowVisibility(container);
    bindAllRostersSearch();
    updateAllRostersSearch();
}

function renderBanners() {
    if (!data.banners) return;
    
    const container = document.getElementById('banners-container');
    // Reverse to show most recent banner first
    const sortedBanners = [...data.banners].reverse();
    container.innerHTML = sortedBanners.map(img => `
        <div class="banner-item">
            <img src="images/banners/${img}" alt="Championship Banner" loading="lazy" decoding="async">
        </div>
    `).join('');
}

function renderHallOfFame() {
    if (!data.hall_of_fame) return;
    
    const hof = data.hall_of_fame;
    const container = document.getElementById('hof-container');
    let html = `
        <nav class="hof-index" aria-label="Hall of Fame sections">
            <button type="button" data-hof-section="hof-seasons">Seasons</button>
            <button type="button" data-hof-section="hof-owners">Owners</button>
            <button type="button" data-hof-section="hof-team-records">Team records</button>
            <button type="button" data-hof-section="hof-player-records">Player records</button>
            <button type="button" data-hof-section="hof-rivalries">Rivalries</button>
        </nav>
    `;
    
    let ownerStatsHtml = '';

    // Owner Stats Table
    if (hof.owner_stats && hof.owner_stats.length > 0) {
        // Calculate leaders for each category (for underlining)
        const parseWins = (record) => parseInt(record?.split('-')[0]) || 0;
        const parsePct = (pct) => parseFloat(pct?.replace('%', '')) || 0;
        const parseNum = (n) => parseInt(n) || 0;
        
        const maxSeasons = Math.max(...hof.owner_stats.map(o => parseNum(o.Seasons)));
        const maxWins = Math.max(...hof.owner_stats.map(o => parseWins(o.Record)));
        const maxWinPct = Math.max(...hof.owner_stats.map(o => parsePct(o['Win%'])));
        const maxPlayoffs = Math.max(...hof.owner_stats.map(o => parseNum(o['Playoff Berths'])));
        const maxPOWinPct = Math.max(...hof.owner_stats.filter(o => parseNum(o['Playoff Berths']) > 0).map(o => parsePct(o['Playoff Win%'])));
        const max3rd = Math.max(...hof.owner_stats.map(o => parseNum(o['3rd Place'])));
        const max2nd = Math.max(...hof.owner_stats.map(o => parseNum(o['2nd Place'])));
        const maxRings = Math.max(...hof.owner_stats.map(o => parseNum(o.Rings)));
        const maxPrestige = Math.max(...hof.owner_stats.map(o => parseFloat(o.Prestige) || 0));
        
        const underlineIf = (val, max, display) => val === max && max > 0 ? `<u>${display}</u>` : display;
        
        ownerStatsHtml = `
            <div class="hof-section" id="hof-owners">
                <div class="hof-section-title">Owner Statistics</div>
                <div class="table-scroll-wrapper">
                <table class="owner-stats-table">
                    <thead>
                        <tr>
                            <th>Owner</th>
                            <th>Seasons</th>
                            <th>Record</th>
                            <th>Win%</th>
                            <th>Playoffs</th>
                            <th>PO Record</th>
                            <th>PO Win%</th>
                            <th>3rd</th>
                            <th>2nd</th>
                            <th>Rings</th>
                            <th>Prestige</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${hof.owner_stats.map(owner => {
                            const seasons = parseNum(owner.Seasons);
                            const wins = parseWins(owner.Record);
                            const winPct = parsePct(owner['Win%']);
                            const playoffs = parseNum(owner['Playoff Berths']);
                            const poWinPct = parsePct(owner['Playoff Win%']);
                            const third = parseNum(owner['3rd Place']);
                            const second = parseNum(owner['2nd Place']);
                            const rings = parseNum(owner.Rings);
                            const prestige = parseFloat(owner.Prestige) || 0;
                            
                            return `
                            <tr>
                                <td>${owner.Owner || ''}</td>
                                <td>${underlineIf(seasons, maxSeasons, owner.Seasons || '')}</td>
                                <td>${underlineIf(wins, maxWins, owner.Record || '')}</td>
                                <td>${underlineIf(winPct, maxWinPct, owner['Win%'] || '')}</td>
                                <td>${underlineIf(playoffs, maxPlayoffs, owner['Playoff Berths'] || '')}</td>
                                <td>${owner['Playoff Record'] || '0-0'}</td>
                                <td>${playoffs > 0 ? underlineIf(poWinPct, maxPOWinPct, owner['Playoff Win%'] || '0%') : (owner['Playoff Win%'] || '0%')}</td>
                                <td>${underlineIf(third, max3rd, owner['3rd Place'] || '0')}</td>
                                <td>${underlineIf(second, max2nd, owner['2nd Place'] || '0')}</td>
                                <td class="rings">${underlineIf(rings, maxRings, '🏆'.repeat(rings))}</td>
                                <td class="prestige">${underlineIf(prestige, maxPrestige, owner.Prestige || '0.00')}</td>
                            </tr>
                        `;}).join('')}
                    </tbody>
                </table>
                </div>
                <div class="formula-note">
                    <strong>Prestige Formula:</strong> (1 + Championships × 0.2) × { (Reg Season Games × Reg Season Win% / League Avg Reg Win% × 0.1) + (Playoff Games × Playoff Win% / League Avg Playoff Win% × 0.2) } / Seasons
                </div>
            </div>
        `;
    }
    
    // Finishes by Year (filter out MVPs section and empty entries)
    let yearResults = hof.finishes_by_year?.filter(y => 
        !y.year.includes('MVP') && 
        y.results && 
        y.results.length > 0
    ) || [];
    
    // Sort by year descending (most recent first)
    yearResults = yearResults.sort((a, b) => parseInt(b.year) - parseInt(a.year));
    const mvpSection = hof.finishes_by_year?.find(y => y.year.includes('MVP'));
    
    if (yearResults.length > 0) {
        html += `
            <div class="hof-section" id="hof-seasons">
                <div class="hof-section-title">Season Finishes</div>
                <div class="hof-seasons-list">
                ${yearResults.map(year => {
                    const stats = year.league_stats || {};
                    const champion = year.results?.[0] || 'Unknown';
                    const runnerUp = year.results?.[1] || '';
                    const thirdPlace = year.results?.[2] || '';
                    const toiletBowl = year.results?.find(r => r.includes('Toilet Bowl'));
                    
                    return `
                    <div class="hof-season-card">
                        <div class="hof-season-header">
                            <div class="hof-season-year">${year.year}</div>
                            <div class="hof-season-champion">
                                <span class="champion-crown">👑</span> ${champion}
                            </div>
                        </div>
                        <div class="hof-season-body">
                            <div class="hof-season-podium">
                                ${runnerUp ? `<div class="podium-item"><span class="podium-badge silver">2nd</span> ${runnerUp}</div>` : ''}
                                ${thirdPlace ? `<div class="podium-item"><span class="podium-badge bronze">3rd</span> ${thirdPlace}</div>` : ''}
                            </div>
                            ${stats.avg_ppg ? `
                            <div class="hof-season-stats-detailed">
                                <div class="stat-row">
                                    <span class="stat-label">League Average PPG</span>
                                    <span class="stat-value">${stats.avg_ppg?.toFixed(1) || 'N/A'}</span>
                                </div>
                                <div class="stat-row">
                                    <span class="stat-label">High Score</span>
                                    <span class="stat-value">${stats.highest_score?.toFixed(0)} <span class="stat-context">by ${stats.highest_score_team} (Week ${stats.highest_score_week})</span></span>
                                </div>
                                <div class="stat-row">
                                    <span class="stat-label">Low Score</span>
                                    <span class="stat-value">${stats.lowest_score?.toFixed(0)} <span class="stat-context">by ${stats.lowest_score_team} (Week ${stats.lowest_score_week})</span></span>
                                </div>
                                <div class="stat-row">
                                    <span class="stat-label">Biggest Win</span>
                                    <span class="stat-value">+${stats.biggest_win?.toFixed(0)} <span class="stat-context">${stats.biggest_win_winner} over ${stats.biggest_win_loser} (Week ${stats.biggest_win_week})</span></span>
                                </div>
                                ${stats.rivalry_winner ? `
                                <div class="stat-row rivalry-row">
                                    <span class="stat-label">🏆 Rivalry Week</span>
                                    <span class="stat-value">+${stats.rivalry_margin?.toFixed(0)} <span class="stat-context">${stats.rivalry_winner} over ${stats.rivalry_loser}</span></span>
                                </div>
                                ` : ''}
                            </div>
                            ` : ''}
                            ${toiletBowl ? `<div class="hof-toilet-bowl">${toiletBowl}</div>` : ''}
                        </div>
                    </div>
                    `;
                }).join('')}
                </div>
            </div>
        `;
    }

    html += ownerStatsHtml;
    
    // MVPs (from mvps array or finishes_by_year)
    const mvps = hof.mvps?.length > 0 ? hof.mvps : (mvpSection?.results || []);
    if (mvps.length > 0) {
        html += `
            <div class="hof-section">
                <div class="hof-section-title">League MVPs</div>
                ${mvps.map(mvp => `<div class="record-item">${mvp}</div>`).join('')}
            </div>
        `;
    }
    
    // Team Records
    if (hof.team_records && hof.team_records.length > 0) {
        html += `
            <div class="hof-section" id="hof-team-records">
                <div class="hof-section-title">Team Records</div>
                ${hof.team_records.map(section => `
                    <div class="record-subsection">
                        <div class="record-subsection-title">${section.title}</div>
                        ${section.records.map(r => `<div class="record-item">${r}</div>`).join('')}
                    </div>
                `).join('')}
            </div>
        `;
    }
    
    // Player Records
    if (hof.player_records && hof.player_records.length > 0) {
        html += `
            <div class="hof-section" id="hof-player-records">
                <div class="hof-section-title">Player Records</div>
                ${hof.player_records.map(section => `
                    <div class="record-subsection">
                        <div class="record-subsection-title">${section.title}</div>
                        ${section.records.map(r => `<div class="record-item">${r}</div>`).join('')}
                    </div>
                `).join('')}
            </div>
        `;
    }
    
    // Rivalry Records (Head-to-Head) - Only show official Rivalry Week matchups
    if (hof.rivalry_records && hof.rivalry_records.records && hof.rivalry_records.records.length > 0) {
        const rivalryWeekMatchups = manualHonorsData?.rivalry_week_matchups || [];
        
        const isRivalryWeek = (t1, t2) => {
            return rivalryWeekMatchups.some(([a, b]) => 
                (t1 === a && t2 === b) || (t1 === b && t2 === a)
            );
        };
        
        // Filter to only show official rivalry week matchups
        const rivalries = hof.rivalry_records.records.filter(r => isRivalryWeek(r.team1, r.team2));
        
        if (rivalries.length > 0) {
            html += `
                <div class="hof-section" id="hof-rivalries">
                    <div class="hof-section-title">Rivalry Week Records</div>
                    <div class="table-scroll-wrapper">
                    <table class="rivalry-table">
                        <thead>
                            <tr>
                                <th>Team 1</th>
                                <th>Record</th>
                                <th>Team 2</th>
                                <th>Games</th>
                                <th>Points</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${rivalries.map(r => {
                                const t1Class = r.leader === r.team1 ? 'rivalry-leader' : '';
                                const t2Class = r.leader === r.team2 ? 'rivalry-leader' : '';
                                const recordStr = r.ties > 0 
                                    ? `${r.team1_wins}-${r.team2_wins}-${r.ties}`
                                    : `${r.team1_wins}-${r.team2_wins}`;
                                return `
                                <tr class="rivalry-week-row">
                                    <td class="${t1Class}"><span class="rivalry-week-indicator">★</span> ${r.team1}</td>
                                    <td class="rivalry-record">${recordStr}</td>
                                    <td class="${t2Class}">${r.team2}</td>
                                    <td>${r.games}</td>
                                    <td class="rivalry-points">${r.team1_pf.toFixed(0)} - ${r.team2_pf.toFixed(0)}</td>
                                </tr>
                            `;}).join('')}
                        </tbody>
                    </table>
                    </div>
                </div>
            `;
        }
    }
    
    container.innerHTML = html;
}

let currentTransactionSeason = null;
let transactionSearchQuery = '';
let transactionTypeFilter = 'ALL';
let transactionTeamFilter = new Set(); // empty = all teams
let txSearchDebounceTimer = null;
let txSearchBound = false;

function buildTxSearchText(tx) {
    const getPlayerStr = (p) => typeof p === 'object' ? `${p.position || ''} ${p.name || ''}`.trim() : (p || '');
    const parts = [tx.type || ''];
    if (tx.proposer) { parts.push(tx.proposer); parts.push(tx.proposer_label || teamLabel(tx.proposer)); }
    if (tx.partner)  { parts.push(tx.partner);  parts.push(tx.partner_label || teamLabel(tx.partner)); }
    if (tx.team) {
        parts.push(tx.team);
        const teamObj = data.teams?.find(t => t.abbrev === tx.team);
        if (teamObj) { parts.push(teamLabel(tx.team)); parts.push(teamObj.owner || ''); }
    }
    (tx.proposer_gives?.players  || []).forEach(p => parts.push(getPlayerStr(p)));
    (tx.proposer_gives?.picks    || []).forEach(p => parts.push(p));
    (tx.proposer_receives?.players || []).forEach(p => parts.push(getPlayerStr(p)));
    (tx.proposer_receives?.picks   || []).forEach(p => parts.push(p));
    if (tx.message)   parts.push(tx.message);
    if (tx.added)     parts.push(getPlayerStr(tx.added));
    if (tx.released)  parts.push(getPlayerStr(tx.released));
    if (tx.activated) parts.push(getPlayerStr(tx.activated));
    return parts.join(' ').toLowerCase();
}

function txInvolvesTeam(tx, abbrev) {
    if (abbrev === 'ALL') return true;
    if (tx.proposer === abbrev || tx.partner === abbrev || tx.team === abbrev) return true;

    const legacyTeams = new Set();
    const directLegacyTeam = ownerTeamCode(tx.team);
    if (directLegacyTeam) legacyTeams.add(directLegacyTeam);

    const titleMatch = String(tx.team || '').match(/^Trade between (.+) and (.+)$/i);
    if (titleMatch) {
        titleMatch.slice(1).map(ownerTeamCode).filter(Boolean).forEach(team => legacyTeams.add(team));
    }

    const { cleanMessage } = getTransactionDate(tx);
    const parsedTrade = parseOldTradeMessage(cleanMessage);
    (parsedTrade?.teams || [])
        .map(team => ownerTeamCode(team.name))
        .filter(Boolean)
        .forEach(team => legacyTeams.add(team));
    return legacyTeams.has(abbrev);
}

// Old-style transactions use type: 'transaction' for all moves; infer the structured type from the message.
function getEffectiveTxType(tx) {
    if (tx.type !== 'transaction') return tx.type;
    const msg = (tx.message || '').toLowerCase();
    if (msg.includes('fa pool') || msg.includes('from fa')) return 'fa_activation';
    if (msg.includes('activated') || msg.includes('activate ')) return 'taxi_activation';
    return tx.type;
}

function txMatchesFilters(tx) {
    if (transactionTypeFilter !== 'ALL' && getEffectiveTxType(tx) !== transactionTypeFilter) return false;
    if (transactionTeamFilter.size > 0) {
        const teams = [...transactionTeamFilter];
        // When exactly two teams are selected and we're filtering to trades,
        // look for trades *between* those two teams (both involved) rather than
        // every trade either team made.
        if (transactionTypeFilter === 'trade' && teams.length === 2) {
            if (!teams.every(abbrev => txInvolvesTeam(tx, abbrev))) return false;
        } else if (!teams.some(abbrev => txInvolvesTeam(tx, abbrev))) {
            return false;
        }
    }
    if (transactionSearchQuery && !buildTxSearchText(tx).includes(transactionSearchQuery)) return false;
    return true;
}

function transactionTimelineMoment(tx) {
    const season = Number(tx.season || data.season || 0);
    const parsedWeek = Number.parseInt(tx.week, 10);
    let week = Number.isFinite(parsedWeek) ? parsedWeek : 0;
    const timestamp = tx.timestamp ? new Date(tx.timestamp) : null;
    if (week === 0 && timestamp && !Number.isNaN(timestamp.getTime())
        && timestamp.getFullYear() === season && timestamp.getMonth() === 11) {
        week = 99;
    }
    return season * 100 + week;
}

function stintStartMoment(stint) {
    return Number(stint.start_season) * 100 + Number(stint.start_week);
}

function stintEndMoment(stint) {
    return Number(stint.end_season) * 100 + Number(stint.end_week);
}

function transactionFranchisePerformance(profile, team, tx, direction = 'acquired') {
    const moment = transactionTimelineMoment(tx);
    const stints = (profile?.franchise_stints || [])
        .filter(stint => stintIncludesTeam(stint, team))
        .sort((a, b) => stintStartMoment(a) - stintStartMoment(b));
    let stint = null;
    if (direction === 'departed') {
        stint = stints.filter(candidate => stintStartMoment(candidate) <= moment).at(-1) || null;
    } else {
        stint = stints.find(candidate =>
            stintStartMoment(candidate) <= moment
            && (stintEndMoment(candidate) >= moment || candidate.ongoing)
        ) || stints.find(candidate => stintStartMoment(candidate) >= moment) || null;
    }
    return {
        stint,
        points: stintPointsForTeam(stint, team, direction === 'departed'
            ? { through: moment }
            : { from: moment }),
    };
}

function transactionAssetProfile(item) {
    const label = typeof item === 'object'
        ? `${item.position || ''} ${item.name || ''}`.trim()
        : String(item || '').trim();
    const positionMatch = label.match(/^\s*(QB|RB|WR|RW|TE|K|D\/ST|DEF|HC|OL)\s+/i);
    const position = positionMatch?.[1]?.toUpperCase().replace('RW', 'WR') || '';
    let lookup = label
        .replace(/^\s*(?:QB|RB|WR|RW|TE|K|D\/ST|DEF|HC|OL)\s+/i, '')
        .replace(/\s+\((?:on\s+)?taxi\)\s*$/i, '')
        .replace(/\s+\([A-Z]{2,4}(?:[^)]*)\)?\s*$/i, '')
        .replace(/,+$/, '')
        .trim();
    if (/\s+defen[cs]e$/i.test(lookup)) {
        lookup = lookup.replace(/\s+defen[cs]e$/i, '');
    }
    const profile = getPlayerCareerProfile(lookup, position === 'DEF' ? 'D/ST' : position)
        || getPlayerCareerProfile(lookup);
    return { label, position, profile };
}

function transactionAssetHtml(item, team, tx, direction = 'acquired', action = '') {
    const { label, position, profile } = transactionAssetProfile(item);
    const playerMarkup = profile
        ? playerProfileButton(profile.name, 'transaction-player-link', label, position || profile.position)
        : `<span>${escapeHtml(label)}</span>`;
    const performance = profile && team
        ? transactionFranchisePerformance(profile, team, tx, direction)
        : null;
    const counting = direction === 'acquired' && performance?.stint?.ongoing;
    const performanceMarkup = performance
        ? `<span class="transaction-performance-badge">${performance.points.toLocaleString(undefined, { maximumFractionDigits: 0 })} pts for ${escapeHtml(team)}${counting ? ' · counting' : ''}</span>`
        : '';
    return `
        <div class="transaction-asset-row">
            <span class="transaction-asset-main">${action ? `<span class="transaction-action">${escapeHtml(action)}</span>` : '<span aria-hidden="true">•</span>'}${playerMarkup}</span>
            ${performanceMarkup}
        </div>
    `;
}

function parseTransactionRosterMoves(tx, cleanMessage) {
    const moves = [];
    const addMove = (action, item, direction) => {
        const value = String(item || '').replace(/,+$/, '').trim();
        if (!value || moves.some(move => move.action === action && move.item === value)) return;
        moves.push({ action, item: value, direction });
    };
    if (tx.added) addMove('Added', tx.added, 'acquired');
    if (tx.activated) addMove('Activated', tx.activated, 'acquired');
    if (tx.released) addMove('Released', tx.released, 'departed');
    if (moves.length) return moves;

    const normalized = String(cleanMessage || '')
        .replace(/,\s+(?=(?:add(?:ed)?|activat(?:ed)?|releas(?:ed)?|drop(?:ped)?)\b)/gi, '|')
        .replace(/\s+and\s+(?=(?:add(?:ed)?|activat(?:ed)?|releas(?:ed)?|drop(?:ped)?)\b)/gi, '|');
    normalized.split('|').forEach(segment => {
        const match = segment.trim().match(/\b(add(?:ed)?|activat(?:ed)?|releas(?:ed)?|drop(?:ped)?)\s+(.+)$/i);
        if (!match) return;
        const verb = match[1].toLowerCase();
        const direction = /releas|drop/.test(verb) ? 'departed' : 'acquired';
        const action = /activat/.test(verb) ? 'Activated' : (direction === 'departed' ? 'Released' : 'Added');
        const item = match[2].replace(/\s+from FA Pool.*$/i, '').trim();
        addMove(action, item, direction);
    });
    return moves;
}

function transactionCorrespondingMoveHtml(move, tx) {
    const ownerMatch = String(move || '').match(/^(.+?)\s+(?=add(?:ed)?|activat(?:ed)?|releas(?:ed)?|drop(?:ped)?)/i);
    const team = ownerMatch
        ? draftOwnerTeamCode(ownerMatch[1], { year: Number(tx.season) })
        : null;
    const moves = parseTransactionRosterMoves({}, move);
    if (!moves.length) {
        return `<div class="transaction-asset-row"><span class="transaction-asset-main"><span aria-hidden="true">•</span><span>${escapeHtml(move)}</span></span></div>`;
    }
    return moves.map(parsed =>
        transactionAssetHtml(parsed.item, team, tx, parsed.direction, parsed.action)
    ).join('');
}

function renderTransactionItem(tx) {
    const { dateStr, cleanMessage } = getTransactionDate(tx);
    const isNewTrade = tx.type === 'trade' && tx.proposer && tx.partner;
    const isOldTrade = tx.team && tx.team.toLowerCase().includes('trade');
    const dateSpan = dateStr ? `<span style="float: right; font-size: 0.85rem; color: var(--text-muted); font-family: 'JetBrains Mono', monospace;">${dateStr}</span>` : '';
    if (isNewTrade) {
        // Prefer the point-in-time label stamped by the exporter (name-battle
        // changeover); fall back to the current owner's first name.
        const a = normalizeCoOwnerLabel(tx.proposer_label || teamLabel(tx.proposer));
        const b = normalizeCoOwnerLabel(tx.partner_label || teamLabel(tx.partner));
        const title = formatTradeTitle(a, b);
        const gives = tx.proposer_gives || {};
        const receives = tx.proposer_receives || {};
        const givesItems = [...(gives.players || []), ...(gives.picks || [])];
        const receivesItems = [...(receives.players || []), ...(receives.picks || [])];
        return `
            <div class="transaction-item">
                <div class="transaction-title">
                    ${title}${dateSpan}
                </div>
                <div class="transaction-details" style="line-height: 1.8;">
                    <div style="margin-top: 0.5rem;"><strong>${a} receives:</strong></div>
                    ${receivesItems.length ? receivesItems.map(item => transactionAssetHtml(item, tx.proposer, tx)).join('') : '<div style="margin-left: 1.5rem; color: var(--text-muted);">nothing</div>'}
                    <div style="margin-top: 0.75rem;"><strong>${b} receives:</strong></div>
                    ${givesItems.length ? givesItems.map(item => transactionAssetHtml(item, tx.partner, tx)).join('') : '<div style="margin-left: 1.5rem; color: var(--text-muted);">nothing</div>'}
                </div>
            </div>`;
    } else if (isOldTrade) {
        const parsed = parseOldTradeMessage(cleanMessage);
        if (parsed && parsed.teams.length >= 2) {
            const title = normalizeCoOwnerLabel(tx.team)
                || formatTradeTitle(parsed.teams[0].name, parsed.teams[1].name);
            let detailsHtml = '';
            for (const team of parsed.teams) {
                const teamCode = draftOwnerTeamCode(team.name, { year: Number(tx.season) });
                detailsHtml += `<div style="margin-top: 0.5rem;"><strong>${team.name} receives:</strong></div>`;
                detailsHtml += team.items.length
                    ? team.items.map(item => transactionAssetHtml(item, teamCode, tx)).join('')
                    : '<div style="margin-left: 1.5rem; color: var(--text-muted);">nothing</div>';
            }
            if (parsed.correspondingMoves.length) {
                detailsHtml += `<div style="margin-top: 0.75rem;"><strong>Corresponding moves:</strong></div>`;
                detailsHtml += parsed.correspondingMoves.map(move => transactionCorrespondingMoveHtml(move, tx)).join('');
            }
            return `
                <div class="transaction-item">
                    <div class="transaction-title">${title}${dateSpan}</div>
                    <div class="transaction-details" style="line-height: 1.8;">${detailsHtml}</div>
                </div>`;
        } else {
            return `
                <div class="transaction-item">
                    <div class="transaction-title">${normalizeCoOwnerLabel(tx.team)}${dateSpan}</div>
                    <div class="transaction-details"><div class="transaction-subheader">${cleanMessage || formatTransactionMessage(tx)}</div></div>
                </div>`;
        }
    } else {
        const teamName = data.teams?.find(t => t.abbrev === tx.team)?.name || normalizeCoOwnerLabel(tx.team);
        const teamCode = tx.team && data.teams?.some(team => team.abbrev === tx.team)
            ? tx.team
            : draftOwnerTeamCode(tx.team, { year: Number(tx.season) });
        const moves = parseTransactionRosterMoves(tx, cleanMessage);
        return `
            <div class="transaction-item">
                <div class="transaction-title">${teamName}${dateSpan}</div>
                <div class="transaction-details">${moves.length
                    ? moves.map(move => transactionAssetHtml(move.item, teamCode, tx, move.direction, move.action)).join('')
                    : `<div class="transaction-subheader">${escapeHtml(cleanMessage || formatTransactionMessage(tx))}</div>`
                }</div>
            </div>`;
    }
}

function clearTransactionFilters() {
    transactionSearchQuery = '';
    transactionTypeFilter = 'ALL';
    transactionTeamFilter = new Set();
    const searchInput = document.getElementById('transactions-search');
    if (searchInput) searchInput.value = '';
}

function syncTransactionRoute() {
    if (parseHashRoute().view !== 'transactions') return;
    const isFiltered = Boolean(
        transactionSearchQuery || transactionTypeFilter !== 'ALL' || transactionTeamFilter.size
    );
    replaceRouteParams({
        season: isFiltered ? null : currentTransactionSeason,
        q: transactionSearchQuery || null,
        type: transactionTypeFilter === 'ALL' ? null : transactionTypeFilter,
        teams: transactionTeamFilter.size ? [...transactionTeamFilter].sort().join(',') : null,
    });
}

function renderTransactions() {
    if (!data.transactions || data.transactions.length === 0) {
        document.getElementById('transactions-container').innerHTML = emptyStateHtml(
            'No transactions available',
            'The current season may have newer league activity.',
            currentSeason === LIVE_SEASON ? [] : [{ label: 'Return to current season', action: 'current-season' }]
        );
        return;
    }

    const selectorContainer = document.getElementById('transactions-season-selector');
    const container = document.getElementById('transactions-container');
    const typeFiltersEl = document.getElementById('transactions-type-filters');
    const teamFiltersEl = document.getElementById('transactions-team-filters');

    // Group all transactions by season
    const bySeason = {};
    data.transactions.forEach(tx => {
        const season = tx.season || data.season || 2025;
        if (!bySeason[season]) bySeason[season] = [];
        bySeason[season].push(tx);
    });
    const seasons = Object.keys(bySeason).sort((a, b) => parseInt(b) - parseInt(a));
    if (currentTransactionSeason === null) {
        currentTransactionSeason = parseInt(seasons[0]) || data.season || 2025;
    }

    const isFiltered = !!(transactionSearchQuery || transactionTypeFilter !== 'ALL' || transactionTeamFilter.size > 0);
    const searchInput = document.getElementById('transactions-search');
    if (searchInput) searchInput.value = transactionSearchQuery;
    syncTransactionRoute();

    // Season selector (dimmed when a search/filter is active)
    selectorContainer.innerHTML = seasons.map(season => `
        <button class="season-btn ${!isFiltered && parseInt(season) === currentTransactionSeason ? 'active' : ''} ${isFiltered ? 'dimmed' : ''}"
                aria-pressed="${!isFiltered && parseInt(season) === currentTransactionSeason}"
                data-season="${season}">${season}</button>
    `).join('');
    selectorContainer.querySelectorAll('.season-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            currentTransactionSeason = parseInt(btn.dataset.season);
            clearTransactionFilters();
            renderTransactions();
        });
    });

    // Type filter chips
    const typeOptions = [
        { key: 'ALL', label: 'All Types' },
        { key: 'trade', label: 'Trades' },
        { key: 'fa_activation', label: 'Free Agents' },
        { key: 'taxi_activation', label: 'Taxi' },
    ];
    if (typeFiltersEl) {
        typeFiltersEl.innerHTML = typeOptions.map(t => `
            <button class="filter-chip ${transactionTypeFilter === t.key ? 'active' : ''}"
                    aria-pressed="${transactionTypeFilter === t.key}" data-type="${t.key}">${t.label}</button>
        `).join('');
        typeFiltersEl.querySelectorAll('.filter-chip').forEach(btn => {
            btn.addEventListener('click', () => {
                transactionTypeFilter = btn.dataset.type;
                renderTransactions();
            });
        });
    }

    // Team filter chips
    const teams = data.teams || [];
    if (teamFiltersEl) {
        teamFiltersEl.innerHTML = [
            `<button class="filter-chip ${transactionTeamFilter.size === 0 ? 'active' : ''}" aria-pressed="${transactionTeamFilter.size === 0}" data-team="ALL">All Teams</button>`,
            ...teams.map(t => `<button class="filter-chip ${transactionTeamFilter.has(t.abbrev) ? 'active' : ''}" aria-pressed="${transactionTeamFilter.has(t.abbrev)}" data-team="${t.abbrev}">${teamLabel(t.abbrev)}</button>`)
        ].join('');
        teamFiltersEl.querySelectorAll('.filter-chip').forEach(btn => {
            btn.addEventListener('click', () => {
                const team = btn.dataset.team;
                if (team === 'ALL') {
                    transactionTeamFilter = new Set();
                } else if (transactionTeamFilter.has(team)) {
                    transactionTeamFilter.delete(team);
                } else {
                    transactionTeamFilter.add(team);
                }
                renderTransactions();
            });
        });
    }

    // Bind search input once (the element persists in the DOM)
    if (!txSearchBound) {
        const searchInput = document.getElementById('transactions-search');
        if (searchInput) {
            searchInput.addEventListener('input', (e) => {
                clearTimeout(txSearchDebounceTimer);
                txSearchDebounceTimer = setTimeout(() => {
                    transactionSearchQuery = e.target.value.trim().toLowerCase();
                    renderTransactions();
                    // Restore focus after re-render
                    const el = document.getElementById('transactions-search');
                    if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); }
                }, 150);
            });
            txSearchBound = true;
        }
    }

    // Render results
    if (isFiltered) {
        const matched = data.transactions.filter(txMatchesFilters);
        if (matched.length === 0) {
            container.innerHTML = emptyStateHtml(
                'No transactions match',
                'Remove the active search and filters to see the full history.',
                [{ label: 'Clear filters', action: 'clear-transaction-filters' }]
            );
            return;
        }
        // Group by season then week
        const bySeasonAll = {};
        matched.forEach(tx => {
            const season = tx.season || data.season || 2025;
            const week = tx.week !== undefined ? tx.week : 0;
            if (!bySeasonAll[season]) bySeasonAll[season] = {};
            if (!bySeasonAll[season][week]) bySeasonAll[season][week] = [];
            bySeasonAll[season][week].push(tx);
        });
        const sortedSeasons = Object.keys(bySeasonAll).sort((a, b) => parseInt(b) - parseInt(a));
        container.innerHTML = `
            <p class="results-summary">${matched.length} ${matched.length === 1 ? 'transaction' : 'transactions'} found</p>
            ${sortedSeasons.map(season => `
            <div>
                <div class="transactions-season-header">${season}</div>
                ${Object.keys(bySeasonAll[season])
                    .sort((a, b) => {
                        const na = isNaN(parseInt(a)) ? -1 : parseInt(a);
                        const nb = isNaN(parseInt(b)) ? -1 : parseInt(b);
                        return nb - na;
                    })
                    .map(week => `
                        <div class="transactions-week">
                            <div class="transactions-week-header">${isNaN(parseInt(week)) ? week : `Week ${week}`}</div>
                            ${bySeasonAll[season][week].map(tx => renderTransactionItem(tx)).join('')}
                        </div>
                    `).join('')}
            </div>
            `).join('')}`;
    } else {
        // Single selected season
        const seasonTxns = bySeason[currentTransactionSeason] || [];
        const byWeek = {};
        seasonTxns.forEach(tx => {
            const week = tx.week !== undefined ? tx.week : 0;
            if (!byWeek[week]) byWeek[week] = [];
            byWeek[week].push(tx);
        });
        const sortedWeeks = Object.keys(byWeek).sort((a, b) => {
            const na = isNaN(parseInt(a)) ? -1 : parseInt(a);
            const nb = isNaN(parseInt(b)) ? -1 : parseInt(b);
            return nb - na;
        });
        container.innerHTML = `
            <p class="results-summary">${seasonTxns.length} ${seasonTxns.length === 1 ? 'transaction' : 'transactions'} in ${currentTransactionSeason}</p>
            <div class="transactions-season">
                ${sortedWeeks.map(week => `
                    <div class="transactions-week">
                        <div class="transactions-week-header">${isNaN(parseInt(week)) ? week : `Week ${week}`}</div>
                        ${byWeek[week].map(tx => renderTransactionItem(tx)).join('')}
                    </div>
                `).join('')}
            </div>
        `;
    }
}

// Drafts
let currentDraft = 0;

function draftYear(draft) {
    if (Number.isInteger(draft?.year)) return draft.year;
    const yearMatch = String(draft?.name || '').match(/\b(20\d{2})\b/);
    return yearMatch ? parseInt(yearMatch[1], 10) : 2020;
}

function draftOwnerTeamCode(rawOwner, draft) {
    const owner = String(rawOwner || '').trim();
    const ownerKey = normalizeCoOwnerLabel(owner).toLowerCase().replace(/\s+/g, ' ');
    const year = draftYear(draft);
    if (['bocki', 'diana', 'ryan przybocki'].includes(ownerKey)) return 'RCP';
    if (['miles', 'miles agus'].includes(ownerKey)) return 'MPA';
    if (ownerKey === 'ryan' && year <= 2021) return 'RCP';
    if (['joe w', 'joe w.'].includes(ownerKey)) return 'JRW';
    if (['joe k', 'joe k.'].includes(ownerKey)) return 'JDK';
    if (ownerKey === 'joe kuhl' && year <= 2023) return 'JDK';
    if (ownerKey === 'joe') {
        if (year <= 2022) return 'JRW';
        if (year === 2023) return 'JDK';
    }
    if (ownerKey === 'censored ward') return year >= 2024 ? 'J/J' : 'JRW';
    if (ownerKey === 'joe censored') return year === 2023 ? 'JDK' : 'J/J';
    if (ownerKey === 'censored' && year <= 2023) return year >= 2022 ? 'JRW' : 'RCP';
    if (ownerKey === 'redacted' && year <= 2023) return 'CGK';
    return ownerTeamCode(owner);
}

function draftOwnerDisplayLabel(rawOwner, draft) {
    const owner = String(rawOwner || '').trim();
    const code = draftOwnerTeamCode(owner, draft);
    if (!code) return normalizeCoOwnerLabel(owner);
    const ownerKey = owner.toLowerCase();
    if (code === 'CGK') return `${ownerKey.startsWith('redacted') ? 'Redacted' : 'Connor'} (CGK)`;
    if (code === 'CWR') return `${ownerKey.startsWith('redacted') ? 'Redacted' : 'Connor'} (CWR)`;
    return `${owner} (${code})`;
}

function draftTeamParts(rawTeam) {
    const raw = String(rawTeam || '').trim();
    const viaMatch = raw.match(/^(.*?)\s*\(\s*(?:via|vía)\s+(.+?)\)\s*\)?$/i);
    if (!viaMatch) return { owner: raw, via: [] };
    const viaTokens = viaMatch[2].split('/').map(value => value.trim()).filter(Boolean);
    const via = [];
    for (let index = 0; index < viaTokens.length; index += 1) {
        const coOwnerPair = viaTokens.slice(index, index + 2).join('/');
        if (index + 1 < viaTokens.length && OWNER_TEAM_CODES[coOwnerPair.toLowerCase()]) {
            via.push(coOwnerPair);
            index += 1;
        } else {
            via.push(viaTokens[index]);
        }
    }
    return { owner: viaMatch[1].trim(), via: via.filter(Boolean) };
}

function draftTeamCode(rawTeam, draft) {
    return draftOwnerTeamCode(draftTeamParts(rawTeam).owner, draft);
}

function draftTeamDisplayLabel(rawTeam, draft) {
    const { owner, via } = draftTeamParts(rawTeam);
    const ownerLabel = draftOwnerDisplayLabel(owner, draft);
    if (!via.length) return ownerLabel;
    return `${ownerLabel} · via ${via.map(value => draftOwnerDisplayLabel(value, draft)).join(' / ')}`;
}

function franchiseCodesForStintTeam(team) {
    if (team === 'CGK/SRY') return ['CGK', 'S/T'];
    if (team === 'CWR/SLS') return ['CWR', 'SLS'];
    return [team];
}

function stintIncludesTeam(stint, team) {
    return Boolean(team && (stint?.teams || []).includes(team));
}

function stintPointsForTeam(stint, team, { from = null, through = null } = {}) {
    if (!stint || !team) return 0;
    return (stint.weekly_points || []).reduce((total, entry) => {
        const [season, week, points, scoredFor = team] = entry;
        const moment = Number(season) * 100 + Number(week);
        if (!franchiseCodesForStintTeam(scoredFor).includes(team)) return total;
        if (from !== null && moment < from) return total;
        if (through !== null && moment > through) return total;
        return total + Number(points || 0);
    }, 0);
}

function draftPerformanceMoment(draft) {
    if (draft?.name === 'Founding Draft') return null;
    const firstScoringWeek = /Midseason Draft/i.test(draft?.name || '') ? 8 : 1;
    return draftYear(draft) * 100 + firstScoringWeek;
}

function draftPickFranchisePerformance(profile, draft, team) {
    const stints = (profile?.franchise_stints || []).filter(stint => stintIncludesTeam(stint, team));
    const from = draftPerformanceMoment(draft);
    const candidates = from === null
        ? stints
        : stints.filter(stint => stintEndMoment(stint) >= from);
    const stint = candidates.sort((a, b) =>
        (Number(a.start_season) * 100 + Number(a.start_week))
        - (Number(b.start_season) * 100 + Number(b.start_week))
    )[0] || null;
    return {
        stint,
        points: stintPointsForTeam(stint, team, { from }),
    };
}

function draftRoundHeading(round) {
    const value = String(round?.round || '').trim();
    if (/^(taxi|expansion|free agent)/i.test(value)) return value;
    const numeric = Number.parseFloat(value);
    return `Round ${Number.isInteger(numeric) ? numeric : value}`;
}

function renderDraftPerformanceSummary(draft) {
    const draftedPlayers = new Map();
    const draftPosition = /OL Expansion Draft/i.test(draft.name || '') ? 'OL' : '';
    for (const round of (draft.rounds || [])) {
        for (const pick of (round.picks || [])) {
            const profile = getPlayerCareerProfile(pick.player, pick.position || draftPosition);
            const team = draftTeamCode(pick.team, draft);
            if (!profile || !team) continue;
            draftedPlayers.set(`${profile.profile_key}:${team}`, {
                profile,
                team,
                performance: draftPickFranchisePerformance(profile, draft, team),
            });
        }
    }
    const profiles = [...draftedPlayers.values()];
    const totalPoints = profiles.reduce((sum, entry) => sum + entry.performance.points, 0);
    const rostered = profiles.filter(entry => getLivePlayerStatus(entry.profile).owner).length;
    const rosteredPct = profiles.length > 0 ? Math.round((rostered / profiles.length) * 100) : 0;
    const topPlayer = profiles
        .filter(entry => entry.performance.points > 0)
        .sort((a, b) => b.performance.points - a.performance.points)[0];

    return `
        <section class="draft-performance-summary" aria-label="Draft class performance">
            <div class="draft-performance-heading">
                <div>
                    <h3>Draft Class Performance</h3>
                    <p>Production for the franchise that made each pick. Later reacquisitions count separately.</p>
                </div>
            </div>
            <div class="draft-performance-metrics">
                <div class="draft-performance-metric">
                    <strong>${totalPoints.toLocaleString(undefined, { maximumFractionDigits: 0 })}</strong>
                    <span>Points for drafting teams</span>
                </div>
                <div class="draft-performance-metric">
                    <strong>${rostered}/${profiles.length} (${rosteredPct}%)</strong>
                    <span>Currently rostered</span>
                </div>
                <div class="draft-performance-metric draft-performance-top">
                    ${topPlayer ? `
                        ${playerProfileButton(topPlayer.profile.name, 'draft-summary-player', null, topPlayer.profile.position)}
                        <span>Top pick · ${topPlayer.performance.points.toLocaleString(undefined, { maximumFractionDigits: 0 })} pts for ${escapeHtml(topPlayer.team)}</span>
                    ` : '<strong>—</strong><span>Top performer</span>'}
                </div>
            </div>
        </section>
    `;
}

function renderHistoricalDraftPick(pick, draft) {
    const isPass = pick.player === 'PASS' || !pick.player;
    if (isPass) {
        return `
            <div class="draft-pick">
                <div class="pick-number">${escapeHtml(pick.pick)}</div>
                <div class="pick-details">
                    <div class="pick-team">${escapeHtml(draftTeamDisplayLabel(pick.team, draft))}</div>
                    <div class="pick-player pick-pass">PASS</div>
                </div>
            </div>
        `;
    }

    const draftPosition = pick.position || (/OL Expansion Draft/i.test(draft.name || '') ? 'OL' : '');
    const profile = getPlayerCareerProfile(pick.player, draftPosition);
    const seasonStats = profile?.seasons?.[String(draftYear(draft))];
    const status = profile ? getLivePlayerStatus(profile) : { owner: null, label: 'Not rostered' };
    const originalOwner = draftTeamCode(pick.team, draft) || seasonStats?.owners?.[0] || null;
    const ownershipState = status.owner
        ? (originalOwner && originalOwner === status.owner
            ? { label: 'Original team', tone: 'original' }
            : { label: `Now ${status.owner}`, tone: 'moved' })
        : { label: status.label, tone: 'unrostered' };
    const performance = profile
        ? draftPickFranchisePerformance(profile, draft, originalOwner)
        : { stint: null, points: 0 };
    const rankLabel = seasonStats?.position_rank && seasonStats?.position
        ? `${seasonStats.position}${seasonStats.position_rank} in ${draftYear(draft)}`
        : null;

    return `
        <div class="draft-pick ${profile ? 'has-performance' : ''}">
            <div class="pick-number">${escapeHtml(pick.pick)}</div>
            <div class="pick-details">
                <div class="pick-team">${escapeHtml(draftTeamDisplayLabel(pick.team, draft))}</div>
                ${playerProfileButton(profile?.name || cleanPlayerProfileLabel(pick.player), 'pick-player draft-player-link', pick.player, draftPosition || profile?.position)}
                ${profile ? `
                    <div class="draft-pick-performance">
                        <span>${performance.points.toLocaleString(undefined, { maximumFractionDigits: 0 })} pts for ${escapeHtml(originalOwner || 'drafting team')}</span>
                        ${rankLabel ? `<span>${escapeHtml(rankLabel)}</span>` : ''}
                        <span class="draft-owner-state ${ownershipState.tone}">${escapeHtml(ownershipState.label)}</span>
                    </div>
                ` : '<div class="draft-pick-performance"><span>No QPFL scoring yet</span></div>'}
                ${pick.dropped && pick.dropped !== '-'
                    ? `<div class="pick-dropped">Dropped: <span>${escapeHtml(pick.dropped)}</span></div>`
                    : ''
                }
                ${pick.first_add_rights
                    ? `<div class="pick-dropped">First-add rights: <span>${escapeHtml(pick.first_add_rights)}</span></div>`
                    : ''
                }
            </div>
        </div>
    `;
}

function renderDrafts() {
    // Combine upcoming drafts with historical drafts
    const upcomingDrafts = data.upcoming_drafts || [];
    const historicalDrafts = data.drafts || [];
    const allDrafts = [...upcomingDrafts, ...historicalDrafts];

    if (allDrafts.length === 0) {
        document.getElementById('drafts-container').innerHTML = emptyStateHtml(
            'No drafts available',
            'Return to the live season or explore another league section.',
            currentSeason === LIVE_SEASON
                ? [{ label: 'View all rosters', route: '#teams/all-rosters' }]
                : [{ label: 'Return to current season', action: 'current-season' }]
        );
        return;
    }

    const requestedDraft = activeRouteParams.get('draft');
    if (requestedDraft) {
        const requestedIndex = allDrafts.findIndex(draft => draft.name === requestedDraft);
        if (requestedIndex >= 0) currentDraft = requestedIndex;
    }
    if (currentDraft >= allDrafts.length) currentDraft = 0;
    if (parseHashRoute().view === 'drafts') {
        replaceRouteParams({ draft: allDrafts[currentDraft]?.name || null });
    }

    // Render draft tabs
    const tabsContainer = document.getElementById('drafts-tabs');
    tabsContainer.innerHTML = allDrafts.map((draft, idx) => `
        <button class="season-btn ${idx === currentDraft ? 'active' : ''}" id="draft-${idx}-tab"
                role="tab" aria-selected="${idx === currentDraft}" aria-controls="drafts-container"
                tabindex="${idx === currentDraft ? '0' : '-1'}"
                data-draft="${idx}">${escapeHtml(draft.name)}</button>
    `).join('');

    document.getElementById('drafts-container')?.setAttribute(
        'aria-labelledby', `draft-${currentDraft}-tab`
    );

    // Add click handlers
    tabsContainer.querySelectorAll('.season-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            currentDraft = parseInt(btn.dataset.draft);
            replaceRouteParams({ draft: allDrafts[currentDraft]?.name || null });
            renderDrafts();
        });
    });

    // Render selected draft
    const draft = allDrafts[currentDraft];
    const container = document.getElementById('drafts-container');
    const isUpcoming = currentDraft < upcomingDrafts.length;
    
    if (!draft.rounds || draft.rounds.length === 0) {
        container.innerHTML = emptyStateHtml(
            'No picks recorded for this draft',
            'Choose another draft above to review its selections.',
            [{ label: 'View all rosters', route: '#teams/all-rosters' }]
        );
        return;
    }

    container.innerHTML = `
        <div class="drafts-season">
            ${isUpcoming ? '' : renderDraftPerformanceSummary(draft)}
            ${draft.rounds.map(round => `
                <div class="draft-round">
                    <div class="draft-round-header">${escapeHtml(draftRoundHeading(round))}</div>
                    <div class="draft-picks-grid">
                        ${round.picks.map(pick => {
                            if (isUpcoming) {
                                // For upcoming drafts, show pick order with current owner
                                const pickNum = pick.pick_number || `${round.round}.${pick.pick || '??'}`;
                                const isTraded = pick.original_team !== pick.current_owner;
                                const fromLabel = isTraded ? ` <span style="color: var(--text-muted); font-size: 0.9em;">(${pick.original_team})</span>` : '';
                                return `
                                    <div class="draft-pick">
                                        <div class="pick-number">${pickNum}</div>
                                        <div class="pick-details">
                                            <div class="pick-team">${pick.current_owner}${fromLabel}</div>
                                        </div>
                                    </div>
                                `;
                            } else {
                                return renderHistoricalDraftPick(pick, draft);
                            }
                        }).join('')}
                    </div>
                </div>
            `).join('')}
        </div>
    `;
}

// Compare Teams View
let compareTeam1 = '';
let compareTeam2 = '';

function initCompareView() {
    const select1 = document.getElementById('compare-team-1');
    const select2 = document.getElementById('compare-team-2');
    
    // Get all teams from standings or teams data
    let teams = data.standings || data.teams || [];
    if (!teams.length) return;
    
    // Populate select dropdowns
    const options = teams.map(t => 
        `<option value="${t.abbrev}">${t.name || t.abbrev}</option>`
    ).join('');
    
    select1.innerHTML = '<option value="">Select Team 1</option>' + options;
    select2.innerHTML = '<option value="">Select Team 2</option>' + options;
    
    // Restore previous selections if valid
    if (compareTeam1 && teams.find(t => t.abbrev === compareTeam1)) {
        select1.value = compareTeam1;
    }
    if (compareTeam2 && teams.find(t => t.abbrev === compareTeam2)) {
        select2.value = compareTeam2;
    }
    replaceRouteParams({ team1: compareTeam1 || null, team2: compareTeam2 || null });
    
    // Add change handlers
    select1.onchange = () => {
        compareTeam1 = select1.value;
        replaceRouteParams({ team1: compareTeam1 || null, team2: compareTeam2 || null });
        renderCompareView();
    };
    select2.onchange = () => {
        compareTeam2 = select2.value;
        replaceRouteParams({ team1: compareTeam1 || null, team2: compareTeam2 || null });
        renderCompareView();
    };
    
    renderCompareView();
}

function getTeamTotalPoints(teamAbbrev) {
    // Get all weeks with scores and calculate total points from matchups
    const weeksWithScores = (data.weeks || []).filter(w => w.has_scores);
    let total = 0;
    
    weeksWithScores.forEach(week => {
        for (const matchup of week.matchups) {
            if (matchup.team1.abbrev === teamAbbrev) {
                total += matchup.team1.total_score || 0;
            } else if (matchup.team2.abbrev === teamAbbrev) {
                total += matchup.team2.total_score || 0;
            }
        }
    });
    
    return total;
}

function getPlayerSeasonPoints(playerName, teamAbbrev) {
    // Get total points scored by a player while on a specific team
    const weeksWithScores = (data.weeks || []).filter(w => w.has_scores);
    let total = 0;
    
    weeksWithScores.forEach(week => {
        for (const matchup of week.matchups) {
            let teamData = null;
            if (matchup.team1.abbrev === teamAbbrev) teamData = matchup.team1;
            else if (matchup.team2.abbrev === teamAbbrev) teamData = matchup.team2;
            
            if (teamData && teamData.roster) {
                const player = teamData.roster.find(p => p.name === playerName);
                if (player && player.score) {
                    total += player.score;
                }
            }
        }
    });
    
    return total;
}

function renderCompareView() {
    const container = document.getElementById('compare-content');
    
    if (!compareTeam1 || !compareTeam2) {
        container.innerHTML = `
            <div class="compare-empty">
                <p>Select two teams above to compare their rosters</p>
            </div>
        `;
        return;
    }
    
    // Get team info
    const teams = data.standings || data.teams || [];
    const team1Info = teams.find(t => t.abbrev === compareTeam1);
    const team2Info = teams.find(t => t.abbrev === compareTeam2);
    
    if (!team1Info || !team2Info) {
        container.innerHTML = '<div class="compare-empty"><p>Unable to load team data</p></div>';
        return;
    }
    
    const team1 = buildCompareTeam(compareTeam1, team1Info);
    const team2 = buildCompareTeam(compareTeam2, team2Info);
    const sides = [team1, team2];

    let html = `
        <div class="compare-grid">
            <div class="compare-grid-header">
                ${sides.map(t => `
                    <div class="compare-team-card">
                        ${teamProfileButton(t.abbrev, t.name, 'compare-team-name')}
                        <span class="compare-team-total">${t.total.toFixed(1)} pts</span>
                    </div>
                `).join('')}
            </div>
    `;

    // Position groups, aligned across both teams
    ROSTER_POSITION_ORDER.forEach(pos => {
        if (!team1.byPosition[pos]?.length && !team2.byPosition[pos]?.length) return;

        html += `
            <div class="compare-section">
                <div class="compare-section-title">${pos}</div>
                <div class="compare-section-cols">
                    ${sides.map(t => {
                        const players = t.byPosition[pos] || [];
                        const posTotal = players.reduce((sum, p) => sum + p.totalPoints, 0);
                        return `
                            <div class="compare-cell">
                                ${players.map(player => renderComparePlayer(player, player.totalPoints.toFixed(1))).join('')
                                  || '<div class="compare-cell-empty">—</div>'}
                                <div class="compare-position-total">
                                    <span class="compare-position-total-label">Total</span>
                                    <span class="compare-position-total-value">${posTotal.toFixed(1)}</span>
                                </div>
                            </div>
                        `;
                    }).join('')}
                </div>
            </div>
        `;
    });

    // Taxi squads
    if (team1.taxiPlayers.length || team2.taxiPlayers.length) {
        html += `
            <div class="compare-section">
                <div class="compare-section-title">Taxi Squad</div>
                <div class="compare-section-cols">
                    ${sides.map(t => `
                        <div class="compare-cell">
                            ${t.taxiPlayers.map(player => renderComparePlayer(player, '-', 'taxi')).join('')
                              || '<div class="compare-cell-empty">—</div>'}
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    // Draft picks
    if (team1.picks.length || team2.picks.length) {
        html += `
            <div class="compare-section">
                <div class="compare-section-title">Draft Picks</div>
                <div class="compare-section-cols">
                    ${sides.map(t => `
                        <div class="compare-cell">
                            ${renderComparePicks(t.picks, t.abbrev) || '<div class="compare-cell-empty">—</div>'}
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    html += '</div>';
    container.innerHTML = html;
}

function renderComparePlayer(player, points, extraClass = '') {
    return `
        <div class="compare-player ${extraClass}">
            <div class="compare-player-info">
                <span class="compare-player-position">${player.position}</span>
                ${playerProfileButton(player.name, 'compare-player-name', null, player.position)}
                <span class="compare-player-nfl">${escapeHtml(player.nfl_team || '')}</span>
            </div>
            <span class="compare-player-points">${points}</span>
        </div>
    `;
}

function renderComparePicks(teamPicks, teamAbbrev) {
    if (!teamPicks.length) return '';

    // Define draft types in display order
    const draftTypes = [
        { key: 'offseason', label: 'Main Draft' },
        { key: 'offseason_taxi', label: 'Taxi Draft' },
        { key: 'waiver', label: 'Waiver Draft' },
        { key: 'waiver_taxi', label: 'Waiver Taxi Draft' }
    ];

    // Group picks by year
    const picksByYear = {};
    teamPicks.forEach(pick => {
        if (!picksByYear[pick.year]) picksByYear[pick.year] = [];
        picksByYear[pick.year].push(pick);
    });

    const years = Object.keys(picksByYear).sort();

    return `
        <div class="compare-picks-grid">
            ${years.map(year => {
                const yearPicks = picksByYear[year];
                return `
                    <div class="compare-picks-year">
                        <div class="compare-picks-year-header">${year}</div>
                        ${draftTypes.map(dt => {
                            const typePicks = yearPicks
                                .filter(p => p.draft_type === dt.key)
                                .sort((a, b) => a.round - b.round);
                            if (typePicks.length === 0) return '';
                            return `
                                <div class="compare-picks-type">
                                    <div class="compare-picks-type-label">${dt.label}</div>
                                    <div class="compare-picks-list">
                                        ${typePicks.map(pick => {
                                            const isOwn = pick.original_team === teamAbbrev;
                                            const pickClass = isOwn ? 'own' : 'acquired';
                                            const fromLabel = !isOwn ? `<span class="compare-pick-from"> (${pick.original_team})</span>` : '';
                                            return `<span class="compare-pick-item ${pickClass}">R${pick.round}${fromLabel}</span>`;
                                        }).join('')}
                                    </div>
                                </div>
                            `;
                        }).join('')}
                    </div>
                `;
            }).join('')}
        </div>
    `;
}

function buildCompareTeam(teamAbbrev, teamInfo) {
    const teamName = teamInfo.name || teamAbbrev;
    const teamTotal = getTeamTotalPoints(teamAbbrev);
    
    // Get roster - for current season use data.rosters, for historical build from matchups
    let activePlayers = [];
    let taxiPlayers = [];
    
    const isHistorical = data.is_historical || data.season !== LIVE_SEASON;
    
    if (!isHistorical && data.rosters?.[teamAbbrev]) {
        // Current season: use live roster
        const roster = data.rosters[teamAbbrev] || [];
        activePlayers = roster.filter(p => !p.taxi);
        taxiPlayers = roster.filter(p => p.taxi);
    } else {
        // Historical season: build roster from matchup data (last week with scores)
        const weeksWithScores = (data.weeks || []).filter(w => w.has_scores);
        if (weeksWithScores.length > 0) {
            // Use the last week's roster as the "final" roster
            const lastWeek = weeksWithScores[weeksWithScores.length - 1];
            for (const matchup of lastWeek.matchups) {
                let teamData = null;
                if (matchup.team1.abbrev === teamAbbrev) teamData = matchup.team1;
                else if (matchup.team2.abbrev === teamAbbrev) teamData = matchup.team2;
                
                if (teamData) {
                    activePlayers = teamData.roster || [];
                    taxiPlayers = teamData.taxi_squad || [];
                    break;
                }
            }
        }
    }
    
    // Get picks for this team (only show for current season)
    const teamPicks = isHistorical ? [] : getCompareTeamPicks(teamAbbrev);
    
    // Group players by position
    const positions = ROSTER_POSITION_ORDER;
    const byPosition = {};
    positions.forEach(pos => byPosition[pos] = []);

    activePlayers.forEach(player => {
        if (byPosition[player.position]) {
            const points = getPlayerSeasonPoints(player.name, teamAbbrev);
            byPosition[player.position].push({...player, totalPoints: points});
        }
    });
    
    // Sort each position by points descending
    positions.forEach(pos => {
        byPosition[pos].sort((a, b) => b.totalPoints - a.totalPoints);
    });
    
    return {
        abbrev: teamAbbrev,
        name: teamName,
        total: teamTotal,
        byPosition,
        taxiPlayers,
        picks: teamPicks
    };
}

function getCompareTeamPicks(teamAbbrev) {
    // Get picks owned by this team
    const allPicks = data.draft_picks || [];
    if (!Array.isArray(allPicks)) return [];
    
    return allPicks.filter(pick => pick.current_owner === teamAbbrev);
}

// Stats Leaders
let currentStatsPosition = 'ALL';

let _statsLeadersCache = { dataRef: null, value: null };

function getStatsLeaders() {
    if (!data) return {};

    // Memoized: stats leaders depend only on the current data object.
    if (_statsLeadersCache.dataRef === data) {
        return _statsLeadersCache.value;
    }

    // Aggregate player stats across all weeks
    const playerStats = {};  // key: "playerName|nflTeam" -> {name, nfl_team, position, fantasy_team, total_points}
    
    // First, add all players from current rosters (so everyone rostered is included)
    if (data.rosters) {
        for (const [teamAbbrev, roster] of Object.entries(data.rosters)) {
            for (const player of roster) {
                if (!player.name || !player.position) continue;
                
                // Include position in key to differentiate OL vs D/ST for same NFL team
                const key = `${player.name}|${player.nfl_team || ''}|${player.position}`;
                
                if (!playerStats[key]) {
                    playerStats[key] = {
                        name: player.name,
                        nfl_team: player.nfl_team || '',
                        position: player.position,
                        fantasy_team: teamAbbrev,
                        total_points: 0,
                        weeks_played: 0
                    };
                }
            }
        }
    }
    
    // Then aggregate stats from matchups
    if (data.weeks) {
        for (const week of data.weeks) {
            if (!week.matchups) continue;
            
            for (const matchup of week.matchups) {
                for (const teamData of [matchup.team1, matchup.team2]) {
                    const fantasyTeam = teamData.abbrev;
                    const roster = teamData.roster || [];
                    
                    for (const player of roster) {
                        if (!player.name || !player.position) continue;
                        
                        // Include position in key to differentiate OL vs D/ST for same NFL team
                        const key = `${player.name}|${player.nfl_team || ''}|${player.position}`;
                        
                        if (!playerStats[key]) {
                            playerStats[key] = {
                                name: player.name,
                                nfl_team: player.nfl_team || '',
                                position: player.position,
                                fantasy_team: fantasyTeam,
                                total_points: 0,
                                weeks_played: 0
                            };
                        }
                        
                        // Always update fantasy team to track ownership
                        playerStats[key].fantasy_team = fantasyTeam;
                        
                        // Add points if player has a score (including negative)
                        if (player.score !== undefined && player.score !== null) {
                            playerStats[key].total_points += player.score;
                            if (player.score !== 0) {
                                playerStats[key].weeks_played++;
                            }
                        }
                    }
                }
            }
        }
    }
    
    // Group by position
    const byPosition = {};
    for (const player of Object.values(playerStats)) {
        if (!byPosition[player.position]) {
            byPosition[player.position] = [];
        }
        byPosition[player.position].push(player);
    }
    
    // Sort each position by total points descending
    for (const pos of Object.keys(byPosition)) {
        byPosition[pos].sort((a, b) => b.total_points - a.total_points);
    }

    _statsLeadersCache = { dataRef: data, value: byPosition };
    return byPosition;
}

function renderStatsLeaders() {
    const leaders = getStatsLeaders();
    const positions = ROSTER_POSITION_ORDER;
    const positionNames = {
        'QB': 'Quarterbacks',
        'RB': 'Running Backs',
        'WR': 'Wide Receivers',
        'TE': 'Tight Ends',
        'K': 'Kickers',
        'D/ST': 'Defenses',
        'HC': 'Head Coaches',
        'OL': 'Offensive Lines'
    };
    if (parseHashRoute().view === 'stats') {
        replaceRouteParams({ position: currentStatsPosition === 'ALL' ? null : currentStatsPosition });
    }
    
    // Render position selector
    const selector = document.getElementById('stats-position-selector');
    selector.innerHTML = `
        <button class="stats-pos-btn ${currentStatsPosition === 'ALL' ? 'active' : ''}"
                id="stats-position-all-tab" role="tab" aria-selected="${currentStatsPosition === 'ALL'}"
                aria-controls="stats-leaders-container" tabindex="${currentStatsPosition === 'ALL' ? '0' : '-1'}"
                data-pos="ALL">All</button>
        ${positions.map(pos => `
            <button class="stats-pos-btn ${currentStatsPosition === pos ? 'active' : ''}"
                    id="stats-position-${posClassKey(pos).toLowerCase()}-tab" role="tab"
                    aria-selected="${currentStatsPosition === pos}" aria-controls="stats-leaders-container"
                    tabindex="${currentStatsPosition === pos ? '0' : '-1'}" data-pos="${pos}">${pos}</button>
        `).join('')}
    `;

    const positionTabId = currentStatsPosition === 'ALL'
        ? 'stats-position-all-tab'
        : `stats-position-${posClassKey(currentStatsPosition).toLowerCase()}-tab`;
    document.getElementById('stats-leaders-container')?.setAttribute('aria-labelledby', positionTabId);
    
    selector.querySelectorAll('.stats-pos-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            currentStatsPosition = btn.dataset.pos;
            replaceRouteParams({ position: currentStatsPosition === 'ALL' ? null : currentStatsPosition });
            renderStatsLeaders();
        });
    });
    
    // Render leaders grid
    const container = document.getElementById('stats-leaders-container');
    const positionsToShow = currentStatsPosition === 'ALL' ? positions : [currentStatsPosition];
    container.classList.toggle('single-position', currentStatsPosition !== 'ALL');
    const visiblePlayerCount = positionsToShow.reduce((total, pos) => {
        const count = (leaders[pos] || []).length;
        return total + (currentStatsPosition === 'ALL' ? Math.min(count, 5) : count);
    }, 0);

    container.innerHTML = `
        <p class="results-summary">${visiblePlayerCount} ${visiblePlayerCount === 1 ? 'player' : 'players'} shown${currentStatsPosition === 'ALL' ? ' · top 5 per position' : ''}</p>
        ${positionsToShow.map(pos => {
        const posLeaders = currentStatsPosition === 'ALL' 
            ? (leaders[pos] || []).slice(0, 5)
            : (leaders[pos] || []);
        if (posLeaders.length === 0) return '';
        
        return `
            <div class="stats-position-card">
                <div class="stats-position-header">${positionNames[pos] || pos}</div>
                ${posLeaders.map((player, idx) => {
                    const rank = idx + 1;
                    const rankClass = rank <= 3 ? `rank-${rank}` : '';
                    return `
                        <div class="stats-leader-row ${rankClass}">
                            <div class="stats-rank">${rank}</div>
                            <div class="stats-player-info">
                                ${playerProfileButton(player.name, 'stats-player-name', null, player.position)}
                                <div class="stats-player-meta">
                                    <span class="stats-nfl-team">${escapeHtml(player.nfl_team || '')}</span>
                                    <span class="stats-fantasy-team">• ${escapeHtml(player.fantasy_team || '')}</span>
                                </div>
                            </div>
                            <div class="stats-points">${player.total_points.toFixed(1)}</div>
                        </div>
                    `;
                }).join('')}
                ${currentStatsPosition === 'ALL' && (leaders[pos] || []).length > 5 ? `
                    <button class="stats-view-all" data-pos="${pos}">View all ${positionNames[pos]}</button>
                ` : ''}
            </div>
        `;
        }).join('')}`;

    // Add click handlers for "view all" buttons
    container.querySelectorAll('.stats-view-all').forEach(btn => {
        btn.addEventListener('click', () => {
            currentStatsPosition = btn.dataset.pos;
            replaceRouteParams({ position: currentStatsPosition });
            renderStatsLeaders();
        });
    });
}

function renderTeamStats() {
    const teamStats = data.team_stats;
    if (!teamStats || Object.keys(teamStats).length === 0) {
        document.getElementById('team-stats-container').innerHTML = 
            '<p style="text-align: center; color: var(--text-muted);">Team stats not available</p>';
        return;
    }
    
    const calculatedOwnerSuccess = calculateOwnerSuccessByTeam();

    // Order by standings rank, falling back to points for any unranked teams
    const standingsOrder = (data.standings || []).map(t => t.abbrev);
    const teams = Object.values(teamStats).map(team => {
        if (Number.isFinite(team.owner_success_rate)) return team;
        return { ...team, ...(calculatedOwnerSuccess[team.abbrev] || {}) };
    }).sort((a, b) => {
        const ai = standingsOrder.indexOf(a.abbrev);
        const bi = standingsOrder.indexOf(b.abbrev);
        if (ai !== -1 && bi !== -1) return ai - bi;
        if (ai !== -1) return -1;
        if (bi !== -1) return 1;
        return (b.total_points_for || 0) - (a.total_points_for || 0);
    });
    const ownerSuccessTeams = teams.filter(team => Number.isFinite(team.owner_success_rate));
    
    const container = document.getElementById('team-stats-container');
    
    // Build comprehensive stats table
    container.innerHTML = `
        <div class="team-stats-section">
            <h3>Team Rankings</h3>
            <div class="stats-table-wrapper">
                <table class="team-stats-table">
                    <thead>
                        <tr>
                            <th class="team-col">Team</th>
                            <th class="num">Record</th>
                            <th class="num">Win %</th>
                            <th class="num">PF</th>
                            <th class="num">PA</th>
                            <th class="num">Diff</th>
                            <th class="num">PPG</th>
                            <th class="num">PPG A</th>
                            <th class="num">Std Dev</th>
                            <th class="num">Avg Rank</th>
                            <th class="num">Best</th>
                            <th class="num">Worst</th>
                            <th class="num">Streak</th>
                            <th class="num" title="Oberon Power Ranking">OPR</th>
                            <th class="num">Adj OPR</th>
                            <th class="num" title="Starter points divided by optimal lineup points">Owner Success Rate</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${teams.map((team, index) => {
                            const winPct = ((team.win_pct || 0) * 100).toFixed(0);
                            const diff = team.point_differential || 0;
                            const diffClass = diff > 0 ? 'positive' : diff < 0 ? 'negative' : '';
                            const streak = team.streak || {};
                            const streakStr = streak.count ? `${streak.count}${streak.type}` : '-';
                            const streakClass = streak.type === 'W' ? 'streak-win' : streak.type === 'L' ? 'streak-loss' : '';
                            const ownerSuccess = Number.isFinite(team.owner_success_rate) ? `${team.owner_success_rate.toFixed(1)}%` : '—';
                            const pointsLeft = Number.isFinite(team.points_left_on_table) ? team.points_left_on_table.toFixed(0) : '0';
                            const percentLeft = Number.isFinite(team.points_left_on_table_pct) ? team.points_left_on_table_pct.toFixed(1) : '0.0';
                            
                            return `
                                <tr>
                                    <td class="team-col">
                                        <span class="team-abbrev">${team.abbrev}</span>
                                        <span class="team-name-short">${(team.name || '').substring(0, 20)}${(team.name || '').length > 20 ? '...' : ''}</span>
                                    </td>
                                    <td class="num">${team.record || '-'}</td>
                                    <td class="num">${winPct}%</td>
                                    <td class="num">${(team.total_points_for || 0).toFixed(0)}</td>
                                    <td class="num">${(team.total_points_against || 0).toFixed(0)}</td>
                                    <td class="num ${diffClass}">${diff > 0 ? '+' : ''}${diff.toFixed(0)}</td>
                                    <td class="num">${(team.ppg || 0).toFixed(1)}</td>
                                    <td class="num">${(team.ppg_against || 0).toFixed(1)}</td>
                                    <td class="num">${(team.std_dev || 0).toFixed(1)}</td>
                                    <td class="num">${(team.avg_rank || 0).toFixed(1)}</td>
                                    <td class="num">${(team.best_week || 0).toFixed(0)}<span class="week-ref">W${team.best_week_num || '-'}</span></td>
                                    <td class="num">${(team.worst_week || 0).toFixed(0)}<span class="week-ref">W${team.worst_week_num || '-'}</span></td>
                                    <td class="num ${streakClass}">${streakStr}</td>
                                    <td class="num">${(team.opr || 0).toFixed(1)}</td>
                                    <td class="num ${(team.adjusted_opr || 0) >= 1 ? 'positive' : 'negative'}">${(team.adjusted_opr || 0).toFixed(2)}</td>
                                    <td class="num" title="${percentLeft}% (${pointsLeft} points) left on the table">${ownerSuccess}</td>
                                </tr>
                            `;
                        }).join('')}
                    </tbody>
                </table>
            </div>
        </div>
        
        <div class="team-stats-section">
            <h3>Advanced Stats</h3>
            <div class="advanced-stats-grid">
                <div class="stat-card">
                    <div class="stat-card-title">Most Points (Single Week)</div>
                    ${teams.slice().sort((a, b) => (b.best_week || 0) - (a.best_week || 0)).slice(0, 5).map((t, i) => `
                        <div class="stat-card-row">
                            <span class="rank">${i + 1}.</span>
                            <span class="team">${t.abbrev}</span>
                            <span class="value">${(t.best_week || 0).toFixed(0)}</span>
                            <span class="context">W${t.best_week_num}</span>
                        </div>
                    `).join('')}
                </div>
                
                <div class="stat-card">
                    <div class="stat-card-title">Fewest Points (Single Week)</div>
                    ${teams.slice().sort((a, b) => (a.worst_week || 999) - (b.worst_week || 999)).slice(0, 5).map((t, i) => `
                        <div class="stat-card-row">
                            <span class="rank">${i + 1}.</span>
                            <span class="team">${t.abbrev}</span>
                            <span class="value">${(t.worst_week || 0).toFixed(0)}</span>
                            <span class="context">W${t.worst_week_num}</span>
                        </div>
                    `).join('')}
                </div>
                
                <div class="stat-card">
                    <div class="stat-card-title">Highest PPG</div>
                    ${teams.slice().sort((a, b) => (b.ppg || 0) - (a.ppg || 0)).slice(0, 5).map((t, i) => `
                        <div class="stat-card-row">
                            <span class="rank">${i + 1}.</span>
                            <span class="team">${t.abbrev}</span>
                            <span class="value">${(t.ppg || 0).toFixed(1)}</span>
                        </div>
                    `).join('')}
                </div>
                
                <div class="stat-card">
                    <div class="stat-card-title">Fewest PPG Against</div>
                    ${teams.slice().sort((a, b) => (a.ppg_against || 999) - (b.ppg_against || 999)).slice(0, 5).map((t, i) => `
                        <div class="stat-card-row">
                            <span class="rank">${i + 1}.</span>
                            <span class="team">${t.abbrev}</span>
                            <span class="value">${(t.ppg_against || 0).toFixed(1)}</span>
                        </div>
                    `).join('')}
                </div>
                
                <div class="stat-card">
                    <div class="stat-card-title">Largest Win Margin</div>
                    ${teams.slice().sort((a, b) => (b.largest_win || 0) - (a.largest_win || 0)).slice(0, 5).map((t, i) => `
                        <div class="stat-card-row">
                            <span class="rank">${i + 1}.</span>
                            <span class="team">${t.abbrev}</span>
                            <span class="value">+${(t.largest_win || 0).toFixed(0)}</span>
                        </div>
                    `).join('')}
                </div>
                
                <div class="stat-card">
                    <div class="stat-card-title">Most Consistent (Low Std Dev)</div>
                    ${teams.slice().sort((a, b) => (a.std_dev || 999) - (b.std_dev || 999)).slice(0, 5).map((t, i) => `
                        <div class="stat-card-row">
                            <span class="rank">${i + 1}.</span>
                            <span class="team">${t.abbrev}</span>
                            <span class="value">σ ${(t.std_dev || 0).toFixed(1)}</span>
                        </div>
                    `).join('')}
                </div>
                
                <div class="stat-card">
                    <div class="stat-card-title">Best Avg Weekly Rank</div>
                    ${teams.slice().sort((a, b) => (a.avg_rank || 999) - (b.avg_rank || 999)).slice(0, 5).map((t, i) => `
                        <div class="stat-card-row">
                            <span class="rank">${i + 1}.</span>
                            <span class="team">${t.abbrev}</span>
                            <span class="value">${(t.avg_rank || 0).toFixed(2)}</span>
                        </div>
                    `).join('')}
                </div>
                
                <div class="stat-card">
                    <div class="stat-card-title">Point Differential</div>
                    ${teams.slice().sort((a, b) => (b.point_differential || 0) - (a.point_differential || 0)).slice(0, 5).map((t, i) => {
                        const diff = t.point_differential || 0;
                        return `
                            <div class="stat-card-row">
                                <span class="rank">${i + 1}.</span>
                                <span class="team">${t.abbrev}</span>
                                <span class="value ${diff > 0 ? 'positive' : 'negative'}">${diff > 0 ? '+' : ''}${diff.toFixed(0)}</span>
                            </div>
                        `;
                    }).join('')}
                </div>
                
                <div class="stat-card">
                    <div class="stat-card-title">OPR (Oberon Power Ranking)</div>
                    ${teams.slice().sort((a, b) => (b.opr || 0) - (a.opr || 0)).slice(0, 5).map((t, i) => `
                        <div class="stat-card-row">
                            <span class="rank">${i + 1}.</span>
                            <span class="team">${t.abbrev}</span>
                            <span class="value">${(t.opr || 0).toFixed(1)}</span>
                        </div>
                    `).join('')}
                </div>

                <div class="stat-card">
                    <div class="stat-card-title">Owner Success Rate</div>
                    ${ownerSuccessTeams.slice().sort((a, b) => b.owner_success_rate - a.owner_success_rate).slice(0, 5).map((t, i) => `
                        <div class="stat-card-row">
                            <span class="rank">${i + 1}.</span>
                            <span class="team">${t.abbrev}</span>
                            <span class="value">${t.owner_success_rate.toFixed(1)}%</span>
                            <span class="context" title="${t.points_left_on_table.toFixed(0)} points left">${t.points_left_on_table_pct.toFixed(1)}% left</span>
                        </div>
                    `).join('')}
                </div>
                
                <div class="stat-card">
                    <div class="stat-card-title">Adjusted OPR (vs League Avg)</div>
                    ${teams.slice().sort((a, b) => (b.adjusted_opr || 0) - (a.adjusted_opr || 0)).slice(0, 5).map((t, i) => `
                        <div class="stat-card-row">
                            <span class="rank">${i + 1}.</span>
                            <span class="team">${t.abbrev}</span>
                            <span class="value ${(t.adjusted_opr || 0) >= 1 ? 'positive' : ''}">${(t.adjusted_opr || 0).toFixed(2)}</span>
                        </div>
                    `).join('')}
                </div>
            </div>
        </div>
        <div class="formula-section">
            <div class="formula-note">
                <strong>Oberon Power Ranking (OPR):</strong> (5 × PPG + 2 × (Best Week + Worst Week) + 3 × Win%) / 10
            </div>
            <div class="formula-note">
                <strong>Adjusted OPR:</strong> Team OPR / League Average OPR
            </div>
            <div class="formula-note">
                <strong>Owner Success Rate:</strong> Starter points / optimal lineup points. A 100% rate means no points were left on the table by starting a lower-scoring player.
            </div>
        </div>
    `;
}

function renderConstitution() {
    if (!data.constitution) return;
    
    const container = document.getElementById('constitution-container');
    
    // Number items within each section
    container.innerHTML = data.constitution.map(article => `
        <div class="constitution-article">
            <div class="article-title">${article.title}</div>
            ${article.sections.map(section => {
                let itemNum = 0;
                let subItemLetter = 'a';
                return `
                    <div class="article-section">
                        <div class="section-title">${section.title}</div>
                        <div class="section-content">
                            ${section.content.map(item => {
                                if (item.type === 'subheader') {
                                    return `<div class="section-subheader">${item.text}</div>`;
                                } else if (item.type === 'header') {
                                    itemNum = 0;
                                    subItemLetter = 'a';
                                    return `<div class="content-header">${item.text}</div>`;
                                } else if (item.type === 'item') {
                                    itemNum++;
                                    subItemLetter = 'a';
                                    return `<div class="content-item"><span class="item-num">${itemNum}.</span> ${item.text}</div>`;
                                } else if (item.type === 'subitem') {
                                    const letter = subItemLetter;
                                    subItemLetter = String.fromCharCode(subItemLetter.charCodeAt(0) + 1);
                                    return `<div class="content-subitem"><span class="item-num">${letter}.</span> ${item.text}</div>`;
                                }
                                return `<p>${item.text}</p>`;
                            }).join('')}
                        </div>
                    </div>
                `;
            }).join('')}
        </div>
    `).join('');
}

// --------------------------------------------------------------------------- //
// Rule Changes
// --------------------------------------------------------------------------- //

const RULE_CHANGES_API_URL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'https://qpfl-scoring.vercel.app/api/rule-changes'
    : `${window.location.origin}/api/rule-changes`;

let ruleProposals = null;

async function fetchRuleProposals() {
    try {
        const res = await fetch(`${RULE_CHANGES_API_URL}?action=proposals`);
        if (!res.ok) return null;
        const json = await res.json();
        return json.proposals || [];
    } catch (e) {
        console.error('Failed to fetch rule proposals:', e);
        return null;
    }
}

function getTeamName(abbrev) {
    if (!abbrev || !data || !data.teams) return abbrev;
    const team = data.teams.find(t => t.abbrev === abbrev);
    return team ? (normalizeCoOwnerLabel(team.owner) || team.name || abbrev) : abbrev;
}

function renderRuleChanges() {
    const container = document.getElementById('rule-changes-container');
    if (!container) return;

    const loggedIn = !!(manageState && manageState.team && manageState.password);

    // Build the live proposals section
    const buildLiveSection = (proposals) => {
        if (!proposals || proposals.length === 0) {
            return '<p class="rc-empty">No proposals yet for the 2026 season.</p>';
        }
        return proposals.map(p => buildProposalCard(p, loggedIn, true)).join('');
    };

    // Build the historical section
    const buildHistorySection = () => {
        if (!data.rule_changes_history || data.rule_changes_history.length === 0) return '';
        return data.rule_changes_history.map(season => {
            const proposals = season.proposals || [];
            const noteHtml = season.note ? `<p class="rc-season-note">${season.note}</p>` : '';
            const proposalsHtml = proposals.length === 0 ? '' : proposals.map(p => buildHistoryCard(p)).join('');
            return `
                <div class="rule-changes-year-section">
                    <div class="rc-year-header">${season.label}</div>
                    ${noteHtml}
                    ${proposalsHtml}
                </div>`;
        }).join('');
    };

    const proposeFormHtml = loggedIn ? `
        <div class="rc-propose-form" id="rc-propose-form" style="display:none;">
            <div class="rc-form-group">
                <label class="rc-form-label" for="rc-propose-title">Proposed Rule <span class="rc-required">*</span></label>
                <input type="text" id="rc-propose-title" class="rc-form-input" placeholder="Describe the proposed change…" maxlength="300">
            </div>
            <div class="rc-form-group">
                <label class="rc-form-label" for="rc-propose-current">Current Rule (optional)</label>
                <input type="text" id="rc-propose-current" class="rc-form-input" placeholder="What is the current rule?">
            </div>
            <div class="rc-form-group">
                <label class="rc-form-label" for="rc-propose-desc">Rationale / Notes (optional)</label>
                <textarea id="rc-propose-desc" class="rc-form-textarea" placeholder="Why should we change this?" rows="3" maxlength="2000"></textarea>
            </div>
            <div class="rc-form-actions">
                <button class="rc-submit-btn" id="rc-propose-submit">Submit Proposal</button>
                <button class="rc-cancel-btn" id="rc-propose-cancel">Cancel</button>
            </div>
            <div class="rc-status" id="rc-propose-status"></div>
        </div>` : '';

    const proposeBtnHtml = loggedIn ? `
        <button class="rc-propose-btn" id="rc-show-propose-form">+ Propose a Rule Change</button>` : '';

    // Use the API-fresh cache when available; an empty split snapshot is the fallback.
    const displayProposals = ruleProposals !== null ? ruleProposals : (data.rule_proposals || []);
    const liveHtml = buildLiveSection(displayProposals);

    container.innerHTML = `
        <div class="rule-changes-header">
            <div class="rc-live-section">
                <div class="rc-year-header rc-live-label">Proposed Prior to the 2026 Season</div>
                <div id="rc-live-proposals">${liveHtml}</div>
                ${proposeBtnHtml}
                ${proposeFormHtml}
            </div>
            <div class="rc-history-section">
                ${buildHistorySection()}
            </div>
        </div>`;

    attachRuleChangeHandlers(loggedIn);

    // Fetch fresh data from API whenever cache is stale (null = first load or post-mutation)
    if (ruleProposals === null) {
        fetchRuleProposals().then(proposals => {
            if (proposals !== null) {
                ruleProposals = proposals;
                const liveContainer = document.getElementById('rc-live-proposals');
                if (liveContainer) {
                    liveContainer.innerHTML = buildLiveSection(ruleProposals);
                    attachVoteAndCommentHandlers(loggedIn);
                }
            }
        });
    }
}

function buildProposalCard(proposal, loggedIn, interactive) {
    const myTeam = manageState && manageState.team;
    const myVote = proposal.votes && myTeam ? proposal.votes[myTeam] : null;
    const yesVoters = Object.entries(proposal.votes || {}).filter(([, v]) => v === 'yes').map(([t]) => getTeamName(t));
    const noVoters = Object.entries(proposal.votes || {}).filter(([, v]) => v === 'no').map(([t]) => getTeamName(t));
    const nominatorName = getTeamName(proposal.nominator);

    const voteHtml = interactive && loggedIn ? `
        <div class="rc-vote-row">
            <button class="rc-vote-btn rc-yes-btn${myVote === 'yes' ? ' active' : ''}" data-id="${proposal.id}" data-vote="yes">
                ✓ Yes${yesVoters.length ? ` (${yesVoters.length})` : ''}
            </button>
            <button class="rc-vote-btn rc-no-btn${myVote === 'no' ? ' active' : ''}" data-id="${proposal.id}" data-vote="no">
                ✗ No${noVoters.length ? ` (${noVoters.length})` : ''}
            </button>
        </div>` : `
        <div class="rc-vote-display">
            ${yesVoters.length ? `<span class="rc-yes-tally">Yes (${yesVoters.length}): ${yesVoters.join(', ')}</span>` : ''}
            ${noVoters.length ? `<span class="rc-no-tally">No (${noVoters.length}): ${noVoters.join(', ')}</span>` : ''}
        </div>`;

    const commentsHtml = buildCommentsHtml(proposal.comments || [], proposal.id, interactive && loggedIn);

    return `
        <div class="rule-change-card" data-proposal-id="${proposal.id}">
            <div class="rc-card-title">${escapeHtml(proposal.title)}</div>
            ${proposal.current ? `<div class="rc-current"><span class="rc-label">Current:</span> ${escapeHtml(proposal.current)}</div>` : ''}
            <div class="rc-meta">Nominated by ${escapeHtml(nominatorName)}</div>
            ${voteHtml}
            ${commentsHtml}
        </div>`;
}

function buildHistoryCard(proposal) {
    const yesNames = (proposal.yes || []).map(normalizeCoOwnerLabel).join(', ');
    const noNames = (proposal.no || []).map(normalizeCoOwnerLabel).join(', ');
    const abstainNames = (proposal.abstain || []).map(normalizeCoOwnerLabel).join(', ');

    const voteHtml = `
        <div class="rc-vote-display">
            ${yesNames ? `<span class="rc-yes-tally">Yes: ${escapeHtml(yesNames)}</span>` : ''}
            ${noNames ? `<span class="rc-no-tally">No: ${escapeHtml(noNames)}</span>` : ''}
            ${abstainNames ? `<span class="rc-abstain-tally">Abstain: ${escapeHtml(abstainNames)}</span>` : ''}
        </div>`;

    const commentsHtml = (proposal.comments || []).length > 0 ? `
        <div class="rc-comments-section rc-history-comments">
            ${proposal.comments.map(c => `
                <div class="rc-comment">
                    <span class="rc-comment-author">${escapeHtml(c.author)}:</span>
                    <span class="rc-comment-text">${escapeHtml(c.text)}</span>
                </div>`).join('')}
        </div>` : '';

    return `
        <div class="rule-change-card rule-change-card--history">
            <div class="rc-card-title">${escapeHtml(proposal.title)}</div>
            ${proposal.current ? `<div class="rc-current"><span class="rc-label">Current:</span> ${escapeHtml(proposal.current)}</div>` : ''}
            <div class="rc-meta">Nominated by ${escapeHtml(proposal.nominator || '')}</div>
            ${voteHtml}
            ${commentsHtml}
        </div>`;
}

function buildCommentsHtml(comments, proposalId, canComment) {
    const commentsListHtml = comments.length > 0 ? comments.map(c => `
        <div class="rc-comment">
            <span class="rc-comment-author">${escapeHtml(getTeamName(c.author))}:</span>
            <span class="rc-comment-text">${escapeHtml(c.text)}</span>
        </div>`).join('') : '';

    const commentFormHtml = canComment ? `
        <div class="rc-comment-form">
            <textarea class="rc-comment-input" data-id="${proposalId}" aria-label="Comment on rule proposal" placeholder="Add a comment…" rows="2" maxlength="2000"></textarea>
            <button class="rc-comment-submit" data-id="${proposalId}">Post</button>
            <span class="rc-comment-status" data-id="${proposalId}"></span>
        </div>` : '';

    if (!commentsListHtml && !commentFormHtml) return '';

    return `
        <div class="rc-comments-section">
            <div class="rc-comments-list">${commentsListHtml}</div>
            ${commentFormHtml}
        </div>`;
}

function attachRuleChangeHandlers(loggedIn) {
    attachVoteAndCommentHandlers(loggedIn);

    if (!loggedIn) return;

    const showBtn = document.getElementById('rc-show-propose-form');
    const form = document.getElementById('rc-propose-form');
    const cancelBtn = document.getElementById('rc-propose-cancel');
    const submitBtn = document.getElementById('rc-propose-submit');

    if (showBtn && form) {
        showBtn.addEventListener('click', () => {
            form.style.display = form.style.display === 'none' ? 'block' : 'none';
            showBtn.style.display = form.style.display === 'none' ? '' : 'none';
        });
    }
    if (cancelBtn && form && showBtn) {
        cancelBtn.addEventListener('click', () => {
            form.style.display = 'none';
            showBtn.style.display = '';
        });
    }
    if (submitBtn) {
        submitBtn.addEventListener('click', async () => {
            const title = document.getElementById('rc-propose-title')?.value.trim();
            const current = document.getElementById('rc-propose-current')?.value.trim();
            const description = document.getElementById('rc-propose-desc')?.value.trim();
            const statusEl = document.getElementById('rc-propose-status');

            if (!title) {
                if (statusEl) statusEl.textContent = 'Please enter a title.';
                return;
            }
            submitBtn.disabled = true;
            if (statusEl) statusEl.textContent = 'Submitting…';

            try {
                const res = await fetch(RULE_CHANGES_API_URL, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        action: 'propose',
                        team: manageState.team,
                        password: manageState.password,
                        title,
                        current,
                        description,
                    }),
                });
                const json = await res.json();
                if (res.ok && json.success) {
                    ruleProposals = null;
                    renderRuleChanges();
                } else {
                    if (statusEl) statusEl.textContent = json.error || 'Failed to submit.';
                    submitBtn.disabled = false;
                }
            } catch (e) {
                if (statusEl) statusEl.textContent = 'Network error.';
                submitBtn.disabled = false;
            }
        });
    }
}

function attachVoteAndCommentHandlers(loggedIn) {
    if (!loggedIn) return;

    document.querySelectorAll('.rc-vote-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const id = btn.dataset.id;
            const vote = btn.dataset.vote;
            const card = btn.closest('.rule-change-card');
            const isActive = btn.classList.contains('active');
            const finalVote = isActive ? null : vote;

            btn.disabled = true;

            try {
                const res = await fetch(RULE_CHANGES_API_URL, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        action: 'vote',
                        team: manageState.team,
                        password: manageState.password,
                        id,
                        vote: finalVote,
                    }),
                });
                const json = await res.json();
                if (res.ok && json.success) {
                    ruleProposals = null;
                    const proposals = await fetchRuleProposals();
                    ruleProposals = proposals;
                    const liveContainer = document.getElementById('rc-live-proposals');
                    if (liveContainer) {
                        liveContainer.innerHTML = proposals
                            ? proposals.map(p => buildProposalCard(p, true, true)).join('')
                            : '';
                        attachVoteAndCommentHandlers(true);
                    }
                } else {
                    btn.disabled = false;
                }
            } catch (e) {
                btn.disabled = false;
            }
        });
    });

    document.querySelectorAll('.rc-comment-submit').forEach(btn => {
        btn.addEventListener('click', async () => {
            const id = btn.dataset.id;
            const textarea = document.querySelector(`.rc-comment-input[data-id="${id}"]`);
            const statusEl = document.querySelector(`.rc-comment-status[data-id="${id}"]`);
            const text = textarea?.value.trim();

            if (!text) return;
            btn.disabled = true;
            if (statusEl) statusEl.textContent = 'Posting…';

            try {
                const res = await fetch(RULE_CHANGES_API_URL, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        action: 'comment',
                        team: manageState.team,
                        password: manageState.password,
                        id,
                        text,
                    }),
                });
                const json = await res.json();
                if (res.ok && json.success) {
                    ruleProposals = null;
                    const proposals = await fetchRuleProposals();
                    ruleProposals = proposals;
                    const liveContainer = document.getElementById('rc-live-proposals');
                    if (liveContainer) {
                        liveContainer.innerHTML = proposals
                            ? proposals.map(p => buildProposalCard(p, true, true)).join('')
                            : '';
                        attachVoteAndCommentHandlers(true);
                    }
                } else {
                    if (statusEl) statusEl.textContent = json.error || 'Failed.';
                    btn.disabled = false;
                }
            } catch (e) {
                if (statusEl) statusEl.textContent = 'Network error.';
                btn.disabled = false;
            }
        });
    });
}

// Lineup Form State
const LINEUP_CONFIG = {
    // Use current host for API calls (works on both preview and production)
    workerUrl: window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
        ? 'https://qpfl-scoring.vercel.app/api/lineup'  // Fallback for local dev
        : `${window.location.origin}/api/lineup`,
    positions: {
        'QB': { max: 1, label: 'Quarterback' },
        'RB': { max: 2, label: 'Running Back' },
        'WR': { max: 2, label: 'Wide Receiver' },
        'TE': { max: 1, label: 'Tight End' },
        'K': { max: 1, label: 'Kicker' },
        'D/ST': { max: 1, label: 'Defense/ST' },
        'HC': { max: 1, label: 'Head Coach' },
        'OL': { max: 1, label: 'Offensive Line' }
    }
};

let lineupState = {
    team: null,
    week: null,
    roster: [],
    selections: {}, // position -> [player names]
    baseline: {}
};

function initLineupForm() {
    // Populate current team name in the input
    const canonicalTeam = data.teams?.find(t => t.abbrev === manageState.team);
    const teamNameInput = document.getElementById('new-team-name');
    if (teamNameInput && canonicalTeam) {
        teamNameInput.value = canonicalTeam.name;
    }
    
    // Set up team name change button
    document.getElementById('change-team-name-btn').onclick = handleTeamNameChange;

    // Set up team avatar editor
    initAvatarEditor();

    const weekSelect = document.getElementById('lineup-week-select');

    // Collect all weeks a lineup could be submitted for. data.schedule (all
    // 17 weeks, populated from schedule.txt - see docs/ROADMAP_2026.md P0.1)
    // is the primary source so Week 1 has an option before anything is
    // scored; data.weeks (already-scored weeks) is merged in as a fallback
    // for review of weeks that predate the current schedule data.
    const allWeeks = new Set();
    if (data && data.schedule) {
        data.schedule.forEach(w => allWeeks.add(w.week));
    }
    if (data && data.weeks) {
        data.weeks.forEach(w => allWeeks.add(w.week));
    }

    const weekNumbers = Array.from(allWeeks).sort((a, b) => a - b);
    const playoffWeeks = new Set((data?.schedule || []).filter(w => w.is_playoffs).map(w => w.week));
    
    weekSelect.innerHTML = '<option value="">-- Select Week --</option>' +
        weekNumbers.map(w => {
            const isPlayoff = playoffWeeks.has(w);
            const scheduleWeek = data.schedule?.find(sw => sw.week === w);
            const label = isPlayoff && scheduleWeek?.playoff_round 
                ? `Week ${w} - ${scheduleWeek.playoff_round}`
                : `Week ${w}`;
            return `<option value="${w}"${w === (data.lineup_week || data.current_week) ? ' selected' : ''}>${label}</option>`;
        }).join('');
    
    // Event listener for week change
    weekSelect.onchange = loadRosterForEditing;
    document.getElementById('lineup-submit-btn').onclick = submitLineup;
    
    // If current week is preselected, load the roster
    if (weekSelect.value) {
        loadRosterForEditing();
    }
}

async function loadRosterForEditing() {
    const week = parseInt(document.getElementById('lineup-week-select').value);
    const teamAbbrev = manageState.team;
    const password = manageState.password;
    
    if (!week) {
        document.getElementById('lineup-editor').style.display = 'none';
        return;
    }
    
    // Find the team's roster for this week - check regular weeks first
    const weekData = data.weeks.find(w => w.week === week);
    const scheduleWeek = data.schedule?.find(w => w.week === week);
    const isPlayoffWeek = scheduleWeek?.is_playoffs;
    
    let teamData = null;
    let roster = [];
    
    if (weekData && weekData.matchups) {
        // Regular week - get roster from matchup data
        for (const matchup of weekData.matchups) {
            if (matchup.team1.abbrev === teamAbbrev) {
                teamData = matchup.team1;
                break;
            }
            if (matchup.team2.abbrev === teamAbbrev) {
                teamData = matchup.team2;
                break;
            }
        }
        if (teamData) {
            roster = teamData.roster;
        }
    }
    
    // For playoff weeks (or any week without roster data), use the roster from the most recent regular season week
    if (roster.length === 0) {
        // Find the most recent week with this team's roster data
        const sortedWeeks = [...data.weeks].sort((a, b) => b.week - a.week);
        for (const w of sortedWeeks) {
            if (w.matchups) {
                for (const matchup of w.matchups) {
                    if (matchup.team1.abbrev === teamAbbrev && matchup.team1.roster?.length > 0) {
                        roster = matchup.team1.roster.map(p => ({
                            name: p.name,
                            nfl_team: p.nfl_team,
                            position: p.position,
                            score: 0,
                            starter: false  // Reset starters for new week
                        }));
                        break;
                    }
                    if (matchup.team2.abbrev === teamAbbrev && matchup.team2.roster?.length > 0) {
                        roster = matchup.team2.roster.map(p => ({
                            name: p.name,
                            nfl_team: p.nfl_team,
                            position: p.position,
                            score: 0,
                            starter: false
                        }));
                        break;
                    }
                }
            }
            if (roster.length > 0) break;
        }
    }

    // No scored week yet at all (e.g. Week 1 before anything has been scored) -
    // fall back to the live current roster (data.rosters, kept up to date by
    // trades/waivers). See docs/ROADMAP_2026.md P0.2.
    if (roster.length === 0 && data.rosters?.[teamAbbrev]) {
        roster = data.rosters[teamAbbrev]
            .filter(p => !p.taxi)
            .map(p => ({
                name: p.name,
                nfl_team: p.nfl_team,
                position: p.position,
                score: 0,
                starter: false
            }));
    }

    if (roster.length === 0) {
        document.getElementById('submit-status').className = 'submit-status error';
        document.getElementById('submit-status').textContent = 'No roster data available for this week';
        document.getElementById('lineup-editor').style.display = 'none';
        return;
    }
    
    // Store state
    const canonicalTeam = data.teams?.find(t => t.abbrev === teamAbbrev);
    lineupState.team = teamAbbrev;
    lineupState.teamName = canonicalTeam?.name || teamAbbrev;
    lineupState.week = week;
    lineupState.password = password;
    lineupState.roster = roster;
    lineupState.selections = {};
    
    // Initialize selections based on current starters
    Object.keys(LINEUP_CONFIG.positions).forEach(pos => {
        lineupState.selections[pos] = roster
            .filter(p => p.position === pos && p.starter)
            .map(p => p.name);
    });
    lineupState.baseline = structuredClone(lineupState.selections);
    
    // Show editor
    document.getElementById('lineup-editor').style.display = 'block';
    const weekLabel = isPlayoffWeek && scheduleWeek?.playoff_round
        ? `${scheduleWeek.playoff_round}`
        : `Week ${week}`;
    document.getElementById('editor-week-label').textContent = weekLabel;
    document.getElementById('submit-status').textContent = '';
    document.getElementById('submit-status').className = 'submit-status';
    
    renderLineupEditor();
}

function resetLineupForm() {
    document.getElementById('lineup-editor').style.display = 'none';
    document.getElementById('submit-status').textContent = '';
    document.getElementById('submit-status').className = 'submit-status';
    document.getElementById('lineup-week-select').value = '';
    lineupState = { team: null, week: null, roster: [], selections: {}, baseline: {} };
}

function renderLineupEditor() {
    const container = document.getElementById('position-groups');
    const positions = Object.keys(LINEUP_CONFIG.positions);
    const lockedPlayers = getLockedPlayers();
    
    container.innerHTML = positions.map(pos => {
        const config = LINEUP_CONFIG.positions[pos];
        const players = lineupState.roster.filter(p => p.position === pos);
        const selected = lineupState.selections[pos] || [];
        const isFull = selected.length === config.max;
        const countClass = isFull ? 'complete' : '';
        
        return `
            <div class="position-group-card">
                <div class="position-group-header">
                    <span class="position-label">${pos} - ${config.label}</span>
                    <span class="starter-count ${countClass}">${selected.length}/${config.max} starting</span>
                </div>
                <div class="player-options">
                    ${players.map(p => {
                        const isSelected = selected.includes(p.name);
                        const isLocked = lockedPlayers.has(p.name);
                        const classes = [
                            'player-option',
                            isSelected ? 'selected' : '',
                            isLocked ? 'locked' : ''
                        ].filter(Boolean).join(' ');
                        
                        return `
                            <div class="${classes}" 
                                 data-position="${pos}" data-player="${p.name}" data-locked="${isLocked}">
                                <div class="starter-indicator">${isLocked ? '🔒' : ''}</div>
                                <div class="player-details">
                                    ${playerProfileButton(p.name, '', null, p.position)}
                                    <span class="player-team">${escapeHtml(p.nfl_team || '')}</span>
                                    ${isLocked ? '<span class="locked-label">LOCKED</span>' : ''}
                                </div>
                            </div>
                        `;
                    }).join('')}
                </div>
            </div>
        `;
    }).join('');
    
    // Add click handlers (only for unlocked players)
    container.querySelectorAll('.player-option').forEach(el => {
        el.addEventListener('click', () => {
            if (el.dataset.locked === 'true') {
                // Show message that player is locked
                const statusEl = document.getElementById('submit-status');
                statusEl.className = 'submit-status error';
                statusEl.textContent = `${el.dataset.player}'s game has already started - lineup locked`;
                setTimeout(() => { statusEl.textContent = ''; statusEl.className = 'submit-status'; }, 3000);
                return;
            }
            const pos = el.dataset.position;
            const player = el.dataset.player;
            togglePlayerSelection(pos, player);
        });
    });
    
    updateLineupSummary();
}

function togglePlayerSelection(position, playerName) {
    const config = LINEUP_CONFIG.positions[position];
    const selected = lineupState.selections[position] || [];
    
    if (selected.includes(playerName)) {
        // Deselect - always allowed
        lineupState.selections[position] = selected.filter(p => p !== playerName);
    } else {
        // Select (if under max limit)
        if (selected.length < config.max) {
            lineupState.selections[position] = [...selected, playerName];
        }
        // At max - do nothing (user must deselect first)
    }
    
    renderLineupEditor();
}

function updateLineupSummary() {
    const summary = document.getElementById('lineup-summary');
    const submitBtn = document.getElementById('lineup-submit-btn');
    
    let total = 0;
    let maxTotal = 0;
    Object.keys(LINEUP_CONFIG.positions).forEach(pos => {
        const config = LINEUP_CONFIG.positions[pos];
        const selected = (lineupState.selections[pos] || []).length;
        total += selected;
        maxTotal += config.max;
    });
    
    // Always valid - users can start 0 to max players
    summary.textContent = `${total} starters selected (max ${maxTotal})`;
    summary.className = 'lineup-summary valid';
    submitBtn.disabled = false;
}

function lineupKickoffForPlayer(player) {
    const teamAliases = {
        LAR: 'LA',
        JAC: 'JAX',
        WSH: 'WAS',
        LA: 'LAR',
        JAX: 'JAC',
        WAS: 'WSH'
    };
    const playerTeam = player.nfl_team;
    const lookupKickoff = kickoffs =>
        kickoffs?.[playerTeam] || kickoffs?.[teamAliases[playerTeam]] || null;

    const isLiveSeason = data?.season === LIVE_SEASON && !data?.is_historical;
    if (isLiveSeason) {
        const activeLineupWeek = Number(data?.lineup_week ?? data?.current_week);
        if (Number(lineupState.week) !== activeLineupWeek) return null;
        return lookupKickoff(data?.kickoffs);
    }

    const historicalWeek = data?.game_times?.[String(lineupState.week)];
    return lookupKickoff(historicalWeek);
}

function isPlayerLocked(player) {
    const gameTime = lineupKickoffForPlayer(player);
    if (!gameTime) return false;

    const kickoff = new Date(gameTime);
    return Number.isFinite(kickoff.getTime()) && new Date() >= kickoff;
}

function getLockedPlayers() {
    // Returns set of player names that are locked
    const locked = new Set();
    lineupState.roster.forEach(player => {
        if (isPlayerLocked(player)) {
            locked.add(player.name);
        }
    });
    return locked;
}

async function handleTeamNameChange() {
    const newName = document.getElementById('new-team-name').value.trim();
    const statusEl = document.getElementById('team-name-status');
    
    if (!newName) {
        statusEl.innerHTML = '<span class="error">Please enter a team name</span>';
        return;
    }
    
    if (newName.length > 50) {
        statusEl.innerHTML = '<span class="error">Team name must be 50 characters or less</span>';
        return;
    }
    
    statusEl.innerHTML = '<span class="pending">Updating team name...</span>';
    
    try {
        // Create the team name change request
        const response = await fetch(LINEUP_CONFIG.workerUrl.replace('/lineup', '/team-name'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                team: manageState.team,
                password: manageState.password,
                newName: newName,
                week: data.current_week
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            statusEl.innerHTML = '<span class="success">Team name updated! Changes will appear after the next data refresh.</span>';
            
            // Update the display immediately
            document.getElementById('manage-team-name').textContent = newName;
            const dashboardName = document.getElementById('my-team-dashboard-name');
            if (dashboardName) dashboardName.textContent = newName;
            
            // Update local data
            const teamData = data.teams?.find(t => t.abbrev === manageState.team);
            if (teamData) {
                teamData.name = newName;
            }
            
            // Clear status after a few seconds
            setTimeout(() => {
                statusEl.innerHTML = '';
            }, 5000);
        } else {
            statusEl.innerHTML = `<span class="error">${result.error || 'Failed to update team name'}</span>`;
        }
    } catch (e) {
        console.error('Team name change error:', e);
        statusEl.innerHTML = '<span class="error">Network error - please try again</span>';
    }
}

// Holds the cropped 256x256 PNG data URL staged for upload (null until a file
// is chosen and processed).
let pendingAvatarDataUrl = null;
const AVATAR_UPLOAD_SIZE = 256;

function initAvatarEditor() {
    const preview = document.getElementById('avatar-preview');
    const fileInput = document.getElementById('avatar-file-input');
    const chooseBtn = document.getElementById('avatar-choose-btn');
    const uploadBtn = document.getElementById('avatar-upload-btn');
    const statusEl = document.getElementById('avatar-status');
    if (!preview || !fileInput || !chooseBtn || !uploadBtn) return;

    // Start from the team's current avatar (uploaded image or initials circle).
    pendingAvatarDataUrl = null;
    uploadBtn.disabled = true;
    if (statusEl) statusEl.innerHTML = '';
    const info = data.teams?.find(t => t.abbrev === manageState.team);
    preview.innerHTML = teamAvatar(manageState.team, info?.name, 'avatar-xl', info?.avatar || currentTeamAvatar(manageState.team));

    chooseBtn.onclick = () => fileInput.click();

    fileInput.onchange = async () => {
        const file = fileInput.files && fileInput.files[0];
        if (!file) return;
        if (!/^image\/(png|jpeg|webp)$/.test(file.type)) {
            statusEl.innerHTML = '<span class="error">Please choose a PNG, JPG, or WebP image</span>';
            return;
        }
        try {
            pendingAvatarDataUrl = await cropImageToSquarePng(file, AVATAR_UPLOAD_SIZE);
            // Show the cropped result in the round preview frame.
            preview.innerHTML = `<span class="team-avatar avatar-xl"><img class="team-avatar-img" src="${pendingAvatarDataUrl}" alt=""></span>`;
            uploadBtn.disabled = false;
            statusEl.innerHTML = '<span class="pending">Preview ready — click Upload Avatar to save.</span>';
        } catch (e) {
            console.error('Avatar processing error:', e);
            statusEl.innerHTML = '<span class="error">Could not read that image — try another file.</span>';
        } finally {
            // Allow re-selecting the same file later.
            fileInput.value = '';
        }
    };

    uploadBtn.onclick = handleAvatarUpload;
}

// Read an image file, cover-crop it to a centered square, and return a PNG data
// URL at the given pixel size. Keeps committed avatars small and uniform.
function cropImageToSquarePng(file, size) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onerror = () => reject(new Error('read failed'));
        reader.onload = () => {
            const img = new Image();
            img.onerror = () => reject(new Error('decode failed'));
            img.onload = () => {
                const canvas = document.createElement('canvas');
                canvas.width = size;
                canvas.height = size;
                const ctx = canvas.getContext('2d');
                // Cover-crop: scale so the shorter side fills the square, center it.
                const side = Math.min(img.width, img.height);
                const sx = (img.width - side) / 2;
                const sy = (img.height - side) / 2;
                ctx.drawImage(img, sx, sy, side, side, 0, 0, size, size);
                resolve(canvas.toDataURL('image/png'));
            };
            img.src = reader.result;
        };
        reader.readAsDataURL(file);
    });
}

async function handleAvatarUpload() {
    const statusEl = document.getElementById('avatar-status');
    const uploadBtn = document.getElementById('avatar-upload-btn');
    if (!pendingAvatarDataUrl) {
        statusEl.innerHTML = '<span class="error">Choose an image first</span>';
        return;
    }

    uploadBtn.disabled = true;
    statusEl.innerHTML = '<span class="pending">Uploading avatar...</span>';

    try {
        const response = await fetch(LINEUP_CONFIG.workerUrl.replace('/lineup', '/team-avatar'), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                team: manageState.team,
                password: manageState.password,
                imageData: pendingAvatarDataUrl,
                // Stamp the version's effective point so it applies from this week
                // forward without rewriting past weeks (see api/team-avatar.py).
                season: data.season,
                week: data.current_week
            })
        });
        const result = await response.json();

        if (result.success) {
            statusEl.innerHTML = '<span class="success">Avatar uploaded! It will appear across the site after the next deploy.</span>';
            const dashboardAvatar = document.getElementById('my-team-dashboard-avatar');
            const preview = document.getElementById('avatar-preview');
            if (dashboardAvatar && preview) dashboardAvatar.innerHTML = preview.innerHTML;
            pendingAvatarDataUrl = null;
            setTimeout(() => { statusEl.innerHTML = ''; }, 6000);
        } else {
            statusEl.innerHTML = `<span class="error">${result.error || 'Failed to upload avatar'}</span>`;
            uploadBtn.disabled = false;
        }
    } catch (e) {
        console.error('Avatar upload error:', e);
        statusEl.innerHTML = '<span class="error">Network error - please try again</span>';
        uploadBtn.disabled = false;
    }
}

async function submitLineup() {
    const statusEl = document.getElementById('submit-status');
    const submitBtn = document.getElementById('lineup-submit-btn');
    
    // Check for localhost
    if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
        statusEl.className = 'submit-status error';
        statusEl.textContent = 'Lineup submission only works on the deployed site (Vercel). Local testing shows the UI only.';
        return;
    }
    
    statusEl.className = 'submit-status loading';
    statusEl.textContent = 'Submitting lineup...';
    submitBtn.disabled = true;
    
    // Get currently locked players (games already started)
    const lockedPlayers = getLockedPlayers();
    
    // Get optional comment
    const commentEl = document.getElementById('lineup-comment');
    const comment = commentEl ? commentEl.value.trim() : '';
    
    const payload = {
        team: lineupState.team,
        week: lineupState.week,
        password: lineupState.password,
        starters: lineupState.selections,
        locked_players: Array.from(lockedPlayers),
        comment: comment,
        submitted_at: new Date().toISOString()
    };
    
    try {
        const response = await fetch(LINEUP_CONFIG.workerUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        
        const result = await response.json();
        
        if (response.ok && result.success) {
            statusEl.className = 'submit-status success';
            statusEl.textContent = '✓ Lineup submitted successfully! Changes will be reflected after the next update.';
            lineupState.baseline = structuredClone(lineupState.selections);
            if (commentEl) commentEl.value = '';
            if (lineupState.week === (data?.lineup_week || data?.current_week)) {
                data.lineups = data.lineups || {};
                data.lineups[lineupState.team] = {
                    ...lineupState.selections,
                    submitted_at: payload.submitted_at
                };
                renderLineupReminder();
                if (getActiveView() === 'manage') renderMyTeamDashboard();
            }
        } else {
            statusEl.className = 'submit-status error';
            statusEl.textContent = result.error || 'Failed to submit lineup';
            submitBtn.disabled = false;
        }
    } catch (error) {
        statusEl.className = 'submit-status error';
        statusEl.textContent = 'Network error - please try again. Make sure you are on the deployed site.';
        submitBtn.disabled = false;
    }
}

function directTabs(tablist) {
    return [...tablist.querySelectorAll('[role="tab"]')].filter(tab =>
        tab.closest('[role="tablist"]') === tablist
        && !tab.hidden
        && tab.style.display !== 'none'
    );
}

function setActiveTab(tablist, activeTab) {
    if (!tablist || !activeTab) return;
    directTabs(tablist).forEach(tab => {
        const selected = tab === activeTab;
        tab.classList.toggle('active', selected);
        tab.setAttribute('aria-selected', String(selected));
        tab.tabIndex = selected ? 0 : -1;
    });
}

document.addEventListener('keydown', event => {
    const currentTab = event.target.closest?.('[role="tab"]');
    const tablist = currentTab?.closest('[role="tablist"]');
    if (!currentTab || !tablist) return;

    const tabs = directTabs(tablist);
    const currentIndex = tabs.indexOf(currentTab);
    if (currentIndex < 0) return;

    let nextIndex = null;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
        nextIndex = (currentIndex + 1) % tabs.length;
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
        nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
    } else if (event.key === 'Home') {
        nextIndex = 0;
    } else if (event.key === 'End') {
        nextIndex = tabs.length - 1;
    }
    if (nextIndex === null) return;

    event.preventDefault();
    const nextTab = tabs[nextIndex];
    const nextId = nextTab.id;
    nextTab.click();
    requestAnimationFrame(() => {
        const refreshedTab = nextId ? document.getElementById(nextId) : nextTab;
        refreshedTab?.focus();
    });
});

// Navigation — hash-based routing
// URL format: #view, #view/subview, or #view/subview/detail
//   #matchups/week/3      -> Matchups view, Week subview, week 3
//   #teams/roster/CGK     -> Teams view, Roster subview, team CGK
//   #teams/activity/GSA   -> Teams view, activity subview, team GSA
//   #teams/history/SLS     -> Teams view, franchise history for team SLS
function parseHashRoute(rawHash = location.hash.slice(1) || 'home') {
    const separator = rawHash.indexOf('?');
    const path = separator >= 0 ? rawHash.slice(0, separator) : rawHash;
    const query = separator >= 0 ? rawHash.slice(separator + 1) : '';
    const [view, subview, ...detailParts] = path.split('/');
    return {
        raw: rawHash,
        path,
        view,
        subview,
        detail: detailParts.length ? detailParts.join('/') : undefined,
        params: new URLSearchParams(query),
    };
}

function replaceRouteParams(updates) {
    const route = parseHashRoute();
    const params = new URLSearchParams(route.params);
    Object.entries(updates).forEach(([key, value]) => {
        if (value === null || value === undefined || value === '') params.delete(key);
        else params.set(key, String(value));
    });
    activeRouteParams = params;
    const query = params.toString();
    history.replaceState(history.state, '', `#${route.path}${query ? `?${query}` : ''}`);
    updatePageMetadata(route.view, route.subview, route.detail);
}

function applyRouteState(route) {
    activeRouteParams = new URLSearchParams(route.params);
    if (route.view === 'transactions') {
        const season = Number(route.params.get('season'));
        currentTransactionSeason = Number.isFinite(season) && season > 0 ? season : null;
        transactionSearchQuery = (route.params.get('q') || '').trim().toLowerCase();
        transactionTypeFilter = route.params.get('type') || 'ALL';
        transactionTeamFilter = new Set(
            (route.params.get('teams') || '').split(',').map(value => value.trim()).filter(Boolean)
        );
    } else if (route.view === 'stats' && (route.subview || 'leaders') === 'leaders') {
        const position = route.params.get('position') || 'ALL';
        currentStatsPosition = ['ALL', ...ROSTER_POSITION_ORDER].includes(position) ? position : 'ALL';
    } else if (route.view === 'teams' && route.subview === 'compare') {
        compareTeam1 = route.params.get('team1') || '';
        compareTeam2 = route.params.get('team2') || '';
    } else if (route.view === 'drafts' && (route.subview || 'history') === 'history') {
        currentDraft = 0;
    }
}

function focusMainContentOnMobile() {
    if (!window.matchMedia('(max-width: 768px)').matches) return;
    const main = document.getElementById('main-content');
    if (!main) return;
    main.focus({ preventScroll: true });
    main.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function navigateToView(view, subview, detail) {
    if (!document.getElementById(`${view}-view`)) view = 'home';
    closeNavMore();
    const sub = subview || DEFAULT_SUBVIEW[view];

    document.querySelectorAll('.nav-btn').forEach(button => {
        button.classList.remove('active');
        button.removeAttribute('aria-current');
    });
    const activeNavButton = document.querySelector(`.nav-btn[data-view="${view}"]`);
    activeNavButton?.classList.add('active');
    activeNavButton?.setAttribute('aria-current', 'page');
    document.getElementById('nav-more-toggle')?.classList.toggle(
        'active',
        Boolean(activeNavButton?.closest('.nav-more-menu'))
    );

    document.querySelectorAll('.view-container').forEach(v => v.classList.remove('active'));
    document.getElementById(`${view}-view`).classList.add('active');

    // Apply detail to view-level state BEFORE rendering, so the renderer reads it.
    // Detail changes invalidate the cached render so the new state actually shows.
    if (view === 'matchups' && detail) {
        const weekNum = parseInt(detail, 10);
        if (Number.isFinite(weekNum) && weekNum !== currentWeek) {
            currentWeek = weekNum;
            viewFresh.delete('matchups');
        }
    } else if (view === 'teams') {
        if (detail) {
            const teamCode = decodeURIComponent(detail).toUpperCase();
            if (teamCode !== currentTeam) {
                currentTeam = teamCode;
                viewFresh.delete(view);
            }
        }
        if (sub !== teamRouteSubview) {
            teamRouteSubview = sub;
            viewFresh.delete(view);
        }
    }

    updatePageMetadata(view, sub, detail);

    if (view === 'matchups' && sub) {
        activateGenericSubview('matchups', sub);
    } else if (view === 'stats' && sub) {
        activateGenericSubview('stats', sub);
    } else if (view === 'history' && sub) {
        activateGenericSubview('history', sub);
    } else if (view === 'drafts' && sub) {
        activateGenericSubview('drafts', sub);
        if (sub === 'challenge') initNflDraftView();
    } else if (view === 'teams' && sub) {
        activateTeamsSubview(sub);
    }

    if (view === 'manage') {
        await prepareViewData('manage');
        if (getActiveView() === 'manage') initManageRoster();
        return;
    }

    await ensureViewRendered(view, sub);
    if (getActiveView() !== view) return;
    if (view === 'teams' && sub === 'compare') initCompareView();
}

const navMore = document.getElementById('nav-more');
const navMoreToggle = document.getElementById('nav-more-toggle');

function closeNavMore({ restoreFocus = false } = {}) {
    if (!navMore || !navMoreToggle) return;
    navMore.classList.remove('open');
    navMoreToggle.setAttribute('aria-expanded', 'false');
    if (restoreFocus) navMoreToggle.focus();
}

navMoreToggle?.addEventListener('click', (event) => {
    event.stopPropagation();
    const willOpen = !navMore?.classList.contains('open');
    navMore?.classList.toggle('open', willOpen);
    navMoreToggle.setAttribute('aria-expanded', String(willOpen));
});

document.addEventListener('click', (event) => {
    if (navMore?.classList.contains('open') && !navMore.contains(event.target)) {
        closeNavMore();
    }
});

document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && navMore?.classList.contains('open')) {
        closeNavMore({ restoreFocus: true });
    }
});

function activateGenericSubview(parent, sub) {
    const view = document.getElementById(`${parent}-view`);
    if (!view) return;
    const btn = view.querySelector(`.subnav-btn[data-subview="${sub}"]`);
    if (!btn) return;
    setActiveTab(btn.closest('[role="tablist"]'), btn);
    view.querySelectorAll('.subview').forEach(panel => {
        const active = panel.id === `${parent}-${sub}-subview`;
        panel.classList.toggle('active', active);
        panel.hidden = !active;
    });
}

function activateTeamsSubview(sub) {
    const teamBtn = document.querySelector(`.team-subnav-btn[data-subview="${sub}"]`);
    if (!teamBtn) return;
    setActiveTab(teamBtn.closest('[role="tablist"]'), teamBtn);
    document.querySelectorAll('.team-subview').forEach(panel => {
        const active = panel.id === `team-${sub}-subview`;
        panel.classList.toggle('active', active);
        panel.hidden = !active;
    });

    // Team selector is only relevant for per-team subviews
    const teamSelector = document.getElementById('team-selector');
    const needsSelector = ['roster', 'history', 'activity'].includes(sub);
    if (teamSelector) teamSelector.style.display = needsSelector ? '' : 'none';
    const hubHeader = document.getElementById('team-hub-header');
    if (hubHeader) hubHeader.hidden = !needsSelector;
}

async function applyHash({ focus = false } = {}) {
    let hash = location.hash.slice(1) || 'home';
    let route = parseHashRoute(hash);

    const legacyTeamHof = route.path.match(/^(?:teams\/hof|hof\/teams)(?:\/(.+))?$/);
    if (legacyTeamHof) {
        const team = legacyTeamHof[1] ? decodeURIComponent(legacyTeamHof[1]) : null;
        hash = team ? `teams/history/${encodeURIComponent(team)}` : 'teams/history';
        history.replaceState(null, '', `#${hash}`);
        route = parseHashRoute(hash);
    }

    const legacyTeamHall = route.path.match(/^history\/teams(?:\/(.+))?$/);
    if (legacyTeamHall) {
        const team = legacyTeamHall[1] ? decodeURIComponent(legacyTeamHall[1]) : null;
        hash = team ? `teams/history/${encodeURIComponent(team)}` : 'teams/history';
        history.replaceState(null, '', `#${hash}`);
        route = parseHashRoute(hash);
    }

    const legacyTradeBlock = route.path.match(/^teams\/tradeblock(?:\/(.+))?$/);
    if (legacyTradeBlock) {
        const team = legacyTradeBlock[1] ? decodeURIComponent(legacyTradeBlock[1]) : null;
        hash = team ? `teams/activity/${encodeURIComponent(team)}` : 'teams/activity';
        history.replaceState(null, '', `#${hash}`);
        route = parseHashRoute(hash);
    }

    const retiredTeamPage = route.path.match(/^teams\/(?:overview|rivalries)(?:\/(.+))?$/);
    if (retiredTeamPage) {
        const team = retiredTeamPage[1] ? decodeURIComponent(retiredTeamPage[1]) : null;
        hash = team ? `teams/history/${encodeURIComponent(team)}` : 'teams/history';
        history.replaceState(null, '', `#${hash}`);
        route = parseHashRoute(hash);
    }

    if (route.path.startsWith('history/lore')) {
        hash = 'history/records';
        history.replaceState(null, '', `#${hash}`);
        route = parseHashRoute(hash);
    }

    // Honor legacy hash paths from before the nav restructure
    if (LEGACY_HASH_REDIRECTS[route.path]) {
        hash = LEGACY_HASH_REDIRECTS[route.path];
        history.replaceState(null, '', `#${hash}`);
        route = parseHashRoute(hash);
    }

    if (route.view === 'player') {
        await Promise.all([
            ensureSharedResource('hall_of_fame'),
            ensureSharedResource('transactions'),
            ensureSharedResource('drafts'),
            ensureCurrentSeasonFiles({ rosters: true }),
            ensureAllSeasonWeeks(),
        ]);
        await navigateToView('teams', 'all-rosters');
        showPlayerModalByProfileKey(decodeURIComponent(route.subview || ''), { updateRoute: false });
        return;
    }

    closePlayerModalOverlay({ restoreFocus: false });
    applyRouteState(route);
    await navigateToView(route.view, route.subview, route.detail);
    if (focus) focusMainContentOnMobile();
}

document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
        closeNavMore();
        if (!confirmManageNavigation(btn.dataset.view)) return;
        // My Team only works for the current season — switch to it if needed.
        if (btn.dataset.view === 'manage' && currentSeason !== LIVE_SEASON) {
            await loadData(LIVE_SEASON);
        }
        history.pushState(null, '', `#${btn.dataset.view}`);
        await navigateToView(btn.dataset.view);
        focusMainContentOnMobile();
    });
});

// Generic subnav handler (Matchups, Stats, History sub-tabs)
document.querySelectorAll('.subnav-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
        const parent = btn.dataset.parent;
        const sub = btn.dataset.subview;
        if (!parent || !sub) return;
        if (!confirmManageNavigation(parent)) return;
        activateGenericSubview(parent, sub);
        history.pushState(null, '', `#${parent}/${sub}`);
        updatePageMetadata(parent, sub);
        viewFresh.delete(parent);
        await ensureViewRendered(parent, sub);
        if (parent === 'drafts' && sub === 'challenge') initNflDraftView();
        focusMainContentOnMobile();
    });
});

// Team sub-navigation (All Rosters, Compare, Roster, Trade Block)
document.querySelectorAll('.team-subnav-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
        const sub = btn.dataset.subview;
        if (!confirmManageNavigation('teams')) return;
        activateTeamsSubview(sub);
        const needsTeam = ['roster', 'history', 'activity'].includes(sub);
        const path = needsTeam && currentTeam
            ? `#teams/${sub}/${encodeURIComponent(currentTeam)}`
            : `#teams/${sub}`;
        history.pushState(null, '', path);
        updatePageMetadata('teams', sub, needsTeam ? currentTeam : undefined);
        teamRouteSubview = sub;
        viewFresh.delete('teams');
        await ensureViewRendered('teams', sub);
        if (sub === 'compare') initCompareView();
        focusMainContentOnMobile();
    });
});

window.addEventListener('popstate', () => {
    const route = parseHashRoute();
    if (!confirmManageNavigation(route.view)) {
        history.pushState(null, '', '#manage');
        return;
    }
    applyHash({ focus: true });
});


// ====== MANAGE ROSTER SECTION ======
const MANAGE_CONFIG = {
    // Use current host for API calls (works on both preview and production)
    apiUrl: window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
        ? 'https://qpfl-scoring.vercel.app/api/transaction'  // Fallback for local dev
        : `${window.location.origin}/api/transaction`
};
const COMMISSIONER_TEAM = 'GSA';

// Keep the existing storage key so current signed-in sessions survive this UI consolidation.
const GLOBAL_SESSION_KEY = 'qpfl_manage_session_v1';
const GLOBAL_SESSION_TTL_MS = 7 * 24 * 60 * 60 * 1000; // 7 days

function loadStoredGlobalSession() {
    try {
        const raw = localStorage.getItem(GLOBAL_SESSION_KEY);
        if (!raw) return null;
        const session = JSON.parse(raw);
        if (!session.team || !session.password || !session.expiresAt) return null;
        if (Date.now() > session.expiresAt) {
            localStorage.removeItem(GLOBAL_SESSION_KEY);
            return null;
        }
        return session;
    } catch (e) {
        return null;
    }
}

function saveGlobalSession(team, password) {
    try {
        localStorage.setItem(GLOBAL_SESSION_KEY, JSON.stringify({
            team,
            password,
            expiresAt: Date.now() + GLOBAL_SESSION_TTL_MS
        }));
    } catch (e) {}
}

function clearGlobalSession() {
    try { localStorage.removeItem(GLOBAL_SESSION_KEY); } catch (e) {}
}

let manageState = {
    team: null,
    password: null,
    selectedTaxiPlayer: null,
    selectedReleasePlayer: null,
    selectedFaPlayer: null,
    selectedFaReleasePlayer: null,
    selectedReleaseOnlyPlayer: null,
    tradeGivePlayers: [],
    tradeGivePicks: [],
    tradeReceivePlayers: [],
    tradeReceivePicks: [],
    tradeConditions: {}, // { itemId: conditionText }
    tradePartner: null,
    actionStatusId: null
};
let tradeBlockBaseline = { seeking: [], tradingAway: [], players: [], notes: '' };

function sortedValues(values) {
    return [...values].sort().join('\u0000');
}

function isLineupDirty() {
    if (!lineupState.team) return false;
    return Object.keys(LINEUP_CONFIG.positions).some(position =>
        sortedValues(lineupState.selections[position] || [])
            !== sortedValues(lineupState.baseline?.[position] || [])
    );
}

function isTradeBlockDirty() {
    const notes = document.getElementById('tradeblock-notes');
    if (!notes) return false;
    const seeking = [...document.querySelectorAll('#seeking-positions input:checked')].map(input => input.value);
    const tradingAway = [...document.querySelectorAll('#trading-positions input:checked')].map(input => input.value);
    const players = [...document.querySelectorAll('#available-players input:checked')].map(input => input.value);
    return sortedValues(seeking) !== sortedValues(tradeBlockBaseline.seeking)
        || sortedValues(tradingAway) !== sortedValues(tradeBlockBaseline.tradingAway)
        || sortedValues(players) !== sortedValues(tradeBlockBaseline.players)
        || notes.value.trim() !== tradeBlockBaseline.notes;
}

function hasUnsavedManageChanges() {
    if (getActiveView() !== 'manage') return false;
    const hasSelections = Boolean(
        manageState.selectedTaxiPlayer
        || manageState.selectedReleasePlayer
        || manageState.selectedFaPlayer
        || manageState.selectedFaReleasePlayer
        || manageState.selectedReleaseOnlyPlayer
        || manageState.tradeGivePlayers.length
        || manageState.tradeGivePicks.length
        || manageState.tradeReceivePlayers.length
        || manageState.tradeReceivePicks.length
        || manageState.tradePartner
        || Object.keys(manageState.tradeConditions).length
    );
    const commentIds = [
        'lineup-comment', 'taxi-comment', 'fa-comment', 'release-comment',
        'trade-comment', 'roster-action-comment'
    ];
    const hasComment = commentIds.some(id => document.getElementById(id)?.value.trim());
    return isLineupDirty() || isDepthChartDirty() || isTradeBlockDirty() || hasSelections || hasComment;
}

function confirmManageNavigation(targetView) {
    if (targetView === 'manage' || !hasUnsavedManageChanges()) return true;
    return window.confirm('You have unsaved My Team changes. Leave this page and discard them?');
}

window.addEventListener('beforeunload', event => {
    if (!hasUnsavedManageChanges()) return;
    event.preventDefault();
    event.returnValue = '';
});

function isCommissioner() {
    return manageState.team === COMMISSIONER_TEAM && Boolean(manageState.password);
}

// --------------------------------------------------------------------------- //
// Global Auth
// --------------------------------------------------------------------------- //

function updateGlobalAuthUI(team) {
    const loginBtn = document.getElementById('global-login-btn');
    const userStatus = document.getElementById('global-user-status');
    const userNameEl = document.getElementById('global-user-name');
    const commissionerTab = document.getElementById('commissioner-tab');
    const hasCommissionerAccess = team === COMMISSIONER_TEAM;

    if (commissionerTab) commissionerTab.hidden = !hasCommissionerAccess;

    if (team) {
        const teams = sharedData?.teams?.length ? sharedData.teams : (data?.teams || []);
        const teamObj = teams.find(t => t.abbrev === team);
        const displayName = normalizeCoOwnerLabel(teamObj?.owner) || team;
        if (loginBtn) loginBtn.style.display = 'none';
        if (userStatus) userStatus.style.display = '';
        if (userNameEl) userNameEl.textContent = displayName;
    } else {
        if (loginBtn) loginBtn.style.display = '';
        if (userStatus) userStatus.style.display = 'none';
    }

    if (!hasCommissionerAccess) {
        if (location.hash === '#manage/commissioner') history.replaceState(null, '', '#manage');
        if (document.getElementById('tx-commissioner')?.classList.contains('active')) {
            switchTxTab('dashboard');
        }
    }

    renderLineupReminder();
}

async function performLogin(team, password) {
    if (!team || !password) return false;

    try {
        const response = await fetch(MANAGE_CONFIG.apiUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'validate', team, password })
        });
        const result = await response.json();

        if (result.success) {
            manageState.team = team;
            manageState.password = password;
            saveGlobalSession(team, password);
            updateGlobalAuthUI(team);
            return true;
        } else {
            clearGlobalSession();
            return false;
        }
    } catch (e) {
        if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
            manageState.team = team;
            manageState.password = password;
            saveGlobalSession(team, password);
            updateGlobalAuthUI(team);
            return true;
        }
        return false;
    }
}

function performLogout() {
    clearGlobalSession();
    resetManageState();
    resetLineupForm();
    updateGlobalAuthUI(null);
    const loginDropdown = document.getElementById('global-login-dropdown');
    const loginPassword = document.getElementById('global-login-password');
    const loginError = document.getElementById('global-login-error');
    if (loginDropdown) loginDropdown.style.display = 'none';
    loginDropdown?.setAttribute('aria-hidden', 'true');
    document.getElementById('global-login-btn')?.setAttribute('aria-expanded', 'false');
    if (loginPassword) loginPassword.value = '';
    if (loginError) loginError.textContent = '';

    // Reset My Team view
    const accessMessage = document.getElementById('manage-access-message');
    const managePanel = document.getElementById('manage-panel');
    if (accessMessage) accessMessage.style.display = '';
    if (managePanel) managePanel.style.display = 'none';
    try { switchTxTab('dashboard'); } catch (e) {}

    // Re-render rule changes to remove vote/propose UI
    if (document.getElementById('history-rules-subview')?.classList.contains('active')) {
        renderRuleChanges();
    }
    if (isNflDraftChallengeActive()) {
        initNflDraftView();
    }
}

function initGlobalAuth() {
    // Populate team select
    const globalSelect = document.getElementById('global-team-select');
    if (globalSelect && data?.teams) {
        globalSelect.innerHTML = '<option value="">-- Choose Your Team --</option>';
        data.teams.forEach(team => {
            const opt = document.createElement('option');
            opt.value = team.abbrev;
            opt.textContent = `${team.name} (${normalizeCoOwnerLabel(team.owner) || team.abbrev})`;
            globalSelect.appendChild(opt);
        });
    }

    // Wire up global login button (toggle dropdown)
    const loginBtn = document.getElementById('global-login-btn');
    const dropdown = document.getElementById('global-login-dropdown');
    const submitBtn = document.getElementById('global-login-submit');
    const logoutBtn = document.getElementById('global-logout-btn');
    const errorEl = document.getElementById('global-login-error');

    if (loginBtn) {
        loginBtn.onclick = (e) => {
            e.stopPropagation();
            const visible = dropdown.style.display !== 'none';
            dropdown.style.display = visible ? 'none' : 'block';
            dropdown.setAttribute('aria-hidden', String(visible));
            loginBtn.setAttribute('aria-expanded', String(!visible));
            if (!visible) document.getElementById('global-login-password')?.focus();
        };
    }

    if (submitBtn) {
        submitBtn.onclick = async () => {
            const team = document.getElementById('global-team-select').value;
            const password = document.getElementById('global-login-password').value;
            if (!team || !password) {
                if (errorEl) errorEl.textContent = 'Please select a team and enter your password.';
                return;
            }
            submitBtn.disabled = true;
            if (errorEl) errorEl.textContent = 'Validating…';

            const success = await performLogin(team, password);
            submitBtn.disabled = false;

            if (success) {
                dropdown.style.display = 'none';
                dropdown.setAttribute('aria-hidden', 'true');
                loginBtn?.setAttribute('aria-expanded', 'false');
                document.getElementById('global-login-password').value = '';
                if (errorEl) errorEl.textContent = '';
                // If on My Team, show the panel
                if (getActiveView() === 'manage') {
                    showManagePanelForTeam(team);
                }
                if (isNflDraftChallengeActive()) {
                    initNflDraftView();
                }
                // Re-render rule changes to show vote/propose UI
                if (document.getElementById('history-rules-subview')?.classList.contains('active')) {
                    renderRuleChanges();
                }
            } else {
                if (errorEl) errorEl.textContent = 'Incorrect password. Try again.';
            }
        };
    }

    // Close dropdown on outside click
    document.addEventListener('click', (e) => {
        if (dropdown && !dropdown.contains(e.target) && e.target !== loginBtn) {
            dropdown.style.display = 'none';
            dropdown.setAttribute('aria-hidden', 'true');
            loginBtn?.setAttribute('aria-expanded', 'false');
        }
    }, { capture: false });

    dropdown?.addEventListener('keydown', e => {
        if (e.key !== 'Escape') return;
        e.preventDefault();
        dropdown.style.display = 'none';
        dropdown.setAttribute('aria-hidden', 'true');
        loginBtn?.setAttribute('aria-expanded', 'false');
        loginBtn?.focus();
    });

    // Submit on Enter
    document.getElementById('global-login-password')?.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') submitBtn?.click();
    });

    if (logoutBtn) {
        logoutBtn.onclick = () => performLogout();
    }

    const lineupReminderAction = document.getElementById('lineup-reminder-action');
    if (lineupReminderAction) {
        lineupReminderAction.onclick = async () => {
            history.pushState(null, '', '#manage');
            await navigateToView('manage');
            switchTxTab('lineup');
            document.getElementById('lineup-week-select')?.focus();
        };
    }

    // Auto-login from stored session
    const stored = loadStoredGlobalSession();
    if (stored && data?.teams?.some(t => t.abbrev === stored.team)) {
        performLogin(stored.team, stored.password).then(success => {
            if (success && getActiveView() === 'manage') {
                showManagePanelForTeam(stored.team);
            }
            if (success && isNflDraftChallengeActive()) {
                initNflDraftView();
            }
            if (success && document.getElementById('history-rules-subview')?.classList.contains('active')) {
                renderRuleChanges();
            }
        });
    }
}

function initManageRoster() {
    resetLineupForm();

    // Set up tab switching
    document.querySelectorAll('.tx-tab').forEach(tab => {
        tab.onclick = () => {
            const tabName = tab.dataset.tab;
            if (tabName === 'commissioner') {
                history.pushState(null, '', '#manage/commissioner');
            } else if (location.hash === '#manage/commissioner') {
                history.replaceState(null, '', '#manage');
            }
            switchTxTab(tabName);
        };
    });

    document.querySelectorAll('[data-trade-tab]').forEach(tab => {
        tab.onclick = () => switchTxTab(tab.dataset.tradeTab);
    });

    switchTxTab('dashboard');

    if (manageState.team && manageState.password) {
        showManagePanelForTeam(manageState.team);
    } else {
        const accessMessage = document.getElementById('manage-access-message');
        const managePanel = document.getElementById('manage-panel');
        if (accessMessage) accessMessage.style.display = '';
        if (managePanel) managePanel.style.display = 'none';
    }
}

function showManagePanelForTeam(team) {
    document.getElementById('manage-access-message').style.display = 'none';
    document.getElementById('manage-panel').style.display = 'block';
    updateGlobalAuthUI(team);

    const canonicalTeam = data.teams?.find(t => t.abbrev === team);
    document.getElementById('manage-team-name').textContent = canonicalTeam?.name || team;

    initLineupForm();
    renderTaxiTab();
    renderFaTab();
    renderReleaseTab();
    renderTradeTab();
    renderPendingTrades();
    initDepthChartTab();
    renderMyTeamDashboard();
    switchTxTab(location.hash === '#manage/commissioner' && isCommissioner() ? 'commissioner' : 'dashboard');
    refreshMyTeamDraftStatus(team);
}

function commissionerTeamOptions(placeholder = 'Select a team') {
    const teams = data?.teams || [];
    return `<option value="">${escapeHtml(placeholder)}</option>` + teams.map(team =>
        `<option value="${escapeHtml(team.abbrev)}">${escapeHtml(team.name)} (${escapeHtml(team.abbrev)})</option>`
    ).join('');
}

function populateCommissionerTeamSelect(id, placeholder) {
    const select = document.getElementById(id);
    if (!select) return;
    const previous = select.value;
    select.innerHTML = commissionerTeamOptions(placeholder);
    if ([...select.options].some(option => option.value === previous)) select.value = previous;
}

function commissionerRosterPlayers(team) {
    const roster = normalizeTeamRoster(data?.rosters?.[team]);
    return sortRosterByPosition([...roster.roster, ...roster.taxi_squad]);
}

function populateCommissionerReleasePlayers() {
    const team = document.getElementById('commissioner-release-team')?.value;
    const select = document.getElementById('commissioner-release-player');
    if (!select) return;
    const players = commissionerRosterPlayers(team);
    select.disabled = !team || players.length === 0;
    select.innerHTML = players.length
        ? '<option value="">Select a player</option>' + players.map(player => {
            const taxi = player.taxi ? ' · Taxi' : '';
            const label = `${player.position || '—'} · ${player.name}${taxi}`;
            return `<option value="${escapeHtml(player.name)}">${escapeHtml(label)}</option>`;
        }).join('')
        : `<option value="">${team ? 'No players found' : 'Select a team first'}</option>`;
}

function populateCommissionerScorePlayers() {
    const team = document.getElementById('commissioner-score-team')?.value;
    const datalist = document.getElementById('commissioner-score-players');
    if (!datalist) return;
    datalist.innerHTML = commissionerRosterPlayers(team)
        .map(player => `<option value="${escapeHtml(player.name)}"></option>`)
        .join('');
}

function commissionerTradeLabel(trade) {
    const completedAt = trade.accepted_at || trade.proposed_at;
    const completed = completedAt ? ` · ${formatDate(completedAt)}` : '';
    return `${trade.id} · ${trade.proposer} ↔ ${trade.partner}${completed}`;
}

function populateCommissionerTrades() {
    const select = document.getElementById('commissioner-reverse-trade');
    if (!select) return;
    const completed = (data?.pending_trades || [])
        .filter(trade => trade.status === 'accepted'
            && trade.execution !== 'in_progress'
            && !trade.reversed_at
            && trade.reversal_execution !== 'in_progress')
        .sort((a, b) => new Date(b.accepted_at || b.proposed_at || 0) - new Date(a.accepted_at || a.proposed_at || 0));
    select.innerHTML = completed.length
        ? '<option value="">Select a completed trade</option>' + completed.map(trade =>
            `<option value="${escapeHtml(trade.id)}">${escapeHtml(commissionerTradeLabel(trade))}</option>`
        ).join('')
        : '<option value="">No reversible completed trades</option>';
    select.disabled = completed.length === 0;
    const submit = document.querySelector('#commissioner-reverse-form button[type="submit"]');
    if (submit) submit.disabled = completed.length === 0;
}

let commissionerConditionalPicks = null;

function commissionerConditionalPickId(pick) {
    const draftType = pick.draft_type || 'offseason';
    const typeSuffix = draftType === 'offseason' ? '' : `-${draftType}`;
    return `${pick.year}${typeSuffix}-R${pick.round}-${pick.original_team}`;
}

function commissionerConditionalPickLabel(pick) {
    const draftTypeLabels = {
        offseason: '',
        offseason_taxi: 'Taxi ',
        waiver: 'Waiver ',
        waiver_taxi: 'Waiver Taxi '
    };
    const pickNumber = pick.pick_number || `R${pick.round}`;
    const typeLabel = draftTypeLabels[pick.draft_type || 'offseason'] ?? `${pick.draft_type} `;
    return `${pick.year} ${typeLabel}${pickNumber} (${pick.original_team}) · currently ${pick.current_owner}`;
}

function commissionerConditionalGroups() {
    const grouped = new Map();
    (commissionerConditionalPicks || []).forEach(pick => {
        const condition = String(pick.condition || '').trim();
        if (!condition) return;
        if (!grouped.has(condition)) grouped.set(condition, { condition, picks: [], claimants: [] });
        const group = grouped.get(condition);
        group.picks.push(pick);
        if (pick.conditional_claim && !group.claimants.includes(pick.conditional_claim)) {
            group.claimants.push(pick.conditional_claim);
        }
    });
    return [...grouped.values()].sort((a, b) => {
        const firstA = a.picks[0] || {};
        const firstB = b.picks[0] || {};
        return Number(firstA.year) - Number(firstB.year)
            || Number(firstA.round) - Number(firstB.round)
            || a.condition.localeCompare(b.condition);
    });
}

function populateCommissionerConditionals(preferClaimant = false) {
    const groupSelect = document.getElementById('commissioner-conditional-group');
    const pickSelect = document.getElementById('commissioner-conditional-pick');
    const ownerSelect = document.getElementById('commissioner-conditional-owner');
    const details = document.getElementById('commissioner-conditional-details');
    const submit = document.querySelector('#commissioner-conditional-form button[type="submit"]');
    if (!groupSelect || !pickSelect || !ownerSelect || !details) return;

    const groups = commissionerConditionalGroups();
    const previousCondition = groupSelect.value;
    const previousOwner = ownerSelect.value;
    groupSelect.innerHTML = groups.length
        ? '<option value="">Select a condition</option>' + groups.map(group => {
            const years = [...new Set(group.picks.map(pick => String(pick.year)))].join('/');
            return `<option value="${escapeHtml(group.condition)}">${escapeHtml(`${years} · ${group.condition}`)}</option>`;
        }).join('')
        : '<option value="">No unresolved conditions</option>';
    if (groups.some(group => group.condition === previousCondition)) {
        groupSelect.value = previousCondition;
    }
    groupSelect.disabled = groups.length === 0;

    const selected = groups.find(group => group.condition === groupSelect.value);
    ownerSelect.innerHTML = commissionerTeamOptions('Select the final owner');
    if (!selected) {
        pickSelect.innerHTML = '<option value="">Select a condition first</option>';
        pickSelect.disabled = true;
        ownerSelect.disabled = true;
        details.hidden = true;
        details.innerHTML = '';
        if (submit) submit.disabled = true;
        return;
    }

    const picks = [...selected.picks].sort((a, b) =>
        Number(a.year) - Number(b.year)
        || Number(a.round) - Number(b.round)
        || String(a.original_team).localeCompare(String(b.original_team))
    );
    pickSelect.innerHTML = '<option value="">Select the pick that conveys</option>' + picks.map(pick =>
        `<option value="${escapeHtml(commissionerConditionalPickId(pick))}">${escapeHtml(commissionerConditionalPickLabel(pick))}</option>`
    ).join('');
    pickSelect.disabled = false;
    ownerSelect.disabled = false;

    const claimant = selected.claimants.length === 1 ? selected.claimants[0] : '';
    const preferredOwner = preferClaimant ? claimant : previousOwner || claimant;
    if ([...ownerSelect.options].some(option => option.value === preferredOwner)) {
        ownerSelect.value = preferredOwner;
    }

    details.innerHTML = `
        <p><strong>Condition:</strong> ${escapeHtml(selected.condition)}</p>
        <p><strong>Claimant:</strong> ${escapeHtml(selected.claimants.join(', ') || 'Not specified')}</p>
        <p><strong>Candidate picks:</strong></p>
        <ul>${picks.map(pick => `<li>${escapeHtml(commissionerConditionalPickLabel(pick))}</li>`).join('')}</ul>`;
    details.hidden = false;
    if (submit) submit.disabled = false;
}

async function loadCommissionerConditionalPicks() {
    const groupSelect = document.getElementById('commissioner-conditional-group');
    const pickSelect = document.getElementById('commissioner-conditional-pick');
    const ownerSelect = document.getElementById('commissioner-conditional-owner');
    const details = document.getElementById('commissioner-conditional-details');
    const submit = document.querySelector('#commissioner-conditional-form button[type="submit"]');
    if (!groupSelect || !pickSelect || !ownerSelect || !details) return;

    commissionerConditionalPicks = null;
    groupSelect.innerHTML = '<option value="">Loading unresolved conditions…</option>';
    groupSelect.disabled = true;
    pickSelect.disabled = true;
    ownerSelect.disabled = true;
    details.hidden = true;
    if (submit) submit.disabled = true;

    try {
        const result = await commissionerRequest('conditional_picks');
        commissionerConditionalPicks = (result.picks || []).map(pick => {
            const published = (data?.draft_picks || []).find(candidate =>
                commissionerConditionalPickId(candidate) === commissionerConditionalPickId(pick)
            );
            return published?.pick_number ? { ...pick, pick_number: published.pick_number } : pick;
        });
        setCommissionerStatus('commissioner-conditional-status', '');
        populateCommissionerConditionals();
    } catch (error) {
        groupSelect.innerHTML = '<option value="">Unable to load conditions</option>';
        setCommissionerStatus('commissioner-conditional-status', error.message, 'error');
    }
}

function populateCommissionerControls() {
    populateCommissionerTeamSelect('commissioner-add-team', 'Select destination team');
    populateCommissionerTeamSelect('commissioner-release-team', 'Select roster');
    populateCommissionerTeamSelect('commissioner-score-team', 'Select scoring team');
    populateCommissionerReleasePlayers();
    populateCommissionerScorePlayers();
    populateCommissionerTrades();
    populateCommissionerConditionals();

    const seasonInput = document.getElementById('commissioner-score-season');
    const weekInput = document.getElementById('commissioner-score-week');
    if (seasonInput && !seasonInput.value) seasonInput.value = data?.season || LIVE_SEASON;
    if (weekInput && !weekInput.value) {
        weekInput.value = Math.max(1, Math.min(data?.current_week || 1, 18));
    }
}

async function commissionerRequest(adminAction, payload = {}) {
    if (!isCommissioner()) throw new Error('Commissioner access required');
    const response = await fetch(MANAGE_CONFIG.apiUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            action: 'admin_adjust',
            admin_action: adminAction,
            team: manageState.team,
            password: manageState.password,
            ...payload
        })
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || !result.success) {
        throw new Error(result.error || 'Commissioner action failed');
    }
    return result;
}

function saveCommissionerWorkbook(result) {
    if (!result.content_base64 || !result.filename) {
        throw new Error('The workbook response was incomplete');
    }
    const binary = atob(result.content_base64);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
        bytes[index] = binary.charCodeAt(index);
    }
    const blob = new Blob([bytes], {
        type: result.mime_type || 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = result.filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

async function downloadCommissionerWorkbook(adminAction, buttonId) {
    const button = document.getElementById(buttonId);
    if (button) button.disabled = true;
    setCommissionerStatus('commissioner-download-status', 'Building fresh workbook…');
    try {
        const payload = adminAction === 'download_draft_board'
            ? { season: LIVE_SEASON }
            : {};
        const result = await commissionerRequest(adminAction, payload);
        saveCommissionerWorkbook(result);
        setCommissionerStatus(
            'commissioner-download-status',
            `${result.filename} downloaded.`,
            'success'
        );
    } catch (error) {
        setCommissionerStatus('commissioner-download-status', error.message, 'error');
    } finally {
        if (button) button.disabled = false;
    }
}

function commissionerAuditDescription(entry) {
    const player = typeof entry.player === 'object' ? entry.player?.name : entry.player;
    if (entry.type === 'admin_add') return `Added ${player || 'player'} to ${entry.team || 'team'}`;
    if (entry.type === 'admin_release') return `Released ${player || 'player'} from ${entry.team || 'team'}`;
    if (entry.type === 'admin_reverse_trade') {
        return `Reversed trade ${entry.trade_id || ''} · ${entry.proposer || 'team'} ↔ ${entry.partner || 'team'}`;
    }
    if (entry.type === 'admin_resolve_conditional_pick') {
        return `${entry.winning_pick_id || 'Conditional pick'} conveyed to ${entry.final_owner || 'team'} · ${entry.condition || 'Condition resolved'}`;
    }
    if (entry.type === 'admin_score_adjustment') {
        const points = Number(entry.points);
        const pointLabel = Number.isFinite(points) ? `${points >= 0 ? '+' : ''}${points}` : '—';
        return `${pointLabel} points · ${entry.team || 'team'} · ${player || 'player'} · ${entry.season || '—'} Week ${entry.week || '—'}`;
    }
    return String(entry.type || 'Commissioner action').replace(/_/g, ' ');
}

function renderCommissionerAudit(entries) {
    const container = document.getElementById('commissioner-audit-log');
    if (!container) return;
    if (!entries.length) {
        container.innerHTML = '<div class="commissioner-audit-empty">No commissioner actions recorded yet.</div>';
        return;
    }
    const labels = {
        admin_add: 'Player Added',
        admin_release: 'Player Released',
        admin_reverse_trade: 'Trade Reversed',
        admin_resolve_conditional_pick: 'Conditional Resolved',
        admin_score_adjustment: 'Score Adjusted'
    };
    container.innerHTML = `<div class="commissioner-audit-list">${entries.map(entry => {
        const title = labels[entry.type] || 'Commissioner Action';
        const reason = entry.reason ? `<p>${escapeHtml(entry.reason)}</p>` : '<p>No reason provided.</p>';
        return `<article class="commissioner-audit-entry">
            <strong>${escapeHtml(title)}</strong>
            <div><p>${escapeHtml(commissionerAuditDescription(entry))}</p>${reason}</div>
            <time datetime="${escapeHtml(entry.timestamp || '')}">${escapeHtml(formatDate(entry.timestamp))}</time>
        </article>`;
    }).join('')}</div>`;
}

async function loadCommissionerAuditLog() {
    const container = document.getElementById('commissioner-audit-log');
    if (!container || !isCommissioner()) return;
    container.innerHTML = '<div class="commissioner-audit-empty">Loading audit log…</div>';
    try {
        const result = await commissionerRequest('audit_log', { limit: 50 });
        renderCommissionerAudit(result.entries || []);
    } catch (error) {
        container.innerHTML = `<div class="commissioner-audit-empty">${escapeHtml(error.message)}</div>`;
    }
}

function setCommissionerStatus(id, message, tone = '') {
    const status = document.getElementById(id);
    if (!status) return;
    status.className = `submit-status${tone ? ` ${tone}` : ''}`;
    status.textContent = message;
}

function applyCommissionerMutationLocally(adminAction, payload, result = {}) {
    if (adminAction === 'release') {
        const raw = data?.rosters?.[payload.target_team];
        if (Array.isArray(raw)) {
            data.rosters[payload.target_team] = raw.filter(player => player.name !== payload.player);
        } else if (raw && typeof raw === 'object') {
            data.rosters[payload.target_team] = {
                ...raw,
                roster: (raw.roster || []).filter(player => player.name !== payload.player),
                taxi_squad: (raw.taxi_squad || []).filter(player => player.name !== payload.player),
                taxi: (raw.taxi || []).filter(player => player.name !== payload.player)
            };
        }
    } else if (adminAction === 'add') {
        const raw = data?.rosters?.[payload.target_team];
        const player = { ...payload.player };
        if (Array.isArray(raw)) {
            raw.push(player);
        } else if (raw && typeof raw === 'object') {
            const key = player.taxi ? 'taxi_squad' : 'roster';
            raw[key] = [...(raw[key] || []), player];
        } else if (data?.rosters) {
            data.rosters[payload.target_team] = [player];
        }
    } else if (adminAction === 'resolve_conditional_pick') {
        const resolvedByKey = new Map((result.resolved_picks || []).map(pick => [
            `${pick.year}|${pick.draft_type || 'offseason'}|${pick.round}|${pick.original_team}`,
            pick
        ]));
        const applyResolution = pick => {
            if (pick.condition !== payload.condition) return pick;
            const key = `${pick.year}|${pick.draft_type || 'offseason'}|${pick.round}|${pick.original_team}`;
            const resolved = resolvedByKey.get(key);
            const updated = { ...pick };
            if (resolved) {
                if (resolved.selected && resolved.previous_owner !== resolved.current_owner) {
                    updated.previous_owners = [...(updated.previous_owners || [])];
                    if (resolved.previous_owner && !updated.previous_owners.includes(resolved.previous_owner)) {
                        updated.previous_owners.push(resolved.previous_owner);
                    }
                }
                updated.current_owner = resolved.current_owner;
            }
            delete updated.condition;
            delete updated.conditional_claim;
            return updated;
        };
        data.draft_picks = (data?.draft_picks || []).map(applyResolution);
        sharedData.draft_picks = data.draft_picks;
        commissionerConditionalPicks = (commissionerConditionalPicks || []).map(applyResolution);
        (data?.upcoming_drafts || []).forEach(draft => {
            (draft.rounds || []).forEach(round => {
                round.picks = (round.picks || []).map(applyResolution);
            });
        });
    } else if (adminAction === 'reverse_trade') {
        const trade = data?.pending_trades?.find(item => item.id === payload.trade_id);
        if (trade) {
            const takePlayer = (team, name) => {
                const raw = data?.rosters?.[team];
                if (Array.isArray(raw)) {
                    const index = raw.findIndex(player => player.name === name);
                    return index >= 0 ? raw.splice(index, 1)[0] : null;
                }
                if (!raw || typeof raw !== 'object') return null;
                let found = null;
                for (const key of ['roster', 'taxi_squad', 'taxi']) {
                    const players = raw[key];
                    if (!Array.isArray(players)) continue;
                    const player = players.find(item => item.name === name);
                    if (player && !found) found = key === 'roster' ? player : { ...player, taxi: true };
                    raw[key] = players.filter(item => item.name !== name);
                }
                return found;
            };
            const addPlayer = (team, player) => {
                if (!player) return;
                const raw = data?.rosters?.[team];
                if (Array.isArray(raw)) {
                    raw.push(player);
                } else if (raw && typeof raw === 'object') {
                    const key = player.taxi ? 'taxi_squad' : 'roster';
                    raw[key] = [...(raw[key] || []), player];
                }
            };

            const toPartner = (trade.proposer_receives?.players || [])
                .map(name => takePlayer(trade.proposer, name));
            const toProposer = (trade.proposer_gives?.players || [])
                .map(name => takePlayer(trade.partner, name));
            toPartner.forEach(player => addPlayer(trade.partner, player));
            toProposer.forEach(player => addPlayer(trade.proposer, player));

            const reversePicks = (trade.proposer_receives?.picks || [])
                .map(id => [id, trade.proposer, trade.partner])
                .concat((trade.proposer_gives?.picks || []).map(id => [id, trade.partner, trade.proposer]));
            reversePicks.forEach(([id, fromTeam, toTeam]) => {
                const match = id.match(/^(\d{4})(?:-(offseason_taxi|waiver|waiver_taxi))?-R(\d+)-(.+)$/);
                if (!match) return;
                const pick = data?.draft_picks?.find(item => String(item.year) === match[1]
                    && (item.draft_type || 'offseason') === (match[2] || 'offseason')
                    && Number(item.round) === Number(match[3])
                    && item.original_team === match[4]
                    && item.current_owner === fromTeam);
                if (pick) pick.current_owner = toTeam;
            });

            trade.reversed_at = new Date().toISOString();
            trade.reversal_execution = 'done';
            data.transactions = [{
                type: 'admin_reverse_trade',
                trade_id: trade.id,
                team: manageState.team,
                proposer: trade.proposer,
                partner: trade.partner,
                proposer_gives: trade.proposer_gives,
                proposer_receives: trade.proposer_receives,
                message: `Reversed completed trade ${trade.id}`,
                admin: true,
                actor: manageState.team,
                reason: payload.reason,
                timestamp: trade.reversed_at
            }, ...(data.transactions || [])];
        }
    }

    ['home', 'teams', 'drafts', 'transactions'].forEach(view => viewFresh.delete(view));
    populateCommissionerControls();
}

async function submitCommissionerAction(form, statusId, adminAction, payload, confirmation) {
    if (!window.confirm(confirmation)) return null;
    const submit = form.querySelector('button[type="submit"]');
    if (submit) submit.disabled = true;
    setCommissionerStatus(statusId, 'Saving…');
    try {
        const result = await commissionerRequest(adminAction, payload);
        applyCommissionerMutationLocally(adminAction, payload, result);
        setCommissionerStatus(statusId, result.message || 'Action completed.', 'success');
        await loadCommissionerAuditLog();
        return result;
    } catch (error) {
        setCommissionerStatus(statusId, error.message, 'error');
        return null;
    } finally {
        if (submit) submit.disabled = false;
    }
}

function wireCommissionerForms() {
    const releaseTeam = document.getElementById('commissioner-release-team');
    const scoreTeam = document.getElementById('commissioner-score-team');
    const conditionalGroup = document.getElementById('commissioner-conditional-group');
    if (releaseTeam) releaseTeam.onchange = populateCommissionerReleasePlayers;
    if (scoreTeam) scoreTeam.onchange = populateCommissionerScorePlayers;
    if (conditionalGroup) {
        conditionalGroup.onchange = () => populateCommissionerConditionals(true);
    }
    document.getElementById('commissioner-audit-refresh').onclick = loadCommissionerAuditLog;
    document.getElementById('commissioner-download-rosters').onclick = () => {
        downloadCommissionerWorkbook('download_rosters', 'commissioner-download-rosters');
    };
    document.getElementById('commissioner-download-draft').onclick = () => {
        downloadCommissionerWorkbook('download_draft_board', 'commissioner-download-draft');
    };

    document.getElementById('commissioner-add-form').onsubmit = async event => {
        event.preventDefault();
        const form = event.currentTarget;
        const targetTeam = document.getElementById('commissioner-add-team').value;
        const player = {
            name: document.getElementById('commissioner-add-player').value.trim(),
            position: document.getElementById('commissioner-add-position').value,
            nfl_team: document.getElementById('commissioner-add-nfl-team').value.trim().toUpperCase(),
            taxi: document.getElementById('commissioner-add-taxi').checked
        };
        const payload = {
            target_team: targetTeam,
            player,
            reason: document.getElementById('commissioner-add-reason').value.trim()
        };
        const result = await submitCommissionerAction(
            form,
            'commissioner-add-status',
            'add',
            payload,
            `Add ${player.name} to ${targetTeam}${player.taxi ? ' (taxi)' : ''}?`
        );
        if (result) {
            document.getElementById('commissioner-add-player').value = '';
            document.getElementById('commissioner-add-nfl-team').value = '';
            document.getElementById('commissioner-add-reason').value = '';
            document.getElementById('commissioner-add-taxi').checked = false;
        }
    };

    document.getElementById('commissioner-release-form').onsubmit = async event => {
        event.preventDefault();
        const form = event.currentTarget;
        const payload = {
            target_team: document.getElementById('commissioner-release-team').value,
            player: document.getElementById('commissioner-release-player').value,
            reason: document.getElementById('commissioner-release-reason').value.trim()
        };
        const result = await submitCommissionerAction(
            form,
            'commissioner-release-status',
            'release',
            payload,
            `Release ${payload.player} from ${payload.target_team}?`
        );
        if (result) document.getElementById('commissioner-release-reason').value = '';
    };

    document.getElementById('commissioner-reverse-form').onsubmit = async event => {
        event.preventDefault();
        const form = event.currentTarget;
        const payload = {
            trade_id: document.getElementById('commissioner-reverse-trade').value,
            reason: document.getElementById('commissioner-reverse-reason').value.trim()
        };
        const result = await submitCommissionerAction(
            form,
            'commissioner-reverse-status',
            'reverse_trade',
            payload,
            `Reverse completed trade ${payload.trade_id}? This transfers its players and picks back to their prior teams.`
        );
        if (result) document.getElementById('commissioner-reverse-reason').value = '';
    };

    document.getElementById('commissioner-conditional-form').onsubmit = async event => {
        event.preventDefault();
        const form = event.currentTarget;
        const groupSelect = document.getElementById('commissioner-conditional-group');
        const pickSelect = document.getElementById('commissioner-conditional-pick');
        const ownerSelect = document.getElementById('commissioner-conditional-owner');
        const payload = {
            condition: groupSelect.value,
            winning_pick_id: pickSelect.value,
            final_owner: ownerSelect.value,
            reason: document.getElementById('commissioner-conditional-reason').value.trim()
        };
        const result = await submitCommissionerAction(
            form,
            'commissioner-conditional-status',
            'resolve_conditional_pick',
            payload,
            `Resolve ${pickSelect.options[pickSelect.selectedIndex]?.text || payload.winning_pick_id} to ${payload.final_owner}? Other candidate picks keep their current owners.`
        );
        if (result) {
            document.getElementById('commissioner-conditional-reason').value = '';
            populateCommissionerConditionals();
        }
    };

    document.getElementById('commissioner-score-form').onsubmit = async event => {
        event.preventDefault();
        const form = event.currentTarget;
        const payload = {
            season: Number(document.getElementById('commissioner-score-season').value),
            week: Number(document.getElementById('commissioner-score-week').value),
            target_team: document.getElementById('commissioner-score-team').value,
            player: document.getElementById('commissioner-score-player').value.trim(),
            points: Number(document.getElementById('commissioner-score-points').value),
            reason: document.getElementById('commissioner-score-reason').value.trim()
        };
        const pointLabel = `${payload.points >= 0 ? '+' : ''}${payload.points}`;
        const result = await submitCommissionerAction(
            form,
            'commissioner-score-status',
            'score_adjustment',
            payload,
            `Apply ${pointLabel} points to ${payload.player} (${payload.target_team}) for ${payload.season} Week ${payload.week}?`
        );
        if (result) {
            document.getElementById('commissioner-score-player').value = '';
            document.getElementById('commissioner-score-points').value = '';
            document.getElementById('commissioner-score-reason').value = '';
        }
    };
}

function initCommissionerTools() {
    if (!isCommissioner()) return;
    populateCommissionerControls();
    wireCommissionerForms();
    loadCommissionerConditionalPicks();
    loadCommissionerAuditLog();
}

function matchupTeamCode(side) {
    return typeof side === 'object' ? side?.abbrev : side;
}

function findMyTeamMatchup(team) {
    if (!data || data.current_week > 17) return null;

    const schedule = [...(data.schedule || [])].sort((a, b) => a.week - b.week);
    const requestedWeek = data.current_week > 0 ? data.current_week : schedule[0]?.week;
    if (!requestedWeek) return null;

    const candidateWeeks = [
        requestedWeek,
        ...schedule.filter(week => week.week > requestedWeek).map(week => week.week)
    ];

    for (const weekNumber of [...new Set(candidateWeeks)]) {
        const scoredWeek = data.weeks?.find(week => week.week === weekNumber);
        const scheduledWeek = schedule.find(week => week.week === weekNumber);
        const matchups = scoredWeek?.matchups?.length
            ? scoredWeek.matchups
            : (scheduledWeek?.matchups || []);
        const matchup = matchups.find(item =>
            matchupTeamCode(item.team1) === team || matchupTeamCode(item.team2) === team
        );
        if (matchup) return { week: weekNumber, matchup };
    }

    return null;
}

function lineupDashboardStatus(team) {
    const week = data?.lineup_week || data?.current_week;
    if (!week || week > 17) {
        return {
            tone: 'neutral',
            label: 'Lineups are not open',
            detail: 'The Week 1 lineup will appear when the schedule is published.'
        };
    }

    const lineup = data.lineups?.[team] || {};
    const requiredSlots = Object.values(LINEUP_CONFIG.positions)
        .reduce((total, position) => total + position.max, 0);
    const selectedSlots = Object.keys(LINEUP_CONFIG.positions)
        .reduce((total, position) => total + (Array.isArray(lineup[position]) ? lineup[position].length : 0), 0);
    const submitted = Boolean(lineup.submitted_at) || selectedSlots === requiredSlots;

    if (submitted) {
        return {
            tone: 'success',
            label: `Week ${week} lineup submitted`,
            detail: lineup.submitted_at
                ? `Last submitted ${formatDate(lineup.submitted_at)}`
                : `${selectedSlots} of ${requiredSlots} starter slots filled.`
        };
    }

    return {
        tone: 'warning',
        label: `Week ${week} lineup not submitted`,
        detail: `${selectedSlots} of ${requiredSlots} starter slots filled.`
    };
}

function renderLineupReminder() {
    const banner = document.getElementById('lineup-reminder-banner');
    const title = document.getElementById('lineup-reminder-title');
    const detail = document.getElementById('lineup-reminder-detail');
    if (!banner || !title || !detail) return;

    const lineupWeek = data?.lineup_week || data?.current_week;
    const isLiveSeason = data
        && data.season === LIVE_SEASON
        && !data.is_historical
        && lineupWeek > 0
        && lineupWeek <= 17;
    if (!manageState.team || !manageState.password || !isLiveSeason) {
        banner.hidden = true;
        return;
    }

    const status = lineupDashboardStatus(manageState.team);
    if (status.tone !== 'warning') {
        banner.hidden = true;
        return;
    }

    const kickoffDates = Object.values(data.kickoffs || {})
        .map(value => new Date(value))
        .filter(value => !Number.isNaN(value.getTime()));
    const firstKickoff = kickoffDates.length
        ? new Date(Math.min(...kickoffDates.map(value => value.getTime())))
        : null;

    title.textContent = status.label;
    detail.textContent = firstKickoff
        ? `${status.detail} The first game locks ${formatDate(firstKickoff.toISOString())}.`
        : `${status.detail} Submit it before the first game kicks off.`;
    banner.hidden = false;
}

function draftDashboardStatus(team) {
    const state = nflDraftState.serverState;
    if (!state) {
        return { tone: 'neutral', label: 'Checking Draft Challenge…', detail: 'Loading your entry status.' };
    }
    if (state.unavailable) {
        return { tone: 'warning', label: 'Status unavailable', detail: 'The Draft Challenge service could not be reached.' };
    }

    const submitted = Boolean(state.submissions?.[team]?.submitted_at);
    if (state.locked) {
        const score = state.scores?.[team];
        if (score) {
            return {
                tone: 'success',
                label: `${score.points} points`,
                detail: `${score.correct} correct first-round picks.`
            };
        }
        return {
            tone: submitted ? 'success' : 'neutral',
            label: submitted ? 'Entry submitted' : 'No entry submitted',
            detail: 'The Draft Challenge is locked.'
        };
    }

    return {
        tone: submitted ? 'success' : 'warning',
        label: submitted ? 'Picks submitted' : 'Picks not submitted',
        detail: formatCountdown(state.lock_time)
    };
}

function myTeamActivity(team) {
    return (data.recent_transactions || data.transactions || [])
        .filter(transaction => txInvolvesTeam(transaction, team))
        .slice(0, 5)
        .map(transaction => {
            const { dateStr, cleanMessage } = getTransactionDate(transaction);
            let message = cleanMessage || formatTransactionMessage(transaction);
            if (!message && transaction.player) {
                const player = typeof transaction.player === 'object'
                    ? transaction.player.name
                    : transaction.player;
                message = `${getEffectiveTxType(transaction).replace(/_/g, ' ')}: ${player}`;
            }
            return {
                date: dateStr,
                type: getEffectiveTxType(transaction).replace(/_/g, ' '),
                message: message || 'Roster updated'
            };
        });
}

function myTeamSummary(team) {
    const standings = Array.isArray(data?.standings) ? data.standings : [];
    const standingIndex = standings.findIndex(item => item.abbrev === team);
    const standing = standingIndex >= 0 ? standings[standingIndex] : {};
    const teamStats = data?.team_stats?.[team] || {};
    const gamesPlayed = (standing.wins || 0) + (standing.losses || 0) + (standing.ties || 0);
    const ppg = Number.isFinite(teamStats.ppg)
        ? teamStats.ppg
        : (gamesPlayed ? (standing.points_for || 0) / gamesPlayed : 0);
    const streak = teamStats.streak?.type && teamStats.streak?.count
        ? `${teamStats.streak.type}${teamStats.streak.count}`
        : '—';

    return {
        rank: standingIndex >= 0 ? standingIndex + 1 : '—',
        totalTeams: Math.max(data?.teams?.length || 0, standings.length) || 10,
        ppg,
        streak
    };
}

function renderMyTeamDashboard() {
    const container = document.getElementById('my-team-dashboard');
    const intro = document.getElementById('my-team-dashboard-intro');
    const dashboardGrid = document.getElementById('my-team-dashboard-grid');
    const team = manageState.team;
    if (!container || !intro || !dashboardGrid || !team || !data) return;

    const teamInfo = data.teams?.find(item => item.abbrev === team) || { abbrev: team, name: team };
    const summary = myTeamSummary(team);
    const summaryText = `Standings: ${summary.rank}/${summary.totalTeams}, PPG: ${summary.ppg.toFixed(1)}, Streak: ${summary.streak}`;
    const next = findMyTeamMatchup(team);
    let matchupHtml = `
        <div class="my-team-empty">The next matchup will appear when the schedule is available.</div>`;
    let matchupAction = '';
    if (next) {
        const mineIsTeam1 = matchupTeamCode(next.matchup.team1) === team;
        const mine = mineIsTeam1 ? next.matchup.team1 : next.matchup.team2;
        const opponent = mineIsTeam1 ? next.matchup.team2 : next.matchup.team1;
        const opponentCode = matchupTeamCode(opponent) || 'TBD';
        const opponentInfo = data.teams?.find(item => item.abbrev === opponentCode) || {};
        const opponentName = typeof opponent === 'object'
            ? (opponent.team_name || opponent.name || opponentInfo.name || opponentCode)
            : (opponentInfo.name || opponentCode);
        const mineScore = typeof mine === 'object' ? mine.total_score : null;
        const opponentScore = typeof opponent === 'object' ? opponent.total_score : null;
        const scoreHtml = Number.isFinite(mineScore) && Number.isFinite(opponentScore)
            ? `<div class="my-team-matchup-score">${mineScore.toFixed(1)} <span>–</span> ${opponentScore.toFixed(1)}</div>`
            : '<div class="my-team-card-detail">Scores not yet available</div>';

        matchupHtml = `
            <div class="my-team-matchup-opponent">
                ${teamAvatar(opponentCode, opponentName, 'avatar-lg', opponentInfo.avatar || currentTeamAvatar(opponentCode))}
                <div>
                    <span>vs.</span>
                    <strong>${escapeHtml(opponentName)}</strong>
                    <small>${escapeHtml(opponentCode)}</small>
                </div>
            </div>
            ${scoreHtml}`;
        matchupAction = `
            <button type="button" class="lineup-btn secondary my-team-card-action" data-my-team-action="matchup" data-week="${next.week}">View Matchup</button>`;
    }

    const lineupStatus = lineupDashboardStatus(team);
    const relevantTrades = (data.pending_trades || []).filter(trade =>
        trade.status === 'pending' && (trade.proposer === team || trade.partner === team)
    );
    const tradesToReview = relevantTrades.filter(trade => trade.partner === team).length;
    const tradeDetail = tradesToReview
        ? `${tradesToReview} ${tradesToReview === 1 ? 'trade needs' : 'trades need'} your response.`
        : (relevantTrades.length ? 'Waiting for the other manager.' : 'No trades need your attention.');
    const draftStatus = draftDashboardStatus(team);
    const activity = myTeamActivity(team);
    const activityHtml = activity.length
        ? activity.map(item => `
            <div class="my-team-activity-row">
                <div>
                    <span class="my-team-activity-type">${escapeHtml(item.type)}</span>
                    <p>${escapeHtml(item.message)}</p>
                </div>
                <time>${escapeHtml(item.date)}</time>
            </div>`).join('')
        : '<div class="my-team-empty">No recent roster activity.</div>';

    intro.innerHTML = `
        <div>
            <span class="my-team-eyebrow">${escapeHtml(team)}</span>
            <h3 id="my-team-dashboard-name">${escapeHtml(teamInfo.name || team)}</h3>
            <p>${escapeHtml(summaryText)}</p>
        </div>
        <div class="my-team-dashboard-identity">
            <div id="my-team-dashboard-avatar">
                ${teamAvatar(team, teamInfo.name, 'avatar-xl', teamInfo.avatar || currentTeamAvatar(team))}
            </div>
            <button type="button" class="lineup-btn secondary my-team-edit-btn" id="my-team-edit-btn" aria-expanded="false" aria-controls="my-team-settings">Edit</button>
        </div>`;

    dashboardGrid.innerHTML = `
            <section class="my-team-card my-team-matchup-card">
                <div class="my-team-card-heading">
                    <span class="my-team-card-label">Next Matchup</span>
                    ${next ? `<span class="my-team-week-pill">Week ${next.week}</span>` : ''}
                </div>
                ${matchupHtml}
                ${matchupAction}
            </section>
            <section class="my-team-card">
                <div class="my-team-card-heading">
                    <span class="my-team-card-label">Lineup</span>
                    <span class="my-team-status-dot ${lineupStatus.tone}" aria-hidden="true"></span>
                </div>
                <strong class="my-team-card-value">${escapeHtml(lineupStatus.label)}</strong>
                <p class="my-team-card-detail">${escapeHtml(lineupStatus.detail)}</p>
                <button type="button" class="lineup-btn primary my-team-card-action" data-my-team-action="lineup">Set Lineup</button>
            </section>
            <section class="my-team-card">
                <div class="my-team-card-heading">
                    <span class="my-team-card-label">Pending Trades</span>
                    <span class="my-team-status-dot ${relevantTrades.length ? 'warning' : 'success'}" aria-hidden="true"></span>
                </div>
                <strong class="my-team-card-value">${relevantTrades.length}</strong>
                <p class="my-team-card-detail">${escapeHtml(tradeDetail)}</p>
                <button type="button" class="lineup-btn secondary my-team-card-action" data-my-team-action="pending">View Trades</button>
            </section>
            <section class="my-team-card">
                <div class="my-team-card-heading">
                    <span class="my-team-card-label">Draft Challenge</span>
                    <span class="my-team-status-dot ${draftStatus.tone}" aria-hidden="true"></span>
                </div>
                <strong class="my-team-card-value">${escapeHtml(draftStatus.label)}</strong>
                <p class="my-team-card-detail">${escapeHtml(draftStatus.detail)}</p>
                <button type="button" class="lineup-btn secondary my-team-card-action" data-my-team-action="draft">Open Challenge</button>
            </section>
            <section class="my-team-card my-team-activity-card">
                <div class="my-team-card-heading">
                    <span class="my-team-card-label">Recent Roster Activity</span>
                </div>
                <div class="my-team-activity-list">${activityHtml}</div>
            </section>`;

    wireMyTeamDashboard();
}

function wireMyTeamDashboard() {
    const editButton = document.getElementById('my-team-edit-btn');
    const settings = document.getElementById('my-team-settings');
    if (editButton && settings) {
        const syncEditButton = () => {
            const isOpen = !settings.hidden;
            editButton.setAttribute('aria-expanded', String(isOpen));
            editButton.textContent = isOpen ? 'Done' : 'Edit';
        };
        syncEditButton();
        editButton.onclick = () => {
            settings.hidden = !settings.hidden;
            syncEditButton();
            if (!settings.hidden) document.getElementById('new-team-name')?.focus();
        };
    }

    document.querySelectorAll('[data-my-team-action]').forEach(button => {
        button.onclick = () => {
            const action = button.dataset.myTeamAction;
            if (action === 'lineup' || action === 'pending') {
                switchTxTab(action);
                return;
            }
            if (action === 'matchup') {
                const week = parseInt(button.dataset.week, 10);
                history.pushState(null, '', `#matchups/week/${week}`);
                navigateToView('matchups', 'week', String(week));
                return;
            }
            if (action === 'draft') {
                history.pushState(null, '', '#drafts/challenge');
                navigateToView('drafts', 'challenge');
            }
        };
    });
}

async function refreshMyTeamDraftStatus(team) {
    nflDraftState.serverState = null;
    renderMyTeamDashboard();
    await loadNflDraftState();
    if (manageState.team === team) renderMyTeamDashboard();
}

function resetManageState() {
    manageState = {
        team: null,
        password: null,
        selectedTaxiPlayer: null,
        selectedReleasePlayer: null,
        selectedFaPlayer: null,
        selectedFaReleasePlayer: null,
        selectedReleaseOnlyPlayer: null,
        tradeGivePlayers: [],
        tradeGivePicks: [],
        tradeReceivePlayers: [],
        tradeReceivePicks: [],
        tradeConditions: {},
        tradePartner: null,
        actionStatusId: null
    };
    depthChartState = { team: null, order: {}, baseline: {} };
    closeRosterAction();
}

function switchTxTab(tabName) {
    if (tabName === 'commissioner' && !isCommissioner()) tabName = 'dashboard';
    const tradeTabs = new Set(['trade', 'pending', 'tradeblock']);
    const rosterTabs = new Set(['depth', 'taxi', 'release']);
    const primaryTabName = tradeTabs.has(tabName)
        ? 'trade'
        : (rosterTabs.has(tabName) ? 'depth' : tabName);

    if (tabName !== 'depth') closeRosterAction();

    const primaryTab = document.querySelector(`.tx-tab[data-tab="${primaryTabName}"]`);
    setActiveTab(primaryTab?.closest('[role="tablist"]'), primaryTab);
    if (primaryTabName === 'trade') primaryTab?.setAttribute('aria-controls', `tx-${tabName}`);

    document.querySelectorAll('.tx-content').forEach(panel => {
        const active = panel.id === `tx-${tabName}`;
        panel.classList.toggle('active', active);
        panel.hidden = !active;
    });

    const tradeNav = document.getElementById('trade-center-tabs');
    if (tradeNav) tradeNav.hidden = !tradeTabs.has(tabName);
    const activeTradeTab = document.querySelector(`[data-trade-tab="${tabName}"]`);
    if (tradeTabs.has(tabName)) {
        setActiveTab(tradeNav, activeTradeTab);
    }
    
    if (tabName === 'trade') {
        renderTradeTab();
    }
    if (tabName === 'pending') {
        renderPendingTrades();
    }
    if (tabName === 'tradeblock') {
        renderTradeBlockTab();
    }
    if (tabName === 'dashboard') {
        renderMyTeamDashboard();
    }
    if (tabName === 'commissioner') {
        initCommissionerTools();
    }

    // Re-render on entry so the depth chart reflects any roster move made in
    // another tab (activation, release, trade) since it was last shown.
    if (tabName === 'depth') {
        renderDepthChartTab();
    }
}

function normalizeTeamRoster(rawRoster) {
    if (Array.isArray(rawRoster)) {
        const roster = rawRoster.filter(player => !player.taxi);
        const taxiSquad = rawRoster.filter(player => player.taxi);
        return { roster, taxi_squad: taxiSquad, taxi: taxiSquad };
    }

    if (rawRoster && typeof rawRoster === 'object') {
        const rosterSource = Array.isArray(rawRoster.roster) ? rawRoster.roster : [];
        const nestedTaxi = Array.isArray(rawRoster.taxi_squad)
            ? rawRoster.taxi_squad
            : (Array.isArray(rawRoster.taxi) ? rawRoster.taxi : []);
        const roster = rosterSource.filter(player => !player.taxi);
        const taxiByName = new Map();
        [...rosterSource.filter(player => player.taxi), ...nestedTaxi].forEach(player => {
            taxiByName.set(player.name, player);
        });
        const taxiSquad = [...taxiByName.values()];
        return { roster, taxi_squad: taxiSquad, taxi: taxiSquad };
    }

    return { roster: [], taxi_squad: [], taxi: [] };
}

function getTeamData(abbrev) {
    if (!data) return null;
    
    // Prefer data.rosters (updated by transactions) over weekly roster data
    // Supports both a flat roster with taxi flags and nested roster/taxi arrays.
    if (data.rosters && data.rosters[abbrev]) {
        const normalizedRoster = normalizeTeamRoster(data.rosters[abbrev]);
        // Get team name from data.teams or standings
        const teamInfo = data.teams?.find(t => t.abbrev === abbrev) || 
                         data.standings?.find(t => t.abbrev === abbrev) || {};
        return {
            abbrev: abbrev,
            name: teamInfo.name || abbrev,
            owner: teamInfo.owner || '',
            ...normalizedRoster
        };
    }
    
    // Fallback to weekly roster data
    if (!data.weeks || data.weeks.length === 0) return null;
    
    // Find the highest week number (weeks may not be sorted numerically)
    const latestWeek = data.weeks.reduce((max, week) => 
        (week.week > max.week) ? week : max, data.weeks[0]);
    
    if (!latestWeek || !latestWeek.teams) return null;
    const teamData = latestWeek.teams.find(t => t.abbrev === abbrev);
    if (!teamData) return null;

    return {
        ...teamData,
        ...normalizeTeamRoster({
            roster: teamData.roster,
            taxi_squad: teamData.taxi_squad || teamData.taxi
        })
    };
}

function renderTaxiTab() {
    const teamData = getTeamData(manageState.team);
    if (!teamData) return;
    
    const taxiList = document.getElementById('taxi-players');
    const taxiSquad = teamData.taxi_squad || [];
    
    if (taxiSquad.length === 0) {
        taxiList.innerHTML = '<p class="no-pending-trades">No players on taxi squad</p>';
        return;
    }
    
    taxiList.innerHTML = sortRosterByPosition(taxiSquad).map(txPlayerRowHtml).join('');
    
    // Add click handlers
    taxiList.querySelectorAll('.tx-player').forEach(el => {
        el.onclick = () => selectTaxiPlayer(el.dataset.name, el.dataset.position);
    });
    
    document.getElementById('taxi-release-section').style.display = 'none';
    document.getElementById('taxi-actions').style.display = 'none';
    
    // Set up submit handler
    document.getElementById('taxi-submit-btn').onclick = submitTaxiActivation;
}

function setTransactionPlayerSelection(selector, name) {
    document.querySelectorAll(selector).forEach(row => {
        const selected = row.dataset.name === name;
        row.classList.toggle('selected', selected);
        row.querySelector('.tx-player-select')?.setAttribute('aria-pressed', String(selected));
    });
}

function selectTaxiPlayer(name, position) {
    setTransactionPlayerSelection('#taxi-players .tx-player', name);
    
    manageState.selectedTaxiPlayer = { name, position };
    manageState.selectedReleasePlayer = null;
    
    // Show release options
    renderTaxiReleaseOptions(position);
}

function renderTaxiReleaseOptions(position) {
    const teamData = getTeamData(manageState.team);
    const roster = teamData.roster.filter(p => p.position === position);
    
    const releaseSection = document.getElementById('taxi-release-section');
    const releaseList = document.getElementById('taxi-release-players');
    
    if (roster.length === 0) {
        releaseList.innerHTML = `<p>No ${position} players on active roster to release</p>`;
    } else {
        releaseList.innerHTML = roster.map(txPlayerRowHtml).join('');

        releaseList.querySelectorAll('.tx-player').forEach(el => {
            el.onclick = () => selectTaxiReleasePlayer(el.dataset.name);
        });
    }
    
    releaseSection.style.display = 'block';
}

function selectTaxiReleasePlayer(name) {
    setTransactionPlayerSelection('#taxi-release-players .tx-player', name);
    
    manageState.selectedReleasePlayer = name;
    
    // Show actions
    document.getElementById('taxi-actions').style.display = 'flex';
    document.getElementById('taxi-summary').textContent = 
        `Activated ${manageState.selectedTaxiPlayer.name}, released ${name}`;
}

function submitTaxiActivation() {
    // Get player info for confirmation display
    const taxiPlayer = manageState.selectedTaxiPlayer;
    const releasePlayer = manageState.selectedReleasePlayer;
    
    // Find full player objects for info display
    const teamData = getTeamData(manageState.team);
    const taxiPlayerFull = teamData.taxi.find(p => p.name === taxiPlayer.name);
    const releasePlayerFull = teamData.roster.find(p => p.name === releasePlayer);
    
    const content = 
        buildPlayerRow('Activate', 'add', taxiPlayer.name, `${taxiPlayer.position} • ${taxiPlayerFull?.nfl_team || 'From Taxi'}`) +
        buildPlayerRow('Release', 'drop', releasePlayer, `${releasePlayerFull?.position || ''} • ${releasePlayerFull?.nfl_team || ''}`);
    
    showConfirmModal({
        title: 'Confirm Taxi Activation',
        icon: '',
        content: content,
        warning: 'This action cannot be undone. The released player will be gone from your roster.',
        confirmText: 'Activate Player',
        onConfirm: () => executeTaxiActivation()
    });
}

async function executeTaxiActivation() {
    const statusEl = document.getElementById(manageState.actionStatusId || 'taxi-status');
    statusEl.className = 'submit-status loading';
    statusEl.textContent = 'Processing...';
    
    // Get optional comment
    const commentEl = document.getElementById('taxi-comment');
    const comment = commentEl ? commentEl.value.trim() : '';
    
    try {
        const response = await fetch(MANAGE_CONFIG.apiUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: 'taxi_activate',
                team: manageState.team,
                password: manageState.password,
                player_to_activate: manageState.selectedTaxiPlayer.name,
                player_to_release: manageState.selectedReleasePlayer,
                week: data.current_week,
                comment: comment,
                submitted_at: new Date().toISOString()
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            statusEl.className = 'submit-status success';
            statusEl.textContent = result.message;
            // Reload data
            setTimeout(() => loadData(null, { forceRefresh: true }), 2000);
        } else {
            statusEl.className = 'submit-status error';
            statusEl.textContent = result.error;
        }
    } catch (e) {
        statusEl.className = 'submit-status error';
        statusEl.textContent = 'Network error - please try again';
    }
}

function renderFaTab() {
    const faList = document.getElementById('fa-players');
    const faPool = data.fa_pool || [];
    
    if (faPool.length === 0) {
        faList.innerHTML = '<p class="no-pending-trades">No players in FA pool</p>';
        return;
    }
    
    // Get players who have already been picked up from transaction log
    const pickedUpPlayers = new Set();
    // Check transaction_log structure (from data/transaction_log.json via legacy export)
    if (data.transaction_log && data.transaction_log.transactions) {
        for (const txn of data.transaction_log.transactions) {
            if ((txn.type === 'fa_activation' || txn.type === 'taxi_activation') && txn.added) {
                pickedUpPlayers.add(txn.added.toLowerCase());
            }
        }
    }
    // Also check the transactions display structure for FA pool text mentions
    // Only check the current season's transactions
    if (data.transactions && Array.isArray(data.transactions)) {
        const currentSeasonTxns = data.transactions.find(s => 
            s.season === `${currentSeason} Season` || s.season === String(currentSeason)
        );
        if (currentSeasonTxns) {
            for (const week of (currentSeasonTxns.weeks || [])) {
                for (const txn of (week.transactions || [])) {
                    for (const item of (txn.items || [])) {
                        if (item.text && item.text.includes('from FA Pool')) {
                            // Extract player name: "Add/Added PLAYER from FA Pool"
                            const match = item.text.match(/Add(?:ed)? (?:(?:QB|RB|WR|TE|K|D\/ST) )?(.+?) (?:\(.+?\) )?from FA Pool/i);
                            if (match) {
                                pickedUpPlayers.add(match[1].toLowerCase());
                            }
                        }
                    }
                }
            }
        }
    }
    
    // Filter out players who have been picked up
    const availablePlayers = faPool.filter(player => {
        const isTaken = player.available === false || pickedUpPlayers.has(player.name.toLowerCase());
        return !isTaken;
    });
    
    if (availablePlayers.length === 0) {
        faList.innerHTML = '<p class="no-pending-trades">All FA pool players have been claimed</p>';
        return;
    }
    
    faList.innerHTML = sortRosterByPosition(availablePlayers).map(txPlayerRowHtml).join('');
    
    // Add click handlers only for available players
    faList.querySelectorAll('.tx-player:not(.unavailable)').forEach(el => {
        el.onclick = () => selectFaPlayer(el.dataset.name, el.dataset.position);
    });
    
    document.getElementById('fa-release-section').style.display = 'none';
    document.getElementById('fa-actions').style.display = 'none';
    
    document.getElementById('fa-submit-btn').onclick = submitFaActivation;
}

function selectFaPlayer(name, position) {
    setTransactionPlayerSelection('#fa-players .tx-player', name);
    
    manageState.selectedFaPlayer = { name, position };
    manageState.selectedFaReleasePlayer = null;
    
    renderFaReleaseOptions(position);
}

function renderFaReleaseOptions(position) {
    const teamData = getTeamData(manageState.team);
    const roster = teamData.roster.filter(p => p.position === position);
    
    const releaseSection = document.getElementById('fa-release-section');
    const releaseList = document.getElementById('fa-release-players');
    
    if (roster.length === 0) {
        releaseList.innerHTML = `<p>No ${position} players on active roster to release</p>`;
    } else {
        releaseList.innerHTML = roster.map(txPlayerRowHtml).join('');

        releaseList.querySelectorAll('.tx-player').forEach(el => {
            el.onclick = () => selectFaReleasePlayer(el.dataset.name);
        });
    }
    
    releaseSection.style.display = 'block';
}

function selectFaReleasePlayer(name) {
    setTransactionPlayerSelection('#fa-release-players .tx-player', name);
    
    manageState.selectedFaReleasePlayer = name;
    
    document.getElementById('fa-actions').style.display = 'flex';
    document.getElementById('fa-summary').textContent = 
        `Added ${manageState.selectedFaPlayer.name} from FA Pool, released ${name}`;
}

function submitFaActivation() {
    // Get player info for confirmation display
    const faPlayer = manageState.selectedFaPlayer;
    const releasePlayer = manageState.selectedFaReleasePlayer;
    
    // Find full player objects for info display
    const teamData = getTeamData(manageState.team);
    const releasePlayerFull = teamData.roster.find(p => p.name === releasePlayer);
    
    const content = 
        buildPlayerRow('Add', 'add', faPlayer.name, `${faPlayer.position} • ${faPlayer.nfl_team} • FA Pool`) +
        buildPlayerRow('Release', 'drop', releasePlayer, `${releasePlayerFull?.position || ''} • ${releasePlayerFull?.nfl_team || ''}`);
    
    showConfirmModal({
        title: 'Confirm Free Agent Pickup',
        icon: '',
        content: content,
        warning: 'This action cannot be undone. The released player will be gone from your roster.',
        confirmText: 'Add Player',
        onConfirm: () => executeFaActivation()
    });
}

async function executeFaActivation() {
    const statusEl = document.getElementById('fa-status');
    statusEl.className = 'submit-status loading';
    statusEl.textContent = 'Processing...';
    
    // Get optional comment
    const commentEl = document.getElementById('fa-comment');
    const comment = commentEl ? commentEl.value.trim() : '';
    
    try {
        const response = await fetch(MANAGE_CONFIG.apiUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: 'fa_activate',
                team: manageState.team,
                password: manageState.password,
                player_to_add: manageState.selectedFaPlayer.name,
                player_to_release: manageState.selectedFaReleasePlayer,
                week: data.current_week,
                comment: comment,
                submitted_at: new Date().toISOString()
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            statusEl.className = 'submit-status success';
            statusEl.textContent = result.message;
            setTimeout(() => loadData(null, { forceRefresh: true }), 2000);
        } else {
            statusEl.className = 'submit-status error';
            statusEl.textContent = result.error;
        }
    } catch (e) {
        statusEl.className = 'submit-status error';
        statusEl.textContent = 'Network error - please try again';
    }
}

function renderReleaseTab() {
    const teamData = getTeamData(manageState.team);
    if (!teamData) return;

    const releaseList = document.getElementById('release-players');
    const roster = teamData.roster || [];

    if (roster.length === 0) {
        releaseList.innerHTML = '<p class="no-pending-trades">No players on active roster</p>';
        return;
    }

    releaseList.innerHTML = sortRosterByPosition(roster).map(txPlayerRowHtml).join('');

    releaseList.querySelectorAll('.tx-player').forEach(el => {
        el.onclick = () => selectReleasePlayer(el.dataset.name);
    });

    document.getElementById('release-actions').style.display = 'none';

    document.getElementById('release-submit-btn').onclick = submitRelease;
}

function selectReleasePlayer(name) {
    setTransactionPlayerSelection('#release-players .tx-player', name);

    manageState.selectedReleaseOnlyPlayer = name;

    document.getElementById('release-actions').style.display = 'flex';
    document.getElementById('release-summary').textContent = `Release ${name}`;
}

function submitRelease() {
    const releasePlayer = manageState.selectedReleaseOnlyPlayer;
    const teamData = getTeamData(manageState.team);
    const releasePlayerFull = teamData.roster.find(p => p.name === releasePlayer);

    const content = buildPlayerRow(
        'Drop', 'drop', releasePlayer,
        `${releasePlayerFull?.position || ''} • ${releasePlayerFull?.nfl_team || ''}`
    );

    showConfirmModal({
        title: 'Confirm Drop',
        icon: '',
        content: content,
        warning: 'This action cannot be undone. The released player will be gone from your roster.',
        confirmText: 'Drop Player',
        isDanger: true,
        onConfirm: () => executeRelease()
    });
}

async function executeRelease() {
    const statusEl = document.getElementById(manageState.actionStatusId || 'release-status');
    statusEl.className = 'submit-status loading';
    statusEl.textContent = 'Processing...';

    const commentEl = document.getElementById('release-comment');
    const comment = commentEl ? commentEl.value.trim() : '';

    try {
        const response = await fetch(MANAGE_CONFIG.apiUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: 'release',
                team: manageState.team,
                password: manageState.password,
                player_to_release: manageState.selectedReleaseOnlyPlayer,
                week: data.current_week,
                comment: comment,
                submitted_at: new Date().toISOString()
            })
        });

        const result = await response.json();

        if (result.success) {
            statusEl.className = 'submit-status success';
            statusEl.textContent = result.message;
            setTimeout(() => loadData(null, { forceRefresh: true }), 2000);
        } else {
            statusEl.className = 'submit-status error';
            statusEl.textContent = result.error;
        }
    } catch (e) {
        statusEl.className = 'submit-status error';
        statusEl.textContent = 'Network error - please try again';
    }
}

function startTradeForPlayer(playerName) {
    manageState.tradeGivePlayers = [playerName];
    manageState.tradeGivePicks = [];
    manageState.tradeReceivePlayers = [];
    manageState.tradeReceivePicks = [];
    manageState.tradeConditions = {};
    manageState.tradePartner = null;

    const comment = document.getElementById('trade-comment');
    const status = document.getElementById('trade-status');
    if (comment) comment.value = '';
    if (status) {
        status.className = 'submit-status';
        status.textContent = '';
    }

    switchTxTab('trade');
    document.getElementById('trade-partner-select')?.focus();
}

function renderTradeTab() {
    // Trade deadline logic:
    // - Before week 12: Trading open
    // - Week 12 Thursday through week 17: Trading blocked (deadline period)
    // - Week 18+ (offseason): Trading open
    const deadlineWarning = document.getElementById('trade-deadline-warning');
    const tradeDeadline = data.trade_deadline_week || 12;
    const isOffseason = Boolean(data.is_offseason) || data.current_week === 0 || data.current_week > 17;
    const isDeadlinePeriod = data.current_week >= tradeDeadline && data.current_week <= 17;
    
    // Reset classes
    deadlineWarning.classList.remove('trading-open', 'trading-blocked', 'trading-normal');
    
    if (isOffseason) {
        // Offseason - trading is open
        deadlineWarning.textContent = 'Offseason trading is open';
        deadlineWarning.classList.add('trading-open');
        document.getElementById('trade-submit-btn').disabled = false;
    } else if (isDeadlinePeriod) {
        deadlineWarning.textContent = `Trade deadline has passed (Week ${tradeDeadline})`;
        deadlineWarning.classList.add('trading-blocked');
        document.getElementById('trade-submit-btn').disabled = true;
    } else {
        deadlineWarning.textContent = `Trade deadline: Week ${tradeDeadline}`;
        deadlineWarning.classList.add('trading-normal');
        document.getElementById('trade-submit-btn').disabled = false;
    }
    
    // Populate trade partner select
    const partnerSelect = document.getElementById('trade-partner-select');
    partnerSelect.innerHTML = '<option value="">-- Select Team --</option>';
    
    // Get teams list - prefer from latest week, fall back to data.teams for offseason
    let teams = [];
    if (data.weeks && data.weeks.length > 0) {
        const latestWeek = data.weeks.reduce((max, week) => 
            (week.week > max.week) ? week : max, data.weeks[0]);
        teams = latestWeek.teams || [];
    }
    // Fall back to data.teams (for offseason when no weeks exist)
    if (teams.length === 0 && data.teams) {
        teams = data.teams;
    }
    teams.filter(t => t.abbrev !== manageState.team).forEach(team => {
        const option = document.createElement('option');
        option.value = team.abbrev;
        option.textContent = `${team.name} (${team.abbrev})`;
        partnerSelect.appendChild(option);
    });

    if ([...partnerSelect.options].some(option => option.value === manageState.tradePartner)) {
        partnerSelect.value = manageState.tradePartner;
    } else {
        manageState.tradePartner = null;
    }
    
    partnerSelect.onchange = () => {
        manageState.tradePartner = partnerSelect.value;
        manageState.tradeReceivePlayers = [];
        manageState.tradeReceivePicks = [];
        Object.keys(manageState.tradeConditions).forEach(key => {
            if (key.includes('-receive-')) delete manageState.tradeConditions[key];
        });
        renderTradePlayers();
    };
    
    renderTradePlayers();
    
    document.getElementById('trade-submit-btn').onclick = submitTradeProposal;
}

function tradeablePlayersFor(teamData) {
    if (!teamData) return [];
    const active = (teamData.roster || []).map(player => ({ ...player, taxi: false }));
    const taxi = (teamData.taxi_squad || []).map(player => ({ ...player, taxi: true }));
    return [...active, ...taxi];
}

function renderTradePlayers() {
    const myTeamData = getTeamData(manageState.team);
    const giveList = document.getElementById('trade-give-players');
    const receiveList = document.getElementById('trade-receive-players');
    if (!giveList || !receiveList) return;

    if (!myTeamData) {
        giveList.innerHTML = '<p class="no-pending-trades">No roster data available</p>';
    } else {
        giveList.innerHTML = sortRosterByPosition(tradeablePlayersFor(myTeamData))
            .map(player => tradePlayerRowHtml(player, manageState.tradeGivePlayers.includes(player.name)))
            .join('');
    }

    giveList.querySelectorAll('.tx-player').forEach(el => {
        el.onclick = () => toggleTradePlayer('give', el.dataset.name, el);
    });

    const partnerTeamData = getTeamData(manageState.tradePartner);
    if (!manageState.tradePartner) {
        receiveList.innerHTML = '<p class="no-pending-trades">Select a trade partner to view their roster</p>';
    } else if (!partnerTeamData) {
        receiveList.innerHTML = '<p class="no-pending-trades">No roster data available</p>';
    } else {
        receiveList.innerHTML = sortRosterByPosition(tradeablePlayersFor(partnerTeamData))
            .map(player => tradePlayerRowHtml(player, manageState.tradeReceivePlayers.includes(player.name)))
            .join('');
        receiveList.querySelectorAll('.tx-player').forEach(el => {
            el.onclick = () => toggleTradePlayer('receive', el.dataset.name, el);
        });
    }
    
    renderTradePicks();
    renderTradeConditions();
}

function toggleTradePlayer(direction, name, el) {
    const list = direction === 'give' ? manageState.tradeGivePlayers : manageState.tradeReceivePlayers;
    const idx = list.indexOf(name);
    const itemId = `player-${direction}-${name}`;
    
    if (idx >= 0) {
        list.splice(idx, 1);
        el.classList.remove('selected');
        el.querySelector('.tx-player-select')?.setAttribute('aria-pressed', 'false');
        // Remove condition if item was deselected
        delete manageState.tradeConditions[itemId];
    } else {
        list.push(name);
        el.classList.add('selected');
        el.querySelector('.tx-player-select')?.setAttribute('aria-pressed', 'true');
    }
    renderTradeConditions();
}

function renderTradePicks() {
    const givePicksList = document.getElementById('trade-give-picks');
    const receivePicksList = document.getElementById('trade-receive-picks');
    
    if (!givePicksList || !receivePicksList) return;
    
    // Get picks the current team owns from draft_picks data
    const myPicks = manageState.team ? getOwnedPicks(manageState.team) : [];
    
    if (myPicks.length === 0) {
        givePicksList.innerHTML = manageState.team 
            ? '<div class="tx-empty">No tradeable picks</div>'
            : '<div class="tx-empty">Login to see your picks</div>';
    } else {
        givePicksList.innerHTML = myPicks.map(pick => {
            const conditionHtml = pick.condition ? `<span class="tx-pick-condition" title="${pick.condition.replace(/"/g, '&quot;')}">⚡ ${pick.condition}</span>` : '';
            return `
            <div class="tx-pick ${manageState.tradeGivePicks.includes(pick.id) ? 'selected' : ''}" data-pick="${pick.id}" data-condition="${pick.condition || ''}">
                <span class="tx-pick-label">${pick.label}</span>
                ${conditionHtml}
            </div>`;
        }).join('');
    
    givePicksList.querySelectorAll('.tx-pick').forEach(el => {
        el.onclick = () => toggleTradePick('give', el.dataset.pick, el);
    });
    }
    
    // Partner picks to receive - only show if partner is selected
    if (manageState.tradePartner) {
        const partnerPicks = getOwnedPicks(manageState.tradePartner);
        
        if (partnerPicks.length === 0) {
            receivePicksList.innerHTML = '<div class="tx-empty">Partner has no tradeable picks</div>';
        } else {
            receivePicksList.innerHTML = partnerPicks.map(pick => {
                const conditionHtml = pick.condition ? `<span class="tx-pick-condition" title="${pick.condition.replace(/"/g, '&quot;')}">⚡ ${pick.condition}</span>` : '';
                return `
                <div class="tx-pick ${manageState.tradeReceivePicks.includes(pick.id) ? 'selected' : ''}" data-pick="${pick.id}" data-condition="${pick.condition || ''}">
                    <span class="tx-pick-label">${pick.label}</span>
                    ${conditionHtml}
                </div>`;
            }).join('');
    
    receivePicksList.querySelectorAll('.tx-pick').forEach(el => {
        el.onclick = () => toggleTradePick('receive', el.dataset.pick, el);
    });
        }
    } else {
        receivePicksList.innerHTML = '<div class="tx-empty">Select a trade partner first</div>';
    }
}

function getOwnedPicks(teamCode) {
    // Get picks that a team currently owns from draft_picks data
    // New format: flat array of picks with original_team, current_owner, etc.
    const picks = [];
    const allPicks = data.draft_picks || [];
    
    if (!Array.isArray(allPicks)) return picks;
    
    // Define pick types with their display info and sort order
    const pickTypeInfo = {
        'offseason': { prefix: '', sortOrder: 0 },
        'offseason_taxi': { prefix: 'Taxi ', sortOrder: 1 },
        'waiver': { prefix: 'Waiver ', sortOrder: 2 },
        'waiver_taxi': { prefix: 'Waiver Taxi ', sortOrder: 3 }
    };
    
    for (const pick of allPicks) {
        // Include picks where team is current owner OR has conditional claim
        const isOwner = pick.current_owner === teamCode;
        const hasConditionalClaim = pick.conditional_claim === teamCode && pick.current_owner !== teamCode;
        if (!isOwner && !hasConditionalClaim) continue;
        
        const typeInfo = pickTypeInfo[pick.draft_type] || { prefix: '', sortOrder: 9 };
        const fromLabel = pick.original_team !== teamCode ? ` (${pick.original_team})` : '';
        const idSuffix = pick.draft_type !== 'offseason' ? `-${pick.draft_type}` : '';
        
        // Calculate "via" from previous_owners
        const prevOwners = pick.previous_owners || [];
        const lastPrevOwner = prevOwners.length > 0 ? prevOwners[prevOwners.length - 1] : null;
        const viaLabel = (lastPrevOwner && lastPrevOwner !== pick.original_team) ? ` via ${lastPrevOwner}` : '';
        
        // For conditional claims, indicate who currently holds the pick
        const conditionalLabel = hasConditionalClaim ? ` [from ${pick.current_owner}]` : '';
        
        picks.push({
            id: `${pick.year}${idSuffix}-R${pick.round}-${pick.original_team}`,
            label: `${pick.year} ${typeInfo.prefix}R${pick.round}${fromLabel}${conditionalLabel}${viaLabel}`,
            year: parseInt(pick.year),
            round: pick.round,
            original_team: pick.original_team,
            draft_type: pick.draft_type,
            typeOrder: typeInfo.sortOrder,
            condition: pick.condition || null,
            isConditionalClaim: hasConditionalClaim
        });
    }
    
    // Sort by year, then by type (regular before taxi before waiver), then by round
    picks.sort((a, b) => a.year - b.year || a.typeOrder - b.typeOrder || a.round - b.round);
    
    return picks;
}

function toggleTradePick(direction, pick, el) {
    const list = direction === 'give' ? manageState.tradeGivePicks : manageState.tradeReceivePicks;
    const idx = list.indexOf(pick);
    const itemId = `pick-${direction}-${pick}`;
    
    if (idx >= 0) {
        list.splice(idx, 1);
        el.classList.remove('selected');
        // Remove condition if item was deselected
        delete manageState.tradeConditions[itemId];
    } else {
        list.push(pick);
        el.classList.add('selected');
    }
    renderTradeConditions();
}

function renderTradeConditions() {
    const section = document.getElementById('trade-conditions-section');
    const list = document.getElementById('trade-conditions-list');
    
    if (!section || !list) return;
    
    // Collect all selected items
    const items = [];
    
    // Players you're giving
    for (const name of manageState.tradeGivePlayers) {
        items.push({
            id: `player-give-${name}`,
            label: name,
            type: 'Player (giving)',
            direction: 'give'
        });
    }
    
    // Players you're receiving
    for (const name of manageState.tradeReceivePlayers) {
        items.push({
            id: `player-receive-${name}`,
            label: name,
            type: 'Player (receiving)',
            direction: 'receive'
        });
    }
    
    // Picks you're giving
    for (const pickId of manageState.tradeGivePicks) {
        items.push({
            id: `pick-give-${pickId}`,
            label: pickId.replace(/-/g, ' '),
            type: 'Pick (giving)',
            direction: 'give'
        });
    }
    
    // Picks you're receiving
    for (const pickId of manageState.tradeReceivePicks) {
        items.push({
            id: `pick-receive-${pickId}`,
            label: pickId.replace(/-/g, ' '),
            type: 'Pick (receiving)',
            direction: 'receive'
        });
    }
    
    // Show/hide section based on whether there are items
    if (items.length === 0) {
        section.style.display = 'none';
        return;
    }
    
    section.style.display = 'block';
    
    // Render condition inputs for each item
    list.innerHTML = items.map(item => {
        const existingCondition = manageState.tradeConditions[item.id] || '';
        return `
            <div class="trade-condition-item">
                <div class="trade-condition-label">
                    <span class="item-type">${item.type}</span>
                    ${item.label}
                </div>
                <input type="text" 
                    class="trade-condition-input" 
                    data-item-id="${item.id}"
                    aria-label="${escapeHtml(`Condition for ${item.label}`)}"
                    value="${existingCondition.replace(/"/g, '&quot;')}"
                    placeholder="Add condition (optional)..."
                    maxlength="200">
            </div>
        `;
    }).join('');
    
    // Add input listeners
    list.querySelectorAll('.trade-condition-input').forEach(input => {
        input.oninput = (e) => {
            const itemId = e.target.dataset.itemId;
            const value = e.target.value.trim();
            if (value) {
                manageState.tradeConditions[itemId] = value;
            } else {
                delete manageState.tradeConditions[itemId];
            }
        };
    });
}

function submitTradeProposal() {
    const statusEl = document.getElementById('trade-status');
    
    if (!manageState.tradePartner) {
        statusEl.className = 'submit-status error';
        statusEl.textContent = 'Please select a trade partner';
        return;
    }
    
    if (manageState.tradeGivePlayers.length === 0 && 
        manageState.tradeGivePicks.length === 0 &&
        manageState.tradeReceivePlayers.length === 0 &&
        manageState.tradeReceivePicks.length === 0) {
        statusEl.className = 'submit-status error';
        statusEl.textContent = 'Trade must include at least one player or pick';
        return;
    }
    
    // Get trade partner name for display
    const partnerData = getTeamData(manageState.tradePartner);
    const partnerName = partnerData ? partnerData.name : manageState.tradePartner;
    
    // Build confirmation content
    let content = '';
    
    // Items you're giving
    if (manageState.tradeGivePlayers.length > 0 || manageState.tradeGivePicks.length > 0) {
        manageState.tradeGivePlayers.forEach(player => {
            content += buildPlayerRow('Give', 'give', player, 'Player');
        });
        manageState.tradeGivePicks.forEach(pick => {
            content += buildPlayerRow('Give', 'give', pick, 'Draft Pick');
        });
    }
    
    // Items you're receiving
    if (manageState.tradeReceivePlayers.length > 0 || manageState.tradeReceivePicks.length > 0) {
        manageState.tradeReceivePlayers.forEach(player => {
            content += buildPlayerRow('Receive', 'receive', player, 'Player');
        });
        manageState.tradeReceivePicks.forEach(pick => {
            content += buildPlayerRow('Receive', 'receive', pick, 'Draft Pick');
        });
    }
    
    showConfirmModal({
        title: `Trade Proposal to ${partnerName}`,
        icon: '',
        content: content,
        warning: 'The other team will need to accept this trade before it goes through.',
        confirmText: 'Send Proposal',
        onConfirm: () => executeTradeProposal()
    });
}

async function executeTradeProposal() {
    const statusEl = document.getElementById('trade-status');
    statusEl.className = 'submit-status loading';
    statusEl.textContent = 'Proposing trade...';
    
    // Get optional comment
    const commentEl = document.getElementById('trade-comment');
    const comment = commentEl ? commentEl.value.trim() : '';
    
    try {
        const response = await fetch(MANAGE_CONFIG.apiUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: 'propose_trade',
                team: manageState.team,
                password: manageState.password,
                trade_partner: manageState.tradePartner,
                give_players: manageState.tradeGivePlayers,
                give_picks: manageState.tradeGivePicks,
                receive_players: manageState.tradeReceivePlayers,
                receive_picks: manageState.tradeReceivePicks,
                conditions: manageState.tradeConditions,
                current_week: data.current_week,
                comment: comment,
                submitted_at: new Date().toISOString()
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            statusEl.className = 'submit-status success';
            statusEl.textContent = result.message;
            // Reset trade selections
            manageState.tradeGivePlayers = [];
            manageState.tradeGivePicks = [];
            manageState.tradeReceivePlayers = [];
            manageState.tradeReceivePicks = [];
            manageState.tradeConditions = {};
            setTimeout(() => loadData(null, { forceRefresh: true }), 2000);
        } else {
            statusEl.className = 'submit-status error';
            statusEl.textContent = result.error;
        }
    } catch (e) {
        statusEl.className = 'submit-status error';
        statusEl.textContent = 'Network error - please try again';
    }
}

function renderPendingTrades() {
    const container = document.getElementById('pending-trades');
    const pendingTrades = data.pending_trades || [];
    
    // Filter trades: only pending status, involving current team
    const relevantTrades = pendingTrades.filter(t => 
        t.status === 'pending' && 
        (t.proposer === manageState.team || t.partner === manageState.team)
    );

    const countBadge = document.getElementById('pending-trade-count');
    if (countBadge) {
        countBadge.textContent = relevantTrades.length;
        countBadge.hidden = relevantTrades.length === 0;
    }
    
    if (relevantTrades.length === 0) {
        container.innerHTML = '<p class="no-pending-trades">No pending trades</p>';
        return;
    }
    
    container.innerHTML = relevantTrades.map(trade => {
        const isProposer = trade.proposer === manageState.team;
        const otherTeam = isProposer ? trade.partner : trade.proposer;
        const otherTeamData = getTeamData(otherTeam);
        const otherTeamName = otherTeamData ? otherTeamData.name : otherTeam;
        const conditions = trade.conditions || {};
        
        // Helper to format item with condition
        const formatItem = (item, type, direction) => {
            const conditionKey = `${type}-${direction}-${item}`;
            const condition = conditions[conditionKey];
            const itemLabel = type === 'player'
                ? playerProfileButton(
                    typeof item === 'object' ? item.name : item,
                    'pending-trade-player',
                    null,
                    typeof item === 'object' ? item.position : ''
                )
                : escapeHtml(item);
            if (condition) {
                return `<li>${itemLabel} <span class="pending-trade-condition">⚡ ${escapeHtml(condition)}</span></li>`;
            }
            return `<li>${itemLabel}</li>`;
        };

        // Countdown to auto-expiry. Pending trades are auto-cancelled by the
        // expire-trades.yml workflow TRADE_EXPIRY_DAYS days after proposal —
        // keep this in sync with that constant.
        let expiresStr = '';
        let expiresTitle = '';
        let expiresClass = '';
        if (trade.status === 'pending' && trade.proposed_at) {
            const proposed = new Date(trade.proposed_at);
            // proposed_at is recorded in UTC but older entries may lack a 'Z'.
            const proposedUtc = /[zZ]|[+-]\d\d:?\d\d$/.test(trade.proposed_at)
                ? proposed
                : new Date(trade.proposed_at + 'Z');
            const expiresDate = new Date(proposedUtc.getTime() + TRADE_EXPIRY_DAYS * 86400000);
            const msLeft = expiresDate.getTime() - Date.now();
            const daysLeft = Math.ceil(msLeft / 86400000);
            expiresTitle = `Auto-cancels ${expiresDate.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}`;
            if (msLeft <= 0) {
                expiresStr = 'Expiring soon';
                expiresClass = 'urgent';
            } else if (daysLeft <= 1) {
                const hoursLeft = Math.ceil(msLeft / 3600000);
                expiresStr = `Expires in ${hoursLeft}h`;
                expiresClass = 'urgent';
            } else {
                expiresStr = `Expires in ${daysLeft} days`;
                if (daysLeft <= 2) expiresClass = 'soon';
            }
        }

        return `
            <div class="pending-trade-card" data-trade-id="${trade.id}">
                <div class="pending-trade-header">
                    <span class="pending-trade-teams">
                        ${isProposer ? 'You and ' + otherTeamName : otherTeamName + ' and You'}
                    </span>
                    <div class="pending-trade-header-right">
                        ${expiresStr ? `<span class="pending-trade-expires ${expiresClass}" title="${expiresTitle}">⏱ ${expiresStr}</span>` : ''}
                        <span class="pending-status-badge ${trade.status}">${trade.status.toUpperCase()}</span>
                    </div>
                </div>
                <div class="pending-trade-details">
                    <div class="pending-trade-side">
                        <h5>${isProposer ? 'You give' : 'You receive'}</h5>
                        <ul>
                            ${trade.proposer_gives.players.map(p => formatItem(p, 'player', 'give')).join('')}
                            ${trade.proposer_gives.picks.map(p => formatItem(p, 'pick', 'give')).join('')}
                            ${trade.proposer_gives.players.length === 0 && trade.proposer_gives.picks.length === 0 ? '<li>(nothing)</li>' : ''}
                        </ul>
                    </div>
                    <div class="pending-trade-side">
                        <h5>${isProposer ? 'You receive' : 'You give'}</h5>
                        <ul>
                            ${trade.proposer_receives.players.map(p => formatItem(p, 'player', 'receive')).join('')}
                            ${trade.proposer_receives.picks.map(p => formatItem(p, 'pick', 'receive')).join('')}
                            ${trade.proposer_receives.players.length === 0 && trade.proposer_receives.picks.length === 0 ? '<li>(nothing)</li>' : ''}
                        </ul>
                    </div>
                </div>
                ${trade.comment ? `
                    <div class="pending-trade-comment">
                        <strong>Message:</strong> "${escapeHtml(trade.comment)}"
                    </div>
                ` : ''}
                ${trade.status === 'pending' && !isProposer ? `
                    <div class="pending-trade-actions">
                        <button class="lineup-btn accept-btn" onclick="respondToTrade('${trade.id}', true)">Accept</button>
                        <button class="lineup-btn reject-btn" onclick="respondToTrade('${trade.id}', false)">Reject</button>
                    </div>
                ` : ''}
                ${trade.status === 'pending' && isProposer ? `
                    <div class="pending-trade-actions">
                        <span style="color: var(--text-secondary);">Waiting for ${otherTeamName} to respond</span>
                        <button class="lineup-btn reject-btn" onclick="cancelTrade('${trade.id}')">Cancel</button>
                    </div>
                ` : ''}
            </div>
        `;
    }).join('');
}

function respondToTrade(tradeId, accept) {
    // If rejecting, execute directly (no confirmation needed)
    if (!accept) {
        executeTradeResponse(tradeId, false);
        return;
    }
    
    // For accepting, show confirmation modal
    const pendingTrades = data.pending_trades || [];
    const trade = pendingTrades.find(t => t.id === tradeId);
    
    if (!trade) {
        const statusEl = document.getElementById('pending-status');
        statusEl.className = 'submit-status error';
        statusEl.textContent = 'Trade not found';
        return;
    }
    
    // Get proposer name
    const proposerData = getTeamData(trade.proposer);
    const proposerName = proposerData ? proposerData.name : trade.proposer;
    
    // Build confirmation content showing what you'll give and receive
    let content = '';
    
    // What proposer gives = what you receive
    const youReceive = trade.proposer_gives || {};
    if (youReceive.players?.length > 0) {
        youReceive.players.forEach(player => {
            content += buildPlayerRow('Receive', 'receive', player, 'Player');
        });
    }
    if (youReceive.picks?.length > 0) {
        youReceive.picks.forEach(pick => {
            content += buildPlayerRow('Receive', 'receive', pick, 'Draft Pick');
        });
    }
    
    // What proposer receives = what you give
    const youGive = trade.proposer_receives || {};
    if (youGive.players?.length > 0) {
        youGive.players.forEach(player => {
            content += buildPlayerRow('Give', 'give', player, 'Player');
        });
    }
    if (youGive.picks?.length > 0) {
        youGive.picks.forEach(pick => {
            content += buildPlayerRow('Give', 'give', pick, 'Draft Pick');
        });
    }
    
    showConfirmModal({
        title: `Accept Trade from ${proposerName}?`,
        icon: '🤝',
        content: content,
        warning: 'This trade will be executed immediately and cannot be undone.',
        confirmText: 'Accept Trade',
        isDanger: false,
        onConfirm: () => executeTradeResponse(tradeId, true)
    });
}

async function executeTradeResponse(tradeId, accept) {
    const statusEl = document.getElementById('pending-status');
    statusEl.className = 'submit-status loading';
    statusEl.textContent = accept ? 'Accepting trade...' : 'Rejecting trade...';
    
    try {
        const response = await fetch(MANAGE_CONFIG.apiUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: 'respond_trade',
                team: manageState.team,
                password: manageState.password,
                trade_id: tradeId,
                accept: accept
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            statusEl.className = 'submit-status success';
            statusEl.textContent = result.message;
            setTimeout(() => loadData(null, { forceRefresh: true }), 2000);
        } else {
            statusEl.className = 'submit-status error';
            statusEl.textContent = result.error;
        }
    } catch (e) {
        statusEl.className = 'submit-status error';
        statusEl.textContent = 'Network error - please try again';
    }
}

async function cancelTrade(tradeId) {
    const statusEl = document.getElementById('pending-status');
    statusEl.className = 'submit-status loading';
    statusEl.textContent = 'Cancelling trade...';
    
    try {
        const response = await fetch(MANAGE_CONFIG.apiUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: 'cancel_trade',
                team: manageState.team,
                password: manageState.password,
                trade_id: tradeId
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            statusEl.className = 'submit-status success';
            statusEl.textContent = result.message;
            setTimeout(() => loadData(null, { forceRefresh: true }), 2000);
        } else {
            statusEl.className = 'submit-status error';
            statusEl.textContent = result.error;
        }
    } catch (e) {
        statusEl.className = 'submit-status error';
        statusEl.textContent = 'Network error - please try again';
    }
}

function renderTradeBlockTab() {
    if (!manageState.team) return;
    
    const tradeBlocks = data.trade_blocks || {};
    const teamBlock = tradeBlocks[manageState.team] || {};
    tradeBlockBaseline = {
        seeking: [...(teamBlock.seeking || [])],
        tradingAway: [...(teamBlock.trading_away || [])],
        players: [...(teamBlock.players_available || [])],
        notes: String(teamBlock.notes || '').trim(),
    };
    
    // Populate seeking checkboxes
    const seekingContainer = document.getElementById('seeking-positions');
    seekingContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => {
        cb.checked = (teamBlock.seeking || []).includes(cb.value);
        cb.parentElement.classList.toggle('selected', cb.checked);
        cb.onchange = () => cb.parentElement.classList.toggle('selected', cb.checked);
    });
    
    // Populate trading away checkboxes
    const tradingContainer = document.getElementById('trading-positions');
    tradingContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => {
        cb.checked = (teamBlock.trading_away || []).includes(cb.value);
        cb.parentElement.classList.toggle('selected', cb.checked);
        cb.onchange = () => cb.parentElement.classList.toggle('selected', cb.checked);
    });
    
    // Populate player selection
    const playersContainer = document.getElementById('available-players');
    const teamData = getTeamData(manageState.team);
    
    if (teamData && teamData.roster) {
        const availablePlayers = teamBlock.players_available || [];
        playersContainer.innerHTML = sortRosterByPosition(teamData.roster).map(player => `
            <div class="trade-block-player-item ${availablePlayers.includes(player.name) ? 'selected' : ''}">
                <input type="checkbox" value="${escapeHtml(player.name)}" aria-label="List ${escapeHtml(player.name)} as available for trade" ${availablePlayers.includes(player.name) ? 'checked' : ''}>
                <span class="trade-block-player-pos">${escapeHtml(player.position)}</span>
                ${playerProfileButton(player.name, 'trade-block-player-name', null, player.position)}
            </div>
        `).join('');
        
        // Add listeners
        playersContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => {
            cb.onchange = () => cb.parentElement.classList.toggle('selected', cb.checked);
        });
        playersContainer.querySelectorAll('.trade-block-player-item').forEach(row => {
            row.onclick = event => {
                if (event.target.closest('input, .player-profile-trigger')) return;
                row.querySelector('input[type="checkbox"]')?.click();
            };
        });
    } else {
        playersContainer.innerHTML = '<p style="color: var(--text-muted);">No roster data available</p>';
    }
    
    // Populate notes
    document.getElementById('tradeblock-notes').value = teamBlock.notes || '';
    
    // Set up submit button
    document.getElementById('tradeblock-submit-btn').onclick = saveTradeBlock;
}

async function saveTradeBlock() {
    const statusEl = document.getElementById('tradeblock-status');
    const submitBtn = document.getElementById('tradeblock-submit-btn');
    
    // Gather data
    const seeking = [];
    document.querySelectorAll('#seeking-positions input:checked').forEach(cb => {
        seeking.push(cb.value);
    });
    
    const tradingAway = [];
    document.querySelectorAll('#trading-positions input:checked').forEach(cb => {
        tradingAway.push(cb.value);
    });
    
    const playersAvailable = [];
    document.querySelectorAll('#available-players input:checked').forEach(cb => {
        playersAvailable.push(cb.value);
    });
    
    const notes = document.getElementById('tradeblock-notes').value.trim();
    
    // Show loading state
    statusEl.className = 'submit-status loading';
    statusEl.textContent = 'Saving trade block...';
    submitBtn.disabled = true;
    
    try {
        const response = await fetch(MANAGE_CONFIG.apiUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: 'save_tradeblock',
                team: manageState.team,
                password: manageState.password,
                seeking: seeking,
                trading_away: tradingAway,
                players_available: playersAvailable,
                notes: notes
            })
        });
        
        const result = await response.json();
        
        if (result.success) {
            statusEl.className = 'submit-status success';
            statusEl.textContent = 'Trade block saved successfully!';
            tradeBlockBaseline = { seeking, tradingAway, players: playersAvailable, notes };
            // Reload data to update the teams view
            setTimeout(() => loadData(null, { forceRefresh: true }), 1500);
        } else {
            statusEl.className = 'submit-status error';
            statusEl.textContent = result.error || 'Failed to save trade block';
        }
    } catch (e) {
        statusEl.className = 'submit-status error';
        statusEl.textContent = 'Network error - please try again';
    }
    
    submitBtn.disabled = false;
}

// --------------------------------------------------------------------------- //
// Depth Chart tab
//
// A team's depth chart is just the order of its players inside data/rosters.json:
// every roster surface renders players in array order (sortRosterByPosition is a
// stable sort by position, so within-position order survives it). Saving posts the
// new per-position order to the `set_depth_chart` transaction action, which
// rewrites that order server-side. Nothing about scoring or starters changes.
// --------------------------------------------------------------------------- //
let depthChartState = {
    team: null,
    order: {},     // { position: [name, ...] } - the working (possibly unsaved) order
    baseline: {}   // the order as currently saved, for dirty-checking and undo
};

function activeRosterFor(abbrev) {
    const teamData = getTeamData(abbrev);
    return (teamData?.roster || []).filter(p => !p.taxi);
}

function closeRosterAction() {
    const panel = document.getElementById('roster-action-panel');
    if (panel) panel.hidden = true;
    manageState.actionStatusId = null;
    manageState.selectedTaxiPlayer = null;
    manageState.selectedReleasePlayer = null;
    manageState.selectedReleaseOnlyPlayer = null;
}

function openRosterAction(mode, playerName) {
    const teamData = getTeamData(manageState.team);
    if (!teamData) return;

    const activeRoster = teamData.roster || [];
    const taxiSquad = teamData.taxi_squad || [];
    const player = mode === 'activate'
        ? taxiSquad.find(item => item.name === playerName)
        : activeRoster.find(item => item.name === playerName);
    if (!player) return;

    const panel = document.getElementById('roster-action-panel');
    const title = document.getElementById('roster-action-title');
    const description = document.getElementById('roster-action-description');
    const options = document.getElementById('roster-action-options');
    const confirm = document.getElementById('roster-action-confirm');
    const comment = document.getElementById('roster-action-comment');
    const status = document.getElementById('roster-action-status');
    if (!panel || !title || !description || !options || !confirm || !comment || !status) return;

    panel.hidden = false;
    manageState.actionStatusId = 'roster-action-status';
    comment.value = '';
    status.className = 'submit-status';
    status.textContent = '';
    confirm.classList.toggle('danger', mode === 'drop');

    if (mode === 'drop') {
        manageState.selectedReleaseOnlyPlayer = player.name;
        title.textContent = `Drop ${player.name}`;
        description.textContent = `${player.position} · ${player.nfl_team || 'No NFL team'}`;
        options.innerHTML = '<p class="roster-action-note">The player will be removed from your roster immediately.</p>';
        confirm.textContent = 'Drop Player';
        confirm.disabled = false;
        confirm.onclick = () => {
            document.getElementById('release-comment').value = comment.value;
            submitRelease();
        };
    } else {
        manageState.selectedTaxiPlayer = { name: player.name, position: player.position };
        manageState.selectedReleasePlayer = null;
        title.textContent = `Activate ${player.name}`;
        description.textContent = `Choose an active ${player.position} to drop in the corresponding move.`;
        confirm.textContent = 'Activate Player';
        confirm.disabled = true;

        const candidates = activeRoster.filter(item => item.position === player.position);
        if (candidates.length === 0) {
            options.innerHTML = `<p class="roster-action-note">There are no active ${escapeHtml(player.position)} players available to drop.</p>`;
        } else {
            options.innerHTML = `
                <fieldset class="roster-release-options">
                    <legend>Player to drop</legend>
                    ${candidates.map(candidate => `
                        <div class="roster-release-option" data-name="${escapeHtml(candidate.name)}">
                            <button type="button" class="roster-release-select" aria-label="Select ${escapeHtml(candidate.name)} to drop" aria-pressed="false">
                                <span class="position-tag">${escapeHtml(candidate.position)}</span>
                            </button>
                            ${playerProfileButton(candidate.name, '', null, candidate.position)}
                            <span class="player-team">${escapeHtml(candidate.nfl_team || '')}</span>
                        </div>
                    `).join('')}
                </fieldset>
            `;
            options.querySelectorAll('.roster-release-option').forEach(option => {
                option.onclick = () => {
                    options.querySelectorAll('.roster-release-option').forEach(item => {
                        item.classList.remove('selected');
                        item.querySelector('.roster-release-select')?.setAttribute('aria-pressed', 'false');
                    });
                    option.classList.add('selected');
                    option.querySelector('.roster-release-select')?.setAttribute('aria-pressed', 'true');
                    manageState.selectedReleasePlayer = option.dataset.name;
                    confirm.disabled = false;
                };
            });
        }

        confirm.onclick = () => {
            if (!manageState.selectedReleasePlayer) return;
            document.getElementById('taxi-comment').value = comment.value;
            submitTaxiActivation();
        };
    }

    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    comment.focus({ preventScroll: true });
}

function renderRosterTaxiSquad() {
    const container = document.getElementById('roster-taxi-players');
    if (!container) return;

    const teamData = getTeamData(manageState.team);
    const taxiSquad = sortRosterByPosition(teamData?.taxi_squad || []);
    const activeRoster = teamData?.roster || [];
    if (taxiSquad.length === 0) {
        container.innerHTML = '<p class="no-pending-trades">No players on taxi squad</p>';
        return;
    }

    container.innerHTML = taxiSquad.map(player => {
        const canActivate = activeRoster.some(item => item.position === player.position);
        const activateHint = canActivate ? '' : ` title="No active ${escapeHtml(player.position)} is available to drop"`;
        return `
            <div class="roster-taxi-row">
                <span class="position-tag">${escapeHtml(player.position)}</span>
                ${playerProfileButton(player.name, '', null, player.position)}
                <span class="player-team">${escapeHtml(player.nfl_team || '')}</span>
                <div class="roster-row-actions">
                    <button type="button" class="roster-action-btn trade roster-trade-btn" data-name="${escapeHtml(player.name)}">Trade</button>
                    <button type="button" class="roster-action-btn activate roster-activate-btn" data-name="${escapeHtml(player.name)}" ${canActivate ? '' : 'disabled'}${activateHint}>Activate</button>
                </div>
            </div>
        `;
    }).join('');

    container.querySelectorAll('.roster-trade-btn').forEach(button => {
        button.onclick = () => startTradeForPlayer(button.dataset.name);
    });
    container.querySelectorAll('.roster-activate-btn').forEach(button => {
        button.onclick = () => openRosterAction('activate', button.dataset.name);
    });
}

// Rebuild state from the live roster. An in-progress reorder is kept only when
// the position's players are unchanged - if a trade or waiver claim moved
// somebody, that position resets to the saved order rather than trying to
// reconcile an edit against a roster that no longer matches it.
function syncDepthChartState() {
    const roster = activeRosterFor(manageState.team);
    const sameTeam = depthChartState.team === manageState.team;
    const baseline = {};
    const order = {};

    ROSTER_POSITION_ORDER.forEach(pos => {
        const names = roster.filter(p => p.position === pos).map(p => p.name);
        if (names.length === 0) return;
        baseline[pos] = names;

        const pending = sameTeam ? depthChartState.order[pos] : null;
        const stillValid = pending
            && pending.length === names.length
            && [...pending].sort().join(' ') === [...names].sort().join(' ');
        order[pos] = stillValid ? pending : names;
    });

    depthChartState = { team: manageState.team, order, baseline };
}

function isDepthChartDirty() {
    return Object.keys(depthChartState.baseline).some(pos =>
        depthChartState.order[pos].join(' ') !== depthChartState.baseline[pos].join(' ')
    );
}

function renderDepthChartTab() {
    if (!manageState.team) return;
    const container = document.getElementById('depth-chart-groups');
    if (!container) return;

    syncDepthChartState();
    renderRosterTaxiSquad();

    const roster = activeRosterFor(manageState.team);
    if (roster.length === 0) {
        container.innerHTML = '<p style="color: var(--text-muted);">No roster data available</p>';
        document.getElementById('depth-chart-save-btn').disabled = true;
        document.getElementById('depth-chart-reset-btn').disabled = true;
        return;
    }

    const byName = {};
    roster.forEach(p => { byName[p.name] = p; });

    container.innerHTML = ROSTER_POSITION_ORDER
        .filter(pos => depthChartState.order[pos])
        .map(pos => {
            const names = depthChartState.order[pos];
            const label = LINEUP_CONFIG.positions[pos]?.label || pos;
            const rows = names.map((name, i) => {
                const p = byName[name] || { name, nfl_team: '' };
                return `
                    <li class="depth-row" draggable="true" data-position="${escapeHtml(pos)}" data-index="${i}">
                        <span class="depth-handle" aria-hidden="true">⠿</span>
                        <span class="depth-rank">${pos}${i + 1}</span>
                        ${playerProfileButton(p.name, '', null, p.position)}
                        <span class="player-team">${escapeHtml(p.nfl_team || '')}</span>
                        <span class="depth-move">
                            <button type="button" class="depth-move-btn" data-position="${escapeHtml(pos)}"
                                    data-index="${i}" data-dir="-1" ${i === 0 ? 'disabled' : ''}
                                    aria-label="Move ${escapeHtml(p.name)} up">▲</button>
                            <button type="button" class="depth-move-btn" data-position="${escapeHtml(pos)}"
                                    data-index="${i}" data-dir="1" ${i === names.length - 1 ? 'disabled' : ''}
                                    aria-label="Move ${escapeHtml(p.name)} down">▼</button>
                        </span>
                        <span class="roster-row-actions">
                            <button type="button" class="roster-action-btn trade roster-trade-btn" data-name="${escapeHtml(p.name)}">Trade</button>
                            <button type="button" class="roster-action-btn drop roster-drop-btn" data-name="${escapeHtml(p.name)}">Drop</button>
                        </span>
                    </li>
                `;
            }).join('');

            return `
                <div class="depth-group">
                    <div class="depth-group-header">
                        <span class="position-label">${escapeHtml(pos)} - ${escapeHtml(label)}</span>
                    </div>
                    <ul class="depth-list" data-position="${escapeHtml(pos)}">${rows}</ul>
                </div>
            `;
        }).join('');

    attachDepthChartHandlers();

    container.querySelectorAll('.roster-trade-btn').forEach(button => {
        button.onclick = () => startTradeForPlayer(button.dataset.name);
    });
    container.querySelectorAll('.roster-drop-btn').forEach(button => {
        button.onclick = () => openRosterAction('drop', button.dataset.name);
    });

    const dirty = isDepthChartDirty();
    document.getElementById('depth-chart-save-btn').disabled = !dirty;
    document.getElementById('depth-chart-reset-btn').disabled = !dirty;
}

function moveDepthPlayer(position, from, to) {
    const list = depthChartState.order[position];
    if (!list || to < 0 || to >= list.length || from === to) return;
    const [moved] = list.splice(from, 1);
    list.splice(to, 0, moved);
    renderDepthChartTab();
}

function attachDepthChartHandlers() {
    const container = document.getElementById('depth-chart-groups');

    container.querySelectorAll('.depth-move-btn').forEach(btn => {
        btn.onclick = () => {
            const from = parseInt(btn.dataset.index);
            moveDepthPlayer(btn.dataset.position, from, from + parseInt(btn.dataset.dir));
        };
    });

    // Drag and drop, constrained to the row's own position group - dropping a
    // WR into the RB list would be a position change, not a reorder.
    let dragging = null;

    container.querySelectorAll('.depth-row').forEach(row => {
        row.addEventListener('dragstart', e => {
            dragging = { position: row.dataset.position, index: parseInt(row.dataset.index) };
            row.classList.add('dragging');
            e.dataTransfer.effectAllowed = 'move';
            // Firefox won't start a drag unless some data is set.
            e.dataTransfer.setData('text/plain', row.dataset.index);
        });

        row.addEventListener('dragend', () => {
            row.classList.remove('dragging');
            container.querySelectorAll('.depth-row').forEach(r => r.classList.remove('drag-over'));
            dragging = null;
        });

        row.addEventListener('dragover', e => {
            if (!dragging || dragging.position !== row.dataset.position) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            row.classList.add('drag-over');
        });

        row.addEventListener('dragleave', () => row.classList.remove('drag-over'));

        row.addEventListener('drop', e => {
            if (!dragging || dragging.position !== row.dataset.position) return;
            e.preventDefault();
            const to = parseInt(row.dataset.index);
            const { position, index } = dragging;
            dragging = null;
            moveDepthPlayer(position, index, to);
        });
    });
}

async function saveDepthChart() {
    const statusEl = document.getElementById('depth-chart-status');
    const saveBtn = document.getElementById('depth-chart-save-btn');
    const resetBtn = document.getElementById('depth-chart-reset-btn');

    // Send only the positions the manager actually changed, so a concurrent
    // roster move at an untouched position can't fail the whole save.
    const order = {};
    Object.keys(depthChartState.baseline).forEach(pos => {
        if (depthChartState.order[pos].join(' ') !== depthChartState.baseline[pos].join(' ')) {
            order[pos] = depthChartState.order[pos];
        }
    });

    if (Object.keys(order).length === 0) return;

    statusEl.className = 'submit-status loading';
    statusEl.textContent = 'Saving depth chart...';
    saveBtn.disabled = true;
    resetBtn.disabled = true;

    try {
        const response = await fetch(MANAGE_CONFIG.apiUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: 'set_depth_chart',
                team: manageState.team,
                password: manageState.password,
                order
            })
        });

        const result = await response.json();

        if (result.success) {
            // Apply the new order to the in-memory roster so every view on the
            // page matches right away; the committed file is what persists.
            applyDepthChartLocally(manageState.team, order);
            statusEl.className = 'submit-status success';
            statusEl.textContent = 'Depth chart saved!';
            setTimeout(() => {
                statusEl.textContent = '';
                statusEl.className = 'submit-status';
            }, 4000);
        } else {
            statusEl.className = 'submit-status error';
            statusEl.textContent = result.error || 'Failed to save depth chart';
        }
    } catch (e) {
        statusEl.className = 'submit-status error';
        statusEl.textContent = 'Network error - please try again';
    }

    renderDepthChartTab();
}

// Mirror the server-side reorder (api/transaction.py reorder_within_positions)
// against either supported data.rosters format by refilling each touched
// position's existing slots with the newly ordered players.
function applyDepthChartLocally(abbrev, order) {
    const rawRoster = data?.rosters?.[abbrev];
    const roster = Array.isArray(rawRoster) ? rawRoster : rawRoster?.roster;
    if (!Array.isArray(roster)) return;

    const queues = {};
    Object.keys(order).forEach(pos => {
        const byName = {};
        roster.forEach(p => {
            if (p.position === pos && !p.taxi) byName[p.name] = p;
        });
        const ordered = order[pos].map(n => byName[n]).filter(Boolean);
        if (ordered.length === order[pos].length) queues[pos] = ordered;
    });

    const cursors = {};
    Object.keys(queues).forEach(pos => { cursors[pos] = 0; });
    const reorderedRoster = roster.map(p => {
        if (p.taxi || !queues[p.position]) return p;
        return queues[p.position][cursors[p.position]++];
    });
    data.rosters[abbrev] = Array.isArray(rawRoster)
        ? reorderedRoster
        : { ...rawRoster, roster: reorderedRoster };

    // Refresh any already-rendered roster surfaces.
    if (typeof renderAllRosters === 'function') renderAllRosters();
}

function initDepthChartTab() {
    document.getElementById('depth-chart-save-btn').onclick = saveDepthChart;
    document.getElementById('depth-chart-reset-btn').onclick = () => {
        depthChartState.order = {};  // drop pending edits; sync repopulates from saved
        document.getElementById('depth-chart-status').textContent = '';
        renderDepthChartTab();
    };
    document.getElementById('roster-action-close').onclick = closeRosterAction;
    document.getElementById('roster-action-cancel').onclick = closeRosterAction;
    renderDepthChartTab();
}

// Auto-refresh every 5 minutes during game windows
function checkRefresh() {
    const now = new Date();
    const day = now.getDay(); // 0=Sun, 4=Thu, 1=Mon
    const hour = now.getHours();
    
    let inGameWindow = false;
    if (day === 4 && hour >= 20) inGameWindow = true; // Thursday night
    if (day === 0 && hour >= 12) inGameWindow = true; // Sunday afternoon
    if (day === 1 && hour >= 20) inGameWindow = true; // Monday night
    
    if (inGameWindow) {
        setTimeout(() => {
            loadData(null, { forceRefresh: true });
            checkRefresh();
        }, 5 * 60 * 1000); // 5 minutes
    } else {
        setTimeout(checkRefresh, 30 * 60 * 1000); // Check again in 30 min
    }
}

loadData();
checkRefresh();

// Confirmation Modal Functions
let pendingConfirmCallback = null;
let confirmModalReturnFocus = null;

const MODAL_FOCUSABLE_SELECTOR = [
    'a[href]',
    'button:not([disabled])',
    'input:not([disabled])',
    'select:not([disabled])',
    'textarea:not([disabled])',
    '[tabindex]:not([tabindex="-1"])'
].join(',');

function openModalOverlay(overlay, initialFocus) {
    if (!overlay) return;
    overlay.classList.add('active');
    overlay.setAttribute('aria-hidden', 'false');
    document.querySelector('.container')?.setAttribute('inert', '');
    document.body.style.overflow = 'hidden';
    requestAnimationFrame(() => initialFocus?.focus());
}

function closeModalOverlay(overlay) {
    if (!overlay) return;
    overlay.classList.remove('active');
    overlay.setAttribute('aria-hidden', 'true');
    if (!document.querySelector('.confirm-modal-overlay.active')) {
        document.querySelector('.container')?.removeAttribute('inert');
        document.body.style.overflow = '';
    }
}

function trapModalFocus(event, overlay) {
    const dialog = overlay?.querySelector('[role="dialog"]');
    if (!dialog) return;
    const focusable = [...dialog.querySelectorAll(MODAL_FOCUSABLE_SELECTOR)].filter(
        element => !element.hidden && element.getAttribute('aria-hidden') !== 'true'
    );
    if (!focusable.length) {
        event.preventDefault();
        dialog.focus();
        return;
    }

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
        event.preventDefault();
        last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
        event.preventDefault();
        first.focus();
    }
}

function showConfirmModal(options) {
    const { title, icon, content, warning, confirmText, isDanger, onConfirm } = options;
    
    document.getElementById('confirm-modal-title').textContent = title || 'Confirm Transaction';
    document.getElementById('confirm-modal-icon').textContent = icon || '⚡';
    document.getElementById('confirm-modal-content').innerHTML = content || '';
    
    const warningEl = document.getElementById('confirm-modal-warning');
    if (warning) {
        warningEl.style.display = 'flex';
        document.getElementById('confirm-modal-warning-text').textContent = warning;
    } else {
        warningEl.style.display = 'none';
    }
    
    const confirmBtn = document.getElementById('confirm-modal-confirm-btn');
    confirmBtn.textContent = confirmText || 'Confirm';
    confirmBtn.classList.toggle('danger', isDanger || false);
    
    pendingConfirmCallback = onConfirm;
    confirmModalReturnFocus = document.activeElement;
    openModalOverlay(
        document.getElementById('confirm-modal-overlay'),
        document.getElementById('confirm-modal-cancel-btn')
    );
}

function hideConfirmModal() {
    closeModalOverlay(document.getElementById('confirm-modal-overlay'));
    pendingConfirmCallback = null;
    if (confirmModalReturnFocus?.isConnected) confirmModalReturnFocus.focus();
    confirmModalReturnFocus = null;
}

function executeConfirmedTransaction() {
    if (pendingConfirmCallback) {
        pendingConfirmCallback();
    }
    hideConfirmModal();
}

// Helper to build player row HTML
function buildPlayerRow(action, actionClass, name, info) {
    return `
        <div class="confirm-modal-row">
            <span class="confirm-modal-action ${actionClass}">${action}</span>
            <div class="confirm-modal-player">
                <div class="confirm-modal-player-name">${name}</div>
                ${info ? `<div class="confirm-modal-player-info">${info}</div>` : ''}
            </div>
        </div>
    `;
}

// ====== PLAYER DETAIL MODAL ======

let playerModalReturnFocus = null;
let playerModalReturnHash = '#teams/all-rosters';

function cleanPlayerProfileLabel(value) {
    return String(value || '')
        .replace(/ \*$/, '')
        .replace(/^\s*(?:QB|RB|WR|TE|K|D\/ST|DEF|HC|OL)\s+/i, '')
        .replace(/\s+\([A-Z]{2,4}\)\s*$/, '')
        .replace(/,+$/, '')
        .trim();
}

function normalizePlayerProfileKey(value) {
    return cleanPlayerProfileLabel(value)
        .replace(/[’]/g, "'")
        .replace(/\s+(?:Sr\.?|Jr\.?|II|III|IV|V)$/i, '')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, ' ')
        .trim();
}

function canonicalPlayerProfilePosition(position) {
    const value = String(position || '').toUpperCase();
    return value === 'DEF' ? 'D/ST' : value;
}

function playerProfileIdentityKey(value, position = '') {
    const key = normalizePlayerProfileKey(value);
    const normalizedPosition = canonicalPlayerProfilePosition(position);
    return key && (normalizedPosition === 'D/ST' || normalizedPosition === 'OL')
        ? `${key}::${normalizedPosition.toLowerCase()}`
        : key;
}

function getPlayerCareerProfile(value, position = '') {
    const profiles = sharedData?.hall_of_fame?.player_career_stats
        || data?.hall_of_fame?.player_career_stats
        || {};
    const requestedKey = normalizePlayerProfileKey(value);
    if (!requestedKey) return null;

    const allProfiles = Object.values(profiles);
    const requestedIdentity = playerProfileIdentityKey(value, position);
    const requestedPosition = canonicalPlayerProfilePosition(position);
    const exact = allProfiles.find(profile =>
        (!requestedPosition || canonicalPlayerProfilePosition(profile.position) === requestedPosition)
        && (
            profile.profile_key === requestedIdentity
            || normalizePlayerProfileKey(profile.name) === requestedKey
            || (profile.aliases || []).some(alias => normalizePlayerProfileKey(alias) === requestedKey)
        )
    );
    if (exact) return exact;

    const parts = requestedKey.split(' ');
    if (parts.length < 2 || parts[0].length > 2) return null;
    const matches = allProfiles.filter(profile => {
        if (requestedPosition && canonicalPlayerProfilePosition(profile.position) !== requestedPosition) return false;
        const candidate = normalizePlayerProfileKey(profile.name).split(' ');
        if (candidate.length < 2 || candidate.at(-1) !== parts.at(-1)) return false;
        const candidateFirst = candidate.slice(0, -1).every(part => part.length === 1)
            ? candidate.slice(0, -1).join('')
            : candidate[0];
        return parts[0].length === 2
            ? candidateFirst === parts[0]
            : candidateFirst.startsWith(parts[0]);
    });
    return matches.length === 1 ? matches[0] : null;
}

function getPlayerCareerProfileByKey(profileKey) {
    const profiles = sharedData?.hall_of_fame?.player_career_stats
        || data?.hall_of_fame?.player_career_stats
        || {};
    return Object.values(profiles).find(profile => profile.profile_key === profileKey) || null;
}

function playerNameMatches(value, profileOrName, position = '') {
    const profile = typeof profileOrName === 'object'
        ? profileOrName
        : getPlayerCareerProfile(profileOrName, position);
    const valueKey = normalizePlayerProfileKey(value);
    if (!valueKey) return false;
    const requestedPosition = canonicalPlayerProfilePosition(position);
    const profilePosition = canonicalPlayerProfilePosition(profile?.position);
    if (requestedPosition && profilePosition && requestedPosition !== profilePosition) return false;
    if (!profile) return valueKey === normalizePlayerProfileKey(profileOrName);
    if (valueKey === normalizePlayerProfileKey(profile.name)) return true;
    return (profile.aliases || []).some(alias => normalizePlayerProfileKey(alias) === valueKey);
}

function liveTeamLabel(abbrev) {
    const teams = sharedData?.teams || data?.teams || [];
    const owner = teams.find(team => team.abbrev === abbrev)?.owner;
    return owner ? compactOwnerLabel(owner) : abbrev;
}

function playerFranchiseLabel(abbrev) {
    return `${liveTeamLabel(abbrev)} (${abbrev})`;
}

function playerDraftTeamLabel(selectedBy, draft) {
    return draftTeamDisplayLabel(selectedBy, draft);
}

function getLivePlayerStatus(profileOrName) {
    const rosters = sharedData?.rosters || data?.rosters || {};
    for (const [owner, rosterData] of Object.entries(rosters)) {
        const players = Array.isArray(rosterData)
            ? rosterData
            : [...(rosterData.roster || []), ...(rosterData.taxi_squad || []).map(p => ({ ...p, taxi: true }))];
        const player = players.find(candidate => playerNameMatches(
            candidate.name,
            profileOrName,
            candidate.position
        ));
        if (player) {
            return {
                owner,
                player,
                label: player.taxi ? 'Taxi squad' : 'Active roster',
                tone: player.taxi ? 'taxi' : 'active',
            };
        }
    }

    const faPool = sharedData?.fa_pool || data?.fa_pool || [];
    const freeAgents = Array.isArray(faPool) ? faPool : (faPool.players || []);
    if (freeAgents.some(player => playerNameMatches(
        typeof player === 'object' ? player.name : player,
        profileOrName,
        typeof player === 'object' ? player.position : ''
    ))) {
        return { owner: null, player: null, label: 'Free agent', tone: 'free-agent' };
    }
    return { owner: null, player: null, label: 'Not rostered', tone: 'unrostered' };
}

function getPlayerDraftHistory(profileOrName) {
    const drafts = sharedData?.drafts || data?.drafts || [];
    const selections = [];
    const profilePosition = canonicalPlayerProfilePosition(profileOrName?.position);
    for (const draft of drafts) {
        const draftPosition = /OL Expansion Draft/i.test(draft.name || '') ? 'OL' : '';
        for (const round of (draft.rounds || [])) {
            for (const pick of (round.picks || [])) {
                const pickPosition = pick.position || draftPosition;
                if (profilePosition === 'OL' && pickPosition !== 'OL') continue;
                if (profilePosition === 'D/ST' && pickPosition === 'OL') continue;
                if (!pick.player || pick.player === 'PASS' || !playerNameMatches(pick.player, profileOrName, pickPosition)) {
                    continue;
                }
                const roundMatch = String(round.round).match(/\d+/);
                const roundNumber = roundMatch ? roundMatch[0] : String(round.round);
                const pickNumber = /^\d+$/.test(String(pick.pick))
                    ? String(pick.pick).padStart(2, '0')
                    : String(pick.pick);
                const isExpansion = draft.type === 'expansion' || /Expansion Draft/i.test(draft.name || '');
                const isFreeAgentAddition = /free agent/i.test(String(round.round));
                const slot = isExpansion
                    ? `${isFreeAgentAddition ? 'FA addition' : 'Expansion pick'} ${pick.pick}`
                    : `${roundNumber}.${pickNumber}`;
                selections.push({
                    draftName: draft.name,
                    year: draftYear(draft),
                    slot,
                    taxi: /taxi/i.test(String(round.round)),
                    selectedBy: pick.team,
                    expansion: isExpansion,
                });
            }
        }
    }
    return selections.sort((a, b) => {
        if (a.year !== b.year) return a.year - b.year;
        const phase = selection => {
            if (selection.draftName === 'Founding Draft') return 0;
            if (selection.expansion) return 2;
            if (/midseason/i.test(selection.draftName)) return 3;
            return 1;
        };
        if (phase(a) !== phase(b)) return phase(a) - phase(b);
        return a.slot.localeCompare(b.slot, undefined, { numeric: true });
    });
}

function transactionPlayerValues(tx) {
    return [
        ...(tx.proposer_gives?.players || []),
        ...(tx.proposer_receives?.players || []),
        tx.added,
        tx.activated,
        tx.released,
    ].filter(Boolean).map(player => typeof player === 'object'
        ? player
        : { name: player, position: '' }
    );
}

function getPlayerTransactionHistory(profileOrName) {
    const transactions = sharedData?.transactions || data?.transactions || [];
    const profile = typeof profileOrName === 'object'
        ? profileOrName
        : getPlayerCareerProfile(profileOrName);
    const searchTerms = [
        typeof profileOrName === 'string' ? profileOrName : '',
        profile?.name,
        ...(profile?.aliases || []),
    ].map(normalizePlayerProfileKey).filter(term => term.length > 3);

    return transactions.filter(tx => {
        const profilePosition = canonicalPlayerProfilePosition(profile?.position);
        if (transactionPlayerValues(tx).some(player => {
            if ((profilePosition === 'OL' || profilePosition === 'D/ST') && !player.position) return false;
            return playerNameMatches(player.name, profileOrName, player.position);
        })) {
            return true;
        }
        const message = ` ${normalizePlayerProfileKey(tx.message || '')} `;
        if (profilePosition === 'OL') {
            return searchTerms.some(term => message.includes(` ol ${term} `));
        }
        if (profilePosition === 'D/ST') {
            return searchTerms.some(term =>
                message.includes(` d st ${term} `) || message.includes(` def ${term} `)
            );
        }
        return searchTerms.some(term => message.includes(` ${term} `));
    });
}

function describePlayerTransaction(tx, profileOrName) {
    const proposerGives = tx.proposer_gives?.players || [];
    const proposerReceives = tx.proposer_receives?.players || [];
    if (proposerGives.some(player => playerNameMatches(player.name || player, profileOrName))) {
        return `Traded ${liveTeamLabel(tx.proposer)} (${tx.proposer}) → ${liveTeamLabel(tx.partner)} (${tx.partner})`;
    }
    if (proposerReceives.some(player => playerNameMatches(player.name || player, profileOrName))) {
        return `Traded ${liveTeamLabel(tx.partner)} (${tx.partner}) → ${liveTeamLabel(tx.proposer)} (${tx.proposer})`;
    }
    if (tx.added && playerNameMatches(typeof tx.added === 'object' ? tx.added.name : tx.added, profileOrName)) {
        return `Added from free agency by ${liveTeamLabel(tx.team)} (${tx.team})`;
    }
    if (tx.activated && playerNameMatches(typeof tx.activated === 'object' ? tx.activated.name : tx.activated, profileOrName)) {
        return `Activated from taxi by ${liveTeamLabel(tx.team)} (${tx.team})`;
    }
    if (tx.released && playerNameMatches(typeof tx.released === 'object' ? tx.released.name : tx.released, profileOrName)) {
        return `Released by ${liveTeamLabel(tx.team)} (${tx.team})`;
    }
    const { cleanMessage } = getTransactionDate(tx);
    return String(cleanMessage || formatTransactionMessage(tx) || 'Roster transaction')
        .replace(/\s*\|\s*/g, ' · ');
}

function playerTransactionLabel(tx) {
    const type = getEffectiveTxType(tx);
    if (type === 'trade') return 'Trade';
    if (type === 'fa_activation') return 'Free agency';
    if (type === 'taxi_activation') return 'Taxi move';
    if (type === 'release') return 'Release';
    return 'Roster move';
}

function formatPlayerPoints(value) {
    return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 1 });
}

function calculatePlayerAge(birthDate, today = new Date()) {
    const match = String(birthDate || '').match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) return null;

    const [, year, month, day] = match.map(Number);
    const birthUtc = Date.UTC(year, month - 1, day);
    const birth = new Date(birthUtc);
    if (
        birth.getUTCFullYear() !== year
        || birth.getUTCMonth() !== month - 1
        || birth.getUTCDate() !== day
        || Number.isNaN(today.getTime())
    ) return null;

    const todayUtc = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
    if (birthUtc > todayUtc) return null;

    let years = today.getFullYear() - year;
    let lastBirthdayUtc = Date.UTC(year + years, month - 1, day);
    if (lastBirthdayUtc > todayUtc) {
        years -= 1;
        lastBirthdayUtc = Date.UTC(year + years, month - 1, day);
    }

    const days = Math.floor((todayUtc - lastBirthdayUtc) / (24 * 60 * 60 * 1000));
    if (years < 0 || years >= 120 || days < 0) return null;
    return `${years} ${years === 1 ? 'year' : 'years'}, ${days} ${days === 1 ? 'day' : 'days'}`;
}

function showPlayerModal(rawName, requestedPosition = '', { updateRoute = true } = {}) {
    const requestedName = cleanPlayerProfileLabel(rawName);
    if (!requestedName) return;

    const profile = getPlayerCareerProfile(requestedName, requestedPosition);
    const displayName = profile?.name || requestedName;
    const liveStatus = getLivePlayerStatus(profile || requestedName);

    if (updateRoute && profile?.profile_key) {
        playerModalReturnHash = location.hash && !location.hash.startsWith('#player/')
            ? location.hash
            : '#teams/all-rosters';
        history.pushState(
            { playerProfile: true, returnHash: playerModalReturnHash },
            '',
            `#player/${encodeURIComponent(profile.profile_key)}`
        );
    }
    if (profile) {
        const title = `${profile.name} Player Profile · QPFL`;
        const description = `${profile.position || 'QPFL'} career stats, ownership history, draft history, and game log.`;
        document.title = title;
        document.querySelector('meta[name="description"]')?.setAttribute('content', description);
        document.querySelector('meta[property="og:title"]')?.setAttribute('content', title);
        document.querySelector('meta[property="og:description"]')?.setAttribute('content', description);
        document.querySelector('meta[property="og:url"]')?.setAttribute('content', location.href);
    }

    const weekData = [];
    let playerPos = liveStatus.player?.position || profile?.position || null;
    let playerNflTeam = liveStatus.player?.nfl_team || profile?.nfl_team || null;

    for (const w of (data.weeks || [])) {
        if (!w.has_scores) continue;
        for (const m of (w.matchups || [])) {
            for (const t of [m.team1, m.team2]) {
                if (!t) continue;
                const p = (t.roster || []).find(r => playerNameMatches(
                    r.name,
                    profile || requestedName,
                    r.position
                ));
                if (p) {
                    if (!playerPos) playerPos = p.position;
                    if (!playerNflTeam) playerNflTeam = p.nfl_team;
                    weekData.push({
                        week: w.week,
                        score: p.score ?? 0,
                        starter: p.starter,
                        fantasyAbbrev: t.abbrev,
                        breakdown: p.breakdown || null
                    });
                }
            }
        }
    }

    // Fall back to rosters for position/team if not in any scored week
    if (!playerPos && data.rosters) {
        for (const [, roster] of Object.entries(data.rosters)) {
            const found = (roster || []).find(p => playerNameMatches(
                p.name,
                profile || requestedName,
                p.position
            ));
            if (found) { playerPos = found.position; playerNflTeam = found.nfl_team; break; }
        }
    }

    const modal = document.getElementById('player-modal-overlay');
    if (!modal) return;

    const awards = profile?.awards || [];
    const playerAge = calculatePlayerAge(profile?.birth_date);
    document.getElementById('player-modal-name').textContent = displayName;
    document.getElementById('player-modal-meta').innerHTML = [
        playerPos ? `<span class="position-tag">${escapeHtml(playerPos)}</span>` : '',
        playerNflTeam ? `<span class="player-team">${escapeHtml(playerNflTeam)}</span>` : '',
        playerAge === null ? '' : `<span class="player-age">Age ${playerAge}</span>`,
        `<span class="player-status-pill ${escapeHtml(liveStatus.tone)}">${escapeHtml(liveStatus.label)}</span>`,
        ...awards.map(award => `<span class="player-award-badge">★ ${escapeHtml(String(award.year))} ${escapeHtml(award.title)}</span>`),
    ].join('');

    weekData.sort((a, b) => a.week - b.week);
    const careerSeasons = Object.entries(profile?.seasons || {})
        .sort(([seasonA], [seasonB]) => Number(seasonB) - Number(seasonA));
    const careerGames = Number(profile?.games) || 0;
    const careerPpg = careerGames ? Number(profile?.total_points || 0) / careerGames : null;
    const ownerValue = liveStatus.owner
        ? playerFranchiseLabel(liveStatus.owner)
        : 'None';

    document.getElementById('player-modal-stats').innerHTML = `
        <div class="player-modal-summary">
            <div class="player-modal-stat">
                <div class="player-modal-stat-val">${formatPlayerPoints(profile?.total_points)}</div>
                <div class="player-modal-stat-label">Career Pts</div>
            </div>
            <div class="player-modal-stat">
                <div class="player-modal-stat-val">${careerPpg === null ? '—' : formatPlayerPoints(careerPpg)}</div>
                <div class="player-modal-stat-label">PPG</div>
            </div>
            <div class="player-modal-stat">
                <div class="player-modal-stat-val">${careerSeasons.length}</div>
                <div class="player-modal-stat-label">Seasons</div>
            </div>
            <div class="player-modal-stat">
                <div class="player-modal-stat-val">${profile?.starts || 0}</div>
                <div class="player-modal-stat-label">Starts</div>
            </div>
            <div class="player-modal-stat">
                <div class="player-modal-stat-val">${profile?.games || 0}</div>
                <div class="player-modal-stat-label">Games</div>
            </div>
        </div>`;

    const draftHistory = getPlayerDraftHistory(profile || requestedName);
    const originalDraft = draftHistory[0];
    const transactions = getPlayerTransactionHistory(profile || requestedName);
    const careerRows = careerSeasons.length ? careerSeasons.map(([season, stats]) => {
        const ownerLabels = (stats.owners || []).map(owner => owner).join(' → ') || '—';
        const rank = stats.position_rank && stats.position
            ? `${stats.position}${stats.position_rank}`
            : '—';
        const seasonGames = Number(stats.games) || 0;
        const seasonPpg = seasonGames ? Number(stats.points || 0) / seasonGames : null;
        return `
            <tr>
                <td><strong>${escapeHtml(season)}</strong></td>
                <td>${escapeHtml(ownerLabels)}</td>
                <td>${escapeHtml(rank)}</td>
                <td class="num"><strong>${formatPlayerPoints(stats.points)}</strong></td>
                <td class="num">${seasonPpg === null ? '—' : formatPlayerPoints(seasonPpg)}</td>
                <td class="num">${stats.starts}/${stats.games}</td>
            </tr>
        `;
    }).join('') : '';

    const transactionItems = transactions.map(tx => {
        const { dateStr } = getTransactionDate(tx);
        const week = Number.isFinite(parseInt(tx.week, 10))
            ? `Week ${parseInt(tx.week, 10)}`
            : (tx.week || 'Offseason');
        const seasonOrder = Number.parseInt(tx.season, 10) || 0;
        const weekOrder = Number.parseInt(tx.week, 10);
        return {
            order: seasonOrder * 100 + (Number.isFinite(weekOrder) ? weekOrder : 99),
            markup: `
                <div class="player-history-item">
                    <span class="player-history-dot" aria-hidden="true"></span>
                    <div>
                        <div class="player-history-title">
                            <strong>${escapeHtml(playerTransactionLabel(tx))}</strong>
                            <span>${escapeHtml(`${tx.season || ''} · ${week} · ${dateStr}`)}</span>
                        </div>
                        <p>${escapeHtml(describePlayerTransaction(tx, profile || requestedName))}</p>
                    </div>
                </div>
            `,
        };
    });

    const draftHistoryItems = draftHistory.map(selection => {
        const phaseOrder = /midseason/i.test(selection.draftName)
            ? 50
            : (selection.expansion ? 20 : 10);
        return {
            order: selection.year * 100 + phaseOrder,
            markup: `
                <div class="player-history-item">
                    <span class="player-history-dot draft" aria-hidden="true"></span>
                    <div>
                        <div class="player-history-title">
                            <strong>${selection.expansion ? 'Expansion acquisition' : 'Drafted'} · ${escapeHtml(selection.slot)}${selection.taxi ? ' Taxi' : ''}</strong>
                            <span>${escapeHtml(String(selection.year))}</span>
                        </div>
                        <p>${escapeHtml(selection.draftName)} · Selected by ${escapeHtml(playerDraftTeamLabel(selection.selectedBy, selection))}</p>
                    </div>
                </div>
            `,
        };
    });
    const historyItems = [...transactionItems, ...draftHistoryItems]
        .sort((a, b) => b.order - a.order)
        .map(item => item.markup)
        .join('');

    document.getElementById('player-modal-profile').innerHTML = `
        <section class="player-profile-section">
            <h4>Current status</h4>
            <div class="player-profile-facts">
                <div><span>Current owner</span><strong>${escapeHtml(ownerValue)}</strong></div>
                <div><span>Roster status</span><strong>${escapeHtml(liveStatus.label)}</strong></div>
                <div><span>Drafted by</span><strong>${originalDraft ? escapeHtml(playerDraftTeamLabel(originalDraft.selectedBy, originalDraft)) : '—'}</strong></div>
                <div><span>Original draft</span><strong>${originalDraft ? `${escapeHtml(originalDraft.slot)}${originalDraft.taxi ? ' Taxi' : ''} · ${escapeHtml(String(originalDraft.year))}` : 'Undrafted'}</strong></div>
            </div>
        </section>
        <section class="player-profile-section">
            <h4>Career by season</h4>
            ${careerRows ? `
                <div class="player-modal-table-wrap">
                    <table class="player-modal-table player-career-table">
                        <thead><tr><th>Season</th><th>QPFL team</th><th>Rank</th><th class="num">Points</th><th class="num">PPG</th><th class="num">Starts</th></tr></thead>
                        <tbody>${careerRows}</tbody>
                    </table>
                </div>
            ` : '<p class="player-modal-no-data">No scored QPFL seasons yet.</p>'}
        </section>
        <section class="player-profile-section">
            <h4>Ownership &amp; transaction history</h4>
            <div class="player-history">
                <div class="player-history-item current">
                    <span class="player-history-dot current" aria-hidden="true"></span>
                    <div>
                        <div class="player-history-title"><strong>Current</strong><span>${escapeHtml(liveStatus.label)}</span></div>
                        <p>${liveStatus.owner ? escapeHtml(playerFranchiseLabel(liveStatus.owner)) : 'No current owner'}</p>
                    </div>
                </div>
                ${historyItems}
                ${!historyItems ? '<p class="player-modal-no-data">No ownership events recorded.</p>' : ''}
            </div>
        </section>
    `;

    document.getElementById('player-modal-weeks').innerHTML = weekData.length ? `
        <section class="player-profile-section player-game-log">
            <h4>${escapeHtml(String(currentSeason || data.season))} game log</h4>
            <div class="player-modal-table-wrap">
                <table class="player-modal-table">
                    <thead><tr><th>Week</th><th>Team</th><th class="num">Score</th><th class="num">Role</th></tr></thead>
                    <tbody>
                        ${weekData.map(w => {
                            const bd = w.breakdown ? renderBreakdown(w.breakdown) : '';
                            const scoreCell = bd
                                ? `<details class="score-breakdown"><summary class="player-score has-breakdown">${w.score.toFixed(0)}</summary>${bd}</details>`
                                : `<strong>${w.score.toFixed(0)}</strong>`;
                            return `
                            <tr>
                                <td>Wk ${w.week}</td>
                                <td><span class="team-code">${escapeHtml(w.fantasyAbbrev)}</span></td>
                                <td class="num">${scoreCell}</td>
                                <td class="num"><span class="${w.starter ? 'pm-starter' : 'pm-bench'}">${w.starter ? 'Start' : 'Bench'}</span></td>
                            </tr>`;
                        }).join('')}
                    </tbody>
                </table>
            </div>
        </section>` : '';

    playerModalReturnFocus = document.activeElement;
    const shareStatus = document.getElementById('player-modal-share-status');
    if (shareStatus) shareStatus.textContent = '';
    const copyButton = document.getElementById('player-modal-copy-link');
    if (copyButton) copyButton.onclick = copyPlayerProfileLink;
    const modalBody = modal.querySelector('.player-modal-body');
    if (modalBody) modalBody.scrollTop = 0;
    openModalOverlay(modal, modal.querySelector('.player-modal-close'));
}

function showPlayerModalByProfileKey(profileKey, options = {}) {
    const profile = getPlayerCareerProfileByKey(profileKey);
    if (!profile) {
        history.replaceState(null, '', '#teams/all-rosters');
        applyHash();
        return;
    }
    playerModalReturnHash = history.state?.returnHash || '#teams/all-rosters';
    showPlayerModal(profile.name, profile.position, options);
}

async function copyPlayerProfileLink() {
    const status = document.getElementById('player-modal-share-status');
    try {
        await navigator.clipboard.writeText(location.href);
        if (status) status.textContent = 'Link copied';
    } catch (error) {
        const input = document.createElement('textarea');
        input.value = location.href;
        input.setAttribute('readonly', '');
        input.style.position = 'fixed';
        input.style.opacity = '0';
        document.body.appendChild(input);
        input.select();
        const copied = document.execCommand('copy');
        input.remove();
        if (status) status.textContent = copied ? 'Link copied' : 'Could not copy link';
    }
}

function closePlayerModalOverlay({ restoreFocus = true } = {}) {
    const el = document.getElementById('player-modal-overlay');
    closeModalOverlay(el);
    if (restoreFocus && playerModalReturnFocus?.isConnected) playerModalReturnFocus.focus();
    playerModalReturnFocus = null;
}

function hidePlayerModal() {
    closePlayerModalOverlay();
    if (!location.hash.startsWith('#player/')) return;
    if (history.state?.playerProfile) {
        history.back();
        return;
    }
    history.replaceState(null, '', playerModalReturnHash || '#teams/all-rosters');
    applyHash();
}

document.body.addEventListener('click', async (e) => {
    const hallSectionTarget = e.target.closest('[data-hof-section]');
    if (hallSectionTarget) {
        const section = document.getElementById(hallSectionTarget.dataset.hofSection);
        section?.scrollIntoView({ block: 'start' });
        return;
    }

    const emptyActionTarget = e.target.closest('[data-empty-action]');
    if (emptyActionTarget) {
        e.preventDefault();
        const action = emptyActionTarget.dataset.emptyAction;
        if (action === 'clear-transaction-filters') {
            clearTransactionFilters();
            renderTransactions();
        } else if (action === 'clear-roster-search') {
            allRostersSearchQuery = '';
            updateAllRostersSearch();
            document.getElementById('all-rosters-search')?.focus();
        } else if (action === 'current-season' && LIVE_SEASON !== null) {
            await loadData(LIVE_SEASON);
        }
        return;
    }

    const playerTarget = e.target.closest('.player-profile-trigger');
    if (playerTarget) {
        e.preventDefault();
        e.stopPropagation();
        playerTarget.setAttribute('aria-busy', 'true');
        try {
            await Promise.all([
                ensureSharedResource('hall_of_fame'),
                ensureSharedResource('transactions'),
                ensureSharedResource('drafts'),
                ensureCurrentSeasonFiles({ rosters: true }),
                ensureAllSeasonWeeks(),
            ]);
            showPlayerModal(
                playerTarget.dataset.playerName || playerTarget.textContent.trim(),
                playerTarget.dataset.playerPosition || ''
            );
        } catch (error) {
            console.error('Error loading player profile:', error);
        } finally {
            playerTarget.removeAttribute('aria-busy');
        }
        return;
    }

    const teamTarget = e.target.closest('.team-profile-trigger');
    if (teamTarget) {
        e.preventDefault();
        e.stopPropagation();
        const abbrev = teamTarget.dataset.teamAbbrev;
        if (!abbrev) return;
        if (!confirmManageNavigation('teams')) return;
        history.pushState(null, '', `#teams/history/${encodeURIComponent(abbrev)}`);
        await navigateToView('teams', 'history', abbrev);
        focusMainContentOnMobile();
        return;
    }

    const routeTarget = e.target.closest('[data-route]');
    if (!routeTarget) return;
    e.preventDefault();
    const route = routeTarget.dataset.route;
    if (!route) return;
    if (!confirmManageNavigation(parseHashRoute(route.replace(/^#/, '')).view)) return;
    history.pushState(null, '', route);
    await applyHash({ focus: true });
}, { capture: true });

document.body.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    if (e.target.closest('button, a, input, select, textarea')) return;
    const target = e.target.closest('[role="button"], [role="link"]');
    if (!target) return;
    e.preventDefault();
    target.click();
});

// Escape keypress to close modal
document.addEventListener('keydown', (e) => {
    const activeOverlay = document.querySelector('.confirm-modal-overlay.active');
    if (e.key === 'Tab' && activeOverlay) {
        trapModalFocus(e, activeOverlay);
        return;
    }
    if (e.key === 'Escape' && document.getElementById('confirm-modal-overlay').classList.contains('active')) {
        e.preventDefault();
        hideConfirmModal();
    } else if (e.key === 'Escape' && document.getElementById('player-modal-overlay')?.classList.contains('active')) {
        e.preventDefault();
        hidePlayerModal();
    }
});

// ====== NFL DRAFT CHALLENGE ======
const NFL_DRAFT_API_URL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'https://qpfl-scoring.vercel.app/api/nfl-draft'
    : `${window.location.origin}/api/nfl-draft`;

let nflDraftState = {
    serverState: null
};

function isNflDraftChallengeActive() {
    return getActiveView() === 'drafts'
        && document.getElementById('drafts-challenge-subview')?.classList.contains('active');
}

async function initNflDraftView() {
    nflDraftState.serverState = null;
    renderNflDraftView();
    await loadNflDraftState();
    renderNflDraftView();
}

function nflDraftFallbackState(reason) {
    return {
        year: Number(sharedData?.season || LIVE_SEASON),
        title: 'Draft Challenge',
        lock_time: null,
        locked: false,
        pick_count: 0,
        max_player_name_length: 0,
        scoring: null,
        max_points: 0,
        prospects: [],
        submissions: {},
        visible_picks: {},
        actual_picks: [],
        scores: {},
        authed_team: null,
        warning: reason || null,
        unavailable: true
    };
}

async function loadNflDraftState() {
    const requestTeam = manageState.team;
    const requestPassword = manageState.password;
    const body = {
        action: 'get_state',
        year: Number(sharedData?.season || LIVE_SEASON)
    };
    if (requestTeam && requestPassword) {
        body.team = requestTeam;
        body.password = requestPassword;
    }
    try {
        const response = await fetch(NFL_DRAFT_API_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const result = await response.json();
        if (requestTeam !== manageState.team || requestPassword !== manageState.password) return;
        if (!response.ok) {
            nflDraftState.serverState = nflDraftFallbackState(result.error || 'Failed to load');
        } else {
            nflDraftState.serverState = result;
        }
    } catch (error) {
        if (requestTeam !== manageState.team || requestPassword !== manageState.password) return;
        nflDraftState.serverState = nflDraftFallbackState('Couldn\u2019t reach the API (offline or preview build). The UI will render but login/submit won\u2019t work until deployed.');
    }
}

function renderNflDraftView() {
    const container = document.getElementById('nfl-draft-content');
    if (!container) return;
    const state = nflDraftState.serverState;
    if (!state) {
        container.innerHTML = `
            <div class="nfl-draft-loading" role="status" aria-live="polite">
                <span class="nfl-draft-loading-spinner" aria-hidden="true"></span>
                <div>
                    <strong>Loading Draft Challenge</strong>
                    <span>Fetching entries and results…</span>
                </div>
            </div>`;
        return;
    }
    const warningBanner = state.warning && !state.unavailable
        ? `<div class="submit-status error" style="margin-bottom:1rem;">${escapeHtml(state.warning)}</div>`
        : '';
    const scoring = state.scoring || {};
    const graduatedThrough = Number(scoring.graduated_through_pick) || 0;
    const flatPoints = Number(scoring.flat_points_after) || 0;

    const rules = warningBanner + `
        <div class="nfl-draft-rules">
            <strong>How it works:</strong> Guess the order of the ${state.pick_count} first-round NFL Draft picks.
            A pick is correct if the named player is selected at that overall number, regardless of team.
            <br><br>
            <strong>Scoring:</strong> Picks 1\u2013${graduatedThrough} are worth their pick number.
            Picks ${graduatedThrough + 1}\u2013${state.pick_count} are worth ${flatPoints} pts each.
            Max possible: ${state.max_points} pts.
            <br><br>
            <strong>Deadline:</strong> Picks lock at the start of the NFL Draft. Other owners can't see your picks until then.
        </div>`;

    if (state.unavailable) {
        container.innerHTML = `
            <div class="nfl-draft-unavailable">
                <h3>Draft Challenge is temporarily unavailable</h3>
                <p>${escapeHtml(state.warning || 'The results service could not be reached. Please try again shortly.')}</p>
                <button type="button" class="lineup-btn secondary" id="nfl-draft-retry-btn">Try Again</button>
            </div>`;
        document.getElementById('nfl-draft-retry-btn')?.addEventListener('click', initNflDraftView);
        return;
    }

    if (state.locked) {
        container.innerHTML = renderNflDraftLocked(state) + rules;
        return;
    }

    if (manageState.team && manageState.password) {
        container.innerHTML = `<div class="nfl-draft-eyebrow">${escapeHtml(state.title)}</div>`
            + rules + renderNflDraftLoggedIn(state);
        wireNflDraftLoggedIn();
    } else {
        container.innerHTML = `<div class="nfl-draft-eyebrow">${escapeHtml(state.title)}</div>`
            + rules + renderNflDraftLoginPrompt(state);
    }
}

function formatCountdown(lockTimeIso) {
    const lock = new Date(lockTimeIso);
    const now = new Date();
    const diffMs = lock - now;
    if (diffMs <= 0) return 'Draft has begun';
    const totalSeconds = Math.floor(diffMs / 1000);
    const days = Math.floor(totalSeconds / 86400);
    const hours = Math.floor((totalSeconds % 86400) / 3600);
    const mins = Math.floor((totalSeconds % 3600) / 60);
    const parts = [];
    if (days) parts.push(`${days}d`);
    parts.push(`${hours}h`);
    parts.push(`${mins}m`);
    return `Picks lock in ${parts.join(' ')} (${lock.toLocaleString()})`;
}

function renderNflDraftSubmissionsChips(state) {
    const teams = draftChallengeTeams();
    if (!teams.length) return '';
    const submissions = state.submissions || {};
    const chips = teams.map(team => {
        const submitted = submissions[team.abbrev]?.submitted_at;
        const cls = submitted ? 'chip submitted' : 'chip';
        const label = submitted ? `${team.abbrev} \u2713` : team.abbrev;
        return `<span class="${cls}" title="${escapeHtml(team.name)}">${escapeHtml(label)}</span>`;
    }).join('');
    return `<div class="nfl-draft-submissions">${chips}</div>`;
}

function renderNflDraftLoginPrompt(state) {
    return `
        <div class="nfl-draft-countdown">${escapeHtml(formatCountdown(state.lock_time))}</div>
        <div class="nfl-draft-login-prompt">
            <h3>Log in to enter the Draft Challenge</h3>
            <p>Use the <strong>Log In</strong> button in the site header to view or save your picks.</p>
        </div>
        ${renderNflDraftSubmissionsChips(state)}`;
}

function renderNflDraftLoggedIn(state) {
    const teamName = teamNameFor(manageState.team) || manageState.team;
    const myEntry = state.visible_picks?.[manageState.team];
    const existingPicks = {};
    (myEntry?.picks || []).forEach(p => { existingPicks[p.pick] = p.player || ''; });
    const submittedLine = myEntry?.submitted_at
        ? `Last saved: ${new Date(myEntry.submitted_at).toLocaleString()}`
        : 'No picks submitted yet.';

    let rows = '';
    for (let i = 1; i <= state.pick_count; i++) {
        const val = existingPicks[i] || '';
        rows += `
            <div class="pick-num">#${i}</div>
            <input type="text" class="pick-input" data-pick="${i}" list="nfl-draft-prospects"
                aria-label="Player for pick ${i}" value="${escapeHtml(val)}"
                placeholder="Player for pick ${i}" maxlength="${state.max_player_name_length}">`;
    }

    const datalistOptions = (state.prospects || [])
        .map(name => `<option value="${escapeHtml(name)}">`).join('');

    return `
        <div class="nfl-draft-countdown">${escapeHtml(formatCountdown(state.lock_time))}</div>
        <div class="manage-header">
            <h3>Logged in as ${escapeHtml(teamName)}</h3>
        </div>
        <p class="submit-status">${escapeHtml(submittedLine)}</p>
        <datalist id="nfl-draft-prospects">${datalistOptions}</datalist>
        <div class="nfl-draft-picks-grid">${rows}</div>
        <div class="nfl-draft-actions">
            <button id="nfl-draft-submit-btn" class="lineup-btn primary large">Save My Picks</button>
            <button id="nfl-draft-clear-btn" class="lineup-btn secondary large">Clear Entry</button>
        </div>
        <div id="nfl-draft-submit-status" class="submit-status"></div>
        <h4 style="margin-top:1.5rem;">Who's submitted</h4>
        ${renderNflDraftSubmissionsChips(state)}`;
}

function wireNflDraftLoggedIn() {
    document.getElementById('nfl-draft-submit-btn').onclick = handleNflDraftSubmit;
    document.getElementById('nfl-draft-clear-btn').onclick = handleNflDraftClear;
}

async function handleNflDraftClear() {
    const statusEl = document.getElementById('nfl-draft-submit-status');
    const submitBtn = document.getElementById('nfl-draft-submit-btn');
    const clearBtn = document.getElementById('nfl-draft-clear-btn');

    const hasSavedEntry = !!nflDraftState.serverState?.visible_picks?.[manageState.team];
    const confirmMsg = hasSavedEntry
        ? 'Clear your saved entry? This will remove your picks from the server.'
        : 'Clear all fields?';
    if (!confirm(confirmMsg)) return;

    document.querySelectorAll('.pick-input').forEach(input => { input.value = ''; });

    if (!hasSavedEntry) {
        statusEl.className = 'submit-status';
        statusEl.textContent = 'Fields cleared. Click Save My Picks to submit.';
        return;
    }

    statusEl.className = 'submit-status loading';
    statusEl.textContent = 'Clearing entry...';
    submitBtn.disabled = true;
    clearBtn.disabled = true;

    try {
        const response = await fetch(NFL_DRAFT_API_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: 'clear',
                year: nflDraftState.serverState.year,
                team: manageState.team,
                password: manageState.password
            })
        });
        const result = await response.json();
        if (!response.ok || !result.success) {
            statusEl.className = 'submit-status error';
            statusEl.textContent = result.error || 'Failed to clear entry.';
            submitBtn.disabled = false;
            clearBtn.disabled = false;
            return;
        }
        nflDraftState.serverState = result;
        renderNflDraftView();
        const freshStatus = document.getElementById('nfl-draft-submit-status');
        if (freshStatus) {
            freshStatus.className = 'submit-status success';
            freshStatus.textContent = 'Entry cleared.';
        }
    } catch (error) {
        statusEl.className = 'submit-status error';
        statusEl.textContent = 'Network error - please try again.';
        submitBtn.disabled = false;
        clearBtn.disabled = false;
    }
}

async function handleNflDraftSubmit() {
    const statusEl = document.getElementById('nfl-draft-submit-status');
    const submitBtn = document.getElementById('nfl-draft-submit-btn');
    statusEl.className = 'submit-status loading';
    statusEl.textContent = 'Saving picks...';
    submitBtn.disabled = true;

    const inputs = document.querySelectorAll('.pick-input');
    const picks = [];
    inputs.forEach(input => {
        const pickNum = parseInt(input.dataset.pick, 10);
        const player = (input.value || '').trim();
        picks.push({ pick: pickNum, player });
    });

    try {
        const response = await fetch(NFL_DRAFT_API_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: 'submit',
                year: nflDraftState.serverState.year,
                team: manageState.team,
                password: manageState.password,
                picks
            })
        });
        const result = await response.json();
        if (!response.ok || !result.success) {
            statusEl.className = 'submit-status error';
            statusEl.textContent = result.error || 'Failed to save picks.';
            submitBtn.disabled = false;
            return;
        }
        nflDraftState.serverState = result;
        renderNflDraftView();
        const freshStatus = document.getElementById('nfl-draft-submit-status');
        if (freshStatus) {
            freshStatus.className = 'submit-status success';
            freshStatus.textContent = 'Picks saved!';
        }
    } catch (error) {
        statusEl.className = 'submit-status error';
        statusEl.textContent = 'Network error - please try again.';
        submitBtn.disabled = false;
    }
}

function renderNflDraftLocked(state) {
    const scores = state.scores || {};
    const teams = draftChallengeTeams();
    const abbrevs = Object.keys(state.visible_picks || {});
    const gradedPicks = new Set(
        (state.actual_picks || [])
            .map(pick => Number(pick.pick))
            .filter(pick => Number.isInteger(pick) && pick >= 1 && pick <= state.pick_count)
    ).size;
    const isComplete = gradedPicks === state.pick_count;
    const maxPoints = state.max_points;

    const leaderboard = abbrevs
        .map(abbrev => ({
            abbrev,
            name: teamNameFor(abbrev) || abbrev,
            points: scores[abbrev]?.points ?? 0,
            correct: scores[abbrev]?.correct ?? 0
        }))
        .sort((a, b) =>
            b.points - a.points ||
            b.correct - a.correct ||
            a.abbrev.localeCompare(b.abbrev)
        );

    let previousResult = null;
    leaderboard.forEach((row, index) => {
        const resultKey = `${row.points}|${row.correct}`;
        row.rank = resultKey === previousResult ? leaderboard[index - 1].rank : index + 1;
        previousResult = resultKey;
    });

    const podium = leaderboard.length ? `
        <div class="nfl-draft-podium" aria-label="${isComplete ? 'Final podium' : 'Current leaders'}">
            ${leaderboard.slice(0, 3).map(row => `
                <article class="nfl-draft-podium-card place-${row.rank}">
                    <span class="nfl-draft-podium-place">${isComplete
                        ? (row.rank === 1 ? 'Champion' : (row.rank === 2 ? 'Runner-up' : 'Third Place'))
                        : (row.rank === 1 ? 'Current Leader' : `#${row.rank}`)}</span>
                    <strong>${escapeHtml(row.name)}</strong>
                    <span>${escapeHtml(row.abbrev)}</span>
                    <div><b>${row.points}</b> pts · ${row.correct} correct</div>
                </article>
            `).join('')}
        </div>` : '';

    const leaderboardRows = leaderboard.map(row => `
        <tr>
            <td>${row.rank}</td>
            <td>${escapeHtml(row.name)} <span class="nfl-draft-team-code">(${escapeHtml(row.abbrev)})</span></td>
            <td>${row.points}</td>
            <td>${row.correct} / ${state.pick_count}</td>
        </tr>`).join('');

    const leaderboardTable = leaderboard.length ? `
        <div class="nfl-draft-leaderboard">
            <table>
                <thead>
                    <tr><th>Rank</th><th>Team</th><th>Points</th><th>Correct</th></tr>
                </thead>
                <tbody>${leaderboardRows}</tbody>
            </table>
        </div>` : `
        <div class="nfl-draft-empty">
            <h3>No entries were submitted</h3>
            <p>The final draft order is available below, but there is no challenge leaderboard for this season.</p>
        </div>`;

    const orderedAbbrevs = leaderboard.map(row => row.abbrev);
    const actualByPick = {};
    (state.actual_picks || []).forEach(pick => {
        actualByPick[pick.pick] = pick.player || '';
    });

    const header = `<tr>
        <th>Pick</th>
        <th>Actual</th>
        ${orderedAbbrevs.map(abbrev => `<th>${escapeHtml(abbrev)}</th>`).join('')}
    </tr>`;

    const bodyRows = [];
    for (let i = 1; i <= state.pick_count; i++) {
        const actual = actualByPick[i] || '';
        const cells = orderedAbbrevs.map(abbrev => {
            const picks = state.visible_picks[abbrev]?.picks || [];
            const pick = picks.find(entry => entry.pick === i);
            const guess = pick?.player || '';
            if (!guess) return '<td class="empty">&mdash;</td>';
            const correct = actual && normalizeClientName(guess) === normalizeClientName(actual);
            return `<td class="${correct ? 'correct' : 'incorrect'}">${escapeHtml(guess)}</td>`;
        }).join('');
        bodyRows.push(`<tr>
            <td class="pick-num">#${i}</td>
            <td class="actual">${escapeHtml(actual) || '<span class="empty">TBD</span>'}</td>
            ${cells}
        </tr>`);
    }

    const details = leaderboard.length ? `
        <details class="nfl-draft-details">
            <summary>
                <span>Pick-by-pick results</span>
                <small>Compare all ${state.pick_count} picks</small>
            </summary>
            <div class="nfl-draft-results-scroll">
                <table class="nfl-draft-results">
                    <thead>${header}</thead>
                    <tbody>${bodyRows.join('')}</tbody>
                </table>
            </div>
        </details>` : '';

    const winningScore = leaderboard[0]?.points ?? 0;
    return `
        <header class="nfl-draft-results-header">
            <span class="nfl-draft-eyebrow">${escapeHtml(state.title)}</span>
            <h2>Draft Challenge ${isComplete ? 'Final Results' : 'Live Standings'}</h2>
            <p>${isComplete
                ? 'All first-round picks are graded. The final leaderboard is set.'
                : `${gradedPicks} of ${state.pick_count} picks have been graded.`}</p>
        </header>
        <div class="nfl-draft-summary">
            <div><strong>${abbrevs.length} of ${teams.length || abbrevs.length}</strong><span>Teams entered</span></div>
            <div><strong>${gradedPicks} / ${state.pick_count}</strong><span>Picks graded</span></div>
            <div><strong>${winningScore} / ${maxPoints}</strong><span>Top score</span></div>
        </div>
        ${podium}
        <h3 class="nfl-draft-section-title">${isComplete ? 'Final Leaderboard' : 'Leaderboard'}</h3>
        ${leaderboardTable}
        ${details}`;
}

function normalizeClientName(name) {
    if (!name) return '';
    const lowered = name.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    const cleaned = lowered.replace(/[^\w\s]/g, ' ');
    const suffixes = new Set(['jr', 'sr', 'ii', 'iii', 'iv', 'v']);
    return cleaned.split(/\s+/).filter(t => t && !suffixes.has(t)).join(' ');
}

function teamNameFor(abbrev) {
    const t = draftChallengeTeams().find(team => team.abbrev === abbrev);
    return t ? t.name : null;
}

function draftChallengeTeams() {
    if (sharedData?.teams?.length) return sharedData.teams;
    return data?.teams || [];
}
