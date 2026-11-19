"""Write the cross-season chart data the site's charts and QPFLTok read.

Loads every season through the weekly-facts history loader, asks
`qpfl.charts` for each chart's block and writes web/data/shared/charts.json.
Runs in the score workflow after the weekly facts.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from qpfl.charts import build_charts
from qpfl.constants import SHARED_DIR
from scripts import export_hall_of_fame as hof
from scripts.export_weekly_facts import default_week, load_history, write_facts

CHARTS_PATH = SHARED_DIR / 'charts.json'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--current-season', type=int, help='Live season (default: league_config)')
    parser.add_argument(
        '--completed-through',
        type=int,
        help='Last completed week of the live season (default: HOF completed_through)',
    )
    parser.add_argument('--output', type=Path, default=CHARTS_PATH)
    args = parser.parse_args()

    current = args.current_season or hof.configured_current_season()
    completed = (
        args.completed_through if args.completed_through is not None else default_week(current)
    )
    team_games, player_games, _timeline, _names = load_history(current, completed)
    charts = build_charts(
        team_games, player_games, current_season=current, completed_through=completed
    )
    # Same rule as the facts files: no commit when only the timestamp moves.
    changed = write_facts(charts, args.output)
    print(f'{"Wrote" if changed else "Unchanged:"} {args.output}')


if __name__ == '__main__':
    main()
