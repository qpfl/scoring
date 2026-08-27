import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'
WEB_INDEX = PROJECT_ROOT / 'web' / 'index.html'
WEB_STYLES = PROJECT_ROOT / 'web' / 'styles.css'


def run_node(script: str):
    result = subprocess.run(
        ['node', '-e', script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def app_slice(start_marker: str, end_marker: str) -> str:
    app = WEB_APP.read_text(encoding='utf-8')
    start = app.index(start_marker)
    end = app.index(end_marker, start)
    return app[start:end]


def test_lineup_assistant_markup_and_health_summary_are_present():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')

    for element_id in (
        'lineup-projected-btn',
        'lineup-copy-btn',
        'lineup-assist-status',
        'lineup-warnings',
    ):
        assert f'id="{element_id}"' in html
    assert 'Nothing is submitted automatically.' in html
    assert 'function useProjectedLineup()' in app
    assert 'function copyLastSubmittedLineup()' in app
    assert 'function lineupHealthWarnings()' in app
    assert 'Projected ${projectedTotal.toFixed(1)} pts' in app
    assert '.lineup-assistant {' in styles
    assert '.lineup-warnings li.danger {' in styles


def test_lineup_recommendations_preserve_locked_starters_and_skip_byes():
    functions = app_slice(
        'function applyLineupRecommendation',
        'function teamLineupFromScoredWeek',
    )
    script = f"""
const LINEUP_CONFIG = {{
    positions: {{ QB: {{ max: 1 }}, RB: {{ max: 2 }} }}
}};
const data = {{ lineup_week: 4, current_week: 4 }};
let lineupState = {{
    week: 4,
    roster: [
        {{ name: 'Locked QB', position: 'QB', projected_points: 10, on_bye: false }},
        {{ name: 'Higher QB', position: 'QB', projected_points: 30, on_bye: false }},
        {{ name: 'Bye RB', position: 'RB', projected_points: 25, on_bye: true }},
        {{ name: 'Ready RB', position: 'RB', projected_points: 18, on_bye: false }},
        {{ name: 'Other RB', position: 'RB', projected_points: 12, on_bye: false }},
    ],
    selections: {{ QB: ['Locked QB'], RB: [] }},
}};
function getLockedPlayers() {{ return new Set(['Locked QB']); }}
function setLineupAssistStatus() {{}}
function renderLineupEditor() {{}}
{functions}
useProjectedLineup();
process.stdout.write(JSON.stringify(lineupState.selections));
"""

    assert run_node(script) == {
        'QB': ['Locked QB'],
        'RB': ['Ready RB', 'Other RB'],
    }


def test_lineup_health_flags_unfilled_bye_and_injury_starters():
    functions = app_slice(
        'function selectedLineupPlayers',
        'function updateLineupSummary',
    )
    script = f"""
const LINEUP_CONFIG = {{
    positions: {{ QB: {{ max: 1 }}, RB: {{ max: 2 }} }}
}};
const data = {{ lineup_week: 4, current_week: 4 }};
const lineupState = {{
    week: 4,
    roster: [
        {{ name: 'Bye QB', position: 'QB', on_bye: true }},
        {{ name: 'Hurt RB', position: 'RB', on_bye: false }},
    ],
    selections: {{ QB: ['Bye QB'], RB: ['Hurt RB'] }},
}};
function getCurrentPlayerInjury(player) {{
    return player.name === 'Hurt RB' ? {{ abbreviation: 'Q' }} : null;
}}
{functions}
process.stdout.write(JSON.stringify(lineupHealthWarnings()));
"""
    warnings = run_node(script)
    messages = [warning['message'] for warning in warnings]

    assert '1 RB starter slot unfilled' in messages
    assert 'On bye: Bye QB' in messages
    assert 'Injury watch: Hurt RB (Q)' in messages


def test_trade_matches_prioritize_two_way_fits_and_include_listed_players():
    functions = app_slice('function tradeBlockSupply', 'function renderTradeMatches')
    script = f"""
const data = {{
    teams: [
        {{ abbrev: 'A', name: 'Alpha' }},
        {{ abbrev: 'B', name: 'Bravo' }},
        {{ abbrev: 'C', name: 'Charlie' }},
    ],
    trade_blocks: {{
        A: {{ seeking: ['WR'], trading_away: ['RB'], players_available: [] }},
        B: {{ seeking: ['RB'], trading_away: ['WR'], players_available: ['Bravo WR'] }},
        C: {{ seeking: ['RB'], trading_away: ['TE'], players_available: [] }},
    }},
}};
const rosters = {{
    A: [{{ name: 'Alpha RB', position: 'RB' }}],
    B: [{{ name: 'Bravo WR', position: 'WR' }}],
    C: [{{ name: 'Charlie TE', position: 'TE' }}],
}};
function getTeamData(team) {{ return {{ roster: rosters[team], taxi_squad: [] }}; }}
function tradeablePlayersFor(team) {{ return team?.roster || []; }}
function currentTeamAvatar() {{ return ''; }}
{functions}
process.stdout.write(JSON.stringify(computeTradeMatches('A')));
"""
    matches = run_node(script)

    assert [match['partner'] for match in matches] == ['B', 'C']
    assert matches[0]['twoWay'] is True
    assert matches[0]['theyOffer'] == ['WR']
    assert matches[0]['theyWant'] == ['RB']
    assert matches[0]['availablePlayers'][0]['name'] == 'Bravo WR'
    assert matches[1]['twoWay'] is False


def test_trade_matches_live_in_my_team_and_handoff_to_trade_builder():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')

    assert 'data-trade-tab="tradematches"' in html
    assert 'id="tx-tradematches"' in html
    assert "new Set(['trade', 'tradematches', 'pending', 'tradeblock'])" in app
    assert 'function computeTradeMatches(teamAbbrev)' in app
    assert "function startTradeFromMatch(partner, playerName = '')" in app
    assert 'manageState.tradePartner = partner;' in app
    assert "switchTxTab('trade');" in app
    assert '.trade-match-card.two-way {' in styles


def test_playoff_odds_show_deterministic_week_over_week_movement():
    app = WEB_APP.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')
    random_function = app_slice('function createSeededRandom', 'function gaussianSample')
    script = f"""
{random_function}
const first = createSeededRandom(1234);
const second = createSeededRandom(1234);
process.stdout.write(JSON.stringify([
    [first(), first(), first()],
    [second(), second(), second()],
]));
"""
    sequences = run_node(script)

    assert sequences[0] == sequences[1]
    assert 'function simulatePlayoffOdds(completedThrough = null)' in app
    assert 'simulatePlayoffOdds(sim.completedThrough - 1)' in app
    assert 'Math.round((team.odds - priorOdds) * 100)' in app
    assert 'movement vs preseason' in app
    assert 'playoff-odds-movement ${movementClass}' in app
    assert '.playoff-odds-movement.up {' in styles
    assert '.playoff-odds-movement.down {' in styles


def test_playoff_odds_stabilize_early_team_averages_and_explain_the_model():
    app = WEB_APP.read_text(encoding='utf-8')
    html = WEB_INDEX.read_text(encoding='utf-8')
    mean_function = app_slice(
        'function stabilizedPlayoffMean',
        'function simulatePlayoffOdds',
    )
    script = f"""
const PLAYOFF_MEAN_PRIOR_GAMES = 3;
{mean_function}
process.stdout.write(JSON.stringify([
    stabilizedPlayoffMean([150], 100),
    stabilizedPlayoffMean([150, 130], 100),
    stabilizedPlayoffMean([150, 130, 140], 100),
]));
"""

    assert run_node(script) == [112.5, 116, 120]
    assert 'const PLAYOFF_MEAN_PRIOR_GAMES = 3;' in app
    assert 'teamMean[t.abbrev] = stabilizedPlayoffMean(' in app
    assert '<strong>How it works:</strong>' in html
    assert '25% of the forecast after Week 1' in html
    assert 'partial weeks do not count' in html
