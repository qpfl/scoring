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
function escapeHtml(value) { return String(value); }
function matchupLink(season, week, label, className, team) {
    return `<a season="${season}" week="${week}" team="${team}">${label}</a>`;
}
"""


def _run_hof_helpers(expression):
    app = WEB_APP.read_text(encoding='utf-8')
    helper = app[app.index('function hofRecordRow') : app.index('function renderHallOfFame()')]
    script = f"""
{HOF_HELPER_STUBS}
{helper}
process.stdout.write(JSON.stringify({expression}));
"""
    result = subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def _record_rows(records):
    return _run_hof_helpers(f'{json.dumps(records)}.map(hofRecordRow)')


def test_hof_records_split_into_holder_when_and_value():
    team, streak, negative, other = _record_rows(
        [
            "Josh Allen's Deleted Tweets (CGK) - 167 (Week 15, 2025)",
            'Connor Kaminska (CGK) - 11 games (Week 14, 2021 to Week 8, 2022)',
            'QB Spencer Rattler (CWR) - -2 (Week 8, 2025)',
            'Something in another shape',
        ]
    )

    assert "Josh Allen's Deleted Tweets (CGK)" in team
    assert (
        '<span class="record-when"><a season="2025" week="15" team="CGK">Week 15, 2025</a></span>'
        in team
    )
    assert '<span class="record-value">167</span>' in team
    assert '<span class="record-value">11 games</span>' in streak
    assert '<span class="record-value">-2</span>' in negative
    assert 'record-row' not in other
    assert 'Something in another shape' in other


def test_hof_record_weeks_link_to_the_holders_matchup():
    streak, playoff_2020, playoff_2024 = _record_rows(
        [
            'Connor Kaminska (CGK) - 11 games (Week 14, 2021 to Week 8, 2022)',
            'Alvin Kamara (CGK) - 52 (Championship Week, 2020)',
            'Denver Broncos (CWR/SLS) - -6 (Semi-Finals, 2024)',
        ]
    )

    assert '<a season="2021" week="14" team="CGK">Week 14, 2021</a> to ' in streak
    assert '<a season="2022" week="8" team="CGK">Week 8, 2022</a>' in streak
    # Playoff weeks moved from 15-16 to 16-17 when the league grew in 2022.
    assert '<a season="2020" week="16" team="CGK">Championship Week, 2020</a>' in playoff_2020
    assert '<a season="2024" week="16" team="CWR/SLS">Semi-Finals, 2024</a>' in playoff_2024


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
