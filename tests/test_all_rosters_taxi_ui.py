"""The All Rosters grid must keep taxi-squad players out of the position groups.

Taxi players don't occupy an active roster slot, so listing them inside the
position blocks overstates how deep a team is at that position. They get their
own block at the bottom of the grid instead.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_JS = (PROJECT_ROOT / 'web' / 'app.js').read_text()
STYLES_CSS = (PROJECT_ROOT / 'web' / 'styles.css').read_text()


def test_position_groups_are_built_from_active_players_only():
    assert 'sortRosterByPosition(roster.filter(p => !p.taxi)).forEach(p => {' in APP_JS


def test_taxi_players_are_collected_into_their_own_block():
    assert 'teamTaxiPlayers[abbrev] = sortRosterByPosition(roster.filter(p => p.taxi));' in APP_JS
    assert (
        'const taxiMax = Math.max(0, ...teamAbbrevs.map(a => teamTaxiPlayers[a].length));' in APP_JS
    )


def test_the_taxi_block_renders_last_and_is_labelled():
    # The taxi group is appended after the position groups, not interleaved.
    position_groups = APP_JS.index('const bodyRows = positions.map(pos => groupRowsHtml({')
    taxi_group = APP_JS.index("label: 'Taxi Squad',")
    assert position_groups < taxi_group

    assert "labelClass: 'ar-taxi-label'," in APP_JS
    assert 'rowCount: taxiMax,' in APP_JS
    assert 'playerAt: (abbrev, i) => teamTaxiPlayers[abbrev][i],' in APP_JS


def test_taxi_rows_show_each_players_position():
    """The block mixes positions, so a row can't rely on a position heading."""
    assert 'showPosition: true,' in APP_JS
    assert 'const posTag = showPosition' in APP_JS


def test_the_taxi_label_is_styled_as_a_non_position_heading():
    assert '.all-rosters-table tr.position-group .ar-taxi-label {' in STYLES_CSS
    assert '.all-rosters-table .ar-player-cell .position-tag {' in STYLES_CSS
