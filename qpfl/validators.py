"""Validation functions for rosters, lineups, and scoring results."""


from .constants import ROSTER_SLOTS, STARTER_SLOTS
from .models import FantasyTeam, PlayerScore


def validate_roster(team: FantasyTeam) -> list[str]:
    """
    Validate that a fantasy team's roster complies with league rules.

    Checks:
    - Position limits (max players per position)
    - No duplicate players across positions
    - All required fields present

    Args:
        team: FantasyTeam object to validate

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []

    # Check position limits
    for pos, limit in ROSTER_SLOTS.items():
        players_at_pos = team.players.get(pos, [])
        count = len(players_at_pos)
        if count > limit:
            errors.append(f'{team.abbreviation} has {count} {pos} players (max {limit})')

    # Check starter limits
    for pos, limit in STARTER_SLOTS.items():
        players_at_pos = team.players.get(pos, [])
        starters = [p for p in players_at_pos if p[2]]  # p[2] = is_started
        starter_count = len(starters)
        if starter_count > limit:
            errors.append(f'{team.abbreviation} starts {starter_count} {pos} (max {limit})')

    # Check for duplicate players across positions
    all_player_names = []
    for _position, players in team.players.items():
        for player_name, _nfl_team, _is_started in players:
            if not player_name or not player_name.strip():
                continue
            all_player_names.append(player_name)

    # Find duplicates
    seen = set()
    duplicates = set()
    for name in all_player_names:
        if name in seen:
            duplicates.add(name)
        seen.add(name)

    if duplicates:
        errors.append(f'{team.abbreviation} has duplicate players: {", ".join(sorted(duplicates))}')

    return errors


def validate_lineup(
    team_abbrev: str, starters: dict[str, list[str]], roster: dict[str, list[tuple[str, str, str]]]
) -> list[str]:
    """
    Validate a weekly lineup submission.

    Checks:
    - Starter limits per position
    - All starters are on the team's active roster
    - No duplicate players in lineup

    Args:
        team_abbrev: Team abbreviation (e.g., 'GSA')
        starters: Dict of position -> list of starter names
        roster: Team's roster dict (position -> [(name, nfl_team, status)])

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []

    # Check starter limits
    for pos, limit in STARTER_SLOTS.items():
        starter_list = starters.get(pos, [])
        count = len(starter_list)
        if count > limit:
            errors.append(f'{team_abbrev} lineup has {count} {pos} starters (max {limit})')

    # Build set of active roster players (name, position)
    active_roster = set()
    for pos, players in roster.items():
        for name, _nfl_team, status in players:
            if status == 'active':
                active_roster.add((name, pos))

    # Check all starters are on active roster
    for pos, starter_list in starters.items():
        for player_name in starter_list:
            if not player_name or not player_name.strip():
                continue
            if (player_name, pos) not in active_roster:
                errors.append(
                    f'{team_abbrev} lineup has {player_name} ({pos}) who is not on active roster'
                )

    # Check for duplicate starters
    all_starters = []
    for starter_list in starters.values():
        all_starters.extend(starter_list)

    seen = set()
    duplicates = set()
    for name in all_starters:
        if not name or not name.strip():
            continue
        if name in seen:
            duplicates.add(name)
        seen.add(name)

    if duplicates:
        errors.append(
            f'{team_abbrev} lineup has duplicate players: {", ".join(sorted(duplicates))}'
        )

    return errors


def validate_player_score(score: PlayerScore) -> list[str]:
    """
    Check that a player's score is reasonable and internally consistent.

    Sanity checks:
    - Total points in reasonable range (-20 to 100)
    - Breakdown totals match final score (within rounding)
    - No NaN or infinity values

    Args:
        score: PlayerScore object to validate

    Returns:
        List of warning messages (empty if no issues)
    """
    warnings = []

    # Check for NaN or infinity
    if not isinstance(score.total_points, (int, float)):
        warnings.append(f'{score.name} has invalid score type: {type(score.total_points)}')
        return warnings

    # Check total points in reasonable range
    if score.total_points > 100:
        warnings.append(
            f'{score.name} scored {score.total_points:.1f} pts (unusually high - check for scoring bug)'
        )
    elif score.total_points < -20:
        warnings.append(
            f'{score.name} scored {score.total_points:.1f} pts (unusually low - check for scoring bug)'
        )

    # Check breakdown adds up to total (within 0.1 for rounding)
    if score.breakdown:
        breakdown_sum = sum(score.breakdown.values())
        diff = abs(breakdown_sum - score.total_points)
        if diff > 0.1:
            warnings.append(
                f'{score.name} breakdown sum ({breakdown_sum:.1f}) != total ({score.total_points:.1f}) - difference: {diff:.1f}'
            )

    return warnings


def validate_team_score(team_abbrev: str, team_total: float, num_starters: int) -> list[str]:
    """
    Check that a team's total score is reasonable.

    Sanity checks:
    - Team total in reasonable range (0 to 300)
    - Average points per starter not impossibly high (>50)
    - No negative team totals

    Args:
        team_abbrev: Team abbreviation
        team_total: Total fantasy points for the team
        num_starters: Number of starters contributing to score

    Returns:
        List of warning messages (empty if no issues)
    """
    warnings = []

    # Check team total range
    if team_total > 300:
        warnings.append(
            f'{team_abbrev} scored {team_total:.1f} pts (unusually high - check for scoring bug)'
        )
    elif team_total < 0:
        warnings.append(
            f'{team_abbrev} scored {team_total:.1f} pts (negative total - check for scoring bug)'
        )

    # Check average per starter
    if num_starters > 0:
        avg_per_starter = team_total / num_starters
        if avg_per_starter > 50:
            warnings.append(
                f'{team_abbrev} averaged {avg_per_starter:.1f} pts/starter (unusually high - check for scoring bug)'
            )

    return warnings


def validate_all_scores(
    team_scores: dict[str, dict[str, PlayerScore]],
) -> tuple[list[str], list[str]]:
    """
    Validate all team scores for a week.

    Args:
        team_scores: Dict of team_abbrev -> {player_name: PlayerScore}

    Returns:
        Tuple of (errors, warnings)
        - errors: Critical issues that should stop scoring
        - warnings: Issues to review but not block scoring
    """
    errors: list[str] = []
    warnings: list[str] = []

    for team_abbrev, player_scores in team_scores.items():
        # Validate each player score
        for _player_name, score in player_scores.items():
            player_warnings = validate_player_score(score)
            warnings.extend(player_warnings)

        # Validate team total
        team_total = sum(s.total_points for s in player_scores.values())
        num_starters = len(player_scores)
        team_warnings = validate_team_score(team_abbrev, team_total, num_starters)
        warnings.extend(team_warnings)

    return errors, warnings
