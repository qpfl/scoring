from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'
WEB_INDEX = PROJECT_ROOT / 'web' / 'index.html'


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
    helper_start = app.index('const PLAYER_DRAFT_TEAM_CODES = {')
    helper_end = app.index('function getLivePlayerStatus(', helper_start)
    helpers = app[helper_start:helper_end]
    modal_start = app.index('function showPlayerModal(rawName, requestedPosition')
    modal_end = app.index('function hidePlayerModal()', modal_start)
    renderer = app[modal_start:modal_end]

    assert "kaminska: 'CGK'" in helpers
    assert 'return `${liveTeamLabel(abbrev)} (${abbrev})`;' in helpers
    assert 'playerDraftTeamLabel(originalDraft.selectedBy)' in renderer
    assert 'playerDraftTeamLabel(selection.selectedBy)' in renderer
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
    assert 'career pts' in app
    assert 'Currently rostered' in app
    assert 'const rosteredPct = profiles.length > 0' in app
    assert '${rostered}/${profiles.length} (${rosteredPct}%)' in app
    assert 'draft-player-link' in app
    assert 'data-player-name=' in app


def test_player_modal_has_accessible_dialog_markup_and_profile_container():
    html = WEB_INDEX.read_text(encoding='utf-8')

    assert 'role="dialog" aria-modal="true" aria-labelledby="player-modal-name"' in html
    assert 'id="player-modal-profile"' in html
    assert 'aria-label="Close player profile"' in html
