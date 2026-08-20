from html.parser import HTMLParser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_INDEX = PROJECT_ROOT / 'web' / 'index.html'
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'
WEB_STYLES = PROJECT_ROOT / 'web' / 'styles.css'


class NavigationParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_primary_nav = False
        self.in_more_menu = False
        self.primary_views = []
        self.more_views = []
        self.hidden_views = []
        self.more_toggle = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'nav' and attributes.get('id') == 'primary-nav':
            self.in_primary_nav = True
        if not self.in_primary_nav:
            return
        if attributes.get('id') == 'nav-more-menu':
            self.in_more_menu = True
        if attributes.get('id') == 'nav-more-toggle':
            self.more_toggle = attributes
        if tag == 'button' and 'data-view' in attributes:
            target = self.more_views if self.in_more_menu else self.primary_views
            target.append(attributes['data-view'])
            if 'hidden' in attributes:
                self.hidden_views.append(attributes['data-view'])

    def handle_endtag(self, tag):
        if tag == 'nav' and self.in_primary_nav:
            self.in_primary_nav = False


def parse_navigation():
    parser = NavigationParser()
    parser.feed(WEB_INDEX.read_text(encoding='utf-8'))
    return parser


def test_mobile_navigation_has_four_primary_destinations_and_more():
    navigation = parse_navigation()

    assert navigation.primary_views == ['home', 'manage', 'matchups', 'standings']
    assert navigation.more_views == [
        'teams',
        'stats',
        'transactions',
        'history',
        'drafts',
    ]
    assert navigation.hidden_views == []
    assert navigation.more_toggle['aria-expanded'] == 'false'
    assert navigation.more_toggle['aria-controls'] == 'nav-more-menu'
    assert navigation.more_toggle['aria-haspopup'] == 'true'


def test_mobile_navigation_uses_fixed_destinations_instead_of_scrolling():
    html = WEB_INDEX.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')

    assert 'id="nav-toggle"' not in html
    assert 'grid-template-columns: repeat(5, minmax(0, 1fr));' in styles
    assert '.nav-more.open .nav-more-menu' in styles
    assert 'overflow-x: auto;' not in styles[styles.index('@media (max-width: 700px)'):styles.index('.week-selector')]


def test_more_menu_supports_active_state_and_keyboard_dismissal():
    app = WEB_APP.read_text(encoding='utf-8')

    assert "Boolean(activeNavButton?.closest('.nav-more-menu'))" in app
    assert "navMoreToggle.setAttribute('aria-expanded', String(willOpen));" in app
    assert "event.key === 'Escape' && navMore?.classList.contains('open')" in app
    assert 'closeNavMore({ restoreFocus: true });' in app
