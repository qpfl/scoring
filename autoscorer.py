"""
QPFL Autoscorer

Automatically scores fantasy football lineups using nflreadpy for real-time NFL stats.
Reads rosters from Excel files and calculates scores based on QPFL scoring rules.

Requirements:
    pip install nflreadpy polars pandas openpyxl
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import openpyxl
import polars as pl

try:
    import nflreadpy as nfl
except ImportError:
    raise ImportError("Please install nflreadpy: pip install nflreadpy")


# =============================================================================
# SCORING RULES (from scoring_rules.py)
# =============================================================================

@dataclass
class PlayerScore:
    """Container for a player's score breakdown."""
    name: str
    position: str
    team: str
    total_points: float = 0.0
    breakdown: Dict[str, float] = field(default_factory=dict)
    found_in_stats: bool = False


def score_quarterback(stats: dict) -> Tuple[float, Dict[str, float]]:
    """
    Score a quarterback based on QPFL rules.
    
    Scoring:
        - Passing yards: floor(yards / 25) points
        - Rushing yards: floor(yards / 10) points
        - Receiving yards: floor(yards / 10) points
        - Total TDs (passing + rushing + receiving): 6 points each
        - Turnovers (interceptions + fumbles lost): -2 points each
        - Turnovers returned for TDs: -4 additional points each (not tracked in basic stats)
        - Two point conversions: 2 points each
    """
    points = 0.0
    breakdown = {}
    
    # Passing yards
    passing_yards = stats.get('passing_yards', 0) or 0
    passing_pts = math.floor(passing_yards / 25)
    if passing_pts:
        breakdown['passing_yards'] = passing_pts
    points += passing_pts
    
    # Rushing yards
    rushing_yards = stats.get('rushing_yards', 0) or 0
    rushing_pts = math.floor(rushing_yards / 10)
    if rushing_pts:
        breakdown['rushing_yards'] = rushing_pts
    points += rushing_pts
    
    # Receiving yards (rare for QB but possible)
    receiving_yards = stats.get('receiving_yards', 0) or 0
    receiving_pts = math.floor(receiving_yards / 10)
    if receiving_pts:
        breakdown['receiving_yards'] = receiving_pts
    points += receiving_pts
    
    # Touchdowns (6 points each)
    passing_tds = stats.get('passing_tds', 0) or 0
    rushing_tds = stats.get('rushing_tds', 0) or 0
    receiving_tds = stats.get('receiving_tds', 0) or 0
    total_tds = passing_tds + rushing_tds + receiving_tds
    td_pts = 6 * total_tds
    if td_pts:
        breakdown['touchdowns'] = td_pts
    points += td_pts
    
    # Turnovers (-2 points each)
    interceptions = stats.get('passing_interceptions', 0) or 0
    fumbles_lost = (
        (stats.get('sack_fumbles_lost', 0) or 0) +
        (stats.get('rushing_fumbles_lost', 0) or 0) +
        (stats.get('receiving_fumbles_lost', 0) or 0)
    )
    turnovers = interceptions + fumbles_lost
    turnover_pts = -2 * turnovers
    if turnover_pts:
        breakdown['turnovers'] = turnover_pts
    points += turnover_pts
    
    # Two point conversions (2 points each)
    two_pt = (
        (stats.get('passing_2pt_conversions', 0) or 0) +
        (stats.get('rushing_2pt_conversions', 0) or 0) +
        (stats.get('receiving_2pt_conversions', 0) or 0)
    )
    two_pt_pts = 2 * two_pt
    if two_pt_pts:
        breakdown['two_point_conversions'] = two_pt_pts
    points += two_pt_pts
    
    return points, breakdown


def score_running_back(stats: dict) -> Tuple[float, Dict[str, float]]:
    """
    Score a running back based on QPFL rules.
    
    Scoring:
        - Rushing yards: floor(yards / 10) points
        - Receiving yards: floor(yards / 10) points
        - Passing yards: floor(yards / 25) points (rare)
        - Total TDs: 6 points each
        - Turnovers: -2 points each
        - Two point conversions: 2 points each
    """
    points = 0.0
    breakdown = {}
    
    # Rushing yards
    rushing_yards = stats.get('rushing_yards', 0) or 0
    rushing_pts = math.floor(rushing_yards / 10)
    if rushing_pts:
        breakdown['rushing_yards'] = rushing_pts
    points += rushing_pts
    
    # Receiving yards
    receiving_yards = stats.get('receiving_yards', 0) or 0
    receiving_pts = math.floor(receiving_yards / 10)
    if receiving_pts:
        breakdown['receiving_yards'] = receiving_pts
    points += receiving_pts
    
    # Passing yards (rare for RB)
    passing_yards = stats.get('passing_yards', 0) or 0
    passing_pts = math.floor(passing_yards / 25)
    if passing_pts:
        breakdown['passing_yards'] = passing_pts
    points += passing_pts
    
    # Touchdowns
    passing_tds = stats.get('passing_tds', 0) or 0
    rushing_tds = stats.get('rushing_tds', 0) or 0
    receiving_tds = stats.get('receiving_tds', 0) or 0
    total_tds = passing_tds + rushing_tds + receiving_tds
    td_pts = 6 * total_tds
    if td_pts:
        breakdown['touchdowns'] = td_pts
    points += td_pts
    
    # Turnovers
    interceptions = stats.get('passing_interceptions', 0) or 0
    fumbles_lost = (
        (stats.get('sack_fumbles_lost', 0) or 0) +
        (stats.get('rushing_fumbles_lost', 0) or 0) +
        (stats.get('receiving_fumbles_lost', 0) or 0)
    )
    turnovers = interceptions + fumbles_lost
    turnover_pts = -2 * turnovers
    if turnover_pts:
        breakdown['turnovers'] = turnover_pts
    points += turnover_pts
    
    # Two point conversions
    two_pt = (
        (stats.get('passing_2pt_conversions', 0) or 0) +
        (stats.get('rushing_2pt_conversions', 0) or 0) +
        (stats.get('receiving_2pt_conversions', 0) or 0)
    )
    two_pt_pts = 2 * two_pt
    if two_pt_pts:
        breakdown['two_point_conversions'] = two_pt_pts
    points += two_pt_pts
    
    return points, breakdown


def score_receiver(stats: dict) -> Tuple[float, Dict[str, float]]:
    """
    Score a wide receiver or tight end based on QPFL rules.
    
    Scoring:
        - Receiving yards: floor(yards / 10) points
        - Rushing yards: floor(yards / 10) points
        - Passing yards: floor(yards / 25) points (rare)
        - Total TDs: 6 points each
        - Turnovers: -2 points each
        - Two point conversions: 2 points each
    """
    points = 0.0
    breakdown = {}
    
    # Receiving yards
    receiving_yards = stats.get('receiving_yards', 0) or 0
    receiving_pts = math.floor(receiving_yards / 10)
    if receiving_pts:
        breakdown['receiving_yards'] = receiving_pts
    points += receiving_pts
    
    # Rushing yards
    rushing_yards = stats.get('rushing_yards', 0) or 0
    rushing_pts = math.floor(rushing_yards / 10)
    if rushing_pts:
        breakdown['rushing_yards'] = rushing_pts
    points += rushing_pts
    
    # Passing yards (rare for WR/TE)
    passing_yards = stats.get('passing_yards', 0) or 0
    passing_pts = math.floor(passing_yards / 25)
    if passing_pts:
        breakdown['passing_yards'] = passing_pts
    points += passing_pts
    
    # Touchdowns
    passing_tds = stats.get('passing_tds', 0) or 0
    rushing_tds = stats.get('rushing_tds', 0) or 0
    receiving_tds = stats.get('receiving_tds', 0) or 0
    total_tds = passing_tds + rushing_tds + receiving_tds
    td_pts = 6 * total_tds
    if td_pts:
        breakdown['touchdowns'] = td_pts
    points += td_pts
    
    # Turnovers
    interceptions = stats.get('passing_interceptions', 0) or 0
    fumbles_lost = (
        (stats.get('sack_fumbles_lost', 0) or 0) +
        (stats.get('rushing_fumbles_lost', 0) or 0) +
        (stats.get('receiving_fumbles_lost', 0) or 0)
    )
    turnovers = interceptions + fumbles_lost
    turnover_pts = -2 * turnovers
    if turnover_pts:
        breakdown['turnovers'] = turnover_pts
    points += turnover_pts
    
    # Two point conversions
    two_pt = (
        (stats.get('passing_2pt_conversions', 0) or 0) +
        (stats.get('rushing_2pt_conversions', 0) or 0) +
        (stats.get('receiving_2pt_conversions', 0) or 0)
    )
    two_pt_pts = 2 * two_pt
    if two_pt_pts:
        breakdown['two_point_conversions'] = two_pt_pts
    points += two_pt_pts
    
    return points, breakdown


def score_kicker(stats: dict) -> Tuple[float, Dict[str, float]]:
    """
    Score a kicker based on QPFL rules.
    
    Scoring:
        - PATs made: 1 point each
        - PATs missed: -2 points each
        - FGs 1-29 yards: 1 point each
        - FGs 30-39 yards: 2 points each
        - FGs 40-49 yards: 3 points each
        - FGs 50-59 yards: 4 points each
        - FGs 60-69 yards: 5 points each
        - FGs 70+ yards: 6 points each
        - FGs missed: -1 point each
    """
    points = 0.0
    breakdown = {}
    
    # PATs
    pat_made = stats.get('pat_made', 0) or 0
    pat_missed = stats.get('pat_missed', 0) or 0
    
    if pat_made:
        breakdown['pat_made'] = pat_made
    points += pat_made
    
    if pat_missed:
        breakdown['pat_missed'] = -2 * pat_missed
    points -= 2 * pat_missed
    
    # Field Goals by distance
    # nflreadpy uses: fg_made_0_19, fg_made_20_29, fg_made_30_39, fg_made_40_49, fg_made_50_59, fg_made_60_
    
    # 1-29 yards: 1 point each (combining 0-19 and 20-29)
    fg_0_19 = stats.get('fg_made_0_19', 0) or 0
    fg_20_29 = stats.get('fg_made_20_29', 0) or 0
    fg_1_29 = fg_0_19 + fg_20_29
    if fg_1_29:
        breakdown['fg_1_29'] = fg_1_29
    points += fg_1_29
    
    # 30-39 yards: 2 points each
    fg_30_39 = stats.get('fg_made_30_39', 0) or 0
    if fg_30_39:
        breakdown['fg_30_39'] = 2 * fg_30_39
    points += 2 * fg_30_39
    
    # 40-49 yards: 3 points each
    fg_40_49 = stats.get('fg_made_40_49', 0) or 0
    if fg_40_49:
        breakdown['fg_40_49'] = 3 * fg_40_49
    points += 3 * fg_40_49
    
    # 50-59 yards: 4 points each
    fg_50_59 = stats.get('fg_made_50_59', 0) or 0
    if fg_50_59:
        breakdown['fg_50_59'] = 4 * fg_50_59
    points += 4 * fg_50_59
    
    # 60+ yards: 5 points each (for 60-69) - nflreadpy only has fg_made_60_
    # We'll count all 60+ as 5 points per the original rules
    fg_60_plus = stats.get('fg_made_60_', 0) or 0
    if fg_60_plus:
        breakdown['fg_60+'] = 5 * fg_60_plus
    points += 5 * fg_60_plus
    
    # Missed FGs: -1 point each
    fg_missed = stats.get('fg_missed', 0) or 0
    if fg_missed:
        breakdown['fg_missed'] = -1 * fg_missed
    points -= fg_missed
    
    return points, breakdown


def score_defense(team_stats: dict, opponent_stats: dict, game_info: dict) -> Tuple[float, Dict[str, float]]:
    """
    Score a defense/special teams based on QPFL rules.
    
    Scoring:
        - Points allowed 0: 8 points
        - Points allowed 1-9: 6 points
        - Points allowed 10-13: 4 points
        - Points allowed 14-17: 2 points
        - Points allowed 18-31: 0 points
        - Points allowed 32-35: -2 points
        - Points allowed 36+: -4 points (Note: scoring_rules.py says -6, but 31-35 is -4)
        - Turnovers forced: 2 points each
        - Sacks: 1 point each
        - Safeties: 2 points each
        - Blocked punt/FG: 2 points each
        - Blocked PATs: 1 point each
        - Defensive TDs: 4 points each
    """
    points = 0.0
    breakdown = {}
    
    # Points allowed - from game_info
    points_allowed = game_info.get('points_allowed', 0) or 0
    
    if points_allowed == 0:
        pa_pts = 8
    elif points_allowed <= 9:
        pa_pts = 6
    elif points_allowed <= 13:
        pa_pts = 4
    elif points_allowed <= 17:
        pa_pts = 2
    elif points_allowed <= 31:
        pa_pts = 0  # Note: scoring_rules.py says -2 for 18-31
    elif points_allowed <= 35:
        pa_pts = -2  # Note: scoring_rules.py says -4 for 32-35
    else:
        pa_pts = -4  # Note: scoring_rules.py says -6 for 36+
    
    # Using scoring_rules.py values:
    if points_allowed == 0:
        pa_pts = 8
    elif points_allowed <= 9:
        pa_pts = 6
    elif points_allowed <= 13:
        pa_pts = 4
    elif points_allowed <= 17:
        pa_pts = 2
    elif points_allowed <= 31:
        pa_pts = -2
    elif points_allowed <= 35:
        pa_pts = -4
    else:
        pa_pts = -6
    
    breakdown['points_allowed'] = pa_pts
    points += pa_pts
    
    # Turnovers forced (opponent's turnovers = our forced turnovers)
    # From opponent_stats: interceptions thrown + fumbles lost
    opp_ints = opponent_stats.get('passing_interceptions', 0) or 0
    opp_fumbles_lost = (
        (opponent_stats.get('sack_fumbles_lost', 0) or 0) +
        (opponent_stats.get('rushing_fumbles_lost', 0) or 0) +
        (opponent_stats.get('receiving_fumbles_lost', 0) or 0)
    )
    turnovers_forced = opp_ints + opp_fumbles_lost
    if turnovers_forced:
        breakdown['turnovers_forced'] = 2 * turnovers_forced
    points += 2 * turnovers_forced
    
    # Sacks (from team defensive stats)
    sacks = team_stats.get('def_sacks', 0) or 0
    if sacks:
        breakdown['sacks'] = int(sacks)
    points += int(sacks)
    
    # Safeties
    safeties = team_stats.get('def_safeties', 0) or 0
    if safeties:
        breakdown['safeties'] = 2 * safeties
    points += 2 * safeties
    
    # Blocked punts/FGs (opponent's blocked kicks)
    blocked_fg = opponent_stats.get('fg_blocked', 0) or 0
    # Note: punt blocks aren't directly tracked in team_stats
    blocked_kicks = blocked_fg
    if blocked_kicks:
        breakdown['blocked_kicks'] = 2 * blocked_kicks
    points += 2 * blocked_kicks
    
    # Blocked PATs
    blocked_pat = opponent_stats.get('pat_blocked', 0) or 0
    if blocked_pat:
        breakdown['blocked_pats'] = blocked_pat
    points += blocked_pat
    
    # Defensive TDs
    def_tds = team_stats.get('def_tds', 0) or 0
    # Also include fumble recovery TDs
    fumble_recovery_tds = team_stats.get('fumble_recovery_tds', 0) or 0
    total_def_tds = def_tds + fumble_recovery_tds
    if total_def_tds:
        breakdown['defensive_tds'] = 4 * total_def_tds
    points += 4 * total_def_tds
    
    return points, breakdown


def score_head_coach(game_info: dict) -> Tuple[float, Dict[str, float]]:
    """
    Score a head coach based on QPFL rules.
    
    Scoring:
        - Win by <10: 2 points
        - Win by 10-19: 3 points
        - Win by 20+: 4 points
        - Loss by <10: -1 point
        - Loss by 10-20: -2 points
        - Loss by 20+: -3 points
    """
    points = 0.0
    breakdown = {}
    
    team_score = game_info.get('team_score', 0) or 0
    opponent_score = game_info.get('opponent_score', 0) or 0
    margin = team_score - opponent_score
    
    if margin > 0:  # Win
        if margin < 10:
            points = 2
            breakdown['win_margin_<10'] = 2
        elif margin <= 19:
            points = 3
            breakdown['win_margin_10-19'] = 3
        else:
            points = 4
            breakdown['win_margin_20+'] = 4
    elif margin < 0:  # Loss
        loss_margin = abs(margin)
        if loss_margin < 10:
            points = -1
            breakdown['loss_margin_<10'] = -1
        elif loss_margin <= 20:
            points = -2
            breakdown['loss_margin_10-20'] = -2
        else:
            points = -3
            breakdown['loss_margin_20+'] = -3
    # Tie = 0 points
    
    return points, breakdown


def score_offensive_line(team_stats: dict) -> Tuple[float, Dict[str, float]]:
    """
    Score an offensive line based on QPFL rules.
    
    Scoring:
        - 1 point for every 100 team passing yards
        - 1 point for every 50 team rushing yards
        - -1 point for every sack allowed
        - +6 points for every offensive lineman TD (rare, tracked via special_teams_tds or misc)
    """
    points = 0.0
    breakdown = {}
    
    # Team passing yards: 1 point per 100 yards
    passing_yards = team_stats.get('passing_yards', 0) or 0
    passing_pts = math.floor(passing_yards / 100)
    if passing_pts:
        breakdown['passing_yards'] = passing_pts
    points += passing_pts
    
    # Team rushing yards: 1 point per 50 yards
    rushing_yards = team_stats.get('rushing_yards', 0) or 0
    rushing_pts = math.floor(rushing_yards / 50)
    if rushing_pts:
        breakdown['rushing_yards'] = rushing_pts
    points += rushing_pts
    
    # Sacks allowed: -1 point each
    sacks_allowed = team_stats.get('sacks_suffered', 0) or 0
    if sacks_allowed:
        breakdown['sacks_allowed'] = -sacks_allowed
    points -= sacks_allowed
    
    # Offensive lineman TDs: 6 points each (very rare - fumble recoveries, etc.)
    # These are typically not tracked separately in nflreadpy, but we check fumble_recovery_tds
    # as OL TDs usually come from recovering fumbles in the end zone
    # Note: This is an approximation; true OL TDs are extremely rare
    
    return points, breakdown


# =============================================================================
# EXCEL ROSTER PARSING
# =============================================================================

# Team name to abbreviation mapping
TEAM_ABBREV_MAP = {
    'Arizona Cardinals': 'ARI', 'Atlanta Falcons': 'ATL', 'Baltimore Ravens': 'BAL',
    'Buffalo Bills': 'BUF', 'Carolina Panthers': 'CAR', 'Chicago Bears': 'CHI',
    'Cincinnati Bengals': 'CIN', 'Cleveland Browns': 'CLE', 'Dallas Cowboys': 'DAL',
    'Denver Broncos': 'DEN', 'Detroit Lions': 'DET', 'Green Bay Packers': 'GB',
    'Houston Texans': 'HOU', 'Indianapolis Colts': 'IND', 'Jacksonville Jaguars': 'JAC',
    'Kansas City Chiefs': 'KC', 'Las Vegas Raiders': 'LV', 'Los Angeles Chargers': 'LAC',
    'Los Angeles Rams': 'LAR', 'Miami Dolphins': 'MIA', 'Minnesota Vikings': 'MIN',
    'New England Patriots': 'NE', 'New Orleans Saints': 'NO', 'New York Giants': 'NYG',
    'New York Jets': 'NYJ', 'Philadelphia Eagles': 'PHI', 'Pittsburgh Steelers': 'PIT',
    'San Francisco 49ers': 'SF', 'Seattle Seahawks': 'SEA', 'Tampa Bay Buccaneers': 'TB',
    'Tennessee Titans': 'TEN', 'Washington Commanders': 'WAS'
}

# Reverse mapping
ABBREV_TO_TEAM = {v: k for k, v in TEAM_ABBREV_MAP.items()}

# Team abbreviation normalization (Excel format -> nflreadpy format)
TEAM_ABBREV_NORMALIZE = {
    'LAR': 'LA',   # Los Angeles Rams
    'JAC': 'JAX',  # Jacksonville Jaguars
}


def parse_player_name(cell_value: str) -> Tuple[str, str]:
    """
    Parse player name from Excel format "Player Name (TEAM)" to (name, team_abbrev).
    
    Examples:
        "Patrick Mahomes II (KC)" -> ("Patrick Mahomes II", "KC")
        "San Francisco 49ers (SF)" -> ("San Francisco 49ers", "SF")
    """
    if not cell_value:
        return "", ""
    
    match = re.match(r'^(.+?)\s*\(([A-Z]{2,3})\)$', cell_value.strip())
    if match:
        return match.group(1).strip(), match.group(2)
    return cell_value.strip(), ""


@dataclass
class FantasyTeam:
    """Container for a fantasy team's roster."""
    name: str
    owner: str
    abbreviation: str
    column_index: int  # 1-based column index in Excel
    players: Dict[str, List[Tuple[str, str, bool]]] = field(default_factory=dict)
    # players[position] = [(player_name, nfl_team, is_started), ...]


def parse_roster_from_excel(
    filepath: str,
    sheet_name: str = "Week 13"
) -> List[FantasyTeam]:
    """
    Parse fantasy team rosters from Excel file.
    
    Args:
        filepath: Path to the Excel file
        sheet_name: Name of the sheet to read
        
    Returns:
        List of FantasyTeam objects
    """
    wb = openpyxl.load_workbook(filepath)
    ws = wb[sheet_name]
    
    teams = []
    
    # Teams are in columns: A(1), C(3), E(5), G(7), I(9), K(11), M(13), O(15), Q(17), S(19)
    # Points are in columns: B(2), D(4), F(6), H(8), J(10), L(12), N(14), P(16), R(18), T(20)
    team_columns = [1, 3, 5, 7, 9, 11, 13, 15, 17, 19]
    
    # Row 2: Team names
    # Row 3: Owner names
    # Row 4: Abbreviations
    for col in team_columns:
        team_name_cell = ws.cell(row=2, column=col)
        team_name = team_name_cell.value or ""
        # Remove ** if present from bold formatting
        team_name = team_name.strip().strip('*')
        
        owner = ws.cell(row=3, column=col).value or ""
        abbrev = ws.cell(row=4, column=col).value or ""
        
        if team_name:
            team = FantasyTeam(
                name=team_name,
                owner=owner,
                abbreviation=abbrev,
                column_index=col,
                players={}
            )
            teams.append(team)
    
    # Position rows mapping
    position_rows = {
        'QB': (6, [7, 8, 9]),
        'RB': (11, [12, 13, 14, 15]),
        'WR': (17, [18, 19, 20, 21, 22]),
        'TE': (24, [25, 26, 27]),
        'K': (29, [30, 31]),
        'D/ST': (33, [34, 35]),
        'HC': (37, [38, 39]),
        'OL': (41, [42, 43])
    }
    
    # Parse players for each team
    for team in teams:
        col = team.column_index
        
        for position, (header_row, player_rows) in position_rows.items():
            team.players[position] = []
            
            for row in player_rows:
                cell = ws.cell(row=row, column=col)
                cell_value = cell.value
                
                if cell_value:
                    # Check if bold (started)
                    is_bold = cell.font.bold if cell.font else False
                    player_name, nfl_team = parse_player_name(str(cell_value))
                    
                    if player_name:
                        team.players[position].append((player_name, nfl_team, is_bold))
    
    wb.close()
    return teams


# =============================================================================
# NFL DATA FETCHING
# =============================================================================

class NFLDataFetcher:
    """Fetches and caches NFL stats from nflreadpy."""
    
    def __init__(self, season: int, week: int):
        self.season = season
        self.week = week
        self._player_stats: Optional[pl.DataFrame] = None
        self._team_stats: Optional[pl.DataFrame] = None
        self._schedules: Optional[pl.DataFrame] = None
        self._players: Optional[pl.DataFrame] = None
    
    @property
    def player_stats(self) -> pl.DataFrame:
        """Lazy load player stats."""
        if self._player_stats is None:
            print(f"Loading player stats for {self.season} week {self.week}...")
            stats = nfl.load_player_stats(seasons=self.season, summary_level='week')
            self._player_stats = stats.filter(pl.col('week') == self.week)
        return self._player_stats
    
    @property
    def team_stats(self) -> pl.DataFrame:
        """Lazy load team stats."""
        if self._team_stats is None:
            print(f"Loading team stats for {self.season} week {self.week}...")
            stats = nfl.load_team_stats(seasons=self.season, summary_level='week')
            self._team_stats = stats.filter(pl.col('week') == self.week)
        return self._team_stats
    
    @property
    def schedules(self) -> pl.DataFrame:
        """Lazy load schedules."""
        if self._schedules is None:
            print(f"Loading schedules for {self.season}...")
            schedules = nfl.load_schedules(seasons=self.season)
            self._schedules = schedules.filter(pl.col('week') == self.week)
        return self._schedules
    
    @property
    def players(self) -> pl.DataFrame:
        """Lazy load player database."""
        if self._players is None:
            print("Loading player database...")
            self._players = nfl.load_players()
        return self._players
    
    def find_player(self, name: str, team: str, position: str) -> Optional[dict]:
        """
        Find a player in the stats by name matching.
        
        Args:
            name: Player name from Excel (e.g., "Patrick Mahomes II")
            team: Team abbreviation (e.g., "KC")
            position: Position (e.g., "QB")
            
        Returns:
            Dict of player stats or None if not found
        """
        stats = self.player_stats
        
        # Try exact match on player_display_name first
        # Clean up name - remove suffixes like "Sr.", "Jr.", "II", "III"
        clean_name = re.sub(r'\s+(Sr\.?|Jr\.?|II|III|IV|V)$', '', name.strip())
        
        # Normalize team abbreviation
        normalized_team = TEAM_ABBREV_NORMALIZE.get(team, team)
        
        # Filter by team first if provided
        if normalized_team:
            team_stats = stats.filter(pl.col('team') == normalized_team)
        else:
            team_stats = stats
        
        # Try exact match on display name
        matches = team_stats.filter(
            pl.col('player_display_name').str.to_lowercase() == clean_name.lower()
        )
        
        if matches.height > 0:
            return matches.row(0, named=True)
        
        # Try contains match
        matches = team_stats.filter(
            pl.col('player_display_name').str.to_lowercase().str.contains(clean_name.lower())
        )
        
        if matches.height > 0:
            return matches.row(0, named=True)
        
        # Try matching just last name
        name_parts = clean_name.split()
        if len(name_parts) >= 2:
            last_name = name_parts[-1]
            matches = team_stats.filter(
                pl.col('player_display_name').str.to_lowercase().str.contains(last_name.lower())
            )
            
            if matches.height == 1:
                return matches.row(0, named=True)
        
        return None
    
    def get_team_stats(self, team: str) -> Optional[dict]:
        """Get team stats for D/ST and OL scoring."""
        stats = self.team_stats
        # Normalize team abbreviation
        normalized_team = TEAM_ABBREV_NORMALIZE.get(team, team)
        team_data = stats.filter(pl.col('team') == normalized_team)
        
        if team_data.height > 0:
            return team_data.row(0, named=True)
        return None
    
    def get_opponent_stats(self, team: str) -> Optional[dict]:
        """Get opponent's team stats (for D/ST scoring)."""
        # First find who the opponent was
        # Normalize team abbreviation
        normalized_team = TEAM_ABBREV_NORMALIZE.get(team, team)
        game = self.get_game_info(normalized_team)
        if not game:
            return None
        
        opponent = game.get('opponent')
        if not opponent:
            return None
        
        return self.get_team_stats(opponent)
    
    def get_game_info(self, team: str) -> Optional[dict]:
        """Get game information for a team."""
        schedules = self.schedules
        # Normalize team abbreviation
        normalized_team = TEAM_ABBREV_NORMALIZE.get(team, team)
        
        # Check if home team
        home_game = schedules.filter(pl.col('home_team') == normalized_team)
        if home_game.height > 0:
            row = home_game.row(0, named=True)
            # Check if game has been played (scores exist)
            if row.get('home_score') is None:
                return None  # Game hasn't been played yet
            return {
                'team_score': row.get('home_score', 0),
                'opponent_score': row.get('away_score', 0),
                'points_allowed': row.get('away_score', 0),
                'opponent': row.get('away_team'),
                'coach': row.get('home_coach'),
                'is_home': True
            }
        
        # Check if away team
        away_game = schedules.filter(pl.col('away_team') == normalized_team)
        if away_game.height > 0:
            row = away_game.row(0, named=True)
            # Check if game has been played (scores exist)
            if row.get('away_score') is None:
                return None  # Game hasn't been played yet
            return {
                'team_score': row.get('away_score', 0),
                'opponent_score': row.get('home_score', 0),
                'points_allowed': row.get('home_score', 0),
                'opponent': row.get('home_team'),
                'coach': row.get('away_coach'),
                'is_home': False
            }
        
        return None


# =============================================================================
# MAIN SCORING ENGINE
# =============================================================================

class QPFLScorer:
    """Main scoring engine for QPFL fantasy football."""
    
    def __init__(self, season: int, week: int):
        self.season = season
        self.week = week
        self.data = NFLDataFetcher(season, week)
    
    def score_player(
        self,
        name: str,
        team: str,
        position: str
    ) -> PlayerScore:
        """Score a single player."""
        result = PlayerScore(name=name, position=position, team=team)
        
        if position in ('QB', 'RB', 'WR', 'TE', 'K'):
            # Find player stats
            stats = self.data.find_player(name, team, position)
            
            if stats:
                result.found_in_stats = True
                
                if position == 'QB':
                    result.total_points, result.breakdown = score_quarterback(stats)
                elif position == 'RB':
                    result.total_points, result.breakdown = score_running_back(stats)
                elif position in ('WR', 'TE'):
                    result.total_points, result.breakdown = score_receiver(stats)
                elif position == 'K':
                    result.total_points, result.breakdown = score_kicker(stats)
            else:
                # Player not found - could be on bye, injured, or name mismatch
                pass
        
        elif position == 'D/ST':
            # D/ST scoring uses team name
            team_stats = self.data.get_team_stats(team)
            opponent_stats = self.data.get_opponent_stats(team)
            game_info = self.data.get_game_info(team)
            
            if team_stats and game_info:
                result.found_in_stats = True
                result.total_points, result.breakdown = score_defense(
                    team_stats, opponent_stats or {}, game_info
                )
        
        elif position == 'HC':
            # HC scoring uses game result
            game_info = self.data.get_game_info(team)
            
            if game_info:
                result.found_in_stats = True
                result.total_points, result.breakdown = score_head_coach(game_info)
        
        elif position == 'OL':
            # OL scoring uses team stats
            team_stats = self.data.get_team_stats(team)
            
            if team_stats:
                result.found_in_stats = True
                result.total_points, result.breakdown = score_offensive_line(team_stats)
        
        return result
    
    def score_fantasy_team(self, team: FantasyTeam) -> Dict[str, List[PlayerScore]]:
        """Score all started players on a fantasy team."""
        results = {}
        
        for position, players in team.players.items():
            results[position] = []
            
            for player_name, nfl_team, is_started in players:
                if is_started:
                    score = self.score_player(player_name, nfl_team, position)
                    results[position].append(score)
        
        return results
    
    def calculate_team_total(self, scores: Dict[str, List[PlayerScore]]) -> float:
        """Calculate total score for a fantasy team."""
        total = 0.0
        for position_scores in scores.values():
            for score in position_scores:
                total += score.total_points
        return total


def score_week(
    excel_path: str,
    sheet_name: str,
    season: int,
    week: int,
    verbose: bool = True
) -> Dict[str, Tuple[float, Dict[str, List[PlayerScore]]]]:
    """
    Score all fantasy teams for a given week.
    
    Args:
        excel_path: Path to the Excel file with rosters
        sheet_name: Name of the sheet to read
        season: NFL season year
        week: Week number
        verbose: Whether to print detailed output
        
    Returns:
        Dict mapping team name to (total_score, position_scores)
    """
    # Parse rosters
    teams = parse_roster_from_excel(excel_path, sheet_name)
    
    if verbose:
        print(f"\nFound {len(teams)} fantasy teams")
        for team in teams:
            started_count = sum(
                1 for players in team.players.values() 
                for _, _, is_started in players if is_started
            )
            print(f"  - {team.name} ({team.abbreviation}): {started_count} started players")
    
    # Initialize scorer
    scorer = QPFLScorer(season, week)
    
    # Score each team
    results = {}
    
    for team in teams:
        if verbose:
            print(f"\n{'='*60}")
            print(f"Scoring: {team.name}")
            print('='*60)
        
        scores = scorer.score_fantasy_team(team)
        total = scorer.calculate_team_total(scores)
        
        if verbose:
            for position, player_scores in scores.items():
                for ps in player_scores:
                    status = "✓" if ps.found_in_stats else "✗"
                    print(f"  {position} {ps.name} ({ps.team}): {ps.total_points:.1f} pts {status}")
                    if ps.breakdown:
                        for key, val in ps.breakdown.items():
                            print(f"      {key}: {val}")
            
            print(f"\n  TOTAL: {total:.1f} points")
        
        results[team.name] = (total, scores)
    
    return results


def update_excel_scores(
    excel_path: str,
    sheet_name: str,
    results: Dict[str, Tuple[float, Dict[str, List[PlayerScore]]]]
):
    """
    Update the Excel file with calculated scores.
    
    Args:
        excel_path: Path to the Excel file
        sheet_name: Sheet to update
        results: Scoring results from score_week()
    """
    wb = openpyxl.load_workbook(excel_path)
    ws = wb[sheet_name]
    
    teams = parse_roster_from_excel(excel_path, sheet_name)
    
    # Position rows mapping
    position_rows = {
        'QB': [7, 8, 9],
        'RB': [12, 13, 14, 15],
        'WR': [18, 19, 20, 21, 22],
        'TE': [25, 26, 27],
        'K': [30, 31],
        'D/ST': [34, 35],
        'HC': [38, 39],
        'OL': [42, 43]
    }
    
    for team in teams:
        if team.name not in results:
            continue
        
        total, scores = results[team.name]
        points_col = team.column_index + 1  # Points column is next to player column
        
        for position, player_rows in position_rows.items():
            if position not in scores:
                continue
            
            # Match scored players to their rows
            for player_name, nfl_team, is_started in team.players.get(position, []):
                if not is_started:
                    continue
                
                # Find the score for this player
                player_score = None
                for ps in scores[position]:
                    if ps.name == player_name:
                        player_score = ps
                        break
                
                if player_score is None:
                    continue
                
                # Find the row for this player
                for row in player_rows:
                    cell = ws.cell(row=row, column=team.column_index)
                    if cell.value:
                        parsed_name, _ = parse_player_name(str(cell.value))
                        if parsed_name == player_name:
                            # Update the score cell
                            score_cell = ws.cell(row=row, column=points_col)
                            score_cell.value = player_score.total_points
                            break
    
    wb.save(excel_path)
    print(f"\nScores saved to {excel_path}")


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="QPFL Fantasy Football Autoscorer")
    parser.add_argument(
        "--excel", "-e",
        default="2025 Scores.xlsx",
        help="Path to the Excel file with rosters"
    )
    parser.add_argument(
        "--sheet", "-s",
        default="Week 13",
        help="Sheet name to score"
    )
    parser.add_argument(
        "--season", "-y",
        type=int,
        default=2025,
        help="NFL season year"
    )
    parser.add_argument(
        "--week", "-w",
        type=int,
        default=13,
        help="Week number to score"
    )
    parser.add_argument(
        "--update", "-u",
        action="store_true",
        help="Update Excel file with scores"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress detailed output"
    )
    
    args = parser.parse_args()
    
    # Score the week
    results = score_week(
        excel_path=args.excel,
        sheet_name=args.sheet,
        season=args.season,
        week=args.week,
        verbose=not args.quiet
    )
    
    # Print summary
    print("\n" + "="*60)
    print("FINAL STANDINGS")
    print("="*60)
    
    sorted_results = sorted(results.items(), key=lambda x: x[1][0], reverse=True)
    for rank, (team_name, (total, _)) in enumerate(sorted_results, 1):
        print(f"  {rank}. {team_name}: {total:.1f} pts")
    
    # Update Excel if requested
    if args.update:
        update_excel_scores(args.excel, args.sheet, results)
