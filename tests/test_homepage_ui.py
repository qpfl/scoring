import json
import re
import subprocess
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


def _function_source(app: str, name: str) -> str:
    match = re.search(rf'^function {name}\(', app, re.MULTILINE)
    assert match, f'{name} not found in web/app.js'
    next_match = re.search(r'^function \w+\(', app[match.end() :], re.MULTILINE)
    end = match.end() + next_match.start() if next_match else len(app)
    return app[match.start() : end]


def test_home_transactions_show_latest_five_without_period_or_type_filters():
    app = WEB_APP.read_text(encoding='utf-8')

    assert "ensureSharedResource('transactions')" in app
    assert 'const HOME_TRANSACTION_LIMIT = 5;' in app
    assert 'data.transactions?.length' in app
    assert '.slice(0, HOME_TRANSACTION_LIMIT)' in app
    assert 'No transactions yet' in app
    assert 'View transaction history' in app

    helpers = '\n'.join(
        _function_source(app, name)
        for name in (
            'extractDateFromMessage',
            'parseTransactionTimestamp',
            'repairMessageDateYear',
            'transactionTime',
            'recentHomeTransactions',
        )
    )
    script = f"""
let data = {{
    transactions: [],
    recent_transactions: [
        {{ id: 'oldest', type: 'trade', season: 2019, week: 4, timestamp: '2019-09-01T00:00:00Z' }},
        {{ id: 'newest', type: 'trade', season: 2026, week: 'Offseason', timestamp: '2026-09-10T00:00:00Z' }},
        {{ id: 'activation', type: 'fa_activation', season: 2026, week: 2, timestamp: '2026-09-09T00:00:00Z' }},
        {{ id: 'prior-season', type: 'taxi_activation', season: 2025, week: 17, timestamp: '2025-12-25T00:00:00Z' }},
        {{ id: 'release', type: 'release', season: 2024, week: 8, timestamp: '2024-10-20T00:00:00Z' }},
        {{ id: 'ancient', type: 'transaction', season: 2020, week: 1, timestamp: '2020-09-01T00:00:00Z' }},
    ],
}};
const HOME_TRANSACTION_LIMIT = 5;
{helpers}
process.stdout.write(JSON.stringify(recentHomeTransactions().map(tx => tx.id)));
"""
    result = subprocess.run(
        ['node', '-e', script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == [
        'newest',
        'activation',
        'prior-season',
        'release',
        'ancient',
    ]


def test_in_season_homepage_uses_current_season_summary_cards():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')
    renderer = app[
        app.index('function renderHomeSeason()') : app.index(
            'function setHomeCardLink', app.index('function renderHomeSeason()')
        )
    ]

    home_switch = app[
        app.index('function renderHome()') : app.index(
            'async function ensurePreviousSeasonLoaded()', app.index('function renderHome()')
        )
    ]
    assert 'const isOffseason = data.is_offseason || data.is_historical;' in home_switch
    assert 'data.current_week === 0' not in home_switch
    assert 'data.current_week > 17' not in home_switch
    assert 'data.previous_season' not in renderer
    assert 'const standingsContext = getPostseasonStatusContext();' in renderer
    assert 'const homeStandings = standingsContext.standings.length' in renderer
    assert 'completedStandingsLabel(standingsContext.completedThrough)' in renderer
    assert 'const scheduledWeek = data.schedule.find' in renderer
    assert ': (scheduledWeek?.matchups || []);' in renderer
    assert 'team.rank_points?.toFixed(1)' in renderer
    assert 'team.wins || 0}-${team.losses || 0}' in renderer
    assert 'renderHomeTransactions();' in renderer
    assert 'id="home-matchups-footer"' in html
    assert 'id="home-current-standings-footer"' in html
    assert 'id="home-standings-as-of"' in html
    assert 'id="home-current-transactions-footer"' in html


def test_home_matchup_highlights_the_whole_logged_in_row():
    app = WEB_APP.read_text(encoding='utf-8')
    matchup = app[
        app.index('function compactHomeMatchup(') : app.index(
            'function renderHomeRecap()', app.index('function compactHomeMatchup(')
        )
    ]

    assert 'const rowMine = myTeamClass(team1.abbrev) || myTeamClass(team2.abbrev);' in matchup
    assert '<a class="home-matchup ${rowMine}"' in matchup
    assert 'home-matchup-team ${team1Result} ${myTeamClass' not in matchup
    assert 'home-matchup-team right ${team2Result} ${myTeamClass' not in matchup


def test_home_recap_shows_previous_scores_or_week_one_draft():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')
    recap = app[
        app.index('function renderHomeRecap()') : app.index(
            'function extractDateFromMessage', app.index('function renderHomeRecap()')
        )
    ]

    assert 'id="home-recap-title"' in html
    assert "title.textContent = 'Last Week\\'s Scores';" in recap
    assert 'const previousWeekNumber = currentWeek - 1;' in recap
    assert '.map(matchup => compactHomeMatchup(matchup, previousWeekNumber))' in recap
    assert 'if (currentWeek === 1)' in recap
    assert 'renderHomeDraftRecap(container, title, weekLabel);' in recap
    assert '(data.drafts || []).find(matchesSeason)' in recap
    assert '(data.upcoming_drafts || []).find(matchesSeason)' in recap
    assert "String(round.round) === '1'" in recap
    assert '#drafts/history?draft=${encodeURIComponent(draft.name)}' in recap
    assert "if (currentWeek === 1) requests.push(ensureSharedResource('drafts'));" in app


def test_historical_homepage_omits_latest_transactions():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')
    prepare = app[
        app.index('async function prepareViewData(view, subview)') : app.index(
            'const VIEW_RENDERERS', app.index('async function prepareViewData(view, subview)')
        )
    ]
    offseason = app[
        app.index('function renderHomeOffseason()') : app.index(
            'function renderHomeOffseasonTransactions()'
        )
    ]
    historical_loader = prepare[
        prepare.index('if (data.is_historical)') : prepare.index('} else if (data.is_offseason)')
    ]

    assert 'id="home-offseason-transactions-card"' in html
    assert 'offseasonTransactionsCard.hidden = Boolean(data.is_historical)' in app
    assert 'ensureAllSeasonWeeks()' in historical_loader
    assert "ensureSharedResource('transactions')" not in historical_loader
    assert 'if (!data.is_historical) {\n        renderHomeOffseasonTransactions();' in offseason


def test_season_selector_keeps_the_current_page():
    app = WEB_APP.read_text(encoding='utf-8')
    switcher = app[
        app.index('async function switchToSeason(season)') : app.index(
            'function renderSeasonSelector()',
            app.index('async function switchToSeason(season)'),
        )
    ]

    assert 'await loadData(season)' in switcher
    assert 'await applyHash()' in switcher
    assert "'#home'" not in switcher
    assert switcher.index('await loadData(season)') < switcher.index('await applyHash()')
    assert 'await switchToSeason(season)' in app


def test_current_offseason_homepage_loads_the_previous_season():
    app = WEB_APP.read_text(encoding='utf-8')
    prepare = app[
        app.index('async function prepareViewData(view, subview)') : app.index(
            'const VIEW_RENDERERS', app.index('async function prepareViewData(view, subview)')
        )
    ]
    previous_loader = app[
        app.index('async function ensurePreviousSeasonLoaded()') : app.index(
            'function renderHomeSeason()', app.index('async function ensurePreviousSeasonLoaded()')
        )
    ]

    assert '} else if (data.is_offseason) {' in prepare
    assert 'ensurePreviousSeasonLoaded()' in prepare
    assert 'data.previous_season || data.is_historical' not in previous_loader
    assert 'await ensureAllSeasonWeeks(target)' in previous_loader


def test_historical_homepage_uses_the_selected_seasons_results():
    app = WEB_APP.read_text(encoding='utf-8')
    offseason = app[
        app.index('function renderHomeOffseason()') : app.index(
            'function renderHomeOffseasonTransactions()',
            app.index('function renderHomeOffseason()'),
        )
    ]

    assert 'const prevSeason = data.is_historical ? null : data.previous_season;' in offseason
    assert 'const displaySeason = prevSeason ? prevSeason.season : data.season;' in offseason
    assert 'const displayWeeks = prevSeason ? prevSeason.weeks : data.weeks;' in offseason
    assert (
        'const displayStandings = prevSeason ? prevSeason.standings : data.standings;' in offseason
    )


def test_homepage_uses_each_seasons_actual_championship_week():
    app = WEB_APP.read_text(encoding='utf-8')
    offseason = app[
        app.index('function renderHomeOffseason()') : app.index(
            'function renderHomeOffseasonTransactions()',
            app.index('function renderHomeOffseason()'),
        )
    ]

    assert 'const championshipWeek = [...displayWeeks]' in offseason
    assert 'Number(b.week) - Number(a.week)' in offseason
    assert '`#matchups/week/${championshipWeekNumber}`' in offseason
    assert "'View Championship Matchup →'" in offseason
    assert 'displaySeason);' in offseason
