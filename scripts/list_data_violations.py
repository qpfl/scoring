#!/usr/bin/env python3
"""Print every schema/integrity violation under data/, one per line. Always
exits 0 - this is a reporting tool, not a gate.

Used by score.yml to capture a baseline (before this run's own changes) and
a post-run snapshot, so the workflow can fail only on violations this run
introduced rather than on any pre-existing one. A single stale violation
blocking every future scoring commit indefinitely, until a human notices and
fixes it by hand, is worse than letting scoring proceed while still
surfacing the problem. See docs/ROADMAP_2026.md P3.1 / the in-season
reliability plan, phase 3.4.
"""

import argparse
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from qpfl.constants import DATA_DIR  # noqa: E402
from qpfl.data_validation import validate_data_dir  # noqa: E402
from qpfl.integrity import check_all  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', default=DATA_DIR)
    args = parser.parse_args()

    for violation in [*validate_data_dir(args.data_dir), *check_all(args.data_dir)]:
        print(violation.replace('\n', ' '))
    return 0


if __name__ == '__main__':
    sys.exit(main())
