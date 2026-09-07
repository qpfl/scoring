#!/usr/bin/env python3
"""
Apply a recorded draft from data/drafts.json to data/rosters.json.

Drafts are recorded in Drafts.xlsx and synced to data/drafts.json by
scripts/sync_drafts_from_excel.py. That file is the historical record of who
picked whom; this script turns those picks into the roster movement they
represent, so rosters.json (the source of truth for everything else) reflects
the draft without hand-editing ten rosters.

Picks are applied in board order, because a player dropped in round 1 is
routinely re-drafted later in the same draft. Regular-round selections land on
the active roster; TAXI-round selections land on the taxi squad. The workbook's
FA section is not a draft round — those players are the post-draft free-agent
pool and are seeded separately with scripts/seed_fa_pool.py.

Positions come from the dropped player when a pick replaces a like-for-like
NFL-team entry (D/ST, OL), from nflreadpy for skill players, from the current
season's coaching staffs for HC, and from POSITION_OVERRIDES for anyone the
lookups miss.

Usage:
    python scripts/apply_draft_to_rosters.py --draft "2026 Offseason Draft" --dry-run
    python scripts/apply_draft_to_rosters.py --draft "2026 Offseason Draft"
"""

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from qpfl.constants import ALL_TEAMS  # noqa: E402

REPO_ROOT = Path(__file__).parent.parent

# nflreadpy uses LA/JAX where the league workbook uses LAR/JAC.
NFLREADPY_TO_OURS = {'LA': 'LAR', 'JAX': 'JAC'}

TEAM_POSITIONS = ('D/ST', 'OL')

# Players nflreadpy can't place — mostly draft-week rookies and coaches who
# aren't on a published NFL roster. Keyed by normalized name.
POSITION_OVERRIDES: dict[str, str] = {
    'jonathan brooks': 'RB',
    'joe brady': 'HC',
    'skylar bell': 'WR',
}

# Misspellings in the hand-recorded draft workbook. Rosters must carry the name
# the scorer will see in the play-by-play, so correct them on the way in and
# report them so the workbook can be fixed too. Keys are normalized, so they
# carry no name suffix — 'michael penix' also matches "Michael Penix Jr".
NAME_CORRECTIONS: dict[str, str] = {
    'andy borregeales': 'Andy Borregales',
    'cairos santos': 'Cairo Santos',
    'ken gainwell': 'Kenny Gainwell',
    'rasheed shaheed': 'Rashid Shaheed',
    'shedeur sander': 'Shedeur Sanders',
    'matthew goldin': 'Matthew Golden',
    'michael penix': 'Michael Penix Jr.',
}


def normalize(name: str) -> str:
    """Loose key for matching names across the workbook and nflreadpy."""
    text = name.lower().replace('’', "'").replace('.', '')
    text = re.sub(r"[^a-z' ]", ' ', text)
    text = re.sub(r'\s+(jr|sr|ii|iii|iv|v)$', '', text.strip())
    return re.sub(r'\s+', ' ', text).strip()


def parse_player_cell(value: str) -> tuple[str, str]:
    """Parse "Player Name (TEAM)" into (name, nfl_team).

    Tolerates the stray brackets that creep into a live-drafted workbook
    ("Zach Ertz {WAS)", "Jonnu Smith (GB(").
    """
    # Rosters use a straight apostrophe (Ja'Marr Chase) because that is what
    # the play-by-play feed uses; the workbook picks up curly ones from Excel.
    text = str(value).strip().replace('’', "'")
    match = re.match(r'^(.*?)\s*[({\[]\s*([A-Za-z]{2,3})\s*[)}\]({\[]?$', text)
    if match:
        team = match.group(2).strip().upper()
        return match.group(1).strip(), NFLREADPY_TO_OURS.get(team, team)
    return text, ''


def team_code(label: str) -> str:
    """ "GSA (via AST)" -> "GSA"."""
    return label.split(' (')[0].strip()


def split_drops(value: str) -> list[str]:
    """A drop cell can carry more than one player, comma separated."""
    return [part.strip() for part in str(value).split(',') if part.strip()]


def load_lookups(season: int) -> tuple[dict[str, str], dict[str, str], set[str], set[str]]:
    """Return (position_by_name, nfl_team_by_name, head_coach_names, nfl_team_names)."""
    positions: dict[str, str] = {}
    teams: dict[str, str] = {}
    coaches: set[str] = set()
    nfl_team_names: set[str] = set()

    try:
        import nflreadpy as nfl
    except ImportError:
        print('  nflreadpy not installed — falling back to overrides only')
        return positions, teams, coaches, nfl_team_names

    for loader, kwargs in ((nfl.load_rosters, {'seasons': [season]}), (nfl.load_players, {})):
        try:
            df = loader(**kwargs)
        except Exception as exc:  # pragma: no cover - network/data availability
            print(f'  {loader.__name__} unavailable: {exc}')
            continue
        if df is None or df.height == 0:
            continue
        name_col = 'full_name' if 'full_name' in df.columns else 'display_name'
        team_col = 'team' if 'team' in df.columns else 'latest_team'
        for row in df.select([name_col, 'position', team_col]).iter_rows():
            name, position, team = row
            if not name or not position:
                continue
            key = normalize(str(name))
            positions.setdefault(key, str(position))
            if team:
                teams.setdefault(key, NFLREADPY_TO_OURS.get(str(team), str(team)))

    try:
        schedules = nfl.load_schedules(seasons=[season])
        for home, away in schedules.select(['home_coach', 'away_coach']).iter_rows():
            for coach in (home, away):
                if coach:
                    coaches.add(normalize(str(coach)))
    except Exception as exc:  # pragma: no cover - network/data availability
        print(f'  load_schedules({season}) unavailable: {exc}')

    try:
        for (team_name,) in nfl.load_teams().select(['team_name']).iter_rows():
            if team_name:
                nfl_team_names.add(normalize(str(team_name)))
    except Exception as exc:  # pragma: no cover - network/data availability
        print(f'  load_teams() unavailable: {exc}')

    return positions, teams, coaches, nfl_team_names


class DraftApplier:
    def __init__(self, rosters: dict[str, list[dict]], season: int):
        self.rosters = rosters
        self.positions, self.nfl_teams, self.coaches, self.nfl_team_names = load_lookups(season)
        # Team names already in use as a D/ST or OL unit, in case load_teams()
        # wasn't reachable.
        self.nfl_team_names |= {
            normalize(p['name'])
            for players in rosters.values()
            for p in players
            if p['position'] in TEAM_POSITIONS
        }
        self.warnings: list[str] = []
        self.corrections: list[str] = []

    def find(self, team: str, name: str, position: str | None = None) -> dict | None:
        """Locate a player on one team's roster.

        `position` scopes the match: an NFL team name can legitimately be one
        roster's D/ST and another's OL, so ownership is per (name, position).
        Drop cells carry no position, so those lookups pass None and fall back
        to a close-name match to absorb workbook typos.
        """
        key = normalize(name)
        players = self.rosters.get(team, [])

        matches = [
            p
            for p in players
            if normalize(p['name']) == key and (position is None or p['position'] == position)
        ]
        if matches:
            return matches[0]

        if position is not None:
            return None

        close = difflib.get_close_matches(key, [normalize(p['name']) for p in players], 1, 0.88)
        if close:
            match = next(p for p in players if normalize(p['name']) == close[0])
            self.corrections.append(f'{team}: read {name!r} as {match["name"]!r}')
            return match
        return None

    def resolve_position(self, team: str, name: str, dropped: list[dict]) -> str | None:
        key = normalize(name)

        if key in POSITION_OVERRIDES:
            return POSITION_OVERRIDES[key]

        # An NFL team name is either a D/ST or an OL unit. A pick that drops one
        # of those is replacing it in kind; otherwise fill the team's open slot.
        if key in self.nfl_team_names:
            for player in dropped:
                if player['position'] in TEAM_POSITIONS:
                    return player['position']
            counts = {
                pos: sum(
                    1 for p in self.rosters[team] if p['position'] == pos and not p.get('taxi')
                )
                for pos in TEAM_POSITIONS
            }
            return min(TEAM_POSITIONS, key=lambda pos: counts[pos])

        if key in self.coaches:
            return 'HC'

        return self.positions.get(key)

    def apply_pick(self, round_label: str, pick: dict) -> None:
        team = team_code(pick['team'])
        if team not in ALL_TEAMS:
            self.warnings.append(f'{round_label}.{pick["pick"]}: unknown team {team!r}')
            return

        dropped_players: list[dict] = []
        for raw in split_drops(pick.get('dropped') or ''):
            name, _ = parse_player_cell(raw)
            player = self.find(team, name)
            if player is None:
                self.warnings.append(
                    f'{round_label}.{pick["pick"]} {team}: dropped {name!r} is not on the roster'
                )
                continue
            self.rosters[team].remove(player)
            dropped_players.append(player)

        if pick['player'] == 'PASS':
            return

        name, nfl_team = parse_player_cell(pick['player'])
        corrected = NAME_CORRECTIONS.get(normalize(name))
        if corrected:
            self.corrections.append(
                f'{round_label}.{pick["pick"]} {team}: {name!r} -> {corrected!r}'
            )
            name = corrected

        is_taxi = round_label.startswith('TAXI')

        position = pick.get('position') or self.resolve_position(team, name, dropped_players)
        if position is None:
            self.warnings.append(
                f'{round_label}.{pick["pick"]} {team}: could not resolve a position for {name!r}'
            )
            position = 'UNKNOWN'

        # Re-drafting a player someone else just dropped is normal; a player
        # still on another roster at the same position is not.
        for other in list(self.rosters):
            while (existing := self.find(other, name, position)) is not None:
                self.rosters[other].remove(existing)
                self.warnings.append(
                    f'{round_label}.{pick["pick"]} {team}: {name!r} ({position}) was still on '
                    f'{other}’s roster and has been removed'
                )

        entry: dict = {
            'name': name,
            'nfl_team': nfl_team or self.nfl_teams.get(normalize(name), ''),
            'position': position,
        }
        if is_taxi:
            entry['taxi'] = True
        self.rosters[team].append(entry)

    def run(self, draft: dict) -> None:
        for rnd in draft['rounds']:
            for pick in rnd['picks']:
                self.apply_pick(rnd['round'], pick)


def report(rosters: dict[str, list[dict]], league_config: dict) -> list[str]:
    """Roster-size and slot-limit summary. Returns the violation lines."""
    slots = league_config.get('roster_slots', {})
    taxi_slots = league_config.get('taxi_slots')
    problems: list[str] = []

    for team in sorted(rosters):
        players = rosters[team]
        active = [p for p in players if not p.get('taxi')]
        taxi = [p for p in players if p.get('taxi')]
        counts: dict[str, int] = {}
        for p in active:
            counts[p['position']] = counts.get(p['position'], 0) + 1

        detail = ' '.join(f'{pos}:{counts.get(pos, 0)}/{limit}' for pos, limit in slots.items())
        print(f'  {team:<4} active {len(active):>2}  taxi {len(taxi)}  {detail}')

        for pos, limit in slots.items():
            if counts.get(pos, 0) > limit:
                problems.append(f'{team}: {counts[pos]} active {pos} exceeds the limit of {limit}')
        for pos in counts:
            if pos not in slots:
                problems.append(f'{team}: unexpected active position {pos!r}')
        if taxi_slots is not None and len(taxi) > taxi_slots:
            problems.append(f'{team}: {len(taxi)} taxi players exceeds the limit of {taxi_slots}')
        taxi_positions: dict[str, int] = {}
        for p in taxi:
            taxi_positions[p['position']] = taxi_positions.get(p['position'], 0) + 1
        for pos, count in taxi_positions.items():
            if count > 1:
                problems.append(f'{team}: {count} taxi {pos} players (max 1 per position)')

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description='Apply a recorded draft to rosters.json')
    parser.add_argument('--draft', required=True, help='Draft name as it appears in drafts.json')
    parser.add_argument('--drafts', default='data/drafts.json')
    parser.add_argument('--rosters', default='data/rosters.json')
    parser.add_argument('--config', default='data/league_config.json')
    parser.add_argument('--dry-run', action='store_true', help='Report without writing')
    args = parser.parse_args()

    drafts_path = REPO_ROOT / args.drafts
    rosters_path = REPO_ROOT / args.rosters
    config = json.loads((REPO_ROOT / args.config).read_text())

    drafts = json.loads(drafts_path.read_text())
    matches = [d for d in drafts['drafts'] if d['name'] == args.draft]
    if not matches:
        print(f'Error: no draft named {args.draft!r} in {drafts_path}')
        return 1
    draft = matches[0]

    rosters = json.loads(rosters_path.read_text())
    season = draft.get('year') or config.get('current_season')

    print(f'Applying {draft["name"]} ({sum(len(r["picks"]) for r in draft["rounds"])} picks)...')
    applier = DraftApplier(rosters, int(season))
    applier.run(draft)

    print('\nRosters after the draft:')
    problems = report(rosters, config)

    if applier.corrections:
        print(
            f'\nName corrections applied ({len(applier.corrections)}) '
            '— fix these in the workbook too:'
        )
        for correction in applier.corrections:
            print(f'  {correction}')

    if applier.warnings:
        print(f'\nWarnings ({len(applier.warnings)}):')
        for warning in applier.warnings:
            print(f'  {warning}')

    if problems:
        print(f'\nRoster violations ({len(problems)}):')
        for problem in problems:
            print(f'  {problem}')

    if args.dry_run:
        print('\nDry run — rosters.json not written.')
        return 0

    # Match how api/transaction.py writes rosters.json, so the next roster move
    # through the API doesn't reformat the whole file.
    rosters_path.write_text(json.dumps(rosters, separators=(',', ':')))
    print(f'\nWrote {rosters_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
