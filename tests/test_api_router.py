"""The /api router dispatches to the right endpoint module and nothing else."""

import json
from io import BytesIO
from pathlib import Path

import pytest

from api import index

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERCEL_CONFIG = json.loads((PROJECT_ROOT / 'vercel.json').read_text(encoding='utf-8'))


def _router_handler(*, path, body=b'', headers=None):
    instance = index.handler.__new__(index.handler)
    instance.path = path
    instance.rfile = BytesIO(body)
    instance.wfile = BytesIO()
    instance.headers = headers or {}
    instance.status = None
    instance.response_headers = {}
    instance.send_response = lambda status: setattr(instance, 'status', status)
    instance.send_header = lambda name, value: instance.response_headers.__setitem__(name, value)
    instance.end_headers = lambda: None
    return instance


def test_every_route_resolves_to_an_importable_handler():
    for route in index.ROUTES:
        assert callable(index.endpoint_handler(route).do_POST)


@pytest.mark.parametrize('route', sorted(index.ROUTES))
def test_route_is_read_from_the_rewrite_query_param(route):
    assert index.resolve_route(f'/api/index.py?__route={route}') == route
    # Endpoint query params must survive alongside the injected __route.
    assert index.resolve_route(f'/api/index.py?__route={route}&action=proposals') == route


@pytest.mark.parametrize('route', sorted(index.ROUTES))
def test_route_falls_back_to_the_request_path(route):
    assert index.resolve_route(f'/api/{route}') == route
    assert index.resolve_route(f'/api/{route}?action=proposals') == route


@pytest.mark.parametrize('path', ['/api/unknown', '/api/index.py?__route=nope', '/', ''])
def test_unknown_routes_do_not_dispatch(path):
    assert index.resolve_route(path) is None


def test_unknown_route_returns_404():
    instance = _router_handler(path='/api/nope')
    index.handler.do_POST(instance)
    assert instance.status == 404
    assert json.loads(instance.wfile.getvalue()) == {'error': 'Unknown API endpoint'}


@pytest.mark.parametrize('route', sorted(index.ROUTES))
def test_preflight_is_delegated_to_the_endpoint(route):
    instance = _router_handler(
        path=f'/api/index.py?__route={route}', headers={'Origin': 'https://qpfl.org'}
    )
    index.handler.do_OPTIONS(instance)
    assert instance.status == 204
    assert instance.response_headers['Access-Control-Allow-Origin'] == 'https://qpfl.org'


@pytest.mark.parametrize('route', sorted(index.ROUTES))
def test_preflight_rejects_disallowed_origin_through_the_router(route):
    instance = _router_handler(
        path=f'/api/index.py?__route={route}', headers={'Origin': 'https://evil.example'}
    )
    index.handler.do_OPTIONS(instance)
    assert instance.status == 403
    assert 'Access-Control-Allow-Origin' not in instance.response_headers


@pytest.mark.parametrize('route', sorted(index.ROUTES))
def test_post_reaches_the_endpoint_body_validation(route):
    body = json.dumps({'action': 'invalid'}).encode()
    instance = _router_handler(
        path=f'/api/index.py?__route={route}',
        body=body,
        headers={
            'Content-Type': 'text/plain',
            'Content-Length': str(len(body)),
            'Origin': 'https://qpfl.org',
        },
    )
    index.handler.do_POST(instance)
    # 415 can only come from the endpoint's read_json_body, so dispatch landed.
    assert instance.status == 415
    assert instance.rfile.tell() == 0


def test_vercel_config_builds_exactly_one_python_function():
    python_builds = [b for b in VERCEL_CONFIG['builds'] if b['use'] == '@vercel/python']
    assert [b['src'] for b in python_builds] == ['api/index.py']


def test_vercel_routes_cover_every_endpoint_via_the_router():
    dests = {
        route['src']: route['dest']
        for route in VERCEL_CONFIG['routes']
        if route.get('dest', '').startswith('/api/')
    }
    assert dests == {f'/api/{name}': f'/api/index.py?__route={name}' for name in index.ROUTES}


def test_python_bundle_excludes_the_static_payload():
    (build,) = [b for b in VERCEL_CONFIG['builds'] if b['use'] == '@vercel/python']
    excluded = build['config']['excludeFiles']
    for directory in ('web', 'previous_seasons', 'tests'):
        assert f'{directory}/**' in excluded
