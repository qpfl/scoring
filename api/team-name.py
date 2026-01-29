"""Vercel Serverless Function for team name changes."""

import base64
import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError

# GitHub repo info
GITHUB_OWNER = os.environ.get('REPO_OWNER') or os.environ.get('GITHUB_OWNER', 'griffin')
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'scoring')
GITHUB_BRANCH = os.environ.get('GITHUB_BRANCH', 'main')


def get_team_password(team_abbrev: str) -> str | None:
    """Get the password for a team from environment variables."""
    env_key = f'TEAM_PASSWORD_{team_abbrev.replace("/", "_")}'
    return os.environ.get(env_key)


def update_team_name_file(
    team: str, new_name: str, week: int, github_token: str
) -> tuple[bool, str]:
    """Update the team names file in the GitHub repo."""
    file_path = 'data/team_names.json'
    api_url = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{file_path}'

    headers = {
        'Authorization': f'Bearer {github_token}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
        'User-Agent': 'QPFL-TeamName-Bot',
    }

    current_sha = None
    content = {'team_names': {}}

    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req) as response:
            current_data = json.loads(response.read().decode())
            current_sha = current_data['sha']
            content = json.loads(base64.b64decode(current_data['content']).decode())
    except HTTPError as e:
        if e.code != 404:
            return False, f'Failed to fetch current team names: {e}'

    # Store team name with effective week
    if 'team_names' not in content:
        content['team_names'] = {}

    if team not in content['team_names']:
        content['team_names'][team] = []

    # Add the new name with effective week
    # Remove any existing entry for this week or later
    content['team_names'][team] = [
        entry for entry in content['team_names'][team] if entry.get('effective_week', 1) < week
    ]

    content['team_names'][team].append({'name': new_name, 'effective_week': week})

    # Sort by effective week
    content['team_names'][team].sort(key=lambda x: x.get('effective_week', 1))

    new_content = base64.b64encode(json.dumps(content, indent=2).encode()).decode()

    update_data = {
        'message': f"Update team name for {team} to '{new_name}' (effective week {week})",
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
                return True, 'Team name updated successfully'
            else:
                return False, f'GitHub API returned status {response.status}'
    except HTTPError as e:
        error_body = e.read().decode() if hasattr(e, 'read') else str(e)
        return False, f'Failed to update team name: {error_body}'


class handler(BaseHTTPRequestHandler):  # noqa: N801
    def do_OPTIONS(self):
        """Handle CORS preflight - no auth needed."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.send_header('Access-Control-Max-Age', '86400')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        """Handle GET requests - just for testing."""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(
            json.dumps({'status': 'Team Name API is running', 'method': 'GET'}).encode()
        )

    def do_POST(self):
        """Handle team name change."""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode()) if body else {}

            team = data.get('team')
            password = data.get('password')
            new_name = data.get('newName')
            week = data.get('week', 1)

            if not team or not password:
                return self._send_json(400, {'error': 'Missing team or password'})

            if not new_name:
                return self._send_json(400, {'error': 'Missing new team name'})

            if len(new_name) > 50:
                return self._send_json(400, {'error': 'Team name must be 50 characters or less'})

            expected_password = get_team_password(team)
            if not expected_password:
                return self._send_json(500, {'error': 'Team not configured'})

            if password != expected_password:
                return self._send_json(401, {'error': 'Invalid password'})

            github_token = os.environ.get('SKYNET_PAT') or os.environ.get('GITHUB_TOKEN')
            if not github_token:
                return self._send_json(500, {'error': 'Server configuration error'})

            success, message = update_team_name_file(team, new_name, week, github_token)

            if success:
                return self._send_json(200, {'success': True, 'message': message})
            else:
                return self._send_json(500, {'error': message})

        except json.JSONDecodeError:
            return self._send_json(400, {'error': 'Invalid JSON'})
        except Exception as e:
            return self._send_json(500, {'error': str(e)})

    def _send_json(self, status_code: int, data: dict):
        """Send JSON response with CORS headers."""
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass
