#!/usr/bin/env python3
"""Dead-man's switch for the scoring pipeline.

score.yml only alerts when a run actually happens and fails
(`if: failure()`). A cron that never fires - and this repo has documented
real dropped ticks (see .github/workflows/nflverse-watch.yml) - produces no
failed run and therefore no alert at all. This script is the independent
check: it looks at committed state for symptoms of "scoring silently
stopped happening" rather than waiting for a run to fail.

Deliberately a separate script/workflow (health.yml) on its own schedule, so
a failure mode that takes out score.yml (e.g. a GitHub Actions outage, or a
bug in score.yml itself) doesn't also take out the thing meant to catch it.

Checks:
1. A week whose NFL games are all final has no matching games_final/has_scores
   in its committed week file (i.e. it was never finalized).
2. The newest `scored_at` across the current season's week files is older
   than `--max-stale-hours`.

Exit code is 1 (with findings printed) if anything looks unhealthy, 0
otherwise. See docs/ROADMAP_2026.md P3.1 / the in-season reliability plan,
phase 2.7.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import nflreadpy as nfl

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from qpfl.week_status import week_games_are_final  # noqa: E402


def _load_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def find_unfinalized_completed_weeks(
    season: int, weeks_dir: Path, schedule_rows: list[dict], max_week: int = 17
) -> list[int]:
    """Weeks whose NFL games are all final but whose committed week file
    doesn't show has_scores/games_final - the signature of a week that
    became complete right as the lock took effect and was never finalized.
    """
    unhealthy = []
    for week in range(1, max_week + 1):
        if not week_games_are_final(schedule_rows, week, season):
            continue
        week_data = _load_json(weeks_dir / f'week_{week}.json')
        if not isinstance(week_data, dict):
            unhealthy.append(week)
            continue
        if not week_data.get('has_scores') or not week_data.get('games_final'):
            unhealthy.append(week)
    return unhealthy


def newest_scored_at(weeks_dir: Path) -> datetime | None:
    """The most recent `scored_at` timestamp across every week file, or None
    if no week file has one (a season with no weeks scored yet)."""
    newest = None
    if not weeks_dir.is_dir():
        return None
    for path in sorted(weeks_dir.glob('week_*.json')):
        data = _load_json(path)
        if not isinstance(data, dict):
            continue
        scored_at = data.get('scored_at')
        if not isinstance(scored_at, str):
            continue
        try:
            parsed = datetime.fromisoformat(scored_at.replace('Z', '+00:00'))
        except ValueError:
            continue
        if newest is None or parsed > newest:
            newest = parsed
    return newest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', type=int, required=True)
    parser.add_argument('--data-dir', default='data')
    parser.add_argument('--web-dir', default='web')
    parser.add_argument('--max-week', type=int, default=17)
    parser.add_argument(
        '--max-stale-hours',
        type=float,
        default=48.0,
        help=(
            'How long scored_at can go without advancing before it is flagged. '
            'Games are played on most days of an in-season week, so this stays '
            'well above the longest normal mid-week gap to avoid false alarms.'
        ),
    )
    args = parser.parse_args()

    weeks_dir = Path(args.web_dir) / 'data' / 'seasons' / str(args.season) / 'weeks'
    findings: list[str] = []

    try:
        schedule_rows = list(nfl.load_schedules(seasons=args.season).iter_rows(named=True))
    except Exception as e:
        print(f'WARNING: could not load NFL schedule ({e}); skipping the unfinalized-week check')
        schedule_rows = []

    if schedule_rows:
        unhealthy_weeks = find_unfinalized_completed_weeks(
            args.season, weeks_dir, schedule_rows, args.max_week
        )
        if unhealthy_weeks:
            findings.append(
                f'Week(s) {", ".join(str(w) for w in unhealthy_weeks)} have all-final NFL '
                'games but the committed week file does not show has_scores/games_final - '
                'they may never have been finalized (see --finalize in autoscorer_json.py).'
            )

    newest = newest_scored_at(weeks_dir)
    now = datetime.now(timezone.utc)
    if newest is not None:
        age_hours = (now - newest).total_seconds() / 3600
        if age_hours > args.max_stale_hours:
            findings.append(
                f'The newest scored_at in {weeks_dir} is {age_hours:.1f} hours old '
                f'(threshold: {args.max_stale_hours}h) - scoring may have silently '
                'stopped running.'
            )

    if findings:
        print('SCORING HEALTH CHECK FAILED:\n')
        for finding in findings:
            print(f'- {finding}')
        return 1

    print('Scoring health check passed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
