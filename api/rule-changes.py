"""Vercel Serverless Function for rule change proposals (votes and comments)."""

import base64
import copy
import json
import os
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError

GITHUB_OWNER = os.environ.get('REPO_OWNER') or os.environ.get('GITHUB_OWNER', 'griffin')
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'scoring')
GITHUB_BRANCH = os.environ.get('GITHUB_BRANCH', 'main')

PROPOSALS_PATH = 'data/rule_proposals.json'


class RuleChangeError(Exception):
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
        'User-Agent': 'QPFL-RuleChange-Bot',
    }


def github_get_file(path: str):
    headers = _github_headers()
    if headers is None:
        raise RuntimeError('Server configuration error - no GitHub token')
    api_url = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}'
    req = urllib.request.Request(api_url, headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode())
        content = json.loads(base64.b64decode(result['content']).decode())
        return result['sha'], content
    except HTTPError as e:
        if e.code == 404:
            return None, None
        raise


def github_put_file(path: str, content_obj, message: str, sha: str | None) -> None:
    headers = _github_headers()
    if headers is None:
        raise RuntimeError('Server configuration error - no GitHub token')
    api_url = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}'
    update_data = {
        'message': message,
        'content': base64.b64encode(
            json.dumps(content_obj, separators=(',', ':')).encode()
        ).decode(),
        'branch': GITHUB_BRANCH,
    }
    if sha:
        update_data['sha'] = sha
    req = urllib.request.Request(
        api_url, data=json.dumps(update_data).encode(), headers=headers, method='PUT'
    )
    with urllib.request.urlopen(req):
        return


def update_json_file(path, mutate_fn, message, default=None, max_retries=5):
    for attempt in range(max_retries):
        try:
            sha, content = github_get_file(path)
        except Exception as e:
            return False, f'Failed to read {path}: {e}'

        if content is None:
            content = copy.deepcopy(default)

        try:
            new_content, extra = mutate_fn(content)
        except RuleChangeError as e:
            return False, e

        try:
            github_put_file(path, new_content, message, sha)
            return True, extra
        except HTTPError as e:
            if e.code == 409 and attempt < max_retries - 1:
                time.sleep(0.5 * (attempt + 1))
                continue
            error_body = e.read().decode() if hasattr(e, 'read') else str(e)
            return False, f'GitHub API error: {error_body}'
        except Exception as e:
            return False, str(e)

    return False, f'Failed to update {path} after {max_retries} attempts'


def get_team_password(team_abbrev: str) -> str | None:
    env_key = f'TEAM_PASSWORD_{team_abbrev.replace("/", "_")}'
    return os.environ.get(env_key)


def validate_team(team: str, password: str) -> tuple[bool, str]:
    if not team or not password:
        return False, 'Missing team or password'
    expected = get_team_password(team)
    if not expected:
        return False, 'Team not configured'
    if password != expected:
        return False, 'Invalid password'
    return True, 'Valid'


def handle_get_proposals() -> tuple[int, dict]:
    try:
        _sha, content = github_get_file(PROPOSALS_PATH)
    except Exception as e:
        return 500, {'error': str(e)}
    if content is None:
        return 200, {'proposals': []}
    return 200, content


def handle_vote(data: dict) -> tuple[int, dict]:
    team = data.get('team')
    password = data.get('password')
    proposal_id = data.get('id')
    vote = data.get('vote')

    valid, msg = validate_team(team, password)
    if not valid:
        return 401, {'error': msg}

    if not proposal_id:
        return 400, {'error': 'Missing proposal id'}
    if vote not in ('yes', 'no', None):
        return 400, {'error': 'Vote must be yes, no, or null to remove'}

    def mutate(content):
        if not isinstance(content, dict):
            raise RuleChangeError(500, {'error': 'Invalid proposals data'})
        proposals = content.get('proposals', [])
        proposal = next((p for p in proposals if p.get('id') == proposal_id), None)
        if not proposal:
            raise RuleChangeError(404, {'error': 'Proposal not found'})
        votes = proposal.setdefault('votes', {})
        if vote is None:
            votes.pop(team, None)
        else:
            votes[team] = vote
        return content, None

    ok, res = update_json_file(
        PROPOSALS_PATH, mutate, f'Vote on proposal {proposal_id} by {team}',
        default={'proposals': []}
    )
    if not ok:
        if isinstance(res, RuleChangeError):
            return res.status, res.body
        return 500, {'error': res}
    return 200, {'success': True}


def handle_comment(data: dict) -> tuple[int, dict]:
    team = data.get('team')
    password = data.get('password')
    proposal_id = data.get('id')
    text = (data.get('text') or '').strip()

    valid, msg = validate_team(team, password)
    if not valid:
        return 401, {'error': msg}

    if not proposal_id:
        return 400, {'error': 'Missing proposal id'}
    if not text:
        return 400, {'error': 'Comment text is required'}
    if len(text) > 2000:
        return 400, {'error': 'Comment must be under 2000 characters'}

    comment = {
        'author': team,
        'text': text,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }

    def mutate(content):
        if not isinstance(content, dict):
            raise RuleChangeError(500, {'error': 'Invalid proposals data'})
        proposals = content.get('proposals', [])
        proposal = next((p for p in proposals if p.get('id') == proposal_id), None)
        if not proposal:
            raise RuleChangeError(404, {'error': 'Proposal not found'})
        proposal.setdefault('comments', []).append(comment)
        return content, None

    ok, res = update_json_file(
        PROPOSALS_PATH, mutate, f'Comment on proposal {proposal_id} by {team}',
        default={'proposals': []}
    )
    if not ok:
        if isinstance(res, RuleChangeError):
            return res.status, res.body
        return 500, {'error': res}
    return 200, {'success': True, 'comment': comment}


def handle_propose(data: dict) -> tuple[int, dict]:
    team = data.get('team')
    password = data.get('password')
    title = (data.get('title') or '').strip()
    current = (data.get('current') or '').strip()
    description = (data.get('description') or '').strip()

    valid, msg = validate_team(team, password)
    if not valid:
        return 401, {'error': msg}

    if not title:
        return 400, {'error': 'Title is required'}
    if len(title) > 300:
        return 400, {'error': 'Title must be under 300 characters'}

    proposal = {
        'id': uuid.uuid4().hex[:10],
        'title': title,
        'current': current,
        'nominator': team,
        'proposed_at': datetime.now(timezone.utc).isoformat(),
        'votes': {},
        'comments': [],
    }
    if description:
        proposal['comments'].append({
            'author': team,
            'text': description,
            'timestamp': proposal['proposed_at'],
        })

    def mutate(content):
        if not isinstance(content, dict):
            content = {'proposals': []}
        content.setdefault('proposals', []).append(proposal)
        return content, None

    ok, res = update_json_file(
        PROPOSALS_PATH, mutate, f'New proposal by {team}: {title[:60]}',
        default={'proposals': []}
    )
    if not ok:
        if isinstance(res, RuleChangeError):
            return res.status, res.body
        return 500, {'error': res}
    return 200, {'success': True, 'proposal': proposal}


class handler(BaseHTTPRequestHandler):  # noqa: N801
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        action = params.get('action', [''])[0]
        if action == 'proposals':
            status, result = handle_get_proposals()
        else:
            status, result = 200, {'status': 'Rule Changes API is running'}
        self._send_json(status, result)

    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode()) if body else {}
            action = data.get('action')

            if action == 'vote':
                status, result = handle_vote(data)
            elif action == 'comment':
                status, result = handle_comment(data)
            elif action == 'propose':
                status, result = handle_propose(data)
            else:
                status, result = 400, {'error': f'Unknown action: {action}'}

            self._send_json(status, result)
        except json.JSONDecodeError:
            self._send_json(400, {'error': 'Invalid JSON'})
        except Exception as e:
            self._send_json(500, {'error': str(e)})

    def _send_json(self, status_code: int, data: dict):
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        pass
