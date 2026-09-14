"""Live maintenance-mode check enforced by every manager-facing endpoint.

Reads data/league_config.json directly rather than through the export
pipeline (scripts/export_current.py), so toggling maintenance mode via
api/transaction.py's admin_adjust takes effect immediately - without waiting
for a scoring run or a redeploy. That matters because a broken export or
redeploy is exactly the kind of thing maintenance mode exists to cover.
"""

from __future__ import annotations

import os
import time
import urllib.request
from http.server import BaseHTTPRequestHandler
from typing import Any

from api.github_content import fetch_json_file
from api.request_util import RequestError, handle_options, read_json_body, send_json

GITHUB_OWNER = os.environ.get('REPO_OWNER') or os.environ.get('GITHUB_OWNER', 'griffin')
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'scoring')
LEAGUE_CONFIG_PATH = 'data/league_config.json'
DEFAULT_MESSAGE = 'No changes are being accepted right now.'

# Warm Vercel containers reuse this between invocations, so the common case
# costs nowhere near one GitHub API read per request. Short enough that a
# toggle is never stale for more than a few seconds on any given container.
_CACHE_TTL_SECONDS = 10
_cache: dict[str, Any] = {'state': None, 'read_at': 0.0}


def _github_headers() -> dict[str, str] | None:
    token = os.environ.get('SKYNET_PAT') or os.environ.get('GITHUB_TOKEN')
    if not token:
        return None
    return {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'QPFL-Maintenance-Check',
    }


def _fetch_state() -> dict[str, Any]:
    headers = _github_headers()
    if headers is None:
        raise RuntimeError('Server configuration error - no GitHub token')
    api_url = (
        f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{LEAGUE_CONFIG_PATH}'
    )
    _metadata, config = fetch_json_file(api_url, headers, opener=urllib.request.urlopen)
    maintenance = config.get('maintenance') if isinstance(config, dict) else None
    if not isinstance(maintenance, dict) or not isinstance(maintenance.get('enabled'), bool):
        raise ValueError('league configuration is missing a valid maintenance setting')
    return {
        'enabled': maintenance['enabled'],
        'message': maintenance.get('message') or '',
        'since': maintenance.get('since'),
    }


def maintenance_state(*, force_refresh: bool = False) -> dict[str, Any]:
    """Return the current maintenance-mode state, cached briefly in-process.

    Raises on any read/parse failure so callers can fail closed instead of
    silently treating a broken config read as "not in maintenance".
    """
    now = time.monotonic()
    cached = _cache['state']
    if not force_refresh and cached is not None and now - _cache['read_at'] < _CACHE_TTL_SECONDS:
        return cached
    state = _fetch_state()
    _cache['state'] = state
    _cache['read_at'] = now
    return state


def guard_mutation(action: str | None, allowed: frozenset[str] = frozenset()) -> None:
    """Block a manager-facing mutation while maintenance mode is on.

    `allowed` lists actions that stay available regardless (read-only actions
    like `validate`/`get_state`, and the commissioner's own `admin_adjust`).
    Fails closed: if the flag can't be read, the mutation is blocked anyway -
    a GitHub read failure here means the write below would fail the same way.
    """
    if action in allowed:
        return
    try:
        state = maintenance_state()
    except Exception:
        raise RequestError(
            503, 'League configuration is unavailable - changes are paused'
        ) from None
    if state['enabled']:
        raise RequestError(503, state['message'] or DEFAULT_MESSAGE)


class handler(BaseHTTPRequestHandler):  # noqa: N801
    def do_OPTIONS(self):
        handle_options(self)

    def do_GET(self):
        try:
            state = maintenance_state()
        except Exception:
            return send_json(self, 503, {'error': 'Maintenance status is unavailable'})
        return send_json(self, 200, state)

    def do_POST(self):
        # This endpoint is GET-only, but the body is still validated first
        # (content-type, size) so a malformed POST fails the same way every
        # other endpoint's do_POST does, instead of masking the real error.
        try:
            read_json_body(self)
        except RequestError as error:
            return send_json(self, error.status, {'error': error.message})
        return send_json(self, 405, {'error': 'Method not allowed'})

    def log_message(self, format, *args):
        pass
