"""Tests for the Vercel serverless API handlers (api/transaction.py, api/lineup.py).

These handlers carry the league's highest-risk logic (roster mutation, trades,
lineup writes) but live outside the importable `qpfl` package, so they're loaded
here directly from their file paths. The GitHub contents API is faked with an
in-memory repo — nothing in this module touches the network.
"""

import base64
import copy
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

import pytest
from openpyxl import load_workbook

API_DIR = Path(__file__).resolve().parent.parent / 'api'


def _load(module_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(module_name, API_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


transaction = _load('qpfl_api_transaction', 'transaction.py')
lineup = _load('qpfl_api_lineup', 'lineup.py')


# --------------------------------------------------------------------------- #
# Fake GitHub repo with optimistic-concurrency (SHA) semantics
# --------------------------------------------------------------------------- #
class FakeRepo:
    """In-memory stand-in for the GitHub contents API.

    Enforces SHA matching on PUT (mismatch -> 409), so it exercises the
    optimistic read-modify-write retry loop. `on_put` is a one-shot hook that
    fires just before a PUT is applied — use it to simulate a concurrent writer
    committing in between this request's GET and PUT.
    """

    def __init__(self, files: dict):
        self.files = {p: copy.deepcopy(c) for p, c in files.items()}
        self.shas = {p: f'sha-{p}-0' for p in self.files}
        self.counter = dict.fromkeys(self.files, 0)
        self.put_log = []
        self.on_put = None

    def get(self, path):
        if path in self.files:
            return self.shas[path], copy.deepcopy(self.files[path])
        return None, None

    def put(self, path, content, message, sha):
        if self.on_put is not None:
            hook, self.on_put = self.on_put, None
            hook(self)
        current = self.shas.get(path)
        if current is not None and sha != current:
            raise HTTPError(path, 409, 'Conflict', {}, None)
        self.counter[path] = self.counter.get(path, 0) + 1
        self.shas[path] = f'sha-{path}-{self.counter[path]}'
        self.files[path] = copy.deepcopy(content)
        self.put_log.append((path, copy.deepcopy(content)))

    def install(self, monkeypatch):
        monkeypatch.setattr(transaction, 'github_get_file', self.get)
        monkeypatch.setattr(transaction, 'github_put_file', self.put)
        # Don't actually sleep between conflict retries.
        monkeypatch.setattr(transaction.time, 'sleep', lambda *_: None)


class _FakeResponse:
    def __init__(self, status=200, body=b'{}'):
        self.status = status
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# --------------------------------------------------------------------------- #
# Password validation
# --------------------------------------------------------------------------- #
def test_validate_team_accepts_correct_password(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'secret')
    ok, _ = transaction.validate_team('GSA', 'secret')
    assert ok is True


def test_validate_team_rejects_wrong_password(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'secret')
    ok, msg = transaction.validate_team('GSA', 'nope')
    assert ok is False
    assert msg == 'Invalid password'


def test_team_password_handles_slash_abbrev(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_S_T', 'pw')
    assert transaction.get_team_password('S/T') == 'pw'


# --------------------------------------------------------------------------- #
# Lineup season path (regression: was hardcoded to 2025)
# --------------------------------------------------------------------------- #
def test_lineup_writes_to_current_season_dir(monkeypatch):
    captured = {}

    def fake_urlopen(req):
        if req.get_method() == 'GET':
            raise HTTPError(req.full_url, 404, 'Not Found', {}, None)
        captured['put_url'] = req.full_url
        return _FakeResponse(status=200)

    monkeypatch.setattr(lineup.urllib.request, 'urlopen', fake_urlopen)

    ok, _, _ = lineup.update_lineup_file(
        week=3, team='GSA', starters={'QB': ['Josh Allen']}, github_token='t'
    )
    assert ok is True
    assert f'data/lineups/{lineup.CURRENT_SEASON}/week_3.json' in captured['put_url']
    assert 'data/lineups/2025/' not in captured['put_url']


# --------------------------------------------------------------------------- #
# Free-agent activation (regression: API expected a {"players": [...]} wrapper
# but the file + website use a flat list)
# --------------------------------------------------------------------------- #
def test_fa_activation_handles_list_shaped_pool(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = FakeRepo(
        {
            'data/fa_pool.json': [
                {'name': 'Backup RB', 'position': 'RB', 'nfl_team': 'KC', 'available': True}
            ],
            'data/rosters.json': {'GSA': [{'name': 'Old RB', 'position': 'RB', 'nfl_team': 'NYJ'}]},
        }
    )
    repo.install(monkeypatch)

    status, body = transaction.handle_fa_activation(
        {
            'team': 'GSA',
            'password': 'pw',
            'player_to_add': 'Backup RB',
            'player_to_release': 'Old RB',
            'week': 2,
        }
    )

    assert status == 200, body
    names = {p['name'] for p in repo.files['data/rosters.json']['GSA']}
    assert 'Backup RB' in names
    assert 'Old RB' not in names
    assert repo.files['data/fa_pool.json'][0]['available'] is False


def test_fa_activation_accepts_week_zero_offseason_move(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = FakeRepo(
        {
            'data/fa_pool.json': [
                {'name': 'New RB', 'position': 'RB', 'nfl_team': 'KC', 'available': True}
            ],
            'data/rosters.json': {'GSA': [{'name': 'Old RB', 'position': 'RB', 'nfl_team': 'NYJ'}]},
        }
    )
    repo.install(monkeypatch)

    status, body = transaction.handle_fa_activation(
        {
            'team': 'GSA',
            'password': 'pw',
            'player_to_add': 'New RB',
            'player_to_release': 'Old RB',
            'week': 0,
        }
    )

    assert status == 200, body
    assert {p['name'] for p in repo.files['data/rosters.json']['GSA']} == {'New RB'}
    assert repo.files['data/transaction_log.json']['transactions'][0]['week'] == 'Offseason'


def test_fa_activation_rolls_back_claim_if_release_invalid(monkeypatch):
    # If the release player isn't on the roster, the FA claim must be reverted
    # so the player isn't stranded as unavailable.
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = FakeRepo(
        {
            'data/fa_pool.json': [
                {'name': 'Backup RB', 'position': 'RB', 'nfl_team': 'KC', 'available': True}
            ],
            'data/rosters.json': {
                'GSA': [{'name': 'Real RB', 'position': 'RB', 'nfl_team': 'NYJ'}]
            },
        }
    )
    repo.install(monkeypatch)

    status, body = transaction.handle_fa_activation(
        {
            'team': 'GSA',
            'password': 'pw',
            'player_to_add': 'Backup RB',
            'player_to_release': 'Ghost RB',  # not on roster
            'week': 2,
        }
    )

    assert status == 400
    assert repo.files['data/fa_pool.json'][0]['available'] is True
    assert 'activated_by' not in repo.files['data/fa_pool.json'][0]


# --------------------------------------------------------------------------- #
# Standalone release (no add required, no restrictions)
# --------------------------------------------------------------------------- #
def test_release_removes_player_from_roster(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = FakeRepo(
        {
            'data/rosters.json': {
                'GSA': [
                    {'name': 'Old RB', 'position': 'RB', 'nfl_team': 'NYJ'},
                    {'name': 'Keep WR', 'position': 'WR', 'nfl_team': 'KC'},
                ]
            },
        }
    )
    repo.install(monkeypatch)

    status, body = transaction.handle_release(
        {'team': 'GSA', 'password': 'pw', 'player_to_release': 'Old RB', 'week': 5}
    )

    assert status == 200, body
    names = {p['name'] for p in repo.files['data/rosters.json']['GSA']}
    assert 'Old RB' not in names
    assert 'Keep WR' in names

    log = repo.files['data/transaction_log.json']['transactions']
    assert log[0]['type'] == 'release'
    assert log[0]['team'] == 'GSA'
    assert log[0]['released']['name'] == 'Old RB'


def test_release_accepts_week_zero_offseason_release(monkeypatch):
    """week=0 means "offseason" (see is_offseason in handle_release) and must
    not be rejected as a missing field just because 0 is falsy - the frontend
    sends exactly this during the offseason (web/app.js current_week)."""
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = FakeRepo(
        {'data/rosters.json': {'GSA': [{'name': 'Old RB', 'position': 'RB', 'nfl_team': 'NYJ'}]}}
    )
    repo.install(monkeypatch)

    status, body = transaction.handle_release(
        {'team': 'GSA', 'password': 'pw', 'player_to_release': 'Old RB', 'week': 0}
    )

    assert status == 200, body
    names = {p['name'] for p in repo.files['data/rosters.json']['GSA']}
    assert 'Old RB' not in names


def test_taxi_activation_accepts_week_zero_offseason_move(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = FakeRepo(
        {
            'data/rosters.json': {
                'GSA': [
                    {'name': 'Old RB', 'position': 'RB', 'nfl_team': 'NYJ'},
                    {'name': 'Taxi RB', 'position': 'RB', 'nfl_team': 'KC', 'taxi': True},
                ]
            }
        }
    )
    repo.install(monkeypatch)

    status, body = transaction.handle_taxi_activation(
        {
            'team': 'GSA',
            'password': 'pw',
            'player_to_activate': 'Taxi RB',
            'player_to_release': 'Old RB',
            'week': 0,
        }
    )

    assert status == 200, body
    roster = repo.files['data/rosters.json']['GSA']
    assert {p['name'] for p in roster} == {'Taxi RB'}
    assert roster[0].get('taxi') is not True
    assert repo.files['data/transaction_log.json']['transactions'][0]['week'] == 'Offseason'


def test_release_rejects_player_not_on_roster(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = FakeRepo(
        {'data/rosters.json': {'GSA': [{'name': 'Real RB', 'position': 'RB', 'nfl_team': 'NYJ'}]}}
    )
    repo.install(monkeypatch)

    status, body = transaction.handle_release(
        {'team': 'GSA', 'password': 'pw', 'player_to_release': 'Ghost RB', 'week': 5}
    )

    assert status == 400
    names = {p['name'] for p in repo.files['data/rosters.json']['GSA']}
    assert 'Real RB' in names


def test_release_rejects_bad_password(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = FakeRepo(
        {'data/rosters.json': {'GSA': [{'name': 'Real RB', 'position': 'RB', 'nfl_team': 'NYJ'}]}}
    )
    repo.install(monkeypatch)

    status, body = transaction.handle_release(
        {'team': 'GSA', 'password': 'wrong', 'player_to_release': 'Real RB', 'week': 5}
    )

    assert status == 401
    names = {p['name'] for p in repo.files['data/rosters.json']['GSA']}
    assert 'Real RB' in names


# --------------------------------------------------------------------------- #
# Depth chart (within-position display order in data/rosters.json)
# --------------------------------------------------------------------------- #
def _depth_repo():
    return FakeRepo(
        {
            'data/rosters.json': {
                'GSA': [
                    {'name': 'QB One', 'position': 'QB', 'nfl_team': 'BUF'},
                    {'name': 'RB A', 'position': 'RB', 'nfl_team': 'SF'},
                    {'name': 'RB B', 'position': 'RB', 'nfl_team': 'NYJ'},
                    {'name': 'RB C', 'position': 'RB', 'nfl_team': 'KC'},
                    {'name': 'WR A', 'position': 'WR', 'nfl_team': 'MIN'},
                    {'name': 'Taxi RB', 'position': 'RB', 'nfl_team': 'DEN', 'taxi': True},
                ]
            }
        }
    )


def _names(repo, team='GSA'):
    return [p['name'] for p in repo.files['data/rosters.json'][team]]


def test_set_depth_chart_reorders_within_position(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = _depth_repo()
    repo.install(monkeypatch)

    status, body = transaction.handle_set_depth_chart(
        {'team': 'GSA', 'password': 'pw', 'order': {'RB': ['RB C', 'RB A', 'RB B']}}
    )

    assert status == 200, body
    # RBs reordered; every other player keeps his slot, and the taxi RB is
    # untouched by an active-roster reorder.
    assert _names(repo) == ['QB One', 'RB C', 'RB A', 'RB B', 'WR A', 'Taxi RB']
    assert repo.files['data/rosters.json']['GSA'][-1]['taxi'] is True


def test_set_depth_chart_leaves_untouched_positions_alone(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = _depth_repo()
    repo.install(monkeypatch)

    status, _ = transaction.handle_set_depth_chart(
        {'team': 'GSA', 'password': 'pw', 'order': {'RB': ['RB B', 'RB A', 'RB C']}}
    )

    assert status == 200
    assert _names(repo)[0] == 'QB One'
    assert _names(repo)[4] == 'WR A'


def test_set_depth_chart_rejects_stale_roster(monkeypatch):
    """A client whose page predates a trade must not be able to add, drop, or
    duplicate a player by sending a mismatched order list."""
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = _depth_repo()
    repo.install(monkeypatch)
    before = _names(repo)

    for bad_order in (
        {'RB': ['RB A', 'RB B']},  # dropped RB C
        {'RB': ['RB A', 'RB B', 'RB C', 'RB D']},  # added someone
        {'RB': ['RB A', 'RB A', 'RB B']},  # duplicate
        {'RB': ['RB A', 'RB B', 'Taxi RB']},  # taxi player smuggled in
    ):
        status, body = transaction.handle_set_depth_chart(
            {'team': 'GSA', 'password': 'pw', 'order': bad_order}
        )
        assert status == 400, bad_order
        assert _names(repo) == before


def test_set_depth_chart_rejects_bad_position_and_password(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = _depth_repo()
    repo.install(monkeypatch)
    before = _names(repo)

    status, _ = transaction.handle_set_depth_chart(
        {'team': 'GSA', 'password': 'pw', 'order': {'PK': ['RB A']}}
    )
    assert status == 400

    status, _ = transaction.handle_set_depth_chart(
        {'team': 'GSA', 'password': 'wrong', 'order': {'RB': ['RB C', 'RB A', 'RB B']}}
    )
    assert status == 401
    assert _names(repo) == before


def test_set_depth_chart_merges_with_concurrent_roster_change(monkeypatch):
    """A release committed between this request's GET and PUT must survive the
    409 retry - and if it removed a player named in the order, the reorder is
    rejected rather than resurrecting him."""
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = _depth_repo()
    repo.install(monkeypatch)

    def concurrent_release(r):
        roster = r.files['data/rosters.json']['GSA']
        r.files['data/rosters.json']['GSA'] = [p for p in roster if p['name'] != 'RB B']
        r.shas['data/rosters.json'] = 'sha-concurrent'

    repo.on_put = concurrent_release

    status, body = transaction.handle_set_depth_chart(
        {'team': 'GSA', 'password': 'pw', 'order': {'RB': ['RB C', 'RB A', 'RB B']}}
    )

    assert status == 400, body
    assert 'RB B' not in _names(repo)

    # Reordering what's actually left still works.
    status, body = transaction.handle_set_depth_chart(
        {'team': 'GSA', 'password': 'pw', 'order': {'RB': ['RB C', 'RB A']}}
    )
    assert status == 200, body
    assert _names(repo) == ['QB One', 'RB C', 'RB A', 'WR A', 'Taxi RB']


# --------------------------------------------------------------------------- #
# Trade execution / ownership validation
# --------------------------------------------------------------------------- #
def _trade_repo():
    return FakeRepo(
        {
            'data/rosters.json': {
                'GSA': [{'name': 'Player X', 'position': 'RB', 'nfl_team': 'KC'}],
                'CGK': [{'name': 'Player Y', 'position': 'WR', 'nfl_team': 'BUF'}],
            }
        }
    )


def _simple_trade():
    return {
        'proposer': 'GSA',
        'partner': 'CGK',
        'proposer_gives': {'players': ['Player X'], 'picks': []},
        'proposer_receives': {'players': ['Player Y'], 'picks': []},
    }


def test_execute_trade_swaps_players(monkeypatch):
    repo = _trade_repo()
    repo.install(monkeypatch)

    ok, msg, _ = transaction.execute_trade(_simple_trade())

    assert ok is True, msg
    gsa = {p['name'] for p in repo.files['data/rosters.json']['GSA']}
    cgk = {p['name'] for p in repo.files['data/rosters.json']['CGK']}
    assert gsa == {'Player Y'}
    assert cgk == {'Player X'}


def test_execute_trade_transfers_picks_with_draft_type_suffix(monkeypatch):
    """web/app.js builds pick IDs as `{year}[-{draft_type}]-R{round}-{team}`,
    e.g. '2028-offseason_taxi-R1-CWR' for a non-default draft_type. A trade
    for such a pick previously crashed mid-execution (int('offseason_taxi')),
    after the player swap had already committed - see incident where trade
    e59b0a77 left players swapped but picks/finalization stuck."""
    repo = FakeRepo(
        {
            'data/rosters.json': {
                'GSA': [{'name': 'Player X', 'position': 'RB', 'nfl_team': 'KC'}],
                'CGK': [{'name': 'Player Y', 'position': 'WR', 'nfl_team': 'BUF'}],
            },
            'data/draft_picks.json': {
                'picks': [
                    {
                        'year': '2028',
                        'round': 1,
                        'draft_type': 'offseason_taxi',
                        'original_team': 'GSA',
                        'current_owner': 'GSA',
                        'previous_owners': [],
                    },
                    # Same year/round/team but a different draft_type - must not
                    # be picked up instead of the taxi pick above.
                    {
                        'year': '2028',
                        'round': 1,
                        'draft_type': 'offseason',
                        'original_team': 'GSA',
                        'current_owner': 'GSA',
                        'previous_owners': [],
                    },
                ]
            },
        }
    )
    repo.install(monkeypatch)

    trade = {
        'proposer': 'GSA',
        'partner': 'CGK',
        'proposer_gives': {'players': ['Player X'], 'picks': ['2028-offseason_taxi-R1-GSA']},
        'proposer_receives': {'players': ['Player Y'], 'picks': []},
    }

    ok, msg, _ = transaction.execute_trade(trade)

    assert ok is True, msg
    picks = repo.files['data/draft_picks.json']['picks']
    taxi_pick = next(p for p in picks if p['draft_type'] == 'offseason_taxi')
    offseason_pick = next(p for p in picks if p['draft_type'] == 'offseason')
    assert taxi_pick['current_owner'] == 'CGK'
    assert offseason_pick['current_owner'] == 'GSA'  # untouched


def test_execute_trade_rejects_roster_overflow(monkeypatch):
    """P1.1: a trade that would push a position over ROSTER_SLOTS must be
    rejected, not silently create an oversized roster."""
    repo = FakeRepo(
        {
            'data/rosters.json': {
                # GSA already has 4 RBs (the max) and would receive a 5th.
                'GSA': [
                    {'name': 'RB1', 'position': 'RB', 'nfl_team': 'KC'},
                    {'name': 'RB2', 'position': 'RB', 'nfl_team': 'BAL'},
                    {'name': 'RB3', 'position': 'RB', 'nfl_team': 'SF'},
                    {'name': 'RB4', 'position': 'RB', 'nfl_team': 'DAL'},
                    {'name': 'Give Away WR', 'position': 'WR', 'nfl_team': 'MIA'},
                ],
                'CGK': [{'name': 'Incoming RB', 'position': 'RB', 'nfl_team': 'BUF'}],
            }
        }
    )
    repo.install(monkeypatch)

    trade = {
        'proposer': 'GSA',
        'partner': 'CGK',
        'proposer_gives': {'players': ['Give Away WR'], 'picks': []},
        'proposer_receives': {'players': ['Incoming RB'], 'picks': []},
    }

    ok, msg, _ = transaction.execute_trade(trade)

    assert ok is False
    assert 'RB' in msg
    # Nothing was written.
    assert repo.put_log == []


# --------------------------------------------------------------------------- #
# Admin actions (docs/ROADMAP_2026.md P2.3)
# --------------------------------------------------------------------------- #
def test_admin_adjust_rejects_non_commissioner_team(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_CGK', 'pw')
    status, body = transaction.handle_admin_adjust(
        {'team': 'CGK', 'password': 'pw', 'admin_action': 'release'}
    )
    assert status == 403


def test_admin_adjust_accepts_gsa_commissioner_login(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = FakeRepo(
        {
            'data/rosters.json': {'GSA': [{'name': 'Bad Add', 'position': 'RB', 'nfl_team': 'KC'}]},
            'data/transaction_log.json': {'transactions': []},
        }
    )
    repo.install(monkeypatch)

    status, body = transaction.handle_admin_adjust(
        {
            'team': 'GSA',
            'password': 'pw',
            'admin_action': 'release',
            'target_team': 'GSA',
            'player': 'Bad Add',
            'reason': 'Correcting a duplicate add',
        }
    )

    assert status == 200, body
    entry = repo.files['data/transaction_log.json']['transactions'][0]
    assert entry['actor'] == 'GSA'
    assert entry['reason'] == 'Correcting a duplicate add'


def test_admin_adjust_release_removes_player_and_logs(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_ADMIN', 'adminpw')
    repo = FakeRepo(
        {
            'data/rosters.json': {'GSA': [{'name': 'Bad Add', 'position': 'RB', 'nfl_team': 'KC'}]},
            'data/transaction_log.json': {'transactions': []},
        }
    )
    repo.install(monkeypatch)

    status, body = transaction.handle_admin_adjust(
        {
            'team': 'ADMIN',
            'password': 'adminpw',
            'admin_action': 'release',
            'target_team': 'GSA',
            'player': 'Bad Add',
        }
    )

    assert status == 200, body
    assert repo.files['data/rosters.json']['GSA'] == []
    log = repo.files['data/transaction_log.json']['transactions']
    assert log[0]['admin'] is True
    assert log[0]['type'] == 'admin_release'


def test_admin_adjust_add_player_to_roster(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_ADMIN', 'adminpw')
    repo = FakeRepo(
        {
            'data/rosters.json': {'GSA': []},
            'data/transaction_log.json': {'transactions': []},
        }
    )
    repo.install(monkeypatch)

    status, body = transaction.handle_admin_adjust(
        {
            'team': 'ADMIN',
            'password': 'adminpw',
            'admin_action': 'add',
            'target_team': 'GSA',
            'player': {'name': 'Corrected Player', 'position': 'RB', 'nfl_team': 'KC'},
        }
    )

    assert status == 200, body
    names = {p['name'] for p in repo.files['data/rosters.json']['GSA']}
    assert 'Corrected Player' in names


def test_admin_adjust_reverses_completed_legacy_trade_and_logs(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_ADMIN', 'adminpw')
    repo = FakeRepo(
        {
            'data/rosters.json': {
                'GSA': [{'name': 'Player Y', 'position': 'WR', 'nfl_team': 'BUF'}],
                'CGK': [{'name': 'Player X', 'position': 'RB', 'nfl_team': 'KC'}],
            },
            'data/draft_picks.json': {
                'picks': [
                    {
                        'year': '2027',
                        'round': 1,
                        'draft_type': 'offseason',
                        'original_team': 'GSA',
                        'current_owner': 'CGK',
                        'previous_owners': ['GSA'],
                    }
                ]
            },
            'data/pending_trades.json': {
                'trades': [
                    {
                        'id': 'trade-1',
                        'proposer': 'GSA',
                        'partner': 'CGK',
                        'status': 'accepted',
                        'proposer_gives': {
                            'players': ['Player X'],
                            'picks': ['2027-R1-GSA'],
                        },
                        'proposer_receives': {'players': ['Player Y'], 'picks': []},
                    }
                ]
            },
            'data/transaction_log.json': {'transactions': []},
        }
    )
    repo.install(monkeypatch)

    status, body = transaction.handle_admin_adjust(
        {
            'team': 'ADMIN',
            'password': 'adminpw',
            'admin_action': 'reverse_trade',
            'trade_id': 'trade-1',
            'reason': 'Original trade was recorded incorrectly',
        }
    )

    assert status == 200, body
    assert {player['name'] for player in repo.files['data/rosters.json']['GSA']} == {'Player X'}
    assert {player['name'] for player in repo.files['data/rosters.json']['CGK']} == {'Player Y'}
    assert repo.files['data/draft_picks.json']['picks'][0]['current_owner'] == 'GSA'
    trade = repo.files['data/pending_trades.json']['trades'][0]
    assert trade['status'] == 'accepted'
    assert trade['reversal_execution'] == 'done'
    assert trade['reversed_by'] == 'ADMIN'
    assert trade['reversal_reason'] == 'Original trade was recorded incorrectly'
    audit = repo.files['data/transaction_log.json']['transactions'][0]
    assert audit['type'] == 'admin_reverse_trade'
    assert audit['trade_id'] == 'trade-1'


def test_admin_adjust_does_not_expose_or_reverse_pending_trade(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    pending_trade = {
        'id': 'trade-1',
        'proposer': 'GSA',
        'partner': 'CGK',
        'status': 'pending',
        'proposer_gives': {'players': [], 'picks': []},
        'proposer_receives': {'players': [], 'picks': []},
    }
    repo = FakeRepo({'data/pending_trades.json': {'trades': [pending_trade]}})
    repo.install(monkeypatch)

    status, body = transaction.handle_admin_adjust(
        {
            'team': 'GSA',
            'password': 'pw',
            'admin_action': 'reverse_trade',
            'trade_id': 'trade-1',
            'reason': 'Should not be allowed',
        }
    )

    assert status == 400
    assert body['error'] == 'Only completed trades can be reversed'
    assert repo.put_log == []


def test_admin_trade_reversal_aborts_if_assets_changed_hands(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = FakeRepo(
        {
            'data/rosters.json': {
                'GSA': [],
                'CGK': [{'name': 'Someone Else', 'position': 'RB', 'nfl_team': 'KC'}],
            },
            'data/pending_trades.json': {
                'trades': [
                    {
                        'id': 'trade-1',
                        'proposer': 'GSA',
                        'partner': 'CGK',
                        'status': 'accepted',
                        'execution': 'done',
                        'proposer_gives': {'players': ['Player X'], 'picks': []},
                        'proposer_receives': {'players': [], 'picks': []},
                    }
                ]
            },
        }
    )
    repo.install(monkeypatch)

    status, body = transaction.handle_admin_adjust(
        {
            'team': 'GSA',
            'password': 'pw',
            'admin_action': 'reverse_trade',
            'trade_id': 'trade-1',
            'reason': 'Correction',
        }
    )

    assert status == 409
    assert 'roster has changed' in body['error']
    assert repo.files['data/rosters.json']['CGK'][0]['name'] == 'Someone Else'
    trade = repo.files['data/pending_trades.json']['trades'][0]
    assert 'reversal_execution' not in trade
    assert 'reversal_token' not in trade
    assert 'last_reversal_error' in trade


def test_admin_trade_reversal_checks_picks_before_moving_players(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = FakeRepo(
        {
            'data/rosters.json': {
                'GSA': [{'name': 'Player Y', 'position': 'WR', 'nfl_team': 'BUF'}],
                'CGK': [{'name': 'Player X', 'position': 'RB', 'nfl_team': 'KC'}],
            },
            'data/draft_picks.json': {
                'picks': [
                    {
                        'year': '2027',
                        'round': 1,
                        'draft_type': 'offseason',
                        'original_team': 'GSA',
                        'current_owner': 'AYP',
                        'previous_owners': ['GSA', 'CGK'],
                    }
                ]
            },
            'data/pending_trades.json': {
                'trades': [
                    {
                        'id': 'trade-1',
                        'proposer': 'GSA',
                        'partner': 'CGK',
                        'status': 'accepted',
                        'execution': 'done',
                        'proposer_gives': {
                            'players': ['Player X'],
                            'picks': ['2027-R1-GSA'],
                        },
                        'proposer_receives': {'players': ['Player Y'], 'picks': []},
                    }
                ]
            },
        }
    )
    repo.install(monkeypatch)

    status, body = transaction.handle_admin_adjust(
        {
            'team': 'GSA',
            'password': 'pw',
            'admin_action': 'reverse_trade',
            'trade_id': 'trade-1',
            'reason': 'Correction',
        }
    )

    assert status == 409
    assert 'pick has changed hands' in body['error']
    assert {player['name'] for player in repo.files['data/rosters.json']['GSA']} == {'Player Y'}
    assert {player['name'] for player in repo.files['data/rosters.json']['CGK']} == {'Player X'}


def test_admin_conditional_picks_reads_only_unresolved_source_picks(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    unresolved = {
        'year': '2027',
        'round': 1,
        'draft_type': 'offseason',
        'original_team': 'CWR',
        'current_owner': 'J/J',
        'previous_owners': ['CWR'],
        'condition': 'S/T receives the earlier first-round pick',
        'conditional_claim': 'S/T',
    }
    resolved = {
        'year': '2026',
        'round': 2,
        'draft_type': 'offseason',
        'original_team': 'SLS',
        'current_owner': 'AYP',
        'previous_owners': ['SLS', 'S/T'],
    }
    repo = FakeRepo(
        {
            'data/draft_picks.json': {
                'updated_at': '2026-08-24T00:00:00+00:00',
                'picks': [resolved, unresolved],
            }
        }
    )
    repo.install(monkeypatch)

    status, body = transaction.handle_admin_adjust(
        {
            'team': 'GSA',
            'password': 'pw',
            'admin_action': 'conditional_picks',
        }
    )

    assert status == 200
    assert body == {'success': True, 'picks': [unresolved]}
    assert repo.put_log == []


def test_admin_resolves_conditional_pick_and_logs_context(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    condition = 'AYP receives the earlier of the SLS and S/T second-round picks'
    repo = FakeRepo(
        {
            'data/draft_picks.json': {
                'updated_at': '2026-01-01T00:00:00+00:00',
                'picks': [
                    {
                        'year': '2026',
                        'round': 2,
                        'draft_type': 'offseason',
                        'original_team': 'SLS',
                        'current_owner': 'S/T',
                        'previous_owners': ['SLS'],
                        'condition': condition,
                        'conditional_claim': 'AYP',
                    },
                    {
                        'year': '2026',
                        'round': 2,
                        'draft_type': 'offseason',
                        'original_team': 'S/T',
                        'current_owner': 'S/T',
                        'previous_owners': [],
                        'condition': condition,
                        'conditional_claim': 'AYP',
                    },
                ],
            },
            'data/transaction_log.json': {'transactions': []},
        }
    )
    repo.install(monkeypatch)

    status, body = transaction.handle_admin_adjust(
        {
            'team': 'GSA',
            'password': 'pw',
            'admin_action': 'resolve_conditional_pick',
            'condition': condition,
            'winning_pick_id': '2026-R2-SLS',
            'final_owner': 'AYP',
            'reason': 'SLS finished ahead of S/T, making its pick 2.07',
        }
    )

    assert status == 200, body
    picks = repo.files['data/draft_picks.json']['picks']
    sls_pick = next(pick for pick in picks if pick['original_team'] == 'SLS')
    st_pick = next(pick for pick in picks if pick['original_team'] == 'S/T')
    assert sls_pick['current_owner'] == 'AYP'
    assert sls_pick['previous_owners'] == ['SLS', 'S/T']
    assert st_pick['current_owner'] == 'S/T'
    assert all('condition' not in pick for pick in picks)
    assert all('conditional_claim' not in pick for pick in picks)
    assert repo.files['data/draft_picks.json']['updated_at'] != '2026-01-01T00:00:00+00:00'
    assert len(body['resolved_picks']) == 2

    audit = repo.files['data/transaction_log.json']['transactions'][0]
    assert audit['type'] == 'admin_resolve_conditional_pick'
    assert audit['condition'] == condition
    assert audit['winning_pick_id'] == '2026-R2-SLS'
    assert audit['final_owner'] == 'AYP'
    assert audit['reason'] == 'SLS finished ahead of S/T, making its pick 2.07'


def test_admin_conditional_resolution_rejects_pick_outside_condition(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    condition = 'S/T receives the earlier of two first-round picks'
    repo = FakeRepo(
        {
            'data/draft_picks.json': {
                'updated_at': '2026-01-01T00:00:00+00:00',
                'picks': [
                    {
                        'year': '2027',
                        'round': 1,
                        'draft_type': 'offseason',
                        'original_team': 'CWR',
                        'current_owner': 'J/J',
                        'previous_owners': ['CWR'],
                        'condition': condition,
                        'conditional_claim': 'S/T',
                    }
                ],
            }
        }
    )
    repo.install(monkeypatch)

    status, body = transaction.handle_admin_adjust(
        {
            'team': 'GSA',
            'password': 'pw',
            'admin_action': 'resolve_conditional_pick',
            'condition': condition,
            'winning_pick_id': '2027-R1-J/J',
            'final_owner': 'S/T',
            'reason': 'Attempted resolution',
        }
    )

    assert status == 400
    assert body['error'] == 'Winning pick is not a candidate for this condition'
    assert repo.put_log == []


def test_admin_conditional_resolution_rejects_completed_retry(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = FakeRepo(
        {
            'data/draft_picks.json': {
                'updated_at': '2026-01-01T00:00:00+00:00',
                'picks': [
                    {
                        'year': '2026',
                        'round': 2,
                        'draft_type': 'offseason',
                        'original_team': 'SLS',
                        'current_owner': 'AYP',
                        'previous_owners': ['SLS', 'S/T'],
                    }
                ],
            }
        }
    )
    repo.install(monkeypatch)

    status, body = transaction.handle_admin_adjust(
        {
            'team': 'GSA',
            'password': 'pw',
            'admin_action': 'resolve_conditional_pick',
            'condition': 'Already resolved condition',
            'winning_pick_id': '2026-R2-SLS',
            'final_owner': 'AYP',
            'reason': 'Duplicate submission',
        }
    )

    assert status == 409
    assert 'already been resolved' in body['error']
    assert repo.put_log == []


def test_admin_score_adjustment_appends_and_logs(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = FakeRepo(
        {
            'data/score_adjustments.json': [],
            'data/transaction_log.json': {'transactions': []},
        }
    )
    repo.install(monkeypatch)

    status, body = transaction.handle_admin_adjust(
        {
            'team': 'GSA',
            'password': 'pw',
            'admin_action': 'score_adjustment',
            'target_team': 'CGK',
            'season': 2026,
            'week': 5,
            'player': 'Josh Allen',
            'points': -2.5,
            'reason': 'Official stat correction',
        }
    )

    assert status == 200, body
    assert repo.files['data/score_adjustments.json'] == [
        {
            'season': 2026,
            'week': 5,
            'team': 'CGK',
            'player': 'Josh Allen',
            'points': -2.5,
            'reason': 'Official stat correction',
        }
    ]
    audit = repo.files['data/transaction_log.json']['transactions'][0]
    assert audit['type'] == 'admin_score_adjustment'
    assert audit['actor'] == 'GSA'


def test_admin_score_adjustment_rejects_identical_retry(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    adjustment = {
        'season': 2026,
        'week': 5,
        'team': 'CGK',
        'player': 'Josh Allen',
        'points': -2.5,
        'reason': 'Official stat correction',
    }
    repo = FakeRepo({'data/score_adjustments.json': [adjustment]})
    repo.install(monkeypatch)

    status, body = transaction.handle_admin_adjust(
        {
            'team': 'GSA',
            'password': 'pw',
            'admin_action': 'score_adjustment',
            'target_team': 'CGK',
            'season': 2026,
            'week': 5,
            'player': 'Josh Allen',
            'points': -2.5,
            'reason': 'Official stat correction',
        }
    )

    assert status == 409
    assert 'already exists' in body['error']
    assert repo.put_log == []


def test_admin_audit_log_is_protected_and_filters_regular_transactions(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = FakeRepo(
        {
            'data/transaction_log.json': {
                'transactions': [
                    {'type': 'admin_release', 'admin': True, 'timestamp': 'new'},
                    {'type': 'release', 'team': 'CGK', 'timestamp': 'regular'},
                ]
            }
        }
    )
    repo.install(monkeypatch)

    status, body = transaction.handle_admin_adjust(
        {'team': 'GSA', 'password': 'pw', 'admin_action': 'audit_log'}
    )

    assert status == 200
    assert body['entries'] == [{'type': 'admin_release', 'admin': True, 'timestamp': 'new'}]


def test_admin_roster_download_is_protected_fresh_and_read_only(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = FakeRepo(
        {
            'data/rosters.json': {
                'GSA': [
                    {'name': 'Fresh Player', 'position': 'QB', 'nfl_team': 'KC'},
                ]
            },
            'data/teams.json': {
                'teams': [
                    {
                        'abbrev': 'GSA',
                        'name': 'No Kings Except Henry',
                        'owner': 'Griffin Ansel',
                    }
                ]
            },
        }
    )
    repo.install(monkeypatch)

    status, body = transaction.handle_admin_adjust(
        {
            'team': 'GSA',
            'password': 'pw',
            'admin_action': 'download_rosters',
        }
    )

    assert status == 200, body
    assert body['filename'] == 'Rosters_current.xlsx'
    workbook = load_workbook(BytesIO(base64.b64decode(body['content_base64'])))
    sheet = workbook['Rosters']
    assert sheet['A7'].value == 'Fresh Player (KC)'
    workbook.close()
    assert repo.put_log == []


def test_execute_trade_preserves_taxi_status(monkeypatch):
    """P1.1: a taxi player traded away must land on the receiving team's taxi
    squad, not get silently activated."""
    repo = FakeRepo(
        {
            'data/rosters.json': {
                'GSA': [{'name': 'Active RB', 'position': 'RB', 'nfl_team': 'KC'}],
                'CGK': [
                    {'name': 'Taxi WR', 'position': 'WR', 'nfl_team': 'BUF', 'taxi': True},
                ],
            }
        }
    )
    repo.install(monkeypatch)

    trade = {
        'proposer': 'GSA',
        'partner': 'CGK',
        'proposer_gives': {'players': ['Active RB'], 'picks': []},
        'proposer_receives': {'players': ['Taxi WR'], 'picks': []},
    }

    ok, msg, _ = transaction.execute_trade(trade)

    assert ok is True, msg
    gsa = repo.files['data/rosters.json']['GSA']
    taxi_wr = next(p for p in gsa if p['name'] == 'Taxi WR')
    assert taxi_wr.get('taxi') is True


def test_execute_trade_aborts_when_player_no_longer_owned(monkeypatch):
    repo = _trade_repo()
    repo.files['data/rosters.json']['GSA'] = [
        {'name': 'Someone Else', 'position': 'RB', 'nfl_team': 'KC'}
    ]
    repo.install(monkeypatch)

    ok, msg, _ = transaction.execute_trade(_simple_trade())

    assert ok is False
    assert 'roster has changed' in msg
    # Nothing was written — the trade did not partially execute.
    assert repo.put_log == []


# --------------------------------------------------------------------------- #
# Trade deadline fails closed on ambiguity (docs/ROADMAP_2026.md P1.5)
# --------------------------------------------------------------------------- #
def _propose_trade_payload():
    return {
        'team': 'GSA',
        'password': 'pw',
        'trade_partner': 'CGK',
        'give_players': ['Player X'],
        'receive_players': ['Player Y'],
    }


def test_propose_trade_fails_closed_when_data_json_unreadable(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')

    def broken_get_file(path):
        raise RuntimeError('GitHub API down')

    monkeypatch.setattr(transaction, 'github_get_file', broken_get_file)

    status, body = transaction.handle_propose_trade(_propose_trade_payload())

    assert status == 503
    assert 'error' in body


def test_propose_trade_allows_when_before_deadline(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = FakeRepo(
        {'web/data.json': {'current_week': 3}, 'data/pending_trades.json': {'trades': []}}
    )
    repo.install(monkeypatch)

    status, body = transaction.handle_propose_trade(_propose_trade_payload())

    assert status == 200, body


def test_propose_trade_blocks_during_deadline_period(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = FakeRepo(
        {'web/data.json': {'current_week': 12}, 'data/pending_trades.json': {'trades': []}}
    )
    repo.install(monkeypatch)

    status, body = transaction.handle_propose_trade(_propose_trade_payload())

    assert status == 400
    assert 'deadline' in body['error'].lower()


# --------------------------------------------------------------------------- #
# Trade accept atomicity (docs/ROADMAP_2026.md P0.6)
# --------------------------------------------------------------------------- #
def _pending_trade_repo(extra_rosters=None, week=5):
    rosters = {
        'GSA': [{'name': 'Player X', 'position': 'RB', 'nfl_team': 'KC'}],
        'CGK': [{'name': 'Player Y', 'position': 'WR', 'nfl_team': 'BUF'}],
    }
    if extra_rosters:
        rosters.update(extra_rosters)
    return FakeRepo(
        {
            'data/rosters.json': rosters,
            'data/pending_trades.json': {
                'trades': [
                    {
                        'id': 'trade-1',
                        'proposer': 'GSA',
                        'partner': 'CGK',
                        'status': 'pending',
                        'week': week,
                        'proposer_gives': {'players': ['Player X'], 'picks': []},
                        'proposer_receives': {'players': ['Player Y'], 'picks': []},
                    }
                ]
            },
            'data/transaction_log.json': {'transactions': []},
        }
    )


def test_trade_accept_swaps_rosters_and_marks_execution_done(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_CGK', 'pw')
    repo = _pending_trade_repo()
    repo.install(monkeypatch)

    status, body = transaction.handle_respond_trade(
        {'team': 'CGK', 'password': 'pw', 'trade_id': 'trade-1', 'accept': True}
    )

    assert status == 200, body
    gsa = {p['name'] for p in repo.files['data/rosters.json']['GSA']}
    cgk = {p['name'] for p in repo.files['data/rosters.json']['CGK']}
    assert gsa == {'Player Y'}
    assert cgk == {'Player X'}

    trade = repo.files['data/pending_trades.json']['trades'][0]
    assert trade['status'] == 'accepted'
    assert trade['execution'] == 'done'


def test_trade_accept_reverts_to_pending_when_execution_fails(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_CGK', 'pw')
    repo = _pending_trade_repo()
    # Player X was traded away/dropped before the partner accepted.
    repo.files['data/rosters.json']['GSA'] = [
        {'name': 'Someone Else', 'position': 'RB', 'nfl_team': 'KC'}
    ]
    repo.install(monkeypatch)

    status, body = transaction.handle_respond_trade(
        {'team': 'CGK', 'password': 'pw', 'trade_id': 'trade-1', 'accept': True}
    )

    assert status == 409
    # Rosters were never touched.
    gsa = {p['name'] for p in repo.files['data/rosters.json']['GSA']}
    assert gsa == {'Someone Else'}

    trade = repo.files['data/pending_trades.json']['trades'][0]
    # Reverted to pending (not stuck as accepted with unswapped rosters), so
    # the partner can retry once the trade is fixed/re-proposed.
    assert trade['status'] == 'pending'
    assert 'execution' not in trade
    assert 'roster has changed' in trade['last_execution_error']


def test_trade_accept_race_only_one_side_wins(monkeypatch):
    """A second concurrent accept must not also execute (no double-swap)."""
    monkeypatch.setenv('TEAM_PASSWORD_CGK', 'pw')
    repo = _pending_trade_repo()
    repo.install(monkeypatch)

    # Simulate another request winning the accept race right as this request's
    # gate-write goes out: it already flipped the trade to accepted.
    def concurrent_accept(r):
        trades = r.files['data/pending_trades.json']['trades']
        trades[0]['status'] = 'accepted'
        trades[0]['execution'] = 'done'
        r.counter['data/pending_trades.json'] += 1
        r.shas['data/pending_trades.json'] = (
            f'sha-data/pending_trades.json-{r.counter["data/pending_trades.json"]}'
        )

    repo.on_put = concurrent_accept

    status, body = transaction.handle_respond_trade(
        {'team': 'CGK', 'password': 'pw', 'trade_id': 'trade-1', 'accept': True}
    )

    # This request's gate write conflicts, retries against fresh content, and
    # sees the trade is no longer pending -> it must not execute a second swap.
    assert status == 400
    assert 'already' in body['error']
    # Rosters were never touched by this (losing) request.
    gsa = {p['name'] for p in repo.files['data/rosters.json']['GSA']}
    cgk = {p['name'] for p in repo.files['data/rosters.json']['CGK']}
    assert gsa == {'Player X'}
    assert cgk == {'Player Y'}


# --------------------------------------------------------------------------- #
# Optimistic concurrency: a concurrent write to a DIFFERENT team must survive
# (the old code re-sent stale content on 409 and clobbered it)
# --------------------------------------------------------------------------- #
def test_roster_write_preserves_concurrent_change_to_other_team(monkeypatch):
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = FakeRepo(
        {
            'data/rosters.json': {
                'GSA': [
                    {'name': 'Old RB', 'position': 'RB', 'nfl_team': 'NYJ'},
                ],
                'GSA_taxi_marker': [],
                'CGK': [{'name': 'CGK Starter', 'position': 'WR', 'nfl_team': 'BUF'}],
            },
            'data/fa_pool.json': [
                {'name': 'New RB', 'position': 'RB', 'nfl_team': 'KC', 'available': True}
            ],
        }
    )
    repo.install(monkeypatch)

    # Simulate CGK committing a roster change between this request's GET and PUT.
    def concurrent_cgk_change(r):
        rosters = r.files['data/rosters.json']
        rosters['CGK'] = [{'name': 'CGK NEW GUY', 'position': 'WR', 'nfl_team': 'MIA'}]
        r.counter['data/rosters.json'] += 1
        r.shas['data/rosters.json'] = f'sha-data/rosters.json-{r.counter["data/rosters.json"]}'

    repo.on_put = concurrent_cgk_change

    status, body = transaction.handle_fa_activation(
        {
            'team': 'GSA',
            'password': 'pw',
            'player_to_add': 'New RB',
            'player_to_release': 'Old RB',
            'week': 2,
        }
    )

    assert status == 200, body
    rosters = repo.files['data/rosters.json']
    # GSA's FA swap applied...
    gsa_names = {p['name'] for p in rosters['GSA']}
    assert 'New RB' in gsa_names and 'Old RB' not in gsa_names
    # ...AND CGK's concurrent change was preserved, not clobbered.
    assert rosters['CGK'] == [{'name': 'CGK NEW GUY', 'position': 'WR', 'nfl_team': 'MIA'}]


# --------------------------------------------------------------------------- #
# Server-side lineup lock at kickoff
# --------------------------------------------------------------------------- #
def test_lineup_lock_prevents_benching_started_player(monkeypatch):
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    site = {'current_week': 5, 'kickoffs': {'KC': past, 'BUF': future}}
    rosters = {
        'GSA': [
            {'name': 'Started RB', 'position': 'RB', 'nfl_team': 'KC'},  # game kicked off
            {'name': 'Bench RB', 'position': 'RB', 'nfl_team': 'BUF'},  # not yet
        ]
    }

    def fake_get_json(path, token):
        return {'web/data.json': site, 'data/rosters.json': rosters}.get(path)

    monkeypatch.setattr(lineup, '_github_get_json', fake_get_json)

    existing_lineup = {'week': 5, 'lineups': {'GSA': {'RB': ['Started RB']}}}
    captured = {}

    def fake_urlopen(req):
        if req.get_method() == 'GET':
            body = json.dumps(
                {
                    'sha': 's',
                    'content': base64.b64encode(json.dumps(existing_lineup).encode()).decode(),
                }
            ).encode()
            return _FakeResponse(200, body)
        put = json.loads(req.data.decode())
        captured['content'] = json.loads(base64.b64decode(put['content']).decode())
        return _FakeResponse(200)

    monkeypatch.setattr(lineup.urllib.request, 'urlopen', fake_urlopen)

    # Manager tries to bench the player whose game already started.
    ok, msg, _ = lineup.update_lineup_file(
        week=5, team='GSA', starters={'RB': ['Bench RB']}, github_token='t'
    )

    assert ok, msg
    saved_rb = captured['content']['lineups']['GSA']['RB']
    # Locked player can't be benched; the not-yet-started add is allowed.
    assert 'Started RB' in saved_rb
    assert 'Bench RB' in saved_rb


def test_lineup_lock_merge_rejects_starter_overflow(monkeypatch):
    """P0.3: a locked RB plus 2 newly submitted RBs must not merge into 3 RBs."""
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    site = {'current_week': 5, 'kickoffs': {'KC': past}}
    rosters = {
        'GSA': [
            {'name': 'Locked RB', 'position': 'RB', 'nfl_team': 'KC'},
            {'name': 'New RB 1', 'position': 'RB', 'nfl_team': 'BUF'},
            {'name': 'New RB 2', 'position': 'RB', 'nfl_team': 'MIA'},
        ]
    }

    monkeypatch.setattr(
        lineup,
        '_github_get_json',
        lambda path, token: {'web/data.json': site, 'data/rosters.json': rosters}.get(path),
    )

    existing_lineup = {'week': 5, 'lineups': {'GSA': {'RB': ['Locked RB']}}}
    put_calls = []

    def fake_urlopen(req):
        if req.get_method() == 'GET':
            body = json.dumps(
                {
                    'sha': 's',
                    'content': base64.b64encode(json.dumps(existing_lineup).encode()).decode(),
                }
            ).encode()
            return _FakeResponse(200, body)
        put_calls.append(req)
        return _FakeResponse(200)

    monkeypatch.setattr(lineup.urllib.request, 'urlopen', fake_urlopen)

    # Client submits 2 different RBs, unaware "Locked RB" is locked and will be
    # merged back in -> would be 3 RBs (max is 2).
    ok, msg, status = lineup.update_lineup_file(
        week=5, team='GSA', starters={'RB': ['New RB 1', 'New RB 2']}, github_token='t'
    )

    assert ok is False
    assert status == 400
    assert 'RB' in msg
    assert not put_calls  # must not have written a lineup that exceeds the limit


# --------------------------------------------------------------------------- #
# Lineup submissions must be on the active roster (docs/ROADMAP_2026.md P1.6)
# --------------------------------------------------------------------------- #
def test_lineup_rejects_player_not_on_roster(monkeypatch):
    rosters = {'GSA': [{'name': 'Real RB', 'position': 'RB', 'nfl_team': 'KC', 'taxi': False}]}
    monkeypatch.setattr(
        lineup,
        '_github_get_json',
        lambda path, token: rosters if 'rosters.json' in path else None,
    )

    ok, msg, status = lineup.update_lineup_file(
        week=3, team='GSA', starters={'RB': ['Fake RB']}, github_token='t'
    )

    assert ok is False
    assert status == 400
    assert 'Fake RB' in msg


def test_lineup_rejects_taxi_player_as_starter(monkeypatch):
    rosters = {'GSA': [{'name': 'Taxi RB', 'position': 'RB', 'nfl_team': 'KC', 'taxi': True}]}
    monkeypatch.setattr(
        lineup,
        '_github_get_json',
        lambda path, token: rosters if 'rosters.json' in path else None,
    )

    ok, msg, status = lineup.update_lineup_file(
        week=3, team='GSA', starters={'RB': ['Taxi RB']}, github_token='t'
    )

    assert ok is False
    assert status == 400
    assert 'Taxi RB' in msg


def test_lineup_accepts_valid_active_roster_player(monkeypatch):
    rosters = {'GSA': [{'name': 'Real RB', 'position': 'RB', 'nfl_team': 'KC', 'taxi': False}]}

    def fake_get_json(path, token):
        return rosters if 'rosters.json' in path else None

    monkeypatch.setattr(lineup, '_github_get_json', fake_get_json)

    def fake_urlopen(req):
        if req.get_method() == 'GET':
            raise HTTPError(req.full_url, 404, 'Not Found', {}, None)
        return _FakeResponse(status=200)

    monkeypatch.setattr(lineup.urllib.request, 'urlopen', fake_urlopen)

    ok, msg, status = lineup.update_lineup_file(
        week=3, team='GSA', starters={'RB': ['Real RB']}, github_token='t'
    )

    assert ok is True, msg
    assert status == 200


def test_lineup_lock_inert_in_offseason(monkeypatch):
    # No kickoffs published -> lock derives nothing, submission applies verbatim.
    monkeypatch.setattr(
        lineup,
        '_github_get_json',
        lambda path, token: {'current_week': 0} if 'data.json' in path else None,
    )
    locked = lineup.get_locked_players(week=1, team='GSA', github_token='t')
    assert locked == set()


def test_lineup_week_enforces_week_one_lock_before_homepage_leaves_offseason(monkeypatch):
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    site = {'current_week': 0, 'lineup_week': 1, 'kickoffs': {'KC': past}}
    rosters = {'GSA': [{'name': 'Week 1 Starter', 'position': 'RB', 'nfl_team': 'KC'}]}
    monkeypatch.setattr(
        lineup,
        '_github_get_json',
        lambda path, token: {'web/data.json': site, 'data/rosters.json': rosters}.get(path),
    )

    locked = lineup.get_locked_players(week=1, team='GSA', github_token='t')

    assert locked == {'Week 1 Starter'}


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
