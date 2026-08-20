from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_INDEX = PROJECT_ROOT / 'web' / 'index.html'
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'


def test_team_halls_live_under_hall_of_fame_navigation():
    html = WEB_INDEX.read_text(encoding='utf-8')

    assert 'data-parent="history" data-subview="teams">Team Halls' in html
    assert 'id="history-teams-subview"' in html
    assert 'id="hof-team-selector"' in html
    assert 'data-subview="hof">Team Hall of Fame' not in html


def test_team_hof_uses_precomputed_export_instead_of_season_fetches():
    app = WEB_APP.read_text(encoding='utf-8')
    start = app.index('function renderTeamHof()')
    end = app.index('function renderTeamTradeBlock()', start)
    renderer = app[start:end]

    assert 'team_hall_of_fame?.[currentTeam]' in renderer
    assert 'data_${season}.json' not in renderer


def test_team_hof_hides_empty_banner_sections_and_shows_owner_history():
    app = WEB_APP.read_text(encoding='utf-8')
    start = app.index('function renderTeamHof()')
    end = app.index('function renderTeamTradeBlock()', start)
    renderer = app[start:end]

    assert 'if (teamBanners.length > 0)' in renderer
    assert 'No championships yet...' not in renderer
    assert 'const ownerStats = teamHistory.ownerStats || [];' in renderer
    assert '<div class="team-hof-section-title">Owner Statistics</div>' in renderer


def test_team_stats_explain_opr_and_owner_success_rate():
    app = WEB_APP.read_text(encoding='utf-8')
    start = app.index('function renderTeamStats()')
    end = app.index('function renderConstitution()', start)
    renderer = app[start:end]

    assert 'Oberon Power Ranking' in renderer
    assert 'Owner Performance Rating' not in renderer
    assert 'Owner Success Rate' in renderer
    assert 'points_left_on_table_pct' in renderer


def test_draft_challenge_has_loading_and_final_result_states():
    app = WEB_APP.read_text(encoding='utf-8')
    init_start = app.index('async function initNflDraftView()')
    init_end = app.index('function nflDraftFallbackState', init_start)
    initializer = app[init_start:init_end]

    assert initializer.index('renderNflDraftView();') < initializer.index(
        'await loadNflDraftState();'
    )
    assert "Draft Challenge ${isComplete ? 'Final Results' : 'Live Standings'}" in app
    assert '<details class="nfl-draft-details">' in app
