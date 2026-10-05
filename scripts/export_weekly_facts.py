"""Generate the weekly "By the Numbers" facts file for the newsletter and site.

Flattens every season the Hall of Fame reads into team and player game rows,
then asks `qpfl.weekly_facts` what was notable about one week compared with
everything before it. Output: web/data/seasons/{season}/facts/week_{week}.json
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from qpfl.constants import SEASONS_DIR, SHARED_DIR
from qpfl.weekly_facts import (
    CONSOLATION,
    PLAYOFFS,
    REGULAR,
    PlayerGame,
    TeamGame,
    generate_week_facts,
)
from scripts import export_hall_of_fame as hof

PLAYOFF_BRACKETS = {'playoffs', 'championship'}

# Earlier ownership eras that belong to a current franchise seat.
LINEAGE = {old: current for current, olds in hof.FRANCHISE_LINEAGE.items() for old in olds}


def franchises_for(abbrev: str) -> tuple[str, ...]:
    """Every current franchise a historical team code counts toward."""
    return tuple(dict.fromkeys(LINEAGE.get(code, code) for code in hof.franchise_codes(abbrev)))


def regular_season_weeks(season: int) -> int:
    return 14 if season <= 2021 else 15


def bracket_for(matchup: dict, week: int, season: int) -> str:
    bracket = matchup.get('bracket')
    if bracket in PLAYOFF_BRACKETS:
        return PLAYOFFS
    if bracket:
        return CONSOLATION
    return REGULAR if week <= regular_season_weeks(season) else PLAYOFFS


def flatten_season(season_data: dict) -> tuple[list[TeamGame], list[PlayerGame]]:
    season = season_data['season']
    team_games: list[TeamGame] = []
    player_games: list[PlayerGame] = []
    # First-leg scores of two-week matchups, so the second leg can carry the
    # combined result.
    first_legs: dict[tuple, dict[str, float]] = {}
    for week in season_data['weeks']:
        week_num = week.get('week')
        if not isinstance(week_num, int) or week.get('has_scores') is False:
            continue
        label = hof.get_week_name(week_num, season)
        for matchup in week.get('matchups', []):
            t1, t2 = matchup.get('team1'), matchup.get('team2')
            if not isinstance(t1, dict) or not isinstance(t2, dict):
                continue
            s1, s2 = hof.get_team_score(t1), hof.get_team_score(t2)
            if s1 is None or s2 is None:
                continue
            bracket = bracket_for(matchup, week_num, season)
            two_week = bool(matchup.get('two_week'))
            totals = None
            if two_week:
                key = (
                    matchup.get('bracket'),
                    *sorted((t1.get('abbrev', ''), t2.get('abbrev', ''))),
                )
                if key in first_legs:
                    leg = first_legs.pop(key)
                    totals = {
                        t1.get('abbrev', ''): leg.get(t1.get('abbrev', ''), 0.0) + float(s1),
                        t2.get('abbrev', ''): leg.get(t2.get('abbrev', ''), 0.0) + float(s2),
                    }
                else:
                    first_legs[key] = {
                        t1.get('abbrev', ''): float(s1),
                        t2.get('abbrev', ''): float(s2),
                    }
            for team, opp, score, opp_score in ((t1, t2, s1, s2), (t2, t1, s2, s1)):
                abbrev = team.get('abbrev', '')
                team_games.append(
                    TeamGame(
                        season=season,
                        week=week_num,
                        week_label=label,
                        bracket=bracket,
                        abbrev=abbrev,
                        franchises=franchises_for(abbrev),
                        score=float(score),
                        opp_abbrev=opp.get('abbrev', ''),
                        opp_franchises=franchises_for(opp.get('abbrev', '')),
                        opp_score=float(opp_score),
                        two_week=two_week,
                        result_score=totals[abbrev] if totals else None,
                        result_opp_score=totals[opp.get('abbrev', '')] if totals else None,
                    )
                )
                for player in team.get('roster', []):
                    points = player.get('score')
                    if not player.get('starter') or not isinstance(points, (int, float)):
                        continue
                    name = hof.clean_player_name(player.get('name', ''))
                    position = hof.canonical_profile_position(player.get('position'))
                    key = hof.player_identity_key(name, position)
                    if not key:
                        continue
                    player_games.append(
                        PlayerGame(
                            season=season,
                            week=week_num,
                            week_label=label,
                            bracket=bracket,
                            player_key=key,
                            name=name,
                            position=position,
                            abbrev=abbrev,
                            franchises=franchises_for(abbrev),
                            score=float(points),
                        )
                    )
    return team_games, player_games


def load_history(current_season: int, completed_through: int) -> tuple[list, list]:
    team_games, player_games = [], []
    for season in hof.discover_seasons(current_season):
        if season > current_season:
            continue
        data = hof.load_season_data(season, current_season, completed_through)
        teams, players = flatten_season(data)
        team_games.extend(teams)
        player_games.extend(players)
    return team_games, player_games


def facts_path(season: int, week: int) -> Path:
    return SEASONS_DIR / str(season) / 'facts' / f'week_{week}.json'


def write_facts(facts: dict, path: Path) -> bool:
    """Write unless only the timestamp would change."""
    if path.exists():
        with open(path) as f:
            existing = json.load(f)
        if {k: v for k, v in existing.items() if k != 'generated_at'} == facts:
            return False
    output = {**facts, 'generated_at': datetime.now(timezone.utc).isoformat()}
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(output, f, indent=2)
        f.write('\n')
    return True


def default_week(season: int) -> int:
    hof_file = SHARED_DIR / 'hall_of_fame.json'
    if hof_file.exists():
        with open(hof_file) as f:
            week = json.load(f).get('completed_through', {}).get(str(season))
        if isinstance(week, int):
            return week
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', type=int)
    parser.add_argument(
        '--week', type=int, help='Week to describe (default: HOF completed_through)'
    )
    parser.add_argument('--current-season', type=int, help='Live season (default: league_config)')
    parser.add_argument(
        '--backfill', action='store_true', help='Regenerate every scored week of --season'
    )
    parser.add_argument('--limit', type=int, default=10)
    args = parser.parse_args()

    current = args.current_season or hof.configured_current_season()
    season = args.season or current
    completed = args.week if args.week is not None else default_week(current)
    if season == current and completed <= 0 and not args.backfill:
        print('No completed weeks yet; nothing to do.')
        return

    team_games, player_games = load_history(current, completed if season == current else 99)
    if args.backfill:
        weeks = sorted({g.week for g in team_games if g.season == season})
    else:
        weeks = [args.week if args.week is not None else completed]

    for week in weeks:
        facts = generate_week_facts(team_games, player_games, season, week, limit=args.limit)
        path = facts_path(season, week)
        changed = write_facts(facts, path)
        status = 'wrote' if changed else 'unchanged'
        print(f'{season} week {week}: {len(facts["all"])} facts, {status} {path}')


if __name__ == '__main__':
    main()
