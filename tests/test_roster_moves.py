"""Roster moves take effect this week unless a player involved has already played.

A started week's roster is frozen the first time a move lands during it
(api/roster_timing.py), so a move made after a player's game can't erase the
points he already scored. See docs/ARCHITECTURE.md "Roster moves and frozen
week rosters".
"""

import copy
from datetime import datetime, timedelta, timezone

from api import roster_timing
from tests.test_api import FakeRepo, lineup, transaction

SNAPSHOT_3 = roster_timing.roster_snapshot_path(transaction.CURRENT_SEASON, 3)
LINEUPS_3 = f'data/lineups/{transaction.CURRENT_SEASON}/week_3.json'
LINEUPS_4 = f'data/lineups/{transaction.CURRENT_SEASON}/week_4.json'


def _iso(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).isoformat()


def _live(lineup_week=3):
    """Week 3 is under way: KC and LV have kicked off, BUF and MIA haven't."""
    return {
        'current_week': lineup_week,
        'lineup_week': lineup_week,
        'is_offseason': False,
        'game_times': {
            '2': {team: _iso(timedelta(days=-7)) for team in ('KC', 'LV', 'BUF', 'MIA')},
            '3': {
                'KC': _iso(timedelta(hours=-2)),
                'LV': _iso(timedelta(hours=-2)),
                'BUF': _iso(timedelta(days=2)),
                'MIA': _iso(timedelta(days=2)),
            },
            '4': {team: _iso(timedelta(days=7)) for team in ('KC', 'LV', 'BUF', 'MIA')},
        },
    }


def _repo(rosters, **extra_files):
    files = {
        'data/rosters.json': rosters,
        transaction.SITE_LIVE_PATH: _live(),
        **extra_files,
    }
    return FakeRepo(files)


def _names(rosters, team):
    return {player['name'] for player in rosters[team]}


def _release(team='GSA', player='Played RB'):
    return transaction.handle_release(
        {'team': team, 'password': 'pw', 'player_to_release': player, 'week': 3}
    )


GSA_ROSTER = [
    {'name': 'Played RB', 'position': 'RB', 'nfl_team': 'KC'},
    {'name': 'Unplayed RB', 'position': 'RB', 'nfl_team': 'BUF'},
]


def test_release_after_the_player_has_played_takes_effect_next_week(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    lineups = {'week': 3, 'lineups': {'GSA': {'RB': ['Played RB'], 'submitted_at': 'x'}}}
    repo = _repo({'GSA': copy.deepcopy(GSA_ROSTER)}, **{LINEUPS_3: copy.deepcopy(lineups)})
    repo.install(monkeypatch)

    status, body = _release()

    assert status == 200, body
    assert body['deferred'] is True
    assert body['effective_week'] == 4
    assert 'Week 4' in body['message']
    assert _names(repo.files['data/rosters.json'], 'GSA') == {'Unplayed RB'}
    frozen = repo.files[SNAPSHOT_3]
    assert frozen['week'] == 3
    assert _names(frozen['rosters'], 'GSA') == {'Played RB', 'Unplayed RB'}
    # His Week 3 start still counts.
    assert repo.files[LINEUPS_3] == lineups
    log = repo.files['data/transaction_log.json']['transactions'][0]
    assert log['week'] == 4
    assert log['effective_week'] == 4


def test_release_before_the_player_has_played_takes_effect_this_week(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    lineups = {'week': 3, 'lineups': {'GSA': {'RB': ['Unplayed RB'], 'submitted_at': 'x'}}}
    repo = _repo({'GSA': copy.deepcopy(GSA_ROSTER)}, **{LINEUPS_3: lineups})
    repo.install(monkeypatch)

    status, body = _release(player='Unplayed RB')

    assert status == 200, body
    assert body['deferred'] is False
    assert body['effective_week'] == 3
    assert _names(repo.files['data/rosters.json'], 'GSA') == {'Played RB'}
    assert _names(repo.files[SNAPSHOT_3]['rosters'], 'GSA') == {'Played RB'}
    assert repo.files[LINEUPS_3]['lineups']['GSA'] == {'RB': []}


def test_week_roster_is_frozen_once_and_later_moves_keep_it(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    roster = [*copy.deepcopy(GSA_ROSTER), {'name': 'Played WR', 'position': 'WR', 'nfl_team': 'LV'}]
    repo = _repo({'GSA': roster})
    repo.install(monkeypatch)

    assert _release()[0] == 200
    first = copy.deepcopy(repo.files[SNAPSHOT_3])
    assert _release(player='Played WR')[0] == 200

    assert repo.files[SNAPSHOT_3] == first
    assert _names(first['rosters'], 'GSA') == {'Played RB', 'Unplayed RB', 'Played WR'}
    assert _names(repo.files['data/rosters.json'], 'GSA') == {'Unplayed RB'}


def test_move_that_no_longer_fits_the_frozen_roster_waits_a_week(monkeypatch):
    """A player picked up in a deferred move isn't on this week's frozen
    roster, so releasing him can only take effect next week."""
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    frozen = {
        'season': transaction.CURRENT_SEASON,
        'week': 3,
        'frozen_at': 'earlier',
        'rosters': {'GSA': [copy.deepcopy(GSA_ROSTER[0])]},
    }
    repo = _repo({'GSA': copy.deepcopy(GSA_ROSTER)}, **{SNAPSHOT_3: frozen})
    repo.install(monkeypatch)

    status, body = _release(player='Unplayed RB')

    assert status == 200, body
    assert body['deferred'] is True
    assert repo.files[SNAPSHOT_3] == frozen


def test_unknown_nfl_team_is_treated_as_played(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = _repo({'GSA': [{'name': 'Mystery RB', 'position': 'RB', 'nfl_team': 'XXX'}]})
    repo.install(monkeypatch)

    status, body = _release(player='Mystery RB')

    assert status == 200, body
    assert body['deferred'] is True


def test_roster_move_fails_closed_when_game_times_are_unreadable(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = _repo({'GSA': copy.deepcopy(GSA_ROSTER)})
    repo.install(monkeypatch)

    def failing_get(path):
        if path == transaction.SITE_LIVE_PATH:
            raise OSError('GitHub is down')
        return repo.get(path)

    monkeypatch.setattr(transaction, 'github_get_file', failing_get)

    status, body = _release()

    assert status == 503
    assert 'game times' in body['error']
    assert _names(repo.files['data/rosters.json'], 'GSA') == {'Played RB', 'Unplayed RB'}


def test_no_started_week_means_no_snapshot(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = _repo({'GSA': copy.deepcopy(GSA_ROSTER)})
    live = repo.files[transaction.SITE_LIVE_PATH]
    live['game_times'] = {'1': {'KC': _iso(timedelta(days=3))}}
    live['lineup_week'] = 1
    repo.install(monkeypatch)

    status, body = _release()

    assert status == 200, body
    assert body['deferred'] is False
    assert body['effective_week'] == 1
    assert not any(path.startswith('data/roster_snapshots/') for path in repo.files)


def test_taxi_activation_of_a_played_player_takes_effect_next_week(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    roster = [
        {'name': 'Unplayed RB', 'position': 'RB', 'nfl_team': 'BUF'},
        {'name': 'Taxi RB', 'position': 'RB', 'nfl_team': 'KC', 'taxi': True},
    ]
    repo = _repo({'GSA': roster})
    repo.install(monkeypatch)

    status, body = transaction.handle_taxi_activation(
        {
            'team': 'GSA',
            'password': 'pw',
            'player_to_activate': 'Taxi RB',
            'player_to_release': 'Unplayed RB',
            'week': 3,
        }
    )

    assert status == 200, body
    assert body['deferred'] is True
    frozen = repo.files[SNAPSHOT_3]['rosters']['GSA']
    assert {(p['name'], p.get('taxi', False)) for p in frozen} == {
        ('Unplayed RB', False),
        ('Taxi RB', True),
    }


def test_fa_pickup_before_either_player_has_played_takes_effect_this_week(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = _repo(
        {'GSA': [{'name': 'Unplayed RB', 'position': 'RB', 'nfl_team': 'BUF'}]},
        **{'data/fa_pool.json': [{'name': 'FA RB', 'position': 'RB', 'nfl_team': 'MIA'}]},
    )
    repo.install(monkeypatch)

    status, body = transaction.handle_fa_activation(
        {
            'team': 'GSA',
            'password': 'pw',
            'player_to_add': 'FA RB',
            'player_to_release': 'Unplayed RB',
            'week': 3,
        }
    )

    assert status == 200, body
    assert body['deferred'] is False
    assert _names(repo.files[SNAPSHOT_3]['rosters'], 'GSA') == {'FA RB'}
    assert repo.files['data/fa_pool.json'][0]['activated_week'] == 3


def test_release_cancels_pending_trades_that_offered_the_player(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    pending = {
        'trades': [
            {
                'id': 'offer-1',
                'proposer': 'GSA',
                'partner': 'CGK',
                'proposer_gives': {'players': ['Played RB'], 'picks': []},
                'proposer_receives': {'players': [], 'picks': []},
                'status': 'pending',
            }
        ]
    }
    repo = _repo(
        {'GSA': copy.deepcopy(GSA_ROSTER), 'CGK': []},
        **{'data/pending_trades.json': pending},
    )
    repo.install(monkeypatch)

    status, body = _release()

    assert status == 200, body
    assert body['cancelled_trades'] == ['offer-1']
    trade = repo.files['data/pending_trades.json']['trades'][0]
    assert trade['status'] == 'cancelled'
    assert 'GSA released Played RB' in trade['cancelled_reason']


def _trade_files(gsa_team, cgk_team):
    rosters = {
        'GSA': [{'name': 'GSA Player', 'position': 'RB', 'nfl_team': gsa_team}],
        'CGK': [{'name': 'CGK Player', 'position': 'RB', 'nfl_team': cgk_team}],
    }
    pending = {
        'trades': [
            {
                'id': 'trade-1',
                'proposer': 'GSA',
                'partner': 'CGK',
                'proposer_gives': {'players': ['GSA Player'], 'picks': []},
                'proposer_receives': {'players': ['CGK Player'], 'picks': []},
                'status': 'pending',
                'week': 3,
            }
        ]
    }
    lineups = {
        'week': 3,
        'lineups': {
            'GSA': {'RB': ['GSA Player'], 'submitted_at': 'x'},
            'CGK': {'RB': ['CGK Player'], 'submitted_at': 'y'},
        },
    }
    return _repo(
        rosters,
        **{
            'data/pending_trades.json': pending,
            'data/league_config.json': {},
            LINEUPS_3: lineups,
            LINEUPS_4: copy.deepcopy({**lineups, 'week': 4}),
        },
    )


def _accept():
    return transaction.handle_respond_trade(
        {'team': 'CGK', 'password': 'pw', 'trade_id': 'trade-1', 'accept': True}
    )


def test_trade_with_one_played_player_is_deferred_as_a_whole(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_CGK', 'pw')
    repo = _trade_files(gsa_team='KC', cgk_team='BUF')
    lineups_3 = copy.deepcopy(repo.files[LINEUPS_3])
    repo.install(monkeypatch)

    status, body = _accept()

    assert status == 200, body
    assert body['deferred'] is True
    assert body['effective_week'] == 4
    assert _names(repo.files['data/rosters.json'], 'GSA') == {'CGK Player'}
    frozen = repo.files[SNAPSHOT_3]['rosters']
    assert _names(frozen, 'GSA') == {'GSA Player'}
    assert _names(frozen, 'CGK') == {'CGK Player'}
    assert repo.files[LINEUPS_3] == lineups_3
    assert body['invalidated_lineups'] == {'GSA': [4], 'CGK': [4]}
    audit = repo.files['data/transaction_log.json']['transactions'][0]
    assert audit['week'] == 4
    assert repo.files['data/pending_trades.json']['trades'][0]['effective_week'] == 4


def test_trade_before_anyone_has_played_takes_effect_this_week(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_CGK', 'pw')
    repo = _trade_files(gsa_team='BUF', cgk_team='MIA')
    repo.install(monkeypatch)

    status, body = _accept()

    assert status == 200, body
    assert body['deferred'] is False
    frozen = repo.files[SNAPSHOT_3]['rosters']
    assert _names(frozen, 'GSA') == {'CGK Player'}
    assert _names(frozen, 'CGK') == {'GSA Player'}
    assert body['invalidated_lineups'] == {'GSA': [3, 4], 'CGK': [3, 4]}


def test_lineup_for_a_frozen_week_uses_the_frozen_roster(monkeypatch):
    """After a deferred trade, the player a team gave up is still its to start
    this week, and the one it received is not."""
    future = _iso(timedelta(days=2))
    site = {
        'season': lineup.CURRENT_SEASON,
        'current_week': 3,
        'lineup_week': 3,
        'schedule': [{'week': 3, 'matchups': []}],
        'kickoffs': {'BUF': future, 'MIA': future},
    }
    current = {'CGK': [{'name': 'GSA Player', 'position': 'RB', 'nfl_team': 'BUF'}]}
    frozen = {
        'season': lineup.CURRENT_SEASON,
        'week': 3,
        'frozen_at': 'earlier',
        'rosters': {'CGK': [{'name': 'CGK Player', 'position': 'RB', 'nfl_team': 'MIA'}]},
    }
    files = {
        lineup.SITE_META_PATH: site,
        lineup.SITE_LIVE_PATH: site,
        'data/rosters.json': current,
        SNAPSHOT_3: frozen,
    }
    monkeypatch.setattr(lineup, '_github_get_json', lambda path, token, **_kw: files.get(path))

    context, message, _status = lineup.load_lineup_context(3, 'CGK', 'token')

    assert context is not None, message
    assert context.active_roster == {('CGK Player', 'RB')}

    # The next week still validates against the current roster.
    site['schedule'].append({'week': 4, 'matchups': []})
    context, message, _status = lineup.load_lineup_context(4, 'CGK', 'token')
    assert context is not None, message
    assert context.active_roster == {('GSA Player', 'RB')}


def test_started_unlocked_week_boundaries():
    now = datetime(2026, 10, 4, 18, tzinfo=timezone.utc)
    times = {
        4: {'KC': now - timedelta(days=3), 'BUF': now + timedelta(hours=1)},
        5: {'KC': now + timedelta(days=4)},
    }
    assert roster_timing.started_unlocked_week(times, now) == 4
    assert roster_timing.started_unlocked_week(times, now + timedelta(days=5)) == 5
    assert roster_timing.started_unlocked_week(times, now - timedelta(days=4)) is None
    # Week 18 is not a fantasy week: once it kicks off, nothing is unlocked.
    late = {17: {'KC': now}, 18: {'KC': now + timedelta(days=6)}}
    assert roster_timing.started_unlocked_week(late, now + timedelta(days=7)) is None


def test_has_played_handles_aliases():
    now = datetime(2026, 10, 4, 18, tzinfo=timezone.utc)
    timing = roster_timing.resolve_roster_timing(
        {4: {'LA': now - timedelta(hours=1), 'JAX': now + timedelta(hours=1)}}, now
    )
    assert timing.has_played('LAR') is True
    assert timing.has_played('JAC') is False
    assert timing.has_played('') is True
