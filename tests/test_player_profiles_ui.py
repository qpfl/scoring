import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'
WEB_INDEX = PROJECT_ROOT / 'web' / 'index.html'
HALL_OF_FAME = PROJECT_ROOT / 'web' / 'data' / 'shared' / 'hall_of_fame.json'


def test_player_modal_exposes_career_status_draft_award_badge_and_history():
    app = WEB_APP.read_text(encoding='utf-8')
    start = app.index('function showPlayerModal(rawName, requestedPosition')
    end = app.index('function hidePlayerModal()', start)
    renderer = app[start:end]

    assert 'Career by season' in renderer
    assert 'Current owner' in renderer
    assert 'Roster status' in renderer
    assert 'Original draft' in renderer
    assert 'player-award-badge' in renderer
    assert '<h4>Awards</h4>' not in renderer
    assert 'Ownership &amp; transaction history' in renderer
    assert 'game log' in renderer


def test_player_modal_sorts_seasons_and_shows_ppg():
    app = WEB_APP.read_text(encoding='utf-8')
    start = app.index('function showPlayerModal(rawName, requestedPosition')
    end = app.index('function hidePlayerModal()', start)
    renderer = app[start:end]

    assert '.sort(([seasonA], [seasonB]) => Number(seasonB) - Number(seasonA))' in renderer
    assert 'Number(profile?.total_points || 0) / careerGames' in renderer
    assert 'Number(stats.points || 0) / seasonGames' in renderer
    assert '<div class="player-modal-stat-label">PPG</div>' in renderer
    assert '<th class="num">PPG</th>' in renderer

    facts = renderer[
        renderer.index('player-profile-facts') : renderer.index(
            '</section>', renderer.index('player-profile-facts')
        )
    ]
    assert facts.index('Drafted by') < facts.index('Original draft')


def test_player_modal_calculates_and_displays_current_age():
    app = WEB_APP.read_text(encoding='utf-8')
    age_helper_start = app.index('function calculatePlayerAge(')
    modal_start = app.index('function showPlayerModal(rawName, requestedPosition')
    modal_end = app.index('function hidePlayerModal()', modal_start)

    age_helper = app[age_helper_start:modal_start]
    assert 'const birthUtc = Date.UTC(year, month - 1, day);' in age_helper
    assert 'const days = Math.floor((todayUtc - lastBirthdayUtc)' in age_helper
    assert (
        "`${years} ${years === 1 ? 'year' : 'years'}, ${days} ${days === 1 ? 'day' : 'days'}`"
        in age_helper
    )
    assert 'calculatePlayerAge(profile?.birth_date)' in app[modal_start:modal_end]
    assert '<span class="player-age">Age ${playerAge}</span>' in app[modal_start:modal_end]


def test_player_status_and_transactions_use_live_shared_data():
    app = WEB_APP.read_text(encoding='utf-8')

    status_start = app.index('function getLivePlayerStatus(')
    status_end = app.index('function getPlayerDraftHistory(', status_start)
    assert 'sharedData?.rosters' in app[status_start:status_end]

    history_start = app.index('function getPlayerTransactionHistory(')
    history_end = app.index('function describePlayerTransaction(', history_start)
    assert 'sharedData?.transactions' in app[history_start:history_end]


def test_player_draft_team_uses_the_same_franchise_label_as_current_owner():
    app = WEB_APP.read_text(encoding='utf-8')
    helper_start = app.index('const OWNER_TEAM_CODES = {')
    helper_end = app.index('function getLivePlayerStatus(', helper_start)
    helpers = app[helper_start:helper_end]
    modal_start = app.index('function showPlayerModal(rawName, requestedPosition')
    modal_end = app.index('function hidePlayerModal()', modal_start)
    renderer = app[modal_start:modal_end]

    assert "kaminska: 'CGK'" in helpers
    assert "connor: 'CWR'" in helpers
    assert 'return `${liveTeamLabel(abbrev)} (${abbrev})`;' in helpers
    assert "if (code === 'CGK')" in helpers
    assert "if (code === 'CWR')" in helpers
    assert 'return draftTeamDisplayLabel(selectedBy, draft);' in helpers
    assert 'playerDraftTeamLabel(originalDraft.selectedBy, originalDraft)' in renderer
    assert 'playerDraftTeamLabel(selection.selectedBy, selection)' in renderer
    assert 'playerFranchiseLabel(liveStatus.owner)' in renderer


def test_player_history_is_rendered_in_reverse_chronological_order():
    app = WEB_APP.read_text(encoding='utf-8')
    start = app.index('const transactionItems = transactions.map(tx => {')
    end = app.index("document.getElementById('player-modal-profile')", start)
    renderer = app[start:end]

    assert 'order: seasonOrder * 100' in renderer
    assert 'order: selection.year * 100 + phaseOrder' in renderer
    assert '.sort((a, b) => b.order - a.order)' in renderer
    assert 'const historyItems = [...transactionItems, ...draftHistoryItems]' in renderer


def test_draft_history_includes_performance_analysis_and_profile_actions():
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'Draft Class Performance' in app
    assert 'function draftPickFranchisePerformance(profile, draft, team)' in app
    assert 'function draftPerformanceMoment(draft)' in app
    assert "/Midseason Draft/i.test(draft?.name || '') ? 8 : 1" in app
    assert 'stintEndMoment(stint) >= from' in app
    assert 'stintPointsForTeam(stint, team, { from })' in app
    assert 'Points for drafting teams' in app
    assert 'pts for ${escapeHtml(originalOwner' in app
    assert 'Currently rostered' in app
    assert 'const rosteredPct = profiles.length > 0' in app
    assert '${rostered}/${profiles.length} (${rosteredPct}%)' in app
    assert 'draftTeamDisplayLabel(pick.team, draft)' in app
    assert 'draft-owner-state ${ownershipState.tone}' in app
    assert 'draft-player-link' in app
    assert 'data-player-name=' in app


def test_draft_roster_status_uses_distinct_badge_states():
    styles = (PROJECT_ROOT / 'web' / 'styles.css').read_text(encoding='utf-8')

    assert '.draft-pick-performance .draft-owner-state {' in styles
    assert '.draft-owner-state.original {' in styles
    assert '.draft-owner-state.moved {' in styles
    assert '.draft-owner-state.unrostered {' in styles


def test_transactions_show_points_from_the_matching_franchise_stint():
    app = WEB_APP.read_text(encoding='utf-8')
    styles = (PROJECT_ROOT / 'web' / 'styles.css').read_text(encoding='utf-8')

    transaction_loader = app[
        app.index("} else if (view === 'transactions')") : app.index(
            "} else if (view === 'drafts'", app.index("} else if (view === 'transactions')")
        )
    ]
    assert "ensureSharedResource('hall_of_fame')" in transaction_loader
    assert 'function transactionFranchisePerformance(profile, team, tx' in app
    assert "direction === 'departed'" in app
    assert 'transactionAssetHtml(item, tx.proposer, tx)' in app
    assert 'transactionAssetHtml(item, tx.partner, tx)' in app
    assert 'parseTransactionRosterMoves(tx, cleanMessage)' in app
    assert 'pts for ${escapeHtml(team)}' in app
    assert '.transaction-performance-badge {' in styles


def test_exported_franchise_stints_cover_founders_and_reacquisitions():
    profiles = json.loads(HALL_OF_FAME.read_text(encoding='utf-8'))['player_career_stats']

    assert profiles['Josh Allen']['franchise_stints'][0]['points'] == 2524
    assert profiles['Michael Thomas']['franchise_stints'][0]['points'] == 50
    ceedee_gsa_stints = [
        stint['points']
        for stint in profiles['CeeDee Lamb']['franchise_stints']
        if stint['teams'] == ['GSA']
    ]
    assert ceedee_gsa_stints == [186, 53]
    assert (
        next(
            stint['points']
            for stint in profiles['Mac Jones']['franchise_stints']
            if stint['teams'] == ['AST']
        )
        == 88
    )
    assert (
        next(
            stint['points']
            for stint in profiles['Aaron Jones Sr.']['franchise_stints']
            if stint['teams'] == ['GSA']
        )
        == 31
    )
    assert (
        next(
            stint['points']
            for stint in profiles['Seattle Seahawks (OL)']['franchise_stints']
            if stint['teams'] == ['GSA']
        )
        == 17
    )
    assert (
        next(
            stint['points']
            for stint in profiles['Atlanta Falcons (D/ST)']['franchise_stints']
            if stint['teams'] == ['WJK']
        )
        == 36
    )


def test_zero_point_2025_midseason_picks_preserve_their_weekly_results():
    profiles = json.loads(HALL_OF_FAME.read_text(encoding='utf-8'))['player_career_stats']
    chargers = next(
        stint
        for stint in profiles['Los Angeles Chargers (OL)']['franchise_stints']
        if stint['teams'] == ['J/J'] and stint['start_season'] == 2025
    )
    trey_benson = next(
        stint for stint in profiles['Trey Benson']['franchise_stints'] if stint['teams'] == ['WJK']
    )

    assert chargers['points'] == -2
    assert sum(entry[2] for entry in chargers['weekly_points']) == -2
    assert trey_benson['points'] == 0
    assert trey_benson['games'] == 10


def test_player_modal_has_accessible_dialog_markup_and_profile_container():
    html = WEB_INDEX.read_text(encoding='utf-8')

    assert 'role="dialog" aria-modal="true" aria-labelledby="player-modal-name"' in html
    assert 'id="player-modal-profile"' in html
    assert 'aria-label="Close player profile"' in html


def test_player_modal_close_preserves_the_exact_underlying_view():
    app = WEB_APP.read_text(encoding='utf-8')
    popstate_start = app.index("window.addEventListener('popstate'")
    popstate_end = app.index('// ====== MANAGE ROSTER SECTION ======', popstate_start)
    popstate = app[popstate_start:popstate_end]
    helper_start = app.index('function restorePlayerModalReturnRoute(')
    helper_end = app.index('function cleanPlayerProfileLabel(', helper_start)
    helper = app[helper_start:helper_end]
    close_start = app.index('function hidePlayerModal()')
    close_end = app.index("document.body.addEventListener('click'", close_start)
    close = app[close_start:close_end]

    assert 'if (restorePlayerModalReturnRoute(route)) return;' in popstate
    assert 'location.hash === playerModalReturnHash' in helper
    assert 'playerModalRenderedReturnHash === playerModalReturnHash' in helper
    assert 'updatePageMetadata(route.view, route.subview, route.detail);' in helper
    assert 'navigateToView(' not in helper
    assert 'applyHash(' not in helper
    assert 'playerModalRouteRestorePending = true;' in close
    assert 'history.back();' in close


def test_player_modal_return_route_covers_home_and_all_route_changing_overlays():
    app = WEB_APP.read_text(encoding='utf-8')
    html = WEB_INDEX.read_text(encoding='utf-8')
    helper_start = app.index('function playerModalReturnHashForCurrentView()')
    helper_end = app.index('function restorePlayerModalReturnRoute(', helper_start)
    helper = app[helper_start:helper_end]

    assert "if (!location.hash || location.hash === '#') return '#home';" in helper
    assert app.count('history.back();') == 1
    assert html.count('class="confirm-modal-overlay"') == 2
