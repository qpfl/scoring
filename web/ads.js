// "Sponsored content" shown only to one manager. Escalates by week from
// START_WEEK: more ads, on more screens, more personal, popups last.
// Everything here is fake - no forms, and clicking an ad rickrolls him.
//
// Testing: ?adpreview=N shows tier N to whoever is logged in, and
// ?adspeed=N divides every popup timer by N.
(function () {
    'use strict';

    const ENABLED = true;
    const TARGET_TEAM = 'WJK';
    const START_WEEK = 6;
    const MAX_TIER = 6;
    const POPUP_TIER = 6;
    const STOP_AFTER_REVEAL = true;
    const FOUND_KEY = 'qpfl_sponsor_found_v1';
    const SEEN_KEY = 'qpfl_sponsor_first_seen_v1';
    const CLICK_URL = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ';

    // When each view starts carrying ads, what kind of copy it shows, and
    // how the first ad is placed:
    //   generic  - plain sportsbook ads
    //   player   - only about players on his roster
    //   personal - his record, matchup, rivalry, him by name
    const VIEWS = {
        home: { tier: 1, style: 'generic', placement: 'sidebar' },
        drafts: { tier: 2, style: 'generic', placement: 'banner' },
        history: { tier: 2, style: 'generic', placement: 'feed' },
        stats: { tier: 3, style: 'player', placement: 'banner' },
        transactions: { tier: 3, style: 'player', placement: 'banner' },
        matchups: { tier: 4, style: 'generic', placement: 'banner' },
        standings: { tier: 5, style: 'personal', placement: 'banner' },
        manage: { tier: 5, style: 'personal', placement: 'banner' },
    };

    // Lists we can slip ads between, per view.
    const FEED_SELECTORS = {
        home: ['#home-matchups'],
        drafts: ['#drafts-container', '#pick-tracker-container'],
        history: ['#hof-container', '#constitution-container', '#banners-container'],
        stats: ['#stats-leaders-container', '#team-stats-container'],
        transactions: ['#transactions-container'],
        matchups: ['#matchups-container'],
        standings: ['#standings-view .standings-table-wrap'],
        manage: ['#manage-view .manage-container'],
    };

    const params = new URLSearchParams(window.location.search);
    const previewTier = Number(params.get('adpreview')) || 0;
    const speed = Math.max(1, Number(params.get('adspeed')) || 1);

    const extra = { rosters: null, hof: null, loading: false };
    let liveWeek = 0;
    let lastView = null;
    let popupTimer = null;
    let lastPopupClosedAt = 0;
    let lastExitIntentAt = 0;
    let observerQueued = false;

    function storageGet(store, key) {
        try { return store.getItem(key); } catch (e) { return null; }
    }

    function storageSet(store, key, value) {
        try { store.setItem(key, value); } catch (e) { /* private mode */ }
    }

    function esc(value) {
        return typeof escapeHtml === 'function' ? escapeHtml(value) : String(value ?? '');
    }

    function appData() {
        return typeof data !== 'undefined' ? data : null;
    }

    function viewerTeam() {
        return typeof myTeamAbbrev === 'function' ? myTeamAbbrev() : null;
    }

    function currentTier() {
        if (!ENABLED) return 0;
        if (STOP_AFTER_REVEAL && !previewTier && storageGet(localStorage, FOUND_KEY)) return 0;
        const team = viewerTeam();
        if (!team) return 0;
        if (previewTier) return Math.min(MAX_TIER, previewTier);
        if (team !== TARGET_TEAM) return 0;
        const d = appData();
        if (d && typeof LIVE_SEASON !== 'undefined' && d.season === LIVE_SEASON && !d.is_offseason) {
            liveWeek = Number(d.current_week) || liveWeek;
        }
        if (!liveWeek) return 0;
        return Math.max(0, Math.min(MAX_TIER, liveWeek - START_WEEK + 1));
    }

    function activeView() {
        return typeof getActiveView === 'function' ? getActiveView() : 'home';
    }

    function loadExtras() {
        if (extra.loading || typeof LIVE_SEASON === 'undefined' || !LIVE_SEASON) return;
        extra.loading = true;
        fetch(`data/seasons/${LIVE_SEASON}/rosters.json`)
            .then(r => (r.ok ? r.json() : null))
            .then(payload => { extra.rosters = payload?.rosters || payload || null; })
            .catch(() => {});
        fetch('data/shared/hall_of_fame.json')
            .then(r => (r.ok ? r.json() : null))
            .then(payload => { extra.hof = payload; })
            .catch(() => {});
    }

    // Everything the copy can personalise with. Each field has a bland
    // fallback so a missing file just makes the ad less creepy, never broken.
    function context() {
        const d = appData() || {};
        const team = previewTier ? viewerTeam() : TARGET_TEAM;
        const teams = Array.isArray(d.teams) ? d.teams : [];
        const me = teams.find(t => t.abbrev === team) || {};
        const week = liveWeek || Number(d.current_week) || 1;

        const scheduleWeek = (d.schedule || []).find(w => Number(w.week) === week) || {};
        const matchup = (scheduleWeek.matchups || []).find(m => m.team1 === team || m.team2 === team);
        const oppAbbrev = matchup ? (matchup.team1 === team ? matchup.team2 : matchup.team1) : null;
        const opp = teams.find(t => t.abbrev === oppAbbrev) || {};

        const standings = Array.isArray(d.standings) ? d.standings : [];
        const row = standings.find(s => s.abbrev === team) || {};
        const rank = standings.indexOf(row) + 1;

        const rosters = d.rosters && Object.keys(d.rosters).length ? d.rosters : extra.rosters;
        const roster = (rosters && rosters[team]) || [];
        const players = roster
            .filter(p => !['HC', 'OL', 'D/ST', 'K'].includes(p.position))
            .sort((a, b) => (b.projected_points || 0) - (a.projected_points || 0));
        const star = players[0] || {};
        const second = players[1] || {};

        const records = (d.hall_of_fame || extra.hof || {}).rivalry_records?.records || [];
        const h2h = records.find(r =>
            (r.team1 === team && r.team2 === oppAbbrev) || (r.team2 === team && r.team1 === oppAbbrev));
        let h2hLosses = null;
        let h2hWins = null;
        if (h2h) {
            h2hWins = h2h.team1 === team ? h2h.team1_wins : h2h.team2_wins;
            h2hLosses = h2h.team1 === team ? h2h.team2_wins : h2h.team1_wins;
        }

        const first = String(me.owner || 'Bill').split(/\s+/)[0];
        return {
            week,
            first,
            teamName: me.name || 'your team',
            opp: opp.name || 'your opponent',
            oppOwner: String(opp.owner || '').split(/\s+/)[0] || 'them',
            isRivalry: Boolean(scheduleWeek.is_rivalry),
            record: row.wins != null ? `${row.wins}-${row.losses}${row.ties ? `-${row.ties}` : ''}` : null,
            rank: rank > 0 ? rank : null,
            pf: row.points_for,
            star: star.name || null,
            starPos: star.position || '',
            starOpp: star.nfl_opponent || null,
            starProj: star.projected_points || null,
            second: second.name || null,
            h2hWins,
            h2hLosses,
        };
    }

    function line(n) {
        return (Math.round(n * 2) / 2 + 0.5).toFixed(1);
    }

    // Copy pools by style. Each entry returns {brand, headline, body, cta}
    // or null when the data it needs is missing.
    const COPY = {
        generic: [
            () => ({ brand: 'BetQuarry', headline: 'New here? Get a $50 bonus bet.', body: 'Sign up in seconds. Terms apply.', cta: 'Claim bonus' }),
            () => ({ brand: 'ParlayPal', headline: 'Sundays hit different with a parlay.', body: 'Odds boosts every week.', cta: 'See boosts' }),
            () => ({ brand: 'FadeKing', headline: 'Trust your gut. Get paid for it.', body: '100% deposit match up to $250.', cta: 'Join now' }),
            c => ({ brand: 'BetQuarry', headline: `Week ${c.week} parlays are LIVE.`, body: 'Lock in before kickoff. Fantasy managers love our same-game builder.', cta: 'Build a parlay' }),
            () => ({ brand: 'LockSmith Sportsbook', headline: 'Fantasy players win 2x more* with LockSmith.', body: '*We made this number up.', cta: 'Get started' }),
            c => ({ brand: 'ParlayPal', headline: `Week ${c.week} odds boost: any QB 300+ yds`, body: 'Boosted to +450 for fantasy managers only.', cta: 'Grab the boost' }),
        ],
        player: [
            c => c.star && ({ brand: 'BetQuarry', headline: `${c.star} OVER ${c.starProj ? line(c.starProj) : '14.5'} pts?`, body: `You already start him. Why not get paid when he hits${c.starOpp ? ` vs ${c.starOpp}` : ''}?`, cta: 'Bet the over' }),
            c => c.second && ({ brand: 'ParlayPal', headline: `${c.star} + ${c.second} anytime TD parlay`, body: 'Your two best players. One beautiful ticket. +620.', cta: 'Add to slip' }),
            c => ({ brand: 'FadeKing', headline: c.star ? `Managers who own ${c.star} also bet on him.` : 'Managers like you also bet on their players.', body: 'Recommended for you based on your roster.', cta: 'See picks' }),
        ],
        personal: [
            c => ({ brand: 'BetQuarry', headline: `${c.teamName} vs ${c.opp}: Week ${c.week}`, body: c.h2hLosses != null ? `${c.opp} has beaten you ${c.h2hLosses} times. Make it pay this time - bet ${c.opp} +3.5.` : `Hedge your matchup. Bet ${c.opp} +3.5.`, cta: 'Hedge now' }),
            c => c.record && ({ brand: 'LockSmith Sportsbook', headline: `${c.record}${c.rank ? ` and ${ordinal(c.rank)} place` : ''}?`, body: `Your fantasy season might be cooked, ${c.first}. Your betting season doesn't have to be.`, cta: 'Start winning' }),
            c => ({ brand: 'Kuhl Kash Casino', headline: 'The Kuhl Cup has odds now.', body: 'Bill Kuhl vs Joe Kuhl, settled by the books. Family rivalry, family discount.', cta: 'Bet on blood' }),
            c => c.isRivalry && ({ brand: 'ParlayPal', headline: `Rivalry Week special: ${c.oppOwner} props`, body: `Will ${c.oppOwner} trash-talk in the group chat before kickoff? -900.`, cta: 'Take the under' }),
            c => ({ brand: 'BetQuarry', headline: `${c.first}, we noticed you haven't placed a bet in ${c.week} weeks 🥺`, body: 'Is everything okay? Here is $500 in bonus bets to say we miss you.', cta: 'I miss you too' }),
            c => ({ brand: 'FadeKing', headline: `${c.first}'s Personalized Odds Board™`, body: `${c.star || 'Your QB'} 2+ TDs: +210 · ${c.teamName} 120+ pts: +145 · ${c.first} reads this ad to the end: -5000`, cta: 'Bet all 3' }),
            c => ({ brand: 'Kuhl Kash Casino', headline: 'Bill. Bill. Bill.', body: 'One bet. Just one. Nobody has to know. (Everyone in the league knows.)', cta: 'Nobody has to know' }),
            c => ({ brand: 'LockSmith Sportsbook', headline: `Your bench scored ${c.pf ? Math.round(c.pf / Math.max(1, c.week - 1) / 4) : 23} pts last week.`, body: 'Imagine if you had bet on them instead of benching them.', cta: 'Imagine harder' }),
            c => ({ brand: 'ParlayPal', headline: 'Responsible gaming reminder:', body: `Gambling should be fun, ${c.first}. You don't look like you're having fun. Have you tried gambling?`, cta: 'Have fun' }),
        ],
    };

    function ordinal(n) {
        const s = ['th', 'st', 'nd', 'rd'];
        const v = n % 100;
        return n + (s[(v - 20) % 10] || s[v] || s[0]);
    }

    function pickAd(styles) {
        const c = context();
        const pool = styles.flatMap(style => COPY[style]);
        // Prefer copy that isn't already on screen so a page full of ads
        // doesn't repeat itself.
        const onScreen = new Set(
            Array.from(document.querySelectorAll('.qpfl-ad-headline'), el => el.textContent)
        );
        let fallback = null;
        for (let attempt = 0; attempt < pool.length * 2; attempt += 1) {
            const ad = pool[Math.floor(Math.random() * pool.length)](c);
            if (!ad) continue;
            if (!onScreen.has(ad.headline)) return ad;
            fallback = fallback || ad;
        }
        return fallback || COPY.generic[0](c);
    }

    function adHtml(ad) {
        return `
            <div class="qpfl-ad-inner">
                <span class="qpfl-ad-label">Sponsored · ${esc(ad.brand)}</span>
                <strong class="qpfl-ad-headline">${esc(ad.headline)}</strong>
                <span class="qpfl-ad-body">${esc(ad.body)}</span>
                <button type="button" class="qpfl-ad-cta" data-qpfl-ad-cta>${esc(ad.cta)}</button>
            </div>`;
    }

    function makeAd(styles, variant) {
        const el = document.createElement('aside');
        el.className = `qpfl-ad qpfl-ad--${variant}`;
        el.setAttribute('aria-label', 'Advertisement');
        el.innerHTML = adHtml(pickAd(styles));
        return el;
    }

    function removeAll() {
        document.querySelectorAll('.qpfl-ad').forEach(el => el.remove());
        document.body.classList.remove('qpfl-ad-takeover');
        if (popupTimer) { clearTimeout(popupTimer); popupTimer = null; }
    }

    function feedContainer(view) {
        for (const selector of FEED_SELECTORS[view] || []) {
            let el = document.querySelector(selector);
            // Step through a single wrapper element to reach the actual list.
            while (el && el.children.length === 1) el = el.firstElementChild;
            if (el && el.children.length > 1 && !/^(TABLE|TBODY|THEAD|TR)$/.test(el.tagName)) return el;
        }
        return null;
    }

    function injectView(view, tier) {
        const root = document.getElementById(`${view}-view`);
        const config = VIEWS[view];
        if (!root || !config || tier < config.tier) return;
        const styles = [config.style];
        // Tiers since this view joined: 1 when it first gets ads.
        const depth = tier - config.tier + 1;

        if (config.placement === 'sidebar' && !root.querySelector('.qpfl-ad--sidebar')) {
            const grid = root.querySelector('.home-grid');
            (grid || root).appendChild(makeAd(styles, 'sidebar'));
        }
        if (config.placement === 'banner' && !root.querySelector('.qpfl-ad--banner')) {
            const title = root.querySelector('.page-title');
            const banner = makeAd(styles, 'banner');
            if (title) title.after(banner);
            else root.prepend(banner);
        }

        // Feed views start with ads between items; sidebar and banner views
        // pick some up a tier after joining.
        const feedDepth = config.placement === 'feed' ? depth : depth - 1;
        if (feedDepth < 1) return;
        const feed = feedContainer(view);
        if (!feed || feed.querySelector(':scope > .qpfl-ad')) return;
        const items = Array.from(feed.children);
        // One more ad per tier, until popup tier puts one after every other item.
        const cap = tier >= POPUP_TIER ? Infinity : feedDepth;
        const every = tier >= POPUP_TIER ? 2 : Math.max(2, Math.floor(items.length / (cap + 1)));
        let placed = 0;
        items.forEach((item, i) => {
            if (placed >= cap) return;
            if ((i + 1) % every === 0 && i < items.length - 1) {
                item.after(makeAd(styles, 'feed'));
                placed += 1;
            }
        });
    }

    function sync() {
        observerQueued = false;
        const tier = currentTier();
        if (!tier) { removeAll(); return; }
        if (!storageGet(localStorage, SEEN_KEY)) storageSet(localStorage, SEEN_KEY, new Date().toISOString());
        if (!extra.rosters && !extra.loading) loadExtras();

        document.body.classList.toggle('qpfl-ad-takeover', tier >= POPUP_TIER);
        const view = activeView();
        injectView(view, tier);

        if (view !== lastView) {
            const changed = lastView !== null;
            lastView = view;
            if (changed && tier >= POPUP_TIER && Math.random() < 0.3) showPopup();
        }
        schedulePopups(tier);
    }

    function queueSync() {
        if (observerQueued) return;
        observerQueued = true;
        setTimeout(sync, 250);
    }

    function userIsBusy() {
        const active = document.activeElement;
        if (active && /^(INPUT|SELECT|TEXTAREA)$/.test(active.tagName)) return true;
        // Never pop over the site's own dialogs (lineup confirm, trades...).
        return Boolean(document.querySelector('.confirm-modal-overlay.active'));
    }

    function popupCount() {
        return document.querySelectorAll('.qpfl-popup-backdrop').length;
    }

    function showPopup({ force = false } = {}) {
        if (popupCount() >= 2) return;
        if (!force && (userIsBusy() || popupCount() > 0)) return;
        if (!force && Date.now() - lastPopupClosedAt < 30000 / speed) return;

        const ad = pickAd(['personal', 'player']);
        const backdrop = document.createElement('div');
        backdrop.className = 'qpfl-popup-backdrop';
        backdrop.innerHTML = `
            <div class="qpfl-popup qpfl-ad" role="dialog" aria-modal="true" aria-label="Advertisement">
                <button type="button" class="qpfl-popup-close qpfl-popup-close--sneaky" aria-label="Close ad">×</button>
                ${adHtml(ad)}
                <span class="qpfl-popup-timer">Offer expires in <b>04:59</b></span>
            </div>`;
        document.body.appendChild(backdrop);

        const timerEl = backdrop.querySelector('.qpfl-popup-timer b');
        let remaining = 299;
        const countdown = setInterval(() => {
            remaining = remaining > 0 ? remaining - 1 : 299;
            timerEl.textContent = `${String(Math.floor(remaining / 60)).padStart(2, '0')}:${String(remaining % 60).padStart(2, '0')}`;
        }, 1000);

        const close = () => {
            clearInterval(countdown);
            backdrop.remove();
            lastPopupClosedAt = Date.now();
            if (!force && Math.random() < 0.25) {
                setTimeout(() => showPopup({ force: true }), 400);
            }
        };
        backdrop.querySelector('.qpfl-popup-close').addEventListener('click', event => {
            event.stopPropagation();
            close();
        });
        backdrop.addEventListener('click', event => {
            if (event.target === backdrop) close();
        });
        document.addEventListener('keydown', function onKey(event) {
            if (!backdrop.isConnected) { document.removeEventListener('keydown', onKey); return; }
            if (event.key === 'Escape') { document.removeEventListener('keydown', onKey); close(); }
        });
    }

    function schedulePopups(tier) {
        if (popupTimer || tier < POPUP_TIER) return;
        // First one shortly after load, then every 45-60s.
        const delay = lastPopupClosedAt ? (45000 + Math.random() * 15000) / speed : 1500;
        popupTimer = setTimeout(() => {
            popupTimer = null;
            const now = currentTier();
            if (now >= POPUP_TIER) showPopup();
            schedulePopups(now);
        }, delay);
    }

    function reveal() {
        storageSet(localStorage, FOUND_KEY, new Date().toISOString());
        window.location.href = CLICK_URL;
    }

    document.addEventListener('click', event => {
        const ad = event.target.closest('.qpfl-ad');
        if (!ad || event.target.closest('.qpfl-popup-close')) return;
        event.preventDefault();
        reveal();
    });

    // Exit intent: the cursor leaves through the top of the window.
    document.addEventListener('mouseout', event => {
        if (event.relatedTarget || event.clientY > 0) return;
        const tier = currentTier();
        if (tier < POPUP_TIER || Date.now() - lastExitIntentAt < 120000 / speed) return;
        lastExitIntentAt = Date.now();
        showPopup();
    });

    // Views re-render by rewriting innerHTML, which wipes injected ads, and
    // My Team renders outside the normal view pipeline - so watch the DOM
    // and top ads back up whenever the page settles.
    function start() {
        const main = document.getElementById('main-content') || document.body;
        new MutationObserver(queueSync).observe(main, { childList: true, subtree: true });
        window.addEventListener('hashchange', queueSync);
        setInterval(queueSync, 5000);
        queueSync();
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
})();
