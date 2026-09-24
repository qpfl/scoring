from html.parser import HTMLParser
from pathlib import Path

WEB_INDEX = Path(__file__).resolve().parent.parent / 'web' / 'index.html'
WEB_APP = Path(__file__).resolve().parent.parent / 'web' / 'app.js'


class ManageMarkupParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.shared_tabs = []
        self.my_team_tabs = []
        self.trade_tabs = []
        self.my_team_subnav_hidden = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        element_id = attributes.get('id')
        if element_id:
            self.ids.append(element_id)

        classes = set(attributes.get('class', '').split())
        if element_id == 'my-team-subnav':
            self.my_team_subnav_hidden = 'hidden' in attributes
        if 'team-subnav-btn' in classes:
            target = self.my_team_tabs if 'my-team-btn' in classes else self.shared_tabs
            target.append(attributes.get('data-subview'))
        if 'manage-subtab' in classes:
            self.trade_tabs.append(attributes.get('data-trade-tab'))


def parse_manage_markup():
    parser = ManageMarkupParser()
    parser.feed(WEB_INDEX.read_text(encoding='utf-8'))
    return parser


def test_shared_and_manager_tab_bars_stay_separate():
    markup = parse_manage_markup()

    assert markup.shared_tabs == ['all-rosters', 'roster', 'history', 'activity', 'compare']
    assert markup.my_team_tabs == ['lineup', 'add', 'trades', 'commissioner']
    assert markup.trade_tabs == ['trade', 'tradematches', 'pending', 'tradeblock']
    assert markup.my_team_subnav_hidden is True

    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')

    # The shared bar never carries a manager-only subview, and gating is the
    # only thing that unhides the manager bar - both bars are always in the
    # static markup, never injected.
    assert not set(markup.shared_tabs) & {'lineup', 'add', 'trades', 'commissioner'}
    assert 'function canManageCurrentTeam()' in app
    assert 'id="my-team-subnav"' in html


def test_hub_header_strip_replaces_the_my_team_dashboard():
    app = WEB_APP.read_text(encoding='utf-8')

    # The Dashboard tab is gone; its surviving, non-duplicated content now
    # renders as a strip below the hub header, gated on canManageCurrentTeam().
    assert 'function renderMyTeamDashboard()' not in app
    assert 'function wireMyTeamDashboard()' not in app
    assert 'function myTeamSummary(' not in app
    assert 'function myTeamActivity(' not in app

    assert 'function myTeamHeaderStripHtml(team)' in app
    assert 'function wireMyTeamHeader(team)' in app
    assert 'function findMyTeamMatchup(team)' in app
    assert 'function lineupDashboardStatus(team)' in app

    for label in ('Next Matchup', 'Lineup', 'Set Lineup', 'Pending Trades'):
        assert label in app

    assert 'data-my-team-action="lineup"' in app
    assert 'data-my-team-action="pending"' in app
    assert 'data-my-team-action="matchup"' in app
    assert 'id="my-team-edit-btn"' in app
    assert 'aria-controls="my-team-settings"' in app

    # Extended, not manager-only: every team's hub header now shows PPG/streak.
    hub_header_start = app.index('function renderTeamHubHeader(teamInfo)')
    hub_header_end = app.index('function myTeamHeaderStripHtml', hub_header_start)
    hub_header_body = app[hub_header_start:hub_header_end]
    assert 'data.team_stats?.[currentTeam]' in hub_header_body
    assert '<span>PPG</span>' in hub_header_body
    assert '<span>streak</span>' in hub_header_body


def test_my_team_subnav_is_hidden_by_default_and_gated_on_canManageCurrentTeam():
    markup = parse_manage_markup()
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')

    assert markup.my_team_subnav_hidden is True
    assert not set(markup.shared_tabs) & set(markup.my_team_tabs)

    sync_start = app.index('function syncMyTeamTabs()')
    sync_end = app.index('\n}\n', sync_start)
    sync_body = app[sync_start:sync_end]
    assert "const canManage = canManageCurrentTeam();" in sync_body
    assert "if (subnav) subnav.hidden = !canManage;" in sync_body
    assert 'id="my-team-subnav" role="tablist" aria-label="Manage my team" hidden' in html


def test_manage_rosters_dom_ids_are_unique():
    markup = parse_manage_markup()

    assert len(markup.ids) == len(set(markup.ids))


def test_roster_workspace_has_contextual_action_controls():
    markup = parse_manage_markup()

    assert {
        'roster-action-panel',
        'roster-action-confirm',
        'roster-action-comment',
        'roster-taxi-players',
        'depth-chart-groups',
    }.issubset(set(markup.ids))


def test_team_settings_open_from_the_hub_header():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')

    hub_header_start = html.index('id="team-hub-header"')
    settings_start = html.index('<section class="team-settings my-team-settings"', hub_header_start)
    roster_subview_start = html.index('id="team-roster-subview"')
    roster_tools_start = html.index('id="my-roster-tools"')

    assert hub_header_start < settings_start < roster_subview_start < roster_tools_start
    assert html.count('<section class="team-settings') == 1
    assert 'id="my-team-settings"' in html
    assert 'id="my-team-edit-btn"' in app
    assert 'aria-controls="my-team-settings"' in app
    assert 'settings.hidden = !settings.hidden;' in app


def test_team_settings_are_wired_when_opened_not_only_from_set_lineup():
    app = WEB_APP.read_text(encoding='utf-8')

    # The name/avatar editors used to be wired by initLineupForm(), which now
    # only runs on the Set Lineup tab - Edit Team must wire them itself.
    header_start = app.index('function wireMyTeamHeader(')
    header_body = app[header_start:app.index('\nfunction ', header_start + 1)]
    lineup_start = app.index('function initLineupForm(')
    lineup_body = app[lineup_start:app.index('\nfunction ', lineup_start + 1)]

    assert 'initTeamSettings()' in header_body
    assert 'change-team-name-btn' not in lineup_body
    assert 'initAvatarEditor()' not in lineup_body


def test_confirmed_leave_prompt_discards_manager_edits():
    app = WEB_APP.read_text(encoding='utf-8')
    start = app.index('function confirmManageNavigation(')
    body = app[start:app.index('\nfunction ', start + 1)]

    assert 'discardManageChanges();' in body
    assert 'function discardManageChanges()' in app


def test_global_auth_is_the_only_login_surface():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'id="global-login-btn"' in html
    assert 'id="global-logout-btn"' in html
    assert 'data-login-trigger>Log In</button>' in app
    assert 'function openGlobalLoginDropdown()' in app
    assert "document.getElementById('global-team-select')?.focus()" in app
    assert html.count('type="password"') == 1

    for removed_id in (
        'manage-access-message',
        'manage-panel',
        'manage-team-select',
        'manage-password',
        'manage-login-btn',
        'manage-logout-btn',
        'nfl-draft-password',
        'nfl-draft-login-btn',
        'nfl-draft-logout-btn',
    ):
        assert removed_id not in html
        assert removed_id not in app

    assert 'handleManageLogin' not in app
    assert 'handleNflDraftLogin' not in app
    assert 'const requestTeam = manageState.team;' in app
    assert 'nflDraftState.authedTeam' not in app


def test_global_login_surfaces_api_and_network_errors():
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'error: result.error || `Login failed (HTTP ${response.status}).`' in app
    assert "error: 'Could not reach the login service. Please try again.'" in app
    assert "errorEl.textContent = loginResult.error || 'Login failed. Try again.'" in app


def test_lineup_editor_restores_the_active_week_submission_after_reload():
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'allWeeks.add(activeLineupWeek);' in app
    assert 'const savedLineup = week === activeLineupWeek && data.lineups?.[teamAbbrev]' in app
    assert 'Array.isArray(savedLineup?.[pos])' in app
    assert '.map(name => namesByNormalized.get(name.trim().toLowerCase()))' in app
    assert 'rosterAtPosition.filter(player => player.starter)' in app
