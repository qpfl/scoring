const CURRENT_SEASON = 2026;

let data = null;
let sharedData = null;  // Holds constitution, hall of fame, banners, transactions, drafts from current season
let currentWeek = 1;
let currentSeason = CURRENT_SEASON;
let availableSeasons = [CURRENT_SEASON];  // Will be populated on load

const ROSTER_POSITION_ORDER = ['QB', 'RB', 'WR', 'TE', 'K', 'D/ST', 'HC', 'OL'];
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
        <div class="tx-player" data-name="${player.name}" data-position="${player.position}">
            <span class="position-tag">${player.position}</span>
            <span class="player-name">${player.name}</span>
            <span class="player-team">${player.nfl_team}</span>
        </div>
    `;
}

async function loadData(season = null) {
    if (season !== null) {
        currentSeason = season;
        document.body.classList.add('app-loading');
    }
    
    try {
        // Always load main data.json first for shared resources
        if (!sharedData) {
            const mainResponse = await fetch('data.json');
            if (mainResponse.ok) {
                sharedData = await mainResponse.json();
                availableSeasons = await detectAvailableSeasons();
            }
        }
        
        // Use data.json for current season, data_YEAR.json for historical
        if (currentSeason === CURRENT_SEASON) {
            data = sharedData;
        } else {
            const dataFile = `data_${currentSeason}.json`;
            const response = await fetch(dataFile);
            
            if (!response.ok) {
                throw new Error(`Season ${currentSeason} not available`);
            }
            
        data = await response.json();
            
            // Merge in shared data from main file
            data.constitution = sharedData.constitution;
            data.hall_of_fame = sharedData.hall_of_fame;
            data.banners = sharedData.banners;
            data.transactions = sharedData.transactions;
            data.drafts = sharedData.drafts;
        }
        
        // Cap currentWeek at 17 for display (offseason shows week 17)
        // During pre-season (week 0), use week 1 for display purposes
        currentWeek = data.current_week === 0 ? 1 : Math.min(data.current_week, 17);
        
        // Normalize nested data structures (from new export format with updated_at wrappers)
        if (data.standings && typeof data.standings === 'object' && !Array.isArray(data.standings)) {
            data.standings = data.standings.standings || [];
        }
        if (data.banners && typeof data.banners === 'object' && !Array.isArray(data.banners)) {
            data.banners = data.banners.banners || [];
        }
        if (data.constitution && typeof data.constitution === 'object' && data.constitution.articles) {
            data.constitution = data.constitution.articles || [];
        }
        // draft_picks is now a flat array - no normalization needed
        // Format: [{ year, round, draft_type, original_team, current_owner, previous_owners }, ...]
        
        // Transactions are now in flat format with season field - no merging needed
        // data.transactions already contains all historical and recent transactions
        
        // Sort standings properly: rank_points (desc), wins (desc), points_for (desc)
        if (Array.isArray(data.standings)) {
            data.standings.sort((a, b) => 
                (b.rank_points || 0) - (a.rank_points || 0) ||
                (b.wins || 0) - (a.wins || 0) ||
                (b.points_for || 0) - (a.points_for || 0)
            );
        }
        
        render();
        renderSeasonSelector();
    } catch (error) {
        console.error('Error loading data:', error);
        document.getElementById('updated-time').textContent = `Error loading ${currentSeason} season`;
        
        // If historical season failed to load, fall back to current
        if (currentSeason !== CURRENT_SEASON) {
            loadData(CURRENT_SEASON);
        }
    }
}

async function detectAvailableSeasons() {
    // Cache the result per browser session so repeat reloads skip the probes
    const cacheKey = `qpfl-seasons-${CURRENT_SEASON}`;
    try {
        const cached = sessionStorage.getItem(cacheKey);
        if (cached) {
            const parsed = JSON.parse(cached);
            if (Array.isArray(parsed) && parsed.length) return parsed;
        }
    } catch (e) {}

    const candidateYears = [];
    for (let year = CURRENT_SEASON - 1; year >= 2020; year--) candidateYears.push(year);

    const probes = candidateYears.map(year =>
        fetch(`data_${year}.json`, { method: 'HEAD' })
            .then(r => r.ok ? year : null)
            .catch(() => null)
    );

    const results = await Promise.all(probes);
    const seasons = [CURRENT_SEASON, ...results.filter(y => y !== null)];

    try { sessionStorage.setItem(cacheKey, JSON.stringify(seasons)); } catch (e) {}
    return seasons;
}

function renderSeasonSelector() {
    const dropdown = document.getElementById('season-dropdown');
    const badge = document.getElementById('season-badge');
    const selector = document.getElementById('season-selector');
    
    badge.textContent = `${currentSeason} Season`;
    
    // Build dropdown options
    dropdown.innerHTML = availableSeasons.map(season => `
        <button class="season-option ${season === currentSeason ? 'active' : ''}" 
                data-season="${season}">${season}</button>
    `).join('');
    
    // Add click handlers
    dropdown.querySelectorAll('.season-option').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const season = parseInt(btn.dataset.season);
            if (season !== currentSeason) {
                loadData(season);
            }
            selector.classList.remove('open');
        });
    });
    
    // Toggle dropdown on badge click
    badge.onclick = (e) => {
        e.stopPropagation();
        selector.classList.toggle('open');
    };
    
    // Close dropdown when clicking outside
    document.addEventListener('click', () => {
        selector.classList.remove('open');
    });
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
        
        msg = `${proposerName} sends ${givesAll.join(', ') || 'nothing'} → ${partnerName} sends ${receivesAll.join(', ') || 'nothing'}`;
    } else if (txType === 'fa_activation') {
        msg = addedStr ? `Added ${addedStr} from FA Pool` : '';
        if (releasedStr) msg += `, released ${releasedStr}`;
    } else if (txType === 'taxi_activation') {
        msg = addedStr ? `Activated ${addedStr}` : '';
        if (releasedStr) msg += `, released ${releasedStr}`;
    } else {
        // Generic format for other types
        msg = txType.replace(/_/g, ' ');
        if (addedStr) msg += `: Added ${addedStr}`;
        if (releasedStr) msg += `, released ${releasedStr}`;
    }
    
    return msg;
}

// Map of view name to its render function. Views not listed here
// (manage, nfl-draft) are initialized in navigateToView via init*().
// Each entry renders all content reachable from that top-level nav item;
// per-subview lazy-rendering happens inside the per-view renderer.
const VIEW_RENDERERS = {
    home: () => renderHome(),
    matchups: () => { renderWeekSelector(); renderMatchups(); renderSchedule(); },
    standings: () => renderStandings(),
    teams: () => { renderAllRosters(); renderTeams(); /* compare initialised on subview activation */ },
    stats: () => { renderStatsLeaders(); renderTeamStats(); },
    history: () => {
        renderHallOfFame();
        renderBanners();
        renderConstitution();
        renderTransactions();
        renderDrafts();
    },
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
    'hof/banners': 'history/banners',
    'hof/constitution': 'history/constitution',
    'transactions': 'history/transactions',
    'drafts': 'history/drafts',
};

// Default subview for each view that has subviews. Used when the URL is
// just `#view` without a subview portion.
const DEFAULT_SUBVIEW = {
    matchups: 'week',
    teams: 'all-rosters',
    stats: 'leaders',
    history: 'records',
};

const viewFresh = new Set();

function ensureViewRendered(view) {
    if (!data) return;
    const renderer = VIEW_RENDERERS[view];
    if (!renderer) return;
    if (viewFresh.has(view)) return;
    renderer();
    viewFresh.add(view);
}

function getActiveView() {
    const active = document.querySelector('.view-container.active');
    if (!active) return 'home';
    return active.id.replace(/-view$/, '');
}

function render() {
    document.body.classList.remove('app-loading');
    document.getElementById('season-badge').textContent = `${data.season} Season`;
    document.getElementById('updated-time').textContent = `Last updated: ${formatDate(data.updated_at)}`;

    const isHistorical = data.is_historical || data.season !== CURRENT_SEASON;

    // Manage Rosters has no meaning for historical seasons.
    const manageBtn = document.querySelector('.nav-btn[data-view="manage"]');
    if (manageBtn) manageBtn.style.display = isHistorical ? 'none' : '';

    // Subview tabs that don't apply to historical seasons.
    const matchupsScheduleBtn = document.querySelector(
        '#matchups-view .subnav-btn[data-subview="schedule"]'
    );
    if (matchupsScheduleBtn) matchupsScheduleBtn.style.display = isHistorical ? 'none' : '';

    const teamsAllRostersBtn = document.querySelector(
        '.team-subnav-btn[data-subview="all-rosters"]'
    );
    if (teamsAllRostersBtn) teamsAllRostersBtn.style.display = isHistorical ? 'none' : '';

    // If currently on Manage when switching to a historical season, redirect to Matchups.
    if (isHistorical) {
        const activeView = document.querySelector('.nav-btn.active');
        if (activeView && activeView.dataset.view === 'manage') {
            document.querySelector('.nav-btn[data-view="matchups"]').click();
        }
    }

    // Data changed: every view is now stale.
    viewFresh.clear();

    if (!render._hashApplied) {
        render._hashApplied = true;
        applyHash();
    } else {
        // Subsequent calls (season switch): render whatever is currently active.
        ensureViewRendered(getActiveView());

        // Re-init compare if the Teams → Compare subview is currently visible
        // so its selectors refresh against the new season's data.
        const compareSubviewActive = document.getElementById('team-compare-subview')?.classList.contains('active');
        if (compareSubviewActive) initCompareView();
    }
}

function renderWeekSelector() {
    const container = document.getElementById('week-selector');
    
    // Collect all weeks from both weeks data and schedule (for playoffs)
    const allWeeks = new Set(data.weeks.map(w => w.week));
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
                        data-week="${weekNum}">${weekNum}</button>
            `;
        }).join('')}
    `;

    container.querySelectorAll('.week-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            currentWeek = parseInt(btn.dataset.week);
            renderWeekSelector();
            renderMatchups();
        });
    });
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
            const t1Score = typeof t1 === 'object' ? (t1.total_score ?? '-') : '-';
            const t2Score = typeof t2 === 'object' ? (t2.total_score ?? '-') : '-';
            
            const t1Winner = t1Score > t2Score ? 'winner' : (t1Score < t2Score ? 'loser' : '');
            const t2Winner = t2Score > t1Score ? 'winner' : (t2Score < t1Score ? 'loser' : '');
            
            return `
                <div class="home-matchup">
                    <div class="home-matchup-team ${t1Winner}">
                        <span>${t1Name}</span>
                        <span class="home-matchup-score">${t1Score}</span>
                    </div>
                    <span class="home-matchup-vs">vs</span>
                    <div class="home-matchup-team ${t2Winner}" style="justify-content: flex-end; text-align: right;">
                        <span class="home-matchup-score">${t2Score}</span>
                        <span>${t2Name}</span>
                    </div>
                </div>
            `;
        }).join('');
    } else {
        matchupsContainer.innerHTML = '<p style="color: var(--text-muted);">No matchups available</p>';
    }
    
    // Render standings
    const standingsContainer = document.getElementById('home-standings');
    standingsContainer.innerHTML = data.standings.map((team, i) => `
        <div class="home-standing-row">
            <span class="home-standing-rank">${i + 1}.</span>
            <span class="home-standing-team">${team.team_name || team.abbrev}</span>
            <span class="home-standing-rp">${team.rank_points?.toFixed(1) || 0} RP</span>
            <span class="home-standing-record">${team.wins || 0}-${team.losses || 0}</span>
        </div>
    `).join('');
    
    // Render recent transactions (capped at 5)
    renderHomeTransactions();
}

function extractDateFromMessage(message) {
    // Extract date from beginning of message if present
    // Format: "MM/DD/YYYY | rest of message"
    if (!message) return { date: null, cleanMessage: message };

    const dateMatch = message.match(/^(\d{1,2}\/\d{1,2}\/\d{4})\s*\|\s*(.*)$/);
    if (dateMatch) {
        return {
            date: dateMatch[1],
            cleanMessage: dateMatch[2].trim()
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

    // Helper to detect if a part is likely a team name vs an item
    const looksLikeTeamName = (part) => {
        // Skip empty or very long parts
        if (!part || part.length > 30) return false;

        // Skip dates
        if (part.match(/^\d{1,2}\/\d{1,2}\/\d{4}$/)) return false;

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
        const itemIndicators = /\b(RB|WR|TE|QB|K|DST|202[0-9]|round|1st|2nd|3rd|4th|\(|\))/i;
        if (itemIndicators.test(part)) return false;

        // Team names are typically short (1-3 words)
        const wordCount = part.split(/\s+/).length;
        return wordCount <= 3;
    };

    for (let part of parts) {
        // Skip empty parts
        if (!part) continue;

        // Check for "Corresponding moves" (with or without colon)
        if (part.toLowerCase().replace(':', '').trim() === 'corresponding moves') {
            inCorrespondingMoves = true;
            currentTeam = null;
            continue;
        }

        // Skip dates
        if (part.match(/^\d{1,2}\/\d{1,2}\/\d{4}$/)) {
            continue;
        }

        // Check for "To Team:" format
        if (part.startsWith('To ')) {
            const teamName = part.replace('To ', '').replace(':', '').trim();
            currentTeam = { name: teamName, items: [] };
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
        if (!currentTeam || looksLikeTeamName(part)) {
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

    // For 2-team trades, swap items (Team1 gives items after their name, but receives Team2's items)
    if (result.teams.length === 2) {
        const team1Items = result.teams[0].items;
        const team2Items = result.teams[1].items;
        result.teams[0].items = team2Items;
        result.teams[1].items = team1Items;
    }

    return result;
}

function renderHomeTransactions() {
    const container = document.getElementById('home-transactions');
    const transactions = data.transactions || [];

    if (transactions.length === 0) {
        container.innerHTML = '<p style="color: var(--text-muted);">No recent transactions</p>';
        return;
    }

    // Transactions are in flat format, newest first - take first 5
    const recent = transactions.slice(0, 5);

    container.innerHTML = recent.map(tx => {
        const isNewTrade = tx.type === 'trade' && tx.proposer && tx.partner;
        const isOldTrade = tx.type === 'trade' && tx.message && tx.message.includes('|');
        let teamName, type, details;

        // Extract date from message or timestamp
        const { dateStr, cleanMessage } = getTransactionDate(tx);

        if (isNewTrade) {
            // New trade format with proposer/partner - format with bullet points
            const proposerName = data.teams?.find(t => t.abbrev === tx.proposer)?.name || tx.proposer;
            const partnerName = data.teams?.find(t => t.abbrev === tx.partner)?.name || tx.partner;

            const getPlayerStr = (p) => typeof p === 'object' ? `${p.position || ''} ${p.name || ''}`.trim() : p;
            const gives = tx.proposer_gives || {};
            const receives = tx.proposer_receives || {};
            const givesItems = [...(gives.players || []).map(getPlayerStr), ...(gives.picks || [])];
            const receivesItems = [...(receives.players || []).map(getPlayerStr), ...(receives.picks || [])];

            return `
                <div class="home-transaction">
                    <div class="home-transaction-header">
                        <span class="home-transaction-team">Trade: ${proposerName} ↔ ${partnerName}</span>
                        <span class="home-transaction-date">${dateStr}</span>
                    </div>
                    <div class="home-transaction-text" style="line-height: 1.8;">
                        <div style="margin-top: 0.25rem;"><strong>${proposerName} receives:</strong></div>
                        ${receivesItems.length ? receivesItems.map(item => `<div style="margin-left: 1rem;">• ${item}</div>`).join('') : '<div style="margin-left: 1rem; color: var(--text-muted);">nothing</div>'}
                        <div style="margin-top: 0.5rem;"><strong>${partnerName} receives:</strong></div>
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
                teamName = tx.team || `Trade: ${team1.name} ↔ ${team2.name}`;

                return `
                    <div class="home-transaction">
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
                    <div class="home-transaction">
                        <div class="home-transaction-header">
                            <span class="home-transaction-team">${tx.team || 'Trade'}</span>
                            <span class="home-transaction-date">${dateStr}</span>
                        </div>
                        <div class="home-transaction-text">${cleanMessage}</div>
                    </div>
                `;
            }
        } else {
            teamName = data.teams?.find(t => t.abbrev === tx.team)?.name || tx.team;
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
                <div class="home-transaction">
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
    // For offseason, show PREVIOUS season's championship
    // Use previous_season data if available (2026 showing 2025 champ)
    const prevSeason = data.previous_season;
    const displaySeason = prevSeason ? prevSeason.season : data.season;
    const displayWeeks = prevSeason ? prevSeason.weeks : data.weeks;
    const displayStandings = prevSeason ? prevSeason.standings : data.standings;
    const displayTeams = prevSeason ? prevSeason.teams : data.teams;
    
    // Render champion banner (previous season's banner)
    const bannerContainer = document.getElementById('home-banner');
    const bannersData = data.banners || {};
    const banners = bannersData.banners || bannersData || [];
    const currentBanner = Array.isArray(banners) ? banners.find(b => b.includes(`${displaySeason}`)) : null;
    
    if (currentBanner) {
        bannerContainer.innerHTML = `<img src="images/banners/${currentBanner}" alt="${displaySeason} Champion Banner" loading="lazy" decoding="async">`;
    }
    
    // Render championship matchup from week 17 and determine champion from game result
    const week17 = displayWeeks.find(w => w && w.week === 17);
    const championshipContainer = document.getElementById('home-championship');
    const champScorersContainer = document.getElementById('home-champ-scorers');
    const championName = document.getElementById('home-champion-name');
    
    let champion = null;
    let championAbbrev = null;
    
    if (week17 && week17.matchups && week17.matchups.length > 0) {
        // First matchup is the championship - winner is the champion
        const champ = week17.matchups[0];
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
        champion = winnerTeam;
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
                        <span class="home-scorer-pos">${p.position}</span>
                        <span class="home-scorer-name">${p.name}</span>
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
                    <span class="home-scorer-pos">${p.position}</span>
                    <span class="home-scorer-name">${p.name}</span>
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
            <span class="home-standing-team">${team.team_name || team.abbrev}</span>
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
}

function renderHomeOffseasonTransactions() {
    const container = document.getElementById('home-offseason-transactions');
    const transactions = data.transactions || [];
    
    if (transactions.length === 0) {
        container.innerHTML = '<div class="home-no-transactions">No recent transactions</div>';
        return;
    }
    
    // Transactions are newest-first, take first 5
    const recentTxns = transactions.slice(0, 5);
    
    container.innerHTML = recentTxns.map(tx => {
        const isNewTrade = tx.type === 'trade' && tx.proposer && tx.partner;
        const isOldTrade = tx.type === 'trade' && tx.message && tx.message.includes('|');

        // Extract date from message or timestamp
        const { dateStr, cleanMessage } = getTransactionDate(tx);

        if (isNewTrade) {
            // Build trade details with bullet points
            const getPlayerStr = (p) => typeof p === 'object' ? `${p.position || ''} ${p.name || ''}`.trim() : p;
            const gives = tx.proposer_gives || {};
            const receives = tx.proposer_receives || {};
            const givesItems = [...(gives.players || []).map(getPlayerStr), ...(gives.picks || [])];
            const receivesItems = [...(receives.players || []).map(getPlayerStr), ...(receives.picks || [])];

            return `
                <div class="home-transaction-item">
                    <div class="home-tx-header">
                        <span class="home-tx-team">Trade: ${tx.proposer} ↔ ${tx.partner}</span>
                        <span class="home-tx-type" style="font-family: 'JetBrains Mono', monospace; font-size: 0.75rem;">${dateStr}</span>
                    </div>
                    <div class="home-tx-details" style="line-height: 1.8;">
                        <div style="margin-top: 0.25rem;"><strong>${tx.proposer} receives:</strong></div>
                        ${receivesItems.length ? receivesItems.map(item => `<div style="margin-left: 1rem;">• ${item}</div>`).join('') : '<div style="margin-left: 1rem; color: var(--text-muted);">nothing</div>'}
                        <div style="margin-top: 0.5rem;"><strong>${tx.partner} receives:</strong></div>
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
                            <span class="home-tx-team">${tx.team || 'Trade'}</span>
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
            const teamDisplay = tx.team;
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
            const teamDisplay = tx.team;
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
                                                <div class="team-name">${t1.name || m.team1}</div>
                                                <div class="team-owner">${t1.owner || ''}</div>
                                            </div>
                                            <div class="vs-container">
                                                <span class="vs-text">vs</span>
                                            </div>
                                            <div class="team right">
                                                <div class="team-name">${t2.name || m.team2}</div>
                                                <div class="team-owner">${t2.owner || ''}</div>
                                                ${seed2}
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
                                <div class="team-name">${m.team1}</div>
                            </div>
                            <div class="vs-container">
                                <span class="vs-text">vs</span>
                            </div>
                            <div class="team right">
                                <div class="team-name">${m.team2}</div>
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
            container.innerHTML = '<div class="no-scores-message"><p>Matchups not available for Week ' + currentWeek + '</p></div>';
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
                                <td>${t.owner}</td>
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
        let midBowlSubtitle = '';
        
        if (isMidBowl) {
            if (currentWeek === 17 && week16MidBowlScores[t1.abbrev] !== undefined) {
                const t1Week16 = week16MidBowlScores[t1.abbrev] || 0;
                const t2Week16 = week16MidBowlScores[t2.abbrev] || 0;
                const t1Week17 = t1.total_score;
                const t2Week17 = t2.total_score;
                t1Score = t1Week16 + t1Week17;
                t2Score = t2Week16 + t2Week17;
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

        return `
            <div class="matchup-card ${bracketClass}">
                <div class="matchup-header">
                    <div class="team">
                        <div class="team-name">${t1.name}</div>
                        <div class="team-owner">${t1.owner}</div>
                    </div>
                    <div class="vs-container">
                        <div class="score-display">
                            <span class="score ${t1Winning ? 'winning' : 'losing'}">${t1Score.toFixed(0)}</span>
                            <span class="score-divider">—</span>
                            <span class="score ${t2Winning ? 'winning' : 'losing'}">${t2Score.toFixed(0)}</span>
                        </div>
                        ${midBowlSubtitle}
                    </div>
                    <div class="team right">
                        <div class="team-name">${t2.name}</div>
                        <div class="team-owner">${t2.owner}</div>
                    </div>
                </div>
                <button class="expand-btn" data-matchup="${idx}">Show Rosters ▼</button>
                <div class="roster-panel" id="roster-${idx}">
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
    // Get game time for this player's team
    const weekKey = String(weekNum);
    const gameTimes = data.game_times && data.game_times[weekKey];
    
    if (!gameTimes) return { status: 'unknown', label: '' };
    
    // Normalize team codes (some sources use different abbreviations)
    const teamAliases = {
        'LAR': 'LA',   // Rams
        'JAC': 'JAX', // Jaguars
        'WSH': 'WAS', // Commanders
    };
    
    let playerTeam = player.nfl_team;
    // Try the original team code first, then the alias
    let gameTime = gameTimes[playerTeam];
    if (!gameTime && teamAliases[playerTeam]) {
        gameTime = gameTimes[teamAliases[playerTeam]];
    }
    // Also try reverse lookup (if game_times uses LAR but player has LA)
    if (!gameTime) {
        const reverseAliases = { 'LA': 'LAR', 'JAX': 'JAC', 'WAS': 'WSH' };
        if (reverseAliases[playerTeam]) {
            gameTime = gameTimes[reverseAliases[playerTeam]];
        }
    }
    
    // No game time = BYE week
    if (!gameTime) {
        return { status: 'bye', label: 'BYE' };
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
                <span class="position-tag">${p.position}</span>
                <span class="player-name">${p.name}</span>
                <span class="player-team">${p.nfl_team}</span>
            </div>
        </div>
    `).join('');
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
        
        if (status.status === 'bye') {
            scoreDisplay = `<span class="player-status bye">BYE</span>`;
        } else if (status.status === 'not-played') {
            const colorClass = status.colorClass || '';
            scoreDisplay = `<span class="player-status not-played ${colorClass}">${status.label}</span>`;
        } else {
            const score = p.score ?? 0;
            scoreDisplay = `<span class="player-score">${score.toFixed(0)}</span>`;
        }
        
        return `
        <div class="player-row ${p.starter ? '' : 'bench'}">
            <div class="player-info">
                <span class="position-tag">${p.position}</span>
                <span class="player-name">${p.name}</span>
                <span class="player-team">${p.nfl_team}</span>
            </div>
                ${scoreDisplay}
        </div>
        `;
    }).join('');
}

function renderStandings() {
    const tbody = document.getElementById('standings-body');
    const totalTeams = data.standings.length;
    
    tbody.innerHTML = data.standings.map((team, idx) => {
        const rank = idx + 1;
        const isPlayoffs = rank <= 4;
        const isToiletBowl = rank > totalTeams - 4;
        const rankClass = isPlayoffs ? 'playoffs' : (isToiletBowl ? 'toilet-bowl' : '');
        const label = isPlayoffs ? '<span class="playoff-label playoffs">Playoffs</span>' : 
                      (isToiletBowl ? '<span class="playoff-label toilet">Toilet Bowl</span>' : '');
        
        return `
            <tr>
                <td class="rank ${rankClass}">${rank}</td>
                <td>
                    <div class="team-name">${team.name}<span class="team-code">${team.abbrev}</span>${label}</div>
                    <div class="team-owner">${team.owner}</div>
                </td>
                <td class="num rank-points">${(team.rank_points ?? 0).toFixed(1)}</td>
                <td class="num record">${team.wins ?? 0}-${team.losses ?? 0}${team.ties ? `-${team.ties}` : ''}</td>
                <td class="num top-half">${team.top_half || 0}</td>
                <td class="num points-for">${(team.points_for ?? 0).toFixed(1)}</td>
                <td class="num points-against">${(team.points_against ?? 0).toFixed(1)}</td>
            </tr>
        `;
    }).join('');
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
            container.innerHTML = '<div class="no-scores-message"><p>Schedule not available</p></div>';
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
                                            <td>${t.owner}</td>
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

function renderTeams() {
    // Get teams from standings, or fall back to data.teams during offseason
    let teams = data.standings;
    if (!teams || teams.length === 0) {
        // During offseason, use data.teams instead
        teams = data.teams || [];
    }
    if (!teams || teams.length === 0) return;
    
    // Default to first team if none selected
    if (!currentTeam) currentTeam = teams[0].abbrev;
    
    // Render team selector buttons
    const selectorContainer = document.getElementById('team-selector');
    selectorContainer.innerHTML = teams.map(team => `
        <button class="team-btn ${team.abbrev === currentTeam ? 'active' : ''}" 
                data-team="${team.abbrev}">${team.abbrev}</button>
    `).join('');
    
    // Add click handlers
    selectorContainer.querySelectorAll('.team-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            currentTeam = btn.dataset.team;
            // Reset to Roster tab when switching teams
            document.querySelectorAll('.team-subnav-btn').forEach(b => b.classList.remove('active'));
            document.querySelector('.team-subnav-btn[data-subview="roster"]')?.classList.add('active');
            document.querySelectorAll('.team-subview').forEach(v => v.classList.remove('active'));
            document.getElementById('team-roster-subview')?.classList.add('active');
            renderTeams();
        });
    });
    
    // Find team info
    const teamInfo = teams.find(t => t.abbrev === currentTeam);
    if (!teamInfo) return;
    
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
    if (currentSeason === CURRENT_SEASON && data.rosters && data.rosters[currentTeam]) {
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
                    <td class="player-name">${nameDisplay}</td>
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
                    <td class="player-name">${nameDisplay}</td>
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
                <div style="overflow-x: auto;">
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
        <div class="team-header">
            <h2>${teamInfo.name}</h2>
            <div class="owner">${teamInfo.owner}</div>
        </div>
        <div style="overflow-x: auto;">
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

async function renderTeamHof() {
    if (!currentTeam || !data) return;
    
    const container = document.getElementById('team-hof-container');
    const teamInfo = data.standings?.find(t => t.abbrev === currentTeam);
    if (!teamInfo) {
        container.innerHTML = '<p class="no-banners">No team data available</p>';
        return;
    }
    
    // Show loading state
    container.innerHTML = '<p style="text-align: center; color: var(--text-muted);">Loading team history...</p>';
    
    // Owner name patterns for matching finishes (map team abbrev to possible owner name patterns)
    const ownerPatterns = {
        'GSA': ['Griffin', 'Griff'],
        'CGK': ['Kaminska', 'Connor Kaminska', 'Redacted Kaminska', 'CGK/SRY'],
        'CWR': ['Reardon', 'Connor Reardon', 'Censored Reardon', 'CWR/SLS'],
        'S/T': ['Spencer/Tim', 'Tim/Spencer', 'Spencer', 'Tim'],
        'SLS': ['Stephen', 'Schmidt', 'CWR/SLS'],
        'SRY': ['Spencer', 'CGK/SRY'],
        'AYP': ['Arnav'],
        'RPA': ['Ryan Ansel', 'Ryan A'],
        'RCP': ['Ryan P'],
        'WJK': ['Bill', 'Kusner'],
        'MPA': ['Miles'],
        'J/J': ['Joe/Joe', 'Joe Ward', 'Joe Kuhl'],
        'JRW': ['Joe Ward'],
        'JDK': ['Joe Kuhl'],
        'AST': ['Anagh']
    };
    
    const matchesTeam = (text, abbrev) => {
        const patterns = ownerPatterns[abbrev] || [];
        return patterns.some(p => text.toLowerCase().includes(p.toLowerCase()));
    };
    
    // Team Ring of Honor data (each * signifies a ring won with the franchise)
    const teamRingOfHonor = {
        'GSA': {
            owners: [
                { years: '2020 - Present', name: 'Griffin Ansel', rings: 3 }
            ],
            players: [
                { position: 'RB', name: 'Dalvin Cook', team: 'MIN', rings: 2 },
                { position: 'WR', name: 'Cooper Kupp', team: 'LAR', rings: 2 },
                { position: 'RB', name: 'Nick Chubb', team: 'CLE', rings: 3 },
                { position: 'WR', name: 'Tyreek Hill', team: 'MIA', rings: 3 },
                { position: 'RB', name: 'Alvin Kamara', team: 'NO', rings: 3 }
            ],
            teamNames: [
                { years: '2020', name: 'Beats by Joe and Tyreek', note: 'founding name' },
                { years: '2020', name: 'The Mixon Administration' },
                { years: '2021', name: 'Alvin, Dalvin, and the Chipmunks', rings: 1 },
                { years: '2022', name: 'Mahomes\' Beermeister', rings: 1 },
                { years: '2023', name: 'TuAnon' },
                { years: '2024', name: 'All Roads Lead to Rome', rings: 1 }
            ]
        },
        'CGK': {
            owners: [
                { years: '2020 - Present', name: 'Connor Kaminska', rings: 1 },
                { years: '2021', name: 'Connor Kaminska & Spencer Yoder', rings: 0 }
            ]
        },
        'CWR': {
            owners: [
                { years: '2020 - Present', name: 'Connor Reardon', rings: 1 },
                { years: '2021', name: 'Connor Reardon & Stephen Schmidt', rings: 0 }
            ]
        },
        'S/T': {
            owners: [
                { years: '2020 - Present', name: 'Spencer Yoder & Tim Grazier', rings: 1 }
            ]
        },
        'SLS': {
            owners: [
                { years: '2020 - Present', name: 'Stephen Schmidt', rings: 0 }
            ]
        },
        'AYP': {
            owners: [
                { years: '2020 - Present', name: 'Arnav Patel', rings: 0 }
            ]
        },
        'RPA': {
            owners: [
                { years: '2020', name: 'Miles Agus', rings: 0 },
                { years: '2021 - Present', name: 'Ryan Ansel', rings: 0 }
            ]
        },
        'RCP': {
            owners: [
                { years: '2020 - Present', name: 'Ryan Przybocki', rings: 0 }
            ]
        },
        'WJK': {
            owners: [
                { years: '2020 - Present', name: 'Bill Kuhl', rings: 0 }
            ]
        },
        'MPA': {
            owners: [
                { years: '2020 - Present', name: 'Miles Agus', rings: 0 }
            ]
        },
        'J/J': {
            owners: [
                { years: '2020 - 2022', name: 'Ryan Przybocki', rings: 0 },
                { years: '2022 - 2023', name: 'Joe Kuhl', rings: 0 },
                { years: '2024 - Present', name: 'Joe Kuhl & Joe Ward', rings: 0 }
            ]
        },
        'AST': {
            owners: [
                { years: '2020 - 2024', name: 'Joe Ward', rings: 0 },
                { years: '2024 - Present', name: 'Anagh Tiwary', rings: 0 }
            ]
        }
    };
    
    // Load data from all available seasons
    const allSeasonData = [];
    const allTimePlayerGames = []; // For all-time top starter performances
    const highestScoringWeeks = []; // For highest team scores
    
    for (const season of availableSeasons) {
        try {
            let seasonData;
            if (season === currentSeason) {
                seasonData = data;
            } else {
                const response = await fetch(`data_${season}.json?t=${Date.now()}`, { cache: 'no-store' });
                if (response.ok) {
                    seasonData = await response.json();
                } else {
                    continue;
                }
            }
            
            // Helper to check if an abbreviation matches this team (handles combined teams)
            // CWR should also match CWR/SLS, CGK should match CGK/SRY
            const matchesCurrentTeam = (abbrev) => {
                if (abbrev === currentTeam) return true;
                // Check if abbrev is a combined code that includes currentTeam
                if (abbrev && abbrev.includes('/')) {
                    const parts = abbrev.split('/');
                    return parts.includes(currentTeam);
                }
                return false;
            };
            
            // Check if this team exists in this season (including combined teams)
            const teamExists = seasonData.standings?.some(t => matchesCurrentTeam(t.abbrev));
            if (!teamExists) continue;
            
            const weeksWithScores = seasonData.weeks?.filter(w => w.has_scores) || [];
            if (weeksWithScores.length === 0) continue;
            
            let highestScore = { score: 0, week: 0, opponent: '' };
            let lowestScore = { score: Infinity, week: 0, opponent: '' };
            let biggestWin = { margin: 0, week: 0, opponent: '', score: '' };
            let biggestLoss = { margin: 0, week: 0, opponent: '', score: '' };
            let totalPoints = 0;
            let wins = 0, losses = 0, ties = 0;
            let gamesPlayed = 0;
            
            weeksWithScores.forEach(week => {
                for (const matchup of week.matchups) {
                    let teamData = null, opponentData = null;
                    
                    if (matchesCurrentTeam(matchup.team1.abbrev)) {
                        teamData = matchup.team1;
                        opponentData = matchup.team2;
                    } else if (matchesCurrentTeam(matchup.team2.abbrev)) {
                        teamData = matchup.team2;
                        opponentData = matchup.team1;
                    }
                    
                    if (!teamData) continue;
                    
                    const teamScore = teamData.total_score || 0;
                    const oppScore = opponentData.total_score || 0;
                    if (teamScore === 0 && oppScore === 0) continue;
                    
                    const margin = teamScore - oppScore;
                    totalPoints += teamScore;
                    gamesPlayed++;
                    
                    // Track for highest scoring weeks
                    highestScoringWeeks.push({
                        score: teamScore,
                        week: week.week,
                        season: season,
                        opponent: opponentData.abbrev,
                        result: teamScore > oppScore ? 'W' : (teamScore < oppScore ? 'L' : 'T')
                    });
                    
                    if (teamScore > oppScore) wins++;
                    else if (teamScore < oppScore) losses++;
                    else ties++;
                    
                    if (teamScore > highestScore.score) {
                        highestScore = { score: teamScore, week: week.week, opponent: opponentData.abbrev };
                    }
                    if (teamScore < lowestScore.score && teamScore > 0) {
                        lowestScore = { score: teamScore, week: week.week, opponent: opponentData.abbrev };
                    }
                    if (margin > biggestWin.margin) {
                        biggestWin = { margin, week: week.week, opponent: opponentData.abbrev, score: `${teamScore.toFixed(0)}-${oppScore.toFixed(0)}` };
                    }
                    if (margin < 0 && Math.abs(margin) > biggestLoss.margin) {
                        biggestLoss = { margin: Math.abs(margin), week: week.week, opponent: opponentData.abbrev, score: `${teamScore.toFixed(0)}-${oppScore.toFixed(0)}` };
                    }
                    
                    // Collect STARTER player performances only for all-time rankings
                    if (teamData.roster) {
                        teamData.roster.forEach(player => {
                            if (player.score && player.score > 0 && player.starter) {
                                allTimePlayerGames.push({
                                    name: player.name,
                                    position: player.position,
                                    nfl_team: player.nfl_team,
                                    score: player.score,
                                    week: week.week,
                                    season: season
                                });
                            }
                        });
                    }
                }
            });
            
            // Find season finish - check playoffs, toilet bowl, and standings position
            const seasonFinishes = []; // Can have multiple badges (e.g., "10th" + "Toilet Bowl")
            const finishes = data.hall_of_fame?.finishes_by_year || [];
            const yearFinish = finishes.find(y => y.year === String(season) || y.year.includes(String(season)));
            
            if (yearFinish && yearFinish.results) {
                // Check playoff positions
                if (yearFinish.results[0] && matchesTeam(yearFinish.results[0], currentTeam)) {
                    seasonFinishes.push({ type: 'champion', label: 'Champion' });
                } else if (yearFinish.results[1] && matchesTeam(yearFinish.results[1], currentTeam)) {
                    seasonFinishes.push({ type: 'playoff', label: '2nd Place' });
                } else if (yearFinish.results[2] && matchesTeam(yearFinish.results[2], currentTeam)) {
                    seasonFinishes.push({ type: 'playoff', label: '3rd Place' });
                }
                
                // Check toilet bowl/jambo
                yearFinish.results.forEach(r => {
                    if (r.includes('Toilet Bowl') && matchesTeam(r, currentTeam)) {
                        seasonFinishes.push({ type: 'toilet-bowl', label: 'Toilet Bowl' });
                    } else if (r.includes('Jambo') && matchesTeam(r, currentTeam)) {
                        seasonFinishes.push({ type: 'jambo', label: 'Jamboree' });
                    }
                });
            }
            
            // Get standings position for this season (use matchesCurrentTeam for combined teams)
            const teamStanding = seasonData.standings?.find(t => matchesCurrentTeam(t.abbrev));
            if (teamStanding) {
                const rank = teamStanding.rank || seasonData.standings.indexOf(teamStanding) + 1;
                // Only show position badge if not already showing a playoff finish
                if (!seasonFinishes.some(f => f.type === 'champion' || f.type === 'playoff')) {
                    // 4th-10th places get a position badge
                    if (rank >= 4 && rank <= 10) {
                        const suffix = rank === 4 ? 'th' : rank === 5 ? 'th' : rank === 6 ? 'th' : 
                                      rank === 7 ? 'th' : rank === 8 ? 'th' : rank === 9 ? 'th' : 'th';
                        seasonFinishes.unshift({ type: 'position', label: `${rank}${suffix} Place` });
                    }
                }
            }
            
            if (gamesPlayed > 0) {
                allSeasonData.push({
                    season,
                    wins, losses, ties,
                    totalPoints,
                    gamesPlayed,
                    ppg: totalPoints / gamesPlayed,
                    highestScore,
                    lowestScore: lowestScore.score === Infinity ? null : lowestScore,
                    biggestWin: biggestWin.margin > 0 ? biggestWin : null,
                    biggestLoss: biggestLoss.margin > 0 ? biggestLoss : null,
                    seasonFinishes
                });
            }
        } catch (e) {
            // Season unavailable — skip silently
        }
    }

    // Sort seasons (most recent first)
    allSeasonData.sort((a, b) => b.season - a.season);
    
    // Calculate all-time franchise stats
    const allTimeTotalPoints = allSeasonData.reduce((sum, s) => sum + s.totalPoints, 0);
    const allTimeGamesPlayed = allSeasonData.reduce((sum, s) => sum + s.gamesPlayed, 0);
    const allTimeWins = allSeasonData.reduce((sum, s) => sum + s.wins, 0);
    const allTimeLosses = allSeasonData.reduce((sum, s) => sum + s.losses, 0);
    const allTimeTies = allSeasonData.reduce((sum, s) => sum + s.ties, 0);
    
    // Find largest margin of victory across all seasons
    let allTimeBiggestWin = { margin: 0, week: 0, season: 0, opponent: '', score: '' };
    allSeasonData.forEach(s => {
        if (s.biggestWin && s.biggestWin.margin > allTimeBiggestWin.margin) {
            allTimeBiggestWin = { ...s.biggestWin, season: s.season };
        }
    });
    
    // Normalize player names to combine variants (e.g., "Patrick Mahomes" and "Patrick Mahomes II")
    const normalizePlayerName = (name) => {
        if (!name) return name;
        // Remove common suffixes
        let normalized = name
            .replace(/\s+(II|III|IV|V|Jr\.?|Sr\.?)$/i, '')
            .trim();
        return normalized;
    };
    
    // Aggregate total starter points per player across all seasons
    const playerTotalPoints = {};
    allTimePlayerGames.forEach(game => {
        const normalizedName = normalizePlayerName(game.name);
        const key = `${normalizedName}|${game.position}`;
        if (!playerTotalPoints[key]) {
            playerTotalPoints[key] = {
                name: game.name, // Keep original name for display (most recent)
                position: game.position,
                nfl_team: game.nfl_team,
                totalPoints: 0,
                gamesStarted: 0
            };
        }
        playerTotalPoints[key].totalPoints += game.score;
        playerTotalPoints[key].gamesStarted += 1;
        // Keep the most recent name and NFL team
        playerTotalPoints[key].name = game.name;
        playerTotalPoints[key].nfl_team = game.nfl_team;
    });
    
    // Get top 10 players by total starter points
    const topPlayersByTotalPoints = Object.values(playerTotalPoints)
        .sort((a, b) => b.totalPoints - a.totalPoints)
        .slice(0, 10);
    
    // Get top 10 all-time STARTER performances
    const topAllTimeGames = allTimePlayerGames
        .sort((a, b) => b.score - a.score)
        .slice(0, 10);
    
    // Get top 10 all-time STARTER performances (Non-QB)
    const topAllTimeGamesNonQB = allTimePlayerGames
        .filter(p => p.position !== 'QB')
        .sort((a, b) => b.score - a.score)
        .slice(0, 10);
    
    // Get top 10 highest scoring weeks
    const topScoringWeeks = highestScoringWeeks
        .sort((a, b) => b.score - a.score)
        .slice(0, 10);
    
    // Find team banners (championship wins) - match by owner name patterns
    const teamBanners = [];
    const finishes = data.hall_of_fame?.finishes_by_year || [];
    finishes.forEach(year => {
        if (year.year.includes('MVP') || year.year === 'TBD') return;
        // First result is the champion
        if (year.results && year.results[0] && matchesTeam(year.results[0], currentTeam)) {
            const yearNum = year.year.replace(/\D/g, '');
            const bannerFile = data.banners?.find(b => b.includes(yearNum));
            if (bannerFile) {
                teamBanners.push({ year: year.year, file: bannerFile });
            }
        }
    });
    
    // Check rivalry records for this team's head-to-head (including combined teams)
    // Need to combine records where currentTeam appears as CWR and CWR/SLS, etc.
    // Also combine opponents that are combined teams (e.g., CGK and CGK/SRY should be same opponent)
    const allRivalries = data.hall_of_fame?.rivalry_records?.records || [];
    
    // Helper to check if a rivalry team matches currentTeam (handles combined teams)
    const matchesRivalryTeam = (abbrev) => {
        if (abbrev === currentTeam) return true;
        if (abbrev && abbrev.includes('/')) {
            return abbrev.split('/').includes(currentTeam);
        }
        return false;
    };
    
    // Known combined teams and their primary owners
    const combinedTeamPrimary = {
        'CWR/SLS': 'CWR',
        'CGK/SRY': 'CGK',
        'S/T': 'S/T',  // S/T is its own primary
        'J/J': 'J/J'   // J/J is its own primary
    };
    
    // Normalize opponent to primary team code
    const normalizeOpponent = (abbrev) => {
        // If it's a known combined team, return the primary
        if (combinedTeamPrimary[abbrev]) {
            return combinedTeamPrimary[abbrev];
        }
        // If it contains a slash but isn't in our map, use first part as primary
        if (abbrev && abbrev.includes('/')) {
            return abbrev.split('/')[0];
        }
        return abbrev;
    };
    
    // Aggregate records by normalized opponent
    const rivalryMap = {};
    
    allRivalries.forEach(r => {
        let opponent = null;
        let wins = 0, losses = 0, ties = 0;
        
        if (matchesRivalryTeam(r.team1)) {
            opponent = r.team2;
            wins = r.team1_wins;
            losses = r.team2_wins;
            ties = r.ties || 0;
        } else if (matchesRivalryTeam(r.team2)) {
            opponent = r.team1;
            wins = r.team2_wins;
            losses = r.team1_wins;
            ties = r.ties || 0;
        }
        
        if (opponent) {
            // Skip if opponent is also a form of the current team (self-matchup from combined team)
            if (matchesRivalryTeam(opponent)) return;
            
            // Normalize opponent to combine CGK and CGK/SRY, etc.
            const opponentKey = normalizeOpponent(opponent);
            
            if (!rivalryMap[opponentKey]) {
                rivalryMap[opponentKey] = { opponent: opponentKey, wins: 0, losses: 0, ties: 0 };
            }
            rivalryMap[opponentKey].wins += wins;
            rivalryMap[opponentKey].losses += losses;
            rivalryMap[opponentKey].ties += ties;
        }
    });
    
    const rivalryRecords = Object.values(rivalryMap);
    
    // Build HTML
    let html = `<h2 style="text-align: center; margin-bottom: 1.5rem;">${teamInfo.name} Hall of Fame</h2>`;
    
    // Championship Banners
    html += `
        <div class="team-hof-section">
            <div class="team-hof-section-title">Championship Banners</div>
            ${teamBanners.length > 0 ? `
                <div class="team-banners-grid">
                    ${teamBanners.map(b => `
                        <div class="team-banner-item">
                            <img src="images/banners/${b.file}" alt="${b.year} Championship" loading="lazy" decoding="async">
                            <div style="text-align: center; margin-top: 0.5rem; color: var(--text-secondary);">${b.year}</div>
                        </div>
                    `).join('')}
                </div>
            ` : `<p class="no-banners">No championships yet...</p>`}
        </div>
    `;
    
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
                                <span class="ring-name">${p.position} ${p.name} (${p.team})</span>
                                <span class="ring-stars">${renderRings(p.rings)}</span>
                            </div>
                        `).join('')}
                    </div>
                ` : ''}
                
                ${ringOfHonor.teamNames && ringOfHonor.teamNames.length > 0 ? `
                    <div class="ring-of-honor-category">
                        <div class="ring-of-honor-category-title">Team Names</div>
                        ${ringOfHonor.teamNames.map(t => `
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
    
    // All-Time Franchise Records
    if (allSeasonData.length > 0) {
        html += `
            <div class="team-hof-section">
                <div class="team-hof-section-title">All-Time Franchise Records</div>
                <div class="team-hof-record">
                    <span class="team-hof-record-label">All-Time Record</span>
                    <span class="team-hof-record-value">${allTimeWins}-${allTimeLosses}${allTimeTies > 0 ? `-${allTimeTies}` : ''}</span>
                </div>
                <div class="team-hof-record">
                    <span class="team-hof-record-label">Total Points Scored</span>
                    <span class="team-hof-record-value">${allTimeTotalPoints.toFixed(0)} pts (${allTimeGamesPlayed} games)</span>
                </div>
                <div class="team-hof-record">
                    <span class="team-hof-record-label">Points Per Game (All-Time)</span>
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
    
    // Top Players by Total Starter Points (All-Time)
    if (topPlayersByTotalPoints.length > 0) {
        html += `
            <div class="team-hof-section">
                <div class="team-hof-section-title">Most Total Points as Starter (All-Time)</div>
                ${topPlayersByTotalPoints.map((p, i) => `
                    <div class="team-hof-record">
                        <span class="team-hof-record-label">${i + 1}. ${p.position} ${p.name} (${p.nfl_team || 'N/A'})</span>
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
                        <span class="team-hof-record-value">${s.totalPoints.toFixed(1)}</span>
                    </div>
                    <div class="team-hof-record">
                        <span class="team-hof-record-label">Points Per Game</span>
                        <span class="team-hof-record-value">${s.ppg.toFixed(1)}</span>
                    </div>
                    <div class="team-hof-record">
                        <span class="team-hof-record-label">Highest Score</span>
                        <span class="team-hof-record-value">${s.highestScore.score.toFixed(1)} (Week ${s.highestScore.week} vs ${s.highestScore.opponent})</span>
                    </div>
                    ${s.lowestScore ? `
                        <div class="team-hof-record">
                            <span class="team-hof-record-label">Lowest Score</span>
                            <span class="team-hof-record-value">${s.lowestScore.score.toFixed(1)} (Week ${s.lowestScore.week} vs ${s.lowestScore.opponent})</span>
                        </div>
                    ` : ''}
                    ${s.biggestWin ? `
                        <div class="team-hof-record">
                            <span class="team-hof-record-label">Biggest Win</span>
                            <span class="team-hof-record-value">+${s.biggestWin.margin.toFixed(1)} (Week ${s.biggestWin.week} vs ${s.biggestWin.opponent}, ${s.biggestWin.score})</span>
                        </div>
                    ` : ''}
                    ${s.biggestLoss ? `
                        <div class="team-hof-record">
                            <span class="team-hof-record-label">Biggest Loss</span>
                            <span class="team-hof-record-value">-${s.biggestLoss.margin.toFixed(1)} (Week ${s.biggestLoss.week} vs ${s.biggestLoss.opponent}, ${s.biggestLoss.score})</span>
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
                <div class="team-hof-section-title">Highest Scoring Weeks (All-Time)</div>
                ${topScoringWeeks.map((w, i) => `
                    <div class="team-hof-record">
                        <span class="team-hof-record-label">${i + 1}. ${w.season} Week ${w.week} vs ${w.opponent}</span>
                        <span class="team-hof-record-value">${w.score.toFixed(0)} pts (${w.result})</span>
                    </div>
                `).join('')}
            </div>
        `;
    }
    
    // All-Time Top STARTER Performances
    if (topAllTimeGames.length > 0) {
        html += `
            <div class="team-hof-section">
                <div class="team-hof-section-title">Top Starter Performances (All-Time)</div>
                ${topAllTimeGames.map((p, i) => `
                    <div class="team-hof-record">
                        <span class="team-hof-record-label">${i + 1}. ${p.position} ${p.name} (${p.nfl_team || 'N/A'})</span>
                        <span class="team-hof-record-value">${p.score.toFixed(0)} pts (${p.season} Week ${p.week})</span>
                    </div>
                `).join('')}
            </div>
        `;
    }
    
    // All-Time Top STARTER Performances (Non-QB)
    if (topAllTimeGamesNonQB.length > 0) {
        html += `
            <div class="team-hof-section">
                <div class="team-hof-section-title">Top Starter Performances - Non-QB (All-Time)</div>
                ${topAllTimeGamesNonQB.map((p, i) => `
                    <div class="team-hof-record">
                        <span class="team-hof-record-label">${i + 1}. ${p.position} ${p.name} (${p.nfl_team || 'N/A'})</span>
                        <span class="team-hof-record-value">${p.score.toFixed(0)} pts (${p.season} Week ${p.week})</span>
                    </div>
                `).join('')}
            </div>
        `;
    }
    
    // Head-to-Head Records
    if (rivalryRecords.length > 0) {
        html += `
            <div class="team-hof-section">
                <div class="team-hof-section-title">All-Time Head-to-Head</div>
                ${rivalryRecords.sort((a, b) => (b.wins + b.losses + b.ties) - (a.wins + a.losses + a.ties)).map(r => {
                    const total = r.wins + r.losses + r.ties;
                    const recordClass = r.wins > r.losses ? 'color: var(--accent);' : (r.losses > r.wins ? 'color: #e74c3c;' : '');
                    return `
                        <div class="team-hof-record">
                            <span class="team-hof-record-label">vs ${r.opponent}</span>
                            <span class="team-hof-record-value" style="${recordClass}">${r.wins}-${r.losses}${r.ties > 0 ? `-${r.ties}` : ''} (${total} games)</span>
                        </div>
                    `;
                }).join('')}
            </div>
        `;
    }
    
    container.innerHTML = html;
}

function renderTeamTradeBlock() {
    if (!currentTeam || !data) return;
    
    const container = document.getElementById('team-tradeblock-container');
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
                            <span class="trade-block-player-pos">${p.position}</span>
                            <span class="trade-block-player-name">${p.name}</span>
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
                <div class="trade-block-notes">${notes}</div>
            </div>
        `;
    }
    
    container.innerHTML = html;
}

function renderAllRosters() {
    const container = document.getElementById('all-rosters-container');
    if (!container) return;
    const rosters = data?.rosters;
    if (!rosters || typeof rosters !== 'object') {
        container.innerHTML = '<p style="padding: 2rem; text-align: center; color: var(--text-muted);">No roster data available</p>';
        return;
    }

    // Order teams by standings rank when available, otherwise alphabetical
    const standingsOrder = (data.standings || []).map(t => t.abbrev);
    const allAbbrevs = Object.keys(rosters);
    const teamAbbrevs = [
        ...standingsOrder.filter(a => allAbbrevs.includes(a)),
        ...allAbbrevs.filter(a => !standingsOrder.includes(a)).sort()
    ];

    if (teamAbbrevs.length === 0) {
        container.innerHTML = '<p style="padding: 2rem; text-align: center; color: var(--text-muted);">No teams to display</p>';
        return;
    }

    const teamInfoFor = (abbrev) =>
        data.teams?.find(t => t.abbrev === abbrev) ||
        data.standings?.find(t => t.abbrev === abbrev) ||
        { abbrev, name: abbrev, owner: '' };

    const positions = ROSTER_POSITION_ORDER;

    // Group each team's roster by position, preserving sortRosterByPosition's grouping
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

    const headerCells = teamAbbrevs.map(abbrev => {
        const info = teamInfoFor(abbrev);
        const owner = info.owner ? `<div class="team-header-owner">${info.owner}</div>` : '';
        return `<th><div class="team-header-name">${info.name || abbrev}</div>${owner}</th>`;
    }).join('');

    const bodyRows = positions.map(pos => {
        if (posMax[pos] === 0) return '';
        let rows = `<tr class="position-group"><td colspan="${teamAbbrevs.length}">${pos}</td></tr>`;
        for (let i = 0; i < posMax[pos]; i++) {
            rows += '<tr>';
            teamAbbrevs.forEach(abbrev => {
                const player = teamPlayersByPos[abbrev][pos][i];
                if (player) {
                    rows += `<td><span class="ar-player-name" title="${player.name}">${player.name}</span><span class="ar-player-team">${player.nfl_team || ''}</span></td>`;
                } else {
                    rows += '<td class="empty-slot"></td>';
                }
            });
            rows += '</tr>';
        }
        return rows;
    }).join('');

    container.innerHTML = `
        <table class="all-rosters-table">
            <thead><tr>${headerCells}</tr></thead>
            <tbody>${bodyRows}</tbody>
        </table>
    `;
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
    
    let html = '';
    
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
        
        html += `
            <div class="hof-section">
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
            <div class="hof-section">
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
            <div class="hof-section">
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
            <div class="hof-section">
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
        // Official "Rivalry Week" matchups only
        const rivalryWeekMatchups = [
            ['GSA', 'RPA'],
            ['AST', 'AYP'],
            ['CGK', 'CWR'],
            ['J/J', 'WJK'],
            ['S/T', 'SLS']
        ];
        
        const isRivalryWeek = (t1, t2) => {
            return rivalryWeekMatchups.some(([a, b]) => 
                (t1 === a && t2 === b) || (t1 === b && t2 === a)
            );
        };
        
        // Filter to only show official rivalry week matchups
        const rivalries = hof.rivalry_records.records.filter(r => isRivalryWeek(r.team1, r.team2));
        
        if (rivalries.length > 0) {
            html += `
                <div class="hof-section">
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

let currentTransactionSeason = null;  // Will be set to current year on first render

function renderTransactions() {
    if (!data.transactions || data.transactions.length === 0) {
        document.getElementById('transactions-container').innerHTML = '<p style="text-align:center; color: var(--text-secondary);">No transactions available</p>';
        return;
    }
    
    const selectorContainer = document.getElementById('transactions-season-selector');
    const container = document.getElementById('transactions-container');
    
    // Flat format: [{type, team, week, season, message, timestamp, ...}]
    // Group by season first
    const bySeason = {};
    data.transactions.forEach(tx => {
        const season = tx.season || data.season || 2025;
        if (!bySeason[season]) bySeason[season] = [];
        bySeason[season].push(tx);
    });
    
    // Get sorted seasons (descending)
    const seasons = Object.keys(bySeason).sort((a, b) => parseInt(b) - parseInt(a));
    
    // Default to current season
    if (currentTransactionSeason === null) {
        currentTransactionSeason = parseInt(seasons[0]) || data.season || 2025;
    }
    
    // Render season selector
    selectorContainer.innerHTML = seasons.map(season => `
        <button class="season-btn ${parseInt(season) === currentTransactionSeason ? 'active' : ''}" 
                data-season="${season}">${season}</button>
    `).join('');
    
    selectorContainer.querySelectorAll('.season-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            currentTransactionSeason = parseInt(btn.dataset.season);
            renderTransactions();
        });
    });
    
    // Get transactions for selected season
    const seasonTxns = bySeason[currentTransactionSeason] || [];
    
    // Group by week
    const byWeek = {};
    seasonTxns.forEach(tx => {
        const week = tx.week || 0;
        if (!byWeek[week]) byWeek[week] = [];
        byWeek[week].push(tx);
    });
    
    // Sort weeks descending
    const sortedWeeks = Object.keys(byWeek).sort((a, b) => parseInt(b) - parseInt(a));
    
    container.innerHTML = `
        <div class="transactions-season">
            ${sortedWeeks.map(week => `
                <div class="transactions-week">
                    <div class="transactions-week-header">${isNaN(parseInt(week)) ? week : `Week ${week}`}</div>
                    ${byWeek[week].map(tx => {
                        // Extract date from message or timestamp
                        const { dateStr, cleanMessage } = getTransactionDate(tx);

                        // For trades, check for new format (proposer/partner) or old format (team with "Trade")
                        const isNewTrade = tx.type === 'trade' && tx.proposer && tx.partner;
                        const isOldTrade = tx.team && tx.team.toLowerCase().includes('trade');

                        if (isNewTrade) {
                            const proposerName = data.teams?.find(t => t.abbrev === tx.proposer)?.name || tx.proposer;
                            const partnerName = data.teams?.find(t => t.abbrev === tx.partner)?.name || tx.partner;

                            const getPlayerStr = (p) => typeof p === 'object' ? `${p.position || ''} ${p.name || ''}`.trim() : p;
                            const gives = tx.proposer_gives || {};
                            const receives = tx.proposer_receives || {};
                            const givesItems = [...(gives.players || []).map(getPlayerStr), ...(gives.picks || [])];
                            const receivesItems = [...(receives.players || []).map(getPlayerStr), ...(receives.picks || [])];

                            return `
                                <div class="transaction-item">
                                    <div class="transaction-title">
                                        Trade: ${proposerName} ↔ ${partnerName}
                                        ${dateStr ? `<span style="float: right; font-size: 0.85rem; color: var(--text-muted); font-family: 'JetBrains Mono', monospace;">${dateStr}</span>` : ''}
                                    </div>
                                    <div class="transaction-details" style="line-height: 1.8;">
                                        <div style="margin-top: 0.5rem;"><strong>${proposerName} receives:</strong></div>
                                        ${receivesItems.length ? receivesItems.map(item => `<div style="margin-left: 1.5rem;">• ${item}</div>`).join('') : '<div style="margin-left: 1.5rem; color: var(--text-muted);">nothing</div>'}
                                        <div style="margin-top: 0.75rem;"><strong>${partnerName} receives:</strong></div>
                                        ${givesItems.length ? givesItems.map(item => `<div style="margin-left: 1.5rem;">• ${item}</div>`).join('') : '<div style="margin-left: 1.5rem; color: var(--text-muted);">nothing</div>'}
                                    </div>
                                </div>
                            `;
                        } else if (isOldTrade) {
                            // Parse old pipe-separated trade format (using cleaned message)
                            const parsed = parseOldTradeMessage(cleanMessage);
                            if (parsed && parsed.teams.length >= 2) {
                                const team1 = parsed.teams[0];
                                const team2 = parsed.teams[1];

                                let detailsHtml = '';
                                for (const team of parsed.teams) {
                                    detailsHtml += `<div style="margin-top: 0.5rem;"><strong>${team.name} receives:</strong></div>`;
                                    if (team.items.length) {
                                        detailsHtml += team.items.map(item => `<div style="margin-left: 1.5rem;">• ${item}</div>`).join('');
                                    } else {
                                        detailsHtml += '<div style="margin-left: 1.5rem; color: var(--text-muted);">nothing</div>';
                                    }
                                }
                                if (parsed.correspondingMoves.length) {
                                    detailsHtml += `<div style="margin-top: 0.75rem;"><strong>Corresponding moves:</strong></div>`;
                                    detailsHtml += parsed.correspondingMoves.map(move => `<div style="margin-left: 1.5rem;">• ${move}</div>`).join('');
                                }

                                return `
                                    <div class="transaction-item">
                                        <div class="transaction-title">
                                            Trade: ${team1.name} ↔ ${team2.name}
                                            ${dateStr ? `<span style="float: right; font-size: 0.85rem; color: var(--text-muted); font-family: 'JetBrains Mono', monospace;">${dateStr}</span>` : ''}
                                        </div>
                                        <div class="transaction-details" style="line-height: 1.8;">
                                            ${detailsHtml}
                                        </div>
                                    </div>
                                `;
                            } else {
                                // Fallback if parsing fails
                                return `
                                    <div class="transaction-item">
                                        <div class="transaction-title">
                                            ${tx.team}
                                            ${dateStr ? `<span style="float: right; font-size: 0.85rem; color: var(--text-muted); font-family: 'JetBrains Mono', monospace;">${dateStr}</span>` : ''}
                                        </div>
                                        <div class="transaction-details">
                                            <div class="transaction-subheader">${cleanMessage || formatTransactionMessage(tx)}</div>
                                        </div>
                                    </div>
                                `;
                            }
                        } else {
                            let teamName = data.teams?.find(t => t.abbrev === tx.team)?.name || tx.team;

                            return `
                                <div class="transaction-item">
                                    <div class="transaction-title">
                                        ${teamName}
                                        ${dateStr ? `<span style="float: right; font-size: 0.85rem; color: var(--text-muted); font-family: 'JetBrains Mono', monospace;">${dateStr}</span>` : ''}
                                    </div>
                                    <div class="transaction-details">
                                        <div class="transaction-subheader">${cleanMessage || formatTransactionMessage(tx)}</div>
                                    </div>
                                </div>
                            `;
                        }
                    }).join('')}
                </div>
            `).join('')}
        </div>
    `;
}

// Drafts
let currentDraft = 0;

function renderDrafts() {
    // Combine upcoming drafts with historical drafts
    const upcomingDrafts = data.upcoming_drafts || [];
    const historicalDrafts = data.drafts || [];
    const allDrafts = [...upcomingDrafts, ...historicalDrafts];

    if (allDrafts.length === 0) {
        document.getElementById('drafts-container').innerHTML = '<p style="text-align:center; color: var(--text-secondary);">No drafts available</p>';
        return;
    }

    // Render draft tabs
    const tabsContainer = document.getElementById('drafts-tabs');
    tabsContainer.innerHTML = allDrafts.map((draft, idx) => `
        <button class="season-btn ${idx === currentDraft ? 'active' : ''}"
                data-draft="${idx}">${draft.name}</button>
    `).join('');

    // Add click handlers
    tabsContainer.querySelectorAll('.season-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            currentDraft = parseInt(btn.dataset.draft);
            renderDrafts();
        });
    });

    // Render selected draft
    const draft = allDrafts[currentDraft];
    const container = document.getElementById('drafts-container');
    const isUpcoming = currentDraft < upcomingDrafts.length;
    
    if (!draft.rounds || draft.rounds.length === 0) {
        container.innerHTML = '<p style="text-align:center; color: var(--text-secondary);">No picks recorded for this draft</p>';
        return;
    }

    container.innerHTML = `
        <div class="drafts-season">
            ${draft.rounds.map(round => `
                <div class="draft-round">
                    <div class="draft-round-header">Round ${String(round.round).includes('Taxi') ? round.round : (Number.isInteger(parseFloat(round.round)) ? parseInt(round.round) : round.round)}</div>
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
                                // For historical drafts, show player selected
                                const isPass = pick.player === 'PASS' || !pick.player;
                                return `
                                    <div class="draft-pick">
                                        <div class="pick-number">${pick.pick}</div>
                                        <div class="pick-details">
                                            <div class="pick-team">${pick.team}</div>
                                            ${isPass
                                                ? '<div class="pick-player pick-pass">PASS</div>'
                                                : `<div class="pick-player">${pick.player}</div>`
                                            }
                                            ${pick.dropped && pick.dropped !== '-'
                                                ? `<div class="pick-dropped">Dropped: <span>${pick.dropped}</span></div>`
                                                : ''
                                            }
                                        </div>
                                    </div>
                                `;
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
    
    // Add change handlers
    select1.onchange = () => {
        compareTeam1 = select1.value;
        renderCompareView();
    };
    select2.onchange = () => {
        compareTeam2 = select2.value;
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
    
    container.innerHTML = `
        <div class="compare-columns">
            <div class="compare-column" id="compare-col-1"></div>
            <div class="compare-column" id="compare-col-2"></div>
        </div>
    `;
    
    renderTeamColumn('compare-col-1', compareTeam1, team1Info);
    renderTeamColumn('compare-col-2', compareTeam2, team2Info);
}

function renderTeamColumn(containerId, teamAbbrev, teamInfo) {
    const container = document.getElementById(containerId);
    const teamName = teamInfo.name || teamAbbrev;
    const teamTotal = getTeamTotalPoints(teamAbbrev);
    
    // Get roster - for current season use data.rosters, for historical build from matchups
    let activePlayers = [];
    let taxiPlayers = [];
    
    const isHistorical = data.is_historical || data.season !== CURRENT_SEASON;
    
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
    
    // Build HTML
    let html = `
        <div class="compare-column-header">
            <span class="compare-team-name">${teamName}</span>
            <span class="compare-team-total">${teamTotal.toFixed(1)} pts</span>
        </div>
    `;
    
    // Render each position group
    positions.forEach(pos => {
        const players = byPosition[pos];
        if (players.length === 0) return;
        
        const posTotal = players.reduce((sum, p) => sum + p.totalPoints, 0);
        
        html += `
            <div class="compare-section">
                <div class="compare-section-title">${pos}</div>
                ${players.map(player => `
                    <div class="compare-player">
                        <div class="compare-player-info">
                            <span class="compare-player-position">${player.position}</span>
                            <span class="compare-player-name">${player.name}</span>
                            <span class="compare-player-nfl">${player.nfl_team || ''}</span>
                        </div>
                        <span class="compare-player-points">${player.totalPoints.toFixed(1)}</span>
                    </div>
                `).join('')}
                <div class="compare-position-total">
                    <span class="compare-position-total-label">${pos} Total</span>
                    <span class="compare-position-total-value">${posTotal.toFixed(1)}</span>
                </div>
            </div>
        `;
    });
    
    // Render taxi squad if present
    if (taxiPlayers.length > 0) {
        html += `
            <div class="compare-section">
                <div class="compare-section-title">Taxi Squad</div>
                ${taxiPlayers.map(player => `
                    <div class="compare-player taxi">
                        <div class="compare-player-info">
                            <span class="compare-player-position">${player.position}</span>
                            <span class="compare-player-name">${player.name}</span>
                            <span class="compare-player-nfl">${player.nfl_team || ''}</span>
                        </div>
                        <span class="compare-player-points">-</span>
                    </div>
                `).join('')}
            </div>
        `;
    }
    
    // Render draft picks
    if (teamPicks.length > 0) {
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
        
        // Sort years
        const years = Object.keys(picksByYear).sort();
        
        html += `
            <div class="compare-section">
                <div class="compare-section-title">Draft Picks</div>
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
            </div>
        `;
    }
    
    container.innerHTML = html;
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
    
    // Render position selector
    const selector = document.getElementById('stats-position-selector');
    selector.innerHTML = `
        <button class="stats-pos-btn ${currentStatsPosition === 'ALL' ? 'active' : ''}" data-pos="ALL">All</button>
        ${positions.map(pos => `
            <button class="stats-pos-btn ${currentStatsPosition === pos ? 'active' : ''}" data-pos="${pos}">${pos}</button>
        `).join('')}
    `;
    
    selector.querySelectorAll('.stats-pos-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            currentStatsPosition = btn.dataset.pos;
            renderStatsLeaders();
        });
    });
    
    // Render leaders grid
    const container = document.getElementById('stats-leaders-container');
    const positionsToShow = currentStatsPosition === 'ALL' ? positions : [currentStatsPosition];
    
    container.innerHTML = positionsToShow.map(pos => {
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
                                <div class="stats-player-name">${player.name}</div>
                                <div class="stats-player-meta">
                                    <span class="stats-nfl-team">${player.nfl_team}</span>
                                    <span class="stats-fantasy-team">• ${player.fantasy_team}</span>
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
    }).join('');
    
    // Add click handlers for "view all" buttons
    container.querySelectorAll('.stats-view-all').forEach(btn => {
        btn.addEventListener('click', () => {
            currentStatsPosition = btn.dataset.pos;
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
    
    // Sort teams by total points for
    const teams = Object.values(teamStats).sort((a, b) => 
        (b.total_points_for || 0) - (a.total_points_for || 0)
    );
    
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
                            <th class="num">OPR</th>
                            <th class="num">Adj OPR</th>
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
                    <div class="stat-card-title">OPR (Owner Performance Rating)</div>
                    ${teams.slice().sort((a, b) => (b.opr || 0) - (a.opr || 0)).slice(0, 5).map((t, i) => `
                        <div class="stat-card-row">
                            <span class="rank">${i + 1}.</span>
                            <span class="team">${t.abbrev}</span>
                            <span class="value">${(t.opr || 0).toFixed(1)}</span>
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
                <strong>OPR Formula:</strong> (5 × PPG + 2 × (Best Week + Worst Week) + 3 × Win%) / 10
            </div>
            <div class="formula-note">
                <strong>Adjusted OPR:</strong> Team OPR / League Average OPR
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
    selections: {} // position -> [player names]
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
    
    const weekSelect = document.getElementById('lineup-week-select');
    
    // Collect all weeks - regular season from data.weeks plus playoff weeks from schedule
    const allWeeks = new Set();
    if (data && data.weeks) {
        data.weeks.forEach(w => allWeeks.add(w.week));
    }
    // Add playoff weeks from schedule
    if (data && data.schedule) {
        data.schedule.forEach(w => {
            if (w.is_playoffs) allWeeks.add(w.week);
        });
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
            return `<option value="${w}"${w === data.current_week ? ' selected' : ''}>${label}</option>`;
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
    lineupState = { team: null, week: null, roster: [], selections: {} };
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
                                    <span class="player-name">${p.name}</span>
                                    <span class="player-team">${p.nfl_team}</span>
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

function isPlayerLocked(player) {
    // Check if player's game has started based on game_times data
    // JSON keys are strings, so convert week to string
    const weekKey = String(lineupState.week);
    if (!data.game_times || !data.game_times[weekKey]) {
        return false;
    }

    const gameTimes = data.game_times[weekKey];
    const playerTeam = player.nfl_team;
    const gameTime = gameTimes[playerTeam];

    if (!gameTime) {
        return false;
    }

    const kickoff = new Date(gameTime);
    const now = new Date();
    return now >= kickoff;
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

// Navigation — hash-based routing
// URL format: #view  or  #view/subview
function navigateToView(view, subview) {
    if (!document.getElementById(`${view}-view`)) view = 'home';

    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.querySelector(`.nav-btn[data-view="${view}"]`)?.classList.add('active');

    document.querySelectorAll('.view-container').forEach(v => v.classList.remove('active'));
    document.getElementById(`${view}-view`).classList.add('active');

    ensureViewRendered(view);

    if (view === 'manage') initManageRoster();
    if (view === 'nfl-draft') initNflDraftView();

    // Apply default subview if none specified
    const sub = subview || DEFAULT_SUBVIEW[view];

    if (view === 'matchups' && sub) {
        activateGenericSubview('matchups', sub);
    } else if (view === 'stats' && sub) {
        activateGenericSubview('stats', sub);
    } else if (view === 'history' && sub) {
        activateGenericSubview('history', sub);
    } else if (view === 'teams' && sub) {
        activateTeamsSubview(sub);
    }
}

function activateGenericSubview(parent, sub) {
    const view = document.getElementById(`${parent}-view`);
    if (!view) return;
    const btn = view.querySelector(`.subnav-btn[data-subview="${sub}"]`);
    if (!btn) return;
    view.querySelectorAll('.subnav-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    view.querySelectorAll('.subview').forEach(v => v.classList.remove('active'));
    document.getElementById(`${parent}-${sub}-subview`)?.classList.add('active');
}

function activateTeamsSubview(sub) {
    const teamBtn = document.querySelector(`.team-subnav-btn[data-subview="${sub}"]`);
    if (!teamBtn) return;
    document.querySelectorAll('.team-subnav-btn').forEach(b => b.classList.remove('active'));
    teamBtn.classList.add('active');
    document.querySelectorAll('.team-subview').forEach(v => v.classList.remove('active'));
    document.getElementById(`team-${sub}-subview`)?.classList.add('active');

    // Team selector is only relevant for per-team subviews
    const teamSelector = document.getElementById('team-selector');
    const needsSelector = sub === 'roster' || sub === 'tradeblock' || sub === 'hof';
    if (teamSelector) teamSelector.style.display = needsSelector ? '' : 'none';

    // Lazy-init for subviews not handled by ensureViewRendered('teams')
    if (sub === 'compare') initCompareView();
    if (sub === 'hof') renderTeamHof();
    if (sub === 'tradeblock') renderTeamTradeBlock();
}

function applyHash() {
    let hash = location.hash.slice(1) || 'home';

    // Honor legacy hash paths from before the nav restructure
    if (LEGACY_HASH_REDIRECTS[hash]) {
        hash = LEGACY_HASH_REDIRECTS[hash];
        history.replaceState(null, '', `#${hash}`);
    }

    const [view, subview] = hash.split('/');
    navigateToView(view, subview);
}

document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        history.pushState(null, '', `#${btn.dataset.view}`);
        navigateToView(btn.dataset.view);
        // Auto-close mobile nav after selection
        const navEl = document.getElementById('primary-nav');
        const toggleEl = document.getElementById('nav-toggle');
        if (navEl?.classList.contains('open')) {
            navEl.classList.remove('open');
            toggleEl?.setAttribute('aria-expanded', 'false');
        }
    });
});

document.getElementById('nav-toggle')?.addEventListener('click', () => {
    const navEl = document.getElementById('primary-nav');
    const toggleEl = document.getElementById('nav-toggle');
    const isOpen = navEl.classList.toggle('open');
    toggleEl.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
});

// Generic subnav handler (Matchups, Stats, History sub-tabs)
document.querySelectorAll('.subnav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const parent = btn.dataset.parent;
        const sub = btn.dataset.subview;
        if (!parent || !sub) return;
        activateGenericSubview(parent, sub);
        history.pushState(null, '', `#${parent}/${sub}`);
    });
});

// Team sub-navigation (All Rosters, Compare, Roster, Trade Block, Team HoF)
document.querySelectorAll('.team-subnav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        activateTeamsSubview(btn.dataset.subview);
        history.pushState(null, '', `#teams/${btn.dataset.subview}`);
    });
});

window.addEventListener('popstate', applyHash);

// ====== MANAGE ROSTER SECTION ======
const MANAGE_CONFIG = {
    // Use current host for API calls (works on both preview and production)
    apiUrl: window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
        ? 'https://qpfl-scoring.vercel.app/api/transaction'  // Fallback for local dev
        : `${window.location.origin}/api/transaction`
};

let manageState = {
    team: null,
    password: null,
    selectedTaxiPlayer: null,
    selectedReleasePlayer: null,
    selectedFaPlayer: null,
    selectedFaReleasePlayer: null,
    tradeGivePlayers: [],
    tradeGivePicks: [],
    tradeReceivePlayers: [],
    tradeReceivePicks: [],
    tradeConditions: {}, // { itemId: conditionText }
    tradePartner: null
};

function initManageRoster() {
    const teamSelect = document.getElementById('manage-team-select');
    teamSelect.innerHTML = '<option value="">-- Choose Team --</option>';
    
    // Get teams from data.teams (offseason) or latest week (during season)
    let teams = [];
    if (data && data.teams && data.teams.length > 0) {
        // Use data.teams directly (works for offseason and during season)
        teams = data.teams;
    } else if (data && data.weeks && data.weeks.length > 0) {
        // Fallback to latest week's teams
        const latestWeek = data.weeks.reduce((max, week) => 
            (week.week > max.week) ? week : max, data.weeks[0]);
        teams = latestWeek.teams || [];
    }
    
    teams.forEach(team => {
        const option = document.createElement('option');
        option.value = team.abbrev;
        option.textContent = `${team.name} (${team.abbrev})`;
        teamSelect.appendChild(option);
    });
    
    // Reset state
    resetManageState();
    resetLineupForm();
    document.getElementById('manage-auth').style.display = 'block';
    document.getElementById('manage-panel').style.display = 'none';
    document.getElementById('manage-error').textContent = '';
    
    // Set up event listeners
    document.getElementById('manage-login-btn').onclick = handleManageLogin;
    document.getElementById('manage-logout-btn').onclick = handleManageLogout;
    
    // Set up tab switching
    document.querySelectorAll('.tx-tab').forEach(tab => {
        tab.onclick = () => switchTxTab(tab.dataset.tab);
    });
    
    // Reset to first tab (lineup)
    switchTxTab('lineup');
}

function resetManageState() {
    manageState = {
        team: null,
        password: null,
        selectedTaxiPlayer: null,
        selectedReleasePlayer: null,
        selectedFaPlayer: null,
        selectedFaReleasePlayer: null,
        tradeGivePlayers: [],
        tradeGivePicks: [],
        tradeReceivePlayers: [],
        tradeReceivePicks: [],
        tradeConditions: {},
        tradePartner: null
    };
}

async function handleManageLogin() {
    const team = document.getElementById('manage-team-select').value;
    const password = document.getElementById('manage-password').value;
    const errorEl = document.getElementById('manage-error');
    
    if (!team || !password) {
        errorEl.textContent = 'Please select a team and enter password';
        return;
    }
    
    errorEl.textContent = 'Validating...';
    
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
            
            document.getElementById('manage-auth').style.display = 'none';
            document.getElementById('manage-panel').style.display = 'block';
            
            // Use canonical team name from data.teams
            const canonicalTeam = data.teams?.find(t => t.abbrev === team);
            document.getElementById('manage-team-name').textContent = canonicalTeam?.name || team;
            
            // Initialize lineup form and other tabs
            initLineupForm();
            renderTaxiTab();
            renderFaTab();
            renderTradeTab();
            renderPendingTrades();
        } else {
            errorEl.textContent = result.error || 'Invalid password';
        }
    } catch (e) {
        console.error('Login error:', e);
        // Allow localhost testing without API validation
        if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
            manageState.team = team;
            manageState.password = password;
            
            document.getElementById('manage-auth').style.display = 'none';
            document.getElementById('manage-panel').style.display = 'block';
            
            const canonicalTeam = data.teams?.find(t => t.abbrev === team);
            document.getElementById('manage-team-name').textContent = canonicalTeam?.name || team;
            
            initLineupForm();
            renderTaxiTab();
            renderFaTab();
            renderTradeTab();
            renderPendingTrades();
            errorEl.textContent = '';
        } else {
            errorEl.textContent = 'Network error - please try again';
        }
    }
}

function handleManageLogout() {
    resetManageState();
    resetLineupForm();
    document.getElementById('manage-auth').style.display = 'block';
    document.getElementById('manage-panel').style.display = 'none';
    document.getElementById('manage-password').value = '';
    // Reset to first tab (lineup)
    switchTxTab('lineup');
}

function switchTxTab(tabName) {
    document.querySelectorAll('.tx-tab').forEach(t => t.classList.remove('active'));
    document.querySelector(`.tx-tab[data-tab="${tabName}"]`).classList.add('active');
    
    document.querySelectorAll('.tx-content').forEach(c => c.classList.remove('active'));
    document.getElementById(`tx-${tabName}`).classList.add('active');
    
    // Initialize trade block tab when switching to it
    if (tabName === 'tradeblock') {
        renderTradeBlockTab();
    }
}

function getTeamData(abbrev) {
    if (!data) return null;
    
    // Prefer data.rosters (updated by transactions) over weekly roster data
    // data.rosters format: { "GSA": [{name, nfl_team, position}, ...], ... }
    if (data.rosters && data.rosters[abbrev]) {
        const rosterArray = data.rosters[abbrev];
        // Get team name from data.teams or standings
        const teamInfo = data.teams?.find(t => t.abbrev === abbrev) || 
                         data.standings?.find(t => t.abbrev === abbrev) || {};
        return {
            abbrev: abbrev,
            name: teamInfo.name || abbrev,
            owner: teamInfo.owner || '',
            roster: rosterArray,
            taxi_squad: []  // Taxi squad not in rosters format, empty in offseason anyway
        };
    }
    
    // Fallback to weekly roster data
    if (!data.weeks || data.weeks.length === 0) return null;
    
    // Find the highest week number (weeks may not be sorted numerically)
    const latestWeek = data.weeks.reduce((max, week) => 
        (week.week > max.week) ? week : max, data.weeks[0]);
    
    if (!latestWeek || !latestWeek.teams) return null;
    const teamData = latestWeek.teams.find(t => t.abbrev === abbrev);
    
    // During offseason (after week 17), taxi squads are empty
    if (teamData && (data.current_week > 17)) {
        teamData.taxi_squad = [];
    }
    
    return teamData;
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

function selectTaxiPlayer(name, position) {
    // Clear previous selection
    document.querySelectorAll('#taxi-players .tx-player').forEach(el => el.classList.remove('selected'));
    
    // Select new player
    const selected = document.querySelector(`#taxi-players .tx-player[data-name="${name}"]`);
    if (selected) selected.classList.add('selected');
    
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
    document.querySelectorAll('#taxi-release-players .tx-player').forEach(el => el.classList.remove('selected'));
    document.querySelector(`#taxi-release-players .tx-player[data-name="${name}"]`).classList.add('selected');
    
    manageState.selectedReleasePlayer = name;
    
    // Show actions
    document.getElementById('taxi-actions').style.display = 'flex';
    document.getElementById('taxi-summary').textContent = 
        `Activate ${manageState.selectedTaxiPlayer.name} → Release ${name}`;
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
    const statusEl = document.getElementById('taxi-status');
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
            setTimeout(() => loadData(), 2000);
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
    document.querySelectorAll('#fa-players .tx-player').forEach(el => el.classList.remove('selected'));
    document.querySelector(`#fa-players .tx-player[data-name="${name}"]`).classList.add('selected');
    
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
    document.querySelectorAll('#fa-release-players .tx-player').forEach(el => el.classList.remove('selected'));
    document.querySelector(`#fa-release-players .tx-player[data-name="${name}"]`).classList.add('selected');
    
    manageState.selectedFaReleasePlayer = name;
    
    document.getElementById('fa-actions').style.display = 'flex';
    document.getElementById('fa-summary').textContent = 
        `Add ${manageState.selectedFaPlayer.name} → Release ${name}`;
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
            setTimeout(() => loadData(), 2000);
        } else {
            statusEl.className = 'submit-status error';
            statusEl.textContent = result.error;
        }
    } catch (e) {
        statusEl.className = 'submit-status error';
        statusEl.textContent = 'Network error - please try again';
    }
}

function renderTradeTab() {
    // Trade deadline logic:
    // - Before week 12: Trading open
    // - Week 12 Thursday through week 17: Trading blocked (deadline period)
    // - Week 18+ (offseason): Trading open
    const deadlineWarning = document.getElementById('trade-deadline-warning');
    const tradeDeadline = data.trade_deadline_week || 12;
    const isOffseason = data.current_week > 17;  // Week 18+ is offseason
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
    
    partnerSelect.onchange = () => {
        manageState.tradePartner = partnerSelect.value;
        // Clear selected picks when partner changes
        manageState.tradeReceivePicks = [];
        if (partnerSelect.value) {
            renderTradePlayers();
        }
        renderTradePicks();
    };
    
    // Clear trade lists initially
    document.getElementById('trade-give-players').innerHTML = '<p class="no-pending-trades">Select trade partner first</p>';
    document.getElementById('trade-receive-players').innerHTML = '<p class="no-pending-trades">Select trade partner first</p>';
    
    // Render picks for current team (give picks always available)
    renderTradePicks();
    
    document.getElementById('trade-submit-btn').onclick = submitTradeProposal;
}

function renderTradePlayers() {
    const myTeamData = getTeamData(manageState.team);
    const partnerTeamData = getTeamData(manageState.tradePartner);
    
    if (!myTeamData || !partnerTeamData) return;
    
    // My players to give
    const giveList = document.getElementById('trade-give-players');
    giveList.innerHTML = sortRosterByPosition(myTeamData.roster).map(txPlayerRowHtml).join('');

    giveList.querySelectorAll('.tx-player').forEach(el => {
        el.onclick = () => toggleTradePlayer('give', el.dataset.name, el);
    });

    // Partner players to receive
    const receiveList = document.getElementById('trade-receive-players');
    receiveList.innerHTML = sortRosterByPosition(partnerTeamData.roster).map(txPlayerRowHtml).join('');
    
    receiveList.querySelectorAll('.tx-player').forEach(el => {
        el.onclick = () => toggleTradePlayer('receive', el.dataset.name, el);
    });
    
    // Draft picks (simplified - showing years 2026-2028)
    renderTradePicks();
}

function toggleTradePlayer(direction, name, el) {
    const list = direction === 'give' ? manageState.tradeGivePlayers : manageState.tradeReceivePlayers;
    const idx = list.indexOf(name);
    const itemId = `player-${direction}-${name}`;
    
    if (idx >= 0) {
        list.splice(idx, 1);
        el.classList.remove('selected');
        // Remove condition if item was deselected
        delete manageState.tradeConditions[itemId];
    } else {
        list.push(name);
        el.classList.add('selected');
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
            <div class="tx-pick" data-pick="${pick.id}" data-condition="${pick.condition || ''}">
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
                <div class="tx-pick" data-pick="${pick.id}" data-condition="${pick.condition || ''}">
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
            setTimeout(() => loadData(), 2000);
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
            if (condition) {
                return `<li>${item} <span class="pending-trade-condition">⚡ ${condition}</span></li>`;
            }
            return `<li>${item}</li>`;
        };

        // Calculate expiration date (7 days from proposal)
        let expiresStr = '';
        if (trade.status === 'pending' && trade.proposed_at) {
            const proposedDate = new Date(trade.proposed_at);
            const expiresDate = new Date(proposedDate.getTime() + 7 * 24 * 60 * 60 * 1000);
            expiresStr = expiresDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
        }

        return `
            <div class="pending-trade-card" data-trade-id="${trade.id}">
                <div class="pending-trade-header">
                    <span class="pending-trade-teams">
                        ${isProposer ? 'You → ' + otherTeamName : otherTeamName + ' → You'}
                    </span>
                    <div class="pending-trade-header-right">
                        ${expiresStr ? `<span class="pending-trade-expires">Expires ${expiresStr}</span>` : ''}
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
                        <strong>Message:</strong> "${trade.comment}"
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
            setTimeout(() => loadData(), 2000);
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
            setTimeout(() => loadData(), 2000);
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
            <label class="trade-block-player-item ${availablePlayers.includes(player.name) ? 'selected' : ''}">
                <input type="checkbox" value="${player.name}" ${availablePlayers.includes(player.name) ? 'checked' : ''}>
                <span class="trade-block-player-pos">${player.position}</span>
                <span class="trade-block-player-name">${player.name}</span>
            </label>
        `).join('');
        
        // Add listeners
        playersContainer.querySelectorAll('input[type="checkbox"]').forEach(cb => {
            cb.onchange = () => cb.parentElement.classList.toggle('selected', cb.checked);
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
            // Reload data to update the teams view
            setTimeout(() => loadData(), 1500);
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
            loadData();
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
    
    document.getElementById('confirm-modal-overlay').classList.add('active');
    document.body.style.overflow = 'hidden';
}

function hideConfirmModal() {
    document.getElementById('confirm-modal-overlay').classList.remove('active');
    document.body.style.overflow = '';
    pendingConfirmCallback = null;
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

// Escape keypress to close modal
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && document.getElementById('confirm-modal-overlay').classList.contains('active')) {
        hideConfirmModal();
    }
});

// ====== NFL DRAFT CHALLENGE ======
const NFL_DRAFT_CONFIG = {
    apiUrl: window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
        ? 'https://qpfl-scoring.vercel.app/api/nfl-draft'
        : `${window.location.origin}/api/nfl-draft`,
    pickCount: 32,
    prospectSuggestions: [
        // Source: AndyNFL Top-250 Big Board for 2026 NFL Draft
        'Sonny Styles', 'Jeremiyah Love', 'Caleb Downs', 'Arvell Reese', 'Fernando Mendoza',
        'Rueben Bain Jr.', 'Vega Ioane', 'Mansoor Delane', 'Carnell Tate', 'Jermod McCoy',
        'Jordyn Tyson', 'Makai Lemon', 'Francis Mauigoa', 'Dillon Thieneman', 'David Bailey',
        'Monroe Freeling', 'Omar Cooper Jr.', 'Max Iheanachor', 'Chris Johnson', 'KC Concepcion',
        'Kenyon Sadiq', 'Spencer Fano', 'Emmanuel McNeil-Warren', 'Emmanuel Pregnon', 'Denzel Boston',
        'Peter Woods', 'Colton Hood', 'CJ Allen', 'Malachi Lawrence', 'Christen Miller',
        'Zion Young', 'Kayden McDonald', 'Avieon Terrell', 'Caleb Lomu', 'D\u2019Angelo Ponds',
        'Treydan Stukes', 'Kadyn Proctor', 'Chris Brazzell II', 'Blake Miller', 'Keldric Faulk',
        'Chase Bisontis', 'Gracen Halton', 'Gabe Jacas', 'Brandon Cisse', 'Lee Hunter',
        'Jacob Rodriguez', 'TJ Parker', 'Keith Abney II', 'Ted Hurst', 'Caleb Banks',
        'Ty Simpson', 'Germie Bernard', 'Jadarian Price', 'Joshua Josephs', 'Keionte Scott',
        'Akheem Mesidor', 'Josiah Trotter', 'Antonio Williams', 'Chris Bell', 'R Mason Thomas',
        'Keylan Rutledge', 'AJ Haulcy', 'Mike Washington Jr.', 'Sam Hecht', 'Oscar Delp',
        'Anthony Hill Jr.', 'Jalen Farmer', 'Domonique Orange', 'Jake Golday', 'Genesis Smith',
        'Kaleb Elarms-Orr', 'Kyle Louis', 'Devin Moore', 'Julian Neal', 'De\u2019Zhaun Stribling',
        'Kamari Ramsey', 'Malachi Fields', 'Derrick Moore', 'Cashius Howell', 'Dani Dennis-Sutton',
        'Eli Stowers', 'Brenen Thompson', 'Davison Igbinosun', 'Emmett Johnson', 'Eli Raridon',
        'Elijah Sarratt', 'Darrell Jackson Jr.', 'Kevin Coleman Jr.', 'Connor Lew', 'Jaishawn Barham',
        'Bryce Lance', 'Justin Joly', 'Jonah Coleman', 'VJ Payne', 'Chris McClellan',
        'Zakee Wheatley', 'Jalon Kilgore', 'Bud Clark', 'Skyler Bell', 'Garrett Nussmeier',
        'Keyron Crawford', 'Max Klare', 'Jadon Canady', 'Dametrious Crownover', 'Matt Gulbin',
        'Billy Schrauth', 'Gennings Dunker', 'Micah Morris', 'Trey Zuhn III', 'Caleb Tiernan',
        'Malik Muhammad', 'Deion Burks', 'Will Lee III', 'Landon Robinson', 'Keagen Trost',
        'Aiden Fisher', 'Cole Payton', 'Logan Jones', 'Bryce Boettcher', 'Beau Stephens',
        'Sam Roush', 'Kage Casey', 'Tyler Onyedim', 'Romello Height', 'Seth McGowan',
        'Ephesians Prysock', 'Kaytron Allen', 'Zachariah Branch', 'Jake Slaughter', 'Red Murdock',
        'Keyshaun Elliott', 'Markel Bell', 'Michael Trigg', 'Josh Cameron', 'Kendrick Law',
        'Dallen Bentley', 'Anez Cooper', 'Tacario Davis', 'Daylen Everette', 'Brian Parker II',
        'Dae\u2019Quan Wright', 'Jalen Huskey', 'Drew Allar', 'Albert Regis', 'Carver Willis',
        'Tim Keenan III', 'Tanner Koziol', 'Jack Endries', 'Charles Demmings', 'Rayshaun Benny',
        'JD Davis', 'Nick Barrett', 'Diego Pounds', 'Carsen Ryan', 'Malik Benson',
        'Max Llewellyn', 'Tyren Montgomery', 'Anthony Lucas', 'Ja\u2019Kobi Lane', 'Chandler Rivers',
        'Travis Burke', 'Colbie Young', 'Demond Claiborne', 'Jude Bowry', 'CJ Daniels',
        'Brent Austin', 'Nate Boerkircher', 'Kaleb Proctor', 'Parker Brailsford', 'Jimmy Rolder',
        'Aamil Wagner', 'TJ Hall', 'Nadame Tucker', 'Cade Klubnik', 'Nicholas Singleton',
        'Jakobe Thomas', 'Taurean York', 'Hezekiah Masses', 'Bishop Fitzgerald', 'Dontay Corleone',
        'Matthew Hibner', 'Justin Jefferson', 'Jaeden Roberts', 'Kaelon Black', 'Will Kacmarek',
        'Dalton Johnson', 'DeMonte Capehart', 'Lewis Bond', 'Drew Shelton', 'Jordan van den Berg',
        'Josh Cuevas', 'Eric Rivers', 'Deontae Lawson', 'Ar\u2019maj Reed-Adams', 'Mason Reiger',
        'Zane Durant', 'Kendal Daniels', 'J\u2019Mari Taylor', 'Le\u2019Veon Moss', 'Carson Beck',
        'Cole Wisniewski', 'LT Overton', 'Caden Curry', 'Jager Burton', 'Taylen Green',
        'Curtis Allen', 'Skyler Gill-Howard', 'Joe Royer', 'Barion Brown', 'Harold Perkins Jr.',
        'Devon Marshall', 'DJ Campbell', 'Nolan Rucci', 'Austin Barber', 'Marlin Klein',
        'Louis Moore', 'Pat Coogan', 'Eric McAlister', 'Mikail Kamara', 'Chase Roberts',
        'Zxavian Harris', 'Tyre West', 'Jack Kelly', 'Fernando Carmona', 'Quintayvious Hutchins',
        'Trey Moore', 'Avery Smith', 'Eli Heidenreich', 'Tyreak Sapp', 'Josh Thompson',
        'Jack Pyburn', 'Brandon Cleveland', 'Jeremiah Wright', 'Adam Randall', 'Michael Taaffe',
        'Aaron Graves', 'Kaden Wetjen', 'Robert Spears-Jennings', 'Vincent Anthony Jr.', 'Lander Barton',
        'Domani Jackson', 'Robert Henry Jr.', 'Luke Altmyer', 'Rene Konga', 'John Michael-Gyllenborg',
        'Shad Banks Jr.', 'Isaiah World', 'J. Michael Sturdivant', 'Josh Braun', 'DeShon Singleton'
    ]
};

let nflDraftState = {
    authedTeam: null,
    password: null,
    serverState: null
};

async function initNflDraftView() {
    await loadNflDraftState();
    renderNflDraftView();
}

function nflDraftFallbackState(reason) {
    return {
        lock_time: '2026-04-24T00:00:00Z',
        locked: false,
        pick_count: NFL_DRAFT_CONFIG.pickCount,
        submissions: {},
        visible_picks: {},
        actual_picks: [],
        scores: {},
        authed_team: null,
        warning: reason || null
    };
}

async function loadNflDraftState() {
    const body = { action: 'get_state' };
    if (nflDraftState.authedTeam && nflDraftState.password) {
        body.team = nflDraftState.authedTeam;
        body.password = nflDraftState.password;
    }
    try {
        const response = await fetch(NFL_DRAFT_CONFIG.apiUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });
        const result = await response.json();
        if (!response.ok) {
            nflDraftState.serverState = nflDraftFallbackState(result.error || 'Failed to load');
        } else {
            nflDraftState.serverState = result;
        }
    } catch (error) {
        nflDraftState.serverState = nflDraftFallbackState('Couldn\u2019t reach the API (offline or preview build). The UI will render but login/submit won\u2019t work until deployed.');
    }
}

function renderNflDraftView() {
    const container = document.getElementById('nfl-draft-content');
    if (!container) return;
    const state = nflDraftState.serverState;
    if (!state) {
        container.innerHTML = '<div class="submit-status loading">Loading...</div>';
        return;
    }
    const warningBanner = state.warning
        ? `<div class="submit-status error" style="margin-bottom:1rem;">${escapeHtml(state.warning)}</div>`
        : '';

    const rules = warningBanner + `
        <div class="nfl-draft-rules">
            <strong>How it works:</strong> Guess the order of the 32 first-round NFL Draft picks.
            A pick is correct if the named player is selected at that overall number, regardless of team.
            <br><br>
            <strong>Scoring:</strong> Picks 1\u20139 are worth their pick number (pick 1 = 1 pt, pick 9 = 9 pts).
            Picks 10\u201332 are worth 10 pts each. Max possible: ${9 * 10 / 2 + 23 * 10} pts.
            <br><br>
            <strong>Deadline:</strong> Picks lock at the start of the NFL Draft. Other owners can't see your picks until then.
        </div>`;

    if (state.locked) {
        container.innerHTML = rules + renderNflDraftLocked(state);
        return;
    }

    if (nflDraftState.authedTeam) {
        container.innerHTML = rules + renderNflDraftLoggedIn(state);
        wireNflDraftLoggedIn();
    } else {
        container.innerHTML = rules + renderNflDraftLogin(state);
        wireNflDraftLogin();
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
    if (!data || !data.teams) return '';
    const submissions = state.submissions || {};
    const chips = data.teams.map(team => {
        const submitted = submissions[team.abbrev]?.submitted_at;
        const cls = submitted ? 'chip submitted' : 'chip';
        const label = submitted ? `${team.abbrev} \u2713` : team.abbrev;
        return `<span class="${cls}" title="${escapeHtml(team.name)}">${escapeHtml(label)}</span>`;
    }).join('');
    return `<div class="nfl-draft-submissions">${chips}</div>`;
}

function renderNflDraftLogin(state) {
    const teamsList = (data && data.teams) ? data.teams : [];
    const options = teamsList.map(t =>
        `<option value="${escapeHtml(t.abbrev)}">${escapeHtml(t.name)} (${escapeHtml(t.abbrev)})</option>`
    ).join('');
    return `
        <div class="nfl-draft-countdown">${escapeHtml(formatCountdown(state.lock_time))}</div>
        <div class="auth-card">
            <h3>Enter the Draft Challenge</h3>
            <select id="nfl-draft-team-select" class="lineup-select">
                <option value="">-- Choose Team --</option>
                ${options}
            </select>
            <input type="password" id="nfl-draft-password" class="lineup-input" placeholder="Enter team password">
            <button id="nfl-draft-login-btn" class="lineup-btn primary">Login</button>
            <div id="nfl-draft-error" class="lineup-error submit-status"></div>
        </div>
        ${renderNflDraftSubmissionsChips(state)}`;
}

function wireNflDraftLogin() {
    const btn = document.getElementById('nfl-draft-login-btn');
    const passwordInput = document.getElementById('nfl-draft-password');
    btn.onclick = handleNflDraftLogin;
    passwordInput.onkeydown = (e) => { if (e.key === 'Enter') handleNflDraftLogin(); };
}

async function handleNflDraftLogin() {
    const team = document.getElementById('nfl-draft-team-select').value;
    const password = document.getElementById('nfl-draft-password').value;
    const errorEl = document.getElementById('nfl-draft-error');
    errorEl.className = 'submit-status';
    errorEl.textContent = '';
    if (!team || !password) {
        errorEl.className = 'submit-status error';
        errorEl.textContent = 'Select a team and enter your password.';
        return;
    }
    try {
        const response = await fetch(NFL_DRAFT_CONFIG.apiUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'validate', team, password })
        });
        const result = await response.json();
        if (!response.ok || !result.success) {
            errorEl.className = 'submit-status error';
            errorEl.textContent = result.error || 'Login failed';
            return;
        }
        nflDraftState.authedTeam = team;
        nflDraftState.password = password;
        await loadNflDraftState();
        renderNflDraftView();
    } catch (error) {
        errorEl.className = 'submit-status error';
        errorEl.textContent = 'Network error - please try again.';
    }
}

function renderNflDraftLoggedIn(state) {
    const teamName = teamNameFor(nflDraftState.authedTeam) || nflDraftState.authedTeam;
    const myEntry = state.visible_picks?.[nflDraftState.authedTeam];
    const existingPicks = {};
    (myEntry?.picks || []).forEach(p => { existingPicks[p.pick] = p.player || ''; });
    const submittedLine = myEntry?.submitted_at
        ? `Last saved: ${new Date(myEntry.submitted_at).toLocaleString()}`
        : 'No picks submitted yet.';

    let rows = '';
    for (let i = 1; i <= NFL_DRAFT_CONFIG.pickCount; i++) {
        const val = existingPicks[i] || '';
        rows += `
            <div class="pick-num">#${i}</div>
            <input type="text" class="pick-input" data-pick="${i}" list="nfl-draft-prospects"
                value="${escapeHtml(val)}" placeholder="Player for pick ${i}" maxlength="80">`;
    }

    const datalistOptions = NFL_DRAFT_CONFIG.prospectSuggestions
        .map(name => `<option value="${escapeHtml(name)}">`).join('');

    return `
        <div class="nfl-draft-countdown">${escapeHtml(formatCountdown(state.lock_time))}</div>
        <div class="manage-header">
            <h3>Logged in as ${escapeHtml(teamName)}</h3>
            <button id="nfl-draft-logout-btn" class="lineup-btn secondary">\u2190 Logout</button>
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
    document.getElementById('nfl-draft-logout-btn').onclick = () => {
        nflDraftState.authedTeam = null;
        nflDraftState.password = null;
        loadNflDraftState().then(renderNflDraftView);
    };
    document.getElementById('nfl-draft-submit-btn').onclick = handleNflDraftSubmit;
    document.getElementById('nfl-draft-clear-btn').onclick = handleNflDraftClear;
}

async function handleNflDraftClear() {
    const statusEl = document.getElementById('nfl-draft-submit-status');
    const submitBtn = document.getElementById('nfl-draft-submit-btn');
    const clearBtn = document.getElementById('nfl-draft-clear-btn');

    const hasSavedEntry = !!nflDraftState.serverState?.visible_picks?.[nflDraftState.authedTeam];
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
        const response = await fetch(NFL_DRAFT_CONFIG.apiUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: 'clear',
                team: nflDraftState.authedTeam,
                password: nflDraftState.password
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
        const response = await fetch(NFL_DRAFT_CONFIG.apiUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                action: 'submit',
                team: nflDraftState.authedTeam,
                password: nflDraftState.password,
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
    const teams = (data && data.teams) ? data.teams : [];
    const abbrevs = Object.keys(state.visible_picks || {});
    const leaderboardRows = abbrevs
        .map(abbrev => ({
            abbrev,
            name: teamNameFor(abbrev) || abbrev,
            points: scores[abbrev]?.points ?? 0,
            correct: scores[abbrev]?.correct ?? 0
        }))
        .sort((a, b) => b.points - a.points || b.correct - a.correct)
        .map((row, idx) => `
            <tr>
                <td>${idx + 1}</td>
                <td>${escapeHtml(row.name)} <span style="color:var(--text-secondary);">(${escapeHtml(row.abbrev)})</span></td>
                <td>${row.points}</td>
                <td>${row.correct} / ${NFL_DRAFT_CONFIG.pickCount}</td>
            </tr>`).join('');

    const leaderboard = `
        <div class="nfl-draft-leaderboard">
            <table>
                <thead>
                    <tr><th>Rank</th><th>Team</th><th>Points</th><th>Correct</th></tr>
                </thead>
                <tbody>${leaderboardRows || '<tr><td colspan="4" style="text-align:center;">No submissions</td></tr>'}</tbody>
            </table>
        </div>`;

    const orderedAbbrevs = abbrevs.slice().sort((a, b) =>
        (scores[b]?.points ?? 0) - (scores[a]?.points ?? 0)
    );

    const actualByPick = {};
    (state.actual_picks || []).forEach(p => { actualByPick[p.pick] = p.player || ''; });

    const header = `<tr>
        <th>Pick</th>
        <th>Actual</th>
        ${orderedAbbrevs.map(ab => `<th>${escapeHtml(ab)}</th>`).join('')}
    </tr>`;

    const bodyRows = [];
    for (let i = 1; i <= NFL_DRAFT_CONFIG.pickCount; i++) {
        const actual = actualByPick[i] || '';
        const cells = orderedAbbrevs.map(ab => {
            const entry = state.visible_picks[ab];
            const picks = entry?.picks || [];
            const p = picks.find(x => x.pick === i);
            const guess = p ? (p.player || '') : '';
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

    const grid = `
        <div class="nfl-draft-results-scroll">
            <table class="nfl-draft-results">
                <thead>${header}</thead>
                <tbody>${bodyRows.join('')}</tbody>
            </table>
        </div>`;

    return `
        <div class="nfl-draft-countdown">Draft is live \u2014 picks are locked.</div>
        <h3>Leaderboard</h3>
        ${leaderboard}
        <h3>Pick-by-pick Results</h3>
        ${grid}`;
}

function normalizeClientName(name) {
    if (!name) return '';
    const lowered = name.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    const cleaned = lowered.replace(/[^\w\s]/g, ' ');
    const suffixes = new Set(['jr', 'sr', 'ii', 'iii', 'iv', 'v']);
    return cleaned.split(/\s+/).filter(t => t && !suffixes.has(t)).join(' ');
}

function teamNameFor(abbrev) {
    if (!data || !data.teams) return null;
    const t = data.teams.find(x => x.abbrev === abbrev);
    return t ? t.name : null;
}

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
