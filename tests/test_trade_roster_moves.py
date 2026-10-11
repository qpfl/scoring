"""Trades can carry each side's roster moves (releases and taxi activations).

They run in the same write as the trade and before roster limits are
checked, so an unbalanced trade can make room for itself. See
docs/PLAN_trade_roster_moves.md.
"""

import copy

from qpfl.integrity import check_pending_trades
from tests.test_api import transaction
from tests.test_roster_moves import LINEUPS_3, LINEUPS_4, SNAPSHOT_3, _names, _release, _repo


def _player(name, position, nfl_team, taxi=False):
    return {
        'name': name,
        'position': position,
        'nfl_team': nfl_team,
        **({'taxi': True} if taxi else {}),
    }


def _rosters(gsa_taxi_team='BUF'):
    """CGK's four active RBs fill the position and its taxi RB slot is taken,
    so GSA's incoming taxi RB has nowhere to go without a move."""
    return {
        'GSA': [
            _player('GSA QB', 'QB', 'BUF'),
            _player('GSA Taxi RB', 'RB', gsa_taxi_team, taxi=True),
        ],
        'CGK': [
            _player('CGK QB', 'QB', 'MIA'),
            *(_player(f'CGK RB{i}', 'RB', 'MIA') for i in range(1, 5)),
            _player('CGK Taxi RB', 'RB', 'MIA', taxi=True),
        ],
    }


def _trade(roster_moves=None):
    trade = {
        'id': 'trade-1',
        'proposer': 'GSA',
        'partner': 'CGK',
        'proposer_gives': {'players': ['GSA QB', 'GSA Taxi RB'], 'picks': []},
        'proposer_receives': {'players': ['CGK QB'], 'picks': []},
        'status': 'pending',
        'week': 3,
    }
    if roster_moves:
        trade['roster_moves'] = roster_moves
    return trade


def _files(rosters=None, trade=None):
    lineups = {
        'week': 3,
        'lineups': {'CGK': {'QB': ['CGK QB'], 'RB': ['CGK RB4'], 'submitted_at': 'y'}},
    }
    return _repo(
        rosters or _rosters(),
        **{
            'data/pending_trades.json': {'trades': [trade or _trade()]},
            'data/league_config.json': {},
            LINEUPS_3: lineups,
            LINEUPS_4: copy.deepcopy({**lineups, 'week': 4}),
        },
    )


def _accept(roster_moves=None):
    payload = {'team': 'CGK', 'password': 'pw', 'trade_id': 'trade-1', 'accept': True}
    if roster_moves is not None:
        payload['roster_moves'] = roster_moves
    return transaction.handle_respond_trade(payload)


def _taxi_names(rosters, team):
    return {player['name'] for player in rosters[team] if player.get('taxi')}


MAKE_ROOM = {'release': ['CGK RB4'], 'activate': ['GSA Taxi RB']}


def test_partner_makes_room_for_an_incoming_taxi_player(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_CGK', 'pw')
    repo = _files()
    repo.install(monkeypatch)

    status, body = _accept(MAKE_ROOM)

    assert status == 200, body
    assert body['deferred'] is False
    assert 'CGK released CGK RB4 and activated GSA Taxi RB' in body['message']
    for rosters in (repo.files['data/rosters.json'], repo.files[SNAPSHOT_3]['rosters']):
        assert _names(rosters, 'CGK') == {
            'GSA QB',
            'CGK RB1',
            'CGK RB2',
            'CGK RB3',
            'GSA Taxi RB',
            'CGK Taxi RB',
        }
        assert _taxi_names(rosters, 'CGK') == {'CGK Taxi RB'}
        assert _names(rosters, 'GSA') == {'CGK QB'}
    # The released RB leaves CGK's lineups; so does the traded-away QB.
    assert repo.files[LINEUPS_3]['lineups']['CGK'] == {'QB': [], 'RB': []}
    trade = repo.files['data/pending_trades.json']['trades'][0]
    assert trade['roster_moves'] == {'CGK': MAKE_ROOM}
    audit = repo.files['data/transaction_log.json']['transactions'][0]
    assert [p['name'] for p in audit['roster_moves']['CGK']['released']] == ['CGK RB4']
    assert audit['roster_moves']['CGK']['activated'] == [_player('GSA Taxi RB', 'RB', 'BUF')]


def test_trade_without_room_explains_how_to_fix_it(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_CGK', 'pw')
    repo = _files()
    repo.install(monkeypatch)
    before = copy.deepcopy(repo.files['data/rosters.json'])

    status, body = _accept()

    assert status == 400
    assert 'release or activate players as part of the trade' in body['error']
    assert 'CGK would have 2 taxi RB players' in body['error']
    assert repo.files['data/rosters.json'] == before


def test_releasing_a_taxi_player_makes_taxi_room(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_CGK', 'pw')
    repo = _files()
    repo.install(monkeypatch)

    status, body = _accept({'release': ['CGK Taxi RB']})

    assert status == 200, body
    assert _taxi_names(repo.files['data/rosters.json'], 'CGK') == {'GSA Taxi RB'}


def test_taxi_player_who_stays_on_taxi_does_not_defer_the_trade(monkeypatch):
    """KC has kicked off, but a taxi player can't score, so moving him from
    one taxi squad to another can't change Week 3's points."""
    monkeypatch.setenv('TEAM_PASSWORD_CGK', 'pw')
    repo = _files(rosters=_rosters(gsa_taxi_team='KC'))
    repo.install(monkeypatch)

    status, body = _accept({'release': ['CGK Taxi RB']})

    assert status == 200, body
    assert body['deferred'] is False
    assert body['effective_week'] == 3


def test_activating_a_player_who_has_played_defers_the_trade(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_CGK', 'pw')
    repo = _files(rosters=_rosters(gsa_taxi_team='KC'))
    repo.install(monkeypatch)

    status, body = _accept(MAKE_ROOM)

    assert status == 200, body
    assert body['deferred'] is True
    assert body['effective_week'] == 4
    frozen = repo.files[SNAPSHOT_3]['rosters']
    assert _names(frozen, 'CGK') >= {'CGK QB', 'CGK RB4'}


def test_invalid_roster_moves_are_rejected(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_CGK', 'pw')
    repo = _files()
    repo.install(monkeypatch)
    before = copy.deepcopy(repo.files)

    status, body = _accept({'release': ['CGK QB']})  # being traded away
    assert status == 409
    assert "CGK QB is not on CGK's roster to release" in body['error']
    status, body = _accept({'release': ['Nobody']})
    assert status == 409
    status, body = _accept({'activate': ['CGK RB1']})  # already active
    assert status == 409
    assert "CGK RB1 is not on CGK's taxi squad to activate" in body['error']
    assert _accept({'release': 'CGK RB4'})[0] == 400
    assert _accept({'demote': ['CGK RB4']})[0] == 400
    assert _accept({'release': ['CGK RB4'], 'activate': ['CGK RB4']})[0] == 400
    assert repo.files == before


def test_partner_cannot_overwrite_the_proposers_moves(monkeypatch):
    """Moves stored for any team other than the proposer are dropped; the
    partner's come only from the acceptance."""
    monkeypatch.setenv('TEAM_PASSWORD_CGK', 'pw')
    repo = _files(trade=_trade({'CGK': {'release': ['CGK RB1'], 'activate': []}}))
    repo.install(monkeypatch)

    status, body = _accept(MAKE_ROOM)

    assert status == 200, body
    assert 'CGK RB1' in _names(repo.files['data/rosters.json'], 'CGK')


def _propose(**overrides):
    payload = {
        'team': 'GSA',
        'password': 'pw',
        'trade_partner': 'CGK',
        'give_players': ['GSA QB', 'GSA Taxi RB'],
        'receive_players': ['CGK QB'],
        **overrides,
    }
    return transaction.handle_propose_trade(payload)


def _propose_files(rosters):
    return _repo(
        rosters,
        **{
            transaction.SITE_META_PATH: {'current_week': 3},
            'data/pending_trades.json': {'trades': []},
            'data/league_config.json': {},
        },
    )


def test_proposal_stores_proposer_moves_and_only_checks_proposer_limits(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    rosters = _rosters()
    rosters['GSA'] += [_player(f'GSA QB{i}', 'QB', 'BUF') for i in range(2, 4)]
    repo = _propose_files(rosters)
    repo.install(monkeypatch)

    # GSA already has 3 QBs; taking CGK's QB without giving one makes 4.
    status, body = _propose(give_players=['GSA Taxi RB'], receive_players=['CGK QB'])
    assert status == 400
    assert 'GSA would have 4 QB players' in body['error']
    assert repo.files['data/pending_trades.json'] == {'trades': []}

    # Releasing a QB fixes GSA's side; CGK's taxi collision is CGK's to fix.
    status, body = _propose(
        give_players=['GSA Taxi RB'],
        receive_players=['CGK QB'],
        roster_moves={'release': ['GSA QB3']},
    )
    assert status == 200, body
    stored = repo.files['data/pending_trades.json']['trades'][0]
    assert stored['roster_moves'] == {'GSA': {'release': ['GSA QB3'], 'activate': []}}


def test_proposal_rejects_players_the_proposer_does_not_own(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = _propose_files(_rosters())
    repo.install(monkeypatch)

    status, body = _propose(roster_moves={'release': ['CGK RB1']})

    assert status == 409
    assert "CGK RB1 is not on GSA's roster to release" in body['error']


def test_releasing_a_player_cancels_trades_that_planned_to_release_him(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    rosters = _rosters()
    rosters['GSA'].append(_player('GSA Extra', 'WR', 'BUF'))
    repo = _files(rosters=rosters, trade=_trade({'GSA': {'release': ['GSA Extra']}}))
    repo.install(monkeypatch)

    status, body = _release(team='GSA', player='GSA Extra')

    assert status == 200, body
    assert body['cancelled_trades'] == ['trade-1']


def test_integrity_flags_pending_release_of_unowned_player():
    trade = _trade({'GSA': {'release': ['Gone'], 'activate': []}})
    errors = check_pending_trades({'trades': [trade]}, _rosters())

    assert errors == ["pending trade trade-1: 'GSA' plans to release 'Gone' but does not own it"]
