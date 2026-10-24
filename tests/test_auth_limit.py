import base64
import importlib.util
import json
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

import pytest

from api import auth_limit, request_util
from api.request_util import RequestError

# Captured before the autouse in-memory store replaces them.
REAL_LOAD_STATE = auth_limit._load_state
REAL_SAVE_STATE = auth_limit._save_state


class FakeHandler:
    def __init__(self, headers):
        self.headers = headers


def _from_ip(ip):
    request_util.remember_client_ip(FakeHandler({'x-real-ip': ip}))


def _check(password, team='GSA', **kwargs):
    return auth_limit.check_team_password(team, password, 'right', **kwargs)


def _fail(times, team='GSA'):
    for _ in range(times):
        assert _check('wrong', team) is False


def test_fifth_wrong_password_locks_the_team_out_for_that_ip():
    _from_ip('203.0.113.7')
    _fail(5)

    with pytest.raises(RequestError) as locked:
        _check('right')

    assert locked.value.status == 429
    assert 'Try again in 15 minutes' in locked.value.message


def test_lockout_does_not_reach_other_ips():
    _from_ip('203.0.113.7')
    _fail(5)

    _from_ip('198.51.100.2')
    assert _check('right') is True


def test_correct_password_clears_the_count(failed_login_store):
    _from_ip('203.0.113.7')
    _fail(4)
    assert _check('right') is True
    assert failed_login_store['state'] == {}

    _fail(4)
    assert _check('right') is True


def test_correct_password_with_no_failures_does_not_write(failed_login_store):
    _from_ip('203.0.113.7')
    assert _check('right') is True
    assert failed_login_store['writes'] == 0


def test_slash_and_underscore_spellings_share_one_count():
    _from_ip('203.0.113.7')
    _fail(3, team='S/T')
    _fail(2, team='S_T')

    with pytest.raises(RequestError) as locked:
        _check('right', team='S/T')
    assert locked.value.status == 429


def test_lockout_ends_after_fifteen_minutes(monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(auth_limit.time, 'time', lambda: now[0])
    _from_ip('203.0.113.7')
    _fail(5)

    now[0] += auth_limit.LOCKOUT_SECONDS - 60
    with pytest.raises(RequestError) as locked:
        _check('right')
    assert 'Try again in 1 minute.' in locked.value.message

    now[0] += 60
    assert _check('right') is True


def test_stored_keys_do_not_contain_the_ip(failed_login_store):
    _from_ip('203.0.113.7')
    _fail(1)

    assert '203.0.113.7' not in json.dumps(failed_login_store['state'])


def test_unreadable_state_fails_closed(monkeypatch):
    def broken():
        raise auth_limit.AuthStateError('GitHub is down')

    monkeypatch.setattr(auth_limit, '_load_state', broken)

    with pytest.raises(RequestError) as unavailable:
        _check('right')
    assert unavailable.value.status == 503
    assert _check('right', optional=True) is False


def test_optional_check_treats_a_lockout_as_signed_out():
    _from_ip('203.0.113.7')
    _fail(5)

    assert _check('right', optional=True) is False


def test_forwarded_for_is_used_when_real_ip_is_missing():
    request_util.remember_client_ip(FakeHandler({'x-forwarded-for': '192.0.2.4, 10.0.0.1'}))
    assert request_util.client_ip() == '192.0.2.4'


def _load_api(filename):
    module_name = f'auth_limit_{filename.removesuffix(".py").replace("-", "_")}'
    spec = importlib.util.spec_from_file_location(
        module_name, Path(request_util.__file__).parent / filename
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _post(module, payload, ip='203.0.113.7'):
    body = json.dumps(payload).encode()
    instance = module.handler.__new__(module.handler)
    instance.rfile = BytesIO(body)
    instance.wfile = BytesIO()
    instance.headers = {
        'Content-Type': 'application/json',
        'Content-Length': str(len(body)),
        'x-real-ip': ip,
    }
    instance.status = None
    instance.send_response = lambda status: setattr(instance, 'status', status)
    instance.send_header = lambda name, value: None
    instance.end_headers = lambda: None
    module.handler.do_POST(instance)
    return instance.status, json.loads(instance.wfile.getvalue())


@pytest.mark.parametrize(
    'filename', ['lineup.py', 'transaction.py', 'nfl-draft.py', 'team-name.py']
)
def test_endpoints_answer_429_after_five_wrong_passwords(monkeypatch, filename):
    module = _load_api(filename)
    monkeypatch.setattr(module, 'guard_mutation', lambda *args, **kwargs: None)
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'right')
    payload = {'action': 'validate', 'team': 'GSA', 'password': 'wrong'}
    if filename == 'team-name.py':
        payload = {'team': 'GSA', 'password': 'wrong', 'newName': 'New Name'}

    for _ in range(5):
        status, _body = _post(module, payload)
        assert status == 401

    status, body = _post(module, {**payload, 'password': 'right'})
    assert status == 429
    assert 'Too many wrong passwords' in body['error']


def test_nfl_draft_validate_counts_one_failure_per_request(monkeypatch, failed_login_store):
    module = _load_api('nfl-draft.py')
    monkeypatch.setattr(module, 'guard_mutation', lambda *args, **kwargs: None)
    monkeypatch.setenv('TEAM_PASSWORD_GSA', 'right')

    _post(module, {'action': 'validate', 'team': 'GSA', 'password': 'wrong'})

    [entry] = failed_login_store['state'].values()
    assert entry['failures'] == 1


class FakeGitHub:
    """Just enough of the Contents and Git Data APIs for the state branch."""

    def __init__(self, *, branch_exists=True, conflicts=0):
        self.branch_exists = branch_exists
        self.conflicts = conflicts
        self.file = None
        self.sha = None
        self.calls = []

    def __call__(self, method, path, payload=None):
        self.calls.append((method, path))
        if method == 'GET':
            if not self.branch_exists or self.file is None:
                raise HTTPError(path, 404, 'Not Found', {}, None)
            return {'content': base64.b64encode(self.file.encode()).decode(), 'sha': self.sha}
        if method == 'PUT':
            if not self.branch_exists:
                raise HTTPError(path, 404, 'Branch not found', {}, None)
            if self.conflicts:
                self.conflicts -= 1
                raise HTTPError(path, 409, 'Conflict', {}, None)
            if payload.get('sha') != self.sha:
                raise HTTPError(path, 409, 'Conflict', {}, None)
            self.file = base64.b64decode(payload['content']).decode()
            self.sha = f'sha-{len(self.calls)}'
            return {}
        if path == '/git/trees':
            self.tree = payload['tree']
            return {'sha': 'tree-sha'}
        if path == '/git/commits':
            assert payload['parents'] == []
            return {'sha': 'commit-sha'}
        if path == '/git/refs':
            assert payload['ref'] == 'refs/heads/auth-state'
            self.branch_exists = True
            self.file = next(item['content'] for item in self.tree if item['path'] == STATE)
            self.sha = 'first-sha'
            return {}
        raise AssertionError(f'unexpected call {method} {path}')


STATE = auth_limit.STATE_PATH


@pytest.fixture
def github(monkeypatch):
    monkeypatch.setattr(auth_limit, '_load_state', REAL_LOAD_STATE)
    monkeypatch.setattr(auth_limit, '_save_state', REAL_SAVE_STATE)
    monkeypatch.setenv('SKYNET_PAT', 'token')
    monkeypatch.setattr(auth_limit.time, 'sleep', lambda _seconds: None)

    def install(**kwargs):
        fake = FakeGitHub(**kwargs)
        monkeypatch.setattr(auth_limit, '_api_request', fake)
        return fake

    return install


def test_first_failure_starts_an_orphan_branch_that_vercel_skips(github):
    fake = github(branch_exists=False)
    _from_ip('203.0.113.7')

    assert _check('wrong') is False

    vercel = next(item for item in fake.tree if item['path'] == 'vercel.json')
    assert json.loads(vercel['content']) == {'git': {'deploymentEnabled': False}}
    [entry] = json.loads(fake.file).values()
    assert entry['failures'] == 1


def test_failures_accumulate_on_the_state_branch(github):
    fake = github()
    _from_ip('203.0.113.7')
    _fail(5)

    with pytest.raises(RequestError) as locked:
        _check('right')
    assert locked.value.status == 429
    [entry] = json.loads(fake.file).values()
    assert entry['failures'] == 5


def test_save_conflicts_are_retried(github):
    fake = github(conflicts=2)
    _from_ip('203.0.113.7')

    assert _check('wrong') is False
    [entry] = json.loads(fake.file).values()
    assert entry['failures'] == 1


def test_a_failure_that_cannot_be_recorded_is_not_answered(github):
    github(conflicts=auth_limit.MAX_WRITE_ATTEMPTS)
    _from_ip('203.0.113.7')

    with pytest.raises(RequestError) as unavailable:
        _check('wrong')
    assert unavailable.value.status == 503
