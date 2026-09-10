"""Tests for qpfl.data_fetcher.NFLDataFetcher.find_player matching fallbacks
(docs/ROADMAP_2026.md P1.4) and stat-snapshot archival (docs/DURABILITY_PLAN.md)."""

import nflreadpy as nfl
import polars as pl
import pytest

from qpfl.data_fetcher import (
    NFLDataFetcher,
    SeasonStatsUnavailableError,
    load_snapshot,
    save_snapshot,
    snapshot_path,
)


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


def test_find_player_prefers_own_team_over_cross_team_namesake():
    """A same-team, different-position match must win over a same-position
    match on another team - otherwise a mislabeled position on the roster's
    own player could get silently swapped for a totally different player."""
    fetcher = _fetcher(
        [
            {
                'player_display_name': 'Same Name',
                'team': 'KC',
                'position': 'RB',
                'player_id': 'own-team-wrong-position',
            },
            {
                'player_display_name': 'Same Name',
                'team': 'BUF',
                'position': 'WR',
                'player_id': 'other-team-right-position',
            },
        ]
    )
    result = fetcher.find_player('Same Name', 'KC', 'WR')
    assert result['player_id'] == 'own-team-wrong-position'
    assert '_data_note' in result


def test_find_player_refuses_ambiguous_cross_team_match():
    """Dropping the team filter to catch a stale nfl_team must not silently
    bind to an arbitrary namesake when more than one team-wide match exists -
    that would credit the wrong player's stats instead of returning None."""
    fetcher = _fetcher(
        [
            {
                'player_display_name': 'Same Name',
                'team': 'BUF',
                'position': 'WR',
                'player_id': 'candidate-1',
            },
            {
                'player_display_name': 'Same Name',
                'team': 'MIA',
                'position': 'WR',
                'player_id': 'candidate-2',
            },
        ]
    )
    # rosters.json says KC, which matches neither candidate.
    assert fetcher.find_player('Same Name', 'KC', 'WR') is None


def test_find_player_falls_back_when_position_column_absent():
    fetcher = _fetcher(
        [
            {'player_display_name': 'Josh Allen', 'team': 'BUF', 'player_id': '1'},
        ]
    )
    result = fetcher.find_player('Josh Allen', 'BUF', 'QB')
    assert result['player_id'] == '1'


def _full_fetcher() -> NFLDataFetcher:
    fetcher = NFLDataFetcher(2026, 1)
    fetcher._player_stats = pl.DataFrame(
        [{'player_display_name': 'Josh Allen', 'team': 'BUF', 'position': 'QB', 'player_id': '1'}]
    )
    fetcher._team_stats = pl.DataFrame([{'team': 'BUF', 'def_sacks': 3}])
    fetcher._schedules = pl.DataFrame(
        [{'home_team': 'BUF', 'away_team': 'MIA', 'home_score': 24, 'away_score': 17, 'week': 1}]
    )
    fetcher._pbp = pl.DataFrame([{'posteam': 'BUF', 'touchdown': 1, 'td_player_id': 'x1'}])
    fetcher._players_db = pl.DataFrame(
        [
            {'gsis_id': 'x1', 'position': 'T'},
            {'gsis_id': 'x2', 'position': 'QB'},
        ]
    )
    return fetcher


def test_snapshot_round_trip_reproduces_scoring_inputs():
    original = _full_fetcher()
    snapshot = original.to_snapshot()

    # players_db is pared down to OL positions only in the snapshot.
    assert snapshot['players_db'] == [{'gsis_id': 'x1', 'position': 'T'}]

    rebuilt = NFLDataFetcher.from_snapshot(snapshot, season=2026, week=1)
    assert rebuilt.find_player('Josh Allen', 'BUF', 'QB')['player_id'] == '1'
    assert rebuilt.get_team_stats('BUF')['def_sacks'] == 3
    assert rebuilt.get_game_info('BUF')['team_score'] == 24
    assert rebuilt.get_ol_touchdowns('BUF') == 1


def test_snapshot_gzip_round_trip(tmp_path):
    fetcher = _full_fetcher()
    path = snapshot_path(2026, 1, data_dir=tmp_path)
    save_snapshot(fetcher.to_snapshot(), path)

    assert path.exists()
    loaded = load_snapshot(path)
    rebuilt = NFLDataFetcher.from_snapshot(loaded, season=2026, week=1)
    assert rebuilt.find_player('Josh Allen', 'BUF', 'QB')['player_id'] == '1'


def test_stats_available_false_when_season_not_published(monkeypatch):
    """nflverse only cuts a season's stat files once games have been played, so a
    run between the schedule dropping and Week 1 kickoff 404s. That's an expected
    state: scoring proceeds with nobody found instead of crashing the workflow."""

    def _missing(*args, **kwargs):
        raise ConnectionError(
            'Failed to download https://github.com/nflverse/nflverse-data/releases/'
            'download/stats_player/stats_player_week_2026.parquet: '
            '404 Client Error: Not Found'
        )

    monkeypatch.setattr(nfl, 'load_player_stats', _missing)
    monkeypatch.setattr(nfl, 'load_team_stats', _missing)
    monkeypatch.setattr(nfl, 'load_pbp', _missing)

    fetcher = NFLDataFetcher(2026, 1)

    assert fetcher.stats_available is False
    assert fetcher.find_player('Josh Allen', 'BUF', 'QB') is None
    assert fetcher.get_team_stats('BUF') is None
    assert fetcher.get_ol_touchdowns('BUF') == 0
    assert fetcher.get_defensive_sacks('BUF') == {
        'aggregated': 0,
        'pbp': 0,
        'value': 0,
        'discrepancy': False,
    }
    assert fetcher.get_turnovers_returned_for_td('1') == {'pick_sixes': 0, 'fumble_sixes': 0}
    assert fetcher.get_extra_fumbles_lost('1', {}) == 0

    # Nothing worth archiving - and archiving zeros would poison a later re-score.
    with pytest.raises(SeasonStatsUnavailableError):
        fetcher.to_snapshot()


def test_real_download_failure_still_raises(monkeypatch):
    """A genuine outage must not be mistaken for an unpublished season."""

    def _outage(*args, **kwargs):
        raise ConnectionError('Failed to download ...: 503 Server Error')

    monkeypatch.setattr(nfl, 'load_player_stats', _outage)

    with pytest.raises(ConnectionError):
        _ = NFLDataFetcher(2026, 1).stats_available
