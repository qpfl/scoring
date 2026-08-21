"""Generate Hall of Fame statistics from all season data."""

import argparse
import copy
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from qpfl import name_battles
from qpfl.constants import DATA_DIR as SOURCE_DATA_DIR
from qpfl.constants import SEASONS_DIR, SHARED_DIR, WEB_DATA_DIR, WEB_DIR

# Alias for backwards compatibility
DATA_DIR = WEB_DATA_DIR

# Owner code to display name mapping (base names without Connor Bowl consideration)
_BASE_OWNER_NAMES = {
    'GSA': 'Griff',
    'CGK': 'Kaminska',
    'CWR': 'Reardon',
    'AYP': 'Arnav',
    'JRW': 'Joe W.',
    'WJK': 'Bill',
    'SLS': 'Stephen',
    'RCP': 'Ryan P.',
    'RPA': 'Ryan A.',
    'MPA': 'Miles',
    'S/T': 'Spencer Yoder & Tim Grazier',
    'J/J': 'Joe Kuhl & Censored Ward',
    'AST': 'Anagh',
    'TJG': 'Tim',
    'SRY': 'Spencer',
    'JDK': 'Joe K.',
    'JTR': 'Jack Reardon',
    # Combined codes - map to primary owner
    'CGK/SRY': 'Kaminska',
    'CWR/SLS': 'Reardon',
}

# Initialize OWNER_NAMES - will be updated with Connor Bowl holder
OWNER_NAMES = _BASE_OWNER_NAMES.copy()
_SEASON_COOWNER_NAMES: dict[tuple[int, str], str] = {}


def get_all_connor_matchups(all_seasons: list[dict]) -> list[tuple]:
    """Get all CGK vs CWR matchups across all seasons.

    Returns list of (season, week, winner_abbrev) tuples.
    """
    connor_matchups = []

    for season_data in all_seasons:
        season = season_data.get('season', 0)
        weeks = season_data.get('weeks', [])

        for week_data in weeks:
            week_num = week_data.get('week', 0)
            matchups = week_data.get('matchups', [])

            for matchup in matchups:
                t1 = matchup.get('team1', {})
                t2 = matchup.get('team2', {})

                if isinstance(t1, str) or isinstance(t2, str):
                    continue

                t1_abbrev = t1.get('abbrev', '')
                t2_abbrev = t2.get('abbrev', '')

                # Check if this is a CGK vs CWR matchup
                if {t1_abbrev, t2_abbrev} == {'CGK', 'CWR'}:
                    s1 = get_team_score(t1)
                    s2 = get_team_score(t2)

                    if s1 is None or s2 is None or s1 == 0 or s2 == 0:
                        continue

                    if s1 > s2:
                        winner = t1_abbrev
                    elif s2 > s1:
                        winner = t2_abbrev
                    else:
                        continue  # Tie, no winner

                    connor_matchups.append((season, week_num, winner))

    return connor_matchups


def get_connor_bowl_holder_at_time(
    connor_matchups: list[tuple], as_of_season: int, as_of_week: int = 99
) -> str | None:
    """Determine who held the Connor Bowl at a specific point in time.

    Args:
        connor_matchups: List of (season, week, winner) tuples
        as_of_season: The season to check
        as_of_week: The week to check (defaults to end of season)

    Returns the abbreviation of the Connor Bowl holder (CGK or CWR), or None.
    """
    # Filter to matchups up to the specified point
    valid_matchups = [
        m
        for m in connor_matchups
        if m[0] < as_of_season or (m[0] == as_of_season and m[1] <= as_of_week)
    ]

    if not valid_matchups:
        return None

    # Sort by season (desc) then week (desc) to get most recent
    valid_matchups.sort(key=lambda x: (x[0], x[1]), reverse=True)

    return valid_matchups[0][2]


def get_connor_bowl_holder(all_seasons: list[dict]) -> str | None:
    """Determine who CURRENTLY holds the Connor Bowl."""
    connor_matchups = get_all_connor_matchups(all_seasons)
    if not connor_matchups:
        return None

    # Sort by season (desc) then week (desc) to get most recent
    connor_matchups.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return connor_matchups[0][2]


def get_connor_names(holder: str | None) -> tuple[str, str]:
    """Get the display names for CGK and CWR based on who holds the Connor Bowl.

    Returns (cgk_name, cwr_name) tuple.
    """
    if holder == 'CGK':
        return ('Connor Kaminska', 'Redacted Reardon')
    elif holder == 'CWR':
        return ('Redacted Kaminska', 'Connor Reardon')
    else:
        return ('Kaminska', 'Reardon')


def get_connor_name_for_abbrev(abbrev: str, holder: str | None) -> str:
    """Get the display name for a specific abbrev based on Connor Bowl holder."""
    cgk_name, cwr_name = get_connor_names(holder)
    if abbrev == 'CGK':
        return cgk_name
    elif abbrev == 'CWR':
        return cwr_name
    return abbrev


def add_season_coowner(name: str, abbrev: str, season: int) -> str:
    """Add co-owners to full Hall of Fame labels from their effective season."""
    season_name = _SEASON_COOWNER_NAMES.get((season, abbrev))
    if season_name:
        return season_name
    if abbrev == 'CWR' and season >= 2026 and 'Jack Reardon' not in name:
        return f'{name} & Jack Reardon'
    return name


def update_season_coowner_names(all_seasons: list[dict]) -> None:
    """Resolve canonical co-owner labels, including point-in-time name battles."""
    global _SEASON_COOWNER_NAMES
    _SEASON_COOWNER_NAMES = {}
    seasons_weeks = {
        season_data['season']: season_data.get('weeks', []) for season_data in all_seasons
    }
    battles = name_battles.load_config(SOURCE_DATA_DIR / 'name_battles.json')

    for season in seasons_weeks:
        _SEASON_COOWNER_NAMES[(season, 'S/T')] = 'Spencer Yoder & Tim Grazier'
        holders = {
            battle.id: name_battles.holder_at(battle, seasons_weeks, season, 100)
            for battle in battles
        }
        _SEASON_COOWNER_NAMES[(season, 'J/J')] = name_battles.apply_all(
            'Joe Kuhl & Censored Ward', battles, holders
        )


def normalize_coowners_in_text(text: str, season: int) -> str:
    """Expand legacy slash-style co-owner labels in generated Hall of Fame text."""
    spencer_tim = add_season_coowner('', 'S/T', season)
    text = text.replace('Spencer/Tim', spencer_tim).replace('Tim/Spencer', spencer_tim)
    joe_label = add_season_coowner('', 'J/J', season)
    for legacy_label in ('Joe/Joe', 'Joe Kuhl/Censored Ward', 'Joe Censored/Censored Ward'):
        text = text.replace(legacy_label, joe_label)
    return text


def update_owner_names_for_connor_bowl(all_seasons: list[dict]):
    """Update OWNER_NAMES to reflect who CURRENTLY holds the Connor Bowl."""
    global OWNER_NAMES
    OWNER_NAMES = _BASE_OWNER_NAMES.copy()

    connor_holder = get_connor_bowl_holder(all_seasons)
    cgk_name, cwr_name = get_connor_names(connor_holder)

    OWNER_NAMES['CGK'] = cgk_name
    OWNER_NAMES['CWR'] = cwr_name


def _normalize_standings(data: dict | list) -> dict:
    if isinstance(data, dict):
        return data
    return {'standings': data}


def calculate_completed_standings(weeks: list[dict], season: int) -> dict:
    """Build owner-stat inputs from completed regular-season matchup data."""
    standings: dict[str, dict] = {}
    regular_season_weeks = 14 if season <= 2021 else 15

    def row_for(team: dict) -> dict:
        abbrev = team.get('abbrev', '')
        return standings.setdefault(
            abbrev,
            {
                'abbrev': abbrev,
                'wins': 0,
                'losses': 0,
                'ties': 0,
                'points_for': 0.0,
                'points_against': 0.0,
            },
        )

    for week in weeks:
        if week.get('week', 0) > regular_season_weeks or week.get('has_scores') is False:
            continue
        for matchup in week.get('matchups', []):
            t1 = matchup.get('team1', {})
            t2 = matchup.get('team2', {})
            if isinstance(t1, str) or isinstance(t2, str):
                continue
            s1 = t1.get('total_score')
            s2 = t2.get('total_score')
            if s1 is None or s2 is None:
                continue

            r1 = row_for(t1)
            r2 = row_for(t2)
            r1['points_for'] += s1
            r1['points_against'] += s2
            r2['points_for'] += s2
            r2['points_against'] += s1
            if s1 > s2:
                r1['wins'] += 1
                r2['losses'] += 1
            elif s2 > s1:
                r2['wins'] += 1
                r1['losses'] += 1
            else:
                r1['ties'] += 1
                r2['ties'] += 1

    return {'standings': list(standings.values())}


def load_season_data(
    season: int,
    current_season: int | None = None,
    completed_through: int | None = None,
) -> dict:
    """Load a season, excluding unfinished current-season weeks from HOF inputs."""
    season_dir = SEASONS_DIR / str(season)
    weeks_dir = season_dir / 'weeks'

    weeks = []
    is_current = current_season is not None and season == current_season

    # Split week files are written directly by the scorer, before data.json is
    # exported, so they are the freshest source for the live season.
    if weeks_dir.exists():
        for week_file in sorted(
            weeks_dir.glob('week_*.json'), key=lambda path: int(path.stem.split('_')[1])
        ):
            with open(week_file) as f:
                weeks.append(json.load(f))

    if is_current and not weeks:
        data_json_path = WEB_DIR / 'data.json'
        if data_json_path.exists():
            with open(data_json_path) as f:
                data_json = json.load(f)
            if data_json.get('season') == season:
                weeks = data_json.get('weeks', [])

    official_standings: dict = {'standings': []}
    standings_file = season_dir / 'standings.json'
    if standings_file.exists():
        with open(standings_file) as f:
            official_standings = _normalize_standings(json.load(f))

    regular_season_weeks = 14 if season <= 2021 else 15
    if is_current and completed_through is not None:
        weeks = [
            week
            for week in weeks
            if isinstance(week.get('week'), int) and week['week'] <= completed_through
        ]
        standings = calculate_completed_standings(weeks, season)
        regular_season_complete = completed_through >= regular_season_weeks
    else:
        standings = official_standings
        regular_season_complete = True

    return {
        'weeks': weeks,
        'standings': standings,
        'award_standings': official_standings,
        'regular_season_complete': regular_season_complete,
        'season': season,
    }


def get_week_name(week_num: int, season: int) -> str:
    """Get display name for a week."""
    if season <= 2021:
        # 8-team: weeks 15-16 are playoffs
        if week_num == 15:
            return 'Semi-Finals'
        elif week_num == 16:
            return 'Championship Week'
    else:
        # 10-team: weeks 16-17 are playoffs
        if week_num == 16:
            return 'Semi-Finals'
        elif week_num == 17:
            return 'Championship Week'
    return f'Week {week_num}'


def clean_team_name(name: str) -> str:
    """Remove seeding prefixes like '(1) ' or '3: ' from team names."""
    import re

    # Remove patterns like "(1) ", "(2) ", etc.
    name = re.sub(r'^\(\d+\)\s*', '', name)
    # Remove patterns like "1: ", "2: ", etc.
    name = re.sub(r'^\d+:\s*', '', name)
    # Remove leading/trailing asterisks
    name = name.strip('*').strip()
    return name


def get_team_score(team: dict) -> int | float | None:
    """Return a recorded team score, preserving a legitimate zero."""
    score = team.get('total_score')
    if score is None:
        score = team.get('score')
    return score if isinstance(score, (int, float)) else None


def calculate_player_records(all_seasons: list[dict]) -> dict:
    """Calculate player-related records."""

    # Track records
    most_points = []  # (points, player_name, team_abbrev, position, week, season)
    most_points_non_qb = []
    least_points_offensive = []
    least_points_kicker = []
    defensive_shame = []  # -6 points

    for season_data in all_seasons:
        season = season_data['season']
        for week in season_data['weeks']:
            week_num = week['week']
            week_name = get_week_name(week_num, season)

            for matchup in week.get('matchups', []):
                for team_key in ['team1', 'team2']:
                    team = matchup[team_key]
                    team_abbrev = team['abbrev']

                    for player in team.get('roster', []):
                        if not player.get('starter', False):
                            continue

                        name = player['name']
                        position = player['position']
                        score = player.get('score')
                        if not isinstance(score, (int, float)):
                            continue
                        nfl_team = player.get('nfl_team', '')

                        record = (score, name, team_abbrev, position, week_name, season, nfl_team)

                        # Most points (all positions)
                        most_points.append(record)

                        # Most points non-QB
                        if position != 'QB':
                            most_points_non_qb.append(record)

                        # Least points offensive (QB, RB, WR, TE)
                        if position in ('QB', 'RB', 'WR', 'TE'):
                            least_points_offensive.append(record)

                        # Least points kicker
                        if position == 'K':
                            least_points_kicker.append(record)

                        # Defensive shame (-6 points)
                        if position in ('D/ST', 'DEF') and score == -6:
                            defensive_shame.append(record)

    # Sort and get top/bottom records
    most_points.sort(key=lambda x: x[0], reverse=True)
    most_points_non_qb.sort(key=lambda x: x[0], reverse=True)
    least_points_offensive.sort(key=lambda x: x[0])
    least_points_kicker.sort(key=lambda x: x[0])

    def format_player_record(r, include_position=False):
        score, name, team_abbrev, position, week_name, season, nfl_team = r
        if include_position:
            return f'{position} {name} ({team_abbrev}) - {score:.0f} ({week_name}, {season})'
        return f'{name} ({team_abbrev}) - {score:.0f} ({week_name}, {season})'

    def format_defense_record(r):
        score, name, team_abbrev, position, week_name, season, nfl_team = r
        return f'{name} ({team_abbrev}) - {score:.0f} ({week_name}, {season})'

    return {
        'most_points': [format_player_record(r) for r in most_points[:5]],
        'most_points_non_qb': [format_player_record(r) for r in most_points_non_qb[:5]],
        'least_points_offensive': [
            format_player_record(r, True) for r in least_points_offensive[:5]
        ],
        'least_points_kicker': [format_player_record(r, True) for r in least_points_kicker[:5]],
        'defensive_shame': [format_defense_record(r) for r in defensive_shame],
    }


def clean_player_name(value: str) -> str:
    """Remove roster metadata from a player label while preserving its display name."""
    name = str(value or '').strip().rstrip(',')
    name = re.sub(r'^\s*(?:QB|RB|WR|TE|K|D/ST|DEF|HC|OL)\s+', '', name, flags=re.I)
    name = re.sub(r'\s+\([A-Z]{2,4}\)\s*$', '', name)
    return name.strip()


def canonical_profile_position(position: str | None) -> str:
    """Normalize the two team-unit positions that can share the same display name."""
    value = str(position or '').upper()
    if value == 'DEF':
        return 'D/ST'
    return value


def player_identity_key(value: str, position: str | None = None) -> str:
    """Return a suffix-insensitive key used to join historical player labels."""
    name = clean_player_name(value).replace('’', "'")
    name = re.sub(r'\s+(?:Sr\.?|Jr\.?|II|III|IV|V)$', '', name, flags=re.I)
    key = re.sub(r'[^a-z0-9]+', ' ', name.casefold()).strip()
    profile_position = canonical_profile_position(position)
    if key and profile_position in {'D/ST', 'OL'}:
        return f'{key}::{profile_position.lower()}'
    return key


def _resolve_player_key(
    value: str,
    profiles: dict[str, dict],
    position: str | None = None,
) -> str:
    """Match abbreviated draft labels such as ``P. Mahomes`` when unambiguous."""
    key = player_identity_key(value, position)
    if key in profiles:
        return key

    base_key = player_identity_key(value)
    exact_name_matches = [
        candidate
        for candidate, profile in profiles.items()
        if player_identity_key(profile.get('name') or candidate.split('::', 1)[0]) == base_key
        and (
            not position
            or canonical_profile_position(profile.get('current_position'))
            == canonical_profile_position(position)
        )
    ]
    if len(exact_name_matches) == 1:
        return exact_name_matches[0]

    parts = base_key.split()
    if len(parts) < 2:
        return base_key
    first, last = parts[0], parts[-1]
    if len(first) > 2:
        return key

    matches = []
    for candidate, profile in profiles.items():
        if position and canonical_profile_position(
            profile.get('current_position')
        ) != canonical_profile_position(position):
            continue
        candidate_parts = player_identity_key(
            profile.get('name') or candidate.split('::', 1)[0]
        ).split()
        if len(candidate_parts) < 2 or candidate_parts[-1] != last:
            continue
        leading_initials = ''.join(candidate_parts[:-1])
        candidate_first = (
            leading_initials
            if all(len(part) == 1 for part in candidate_parts[:-1])
            else candidate_parts[0]
        )
        if (len(first) == 2 and candidate_first == first) or (
            len(first) == 1 and candidate_first.startswith(first)
        ):
            matches.append(candidate)
    return matches[0] if len(matches) == 1 else base_key


def load_player_birth_dates(existing_profiles: dict | None = None) -> dict[str, str]:
    """Load NFL birth dates, preserving previously exported values on lookup failure."""
    birth_dates = {
        profile.get('profile_key', player_identity_key(profile.get('name', ''))): profile[
            'birth_date'
        ]
        for profile in (existing_profiles or {}).values()
        if profile.get('birth_date')
    }

    try:
        import nflreadpy as nfl

        players = nfl.load_players()
        if 'display_name' not in players.columns or 'birth_date' not in players.columns:
            return birth_dates
        for row in players.select(['display_name', 'birth_date']).iter_rows(named=True):
            key = player_identity_key(row.get('display_name', ''))
            birth_date = row.get('birth_date')
            if key and birth_date:
                birth_dates[key] = str(birth_date)
    except Exception as error:  # pragma: no cover - depends on live nflverse data
        print(f'  Could not refresh player birth dates: {error}')

    return birth_dates


def calculate_player_career_stats(
    all_seasons: list[dict],
    drafts: list[dict] | None = None,
    current_rosters: dict | None = None,
    award_entries: list[str] | None = None,
    player_birth_dates: dict[str, str] | None = None,
) -> dict[str, dict]:
    """Aggregate a compact, canonical player index for career profile views."""
    profiles: dict[str, dict] = {}

    def ensure_profile(
        name: str,
        *,
        position: str | None = None,
        prefer_display: bool = False,
    ) -> tuple[str, dict] | None:
        cleaned = clean_player_name(name)
        key = player_identity_key(cleaned, position)
        if not key or cleaned.upper() == 'PASS':
            return None
        profile = profiles.setdefault(
            key,
            {
                'name': cleaned,
                'profile_key': key,
                'aliases': set(),
                'position_counts': defaultdict(int),
                'nfl_teams': [],
                'current_position': '',
                'current_nfl_team': '',
                'seasons': {},
                'awards': [],
            },
        )
        profile['aliases'].add(cleaned)
        if prefer_display:
            profile['name'] = cleaned
        return key, profile

    for roster in (current_rosters or {}).values():
        if isinstance(roster, list):
            players = roster
        elif isinstance(roster, dict):
            players = [
                *(roster.get('roster', []) or []),
                *(roster.get('taxi_squad', []) or []),
            ]
        else:
            players = []
        for player in players:
            position = player.get('position')
            ensured = ensure_profile(
                player.get('name', ''),
                position=position,
                prefer_display=True,
            )
            if not ensured:
                continue
            _, profile = ensured
            nfl_team = player.get('nfl_team')
            if position:
                profile['position_counts'][position] += 1
                profile['current_position'] = position
            if nfl_team and nfl_team not in profile['nfl_teams']:
                profile['nfl_teams'].append(nfl_team)
            if nfl_team:
                profile['current_nfl_team'] = nfl_team

    for season_data in sorted(all_seasons, key=lambda item: item['season']):
        season = season_data['season']
        seen_appearances: set[tuple[int, int, str]] = set()
        for week in season_data.get('weeks', []):
            if week.get('has_scores') is False:
                continue
            week_num = week.get('week', 0)
            for matchup in week.get('matchups', []):
                for team_key in ('team1', 'team2'):
                    team = matchup.get(team_key)
                    if not isinstance(team, dict):
                        continue
                    owner = team.get('abbrev', '')
                    for player in team.get('roster', []):
                        position = player.get('position', '')
                        ensured = ensure_profile(player.get('name', ''), position=position)
                        if not ensured:
                            continue
                        key, profile = ensured
                        appearance_key = (season, week_num, key)
                        if appearance_key in seen_appearances:
                            continue
                        score = player.get('score')
                        if not isinstance(score, (int, float)):
                            continue
                        seen_appearances.add(appearance_key)

                        nfl_team = player.get('nfl_team', '')
                        if position:
                            profile['position_counts'][position] += 1
                        if nfl_team and nfl_team not in profile['nfl_teams']:
                            profile['nfl_teams'].append(nfl_team)

                        season_stats = profile['seasons'].setdefault(
                            str(season),
                            {
                                'points': 0.0,
                                'games': 0,
                                'starts': 0,
                                'owners': [],
                                'position': position,
                            },
                        )
                        season_stats['points'] += score
                        season_stats['games'] += 1
                        season_stats['starts'] += int(bool(player.get('starter')))
                        if owner and owner not in season_stats['owners']:
                            season_stats['owners'].append(owner)
                        if not season_stats['position'] and position:
                            season_stats['position'] = position

    for draft in drafts or []:
        draft_position = 'OL' if 'OL Expansion Draft' in draft.get('name', '') else None
        for round_data in draft.get('rounds', []):
            for pick in round_data.get('picks', []):
                pick_position = pick.get('position') or draft_position
                raw_name = pick.get('player', '')
                cleaned = clean_player_name(raw_name)
                if not cleaned or cleaned.upper() == 'PASS':
                    continue
                key = _resolve_player_key(cleaned, profiles, pick_position)
                if key not in profiles:
                    same_name_profiles = [
                        profile
                        for profile in profiles.values()
                        if player_identity_key(profile.get('name', ''))
                        == player_identity_key(cleaned)
                    ]
                    if len(same_name_profiles) > 1 and not pick_position:
                        continue
                    ensured = ensure_profile(cleaned, position=pick_position)
                    if not ensured:
                        continue
                    key, _ = ensured
                profiles[key]['aliases'].add(cleaned)

    totals_by_season_position: dict[tuple[str, str], list[tuple[str, float]]] = defaultdict(list)
    for key, profile in profiles.items():
        for season, stats in profile['seasons'].items():
            position = stats.get('position', '')
            if position:
                totals_by_season_position[(season, position)].append((key, stats['points']))

    for (season, _position), totals in totals_by_season_position.items():
        totals.sort(key=lambda item: (-item[1], profiles[item[0]]['name']))
        for rank, (key, _points) in enumerate(totals, 1):
            profiles[key]['seasons'][season]['position_rank'] = rank

    for entry in award_entries or []:
        match = re.match(r'\s*(\d{4})\s*-\s*(.+?)\s*\([^)]*\)\s*$', entry)
        if not match:
            continue
        year, raw_name = match.groups()
        key = _resolve_player_key(raw_name, profiles)
        if key in profiles:
            profiles[key]['awards'].append({'year': int(year), 'title': 'QPFL MVP'})

    output: dict[str, dict] = {}
    for profile in profiles.values():
        seasons = profile['seasons']
        position = max(
            profile['position_counts'],
            key=profile['position_counts'].get,
            default='',
        )
        output_profile = {
            'name': profile['name'],
            'profile_key': profile['profile_key'],
            'aliases': sorted(profile['aliases']),
            'position': profile['current_position'] or position,
            'nfl_team': profile['current_nfl_team']
            or (profile['nfl_teams'][-1] if profile['nfl_teams'] else ''),
            'total_points': round(sum(s['points'] for s in seasons.values()), 2),
            'games': sum(s['games'] for s in seasons.values()),
            'starts': sum(s['starts'] for s in seasons.values()),
            'seasons': {
                season: {
                    **stats,
                    'points': round(stats['points'], 2),
                }
                for season, stats in sorted(seasons.items(), reverse=True)
            },
            'awards': sorted(profile['awards'], key=lambda award: award['year'], reverse=True),
        }
        birth_date = (player_birth_dates or {}).get(profile['profile_key'])
        if birth_date:
            output_profile['birth_date'] = birth_date
        output_key = profile['name']
        if canonical_profile_position(position) in {'D/ST', 'OL'}:
            output_key = f'{output_key} ({canonical_profile_position(position)})'
        output[output_key] = output_profile
    return dict(sorted(output.items()))


def calculate_team_records(all_seasons: list[dict]) -> dict:
    """Calculate team-related records."""

    # Track records
    most_points = []  # (points, team_name, team_abbrev, week, season)
    least_points = []
    margins = []  # (margin, winner_name, winner_abbrev, loser_name, loser_abbrev, week, season)

    for season_data in all_seasons:
        season = season_data['season']
        for week in season_data['weeks']:
            week_num = week['week']
            week_name = get_week_name(week_num, season)

            for matchup in week.get('matchups', []):
                t1 = matchup['team1']
                t2 = matchup['team2']

                s1 = get_team_score(t1)
                s2 = get_team_score(t2)
                if s1 is None or s2 is None:
                    continue

                t1_name = clean_team_name(t1['name'])
                t2_name = clean_team_name(t2['name'])

                if s1 > 0:
                    most_points.append((s1, t1_name, t1['abbrev'], week_name, season))
                    least_points.append((s1, t1_name, t1['abbrev'], week_name, season))

                if s2 > 0:
                    most_points.append((s2, t2_name, t2['abbrev'], week_name, season))
                    least_points.append((s2, t2_name, t2['abbrev'], week_name, season))

                # Margin of victory
                if s1 > 0 and s2 > 0:
                    margin = abs(s1 - s2)
                    if s1 > s2:
                        margins.append(
                            (
                                margin,
                                t1_name,
                                t1['abbrev'],
                                t2_name,
                                t2['abbrev'],
                                week_name,
                                season,
                            )
                        )
                    else:
                        margins.append(
                            (
                                margin,
                                t2_name,
                                t2['abbrev'],
                                t1_name,
                                t1['abbrev'],
                                week_name,
                                season,
                            )
                        )

    most_points.sort(key=lambda x: x[0], reverse=True)
    least_points.sort(key=lambda x: x[0])
    margins.sort(key=lambda x: x[0], reverse=True)

    def format_team_record(r):
        score, name, abbrev, week_name, season = r
        return f'{name} ({abbrev}) - {score:.0f} ({week_name}, {season})'

    def format_margin_record(r):
        margin, winner_name, winner_abbrev, loser_name, loser_abbrev, week_name, season = r
        return f'{winner_name} ({winner_abbrev}) over {loser_name} ({loser_abbrev}) - {margin:.0f} ({week_name}, {season})'

    return {
        'most_points': [format_team_record(r) for r in most_points[:5]],
        'least_points': [format_team_record(r) for r in least_points[:5]],
        'largest_margin': [format_margin_record(r) for r in margins[:5]],
    }


# Combined team codes map to their individual owner codes
COMBINED_TEAM_OWNERS = {
    'S/T': ['SRY', 'TJG'],  # Spencer + Tim
    'J/J': ['JRW', 'JDK'],  # Joe Ward + Joe Kuhl
    'CGK/SRY': ['CGK'],  # Kaminska (with Spencer as co-owner, but CGK is primary)
    'CWR/SLS': ['CWR'],  # Reardon (with Stephen as co-owner, but CWR is primary)
}

TEAM_FINISH_PATTERNS = {
    'GSA': ['Griffin', 'Griff'],
    'CGK': ['Kaminska', 'Connor Kaminska', 'Redacted Kaminska', 'CGK/SRY'],
    'CWR': ['Reardon', 'Connor Reardon', 'Jack Reardon', 'Censored Reardon', 'CWR/SLS'],
    'S/T': ['Spencer/Tim', 'Tim/Spencer', 'Spencer Yoder', 'Tim Grazier'],
    'SLS': ['Stephen', 'Schmidt', 'CWR/SLS'],
    'SRY': ['Spencer', 'CGK/SRY'],
    'AYP': ['Arnav'],
    'RPA': ['Ryan Ansel', 'Ryan A'],
    'RCP': ['Ryan P'],
    'WJK': ['Bill', 'Kusner'],
    'MPA': ['Miles'],
    'J/J': ['Joe/Joe', 'Joe Ward', 'Joe Kuhl', 'Joe Censored', 'Censored Ward'],
    'JRW': ['Joe Ward'],
    'JDK': ['Joe Kuhl'],
    'AST': ['Anagh'],
}

COMBINED_TEAM_PRIMARY = {
    'CWR/SLS': 'CWR',
    'CGK/SRY': 'CGK',
    'S/T': 'S/T',
    'J/J': 'J/J',
}

# Current franchise codes whose earlier ownership eras used different codes.
# Team Hall of Fame pages follow the franchise seat through those transfers.
FRANCHISE_LINEAGE = {
    'RPA': {'MPA'},
    'J/J': {'RCP', 'JDK'},
    'AST': {'JRW'},
}


def get_owner_codes(abbrev: str, season: int | None = None) -> list[str]:
    """Get all owner codes for an abbreviation (handles combined teams)."""
    if abbrev == 'CWR' and season is not None and season >= 2026:
        return ['CWR', 'JTR']

    # Check if it's a known combined team
    if abbrev in COMBINED_TEAM_OWNERS:
        return COMBINED_TEAM_OWNERS[abbrev]

    # Handle unknown combined codes
    if '/' in abbrev:
        parts = abbrev.split('/')
        # If both parts are short (like S/T, J/J), it's a combined team
        # but we don't know the mapping, so return as-is
        if all(len(p) <= 2 for p in parts):
            return [abbrev]
        # Otherwise return the first part (primary owner)
        return [parts[0]]

    return [abbrev]


def calculate_owner_stats(all_seasons: list[dict], finishes_by_year: list[dict]) -> list[dict]:
    """Calculate owner statistics across all seasons."""

    # Map owner names (from finishes) to owner codes
    name_to_code = {
        'Griffin Ansel': 'GSA',
        'Griff': 'GSA',
        'Connor Kaminska': 'CGK',
        'Kaminska': 'CGK',
        'Redacted Kaminska': 'CGK',
        'Connor Reardon': 'CWR',
        'Reardon': 'CWR',
        'Redacted Reardon': 'CWR',
        'Jack Reardon': 'JTR',
        'Arnav Patel': 'AYP',
        'Arnav': 'AYP',
        'Joe Ward': 'JRW',
        'Joe W.': 'JRW',
        'Bill': 'WJK',
        'Bill Kuhl': 'WJK',
        'Stephen Schmidt': 'SLS',
        'Stephen': 'SLS',
        'Ryan Ansel': 'RPA',
        'Ryan': 'RPA',
        'Ryan P.': 'RCP',
        'Bocki': 'RCP',
        'Miles Agus': 'MPA',
        'Miles': 'MPA',
        'Spencer/Tim': 'S/T',
        'Tim/Spencer': 'S/T',
        'Spencer Yoder': 'SRY',
        'Tim Grazier': 'TJG',
        'Joe/Joe': 'J/J',
        'Anagh': 'AST',
        'Tim': 'TJG',
        'Spencer': 'SRY',
        'Joe Kuhl': 'JDK',
        'Joe K.': 'JDK',
        'Joe Censored': 'JDK',
        'Censored Ward': 'JRW',
    }

    # Track stats by owner code
    owner_stats = defaultdict(
        lambda: {
            'seasons': set(),
            'wins': 0,
            'losses': 0,
            'ties': 0,
            'reg_season_wins': 0,
            'reg_season_losses': 0,
            'reg_season_ties': 0,
            'playoff_wins': 0,
            'playoff_losses': 0,
            'playoff_berths': 0,
            'sewer_series_berths': 0,
            'third_place': 0,
            'second_place': 0,
            'championships': 0,
            'last_place': 0,
            'points_for': 0,
            'points_against': 0,
        }
    )

    for season_data in all_seasons:
        season = season_data['season']
        standings_data = season_data.get('standings', {})
        standings = standings_data.get('standings', [])

        for team in standings:
            abbrev = team.get('abbrev', '')
            owner_codes = get_owner_codes(abbrev, season)
            for owner_code in owner_codes:
                stats = owner_stats[owner_code]
                stats['seasons'].add(season)
                stats['wins'] += team.get('wins', 0)
                stats['losses'] += team.get('losses', 0)
                stats['ties'] += team.get('ties', 0)
                stats['points_for'] += team.get('points_for', 0)
                stats['points_against'] += team.get('points_against', 0)

        if season_data.get('regular_season_complete', True):
            award_data = season_data.get('award_standings', standings_data)
            award_standings = award_data.get('standings', [])
            num_teams = 8 if season <= 2021 else 10
            playoff_cutoff = 4
            for rank, team in enumerate(award_standings, 1):
                owner_codes = get_owner_codes(team.get('abbrev', ''), season)
                for owner_code in owner_codes:
                    stats = owner_stats[owner_code]
                    if rank <= playoff_cutoff:
                        stats['playoff_berths'] += 1
                    if num_teams == 10 and rank > 6 or num_teams == 8 and rank > 4:
                        stats['sewer_series_berths'] += 1
                    if rank == num_teams:
                        stats['last_place'] += 1

    # Parse championship/placement data from finishes_by_year
    for finish in finishes_by_year:
        year = finish.get('year', '')
        if not year.isdigit():
            continue  # Skip non-year entries like "QPFL MVPs"

        results = finish.get('results', [])
        for i, result in enumerate(results):
            if i > 2:  # Only first 3 are 1st, 2nd, 3rd place
                break

            # Parse the owner name from the result
            # Handle formats like "Griffin Ansel", "Spencer/Tim", "Connor Reardon & Stephen Schmidt"
            owner_name = result.strip()

            # Handle "&" for co-3rd place
            names = owner_name.split(' & ') if ' & ' in owner_name else [owner_name]

            for name in names:
                name = name.strip()
                owner_code = name_to_code.get(name)
                if owner_code:
                    # Get all individual owner codes (handles combined teams like S/T -> SRY, TJG)
                    individual_codes = COMBINED_TEAM_OWNERS.get(owner_code, [owner_code])
                    for code in individual_codes:
                        if i == 0:
                            owner_stats[code]['championships'] += 1
                        elif i == 1:
                            owner_stats[code]['second_place'] += 1
                        elif i == 2:
                            owner_stats[code]['third_place'] += 1

    # Process playoff matchups to track playoff wins/losses
    for season_data in all_seasons:
        season = season_data['season']

        # Determine playoff weeks based on season
        playoff_weeks = [15, 16] if season <= 2021 else [16, 17]

        for week in season_data['weeks']:
            week_num = week['week']
            if week_num not in playoff_weeks:
                continue

            for matchup in week.get('matchups', []):
                # Only count playoff matchups (not sewer series, mid bowl, etc.)
                bracket = matchup.get('bracket', '')
                if bracket not in ('playoffs', 'championship', 'consolation_cup'):
                    continue

                t1 = matchup.get('team1', {})
                t2 = matchup.get('team2', {})

                s1 = get_team_score(t1)
                s2 = get_team_score(t2)

                if s1 is None or s2 is None or s1 == 0 or s2 == 0:
                    continue

                t1_codes = get_owner_codes(t1.get('abbrev', ''), season)
                t2_codes = get_owner_codes(t2.get('abbrev', ''), season)

                if s1 > s2:
                    for code in t1_codes:
                        owner_stats[code]['playoff_wins'] += 1
                    for code in t2_codes:
                        owner_stats[code]['playoff_losses'] += 1
                elif s2 > s1:
                    for code in t2_codes:
                        owner_stats[code]['playoff_wins'] += 1
                    for code in t1_codes:
                        owner_stats[code]['playoff_losses'] += 1

    # Copy regular season stats from overall (which comes from standings = reg season only)
    for _owner_code, stats in owner_stats.items():
        stats['reg_season_wins'] = stats['wins']
        stats['reg_season_losses'] = stats['losses']
        stats['reg_season_ties'] = stats['ties']

    # Calculate league averages for Prestige Ranking
    total_reg_season_games = 0
    total_reg_season_wins = 0
    total_playoff_games = 0
    total_playoff_wins = 0

    for _owner_code, stats in owner_stats.items():
        reg_games = stats['reg_season_wins'] + stats['reg_season_losses'] + stats['reg_season_ties']
        playoff_games = stats['playoff_wins'] + stats['playoff_losses']

        total_reg_season_games += reg_games
        total_reg_season_wins += stats['reg_season_wins']
        total_playoff_games += playoff_games
        total_playoff_wins += stats['playoff_wins']

    league_avg_reg_win_pct = (
        total_reg_season_wins / total_reg_season_games if total_reg_season_games > 0 else 0.5
    )
    league_avg_playoff_win_pct = (
        total_playoff_wins / total_playoff_games if total_playoff_games > 0 else 0.5
    )

    # Convert to list format
    result = []
    for owner_code, stats in owner_stats.items():
        if not stats['seasons']:
            continue

        total_games = stats['wins'] + stats['losses'] + stats['ties']
        win_pct = stats['wins'] / total_games * 100 if total_games > 0 else 0

        record = f'{stats["wins"]}-{stats["losses"]}'
        if stats['ties'] > 0:
            record += f'-{stats["ties"]}'

        # Calculate Prestige Ranking
        # Formula: (1+(Championships x 0.2)) x { ((Reg. Szn Games Played x Reg. Szn. Win %) / (League Avg. Reg. Szn. Win %) x 0.1) +
        #          ((Playoff Games Played x Playoff Win %) / (League Avg. Playoff Win %) x 0.2) } / # of Szn. in League
        num_seasons = len(stats['seasons'])
        championships = stats['championships']

        reg_games = stats['reg_season_wins'] + stats['reg_season_losses'] + stats['reg_season_ties']
        reg_win_pct = stats['reg_season_wins'] / reg_games if reg_games > 0 else 0

        playoff_games = stats['playoff_wins'] + stats['playoff_losses']
        playoff_win_pct = stats['playoff_wins'] / playoff_games if playoff_games > 0 else 0

        # Avoid division by zero
        reg_component = (
            (reg_games * reg_win_pct) / league_avg_reg_win_pct * 0.1
            if league_avg_reg_win_pct > 0
            else 0
        )
        playoff_component = (
            (playoff_games * playoff_win_pct) / league_avg_playoff_win_pct * 0.2
            if league_avg_playoff_win_pct > 0
            else 0
        )

        prestige = (
            (1 + (championships * 0.2)) * (reg_component + playoff_component) / num_seasons
            if num_seasons > 0
            else 0
        )

        # Playoff record string
        playoff_record = f'{stats["playoff_wins"]}-{stats["playoff_losses"]}'
        playoff_win_pct_display = (
            (stats['playoff_wins'] / playoff_games * 100) if playoff_games > 0 else 0
        )

        result.append(
            {
                'Owner': OWNER_NAMES.get(owner_code, owner_code),
                'Code': owner_code,
                'Seasons': str(num_seasons),
                'Record': record,
                'Win%': f'{win_pct:.1f}%',
                'Points For': f'{stats["points_for"]:.0f}',
                'Playoff Berths': str(stats['playoff_berths']),
                'Playoff Record': playoff_record,
                'Playoff Win%': f'{playoff_win_pct_display:.1f}%',
                '3rd Place': str(stats['third_place']),
                '2nd Place': str(stats['second_place']),
                'Rings': str(stats['championships']),
                'Sewer Series Berths': str(stats['sewer_series_berths']),
                'Last Place': str(stats['last_place']),
                'Prestige': f'{prestige:.2f}',
            }
        )

    # Combine Spencer (SRY) and Tim (TJG) into one co-owner row for display.
    # Find and merge their stats
    spencer_data = next((r for r in result if r['Code'] == 'SRY'), None)
    tim_data = next((r for r in result if r['Code'] == 'TJG'), None)

    if spencer_data and tim_data:
        # They share S/T stats, so we just need one combined entry
        # Use Spencer's data as base (they should be identical for shared seasons)
        result = [r for r in result if r['Code'] not in ('SRY', 'TJG')]
        spencer_data['Owner'] = 'Spencer Yoder & Tim Grazier'
        spencer_data['Code'] = 'S/T'
        result.append(spencer_data)

    # Sort by Win% (descending)
    result.sort(key=lambda x: float(x['Win%'].rstrip('%')), reverse=True)

    return result


def calculate_rivalry_records(all_seasons: list[dict]) -> dict:
    """Calculate head-to-head records between all teams."""

    # Structure: {team1: {team2: {wins: 0, losses: 0, ties: 0, pf: 0, pa: 0}}}
    h2h = defaultdict(
        lambda: defaultdict(lambda: {'wins': 0, 'losses': 0, 'ties': 0, 'pf': 0, 'pa': 0})
    )

    # All teams that have played
    all_teams = set()

    for season_data in all_seasons:
        for week in season_data.get('weeks', []):
            for matchup in week.get('matchups', []):
                t1_abbrev = matchup['team1']['abbrev']
                t2_abbrev = matchup['team2']['abbrev']
                s1 = get_team_score(matchup['team1'])
                s2 = get_team_score(matchup['team2'])

                # Skip if no scores
                if s1 is None or s2 is None:
                    continue

                all_teams.add(t1_abbrev)
                all_teams.add(t2_abbrev)

                # Update team1's record vs team2
                h2h[t1_abbrev][t2_abbrev]['pf'] += s1
                h2h[t1_abbrev][t2_abbrev]['pa'] += s2

                # Update team2's record vs team1
                h2h[t2_abbrev][t1_abbrev]['pf'] += s2
                h2h[t2_abbrev][t1_abbrev]['pa'] += s1

                if s1 > s2:
                    h2h[t1_abbrev][t2_abbrev]['wins'] += 1
                    h2h[t2_abbrev][t1_abbrev]['losses'] += 1
                elif s2 > s1:
                    h2h[t1_abbrev][t2_abbrev]['losses'] += 1
                    h2h[t2_abbrev][t1_abbrev]['wins'] += 1
                else:
                    h2h[t1_abbrev][t2_abbrev]['ties'] += 1
                    h2h[t2_abbrev][t1_abbrev]['ties'] += 1

    # Convert to serializable format
    # Create a matrix-style output for easy display
    teams = sorted(all_teams)

    # Build rivalry records list
    rivalry_records = []
    for t1 in teams:
        for t2 in teams:
            if t1 >= t2:  # Only include one direction (and skip self)
                continue

            record = h2h[t1][t2]
            if record['wins'] + record['losses'] + record['ties'] == 0:
                continue  # No matchups between these teams

            # Determine who has the better record
            if record['wins'] > record['losses']:
                leader = t1
            elif record['losses'] > record['wins']:
                leader = t2
            else:
                leader = None

            rivalry_records.append(
                {
                    'team1': t1,
                    'team2': t2,
                    'team1_wins': record['wins'],
                    'team2_wins': record['losses'],
                    'ties': record['ties'],
                    'team1_pf': round(record['pf'], 1),
                    'team2_pf': round(record['pa'], 1),
                    'games': record['wins'] + record['losses'] + record['ties'],
                    'leader': leader,
                }
            )

    # Sort alphabetically by team1, then team2
    rivalry_records.sort(key=lambda x: (x['team1'], x['team2']))

    return {
        'teams': teams,
        'records': rivalry_records,
        'h2h_matrix': {t1: {t2: h2h[t1][t2] for t2 in teams if t2 != t1} for t1 in teams},
    }


def _matches_franchise(team_abbrev: str, franchise_abbrev: str) -> bool:
    franchise_codes = {franchise_abbrev, *FRANCHISE_LINEAGE.get(franchise_abbrev, set())}
    if team_abbrev in franchise_codes:
        return True
    if '/' not in team_abbrev:
        return False
    return any(code in team_abbrev.split('/') for code in franchise_codes)


def _matches_finish(text: str, franchise_abbrev: str) -> bool:
    lowered = text.casefold()
    return any(
        pattern.casefold() in lowered for pattern in TEAM_FINISH_PATTERNS.get(franchise_abbrev, [])
    )


def _normalize_opponent(team_abbrev: str) -> str:
    for franchise_abbrev, historical_codes in FRANCHISE_LINEAGE.items():
        if team_abbrev in historical_codes:
            return franchise_abbrev
    if team_abbrev in COMBINED_TEAM_PRIMARY:
        return COMBINED_TEAM_PRIMARY[team_abbrev]
    return team_abbrev.split('/')[0] if '/' in team_abbrev else team_abbrev


def _owner_label_for_team(team_abbrev: str, season: int) -> str:
    if team_abbrev == 'CGK/SRY':
        return 'Connor Kaminska & Spencer Yoder'
    if team_abbrev == 'CWR/SLS':
        return 'Connor Reardon & Stephen Schmidt'
    if team_abbrev in ('S/T', 'J/J'):
        return add_season_coowner('', team_abbrev, season) or _BASE_OWNER_NAMES[team_abbrev]

    base_name = OWNER_NAMES.get(team_abbrev, _BASE_OWNER_NAMES.get(team_abbrev, team_abbrev))
    return add_season_coowner(base_name, team_abbrev, season)


def _summarize_owner_eras(seasons: list[dict]) -> list[dict]:
    owners = defaultdict(
        lambda: {
            'seasons': [],
            'wins': 0,
            'losses': 0,
            'ties': 0,
            'totalPoints': 0,
            'gamesPlayed': 0,
            'rings': 0,
        }
    )

    for season in seasons:
        owner = season.get('owner') or 'Unknown'
        stats = owners[owner]
        stats['seasons'].append(season['season'])
        stats['wins'] += season['wins']
        stats['losses'] += season['losses']
        stats['ties'] += season['ties']
        stats['totalPoints'] += season['totalPoints']
        stats['gamesPlayed'] += season['gamesPlayed']
        if any(finish.get('type') == 'champion' for finish in season.get('seasonFinishes', [])):
            stats['rings'] += 1

    result = []
    for owner, stats in owners.items():
        games = stats['wins'] + stats['losses'] + stats['ties']
        result.append(
            {
                'owner': owner,
                'seasons': sorted(stats['seasons']),
                'wins': stats['wins'],
                'losses': stats['losses'],
                'ties': stats['ties'],
                'winPct': (stats['wins'] + 0.5 * stats['ties']) / games * 100 if games else 0,
                'totalPoints': stats['totalPoints'],
                'gamesPlayed': stats['gamesPlayed'],
                'ppg': (stats['totalPoints'] / stats['gamesPlayed'] if stats['gamesPlayed'] else 0),
                'rings': stats['rings'],
            }
        )

    return sorted(result, key=lambda row: max(row['seasons']), reverse=True)


def _current_franchise_abbrevs() -> list[str]:
    teams_file = SOURCE_DATA_DIR / 'teams.json'
    if not teams_file.exists():
        return []
    with open(teams_file) as f:
        teams = json.load(f).get('teams', [])
    return [team['abbrev'] for team in teams if team.get('abbrev')]


def _season_finish_badges(
    finishes_by_year: list[dict],
    season: int,
    franchise_abbrev: str,
    standings: list[dict],
    regular_season_complete: bool,
) -> list[dict]:
    badges = []
    year_finish = next(
        (finish for finish in finishes_by_year if str(season) in str(finish.get('year', ''))),
        None,
    )
    results = year_finish.get('results', []) if year_finish else []

    if results and _matches_finish(results[0], franchise_abbrev):
        badges.append({'type': 'champion', 'label': 'Champion'})
    elif len(results) > 1 and _matches_finish(results[1], franchise_abbrev):
        badges.append({'type': 'playoff', 'label': '2nd Place'})
    elif len(results) > 2 and _matches_finish(results[2], franchise_abbrev):
        badges.append({'type': 'playoff', 'label': '3rd Place'})

    for result in results:
        if 'Toilet Bowl' in result and _matches_finish(result, franchise_abbrev):
            badges.append({'type': 'toilet-bowl', 'label': 'Toilet Bowl'})
        elif 'Jambo' in result and _matches_finish(result, franchise_abbrev):
            badges.append({'type': 'jambo', 'label': 'Jamboree'})

    if regular_season_complete and not any(
        badge['type'] in ('champion', 'playoff') for badge in badges
    ):
        standing_index = next(
            (
                index
                for index, row in enumerate(standings)
                if _matches_franchise(row.get('abbrev', ''), franchise_abbrev)
            ),
            None,
        )
        if standing_index is not None:
            standing = standings[standing_index]
            rank = standing.get('rank') or standing_index + 1
            if 4 <= rank <= 10:
                badges.insert(0, {'type': 'position', 'label': f'{rank}th Place'})

    return badges


def _franchise_rivalries(franchise_abbrev: str, rivalry_records: dict) -> list[dict]:
    aggregated = {}
    for record in rivalry_records.get('records', []):
        opponent = None
        wins = losses = ties = 0
        if _matches_franchise(record['team1'], franchise_abbrev):
            opponent = record['team2']
            wins = record['team1_wins']
            losses = record['team2_wins']
            ties = record.get('ties', 0)
        elif _matches_franchise(record['team2'], franchise_abbrev):
            opponent = record['team1']
            wins = record['team2_wins']
            losses = record['team1_wins']
            ties = record.get('ties', 0)

        if not opponent or _matches_franchise(opponent, franchise_abbrev):
            continue
        opponent = _normalize_opponent(opponent)
        row = aggregated.setdefault(
            opponent, {'opponent': opponent, 'wins': 0, 'losses': 0, 'ties': 0}
        )
        row['wins'] += wins
        row['losses'] += losses
        row['ties'] += ties

    return sorted(
        aggregated.values(),
        key=lambda row: (-(row['wins'] + row['losses'] + row['ties']), row['opponent']),
    )


def calculate_team_hall_of_fame(
    all_seasons: list[dict],
    finishes_by_year: list[dict],
    rivalry_records: dict,
    franchise_abbrevs: list[str] | None = None,
) -> dict:
    """Precompute franchise history so the browser never loads every season file."""
    franchise_abbrevs = franchise_abbrevs or _current_franchise_abbrevs()
    result = {}

    for franchise_abbrev in franchise_abbrevs:
        seasons = []
        player_games = []
        scoring_weeks = []

        for season_data in all_seasons:
            season = season_data['season']
            standings = season_data.get('standings', {}).get('standings', [])
            standing = next(
                (
                    row
                    for row in standings
                    if _matches_franchise(row.get('abbrev', ''), franchise_abbrev)
                ),
                None,
            )
            if standing is None:
                continue
            season_team_abbrev = standing.get('abbrev', franchise_abbrev)
            owner_label = _owner_label_for_team(season_team_abbrev, season)

            highest_score = None
            lowest_score = None
            biggest_win = None
            biggest_loss = None
            total_points = 0
            wins = losses = ties = games_played = 0

            for week in season_data.get('weeks', []):
                if week.get('has_scores') is False:
                    continue
                for matchup in week.get('matchups', []):
                    team1 = matchup.get('team1', {})
                    team2 = matchup.get('team2', {})
                    if isinstance(team1, str) or isinstance(team2, str):
                        continue
                    if _matches_franchise(team1.get('abbrev', ''), franchise_abbrev):
                        team, opponent = team1, team2
                    elif _matches_franchise(team2.get('abbrev', ''), franchise_abbrev):
                        team, opponent = team2, team1
                    else:
                        continue

                    team_score = get_team_score(team)
                    opponent_score = get_team_score(opponent)
                    if team_score is None or opponent_score is None:
                        continue
                    if team_score == 0 and opponent_score == 0:
                        continue

                    week_number = week.get('week', 0)
                    opponent_abbrev = opponent.get('abbrev', '')
                    margin = team_score - opponent_score
                    total_points += team_score
                    games_played += 1
                    scoring_weeks.append(
                        {
                            'score': team_score,
                            'week': week_number,
                            'season': season,
                            'opponent': opponent_abbrev,
                            'result': 'W' if margin > 0 else ('L' if margin < 0 else 'T'),
                        }
                    )

                    if margin > 0:
                        wins += 1
                    elif margin < 0:
                        losses += 1
                    else:
                        ties += 1

                    score_context = {
                        'score': team_score,
                        'week': week_number,
                        'opponent': opponent_abbrev,
                    }
                    if highest_score is None or team_score > highest_score['score']:
                        highest_score = score_context
                    if team_score > 0 and (
                        lowest_score is None or team_score < lowest_score['score']
                    ):
                        lowest_score = score_context

                    margin_context = {
                        'margin': abs(margin),
                        'week': week_number,
                        'opponent': opponent_abbrev,
                        'score': f'{team_score:.0f}-{opponent_score:.0f}',
                    }
                    if margin > 0 and (biggest_win is None or margin > biggest_win['margin']):
                        biggest_win = margin_context
                    if margin < 0 and (
                        biggest_loss is None or abs(margin) > biggest_loss['margin']
                    ):
                        biggest_loss = margin_context

                    for player in team.get('roster', []):
                        player_score = player.get('score')
                        if not player.get('starter') or not isinstance(player_score, (int, float)):
                            continue
                        if player_score <= 0:
                            continue
                        player_games.append(
                            {
                                'name': player.get('name', ''),
                                'position': player.get('position', ''),
                                'nfl_team': player.get('nfl_team', ''),
                                'score': player_score,
                                'week': week_number,
                                'season': season,
                            }
                        )

            if games_played:
                seasons.append(
                    {
                        'season': season,
                        'owner': owner_label,
                        'wins': wins,
                        'losses': losses,
                        'ties': ties,
                        'totalPoints': total_points,
                        'gamesPlayed': games_played,
                        'ppg': total_points / games_played,
                        'highestScore': highest_score,
                        'lowestScore': lowest_score,
                        'biggestWin': biggest_win,
                        'biggestLoss': biggest_loss,
                        'seasonFinishes': _season_finish_badges(
                            finishes_by_year,
                            season,
                            (
                                season_team_abbrev
                                if season_team_abbrev in TEAM_FINISH_PATTERNS
                                else franchise_abbrev
                            ),
                            standings,
                            season_data.get('regular_season_complete', True),
                        ),
                    }
                )

        seasons.sort(key=lambda row: row['season'], reverse=True)
        player_games.sort(key=lambda row: (row['score'], row['season']), reverse=True)
        scoring_weeks.sort(key=lambda row: (row['score'], row['season']), reverse=True)

        player_totals = {}
        for game in sorted(player_games, key=lambda row: row['season']):
            normalized_name = game['name']
            for suffix in (' II', ' III', ' IV', ' V', ' Jr.', ' Jr', ' Sr.', ' Sr'):
                if normalized_name.casefold().endswith(suffix.casefold()):
                    normalized_name = normalized_name[: -len(suffix)].strip()
                    break
            key = (normalized_name.casefold(), game['position'])
            player = player_totals.setdefault(
                key,
                {
                    'name': game['name'],
                    'position': game['position'],
                    'nfl_team': game['nfl_team'],
                    'totalPoints': 0,
                    'gamesStarted': 0,
                },
            )
            player['totalPoints'] += game['score']
            player['gamesStarted'] += 1
            player['name'] = game['name']
            player['nfl_team'] = game['nfl_team']

        top_players = sorted(
            player_totals.values(),
            key=lambda row: (row['totalPoints'], row['gamesStarted']),
            reverse=True,
        )[:10]
        total_points = sum(row['totalPoints'] for row in seasons)
        games_played = sum(row['gamesPlayed'] for row in seasons)
        biggest_wins = [
            {**row['biggestWin'], 'season': row['season']} for row in seasons if row['biggestWin']
        ]
        biggest_win = max(biggest_wins, key=lambda row: row['margin'], default=None)

        result[franchise_abbrev] = {
            'seasons': seasons,
            'allTime': {
                'wins': sum(row['wins'] for row in seasons),
                'losses': sum(row['losses'] for row in seasons),
                'ties': sum(row['ties'] for row in seasons),
                'totalPoints': total_points,
                'gamesPlayed': games_played,
                'ppg': total_points / games_played if games_played else 0,
                'biggestWin': biggest_win,
            },
            'topPlayersByTotalPoints': top_players,
            'topAllTimeGames': player_games[:10],
            'topAllTimeGamesNonQB': [game for game in player_games if game['position'] != 'QB'][
                :10
            ],
            'topScoringWeeks': scoring_weeks[:10],
            'rivalryRecords': _franchise_rivalries(franchise_abbrev, rivalry_records),
            'ownerStats': _summarize_owner_eras(seasons),
        }

    return result


def calculate_fun_stats(all_seasons: list[dict]) -> list[dict]:
    """Calculate additional fun statistics."""

    fun_stats = []

    # Highest scoring week (combined all teams)
    weekly_totals = []
    for season_data in all_seasons:
        season = season_data['season']
        for week in season_data['weeks']:
            week_num = week['week']
            week_name = get_week_name(week_num, season)

            scores = []
            for matchup in week.get('matchups', []):
                s1 = get_team_score(matchup['team1'])
                s2 = get_team_score(matchup['team2'])
                if s1 is None or s2 is None:
                    scores = []
                    break
                scores.extend((s1, s2))

            if scores and sum(scores) > 0:
                weekly_totals.append((sum(scores), week_name, season))

    weekly_totals.sort(key=lambda x: x[0], reverse=True)
    fun_stats.append(
        {
            'title': 'Highest Scoring Week (League Total)',
            'records': [f'{r[0]:.0f} points ({r[1]}, {r[2]})' for r in weekly_totals[:3]],
        }
    )

    # Lowest scoring week
    weekly_totals.sort(key=lambda x: x[0])
    fun_stats.append(
        {
            'title': 'Lowest Scoring Week (League Total)',
            'records': [f'{r[0]:.0f} points ({r[1]}, {r[2]})' for r in weekly_totals[:3]],
        }
    )

    # Closest games
    closest_games = []
    for season_data in all_seasons:
        season = season_data['season']
        for week in season_data['weeks']:
            week_num = week['week']
            week_name = get_week_name(week_num, season)

            for matchup in week.get('matchups', []):
                t1 = matchup['team1']
                t2 = matchup['team2']
                t1_name = clean_team_name(t1['name'])
                t2_name = clean_team_name(t2['name'])
                s1 = get_team_score(t1)
                s2 = get_team_score(t2)

                if s1 is not None and s2 is not None and s1 > 0 and s2 > 0:
                    margin = abs(s1 - s2)
                    if s1 > s2:
                        closest_games.append(
                            (
                                margin,
                                t1_name,
                                t1['abbrev'],
                                s1,
                                t2_name,
                                t2['abbrev'],
                                s2,
                                week_name,
                                season,
                            )
                        )
                    else:
                        closest_games.append(
                            (
                                margin,
                                t2_name,
                                t2['abbrev'],
                                s2,
                                t1_name,
                                t1['abbrev'],
                                s1,
                                week_name,
                                season,
                            )
                        )

    closest_games.sort(key=lambda x: x[0])
    fun_stats.append(
        {
            'title': 'Closest Games',
            'records': [
                f'{r[1]} ({r[2]}) {r[3]:.0f} vs {r[4]} ({r[5]}) {r[6]:.0f} - {r[0]:.0f} pt margin ({r[7]}, {r[8]})'
                for r in closest_games[:5]
            ],
        }
    )

    # Most combined points in a matchup
    highest_combined = []
    for season_data in all_seasons:
        season = season_data['season']
        for week in season_data['weeks']:
            week_num = week['week']
            week_name = get_week_name(week_num, season)

            for matchup in week.get('matchups', []):
                t1 = matchup['team1']
                t2 = matchup['team2']
                t1_name = clean_team_name(t1['name'])
                t2_name = clean_team_name(t2['name'])
                s1 = get_team_score(t1)
                s2 = get_team_score(t2)

                if s1 is not None and s2 is not None and s1 > 0 and s2 > 0:
                    combined = s1 + s2
                    highest_combined.append(
                        (
                            combined,
                            t1_name,
                            t1['abbrev'],
                            s1,
                            t2_name,
                            t2['abbrev'],
                            s2,
                            week_name,
                            season,
                        )
                    )

    highest_combined.sort(key=lambda x: x[0], reverse=True)
    fun_stats.append(
        {
            'title': 'Highest Combined Score (Single Matchup)',
            'records': [
                f'{r[1]} ({r[3]:.0f}) vs {r[4]} ({r[6]:.0f}) = {r[0]:.0f} ({r[7]}, {r[8]})'
                for r in highest_combined[:3]
            ],
        }
    )

    # Most consistent scorer (lowest standard deviation in weekly scores)
    # This would require more complex calculation - skip for now

    return fun_stats


def calculate_season_stats_for_team(season_data: dict, abbrev: str, season: int) -> dict:
    """Calculate season stats for a specific team.

    Returns stats like average PPG, highest score, lowest score, biggest win margin.
    """
    weeks = season_data.get('weeks', [])
    regular_season_weeks = 14 if season <= 2021 else 15

    scores = []
    win_margins = []
    wins = 0
    losses = 0

    for week in weeks:
        week_num = week.get('week', 0)
        if week_num > regular_season_weeks:
            continue  # Only regular season

        for matchup in week.get('matchups', []):
            t1 = matchup.get('team1', {})
            t2 = matchup.get('team2', {})

            if isinstance(t1, str) or isinstance(t2, str):
                continue

            t1_abbrev = t1.get('abbrev')
            t2_abbrev = t2.get('abbrev')
            s1 = get_team_score(t1)
            s2 = get_team_score(t2)
            if s1 is None or s2 is None:
                continue

            if t1_abbrev == abbrev:
                if s1 > 0:
                    scores.append(s1)
                margin = s1 - s2
                if margin > 0:
                    win_margins.append(margin)
                    wins += 1
                elif margin < 0:
                    losses += 1
            elif t2_abbrev == abbrev:
                if s2 > 0:
                    scores.append(s2)
                margin = s2 - s1
                if margin > 0:
                    win_margins.append(margin)
                    wins += 1
                elif margin < 0:
                    losses += 1

    if not scores:
        return {}

    return {
        'avg_ppg': round(sum(scores) / len(scores), 1),
        'highest_score': max(scores),
        'lowest_score': min(scores),
        'biggest_win': max(win_margins) if win_margins else 0,
        'record': f'{wins}-{losses}',
    }


def calculate_league_season_stats(
    season_data: dict, season: int, connor_matchups: list = None
) -> dict:
    """Calculate league-wide stats for a season.

    Returns stats like average PPG across all teams, league high score,
    league low score, biggest win margin - with context on who/against whom.

    Args:
        season_data: Season data with weeks and matchups
        season: Season year
        connor_matchups: List of (season, week, winner) tuples for Connor Bowl history
    """
    weeks = season_data.get('weeks', [])
    regular_season_weeks = 14 if season <= 2021 else 15
    rivalry_week = 5 if season >= 2022 else None

    connor_matchups = connor_matchups or []

    def get_owner_name(abbrev: str, week_num: int) -> str:
        """Get owner name with correct Connor Bowl naming for a specific week."""
        base_name = _BASE_OWNER_NAMES.get(abbrev, abbrev)
        if abbrev in ('CGK', 'CWR'):
            holder = get_connor_bowl_holder_at_time(connor_matchups, season, week_num)
            base_name = get_connor_name_for_abbrev(abbrev, holder)
        return add_season_coowner(base_name, abbrev, season)

    all_scores = []
    highest_score_info = {'score': 0, 'abbrev': '', 'week': 0}
    lowest_score_info = {'score': float('inf'), 'abbrev': '', 'week': 0}
    biggest_win_info = {'margin': 0, 'winner_abbrev': '', 'loser_abbrev': '', 'week': 0}
    rivalry_biggest_win = {'margin': 0, 'winner_abbrev': '', 'loser_abbrev': '', 'week': 0}

    for week in weeks:
        week_num = week.get('week', 0)
        if week_num > regular_season_weeks:
            continue  # Only regular season

        for matchup in week.get('matchups', []):
            t1 = matchup.get('team1', {})
            t2 = matchup.get('team2', {})

            if isinstance(t1, str) or isinstance(t2, str):
                continue

            s1 = get_team_score(t1)
            s2 = get_team_score(t2)
            if s1 is None or s2 is None:
                continue
            t1_abbrev = t1.get('abbrev', '')
            t2_abbrev = t2.get('abbrev', '')

            # Track all scores for average
            if s1 > 0:
                all_scores.append(s1)
                if s1 > highest_score_info['score']:
                    highest_score_info = {'score': s1, 'abbrev': t1_abbrev, 'week': week_num}
                if s1 < lowest_score_info['score']:
                    lowest_score_info = {'score': s1, 'abbrev': t1_abbrev, 'week': week_num}

            if s2 > 0:
                all_scores.append(s2)
                if s2 > highest_score_info['score']:
                    highest_score_info = {'score': s2, 'abbrev': t2_abbrev, 'week': week_num}
                if s2 < lowest_score_info['score']:
                    lowest_score_info = {'score': s2, 'abbrev': t2_abbrev, 'week': week_num}

            # Track biggest win margin
            if s1 > 0 and s2 > 0:
                margin = abs(s1 - s2)
                if margin > biggest_win_info['margin']:
                    if s1 > s2:
                        biggest_win_info = {
                            'margin': margin,
                            'winner_abbrev': t1_abbrev,
                            'loser_abbrev': t2_abbrev,
                            'week': week_num,
                        }
                    else:
                        biggest_win_info = {
                            'margin': margin,
                            'winner_abbrev': t2_abbrev,
                            'loser_abbrev': t1_abbrev,
                            'week': week_num,
                        }

                # Track rivalry week biggest win
                if week_num == rivalry_week and margin > rivalry_biggest_win['margin']:
                    if s1 > s2:
                        rivalry_biggest_win = {
                            'margin': margin,
                            'winner_abbrev': t1_abbrev,
                            'loser_abbrev': t2_abbrev,
                            'week': week_num,
                        }
                    else:
                        rivalry_biggest_win = {
                            'margin': margin,
                            'winner_abbrev': t2_abbrev,
                            'loser_abbrev': t1_abbrev,
                            'week': week_num,
                        }

    if not all_scores:
        return {}

    # Now resolve names with correct Connor Bowl status at time of each event
    result = {
        'avg_ppg': round(sum(all_scores) / len(all_scores), 1),
        'highest_score': highest_score_info['score'],
        'highest_score_team': get_owner_name(
            highest_score_info['abbrev'], highest_score_info['week']
        ),
        'highest_score_week': highest_score_info['week'],
        'lowest_score': lowest_score_info['score']
        if lowest_score_info['score'] != float('inf')
        else 0,
        'lowest_score_team': get_owner_name(lowest_score_info['abbrev'], lowest_score_info['week']),
        'lowest_score_week': lowest_score_info['week'],
        'biggest_win': biggest_win_info['margin'],
        'biggest_win_winner': get_owner_name(
            biggest_win_info['winner_abbrev'], biggest_win_info['week']
        ),
        'biggest_win_loser': get_owner_name(
            biggest_win_info['loser_abbrev'], biggest_win_info['week']
        ),
        'biggest_win_week': biggest_win_info['week'],
    }

    # Add rivalry week winner if there was one (use Connor Bowl status at week 5)
    if rivalry_biggest_win['margin'] > 0:
        result['rivalry_winner'] = get_owner_name(
            rivalry_biggest_win['winner_abbrev'], rivalry_week
        )
        result['rivalry_loser'] = get_owner_name(rivalry_biggest_win['loser_abbrev'], rivalry_week)
        result['rivalry_margin'] = rivalry_biggest_win['margin']

    return result


def generate_season_finishes(season_data: dict, season: int) -> dict | None:
    """Auto-generate finishes for a season from playoff results.

    Returns a finish entry like:
    {
        "year": "2025",
        "results": [...],
        "champion_abbrev": "CGK",
        "champion_stats": { "avg_ppg": 85.5, "highest_score": 120, ... }
    }
    """
    weeks = season_data.get('weeks', [])

    # Find the finals week (week 17 for 10-team, week 16 for 8-team)
    finals_week = 17 if season >= 2022 else 16

    finals_data = None
    for week in weeks:
        if week.get('week') == finals_week:
            finals_data = week
            break

    if not finals_data:
        return None

    matchups = finals_data.get('matchups', [])
    if not matchups:
        return None

    results = []
    sewer_teams = []  # Teams in sewer series
    toilet_bowl_loser = None
    champion_abbrev = None

    for matchup in matchups:
        game = matchup.get('game', '')
        t1 = matchup.get('team1', {})
        t2 = matchup.get('team2', {})
        if isinstance(t1, str) or isinstance(t2, str):
            # TBD teams, skip
            continue

        s1 = get_team_score(t1)
        s2 = get_team_score(t2)
        if s1 is None or s2 is None or s1 == 0 or s2 == 0 or s1 == s2:
            continue

        t1_abbrev = t1.get('abbrev', '')
        t2_abbrev = t2.get('abbrev', '')
        t1_owner = add_season_coowner(
            OWNER_NAMES.get(t1_abbrev, t1.get('owner', '')), t1_abbrev, season
        )
        t2_owner = add_season_coowner(
            OWNER_NAMES.get(t2_abbrev, t2.get('owner', '')), t2_abbrev, season
        )

        if game == 'championship':
            if s1 > s2:
                results.append(t1_owner)  # 1st place
                results.append(t2_owner)  # 2nd place
                champion_abbrev = t1_abbrev
            else:
                results.append(t2_owner)  # 1st place
                results.append(t1_owner)  # 2nd place
                champion_abbrev = t2_abbrev

        elif game == 'consolation_cup':
            if s1 > s2:
                results.append(t1_owner)  # 3rd place
            else:
                results.append(t2_owner)  # 3rd place

        elif game == 'toilet_bowl':
            # The LOSER of the toilet bowl is the one recorded
            sewer_teams.append(t1_owner)
            sewer_teams.append(t2_owner)
            toilet_bowl_loser = t1_owner if s1 < s2 else t2_owner

    # Also get sewer series teams from week 16 (the other 2 teams)
    semifinal_week = finals_week - 1
    for week in weeks:
        if week.get('week') == semifinal_week:
            for matchup in week.get('matchups', []):
                game = matchup.get('game', '')
                if game.startswith('sewer_'):
                    t1 = matchup.get('team1', {})
                    t2 = matchup.get('team2', {})
                    if not isinstance(t1, str):
                        t1_abbrev = t1.get('abbrev', '')
                        t1_owner = add_season_coowner(
                            OWNER_NAMES.get(t1_abbrev, t1.get('owner', '')),
                            t1_abbrev,
                            season,
                        )
                        if t1_owner and t1_owner not in sewer_teams:
                            sewer_teams.append(t1_owner)
                    if not isinstance(t2, str):
                        t2_abbrev = t2.get('abbrev', '')
                        t2_owner = add_season_coowner(
                            OWNER_NAMES.get(t2_abbrev, t2.get('owner', '')),
                            t2_abbrev,
                            season,
                        )
                        if t2_owner and t2_owner not in sewer_teams:
                            sewer_teams.append(t2_owner)
            break

    # Build toilet bowl entry
    if toilet_bowl_loser and sewer_teams:
        other_sewer = [t for t in sewer_teams if t != toilet_bowl_loser]
        if other_sewer:
            results.append(f'Toilet Bowl - {toilet_bowl_loser} ({", ".join(other_sewer)})')
        else:
            results.append(f'Toilet Bowl - {toilet_bowl_loser}')

    # TODO: Add rivalry week winner detection if applicable
    # For now, this would need to be determined from rivalry matchups

    if not results:
        return None

    # Calculate league-wide stats (connor_matchups will be passed from caller if available)
    # For now, this gets called without connor_matchups and stats are updated later

    return {
        'year': str(season),
        'results': results,
        'champion_abbrev': champion_abbrev,
        'league_stats': {},  # Will be populated later with correct Connor Bowl naming
    }


def configured_current_season() -> int:
    config_path = SOURCE_DATA_DIR / 'league_config.json'
    if config_path.exists():
        with open(config_path) as f:
            season = json.load(f).get('current_season')
        if isinstance(season, int):
            return season
    return datetime.now(timezone.utc).year


def discover_seasons(current_season: int) -> list[int]:
    """Find archived seasons and always include the configured live season."""
    seasons = {current_season}
    index_file = DATA_DIR / 'index.json'
    if index_file.exists():
        with open(index_file) as f:
            index_data = json.load(f)
        seasons.update(
            int(season)
            for season in index_data.get('seasons', index_data.get('available_seasons', []))
        )
    if SEASONS_DIR.exists():
        seasons.update(
            int(path.name)
            for path in SEASONS_DIR.iterdir()
            if path.is_dir() and path.name.isdigit()
        )
    return sorted(seasons, reverse=True)


def _without_refresh_metadata(data: dict) -> dict:
    return {key: value for key, value in data.items() if key != 'updated_at'}


def resolve_completed_through(
    existing_hof: dict, current_season: int, requested_week: int | None
) -> int:
    """Use an explicit completed week or the last safely generated marker."""
    if requested_week is not None:
        return requested_week
    saved_week = existing_hof.get('completed_through', {}).get(str(current_season), 0)
    return saved_week if isinstance(saved_week, int) and saved_week >= 0 else 0


def generate_hall_of_fame(
    current_season: int | None = None, completed_through: int | None = None
) -> bool:
    """Generate the complete Hall of Fame data."""

    print('Generating Hall of Fame statistics...')

    current_season = current_season or configured_current_season()
    existing_hof = {}
    hof_file = SHARED_DIR / 'hall_of_fame.json'
    if hof_file.exists():
        with open(hof_file) as f:
            existing_hof = json.load(f)
    completed_through = resolve_completed_through(existing_hof, current_season, completed_through)
    seasons = discover_seasons(current_season)

    # Load all season data
    all_seasons = []
    for season in seasons:
        print(f'  Loading {season}...')
        season_data = load_season_data(season, current_season, completed_through)
        all_seasons.append(season_data)

    finishes_by_year = copy.deepcopy(existing_hof.get('finishes_by_year', []))
    update_season_coowner_names(all_seasons)

    # Determine who holds the Connor Bowl (based on most recent head-to-head) and update owner names
    update_owner_names_for_connor_bowl(all_seasons)
    connor_holder = get_connor_bowl_holder(all_seasons)
    if connor_holder:
        print(f'  Connor Bowl holder: {OWNER_NAMES.get(connor_holder, connor_holder)}')

    # Get all Connor matchups for historical lookup
    connor_matchups = get_all_connor_matchups(all_seasons)

    def apply_connor_bowl_naming_for_season(text: str, season: int) -> str:
        """Update Connor Bowl naming in text based on who held the bowl at end of that season."""
        text = normalize_coowners_in_text(text, season)
        holder = get_connor_bowl_holder_at_time(connor_matchups, season)
        cgk_name, cwr_name = get_connor_names(holder)
        jack_marker = '__JACK_REARDON__'

        # First normalize to just last names
        text = text.replace('Jack Reardon', jack_marker)
        text = text.replace('Connor Kaminska', 'Kaminska')
        text = text.replace('Redacted Kaminska', 'Kaminska')
        text = text.replace('Connor Reardon', 'Reardon')
        text = text.replace('Redacted Reardon', 'Reardon')

        # Then apply the correct names for this historical moment
        text = text.replace('Kaminska', cgk_name)
        text = text.replace('Reardon', cwr_name)

        return text.replace(jack_marker, 'Jack Reardon')

    print('  Applying historical Connor Bowl naming to entries...')
    for entry in finishes_by_year:
        year_str = entry.get('year', '')
        if not year_str.isdigit():
            continue
        season = int(year_str)
        if 'results' in entry:
            entry['results'] = [
                apply_connor_bowl_naming_for_season(r, season) for r in entry['results']
            ]

    # Auto-generate/update finishes for seasons with completed playoffs (with correct names now)
    print('  Auto-generating season finishes from playoff results...')
    for season_data in all_seasons:
        season = season_data.get('season')
        if not season:
            continue

        # Check if this season has a completed finals week
        auto_finish = generate_season_finishes(season_data, season)
        if auto_finish and auto_finish.get('results'):
            # Find existing entry for this year
            existing_entry = None
            for i, entry in enumerate(finishes_by_year):
                if entry.get('year') == str(season):
                    existing_entry = i
                    break

            if existing_entry is not None:
                # Update existing entry with auto-generated data
                # Preserve rivalry week winner if it exists in the old entry
                old_results = finishes_by_year[existing_entry].get('results', [])
                rivalry_winner = None
                for r in old_results:
                    if 'Rivalry Week Winner' in r:
                        rivalry_winner = r
                        break

                # Replace with auto-generated, but keep rivalry winner
                new_results = auto_finish['results']
                if rivalry_winner and not any('Rivalry Week Winner' in r for r in new_results):
                    new_results.append(rivalry_winner)

                finishes_by_year[existing_entry]['results'] = new_results
                finishes_by_year[existing_entry]['champion_abbrev'] = auto_finish.get(
                    'champion_abbrev'
                )
                finishes_by_year[existing_entry]['league_stats'] = auto_finish.get(
                    'league_stats', {}
                )
                print(f'    Updated {season} finishes from playoff results')
            else:
                # Add new entry
                finishes_by_year.append(auto_finish)
                print(f'    Added {season} finishes from playoff results')

    # Add league stats to any entries that don't have them yet (or have old format)
    print('  Adding league stats to historical seasons...')

    for entry in finishes_by_year:
        year_str = entry.get('year', '')
        if not year_str.isdigit():
            continue

        year = int(year_str)

        # Find the season data
        season_data = next((s for s in all_seasons if s.get('season') == year), None)
        if not season_data:
            continue

        # Always recalculate league stats to get correct Connor Bowl naming at each event's time
        stats = calculate_league_season_stats(season_data, year, connor_matchups)
        if stats:
            entry['league_stats'] = stats
            print(f'    Added league stats for {year}')

    # Calculate records
    drafts = []
    drafts_path = SOURCE_DATA_DIR / 'drafts.json'
    if drafts_path.exists():
        with open(drafts_path) as f:
            drafts = json.load(f).get('drafts', [])

    current_rosters = {}
    rosters_path = SOURCE_DATA_DIR / 'rosters.json'
    if rosters_path.exists():
        with open(rosters_path) as f:
            current_rosters = json.load(f)

    award_entries = list(existing_hof.get('mvps', []))
    for entry in finishes_by_year:
        if 'MVP' in str(entry.get('year', '')):
            award_entries.extend(entry.get('results', []))

    print('  Loading player birth dates...')
    player_birth_dates = load_player_birth_dates(existing_hof.get('player_career_stats', {}))

    print('  Calculating player career profiles...')
    player_career_stats = calculate_player_career_stats(
        all_seasons,
        drafts=drafts,
        current_rosters=current_rosters,
        award_entries=award_entries,
        player_birth_dates=player_birth_dates,
    )

    print('  Calculating player records...')
    player_records = calculate_player_records(all_seasons)

    print('  Calculating team records...')
    team_records = calculate_team_records(all_seasons)

    print('  Calculating owner stats...')
    owner_stats = calculate_owner_stats(all_seasons, finishes_by_year)

    print('  Calculating fun stats...')
    fun_stats = calculate_fun_stats(all_seasons)

    print('  Calculating rivalry records...')
    rivalry_records = calculate_rivalry_records(all_seasons)

    print('  Calculating team Hall of Fame stats...')
    team_hall_of_fame = calculate_team_hall_of_fame(all_seasons, finishes_by_year, rivalry_records)

    # Build output structure
    output = {
        'finishes_by_year': finishes_by_year,  # Use the auto-updated version
        'mvps': existing_hof.get('mvps', []),
        'team_records': [
            {'title': 'Most Points Scored (Team)', 'records': team_records['most_points']},
            {'title': 'Least Points Scored (Team)', 'records': team_records['least_points']},
            {'title': 'Largest Margin of Victory', 'records': team_records['largest_margin']},
        ],
        'player_records': [
            {'title': 'Most Points Scored', 'records': player_records['most_points']},
            {
                'title': 'Most Points Scored (Non-QB)',
                'records': player_records['most_points_non_qb'],
            },
            {
                'title': 'Least Points Scored (Offensive Player)',
                'records': player_records['least_points_offensive'],
            },
            {
                'title': 'Least Points Scored (Kicker)',
                'records': player_records['least_points_kicker'],
            },
            {
                'title': 'Defensive Hall of Shame (-6 points)',
                'records': player_records['defensive_shame'],
            },
        ],
        'player_career_stats': player_career_stats,
        'fun_stats': fun_stats,
        'owner_stats': owner_stats,
        'rivalry_records': rivalry_records,
        'team_hall_of_fame': team_hall_of_fame,
    }
    completed_weeks = copy.deepcopy(existing_hof.get('completed_through', {}))
    completed_weeks[str(current_season)] = completed_through
    if completed_weeks:
        output['completed_through'] = completed_weeks

    if _without_refresh_metadata(existing_hof) == output:
        print('  Hall of Fame is already current; no file changes needed')
        return False

    output['updated_at'] = datetime.now(timezone.utc).isoformat()

    # Write output
    SHARED_DIR.mkdir(parents=True, exist_ok=True)
    with open(hof_file, 'w') as f:
        json.dump(output, f, indent=2)
        f.write('\n')

    print(f'  Saved to {hof_file}')
    print('Hall of Fame generated!')

    # Print summary
    print('\n=== Summary ===')
    print(f'Seasons analyzed: {seasons}')
    print(f'Top scorer: {player_records["most_points"][0]}')
    print(f'Top team score: {team_records["most_points"][0]}')
    print(f'Largest margin: {team_records["largest_margin"][0]}')
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--current-season', type=int)
    parser.add_argument('--completed-through', type=int)
    args = parser.parse_args()
    generate_hall_of_fame(args.current_season, args.completed_through)
