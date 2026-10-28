import json

from scripts.score_off_roster_weeks import missing_by_week


def _snapshot(data_dir, week, rosters):
    path = data_dir / 'roster_snapshots' / '2026' / f'week_{week}.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'season': 2026, 'week': week, 'rosters': rosters}))


GESICKI = {'name': 'Mike Gesicki', 'nfl_team': 'CIN', 'position': 'TE'}
BENGALS_DST = {'name': 'Cincinnati Bengals', 'nfl_team': 'CIN', 'position': 'D/ST'}
BENGALS_OL = {'name': 'Cincinnati Bengals', 'nfl_team': 'CIN', 'position': 'OL'}


def test_only_completed_weeks_off_every_roster_are_missing(tmp_path):
    _snapshot(tmp_path, 1, {'RPA': [GESICKI]})
    _snapshot(tmp_path, 2, {'RPA': []})
    _snapshot(tmp_path, 3, {'RPA': []})

    missing = missing_by_week({'GSA': [GESICKI]}, {}, 2026, 2, tmp_path)

    assert missing == {2: [GESICKI]}


def test_scored_weeks_are_not_rescored(tmp_path):
    _snapshot(tmp_path, 1, {})
    cache = {'1': {'mike gesicki|TE': 13.0}}

    assert missing_by_week({'GSA': [GESICKI]}, cache, 2026, 1, tmp_path) == {}


def test_team_units_are_tracked_per_position(tmp_path):
    _snapshot(tmp_path, 1, {'AST': [BENGALS_OL]})

    missing = missing_by_week({'RPA': [BENGALS_DST]}, {}, 2026, 1, tmp_path)

    assert missing == {1: [BENGALS_DST]}


def test_weeks_without_a_roster_snapshot_are_skipped(tmp_path):
    assert missing_by_week({'GSA': [GESICKI]}, {}, 2026, 3, tmp_path) == {}
