"""Tests for api/maintenance.py: the live maintenance-mode reader and guard
enforced by every manager-facing endpoint (see api/lineup.py, api/transaction.py,
api/nfl-draft.py, api/rule-changes.py, api/team-name.py, api/team-avatar.py).
"""

import importlib.util
import json
from io import BytesIO
from pathlib import Path

import pytest

from api import maintenance
from api.request_util import RequestError

API_DIR = Path(maintenance.__file__).resolve().parent


def _load_api(filename):
    """Load an endpoint module fresh from disk.

    The hyphenated filenames aren't valid import syntax, so each endpoint is
    loaded by file path - but its `from api.maintenance import guard_mutation`
    still resolves to the one real api.maintenance module in sys.modules, so
    patching `maintenance.maintenance_state` below controls every endpoint
    loaded this way.
    """
    module_name = f'maintenance_integration_{filename.removesuffix(".py").replace("-", "_")}'
    spec = importlib.util.spec_from_file_location(module_name, API_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _post_handler(module, payload, *, origin='https://qpfl-scoring.vercel.app'):
    body = json.dumps(payload).encode()
    instance = module.handler.__new__(module.handler)
    instance.rfile = BytesIO(body)
    instance.wfile = BytesIO()
    instance.headers = {
        'Content-Type': 'application/json',
        'Content-Length': str(len(body)),
        'Origin': origin,
    }
    instance.status = None
    instance.response_headers = {}
    instance.send_response = lambda status: setattr(instance, 'status', status)
    instance.send_header = lambda name, value: instance.response_headers.__setitem__(name, value)
    instance.end_headers = lambda: None
    return instance


# A mutating action for each endpoint (blocked while maintenance is enabled)
# alongside a read-only action that stays available, where one exists.
MUTATING_REQUESTS = [
    ('lineup.py', {'action': 'submit', 'team': 'GSA', 'password': 'pw'}),
    ('transaction.py', {'action': 'taxi_activate', 'team': 'GSA', 'password': 'pw'}),
    ('nfl-draft.py', {'action': 'submit', 'team': 'GSA', 'password': 'pw'}),
    ('rule-changes.py', {'action': 'vote', 'team': 'GSA', 'password': 'pw'}),
    ('team-name.py', {'team': 'GSA', 'password': 'pw', 'newName': 'Foo'}),
    ('team-avatar.py', {'team': 'GSA', 'password': 'pw', 'imageData': 'x'}),
]

EXEMPT_REQUESTS = [
    ('lineup.py', {'action': 'validate', 'team': 'GSA', 'password': 'wrong'}),
    ('transaction.py', {'action': 'validate', 'team': 'GSA', 'password': 'wrong'}),
    ('nfl-draft.py', {'action': 'validate', 'team': 'GSA', 'password': 'wrong'}),
]


@pytest.mark.parametrize(('filename', 'payload'), MUTATING_REQUESTS)
def test_mutation_is_blocked_with_503_while_maintenance_is_enabled(filename, payload, monkeypatch):
    module = _load_api(filename)
    monkeypatch.setattr(
        maintenance,
        'maintenance_state',
        lambda **_kwargs: {
            'enabled': True,
            'message': 'Fixing Week 1 scores',
            'since': '2026-09-14T00:00:00+00:00',
        },
    )

    instance = _post_handler(module, payload)
    module.handler.do_POST(instance)

    assert instance.status == 503
    assert json.loads(instance.wfile.getvalue()) == {'error': 'Fixing Week 1 scores'}


@pytest.mark.parametrize(('filename', 'payload'), MUTATING_REQUESTS)
def test_mutation_proceeds_normally_while_maintenance_is_disabled(filename, payload, monkeypatch):
    module = _load_api(filename)
    monkeypatch.setattr(
        maintenance,
        'maintenance_state',
        lambda **_kwargs: {'enabled': False, 'message': '', 'since': None},
    )

    instance = _post_handler(module, payload)
    module.handler.do_POST(instance)

    # Whatever normal validation the endpoint does next (missing config,
    # invalid credential, ...) is fine - the point is maintenance mode did
    # not intervene.
    assert instance.status != 503


@pytest.mark.parametrize(('filename', 'payload'), EXEMPT_REQUESTS)
def test_read_only_actions_skip_the_maintenance_check_entirely(filename, payload, monkeypatch):
    module = _load_api(filename)

    def fail(**_kwargs):
        raise AssertionError('a read-only action must not need to check maintenance state')

    monkeypatch.setattr(maintenance, 'maintenance_state', fail)
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'correct-password')

    instance = _post_handler(module, payload)
    module.handler.do_POST(instance)

    # Wrong password reaching a real 401 (not an AssertionError-triggered 500)
    # proves execution passed straight through the guard.
    assert instance.status == 401


def test_commissioner_admin_adjust_is_exempt_while_maintenance_is_enabled(monkeypatch):
    """The commissioner must be able to fix things while everyone else is frozen out."""
    module = _load_api('transaction.py')
    monkeypatch.setattr(
        maintenance,
        'maintenance_state',
        lambda **_kwargs: {
            'enabled': True,
            'message': 'Fixing Week 1 scores',
            'since': '2026-09-14T00:00:00+00:00',
        },
    )
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'pw')

    payload = {
        'action': 'admin_adjust',
        'admin_action': 'season_status',
        'team': 'GSA',
        'password': 'pw',
    }
    instance = _post_handler(module, payload)
    module.handler.do_POST(instance)

    # Reaches real admin_adjust logic (which then fails for lack of a live
    # GitHub token in this test) rather than being turned away at 503 by the
    # maintenance guard itself.
    assert instance.status != 503


@pytest.fixture(autouse=True)
def _reset_cache():
    """Each test controls its own fake GitHub read, so the in-process cache
    from a previous test must never leak into the next one."""
    maintenance._cache['state'] = None
    maintenance._cache['read_at'] = 0.0
    yield
    maintenance._cache['state'] = None
    maintenance._cache['read_at'] = 0.0


def _install_config(monkeypatch, config, *, headers_ok=True):
    """Stand in for the GitHub read inside api.maintenance._fetch_state."""
    calls = {'count': 0}

    def fake_fetch_json_file(api_url, headers, *, opener):
        del api_url, headers, opener
        calls['count'] += 1
        return {'sha': 'abc'}, config

    monkeypatch.setattr(maintenance, 'fetch_json_file', fake_fetch_json_file)
    if headers_ok:
        monkeypatch.setenv('SKYNET_PAT', 'test-token')
    return calls


def test_maintenance_state_reports_enabled_with_message(monkeypatch):
    _install_config(
        monkeypatch,
        {
            'maintenance': {
                'enabled': True,
                'message': 'Fixing Week 1 scores',
                'since': '2026-09-14T00:00:00+00:00',
                'actor': 'GSA',
            }
        },
    )

    state = maintenance.maintenance_state()

    assert state == {
        'enabled': True,
        'message': 'Fixing Week 1 scores',
        'since': '2026-09-14T00:00:00+00:00',
    }


def test_maintenance_state_reports_disabled(monkeypatch):
    _install_config(
        monkeypatch,
        {'maintenance': {'enabled': False, 'message': '', 'since': None, 'actor': None}},
    )

    state = maintenance.maintenance_state()

    assert state['enabled'] is False


def test_maintenance_state_raises_when_key_missing(monkeypatch):
    _install_config(monkeypatch, {'current_season': 2026})

    with pytest.raises(ValueError):
        maintenance.maintenance_state()


def test_maintenance_state_raises_when_enabled_is_not_boolean(monkeypatch):
    _install_config(
        monkeypatch,
        {'maintenance': {'enabled': 'true', 'message': '', 'since': None, 'actor': None}},
    )

    with pytest.raises(ValueError):
        maintenance.maintenance_state()


def test_maintenance_state_raises_without_a_github_token(monkeypatch):
    _install_config(
        monkeypatch,
        {'maintenance': {'enabled': False, 'message': '', 'since': None, 'actor': None}},
        headers_ok=False,
    )
    monkeypatch.delenv('SKYNET_PAT', raising=False)
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)

    with pytest.raises(RuntimeError):
        maintenance.maintenance_state()


def test_maintenance_state_caches_within_the_ttl(monkeypatch):
    calls = _install_config(
        monkeypatch,
        {'maintenance': {'enabled': False, 'message': '', 'since': None, 'actor': None}},
    )

    maintenance.maintenance_state()
    maintenance.maintenance_state()
    maintenance.maintenance_state()

    assert calls['count'] == 1


def test_maintenance_state_force_refresh_bypasses_the_cache(monkeypatch):
    calls = _install_config(
        monkeypatch,
        {'maintenance': {'enabled': False, 'message': '', 'since': None, 'actor': None}},
    )

    maintenance.maintenance_state()
    maintenance.maintenance_state(force_refresh=True)

    assert calls['count'] == 2


def test_guard_mutation_allows_listed_actions_without_reading_state(monkeypatch):
    def fake_fetch_json_file(*_args, **_kwargs):
        raise AssertionError('guard_mutation must not read state for an allowed action')

    monkeypatch.setattr(maintenance, 'fetch_json_file', fake_fetch_json_file)

    maintenance.guard_mutation('validate', allowed=frozenset({'validate'}))


def test_guard_mutation_passes_through_when_disabled(monkeypatch):
    _install_config(
        monkeypatch,
        {'maintenance': {'enabled': False, 'message': '', 'since': None, 'actor': None}},
    )

    maintenance.guard_mutation('submit', allowed=frozenset({'validate'}))


def test_guard_mutation_blocks_when_enabled(monkeypatch):
    _install_config(
        monkeypatch,
        {
            'maintenance': {
                'enabled': True,
                'message': 'Fixing Week 1 scores',
                'since': '2026-09-14T00:00:00+00:00',
                'actor': 'GSA',
            }
        },
    )

    with pytest.raises(RequestError) as excinfo:
        maintenance.guard_mutation('submit', allowed=frozenset({'validate'}))

    assert excinfo.value.status == 503
    assert excinfo.value.message == 'Fixing Week 1 scores'


def test_guard_mutation_falls_back_to_default_message_when_blank(monkeypatch):
    _install_config(
        monkeypatch,
        {'maintenance': {'enabled': True, 'message': '', 'since': None, 'actor': 'GSA'}},
    )

    with pytest.raises(RequestError) as excinfo:
        maintenance.guard_mutation('submit')

    assert excinfo.value.status == 503
    assert excinfo.value.message == maintenance.DEFAULT_MESSAGE


def test_guard_mutation_fails_closed_when_state_is_unreadable(monkeypatch):
    def fake_fetch_json_file(*_args, **_kwargs):
        raise OSError('network is down')

    monkeypatch.setattr(maintenance, 'fetch_json_file', fake_fetch_json_file)
    monkeypatch.setenv('SKYNET_PAT', 'test-token')

    with pytest.raises(RequestError) as excinfo:
        maintenance.guard_mutation('submit')

    assert excinfo.value.status == 503


def test_guard_mutation_still_allowed_action_skips_broken_config(monkeypatch):
    def fake_fetch_json_file(*_args, **_kwargs):
        raise AssertionError('should not be called for an allowed action')

    monkeypatch.setattr(maintenance, 'fetch_json_file', fake_fetch_json_file)

    maintenance.guard_mutation(None, allowed=frozenset({None}))


def test_failed_refresh_keeps_a_recent_state(monkeypatch):
    _install_config(monkeypatch, {'maintenance': {'enabled': False}})
    assert maintenance.maintenance_state()['enabled'] is False

    def broken(*_args, **_kwargs):
        raise OSError('GitHub is down')

    monkeypatch.setattr(maintenance, 'fetch_json_file', broken)
    maintenance._cache['read_at'] -= maintenance._CACHE_TTL_SECONDS + 1
    assert maintenance.maintenance_state()['enabled'] is False

    maintenance._cache['read_at'] -= maintenance._STALE_FALLBACK_SECONDS
    with pytest.raises(OSError):
        maintenance.maintenance_state()
