"""Generate Hall of Fame statistics from all season data."""

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

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
    'S/T': 'Spencer/Tim',
    'J/J': 'Joe/Joe',
    'AST': 'Anagh',
    'TJG': 'Tim',
    'SRY': 'Spencer',
    'JDK': 'Joe K.',
    # Combined codes - map to primary owner
    'CGK/SRY': 'Kaminska',
    'CWR/SLS': 'Reardon',
}

# Initialize OWNER_NAMES - will be updated with Connor Bowl holder
OWNER_NAMES = _BASE_OWNER_NAMES.copy()


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
                    s1 = t1.get('total_score', 0)
                    s2 = t2.get('total_score', 0)

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


def update_owner_names_for_connor_bowl(all_seasons: list[dict]):
    """Update OWNER_NAMES to reflect who CURRENTLY holds the Connor Bowl."""
    global OWNER_NAMES
    OWNER_NAMES = _BASE_OWNER_NAMES.copy()

    connor_holder = get_connor_bowl_holder(all_seasons)
    cgk_name, cwr_name = get_connor_names(connor_holder)

    OWNER_NAMES['CGK'] = cgk_name
    OWNER_NAMES['CWR'] = cwr_name


# Seasons will be loaded dynamically from index.json


def load_season_data(season: int) -> dict:
    """Load all week data for a season.

    For current season (2025), prefer data.json as it has the most recent
    week data with correct playoff matchups.
    """
    season_dir = SEASONS_DIR / str(season)
    weeks_dir = season_dir / 'weeks'

    weeks = []

    # For current season, prefer data.json as it has the most up-to-date data
    if season == 2025:
        data_json_path = WEB_DIR / 'data.json'
        if data_json_path.exists():
            with open(data_json_path) as f:
                data_json = json.load(f)
            weeks = data_json.get('weeks', [])

    # Fall back to individual week files if data.json didn't have data
    if not weeks and weeks_dir.exists():
        for week_file in sorted(weeks_dir.glob('week_*.json')):
            with open(week_file) as f:
                weeks.append(json.load(f))

    standings = {}
    standings_file = season_dir / 'standings.json'
    if standings_file.exists():
        with open(standings_file) as f:
            standings = json.load(f)

    return {'weeks': weeks, 'standings': standings, 'season': season}


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
                        score = player.get('score', 0)
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

                s1 = t1.get('total_score', 0)
                s2 = t2.get('total_score', 0)

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


def get_owner_codes(abbrev: str) -> list[str]:
    """Get all owner codes for an abbreviation (handles combined teams)."""
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
        'Joe/Joe': 'J/J',
        'Anagh': 'AST',
        'Tim': 'TJG',
        'Spencer': 'SRY',
        'Joe Kuhl': 'JDK',
        'Joe K.': 'JDK',
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

        # Determine playoff cutoff based on season
        num_teams = 8 if season <= 2021 else 10
        playoff_cutoff = 4  # Top 4 make playoffs in both formats

        for i, team in enumerate(standings):
            abbrev = team.get('abbrev', '')
            owner_codes = get_owner_codes(abbrev)

            rank = i + 1

            # Apply stats to all owners of this team
            for owner_code in owner_codes:
                stats = owner_stats[owner_code]
                stats['seasons'].add(season)
                stats['wins'] += team.get('wins', 0)
                stats['losses'] += team.get('losses', 0)
                stats['ties'] += team.get('ties', 0)
                stats['points_for'] += team.get('points_for', 0)
                stats['points_against'] += team.get('points_against', 0)

                # Playoff berths (top 4)
                if rank <= playoff_cutoff:
                    stats['playoff_berths'] += 1

                # Sewer series (bottom teams depending on league size)
                if (
                    num_teams == 10 and rank > 6 or num_teams == 8 and rank > 4
                ):  # 7-10 are sewer series
                    stats['sewer_series_berths'] += 1

                # Last place
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

                s1 = t1.get('total_score', 0) or t1.get('score', 0)
                s2 = t2.get('total_score', 0) or t2.get('score', 0)

                if s1 is None or s2 is None or s1 == 0 or s2 == 0:
                    continue

                t1_codes = get_owner_codes(t1.get('abbrev', ''))
                t2_codes = get_owner_codes(t2.get('abbrev', ''))

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

    # Combine Spencer (SRY) and Tim (TJG) into "Spencer/Tim" for display
    # Find and merge their stats
    spencer_data = next((r for r in result if r['Code'] == 'SRY'), None)
    tim_data = next((r for r in result if r['Code'] == 'TJG'), None)

    if spencer_data and tim_data:
        # They share S/T stats, so we just need one combined entry
        # Use Spencer's data as base (they should be identical for shared seasons)
        result = [r for r in result if r['Code'] not in ('SRY', 'TJG')]
        spencer_data['Owner'] = 'Spencer/Tim'
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
                s1 = matchup['team1'].get('total_score')
                s2 = matchup['team2'].get('total_score')

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

            total = 0
            for matchup in week.get('matchups', []):
                total += matchup['team1'].get('total_score', 0)
                total += matchup['team2'].get('total_score', 0)

            if total > 0:
                weekly_totals.append((total, week_name, season))

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
                s1 = t1.get('total_score', 0)
                s2 = t2.get('total_score', 0)

                if s1 > 0 and s2 > 0:
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
                s1 = t1.get('total_score', 0)
                s2 = t2.get('total_score', 0)

                if s1 > 0 and s2 > 0:
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
            s1 = t1.get('total_score', 0)
            s2 = t2.get('total_score', 0)

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
    rivalry_week = 5  # Rivalry Week is always Week 5

    connor_matchups = connor_matchups or []

    def get_owner_name(abbrev: str, week_num: int) -> str:
        """Get owner name with correct Connor Bowl naming for a specific week."""
        base_name = _BASE_OWNER_NAMES.get(abbrev, abbrev)
        if abbrev in ('CGK', 'CWR'):
            holder = get_connor_bowl_holder_at_time(connor_matchups, season, week_num)
            return get_connor_name_for_abbrev(abbrev, holder)
        return base_name

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

            s1 = t1.get('total_score', 0)
            s2 = t2.get('total_score', 0)
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
        s1 = t1.get('total_score', 0)
        s2 = t2.get('total_score', 0)

        if isinstance(t1, str) or isinstance(t2, str):
            # TBD teams, skip
            continue

        t1_abbrev = t1.get('abbrev', '')
        t2_abbrev = t2.get('abbrev', '')
        t1_owner = OWNER_NAMES.get(t1_abbrev, t1.get('owner', ''))
        t2_owner = OWNER_NAMES.get(t2_abbrev, t2.get('owner', ''))

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
                        t1_owner = OWNER_NAMES.get(t1.get('abbrev', ''), t1.get('owner', ''))
                        if t1_owner and t1_owner not in sewer_teams:
                            sewer_teams.append(t1_owner)
                    if not isinstance(t2, str):
                        t2_owner = OWNER_NAMES.get(t2.get('abbrev', ''), t2.get('owner', ''))
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


def generate_hall_of_fame():
    """Generate the complete Hall of Fame data."""

    print('Generating Hall of Fame statistics...')

    # Load available seasons from index.json
    index_file = DATA_DIR / 'index.json'
    if index_file.exists():
        with open(index_file) as f:
            index_data = json.load(f)
        seasons = index_data.get('seasons', index_data.get('available_seasons', [2025]))
    else:
        seasons = [2025]

    # Load all season data
    all_seasons = []
    for season in seasons:
        print(f'  Loading {season}...')
        season_data = load_season_data(season)
        all_seasons.append(season_data)

    # Load existing hall of fame for finishes_by_year and MVPs (manual data)
    existing_hof = {}
    hof_file = SHARED_DIR / 'hall_of_fame.json'
    if hof_file.exists():
        with open(hof_file) as f:
            existing_hof = json.load(f)

    finishes_by_year = existing_hof.get('finishes_by_year', [])

    # Determine who holds the Connor Bowl (based on most recent head-to-head) and update owner names
    update_owner_names_for_connor_bowl(all_seasons)
    connor_holder = get_connor_bowl_holder(all_seasons)
    if connor_holder:
        print(f'  Connor Bowl holder: {OWNER_NAMES.get(connor_holder, connor_holder)}')

    # Get all Connor matchups for historical lookup
    connor_matchups = get_all_connor_matchups(all_seasons)

    def apply_connor_bowl_naming_for_season(text: str, season: int) -> str:
        """Update Connor Bowl naming in text based on who held the bowl at end of that season."""
        holder = get_connor_bowl_holder_at_time(connor_matchups, season)
        cgk_name, cwr_name = get_connor_names(holder)

        # First normalize to just last names
        text = text.replace('Connor Kaminska', 'Kaminska')
        text = text.replace('Redacted Kaminska', 'Kaminska')
        text = text.replace('Connor Reardon', 'Reardon')
        text = text.replace('Redacted Reardon', 'Reardon')

        # Then apply the correct names for this historical moment
        text = text.replace('Kaminska', cgk_name)
        text = text.replace('Reardon', cwr_name)

        return text

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

    # Build output structure
    output = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
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
        'fun_stats': fun_stats,
        'owner_stats': owner_stats,
        'rivalry_records': rivalry_records,
    }

    # Write output
    SHARED_DIR.mkdir(parents=True, exist_ok=True)
    with open(hof_file, 'w') as f:
        json.dump(output, f, indent=2)

    print(f'  Saved to {hof_file}')
    print('Hall of Fame generated!')

    # Print summary
    print('\n=== Summary ===')
    print(f'Seasons analyzed: {seasons}')
    print(f'Top scorer: {player_records["most_points"][0]}')
    print(f'Top team score: {team_records["most_points"][0]}')
    print(f'Largest margin: {team_records["largest_margin"][0]}')


if __name__ == '__main__':
    generate_hall_of_fame()
