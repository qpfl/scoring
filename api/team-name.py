"""Vercel serverless function for season-aware team name changes."""

import base64
import hmac
import json
import logging
import os
import urllib.request
from copy import deepcopy
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError

from api.request_util import RequestError, handle_options, read_json_body, request_id, send_json

GITHUB_OWNER = os.environ.get('REPO_OWNER') or os.environ.get('GITHUB_OWNER', 'griffin')
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'scoring')
GITHUB_BRANCH = os.environ.get('GITHUB_BRANCH', 'main')
VALID_TEAMS = {'GSA', 'WJK', 'RPA', 'S/T', 'CGK', 'AST', 'CWR', 'J/J', 'SLS', 'AYP'}
MAX_UPDATE_ATTEMPTS = 4
logger = logging.getLogger(__name__)


def normalize_team_name_history(raw) -> dict[str, list[dict]]:
    """Normalize legacy name entries without importing the excluded core package."""
    if not isinstance(raw, dict):
        return {}
    source = raw.get('team_names', raw)
    if not isinstance(source, dict):
        return {}

    normalized = {}
    for team, value in source.items():
        entries = [value] if isinstance(value, (str, dict)) else value
        if not isinstance(entries, list):
            continue
        team_entries = []
        for entry in entries:
            if isinstance(entry, str):
                entry = {'season': 2025, 'effective_week': 0, 'name': entry}
            if not isinstance(entry, dict):
                continue
            candidate = deepcopy(entry)
            candidate.setdefault('season', 2025)
            candidate.setdefault('effective_week', 0)
            team_entries.append(candidate)
        normalized[str(team)] = sorted(
            team_entries,
            key=lambda entry: (entry.get('season', 2025), entry.get('effective_week', 0)),
        )
    return normalized


def canonicalize_team_names(histories: dict[str, list[dict]]) -> dict:
    canonical = {}
    for team, entries in histories.items():
        if team not in VALID_TEAMS or not isinstance(entries, list):
            raise ValueError('invalid team-name history')
        canonical_entries = []
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {'season', 'effective_week', 'name'}:
                raise ValueError('invalid team-name entry')
            season = entry['season']
            week = entry['effective_week']
            if (
                isinstance(season, bool)
                or not isinstance(season, int)
                or not 2020 <= season <= 2100
            ):
                raise ValueError('invalid team-name season')
            if isinstance(week, bool) or not isinstance(week, int) or not 0 <= week <= 17:
                raise ValueError('invalid team-name week')
            canonical_entries.append(
                {'season': season, 'effective_week': week, 'name': validate_new_name(entry['name'])}
            )
        canonical[team] = canonical_entries
    return {'team_names': canonical}


def get_team_password(team_abbrev: str) -> str | None:
    env_key = f'TEAM_PASSWORD_{team_abbrev.replace("/", "_")}'
    return os.environ.get(env_key)


def _github_headers(github_token: str) -> dict[str, str]:
    return {
        'Authorization': f'Bearer {github_token}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
        'User-Agent': 'QPFL-TeamName-Bot',
    }


def _read_github_json(
    path: str, github_token: str, *, default: dict | None = None
) -> tuple[dict, str | None]:
    api_url = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}'
    request = urllib.request.Request(api_url, headers=_github_headers(github_token))
    try:
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode())
    except HTTPError as error:
        if error.code == 404 and default is not None:
            return default, None
        raise
    content = json.loads(base64.b64decode(payload['content']).decode())
    if not isinstance(content, dict):
        raise ValueError(f'{path} must contain a JSON object')
    return content, payload.get('sha')


def get_authoritative_effective_point(github_token: str) -> tuple[int, int]:
    config, _ = _read_github_json('data/league_config.json', github_token)
    season = config.get('current_season')
    is_offseason = config.get('is_offseason')
    if isinstance(season, bool) or not isinstance(season, int) or not 2020 <= season <= 2100:
        raise ValueError('invalid current season configuration')
    if not isinstance(is_offseason, bool):
        raise ValueError('invalid offseason configuration')
    if is_offseason:
        return season, 0

    site_data, _ = _read_github_json('web/data.json', github_token)
    week = site_data.get('current_week')
    if site_data.get('season') != season:
        raise ValueError('site data season is stale')
    if isinstance(week, bool) or not isinstance(week, int) or not 1 <= week <= 17:
        raise ValueError('invalid current week in site data')
    return season, week


def validate_new_name(value) -> str:
    if not isinstance(value, str):
        raise ValueError('Team name must be text')
    name = value.strip()
    if not name:
        raise ValueError('Missing new team name')
    if len(name) > 50:
        raise ValueError('Team name must be 50 characters or less')
    if '<' in name or '>' in name:
        raise ValueError('Team name cannot contain angle brackets')
    if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in name):
        raise ValueError('Team name cannot contain control characters')
    return name


def update_team_name_file(
    team: str,
    new_name: str,
    season: int,
    week: int,
    github_token: str,
) -> tuple[bool, str]:
    path = 'data/team_names.json'
    api_url = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}'

    for attempt in range(MAX_UPDATE_ATTEMPTS):
        try:
            content, current_sha = _read_github_json(path, github_token, default={'team_names': {}})
            histories = normalize_team_name_history(content)
            entries = [
                entry
                for entry in histories.get(team, [])
                if (entry.get('season'), entry.get('effective_week')) != (season, week)
            ]
            entries.append({'season': season, 'effective_week': week, 'name': new_name})
            histories[team] = sorted(
                entries, key=lambda entry: (entry['season'], entry['effective_week'])
            )
            canonical = canonicalize_team_names(histories)
            encoded = base64.b64encode(
                json.dumps(canonical, separators=(',', ':')).encode()
            ).decode()
            update_data = {
                'message': (
                    f"Update team name for {team} to '{new_name}' (effective {season} week {week})"
                ),
                'content': encoded,
                'branch': GITHUB_BRANCH,
            }
            if current_sha:
                update_data['sha'] = current_sha
            request = urllib.request.Request(
                api_url,
                data=json.dumps(update_data).encode(),
                headers=_github_headers(github_token),
                method='PUT',
            )
            with urllib.request.urlopen(request) as response:
                if response.status in (200, 201):
                    return True, 'Team name updated successfully'
                raise RuntimeError(f'unexpected GitHub status {response.status}')
        except HTTPError as error:
            if error.code == 409 and attempt + 1 < MAX_UPDATE_ATTEMPTS:
                continue
            logger.exception('GitHub rejected team-name update')
            break
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            logger.exception('Invalid team-name repository data')
            break
    return False, 'Unable to update team name right now'


class handler(BaseHTTPRequestHandler):  # noqa: N801
    def do_OPTIONS(self):
        handle_options(self)

    def do_GET(self):
        self._send_json(200, {'status': 'Team Name API is running', 'method': 'GET'})

    def do_POST(self):
        try:
            data = read_json_body(self)

            team = data.get('team')
            password = data.get('password')
            if not isinstance(team, str) or team not in VALID_TEAMS or not password:
                return self._send_json(400, {'error': 'Invalid team or password'})
            try:
                new_name = validate_new_name(data.get('newName'))
            except ValueError as error:
                return self._send_json(400, {'error': str(error)})

            expected_password = get_team_password(team)
            if not expected_password:
                return self._send_json(500, {'error': 'Team not configured'})
            if not hmac.compare_digest(str(password), expected_password):
                return self._send_json(401, {'error': 'Invalid password'})

            github_token = os.environ.get('SKYNET_PAT') or os.environ.get('GITHUB_TOKEN')
            if not github_token:
                return self._send_json(500, {'error': 'Server configuration error'})
            try:
                season, week = get_authoritative_effective_point(github_token)
            except (HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                logger.exception('Could not resolve authoritative team-name point')
                return self._send_json(503, {'error': 'League context is unavailable'})

            success, message = update_team_name_file(team, new_name, season, week, github_token)
            if success:
                return self._send_json(200, {'success': True, 'message': message})
            return self._send_json(503, {'error': message})
        except RequestError as error:
            return self._send_json(error.status, {'error': error.message})
        except (TypeError, ValueError):
            return self._send_json(400, {'error': 'Invalid request'})
        except Exception:
            incident = request_id()
            logger.exception('Unexpected team-name API failure request_id=%s', incident)
            return self._send_json(
                500, {'error': 'Unexpected server error', 'request_id': incident}
            )

    def _send_json(self, status_code: int, data: dict):
        send_json(self, status_code, data)

    def log_message(self, format, *args):
        pass
