import importlib.util
import json
from io import BytesIO
from pathlib import Path

import pytest

from api import request_util

API_FILES = (
    'lineup.py',
    'nfl-draft.py',
    'rule-changes.py',
    'team-avatar.py',
    'team-name.py',
    'transaction.py',
)


def _load_api(filename):
    module_name = f'request_boundary_{filename.removesuffix(".py").replace("-", "_")}'
    spec = importlib.util.spec_from_file_location(
        module_name, Path(request_util.__file__).parent / filename
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _endpoint_handler(module, *, body=b'', headers=None):
    instance = module.handler.__new__(module.handler)
    instance.rfile = BytesIO(body)
    instance.wfile = BytesIO()
    instance.headers = headers or {}
    instance.status = None
    instance.response_headers = {}
    instance.send_response = lambda status: setattr(instance, 'status', status)
    instance.send_header = lambda name, value: instance.response_headers.__setitem__(name, value)
    instance.end_headers = lambda: None
    return instance


class FakeHandler:
    def __init__(self, body=b'', headers=None):
        self.rfile = BytesIO(body)
        self.wfile = BytesIO()
        self.headers = headers or {}
        self.status = None
        self.response_headers = {}

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.response_headers[name] = value

    def end_headers(self):
        pass


def _json_handler(payload, *, origin='https://qpfl-scoring.vercel.app'):
    body = json.dumps(payload).encode()
    return FakeHandler(
        body,
        {
            'Content-Type': 'application/json',
            'Content-Length': str(len(body)),
            **({'Origin': origin} if origin else {}),
        },
    )


@pytest.mark.parametrize(
    'origin',
    [
        'https://qpfl.org',
        'https://www.qpfl.org',
        'https://qpfl-scoring.vercel.app',
        'https://qpfl.github.io',
        None,
    ],
)
def test_allowed_and_missing_origins_can_parse_json(origin):
    handler = _json_handler({'ok': True}, origin=origin)
    assert request_util.read_json_body(handler) == {'ok': True}


def test_explicit_preview_origin_can_be_configured(monkeypatch):
    monkeypatch.setenv('QPFL_ALLOWED_PREVIEW_ORIGINS', 'https://preview.example')
    handler = _json_handler({'ok': True}, origin='https://preview.example')
    assert request_util.read_json_body(handler) == {'ok': True}


def test_disallowed_origin_is_rejected():
    with pytest.raises(request_util.RequestError) as caught:
        request_util.read_json_body(_json_handler({}, origin='https://evil.example'))
    assert caught.value.status == 403


@pytest.mark.parametrize(
    ('headers', 'status'),
    [
        ({'Content-Type': 'text/plain', 'Content-Length': '2'}, 415),
        ({'Content-Type': 'application/json'}, 411),
        ({'Content-Type': 'application/json', 'Content-Length': 'nope'}, 400),
        ({'Content-Type': 'application/json', 'Content-Length': '-1'}, 400),
        ({'Content-Type': 'application/json', 'Content-Length': '100'}, 413),
    ],
)
def test_request_metadata_is_validated_before_body_read(headers, status):
    handler = FakeHandler(b'{}', headers)
    with pytest.raises(request_util.RequestError) as caught:
        request_util.read_json_body(handler, max_bytes=10)
    assert caught.value.status == status
    assert handler.rfile.tell() == 0


def test_options_rejects_disallowed_origin_without_cors_header():
    handler = FakeHandler(headers={'Origin': 'https://evil.example'})
    request_util.handle_options(handler)
    assert handler.status == 403
    assert 'Access-Control-Allow-Origin' not in handler.response_headers


def test_json_response_echoes_only_allowed_origin():
    handler = FakeHandler(headers={'Origin': 'https://qpfl.github.io'})
    request_util.send_json(handler, 200, {'ok': True})
    assert handler.response_headers['Access-Control-Allow-Origin'] == 'https://qpfl.github.io'
    assert handler.response_headers['Vary'] == 'Origin'


def test_all_api_handlers_use_shared_request_boundaries():
    api_dir = Path(request_util.__file__).parent
    for filename in API_FILES:
        source = (api_dir / filename).read_text(encoding='utf-8')
        assert 'read_json_body(self' in source
        assert 'handle_options(self)' in source
        assert 'send_json(self, status_code, data)' in source
        assert "'Access-Control-Allow-Origin', '*'" not in source


@pytest.mark.parametrize('filename', API_FILES)
@pytest.mark.parametrize(
    ('origin', 'expected_status'),
    [
        ('https://qpfl.org', 204),
        ('https://www.qpfl.org', 204),
        ('https://qpfl-scoring.vercel.app', 204),
        ('https://qpfl.github.io', 204),
        (None, 204),
        ('https://evil.example', 403),
    ],
)
def test_every_api_handler_enforces_preflight_origins(filename, origin, expected_status):
    module = _load_api(filename)
    headers = {'Origin': origin} if origin else {}
    instance = _endpoint_handler(module, headers=headers)

    module.handler.do_OPTIONS(instance)

    assert instance.status == expected_status
    if expected_status == 204 and origin:
        assert instance.response_headers['Access-Control-Allow-Origin'] == origin
    if expected_status == 403:
        assert 'Access-Control-Allow-Origin' not in instance.response_headers


@pytest.mark.parametrize('filename', API_FILES)
@pytest.mark.parametrize(
    ('headers', 'expected_status'),
    [
        ({'Content-Type': 'text/plain', 'Content-Length': '2'}, 415),
        ({'Content-Type': 'application/json', 'Content-Length': 'invalid'}, 400),
        ({'Content-Type': 'application/json', 'Content-Length': str(4 * 1024 * 1024)}, 413),
    ],
)
def test_every_api_handler_rejects_bad_request_metadata_before_read(
    filename, headers, expected_status
):
    module = _load_api(filename)
    instance = _endpoint_handler(module, body=b'{}', headers=headers)

    module.handler.do_POST(instance)

    assert instance.status == expected_status
    assert instance.rfile.tell() == 0


@pytest.mark.parametrize('filename', API_FILES)
@pytest.mark.parametrize(
    ('origin', 'expected_status'),
    [
        ('https://qpfl.org', 400),
        ('https://www.qpfl.org', 400),
        ('https://qpfl-scoring.vercel.app', 400),
        ('https://qpfl.github.io', 400),
        (None, 400),
        ('https://evil.example', 403),
    ],
)
def test_every_api_handler_enforces_post_origins(filename, origin, expected_status):
    module = _load_api(filename)
    body = json.dumps({'action': 'invalid'}).encode()
    headers = {
        'Content-Type': 'application/json',
        'Content-Length': str(len(body)),
        **({'Origin': origin} if origin else {}),
    }
    instance = _endpoint_handler(module, body=body, headers=headers)

    module.handler.do_POST(instance)

    assert instance.status == expected_status
    if expected_status == 400 and origin:
        assert instance.response_headers['Access-Control-Allow-Origin'] == origin
    if expected_status == 403:
        assert instance.rfile.tell() == 0
        assert 'Access-Control-Allow-Origin' not in instance.response_headers


@pytest.mark.parametrize('filename', API_FILES)
def test_every_api_handler_returns_generic_unexpected_errors(filename, monkeypatch):
    module = _load_api(filename)
    instance = _endpoint_handler(module)
    monkeypatch.setattr(
        module,
        'read_json_body',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError('sensitive upstream response')
        ),
    )
    monkeypatch.setattr(module, 'request_id', lambda: 'request-test')

    module.handler.do_POST(instance)

    assert instance.status == 500
    payload = json.loads(instance.wfile.getvalue())
    assert payload == {'error': 'Unexpected server error', 'request_id': 'request-test'}
    assert b'sensitive upstream response' not in instance.wfile.getvalue()
