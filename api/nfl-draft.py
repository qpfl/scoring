"""Vercel Serverless Function for the NFL Draft Challenge."""

import base64
import hmac
import json
import logging
import os
import re
import time
import unicodedata
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError

from api.request_util import RequestError, handle_options, read_json_body, request_id, send_json

GITHUB_OWNER = os.environ.get('REPO_OWNER') or os.environ.get('GITHUB_OWNER', 'griffin')
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'scoring')
GITHUB_BRANCH = os.environ.get('GITHUB_BRANCH', 'main')

CHALLENGE_DIR = 'data/nfl_draft_challenges'
LEAGUE_CONFIG_PATH = 'data/league_config.json'
logger = logging.getLogger(__name__)


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


def fetch_repo_json(path: str, github_token: str) -> tuple[dict | None, str | None]:
    api_url = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}'
    try:
        req = urllib.request.Request(api_url, headers=github_headers(github_token))
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
        sha = data['sha']
        return json.loads(base64.b64decode(data['content']).decode()), sha
    except HTTPError as e:
        if e.code == 404:
            return None, None
        raise


def resolve_challenge_year(requested_year, github_token: str) -> int:
    if requested_year is None:
        league_config, _ = fetch_repo_json(LEAGUE_CONFIG_PATH, github_token)
        requested_year = (
            league_config.get('current_season') if isinstance(league_config, dict) else None
        )
    try:
        year = int(requested_year)
    except (TypeError, ValueError) as exc:
        raise ValueError('Challenge year is not configured') from exc
    if year < 2020 or year > 2100:
        raise ValueError('Challenge year must be between 2020 and 2100')
    return year


def validate_challenge_config(config: dict, year: int) -> dict:
    if not isinstance(config, dict) or config.get('year') != year:
        raise ValueError(f'{year} Draft Challenge configuration is missing or has the wrong year')
    if not config.get('enabled'):
        raise ValueError(f'{year} Draft Challenge is not enabled')
    if not isinstance(config.get('title'), str) or not config['title'].strip():
        raise ValueError('Draft Challenge title is required')
    try:
        lock_time = datetime.fromisoformat(config['lock_time'].replace('Z', '+00:00'))
    except (AttributeError, KeyError, ValueError) as exc:
        raise ValueError('Draft Challenge lock_time is invalid') from exc
    if lock_time.tzinfo is None:
        raise ValueError('Draft Challenge lock_time must include a timezone')
    pick_count = config.get('pick_count')
    if not isinstance(pick_count, int) or pick_count < 1 or pick_count > 256:
        raise ValueError('Draft Challenge pick_count must be between 1 and 256')
    max_name_length = config.get('max_player_name_length')
    if not isinstance(max_name_length, int) or max_name_length < 1 or max_name_length > 200:
        raise ValueError('Draft Challenge max_player_name_length must be between 1 and 200')
    scoring = config.get('scoring')
    if not isinstance(scoring, dict):
        raise ValueError('Draft Challenge scoring configuration is required')
    graduated_through = scoring.get('graduated_through_pick')
    flat_points = scoring.get('flat_points_after')
    if not isinstance(graduated_through, int) or not 0 <= graduated_through <= pick_count:
        raise ValueError('Draft Challenge graduated_through_pick is invalid')
    if not isinstance(flat_points, int) or flat_points < 0:
        raise ValueError('Draft Challenge flat_points_after is invalid')
    prospects = config.get('prospects')
    if not isinstance(prospects, list) or any(
        not isinstance(name, str) or not name.strip() or len(name) > max_name_length
        for name in prospects
    ):
        raise ValueError('Draft Challenge prospects must be a list of names')
    return config


def fetch_challenge_config(year: int, github_token: str) -> dict:
    config, _ = fetch_repo_json(f'{CHALLENGE_DIR}/{year}_config.json', github_token)
    return validate_challenge_config(config, year)


def fetch_challenge_file(year: int, github_token: str) -> tuple[dict, str | None]:
    content, sha = fetch_repo_json(f'{CHALLENGE_DIR}/{year}.json', github_token)
    if content is None:
        content = {
            'year': year,
            'actual_picks': [],
            'picks_by_team': {},
            'updated_at': None,
        }
    if not isinstance(content, dict) or content.get('year') != year:
        raise ValueError(f'{year} Draft Challenge state file has the wrong year')
    return content, sha


def update_challenge_file(
    year: int,
    team: str,
    picks: list,
    github_token: str,
    config: dict,
    max_retries: int = 3,
    clear: bool = False,
) -> tuple[bool, str]:
    """Merge this team's picks into the selected year's state file with SHA retry.

    When clear=True, remove the team's entry entirely instead of writing picks.
    """
    challenge_path = f'{CHALLENGE_DIR}/{year}.json'
    api_url = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{challenge_path}'
    headers = github_headers(github_token)

    for attempt in range(max_retries):
        try:
            content, current_sha = fetch_challenge_file(year, github_token)
        except (HTTPError, ValueError) as e:
            return False, f'Failed to fetch challenge file: {e}'

        lock_time_str = config['lock_time']
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
            f'Clear {team} {year} NFL Draft Challenge picks'
            if clear
            else f'Update {team} {year} NFL Draft Challenge picks'
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
    cleaned = re.sub(r'[^\w\s]', ' ', lowered)
    tokens = [t for t in cleaned.split() if t not in _SUFFIXES]
    return ' '.join(tokens)


def points_for_pick(pick_num: int, config: dict) -> int:
    scoring = config['scoring']
    if pick_num <= scoring['graduated_through_pick']:
        return pick_num
    return scoring['flat_points_after']


def compute_max_points(config: dict) -> int:
    return sum(points_for_pick(pick_num, config) for pick_num in range(1, config['pick_count'] + 1))


def compute_scores(actual_picks: list, picks_by_team: dict, config: dict) -> dict:
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
            if pick_num < 1 or pick_num > config['pick_count']:
                continue
            guess_norm = normalize_name(p.get('player', ''))
            if not guess_norm:
                continue
            actual_norm = actual_by_num.get(pick_num)
            if actual_norm and guess_norm == actual_norm:
                total += points_for_pick(pick_num, config)
                correct += 1
        scores[team] = {'points': total, 'correct': correct}
    return scores


def validate_picks_payload(raw_picks, config: dict) -> tuple[list | None, str | None]:
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
        if pick_num < 1 or pick_num > config['pick_count']:
            return None, f'pick must be between 1 and {config["pick_count"]}'
        if pick_num in seen:
            return None, f'Duplicate pick number: {pick_num}'
        seen.add(pick_num)
        player = (entry.get('player') or '').strip()
        if len(player) > config['max_player_name_length']:
            return None, f'Player name too long at pick {pick_num}'
        cleaned.append({'pick': pick_num, 'player': player})
    cleaned.sort(key=lambda e: e['pick'])
    return cleaned, None


def build_state_response(content: dict, config: dict, authed_team: str | None) -> dict:
    lock_time_str = config['lock_time']
    lock_dt = datetime.fromisoformat(lock_time_str.replace('Z', '+00:00'))
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

    scores = compute_scores(actual_picks, picks_by_team, config) if locked else {}

    return {
        'year': config['year'],
        'title': config['title'],
        'lock_time': lock_time_str,
        'locked': locked,
        'pick_count': config['pick_count'],
        'max_player_name_length': config['max_player_name_length'],
        'scoring': config['scoring'],
        'max_points': compute_max_points(config),
        'prospect_source': config.get('prospect_source'),
        'prospects': config['prospects'],
        'submissions': submissions,
        'visible_picks': visible_picks,
        'actual_picks': actual_picks if locked else [],
        'scores': scores,
        'authed_team': authed_team,
    }


class handler(BaseHTTPRequestHandler):  # noqa: N801
    def do_OPTIONS(self):
        handle_options(self)

    def do_GET(self):
        self._send_json(200, {'status': 'API is running', 'method': 'GET'})

    def do_POST(self):
        try:
            data = read_json_body(self)

            action = data.get('action', 'get_state')
            team = data.get('team')
            password = data.get('password')

            github_token = os.environ.get('SKYNET_PAT') or os.environ.get('GITHUB_TOKEN')

            authed_team = None
            if team and password:
                expected = get_team_password(team)
                if expected and hmac.compare_digest(str(password), expected):
                    authed_team = team

            if action == 'validate':
                if not team or not password:
                    return self._send_json(400, {'error': 'Missing team or password'})
                expected = get_team_password(team)
                if not expected:
                    return self._send_json(500, {'error': 'Team not configured'})
                if not hmac.compare_digest(str(password), expected):
                    return self._send_json(401, {'error': 'Invalid password'})
                return self._send_json(200, {'success': True, 'message': 'Password valid'})

            if action == 'get_state':
                if not github_token:
                    return self._send_json(500, {'error': 'Server configuration error'})
                try:
                    year = resolve_challenge_year(data.get('year'), github_token)
                    config = fetch_challenge_config(year, github_token)
                    content, _ = fetch_challenge_file(year, github_token)
                except (HTTPError, ValueError):
                    return self._send_json(503, {'error': 'Challenge data is unavailable'})
                response = build_state_response(content, config, authed_team)
                return self._send_json(200, response)

            if action == 'clear':
                if not team or not password:
                    return self._send_json(400, {'error': 'Missing team or password'})
                expected = get_team_password(team)
                if not expected:
                    return self._send_json(500, {'error': 'Team not configured'})
                if not hmac.compare_digest(str(password), expected):
                    return self._send_json(401, {'error': 'Invalid password'})

                if not github_token:
                    return self._send_json(500, {'error': 'Server configuration error'})

                try:
                    year = resolve_challenge_year(data.get('year'), github_token)
                    config = fetch_challenge_config(year, github_token)
                except (HTTPError, ValueError):
                    return self._send_json(503, {'error': 'Challenge data is unavailable'})

                success, message = update_challenge_file(
                    year, team, [], github_token, config, clear=True
                )
                if not success:
                    return self._send_json(503, {'error': 'Could not update challenge entry'})

                try:
                    content, _ = fetch_challenge_file(year, github_token)
                except (HTTPError, ValueError):
                    return self._send_json(200, {'success': True, 'message': 'Entry cleared'})
                response = build_state_response(content, config, team)
                response['success'] = True
                response['message'] = 'Entry cleared'
                return self._send_json(200, response)

            if action == 'submit':
                if not team or not password:
                    return self._send_json(400, {'error': 'Missing team or password'})
                expected = get_team_password(team)
                if not expected:
                    return self._send_json(500, {'error': 'Team not configured'})
                if not hmac.compare_digest(str(password), expected):
                    return self._send_json(401, {'error': 'Invalid password'})

                if not github_token:
                    return self._send_json(500, {'error': 'Server configuration error'})

                try:
                    year = resolve_challenge_year(data.get('year'), github_token)
                    config = fetch_challenge_config(year, github_token)
                except (HTTPError, ValueError):
                    return self._send_json(503, {'error': 'Challenge data is unavailable'})

                cleaned, err = validate_picks_payload(data.get('picks'), config)
                if err:
                    return self._send_json(400, {'error': err})

                success, message = update_challenge_file(year, team, cleaned, github_token, config)
                if not success:
                    return self._send_json(503, {'error': 'Could not update challenge entry'})

                try:
                    content, _ = fetch_challenge_file(year, github_token)
                except (HTTPError, ValueError):
                    return self._send_json(200, {'success': True, 'message': message})
                response = build_state_response(content, config, team)
                response['success'] = True
                response['message'] = message
                return self._send_json(200, response)

            return self._send_json(400, {'error': f'Unknown action: {action}'})

        except RequestError as error:
            return self._send_json(error.status, {'error': error.message})
        except Exception:
            incident = request_id()
            logger.exception('Unexpected NFL draft API failure request_id=%s', incident)
            return self._send_json(
                500, {'error': 'Unexpected server error', 'request_id': incident}
            )

    def _send_json(self, status_code: int, data: dict):
        send_json(self, status_code, data)

    def log_message(self, format, *args):
        pass
