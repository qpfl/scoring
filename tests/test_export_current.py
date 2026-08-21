"""Tests for scripts/export_current.py schedule handling (docs/ROADMAP_2026.md P0.1)."""

import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.export_current import (
    add_co_owner_labels,
    build_week_kickoffs,
    export_current_season,
    is_before_season_kickoff,
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


class ScheduleRows:
    def __init__(self, rows):
        self.rows = rows

    def iter_rows(self, named=False):
        assert named is True
        return iter(self.rows)


def test_preseason_games_do_not_open_or_lock_regular_season_lineups():
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    rows = [
        {
            'game_type': 'PRE',
            'week': 1,
            'gameday': yesterday,
            'gametime': '20:00',
            'home_team': 'KC',
            'away_team': 'BUF',
        },
        {
            'game_type': 'REG',
            'week': 1,
            'gameday': tomorrow,
            'gametime': '20:20',
            'home_team': 'PHI',
            'away_team': 'DAL',
        },
    ]

    with patch('scripts.export_current.nfl.load_schedules', return_value=ScheduleRows(rows)):
        assert is_before_season_kickoff(2026) is True
        kickoffs = build_week_kickoffs(2026, 1)

    assert set(kickoffs) == {'PHI', 'DAL'}


def test_cwr_transaction_labels_include_jack_beginning_in_2026():
    assert add_co_owner_labels('Redacted', 'CWR', 2025) == 'Redacted'
    assert add_co_owner_labels('Redacted', 'CWR', 2026) == 'Redacted Reardon & Jack Reardon'
    assert add_co_owner_labels('Connor', 'CWR', 2027) == 'Connor Reardon & Jack Reardon'
    assert add_co_owner_labels('Connor', 'CGK', 2026) == 'Connor'


@pytest.fixture
def fixture_dirs(tmp_path):
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    web_dir = tmp_path / 'web'
    (web_dir / 'data' / 'seasons' / '2026').mkdir(parents=True)

    (data_dir / 'teams.json').write_text(json.dumps(TEAMS))
    (tmp_path / 'schedule.txt').write_text(SCHEDULE_TXT)

    meta_path = web_dir / 'data' / 'seasons' / '2026' / 'meta.json'
    meta_path.write_text(json.dumps({'season': 2026, 'schedule': []}))

    return data_dir, web_dir


class TestScheduleFromScheduleTxt:
    def test_week_one_lineups_open_before_kickoff_while_home_stays_offseason(self, fixture_dirs):
        data_dir, web_dir = fixture_dirs
        lineups_dir = data_dir / 'lineups' / '2026'
        lineups_dir.mkdir(parents=True)
        lineups = {'GSA': {'QB': ['Starter'], 'submitted_at': '2026-09-09T12:00:00Z'}}
        (lineups_dir / 'week_1.json').write_text(json.dumps({'week': 1, 'lineups': lineups}))
        kickoffs = {'KC': '2026-09-11T00:20:00+00:00'}
        with (
            patch('scripts.export_current.is_before_season_kickoff', return_value=True),
            patch('scripts.export_current.get_current_nfl_week', return_value=1),
            patch('scripts.export_current.build_week_kickoffs', return_value=kickoffs),
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

    def test_in_season_populates_schedule_from_schedule_txt(self, fixture_dirs):
        data_dir, web_dir = fixture_dirs
        lineups_dir = data_dir / 'lineups' / '2026'
        lineups_dir.mkdir(parents=True)
        lineups = {'GSA': {'QB': ['Starter'], 'submitted_at': '2026-09-10T12:00:00Z'}}
        (lineups_dir / 'week_1.json').write_text(json.dumps({'week': 1, 'lineups': lineups}))
        with (
            patch('scripts.export_current.is_before_season_kickoff', return_value=False),
            patch('scripts.export_current.get_current_nfl_week', return_value=1),
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

    def test_missing_schedule_txt_is_offseason(self, fixture_dirs):
        data_dir, web_dir = fixture_dirs
        (Path(data_dir).parent / 'schedule.txt').unlink()
        with patch('scripts.export_current.is_before_season_kickoff', return_value=False):
            data = export_current_season(data_dir, web_dir, 2026)
        assert data['is_offseason'] is True
        assert data['lineup_week'] == 0
        assert data['schedule'] == []

    def test_offseason_clears_stale_lineups(self, fixture_dirs):
        data_dir, web_dir = fixture_dirs
        (web_dir / 'data.json').write_text(json.dumps({'lineups': {'GSA': {'QB': ['Old']}}}))

        with patch('scripts.export_current.is_before_season_kickoff', return_value=True):
            data = export_current_season(data_dir, web_dir, 2026)

        assert data['lineups'] == {}
