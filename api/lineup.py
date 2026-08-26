"""Vercel serverless function for authoritative lineup submissions."""

import base64
import hmac
import json
import logging
import os
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError

from api.request_util import RequestError, handle_options, read_json_body, request_id, send_json

GITHUB_OWNER = os.environ.get('REPO_OWNER') or os.environ.get('GITHUB_OWNER', 'griffin')
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'scoring')
GITHUB_BRANCH = os.environ.get('GITHUB_BRANCH', 'main')
CURRENT_SEASON = 2026
VALID_POSITIONS = ['QB', 'RB', 'WR', 'TE', 'K', 'D/ST', 'HC', 'OL']
MAX_STARTERS = {'QB': 1, 'RB': 2, 'WR': 2, 'TE': 1, 'K': 1, 'D/ST': 1, 'HC': 1, 'OL': 1}
_NFL_TEAM_ALIASES = {'LAR': 'LA', 'JAC': 'JAX'}
logger = logging.getLogger(__name__)


class GitHubReadError(RuntimeError):
    def __init__(self, path: str, kind: str, status: int | None = None):
        super().__init__(f'{kind} error reading {path}')
        self.path = path
        self.kind = kind
        self.status = status


@dataclass(frozen=True)
class LineupContext:
    site: dict
    rosters: dict
    active_roster: set[tuple[str, str]]
    all_players: list[dict]
    lineup_week: int
    kickoffs: dict[str, datetime]


def get_team_password(team_abbrev: str) -> str | None:
    env_key = f'TEAM_PASSWORD_{team_abbrev.replace("/", "_")}'
    return os.environ.get(env_key)


def _github_get_json(path: str, github_token: str, *, optional: bool = False):
    """Fetch a GitHub JSON file; return ``None`` only for an optional 404."""
    api_url = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}'
    headers = {
        'Authorization': f'Bearer {github_token}',
        'Accept': 'application/vnd.github.v3+json',
        'User-Agent': 'QPFL-Lineup-Bot',
    }
    request = urllib.request.Request(api_url, headers=headers)
    try:
        with urllib.request.urlopen(request) as response:
            result = json.loads(response.read().decode())
        return json.loads(base64.b64decode(result['content']).decode())
    except HTTPError as error:
        if optional and error.code == 404:
            return None
        raise GitHubReadError(path, 'http', error.code) from error
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise GitHubReadError(path, 'decode') from error
    except Exception as error:
        raise GitHubReadError(path, 'transport') from error


def validate_submission(week, starters) -> tuple[int, dict[str, list[str]]]:
    if isinstance(week, bool) or not isinstance(week, int) or not 1 <= week <= 17:
        raise ValueError('Week must be an integer from 1 through 17')
    if not isinstance(starters, dict) or not starters:
        raise ValueError('Starters must be a nonempty object')

    validated = {}
    seen = set()
    for position, players in starters.items():
        if position not in VALID_POSITIONS:
            raise ValueError(f'Invalid position: {position}')
        if not isinstance(players, list):
            raise ValueError(f'Starters for {position} must be a list')
        if len(players) > MAX_STARTERS[position]:
            raise ValueError(f'Too many starters for {position}')
        clean_players = []
        for player in players:
            if not isinstance(player, str) or not player.strip():
                raise ValueError('Starter names must be nonempty text')
            name = player.strip()
            if name in seen:
                raise ValueError(f'Duplicate starter: {name}')
            seen.add(name)
            clean_players.append(name)
        validated[position] = clean_players
    return week, validated


def _parse_kickoffs(raw) -> dict[str, datetime]:
    if not isinstance(raw, dict) or not raw:
        raise ValueError('kickoff data is unavailable')
    parsed = {}
    for nfl_team, value in raw.items():
        if not isinstance(nfl_team, str) or not isinstance(value, str):
            raise ValueError('kickoff data is malformed')
        try:
            kickoff = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError as error:
            raise ValueError('kickoff data is malformed') from error
        if kickoff.tzinfo is None:
            raise ValueError('kickoff data is malformed')
        parsed[nfl_team] = kickoff
    return parsed


def load_lineup_context(
    week: int, team: str, github_token: str
) -> tuple[LineupContext | None, str | None, int | None]:
    try:
        site = _github_get_json('web/data.json', github_token)
        rosters = _github_get_json('data/rosters.json', github_token)
    except GitHubReadError:
        logger.exception('Could not load lineup context')
        return None, 'League lineup context is unavailable', 503

    if not isinstance(site, dict) or not isinstance(rosters, dict):
        return None, 'League lineup context is unavailable', 503
    if site.get('season') != CURRENT_SEASON:
        return None, 'League lineup context is stale', 503

    schedule = site.get('schedule')
    if not isinstance(schedule, list) or not any(
        isinstance(entry, dict) and entry.get('week') == week for entry in schedule
    ):
        return None, 'Week is not present in the league schedule', 400

    lineup_week = site.get('lineup_week', site.get('current_week'))
    if (
        isinstance(lineup_week, bool)
        or not isinstance(lineup_week, int)
        or not 1 <= lineup_week <= 17
    ):
        return None, 'League lineup context is unavailable', 503
    if week < lineup_week:
        return None, 'Past-week lineups can no longer be changed', 409

    team_data = rosters.get(team)
    if isinstance(team_data, list):
        all_players = team_data
        active_players = [player for player in team_data if not player.get('taxi', False)]
    elif isinstance(team_data, dict):
        active_players = team_data.get('roster')
        taxi_players = team_data.get('taxi_squad', [])
        if not isinstance(active_players, list) or not isinstance(taxi_players, list):
            return None, 'League roster data is unavailable', 503
        all_players = active_players + taxi_players
    else:
        return None, 'League roster data is unavailable', 503

    if any(
        not isinstance(player, dict)
        or not isinstance(player.get('name'), str)
        or player.get('position') not in VALID_POSITIONS
        for player in all_players
    ):
        return None, 'League roster data is unavailable', 503
    active_roster = {(player['name'], player['position']) for player in active_players}

    kickoffs = {}
    if week == lineup_week:
        try:
            kickoffs = _parse_kickoffs(site.get('kickoffs'))
        except ValueError:
            return None, 'Kickoff data is unavailable; lineup changes are temporarily closed', 503

    return (
        LineupContext(site, rosters, active_roster, all_players, lineup_week, kickoffs),
        None,
        None,
    )


def _locked_players(context: LineupContext, week: int) -> set[str]:
    if week != context.lineup_week:
        return set()
    now = datetime.now(timezone.utc)
    locked = set()
    for player in context.all_players:
        nfl_team = player.get('nfl_team')
        if not nfl_team:
            continue
        kickoff = context.kickoffs.get(nfl_team) or context.kickoffs.get(
            _NFL_TEAM_ALIASES.get(nfl_team, '')
        )
        if kickoff is not None and kickoff <= now:
            locked.add(player['name'])
    return locked


def get_locked_players(week: int, team: str, github_token: str) -> set[str]:
    context, message, _ = load_lineup_context(week, team, github_token)
    if context is None:
        raise GitHubReadError('lineup context', message or 'unavailable')
    return _locked_players(context, week)


def update_lineup_file(
    week: int,
    team: str,
    starters: dict,
    github_token: str,
    locked_players: list | None = None,
    comment: str | None = None,
    max_retries: int = 3,
) -> tuple[bool, str, int]:
    """Validate against one context snapshot and update a lineup with SHA retries."""
    del locked_players
    try:
        week, starters = validate_submission(week, starters)
    except ValueError as error:
        return False, str(error), 400

    context, message, status = load_lineup_context(week, team, github_token)
    if context is None:
        return False, message or 'League lineup context is unavailable', status or 503

    invalid = [
        name
        for position, names in starters.items()
        for name in names
        if (name, position) not in context.active_roster
    ]
    if invalid:
        return (
            False,
            'These players are not on your active roster at the submitted position: '
            + ', '.join(invalid),
            400,
        )

    file_path = f'data/lineups/{CURRENT_SEASON}/week_{week}.json'
    api_url = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{file_path}'
    headers = {
        'Authorization': f'Bearer {github_token}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
        'User-Agent': 'QPFL-Lineup-Bot',
    }
    server_locked = _locked_players(context, week)

    for attempt in range(max_retries):
        current_sha = None
        content = {'week': week, 'lineups': {}}
        try:
            request = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(request) as response:
                current_data = json.loads(response.read().decode())
                current_sha = current_data['sha']
                content = json.loads(base64.b64decode(current_data['content']).decode())
        except HTTPError as error:
            if error.code != 404:
                return False, 'Lineup storage is temporarily unavailable', 503
        except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return False, 'Saved lineup data is malformed', 503

        lineups = content.get('lineups')
        if not isinstance(lineups, dict):
            return False, 'Saved lineup data is malformed', 503
        current_team_lineup = lineups.get(team, {})
        if not isinstance(current_team_lineup, dict):
            return False, 'Saved lineup data is malformed', 503

        working_starters = {position: list(names) for position, names in starters.items()}
        if server_locked:
            for position in VALID_POSITIONS:
                saved = current_team_lineup.get(position, [])
                if not isinstance(saved, list) or any(not isinstance(name, str) for name in saved):
                    return False, 'Saved lineup data is malformed', 503
            for player in server_locked:
                saved_positions = {
                    position
                    for position in VALID_POSITIONS
                    if player in current_team_lineup.get(position, [])
                }
                submitted_positions = {
                    position
                    for position in VALID_POSITIONS
                    if player in working_starters.get(position, [])
                }
                if saved_positions != submitted_positions:
                    return False, f'{player} is locked because their game has started', 409

        working_starters['submitted_at'] = datetime.now(timezone.utc).isoformat()
        if comment:
            working_starters['comment'] = comment
        content['lineups'][team] = working_starters
        encoded = base64.b64encode(json.dumps(content, separators=(',', ':')).encode()).decode()
        update_data = {
            'message': f'Update {team} lineup for Week {week}',
            'content': encoded,
            'branch': GITHUB_BRANCH,
        }
        if current_sha:
            update_data['sha'] = current_sha

        try:
            request = urllib.request.Request(
                api_url,
                data=json.dumps(update_data).encode(),
                headers=headers,
                method='PUT',
            )
            with urllib.request.urlopen(request) as response:
                if response.status in (200, 201):
                    return True, 'Lineup updated successfully', 200
                return False, 'Lineup storage is temporarily unavailable', 503
        except HTTPError as error:
            if error.code == 409 and attempt + 1 < max_retries:
                time.sleep(0.5 * (attempt + 1))
                continue
            return False, 'Lineup storage is temporarily unavailable', 503

    return False, 'Lineup update conflicted too many times', 503


class handler(BaseHTTPRequestHandler):  # noqa: N801
    def do_OPTIONS(self):
        handle_options(self)

    def do_GET(self):
        self._send_json(200, {'status': 'API is running', 'method': 'GET'})

    def do_POST(self):
        try:
            data = read_json_body(self)

            action = data.get('action', 'submit')
            team = data.get('team')
            password = data.get('password')
            if not isinstance(team, str) or not password:
                return self._send_json(400, {'error': 'Missing team or password'})

            expected_password = get_team_password(team)
            if not expected_password:
                return self._send_json(500, {'error': 'Team not configured'})
            if not hmac.compare_digest(str(password), expected_password):
                return self._send_json(401, {'error': 'Invalid password'})
            if action == 'validate':
                return self._send_json(200, {'success': True, 'message': 'Password valid'})

            try:
                week, starters = validate_submission(data.get('week'), data.get('starters'))
            except ValueError as error:
                return self._send_json(400, {'error': str(error)})
            comment = data.get('comment', '')
            if not isinstance(comment, str) or len(comment) > 500:
                return self._send_json(400, {'error': 'Invalid comment'})
            comment = comment.strip()

            github_token = os.environ.get('SKYNET_PAT') or os.environ.get('GITHUB_TOKEN')
            if not github_token:
                return self._send_json(500, {'error': 'Server configuration error'})
            success, message, status_code = update_lineup_file(
                week, team, starters, github_token, comment=comment
            )
            if success:
                return self._send_json(200, {'success': True, 'message': message})
            return self._send_json(status_code, {'error': message})
        except RequestError as error:
            return self._send_json(error.status, {'error': error.message})
        except (TypeError, ValueError):
            return self._send_json(400, {'error': 'Invalid request'})
        except Exception:
            incident = request_id()
            logger.exception('Unexpected lineup API failure request_id=%s', incident)
            return self._send_json(
                500, {'error': 'Unexpected server error', 'request_id': incident}
            )

    def _send_json(self, status_code: int, data: dict):
        send_json(self, status_code, data)

    def log_message(self, format, *args):
        pass
