from html.parser import HTMLParser
from pathlib import Path

WEB_INDEX = Path(__file__).resolve().parent.parent / 'web' / 'index.html'
WEB_APP = Path(__file__).resolve().parent.parent / 'web' / 'app.js'


class ManageMarkupParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.primary_tabs = []
        self.trade_tabs = []
        self.active_content = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        element_id = attributes.get('id')
        if element_id:
            self.ids.append(element_id)

        classes = set(attributes.get('class', '').split())
        if 'tx-tab' in classes:
            self.primary_tabs.append(attributes.get('data-tab'))
        if 'manage-subtab' in classes:
            self.trade_tabs.append(attributes.get('data-trade-tab'))
        if 'tx-content' in classes and 'active' in classes:
            self.active_content.append(element_id)


def parse_manage_markup():
    parser = ManageMarkupParser()
    parser.feed(WEB_INDEX.read_text(encoding='utf-8'))
    return parser


def test_my_team_uses_dashboard_first_consolidated_navigation():
    markup = parse_manage_markup()

    assert markup.primary_tabs == ['dashboard', 'depth', 'lineup', 'fa', 'trade', 'commissioner']
    assert markup.trade_tabs == ['trade', 'pending', 'tradeblock']
    assert markup.active_content == ['tx-dashboard']


def test_my_team_dashboard_has_required_statuses_and_actions():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'data-view="manage">My Team</button>' in html
    assert '<div class="page-title">My Team</div>' in html
    assert 'id="my-team-dashboard"' in html

    for label in (
        'Next Matchup',
        'Lineup',
        'Set Lineup',
        'Pending Trades',
        'Draft Challenge',
        'Recent Roster Activity',
    ):
        assert label in app

    assert 'function findMyTeamMatchup(team)' in app
    assert 'function lineupDashboardStatus(team)' in app
    assert 'function myTeamSummary(team)' in app
    assert 'Standings: ${summary.rank}/${summary.totalTeams}, PPG: ${summary.ppg.toFixed(1)}, Streak: ${summary.streak}' in app
    assert 'Your matchup, deadlines, and team activity in one place.' not in app
    assert 'refreshMyTeamDraftStatus(team);' in app
    assert "data-my-team-action=\"lineup\"" in app


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


def test_team_settings_open_from_dashboard_and_are_removed_from_roster():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')

    dashboard_start = html.index('<div class="tx-content active" id="tx-dashboard"')
    settings_start = html.index('<section class="team-settings my-team-settings"', dashboard_start)
    roster_start = html.index('<div class="tx-content" id="tx-depth"')
    roster_actions_start = html.index('<section class="roster-action-panel"', roster_start)

    assert dashboard_start < settings_start < roster_start
    assert '<section class="team-settings' not in html[roster_start:roster_actions_start]
    assert 'id="my-team-settings"' in html
    assert 'id="my-team-edit-btn"' in app
    assert 'aria-controls="my-team-settings"' in app
    assert 'settings.hidden = !settings.hidden;' in app


def test_global_auth_is_the_only_login_surface():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'id="global-login-btn"' in html
    assert 'id="global-logout-btn"' in html
    assert 'id="manage-access-message"' in html
    assert html.count('type="password"') == 1

    for removed_id in (
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
