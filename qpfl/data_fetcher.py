"""NFL data fetching using nflreadpy."""

import gzip
import json
import re
from pathlib import Path

import polars as pl

try:
    import nflreadpy as nfl
except ImportError as err:
    raise ImportError('Please install nflreadpy: pip install nflreadpy') from err

from .constants import DATA_DIR, TEAM_ABBREV_NORMALIZE

# Offensive line positions
OL_POSITIONS = {'T', 'G', 'C', 'OT', 'OG', 'OL', 'LT', 'RT', 'LG', 'RG'}


def snapshot_path(season: int, week: int, data_dir: Path = DATA_DIR) -> Path:
    """Path to the archived stat snapshot for a scored week (docs/DURABILITY_PLAN.md)."""
    return Path(data_dir) / 'stat_snapshots' / str(season) / f'week_{week}.json.gz'


def save_snapshot(snapshot: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, 'wt', encoding='utf-8') as f:
        json.dump(snapshot, f)


def load_snapshot(path: Path) -> dict:
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        return json.load(f)


class NFLDataFetcher:
    """Fetches and caches NFL stats from nflreadpy."""

    def __init__(self, season: int, week: int):
        self.season = season
        self.week = week
        self._player_stats: pl.DataFrame | None = None
        self._team_stats: pl.DataFrame | None = None
        self._schedules: pl.DataFrame | None = None
        self._pbp: pl.DataFrame | None = None
        self._players_db: pl.DataFrame | None = None

    @classmethod
    def from_snapshot(cls, snapshot: dict, season: int, week: int) -> 'NFLDataFetcher':
        """Rebuild a fetcher entirely from a snapshot (see to_snapshot()) with
        no network access - lets a historical week be re-scored bit-for-bit
        forever, independent of whether nflreadpy/nflverse still exists or has
        renamed/reclassified players since. See docs/DURABILITY_PLAN.md."""
        fetcher = cls(season, week)
        fetcher._player_stats = pl.DataFrame(snapshot['player_stats'])
        fetcher._team_stats = pl.DataFrame(snapshot['team_stats'])
        fetcher._schedules = pl.DataFrame(snapshot['schedules'])
        fetcher._pbp = pl.DataFrame(snapshot['pbp'])
        fetcher._players_db = pl.DataFrame(snapshot['players_db'])
        return fetcher

    def to_snapshot(self) -> dict:
        """Serialize every frame this fetcher used for self.season/self.week
        to plain JSON-safe dicts, for archival to data/stat_snapshots/. Only
        the OL-position slice of players_db is kept (that's all scoring
        consults it for) to keep snapshot size down."""
        ol_players = self.players_db.filter(pl.col('position').is_in(list(OL_POSITIONS)))
        return {
            'season': self.season,
            'week': self.week,
            'player_stats': self.player_stats.to_dicts(),
            'team_stats': self.team_stats.to_dicts(),
            'schedules': self.schedules.to_dicts(),
            'pbp': self.pbp.to_dicts(),
            'players_db': ol_players.to_dicts(),
        }

    @property
    def player_stats(self) -> pl.DataFrame:
        """Lazy load player stats."""
        if self._player_stats is None:
            print(f'Loading player stats for {self.season} week {self.week}...')
            stats = nfl.load_player_stats(seasons=self.season, summary_level='week')
            self._player_stats = stats.filter(pl.col('week') == self.week)
        return self._player_stats

    @property
    def team_stats(self) -> pl.DataFrame:
        """Lazy load team stats."""
        if self._team_stats is None:
            print(f'Loading team stats for {self.season} week {self.week}...')
            stats = nfl.load_team_stats(seasons=self.season, summary_level='week')
            self._team_stats = stats.filter(pl.col('week') == self.week)
        return self._team_stats

    @property
    def schedules(self) -> pl.DataFrame:
        """Lazy load schedules."""
        if self._schedules is None:
            print(f'Loading schedules for {self.season}...')
            schedules = nfl.load_schedules(seasons=self.season)
            self._schedules = schedules.filter(pl.col('week') == self.week)
        return self._schedules

    @property
    def pbp(self) -> pl.DataFrame:
        """Lazy load play-by-play data."""
        if self._pbp is None:
            print(f'Loading play-by-play for {self.season} week {self.week}...')
            pbp = nfl.load_pbp(seasons=self.season)
            self._pbp = pbp.filter(pl.col('week') == self.week)
        return self._pbp

    @property
    def players_db(self) -> pl.DataFrame:
        """Lazy load players database."""
        if self._players_db is None:
            self._players_db = nfl.load_players()
        return self._players_db

    def _normalize_team(self, team: str) -> str:
        """Normalize team abbreviation to nflreadpy format."""
        return TEAM_ABBREV_NORMALIZE.get(team, team)

    def _match_in_frame(self, frame, clean_name: str, require_unique: bool = False) -> dict | None:
        """Try exact -> contains -> unique-last-name matching within `frame`.

        `require_unique` gates the exact/contains stages behind a uniqueness
        check too - used for broad, cross-team/cross-position scopes where a
        namesake elsewhere in the league would otherwise be silently credited
        with the wrong player's stats.
        """
        matches = frame.filter(
            pl.col('player_display_name').str.to_lowercase() == clean_name.lower()
        )
        if matches.height > 0:
            if require_unique and matches.height > 1:
                return None
            return matches.row(0, named=True)

        matches = frame.filter(
            pl.col('player_display_name').str.to_lowercase().str.contains(clean_name.lower())
        )
        if matches.height > 0:
            if require_unique and matches.height > 1:
                return None
            return matches.row(0, named=True)

        name_parts = clean_name.split()
        if len(name_parts) >= 2:
            last_name = name_parts[-1]
            matches = frame.filter(
                pl.col('player_display_name').str.to_lowercase().str.contains(last_name.lower())
            )
            if matches.height == 1:
                return matches.row(0, named=True)

        return None

    def find_player(self, name: str, team: str, position: str) -> dict | None:
        """
        Find a player in the stats by name matching.

        Tries progressively broader scopes so a stale `nfl_team` in
        rosters.json (a traded player) or an unexpected position value doesn't
        silently score 0 all season: (1) team + position, (2) team only
        (drops the position filter - catches a mislabeled position while
        still requiring the player's own team), (3) position only (drops the
        team filter - catches stale nfl_team, but risks matching a namesake
        on another team so it requires a unique match), (4) unfiltered (also
        requires a unique match). The first scope with a match wins; a match
        found only after dropping a filter gets a `_data_note` key set on the
        returned row so callers can flag it. See docs/ROADMAP_2026.md P1.4.

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

        has_position_col = 'position' in stats.columns
        by_position = stats.filter(pl.col('position') == position) if has_position_col else stats
        by_team = stats.filter(pl.col('team') == normalized_team) if normalized_team else stats
        by_team_and_position = (
            by_position.filter(pl.col('team') == normalized_team)
            if normalized_team
            else by_position
        )

        result = self._match_in_frame(by_team_and_position, clean_name)
        if result is not None:
            return result

        # Same team, any position - catches a position value that doesn't
        # line up with nflverse's schema for this row. Still scoped to the
        # player's own team, so no uniqueness requirement is needed.
        if normalized_team:
            result = self._match_in_frame(by_team, clean_name)
            if result is not None:
                result = dict(result)
                result['_data_note'] = (
                    f'{name} not found at position {position} on team {team}; matched by '
                    f'name+team at position {result.get("position", "?")} instead'
                )
                return result

        # Same position, any team - catches a stale nfl_team in rosters.json.
        # This drops the team filter, so require a unique match league-wide;
        # otherwise a namesake on another team could be silently credited.
        if normalized_team:
            result = self._match_in_frame(by_position, clean_name, require_unique=True)
            if result is not None:
                result = dict(result)
                result['_data_note'] = (
                    f'{name} not found on roster team {team}; matched by name+position '
                    f'on {result.get("team", "a different team")} instead (stale nfl_team?)'
                )
                return result

        # Fully unfiltered fallback in case both team and position are off.
        # Require a unique match for the same reason as above.
        result = self._match_in_frame(stats, clean_name, require_unique=True)
        if result is not None:
            result = dict(result)
            result.setdefault(
                '_data_note',
                f'{name} not found on team {team} at position {position}; matched by name '
                f'only (both team and position mismatched)',
            )
            return result

        return None

    def get_team_stats(self, team: str) -> dict | None:
        """Get team stats for D/ST and OL scoring."""
        normalized_team = self._normalize_team(team)
        team_data = self.team_stats.filter(pl.col('team') == normalized_team)

        if team_data.height > 0:
            return team_data.row(0, named=True)
        return None

    def get_opponent_stats(self, team: str) -> dict | None:
        """Get opponent's team stats (for D/ST scoring)."""
        game = self.get_game_info(team)
        if not game:
            return None

        opponent = game.get('opponent')
        if not opponent:
            return None

        return self.get_team_stats(opponent)

    def get_game_info(self, team: str) -> dict | None:
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

    def get_turnovers_returned_for_td(self, player_id: str) -> dict:
        """
        Get count of turnovers returned for TDs by this player.

        Returns dict with:
            - pick_sixes: number of interceptions returned for TD
            - fumble_sixes: number of fumbles returned for TD
        """
        pbp = self.pbp

        # Pick sixes (interceptions returned for TD where this player threw the INT)
        pick_sixes = pbp.filter(
            (pl.col('interception') == 1)
            & (pl.col('return_touchdown') == 1)
            & (pl.col('passer_player_id') == player_id)
        ).height

        # Fumble sixes (fumbles returned for TD where this player fumbled)
        # Check both fumbled_1_player_id and fumbled_2_player_id (for multi-fumble plays)
        fumble_sixes_1 = pbp.filter(
            (pl.col('fumble_lost') == 1)
            & (pl.col('return_touchdown') == 1)
            & (pl.col('fumbled_1_player_id') == player_id)
        ).height

        fumble_sixes_2 = pbp.filter(
            (pl.col('fumble_lost') == 1)
            & (pl.col('return_touchdown') == 1)
            & (pl.col('fumbled_2_player_id') == player_id)
        ).height

        return {
            'pick_sixes': pick_sixes,
            'fumble_sixes': fumble_sixes_1 + fumble_sixes_2,
        }

    def get_extra_fumbles_lost(self, player_id: str, player_stats: dict) -> int:
        """
        Get fumbles lost from PBP that aren't in player stats.

        This catches fumbles on laterals and other plays that don't get
        attributed to the player in the standard stats.

        Also handles multi-fumble plays where fumbled_2_player_id is used.

        Args:
            player_id: Player's NFL ID
            player_stats: Player's stats dict (to compare against)

        Returns:
            Number of additional fumbles lost not in player stats
        """
        pbp = self.pbp

        # Count fumbles lost where this player fumbled (from PBP)
        # Check both fumbled_1_player_id and fumbled_2_player_id
        pbp_fumbles_1 = pbp.filter(
            (pl.col('fumble_lost') == 1) & (pl.col('fumbled_1_player_id') == player_id)
        ).height

        pbp_fumbles_2 = pbp.filter(
            (pl.col('fumble_lost') == 1) & (pl.col('fumbled_2_player_id') == player_id)
        ).height

        pbp_fumbles = pbp_fumbles_1 + pbp_fumbles_2

        # Count fumbles in player stats
        stats_fumbles = (
            (player_stats.get('sack_fumbles_lost', 0) or 0)
            + (player_stats.get('rushing_fumbles_lost', 0) or 0)
            + (player_stats.get('receiving_fumbles_lost', 0) or 0)
        )

        # Extra fumbles = PBP fumbles not in stats
        extra = max(0, pbp_fumbles - stats_fumbles)
        return extra

    def get_ol_touchdowns(self, team: str) -> int:
        """
        Get offensive lineman touchdowns for a team from play-by-play.

        Checks TD scorers against the players database to identify OL positions.

        Args:
            team: Team abbreviation (e.g., 'TB')

        Returns:
            Number of TDs scored by offensive linemen
        """
        normalized_team = self._normalize_team(team)
        pbp = self.pbp
        players = self.players_db

        # Get OL player IDs from the database
        ol_players = players.filter(pl.col('position').is_in(list(OL_POSITIONS)))
        ol_ids = set(ol_players['gsis_id'].to_list())

        # Find TDs by this team
        team_tds = pbp.filter(
            (pl.col('touchdown') == 1)
            & (pl.col('posteam') == normalized_team)
            & (pl.col('td_player_id').is_not_null())
        )

        # Count TDs where scorer is an OL
        ol_td_count = 0
        for row in team_tds.iter_rows(named=True):
            td_id = row.get('td_player_id')
            if td_id and td_id in ol_ids:
                ol_td_count += 1

        return ol_td_count

    def get_defensive_sacks(self, team: str) -> dict:
        """
        Get sack count from both aggregated stats and play-by-play.

        The team_stats 'def_sacks' column can undercount sacks, so we
        also count directly from PBP for accuracy.

        Args:
            team: Team abbreviation (e.g., 'KC')

        Returns:
            Dict with 'aggregated', 'pbp', 'value' (the one to use), and 'discrepancy' flag
        """
        normalized_team = self._normalize_team(team)

        # Get aggregated stats sacks
        team_data = self.team_stats.filter(pl.col('team') == normalized_team)
        agg_sacks = int(team_data['def_sacks'][0]) if team_data.height > 0 else 0

        # Count from PBP
        pbp = self.pbp
        pbp_sacks = pbp.filter(
            (pl.col('defteam') == normalized_team) & (pl.col('sack') == 1)
        ).height

        # Use PBP if different (more accurate)
        discrepancy = agg_sacks != pbp_sacks

        return {
            'aggregated': agg_sacks,
            'pbp': pbp_sacks,
            'value': pbp_sacks if discrepancy else agg_sacks,
            'discrepancy': discrepancy,
        }
