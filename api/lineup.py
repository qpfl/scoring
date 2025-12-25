"""Vercel Serverless Function for lineup submissions."""

from http.server import BaseHTTPRequestHandler
from datetime import datetime, timezone
import json
import os
import base64
import urllib.request
from urllib.error import HTTPError

# GitHub repo info
GITHUB_OWNER = os.environ.get("REPO_OWNER") or os.environ.get("GITHUB_OWNER", "griffin")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "scoring")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")


def get_team_password(team_abbrev: str) -> str | None:
    """Get the password for a team from environment variables."""
    env_key = f"TEAM_PASSWORD_{team_abbrev.replace('/', '_')}"
    return os.environ.get(env_key)


def update_lineup_file(week: int, team: str, starters: dict, github_token: str, locked_players: list = None, comment: str = None, max_retries: int = 3) -> tuple[bool, str]:
    """Update the lineup file in the GitHub repo with retry logic for concurrent updates."""
    import time
    
    file_path = f"data/lineups/2025/week_{week}.json"
    api_url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{file_path}"
    
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "User-Agent": "QPFL-Lineup-Bot"
    }
    
    # Retry loop for handling concurrent updates (409 Conflict)
    for attempt in range(max_retries):
        current_sha = None
        content = {"week": week, "lineups": {}}
        current_team_lineup = {}
        
        try:
            req = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(req) as response:
                current_data = json.loads(response.read().decode())
                current_sha = current_data["sha"]
                content = json.loads(base64.b64decode(current_data["content"]).decode())
                current_team_lineup = content.get("lineups", {}).get(team, {})
        except HTTPError as e:
            if e.code != 404:
                return False, f"Failed to fetch current lineup: {e}"
        
        # Handle locked players
        locked_players_list = locked_players or []
        locked_set = set(locked_players_list)
        
        working_starters = starters.copy()
        
        if locked_set and current_team_lineup:
            final_starters = {}
            for pos in ["QB", "RB", "WR", "TE", "K", "D/ST", "HC", "OL"]:
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
        working_starters["submitted_at"] = datetime.now(timezone.utc).isoformat()
        if comment:
            working_starters["comment"] = comment
        
        content["lineups"][team] = working_starters
        
        new_content = base64.b64encode(json.dumps(content, indent=2).encode()).decode()
        
        update_data = {
            "message": f"Update {team} lineup for Week {week}",
            "content": new_content,
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
                if response.status in [200, 201]:
                    return True, "Lineup updated successfully"
                else:
                    return False, f"GitHub API returned status {response.status}"
        except HTTPError as e:
            if e.code == 409 and attempt < max_retries - 1:
                # Conflict - another update happened, retry with fresh SHA
                print(f"Conflict updating lineup, retrying ({attempt + 1}/{max_retries})...")
                time.sleep(0.5 * (attempt + 1))  # Exponential backoff
                continue
            else:
                error_body = e.read().decode() if hasattr(e, 'read') else str(e)
                return False, f"Failed to update lineup: {error_body}"
    
    return False, "Failed to update lineup after max retries"


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        """Handle CORS preflight - no auth needed."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Content-Length", "0")
        self.end_headers()
    
    def do_GET(self):
        """Handle GET requests - just for testing."""
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "API is running", "method": "GET"}).encode())
    
    def do_POST(self):
        """Handle lineup submission or password validation."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body.decode()) if body else {}
            
            action = data.get("action", "submit")
            team = data.get("team")
            password = data.get("password")
            
            if not team or not password:
                return self._send_json(400, {"error": "Missing team or password"})
            
            expected_password = get_team_password(team)
            if not expected_password:
                return self._send_json(500, {"error": "Team not configured"})
            
            if password != expected_password:
                return self._send_json(401, {"error": "Invalid password"})
            
            if action == "validate":
                return self._send_json(200, {"success": True, "message": "Password valid"})
            
            week = data.get("week")
            starters = data.get("starters")
            locked_players = data.get("locked_players", [])
            comment = data.get("comment", "").strip()
            
            if not all([week, starters]):
                return self._send_json(400, {"error": "Missing required fields for submission"})
            
            valid_positions = ["QB", "RB", "WR", "TE", "K", "D/ST", "HC", "OL"]
            max_starters = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "D/ST": 1, "HC": 1, "OL": 1}
            
            for pos, players in starters.items():
                if pos not in valid_positions:
                    return self._send_json(400, {"error": f"Invalid position: {pos}"})
                if len(players) > max_starters.get(pos, 0):
                    return self._send_json(400, {"error": f"Too many starters for {pos}"})
            
            github_token = os.environ.get("SKYNET_PAT") or os.environ.get("GITHUB_TOKEN")
            if not github_token:
                return self._send_json(500, {"error": "Server configuration error"})
            
            success, message = update_lineup_file(week, team, starters, github_token, locked_players, comment)
            
            if success:
                return self._send_json(200, {"success": True, "message": message})
            else:
                return self._send_json(500, {"error": message})
                
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
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def log_message(self, format, *args):
        """Suppress default logging."""
        pass
