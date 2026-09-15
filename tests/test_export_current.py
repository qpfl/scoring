"""Tests for scripts/export_current.py schedule handling (docs/ROADMAP_2026.md P0.1)."""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.export_current import (
    add_co_owner_labels,
    build_week_kickoffs,
    enrich_live_roster_context,
    export_current_season,
    write_split_runtime_data,
)

SCHEDULE_TXT = """Week 1: GSA versus WJK, RPA versus S/T, CGK versus AST, CWR versus J/J, SLS versus AYP
Rivalry Week 5: GSA versus RPA, CWR versus CGK, WJK versus J/J, AYP versus AST, S/T versus SLS
"""

TEAMS = {
    'teams': [
        {'abbrev': 'GSA', 'name': 'Team GSA', 'owner': 'A'},
        {'abbrev': 'WJK', 'name': 'Team WJK', 'owner': 'B'},
    ]
}


def test_split_standings_include_last_completed_week_snapshot(tmp_path):
    web_dir = tmp_path / 'web'
    week_dir = web_dir / 'data' / 'seasons' / '2026' / 'weeks'
    week_dir.mkdir(parents=True)
    (week_dir / 'week_1.json').write_text(
        json.dumps(
            {
                'week': 1,
                'has_scores': True,
                'teams': [
                    {'abbrev': 'GSA', 'name': 'Team GSA', 'owner': 'A', 'total_score': 120},
                    {'abbrev': 'WJK', 'name': 'Team WJK', 'owner': 'B', 'total_score': 90},
                ],
                'matchups': [
                    {
                        'team1': {'abbrev': 'GSA', 'total_score': 120},
                        'team2': {'abbrev': 'WJK', 'total_score': 90},
                    }
                ],
            }
        )
    )
    data = {
        **TEAMS,
        'current_week': 2,
        'lineup_week': 2,
        'weeks': [{'week': 1}],
        'standings': [
            {'abbrev': 'WJK', 'name': 'Team WJK', 'wins': 1, 'rank_points': 1.5},
            {'abbrev': 'GSA', 'name': 'Team GSA', 'wins': 1, 'rank_points': 1.0},
        ],
        'hall_of_fame': {'completed_through': {'2026': 1}},
        'updated_at': '2026-09-15T12:00:00Z',
    }

    write_split_runtime_data(data, web_dir, 2026)

    meta = json.loads((week_dir.parent / 'meta.json').read_text())
    payload = json.loads((week_dir.parent / 'standings.json').read_text())
    assert meta['completed_through'] == 1
    assert payload['completed_through'] == 1
    assert payload['standings'][0]['abbrev'] == 'WJK'
    assert [team['abbrev'] for team in payload['completed_standings']] == ['GSA', 'WJK']
    assert payload['completed_standings'][0]['wins'] == 1
    assert payload['completed_standings'][0]['rank_points'] == 1.5


class ScheduleRows:
    def __init__(self, rows):
        self.rows = rows

    def iter_rows(self, named=False):
        assert named is True
        return iter(self.rows)


def test_kickoff_export_ignores_preseason_games():
    rows = [
        {
            'game_type': 'PRE',
            'week': 1,
            'gameday': '2026-08-20',
            'gametime': '20:00',
            'home_team': 'KC',
            'away_team': 'BUF',
        },
        {
            'game_type': 'REG',
            'week': 1,
            'gameday': '2026-09-10',
            'gametime': '20:20',
            'home_team': 'PHI',
            'away_team': 'DAL',
        },
    ]

    with patch('scripts.export_current.nfl.load_schedules', return_value=ScheduleRows(rows)):
        kickoffs = build_week_kickoffs(2026, 1)

    assert set(kickoffs) == {'PHI', 'DAL'}


def test_live_roster_context_includes_opponent_kickoff_and_projection(tmp_path):
    history_root = tmp_path / 'web' / 'data' / 'seasons'
    history_week = history_root / '2025' / 'weeks' / 'week_1.json'
    history_week.parent.mkdir(parents=True)
    history_week.write_text(
        json.dumps(
            {
                'week': 1,
                'teams': [
                    {
                        'abbrev': 'GSA',
                        'roster': [
                            {
                                'name': 'Patrick Mahomes II',
                                'position': 'QB',
                                'nfl_team': 'KC',
                                'score': 10,
                                'starter': True,
                            }
                        ],
                    }
                ],
            }
        )
    )
    rows = [
        {
            'season': 2025,
            'game_type': 'REG',
            'week': 1,
            'gameday': '2025-09-07',
            'gametime': '13:00',
            'home_team': 'KC',
            'away_team': 'LV',
            'result': 'KC 24-17 LV',
        },
        {
            'season': 2026,
            'game_type': 'REG',
            'week': 1,
            'gameday': '2026-09-09',
            'gametime': '20:20',
            'home_team': 'BUF',
            'away_team': 'KC',
            'result': None,
        },
        {
            'season': 2026,
            'game_type': 'REG',
            'week': 2,
            'gameday': '2026-09-14',
            'gametime': '13:00',
            'home_team': 'CHI',
            'away_team': 'MIN',
            'result': None,
        },
    ]
    data = {
        'teams': [{'abbrev': 'GSA', 'name': 'Team GSA', 'owner': 'Griff'}],
        'rosters': {'GSA': [{'name': 'Patrick Mahomes II', 'position': 'QB', 'nfl_team': 'KC'}]},
        'lineups': {'GSA': {'QB': ['Patrick Mahomes II']}},
        'schedule': [],
    }

    kickoffs = enrich_live_roster_context(data, 2026, 1, history_root, rows, roster_rows=[])

    player = data['rosters']['GSA'][0]
    assert kickoffs['KC'] == kickoffs['BUF']
    assert player['nfl_opponent'] == 'BUF'
    assert player['nfl_is_home'] is False
    assert player['kickoff'] == kickoffs['KC']
    assert player['projected_points'] == 10
    assert player['on_bye'] is False
    assert 'unavailable_reason' not in player

    # Full-season schedule maps are rebuilt on every export (not just the active
    # lineup week), so browsing another week never falls back to stale data.
    assert data['game_times']['1']['KC'] == data['game_times']['1']['BUF']
    assert data['game_opponents']['1']['KC'] == {'opponent': 'BUF', 'is_home': False}
    assert data['game_opponents']['2']['CHI'] == {'opponent': 'MIN', 'is_home': True}
    assert data['game_opponents']['2']['MIN'] == {'opponent': 'CHI', 'is_home': False}
    # Prior-season rows (loaded for the projection model) must not leak in.
    assert 'LV' not in data['game_opponents']['1']


def test_live_roster_context_carries_forward_previous_kickoffs_on_schedule_failure(tmp_path):
    """A transient nflverse schedule-load failure must not drop
    kickoffs/game_times/game_opponents outright - api/lineup.py fail-closes
    on an absent `kickoffs` key, locking the whole league out of lineup
    submission on what may be a one-run blip. Carrying forward the previous
    export's values is safe because kickoff times for the active week are
    effectively immutable once published. See docs/ROADMAP_2026.md P3.1 /
    the in-season reliability plan, phase 2.3."""
    history_root = tmp_path / 'web' / 'data' / 'seasons'
    data = {
        'teams': [{'abbrev': 'GSA', 'name': 'Team GSA', 'owner': 'Griff'}],
        'rosters': {'GSA': [{'name': 'Patrick Mahomes II', 'position': 'QB', 'nfl_team': 'KC'}]},
        'lineups': {'GSA': {'QB': ['Patrick Mahomes II']}},
        'schedule': [],
    }
    previous_kickoffs = {'KC': '2026-09-09T20:20:00+00:00', 'BUF': '2026-09-09T20:20:00+00:00'}
    previous_game_times = {'1': {'KC': '2026-09-09T20:20:00+00:00'}}
    previous_game_opponents = {'1': {'KC': {'opponent': 'BUF', 'is_home': False}}}

    def _boom(*_args, **_kwargs):
        raise ConnectionError('nflverse schedule feed unreachable')

    with patch('scripts.export_current.load_projection_schedule_rows', side_effect=_boom):
        kickoffs = enrich_live_roster_context(
            data,
            2026,
            1,
            history_root,
            previous_kickoffs=previous_kickoffs,
            previous_game_times=previous_game_times,
            previous_game_opponents=previous_game_opponents,
        )

    assert kickoffs == previous_kickoffs
    assert data['game_times'] == previous_game_times
    assert data['game_opponents'] == previous_game_opponents


def test_live_roster_context_zeroes_a_player_off_the_active_nfl_roster(tmp_path):
    history_root = tmp_path / 'web' / 'data' / 'seasons'
    history_week = history_root / '2025' / 'weeks' / 'week_1.json'
    history_week.parent.mkdir(parents=True)
    history_week.write_text(
        json.dumps(
            {
                'week': 1,
                'teams': [
                    {
                        'abbrev': 'GSA',
                        'roster': [
                            {
                                'name': 'Patrick Mahomes II',
                                'position': 'QB',
                                'nfl_team': 'KC',
                                'score': 10,
                                'starter': True,
                            }
                        ],
                    }
                ],
            }
        )
    )
    rows = [
        {
            'season': 2026,
            'game_type': 'REG',
            'week': 1,
            'gameday': '2026-09-09',
            'gametime': '20:20',
            'home_team': 'BUF',
            'away_team': 'KC',
            'result': None,
        },
    ]
    data = {
        'teams': [{'abbrev': 'GSA', 'name': 'Team GSA', 'owner': 'Griff'}],
        'rosters': {'GSA': [{'name': 'Patrick Mahomes II', 'position': 'QB', 'nfl_team': 'KC'}]},
        'lineups': {'GSA': {'QB': ['Patrick Mahomes II']}},
        'schedule': [],
    }
    roster_rows = [
        {'full_name': 'Patrick Mahomes', 'position': 'QB', 'team': 'KC', 'status': 'EXE'}
    ]

    enrich_live_roster_context(
        data,
        2026,
        1,
        history_root,
        rows,
        roster_rows=roster_rows,
        now=datetime(2026, 9, 8, tzinfo=timezone.utc),
    )

    player = data['rosters']['GSA'][0]
    assert player['projected_points'] == 0
    assert player['unavailable_reason'] == 'exempt'


def test_cwr_transaction_labels_include_jack_beginning_in_2026():
    assert add_co_owner_labels('Redacted', 'CWR', 2025) == 'Redacted'
    assert add_co_owner_labels('Redacted', 'CWR', 2026) == 'Redacted Reardon & Jack Reardon'
    assert add_co_owner_labels('Connor', 'CWR', 2027) == 'Connor Reardon & Jack Reardon'
    assert add_co_owner_labels('Connor', 'CGK', 2026) == 'Connor'


@pytest.fixture
def fixture_dirs(tmp_path):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    season_source_dir = data_dir / 'seasons' / '2026'
    season_source_dir.mkdir(parents=True)
    web_dir = tmp_path / 'web'
    (web_dir / 'data' / 'seasons' / '2026').mkdir(parents=True)

    (data_dir / 'teams.json').write_text(json.dumps(TEAMS))
    (data_dir / 'league_config.json').write_text(json.dumps({'is_offseason': True}))
    (season_source_dir / 'schedule.txt').write_text(SCHEDULE_TXT)

    meta_path = web_dir / 'data' / 'seasons' / '2026' / 'meta.json'
    meta_path.write_text(json.dumps({'season': 2026, 'schedule': []}))

    return data_dir, web_dir


class TestScheduleFromScheduleTxt:
    def test_commissioner_offseason_mode_keeps_week_one_lineups_open(self, fixture_dirs):
        data_dir, web_dir = fixture_dirs
        lineups_dir = data_dir / 'lineups' / '2026'
        lineups_dir.mkdir(parents=True)
        lineups = {'GSA': {'QB': ['Starter'], 'submitted_at': '2026-09-09T12:00:00Z'}}
        (lineups_dir / 'week_1.json').write_text(json.dumps({'week': 1, 'lineups': lineups}))
        kickoffs = {'KC': '2026-09-11T00:20:00+00:00'}
        with (
            patch('scripts.export_current.get_current_nfl_week', return_value=1),
            patch('scripts.export_current.enrich_live_roster_context', return_value=kickoffs),
        ):
            data = export_current_season(data_dir, web_dir, 2026)
        assert data['is_offseason'] is True
        assert data['current_week'] == 0
        assert data['lineup_week'] == 1
        assert len(data['schedule']) == 5
        assert data['lineups'] == lineups
        assert data['kickoffs'] == kickoffs

        meta = json.loads((web_dir / 'data' / 'seasons' / '2026' / 'meta.json').read_text())
        live = json.loads((web_dir / 'data' / 'seasons' / '2026' / 'live.json').read_text())
        assert meta['lineup_week'] == 1
        assert len(meta['schedule']) == 5
        assert live['lineup_week'] == 1
        assert live['lineups'] == lineups

    def test_fa_pool_is_synced_from_data_fa_pool_json(self, fixture_dirs):
        """data/fa_pool.json is the only thing api/transaction.py writes to, so
        the exporter must read it fresh every run rather than carrying forward
        whatever fa_pool happened to already be in web/data.json (which is
        never `[]` -> populated on its own otherwise)."""
        data_dir, web_dir = fixture_dirs
        fa_pool = [
            {'name': 'Kaleb Johnson', 'nfl_team': 'PIT', 'position': 'RB', 'available': True}
        ]
        (data_dir / 'fa_pool.json').write_text(json.dumps(fa_pool))
        lineups_dir = data_dir / 'lineups' / '2026'
        lineups_dir.mkdir(parents=True)
        (lineups_dir / 'week_1.json').write_text(json.dumps({'week': 1, 'lineups': {}}))

        with (
            patch('scripts.export_current.get_current_nfl_week', return_value=1),
            patch('scripts.export_current.enrich_live_roster_context', return_value={}),
        ):
            data = export_current_season(data_dir, web_dir, 2026)

        assert data['fa_pool'] == fa_pool
        live = json.loads((web_dir / 'data' / 'seasons' / '2026' / 'live.json').read_text())
        assert live['fa_pool'] == fa_pool

    def test_a_stale_provider_season_does_not_close_lineups(self, fixture_dirs):
        """nflreadpy reports the previous season until the new one kicks off.

        In early September 2026 it still returns week 22 of 2025. Letting that
        into current_week puts it outside 1-17, which zeroes lineup_week and
        makes /api/lineup answer "League lineup context is unavailable" for
        every team.
        """
        data_dir, web_dir = fixture_dirs
        (data_dir / 'league_config.json').write_text(json.dumps({'is_offseason': False}))
        lineups_dir = data_dir / 'lineups' / '2026'
        lineups_dir.mkdir(parents=True)
        (lineups_dir / 'week_1.json').write_text(json.dumps({'week': 1, 'lineups': {}}))
        kickoffs = {'KC': '2026-09-11T00:20:00+00:00'}

        with (
            patch('scripts.export_current.nfl.get_current_season', return_value=2025),
            patch('scripts.export_current.nfl.get_current_week', return_value=22),
            patch('scripts.export_current.enrich_live_roster_context', return_value=kickoffs),
        ):
            data = export_current_season(data_dir, web_dir, 2026)

        assert data['current_week'] == 1
        assert data['lineup_week'] == 1
        assert data['kickoffs'] == kickoffs

    def test_write_split_runtime_data_is_idempotent_across_runs(self, fixture_dirs):
        """A run whose content genuinely didn't change must leave every split
        file byte-identical, not just logically equal - otherwise `updated_at`
        alone produces a commit and a redeploy on every run, even a no-op
        one. Regression test for a real bug found while implementing the
        guard: an earlier intermediate meta.json write ran before
        apply_avatars() finished stamping `data['teams']`, so meta.json
        always looked "changed" even when nothing was. See
        docs/ROADMAP_2026.md P3.1 / the in-season reliability plan, phase 3.3.
        """
        data_dir, web_dir = fixture_dirs
        (data_dir / 'league_config.json').write_text(json.dumps({'is_offseason': False}))
        lineups_dir = data_dir / 'lineups' / '2026'
        lineups_dir.mkdir(parents=True)
        (lineups_dir / 'week_1.json').write_text(json.dumps({'week': 1, 'lineups': {}}))

        with (
            patch('scripts.export_current.get_current_nfl_week', return_value=1),
            patch('scripts.export_current.enrich_live_roster_context', return_value={}),
        ):
            export_current_season(data_dir, web_dir, 2026)
            season_dir = web_dir / 'data' / 'seasons' / '2026'
            first_pass = {
                path.name: path.read_bytes() for path in sorted(season_dir.glob('*.json'))
            }

            export_current_season(data_dir, web_dir, 2026)
            second_pass = {
                path.name: path.read_bytes() for path in sorted(season_dir.glob('*.json'))
            }

        assert second_pass == first_pass

    def test_mid_season_provider_failure_keeps_previous_current_week(self, fixture_dirs):
        """A transient nflreadpy failure mid-season (not the pre-season stale-
        provider case above) must fall back to the last committed
        current_week, not reset to 1 and repoint lineup editing at Week 1.
        See docs/ROADMAP_2026.md P3.1 / the in-season reliability plan, phase 2.2.
        """
        data_dir, web_dir = fixture_dirs
        (data_dir / 'league_config.json').write_text(json.dumps({'is_offseason': False}))
        meta_path = web_dir / 'data' / 'seasons' / '2026' / 'meta.json'
        meta_path.write_text(json.dumps({'season': 2026, 'schedule': [], 'current_week': 10}))
        lineups_dir = data_dir / 'lineups' / '2026'
        lineups_dir.mkdir(parents=True)
        (lineups_dir / 'week_10.json').write_text(json.dumps({'week': 10, 'lineups': {}}))

        def _boom(*_args, **_kwargs):
            raise RuntimeError('nflreadpy unreachable')

        with (
            patch('scripts.export_current.nfl.get_current_season', side_effect=_boom),
            patch('scripts.export_current.enrich_live_roster_context', return_value={}),
        ):
            data = export_current_season(data_dir, web_dir, 2026)

        assert data['current_week'] == 10
        assert data['lineup_week'] == 10

    def test_provider_week_is_used_once_it_reports_the_exported_season(self, fixture_dirs):
        data_dir, web_dir = fixture_dirs
        (data_dir / 'league_config.json').write_text(json.dumps({'is_offseason': False}))
        lineups_dir = data_dir / 'lineups' / '2026'
        lineups_dir.mkdir(parents=True)
        (lineups_dir / 'week_4.json').write_text(json.dumps({'week': 4, 'lineups': {}}))

        with (
            patch('scripts.export_current.nfl.get_current_season', return_value=2026),
            patch('scripts.export_current.nfl.get_current_week', return_value=4),
            patch('scripts.export_current.enrich_live_roster_context', return_value={}),
        ):
            data = export_current_season(data_dir, web_dir, 2026)

        assert data['current_week'] == 4
        assert data['lineup_week'] == 4

    def test_in_season_populates_schedule_from_schedule_txt(self, fixture_dirs):
        data_dir, web_dir = fixture_dirs
        (data_dir / 'league_config.json').write_text(json.dumps({'is_offseason': False}))
        lineups_dir = data_dir / 'lineups' / '2026'
        lineups_dir.mkdir(parents=True)
        lineups = {'GSA': {'QB': ['Starter'], 'submitted_at': '2026-09-10T12:00:00Z'}}
        (lineups_dir / 'week_1.json').write_text(json.dumps({'week': 1, 'lineups': lineups}))
        with (
            patch('scripts.export_current.get_current_nfl_week', return_value=1),
            patch('scripts.export_current.enrich_live_roster_context', return_value={}),
        ):
            data = export_current_season(data_dir, web_dir, 2026)
        assert data['is_offseason'] is False
        assert data['current_week'] == 1
        assert data['lineup_week'] == 1
        # parse_schedule_file pads through the highest week number seen (5),
        # so weeks 2-4 appear with empty matchups.
        assert len(data['schedule']) == 5
        week1 = data['schedule'][0]
        assert week1['week'] == 1
        assert week1['is_rivalry'] is False
        assert len(week1['matchups']) == 5
        week5 = data['schedule'][4]
        assert week5['week'] == 5
        assert week5['is_rivalry'] is True
        assert data['lineups'] == lineups

        # meta.json should be kept in sync with the schedule of record.
        meta_path = web_dir / 'data' / 'seasons' / '2026' / 'meta.json'
        meta = json.loads(meta_path.read_text())
        assert meta['schedule'] == data['schedule']
        assert meta['teams'] == data['teams']
        assert meta['current_week'] == 1
        assert meta['is_offseason'] is False

        split_standings = json.loads(
            (web_dir / 'data' / 'seasons' / '2026' / 'standings.json').read_text()
        )
        assert split_standings['standings'] == data.get('standings', [])
        assert split_standings['updated_at'] == data['updated_at']

        live = json.loads((web_dir / 'data' / 'seasons' / '2026' / 'live.json').read_text())
        assert live['current_week'] == 1
        assert live['lineup_week'] == 1
        assert live['lineups'] == lineups
        assert live['is_offseason'] is False
        assert (
            json.loads((web_dir / 'data' / 'seasons' / '2026' / 'rosters.json').read_text()) == {}
        )
        assert (
            json.loads((web_dir / 'data' / 'seasons' / '2026' / 'draft_picks.json').read_text())
            == []
        )

    def test_missing_schedule_does_not_override_commissioner_mode(self, fixture_dirs):
        data_dir, web_dir = fixture_dirs
        (data_dir / 'league_config.json').write_text(json.dumps({'is_offseason': False}))
        (Path(data_dir) / 'seasons' / '2026' / 'schedule.txt').unlink()
        with (
            patch('scripts.export_current.get_current_nfl_week', return_value=4),
            patch('scripts.export_current.enrich_live_roster_context', return_value={}),
        ):
            data = export_current_season(data_dir, web_dir, 2026)
        assert data['is_offseason'] is False
        assert data['current_week'] == 4
        assert data['lineup_week'] == 4
        assert data['schedule'] == []

    def test_offseason_lineup_testing_does_not_require_a_fantasy_schedule(self, fixture_dirs):
        data_dir, web_dir = fixture_dirs
        (data_dir / 'seasons' / '2026' / 'schedule.txt').unlink()
        lineups_dir = data_dir / 'lineups' / '2026'
        lineups_dir.mkdir(parents=True)
        lineups = {'GSA': {'QB': ['Starter'], 'submitted_at': '2026-09-09T12:00:00Z'}}
        (lineups_dir / 'week_1.json').write_text(json.dumps({'week': 1, 'lineups': lineups}))
        kickoffs = {'KC': '2026-09-11T00:20:00+00:00'}

        with (
            patch('scripts.export_current.get_current_nfl_week', return_value=1),
            patch('scripts.export_current.enrich_live_roster_context', return_value=kickoffs),
        ):
            data = export_current_season(data_dir, web_dir, 2026)

        assert data['schedule'] == []
        assert data['current_week'] == 0
        assert data['lineup_week'] == 1
        assert data['lineups'] == lineups
        assert data['kickoffs'] == kickoffs

    def test_offseason_clears_stale_lineups(self, fixture_dirs):
        data_dir, web_dir = fixture_dirs
        (web_dir / 'data.json').write_text(json.dumps({'lineups': {'GSA': {'QB': ['Old']}}}))

        with (
            patch('scripts.export_current.get_current_nfl_week', return_value=1),
            patch('scripts.export_current.enrich_live_roster_context', return_value={}),
        ):
            data = export_current_season(data_dir, web_dir, 2026)

        assert data['lineups'] == {}

    def test_invalid_commissioner_setting_fails_export(self, fixture_dirs):
        data_dir, web_dir = fixture_dirs
        (data_dir / 'league_config.json').write_text(json.dumps({'is_offseason': 'yes'}))

        with pytest.raises(ValueError, match='is_offseason must be true or false'):
            export_current_season(data_dir, web_dir, 2026)
