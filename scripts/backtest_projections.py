#!/usr/bin/env python3
"""Walk-forward backtest and tuning utility for QPFL projections."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from collections.abc import Mapping
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
    normalize_player_name,
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
    treat_unknown_team_as_bye: bool = False
    position_mean_starters_only: bool = True
    market_lines_for_head_coach: bool = True
    market_lines_for_defense: bool = False
    head_coach_margin_spread: float = 2.0
    implied_total_sensitivity: float = 0.5
    home_away_adjustment: bool = False
    unbiased_team_totals: bool = True
    history_seasons: int = 2
    history_seasons_by_position: tuple[tuple[str, int], ...] = tuple(
        sorted(projection_module.HISTORY_SEASONS_BY_POSITION.items())
    )
    opponent_cap_by_position: tuple[tuple[str, float], ...] = tuple(
        sorted(projection_module.OPPONENT_CAP_BY_POSITION.items())
    )
    position_average_weight_by_position: tuple[tuple[str, float], ...] = tuple(
        sorted(projection_module.POSITION_AVERAGE_WEIGHT_BY_POSITION.items())
    )
    position_average_uses_plain_mean: bool = True
    prior_games_weight_by_position: tuple[tuple[str, int], ...] = tuple(
        sorted(projection_module.PRIOR_GAMES_WEIGHT_BY_POSITION.items())
    )
    player_position_weight_by_position: tuple[tuple[str, int], ...] = tuple(
        sorted(projection_module.PLAYER_POSITION_WEIGHT_BY_POSITION.items())
    )
    trim_fraction_by_position: tuple[tuple[str, float], ...] = tuple(
        sorted(projection_module.OUTLIER_TRIM_FRACTION_BY_POSITION.items())
    )
    central_quantile_by_position: tuple[tuple[str, float], ...] = tuple(
        sorted(projection_module.CENTRAL_QUANTILE_BY_POSITION.items())
    )


@dataclass
class ErrorMetrics:
    count: int = 0
    absolute_error: float = 0.0
    squared_error: float = 0.0
    signed_error: float = 0.0
    actual_total: float = 0.0
    actual_squared: float = 0.0

    def add(self, projected: float, actual: float) -> None:
        error = projected - actual
        self.count += 1
        self.absolute_error += abs(error)
        self.squared_error += error**2
        self.signed_error += error
        self.actual_total += actual
        self.actual_squared += actual**2

    def merge(self, other: ErrorMetrics) -> None:
        self.count += other.count
        self.absolute_error += other.absolute_error
        self.squared_error += other.squared_error
        self.signed_error += other.signed_error
        self.actual_total += other.actual_total
        self.actual_squared += other.actual_squared

    def actual_standard_deviation(self) -> float:
        """Population standard deviation of the actual scores being predicted."""
        if self.count < 2:
            return 0.0
        mean = self.actual_total / self.count
        variance = self.actual_squared / self.count - mean**2
        return math.sqrt(max(0.0, variance))

    def summary(self) -> dict[str, float | int | None]:
        if not self.count:
            return {
                'count': 0,
                'mae': None,
                'rmse': None,
                'bias': None,
                'actual_mean': None,
                'actual_sd': None,
                'mae_over_sd': None,
            }
        mae = self.absolute_error / self.count
        deviation = self.actual_standard_deviation()
        return {
            'count': self.count,
            'mae': round(mae, 3),
            'rmse': round(math.sqrt(self.squared_error / self.count), 3),
            'bias': round(self.signed_error / self.count, 3),
            'actual_mean': round(self.actual_total / self.count, 3),
            'actual_sd': round(deviation, 3),
            # Error relative to how variable the position is. A predictor that
            # always guesses the mean lands near 0.8; above that is no skill.
            'mae_over_sd': round(mae / deviation, 3) if deviation else None,
        }


BASELINE_NAMES = ('position_mean', 'player_mean')


def _baseline_metrics() -> dict[str, ErrorMetrics]:
    return {name: ErrorMetrics() for name in BASELINE_NAMES}


@dataclass
class BacktestMetrics:
    players: ErrorMetrics = field(default_factory=ErrorMetrics)
    teams: ErrorMetrics = field(default_factory=ErrorMetrics)
    positions: dict[str, ErrorMetrics] = field(default_factory=lambda: defaultdict(ErrorMetrics))
    # Naive reference predictors scored on exactly the same predictions as the
    # model, so "is the model better than guessing the average?" is answerable.
    baselines: dict[str, ErrorMetrics] = field(default_factory=_baseline_metrics)
    baseline_positions: dict[str, dict[str, ErrorMetrics]] = field(
        default_factory=lambda: {name: defaultdict(ErrorMetrics) for name in BASELINE_NAMES}
    )
    matchup_count: int = 0
    correct_winners: int = 0
    brier_total: float = 0.0

    def add_baseline(self, name: str, position: str, projected: float, actual: float) -> None:
        self.baselines[name].add(projected, actual)
        self.baseline_positions[name][position].add(projected, actual)

    def merge(self, other: BacktestMetrics) -> None:
        self.players.merge(other.players)
        self.teams.merge(other.teams)
        for position, metrics in other.positions.items():
            self.positions[position].merge(metrics)
        for name in BASELINE_NAMES:
            self.baselines[name].merge(other.baselines[name])
            for position, metrics in other.baseline_positions[name].items():
                self.baseline_positions[name][position].merge(metrics)
        self.matchup_count += other.matchup_count
        self.correct_winners += other.correct_winners
        self.brier_total += other.brier_total

    def _skill(self) -> dict[str, Any]:
        """Model MAE relative to each baseline. Negative means the model wins."""
        skill: dict[str, Any] = {}
        for name in BASELINE_NAMES:
            overall = self.baselines[name]
            positions = {
                position: round(
                    (self.positions[position].absolute_error / self.positions[position].count)
                    / (metrics.absolute_error / metrics.count)
                    - 1,
                    4,
                )
                for position, metrics in sorted(self.baseline_positions[name].items())
                if metrics.count and metrics.absolute_error and self.positions[position].count
            }
            skill[name] = {
                'overall': round(
                    (self.players.absolute_error / self.players.count)
                    / (overall.absolute_error / overall.count)
                    - 1,
                    4,
                )
                if overall.count and overall.absolute_error and self.players.count
                else None,
                'positions': positions,
            }
        return skill

    def summary(self) -> dict[str, Any]:
        return {
            'players': self.players.summary(),
            'teams': self.teams.summary(),
            'positions': {
                position: metrics.summary() for position, metrics in sorted(self.positions.items())
            },
            'baselines': {
                name: {
                    'overall': self.baselines[name].summary(),
                    'positions': {
                        position: metrics.summary()
                        for position, metrics in sorted(self.baseline_positions[name].items())
                    },
                }
                for name in BASELINE_NAMES
            },
            'skill_vs_baseline': self._skill(),
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
        'TREAT_UNKNOWN_TEAM_AS_BYE': settings.treat_unknown_team_as_bye,
        'POSITION_MEAN_STARTERS_ONLY': settings.position_mean_starters_only,
        'USE_MARKET_LINES_FOR_HEAD_COACH': settings.market_lines_for_head_coach,
        'USE_MARKET_LINES_FOR_DEFENSE': settings.market_lines_for_defense,
        'HEAD_COACH_MARGIN_SPREAD': settings.head_coach_margin_spread,
        'IMPLIED_TOTAL_SENSITIVITY': settings.implied_total_sensitivity,
        'HOME_AWAY_ADJUSTMENT': settings.home_away_adjustment,
        'UNBIASED_TEAM_TOTALS': settings.unbiased_team_totals,
        'HISTORY_SEASONS': settings.history_seasons,
        'HISTORY_SEASONS_BY_POSITION': dict(settings.history_seasons_by_position),
        'OPPONENT_CAP_BY_POSITION': dict(settings.opponent_cap_by_position),
        'POSITION_AVERAGE_WEIGHT_BY_POSITION': dict(settings.position_average_weight_by_position),
        'POSITION_AVERAGE_USES_PLAIN_MEAN': settings.position_average_uses_plain_mean,
        'PRIOR_GAMES_WEIGHT_BY_POSITION': dict(settings.prior_games_weight_by_position),
        'PLAYER_POSITION_WEIGHT_BY_POSITION': dict(settings.player_position_weight_by_position),
        'OUTLIER_TRIM_FRACTION_BY_POSITION': dict(settings.trim_fraction_by_position),
        'CENTRAL_QUANTILE_BY_POSITION': dict(settings.central_quantile_by_position),
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


class _RunningMeans:
    """Walk-forward running averages backing the naive baseline predictors.

    Only observations from strictly earlier weeks are ever visible, matching the
    no-leakage rule the model itself follows.
    """

    def __init__(self) -> None:
        self._positions: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        self._players: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0.0])

    def observe(self, player_key: tuple[str, str], score: float) -> None:
        position = player_key[1]
        for bucket in (self._positions[position], self._players[player_key]):
            bucket[0] += score
            bucket[1] += 1

    def position_mean(self, position: str) -> float:
        total, count = self._positions[position]
        return total / count if count else 0.0

    def player_mean(self, player_key: tuple[str, str]) -> float:
        total, count = self._players[player_key]
        if not count:
            return self.position_mean(player_key[1])
        return total / count

    def observe_week(self, week_data: Mapping[str, Any]) -> None:
        for team in week_data.get('teams', []) or []:
            for player in team.get('roster', []) or []:
                score = player.get('score')
                name = player.get('name')
                position = player.get('position')
                if player.get('starter') is not True:
                    continue
                if not isinstance(score, (int, float)) or not math.isfinite(score):
                    continue
                if not isinstance(name, str) or not isinstance(position, str):
                    continue
                if player.get('found') is False:
                    continue
                self.observe((normalize_player_name(name), position), float(score))

    def seed_from_season(self, history_root: Path, season: int) -> None:
        weeks_dir = history_root / str(season) / 'weeks'
        if not weeks_dir.is_dir():
            return
        for path in sorted(weeks_dir.glob('week_*.json')):
            try:
                self.observe_week(json.loads(path.read_text(encoding='utf-8')))
            except (OSError, json.JSONDecodeError):
                continue


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
    residuals: list[dict[str, Any]] | None = None,
) -> BacktestMetrics:
    metrics = BacktestMetrics()
    running = _RunningMeans()
    running.seed_from_season(history_root, season - 1)
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

                player_key = (key[1], position)
                position_mean = running.position_mean(position)
                player_mean = running.player_mean(player_key)
                metrics.add_baseline('position_mean', position, position_mean, actual)
                metrics.add_baseline('player_mean', position, player_mean, actual)

                if residuals is not None:
                    residuals.append(
                        {
                            'season': season,
                            'week': week,
                            'team': key[0],
                            'player': key[1],
                            'position': position,
                            'projected': projection.projected_points,
                            'actual': actual,
                            'sample_size': projection.sample_size,
                            'opponent_multiplier': round(projection.opponent_multiplier, 4),
                            'on_bye': projection.on_bye,
                            'position_mean': round(position_mean, 3),
                            'player_mean': round(player_mean, 3),
                        }
                    )

            # Absorb this week only after it has been predicted.
            running.observe_week(week_data)

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


def parse_season_range(value: str) -> list[int]:
    """Parse ``2021-2025`` or ``2021,2023`` into an ascending list of seasons."""
    seasons: set[int] = set()
    for part in value.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part.lstrip('-'):
            start_text, _, end_text = part.partition('-')
            start, end = int(start_text), int(end_text)
            if end < start:
                raise argparse.ArgumentTypeError(f'Invalid season range: {part}')
            seasons.update(range(start, end + 1))
        else:
            seasons.add(int(part))
    if not seasons:
        raise argparse.ArgumentTypeError('No seasons requested')
    return sorted(seasons)


# Structural flags and per-position tables off: how the model behaved before any
# tuning work, and how it behaved between the 2024 tuning and the 2021-2025 study.
_UNTUNED_STRUCTURE = {
    'treat_unknown_team_as_bye': True,
    'position_mean_starters_only': False,
    'market_lines_for_head_coach': False,
    'market_lines_for_defense': False,
    'prior_games_weight_by_position': (),
    'player_position_weight_by_position': (),
    'trim_fraction_by_position': (),
    'central_quantile_by_position': (),
    'unbiased_team_totals': False,
    'history_seasons_by_position': (),
    'opponent_cap_by_position': (),
    'position_average_weight_by_position': (),
    'position_average_uses_plain_mean': False,
}

BASELINE_SETTINGS = ProjectionSettings(
    prior_games_weight=4,
    player_position_weight=0,
    trim_fraction=0,
    minimum_trim_samples=10,
    opponent_full_weight_samples=1,
    exclude_legacy_bench_zeroes=False,
    **_UNTUNED_STRUCTURE,
)

PREVIOUS_SETTINGS = ProjectionSettings(
    prior_games_weight=2,
    player_position_weight=8,
    trim_fraction=0.1,
    **_UNTUNED_STRUCTURE,
)


def _write_residuals(path: Path | None, residuals: list[dict[str, Any]] | None) -> None:
    if path is None or residuals is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as handle:
        for row in residuals:
            handle.write(json.dumps(row) + '\n')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', type=int, default=2025, help='Season to evaluate')
    parser.add_argument(
        '--seasons',
        type=parse_season_range,
        help='Evaluate several seasons and pool the results, e.g. 2021-2025',
    )
    parser.add_argument(
        '--tune',
        action='store_true',
        help='Tune on the preceding season before evaluating the requested season',
    )
    parser.add_argument(
        '--dump-residuals',
        type=Path,
        help='Write one JSON line per current-model prediction to this path',
    )
    args = parser.parse_args()

    history_root = PROJECT_ROOT / 'web' / 'data' / 'seasons'
    evaluation_weeks = list(range(1, 18))
    current = ProjectionSettings()
    residuals: list[dict[str, Any]] | None = [] if args.dump_residuals else None

    if args.seasons:
        seasons: list[int] = args.seasons
        if args.tune:
            parser.error('--tune evaluates a single season; use --season with --tune')
        needed = sorted({year for season in seasons for year in (season - 2, season - 1, season)})
        schedule_rows = load_projection_schedule_rows(needed)
        pooled = {
            'original_model': BacktestMetrics(),
            'previous_model': BacktestMetrics(),
            'current_model': BacktestMetrics(),
        }
        per_season: dict[str, Any] = {}
        for season in seasons:
            season_report: dict[str, Any] = {}
            for label, settings in (
                ('original_model', BASELINE_SETTINGS),
                ('previous_model', PREVIOUS_SETTINGS),
                ('current_model', current),
            ):
                metrics = run_backtest(
                    season,
                    evaluation_weeks,
                    settings,
                    history_root,
                    schedule_rows,
                    residuals if label == 'current_model' else None,
                )
                pooled[label].merge(metrics)
                season_report[label] = metrics.summary()
            per_season[str(season)] = season_report

        print(
            json.dumps(
                {
                    'evaluation_seasons': seasons,
                    'evaluation_weeks': [1, 17],
                    'settings': {
                        'original_model': asdict(BASELINE_SETTINGS),
                        'previous_model': asdict(PREVIOUS_SETTINGS),
                        'current_model': asdict(current),
                    },
                    'seasons': per_season,
                    'pooled': {label: metrics.summary() for label, metrics in pooled.items()},
                },
                indent=2,
            )
        )
        _write_residuals(args.dump_residuals, residuals)
        return

    tuning_season = args.season - 1
    schedule_rows = load_projection_schedule_rows([args.season - 2, tuning_season, args.season])
    report: dict[str, Any] = {
        'evaluation_season': args.season,
        'evaluation_weeks': [1, 17],
        'original_model': {
            'settings': asdict(BASELINE_SETTINGS),
            'evaluation': run_backtest(
                args.season,
                evaluation_weeks,
                BASELINE_SETTINGS,
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
                residuals,
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
    _write_residuals(args.dump_residuals, residuals)


if __name__ == '__main__':
    main()
