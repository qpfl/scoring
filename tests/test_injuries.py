import io
import json
from datetime import datetime, timedelta, timezone

from qpfl.injuries import (
    ESPN_INJURIES_URL,
    _flatten_espn_injuries,
    injury_identity_key,
    load_injury_statuses,
    match_injuries,
)


class JsonResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _rosters(*players):
    return {'GSA': list(players)}


def _espn_item(
    name,
    position,
    team,
    status,
    fantasy_status=None,
    return_date=None,
    body_part=None,
    detail='Not Specified',
):
    details = {'detail': detail}
    if fantasy_status:
        details['fantasyStatus'] = {'abbreviation': fantasy_status}
    if return_date:
        details['returnDate'] = return_date
    if body_part:
        details['type'] = body_part
    return {
        'status': status,
        'athlete': {
            'displayName': name,
            'position': {'abbreviation': position},
            'team': {'abbreviation': team},
        },
        'details': details,
    }


def _espn_payload(*items):
    return {'injuries': [{'displayName': 'Team', 'injuries': list(items)}]}


def _records(*items):
    return _flatten_espn_injuries(_espn_payload(*items))


def test_stale_out_from_last_game_uses_the_coming_week_designation():
    targets = [{'name': 'Jalen Coker', 'position': 'WR', 'team': 'CAR'}]
    records = _records(
        _espn_item(
            'Jalen Coker',
            'WR',
            'CAR',
            'Out',
            fantasy_status='QUESTIONABLE',
            return_date='2026-10-04',
            body_part='Quadriceps',
            detail='Strain',
        )
    )

    injuries = match_injuries(targets, records)

    assert injuries[injury_identity_key('Jalen Coker', 'WR')] == {
        'status': 'Questionable',
        'abbreviation': 'Q',
        'body_part': 'Quadriceps',
        'notes': 'Strain',
        'return_date': '2026-10-04',
    }


def test_matches_designations_and_reserve_status_with_suffix_and_team_aliases():
    targets = [
        {'name': 'Patrick Mahomes II', 'position': 'QB', 'team': 'KC'},
        {'name': 'Graham Mertz', 'position': 'QB', 'team': 'HOU'},
        {'name': 'Example Runner Jr.', 'position': 'RB', 'team': 'JAC'},
        {'name': 'Healthy Receiver', 'position': 'WR', 'team': 'WAS'},
        {'name': 'Leg Kicker', 'position': 'K', 'team': 'NYJ'},
    ]
    records = _records(
        _espn_item('Patrick Mahomes', 'QB', 'KC', 'Out', 'OUT', '2026-11-01', 'Knee'),
        _espn_item('Graham Mertz', 'QB', 'HOU', 'Injured Reserve', 'IR', '2026-12-01'),
        _espn_item('Example Runner', 'RB', 'JAX', 'Out', 'PUP-R', '2026-11-15'),
        _espn_item('Healthy Receiver', 'WR', 'WSH', 'Active'),
        _espn_item('Leg Kicker', 'PK', 'NYJ', 'Questionable', 'QUESTIONABLE'),
    )

    injuries = match_injuries(targets, records)

    assert injuries[injury_identity_key('Patrick Mahomes II', 'QB')] == {
        'status': 'Out',
        'abbreviation': 'O',
        'body_part': 'Knee',
        'return_date': '2026-11-01',
    }
    # Reserve lists are open-ended, so no misleading return date.
    assert injuries[injury_identity_key('Graham Mertz', 'QB')] == {
        'status': 'Injured Reserve',
        'abbreviation': 'IR',
    }
    assert injuries[injury_identity_key('Example Runner Jr.', 'RB')]['abbreviation'] == 'PUP'
    assert injury_identity_key('Healthy Receiver', 'WR') not in injuries
    # ESPN calls kickers PK.
    assert injuries[injury_identity_key('Leg Kicker', 'K')]['abbreviation'] == 'Q'


def test_game_day_inactive_only_carries_over_when_he_misses_the_next_game():
    targets = [
        {'name': 'Back Soon', 'position': 'TE', 'team': 'SEA'},
        {'name': 'Still Hurt', 'position': 'TE', 'team': 'LAR'},
    ]
    records = _records(
        _espn_item('Back Soon', 'TE', 'SEA', 'Out', 'INACTIVE', '2026-10-04'),
        _espn_item('Still Hurt', 'TE', 'LA', 'Out', 'INACTIVE', '2026-10-11'),
    )
    # Thursday night kickoff at 8:15 PM ET is already the next day in UTC.
    next_kickoffs = {'SEA': '2026-10-02T00:15:00+00:00', 'LAR': '2026-10-04'}

    injuries = match_injuries(targets, records, next_kickoffs)
    assert injury_identity_key('Back Soon', 'TE') in injuries  # Oct 4 is after the Oct 1 game
    assert injuries[injury_identity_key('Still Hurt', 'TE')]['abbreviation'] == 'O'

    next_kickoffs['SEA'] = '2026-10-04T17:00:00+00:00'
    injuries = match_injuries(targets, records, next_kickoffs)
    assert injury_identity_key('Back Soon', 'TE') not in injuries

    # Without schedule context an inactive is never guessed to be out.
    assert match_injuries(targets, records) == {}


def test_ambiguous_names_are_skipped():
    targets = [{'name': 'Same Name', 'position': 'WR', 'team': 'NYJ'}]
    records = _records(
        _espn_item('Same Name', 'WR', 'DAL', 'Out', 'OUT'),
        _espn_item('Same Name', 'WR', 'MIA', 'Questionable', 'QUESTIONABLE'),
    )

    assert match_injuries(targets, records) == {}


def test_cache_is_reused_within_the_ttl(tmp_path):
    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
    cache_path = tmp_path / 'injury_statuses.json'
    rosters = _rosters(
        {'name': 'Test Player Jr.', 'position': 'WR', 'nfl_team': 'BUF'},
        {'name': 'Buffalo Bills', 'position': 'D/ST', 'nfl_team': 'BUF'},
    )
    response = _espn_payload(
        _espn_item('Test Player', 'WR', 'BUF', 'Doubtful', 'DOUBTFUL', body_part='Hamstring')
    )
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
        now=now + timedelta(hours=2),
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('unexpected fetch')),
    )

    key = injury_identity_key('Test Player Jr.', 'WR')
    assert calls == [(ESPN_INJURIES_URL, 30)]
    assert first == second
    assert second['source'] == 'ESPN'
    assert second['players'][key]['abbreviation'] == 'D'
    assert injury_identity_key('Buffalo Bills', 'D/ST') not in second['players']

    load_injury_statuses(rosters, cache_path, now=now + timedelta(hours=4), opener=opener)
    assert len(calls) == 2


def test_a_cache_from_another_provider_is_refreshed_immediately(tmp_path):
    now = datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
    cache_path = tmp_path / 'injury_statuses.json'
    key = injury_identity_key('Jalen Coker', 'WR')
    cache_path.write_text(
        json.dumps(
            {
                'source': 'Sleeper',
                'updated_at': now.isoformat(),
                'players': {key: {'status': 'Out', 'abbreviation': 'O'}},
            }
        )
    )
    response = _espn_payload(_espn_item('Jalen Coker', 'WR', 'CAR', 'Out', 'QUESTIONABLE'))

    result = load_injury_statuses(
        _rosters({'name': 'Jalen Coker', 'position': 'WR', 'nfl_team': 'CAR'}),
        cache_path,
        now=now + timedelta(minutes=5),
        opener=lambda *_args, **_kwargs: JsonResponse(json.dumps(response).encode()),
    )

    assert result['source'] == 'ESPN'
    assert result['players'][key]['abbreviation'] == 'Q'


def test_refresh_failure_preserves_the_last_good_cache(tmp_path):
    now = datetime(2026, 9, 10, 12, tzinfo=timezone.utc)
    cache_path = tmp_path / 'injury_statuses.json'
    rosters = _rosters({'name': 'Test Player', 'position': 'TE', 'nfl_team': 'SEA'})
    response = _espn_payload(_espn_item('Test Player', 'TE', 'SEA', 'Out', 'OUT'))
    load_injury_statuses(
        rosters,
        cache_path,
        now=now,
        opener=lambda *_args, **_kwargs: JsonResponse(json.dumps(response).encode()),
    )

    for failing_opener in (
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError('offline')),
        lambda *_args, **_kwargs: JsonResponse(b'{"unexpected": true}'),
    ):
        cached = load_injury_statuses(
            rosters, cache_path, now=now + timedelta(days=2), opener=failing_opener
        )
        assert cached['updated_at'] == now.isoformat()
        assert cached['players'][injury_identity_key('Test Player', 'TE')]['abbreviation'] == 'O'
