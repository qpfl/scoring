#!/usr/bin/env python3
"""Score current rostered players for completed weeks they spent off every roster.

A player picked up midseason (a draft, a free-agent activation) has no score
in the week files for the weeks before he joined, because only rostered
players are scored. The roster pages show what a player scored elsewhere in
parentheses; this fills in the weeks he was a free agent, so a midseason pick
like Mike Gesicki shows his full season too.

Each week is rescored from its archived stat snapshot, so the numbers match
how the week was officially scored. Only completed weeks are scored, and a
(player, week) score is computed once and kept in
data/off_roster_scores/<season>.json as {"score", "found"}, where found says
whether he appeared in the week's stats (the roster pages count only those
weeks toward PPG). export_current.py publishes the scores of currently
rostered players with the season's rosters.

Usage:
    python scripts/score_off_roster_weeks.py --season 2026 --completed-through 7
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from qpfl.base_scorer import BaseScorer  # noqa: E402
from qpfl.data_fetcher import NFLDataFetcher, load_snapshot, snapshot_path  # noqa: E402

DATA_DIR = PROJECT_DIR / 'data'


def player_key(player: dict) -> str:
    """Lowercased "name|position": an NFL team name can be both a D/ST and an OL."""
    return f"{player['name'].lower()}|{player['position']}"


def cache_path(season: int, data_dir: Path = DATA_DIR) -> Path:
    return data_dir / 'off_roster_scores' / f'{season}.json'


def load_cache(season: int, data_dir: Path = DATA_DIR) -> dict[str, dict[str, dict]]:
    path = cache_path(season, data_dir)
    if not path.exists():
        return {}
    return json.loads(path.read_text()).get('weeks', {})


def rostered_keys(week: int, season: int, data_dir: Path) -> set[str] | None:
    """Every player on any roster (active or taxi) in that week, or None if unknown."""
    path = data_dir / 'roster_snapshots' / str(season) / f'week_{week}.json'
    if not path.exists():
        return None
    rosters = json.loads(path.read_text()).get('rosters', {})
    return {player_key(p) for players in rosters.values() for p in players}


def missing_by_week(
    rosters: dict[str, list[dict]],
    cache: dict[str, dict[str, dict]],
    season: int,
    completed_through: int,
    data_dir: Path = DATA_DIR,
) -> dict[int, list[dict]]:
    """Current players with no score yet for completed weeks they were off every roster."""
    current = {player_key(p): p for players in rosters.values() for p in players}
    missing: dict[int, list[dict]] = {}
    for week in range(1, completed_through + 1):
        on_rosters = rostered_keys(week, season, data_dir)
        if on_rosters is None:
            continue
        scored = cache.get(str(week), {})
        # A bare number is a score saved before "found" was recorded; rescore it.
        players = [
            p
            for key, p in current.items()
            if key not in on_rosters and not isinstance(scored.get(key), dict)
        ]
        if players:
            missing[week] = players
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--season', type=int, required=True)
    parser.add_argument('--completed-through', type=int, required=True)
    args = parser.parse_args()

    rosters = json.loads((DATA_DIR / 'rosters.json').read_text())
    cache = load_cache(args.season)
    missing = missing_by_week(rosters, cache, args.season, args.completed_through)
    if not missing:
        print('No off-roster weeks to score.')
        return 0

    for week, players in sorted(missing.items()):
        snapshot = snapshot_path(args.season, week)
        if not snapshot.exists():
            print(f'  Week {week}: no stat snapshot, skipping {len(players)} players')
            continue
        fetcher = NFLDataFetcher.from_snapshot(load_snapshot(snapshot), args.season, week)
        scorer = BaseScorer(args.season, week, data_fetcher=fetcher)
        week_scores = cache.setdefault(str(week), {})
        for player in players:
            result = scorer.score_player(
                player['name'], player.get('nfl_team', ''), player['position']
            )
            week_scores[player_key(player)] = {
                'score': result.total_points,
                'found': result.found_in_stats,
            }
        print(f'  Week {week}: scored {len(players)} off-roster players')

    path = cache_path(args.season)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = {
        week: dict(sorted(scores.items()))
        for week, scores in sorted(cache.items(), key=lambda item: int(item[0]))
    }
    path.write_text(json.dumps({'season': args.season, 'weeks': ordered}, indent=2) + '\n')
    print(f'Wrote {path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
