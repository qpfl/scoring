"""Lightweight matchup projections derived from scored QPFL weeks."""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean, stdev
from typing import Any
from zoneinfo import ZoneInfo

from .availability import is_listed_head_coach
from .constants import STARTER_SLOTS, TEAM_ABBREV_NORMALIZE
from .injuries import injury_identity_key
from .models import FantasyTeam, PlayerScore

PRIOR_GAMES_WEIGHT = 2
MIN_OPPONENT_MULTIPLIER = 0.8
MAX_OPPONENT_MULTIPLIER = 1.2
OUTLIER_TRIM_FRACTION = 0.1
MIN_OUTLIER_SAMPLES = 10
OPPONENT_FULL_WEIGHT_SAMPLES = 32
EXCLUDE_LEGACY_BENCH_ZEROES = True
PLAYER_POSITION_WEIGHT = 8
# A player whose NFL team cannot be resolved against the schedule is currently
# indistinguishable from one whose team has no game, so he projects 0. Setting
# this False fails open instead: unknown team means no opponent adjustment, not
# a guaranteed zero.
TREAT_UNKNOWN_TEAM_AS_BYE = False
# The position average is the anchor every thin-history player is shrunk toward.
# Averaging bench appearances into it pulls that anchor below the starters the
# projection is actually predicting.
POSITION_MEAN_STARTERS_ONLY = True
# Per-position overrides for the tunables above; a position absent from a map
# uses the global default. Selected on 2021-2024 and confirmed once on 2025 --
# see docs/PROJECTION_BACKTEST.md.
PRIOR_GAMES_WEIGHT_BY_POSITION: dict[str, int] = {
    'D/ST': 8,
    'HC': 8,
    'K': 8,
    'OL': 8,
    'QB': 8,
    'RB': 4,
    'TE': 8,
    'WR': 8,
}
PLAYER_POSITION_WEIGHT_BY_POSITION: dict[str, int] = {
    'D/ST': 16,
    'HC': 6,
    'K': 16,
    'OL': 0,
    'QB': 16,
    'RB': 12,
    'TE': 12,
    'WR': 12,
}
# Quantile used as the central estimate, per position. A position absent from
# this map uses the arithmetic mean, which is the historical behaviour.
# Empty: absolute error is minimised by the median, but trimming and shrinkage
# already pull toward it, and a quantile of a thin per-player sample is noisier
# than its mean. The two positions that gained on the tuning seasons (TE, WR)
# gave it back on the holdout and dragged team totals low, because a sum of
# medians is not the median of the sum.
CENTRAL_QUANTILE_BY_POSITION: dict[str, float] = {}
OUTLIER_TRIM_FRACTION_BY_POSITION: dict[str, float] = {
    'D/ST': 0.1,
    'HC': 0.2,
    'K': 0.0,
    'OL': 0.0,
    'QB': 0.05,
    'RB': 0.15,
    'TE': 0.2,
    'WR': 0.2,
}


USE_MARKET_LINES_FOR_HEAD_COACH = True
USE_MARKET_LINES_FOR_DEFENSE = False
# Spread of plausible final margins around the market spread, in points. Tuning
# drives this toward zero, where the projection becomes the coach score for the
# spread itself -- the median outcome, which is what minimises absolute error
# for a monotone step function. A small non-zero value keeps the projection from
# jumping a whole point on a half-point line move.
HEAD_COACH_MARGIN_SPREAD = 2.0
# League-average implied team total, the neutral point for the defence scaling.
LEAGUE_MEAN_IMPLIED_TOTAL = 22.5
IMPLIED_TOTAL_SENSITIVITY = 0.5
MIN_IMPLIED_TOTAL_MULTIPLIER = 0.75
MAX_IMPLIED_TOTAL_MULTIPLIER = 1.25
# Home-field adjustment, estimated per position from the same history.
# Off: the raw home/away gap in the data is real (QB +1.65 points, most others
# +0.3 to +0.7) but applying it makes the model slightly worse, because home
# teams are disproportionately favourites and the opponent multiplier and market
# lines already capture that. Kept behind a flag so the result stays measurable.
HOME_AWAY_ADJUSTMENT = False
MIN_HOME_AWAY_MULTIPLIER = 0.9
MAX_HOME_AWAY_MULTIPLIER = 1.1
HOME_AWAY_FULL_WEIGHT_SAMPLES = 32
# How many seasons of scored weeks feed a projection, counting the current one.
HISTORY_SEASONS = 2
# Per-position window override. Empty: widening it for D/ST and QB looked worth
# 3.5% and 0.7% on the tuning seasons and returned nothing on the holdout.
HISTORY_SEASONS_BY_POSITION: dict[str, int] = {}
# Per-position override of the opponent-strength cap, as a fraction either side
# of neutral. Absent means the global MAX_OPPONENT_MULTIPLIER applies. Empty for
# the same reason: no override survived the holdout.
OPPONENT_CAP_BY_POSITION: dict[str, float] = {}
# How far to pull a finished projection back toward the position average, for
# positions where week-to-week scoring is close to noise. 1.0 discards the
# player-specific estimate entirely and projects every starter at that position
# at the position average, which is what D/ST and OL get: both lose to that
# average as a predictor, so the model has nothing to add and says so. K and WR
# were tested here too and were worse on the holdout.
POSITION_AVERAGE_WEIGHT_BY_POSITION: dict[str, float] = {
    'D/ST': 1.0,
    'OL': 1.0,
}
# Which position average the weight above pulls toward: the model's own blended
# estimate (trimmed, starters-only, prior season folded in) or the plain running
# mean of every starter observation, which is the naive predictor the backtest
# measures against. Plain is the honest reading of "just use the average".
POSITION_AVERAGE_USES_PLAIN_MEAN = True
# Sum untrimmed means into team totals instead of the per-player projections.
# The two want different estimators: minimising a player's absolute error pulls
# his number below his mean, and adding nine of those under-projects the team.
UNBIASED_TEAM_TOTALS = True


def prior_games_weight(position: str | None = None) -> int:
    return PRIOR_GAMES_WEIGHT_BY_POSITION.get(position or '', PRIOR_GAMES_WEIGHT)


def player_position_weight(position: str | None = None) -> int:
    return PLAYER_POSITION_WEIGHT_BY_POSITION.get(position or '', PLAYER_POSITION_WEIGHT)


def trim_fraction(position: str | None = None) -> float:
    return OUTLIER_TRIM_FRACTION_BY_POSITION.get(position or '', OUTLIER_TRIM_FRACTION)


def history_seasons(position: str | None = None) -> int:
    return max(1, HISTORY_SEASONS_BY_POSITION.get(position or '', HISTORY_SEASONS))


def opponent_cap(position: str | None = None) -> float:
    return OPPONENT_CAP_BY_POSITION.get(position or '', MAX_OPPONENT_MULTIPLIER - 1.0)


def position_average_weight(position: str | None = None) -> float:
    return POSITION_AVERAGE_WEIGHT_BY_POSITION.get(position or '', 0.0)


_TEAM_ALIASES = {
    **TEAM_ABBREV_NORMALIZE,
    'WSH': 'WAS',
}
_SUFFIX_RE = re.compile(r'\s+(sr\.?|jr\.?|ii|iii|iv|v)$', re.IGNORECASE)


@dataclass(frozen=True)
class GameContext:
    opponent: str | None
    kickoff: str | None
    final: bool
    is_home: bool | None = None
    coach: str | None = None
    # Pregame market lines, from this team's perspective: the margin it is
    # favoured by, and the points its opponent is expected to score. Both are
    # None for games with no posted line, and every consumer must fail open.
    spread: float | None = None
    opponent_implied_total: float | None = None


@dataclass(frozen=True)
class PlayerProjection:
    projected_points: float
    standard_deviation: float
    sample_size: int
    opponent_multiplier: float
    game: GameContext
    on_bye: bool = False
    unavailable_reason: str | None = None


@dataclass
class TeamProjection:
    ready: bool
    # The live projection: real points for starters whose games have finished,
    # projections for everyone still to play. This is what win_probability is
    # built on, and it converges to the final score as the week resolves.
    projected_total: float | None
    variance: float
    starters_remaining: int
    win_probability: float | None = None
    # The projection with no results folded in - every starter projected, as if
    # the week had not started. Kept alongside the live number so a team can be
    # compared against what was expected of it rather than only against its
    # opponent.
    pregame_total: float | None = None


@dataclass
class WeekProjections:
    players: dict[tuple[str, str, str], PlayerProjection]
    teams: dict[str, TeamProjection]


@dataclass(frozen=True)
class _Observation:
    season: int
    week: int
    player_key: tuple[str, str]
    position: str
    nfl_team: str
    opponent: str | None
    score: float
    starter: bool = False
    is_home: bool | None = None


def normalize_team(team: str | None) -> str:
    value = str(team or '').strip().upper()
    return _TEAM_ALIASES.get(value, value)


def normalize_player_name(name: str) -> str:
    value = ' '.join(str(name).strip().casefold().split())
    return _SUFFIX_RE.sub('', value)


def player_projection_key(team_abbrev: str, name: str, position: str) -> tuple[str, str, str]:
    return team_abbrev, normalize_player_name(name), position


def compact_schedule_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    keys = (
        'season',
        'week',
        'game_type',
        'home_team',
        'away_team',
        'gameday',
        'gametime',
        'result',
        'home_coach',
        'away_coach',
        'spread_line',
        'total_line',
    )
    return [{key: row.get(key) for key in keys} for row in rows]


def load_projection_schedule_rows(seasons: list[int]) -> list[dict[str, Any]]:
    import nflreadpy as nfl

    return compact_schedule_rows(nfl.load_schedules(seasons=seasons).iter_rows(named=True))


def _kickoff_iso(row: Mapping[str, Any]) -> str | None:
    gameday = row.get('gameday')
    gametime = row.get('gametime')
    if not gameday or not gametime:
        return None
    try:
        eastern = ZoneInfo('America/New_York')
        local = datetime.strptime(f'{gameday} {gametime}', '%Y-%m-%d %H:%M').replace(tzinfo=eastern)
    except (TypeError, ValueError):
        return None
    return local.astimezone(timezone.utc).isoformat()


def _market_lines(
    row: Mapping[str, Any],
) -> tuple[float | None, float | None, float | None, float | None]:
    """Home spread, home's opponent total, away spread, away's opponent total.

    ``spread_line`` is the home team's margin. Splitting it against
    ``total_line`` gives each side's implied score. Missing or malformed lines
    yield ``None`` so the projection falls back to history.
    """
    spread = row.get('spread_line')
    total = row.get('total_line')
    if not isinstance(spread, (int, float)) or not math.isfinite(spread):
        return None, None, None, None
    home_spread = float(spread)
    if not isinstance(total, (int, float)) or not math.isfinite(total):
        return home_spread, None, -home_spread, None
    home_points = (float(total) + home_spread) / 2
    away_points = (float(total) - home_spread) / 2
    return home_spread, away_points, -home_spread, home_points


def build_schedule_lookup(
    rows: Iterable[Mapping[str, Any]],
) -> dict[tuple[int, int, str], GameContext]:
    lookup: dict[tuple[int, int, str], GameContext] = {}
    for row in rows:
        if row.get('game_type') not in (None, 'REG'):
            continue
        season = row.get('season')
        week = row.get('week')
        if not isinstance(season, int) or not isinstance(week, int):
            continue
        home = normalize_team(row.get('home_team'))
        away = normalize_team(row.get('away_team'))
        if not home or not away:
            continue
        kickoff = _kickoff_iso(row)
        final = row.get('result') not in (None, '')
        # Snapshots written before coaches were compacted in have no coach
        # columns; leaving them None disables the head-coach check for a replay.
        home_coach = row.get('home_coach') or None
        away_coach = row.get('away_coach') or None
        home_spread, home_allowed, away_spread, away_allowed = _market_lines(row)
        lookup[(season, week, home)] = GameContext(
            away, kickoff, final, True, home_coach, home_spread, home_allowed
        )
        lookup[(season, week, away)] = GameContext(
            home, kickoff, final, False, away_coach, away_spread, away_allowed
        )
    return lookup


_WEEK_FILE_CACHE: dict[tuple[str, int, int], dict[str, Any] | None] = {}


def _read_week_file(path: Path) -> dict[str, Any] | None:
    """Parse a scored week, memoised on the file's size and mtime.

    Every projected week re-reads the whole history, so without this the cost
    is quadratic in the number of weeks replayed. Keying on the stat means a
    rewritten week file is picked up rather than served stale.
    """
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if key in _WEEK_FILE_CACHE:
        return _WEEK_FILE_CACHE[key]
    try:
        parsed = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        parsed = None
    if not isinstance(parsed, dict):
        parsed = None
    _WEEK_FILE_CACHE[key] = parsed
    return parsed


def _load_history(
    history_root: Path,
    season: int,
    target_week: int,
    schedule_lookup: Mapping[tuple[int, int, str], GameContext],
    schedule_weeks: set[tuple[int, int]],
) -> list[_Observation]:
    observations: list[_Observation] = []
    # Load the widest window any position asks for; each position then keeps
    # only as much of it as its own setting allows.
    widest = max([HISTORY_SEASONS, *HISTORY_SEASONS_BY_POSITION.values()])
    oldest = season - max(1, widest - 1)
    for history_season in range(oldest, season + 1):
        weeks_dir = history_root / str(history_season) / 'weeks'
        if not weeks_dir.is_dir():
            continue
        for path in sorted(weeks_dir.glob('week_*.json')):
            week_data = _read_week_file(path)
            if week_data is None:
                continue
            week = week_data.get('week')
            if not isinstance(week, int):
                continue
            if history_season == season and week >= target_week:
                continue
            for team in week_data.get('teams', []) or []:
                for player in team.get('roster', []) or []:
                    score = player.get('score')
                    position = player.get('position')
                    nfl_team = normalize_team(player.get('nfl_team'))
                    if not isinstance(score, (int, float)) or not math.isfinite(score):
                        continue
                    if (
                        EXCLUDE_LEGACY_BENCH_ZEROES
                        and score == 0
                        and 'found' not in player
                        and player.get('starter') is False
                    ):
                        continue
                    if not position or not nfl_team:
                        continue
                    if 'found' in player and player.get('found') is False:
                        continue
                    game = schedule_lookup.get((history_season, week, nfl_team))
                    if (history_season, week) in schedule_weeks and game is None:
                        continue
                    name = player.get('name')
                    if not name:
                        continue
                    observations.append(
                        _Observation(
                            season=history_season,
                            week=week,
                            player_key=(normalize_player_name(name), position),
                            position=position,
                            nfl_team=nfl_team,
                            opponent=game.opponent if game else None,
                            score=float(score),
                            starter=player.get('starter') is True,
                            is_home=game.is_home if game else None,
                        )
                    )
    return observations


def _trim_extremes(values: list[float], position: str | None = None) -> list[float]:
    if len(values) < MIN_OUTLIER_SAMPLES:
        return list(values)
    trim_count = int(len(values) * trim_fraction(position))
    if trim_count == 0:
        return list(values)
    ordered = sorted(values)
    return ordered[trim_count:-trim_count]


def _central(values: list[float], position: str | None = None) -> float:
    """Central tendency of a sample: the mean, or a quantile where tuned.

    Absolute error is minimised by the median rather than the mean, and QPFL
    scoring is right-skewed, so some positions do better with a quantile. The
    estimator is per-position because a few positions prefer the mean.
    """
    quantile = CENTRAL_QUANTILE_BY_POSITION.get(position or '')
    if quantile is None:
        return fmean(values)
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = quantile * (len(ordered) - 1)
    low = int(math.floor(index))
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def _mean(values: list[float], default: float = 0.0, position: str | None = None) -> float:
    trimmed = _trim_extremes(values, position)
    return _central(trimmed, position) if trimmed else default


def _standard_deviation(
    values: list[float], fallback: list[float], position: str | None = None
) -> float:
    source = values if len(values) >= 2 else fallback
    source = _trim_extremes(source, position)
    return stdev(source) if len(source) >= 2 else 0.0


def _blended_mean(current: list[float], prior_mean: float, position: str | None = None) -> float:
    trimmed = _trim_extremes(current, position)
    weight = prior_games_weight(position)
    denominator = len(trimmed) + weight
    if denominator <= 0:
        # No current-season games and no prior weight: the prior is all we have.
        return prior_mean
    if not trimmed:
        return prior_mean
    return (len(trimmed) * _central(trimmed, position) + weight * prior_mean) / denominator


def _opponent_multiplier(
    allowed: float,
    league_mean: float,
    prior_samples: list[float],
    current_samples: list[float],
    position: str | None = None,
) -> float:
    if league_mean <= 0:
        return 1.0
    cap = opponent_cap(position)
    bounded = min(1.0 + cap, max(1.0 - cap, allowed / league_mean))
    retained_samples = len(_trim_extremes(prior_samples, position)) + len(
        _trim_extremes(current_samples, position)
    )
    reliability = min(1.0, retained_samples / OPPONENT_FULL_WEIGHT_SAMPLES)
    return 1.0 + (bounded - 1.0) * reliability


def _unbiased_baseline(
    prior_player: list[float],
    current_player: list[float],
    prior_position_mean: float,
    position: str | None = None,
) -> float:
    """Mean-based twin of the player baseline, for summing into a team total.

    A player projection is tuned to minimise absolute error, and trimming pulls
    it toward the median of a right-skewed distribution -- below the mean. That
    is the right point estimate for one player and the wrong one to add up:
    nine of them systematically under-project a team. Team totals therefore use
    the untrimmed mean, which is unbiased under addition.
    """
    position_weight = player_position_weight(position)
    prior_denominator = len(prior_player) + position_weight
    prior_mean = (
        (sum(prior_player) + position_weight * prior_position_mean) / prior_denominator
        if prior_denominator > 0
        else prior_position_mean
    )
    prior_weight = prior_games_weight(position)
    denominator = len(current_player) + prior_weight
    if denominator <= 0:
        return prior_mean
    return (sum(current_player) + prior_weight * prior_mean) / denominator


def _player_mean(values: list[float], position_mean: float, position: str | None = None) -> float:
    trimmed = _trim_extremes(values, position)
    if not trimmed:
        return position_mean
    weight = player_position_weight(position)
    return (len(trimmed) * _central(trimmed, position) + weight * position_mean) / (
        len(trimmed) + weight
    )


def _head_coach_points(margin: float) -> float:
    """Mirror of ``score_head_coach``: QPFL coach points for a final margin."""
    if margin > 0:
        return 2.0 if margin < 10 else (3.0 if margin <= 19 else 4.0)
    if margin < 0:
        deficit = -margin
        return -1.0 if deficit < 10 else (-2.0 if deficit <= 20 else -3.0)
    return 0.0


def _expected_head_coach_points(spread: float) -> float:
    """Expected coach score for a team favoured by ``spread``.

    Coach scoring is a step function of the final margin and nothing else, so
    the projection is that function averaged over a normal distribution of
    plausible margins centred on the market spread.
    """
    weight_total = 0.0
    points_total = 0.0
    for margin in range(-60, 61):
        weight = math.exp(-0.5 * ((margin - spread) / HEAD_COACH_MARGIN_SPREAD) ** 2)
        weight_total += weight
        points_total += weight * _head_coach_points(margin)
    if weight_total <= 0:
        return 0.0
    return points_total / weight_total


def _implied_total_multiplier(opponent_implied_total: float, league_mean_total: float) -> float:
    """Scale a defensive projection by how much its opponent is expected to score.

    A defence facing an offence the market expects to be shut down should
    project higher, and vice versa. Bounded like the opponent multiplier so a
    single extreme line cannot dominate.
    """
    if league_mean_total <= 0:
        return 1.0
    ratio = opponent_implied_total / league_mean_total
    scaled = 1.0 - (ratio - 1.0) * IMPLIED_TOTAL_SENSITIVITY
    return min(MAX_IMPLIED_TOTAL_MULTIPLIER, max(MIN_IMPLIED_TOTAL_MULTIPLIER, scaled))


def _home_away_multiplier(
    home_values: list[float],
    away_values: list[float],
    is_home: bool | None,
    position: str | None = None,
) -> float:
    """Scale for playing at home or on the road, shrunk by sample size.

    The split is estimated from the same history the projection is built on, and
    faded toward neutral when either side is thinly observed -- the same
    treatment the opponent adjustment gets.
    """
    if is_home is None or not HOME_AWAY_ADJUSTMENT:
        return 1.0
    home_mean = _central(home_values, position) if home_values else 0.0
    away_mean = _central(away_values, position) if away_values else 0.0
    overall = (
        (len(home_values) * home_mean + len(away_values) * away_mean)
        / (len(home_values) + len(away_values))
        if (home_values or away_values)
        else 0.0
    )
    if overall <= 0:
        return 1.0
    side_mean = home_mean if is_home else away_mean
    side_values = home_values if is_home else away_values
    bounded = min(
        MAX_HOME_AWAY_MULTIPLIER,
        max(MIN_HOME_AWAY_MULTIPLIER, side_mean / overall),
    )
    reliability = min(1.0, len(side_values) / HOME_AWAY_FULL_WEIGHT_SAMPLES)
    return 1.0 + (bounded - 1.0) * reliability


def _apply_market_lines(position: str, game: GameContext, projected: float) -> float:
    """Fold pregame betting lines into a projection, where they carry signal.

    Only head coaches and defences: their scores track the shape of the game,
    and the correlation with market lines is negligible for skill positions.
    Falls through untouched whenever the relevant line is missing.
    """
    if position == 'HC' and USE_MARKET_LINES_FOR_HEAD_COACH and game.spread is not None:
        return _expected_head_coach_points(game.spread)
    if (
        position == 'D/ST'
        and USE_MARKET_LINES_FOR_DEFENSE
        and game.opponent_implied_total is not None
    ):
        return projected * _implied_total_multiplier(
            game.opponent_implied_total, LEAGUE_MEAN_IMPLIED_TOTAL
        )
    return projected


def _finish_projection(
    value: float,
    position: str,
    game: GameContext,
    multiplier: float,
    on_bye: bool,
    league_mean: float,
    home_values: list[float],
    away_values: list[float],
    plain_position_mean: float | None = None,
) -> float:
    """Apply every game-context adjustment to a raw baseline."""
    if on_bye:
        return 0.0
    adjusted = value + abs(value) * (multiplier - 1)
    adjusted *= _home_away_multiplier(home_values, away_values, game.is_home, position)
    adjusted = _apply_market_lines(position, game, adjusted)
    average_weight = position_average_weight(position)
    if average_weight:
        anchor = (
            plain_position_mean
            if POSITION_AVERAGE_USES_PLAIN_MEAN and plain_position_mean is not None
            else league_mean
        )
        adjusted = (1 - average_weight) * adjusted + average_weight * anchor
    return adjusted


def _unavailable_reason(
    name: str,
    position: str,
    nfl_team: str,
    game: GameContext,
    availability: Mapping[str, str],
    coach_overrides: Mapping[str, str],
) -> str | None:
    """Why this player will not play, or None if he is expected to.

    Head coaches are judged against whoever is actually listed as coaching the
    team; everyone else against the injury and NFL roster feeds.
    """
    if position == 'HC':
        if is_listed_head_coach(name, game.coach, coach_overrides.get(nfl_team)):
            return None
        return 'not_head_coach'
    return availability.get(injury_identity_key(name, position))


def _normal_win_probability(mean_difference: float, variance: float) -> float:
    if variance <= 0:
        if mean_difference > 0:
            return 0.99
        if mean_difference < 0:
            return 0.01
        return 0.5
    z_score = mean_difference / math.sqrt(variance)
    return 0.5 * (1 + math.erf(z_score / math.sqrt(2)))


def _mid_bowl_carryover(
    history_root: Path, season: int, week: int, matchup: Mapping[str, Any]
) -> dict[str, float]:
    if week != 17 or matchup.get('bracket') != 'mid_bowl':
        return {}
    path = history_root / str(season) / 'weeks' / 'week_16.json'
    if not path.exists():
        return {}
    try:
        week_data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return {}
    team_codes = {matchup.get('team1'), matchup.get('team2')}
    return {
        team.get('abbrev'): float(team.get('total_score', 0))
        for team in week_data.get('teams', []) or []
        if team.get('abbrev') in team_codes
    }


def calculate_week_projections(
    teams: list[FantasyTeam],
    results: dict[str, tuple[float, dict[str, list[tuple[PlayerScore, bool]]]]],
    matchups: list[dict[str, Any]],
    season: int,
    week: int,
    history_root: str | Path,
    schedule_rows: Iterable[Mapping[str, Any]],
    availability: Mapping[str, str] | None = None,
    coach_overrides: Mapping[str, str] | None = None,
) -> WeekProjections:
    history_root = Path(history_root)
    schedule_rows = list(schedule_rows)
    availability = availability or {}
    # Accept either abbreviation for the teams nflverse spells differently
    # (LAR/LA, JAC/JAX, WSH/WAS).
    coach_overrides = {normalize_team(team): name for team, name in (coach_overrides or {}).items()}
    schedule_lookup = build_schedule_lookup(schedule_rows)
    scheduled_teams = {team for (row_season, _, team) in schedule_lookup if row_season == season}
    schedule_weeks: set[tuple[int, int]] = set()
    for row in schedule_rows:
        row_season = row.get('season')
        row_week = row.get('week')
        if isinstance(row_season, int) and isinstance(row_week, int):
            schedule_weeks.add((row_season, row_week))
    observations = _load_history(history_root, season, week, schedule_lookup, schedule_weeks)

    player_values: dict[tuple[int, tuple[str, str]], list[float]] = defaultdict(list)
    position_values: dict[tuple[int, str], list[float]] = defaultdict(list)
    defense_values: dict[tuple[int, str, str], list[float]] = defaultdict(list)
    home_values: dict[str, list[float]] = defaultdict(list)
    away_values: dict[str, list[float]] = defaultdict(list)
    for observation in observations:
        # Everything before the current season pools into one "prior" bucket:
        # the model has a current/prior split, not a per-season one, and the
        # data says older games are no less informative than recent ones.
        if observation.season < season - (history_seasons(observation.position) - 1):
            continue
        bucket = observation.season if observation.season == season else season - 1
        player_values[(bucket, observation.player_key)].append(observation.score)
        if observation.starter or not POSITION_MEAN_STARTERS_ONLY:
            position_values[(bucket, observation.position)].append(observation.score)
        if observation.starter and observation.is_home is not None:
            side = home_values if observation.is_home else away_values
            side[observation.position].append(observation.score)
        if observation.opponent:
            defense_values[(bucket, observation.opponent, observation.position)].append(
                observation.score
            )

    player_projections: dict[tuple[str, str, str], PlayerProjection] = {}
    team_projections: dict[str, TeamProjection] = {}

    for team in teams:
        result = results.get(team.name)
        if result is None:
            continue
        total_score, scores = result
        starter_counts: dict[str, int] = defaultdict(int)
        starter_scores_total = 0.0
        effective_total = 0.0
        pregame_total = 0.0
        variance = 0.0
        starters_remaining = 0

        for position, position_scores in scores.items():
            prior_position = position_values[(season - 1, position)]
            current_position = position_values[(season, position)]
            prior_position_mean = _mean(
                prior_position, _mean(current_position, position=position), position=position
            )
            league_mean = _blended_mean(current_position, prior_position_mean, position)
            # Untrimmed, unweighted mean of every starter observation at this
            # position - the naive "just predict the position average"
            # predictor, kept separately from the model's own blended estimate.
            plain_history = prior_position + current_position
            plain_position_mean = fmean(plain_history) if plain_history else league_mean

            for player_score, is_starter in position_scores:
                identity = (normalize_player_name(player_score.name), position)
                prior_player = player_values[(season - 1, identity)]
                current_player = player_values[(season, identity)]
                prior_mean = _player_mean(prior_player, prior_position_mean, position)
                baseline = _blended_mean(current_player, prior_mean, position)

                nfl_team = normalize_team(player_score.team)
                game = schedule_lookup.get((season, week, nfl_team))
                team_known = bool(nfl_team) and nfl_team in scheduled_teams
                on_bye = game is None and (team_known or TREAT_UNKNOWN_TEAM_AS_BYE)
                game = game or GameContext(None, None, False)

                prior_defense = defense_values[(season - 1, game.opponent or '', position)]
                current_defense = defense_values[(season, game.opponent or '', position)]
                prior_allowed = _mean(prior_defense, prior_position_mean, position=position)
                allowed = _blended_mean(current_defense, prior_allowed, position)
                if on_bye:
                    multiplier = 1.0
                else:
                    multiplier = _opponent_multiplier(
                        allowed,
                        league_mean,
                        prior_defense,
                        current_defense,
                        position,
                    )

                projected_points = _finish_projection(
                    baseline,
                    position,
                    game,
                    multiplier,
                    on_bye,
                    league_mean,
                    home_values[position],
                    away_values[position],
                    plain_position_mean,
                )
                # What this player is expected to score, as opposed to the
                # absolute-error-optimal guess. Only team totals use it.
                expected_points = (
                    _finish_projection(
                        _unbiased_baseline(
                            prior_player, current_player, prior_position_mean, position
                        ),
                        position,
                        game,
                        multiplier,
                        on_bye,
                        league_mean,
                        home_values[position],
                        away_values[position],
                        plain_position_mean,
                    )
                    if UNBIASED_TEAM_TOTALS
                    else projected_points
                )
                history_values = prior_player + current_player
                position_history = prior_position + current_position
                player_stdev = _standard_deviation(history_values, position_history, position)
                if not on_bye:
                    player_stdev *= multiplier

                unavailable_reason = _unavailable_reason(
                    player_score.name,
                    position,
                    nfl_team,
                    game,
                    availability,
                    coach_overrides,
                )
                if unavailable_reason:
                    projected_points = 0.0
                    expected_points = 0.0
                    player_stdev = 0.0

                projected_player = PlayerProjection(
                    projected_points=round(projected_points, 1),
                    standard_deviation=player_stdev,
                    sample_size=len(history_values),
                    opponent_multiplier=multiplier,
                    game=game,
                    on_bye=on_bye,
                    unavailable_reason=unavailable_reason,
                )
                player_projections[
                    player_projection_key(team.abbreviation, player_score.name, position)
                ] = projected_player

                if not is_starter:
                    continue
                starter_counts[position] += 1
                starter_scores_total += player_score.total_points
                if on_bye:
                    continue
                # The pregame line ignores results entirely, so every starter
                # contributes his projection to it no matter what his game has
                # done since.
                pregame_total += expected_points
                if game.final:
                    # A finished game beats any designation: if he played after
                    # all, his real points count.
                    effective_total += player_score.total_points
                elif unavailable_reason:
                    # Contributes a certain zero, so there is nothing left to
                    # resolve and nothing to add to the variance.
                    continue
                else:
                    effective_total += expected_points
                    variance += player_stdev**2
                    starters_remaining += 1

        ready = all(
            starter_counts.get(position, 0) == required
            for position, required in STARTER_SLOTS.items()
        )
        if ready:
            team_only_adjustment = total_score - starter_scores_total
            effective_total += team_only_adjustment
            pregame_total += team_only_adjustment
        team_projections[team.abbreviation] = TeamProjection(
            ready=ready,
            projected_total=round(effective_total, 1) if ready else None,
            variance=variance if ready else 0.0,
            starters_remaining=starters_remaining if ready else sum(STARTER_SLOTS.values()),
            pregame_total=round(pregame_total, 1) if ready else None,
        )

    for matchup in matchups:
        team1 = matchup.get('team1')
        team2 = matchup.get('team2')
        if not isinstance(team1, str) or not isinstance(team2, str):
            continue
        projection1 = team_projections.get(team1)
        projection2 = team_projections.get(team2)
        if not projection1 or not projection2:
            continue
        if not projection1.ready or not projection2.ready:
            for team_projection in (projection1, projection2):
                team_projection.ready = False
                team_projection.projected_total = None
                team_projection.pregame_total = None
                team_projection.variance = 0.0
                team_projection.win_probability = None
            continue
        carryover = _mid_bowl_carryover(history_root, season, week, matchup)
        mean1 = (projection1.projected_total or 0) + carryover.get(team1, 0)
        mean2 = (projection2.projected_total or 0) + carryover.get(team2, 0)
        all_resolved = projection1.starters_remaining == projection2.starters_remaining == 0
        if all_resolved:
            probability1 = 1.0 if mean1 > mean2 else 0.0 if mean1 < mean2 else 0.5
        else:
            probability1 = _normal_win_probability(
                mean1 - mean2, projection1.variance + projection2.variance
            )
            probability1 = min(0.99, max(0.01, probability1))
        projection1.win_probability = probability1
        projection2.win_probability = 1 - probability1

    return WeekProjections(players=player_projections, teams=team_projections)
