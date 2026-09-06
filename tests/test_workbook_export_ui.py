"""The Excel export buttons on Teams -> All Rosters and Drafts -> Pick Tracker.

They call the same builders as the commissioner's Workbook Downloads card, but
through the team-level `export_workbook` action rather than `admin_adjust`.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_INDEX = PROJECT_ROOT / 'web' / 'index.html'
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'
WEB_STYLES = PROJECT_ROOT / 'web' / 'styles.css'


def _export_module(app: str) -> str:
    start = app.index('function workbookExportButtons')
    return app[start : app.index('function commissionerAuditDescription', start)]


def test_export_buttons_sit_on_the_rosters_and_pick_tracker_pages():
    html = WEB_INDEX.read_text(encoding='utf-8')

    rosters_subview = html.index('id="team-all-rosters-subview"')
    picks_subview = html.index('id="drafts-picks-subview"')

    rosters_button = html.index('id="export-rosters-btn"')
    draft_button = html.index('id="export-draft-board-btn"')

    assert rosters_subview < rosters_button < html.index('class="all-rosters-wrapper"')
    assert picks_subview < draft_button < html.index('id="pick-tracker-container"')

    assert 'data-export="download_rosters"' in html
    assert 'data-export="download_draft_board"' in html
    assert 'id="export-rosters-status"' in html
    assert 'id="export-draft-board-status"' in html
    assert '.workbook-export' in WEB_STYLES.read_text(encoding='utf-8')


def test_export_requests_use_the_team_login_not_commissioner_credentials():
    module = _export_module(WEB_APP.read_text(encoding='utf-8'))

    assert "action: 'export_workbook'" in module
    assert 'export: exportAction' in module
    assert 'team: manageState.team' in module
    assert 'password: manageState.password' in module
    assert 'admin_adjust' not in module
    assert 'isCommissioner' not in module
    # Reuses the commissioner card's base64 -> download helper.
    assert 'saveWorkbookDownload(result)' in module


def test_export_buttons_stand_down_when_logged_out_or_browsing_an_old_season():
    module = _export_module(WEB_APP.read_text(encoding='utf-8'))

    assert 'const loggedIn = Boolean(manageState.team && manageState.password);' in module
    assert 'currentSeason === null || currentSeason === LIVE_SEASON' in module
    assert 'button.disabled = !loggedIn || !liveSeason;' in module
    assert 'Log in to download this workbook.' in module


def test_export_button_state_follows_login_and_season_changes():
    app = WEB_APP.read_text(encoding='utf-8')

    auth_start = app.index('function updateGlobalAuthUI')
    auth_end = app.index('async function performLogin', auth_start)
    assert 'updateWorkbookExportButtons();' in app[auth_start:auth_end]

    render_start = app.index('if (!render._hashApplied)')
    render_end = app.index('if (compareSubviewActive) initCompareView();', render_start)
    refresh = app[render_start:render_end]
    assert 'initWorkbookExportButtons();' in refresh
    assert 'updateWorkbookExportButtons();' in refresh


def test_draft_board_export_requests_the_live_season():
    module = _export_module(WEB_APP.read_text(encoding='utf-8'))

    assert "exportAction === 'download_draft_board' ? { season: LIVE_SEASON } : {}" in module
