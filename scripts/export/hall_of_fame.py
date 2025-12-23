"""Generate Hall of Fame statistics from all season data."""

import json
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

# Paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent.parent
WEB_DIR = PROJECT_DIR / "web"
DATA_DIR = WEB_DIR / "data"
SEASONS_DIR = DATA_DIR / "seasons"
SHARED_DIR = DATA_DIR / "shared"

# Owner code to display name mapping
OWNER_NAMES = {
    "GSA": "Griff",
    "CGK": "Kaminska",
    "CWR": "Reardon",
    "AYP": "Arnav",
    "JRW": "Joe W.",
    "WJK": "Bill",
    "SLS": "Stephen",
    "RCP": "Ryan P.",
    "RPA": "Ryan A.",
    "MPA": "Miles",
    "S/T": "Spencer/Tim",
    "J/J": "Joe/Joe",
    "AST": "Anagh",
    "TJG": "Tim",
    "SRY": "Spencer",
    "JDK": "Joe K.",
    # Combined codes - map to primary owner
    "CGK/SRY": "Kaminska",
    "CWR/SLS": "Reardon",
}

# Seasons will be loaded dynamically from index.json


def load_season_data(season: int) -> dict:
    """Load all week data for a season."""
    season_dir = SEASONS_DIR / str(season)
    weeks_dir = season_dir / "weeks"
    
    weeks = []
    if weeks_dir.exists():
        for week_file in sorted(weeks_dir.glob("week_*.json")):
            with open(week_file) as f:
                weeks.append(json.load(f))
    
    standings = {}
    standings_file = season_dir / "standings.json"
    if standings_file.exists():
        with open(standings_file) as f:
            standings = json.load(f)
    
    return {"weeks": weeks, "standings": standings, "season": season}


def get_week_name(week_num: int, season: int) -> str:
    """Get display name for a week."""
    if season <= 2021:
        # 8-team: weeks 15-16 are playoffs
        if week_num == 15:
            return "Semi-Finals"
        elif week_num == 16:
            return "Championship Week"
    else:
        # 10-team: weeks 16-17 are playoffs
        if week_num == 16:
            return "Semi-Finals"
        elif week_num == 17:
            return "Championship Week"
    return f"Week {week_num}"


def clean_team_name(name: str) -> str:
    """Remove seeding prefixes like '(1) ' or '3: ' from team names."""
    import re
    # Remove patterns like "(1) ", "(2) ", etc.
    name = re.sub(r'^\(\d+\)\s*', '', name)
    # Remove patterns like "1: ", "2: ", etc.
    name = re.sub(r'^\d+:\s*', '', name)
    # Remove leading/trailing asterisks
    name = name.strip('*').strip()
    return name


def calculate_player_records(all_seasons: list[dict]) -> dict:
    """Calculate player-related records."""
    
    # Track records
    most_points = []  # (points, player_name, team_abbrev, position, week, season)
    most_points_non_qb = []
    least_points_offensive = []
    least_points_kicker = []
    defensive_shame = []  # -6 points
    
    for season_data in all_seasons:
        season = season_data["season"]
        for week in season_data["weeks"]:
            week_num = week["week"]
            week_name = get_week_name(week_num, season)
            
            for matchup in week.get("matchups", []):
                for team_key in ["team1", "team2"]:
                    team = matchup[team_key]
                    team_abbrev = team["abbrev"]
                    
                    for player in team.get("roster", []):
                        if not player.get("starter", False):
                            continue
                            
                        name = player["name"]
                        position = player["position"]
                        score = player.get("score", 0)
                        nfl_team = player.get("nfl_team", "")
                        
                        record = (score, name, team_abbrev, position, week_name, season, nfl_team)
                        
                        # Most points (all positions)
                        most_points.append(record)
                        
                        # Most points non-QB
                        if position != "QB":
                            most_points_non_qb.append(record)
                        
                        # Least points offensive (QB, RB, WR, TE)
                        if position in ("QB", "RB", "WR", "TE"):
                            least_points_offensive.append(record)
                        
                        # Least points kicker
                        if position == "K":
                            least_points_kicker.append(record)
                        
                        # Defensive shame (-6 points)
                        if position in ("D/ST", "DEF") and score == -6:
                            defensive_shame.append(record)
    
    # Sort and get top/bottom records
    most_points.sort(key=lambda x: x[0], reverse=True)
    most_points_non_qb.sort(key=lambda x: x[0], reverse=True)
    least_points_offensive.sort(key=lambda x: x[0])
    least_points_kicker.sort(key=lambda x: x[0])
    
    def format_player_record(r, include_position=False):
        score, name, team_abbrev, position, week_name, season, nfl_team = r
        if include_position:
            return f"{position} {name} ({team_abbrev}) - {score:.0f} ({week_name}, {season})"
        return f"{name} ({team_abbrev}) - {score:.0f} ({week_name}, {season})"
    
    def format_defense_record(r):
        score, name, team_abbrev, position, week_name, season, nfl_team = r
        return f"{name} ({team_abbrev}) - {score:.0f} ({week_name}, {season})"
    
    return {
        "most_points": [format_player_record(r) for r in most_points[:5]],
        "most_points_non_qb": [format_player_record(r) for r in most_points_non_qb[:5]],
        "least_points_offensive": [format_player_record(r, True) for r in least_points_offensive[:5]],
        "least_points_kicker": [format_player_record(r, True) for r in least_points_kicker[:5]],
        "defensive_shame": [format_defense_record(r) for r in defensive_shame],
    }


def calculate_team_records(all_seasons: list[dict]) -> dict:
    """Calculate team-related records."""
    
    # Track records
    most_points = []  # (points, team_name, team_abbrev, week, season)
    least_points = []
    margins = []  # (margin, winner_name, winner_abbrev, loser_name, loser_abbrev, week, season)
    
    for season_data in all_seasons:
        season = season_data["season"]
        for week in season_data["weeks"]:
            week_num = week["week"]
            week_name = get_week_name(week_num, season)
            
            for matchup in week.get("matchups", []):
                t1 = matchup["team1"]
                t2 = matchup["team2"]
                
                s1 = t1.get("total_score", 0)
                s2 = t2.get("total_score", 0)
                
                t1_name = clean_team_name(t1["name"])
                t2_name = clean_team_name(t2["name"])
                
                if s1 > 0:
                    most_points.append((s1, t1_name, t1["abbrev"], week_name, season))
                    least_points.append((s1, t1_name, t1["abbrev"], week_name, season))
                
                if s2 > 0:
                    most_points.append((s2, t2_name, t2["abbrev"], week_name, season))
                    least_points.append((s2, t2_name, t2["abbrev"], week_name, season))
                
                # Margin of victory
                if s1 > 0 and s2 > 0:
                    margin = abs(s1 - s2)
                    if s1 > s2:
                        margins.append((margin, t1_name, t1["abbrev"], t2_name, t2["abbrev"], week_name, season))
                    else:
                        margins.append((margin, t2_name, t2["abbrev"], t1_name, t1["abbrev"], week_name, season))
    
    most_points.sort(key=lambda x: x[0], reverse=True)
    least_points.sort(key=lambda x: x[0])
    margins.sort(key=lambda x: x[0], reverse=True)
    
    def format_team_record(r):
        score, name, abbrev, week_name, season = r
        return f"{name} ({abbrev}) - {score:.0f} ({week_name}, {season})"
    
    def format_margin_record(r):
        margin, winner_name, winner_abbrev, loser_name, loser_abbrev, week_name, season = r
        return f"{winner_name} ({winner_abbrev}) over {loser_name} ({loser_abbrev}) - {margin:.0f} ({week_name}, {season})"
    
    return {
        "most_points": [format_team_record(r) for r in most_points[:5]],
        "least_points": [format_team_record(r) for r in least_points[:5]],
        "largest_margin": [format_margin_record(r) for r in margins[:5]],
    }


# Combined team codes map to their individual owner codes
COMBINED_TEAM_OWNERS = {
    "S/T": ["SRY", "TJG"],      # Spencer + Tim
    "J/J": ["JRW", "JDK"],      # Joe Ward + Joe Kuhl
    "CGK/SRY": ["CGK"],         # Kaminska (with Spencer as co-owner, but CGK is primary)
    "CWR/SLS": ["CWR"],         # Reardon (with Stephen as co-owner, but CWR is primary)
}


def get_owner_codes(abbrev: str) -> list[str]:
    """Get all owner codes for an abbreviation (handles combined teams)."""
    # Check if it's a known combined team
    if abbrev in COMBINED_TEAM_OWNERS:
        return COMBINED_TEAM_OWNERS[abbrev]
    
    # Handle unknown combined codes
    if "/" in abbrev:
        parts = abbrev.split("/")
        # If both parts are short (like S/T, J/J), it's a combined team
        # but we don't know the mapping, so return as-is
        if all(len(p) <= 2 for p in parts):
            return [abbrev]
        # Otherwise return the first part (primary owner)
        return [parts[0]]
    
    return [abbrev]


def calculate_owner_stats(all_seasons: list[dict], finishes_by_year: list[dict]) -> list[dict]:
    """Calculate owner statistics across all seasons."""
    
    # Map owner names (from finishes) to owner codes
    NAME_TO_CODE = {
        "Griffin Ansel": "GSA",
        "Griff": "GSA",
        "Connor Kaminska": "CGK",
        "Kaminska": "CGK",
        "Redacted Kaminska": "CGK",
        "Connor Reardon": "CWR",
        "Reardon": "CWR",
        "Redacted Reardon": "CWR",
        "Arnav Patel": "AYP",
        "Arnav": "AYP",
        "Joe Ward": "JRW",
        "Joe W.": "JRW",
        "Bill": "WJK",
        "Bill Kuhl": "WJK",
        "Stephen Schmidt": "SLS",
        "Stephen": "SLS",
        "Ryan Ansel": "RPA",
        "Ryan": "RPA",
        "Ryan P.": "RCP",
        "Bocki": "RCP",
        "Miles Agus": "MPA",
        "Miles": "MPA",
        "Spencer/Tim": "S/T",
        "Tim/Spencer": "S/T",
        "Joe/Joe": "J/J",
        "Anagh": "AST",
        "Tim": "TJG",
        "Spencer": "SRY",
        "Joe Kuhl": "JDK",
        "Joe K.": "JDK",
        "Censored Ward": "JRW",
    }
    
    # Track stats by owner code
    owner_stats = defaultdict(lambda: {
        "seasons": set(),
        "wins": 0,
        "losses": 0,
        "ties": 0,
        "reg_season_wins": 0,
        "reg_season_losses": 0,
        "reg_season_ties": 0,
        "playoff_wins": 0,
        "playoff_losses": 0,
        "playoff_berths": 0,
        "sewer_series_berths": 0,
        "third_place": 0,
        "second_place": 0,
        "championships": 0,
        "last_place": 0,
        "points_for": 0,
        "points_against": 0,
    })
    
    for season_data in all_seasons:
        season = season_data["season"]
        standings_data = season_data.get("standings", {})
        standings = standings_data.get("standings", [])
        
        # Determine playoff cutoff based on season
        num_teams = 8 if season <= 2021 else 10
        playoff_cutoff = 4  # Top 4 make playoffs in both formats
        
        for i, team in enumerate(standings):
            abbrev = team.get("abbrev", "")
            owner_codes = get_owner_codes(abbrev)
            
            rank = i + 1
            
            # Apply stats to all owners of this team
            for owner_code in owner_codes:
                stats = owner_stats[owner_code]
                stats["seasons"].add(season)
                stats["wins"] += team.get("wins", 0)
                stats["losses"] += team.get("losses", 0)
                stats["ties"] += team.get("ties", 0)
                stats["points_for"] += team.get("points_for", 0)
                stats["points_against"] += team.get("points_against", 0)
                
                # Playoff berths (top 4)
                if rank <= playoff_cutoff:
                    stats["playoff_berths"] += 1
                
                # Sewer series (bottom teams depending on league size)
                if num_teams == 10 and rank > 6:  # 7-10 are sewer series
                    stats["sewer_series_berths"] += 1
                elif num_teams == 8 and rank > 4:  # 5-8 are sewer series
                    stats["sewer_series_berths"] += 1
                
                # Last place
                if rank == num_teams:
                    stats["last_place"] += 1
    
    # Parse championship/placement data from finishes_by_year
    for finish in finishes_by_year:
        year = finish.get("year", "")
        if not year.isdigit():
            continue  # Skip non-year entries like "QPFL MVPs"
        
        results = finish.get("results", [])
        for i, result in enumerate(results):
            if i > 2:  # Only first 3 are 1st, 2nd, 3rd place
                break
            
            # Parse the owner name from the result
            # Handle formats like "Griffin Ansel", "Spencer/Tim", "Connor Reardon & Stephen Schmidt"
            owner_name = result.strip()
            
            # Handle "&" for co-3rd place
            if " & " in owner_name:
                names = owner_name.split(" & ")
            else:
                names = [owner_name]
            
            for name in names:
                name = name.strip()
                owner_code = NAME_TO_CODE.get(name)
                if owner_code:
                    # Get all individual owner codes (handles combined teams like S/T -> SRY, TJG)
                    individual_codes = COMBINED_TEAM_OWNERS.get(owner_code, [owner_code])
                    for code in individual_codes:
                        if i == 0:
                            owner_stats[code]["championships"] += 1
                        elif i == 1:
                            owner_stats[code]["second_place"] += 1
                        elif i == 2:
                            owner_stats[code]["third_place"] += 1
    
    # Process playoff matchups to track playoff wins/losses
    for season_data in all_seasons:
        season = season_data["season"]
        
        # Determine playoff weeks based on season
        if season <= 2021:
            playoff_weeks = [15, 16]  # 8-team: weeks 15-16 are playoffs
        else:
            playoff_weeks = [16, 17]  # 10-team: weeks 16-17 are playoffs
        
        for week in season_data["weeks"]:
            week_num = week["week"]
            if week_num not in playoff_weeks:
                continue
            
            for matchup in week.get("matchups", []):
                # Only count playoff matchups (not sewer series, mid bowl, etc.)
                bracket = matchup.get("bracket", "")
                if bracket not in ("playoffs", "championship", "consolation_cup"):
                    continue
                
                t1 = matchup.get("team1", {})
                t2 = matchup.get("team2", {})
                
                s1 = t1.get("total_score", 0) or t1.get("score", 0)
                s2 = t2.get("total_score", 0) or t2.get("score", 0)
                
                if s1 is None or s2 is None or s1 == 0 or s2 == 0:
                    continue
                
                t1_codes = get_owner_codes(t1.get("abbrev", ""))
                t2_codes = get_owner_codes(t2.get("abbrev", ""))
                
                if s1 > s2:
                    for code in t1_codes:
                        owner_stats[code]["playoff_wins"] += 1
                    for code in t2_codes:
                        owner_stats[code]["playoff_losses"] += 1
                elif s2 > s1:
                    for code in t2_codes:
                        owner_stats[code]["playoff_wins"] += 1
                    for code in t1_codes:
                        owner_stats[code]["playoff_losses"] += 1
    
    # Copy regular season stats from overall (which comes from standings = reg season only)
    for owner_code, stats in owner_stats.items():
        stats["reg_season_wins"] = stats["wins"]
        stats["reg_season_losses"] = stats["losses"]
        stats["reg_season_ties"] = stats["ties"]
    
    # Calculate league averages for Prestige Ranking
    total_reg_season_games = 0
    total_reg_season_wins = 0
    total_playoff_games = 0
    total_playoff_wins = 0
    
    for owner_code, stats in owner_stats.items():
        reg_games = stats["reg_season_wins"] + stats["reg_season_losses"] + stats["reg_season_ties"]
        playoff_games = stats["playoff_wins"] + stats["playoff_losses"]
        
        total_reg_season_games += reg_games
        total_reg_season_wins += stats["reg_season_wins"]
        total_playoff_games += playoff_games
        total_playoff_wins += stats["playoff_wins"]
    
    league_avg_reg_win_pct = total_reg_season_wins / total_reg_season_games if total_reg_season_games > 0 else 0.5
    league_avg_playoff_win_pct = total_playoff_wins / total_playoff_games if total_playoff_games > 0 else 0.5
    
    # Convert to list format
    result = []
    for owner_code, stats in owner_stats.items():
        if not stats["seasons"]:
            continue
            
        total_games = stats["wins"] + stats["losses"] + stats["ties"]
        win_pct = stats["wins"] / total_games * 100 if total_games > 0 else 0
        
        record = f"{stats['wins']}-{stats['losses']}"
        if stats["ties"] > 0:
            record += f"-{stats['ties']}"
        
        # Calculate Prestige Ranking
        # Formula: (1+(Championships x 0.2)) x { ((Reg. Szn Games Played x Reg. Szn. Win %) / (League Avg. Reg. Szn. Win %) x 0.1) + 
        #          ((Playoff Games Played x Playoff Win %) / (League Avg. Playoff Win %) x 0.2) } / # of Szn. in League
        num_seasons = len(stats["seasons"])
        championships = stats["championships"]
        
        reg_games = stats["reg_season_wins"] + stats["reg_season_losses"] + stats["reg_season_ties"]
        reg_win_pct = stats["reg_season_wins"] / reg_games if reg_games > 0 else 0
        
        playoff_games = stats["playoff_wins"] + stats["playoff_losses"]
        playoff_win_pct = stats["playoff_wins"] / playoff_games if playoff_games > 0 else 0
        
        # Avoid division by zero
        reg_component = (reg_games * reg_win_pct) / league_avg_reg_win_pct * 0.1 if league_avg_reg_win_pct > 0 else 0
        playoff_component = (playoff_games * playoff_win_pct) / league_avg_playoff_win_pct * 0.2 if league_avg_playoff_win_pct > 0 else 0
        
        prestige = (1 + (championships * 0.2)) * (reg_component + playoff_component) / num_seasons if num_seasons > 0 else 0
        
        # Playoff record string
        playoff_record = f"{stats['playoff_wins']}-{stats['playoff_losses']}"
        playoff_win_pct_display = (stats["playoff_wins"] / playoff_games * 100) if playoff_games > 0 else 0
        
        result.append({
            "Owner": OWNER_NAMES.get(owner_code, owner_code),
            "Code": owner_code,
            "Seasons": str(num_seasons),
            "Record": record,
            "Win%": f"{win_pct:.1f}%",
            "Points For": f"{stats['points_for']:.0f}",
            "Playoff Berths": str(stats["playoff_berths"]),
            "Playoff Record": playoff_record,
            "Playoff Win%": f"{playoff_win_pct_display:.1f}%",
            "3rd Place": str(stats["third_place"]),
            "2nd Place": str(stats["second_place"]),
            "Rings": str(stats["championships"]),
            "Sewer Series Berths": str(stats["sewer_series_berths"]),
            "Last Place": str(stats["last_place"]),
            "Prestige": f"{prestige:.2f}",
        })
    
    # Combine Spencer (SRY) and Tim (TJG) into "Spencer/Tim" for display
    # Find and merge their stats
    spencer_data = next((r for r in result if r["Code"] == "SRY"), None)
    tim_data = next((r for r in result if r["Code"] == "TJG"), None)
    
    if spencer_data and tim_data:
        # They share S/T stats, so we just need one combined entry
        # Use Spencer's data as base (they should be identical for shared seasons)
        result = [r for r in result if r["Code"] not in ("SRY", "TJG")]
        spencer_data["Owner"] = "Spencer/Tim"
        spencer_data["Code"] = "S/T"
        result.append(spencer_data)
    
    # Sort by Win% (descending)
    result.sort(key=lambda x: float(x["Win%"].rstrip("%")), reverse=True)
    
    return result


def calculate_fun_stats(all_seasons: list[dict]) -> list[dict]:
    """Calculate additional fun statistics."""
    
    fun_stats = []
    
    # Highest scoring week (combined all teams)
    weekly_totals = []
    for season_data in all_seasons:
        season = season_data["season"]
        for week in season_data["weeks"]:
            week_num = week["week"]
            week_name = get_week_name(week_num, season)
            
            total = 0
            for matchup in week.get("matchups", []):
                total += matchup["team1"].get("total_score", 0)
                total += matchup["team2"].get("total_score", 0)
            
            if total > 0:
                weekly_totals.append((total, week_name, season))
    
    weekly_totals.sort(key=lambda x: x[0], reverse=True)
    fun_stats.append({
        "title": "Highest Scoring Week (League Total)",
        "records": [f"{r[0]:.0f} points ({r[1]}, {r[2]})" for r in weekly_totals[:3]]
    })
    
    # Lowest scoring week
    weekly_totals.sort(key=lambda x: x[0])
    fun_stats.append({
        "title": "Lowest Scoring Week (League Total)",
        "records": [f"{r[0]:.0f} points ({r[1]}, {r[2]})" for r in weekly_totals[:3]]
    })
    
    # Closest games
    closest_games = []
    for season_data in all_seasons:
        season = season_data["season"]
        for week in season_data["weeks"]:
            week_num = week["week"]
            week_name = get_week_name(week_num, season)
            
            for matchup in week.get("matchups", []):
                t1 = matchup["team1"]
                t2 = matchup["team2"]
                t1_name = clean_team_name(t1["name"])
                t2_name = clean_team_name(t2["name"])
                s1 = t1.get("total_score", 0)
                s2 = t2.get("total_score", 0)
                
                if s1 > 0 and s2 > 0:
                    margin = abs(s1 - s2)
                    if s1 > s2:
                        closest_games.append((margin, t1_name, t1["abbrev"], s1, t2_name, t2["abbrev"], s2, week_name, season))
                    else:
                        closest_games.append((margin, t2_name, t2["abbrev"], s2, t1_name, t1["abbrev"], s1, week_name, season))
    
    closest_games.sort(key=lambda x: x[0])
    fun_stats.append({
        "title": "Closest Games",
        "records": [
            f"{r[1]} ({r[2]}) {r[3]:.0f} vs {r[4]} ({r[5]}) {r[6]:.0f} - {r[0]:.0f} pt margin ({r[7]}, {r[8]})"
            for r in closest_games[:5]
        ]
    })
    
    # Most combined points in a matchup
    highest_combined = []
    for season_data in all_seasons:
        season = season_data["season"]
        for week in season_data["weeks"]:
            week_num = week["week"]
            week_name = get_week_name(week_num, season)
            
            for matchup in week.get("matchups", []):
                t1 = matchup["team1"]
                t2 = matchup["team2"]
                t1_name = clean_team_name(t1["name"])
                t2_name = clean_team_name(t2["name"])
                s1 = t1.get("total_score", 0)
                s2 = t2.get("total_score", 0)
                
                if s1 > 0 and s2 > 0:
                    combined = s1 + s2
                    highest_combined.append((combined, t1_name, t1["abbrev"], s1, t2_name, t2["abbrev"], s2, week_name, season))
    
    highest_combined.sort(key=lambda x: x[0], reverse=True)
    fun_stats.append({
        "title": "Highest Combined Score (Single Matchup)",
        "records": [
            f"{r[1]} ({r[3]:.0f}) vs {r[4]} ({r[6]:.0f}) = {r[0]:.0f} ({r[7]}, {r[8]})"
            for r in highest_combined[:3]
        ]
    })
    
    # Most consistent scorer (lowest standard deviation in weekly scores)
    # This would require more complex calculation - skip for now
    
    return fun_stats


def generate_hall_of_fame():
    """Generate the complete Hall of Fame data."""
    
    print("Generating Hall of Fame statistics...")
    
    # Load available seasons from index.json
    index_file = DATA_DIR / "index.json"
    if index_file.exists():
        with open(index_file) as f:
            index_data = json.load(f)
        seasons = index_data.get("seasons", index_data.get("available_seasons", [2025]))
    else:
        seasons = [2025]
    
    # Load all season data
    all_seasons = []
    for season in seasons:
        print(f"  Loading {season}...")
        season_data = load_season_data(season)
        all_seasons.append(season_data)
    
    # Load existing hall of fame for finishes_by_year and MVPs (manual data)
    existing_hof = {}
    hof_file = SHARED_DIR / "hall_of_fame.json"
    if hof_file.exists():
        with open(hof_file) as f:
            existing_hof = json.load(f)
    
    finishes_by_year = existing_hof.get("finishes_by_year", [])
    
    # Calculate records
    print("  Calculating player records...")
    player_records = calculate_player_records(all_seasons)
    
    print("  Calculating team records...")
    team_records = calculate_team_records(all_seasons)
    
    print("  Calculating owner stats...")
    owner_stats = calculate_owner_stats(all_seasons, finishes_by_year)
    
    print("  Calculating fun stats...")
    fun_stats = calculate_fun_stats(all_seasons)
    
    # Build output structure
    output = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "finishes_by_year": existing_hof.get("finishes_by_year", []),
        "mvps": existing_hof.get("mvps", []),
        "team_records": [
            {"title": "Most Points Scored (Team)", "records": team_records["most_points"]},
            {"title": "Least Points Scored (Team)", "records": team_records["least_points"]},
            {"title": "Largest Margin of Victory", "records": team_records["largest_margin"]},
        ],
        "player_records": [
            {"title": "Most Points Scored", "records": player_records["most_points"]},
            {"title": "Most Points Scored (Non-QB)", "records": player_records["most_points_non_qb"]},
            {"title": "Least Points Scored (Offensive Player)", "records": player_records["least_points_offensive"]},
            {"title": "Least Points Scored (Kicker)", "records": player_records["least_points_kicker"]},
            {"title": "Defensive Hall of Shame (-6 points)", "records": player_records["defensive_shame"]},
        ],
        "fun_stats": fun_stats,
        "owner_stats": owner_stats,
    }
    
    # Write output
    SHARED_DIR.mkdir(parents=True, exist_ok=True)
    with open(hof_file, "w") as f:
        json.dump(output, f, indent=2)
    
    print(f"  Saved to {hof_file}")
    print("Hall of Fame generated!")
    
    # Print summary
    print("\n=== Summary ===")
    print(f"Seasons analyzed: {seasons}")
    print(f"Top scorer: {player_records['most_points'][0]}")
    print(f"Top team score: {team_records['most_points'][0]}")
    print(f"Largest margin: {team_records['largest_margin'][0]}")


if __name__ == "__main__":
    generate_hall_of_fame()

