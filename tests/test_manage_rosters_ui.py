from html.parser import HTMLParser
from pathlib import Path

WEB_INDEX = Path(__file__).resolve().parent.parent / 'web' / 'index.html'


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


def test_manage_rosters_uses_consolidated_navigation():
    markup = parse_manage_markup()

    assert markup.primary_tabs == ['depth', 'lineup', 'fa', 'trade']
    assert markup.trade_tabs == ['trade', 'pending', 'tradeblock']
    assert markup.active_content == ['tx-depth']


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


def test_team_settings_are_always_open_on_roster_tab():
    html = WEB_INDEX.read_text(encoding='utf-8')

    roster_start = html.index('<div class="tx-content active" id="tx-depth">')
    settings_start = html.index('<section class="team-settings"', roster_start)

    assert settings_start > roster_start
    assert '<details class="team-settings">' not in html
