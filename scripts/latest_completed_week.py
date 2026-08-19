#!/usr/bin/env python3
"""Print the latest QPFL week for which every NFL game is final."""

import argparse
import sys
from pathlib import Path

import nflreadpy as nfl

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from qpfl.week_status import latest_completed_week  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--season', type=int, required=True)
    parser.add_argument('--max-week', type=int, default=17)
    args = parser.parse_args()

    schedule = nfl.load_schedules(seasons=args.season)
    rows = schedule.iter_rows(named=True)
    print(latest_completed_week(rows, max_week=args.max_week))


if __name__ == '__main__':
    main()
