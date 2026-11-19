"""Cross-season chart data for the site's charts and QPFLTok.

Pure functions over the flattened history rows that `scripts/export_weekly_facts.py`
already builds (`TeamGame` / `PlayerGame`). `scripts/export_charts.py` writes the
result to web/data/shared/charts.json; web/charts.js draws it.

Each chart family adds its keys here, so charts that need every season never
make the browser fetch seven seasons of week files. See
docs/PLAN_qpfltok_and_charts.md.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from qpfl.weekly_facts import PlayerGame, TeamGame

# Bump when the file's shape changes in a way old clients can't read.
CHARTS_VERSION = 1


def build_charts(
    team_games: Sequence[TeamGame],
    player_games: Sequence[PlayerGame],
    *,
    current_season: int,
    completed_through: int,
) -> dict[str, Any]:
    """Every precomputed chart block, keyed by chart id.

    `completed_through` is the last completed week of `current_season`; the
    history rows passed in must already stop there.
    """
    del team_games, player_games  # The first chart families add their blocks here.
    return {
        'version': CHARTS_VERSION,
        'season': current_season,
        'completed_through': completed_through,
    }
