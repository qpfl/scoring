"""NFL data fetching using nflreadpy."""

import re
from typing import Optional

import polars as pl

try:
    import nflreadpy as nfl
except ImportError:
    raise ImportError("Please install nflreadpy: pip install nflreadpy")

from .constants import TEAM_ABBREV_NORMALIZE


class NFLDataFetcher:
    """Fetches and caches NFL stats from nflreadpy."""
    
    def __init__(self, season: int, week: int):
        self.season = season
        self.week = week
        self._player_stats: Optional[pl.DataFrame] = None
        self._team_stats: Optional[pl.DataFrame] = None
        self._schedules: Optional[pl.DataFrame] = None
    
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
    
    def _normalize_team(self, team: str) -> str:
        """Normalize team abbreviation to nflreadpy format."""
        return TEAM_ABBREV_NORMALIZE.get(team, team)
    
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
        
        # Clean up name - remove suffixes like "Sr.", "Jr.", "II", "III"
        clean_name = re.sub(r'\s+(Sr\.?|Jr\.?|II|III|IV|V)$', '', name.strip())
        normalized_team = self._normalize_team(team)
        
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
        normalized_team = self._normalize_team(team)
        team_data = self.team_stats.filter(pl.col('team') == normalized_team)
        
        if team_data.height > 0:
            return team_data.row(0, named=True)
        return None
    
    def get_opponent_stats(self, team: str) -> Optional[dict]:
        """Get opponent's team stats (for D/ST scoring)."""
        game = self.get_game_info(team)
        if not game:
            return None
        
        opponent = game.get('opponent')
        if not opponent:
            return None
        
        return self.get_team_stats(opponent)
    
    def get_game_info(self, team: str) -> Optional[dict]:
        """Get game information for a team."""
        normalized_team = self._normalize_team(team)
        schedules = self.schedules
        
        # Check if home team
        home_game = schedules.filter(pl.col('home_team') == normalized_team)
        if home_game.height > 0:
            row = home_game.row(0, named=True)
            if row.get('home_score') is None:
                return None  # Game hasn't been played yet
            return {
                'team_score': row.get('home_score', 0),
                'opponent_score': row.get('away_score', 0),
                'points_allowed': row.get('away_score', 0),
                'opponent': row.get('away_team'),
                'coach': row.get('home_coach'),
                'is_home': True,
            }
        
        # Check if away team
        away_game = schedules.filter(pl.col('away_team') == normalized_team)
        if away_game.height > 0:
            row = away_game.row(0, named=True)
            if row.get('away_score') is None:
                return None  # Game hasn't been played yet
            return {
                'team_score': row.get('away_score', 0),
                'opponent_score': row.get('home_score', 0),
                'points_allowed': row.get('home_score', 0),
                'opponent': row.get('home_team'),
                'coach': row.get('away_coach'),
                'is_home': False,
            }
        
        return None

