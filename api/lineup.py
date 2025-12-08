"""Vercel Serverless Function for lineup submissions."""

import json
import os
import base64
from http.server import BaseHTTPRequestHandler
import urllib.request

# Team passwords are stored as Vercel environment variables
# Format: TEAM_PASSWORD_GSA, TEAM_PASSWORD_CGK, etc.

# GitHub repo info - Update these for your repo
GITHUB_OWNER = os.environ.get("REPO_OWNER") or os.environ.get("GITHUB_OWNER", "griffin")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "qpfl")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")


def get_team_password(team_abbrev: str) -> str | None:
    """Get the password for a team from environment variables."""
    env_key = f"TEAM_PASSWORD_{team_abbrev.replace('/', '_')}"
    return os.environ.get(env_key)


def update_lineup_file(week: int, team: str, starters: dict, github_token: str, locked_players: list = None) -> tuple[bool, str]:
    """Update the lineup file in the GitHub repo.
    
    Args:
        week: NFL week number
        team: Team abbreviation
        starters: Dict of position -> list of player names
        github_token: GitHub API token
        locked_players: List of player names whose games have started (cannot be changed)
    """
    file_path = f"data/lineups/2025/week_{week}.json"
    api_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{file_path}"
    
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "User-Agent": "QPFL-Lineup-Bot"
    }
    
    current_sha = None
    content = {"week": week, "lineups": {}}
    current_team_lineup = {}
    
    try:
        # Get current file content and SHA
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req) as response:
            current_data = json.loads(response.read().decode())
            current_sha = current_data["sha"]
            content = json.loads(base64.b64decode(current_data["content"]).decode())
            current_team_lineup = content.get("lineups", {}).get(team, {})
    except urllib.error.HTTPError as e:
        if e.code != 404:
            return False, f"Failed to fetch current lineup: {e}"
    
    # Handle locked players - preserve their status from current lineup
    locked_players = locked_players or []
    locked_set = set(locked_players)
    
    if locked_set and current_team_lineup:
        # For each position, ensure locked players maintain their current status
        final_starters = {}
        for pos in ["QB", "RB", "WR", "TE", "K", "D/ST", "HC", "OL"]:
            current_pos_starters = set(current_team_lineup.get(pos, []))
            new_pos_starters = set(starters.get(pos, []))
            
            # Start with new selections for unlocked players
            final_pos = []
            
            # First, add locked players that were starting (must stay starting)
            for player in current_pos_starters:
                if player in locked_set:
                    final_pos.append(player)
            
            # Then add new selections that aren't locked
            for player in new_pos_starters:
                if player not in locked_set and player not in final_pos:
                    final_pos.append(player)
            
            final_starters[pos] = final_pos
        
        starters = final_starters
    
    # Update the lineup for this team
    content["lineups"][team] = starters
    
    # Prepare the update
    new_content = base64.b64encode(json.dumps(content, indent=2).encode()).decode()
    
    update_data = {
        "message": f"Update {team} lineup for Week {week}",
        "content": new_content,
        "branch": GITHUB_BRANCH
    }
    if current_sha:
        update_data["sha"] = current_sha
    
    # Push the update
    try:
        req = urllib.request.Request(
            api_url,
            data=json.dumps(update_data).encode(),
            headers=headers,
            method="PUT"
        )
        with urllib.request.urlopen(req) as response:
            if response.status in [200, 201]:
                return True, "Lineup updated successfully"
            else:
                return False, f"GitHub API returned status {response.status}"
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else str(e)
        return False, f"Failed to update lineup: {error_body}"


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
    
    def do_POST(self):
        """Handle lineup submission."""
        # CORS headers
        self.send_header("Access-Control-Allow-Origin", "*")
        
        try:
            # Parse request body
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode())
            
            team = data.get("team")
            week = data.get("week")
            password = data.get("password")
            starters = data.get("starters")
            locked_players = data.get("locked_players", [])
            
            # Validate required fields
            if not all([team, week, password, starters]):
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Missing required fields"}).encode())
                return
            
            # Validate password
            expected_password = get_team_password(team)
            if not expected_password:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Team not configured"}).encode())
                return
            
            if password != expected_password:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Invalid password"}).encode())
                return
            
            # Validate starters structure
            valid_positions = ["QB", "RB", "WR", "TE", "K", "D/ST", "HC", "OL"]
            max_starters = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "D/ST": 1, "HC": 1, "OL": 1}
            
            for pos, players in starters.items():
                if pos not in valid_positions:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": f"Invalid position: {pos}"}).encode())
                    return
                if len(players) > max_starters.get(pos, 0):
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": f"Too many starters for {pos}"}).encode())
                    return
            
            # Get GitHub token (try multiple env var names)
            github_token = os.environ.get("SKYNET_PAT") or os.environ.get("GITHUB_TOKEN")
            if not github_token:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Server configuration error"}).encode())
                return
            
            # Update the lineup (with locked player protection)
            success, message = update_lineup_file(week, team, starters, github_token, locked_players)
            
            if success:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "message": message}).encode())
            else:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": message}).encode())
                
        except json.JSONDecodeError:
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Invalid JSON"}).encode())
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode())

