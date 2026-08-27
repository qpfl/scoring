import io
import json
from datetime import datetime, timedelta, timezone

from qpfl.injuries import injury_identity_key, load_injury_statuses, match_injuries


class JsonResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _rosters(*players):
    return {'GSA': list(players)}


def test_matches_weekly_designations_and_reserve_status_with_suffix_normalization():
    targets = [
        {'name': 'Patrick Mahomes II', 'position': 'QB', 'team': 'KC'},
        {'name': 'Graham Mertz', 'position': 'QB', 'team': 'HOU'},
        {'name': 'Example Runner Jr.', 'position': 'RB', 'team': 'JAC'},
    ]
    sleeper_players = {
        '1': {
            'full_name': 'Patrick Mahomes',
            'position': 'QB',
            'team': 'KC',
            'status': 'Active',
            'injury_status': 'Questionable',
            'injury_body_part': 'Knee',
        },
        '2': {
            'full_name': 'Graham Mertz',
            'position': 'QB',
            'team': 'HOU',
            'status': 'Inactive',
            'injury_status': 'IR',
        },
        '3': {
            'full_name': 'Example Runner',
            'position': 'RB',
            'team': 'JAX',
            'status': 'Injured Reserve',
            'injury_status': None,
        },
    }

    injuries = match_injuries(targets, sleeper_players)

    assert injuries[injury_identity_key('Patrick Mahomes II', 'QB')] == {
        'status': 'Questionable',
        'abbreviation': 'Q',
        'body_part': 'Knee',
    }
    assert injuries[injury_identity_key('Graham Mertz', 'QB')]['abbreviation'] == 'IR'
    assert injuries[injury_identity_key('Example Runner Jr.', 'RB')]['abbreviation'] == 'IR'


def test_daily_cache_avoids_a_second_full_player_download(tmp_path):
    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
    cache_path = tmp_path / 'injury_statuses.json'
    rosters = _rosters(
        {'name': 'Test Player Jr.', 'position': 'WR', 'nfl_team': 'BUF'},
        {'name': 'Buffalo Bills', 'position': 'D/ST', 'nfl_team': 'BUF'},
    )
    response = {
        '1': {
            'full_name': 'Test Player',
            'position': 'WR',
            'team': 'BUF',
            'status': 'Active',
            'injury_status': 'Doubtful',
            'injury_body_part': 'Hamstring',
        }
    }
    calls = []

    def opener(request, timeout):
        calls.append((request.full_url, timeout))
        return JsonResponse(json.dumps(response).encode())

    first = load_injury_statuses(rosters, cache_path, now=now, opener=opener)
    second = load_injury_statuses(
        _rosters(
            {'name': 'Test Player Jr.', 'position': 'WR', 'nfl_team': 'BUF'},
            {'name': 'New Player', 'position': 'RB', 'nfl_team': 'MIA'},
        ),
        cache_path,
        now=now + timedelta(hours=23),
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('unexpected fetch')),
    )

    key = injury_identity_key('Test Player Jr.', 'WR')
    assert calls == [('https://api.sleeper.app/v1/players/nfl', 30)]
    assert first == second
    assert second['players'][key]['abbreviation'] == 'D'
    assert injury_identity_key('Buffalo Bills', 'D/ST') not in second['players']


def test_refresh_failure_preserves_the_last_good_cache(tmp_path):
    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
    cache_path = tmp_path / 'injury_statuses.json'
    rosters = _rosters({'name': 'Test Player', 'position': 'TE', 'nfl_team': 'SEA'})
    response = {
        '1': {
            'full_name': 'Test Player',
            'position': 'TE',
            'team': 'SEA',
            'status': 'Active',
            'injury_status': 'Out',
        }
    }
    load_injury_statuses(
        rosters,
        cache_path,
        now=now,
        opener=lambda *_args, **_kwargs: JsonResponse(json.dumps(response).encode()),
    )

    cached = load_injury_statuses(
        rosters,
        cache_path,
        now=now + timedelta(days=2),
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError('offline')),
    )

    assert cached['updated_at'] == now.isoformat()
    assert cached['players'][injury_identity_key('Test Player', 'TE')]['abbreviation'] == 'O'
