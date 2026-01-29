"""JSON-based scoring for 2026+.

This module provides scoring that reads lineups from JSON files instead of Excel.
Rosters are still sourced from rosters.json (which syncs with Excel for roster management).
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any

from .base_scorer import BaseScorer
from .models import FantasyTeam, PlayerScore


def load_rosters(rosters_path: str | Path) -> dict[str, list[dict[str, Any]]]:
    """Load team rosters from rosters.json.

    Args:
        rosters_path: Path to rosters.json file

    Returns:
        Dict mapping team abbrev to list of player dicts
    """
    rosters_path = Path(rosters_path)
    if not rosters_path.exists():
        raise FileNotFoundError(f'Rosters file not found: {rosters_path}')

    with open(rosters_path) as f:
        return json.load(f)  # type: ignore[no-any-return]


def load_lineup(lineup_path: str | Path, week: int) -> dict[str, dict[str, Any]]:
    """Load lineup submissions for a week.

    Args:
        lineup_path: Path to lineup JSON file (e.g., data/lineups/2026/week_1.json)
        week: Week number (for validation)

    Returns:
        Dict mapping team abbrev to lineup dict with starters per position
    """
    lineup_path = Path(lineup_path)
    if not lineup_path.exists():
        raise FileNotFoundError(f'Lineup file not found: {lineup_path}')

    with open(lineup_path) as f:
        data = json.load(f)

    if data.get('week') != week:
        print(
            f"Warning: Lineup file week ({data.get('week')}) doesn't match expected week ({week})"
        )

    return data.get('lineups', {})  # type: ignore[no-any-return]


def build_fantasy_team_from_json(
    team_abbrev: str,
    rosters: dict[str, list[dict[str, Any]]],
    lineups: dict[str, dict[str, Any]],
    teams_info: Optional[dict[str, dict[str, Any]]] = None,
) -> FantasyTeam:
    """Build a FantasyTeam from JSON roster and lineup data.

    Args:
        team_abbrev: Team abbreviation (e.g., 'GSA')
        rosters: Full rosters dict from rosters.json
        lineups: Week lineups dict from week_N.json
        teams_info: Optional team info dict with name/owner

    Returns:
        FantasyTeam object with players and starter status
    """
    roster = rosters.get(team_abbrev, [])
    lineup = lineups.get(team_abbrev, {})

    # Get team info
    team_info = teams_info.get(team_abbrev, {}) if teams_info else {}
    team_name = team_info.get('name', team_abbrev)
    owner = team_info.get('owner', '')

    # Build starters set from lineup
    starters = set()
    for position, player_names in lineup.items():
        if position in ('submitted_at', 'comment'):
            continue
        for name in player_names:
            starters.add(name)

    # Build players dict
    players: dict[str, list[tuple[str, str, bool]]] = {}

    for player in roster:
        name = player.get('name', '')
        nfl_team = player.get('nfl_team', '')
        position = player.get('position', '')
        is_taxi = player.get('taxi', False)

        if is_taxi:
            # Skip taxi squad players for scoring purposes
            continue

        if position not in players:
            players[position] = []

        is_starter = name in starters
        players[position].append((name, nfl_team, is_starter))

    return FantasyTeam(
        name=team_name,
        owner=owner,
        abbreviation=team_abbrev,
        column_index=0,  # Not used for JSON-based scoring
        players=players,
    )


def score_week_from_json(
    rosters_path: str | Path,
    lineup_path: str | Path,
    season: int,
    week: int,
    teams_info: Optional[dict[str, dict[str, Any]]] = None,
    verbose: bool = True,
) -> tuple[list[FantasyTeam], dict[str, tuple[float, dict[str, list[tuple[PlayerScore, bool]]]]]]:
    """Score all fantasy teams for a week using JSON data sources.

    Args:
        rosters_path: Path to rosters.json
        lineup_path: Path to week lineup JSON (e.g., data/lineups/2026/week_1.json)
        season: NFL season year
        week: Week number
        teams_info: Optional dict mapping team abbrev to {name, owner}
        verbose: Whether to print detailed output

    Returns:
        Tuple of (teams, results) where results maps team name to (total_score, position_scores)
    """
    # Load data
    rosters = load_rosters(rosters_path)
    lineups = load_lineup(lineup_path, week)

    # Build fantasy teams
    teams = []
    for team_abbrev in rosters:
        team = build_fantasy_team_from_json(team_abbrev, rosters, lineups, teams_info)
        teams.append(team)

    if verbose:
        print(f'\nFound {len(teams)} fantasy teams')
        for team in teams:
            started_count = sum(
                1 for players in team.players.values() for _, _, is_started in players if is_started
            )
            print(f'  - {team.name} ({team.abbreviation}): {started_count} started players')

    # Score all teams using shared logic from BaseScorer
    scorer = BaseScorer(season, week)
    results = scorer.score_teams(teams, verbose=verbose)

    return teams, results


def save_week_scores(
    output_path: str | Path,
    week: int,
    teams: list[FantasyTeam],
    results: dict[str, tuple[float, dict]],
    matchups: Optional[list[dict[str, Any]]] = None,
) -> None:
    """Save scored week data to JSON.

    Args:
        output_path: Path to output JSON file
        week: Week number
        teams: List of FantasyTeam objects
        results: Scoring results dict
        matchups: Optional list of matchup dicts for the week
    """
    teams_data = []

    for team in teams:
        if team.name not in results:
            continue

        total, scores = results[team.name]

        roster = []
        for position, player_scores in scores.items():
            for ps, is_starter in player_scores:
                roster.append(
                    {
                        'name': ps.name,
                        'nfl_team': ps.team,
                        'position': position,
                        'score': ps.total_points,
                        'starter': is_starter,
                    }
                )

        teams_data.append(
            {
                'name': team.name,
                'owner': team.owner,
                'abbrev': team.abbreviation,
                'roster': roster,
                'total_score': round(total, 1),
            }
        )

    # Sort by score for ranking
    sorted_teams: list[dict[str, Any]] = sorted(
        teams_data, key=lambda t: float(t['total_score']), reverse=True
    )
    for rank, team_dict in enumerate(sorted_teams, 1):
        team_dict['score_rank'] = rank

    week_data = {
        'week': week,
        'scored_at': datetime.now(timezone.utc).isoformat(),
        'teams': teams_data,
        'has_scores': any(float(t['total_score']) > 0 for t in teams_data),  # type: ignore[arg-type]
    }

    if matchups:
        # Build matchup data with scores
        matchups_data = []
        team_by_abbrev = {t['abbrev']: t for t in teams_data}

        for matchup in matchups:
            t1_abbrev = matchup.get('team1')
            t2_abbrev = matchup.get('team2')

            matchup_data = {
                'team1': team_by_abbrev.get(t1_abbrev, {'abbrev': t1_abbrev}),
                'team2': team_by_abbrev.get(t2_abbrev, {'abbrev': t2_abbrev}),
            }

            if 'bracket' in matchup:
                matchup_data['bracket'] = matchup['bracket']

            matchups_data.append(matchup_data)

        week_data['matchups'] = matchups_data

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump(week_data, f, indent=2)

    print(f'Scores saved to {output_path}')


def update_standings_json(
    standings_path: str | Path,
    week_data_paths: list[str | Path],
    season: int,
) -> list[dict]:
    """Update standings based on scored weeks.

    Args:
        standings_path: Path to standings.json output
        week_data_paths: List of paths to scored week JSON files
        season: Season year

    Returns:
        Updated standings list
    """

    standings = {}
    regular_season_weeks = 15

    for week_path in week_data_paths:
        week_path = Path(week_path)
        if not week_path.exists():
            continue

        with open(week_path) as f:
            week_data = json.load(f)

        week_num = week_data.get('week', 0)
        if week_num > regular_season_weeks or not week_data.get('has_scores'):
            continue

        # Process team scores
        for team in week_data.get('teams', []):
            abbrev = team['abbrev']
            if abbrev not in standings:
                standings[abbrev] = {
                    'name': team['name'],
                    'owner': team.get('owner', ''),
                    'abbrev': abbrev,
                    'rank_points': 0.0,
                    'wins': 0,
                    'losses': 0,
                    'ties': 0,
                    'top_half': 0,
                    'points_for': 0.0,
                    'points_against': 0.0,
                }

        # Process matchups for W/L
        for matchup in week_data.get('matchups', []):
            t1 = matchup.get('team1', {})
            t2 = matchup.get('team2', {})

            if not t1 or not t2:
                continue

            s1 = t1.get('total_score', 0)
            s2 = t2.get('total_score', 0)
            a1 = t1.get('abbrev', '')
            a2 = t2.get('abbrev', '')

            if a1 not in standings or a2 not in standings:
                continue

            standings[a1]['points_for'] += s1
            standings[a1]['points_against'] += s2
            standings[a2]['points_for'] += s2
            standings[a2]['points_against'] += s1

            if s1 > s2:
                standings[a1]['rank_points'] += 1.0
                standings[a1]['wins'] += 1
                standings[a2]['losses'] += 1
            elif s2 > s1:
                standings[a2]['rank_points'] += 1.0
                standings[a2]['wins'] += 1
                standings[a1]['losses'] += 1
            else:
                standings[a1]['rank_points'] += 0.5
                standings[a2]['rank_points'] += 0.5
                standings[a1]['ties'] += 1
                standings[a2]['ties'] += 1

        # Top half scoring
        teams_by_score = sorted(
            week_data.get('teams', []), key=lambda x: x.get('total_score', 0), reverse=True
        )
        num_teams = len(teams_by_score)
        top_half_cutoff = num_teams // 2

        current_rank = 1
        i = 0
        while i < len(teams_by_score):
            current_score = teams_by_score[i].get('total_score', 0)
            tied_teams = []
            while (
                i < len(teams_by_score) and teams_by_score[i].get('total_score', 0) == current_score
            ):
                tied_teams.append(teams_by_score[i])
                i += 1

            tied_positions = list(range(current_rank, current_rank + len(tied_teams)))
            positions_in_top_half = [p for p in tied_positions if p <= top_half_cutoff]

            if positions_in_top_half:
                points_per_team = (0.5 * len(positions_in_top_half)) / len(tied_teams)
                for team in tied_teams:
                    abbrev = team.get('abbrev', '')
                    if abbrev in standings:
                        standings[abbrev]['rank_points'] += points_per_team
                        standings[abbrev]['top_half'] += len(positions_in_top_half) / len(
                            tied_teams
                        )

            current_rank += len(tied_teams)

    # Sort standings
    sorted_standings = sorted(
        standings.values(), key=lambda x: (x['rank_points'], x['points_for']), reverse=True
    )

    # Save to file
    standings_path = Path(standings_path)
    standings_path.parent.mkdir(parents=True, exist_ok=True)

    with open(standings_path, 'w') as f:
        json.dump(
            {
                'updated_at': datetime.now(timezone.utc).isoformat(),
                'standings': sorted_standings,
            },
            f,
            indent=2,
        )

    return sorted_standings
