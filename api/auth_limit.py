"""Lock a team's password out for one client IP after repeated wrong guesses.

Every team-password check goes through ``check_team_password``. Five wrong
passwords for a team from one IP lock that team out for that IP for 15
minutes; other IPs, including the real owner's, are unaffected. A correct
password clears the IP's count.

Vercel runs many short-lived instances, so the counts can't live in memory.
They live in ``failed_logins.json`` on a dedicated ``auth-state`` branch: no
workflow runs on it (they filter on main/develop) and its own vercel.json
turns deployments off, so a wrong password neither commits to main nor
redeploys the site. Only a wrong password writes; a correct one costs one
read. Keys are HMACs of team and IP, so the branch never holds raw IPs.

Failures are counted after the password is compared, so a burst of
concurrent wrong guesses that all read the state before any write lands can
exceed five. Counting before comparing would close that gap, but the site
sends several authenticated requests at once on page load, which would lock
real owners out.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import random
import time
import urllib.request
from typing import Any
from urllib.error import HTTPError

from api.github_http import open_github_with_retry
from api.request_util import RequestError, client_ip

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_SECONDS = 15 * 60
STATE_PATH = 'failed_logins.json'
MAX_WRITE_ATTEMPTS = 5
# The auth-state branch carries this so Vercel never deploys its commits.
BRANCH_VERCEL_CONFIG = {'git': {'deploymentEnabled': False}}
logger = logging.getLogger(__name__)


class AuthStateError(RuntimeError):
    pass


def _settings() -> tuple[str, str, str, dict[str, str]]:
    owner = os.environ.get('REPO_OWNER') or os.environ.get('GITHUB_OWNER', 'griffin')
    repo = os.environ.get('GITHUB_REPO', 'scoring')
    branch = os.environ.get('AUTH_STATE_BRANCH', 'auth-state')
    token = os.environ.get('SKYNET_PAT') or os.environ.get('GITHUB_TOKEN')
    if not token:
        raise AuthStateError('GitHub credentials are not configured')
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
        'User-Agent': 'QPFL-Auth-Limit',
    }
    return owner, repo, branch, headers


def _api_request(method: str, path: str, payload: dict | None = None) -> dict:
    owner, repo, _branch, headers = _settings()
    request = urllib.request.Request(
        f'https://api.github.com/repos/{owner}/{repo}{path}',
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers,
        method=method,
    )
    with open_github_with_retry(request) as response:
        body = response.read()
    return json.loads(body.decode()) if body else {}


def _load_state() -> tuple[dict[str, Any], str | None]:
    """Return the failure counts and their blob sha; ({}, None) before the first."""
    _owner, _repo, branch, _headers = _settings()
    try:
        metadata = _api_request('GET', f'/contents/{STATE_PATH}?ref={branch}')
        state = json.loads(base64.b64decode(metadata['content']).decode())
    except HTTPError as error:
        if error.code == 404:
            return {}, None
        raise AuthStateError(f'could not read auth state ({error.code})') from error
    except (KeyError, TypeError, ValueError) as error:
        raise AuthStateError('auth state is malformed') from error
    except Exception as error:
        raise AuthStateError('could not read auth state') from error
    if not isinstance(state, dict):
        raise AuthStateError('auth state is malformed')
    return state, metadata.get('sha')


def _create_branch(state: dict[str, Any]) -> None:
    """Start the auth-state branch as an orphan holding the state and vercel.json."""
    _owner, _repo, branch, _headers = _settings()
    tree = _api_request(
        'POST',
        '/git/trees',
        {
            'tree': [
                {
                    'path': STATE_PATH,
                    'mode': '100644',
                    'type': 'blob',
                    'content': json.dumps(state, sort_keys=True),
                },
                {
                    'path': 'vercel.json',
                    'mode': '100644',
                    'type': 'blob',
                    'content': json.dumps(BRANCH_VERCEL_CONFIG, indent=2) + '\n',
                },
            ]
        },
    )
    commit = _api_request(
        'POST',
        '/git/commits',
        {'message': 'Start failed-login state', 'tree': tree['sha'], 'parents': []},
    )
    _api_request('POST', '/git/refs', {'ref': f'refs/heads/{branch}', 'sha': commit['sha']})


def _save_state(state: dict[str, Any], sha: str | None) -> None:
    """Write the state with compare-and-swap; HTTPError 409/422 means retry."""
    _owner, _repo, branch, _headers = _settings()
    payload = {
        'message': 'Update failed-login state',
        'content': base64.b64encode(json.dumps(state, sort_keys=True).encode()).decode(),
        'branch': branch,
    }
    if sha:
        payload['sha'] = sha
    try:
        _api_request('PUT', f'/contents/{STATE_PATH}', payload)
    except HTTPError as error:
        # The Contents API answers 404 when the branch itself doesn't exist.
        if error.code != 404 or sha:
            raise
        _create_branch(state)


def _update_state(mutate) -> Any:
    """Apply ``mutate(state, now)`` with sha retries; it returns (changed, result)."""
    for attempt in range(MAX_WRITE_ATTEMPTS):
        state, sha = _load_state()
        now = time.time()
        state = {
            key: entry
            for key, entry in state.items()
            if isinstance(entry, dict)
            and isinstance(entry.get('last_failed_at'), (int, float))
            and now - entry['last_failed_at'] < LOCKOUT_SECONDS
        }
        changed, result = mutate(state, now)
        if not changed:
            return result
        try:
            _save_state(state, sha)
            return result
        except HTTPError as error:
            if error.code in (409, 422) and attempt + 1 < MAX_WRITE_ATTEMPTS:
                time.sleep(0.2 * (attempt + 1) * random.uniform(0.7, 1.3))
                continue
            raise AuthStateError(f'could not save auth state ({error.code})') from error
        except AuthStateError:
            raise
        except Exception as error:
            raise AuthStateError('could not save auth state') from error
    raise AuthStateError('auth state update conflicted too many times')


def _attempt_key(team: str) -> str:
    secret = (
        os.environ.get('AUTH_LIMIT_SECRET')
        or os.environ.get('SKYNET_PAT')
        or os.environ.get('GITHUB_TOKEN')
    )
    if not secret:
        raise AuthStateError('no secret is configured for failed-login keys')
    # Same normalization as the TEAM_PASSWORD_* lookup, so "S/T" and "S_T"
    # share one count.
    subject = f'{team.replace("/", "_")}|{client_ip()}'
    return hmac.new(secret.encode(), subject.encode(), hashlib.sha256).hexdigest()[:32]


def _locked_minutes(entry: dict | None, now: float) -> int | None:
    if not entry or entry.get('failures', 0) < MAX_FAILED_ATTEMPTS:
        return None
    remaining = LOCKOUT_SECONDS - (now - entry['last_failed_at'])
    return max(1, int(-(-remaining // 60)))


def _locked_error(minutes: int) -> RequestError:
    unit = 'minute' if minutes == 1 else 'minutes'
    return RequestError(429, f'Too many wrong passwords. Try again in {minutes} {unit}.')


def check_team_password(team: str, password, expected: str, *, optional: bool = False) -> bool:
    """Compare a team password, enforcing the per-IP lockout.

    Returns whether ``password`` matches ``expected``. Raises RequestError 429
    while locked out and 503 when the failure counts can't be read or saved,
    so a guess is never answered without being counted. With ``optional``, a
    lockout or unavailable state returns False instead of raising, for
    endpoints that also serve anonymous visitors.
    """
    try:
        key = _attempt_key(team)
        state, _sha = _load_state()
        now = time.time()
        entry = state.get(key)
        if isinstance(entry, dict) and isinstance(entry.get('last_failed_at'), (int, float)):
            if now - entry['last_failed_at'] >= LOCKOUT_SECONDS:
                entry = None
        else:
            entry = None
        minutes = _locked_minutes(entry, now)
        if minutes is not None:
            raise _locked_error(minutes)

        if hmac.compare_digest(str(password), expected):
            if entry is not None:
                try:
                    _update_state(lambda current, _now: (current.pop(key, None) is not None, None))
                except AuthStateError:
                    # The login is valid; a stale count only costs this IP a try.
                    logger.exception('Could not clear failed-login count')
            return True

        def record_failure(current, now):
            previous = current.get(key)
            minutes = _locked_minutes(previous, now)
            if minutes is not None:
                # Concurrent guesses already used up this IP's tries.
                return False, minutes
            failures = (previous or {}).get('failures', 0) + 1
            current[key] = {'failures': failures, 'last_failed_at': now}
            return True, None

        minutes = _update_state(record_failure)
        if minutes is not None:
            raise _locked_error(minutes)
        return False
    except RequestError:
        if optional:
            return False
        raise
    except AuthStateError as error:
        logger.exception('Failed-login state is unavailable')
        if optional:
            return False
        raise RequestError(503, 'Sign-in is temporarily unavailable') from error
