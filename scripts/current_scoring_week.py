#!/usr/bin/env python3
"""Print the fantasy week scoring should work on (see qpfl.week_status.current_scoring_week)."""

import argparse
import sys
from pathlib import Path

import nflreadpy as nfl

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from qpfl.week_status import (  # noqa: E402
    apply_game_overrides,
    current_scoring_week,
    load_game_overrides,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', type=int, required=True)
    parser.add_argument('--data-dir', default='data')
    args = parser.parse_args()

    rows = apply_game_overrides(
        nfl.load_schedules(seasons=args.season).iter_rows(named=True),
        load_game_overrides(args.data_dir),
    )
    print(current_scoring_week(rows, args.season))


if __name__ == '__main__':
    main()
