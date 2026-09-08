"""Single Vercel function that routes every /api/* request to its endpoint module.

The Python runtime does no tree-shaking: each function bundles the whole
project, so six functions meant six copies of it in Deployment Storage. Routing
through one function keeps the public URLs unchanged while storing one bundle.

Endpoint modules stay independent and are still loaded directly by the tests;
this only adds a dispatch layer in front of them.
"""

from __future__ import annotations

import importlib
from http.server import BaseHTTPRequestHandler
from types import ModuleType
from urllib.parse import parse_qs, urlparse

from api.request_util import send_json

# Public route name -> module path. The hyphenated names are not valid import
# syntax, so these are resolved through importlib rather than an import stmt.
ROUTES = {
    'lineup': 'api.lineup',
    'transaction': 'api.transaction',
    'rule-changes': 'api.rule-changes',
    'nfl-draft': 'api.nfl-draft',
    'team-name': 'api.team-name',
    'team-avatar': 'api.team-avatar',
}

_modules: dict[str, ModuleType] = {}


def resolve_route(path: str | None) -> str | None:
    """Pick the endpoint for a request path, or None when it matches nothing.

    vercel.json passes the endpoint as `__route` so dispatch does not depend on
    whether the rewrite preserves the original path; the path is read as a
    fallback for direct invocations.
    """
    parsed = urlparse(path or '')
    explicit = parse_qs(parsed.query).get('__route', [''])[0]
    if explicit in ROUTES:
        return explicit
    segment = parsed.path.rsplit('/', 1)[-1].removesuffix('.py')
    return segment if segment in ROUTES else None


def endpoint_handler(route: str) -> type:
    """Return the endpoint module's handler class, importing it on first use."""
    if route not in _modules:
        _modules[route] = importlib.import_module(ROUTES[route])
    return _modules[route].handler


class handler(BaseHTTPRequestHandler):  # noqa: N801
    def do_OPTIONS(self):
        self._dispatch('do_OPTIONS')

    def do_GET(self):
        self._dispatch('do_GET')

    def do_POST(self):
        self._dispatch('do_POST')

    def _dispatch(self, method: str):
        route = resolve_route(self.path)
        if route is None:
            return send_json(self, 404, {'error': 'Unknown API endpoint'})
        # The endpoint methods only touch the BaseHTTPRequestHandler protocol,
        # so they run against this instance unbound.
        return getattr(endpoint_handler(route), method)(self)

    def _send_json(self, status_code: int, data: dict):
        send_json(self, status_code, data)

    def log_message(self, format, *args):
        pass
