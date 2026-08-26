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

from .constants import STARTER_SLOTS, TEAM_ABBREV_NORMALIZE
from .models import FantasyTeam, PlayerScore

PRIOR_GAMES_WEIGHT = 4
MIN_OPPONENT_MULTIPLIER = 0.8
MAX_OPPONENT_MULTIPLIER = 1.2

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


@dataclass(frozen=True)
class PlayerProjection:
    projected_points: float
    standard_deviation: float
    sample_size: int
    opponent_multiplier: float
    game: GameContext
    on_bye: bool = False


@dataclass
class TeamProjection:
    ready: bool
    projected_total: float | None
    variance: float
    starters_remaining: int
    win_probability: float | None = None


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
        lookup[(season, week, home)] = GameContext(away, kickoff, final, True)
        lookup[(season, week, away)] = GameContext(home, kickoff, final, False)
    return lookup


def _load_history(
    history_root: Path,
    season: int,
    target_week: int,
    schedule_lookup: Mapping[tuple[int, int, str], GameContext],
    schedule_weeks: set[tuple[int, int]],
) -> list[_Observation]:
    observations: list[_Observation] = []
    for history_season in (season - 1, season):
        weeks_dir = history_root / str(history_season) / 'weeks'
        if not weeks_dir.is_dir():
            continue
        for path in sorted(weeks_dir.glob('week_*.json')):
            try:
                week_data = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError):
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
                        )
                    )
    return observations


def _mean(values: list[float], default: float = 0.0) -> float:
    return fmean(values) if values else default


def _standard_deviation(values: list[float], fallback: list[float]) -> float:
    source = values if len(values) >= 2 else fallback
    return stdev(source) if len(source) >= 2 else 0.0


def _blended_mean(current: list[float], prior_mean: float) -> float:
    return (sum(current) + PRIOR_GAMES_WEIGHT * prior_mean) / (len(current) + PRIOR_GAMES_WEIGHT)


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
) -> WeekProjections:
    history_root = Path(history_root)
    schedule_rows = list(schedule_rows)
    schedule_lookup = build_schedule_lookup(schedule_rows)
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
    for observation in observations:
        player_values[(observation.season, observation.player_key)].append(observation.score)
        position_values[(observation.season, observation.position)].append(observation.score)
        if observation.opponent:
            defense_values[(observation.season, observation.opponent, observation.position)].append(
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
        variance = 0.0
        starters_remaining = 0

        for position, position_scores in scores.items():
            prior_position = position_values[(season - 1, position)]
            current_position = position_values[(season, position)]
            prior_position_mean = _mean(prior_position, _mean(current_position))
            league_mean = _blended_mean(current_position, prior_position_mean)

            for player_score, is_starter in position_scores:
                identity = (normalize_player_name(player_score.name), position)
                prior_player = player_values[(season - 1, identity)]
                current_player = player_values[(season, identity)]
                prior_mean = _mean(prior_player, prior_position_mean)
                baseline = _blended_mean(current_player, prior_mean)

                nfl_team = normalize_team(player_score.team)
                game = schedule_lookup.get((season, week, nfl_team))
                on_bye = game is None
                game = game or GameContext(None, None, False)

                prior_defense = defense_values[(season - 1, game.opponent or '', position)]
                current_defense = defense_values[(season, game.opponent or '', position)]
                prior_allowed = _mean(prior_defense, prior_position_mean)
                allowed = _blended_mean(current_defense, prior_allowed)
                if on_bye or league_mean <= 0:
                    multiplier = 1.0
                else:
                    multiplier = min(
                        MAX_OPPONENT_MULTIPLIER,
                        max(MIN_OPPONENT_MULTIPLIER, allowed / league_mean),
                    )

                projected_points = 0.0 if on_bye else baseline + abs(baseline) * (multiplier - 1)
                history_values = prior_player + current_player
                position_history = prior_position + current_position
                player_stdev = _standard_deviation(history_values, position_history)
                if not on_bye:
                    player_stdev *= multiplier

                projected_player = PlayerProjection(
                    projected_points=round(projected_points, 1),
                    standard_deviation=player_stdev,
                    sample_size=len(history_values),
                    opponent_multiplier=multiplier,
                    game=game,
                    on_bye=on_bye,
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
                if game.final:
                    effective_total += player_score.total_points
                else:
                    effective_total += projected_points
                    variance += player_stdev**2
                    starters_remaining += 1

        ready = all(
            starter_counts.get(position, 0) == required
            for position, required in STARTER_SLOTS.items()
        )
        if ready:
            team_only_adjustment = total_score - starter_scores_total
            effective_total += team_only_adjustment
        team_projections[team.abbreviation] = TeamProjection(
            ready=ready,
            projected_total=round(effective_total, 1) if ready else None,
            variance=variance if ready else 0.0,
            starters_remaining=starters_remaining if ready else sum(STARTER_SLOTS.values()),
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
