"""Vercel function for authenticated QPFL superlative voting."""

import base64
import copy
import hmac
import json
import os
import time
import urllib.request
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError

GITHUB_OWNER = os.environ.get('REPO_OWNER') or os.environ.get('GITHUB_OWNER', 'griffin')
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'scoring')
GITHUB_BRANCH = os.environ.get('GITHUB_BRANCH', 'main')
LORE_PATH = 'data/league_lore.json'


class LoreError(Exception):
    def __init__(self, status: int, body: dict):
        super().__init__(body.get('error', 'error'))
        self.status = status
        self.body = body


def _github_headers() -> dict | None:
    token = os.environ.get('SKYNET_PAT') or os.environ.get('GITHUB_TOKEN')
    if not token:
        return None
    return {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
        'User-Agent': 'QPFL-Lore-Bot',
    }


def github_get_file(path: str):
    headers = _github_headers()
    if headers is None:
        raise RuntimeError('Server configuration error - no GitHub token')
    url = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}'
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request) as response:
            result = json.loads(response.read().decode())
        content = json.loads(base64.b64decode(result['content']).decode())
        return result['sha'], content
    except HTTPError as error:
        if error.code == 404:
            return None, None
        raise


def github_put_file(path: str, content: dict, message: str, sha: str | None) -> None:
    headers = _github_headers()
    if headers is None:
        raise RuntimeError('Server configuration error - no GitHub token')
    url = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}'
    payload: dict[str, object] = {
        'message': message,
        'content': base64.b64encode(json.dumps(content, separators=(',', ':')).encode()).decode(),
        'branch': GITHUB_BRANCH,
    }
    if sha:
        payload['sha'] = sha
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers=headers,
        method='PUT',
    )
    with urllib.request.urlopen(request):
        return


def update_lore(mutate, message: str, max_retries: int = 5):
    for attempt in range(max_retries):
        try:
            sha, content = github_get_file(LORE_PATH)
        except Exception as error:
            return False, f'Failed to read {LORE_PATH}: {error}'
        if content is None:
            content = {
                'rivalries': [],
                'moments': [],
                'season_notes': {},
                'superlative_ballots': [],
                'superlatives': [],
            }
        try:
            updated, result = mutate(copy.deepcopy(content))
        except LoreError as error:
            return False, error
        try:
            github_put_file(LORE_PATH, updated, message, sha)
            return True, result
        except HTTPError as error:
            if error.code == 409 and attempt < max_retries - 1:
                time.sleep(0.5 * (attempt + 1))
                continue
            return False, f'GitHub API error: {error}'
        except Exception as error:
            return False, str(error)
    return False, f'Failed to update {LORE_PATH} after {max_retries} attempts'


def get_team_password(team: str) -> str | None:
    return os.environ.get(f'TEAM_PASSWORD_{team.replace("/", "_")}')


def validate_team(team: str, password: str) -> tuple[bool, str]:
    if not isinstance(team, str) or not isinstance(password, str) or not team or not password:
        return False, 'Missing team or password'
    expected = get_team_password(team)
    if not expected:
        return False, 'Team not configured'
    if not hmac.compare_digest(str(password), expected):
        return False, 'Invalid password'
    return True, 'Valid'


def handle_superlative_vote(data: dict) -> tuple[int, dict]:
    team = data.get('team')
    password = data.get('password')
    season = data.get('season')
    category_id = data.get('category')
    nominee_id = data.get('nominee')
    valid, message = validate_team(team, password)
    if not valid:
        return 401, {'error': message}
    if not isinstance(season, int) or isinstance(season, bool):
        return 400, {'error': 'A numeric season is required'}
    if not isinstance(category_id, str) or not category_id:
        return 400, {'error': 'A category is required'}
    if nominee_id is not None and not isinstance(nominee_id, str):
        return 400, {'error': 'Nominee must be a string or null'}

    def mutate(content):
        ballot = next(
            (
                item
                for item in content.get('superlative_ballots', [])
                if item.get('season') == season
            ),
            None,
        )
        if not ballot:
            raise LoreError(404, {'error': 'Superlative ballot not found'})
        if ballot.get('status') != 'open':
            raise LoreError(409, {'error': 'This superlative ballot is not open'})
        category = next(
            (item for item in ballot.get('categories', []) if item.get('id') == category_id),
            None,
        )
        if not category:
            raise LoreError(404, {'error': 'Superlative category not found'})
        nominee_ids = {item.get('id') for item in category.get('nominees', [])}
        if nominee_id is not None and nominee_id not in nominee_ids:
            raise LoreError(400, {'error': 'Nominee is not on this ballot'})
        votes = category.setdefault('votes', {})
        if nominee_id is None:
            votes.pop(team, None)
        else:
            votes[team] = nominee_id
        return content, {'category': category_id, 'nominee': nominee_id}

    ok, result = update_lore(
        mutate,
        f'{season} superlative vote by {team}: {category_id}',
    )
    if not ok:
        if isinstance(result, LoreError):
            return result.status, result.body
        return 500, {'error': result}
    return 200, {'success': True, **result}


class handler(BaseHTTPRequestHandler):  # noqa: N801
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode()) if body else {}
            if data.get('action') == 'vote_superlative':
                status, result = handle_superlative_vote(data)
            else:
                status, result = 400, {'error': f"Unknown action: {data.get('action')}"}
            self._send_json(status, result)
        except json.JSONDecodeError:
            self._send_json(400, {'error': 'Invalid JSON'})
        except Exception as error:
            self._send_json(500, {'error': str(error)})

    def _send_json(self, status_code: int, data: dict):
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        pass
