import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_INDEX = PROJECT_ROOT / 'web' / 'index.html'
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'
WEB_STYLES = PROJECT_ROOT / 'web' / 'styles.css'


def evaluate_team_transaction(transaction: dict) -> dict:
    app = WEB_APP.read_text(encoding='utf-8')
    date_helpers = app[
        app.index('function extractDateFromMessage') : app.index('function parseOldTradeMessage')
    ]
    legacy_trade_helpers = app[
        app.index('function parseOldTradeMessage') : app.index('function compactOwnerLabel')
    ]
    owner_helpers = app[
        app.index('const OWNER_TEAM_CODES') : app.index('function formatTradeTitle')
    ]
    team_transaction_helpers = app[
        app.index('function transactionAssets') : app.index('function renderTeamActivity')
    ]
    script = f"""
let data = {{teams: [{{abbrev: 'GSA', owner: 'Griffin Ansel'}}]}};
let sharedData = {{teams: data.teams}};
let currentTeam = 'GSA';
function formatDate(value) {{ return `formatted:${{value}}`; }}
function formatTransactionMessage() {{ return ''; }}
{date_helpers}
{legacy_trade_helpers}
{owner_helpers}
{team_transaction_helpers}
const transaction = {json.dumps(transaction)};
process.stdout.write(JSON.stringify({{
    summary: teamTransactionSummary(transaction),
    date: teamTransactionDateLabel(transaction),
}}));
"""
    result = subprocess.run(
        ['node', '-e', script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


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


def test_team_activity_summarizes_legacy_trade_for_selected_team():
    transaction = {
        'type': 'trade',
        'team': 'Trade between Anagh and Griff',
        'message': (
            '11/20/2025 | To Griff: | TE George Kittle (SF) | AST 2027 1st round waiver '
            '| To Anagh: | TE Dallas Goedert (PHI) | GSA 2027 2nd round taxi'
        ),
        'timestamp': '2025-01-01T00:00:00',
    }

    display = evaluate_team_transaction(transaction)

    assert display == {
        'summary': (
            'Trade with Anagh: received TE George Kittle (SF), '
            'AST 2027 1st round waiver; sent TE Dallas Goedert (PHI), '
            'GSA 2027 2nd round taxi.'
        ),
        'date': '11/20/2025',
    }


def test_team_activity_keeps_structured_trade_summary_and_timestamp():
    transaction = {
        'type': 'trade',
        'proposer': 'GSA',
        'partner': 'SLS',
        'proposer_gives': {'players': ['Sent Player'], 'picks': []},
        'proposer_receives': {'players': ['Received Player'], 'picks': []},
        'timestamp': '2026-08-24T12:34:56-07:00',
    }

    display = evaluate_team_transaction(transaction)

    assert display == {
        'summary': 'Trade with SLS: received Received Player; sent Sent Player.',
        'date': 'formatted:2026-08-24T12:34:56-07:00',
    }


def test_team_home_uses_meaningful_team_history_without_equal_size_roster_counts():
    app = WEB_APP.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')
    start = app.index('function renderTeamOverview()')
    end = app.index('function renderTeamRivalries()', start)
    renderer = app[start:end]

    assert 'Roster Snapshot' not in renderer
    assert '<h3>Team Record</h3>' in renderer
    assert '<h3>Team Lore</h3>' in renderer
    assert 'team-overview-lore' in renderer
    assert 'align-items: start;' in styles


def test_team_history_has_a_home_link_and_avoids_redundant_all_time_labels():
    app = WEB_APP.read_text(encoding='utf-8')
    start = app.index('function renderTeamHistory()')
    end = app.index('function teamHistoryData()', start)
    renderer = app[start:end]

    assert '← Team Home' in renderer
    assert '(All-Time)' not in renderer
    assert 'Franchise Records' in renderer


def test_legacy_transaction_team_filter_uses_exact_owner_aliases():
    app = WEB_APP.read_text(encoding='utf-8')
    start = app.index('function txInvolvesTeam(')
    end = app.index('function getEffectiveTxType(', start)
    helper = app[start:end]

    assert "connor: 'CWR'" in app
    assert "'connor kaminska': 'CGK'" in app
    assert 'parseOldTradeMessage(cleanMessage)' in helper
    assert 'buildTxSearchText(tx).includes(teamLabel(abbrev)' not in helper


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
