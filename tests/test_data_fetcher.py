"""Tests for qpfl.data_fetcher.NFLDataFetcher.find_player matching fallbacks
(docs/ROADMAP_2026.md P1.4)."""

import polars as pl

from qpfl.data_fetcher import NFLDataFetcher


def _fetcher(rows: list[dict]) -> NFLDataFetcher:
    fetcher = NFLDataFetcher(2026, 1)
    fetcher._player_stats = pl.DataFrame(rows)
    return fetcher


def test_find_player_matches_team_and_position():
    fetcher = _fetcher(
        [
            {
                'player_display_name': 'Josh Allen',
                'team': 'BUF',
                'position': 'QB',
                'player_id': '1',
            },
            {
                'player_display_name': 'Josh Allen',
                'team': 'JAC',
                'position': 'LB',
                'player_id': '2',
            },
        ]
    )
    result = fetcher.find_player('Josh Allen', 'BUF', 'QB')
    assert result['player_id'] == '1'
    assert '_data_note' not in result


def test_find_player_falls_back_to_position_when_team_is_stale():
    """A traded player whose rosters.json nfl_team is stale must still be
    found by name+position, with a note flagging the mismatch."""
    fetcher = _fetcher(
        [
            {
                'player_display_name': 'Stefon Diggs',
                'team': 'HOU',
                'position': 'WR',
                'player_id': '1',
            },
        ]
    )
    # rosters.json still says PIT (last season's team) - stale.
    result = fetcher.find_player('Stefon Diggs', 'PIT', 'WR')
    assert result is not None
    assert result['player_id'] == '1'
    assert 'PIT' in result['_data_note']
    assert 'HOU' in result['_data_note']


def test_find_player_returns_none_when_nobody_matches():
    fetcher = _fetcher(
        [
            {
                'player_display_name': 'Someone Else',
                'team': 'BUF',
                'position': 'QB',
                'player_id': '1',
            },
        ]
    )
    assert fetcher.find_player('Nonexistent Player', 'BUF', 'QB') is None


def test_find_player_falls_back_when_position_column_absent():
    fetcher = _fetcher(
        [
            {'player_display_name': 'Josh Allen', 'team': 'BUF', 'player_id': '1'},
        ]
    )
    result = fetcher.find_player('Josh Allen', 'BUF', 'QB')
    assert result['player_id'] == '1'
