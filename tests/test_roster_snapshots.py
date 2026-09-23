"""Frozen week rosters on the scoring side (qpfl/roster_snapshots.py)."""

import json

from qpfl.integrity import check_all
from qpfl.json_scorer import load_rosters
from qpfl.roster_snapshots import roster_snapshot_path, write_roster_snapshot

ROSTERS = {'GSA': [{'name': 'Starter', 'position': 'QB', 'nfl_team': 'KC'}]}


def test_load_rosters_reads_a_frozen_week_roster(tmp_path):
    path = roster_snapshot_path(tmp_path, 2026, 3)
    assert write_roster_snapshot(path, 2026, 3, ROSTERS, '2026-09-27T17:00:00+00:00')

    assert load_rosters(path) == ROSTERS


def test_write_roster_snapshot_never_overwrites(tmp_path):
    path = roster_snapshot_path(tmp_path, 2026, 3)
    write_roster_snapshot(path, 2026, 3, ROSTERS, 'first')

    assert write_roster_snapshot(path, 2026, 3, {'GSA': []}, 'second') is False
    assert json.loads(path.read_text())['frozen_at'] == 'first'


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content))


def test_integrity_checks_a_lineup_against_its_week_roster(tmp_path):
    data_dir = tmp_path / 'data'
    _write(data_dir / 'league_config.json', {'current_season': 2026, 'roster_slots': {}})
    # The starter was traded away after he played; rosters.json has moved on.
    _write(data_dir / 'rosters.json', {'GSA': [], 'CGK': ROSTERS['GSA']})
    _write(
        data_dir / 'lineups' / '2026' / 'week_3.json',
        {'week': 3, 'lineups': {'GSA': {'QB': ['Starter']}}},
    )
    _write(
        tmp_path / 'web' / 'data' / 'seasons' / '2026' / 'meta.json',
        {'season': 2026, 'lineup_week': 4},
    )

    # A past week with no frozen roster is not checked against today's roster.
    assert check_all(data_dir) == []

    write_roster_snapshot(
        roster_snapshot_path(data_dir, 2026, 3), 2026, 3, {'GSA': [], 'CGK': []}, 'x'
    )
    assert check_all(data_dir) == [
        "week 3 lineup[GSA]: starter 'Starter' at QB not found on active roster"
    ]

    (roster_snapshot_path(data_dir, 2026, 3)).unlink()
    write_roster_snapshot(roster_snapshot_path(data_dir, 2026, 3), 2026, 3, ROSTERS, 'x')
    assert check_all(data_dir) == []
