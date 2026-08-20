from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_INDEX = PROJECT_ROOT / 'web' / 'index.html'
WEB_STYLES = PROJECT_ROOT / 'web' / 'styles.css'


def test_desktop_homepage_uses_centered_masthead_and_championship_showcase():
    html = WEB_INDEX.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')

    assert '<div class="league-heading">' in html
    assert '<div class="league-meta">' in html
    assert '<div class="home-championship-showcase">' in html
    showcase = html[html.index('<div class="home-championship-showcase">'):]
    assert showcase.index('id="home-banner"') < showcase.index('id="home-championship"')
    assert showcase.index('id="home-championship"') < showcase.index('id="home-season-scorers"')

    header = styles[styles.index('header {'):styles.index('.league-logo {')]
    assert 'text-align: center;' in header
    assert 'margin-bottom: 1rem;' in header
    assert '@media (min-width: 901px)' in styles
    assert 'grid-template-columns: minmax(13rem, 0.7fr) repeat(2, minmax(0, 1fr));' in styles
    assert 'max-width: 11rem;' in styles


def test_mobile_header_restores_centered_stacked_layout():
    styles = WEB_STYLES.read_text(encoding='utf-8')
    mobile = styles[styles.rindex('@media (max-width: 600px)'):]

    assert 'header {' in mobile
    assert 'display: block;' in mobile
    assert 'text-align: center;' in mobile
    assert 'margin: 0 auto 0.5rem;' in mobile


def test_home_transactions_follow_current_period_rules():
    app = (PROJECT_ROOT / 'web' / 'app.js').read_text(encoding='utf-8')

    assert "ensureSharedResource('transactions')" in app
    assert 'const HOME_TRANSACTION_WINDOW_MS = 7 * 24 * 60 * 60 * 1000;' in app
    assert "week === 'offseason' || week === '0'" in app
    assert 'age >= 0 && age <= HOME_TRANSACTION_WINDOW_MS' in app
    assert 'No offseason transactions yet' in app
    assert 'No transactions in the last 7 days' in app
