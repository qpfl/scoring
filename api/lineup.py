"""Vercel Serverless Function for lineup submissions."""

import base64
import json
import os
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError

# GitHub repo info
GITHUB_OWNER = os.environ.get('REPO_OWNER') or os.environ.get('GITHUB_OWNER', 'griffin')
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'scoring')
GITHUB_BRANCH = os.environ.get('GITHUB_BRANCH', 'main')

# Updated automatically by scripts/create_new_season.py during the season
# transition. Lineups MUST be written under the current season so the scorer
# (which reads data/lineups/{season}/) picks them up.
CURRENT_SEASON = 2026


def get_team_password(team_abbrev: str) -> str | None:
    """Get the password for a team from environment variables."""
    env_key = f'TEAM_PASSWORD_{team_abbrev.replace("/", "_")}'
    return os.environ.get(env_key)


# Roster nfl_team values vs. nflverse schedule abbreviations.
_NFL_TEAM_ALIASES = {'LAR': 'LA', 'JAC': 'JAX'}


def _github_get_json(path: str, github_token: str):
    """Fetch and decode a JSON file from the repo, or None if missing/unreadable."""
    api_url = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}'
    headers = {
        'Authorization': f'Bearer {github_token}',
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'QPFL-Lineup-Bot',
    }
    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode())
        return json.loads(base64.b64decode(result['content']).decode())
    except Exception:
        return None


def get_locked_players(week: int, team: str, github_token: str) -> set:
    """Players on `team` whose NFL game has already kicked off for `week`.

    This is the authoritative, server-side lineup lock: lock state is derived
    from kickoff times published in web/data.json by the export pipeline, NOT
    from a client-supplied list (which a manager could simply omit). A locked
    player can't be added to or removed from the starting lineup.

    Fails open (returns an empty set) when kickoff data or rosters are
    unavailable — e.g. the offseason, or before the first export of a week — so
    it never wrongly blocks a legitimate submission.
    """
    site = _github_get_json('web/data.json', github_token)
    if not isinstance(site, dict):
        return set()
    # Only the current week is live; past weeks are already scored and locked,
    # future weeks haven't kicked off.
    if site.get('current_week') != week:
        return set()
    kickoffs = site.get('kickoffs') or {}
    if not kickoffs:
        return set()

    rosters = _github_get_json('data/rosters.json', github_token)
    if not isinstance(rosters, dict):
        return set()

    team_data = rosters.get(team, [])
    players = team_data if isinstance(team_data, list) else (
        team_data.get('roster', []) + team_data.get('taxi_squad', [])
    )

    now = datetime.now(timezone.utc)
    locked = set()
    for p in players:
        nfl_team = p.get('nfl_team')
        if not nfl_team:
            continue
        kickoff = kickoffs.get(nfl_team) or kickoffs.get(_NFL_TEAM_ALIASES.get(nfl_team, ''))
        if not kickoff:
            continue
        try:
            kickoff_dt = datetime.fromisoformat(kickoff.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            continue
        if kickoff_dt <= now:
            locked.add(p['name'])
    return locked


def update_lineup_file(
    week: int,
    team: str,
    starters: dict,
    github_token: str,
    locked_players: list = None,
    comment: str = None,
    max_retries: int = 3,
) -> tuple[bool, str]:
    """Update the lineup file in the GitHub repo with retry logic for concurrent updates."""
    import time

    file_path = f'data/lineups/{CURRENT_SEASON}/week_{week}.json'
    api_url = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{file_path}'

    headers = {
        'Authorization': f'Bearer {github_token}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
        'User-Agent': 'QPFL-Lineup-Bot',
    }

    # Authoritative server-side lock: players whose games have started can't be
    # added or dropped, regardless of the client-supplied locked_players list.
    # Computed once up front — kickoff times don't change between retries.
    server_locked = get_locked_players(week, team, github_token)

    # Retry loop for handling concurrent updates (409 Conflict)
    for attempt in range(max_retries):
        current_sha = None
        content = {'week': week, 'lineups': {}}
        current_team_lineup = {}

        try:
            req = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(req) as response:
                current_data = json.loads(response.read().decode())
                current_sha = current_data['sha']
                content = json.loads(base64.b64decode(current_data['content']).decode())
                current_team_lineup = content.get('lineups', {}).get(team, {})
        except HTTPError as e:
            if e.code != 404:
                return False, f'Failed to fetch current lineup: {e}'

        # Locked players: the server-derived set (kickoff-based) is authoritative;
        # the client list is merged in only as a hint.
        locked_set = set(locked_players or []) | server_locked

        working_starters = starters.copy()

        # Locked players keep whatever the saved lineup had and can't be added or
        # removed. Applied even with no prior lineup, so a manager can't first-set
        # a player whose game already kicked off.
        if locked_set:
            final_starters = {}
            for pos in ['QB', 'RB', 'WR', 'TE', 'K', 'D/ST', 'HC', 'OL']:
                current_pos_starters = set(current_team_lineup.get(pos, []))
                new_pos_starters = set(working_starters.get(pos, []))

                final_pos = []
                for player in current_pos_starters:
                    if player in locked_set:
                        final_pos.append(player)

                for player in new_pos_starters:
                    if player not in locked_set and player not in final_pos:
                        final_pos.append(player)

                final_starters[pos] = final_pos

            working_starters = final_starters

        # Add timestamp and comment to the lineup
        working_starters['submitted_at'] = datetime.now(timezone.utc).isoformat()
        if comment:
            working_starters['comment'] = comment

        content['lineups'][team] = working_starters

        new_content = base64.b64encode(json.dumps(content, separators=(',', ':')).encode()).decode()

        update_data = {
            'message': f'Update {team} lineup for Week {week}',
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
                    return True, 'Lineup updated successfully'
                else:
                    return False, f'GitHub API returned status {response.status}'
        except HTTPError as e:
            if e.code == 409 and attempt < max_retries - 1:
                # Conflict - another update happened, retry with fresh SHA
                print(f'Conflict updating lineup, retrying ({attempt + 1}/{max_retries})...')
                time.sleep(0.5 * (attempt + 1))  # Exponential backoff
                continue
            else:
                error_body = e.read().decode() if hasattr(e, 'read') else str(e)
                return False, f'Failed to update lineup: {error_body}'

    return False, 'Failed to update lineup after max retries'


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
        self.wfile.write(json.dumps({'status': 'API is running', 'method': 'GET'}).encode())

    def do_POST(self):
        """Handle lineup submission or password validation."""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode()) if body else {}

            action = data.get('action', 'submit')
            team = data.get('team')
            password = data.get('password')

            if not team or not password:
                return self._send_json(400, {'error': 'Missing team or password'})

            expected_password = get_team_password(team)
            if not expected_password:
                return self._send_json(500, {'error': 'Team not configured'})

            if password != expected_password:
                return self._send_json(401, {'error': 'Invalid password'})

            if action == 'validate':
                return self._send_json(200, {'success': True, 'message': 'Password valid'})

            week = data.get('week')
            starters = data.get('starters')
            locked_players = data.get('locked_players', [])
            comment = data.get('comment', '').strip()

            if not all([week, starters]):
                return self._send_json(400, {'error': 'Missing required fields for submission'})

            valid_positions = ['QB', 'RB', 'WR', 'TE', 'K', 'D/ST', 'HC', 'OL']
            max_starters = {'QB': 1, 'RB': 2, 'WR': 2, 'TE': 1, 'K': 1, 'D/ST': 1, 'HC': 1, 'OL': 1}

            for pos, players in starters.items():
                if pos not in valid_positions:
                    return self._send_json(400, {'error': f'Invalid position: {pos}'})
                if len(players) > max_starters.get(pos, 0):
                    return self._send_json(400, {'error': f'Too many starters for {pos}'})

            github_token = os.environ.get('SKYNET_PAT') or os.environ.get('GITHUB_TOKEN')
            if not github_token:
                return self._send_json(500, {'error': 'Server configuration error'})

            success, message = update_lineup_file(
                week, team, starters, github_token, locked_players, comment
            )

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
