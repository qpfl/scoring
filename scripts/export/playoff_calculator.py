"""Playoff bracket calculation and matchup generation."""


def get_playoff_matchups(
    standings: list[dict], week_num: int, week_16_results: dict | None = None
) -> list[dict]:
    """
    Generate playoff matchups based on seeding.

    Playoff Structure:
    - Week 16:
      - Championship bracket: Seeds 1-4 (1v4, 2v3)
      - Mid bowl: Seeds 5-6
      - Sewer series: Seeds 7-8
      - Toilet bowl: Seeds 9-10
    - Week 17:
      - Championship: Winners from week 16
      - Consolation: Losers from week 16
      - Plus other bracket finals

    Args:
        standings: List of team standings dicts (sorted by rank)
        week_num: Week number (16 or 17)
        week_16_results: Week 16 results for determining week 17 matchups

    Returns:
        List of matchup dicts with home/away teams and bracket info
    """
    matchups = []

    if week_num == 16:
        # Championship bracket semifinals
        matchups.append(
            {'home': standings[0]['team'], 'away': standings[3]['team'], 'bracket': 'Championship'}
        )
        matchups.append(
            {'home': standings[1]['team'], 'away': standings[2]['team'], 'bracket': 'Championship'}
        )

        # Mid bowl
        matchups.append(
            {'home': standings[4]['team'], 'away': standings[5]['team'], 'bracket': 'Mid Bowl'}
        )

        # Sewer series
        matchups.append(
            {'home': standings[6]['team'], 'away': standings[7]['team'], 'bracket': 'Sewer Series'}
        )

        # Toilet bowl
        matchups.append(
            {'home': standings[8]['team'], 'away': standings[9]['team'], 'bracket': 'Toilet Bowl'}
        )

    elif week_num == 17 and week_16_results:
        # Determine championship matchup (winners of 1v4 and 2v3)
        championship_winner_1 = week_16_results.get('championship_1_winner')
        championship_winner_2 = week_16_results.get('championship_2_winner')

        if championship_winner_1 and championship_winner_2:
            matchups.append(
                {
                    'home': championship_winner_1,
                    'away': championship_winner_2,
                    'bracket': 'Championship',
                }
            )

        # Consolation (losers from championship bracket)
        championship_loser_1 = week_16_results.get('championship_1_loser')
        championship_loser_2 = week_16_results.get('championship_2_loser')

        if championship_loser_1 and championship_loser_2:
            matchups.append(
                {
                    'home': championship_loser_1,
                    'away': championship_loser_2,
                    'bracket': 'Consolation',
                }
            )

        # Other bracket finals would be determined similarly

    return matchups


def adjust_standings_for_playoffs(
    standings: list[dict], season: int, weeks: list[dict]
) -> list[dict]:
    """
    Adjust standings to reflect playoff performance.

    In playoffs, wins/losses still affect final standings but not
    in the same way as regular season.

    Args:
        standings: Current standings
        season: Season year
        weeks: All week data including playoff weeks

    Returns:
        Adjusted standings with playoff results incorporated
    """
    # Find playoff weeks (16, 17)
    playoff_weeks = [w for w in weeks if w.get('week') in [16, 17]]

    if not playoff_weeks:
        return standings

    # Adjust standings based on playoff results
    # This would need more complex logic based on your specific rules
    # For now, just return standings as-is
    # TODO: Implement playoff-specific standings adjustments

    return standings


def determine_playoff_seeds(standings: list[dict]) -> dict[str, int]:
    """
    Determine playoff seeding for all teams.

    Args:
        standings: Standings sorted by rank

    Returns:
        Dict mapping team abbreviation -> seed number (1-10)
    """
    seeds = {}
    for i, team_standing in enumerate(standings):
        team = team_standing['team']
        seeds[team] = i + 1

    return seeds


def get_bracket_for_seed(seed: int) -> str:
    """
    Get playoff bracket name for a given seed.

    Args:
        seed: Seed number (1-10)

    Returns:
        Bracket name (Championship, Mid Bowl, Sewer Series, Toilet Bowl)
    """
    if seed <= 4:
        return 'Championship'
    elif seed <= 6:
        return 'Mid Bowl'
    elif seed <= 8:
        return 'Sewer Series'
    else:
        return 'Toilet Bowl'
