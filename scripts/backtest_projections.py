#!/usr/bin/env python3
"""Walk-forward backtest and tuning utility for QPFL projections."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from itertools import product
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import qpfl.projections as projection_module  # noqa: E402
from qpfl.models import FantasyTeam, PlayerScore  # noqa: E402
from qpfl.projections import (  # noqa: E402
    calculate_week_projections,
    load_projection_schedule_rows,
    player_projection_key,
)


@dataclass(frozen=True)
class ProjectionSettings:
    prior_games_weight: int = 2
    player_position_weight: int = 8
    trim_fraction: float = 0.1
    minimum_trim_samples: int = 10
    opponent_cap: float = 0.2
    opponent_full_weight_samples: int = 32
    exclude_legacy_bench_zeroes: bool = True


@dataclass
class ErrorMetrics:
    count: int = 0
    absolute_error: float = 0.0
    squared_error: float = 0.0
    signed_error: float = 0.0

    def add(self, projected: float, actual: float) -> None:
        error = projected - actual
        self.count += 1
        self.absolute_error += abs(error)
        self.squared_error += error**2
        self.signed_error += error

    def summary(self) -> dict[str, float | int | None]:
        if not self.count:
            return {'count': 0, 'mae': None, 'rmse': None, 'bias': None}
        return {
            'count': self.count,
            'mae': round(self.absolute_error / self.count, 3),
            'rmse': round(math.sqrt(self.squared_error / self.count), 3),
            'bias': round(self.signed_error / self.count, 3),
        }


@dataclass
class BacktestMetrics:
    players: ErrorMetrics = field(default_factory=ErrorMetrics)
    teams: ErrorMetrics = field(default_factory=ErrorMetrics)
    positions: dict[str, ErrorMetrics] = field(default_factory=lambda: defaultdict(ErrorMetrics))
    matchup_count: int = 0
    correct_winners: int = 0
    brier_total: float = 0.0

    def summary(self) -> dict[str, Any]:
        return {
            'players': self.players.summary(),
            'teams': self.teams.summary(),
            'positions': {
                position: metrics.summary() for position, metrics in sorted(self.positions.items())
            },
            'matchups': {
                'count': self.matchup_count,
                'winner_accuracy': round(self.correct_winners / self.matchup_count, 3)
                if self.matchup_count
                else None,
                'brier_score': round(self.brier_total / self.matchup_count, 3)
                if self.matchup_count
                else None,
            },
        }


@contextmanager
def use_projection_settings(settings: ProjectionSettings):
    values = {
        'PRIOR_GAMES_WEIGHT': settings.prior_games_weight,
        'PLAYER_POSITION_WEIGHT': settings.player_position_weight,
        'OUTLIER_TRIM_FRACTION': settings.trim_fraction,
        'MIN_OUTLIER_SAMPLES': settings.minimum_trim_samples,
        'MIN_OPPONENT_MULTIPLIER': 1.0 - settings.opponent_cap,
        'MAX_OPPONENT_MULTIPLIER': 1.0 + settings.opponent_cap,
        'OPPONENT_FULL_WEIGHT_SAMPLES': settings.opponent_full_weight_samples,
        'EXCLUDE_LEGACY_BENCH_ZEROES': settings.exclude_legacy_bench_zeroes,
    }
    originals = {name: getattr(projection_module, name) for name in values}
    try:
        for name, value in values.items():
            setattr(projection_module, name, value)
        yield
    finally:
        for name, value in originals.items():
            setattr(projection_module, name, value)


def _week_inputs(
    week_data: dict[str, Any],
) -> tuple[
    list[FantasyTeam],
    dict[str, tuple[float, dict[str, list[tuple[PlayerScore, bool]]]]],
    list[dict[str, str]],
    dict[tuple[str, str, str], tuple[float, str]],
    dict[str, float],
]:
    teams: list[FantasyTeam] = []
    results: dict[str, tuple[float, dict[str, list[tuple[PlayerScore, bool]]]]] = {}
    actual_players: dict[tuple[str, str, str], tuple[float, str]] = {}
    actual_teams: dict[str, float] = {}

    for team_data in week_data.get('teams', []):
        abbrev = team_data.get('abbrev')
        if not isinstance(abbrev, str):
            continue
        name = str(team_data.get('name') or abbrev)
        players: dict[str, list[tuple[str, str, bool]]] = defaultdict(list)
        scores: dict[str, list[tuple[PlayerScore, bool]]] = defaultdict(list)
        starter_total = 0.0
        for player in team_data.get('roster', []):
            player_name = player.get('name')
            position = player.get('position')
            nfl_team = player.get('nfl_team')
            score = player.get('score')
            if (
                not isinstance(player_name, str)
                or not isinstance(position, str)
                or not isinstance(nfl_team, str)
                or not isinstance(score, (int, float))
            ):
                continue
            is_starter = player.get('starter') is True
            players[position].append((player_name, nfl_team, is_starter))
            player_score = PlayerScore(
                name=player_name,
                position=position,
                team=nfl_team,
                total_points=float(score),
                found_in_stats=player.get('found') is not False,
            )
            scores[position].append((player_score, is_starter))
            if is_starter:
                starter_total += float(score)
                actual_players[player_projection_key(abbrev, player_name, position)] = (
                    float(score),
                    position,
                )

        team = FantasyTeam(
            name=name,
            owner=str(team_data.get('owner') or ''),
            abbreviation=abbrev,
            column_index=0,
            players=dict(players),
        )
        teams.append(team)
        results[name] = (starter_total, dict(scores))
        actual_teams[abbrev] = starter_total

    matchups = []
    for matchup in week_data.get('matchups', []):
        team1 = matchup.get('team1', {})
        team2 = matchup.get('team2', {})
        team1_abbrev = team1.get('abbrev') if isinstance(team1, dict) else team1
        team2_abbrev = team2.get('abbrev') if isinstance(team2, dict) else team2
        if isinstance(team1_abbrev, str) and isinstance(team2_abbrev, str):
            matchups.append({'team1': team1_abbrev, 'team2': team2_abbrev})

    return teams, results, matchups, actual_players, actual_teams


def _pregame_schedule(rows: list[dict[str, Any]], season: int, week: int) -> list[dict[str, Any]]:
    return [
        {**row, 'result': None} if row.get('season') == season and row.get('week') == week else row
        for row in rows
    ]


def run_backtest(
    season: int,
    weeks: list[int],
    settings: ProjectionSettings,
    history_root: Path,
    schedule_rows: list[dict[str, Any]],
) -> BacktestMetrics:
    metrics = BacktestMetrics()
    with use_projection_settings(settings):
        for week in weeks:
            week_path = history_root / str(season) / 'weeks' / f'week_{week}.json'
            if not week_path.exists():
                continue
            week_data = json.loads(week_path.read_text(encoding='utf-8'))
            teams, results, matchups, actual_players, actual_teams = _week_inputs(week_data)
            projections = calculate_week_projections(
                teams,
                results,
                matchups,
                season,
                week,
                history_root,
                _pregame_schedule(schedule_rows, season, week),
            )

            for key, (actual, position) in actual_players.items():
                projection = projections.players.get(key)
                if not projection:
                    continue
                metrics.players.add(projection.projected_points, actual)
                metrics.positions[position].add(projection.projected_points, actual)

            for abbrev, actual in actual_teams.items():
                projection = projections.teams.get(abbrev)
                if not projection or projection.projected_total is None:
                    continue
                metrics.teams.add(projection.projected_total, actual)

            for matchup in matchups:
                team1 = matchup['team1']
                team2 = matchup['team2']
                projection1 = projections.teams.get(team1)
                projection2 = projections.teams.get(team2)
                actual1 = actual_teams.get(team1)
                actual2 = actual_teams.get(team2)
                if (
                    not projection1
                    or not projection2
                    or projection1.projected_total is None
                    or projection2.projected_total is None
                    or projection1.win_probability is None
                    or actual1 is None
                    or actual2 is None
                    or actual1 == actual2
                ):
                    continue
                metrics.matchup_count += 1
                projected_team1_win = projection1.projected_total > projection2.projected_total
                actual_team1_win = actual1 > actual2
                metrics.correct_winners += projected_team1_win == actual_team1_win
                outcome = 1.0 if actual_team1_win else 0.0
                metrics.brier_total += (projection1.win_probability - outcome) ** 2

    return metrics


def _team_mae(metrics: BacktestMetrics) -> float:
    if not metrics.teams.count:
        return math.inf
    return metrics.teams.absolute_error / metrics.teams.count


def tune_settings(
    season: int,
    history_root: Path,
    schedule_rows: list[dict[str, Any]],
) -> tuple[ProjectionSettings, BacktestMetrics]:
    candidates = (
        ProjectionSettings(
            prior_games_weight=prior_weight,
            player_position_weight=player_position_weight,
            opponent_cap=opponent_cap,
            opponent_full_weight_samples=opponent_samples,
        )
        for prior_weight, player_position_weight, opponent_cap, opponent_samples in product(
            (2, 4, 6, 8),
            (0, 2, 4, 6, 8),
            (0.0, 0.1, 0.2),
            (16, 32),
        )
    )
    best_settings: ProjectionSettings | None = None
    best_metrics: BacktestMetrics | None = None
    for settings in candidates:
        metrics = run_backtest(
            season,
            list(range(1, 18)),
            settings,
            history_root,
            schedule_rows,
        )
        if best_metrics is None or _team_mae(metrics) < _team_mae(best_metrics):
            best_settings = settings
            best_metrics = metrics
    if best_settings is None or best_metrics is None:
        raise RuntimeError('No projection settings could be evaluated')
    return best_settings, best_metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', type=int, default=2025, help='Season to evaluate')
    parser.add_argument(
        '--tune',
        action='store_true',
        help='Tune on the preceding season before evaluating the requested season',
    )
    args = parser.parse_args()

    history_root = PROJECT_ROOT / 'web' / 'data' / 'seasons'
    tuning_season = args.season - 1
    evaluation_weeks = list(range(1, 18))
    schedule_rows = load_projection_schedule_rows([args.season - 2, tuning_season, args.season])
    baseline = ProjectionSettings(
        prior_games_weight=4,
        player_position_weight=0,
        trim_fraction=0,
        minimum_trim_samples=10,
        opponent_full_weight_samples=1,
        exclude_legacy_bench_zeroes=False,
    )
    current = ProjectionSettings()
    report: dict[str, Any] = {
        'evaluation_season': args.season,
        'evaluation_weeks': [1, 17],
        'original_model': {
            'settings': asdict(baseline),
            'evaluation': run_backtest(
                args.season,
                evaluation_weeks,
                baseline,
                history_root,
                schedule_rows,
            ).summary(),
        },
        'current_model': {
            'settings': asdict(current),
            'evaluation': run_backtest(
                args.season,
                evaluation_weeks,
                current,
                history_root,
                schedule_rows,
            ).summary(),
        },
    }

    if args.tune:
        tuned, tuning_metrics = tune_settings(tuning_season, history_root, schedule_rows)
        report['tuned_model'] = {
            'settings': asdict(tuned),
            'tuning_season': tuning_season,
            'tuning': tuning_metrics.summary(),
            'evaluation': run_backtest(
                args.season,
                evaluation_weeks,
                tuned,
                history_root,
                schedule_rows,
            ).summary(),
        }

    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
