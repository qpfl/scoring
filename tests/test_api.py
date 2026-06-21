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
from pathlib import Path
from urllib.error import HTTPError

import pytest

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

    ok, _ = lineup.update_lineup_file(
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


def test_fa_activation_rolls_back_claim_if_release_invalid(monkeypatch):
    # If the release player isn't on the roster, the FA claim must be reverted
    # so the player isn't stranded as unavailable.
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')
    repo = FakeRepo(
        {
            'data/fa_pool.json': [
                {'name': 'Backup RB', 'position': 'RB', 'nfl_team': 'KC', 'available': True}
            ],
            'data/rosters.json': {'GSA': [{'name': 'Real RB', 'position': 'RB', 'nfl_team': 'NYJ'}]},
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
            {'name': 'Started RB', 'position': 'RB', 'nfl_team': 'KC'},   # game kicked off
            {'name': 'Bench RB', 'position': 'RB', 'nfl_team': 'BUF'},     # not yet
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
    ok, msg = lineup.update_lineup_file(
        week=5, team='GSA', starters={'RB': ['Bench RB']}, github_token='t'
    )

    assert ok, msg
    saved_rb = captured['content']['lineups']['GSA']['RB']
    # Locked player can't be benched; the not-yet-started add is allowed.
    assert 'Started RB' in saved_rb
    assert 'Bench RB' in saved_rb


def test_lineup_lock_inert_in_offseason(monkeypatch):
    # No kickoffs published -> lock derives nothing, submission applies verbatim.
    monkeypatch.setattr(
        lineup, '_github_get_json', lambda path, token: {'current_week': 0} if 'data.json' in path else None
    )
    locked = lineup.get_locked_players(week=1, team='GSA', github_token='t')
    assert locked == set()


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
