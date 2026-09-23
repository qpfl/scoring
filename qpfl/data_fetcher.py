"""NFL data fetching using nflreadpy."""

import gzip
import json
import re
import time
from pathlib import Path
from typing import cast

import polars as pl

try:
    import nflreadpy as nfl
except ImportError as err:
    raise ImportError('Please install nflreadpy: pip install nflreadpy') from err

from .constants import DATA_DIR, TEAM_ABBREV_NORMALIZE

# Offensive line positions
OL_POSITIONS = {'T', 'G', 'C', 'OT', 'OG', 'OL', 'LT', 'RT', 'LG', 'RG'}

# Waits between download attempts. nflreadpy makes a single HTTP attempt, and
# nflverse's delete-and-re-upload publishing leaves a window of a minute or
# two where an asset 404s; retrying across it keeps one blip from failing the
# run and paging the commissioner.
LOAD_RETRY_DELAYS_SECONDS: tuple[float, ...] = (30.0, 90.0)


class SeasonStatsUnavailableError(RuntimeError):
    """nflverse has not published this season's stat files yet.

    The per-season parquet files (stats_player_week_{season}, stats_team_week_
    {season}, play-by-play) only appear once the season's first games have been
    played, so any scoring run between the schedule dropping and Week 1 kickoff
    hits a 404. That's an expected state, not a failure - see stats_available.
    """


def _is_unpublished_season(err: Exception) -> bool:
    """Whether `err` means "nflverse doesn't have this season yet" rather than a
    real outage. A missing release asset 404s; load_pbp() range-checks the season
    up front and raises ValueError instead.

    This is a necessary but not sufficient signal: nflverse also 404s
    mid-season during a release-asset delete+re-upload (it publishes by
    replacing the whole file), which looks identical to "unpublished" by
    message alone. Callers must additionally confirm the season genuinely
    has no completed games yet - see `_season_has_played_games` - before
    treating a 404 as "score this as zero" rather than a transient outage.
    """
    message = str(err)
    return '404' in message or 'Season must be between' in message


def snapshot_path(season: int, week: int, data_dir: Path = DATA_DIR) -> Path:
    """Path to the archived stat snapshot for a scored week (docs/DURABILITY_PLAN.md)."""
    return Path(data_dir) / 'stat_snapshots' / str(season) / f'week_{week}.json.gz'


# Projection context archived alongside the stats. It changes daily (depth
# charts, NFL roster statuses, other weeks' lines and results) without
# changing any score, so a difference only here doesn't earn a new ~2.5 MB
# compressed blob in git history.
VOLATILE_SNAPSHOT_KEYS = frozenset(
    {'projection_rosters', 'projection_depth_charts', 'projection_schedules'}
)


def save_snapshot(snapshot: dict, path: Path) -> bool:
    """Write a reproducible gzip archive, skipping a rewrite that changes no stats."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(snapshot, sort_keys=True, separators=(',', ':')).encode()
    compressed = gzip.compress(payload, mtime=0)
    if path.exists():
        if path.read_bytes() == compressed:
            return False
        try:
            existing = load_snapshot(path)
        except (OSError, ValueError):
            existing = None
        if isinstance(existing, dict) and _stable_part(existing) == _stable_part(snapshot):
            return False

    temporary_path = path.with_suffix(f'{path.suffix}.tmp')
    temporary_path.write_bytes(compressed)
    temporary_path.replace(path)
    return True


def _stable_part(snapshot: dict) -> dict:
    return {key: value for key, value in snapshot.items() if key not in VOLATILE_SNAPSHOT_KEYS}


def load_snapshot(path: Path) -> dict:
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        snapshot = json.load(f)
    if not isinstance(snapshot, dict):
        raise ValueError(f'Snapshot must contain a JSON object: {path}')
    return snapshot


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
        self._stats_available: bool | None = None

    @classmethod
    def from_snapshot(cls, snapshot: dict, season: int, week: int) -> 'NFLDataFetcher':
        """Rebuild a fetcher entirely from a snapshot (see to_snapshot()) with
        no network access - lets a historical week be re-scored bit-for-bit
        forever, independent of whether nflreadpy/nflverse still exists or has
        renamed/reclassified players since. See docs/DURABILITY_PLAN.md."""
        fetcher = cls(season, week)
        # infer_schema_length=None scans every row rather than just the first
        # 100: pbp has 300+ sparsely-populated columns, so a column that's
        # null in the initial sample but a string (e.g. a player id) further
        # down would otherwise make polars guess the wrong dtype and error.
        fetcher._player_stats = pl.DataFrame(snapshot['player_stats'], infer_schema_length=None)
        fetcher._team_stats = pl.DataFrame(snapshot['team_stats'], infer_schema_length=None)
        fetcher._schedules = pl.DataFrame(snapshot['schedules'], infer_schema_length=None)
        fetcher._pbp = pl.DataFrame(snapshot['pbp'], infer_schema_length=None)
        fetcher._players_db = pl.DataFrame(snapshot['players_db'], infer_schema_length=None)
        # A few pre-kickoff snapshots were created after the season-level files
        # existed but before this week's rows did. Treat those archives as an
        # all-zero feed instead of trying to filter schema-less empty frames.
        fetcher._stats_available = not fetcher._player_stats.is_empty()
        return fetcher

    def to_snapshot(self) -> dict:
        """Serialize every frame this fetcher used for self.season/self.week
        to plain JSON-safe dicts, for archival to data/stat_snapshots/. Only
        the OL-position slice of players_db is kept (that's all scoring
        consults it for) to keep snapshot size down."""
        if not self.week_stats_available:
            raise SeasonStatsUnavailableError(
                f'Cannot snapshot {self.season} week {self.week}: nflverse has not '
                'published stats for this week yet'
            )
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
    def stats_available(self) -> bool:
        """Whether nflverse has published this season's stats yet.

        Before the season's first game there are no stat files to download, so
        scoring should behave the way it already does for a game that hasn't
        kicked off: nobody is found, everybody scores 0. Callers that need real
        stats (snapshot archival) should check this first.
        """
        if self._stats_available is None:
            try:
                _ = self.player_stats
                self._stats_available = True
            except SeasonStatsUnavailableError as err:
                print(f'⚠️  {err}')
                self._stats_available = False
        return self._stats_available

    @property
    def week_stats_available(self) -> bool:
        """Whether the target week has at least one published player stat row."""
        return self.stats_available and not self.player_stats.is_empty()

    def _season_has_played_games(self) -> bool:
        """Whether any REG game of this season already has a final result.

        The schedule is published well before any stat files and rarely 404s
        for "unpublished" the way stat/pbp loaders do, so it is a reliable way
        to tell a genuinely pre-season 404 (nobody has played yet - score as
        zero) apart from a mid-season 404 during nflverse's delete+re-upload
        of a release asset (a transient outage that must not zero real
        scores). If the schedule itself can't be loaded, fail toward "yes" -
        an inability to tell should raise, not silently zero a played week.
        """
        try:
            schedule_rows = nfl.load_schedules(seasons=self.season).to_dicts()
        except Exception:
            return True
        return any(
            row.get('game_type') == 'REG' and row.get('result') not in (None, '')
            for row in schedule_rows
        )

    def _load(self, loader, label: str, **kwargs) -> pl.DataFrame:
        """Call an nflreadpy loader, converting "season not published yet" into
        SeasonStatsUnavailableError and leaving every other failure alone.

        A 404 partway through the season - nflverse publishes stat files by
        deleting and re-uploading the release asset, so this is a real window
        - is NOT treated as "unpublished"; it's re-raised as a transient
        outage so the caller aborts instead of committing an all-zero week
        over real scores. See docs/ROADMAP_2026.md P3.1 / the in-season
        reliability plan, phase 2.1. That 404 and plain network errors are
        retried after LOAD_RETRY_DELAYS_SECONDS before giving up.
        """
        delays = list(LOAD_RETRY_DELAYS_SECONDS)
        while True:
            try:
                frame: pl.DataFrame = loader(**kwargs)
                return frame
            except (ConnectionError, OSError, ValueError) as err:
                unpublished = _is_unpublished_season(err)
                if not unpublished and not isinstance(err, (ConnectionError, OSError)):
                    raise
                if unpublished and not self._season_has_played_games():
                    raise SeasonStatsUnavailableError(
                        f'nflverse has not published {label} for {self.season} yet '
                        '(no games played) - scoring this week as all zeros'
                    ) from err
                if delays:
                    delay = delays.pop(0)
                    print(f'⚠️  Loading {label} failed ({err}); retrying in {delay:.0f}s')
                    time.sleep(delay)
                    continue
                if not unpublished:
                    raise
                raise ConnectionError(
                    f'nflverse returned a "not published" error for {label} '
                    f'({self.season}), but the season has already played games - '
                    'treating this as a transient outage (e.g. mid-publish '
                    'delete+re-upload), not an unplayed season, so this week is '
                    'not scored as all zeros'
                ) from err

    @property
    def player_stats(self) -> pl.DataFrame:
        """Lazy load player stats."""
        if self._player_stats is None:
            print(f'Loading player stats for {self.season} week {self.week}...')
            stats = self._load(
                nfl.load_player_stats,
                'player stats',
                seasons=self.season,
                summary_level='week',
            )
            self._player_stats = stats.filter(pl.col('week') == self.week)
        return self._player_stats

    @property
    def team_stats(self) -> pl.DataFrame:
        """Lazy load team stats."""
        if self._team_stats is None:
            print(f'Loading team stats for {self.season} week {self.week}...')
            stats = self._load(
                nfl.load_team_stats,
                'team stats',
                seasons=self.season,
                summary_level='week',
            )
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
            pbp = self._load(nfl.load_pbp, 'play-by-play', seasons=self.season)
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
            return cast(dict, matches.row(0, named=True))

        matches = frame.filter(
            pl.col('player_display_name').str.to_lowercase().str.contains(clean_name.lower())
        )
        if matches.height > 0:
            if require_unique and matches.height > 1:
                return None
            return cast(dict, matches.row(0, named=True))

        # Last-name-only matching is a big leap - it's here for spelling and
        # nickname drift on a known team ("Gabe Davis" vs "Gabriel Davis"), so
        # it stays out of the broad cross-team scopes: with only a game or two
        # of stats published, "the only Smith in the league this week" is
        # routinely a completely different player. It also compares surname
        # tokens rather than substrings, so Rice doesn't match Price.
        name_parts = clean_name.split()
        if len(name_parts) >= 2 and not require_unique:
            first_name = name_parts[0].lower()
            last_name = name_parts[-1].lower()
            matches = frame.filter(
                pl.col('player_display_name')
                .str.to_lowercase()
                .str.replace(r'\s+(sr\.?|jr\.?|ii|iii|iv|v)$', '')
                .str.split(' ')
                .list.last()
                == last_name
            )
            if matches.height == 1:
                candidate = cast(dict, matches.row(0, named=True))
                # Same last name isn't enough on its own - two different
                # players can share one on the same team (Josh Allen and Kyle
                # Allen, both BUF QBs). Require the first names to agree on at
                # least a short shared prefix too, which still lets spelling
                # drift through ("Gabe" vs "Gabriel", "Marvin" vs "Marvin H.")
                # while rejecting unrelated first names ("Kyle" vs "Josh").
                candidate_first = candidate['player_display_name'].split()[0].lower()
                prefix_len = min(3, len(first_name), len(candidate_first))
                if first_name[:prefix_len] == candidate_first[:prefix_len]:
                    return candidate

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
        if not self.stats_available:
            return None

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
        if not self.stats_available:
            return None

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
        if not self.stats_available:
            return {'pick_sixes': 0, 'fumble_sixes': 0}

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
        if not self.stats_available:
            return 0

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
        if not self.stats_available:
            return 0

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
        if not self.stats_available:
            return {'aggregated': 0, 'pbp': 0, 'value': 0, 'discrepancy': False}

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
