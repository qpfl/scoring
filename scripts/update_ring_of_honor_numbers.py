"""Look up jersey numbers for Ring of Honor plaques.

Every player in a franchise's Ring of Honor (``manual_honors.json``) gets a
plaque on the site. Plaques show the jersey number the player wore for his NFL
team while he was on that QPFL franchise. This fills in any inductee missing
from ``ring_of_honor_numbers.json`` from nflverse rosters, so a new inductee's
plaque gets its number on the next scoring run with nothing to add by hand.

Numbers already on file are kept (pass ``--refresh`` to look them all up
again). Head coaches, D/ST and OL have no number; their plaques show the NFL
team instead, so they are skipped.

Usage:
    python scripts/update_ring_of_honor_numbers.py [--refresh]
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from qpfl.constants import SHARED_DIR

MANUAL_HONORS_PATH = SHARED_DIR / 'manual_honors.json'
HALL_OF_FAME_PATH = SHARED_DIR / 'hall_of_fame.json'
NUMBERS_PATH = SHARED_DIR / 'ring_of_honor_numbers.json'

NUMBERED_POSITIONS = {'QB', 'RB', 'WR', 'TE', 'K'}

# Franchises that changed abbreviation under a new owner (mirrors
# FRANCHISE_SUCCESSION_GROUPS in web/app.js).
FRANCHISE_SUCCESSION_GROUPS = [
    {'MPA', 'RPA'},
    {'RCP', 'JDK', 'J/J'},
    {'JRW', 'AST'},
]
# Co-owned franchises whose code contains a slash but is one team.
CO_OWNED_CODES = {'S/T', 'J/J'}

_SUFFIX = re.compile(r'\b(jr|sr|ii|iii|iv|v)\b')


def normalize_name(name: str) -> str:
    """Lowercase, drop punctuation and generational suffixes."""
    key = re.sub(r"[.'’]", '', str(name or '').lower())
    key = _SUFFIX.sub('', key.replace('-', ' '))
    return ' '.join(key.split())


def franchise_codes(franchise: str) -> set[str]:
    for group in FRANCHISE_SUCCESSION_GROUPS:
        if franchise in group:
            return set(group)
    return {franchise}


def owner_matches_franchise(owner: str, franchise: str) -> bool:
    """Whether a season's owner code (e.g. ``CGK/SRY``) is this franchise."""
    codes = franchise_codes(franchise)
    if owner in codes:
        return True
    if owner in CO_OWNED_CODES:
        return False
    return any(part in codes for part in owner.split('/'))


def franchise_seasons(profile: dict, franchise: str) -> list[int]:
    return sorted(
        int(season)
        for season, stats in (profile.get('seasons') or {}).items()
        if any(owner_matches_franchise(owner, franchise) for owner in stats.get('owners') or [])
    )


def find_profile(profiles: dict, name: str, position: str) -> dict | None:
    key = normalize_name(name)
    for profile in profiles.values():
        names = [profile.get('name', ''), *(profile.get('aliases') or [])]
        if profile.get('position') == position and any(normalize_name(n) == key for n in names):
            return profile
    return None


def lookup_number(rows: list[dict], name: str, nfl_teams: set[str]) -> int | None:
    """The jersey number he wore most often for those NFL teams."""
    key = normalize_name(name)
    matches = [
        row
        for row in rows
        if normalize_name(row.get('full_name')) == key and row.get('jersey_number') is not None
    ]
    on_team = [row for row in matches if row.get('team') in nfl_teams]
    numbers = Counter(int(row['jersey_number']) for row in (on_team or matches))
    return numbers.most_common(1)[0][0] if numbers else None


def load_roster_rows(seasons: set[int]) -> list[dict]:
    import nflreadpy as nfl

    frame = nfl.load_rosters(seasons=sorted(seasons))
    return [
        {key: row.get(key) for key in ('season', 'full_name', 'team', 'jersey_number')}
        for row in frame.iter_rows(named=True)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--refresh', action='store_true', help='Look up every number again')
    args = parser.parse_args()

    honors = json.loads(MANUAL_HONORS_PATH.read_text())
    profiles = json.loads(HALL_OF_FAME_PATH.read_text()).get('player_career_stats') or {}
    numbers: dict[str, dict[str, int]] = {}
    if NUMBERS_PATH.exists() and not args.refresh:
        numbers = json.loads(NUMBERS_PATH.read_text())

    wanted = []
    for franchise, entry in (honors.get('team_ring_of_honor') or {}).items():
        for player in entry.get('players') or []:
            if player.get('position') not in NUMBERED_POSITIONS:
                continue
            if player['name'] in numbers.get(franchise, {}):
                continue
            profile = find_profile(profiles, player['name'], player['position'])
            seasons = franchise_seasons(profile, franchise) if profile else []
            if not seasons:
                print(f'  {franchise} {player["name"]}: no seasons with the franchise, skipped')
                continue
            wanted.append((franchise, player, seasons))

    if not wanted:
        print('Ring of Honor numbers are up to date.')
        return 0

    rows = load_roster_rows({season for _, _, seasons in wanted for season in seasons})
    for franchise, player, seasons in wanted:
        nfl_teams = set(str(player.get('team') or '').split('/'))
        season_rows = [row for row in rows if row['season'] in seasons]
        number = lookup_number(season_rows, player['name'], nfl_teams)
        if number is None:
            print(f'  {franchise} {player["name"]}: no jersey number found')
            continue
        numbers.setdefault(franchise, {})[player['name']] = number
        print(f'  {franchise} {player["name"]}: #{number}')

    ordered = {team: dict(sorted(players.items())) for team, players in sorted(numbers.items())}
    NUMBERS_PATH.write_text(json.dumps(ordered, indent=2) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
