#!/usr/bin/env python3
"""CLI wrapper for qpfl.integrity.check_all() — repo-wide invariants over data/.

Usage:
    uv run python scripts/check_integrity.py
"""

import sys
from pathlib import Path

# qpfl lives one level up from scripts/; make it importable when run as a script.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from qpfl.integrity import check_all  # noqa: E402


def main() -> int:
    errors = check_all()
    if errors:
        print(f'✗ {len(errors)} integrity violation(s):\n')
        for err in errors:
            print(f'  - {err}')
        return 1
    print('✓ No integrity violations found')
    return 0


if __name__ == '__main__':
    sys.exit(main())
