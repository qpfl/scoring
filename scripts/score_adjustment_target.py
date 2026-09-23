#!/usr/bin/env python3
"""Print the weeks a score-adjustment change needs rescored.

With --state, compares data/score_adjustments.json against the adjustments
the last successful scoring run applied (recorded in data/scoring_state.json)
and prints every affected week, space-separated - additions and removals
alike, however many pushes were coalesced into this run. --record writes the
current adjustments into the state file once those weeks are rescored.
"""

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any


def _identity(adjustment: Any) -> str:
    return json.dumps(adjustment, sort_keys=True, separators=(',', ':'))


def added_adjustments(current: list, previous: list) -> list[dict]:
    """Return list entries newly added since the previous revision."""
    remaining = Counter(_identity(item) for item in previous)
    added = []
    for item in current:
        identity = _identity(item)
        if remaining[identity]:
            remaining[identity] -= 1
        elif isinstance(item, dict):
            added.append(item)
    return added


def target_week(current: list, previous: list, season: int) -> int:
    additions = added_adjustments(current, previous)
    targets = {
        int(item['week'])
        for item in additions
        if int(item.get('season', -1)) == season and 1 <= int(item.get('week', 0)) <= 17
    }
    if len(targets) != 1:
        raise ValueError(
            f'Expected exactly one new {season} score-adjustment week; found {sorted(targets)}'
        )
    return targets.pop()


def changed_weeks(current: list, scored: list, season: int) -> list[int]:
    """Weeks with an adjustment added or removed since ``scored`` was applied."""
    now, before = Counter(map(_identity, current)), Counter(map(_identity, scored))
    changed = (now - before) + (before - now)
    weeks = set()
    for identity in changed:
        item = json.loads(identity)
        if not isinstance(item, dict):
            continue
        try:
            item_season, week = int(item.get('season', -1)), int(item.get('week', 0))
        except (TypeError, ValueError):
            continue
        if item_season == season and 1 <= week <= 17:
            weeks.add(week)
    return sorted(weeks)


def _load_state(path: Path) -> dict:
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def _load_previous(path: str, ref: str) -> list:
    result = subprocess.run(
        ['git', 'show', f'{ref}:{path}'],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    value = json.loads(result.stdout)
    if not isinstance(value, list):
        raise ValueError('Previous score adjustments must be a JSON array')
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--season', type=int, required=True)
    parser.add_argument('--path', default='data/score_adjustments.json')
    parser.add_argument('--previous-ref', default='HEAD~1')
    parser.add_argument('--state', type=Path, help='data/scoring_state.json')
    parser.add_argument(
        '--record', action='store_true', help='Record the current adjustments as applied'
    )
    args = parser.parse_args()

    adjustments_path = Path(args.path)
    current = (
        json.loads(adjustments_path.read_text(encoding='utf-8'))
        if adjustments_path.exists()
        else []
    )
    if not isinstance(current, list):
        raise ValueError('Current score adjustments must be a JSON array')

    if args.state is None:
        print(target_week(current, _load_previous(args.path, args.previous_ref), args.season))
        return 0

    state = _load_state(args.state)
    if args.record:
        state['score_adjustments'] = current
        args.state.write_text(json.dumps(state, indent=2, sort_keys=True) + '\n')
        return 0
    # Before this state existed, nothing was recorded; treat what's committed
    # as already applied rather than rescoring every adjusted week.
    scored = state.get('score_adjustments', current)
    if not isinstance(scored, list):
        scored = []
    print(' '.join(str(week) for week in changed_weeks(current, scored, args.season)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
