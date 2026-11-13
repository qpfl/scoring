"""Generate the pregame notes for an upcoming week's matchups.

Storylines, revenge games, and records or milestones within reach for each
matchup, from games already played (see `qpfl.pregame`). Rosters, starters and
projections come from the week's file when it exists, else from the submitted
lineups and current rosters.

Output: web/data/seasons/{season}/pregame/week_{week}.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from qpfl.constants import SEASONS_DIR, SHARED_DIR
from qpfl.pregame import RosterPlayer, generate_pregame
from qpfl.weekly_facts import TeamGame
from scripts import export_hall_of_fame as hof
from scripts.export_weekly_facts import (
    OWNER_NAMES,
    bracket_for,
    franchises_for,
    load_history,
    load_trades,
    owner_names,
    write_facts,
)
from scripts.hof_records import profile_key_lookup

DATA_DIR = Path(__file__).parent.parent / 'data'


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def _player(row: dict, starter: bool) -> RosterPlayer | None:
    name = hof.clean_player_name(row.get('name', ''))
    position = hof.canonical_profile_position(row.get('position'))
    key = hof.player_identity_key(name, position)
    if not key:
        return None
    projected = row.get('projected_points')
    return RosterPlayer(
        player_key=key,
        name=name,
        position=position,
        starter=starter,
        projected=float(projected) if isinstance(projected, (int, float)) else None,
    )


def load_rosters(season: int, week: int) -> dict[str, list[RosterPlayer]]:
    """Each team's roster for the week, starters flagged."""
    week_file = _load(SEASONS_DIR / str(season) / 'weeks' / f'week_{week}.json')
    rosters: dict[str, list[RosterPlayer]] = {}
    for matchup in week_file.get('matchups', []):
        for side in (matchup.get('team1'), matchup.get('team2')):
            if isinstance(side, dict) and side.get('abbrev'):
                players = (_player(p, bool(p.get('starter'))) for p in side.get('roster') or [])
                rosters[side['abbrev']] = [p for p in players if p]
    if rosters:
        return rosters

    lineups = _load(DATA_DIR / 'lineups' / str(season) / f'week_{week}.json').get('lineups', {})
    for abbrev, players in _load(DATA_DIR / 'rosters.json').items():
        lineup = lineups.get(abbrev) or {}
        started = {
            hof.clean_player_name(name)
            for slot, names in lineup.items()
            if isinstance(names, list)
            for name in names
        }
        built = (_player(p, hof.clean_player_name(p.get('name', '')) in started) for p in players)
        rosters[abbrev] = [p for p in built if p]
    return rosters


def load_team_projections(season: int, week: int) -> dict[str, float]:
    """Each team's pregame projected total from the week's file (the card's "Proj")."""
    week_file = _load(SEASONS_DIR / str(season) / 'weeks' / f'week_{week}.json')
    totals = {}
    for matchup in week_file.get('matchups', []):
        for side in (matchup.get('team1'), matchup.get('team2')):
            if not isinstance(side, dict) or not side.get('abbrev'):
                continue
            value = side.get('pregame_total')
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                totals[side['abbrev']] = float(value)
    return totals


def upcoming_rows(meta: dict, season: int, week: int) -> tuple[list[TeamGame], bool]:
    """One placeholder TeamGame per team in the week's schedule."""
    entry = next((w for w in meta.get('schedule', []) if w.get('week') == week), None)
    if entry is None:
        return [], False
    label = hof.get_week_name(week, season)
    rows = []
    for matchup in entry.get('matchups', []):
        t1, t2 = matchup.get('team1'), matchup.get('team2')
        if not isinstance(t1, str) or not isinstance(t2, str):
            continue
        bracket = bracket_for(matchup, week, season)
        for abbrev, opp in ((t1, t2), (t2, t1)):
            rows.append(
                TeamGame(
                    season=season,
                    week=week,
                    week_label=label,
                    bracket=bracket,
                    abbrev=abbrev,
                    franchises=franchises_for(abbrev),
                    score=0.0,
                    opp_abbrev=opp,
                    opp_franchises=franchises_for(opp),
                    opp_score=0.0,
                    owners=tuple(hof.get_owner_codes(abbrev, season)),
                    opp_owners=tuple(hof.get_owner_codes(opp, season)),
                )
            )
    return rows, bool(entry.get('is_rivalry'))


def standings_ranks(season: int) -> dict[str, int]:
    payload = _load(SEASONS_DIR / str(season) / 'standings.json')
    rows = payload.get('completed_standings') or payload.get('standings') or []
    return {row['abbrev']: index + 1 for index, row in enumerate(rows) if row.get('abbrev')}


def pregame_path(season: int, week: int) -> Path:
    return SEASONS_DIR / str(season) / 'pregame' / f'week_{week}.json'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', type=int, help='Season (default: league_config)')
    parser.add_argument('--week', type=int, help="Week to preview (default: meta's lineup_week)")
    args = parser.parse_args()

    season = args.season or hof.configured_current_season()
    meta = _load(SEASONS_DIR / str(season) / 'meta.json')
    week = args.week or meta.get('lineup_week') or meta.get('current_week') or 0
    if meta.get('is_offseason') or week <= 0:
        print('No upcoming week to preview.')
        return

    upcoming, is_rivalry = upcoming_rows(meta, season, week)
    if not upcoming:
        print(f'{season} week {week}: no scheduled matchups; nothing to preview.')
        return

    current = week >= (meta.get('lineup_week') or meta.get('current_week') or week)
    team_games, player_games, timeline, player_names = load_history(season, week - 1)
    hall = _load(SHARED_DIR / 'hall_of_fame.json')
    records = _load(SHARED_DIR / 'hall_of_fame_records.json')
    notes = generate_pregame(
        team_games,
        player_games,
        season,
        week,
        upcoming,
        load_rosters(season, week),
        # Standings and the record book only exist as they stand today, so a
        # week regenerated after the fact leaves out the notes built on them.
        record_groups=records.get('record_book', {}).get('groups', []) if current else [],
        ranks=standings_ranks(season) if current else {},
        trades=load_trades(timeline, player_names),
        owner_names=OWNER_NAMES,
        profile_key_for=profile_key_lookup(hall.get('player_career_stats', {})),
        owner_code=hof._owner_identity_code,
        is_rivalry=is_rivalry,
        team_projections=load_team_projections(season, week),
    )
    notes['names'] = owner_names(season)
    path = pregame_path(season, week)
    changed = write_facts(notes, path)
    count = sum(
        len(m[kind])
        for m in notes['matchups']
        for kind in ('storylines', 'revenge', 'records', 'milestones')
    )
    print(
        f'{season} week {week}: {count} pregame notes, {"wrote" if changed else "unchanged"} {path}'
    )


if __name__ == '__main__':
    main()
