from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_INDEX = PROJECT_ROOT / 'web' / 'index.html'
WEB_STYLES = PROJECT_ROOT / 'web' / 'styles.css'
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'


def test_desktop_homepage_uses_centered_masthead_and_championship_showcase():
    html = WEB_INDEX.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')

    assert '<div class="league-heading">' in html
    assert '<div class="league-meta">' in html
    assert 'class="home-header"' not in html
    assert 'Welcome to the QPFL' not in html
    assert '<div class="home-championship-showcase">' in html
    showcase = html[html.index('<div class="home-championship-showcase">') :]
    assert showcase.index('id="home-banner"') < showcase.index('id="home-championship"')
    assert showcase.index('id="home-championship"') < showcase.index('id="home-season-scorers"')

    header = styles[styles.index('header {') : styles.index('.league-logo {')]
    assert 'text-align: center;' in header
    assert 'margin-bottom: 1rem;' in header
    league_meta = styles[styles.index('.league-meta {') : styles.index('.season-selector {')]
    assert 'flex-direction: column;' in league_meta
    assert '@media (min-width: 901px)' in styles
    assert 'grid-template-columns: minmax(13rem, 0.7fr) repeat(2, minmax(0, 1fr));' in styles
    assert 'max-width: 11rem;' in styles


def test_mobile_header_uses_compact_masthead_layout():
    styles = WEB_STYLES.read_text(encoding='utf-8')
    mobile = styles[styles.rindex('@media (max-width: 600px)') :]

    assert 'header {' in mobile
    assert 'display: grid;' in mobile
    assert 'grid-template-columns: 3.25rem minmax(0, 1fr);' in mobile
    assert 'text-align: left;' in mobile
    assert 'width: 3.25rem;' in mobile


def test_home_transactions_follow_current_period_rules():
    app = WEB_APP.read_text(encoding='utf-8')

    assert "ensureSharedResource('transactions')" in app
    assert 'const HOME_TRANSACTION_WINDOW_MS = 7 * 24 * 60 * 60 * 1000;' in app
    assert "week === 'offseason' || week === '0'" in app
    assert 'age >= 0 && age <= HOME_TRANSACTION_WINDOW_MS' in app
    assert 'No offseason moves yet' in app
    assert 'No moves in the last 7 days' in app
    assert 'View transaction history' in app


def test_season_selector_opens_the_selected_season_homepage():
    app = WEB_APP.read_text(encoding='utf-8')
    switcher = app[
        app.index('async function switchToSeasonHome(season)') :
        app.index('function renderSeasonSelector()', app.index('async function switchToSeasonHome(season)'))
    ]

    assert "history.pushState(null, '', '#home')" in switcher
    assert 'await loadData(season)' in switcher
    assert "await navigateToView('home')" in switcher
    assert switcher.index('await loadData(season)') < switcher.index("history.pushState(null, '', '#home')")
    assert 'await switchToSeasonHome(season)' in app


def test_every_offseason_homepage_loads_the_previous_season():
    app = WEB_APP.read_text(encoding='utf-8')
    prepare = app[
        app.index('async function prepareViewData(view, subview)') :
        app.index('const VIEW_RENDERERS', app.index('async function prepareViewData(view, subview)'))
    ]
    previous_loader = app[
        app.index('async function ensurePreviousSeasonLoaded()') :
        app.index('function renderHomeSeason()', app.index('async function ensurePreviousSeasonLoaded()'))
    ]

    assert 'data.is_historical || data.is_offseason' in prepare
    assert 'ensurePreviousSeasonLoaded()' in prepare
    assert 'data.previous_season || data.is_historical' not in previous_loader
    assert 'await ensureAllSeasonWeeks(target)' in previous_loader


def test_homepage_uses_each_seasons_actual_championship_week():
    app = WEB_APP.read_text(encoding='utf-8')
    offseason = app[
        app.index('function renderHomeOffseason()') :
        app.index('function renderHomeOffseasonTransactions()', app.index('function renderHomeOffseason()'))
    ]

    assert 'const championshipWeek = [...displayWeeks]' in offseason
    assert 'Number(b.week) - Number(a.week)' in offseason
    assert '`#matchups/week/${championshipWeekNumber}`' in offseason
    assert "navigateToView('matchups', 'week', championshipWeekNumber)" in offseason
