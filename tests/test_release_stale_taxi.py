"""Tests for scripts/release_stale_taxi.py (docs/ROADMAP_2026.md P2.2)."""

import json

from scripts.release_stale_taxi import release_stale_taxi


def _rosters_file(tmp_path):
    path = tmp_path / 'rosters.json'
    path.write_text(
        json.dumps(
            {
                'GSA': [
                    {'name': 'Active RB', 'position': 'RB', 'nfl_team': 'KC'},
                    {'name': 'Taxi WR', 'position': 'WR', 'nfl_team': 'BUF', 'taxi': True},
                ],
                'CGK': [
                    {'name': 'Other Active', 'position': 'QB', 'nfl_team': 'BUF'},
                ],
            }
        )
    )
    return path


def test_releases_taxi_players_from_all_teams(tmp_path):
    path = _rosters_file(tmp_path)

    count = release_stale_taxi(path)

    assert count == 1
    rosters = json.loads(path.read_text())
    gsa_names = {p['name'] for p in rosters['GSA']}
    assert gsa_names == {'Active RB'}
    assert rosters['CGK'] == [{'name': 'Other Active', 'position': 'QB', 'nfl_team': 'BUF'}]


def test_dry_run_does_not_write(tmp_path):
    path = _rosters_file(tmp_path)
    original = path.read_text()

    count = release_stale_taxi(path, dry_run=True)

    assert count == 1
    assert path.read_text() == original


def test_team_filter_only_releases_that_team(tmp_path):
    path2 = tmp_path / 'rosters2.json'
    path2.write_text(
        json.dumps(
            {
                'GSA': [{'name': 'Taxi A', 'position': 'WR', 'nfl_team': 'BUF', 'taxi': True}],
                'CGK': [{'name': 'Taxi B', 'position': 'RB', 'nfl_team': 'MIA', 'taxi': True}],
            }
        )
    )

    release_stale_taxi(path2, team='GSA')

    rosters = json.loads(path2.read_text())
    assert rosters['GSA'] == []
    assert len(rosters['CGK']) == 1


def test_releases_taxi_players_from_nested_format_teams(tmp_path):
    path = tmp_path / 'rosters3.json'
    path.write_text(
        json.dumps(
            {
                'GSA': {
                    'roster': [{'name': 'Active RB', 'position': 'RB', 'nfl_team': 'KC'}],
                    'taxi_squad': [{'name': 'Taxi WR', 'position': 'WR', 'nfl_team': 'BUF'}],
                },
            }
        )
    )

    count = release_stale_taxi(path)

    assert count == 1
    rosters = json.loads(path.read_text())
    assert rosters['GSA']['taxi_squad'] == []
    assert rosters['GSA']['roster'] == [{'name': 'Active RB', 'position': 'RB', 'nfl_team': 'KC'}]
