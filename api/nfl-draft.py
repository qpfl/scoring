"""Vercel Serverless Function for the NFL Draft Challenge."""

import base64
import json
import os
import re
import time
import unicodedata
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError

GITHUB_OWNER = os.environ.get('REPO_OWNER') or os.environ.get('GITHUB_OWNER', 'griffin')
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'scoring')
GITHUB_BRANCH = os.environ.get('GITHUB_BRANCH', 'main')

CHALLENGE_FILE_PATH = 'data/nfl_draft_challenge.json'
DEFAULT_LOCK_TIME = '2026-04-24T00:00:00Z'
PICK_COUNT = 32
MAX_PLAYER_NAME_LEN = 80


def get_team_password(team_abbrev: str) -> str | None:
    env_key = f'TEAM_PASSWORD_{team_abbrev.replace("/", "_")}'
    return os.environ.get(env_key)


def github_headers(github_token: str) -> dict:
    return {
        'Authorization': f'Bearer {github_token}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
        'User-Agent': 'QPFL-NFL-Draft-Bot',
    }


def fetch_challenge_file(github_token: str) -> tuple[dict, str | None]:
    """Return (contents, sha). Falls back to a default skeleton if file is missing."""
    api_url = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{CHALLENGE_FILE_PATH}'
    try:
        req = urllib.request.Request(api_url, headers=github_headers(github_token))
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
        sha = data['sha']
        content = json.loads(base64.b64decode(data['content']).decode())
        return content, sha
    except HTTPError as e:
        if e.code == 404:
            return (
                {
                    'lock_time': DEFAULT_LOCK_TIME,
                    'actual_picks': [],
                    'picks_by_team': {},
                    'updated_at': None,
                },
                None,
            )
        raise


def update_challenge_file(
    team: str,
    picks: list,
    github_token: str,
    max_retries: int = 3,
    clear: bool = False,
) -> tuple[bool, str]:
    """Merge this team's picks into data/nfl_draft_challenge.json with SHA retry.

    When clear=True, remove the team's entry entirely instead of writing picks.
    """
    api_url = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{CHALLENGE_FILE_PATH}'
    headers = github_headers(github_token)

    for attempt in range(max_retries):
        try:
            content, current_sha = fetch_challenge_file(github_token)
        except HTTPError as e:
            return False, f'Failed to fetch challenge file: {e}'

        lock_time_str = content.get('lock_time') or DEFAULT_LOCK_TIME
        try:
            lock_dt = datetime.fromisoformat(lock_time_str.replace('Z', '+00:00'))
        except ValueError:
            return False, 'Challenge file has an invalid lock_time'

        if datetime.now(tz=timezone.utc) >= lock_dt:
            return False, 'Picks are locked — the NFL draft has started'

        content.setdefault('picks_by_team', {})
        if clear:
            if team in content['picks_by_team']:
                del content['picks_by_team'][team]
        else:
            content['picks_by_team'][team] = {
                'picks': picks,
                'submitted_at': datetime.now(timezone.utc).isoformat(),
            }
        content['updated_at'] = datetime.now(timezone.utc).isoformat()

        new_content = base64.b64encode(json.dumps(content, separators=(',', ':')).encode()).decode()

        commit_message = (
            f'Clear {team} NFL Draft Challenge picks'
            if clear
            else f'Update {team} NFL Draft Challenge picks'
        )
        update_data = {
            'message': commit_message,
            'content': new_content,
            'branch': GITHUB_BRANCH,
        }
        if current_sha:
            update_data['sha'] = current_sha

        try:
            req = urllib.request.Request(
                api_url, data=json.dumps(update_data).encode(), headers=headers, method='PUT'
            )
            with urllib.request.urlopen(req) as response:
                if response.status in [200, 201]:
                    return True, 'Picks saved'
                return False, f'GitHub API returned status {response.status}'
        except HTTPError as e:
            if e.code == 409 and attempt < max_retries - 1:
                time.sleep(0.5 * (attempt + 1))
                continue
            error_body = e.read().decode() if hasattr(e, 'read') else str(e)
            return False, f'Failed to update picks: {error_body}'

    return False, 'Failed to update picks after max retries'


_SUFFIXES = {'jr', 'sr', 'ii', 'iii', 'iv', 'v'}


def normalize_name(name: str) -> str:
    if not name:
        return ''
    decomposed = unicodedata.normalize('NFKD', name)
    ascii_name = ''.join(c for c in decomposed if not unicodedata.combining(c))
    lowered = ascii_name.lower()
    cleaned = re.sub(r"[^\w\s]", ' ', lowered)
    tokens = [t for t in cleaned.split() if t not in _SUFFIXES]
    return ' '.join(tokens)


def compute_scores(actual_picks: list, picks_by_team: dict) -> dict:
    """Return {team_abbrev: {points, correct}} given actual picks and submissions."""
    actual_by_num = {}
    for entry in actual_picks or []:
        try:
            pick_num = int(entry.get('pick'))
        except (TypeError, ValueError):
            continue
        player_norm = normalize_name(entry.get('player', ''))
        if player_norm:
            actual_by_num[pick_num] = player_norm

    scores: dict = {}
    for team, payload in (picks_by_team or {}).items():
        picks = payload.get('picks') if isinstance(payload, dict) else payload
        total = 0
        correct = 0
        for p in picks or []:
            try:
                pick_num = int(p.get('pick'))
            except (TypeError, ValueError):
                continue
            if pick_num < 1 or pick_num > PICK_COUNT:
                continue
            guess_norm = normalize_name(p.get('player', ''))
            if not guess_norm:
                continue
            actual_norm = actual_by_num.get(pick_num)
            if actual_norm and guess_norm == actual_norm:
                total += pick_num if pick_num <= 9 else 10
                correct += 1
        scores[team] = {'points': total, 'correct': correct}
    return scores


def validate_picks_payload(raw_picks) -> tuple[list | None, str | None]:
    if not isinstance(raw_picks, list):
        return None, 'picks must be a list'
    seen = set()
    cleaned = []
    for entry in raw_picks:
        if not isinstance(entry, dict):
            return None, 'Each pick must be an object'
        try:
            pick_num = int(entry.get('pick'))
        except (TypeError, ValueError):
            return None, 'Each pick needs an integer "pick" field'
        if pick_num < 1 or pick_num > PICK_COUNT:
            return None, f'pick must be between 1 and {PICK_COUNT}'
        if pick_num in seen:
            return None, f'Duplicate pick number: {pick_num}'
        seen.add(pick_num)
        player = (entry.get('player') or '').strip()
        if len(player) > MAX_PLAYER_NAME_LEN:
            return None, f'Player name too long at pick {pick_num}'
        cleaned.append({'pick': pick_num, 'player': player})
    cleaned.sort(key=lambda e: e['pick'])
    return cleaned, None


def build_state_response(content: dict, authed_team: str | None) -> dict:
    lock_time_str = content.get('lock_time') or DEFAULT_LOCK_TIME
    try:
        lock_dt = datetime.fromisoformat(lock_time_str.replace('Z', '+00:00'))
    except ValueError:
        lock_dt = datetime.fromisoformat(DEFAULT_LOCK_TIME.replace('Z', '+00:00'))
    locked = datetime.now(tz=timezone.utc) >= lock_dt

    picks_by_team = content.get('picks_by_team') or {}
    actual_picks = content.get('actual_picks') or []

    submissions = {}
    for team, payload in picks_by_team.items():
        submitted_at = payload.get('submitted_at') if isinstance(payload, dict) else None
        submissions[team] = {'submitted_at': submitted_at}

    visible_picks: dict = {}
    if locked:
        for team, payload in picks_by_team.items():
            visible_picks[team] = {
                'picks': payload.get('picks', []) if isinstance(payload, dict) else [],
                'submitted_at': payload.get('submitted_at') if isinstance(payload, dict) else None,
            }
    elif authed_team and authed_team in picks_by_team:
        payload = picks_by_team[authed_team]
        visible_picks[authed_team] = {
            'picks': payload.get('picks', []) if isinstance(payload, dict) else [],
            'submitted_at': payload.get('submitted_at') if isinstance(payload, dict) else None,
        }

    scores = compute_scores(actual_picks, picks_by_team) if locked else {}

    return {
        'lock_time': lock_time_str,
        'locked': locked,
        'pick_count': PICK_COUNT,
        'submissions': submissions,
        'visible_picks': visible_picks,
        'actual_picks': actual_picks if locked else [],
        'scores': scores,
        'authed_team': authed_team,
    }


class handler(BaseHTTPRequestHandler):  # noqa: N801
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.send_header('Access-Control-Max-Age', '86400')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({'status': 'API is running', 'method': 'GET'}).encode())

    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode()) if body else {}

            action = data.get('action', 'get_state')
            team = data.get('team')
            password = data.get('password')

            github_token = os.environ.get('SKYNET_PAT') or os.environ.get('GITHUB_TOKEN')

            authed_team = None
            if team and password:
                expected = get_team_password(team)
                if expected and password == expected:
                    authed_team = team

            if action == 'validate':
                if not team or not password:
                    return self._send_json(400, {'error': 'Missing team or password'})
                expected = get_team_password(team)
                if not expected:
                    return self._send_json(500, {'error': 'Team not configured'})
                if password != expected:
                    return self._send_json(401, {'error': 'Invalid password'})
                return self._send_json(200, {'success': True, 'message': 'Password valid'})

            if action == 'get_state':
                if not github_token:
                    return self._send_json(500, {'error': 'Server configuration error'})
                try:
                    content, _ = fetch_challenge_file(github_token)
                except HTTPError as e:
                    return self._send_json(500, {'error': f'Failed to load challenge file: {e}'})
                response = build_state_response(content, authed_team)
                return self._send_json(200, response)

            if action == 'clear':
                if not team or not password:
                    return self._send_json(400, {'error': 'Missing team or password'})
                expected = get_team_password(team)
                if not expected:
                    return self._send_json(500, {'error': 'Team not configured'})
                if password != expected:
                    return self._send_json(401, {'error': 'Invalid password'})

                if not github_token:
                    return self._send_json(500, {'error': 'Server configuration error'})

                success, message = update_challenge_file(team, [], github_token, clear=True)
                if not success:
                    return self._send_json(500, {'error': message})

                try:
                    content, _ = fetch_challenge_file(github_token)
                except HTTPError:
                    return self._send_json(200, {'success': True, 'message': 'Entry cleared'})
                response = build_state_response(content, team)
                response['success'] = True
                response['message'] = 'Entry cleared'
                return self._send_json(200, response)

            if action == 'submit':
                if not team or not password:
                    return self._send_json(400, {'error': 'Missing team or password'})
                expected = get_team_password(team)
                if not expected:
                    return self._send_json(500, {'error': 'Team not configured'})
                if password != expected:
                    return self._send_json(401, {'error': 'Invalid password'})

                cleaned, err = validate_picks_payload(data.get('picks'))
                if err:
                    return self._send_json(400, {'error': err})

                if not github_token:
                    return self._send_json(500, {'error': 'Server configuration error'})

                success, message = update_challenge_file(team, cleaned, github_token)
                if not success:
                    return self._send_json(500, {'error': message})

                try:
                    content, _ = fetch_challenge_file(github_token)
                except HTTPError:
                    return self._send_json(200, {'success': True, 'message': message})
                response = build_state_response(content, team)
                response['success'] = True
                response['message'] = message
                return self._send_json(200, response)

            return self._send_json(400, {'error': f'Unknown action: {action}'})

        except json.JSONDecodeError:
            return self._send_json(400, {'error': 'Invalid JSON'})
        except Exception as e:
            return self._send_json(500, {'error': str(e)})

    def _send_json(self, status_code: int, data: dict):
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        pass
