import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'


def test_draft_challenge_results_header_is_not_a_header_element():
    # A bare `header` rule styles the site masthead (flex row, right padding),
    # so a <header> here would inherit that layout.
    app = WEB_APP.read_text(encoding='utf-8')
    assert '<header class="nfl-draft-results-header">' not in app
    assert '<div class="nfl-draft-results-header">' in app


# Stand-ins for the app's helpers: a link that spells out where it goes.
HOF_HELPER_STUBS = """
function isMyFranchiseTextMatch() { return false; }
function myTeamClass() { return ''; }
function isMyFranchise() { return false; }
function myTeamAbbrev() { return 'GSA'; }
function escapeHtml(value) { return String(value); }
function seasonAwareRoute(route) { return route; }
function teamDirectoryTeams() { return [{abbrev: 'GSA'}, {abbrev: 'J/J'}, {abbrev: 'CGK'}]; }
function franchiseCodesForStintTeam(team) { return team === 'RCP' ? ['RCP', 'JDK', 'J/J'] : [team]; }
function matchupLink(season, week, label, className, team) {
    return `<a season="${season}" week="${week}" team="${team}">${label}</a>`;
}
function playerProfileButton(name, className, displayName, position, season) {
    return `<a player="${name}" position="${position}">${name}</a>`;
}
function teamProfileButton(abbrev, name, className, subview, season) {
    return `<a franchise="${abbrev}" subview="${subview}">${name}</a>`;
}
"""


def _run_hof_helpers(expression):
    app = WEB_APP.read_text(encoding='utf-8')
    helper = app[
        app.index('function hofPerfectLineupsSubsection') : app.index('function renderHallOfFame()')
    ]
    script = f"""
{HOF_HELPER_STUBS}
{helper}
process.stdout.write(JSON.stringify({expression}));
"""
    # Piped over stdin: the script can outgrow Linux's 128 KB limit on one
    # command-line argument (`node -e`), which macOS doesn't enforce.
    result = subprocess.run(['node'], input=script, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def _card(group):
    return _run_hof_helpers(f'hofRecordCard({json.dumps(group)})')


def test_record_card_features_the_holder_and_links_the_game():
    html = _card(
        {
            'id': 'team-game-most-points',
            'title': 'Most Points in a Game',
            'unit': 'pts',
            'entries': [
                {
                    'rank': 1,
                    'value': 167,
                    'season': 2025,
                    'week': 15,
                    'week_label': 'Week 15',
                    'team': 'CGK',
                    'owner': 'Connor Kaminska',
                    'team_name': "Josh Allen's Deleted Tweets",
                    'opponent': 'S/T',
                    'opponent_name': "Drunk Darts Don't Count",
                    'score': 167,
                    'opponent_score': 129,
                },
                {
                    'rank': 2,
                    'value': 156,
                    'season': 2021,
                    'week': 5,
                    'week_label': 'Week 5',
                    'team': 'RCP',
                    'owner': 'Ryan P.',
                    'team_name': 'Bocki Balboa',
                },
            ],
            'more_tied': 2,
        }
    )

    assert 'id="record-team-game-most-points"' in html
    assert '<div class="hof-record-leader">' in html
    assert '<span class="hof-record-figure">167</span>' in html
    assert '<a season="2025" week="15" team="CGK">Week 15, 2025</a>' in html
    assert "167-129 vs Drunk Darts Don't Count" in html
    # Old team codes link to the franchise that carries their history.
    assert '<a franchise="J/J" subview="history">Bocki Balboa</a>' in html
    assert '+2 more tied at 156' in html


def test_record_card_shows_players_runs_and_my_team():
    html = _card(
        {
            'id': 'team-longest-win-streak',
            'title': 'Longest Winning Streak',
            'unit': 'games',
            'entries': [
                {
                    'rank': 1,
                    'value': 14,
                    'season': 2026,
                    'week': 7,
                    'week_label': 'Week 7',
                    'team': 'CGK',
                    'owner': 'Connor Kaminska',
                    'start': {'season': 2025, 'week': 3, 'week_label': 'Week 3', 'team': 'CGK'},
                },
                {
                    'rank': 2,
                    'value': 9,
                    'season': 2023,
                    'week': 9,
                    'week_label': 'Week 9',
                    'team': 'GSA',
                    'owner': 'Griff',
                },
            ],
        }
    )
    # No unit label: the title already says it counts games.
    assert '<span class="hof-record-figure">14</span>' in html
    assert '<small>' not in html
    assert (
        '<a season="2025" week="3" team="CGK">Week 3, 2025</a> to '
        '<a season="2026" week="7" team="CGK">Week 7, 2026</a>'
    ) in html
    assert '<li class="hof-record-row is-my-team">' in html

    player = _card(
        {
            'id': 'player-career-most-points',
            'title': 'Most Career Points',
            'unit': 'pts',
            'entries': [
                {
                    'rank': 1,
                    'value': 2707,
                    'player': 'Josh Allen',
                    'position': 'QB',
                    'season': 2026,
                    'team': 'CGK',
                    'owner': 'Connor Kaminska',
                    'starts': 100,
                }
            ],
        }
    )
    assert '<a player="Josh Allen" position="QB">Josh Allen</a>' in player
    assert 'QB · Connor Kaminska' in player
    assert '100 starts · through 2026' in player


def test_shared_records_with_many_holders_list_every_holder():
    entry = {
        'rank': 1,
        'value': -6,
        'player': 'Buffalo Bills',
        'position': 'D/ST',
        'season': 2020,
        'week': 5,
        'week_label': 'Week 5',
        'team': 'JRW',
        'owner': 'Joe W.',
    }
    html = _card(
        {
            'id': 'player-game-defense-shame',
            'title': 'Defensive Hall of Shame',
            'unit': 'pts',
            'entries': [entry, entry, entry],
        }
    )
    assert 'hof-record-leader' not in html
    assert html.count('<li class="hof-record-row">') == 3


def test_hof_perfect_lineups_list_counts_and_link_the_latest():
    html = _run_hof_helpers(
        'hofPerfectLineupsSubsection(['
        "{code: 'JRW', owner: 'Joe W.', count: 2, games: 106,"
        " latest: {season: 2022, week: 11, week_label: 'Week 11', abbrev: 'JRW'}},"
        "{code: 'GSA', owner: 'Griff', count: 0, games: 108, latest: null}])"
    )

    assert 'Perfect Lineups' in html
    assert '<span class="record-holder">Joe W.<span' in html
    assert 'Most recent: <a season="2022" week="11" team="JRW">Week 11, 2022</a>' in html
    assert (
        '<span class="record-value" title="2 of 106 games with full bench scores">2</span>' in html
    )
    assert 'None yet' in html
    assert _run_hof_helpers('hofPerfectLineupsSubsection([])') == ''
