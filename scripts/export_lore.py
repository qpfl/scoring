#!/usr/bin/env python3
"""Generate the shared League Lore resource without external services."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from qpfl.lore import export_league_lore  # noqa: E402


def main() -> None:
    lore = export_league_lore(PROJECT_ROOT / 'data', PROJECT_ROOT / 'web')
    print(
        'Exported League Lore: '
        f"{sum(len(weeks) for weeks in lore['chronicles'].values())} weeks, "
        f"{len(lore['rivalries'])} rivalries, {len(lore['yearbooks'])} yearbooks"
    )


if __name__ == '__main__':
    main()
