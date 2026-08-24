"""Vercel Serverless Function for transaction handling."""

import base64
import copy
import hmac
import json
import math
import os
import re
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError

# GitHub repo info
GITHUB_OWNER = os.environ.get('REPO_OWNER') or os.environ.get('GITHUB_OWNER', 'griffin')
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'scoring')
GITHUB_BRANCH = os.environ.get('GITHUB_BRANCH', 'main')

TRADE_DEADLINE_WEEK = 12
CURRENT_SEASON = 2026

# Duplicated from qpfl/constants.py: Vercel functions can't import qpfl unless
# it's bundled (see docs/ROADMAP_2026.md P3.1), so these are kept in sync by
# hand. Keep values identical to ROSTER_SLOTS / taxi_slots there.
ROSTER_SLOTS = {'QB': 3, 'RB': 4, 'WR': 5, 'TE': 3, 'K': 2, 'D/ST': 2, 'HC': 2, 'OL': 2}
TAXI_SLOTS = 4
COMMISSIONER_TEAM = os.environ.get('COMMISSIONER_TEAM', 'GSA')
LEAGUE_TEAMS = {'GSA', 'WJK', 'RPA', 'S/T', 'CGK', 'AST', 'CWR', 'J/J', 'SLS', 'AYP'}

# Pick IDs are built by web/app.js as `${year}[-${draft_type}]-R${round}-${original_team}`,
# where the draft_type segment is omitted for the default 'offseason' type
# (e.g. "2027-R3-CWR" vs "2028-offseason_taxi-R1-CWR"). original_team can
# contain '/' (e.g. "S/T") but never '-', so splitting on '-' is safe.
PICK_ID_RE = re.compile(
    r'^(?P<year>\d{4})(?:-(?P<draft_type>offseason_taxi|waiver|waiver_taxi))?-R(?P<round>\d+)-(?P<team>.+)$'
)


class TransactionError(Exception):
    """Raised inside a mutate_fn to abort a write with an HTTP status + body.

    update_json_file catches this, skips the PUT entirely (so nothing is
    written), and returns it to the caller to turn into an HTTP response.
    """

    def __init__(self, status: int, body: dict):
        super().__init__(body.get('error', 'transaction error'))
        self.status = status
        self.body = body


def get_team_password(team_abbrev: str) -> str | None:
    """Get the password for a team from environment variables."""
    env_key = f'TEAM_PASSWORD_{team_abbrev.replace("/", "_")}'
    return os.environ.get(env_key)


# --------------------------------------------------------------------------- #
# Low-level GitHub contents API seams. These are the only functions that touch
# the network — tests monkeypatch them with an in-memory store.
# --------------------------------------------------------------------------- #
def _github_headers() -> dict | None:
    github_token = os.environ.get('SKYNET_PAT') or os.environ.get('GITHUB_TOKEN')
    if not github_token:
        return None
    return {
        'Authorization': f'Bearer {github_token}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
        'User-Agent': 'QPFL-Transaction-Bot',
    }


def github_get_file(path: str):
    """Fetch a JSON file from the repo.

    Returns (sha, content). Returns (None, None) if the file does not exist
    (404). Raises HTTPError/RuntimeError on any other failure.
    """
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
    """Write a JSON file to the repo. Raises HTTPError (409 on stale SHA)."""
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
    """Optimistic read-modify-write against a JSON file in the repo.

    Fetches the current content + SHA, applies ``mutate_fn`` to a FRESH copy,
    and PUTs with that SHA. If GitHub rejects the write with a 409 (another
    request committed in between), it re-fetches the now-current content and
    re-applies ``mutate_fn`` — so two independent changes to the same file
    (e.g. roster moves by different teams) merge instead of clobbering each
    other. The previous implementation re-sent the *stale* content on retry,
    silently dropping the concurrent update.

    ``mutate_fn(content)`` must return ``(new_content, extra)``. It may raise
    ``TransactionError`` to abort the write; because validation lives inside
    mutate_fn, it re-runs against fresh content on every attempt.

    Returns:
        (True, extra) on success
        (False, TransactionError) if mutate_fn aborted
        (False, error_string) on transport/config error or exhausted retries
    """
    for attempt in range(max_retries):
        try:
            sha, content = github_get_file(path)
        except Exception as e:
            return False, f'Failed to read {path}: {e}'

        if content is None:
            content = copy.deepcopy(default)

        try:
            new_content, extra = mutate_fn(content)
        except TransactionError as e:
            return False, e

        try:
            github_put_file(path, new_content, message, sha)
            return True, extra
        except HTTPError as e:
            if e.code == 409 and attempt < max_retries - 1:
                print(f'Conflict on {path}, retrying ({attempt + 1}/{max_retries})...')
                time.sleep(0.5 * (attempt + 1))
                continue
            error_body = e.read().decode() if hasattr(e, 'read') else str(e)
            return False, f'GitHub API error: {error_body}'
        except Exception as e:
            return False, str(e)

    return False, f'Failed to update {path} after {max_retries} attempts (conflicts)'


def _write_result(ok, res, success_body):
    """Translate an update_json_file result into an (status, body) response."""
    if ok:
        return 200, success_body
    if isinstance(res, TransactionError):
        return res.status, res.body
    return 500, {'error': res}


def get_authoritative_current_week() -> int | None:
    """Read the current week from the committed site data (web/data.json).

    The trade deadline must be enforced against a value the client cannot
    control — otherwise a manager could spoof `current_week` in the request body
    to trade past the deadline. Returns None if data.json is unreachable or
    malformed so the caller can fail closed (reject the trade with a "try
    again" error) instead of defaulting to "deadline open" during an outage
    that happens to land in the deadline window. See docs/ROADMAP_2026.md P1.5.
    """
    try:
        _sha, content = github_get_file('web/data.json')
    except Exception:
        return None
    if isinstance(content, dict):
        try:
            return int(content.get('current_week', 1))
        except (TypeError, ValueError):
            return None
    return None


def validate_team(team: str, password: str) -> tuple[bool, str]:
    """Validate team password."""
    if not team or not password:
        return False, 'Missing team or password'

    expected = get_team_password(team)
    if not expected:
        return False, 'Team not configured'

    if not hmac.compare_digest(str(password), expected):
        return False, 'Invalid password'

    return True, 'Valid'


def validate_commissioner(team: str, password: str) -> tuple[bool, str, int]:
    """Authorize commissioner actions with GSA's login.

    The legacy ADMIN credential remains valid for raw API clients, while the
    browser UI uses the already-authenticated commissioner team's password.
    """
    valid, msg = validate_team(team, password)
    if not valid:
        return False, msg, 401
    if team not in {COMMISSIONER_TEAM, 'ADMIN'}:
        return False, 'Commissioner access required', 403
    return True, 'Valid', 200


def get_roster_and_taxi(rosters: dict, team: str) -> tuple[list, list]:
    """Get roster and taxi squad from rosters data, handling all formats."""
    team_data = rosters.get(team, [])
    if isinstance(team_data, list):
        # Flat format with taxi flag: team -> [players] where some have taxi: True
        roster = [p for p in team_data if not p.get('taxi')]
        taxi = [p for p in team_data if p.get('taxi')]
        return roster, taxi
    else:
        # Nested format: team -> {roster: [], taxi_squad: []}
        return team_data.get('roster', []), team_data.get('taxi_squad', [])


def set_roster_and_taxi(rosters: dict, team: str, roster: list, taxi: list):
    """Set roster and taxi squad, preserving the original format."""
    if team in rosters and isinstance(rosters[team], dict):
        rosters[team] = {'roster': roster, 'taxi_squad': taxi}
    else:
        # Flat format with taxi flag: merge roster and taxi, marking taxi players
        merged = []
        for p in roster:
            player_copy = {k: v for k, v in p.items() if k != 'taxi'}
            merged.append(player_copy)
        for p in taxi:
            player_copy = dict(p.items())
            player_copy['taxi'] = True
            merged.append(player_copy)
        rosters[team] = merged


def handle_taxi_activation(data: dict) -> tuple[int, dict]:
    """Handle taxi squad activation."""
    team = data.get('team')
    password = data.get('password')
    player_to_activate = data.get('player_to_activate')
    player_to_release = data.get('player_to_release')
    week = data.get('week')

    valid, msg = validate_team(team, password)
    if not valid:
        return 401, {'error': msg}

    if not player_to_activate or not player_to_release or week is None:
        return 400, {'error': 'Missing required fields'}

    def mutate(rosters):
        roster, taxi = get_roster_and_taxi(rosters, team)

        taxi_player = next((p for p in taxi if p['name'] == player_to_activate), None)
        if not taxi_player:
            raise TransactionError(
                400, {'error': f'{player_to_activate} is not on your taxi squad'}
            )

        roster_player = next((p for p in roster if p['name'] == player_to_release), None)
        if not roster_player:
            raise TransactionError(
                400, {'error': f'{player_to_release} is not on your active roster'}
            )

        if taxi_player['position'] != roster_player['position']:
            raise TransactionError(
                400,
                {
                    'error': f'Position mismatch: {taxi_player["position"]} '
                    f'vs {roster_player["position"]}'
                },
            )

        taxi = [p for p in taxi if p['name'] != player_to_activate]
        roster = [p for p in roster if p['name'] != player_to_release]
        roster.append(taxi_player)
        set_roster_and_taxi(rosters, team, roster, taxi)
        return rosters, {'taxi_player': taxi_player, 'roster_player': roster_player}

    ok, res = update_json_file(
        'data/rosters.json',
        mutate,
        f'Taxi activation: {team} activates {player_to_activate}, releases {player_to_release}',
        default={},
    )
    if not ok:
        if isinstance(res, TransactionError):
            return res.status, res.body
        return 500, {'error': res}

    taxi_player = res['taxi_player']
    roster_player = res['roster_player']
    is_offseason = week == 0 or week > 17
    add_transaction_log(
        {
            'type': 'taxi_activation',
            'team': team,
            'activated': {
                'name': taxi_player['name'],
                'position': taxi_player.get('position', ''),
                'nfl_team': taxi_player.get('nfl_team', ''),
            },
            'released': {
                'name': roster_player['name'],
                'position': roster_player.get('position', ''),
                'nfl_team': roster_player.get('nfl_team', ''),
            },
            'week': 'Offseason' if is_offseason else week,
            'season': CURRENT_SEASON,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }
    )

    return 200, {
        'success': True,
        'message': f'Activated {player_to_activate}, released {player_to_release}',
    }


def handle_release(data: dict) -> tuple[int, dict]:
    """Handle a standalone player release (no add required, no restrictions)."""
    team = data.get('team')
    password = data.get('password')
    player_to_release = data.get('player_to_release')
    week = data.get('week')

    valid, msg = validate_team(team, password)
    if not valid:
        return 401, {'error': msg}

    if not player_to_release or week is None:
        return 400, {'error': 'Missing required fields'}

    def mutate(rosters):
        roster, taxi = get_roster_and_taxi(rosters, team)

        roster_player = next((p for p in roster if p['name'] == player_to_release), None)
        if not roster_player:
            raise TransactionError(
                400, {'error': f'{player_to_release} is not on your active roster'}
            )

        roster = [p for p in roster if p['name'] != player_to_release]
        set_roster_and_taxi(rosters, team, roster, taxi)
        return rosters, roster_player

    ok, res = update_json_file(
        'data/rosters.json',
        mutate,
        f'Release: {team} releases {player_to_release}',
        default={},
    )
    if not ok:
        if isinstance(res, TransactionError):
            return res.status, res.body
        return 500, {'error': res}

    roster_player = res
    is_offseason = week == 0 or week > 17
    add_transaction_log(
        {
            'type': 'release',
            'team': team,
            'released': {
                'name': roster_player['name'],
                'position': roster_player.get('position', ''),
                'nfl_team': roster_player.get('nfl_team', ''),
            },
            'week': 'Offseason' if is_offseason else week,
            'season': CURRENT_SEASON,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }
    )

    return 200, {
        'success': True,
        'message': f'Released {player_to_release}',
    }


def _fa_list(fa_pool):
    """fa_pool.json is a flat list of player objects — matching the on-disk file
    and the website (web/app.js reads `data.fa_pool` as a list). Tolerate a
    legacy {"players": [...]} wrapper if one ever appears."""
    if isinstance(fa_pool, dict):
        return fa_pool.get('players', [])
    return fa_pool


def handle_fa_activation(data: dict) -> tuple[int, dict]:
    """Handle FA pool activation.

    This spans two files (fa_pool + rosters). GitHub has no multi-file
    transaction, so we claim the FA player first (the optimistic write on
    fa_pool is what stops two managers grabbing the same player), then update
    the roster. If the roster write fails, we roll the claim back so the player
    isn't left stuck as unavailable.
    """
    team = data.get('team')
    password = data.get('password')
    player_to_add = data.get('player_to_add')
    player_to_release = data.get('player_to_release')
    week = data.get('week')

    valid, msg = validate_team(team, password)
    if not valid:
        return 401, {'error': msg}

    if not player_to_add or not player_to_release or week is None:
        return 400, {'error': 'Missing required fields'}

    # Step 1: claim the FA player (authoritative under concurrency).
    def claim(fa_pool):
        fa_pool = _fa_list(fa_pool)
        fa_player = next(
            (p for p in fa_pool if p['name'] == player_to_add and p.get('available', True)),
            None,
        )
        if not fa_player:
            raise TransactionError(
                400, {'error': f'{player_to_add} is not available in the FA pool'}
            )
        for p in fa_pool:
            if p['name'] == player_to_add:
                p['available'] = False
                p['activated_by'] = team
                p['activated_week'] = week
        return fa_pool, dict(fa_player)

    ok, res = update_json_file(
        'data/fa_pool.json',
        claim,
        f'FA pool update: {player_to_add} activated by {team}',
        default=[],
    )
    if not ok:
        if isinstance(res, TransactionError):
            return res.status, res.body
        return 500, {'error': res}
    fa_player = res

    # Step 2: swap the FA player onto the roster.
    def swap(rosters):
        roster, taxi = get_roster_and_taxi(rosters, team)
        roster_player = next((p for p in roster if p['name'] == player_to_release), None)
        if not roster_player:
            raise TransactionError(
                400, {'error': f'{player_to_release} is not on your active roster'}
            )
        if fa_player['position'] != roster_player['position']:
            raise TransactionError(
                400,
                {
                    'error': f'Position mismatch: {fa_player["position"]} '
                    f'vs {roster_player["position"]}'
                },
            )
        roster = [p for p in roster if p['name'] != player_to_release]
        roster.append(
            {
                'name': fa_player['name'],
                'nfl_team': fa_player['nfl_team'],
                'position': fa_player['position'],
            }
        )
        set_roster_and_taxi(rosters, team, roster, taxi)
        return rosters, roster_player

    ok, res = update_json_file(
        'data/rosters.json',
        swap,
        f'FA activation: {team} adds {player_to_add}, releases {player_to_release}',
        default={},
    )
    if not ok:
        # Roll back the claim so the FA player returns to the pool.
        def unclaim(fa_pool):
            fa_pool = _fa_list(fa_pool)
            for p in fa_pool:
                if p['name'] == player_to_add:
                    p['available'] = True
                    p.pop('activated_by', None)
                    p.pop('activated_week', None)
            return fa_pool, None

        update_json_file(
            'data/fa_pool.json', unclaim, f'Revert FA claim: {player_to_add}', default=[]
        )
        if isinstance(res, TransactionError):
            return res.status, res.body
        return 500, {'error': res}
    roster_player = res

    is_offseason = week == 0 or week > 17
    add_transaction_log(
        {
            'type': 'fa_activation',
            'team': team,
            'added': {
                'name': fa_player['name'],
                'position': fa_player.get('position', ''),
                'nfl_team': fa_player.get('nfl_team', ''),
            },
            'released': {
                'name': roster_player['name'],
                'position': roster_player.get('position', ''),
                'nfl_team': roster_player.get('nfl_team', ''),
            },
            'week': 'Offseason' if is_offseason else week,
            'season': CURRENT_SEASON,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }
    )

    return 200, {
        'success': True,
        'message': f'Added {player_to_add} from FA pool, released {player_to_release}',
    }


def handle_propose_trade(data: dict) -> tuple[int, dict]:
    """Handle trade proposal."""
    team = data.get('team')
    password = data.get('password')
    trade_partner = data.get('trade_partner')
    give_players = data.get('give_players', [])
    give_picks = data.get('give_picks', [])
    receive_players = data.get('receive_players', [])
    receive_picks = data.get('receive_picks', [])
    conditions = data.get('conditions', {})
    comment = data.get('comment', '')

    valid, msg = validate_team(team, password)
    if not valid:
        return 401, {'error': msg}

    if not trade_partner:
        return 400, {'error': 'Must specify trade partner'}

    if not (give_players or give_picks) and not (receive_players or receive_picks):
        return 400, {'error': 'Trade must include players or picks'}

    # Derive the current week server-side — never trust the client-supplied value
    # for deadline enforcement (see get_authoritative_current_week).
    current_week = get_authoritative_current_week()
    if current_week is None:
        # Fail closed: we can't verify whether the deadline has passed, so
        # don't let the trade through. Better than defaulting to "open" and
        # silently allowing a deadline-period trade during an outage.
        return 503, {'error': 'Cannot verify trade deadline right now — please try again'}

    # Trading is blocked from week 12 through week 17 (deadline period); open
    # before week 12 and after week 17 (offseason).
    is_deadline_period = current_week >= TRADE_DEADLINE_WEEK and current_week <= 17
    if is_deadline_period:
        return 400, {'error': f'Trade deadline has passed (Week {TRADE_DEADLINE_WEEK})'}

    trade = {
        'id': str(uuid.uuid4())[:8],
        'proposer': team,
        'partner': trade_partner,
        'proposer_gives': {'players': give_players, 'picks': give_picks},
        'proposer_receives': {'players': receive_players, 'picks': receive_picks},
        'status': 'pending',
        'proposed_at': datetime.now(timezone.utc).isoformat(),
        'week': current_week,
    }
    if conditions:
        trade['conditions'] = conditions
    if comment:
        trade['comment'] = comment

    def mutate(pending):
        if not isinstance(pending, dict) or 'trades' not in pending:
            pending = {'trades': [], 'trade_deadline_week': TRADE_DEADLINE_WEEK}
        pending['trades'].append(trade)
        return pending, None

    ok, res = update_json_file(
        'data/pending_trades.json',
        mutate,
        f'Trade proposed: {team} to {trade_partner}',
        default={'trades': [], 'trade_deadline_week': TRADE_DEADLINE_WEEK},
    )
    return _write_result(
        ok,
        res,
        {
            'success': True,
            'message': f'Trade proposed to {trade_partner}',
            'trade_id': trade['id'],
        },
    )


def execute_trade(trade: dict) -> tuple[bool, str, dict]:
    """Execute a trade by swapping players between teams.

    Ownership is validated *inside* the optimistic roster write, so it re-checks
    against the latest rosters on every retry. A trade can sit pending for days
    (auto-expires after 7), during which a player may be dropped or traded
    elsewhere — without this check the swap would silently complete with the
    moved player missing, handing one side something for nothing.

    Returns (success, message, player_details).
    """
    proposer = trade['proposer']
    partner = trade['partner']
    proposer_gives = trade['proposer_gives']
    proposer_receives = trade['proposer_receives']

    picks_to_transfer = []
    for pick_str in proposer_gives.get('picks', []):
        picks_to_transfer.append((pick_str, proposer, partner))
    for pick_str in proposer_receives.get('picks', []):
        picks_to_transfer.append((pick_str, partner, proposer))

    if picks_to_transfer:
        try:
            _sha, current_draft_picks = github_get_file('data/draft_picks.json')
        except Exception as e:
            return False, f'Failed to validate draft picks: {e}', {}
        picks = (
            current_draft_picks.get('picks', []) if isinstance(current_draft_picks, dict) else []
        )
        missing = []
        for pick_str, from_team, _to_team in picks_to_transfer:
            match = PICK_ID_RE.match(pick_str)
            if not match:
                missing.append(pick_str)
                continue
            expected = (
                match.group('year'),
                match.group('draft_type') or 'offseason',
                int(match.group('round')),
                match.group('team'),
                from_team,
            )
            found = any(
                (
                    pick.get('year'),
                    pick.get('draft_type'),
                    pick.get('round'),
                    pick.get('original_team'),
                    pick.get('current_owner'),
                )
                == expected
                for pick in picks
            )
            if not found:
                missing.append(pick_str)
        if missing:
            return (
                False,
                'Trade can no longer be executed — pick has changed hands: ' + ', '.join(missing),
                {},
            )

    def mutate(rosters):
        proposer_roster, proposer_taxi = get_roster_and_taxi(rosters, proposer)
        partner_roster, partner_taxi = get_roster_and_taxi(rosters, partner)

        def _owned(name, roster, taxi):
            return any(p['name'] == name for p in roster) or any(p['name'] == name for p in taxi)

        missing = []
        for name in proposer_gives.get('players', []):
            if not _owned(name, proposer_roster, proposer_taxi):
                missing.append(f'{name} (no longer on {proposer})')
        for name in proposer_receives.get('players', []):
            if not _owned(name, partner_roster, partner_taxi):
                missing.append(f'{name} (no longer on {partner})')
        if missing:
            raise TransactionError(
                409,
                {
                    'error': 'Trade can no longer be executed — roster has changed: '
                    + ', '.join(missing)
                },
            )

        # Move players proposer gives to partner, preserving active/taxi status:
        # a taxi player traded away lands on the receiving team's taxi squad
        # (the manager can activate it later via the existing taxi flow), not
        # silently activated. See docs/ROADMAP_2026.md P1.1.
        players_to_partner = []
        partner_gets_active = []
        partner_gets_taxi = []
        for player_name in proposer_gives.get('players', []):
            player = next((p for p in proposer_roster if p['name'] == player_name), None)
            if player:
                proposer_roster = [p for p in proposer_roster if p['name'] != player_name]
                partner_gets_active.append(player)
            else:
                player = next((p for p in proposer_taxi if p['name'] == player_name), None)
                proposer_taxi = [p for p in proposer_taxi if p['name'] != player_name]
                partner_gets_taxi.append(player)
            players_to_partner.append(player)

        # Move players proposer receives from partner, same active/taxi rule.
        players_to_proposer = []
        proposer_gets_active = []
        proposer_gets_taxi = []
        for player_name in proposer_receives.get('players', []):
            player = next((p for p in partner_roster if p['name'] == player_name), None)
            if player:
                partner_roster = [p for p in partner_roster if p['name'] != player_name]
                proposer_gets_active.append(player)
            else:
                player = next((p for p in partner_taxi if p['name'] == player_name), None)
                partner_taxi = [p for p in partner_taxi if p['name'] != player_name]
                proposer_gets_taxi.append(player)
            players_to_proposer.append(player)

        new_partner_roster = partner_roster + partner_gets_active
        new_partner_taxi = partner_taxi + partner_gets_taxi
        new_proposer_roster = proposer_roster + proposer_gets_active
        new_proposer_taxi = proposer_taxi + proposer_gets_taxi

        # Validate roster compliance post-trade (constitution: "a roster spot
        # must be available or cleared" - unbalanced trades are fine, but the
        # resulting roster must still fit within slot/taxi limits).
        violations = []
        for team_name, active, taxi in (
            (proposer, new_proposer_roster, new_proposer_taxi),
            (partner, new_partner_roster, new_partner_taxi),
        ):
            active_counts: dict[str, int] = {}
            for p in active:
                pos = p.get('position')
                active_counts[pos] = active_counts.get(pos, 0) + 1
            for pos, count in active_counts.items():
                limit = ROSTER_SLOTS.get(pos)
                if limit is not None and count > limit:
                    violations.append(f'{team_name} would have {count} {pos} players (max {limit})')

            if len(taxi) > TAXI_SLOTS:
                violations.append(
                    f'{team_name} would have {len(taxi)} taxi players (max {TAXI_SLOTS})'
                )
            taxi_counts: dict[str, int] = {}
            for p in taxi:
                pos = p.get('position')
                taxi_counts[pos] = taxi_counts.get(pos, 0) + 1
            for pos, count in taxi_counts.items():
                if count > 1:
                    violations.append(
                        f'{team_name} would have {count} taxi {pos} players (max 1 per position)'
                    )

        if violations:
            raise TransactionError(
                400,
                {
                    'error': 'Trade would violate roster rules — release someone or adjust the '
                    'trade first: ' + '; '.join(violations)
                },
            )

        set_roster_and_taxi(rosters, proposer, new_proposer_roster, new_proposer_taxi)
        set_roster_and_taxi(rosters, partner, new_partner_roster, new_partner_taxi)
        return rosters, {
            'proposer_gives_players': players_to_partner,
            'proposer_receives_players': players_to_proposer,
        }

    ok, res = update_json_file(
        'data/rosters.json', mutate, f'Trade executed: {proposer} <-> {partner}', default={}
    )
    if not ok:
        if isinstance(res, TransactionError):
            return False, res.body['error'], {}
        return False, f'Failed to save rosters: {res}', {}
    player_details = res

    if picks_to_transfer:

        def mutate_picks(draft_picks):
            picks = draft_picks.get('picks', [])
            missing = []
            for pick_str, from_team, to_team in picks_to_transfer:
                m = PICK_ID_RE.match(pick_str)
                if not m:
                    missing.append(pick_str)
                    continue
                year = m.group('year')
                draft_type = m.group('draft_type') or 'offseason'
                round_num = int(m.group('round'))
                original_team = m.group('team')
                for pick in picks:
                    if (
                        pick.get('year') == year
                        and pick.get('round') == round_num
                        and pick.get('draft_type') == draft_type
                        and pick.get('original_team') == original_team
                        and pick.get('current_owner') == from_team
                    ):
                        prev_owners = pick.get('previous_owners', [])
                        if from_team not in prev_owners:
                            prev_owners.append(from_team)
                        pick['previous_owners'] = prev_owners
                        pick['current_owner'] = to_team
                        break
                else:
                    missing.append(pick_str)
            if missing:
                raise TransactionError(
                    409,
                    {
                        'error': 'Trade can no longer be executed — pick has changed hands: '
                        + ', '.join(missing)
                    },
                )
            draft_picks['picks'] = picks
            draft_picks['updated_at'] = datetime.now(timezone.utc).isoformat()
            return draft_picks, None

        picks_ok, picks_res = update_json_file(
            'data/draft_picks.json',
            mutate_picks,
            f'Pick trade: {proposer} <-> {partner}',
            default={'picks': []},
        )
        if not picks_ok:
            # Players already swapped (data/rosters.json write above succeeded)
            # but the pick transfer failed - surface it rather than silently
            # reporting success, so the accept flow's failure path (revert to
            # pending + last_execution_error) kicks in and a commissioner sees
            # it instead of the trade looking done with picks never moved.
            err = (
                picks_res.body['error']
                if isinstance(picks_res, TransactionError)
                else str(picks_res)
            )
            return False, f'Players swapped but pick transfer failed: {err}', player_details

    return True, 'Trade executed successfully', player_details


def handle_respond_trade(data: dict) -> tuple[int, dict]:
    """Handle trade acceptance or rejection."""
    team = data.get('team')
    password = data.get('password')
    trade_id = data.get('trade_id')
    accept = data.get('accept', False)

    valid, msg = validate_team(team, password)
    if not valid:
        return 401, {'error': msg}

    if not trade_id:
        return 400, {'error': 'Missing trade_id'}

    # Read the trade first to validate the responder and (if accepting) execute
    # the swap, before marking it resolved in pending_trades.
    try:
        _sha, pending = github_get_file('data/pending_trades.json')
    except Exception as e:
        return 500, {'error': str(e)}
    if not isinstance(pending, dict):
        return 400, {'error': 'Trade not found'}

    trade = next((t for t in pending.get('trades', []) if t['id'] == trade_id), None)
    if not trade:
        return 400, {'error': 'Trade not found'}
    if trade['partner'] != team:
        return 403, {'error': 'You are not the trade partner'}
    if trade['status'] != 'pending':
        return 400, {'error': f'Trade is already {trade["status"]}'}

    if not accept:
        return _finalize_trade_status(trade_id, 'rejected', {})

    # Accept path must be atomic: a naive "swap rosters, then mark accepted"
    # order can leave rosters swapped with the trade still 'pending' (so a
    # second accept could double-execute) if the status write fails after a
    # successful swap, or leave it 'accepted' with rosters unswapped if the
    # swap fails after the status write. See docs/ROADMAP_2026.md P0.6.
    #
    # Step 1: atomically transition pending -> accepted with an
    # execution:"in_progress" marker. This mutate aborts (via TransactionError)
    # if the trade isn't pending anymore, so it's the concurrency gate — only
    # one concurrent accept can win this write.
    def gate(pending_now):
        if not isinstance(pending_now, dict):
            raise TransactionError(400, {'error': 'Trade not found'})
        t = next((x for x in pending_now.get('trades', []) if x['id'] == trade_id), None)
        if not t:
            raise TransactionError(400, {'error': 'Trade not found'})
        if t['status'] != 'pending':
            raise TransactionError(400, {'error': f'Trade is already {t["status"]}'})
        t['status'] = 'accepted'
        t['execution'] = 'in_progress'
        t['accepted_at'] = datetime.now(timezone.utc).isoformat()
        return pending_now, None

    ok, res = update_json_file(
        'data/pending_trades.json',
        gate,
        f'Trade {trade_id} accepted (executing)',
        default={'trades': []},
    )
    if not ok:
        if isinstance(res, TransactionError):
            return res.status, res.body
        return 500, {'error': res}

    # Step 2: execute the roster swap.
    success, exec_msg, player_details = execute_trade(trade)

    if not success:
        # Step 3 (failure): best-effort revert to pending so the partner can
        # retry, recording the error. If this revert write itself fails, the
        # trade is left stuck as accepted/in_progress for the commissioner to
        # resolve by hand — it will never silently double-execute, since a
        # re-accept is blocked by the gate above (status is no longer pending).
        def revert(pending_now):
            if not isinstance(pending_now, dict):
                raise TransactionError(400, {'error': 'Trade not found'})
            t = next((x for x in pending_now.get('trades', []) if x['id'] == trade_id), None)
            if not t:
                raise TransactionError(400, {'error': 'Trade not found'})
            t['status'] = 'pending'
            t.pop('execution', None)
            t.pop('accepted_at', None)
            t['last_execution_error'] = exec_msg
            return pending_now, None

        update_json_file(
            'data/pending_trades.json',
            revert,
            f'Trade {trade_id} execution failed, reverted to pending',
            default={'trades': []},
        )
        return 409, {'error': exec_msg}

    # Step 3 (success): best-effort mark execution done. If this write fails,
    # the trade stays accepted/in_progress despite having executed - harmless
    # (the swap already happened and can't double-apply), just needs a
    # commissioner to clear the marker; expire-trades.yml flags stale
    # in_progress trades so this doesn't go unnoticed.
    def finish(pending_now):
        if not isinstance(pending_now, dict):
            return pending_now, None
        t = next((x for x in pending_now.get('trades', []) if x['id'] == trade_id), None)
        if t:
            t['execution'] = 'done'
        return pending_now, None

    update_json_file(
        'data/pending_trades.json',
        finish,
        f'Trade {trade_id} execution complete',
        default={'trades': []},
    )

    return _finalize_trade_status(trade_id, 'accepted', player_details, trade=trade)


def _finalize_trade_status(
    trade_id: str, new_status: str, player_details: dict, trade: dict | None = None
) -> tuple[int, dict]:
    """Log the resolved trade to the transaction log (accept path only) and
    return the HTTP response. Status itself is already persisted by the
    caller (gate/mutate above for accept, or here for reject)."""
    if new_status == 'rejected':

        def mutate(pending_now):
            if not isinstance(pending_now, dict):
                raise TransactionError(400, {'error': 'Trade not found'})
            t = next((x for x in pending_now.get('trades', []) if x['id'] == trade_id), None)
            if not t:
                raise TransactionError(400, {'error': 'Trade not found'})
            if t['status'] != 'pending':
                raise TransactionError(400, {'error': f'Trade is already {t["status"]}'})
            t['status'] = 'rejected'
            t['rejected_at'] = datetime.now(timezone.utc).isoformat()
            return pending_now, None

        ok, res = update_json_file(
            'data/pending_trades.json', mutate, f'Trade {trade_id} rejected', default={'trades': []}
        )
        if not ok:
            if isinstance(res, TransactionError):
                return res.status, res.body
            return 500, {'error': res}
        return 200, {'success': True, 'message': 'Trade rejected'}

    if trade is not None:
        trade_week = trade.get('week', 0)
        is_offseason = trade_week == 0 or trade_week > 17
        add_transaction_log(
            {
                'type': 'trade',
                'proposer': trade['proposer'],
                'partner': trade['partner'],
                'proposer_gives': {
                    'players': player_details.get('proposer_gives_players', []),
                    'picks': trade['proposer_gives'].get('picks', []),
                },
                'proposer_receives': {
                    'players': player_details.get('proposer_receives_players', []),
                    'picks': trade['proposer_receives'].get('picks', []),
                },
                'week': 'Offseason' if is_offseason else trade_week,
                'season': CURRENT_SEASON,
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }
        )

    return 200, {'success': True, 'message': 'Trade accepted and executed'}


def handle_cancel_trade(data: dict) -> tuple[int, dict]:
    """Handle trade cancellation by the proposer."""
    team = data.get('team')
    password = data.get('password')
    trade_id = data.get('trade_id')

    valid, msg = validate_team(team, password)
    if not valid:
        return 401, {'error': msg}

    if not trade_id:
        return 400, {'error': 'Missing trade_id'}

    def mutate(pending):
        if not isinstance(pending, dict):
            raise TransactionError(400, {'error': 'Trade not found'})
        trade = next((t for t in pending.get('trades', []) if t['id'] == trade_id), None)
        if not trade:
            raise TransactionError(400, {'error': 'Trade not found'})
        if trade['proposer'] != team:
            raise TransactionError(403, {'error': 'Only the proposer can cancel this trade'})
        if trade['status'] != 'pending':
            raise TransactionError(400, {'error': f'Trade is already {trade["status"]}'})
        trade['status'] = 'cancelled'
        trade['cancelled_at'] = datetime.now(timezone.utc).isoformat()
        return pending, None

    ok, res = update_json_file(
        'data/pending_trades.json',
        mutate,
        f'Trade {trade_id} cancelled by {team}',
        default={'trades': []},
    )
    return _write_result(ok, res, {'success': True, 'message': 'Trade cancelled'})


def handle_save_tradeblock(data: dict) -> tuple[int, dict]:
    """Handle saving trade block data."""
    team = data.get('team')
    password = data.get('password')
    seeking = data.get('seeking', [])
    trading_away = data.get('trading_away', [])
    players_available = data.get('players_available', [])
    notes = data.get('notes', '')

    valid, msg = validate_team(team, password)
    if not valid:
        return 401, {'error': msg}

    def mutate(trade_blocks):
        if not isinstance(trade_blocks, dict):
            trade_blocks = {}
        trade_blocks[team] = {
            'seeking': seeking,
            'trading_away': trading_away,
            'players_available': players_available,
            'notes': notes,
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }
        return trade_blocks, None

    ok, res = update_json_file(
        'data/trade_blocks.json', mutate, f'Trade block updated: {team}', default={}
    )
    return _write_result(ok, res, {'success': True, 'message': 'Trade block saved'})


def reorder_within_positions(roster: list, order: dict) -> list:
    """Return `roster` with each listed position's players in the given order.

    The depth chart is stored as nothing more than the order of the team's
    players inside `data/rosters.json` — every roster view renders players in
    array order (web/app.js sortRosterByPosition is a stable sort by position),
    so reordering the array is what moves a player up or down his position
    group across the whole site.

    Only *within-position* order changes: each position's existing slots in the
    array are refilled with the newly ordered players, so a roster that happens
    to interleave positions keeps its overall shape. Positions absent from
    `order` are left alone, which is what lets the client send a partial update.

    Raises TransactionError if `order` doesn't name exactly the players the
    team has at that position — a stale client (roster changed via a trade
    since the page loaded) must not be able to add, drop, or duplicate anyone.
    """
    by_pos = {}
    for p in roster:
        by_pos.setdefault(p.get('position'), []).append(p)

    reordered = {}
    for pos, names in order.items():
        current = by_pos.get(pos, [])
        current_names = [p.get('name') for p in current]
        if not isinstance(names, list) or sorted(names) != sorted(current_names):
            raise TransactionError(
                400,
                {
                    'error': f'Your {pos} depth chart no longer matches your roster '
                    f'(it may have changed since you loaded the page). Reload and try again.'
                },
            )
        if len(set(current_names)) != len(current_names):
            raise TransactionError(
                400, {'error': f'Duplicate player names at {pos} - contact the commissioner'}
            )
        index = {p['name']: p for p in current}
        reordered[pos] = [index[n] for n in names]

    cursors = dict.fromkeys(reordered, 0)
    result = []
    for p in roster:
        pos = p.get('position')
        if pos in reordered:
            result.append(reordered[pos][cursors[pos]])
            cursors[pos] += 1
        else:
            result.append(p)
    return result


def handle_set_depth_chart(data: dict) -> tuple[int, dict]:
    """Save a team's depth chart: the display order of its active-roster players
    within each position group.

    Purely cosmetic — the scorer never reads roster order, so this is not gated
    on the trade deadline or lineup locks. It only touches the team's own
    players, and taxi-squad players are excluded (they're ordered separately by
    the roster file's taxi section).
    """
    team = data.get('team')
    password = data.get('password')
    order = data.get('order')

    valid, msg = validate_team(team, password)
    if not valid:
        return 401, {'error': msg}

    if not isinstance(order, dict) or not order:
        return 400, {'error': 'Missing depth chart order'}

    bad = [pos for pos in order if pos not in ROSTER_SLOTS]
    if bad:
        return 400, {'error': f'Invalid position(s): {", ".join(map(str, bad))}'}

    def mutate(rosters):
        if not isinstance(rosters, dict) or team not in rosters:
            raise TransactionError(400, {'error': 'No roster found for your team'})
        roster, taxi = get_roster_and_taxi(rosters, team)
        set_roster_and_taxi(rosters, team, reorder_within_positions(roster, order), taxi)
        return rosters, None

    ok, res = update_json_file(
        'data/rosters.json', mutate, f'Depth chart updated: {team}', default={}
    )
    return _write_result(ok, res, {'success': True, 'message': 'Depth chart saved'})


def handle_admin_adjust(data: dict) -> tuple[int, dict]:
    """Commissioner admin actions: fix a bad transaction without hand-editing
    JSON in git. Gated by the GSA team login; the legacy TEAM_PASSWORD_ADMIN
    credential (set `team: "ADMIN"`) remains supported for raw API clients.

    Supports `admin_action`:
    - "release": remove a player from any team's roster (target_team, player)
    - "add": add a player to any team's roster (target_team, player: {name, position, nfl_team, taxi})
    - "reverse_trade": transfer a completed trade's players and picks back (trade_id)
    - "conditional_picks": return the unresolved conditional picks
    - "resolve_conditional_pick": choose the conveying pick and its final owner
    - "download_rosters": export the current roster workbook
    - "download_draft_board": export this season's trade-adjusted draft board
    - "score_adjustment": append a manual scoring correction
    - "audit_log": return recent commissioner actions

    All modifying admin actions are appended to the transaction log with
    "admin": true so they're visible in the site's transaction history.
    See docs/ROADMAP_2026.md P2.3.
    """
    team = data.get('team')
    password = data.get('password')

    valid, msg, error_status = validate_commissioner(team, password)
    if not valid:
        return error_status, {'error': msg}

    admin_action = data.get('admin_action')
    reason = str(data.get('reason') or '').strip()
    if len(reason) > 500:
        return 400, {'error': 'Reason must be 500 characters or less'}

    if admin_action in {'download_rosters', 'download_draft_board'}:
        try:
            from api.commissioner_exports import (
                build_draft_board_workbook,
                build_roster_workbook,
            )

            def read_export_source(path):
                _sha, content = github_get_file(path)
                if content is None:
                    raise ValueError(f'{path} was not found')
                return content

            teams = read_export_source('data/teams.json')
            if admin_action == 'download_rosters':
                content = build_roster_workbook(
                    read_export_source('data/rosters.json'),
                    teams,
                )
                filename = 'Rosters_current.xlsx'
            else:
                try:
                    season = int(data.get('season', CURRENT_SEASON))
                except (TypeError, ValueError):
                    return 400, {'error': 'Invalid draft season'}
                if not 2020 <= season <= 2100:
                    return 400, {'error': 'Invalid draft season'}
                content = build_draft_board_workbook(
                    read_export_source('data/draft_picks.json'),
                    read_export_source('data/draft_orders.json'),
                    teams,
                    season,
                )
                filename = f'{season}_Draft_Board.xlsx'
        except Exception as e:
            return 500, {'error': f'Failed to build commissioner export: {e}'}

        return 200, {
            'success': True,
            'filename': filename,
            'mime_type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'content_base64': base64.b64encode(content).decode('ascii'),
        }

    if admin_action == 'audit_log':
        try:
            limit = max(1, min(int(data.get('limit', 50)), 100))
        except (TypeError, ValueError):
            return 400, {'error': 'Invalid audit log limit'}
        try:
            _sha, log = github_get_file('data/transaction_log.json')
        except Exception as e:
            return 500, {'error': f'Failed to read audit log: {e}'}
        transactions = log.get('transactions', []) if isinstance(log, dict) else []
        entries = [entry for entry in transactions if entry.get('admin')][:limit]
        return 200, {'success': True, 'entries': entries}

    if admin_action == 'conditional_picks':
        try:
            _sha, draft_picks = github_get_file('data/draft_picks.json')
        except Exception as e:
            return 500, {'error': f'Failed to read draft picks: {e}'}
        if not isinstance(draft_picks, dict) or not isinstance(draft_picks.get('picks'), list):
            return 500, {'error': 'Draft picks file is malformed'}
        unresolved = [copy.deepcopy(pick) for pick in draft_picks['picks'] if pick.get('condition')]
        return 200, {'success': True, 'picks': unresolved}

    if admin_action == 'release':
        target_team = data.get('target_team')
        player_name = str(data.get('player') or '').strip()
        if not target_team or not player_name:
            return 400, {'error': 'Missing target_team or player'}
        if target_team not in LEAGUE_TEAMS:
            return 400, {'error': 'Invalid target_team'}

        def mutate(rosters):
            roster, taxi = get_roster_and_taxi(rosters, target_team)
            player = next((p for p in roster + taxi if p['name'] == player_name), None)
            if not player:
                raise TransactionError(400, {'error': f'{player_name} not found on {target_team}'})
            roster = [p for p in roster if p['name'] != player_name]
            taxi = [p for p in taxi if p['name'] != player_name]
            set_roster_and_taxi(rosters, target_team, roster, taxi)
            return rosters, player

        ok, res = update_json_file(
            'data/rosters.json',
            mutate,
            f'Admin release: {player_name} from {target_team}',
            default={},
        )
        if not ok:
            return _write_result(ok, res, {})
        add_transaction_log(
            {
                'type': 'admin_release',
                'team': target_team,
                'player': res,
                'admin': True,
                'actor': team,
                'reason': reason,
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }
        )
        return 200, {'success': True, 'message': f'Released {player_name} from {target_team}'}

    if admin_action == 'add':
        target_team = data.get('target_team')
        player = data.get('player')
        if not target_team or not isinstance(player, dict) or not player.get('name'):
            return 400, {'error': 'Missing target_team or player'}
        if target_team not in LEAGUE_TEAMS:
            return 400, {'error': 'Invalid target_team'}
        player = {
            'name': str(player.get('name') or '').strip(),
            'position': str(player.get('position') or '').strip().upper(),
            'nfl_team': str(player.get('nfl_team') or '').strip().upper(),
            **({'taxi': True} if player.get('taxi') else {}),
        }
        if not player['name']:
            return 400, {'error': 'Player name is required'}
        if len(player['name']) > 100:
            return 400, {'error': 'Player name must be 100 characters or less'}
        if player['position'] not in ROSTER_SLOTS:
            return 400, {'error': 'Invalid player position'}
        if not player['nfl_team'] or len(player['nfl_team']) > 3:
            return 400, {'error': 'Invalid NFL team abbreviation'}

        def mutate(rosters):
            roster, taxi = get_roster_and_taxi(rosters, target_team)
            if any(p['name'] == player['name'] for p in roster + taxi):
                raise TransactionError(
                    400, {'error': f'{player["name"]} is already on {target_team}'}
                )
            if player.get('taxi'):
                taxi = taxi + [player]
            else:
                roster = roster + [player]
            set_roster_and_taxi(rosters, target_team, roster, taxi)
            return rosters, player

        ok, res = update_json_file(
            'data/rosters.json', mutate, f'Admin add: {player["name"]} to {target_team}', default={}
        )
        if not ok:
            return _write_result(ok, res, {})
        add_transaction_log(
            {
                'type': 'admin_add',
                'team': target_team,
                'player': res,
                'admin': True,
                'actor': team,
                'reason': reason,
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }
        )
        return 200, {'success': True, 'message': f'Added {player["name"]} to {target_team}'}

    if admin_action == 'reverse_trade':
        trade_id = data.get('trade_id')
        if not trade_id:
            return 400, {'error': 'Missing trade_id'}
        if not reason:
            return 400, {'error': 'Reason is required for trade reversals'}

        reversal_token = str(uuid.uuid4())

        def gate_reversal(pending):
            if not isinstance(pending, dict):
                raise TransactionError(400, {'error': 'Trade not found'})
            trade = next((t for t in pending.get('trades', []) if t['id'] == trade_id), None)
            if not trade:
                raise TransactionError(400, {'error': 'Trade not found'})
            if trade.get('status') != 'accepted' or trade.get('execution') == 'in_progress':
                raise TransactionError(400, {'error': 'Only completed trades can be reversed'})
            if trade.get('reversed_at') or trade.get('reversal_execution') == 'done':
                raise TransactionError(409, {'error': 'Trade has already been reversed'})
            if trade.get('reversal_execution') == 'in_progress':
                raise TransactionError(409, {'error': 'Trade reversal is already in progress'})
            trade['reversal_execution'] = 'in_progress'
            trade['reversal_token'] = reversal_token
            return pending, copy.deepcopy(trade)

        ok, res = update_json_file(
            'data/pending_trades.json',
            gate_reversal,
            f'Admin reversal started for trade {trade_id}',
            default={'trades': []},
        )
        if not ok:
            return _write_result(ok, res, {})

        trade = res
        reverse_trade = {
            'proposer': trade['proposer'],
            'partner': trade['partner'],
            'proposer_gives': copy.deepcopy(trade['proposer_receives']),
            'proposer_receives': copy.deepcopy(trade['proposer_gives']),
        }
        success, execution_message, _player_details = execute_trade(reverse_trade)
        if not success:

            def clear_reversal_gate(pending):
                if not isinstance(pending, dict):
                    return pending, None
                current = next(
                    (item for item in pending.get('trades', []) if item['id'] == trade_id), None
                )
                if current and current.get('reversal_token') == reversal_token:
                    current.pop('reversal_execution', None)
                    current.pop('reversal_token', None)
                    current['last_reversal_error'] = execution_message
                return pending, None

            update_json_file(
                'data/pending_trades.json',
                clear_reversal_gate,
                f'Admin reversal failed for trade {trade_id}',
                default={'trades': []},
            )
            return 409, {'error': execution_message}

        reversed_at = datetime.now(timezone.utc).isoformat()

        def finish_reversal(pending):
            if not isinstance(pending, dict):
                raise TransactionError(500, {'error': 'Trade reversal record is missing'})
            current = next(
                (item for item in pending.get('trades', []) if item['id'] == trade_id), None
            )
            if not current or current.get('reversal_token') != reversal_token:
                raise TransactionError(
                    409, {'error': 'Trade reversal record changed during execution'}
                )
            current['reversal_execution'] = 'done'
            current['reversed_at'] = reversed_at
            current['reversed_by'] = team
            current['reversal_reason'] = reason
            current.pop('reversal_token', None)
            current.pop('last_reversal_error', None)
            return pending, None

        finish_ok, finish_res = update_json_file(
            'data/pending_trades.json',
            finish_reversal,
            f'Admin reversed trade {trade_id}',
            default={'trades': []},
        )
        if not finish_ok:
            return _write_result(finish_ok, finish_res, {})

        add_transaction_log(
            {
                'type': 'admin_reverse_trade',
                'trade_id': trade_id,
                'team': team,
                'proposer': trade['proposer'],
                'partner': trade['partner'],
                'proposer_gives': trade['proposer_gives'],
                'proposer_receives': trade['proposer_receives'],
                'message': f'Reversed completed trade {trade_id}',
                'admin': True,
                'actor': team,
                'reason': reason,
                'timestamp': reversed_at,
            }
        )
        return 200, {'success': True, 'message': f'Trade {trade_id} reversed'}

    if admin_action == 'resolve_conditional_pick':
        condition = str(data.get('condition') or '').strip()
        winning_pick_id = str(data.get('winning_pick_id') or '').strip()
        final_owner = str(data.get('final_owner') or '').strip()
        if not condition:
            return 400, {'error': 'Condition is required'}
        if len(condition) > 500:
            return 400, {'error': 'Condition must be 500 characters or less'}
        if not winning_pick_id:
            return 400, {'error': 'Winning pick is required'}
        winning_match = PICK_ID_RE.match(winning_pick_id)
        if not winning_match:
            return 400, {'error': 'Invalid winning pick'}
        if final_owner not in LEAGUE_TEAMS:
            return 400, {'error': 'Invalid final_owner'}
        if not reason:
            return 400, {'error': 'Reason is required for conditional pick resolutions'}

        winning_key = (
            winning_match.group('year'),
            winning_match.group('draft_type') or 'offseason',
            int(winning_match.group('round')),
            winning_match.group('team'),
        )
        resolved_at = datetime.now(timezone.utc).isoformat()

        def resolve_condition(draft_picks):
            if not isinstance(draft_picks, dict) or not isinstance(draft_picks.get('picks'), list):
                raise TransactionError(500, {'error': 'Draft picks file is malformed'})

            candidates = [
                pick for pick in draft_picks['picks'] if pick.get('condition') == condition
            ]
            if not candidates:
                raise TransactionError(
                    409, {'error': 'This conditional has already been resolved or no longer exists'}
                )

            winner = next(
                (
                    pick
                    for pick in candidates
                    if (
                        str(pick.get('year')),
                        pick.get('draft_type') or 'offseason',
                        pick.get('round'),
                        pick.get('original_team'),
                    )
                    == winning_key
                ),
                None,
            )
            if winner is None:
                raise TransactionError(
                    400, {'error': 'Winning pick is not a candidate for this condition'}
                )

            resolved_picks = []
            for pick in candidates:
                previous_owner = pick.get('current_owner')
                selected = pick is winner
                if selected and previous_owner != final_owner:
                    previous_owners = pick.setdefault('previous_owners', [])
                    if previous_owner and previous_owner not in previous_owners:
                        previous_owners.append(previous_owner)
                    pick['current_owner'] = final_owner
                pick.pop('condition', None)
                pick.pop('conditional_claim', None)
                resolved_picks.append(
                    {
                        'year': str(pick.get('year')),
                        'round': pick.get('round'),
                        'draft_type': pick.get('draft_type') or 'offseason',
                        'original_team': pick.get('original_team'),
                        'previous_owner': previous_owner,
                        'current_owner': pick.get('current_owner'),
                        'selected': selected,
                    }
                )

            draft_picks['updated_at'] = resolved_at
            return draft_picks, resolved_picks

        ok, res = update_json_file(
            'data/draft_picks.json',
            resolve_condition,
            f'Admin resolved conditional pick: {winning_pick_id} to {final_owner}',
            default={'updated_at': resolved_at, 'picks': []},
        )
        if not ok:
            return _write_result(ok, res, {})

        add_transaction_log(
            {
                'type': 'admin_resolve_conditional_pick',
                'condition': condition,
                'winning_pick_id': winning_pick_id,
                'final_owner': final_owner,
                'resolved_picks': res,
                'reason': reason,
                'admin': True,
                'actor': team,
                'timestamp': resolved_at,
            }
        )
        return 200, {
            'success': True,
            'message': f'Resolved {winning_pick_id} to {final_owner}',
            'resolved_picks': res,
        }

    if admin_action == 'score_adjustment':
        target_team = data.get('target_team')
        player_name = str(data.get('player') or '').strip()
        if target_team not in LEAGUE_TEAMS:
            return 400, {'error': 'Invalid target_team'}
        if not player_name:
            return 400, {'error': 'Player name is required'}
        if len(player_name) > 100:
            return 400, {'error': 'Player name must be 100 characters or less'}
        if not reason:
            return 400, {'error': 'Reason is required for score adjustments'}
        try:
            season = int(data.get('season'))
            week = int(data.get('week'))
            points = float(data.get('points'))
        except (TypeError, ValueError):
            return 400, {'error': 'Season, week, and points must be numeric'}
        if not 2020 <= season <= 2100:
            return 400, {'error': 'Season must be between 2020 and 2100'}
        if not 1 <= week <= 18:
            return 400, {'error': 'Week must be between 1 and 18'}
        if not math.isfinite(points):
            return 400, {'error': 'Points must be a finite number'}

        adjustment = {
            'season': season,
            'week': week,
            'team': target_team,
            'player': player_name,
            'points': points,
            'reason': reason,
        }

        def mutate(adjustments):
            if not isinstance(adjustments, list):
                raise TransactionError(500, {'error': 'Score adjustments file is malformed'})
            if adjustment in adjustments:
                raise TransactionError(409, {'error': 'This score adjustment already exists'})
            adjustments.append(adjustment)
            return adjustments, adjustment

        ok, res = update_json_file(
            'data/score_adjustments.json',
            mutate,
            f'Admin score adjustment: {target_team} {points:+g} in {season} week {week}',
            default=[],
        )
        if not ok:
            return _write_result(ok, res, {})
        add_transaction_log(
            {
                'type': 'admin_score_adjustment',
                'team': target_team,
                'player': player_name,
                'points': points,
                'season': season,
                'week': week,
                'reason': reason,
                'admin': True,
                'actor': team,
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }
        )
        return 200, {
            'success': True,
            'message': f'Added {points:+g} point adjustment for {player_name}',
        }

    return 400, {'error': f'Unknown admin_action: {admin_action}'}


def add_transaction_log(transaction: dict):
    """Append a transaction to the log (newest first), de-duped by timestamp.

    Uses the same optimistic read-modify-write so concurrent logging from two
    moves doesn't drop an entry.
    """

    def mutate(log):
        if not isinstance(log, dict):
            log = {'transactions': []}
        existing = log.setdefault('transactions', [])
        ts = transaction.get('timestamp')
        if ts and any(t.get('timestamp') == ts for t in existing):
            return log, None  # already logged
        existing.insert(0, transaction)
        return log, None

    ok, res = update_json_file(
        'data/transaction_log.json',
        mutate,
        f'Transaction logged: {transaction.get("type", "unknown")}',
        default={'transactions': []},
    )
    if not ok:
        print(f'Failed to save transaction log: {res}')


class handler(BaseHTTPRequestHandler):  # noqa: N801
    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        """Handle GET requests."""
        self._send_json(200, {'status': 'Transaction API is running'})

    def do_POST(self):
        """Handle transaction requests."""
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode()) if body else {}

            action = data.get('action')

            if action == 'validate':
                valid, msg = validate_team(data.get('team'), data.get('password'))
                if valid:
                    return self._send_json(200, {'success': True})
                else:
                    return self._send_json(401, {'error': msg})

            elif action == 'taxi_activate':
                status, result = handle_taxi_activation(data)
                return self._send_json(status, result)

            elif action == 'fa_activate':
                status, result = handle_fa_activation(data)
                return self._send_json(status, result)

            elif action == 'release':
                status, result = handle_release(data)
                return self._send_json(status, result)

            elif action == 'propose_trade':
                status, result = handle_propose_trade(data)
                return self._send_json(status, result)

            elif action == 'respond_trade':
                status, result = handle_respond_trade(data)
                return self._send_json(status, result)

            elif action == 'cancel_trade':
                status, result = handle_cancel_trade(data)
                return self._send_json(status, result)

            elif action == 'set_depth_chart':
                status, result = handle_set_depth_chart(data)
                return self._send_json(status, result)

            elif action == 'save_tradeblock':
                status, result = handle_save_tradeblock(data)
                return self._send_json(status, result)

            elif action == 'admin_adjust':
                status, result = handle_admin_adjust(data)
                return self._send_json(status, result)

            else:
                return self._send_json(400, {'error': f'Unknown action: {action}'})

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
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass
