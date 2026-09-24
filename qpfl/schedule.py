"""Schedule parsing and playoff structure for QPFL.

Starting in 2026:
- Weeks 1-15: Regular season matchups from data/seasons/{season}/schedule.txt
- Week 16: Playoff round 1
  - 1 seed vs 4 seed (playoffs - affects standings)
  - 2 seed vs 3 seed (playoffs - affects standings)
  - 5 seed vs 6 seed (mid bowl - no standings impact, cumulative over weeks 16-17)
  - 7 seed vs 10 seed (sewer series - no standings impact)
  - 8 seed vs 9 seed (sewer series - no standings impact)
- Week 17: Finals
  - Championship: Winners of 1v4 and 2v3 (1st/2nd place)
  - Consolation Cup: Losers of 1v4 and 2v3 (3rd/4th place)
  - Mid Bowl: Same 5v6 teams, cumulative score from weeks 16-17 (5th/6th place)
  - Toilet Bowl: Losers of sewer series matchups (9th/10th place - loser is Toilet Bowl loser)
  - 7th Place Game: Winners of sewer series matchups (7th/8th place)
"""

import json
import re
from pathlib import Path
from typing import Any

# Playoff structure for 2026+
PLAYOFF_STRUCTURE_2026: dict[int, dict[str, Any]] = {
    16: {
        'round': 'Semifinals',
        'matchups': [
            {
                'seed1': 1,
                'seed2': 4,
                'bracket': 'playoffs',
                'game': 'semi_1',
                'affects_standings': True,
            },
            {
                'seed1': 2,
                'seed2': 3,
                'bracket': 'playoffs',
                'game': 'semi_2',
                'affects_standings': True,
            },
            {
                'seed1': 5,
                'seed2': 6,
                'bracket': 'mid_bowl',
                'game': 'mid_bowl_1',
                'two_week': True,
                'affects_standings': False,
            },
            {
                'seed1': 7,
                'seed2': 10,
                'bracket': 'sewer_series',
                'game': 'sewer_1',
                'affects_standings': False,
            },
            {
                'seed1': 8,
                'seed2': 9,
                'bracket': 'sewer_series',
                'game': 'sewer_2',
                'affects_standings': False,
            },
        ],
    },
    17: {
        'round': 'Finals',
        'matchups': [
            {
                'from_games': ['semi_1', 'semi_2'],
                'take': 'winners',
                'bracket': 'championship',
                'game': 'championship',
                'determines': [1, 2],
            },
            {
                'from_games': ['semi_1', 'semi_2'],
                'take': 'losers',
                'bracket': 'consolation_cup',
                'game': 'consolation_cup',
                'determines': [3, 4],
            },
            {
                'seed1': 5,
                'seed2': 6,
                'bracket': 'mid_bowl',
                'game': 'mid_bowl_2',
                'two_week': True,
                'cumulative_with': 'mid_bowl_1',
                'determines': [5, 6],
            },
            {
                'from_games': ['sewer_1', 'sewer_2'],
                'take': 'losers',
                'bracket': 'toilet_bowl',
                'game': 'toilet_bowl',
                'determines': [9, 10],
            },
            {
                'from_games': ['sewer_1', 'sewer_2'],
                'take': 'winners',
                'bracket': '7th_place',
                'game': '7th_place',
                'determines': [7, 8],
            },
        ],
    },
}


def schedule_path_for_season(data_dir: str | Path, season: int) -> Path:
    """Return the source-of-truth schedule path for one season."""
    return Path(data_dir) / 'seasons' / str(season) / 'schedule.txt'


def parse_schedule_file(schedule_path: str | Path) -> list[list[tuple[str, str]]]:
    """Parse schedule.txt file into weekly matchups.

    Supports format:
        Week 1: GSA versus S/T, RPA versus CWR, CGK versus AYP
        Rivalry Week 5: GSA versus RPA, CWR versus CGK

    Args:
        schedule_path: Path to schedule.txt file

    Returns:
        List of 15 weeks, each containing list of (team1, team2) tuples
    """
    schedule_path = Path(schedule_path)
    if not schedule_path.exists():
        raise FileNotFoundError(f'Schedule file not found: {schedule_path}')

    with open(schedule_path) as f:
        content = f.read()

    weeks: list[list[tuple[str, str]]] = []

    for line in content.split('\n'):
        line = line.strip()

        # Skip empty lines and comments
        if not line or line.startswith('#'):
            continue

        # Parse line format: "Week N: matchups" or "Rivalry Week N: matchups"
        # Match "Week N:" or "Rivalry Week N:" etc.
        week_match = re.match(r'^(?:Rivalry\s+)?Week\s+(\d+)\s*:\s*(.+)$', line, re.IGNORECASE)
        if week_match:
            week_num = int(week_match.group(1))
            matchups_str = week_match.group(2)

            # Parse comma-separated matchups: "Team1 versus Team2, Team3 versus Team4"
            matchups = []
            for matchup in matchups_str.split(','):
                matchup = matchup.strip()
                # Match "Team1 versus Team2" or "Team1 vs Team2"
                teams_match = re.match(
                    r'^([A-Z/]+)\s+(?:versus|vs)\s+([A-Z/]+)$', matchup, re.IGNORECASE
                )
                if teams_match:
                    team1 = teams_match.group(1).upper()
                    team2 = teams_match.group(2).upper()
                    matchups.append((team1, team2))

            # Ensure weeks list is long enough
            while len(weeks) < week_num:
                weeks.append([])

            # Store matchups (week_num is 1-indexed, list is 0-indexed)
            weeks[week_num - 1] = matchups

    return weeks


def get_regular_season_schedule(schedule_path: str | Path) -> list[dict]:
    """Get regular season schedule in JSON format.

    Args:
        schedule_path: Path to schedule.txt file

    Returns:
        List of week objects with matchups
    """
    weeks = parse_schedule_file(schedule_path)
    rivalry_weeks = detect_rivalry_weeks(schedule_path)
    schedule_data = []

    for week_num, matchups in enumerate(weeks, 1):
        week_matchups = []
        for team1, team2 in matchups:
            week_matchups.append(
                {
                    'team1': team1,
                    'team2': team2,
                }
            )

        schedule_data.append(
            {
                'week': week_num,
                'is_rivalry': week_num in rivalry_weeks,
                'is_playoffs': False,
                'matchups': week_matchups,
            }
        )

    return schedule_data


def detect_rivalry_weeks(schedule_path: str | Path) -> set[int]:
    """Detect which weeks are rivalry weeks from the schedule file.

    Args:
        schedule_path: Path to schedule.txt file

    Returns:
        Set of week numbers that are rivalry weeks
    """
    schedule_path = Path(schedule_path)
    if not schedule_path.exists():
        return set()

    rivalry_weeks = set()

    with open(schedule_path) as f:
        for line in f:
            line = line.strip()
            # Check for "Rivalry Week N:"
            match = re.match(r'^Rivalry\s+Week\s+(\d+)\s*:', line, re.IGNORECASE)
            if match:
                rivalry_weeks.add(int(match.group(1)))

    return rivalry_weeks


def _score(team: object) -> float | None:
    if not isinstance(team, dict):
        return None
    score = team.get('total_score')
    return float(score) if isinstance(score, (int, float)) else None


def _abbrev(team: object) -> str | None:
    if isinstance(team, dict):
        team = team.get('abbrev')
    return team if isinstance(team, str) and team and team != 'TBD' else None


def playoff_game_result(matchup: dict) -> dict | None:
    """Winner/loser of one scored playoff matchup, or None if it can't be decided.

    Playoff games can't end tied: the constitution breaks a tie by seed, so
    the better (numerically lower) seed advances. Without recorded seeds,
    team1 is the better seed - true of every Week 16 game in the bracket.
    """
    team1, team2 = matchup.get('team1'), matchup.get('team2')
    abbrev1, abbrev2 = _abbrev(team1), _abbrev(team2)
    score1, score2 = _score(team1), _score(team2)
    if abbrev1 is None or abbrev2 is None or score1 is None or score2 is None:
        return None
    seed1, seed2 = matchup.get('seed1'), matchup.get('seed2')
    if score1 != score2:
        team1_wins = score1 > score2
    elif isinstance(seed1, int) and isinstance(seed2, int):
        team1_wins = seed1 < seed2
    else:
        team1_wins = True
    winner = (abbrev1, seed1) if team1_wins else (abbrev2, seed2)
    loser = (abbrev2, seed2) if team1_wins else (abbrev1, seed1)
    return {
        'winner': winner[0],
        'loser': loser[0],
        'winner_seed': winner[1] if isinstance(winner[1], int) else None,
        'loser_seed': loser[1] if isinstance(loser[1], int) else None,
    }


def week16_results_from_output(week16_output: object) -> dict[str, dict]:
    """``{game_id: playoff_game_result}`` from a scored Week 16 file.

    Only a Week 16 whose NFL games are all final (``games_final``) decides the
    finals; until then this returns ``{}`` so Week 17 stays TBD rather than
    advancing whoever happens to lead mid-week.
    """
    if not isinstance(week16_output, dict) or week16_output.get('games_final') is not True:
        return {}
    results = {}
    for matchup in week16_output.get('matchups', []) or []:
        if not isinstance(matchup, dict) or not isinstance(matchup.get('game'), str):
            continue
        result = playoff_game_result(matchup)
        if result is not None:
            results[matchup['game']] = result
    return results


def load_week16_results(week16_path: str | Path) -> dict[str, dict]:
    """Week 16 results from its scored file, warning when Week 17 can't be set yet."""
    path = Path(week16_path)
    try:
        week16_output = json.loads(path.read_text()) if path.exists() else None
    except (OSError, json.JSONDecodeError):
        week16_output = None
    results = week16_results_from_output(week16_output)
    if not results:
        print(
            f'WARNING: Week 16 is not final yet ({path}); Week 17 finals matchups stay TBD '
            'until every Week 16 NFL game is final.'
        )
    return results


def teams_from_games(game: dict, results: dict[str, dict]) -> list[tuple[str, int | None]]:
    """The (team, seed) pairs a ``from_games``/``take`` finals game draws from
    Week 16 results, better seed first. Empty unless every source game is decided."""
    side = 'winner' if game.get('take') == 'winners' else 'loser'
    teams = []
    for source in game.get('from_games', []):
        result = results.get(source)
        if result is None or not result.get(side):
            return []
        teams.append((result[side], result.get(f'{side}_seed')))
    if all(isinstance(seed, int) for _team, seed in teams):
        teams.sort(key=lambda pair: pair[1] or 0)
    return teams


def get_playoff_schedule(
    standings: list[dict],
    season: int = 2026,
    week16_results: dict[str, dict] | None = None,
) -> list[dict]:
    """Generate playoff schedule based on standings.

    2026+ only: historical seasons (2020-2025) are frozen/scored-from-Excel and
    are never re-seeded through this path, so there is no legacy branch here.

    Args:
        standings: List of team standings (sorted by seed)
        season: Season year (affects playoff structure)
        week16_results: Decided Week 16 games (see ``week16_results_from_output``); fills
            in the Week 17 finals matchups, which otherwise stay TBD

    Returns:
        List of week 16-17 schedule objects
    """
    if season < 2026:
        raise ValueError(
            f'get_playoff_schedule only supports season >= 2026 (got {season}); '
            'historical seasons are frozen and scored via the legacy Excel pipeline'
        )
    playoff_structure = PLAYOFF_STRUCTURE_2026

    seed_to_team = {i + 1: team['abbrev'] for i, team in enumerate(standings)}
    schedule_data = []

    for week_num in [16, 17]:
        playoff_info = playoff_structure[week_num]
        week_matchups = []

        for game in playoff_info['matchups']:
            matchup = {
                'bracket': game['bracket'],
                'game': game['game'],
            }

            if 'seed1' in game:
                matchup['team1'] = seed_to_team.get(game['seed1'], 'TBD')
                matchup['team2'] = seed_to_team.get(game['seed2'], 'TBD')
                matchup['seed1'] = game['seed1']
                matchup['seed2'] = game['seed2']
            else:
                matchup['team1'] = 'TBD'
                matchup['team2'] = 'TBD'
                matchup['from_games'] = game.get('from_games', [])
                matchup['take'] = game.get('take', '')
                teams = teams_from_games(game, week16_results or {})
                if len(teams) == 2:
                    (matchup['team1'], seed1), (matchup['team2'], seed2) = teams
                    if isinstance(seed1, int) and isinstance(seed2, int):
                        matchup['seed1'] = seed1
                        matchup['seed2'] = seed2

            if game.get('two_week'):
                matchup['two_week'] = True
            if game.get('cumulative_with'):
                matchup['cumulative_with'] = game['cumulative_with']
            if game.get('determines'):
                matchup['determines'] = game['determines']
            if game.get('affects_standings') is not None:
                matchup['affects_standings'] = game['affects_standings']

            week_matchups.append(matchup)

        schedule_data.append(
            {
                'week': week_num,
                'is_rivalry': False,
                'is_playoffs': True,
                'playoff_round': playoff_info['round'],
                'matchups': week_matchups,
            }
        )

    return schedule_data


def get_full_schedule(
    schedule_path: str | Path,
    standings: list[dict] | None = None,
    season: int = 2026,
    week16_results: dict[str, dict] | None = None,
) -> list[dict]:
    """Get complete season schedule including playoffs.

    Args:
        schedule_path: Path to schedule.txt file
        standings: List of team standings (needed for playoff seeding)
        season: Season year

    Returns:
        List of all week schedule objects (weeks 1-17)
    """
    # Get regular season from schedule.txt
    schedule = get_regular_season_schedule(schedule_path)

    # Add playoff weeks if standings available
    if standings:
        playoff_weeks = get_playoff_schedule(standings, season, week16_results)
        schedule.extend(playoff_weeks)

    return schedule


def resolve_playoff_matchups(week_16_results: dict, week_17_results: dict | None = None) -> dict:
    """Resolve playoff matchups based on week 16 results.

    Args:
        week_16_results: Dict mapping game name to (winner_abbrev, loser_abbrev, scores)
        week_17_results: Optional dict for week 17 results

    Returns:
        Dict with final standings positions for each team
    """
    final_standings = {}

    # Week 16 games determine week 17 matchups. Championship (1st/2nd) is
    # contested by the semi winners and consolation (3rd/4th) by the semi
    # losers; the actual placements are read from the week 17 results.
    if 'semi_1' in week_16_results and 'semi_2' in week_16_results and week_17_results:
        if 'championship' in week_17_results:
            champ = week_17_results['championship']
            final_standings[champ['winner']] = 1
            final_standings[champ['loser']] = 2

        if 'consolation_cup' in week_17_results:
            consolation = week_17_results['consolation_cup']
            final_standings[consolation['winner']] = 3
            final_standings[consolation['loser']] = 4

    # Mid bowl: cumulative scores from weeks 16-17
    if 'mid_bowl_1' in week_16_results and week_17_results and 'mid_bowl_2' in week_17_results:
        mb1 = week_16_results['mid_bowl_1']
        mb2 = week_17_results['mid_bowl_2']

        # Calculate cumulative scores
        team1 = mb1['team1']
        team2 = mb1['team2']
        team1_total = mb1['team1_score'] + mb2.get('team1_score', 0)
        team2_total = mb1['team2_score'] + mb2.get('team2_score', 0)

        # team1 is always the higher (numerically lower) seed in this matchup
        # (seed 5 vs seed 6 - see PLAYOFF_STRUCTURE_2026). The constitution
        # breaks playoff ties by regular-season seeding, so an exact tie must
        # go to team1, not team2. See docs/ROADMAP_2026.md P1.3.
        if team1_total >= team2_total:
            final_standings[team1] = 5
            final_standings[team2] = 6
        else:
            final_standings[team2] = 5
            final_standings[team1] = 6

    # Sewer series -> toilet bowl and 7th place
    if 'sewer_1' in week_16_results and 'sewer_2' in week_16_results and week_17_results:
        # 7th place: winners of sewer series
        if '7th_place' in week_17_results:
            seventh = week_17_results['7th_place']
            final_standings[seventh['winner']] = 7
            final_standings[seventh['loser']] = 8

        # Toilet bowl: losers of sewer series (loser of this game is 10th)
        if 'toilet_bowl' in week_17_results:
            toilet = week_17_results['toilet_bowl']
            final_standings[toilet['winner']] = 9
            final_standings[toilet['loser']] = 10

    return final_standings
