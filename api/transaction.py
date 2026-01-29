"""Vercel Serverless Function for transaction handling."""

import base64
import json
import os
import urllib.request
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler
from urllib.error import HTTPError

# GitHub repo info
GITHUB_OWNER = os.environ.get("REPO_OWNER") or os.environ.get("GITHUB_OWNER", "griffin")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "scoring")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")

TRADE_DEADLINE_WEEK = 12
CURRENT_SEASON = 2026


def get_team_password(team_abbrev: str) -> str | None:
    """Get the password for a team from environment variables."""
    env_key = f"TEAM_PASSWORD_{team_abbrev.replace('/', '_')}"
    return os.environ.get(env_key)


def github_api_request(path: str, method: str = "GET", data: dict = None, max_retries: int = 3) -> tuple[bool, dict | str]:
    """Make a GitHub API request with retry logic for concurrent updates."""
    import time

    github_token = os.environ.get("SKYNET_PAT") or os.environ.get("GITHUB_TOKEN")
    if not github_token:
        return False, "Server configuration error - no GitHub token"

    api_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"

    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "User-Agent": "QPFL-Transaction-Bot"
    }

    try:
        if method == "GET":
            req = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode())
                content = json.loads(base64.b64decode(result["content"]).decode())
                return True, {"content": content, "sha": result["sha"]}

        elif method == "PUT":
            # Retry loop for handling concurrent updates (409 Conflict)
            for attempt in range(max_retries):
                # Get current SHA
                req = urllib.request.Request(api_url, headers=headers)
                current_sha = None
                current_content = None
                try:
                    with urllib.request.urlopen(req) as response:
                        result = json.loads(response.read().decode())
                        current_sha = result["sha"]
                        current_content = json.loads(base64.b64decode(result["content"]).decode())
                except HTTPError as e:
                    if e.code != 404:
                        return False, f"Failed to get file: {e}"

                # For transaction logs, merge with current content to avoid losing concurrent updates
                content_to_write = data["content"]
                if "transaction_log" in path and current_content and "transactions" in data["content"]:
                    # Merge: keep all existing transactions and add new ones
                    existing_txns = current_content.get("transactions", [])
                    new_txns = data["content"].get("transactions", [])
                    # Find truly new transactions (not already in existing)
                    existing_timestamps = {t.get("timestamp") for t in existing_txns}
                    merged_txns = existing_txns + [t for t in new_txns if t.get("timestamp") not in existing_timestamps]
                    content_to_write = {"transactions": merged_txns}

                update_data = {
                    "message": data.get("message", "Update file"),
                    "content": base64.b64encode(json.dumps(content_to_write, indent=2).encode()).decode(),
                    "branch": GITHUB_BRANCH
                }
                if current_sha:
                    update_data["sha"] = current_sha

                try:
                    req = urllib.request.Request(
                        api_url,
                        data=json.dumps(update_data).encode(),
                        headers=headers,
                        method="PUT"
                    )
                    with urllib.request.urlopen(req) as response:
                        return True, "File updated successfully"
                except HTTPError as e:
                    if e.code == 409 and attempt < max_retries - 1:
                        # Conflict - another update happened, retry with fresh SHA
                        print(f"Conflict on {path}, retrying ({attempt + 1}/{max_retries})...")
                        time.sleep(0.5 * (attempt + 1))  # Exponential backoff
                        continue
                    else:
                        error_body = e.read().decode() if hasattr(e, 'read') else str(e)
                        return False, f"GitHub API error: {error_body}"

    except HTTPError as e:
        error_body = e.read().decode() if hasattr(e, 'read') else str(e)
        return False, f"GitHub API error: {error_body}"
    except Exception as e:
        return False, str(e)

    return False, "Unknown error"


def validate_team(team: str, password: str) -> tuple[bool, str]:
    """Validate team password."""
    if not team or not password:
        return False, "Missing team or password"

    expected = get_team_password(team)
    if not expected:
        return False, "Team not configured"

    if password != expected:
        return False, "Invalid password"

    return True, "Valid"


def handle_taxi_activation(data: dict) -> tuple[int, dict]:
    """Handle taxi squad activation."""
    team = data.get("team")
    password = data.get("password")
    player_to_activate = data.get("player_to_activate")
    player_to_release = data.get("player_to_release")
    week = data.get("week")

    valid, msg = validate_team(team, password)
    if not valid:
        return 401, {"error": msg}

    if not all([player_to_activate, player_to_release, week]):
        return 400, {"error": "Missing required fields"}

    # Get current roster
    success, result = github_api_request("data/rosters.json")
    if not success:
        return 500, {"error": result}

    rosters = result["content"]
    roster, taxi = get_roster_and_taxi(rosters, team)

    # Validate player_to_activate is in taxi
    taxi_player = next((p for p in taxi if p["name"] == player_to_activate), None)
    if not taxi_player:
        return 400, {"error": f"{player_to_activate} is not on your taxi squad"}

    # Validate player_to_release is in roster and same position
    roster_player = next((p for p in roster if p["name"] == player_to_release), None)
    if not roster_player:
        return 400, {"error": f"{player_to_release} is not on your active roster"}

    if taxi_player["position"] != roster_player["position"]:
        return 400, {"error": f"Position mismatch: {taxi_player['position']} vs {roster_player['position']}"}

    # Execute the swap
    taxi = [p for p in taxi if p["name"] != player_to_activate]
    roster = [p for p in roster if p["name"] != player_to_release]
    roster.append(taxi_player)

    set_roster_and_taxi(rosters, team, roster, taxi)

    # Save updated rosters
    success, msg = github_api_request("data/rosters.json", "PUT", {
        "message": f"Taxi activation: {team} activates {player_to_activate}, releases {player_to_release}",
        "content": rosters
    })

    if not success:
        return 500, {"error": msg}

    # Add to transaction log with full player info
    # Week 0 or 18+ is offseason
    is_offseason = week == 0 or week > 17
    add_transaction_log({
        "type": "taxi_activation",
        "team": team,
        "activated": {
            "name": taxi_player["name"],
            "position": taxi_player.get("position", ""),
            "nfl_team": taxi_player.get("nfl_team", "")
        },
        "released": {
            "name": roster_player["name"],
            "position": roster_player.get("position", ""),
            "nfl_team": roster_player.get("nfl_team", "")
        },
        "week": "Offseason" if is_offseason else week,
        "season": CURRENT_SEASON,
        "timestamp": datetime.utcnow().isoformat()
    })

    return 200, {"success": True, "message": f"Activated {player_to_activate}, released {player_to_release}"}


def handle_fa_activation(data: dict) -> tuple[int, dict]:
    """Handle FA pool activation."""
    team = data.get("team")
    password = data.get("password")
    player_to_add = data.get("player_to_add")
    player_to_release = data.get("player_to_release")
    week = data.get("week")

    valid, msg = validate_team(team, password)
    if not valid:
        return 401, {"error": msg}

    if not all([player_to_add, player_to_release, week]):
        return 400, {"error": "Missing required fields"}

    # Get FA pool
    success, result = github_api_request("data/fa_pool.json")
    if not success:
        return 500, {"error": result}

    fa_pool = result["content"]
    fa_player = next((p for p in fa_pool["players"] if p["name"] == player_to_add and p.get("available", True)), None)
    if not fa_player:
        return 400, {"error": f"{player_to_add} is not available in the FA pool"}

    # Get current roster
    success, result = github_api_request("data/rosters.json")
    if not success:
        return 500, {"error": result}

    rosters = result["content"]
    roster, taxi = get_roster_and_taxi(rosters, team)

    # Validate player_to_release
    roster_player = next((p for p in roster if p["name"] == player_to_release), None)
    if not roster_player:
        return 400, {"error": f"{player_to_release} is not on your active roster"}

    if fa_player["position"] != roster_player["position"]:
        return 400, {"error": f"Position mismatch: {fa_player['position']} vs {roster_player['position']}"}

    # Execute the add
    roster = [p for p in roster if p["name"] != player_to_release]
    roster.append({"name": fa_player["name"], "nfl_team": fa_player["nfl_team"], "position": fa_player["position"]})

    set_roster_and_taxi(rosters, team, roster, taxi)

    # Mark FA player as unavailable
    for p in fa_pool["players"]:
        if p["name"] == player_to_add:
            p["available"] = False
            p["activated_by"] = team
            p["activated_week"] = week

    # Save updates
    success, msg = github_api_request("data/rosters.json", "PUT", {
        "message": f"FA activation: {team} adds {player_to_add}, releases {player_to_release}",
        "content": rosters
    })
    if not success:
        return 500, {"error": msg}

    success, msg = github_api_request("data/fa_pool.json", "PUT", {
        "message": f"FA pool update: {player_to_add} activated by {team}",
        "content": fa_pool
    })
    if not success:
        return 500, {"error": msg}

    # Add to transaction log with full player info
    # Week 0 or 18+ is offseason
    is_offseason = week == 0 or week > 17
    add_transaction_log({
        "type": "fa_activation",
        "team": team,
        "added": {
            "name": fa_player["name"],
            "position": fa_player.get("position", ""),
            "nfl_team": fa_player.get("nfl_team", "")
        },
        "released": {
            "name": roster_player["name"],
            "position": roster_player.get("position", ""),
            "nfl_team": roster_player.get("nfl_team", "")
        },
        "week": "Offseason" if is_offseason else week,
        "season": CURRENT_SEASON,
        "timestamp": datetime.utcnow().isoformat()
    })

    return 200, {"success": True, "message": f"Added {player_to_add} from FA pool, released {player_to_release}"}


def handle_propose_trade(data: dict) -> tuple[int, dict]:
    """Handle trade proposal."""
    team = data.get("team")
    password = data.get("password")
    trade_partner = data.get("trade_partner")
    give_players = data.get("give_players", [])
    give_picks = data.get("give_picks", [])
    receive_players = data.get("receive_players", [])
    receive_picks = data.get("receive_picks", [])
    current_week = data.get("current_week", 1)
    conditions = data.get("conditions", {})
    comment = data.get("comment", "")

    valid, msg = validate_team(team, password)
    if not valid:
        return 401, {"error": msg}

    if not trade_partner:
        return 400, {"error": "Must specify trade partner"}

    if not (give_players or give_picks) and not (receive_players or receive_picks):
        return 400, {"error": "Trade must include players or picks"}

    # Check trade deadline
    # Trading is blocked from week 12 through week 17 (deadline period)
    # Trading is open before week 12 and after week 17 (offseason)
    is_deadline_period = current_week >= TRADE_DEADLINE_WEEK and current_week <= 17
    if is_deadline_period:
        return 400, {"error": f"Trade deadline has passed (Week {TRADE_DEADLINE_WEEK})"}

    # Get pending trades
    success, result = github_api_request("data/pending_trades.json")
    if not success:
        # File might not exist yet
        pending = {"trades": [], "trade_deadline_week": TRADE_DEADLINE_WEEK}
    else:
        pending = result["content"]

    # Create trade proposal
    trade = {
        "id": str(uuid.uuid4())[:8],
        "proposer": team,
        "partner": trade_partner,
        "proposer_gives": {"players": give_players, "picks": give_picks},
        "proposer_receives": {"players": receive_players, "picks": receive_picks},
        "status": "pending",
        "proposed_at": datetime.utcnow().isoformat(),
        "week": current_week
    }

    # Add conditions if provided
    if conditions:
        trade["conditions"] = conditions

    # Add comment if provided
    if comment:
        trade["comment"] = comment

    pending["trades"].append(trade)

    # Save
    success, msg = github_api_request("data/pending_trades.json", "PUT", {
        "message": f"Trade proposed: {team} to {trade_partner}",
        "content": pending
    })

    if not success:
        return 500, {"error": msg}

    return 200, {"success": True, "message": f"Trade proposed to {trade_partner}", "trade_id": trade["id"]}


def get_roster_and_taxi(rosters: dict, team: str) -> tuple[list, list]:
    """Get roster and taxi squad from rosters data, handling all formats."""
    team_data = rosters.get(team, [])
    if isinstance(team_data, list):
        # Flat format with taxi flag: team -> [players] where some have taxi: True
        roster = [p for p in team_data if not p.get("taxi")]
        taxi = [p for p in team_data if p.get("taxi")]
        return roster, taxi
    else:
        # Nested format: team -> {roster: [], taxi_squad: []}
        return team_data.get("roster", []), team_data.get("taxi_squad", [])


def set_roster_and_taxi(rosters: dict, team: str, roster: list, taxi: list):
    """Set roster and taxi squad, preserving the original format."""
    if team in rosters and isinstance(rosters[team], dict):
        rosters[team] = {"roster": roster, "taxi_squad": taxi}
    else:
        # Flat format with taxi flag: merge roster and taxi, marking taxi players
        # Remove taxi flag from roster players, add taxi flag to taxi players
        merged = []
        for p in roster:
            player_copy = {k: v for k, v in p.items() if k != "taxi"}
            merged.append(player_copy)
        for p in taxi:
            player_copy = dict(p.items())
            player_copy["taxi"] = True
            merged.append(player_copy)
        rosters[team] = merged


def execute_trade(trade: dict) -> tuple[bool, str, dict]:
    """Execute a trade by swapping players between teams.

    Returns (success, message, player_details) where player_details contains
    the full player objects with position/team info.
    """
    proposer = trade["proposer"]
    partner = trade["partner"]
    proposer_gives = trade["proposer_gives"]
    proposer_receives = trade["proposer_receives"]

    # Get current rosters
    success, result = github_api_request("data/rosters.json")
    if not success:
        return False, f"Failed to get rosters: {result}", {}

    rosters = result["content"]

    # Get proposer and partner rosters
    proposer_roster, proposer_taxi = get_roster_and_taxi(rosters, proposer)
    partner_roster, partner_taxi = get_roster_and_taxi(rosters, partner)

    # Players proposer gives to partner
    players_to_partner = []
    for player_name in proposer_gives.get("players", []):
        # Find in roster
        player = next((p for p in proposer_roster if p["name"] == player_name), None)
        if player:
            proposer_roster = [p for p in proposer_roster if p["name"] != player_name]
            players_to_partner.append(player)
        else:
            # Check taxi
            player = next((p for p in proposer_taxi if p["name"] == player_name), None)
            if player:
                proposer_taxi = [p for p in proposer_taxi if p["name"] != player_name]
                players_to_partner.append(player)

    # Players proposer receives from partner
    players_to_proposer = []
    for player_name in proposer_receives.get("players", []):
        player = next((p for p in partner_roster if p["name"] == player_name), None)
        if player:
            partner_roster = [p for p in partner_roster if p["name"] != player_name]
            players_to_proposer.append(player)
        else:
            player = next((p for p in partner_taxi if p["name"] == player_name), None)
            if player:
                partner_taxi = [p for p in partner_taxi if p["name"] != player_name]
                players_to_proposer.append(player)

    # Add traded players to new teams
    partner_roster.extend(players_to_partner)
    proposer_roster.extend(players_to_proposer)

    # Update rosters (preserving original format)
    set_roster_and_taxi(rosters, proposer, proposer_roster, proposer_taxi)
    set_roster_and_taxi(rosters, partner, partner_roster, partner_taxi)

    # Save updated rosters
    success, msg = github_api_request("data/rosters.json", "PUT", {
        "message": f"Trade executed: {proposer} <-> {partner}",
        "content": rosters
    })

    if not success:
        return False, f"Failed to save rosters: {msg}", {}

    # Update draft pick ownership
    picks_to_transfer = []
    for pick_str in proposer_gives.get("picks", []):
        # Format: "2027-R3-CWR" (year-round-original_owner)
        picks_to_transfer.append((pick_str, proposer, partner))
    for pick_str in proposer_receives.get("picks", []):
        picks_to_transfer.append((pick_str, partner, proposer))

    if picks_to_transfer:
        success, result = github_api_request("data/draft_picks.json")
        if success:
            draft_picks = result["content"]
            picks = draft_picks.get("picks", [])

            for pick_str, from_team, to_team in picks_to_transfer:
                # Parse pick string: "2027-R3-CWR"
                parts = pick_str.split("-")
                if len(parts) >= 3:
                    year = parts[0]
                    round_num = int(parts[1].replace("R", ""))
                    original_team = parts[2]

                    # Find and update the pick
                    for pick in picks:
                        if (pick.get("year") == year and
                            pick.get("round") == round_num and
                            pick.get("original_team") == original_team and
                            pick.get("current_owner") == from_team):
                            # Add from_team to previous_owners if not already there
                            prev_owners = pick.get("previous_owners", [])
                            if from_team not in prev_owners:
                                prev_owners.append(from_team)
                            pick["previous_owners"] = prev_owners
                            pick["current_owner"] = to_team
                            break

            # Save updated picks
            draft_picks["picks"] = picks
            draft_picks["updated_at"] = datetime.utcnow().isoformat()
            github_api_request("data/draft_picks.json", "PUT", {
                "message": f"Pick trade: {proposer} <-> {partner}",
                "content": draft_picks
            })

    # Return full player objects with position/team info
    player_details = {
        "proposer_gives_players": players_to_partner,
        "proposer_receives_players": players_to_proposer
    }

    return True, "Trade executed successfully", player_details


def handle_respond_trade(data: dict) -> tuple[int, dict]:
    """Handle trade acceptance or rejection."""
    team = data.get("team")
    password = data.get("password")
    trade_id = data.get("trade_id")
    accept = data.get("accept", False)

    valid, msg = validate_team(team, password)
    if not valid:
        return 401, {"error": msg}

    if not trade_id:
        return 400, {"error": "Missing trade_id"}

    # Get pending trades
    success, result = github_api_request("data/pending_trades.json")
    if not success:
        return 500, {"error": result}

    pending = result["content"]
    trade = next((t for t in pending["trades"] if t["id"] == trade_id), None)

    if not trade:
        return 400, {"error": "Trade not found"}

    if trade["partner"] != team:
        return 403, {"error": "You are not the trade partner"}

    if trade["status"] != "pending":
        return 400, {"error": f"Trade is already {trade['status']}"}

    if accept:
        # Execute the trade - swap players
        success, exec_msg, player_details = execute_trade(trade)
        if not success:
            return 500, {"error": exec_msg}

        trade["status"] = "accepted"
        trade["accepted_at"] = datetime.utcnow().isoformat()

        # Add to transaction log with full player info
        # Week 0 or 18+ is offseason
        trade_week = trade.get("week", 0)
        is_offseason = trade_week == 0 or trade_week > 17
        add_transaction_log({
            "type": "trade",
            "proposer": trade["proposer"],
            "partner": trade["partner"],
            "proposer_gives": {
                "players": player_details.get("proposer_gives_players", []),
                "picks": trade["proposer_gives"].get("picks", [])
            },
            "proposer_receives": {
                "players": player_details.get("proposer_receives_players", []),
                "picks": trade["proposer_receives"].get("picks", [])
            },
            "week": "Offseason" if is_offseason else trade_week,
            "season": CURRENT_SEASON,
            "timestamp": datetime.utcnow().isoformat()
        })

        message = "Trade accepted and executed"
    else:
        trade["status"] = "rejected"
        trade["rejected_at"] = datetime.utcnow().isoformat()
        message = "Trade rejected"

    # Save updated pending trades
    success, msg = github_api_request("data/pending_trades.json", "PUT", {
        "message": f"Trade {trade_id} {trade['status']}",
        "content": pending
    })

    if not success:
        return 500, {"error": msg}

    return 200, {"success": True, "message": message}


def handle_cancel_trade(data: dict) -> tuple[int, dict]:
    """Handle trade cancellation by the proposer."""
    team = data.get("team")
    password = data.get("password")
    trade_id = data.get("trade_id")

    valid, msg = validate_team(team, password)
    if not valid:
        return 401, {"error": msg}

    if not trade_id:
        return 400, {"error": "Missing trade_id"}

    # Get pending trades
    success, result = github_api_request("data/pending_trades.json")
    if not success:
        return 500, {"error": result}

    pending = result["content"]
    trade = next((t for t in pending["trades"] if t["id"] == trade_id), None)

    if not trade:
        return 400, {"error": "Trade not found"}

    if trade["proposer"] != team:
        return 403, {"error": "Only the proposer can cancel this trade"}

    if trade["status"] != "pending":
        return 400, {"error": f"Trade is already {trade['status']}"}

    trade["status"] = "cancelled"
    trade["cancelled_at"] = datetime.utcnow().isoformat()

    # Save updated pending trades
    success, msg = github_api_request("data/pending_trades.json", "PUT", {
        "message": f"Trade {trade_id} cancelled by {team}",
        "content": pending
    })

    if not success:
        return 500, {"error": msg}

    return 200, {"success": True, "message": "Trade cancelled"}


def handle_save_tradeblock(data: dict) -> tuple[int, dict]:
    """Handle saving trade block data."""
    team = data.get("team")
    password = data.get("password")
    seeking = data.get("seeking", [])
    trading_away = data.get("trading_away", [])
    players_available = data.get("players_available", [])
    notes = data.get("notes", "")

    valid, msg = validate_team(team, password)
    if not valid:
        return 401, {"error": msg}

    # Get current trade blocks
    success, result = github_api_request("data/trade_blocks.json")
    # File might not exist yet, create empty structure
    trade_blocks = {} if not success else result["content"]

    # Update this team's trade block
    trade_blocks[team] = {
        "seeking": seeking,
        "trading_away": trading_away,
        "players_available": players_available,
        "notes": notes,
        "updated_at": datetime.utcnow().isoformat()
    }

    # Save updated trade blocks
    success, msg = github_api_request("data/trade_blocks.json", "PUT", {
        "message": f"Trade block updated: {team}",
        "content": trade_blocks
    })

    if not success:
        return 500, {"error": msg}

    return 200, {"success": True, "message": "Trade block saved"}


def add_transaction_log(transaction: dict):
    """Add a transaction to the transaction log JSON file."""
    try:
        # Get current transaction log
        success, result = github_api_request("data/transaction_log.json")
        log = result["content"] if success else {"transactions": []}

        # Add new transaction at the beginning (newest first)
        log["transactions"].insert(0, transaction)

        # Save updated log
        success, msg = github_api_request("data/transaction_log.json", "PUT", {
            "message": f"Transaction logged: {transaction.get('type', 'unknown')}",
            "content": log
        })

        if not success:
            print(f"Failed to save transaction log: {msg}")
    except Exception as e:
        print(f"Error logging transaction: {e}")


class handler(BaseHTTPRequestHandler):  # noqa: N801
    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        """Handle GET requests."""
        self._send_json(200, {"status": "Transaction API is running"})

    def do_POST(self):
        """Handle transaction requests."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode()) if body else {}

            action = data.get("action")

            if action == "validate":
                valid, msg = validate_team(data.get("team"), data.get("password"))
                if valid:
                    return self._send_json(200, {"success": True})
                else:
                    return self._send_json(401, {"error": msg})

            elif action == "taxi_activate":
                status, result = handle_taxi_activation(data)
                return self._send_json(status, result)

            elif action == "fa_activate":
                status, result = handle_fa_activation(data)
                return self._send_json(status, result)

            elif action == "propose_trade":
                status, result = handle_propose_trade(data)
                return self._send_json(status, result)

            elif action == "respond_trade":
                status, result = handle_respond_trade(data)
                return self._send_json(status, result)

            elif action == "cancel_trade":
                status, result = handle_cancel_trade(data)
                return self._send_json(status, result)

            elif action == "save_tradeblock":
                status, result = handle_save_tradeblock(data)
                return self._send_json(status, result)

            else:
                return self._send_json(400, {"error": f"Unknown action: {action}"})

        except json.JSONDecodeError:
            return self._send_json(400, {"error": "Invalid JSON"})
        except Exception as e:
            return self._send_json(500, {"error": str(e)})

    def _send_json(self, status_code: int, data: dict):
        """Send JSON response with CORS headers."""
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

