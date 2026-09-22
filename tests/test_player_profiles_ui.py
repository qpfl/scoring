import json
import subprocess
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


def test_player_modal_shows_the_nfl_bye_week_beside_roster_status():
    app = WEB_APP.read_text(encoding='utf-8')
    styles = (PROJECT_ROOT / 'web' / 'styles.css').read_text(encoding='utf-8')
    resolve_start = app.index('function resolveNflTeamKey(')
    resolve_end = app.index('function getWeekOpponent(', resolve_start)
    bye_start = app.index('function getNflByeWeek(')
    bye_end = app.index('function getPlayerDraftHistory(', bye_start)
    modal_start = app.index('function showPlayerModal(rawName, requestedPosition')
    modal_end = app.index('function hidePlayerModal()', modal_start)

    assert 'const byeWeek = getNflByeWeek(playerNflTeam);' in app[modal_start:modal_end]
    assert (
        '<span class="player-status-pill bye">Bye ${byeWeek}</span>' in app[modal_start:modal_end]
    )
    assert '.player-status-pill.bye {' in styles

    schedule = {
        str(week): ({} if week == 7 else {'LA': {'opponent': 'SEA'}}) for week in range(1, 19)
    }
    script = f"""
const sharedData = {{ game_opponents: {json.dumps(schedule)} }};
const data = {{ game_opponents: {{}} }};
const NFL_TEAM_ALIASES = {{ LAR: 'LA', JAC: 'JAX', WSH: 'WAS' }};
const NFL_TEAM_REVERSE_ALIASES = {{ LA: 'LAR', JAX: 'JAC', WAS: 'WSH' }};
{app[resolve_start:resolve_end]}
{app[bye_start:bye_end]}
process.stdout.write(JSON.stringify({{
    rams: getNflByeWeek('LAR'),
    unknown: getNflByeWeek('FA'),
}}));
"""
    result = subprocess.run(
        ['node', '-e', script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == {'rams': 7, 'unknown': None}


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
    assert 'draftTeamLink(originalDraft.selectedBy, originalDraft)' in renderer
    assert 'draftTeamLink(selection.selectedBy, selection)' in renderer
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
    assert 'draftTeamLink(pick.team, draft)' in app
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
    # Each side of a trade card scores its own assets against its own team.
    assert 'transactionAssetHtml(item, teamCode, tx)' in app
    assert (
        'transactionSideHtml(transactionTeamLink(tx.proposer, a, tx), receivesItems, tx.proposer, tx)'
        in app
    )
    assert (
        'transactionSideHtml(transactionTeamLink(tx.partner, b, tx), givesItems, tx.partner, tx)'
        in app
    )
    assert 'parseTransactionRosterMoves(tx, cleanMessage)' in app
    assert 'function performanceBadgeHtml(points, team' in app
    assert '.transaction-performance-badge {' in styles
    # Badges live in their own grid column so they line up at every depth.
    assert '.transaction-asset-value {' in styles
    assert 'grid-template-columns: minmax(0, 1fr) auto;' in styles


def test_exported_franchise_stints_cover_founders_and_reacquisitions():
    profiles = json.loads(HALL_OF_FAME.read_text(encoding='utf-8'))['player_career_stats']

    allen_stint = profiles['Josh Allen']['franchise_stints'][0]
    assert allen_stint['points'] == sum(row[2] for row in allen_stint['weekly_points'])
    assert allen_stint['ongoing'] is True
    # An ongoing stint runs to the newest week the export covers. Pinning a
    # specific week here just breaks again every time the scorer runs.
    newest_week = max(
        tuple(row[:2])
        for profile in profiles.values()
        for stint in profile.get('franchise_stints', [])
        for row in stint.get('weekly_points', [])
    )
    assert tuple(allen_stint['weekly_points'][-1][:2]) == newest_week
    # A stint's points are what the player scored from the team's lineup, so a
    # week on the bench or the taxi squad adds a game but no points.
    thomas_stint = profiles['Michael Thomas']['franchise_stints'][0]
    assert thomas_stint['points'] == 41
    assert thomas_stint['starts'] == 8
    assert thomas_stint['games'] == 32
    ceedee_gsa_stints = [
        (stint['points'], stint['starts'], stint['games'])
        for stint in profiles['CeeDee Lamb']['franchise_stints']
        if stint['teams'] == ['GSA']
    ]
    assert ceedee_gsa_stints == [(7, 2, 22), (7, 1, 5)]
    # Never started for these teams: all of their points came off the bench or
    # the taxi squad, so none of it counts as production for the franchise.
    for name, team in (
        ('Mac Jones', 'AST'),
        ('Aaron Jones', 'GSA'),
        ('Atlanta Falcons (D/ST)', 'WJK'),
    ):
        stint = next(
            stint for stint in profiles[name]['franchise_stints'] if stint['teams'] == [team]
        )
        assert (name, stint['points'], stint['starts']) == (name, 0, 0)
    # The contrast case: a unit that does start banks real points. This stint
    # is still running, so check the total against its own weekly rows rather
    # than pinning a number that grows every week.
    seahawks_ol = next(
        stint
        for stint in profiles['Seattle Seahawks (OL)']['franchise_stints']
        if stint['teams'] == ['GSA']
    )
    assert seahawks_ol['starts'] > 0
    assert seahawks_ol['points'] > 0
    assert seahawks_ol['points'] == sum(row[2] for row in seahawks_ol['weekly_points'])


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

    chargers_2025 = [entry for entry in chargers['weekly_points'] if entry[0] == 2025]
    assert sum(entry[2] for entry in chargers_2025) == 2
    assert chargers['points'] == sum(entry[2] for entry in chargers['weekly_points'])
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
