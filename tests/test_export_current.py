"""Tests for scripts/export_current.py schedule handling (docs/ROADMAP_2026.md P0.1)."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.export_current import add_co_owner_labels, export_current_season

SCHEDULE_TXT = """Week 1: GSA versus WJK, RPA versus S/T, CGK versus AST, CWR versus J/J, SLS versus AYP
Rivalry Week 5: GSA versus RPA, CWR versus CGK, WJK versus J/J, AYP versus AST, S/T versus SLS
"""

TEAMS = {
    'teams': [
        {'abbrev': 'GSA', 'name': 'Team GSA', 'owner': 'A'},
        {'abbrev': 'WJK', 'name': 'Team WJK', 'owner': 'B'},
    ]
}


def test_cwr_transaction_labels_include_jack_beginning_in_2026():
    assert add_co_owner_labels('Redacted', 'CWR', 2025) == 'Redacted'
    assert (
        add_co_owner_labels('Redacted', 'CWR', 2026)
        == 'Redacted Reardon & Jack Reardon'
    )
    assert (
        add_co_owner_labels('Connor', 'CWR', 2027)
        == 'Connor Reardon & Jack Reardon'
    )
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
    def test_offseason_before_kickoff_clears_schedule(self, fixture_dirs):
        data_dir, web_dir = fixture_dirs
        with patch('scripts.export_current.is_before_season_kickoff', return_value=True):
            data = export_current_season(data_dir, web_dir, 2026)
        assert data['is_offseason'] is True
        assert data['current_week'] == 0
        assert data['schedule'] == []

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

    def test_missing_schedule_txt_is_offseason(self, fixture_dirs):
        data_dir, web_dir = fixture_dirs
        (Path(data_dir).parent / 'schedule.txt').unlink()
        with patch('scripts.export_current.is_before_season_kickoff', return_value=False):
            data = export_current_season(data_dir, web_dir, 2026)
        assert data['is_offseason'] is True
        assert data['schedule'] == []

    def test_offseason_clears_stale_lineups(self, fixture_dirs):
        data_dir, web_dir = fixture_dirs
        (web_dir / 'data.json').write_text(json.dumps({'lineups': {'GSA': {'QB': ['Old']}}}))

        with patch('scripts.export_current.is_before_season_kickoff', return_value=True):
            data = export_current_season(data_dir, web_dir, 2026)

        assert data['lineups'] == {}
