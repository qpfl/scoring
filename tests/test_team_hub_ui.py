from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_INDEX = PROJECT_ROOT / 'web' / 'index.html'
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'
WEB_STYLES = PROJECT_ROOT / 'web' / 'styles.css'


def test_team_hub_consolidates_franchise_views_without_removing_league_tools():
    html = WEB_INDEX.read_text(encoding='utf-8')

    for subview in ('overview', 'roster', 'history', 'rivalries', 'activity'):
        assert f'id="team-{subview}-tab"' in html
        assert f'id="team-{subview}-subview"' in html
    assert 'id="team-hub-header"' in html
    assert 'data-subview="all-rosters">All Rosters' in html
    assert 'data-subview="compare">Compare Teams' in html


def test_team_profiles_open_the_canonical_franchise_home():
    app = WEB_APP.read_text(encoding='utf-8')

    assert "history.pushState(null, '', `#teams/overview/${encodeURIComponent(abbrev)}`)" in app
    assert "await navigateToView('teams', 'overview', abbrev)" in app
    assert "const TEAM_HUB_SUBVIEWS = new Set(['overview', 'roster', 'history', 'rivalries', 'activity'])" in app


def test_team_hub_reuses_lore_hall_and_transaction_data():
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'function renderTeamOverview()' in app
    assert 'function renderTeamHistory()' in app
    assert 'function renderTeamRivalries()' in app
    assert 'function renderTeamActivity()' in app
    assert "return data.hall_of_fame?.team_hall_of_fame?.[currentTeam]" in app
    assert '(loreResource().rivalries || []).filter' in app
    assert 'sharedData.transactions || data.transactions || []' in app


def test_legacy_team_hall_and_trade_block_links_are_preserved():
    app = WEB_APP.read_text(encoding='utf-8')

    assert "route.path.match(/^history\\/teams" in app
    assert "`teams/history/${encodeURIComponent(team)}`" in app
    assert "route.path.match(/^teams\\/tradeblock" in app
    assert "`teams/activity/${encodeURIComponent(team)}`" in app


def test_team_hub_has_responsive_franchise_layouts():
    styles = WEB_STYLES.read_text(encoding='utf-8')

    assert '.team-hub-hero' in styles
    assert '.team-overview-grid,' in styles
    assert '.team-named-rivalries' in styles
    assert '.team-activity-grid' in styles
    assert '@media (max-width: 700px)' in styles
