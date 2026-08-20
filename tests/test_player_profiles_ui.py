from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'
WEB_INDEX = PROJECT_ROOT / 'web' / 'index.html'


def test_player_modal_exposes_career_status_draft_awards_and_history():
    app = WEB_APP.read_text(encoding='utf-8')
    start = app.index('function showPlayerModal(rawName)')
    end = app.index('function hidePlayerModal()', start)
    renderer = app[start:end]

    assert 'Career by season' in renderer
    assert 'Current owner' in renderer
    assert 'Roster status' in renderer
    assert 'Original draft' in renderer
    assert 'Awards' in renderer
    assert 'Ownership &amp; transaction history' in renderer
    assert 'game log' in renderer


def test_player_status_and_transactions_use_live_shared_data():
    app = WEB_APP.read_text(encoding='utf-8')

    status_start = app.index('function getLivePlayerStatus(')
    status_end = app.index('function getPlayerDraftHistory(', status_start)
    assert 'sharedData?.rosters' in app[status_start:status_end]

    history_start = app.index('function getPlayerTransactionHistory(')
    history_end = app.index('function describePlayerTransaction(', history_start)
    assert 'sharedData?.transactions' in app[history_start:history_end]


def test_draft_history_includes_performance_analysis_and_profile_actions():
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'Draft Class Performance' in app
    assert 'career pts' in app
    assert 'Currently rostered' in app
    assert 'draft-player-link' in app
    assert 'data-player-name=' in app


def test_player_modal_has_accessible_dialog_markup_and_profile_container():
    html = WEB_INDEX.read_text(encoding='utf-8')

    assert 'role="dialog" aria-modal="true" aria-labelledby="player-modal-name"' in html
    assert 'id="player-modal-profile"' in html
    assert 'aria-label="Close player profile"' in html
