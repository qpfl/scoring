"""Taxi players can't be activated between Week 7's Thursday night game and Week 8.

The constitution releases any player still on a practice squad at the Thursday
night game the week of the midseason draft, which runs after Week 7's games.
"""

import copy
from datetime import datetime, timedelta, timezone

from api import roster_timing
from tests.test_api import FakeRepo, transaction
from tests.test_trade_roster_moves import MAKE_ROOM, _accept, _rosters, _trade

NOW = datetime(2026, 10, 25, 18, tzinfo=timezone.utc)


def _times(**weeks):
    """{week: hours from NOW of its first kickoff}."""
    return {
        int(week[1:]): {'KC': NOW + timedelta(hours=hours), 'BUF': NOW + timedelta(hours=hours + 3)}
        for week, hours in weeks.items()
    }


def test_frozen_only_from_week_7_kickoff_until_week_8_kickoff():
    frozen = roster_timing.taxi_activation_frozen
    assert not frozen(_times(w7=2, w8=170), NOW)  # before Thursday night
    assert frozen(_times(w7=0, w8=170), NOW)  # Thursday kickoff
    assert frozen(_times(w7=-70, w8=100), NOW)  # Sunday of Week 7, draft pending
    assert not frozen(_times(w7=-170, w8=0), NOW)  # Week 8 under way
    assert not frozen(_times(w6=-70, w7=100), NOW)
    assert not frozen({}, NOW)  # offseason: no game times


def _iso(hours):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _week_7_live():
    teams = ('KC', 'LV', 'BUF', 'MIA')
    return {
        'current_week': 7,
        'lineup_week': 7,
        'is_offseason': False,
        'game_times': {
            '6': {team: _iso(-24 * 7) for team in teams},
            '7': {team: _iso(-70) for team in teams},
            '8': {team: _iso(100) for team in teams},
        },
    }


def test_taxi_activation_is_refused_after_week_7_kickoff(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    rosters = {'GSA': [{'name': 'Taxi RB', 'position': 'RB', 'nfl_team': 'KC', 'taxi': True}]}
    repo = FakeRepo({'data/rosters.json': rosters, transaction.SITE_LIVE_PATH: _week_7_live()})
    repo.install(monkeypatch)
    before = copy.deepcopy(repo.files)

    status, body = transaction.handle_taxi_activation(
        {'team': 'GSA', 'password': 'pw', 'player_to_activate': 'Taxi RB', 'week': 7}
    )

    assert status == 400
    assert 'midseason draft' in body['error']
    assert repo.files == before


def _trade_repo():
    return FakeRepo(
        {
            'data/rosters.json': _rosters(),
            transaction.SITE_LIVE_PATH: _week_7_live(),
            'data/pending_trades.json': {'trades': [_trade()]},
            'data/league_config.json': {},
        }
    )


def test_a_trade_cannot_activate_a_taxi_player_after_week_7_kickoff(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_CGK', 'pw')
    repo = _trade_repo()
    repo.install(monkeypatch)
    before = copy.deepcopy(repo.files)

    status, body = _accept(MAKE_ROOM)

    assert status == 400
    assert 'midseason draft' in body['error']
    assert repo.files == before


def test_a_trade_without_activations_still_goes_through(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_CGK', 'pw')
    repo = _trade_repo()
    repo.install(monkeypatch)

    status, body = _accept({'release': ['CGK RB4', 'CGK Taxi RB'], 'activate': []})

    assert status == 200, body
