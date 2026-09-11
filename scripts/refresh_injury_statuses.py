#!/usr/bin/env python3
"""Refresh data/injury_statuses.json from Sleeper (no-op if cache is still fresh)."""

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from qpfl.injuries import load_injury_statuses  # noqa: E402
from qpfl.json_scorer import load_rosters  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, default=Path('data'))
    args = parser.parse_args()

    rosters = load_rosters(args.data_dir / 'rosters.json')
    result = load_injury_statuses(rosters, args.data_dir / 'injury_statuses.json')
    print(f"Injury cache updated_at: {result.get('updated_at')} ({len(result.get('players', {}))} players)")


if __name__ == '__main__':
    main()
