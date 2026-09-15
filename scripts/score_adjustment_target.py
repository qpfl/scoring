#!/usr/bin/env python3
"""Print the week added by a score-adjustment commit."""

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
    args = parser.parse_args()

    current = json.loads(Path(args.path).read_text(encoding='utf-8'))
    if not isinstance(current, list):
        raise ValueError('Current score adjustments must be a JSON array')
    print(target_week(current, _load_previous(args.path, args.previous_ref), args.season))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
