"""Vercel Serverless Function for transaction handling."""

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

# GitHub repo info
GITHUB_OWNER = os.environ.get('REPO_OWNER') or os.environ.get('GITHUB_OWNER', 'griffin')
GITHUB_REPO = os.environ.get('GITHUB_REPO', 'scoring')
GITHUB_BRANCH = os.environ.get('GITHUB_BRANCH', 'main')

TRADE_DEADLINE_WEEK = 12
CURRENT_SEASON = 2026


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


def get_authoritative_current_week() -> int:
    """Read the current week from the committed site data (web/data.json).

    The trade deadline must be enforced against a value the client cannot
    control — otherwise a manager could spoof `current_week` in the request body
    to trade past the deadline. Falls back to 1 (deadline open) if data.json is
    unreachable, matching the prior default behavior.
    """
    try:
        _sha, content = github_get_file('web/data.json')
    except Exception:
        return 1
    if isinstance(content, dict):
        try:
            return int(content.get('current_week', 1))
        except (TypeError, ValueError):
            return 1
    return 1


def validate_team(team: str, password: str) -> tuple[bool, str]:
    """Validate team password."""
    if not team or not password:
        return False, 'Missing team or password'

    expected = get_team_password(team)
    if not expected:
        return False, 'Team not configured'

    if password != expected:
        return False, 'Invalid password'

    return True, 'Valid'


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

    if not all([player_to_activate, player_to_release, week]):
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

    if not all([player_to_add, player_to_release, week]):
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

    def mutate(rosters):
        proposer_roster, proposer_taxi = get_roster_and_taxi(rosters, proposer)
        partner_roster, partner_taxi = get_roster_and_taxi(rosters, partner)

        def _owned(name, roster, taxi):
            return any(p['name'] == name for p in roster) or any(
                p['name'] == name for p in taxi
            )

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

        # Move players proposer gives to partner.
        players_to_partner = []
        for player_name in proposer_gives.get('players', []):
            player = next((p for p in proposer_roster if p['name'] == player_name), None)
            if player:
                proposer_roster = [p for p in proposer_roster if p['name'] != player_name]
            else:
                player = next((p for p in proposer_taxi if p['name'] == player_name), None)
                proposer_taxi = [p for p in proposer_taxi if p['name'] != player_name]
            players_to_partner.append(player)

        # Move players proposer receives from partner.
        players_to_proposer = []
        for player_name in proposer_receives.get('players', []):
            player = next((p for p in partner_roster if p['name'] == player_name), None)
            if player:
                partner_roster = [p for p in partner_roster if p['name'] != player_name]
            else:
                player = next((p for p in partner_taxi if p['name'] == player_name), None)
                partner_taxi = [p for p in partner_taxi if p['name'] != player_name]
            players_to_proposer.append(player)

        partner_roster.extend(players_to_partner)
        proposer_roster.extend(players_to_proposer)

        set_roster_and_taxi(rosters, proposer, proposer_roster, proposer_taxi)
        set_roster_and_taxi(rosters, partner, partner_roster, partner_taxi)
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

    # Update draft pick ownership (separate optimistic write).
    picks_to_transfer = []
    for pick_str in proposer_gives.get('picks', []):
        picks_to_transfer.append((pick_str, proposer, partner))
    for pick_str in proposer_receives.get('picks', []):
        picks_to_transfer.append((pick_str, partner, proposer))

    if picks_to_transfer:

        def mutate_picks(draft_picks):
            picks = draft_picks.get('picks', [])
            for pick_str, from_team, to_team in picks_to_transfer:
                # Format: "2027-R3-CWR" (year-round-original_owner)
                parts = pick_str.split('-')
                if len(parts) >= 3:
                    year = parts[0]
                    round_num = int(parts[1].replace('R', ''))
                    original_team = parts[2]
                    for pick in picks:
                        if (
                            pick.get('year') == year
                            and pick.get('round') == round_num
                            and pick.get('original_team') == original_team
                            and pick.get('current_owner') == from_team
                        ):
                            prev_owners = pick.get('previous_owners', [])
                            if from_team not in prev_owners:
                                prev_owners.append(from_team)
                            pick['previous_owners'] = prev_owners
                            pick['current_owner'] = to_team
                            break
            draft_picks['picks'] = picks
            draft_picks['updated_at'] = datetime.now(timezone.utc).isoformat()
            return draft_picks, None

        update_json_file(
            'data/draft_picks.json',
            mutate_picks,
            f'Pick trade: {proposer} <-> {partner}',
            default={'picks': []},
        )

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

    new_status = 'accepted' if accept else 'rejected'
    player_details = {}

    if accept:
        success, exec_msg, player_details = execute_trade(trade)
        if not success:
            return 409, {'error': exec_msg}

    # Mark the trade resolved. Re-find it inside the mutation so a concurrent
    # write to pending_trades.json isn't clobbered.
    def mutate(pending_now):
        if not isinstance(pending_now, dict):
            raise TransactionError(400, {'error': 'Trade not found'})
        t = next((x for x in pending_now.get('trades', []) if x['id'] == trade_id), None)
        if not t:
            raise TransactionError(400, {'error': 'Trade not found'})
        if t['status'] != 'pending':
            raise TransactionError(400, {'error': f'Trade is already {t["status"]}'})
        t['status'] = new_status
        t[f'{new_status}_at'] = datetime.now(timezone.utc).isoformat()
        return pending_now, None

    ok, res = update_json_file(
        'data/pending_trades.json', mutate, f'Trade {trade_id} {new_status}', default={'trades': []}
    )
    if not ok:
        if isinstance(res, TransactionError):
            return res.status, res.body
        return 500, {'error': res}

    if accept:
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

    return 200, {
        'success': True,
        'message': 'Trade accepted and executed' if accept else 'Trade rejected',
    }


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

            elif action == 'propose_trade':
                status, result = handle_propose_trade(data)
                return self._send_json(status, result)

            elif action == 'respond_trade':
                status, result = handle_respond_trade(data)
                return self._send_json(status, result)

            elif action == 'cancel_trade':
                status, result = handle_cancel_trade(data)
                return self._send_json(status, result)

            elif action == 'save_tradeblock':
                status, result = handle_save_tradeblock(data)
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
