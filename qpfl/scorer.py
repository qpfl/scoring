"""Excel-based scoring engine."""

from pathlib import Path

from .base_scorer import BaseScorer
from .models import FantasyTeam, PlayerScore


class QPFLScorer(BaseScorer):
    """
    QPFL scoring engine.

    Now inherits from BaseScorer which contains all shared scoring logic.
    This class is kept for backward compatibility.
    """

    pass


def score_week(
    excel_path: str | Path,
    sheet_name: str,
    season: int,
    week: int,
    verbose: bool = True,
) -> tuple[list[FantasyTeam], dict[str, tuple[float, dict[str, list[tuple[PlayerScore, bool]]]]]]:
    """
    Score all fantasy teams for a week from Excel data.

    Args:
        excel_path: Path to Excel file with rosters
        sheet_name: Sheet name (e.g., '2025')
        season: NFL season year
        week: Week number
        verbose: Whether to print detailed output

    Returns:
        Tuple of (teams, results) where results maps team name to (total_score, position_scores)
    """
    from .excel_parser import parse_roster_from_excel

    # Load teams from Excel
    teams = parse_roster_from_excel(str(excel_path), sheet_name)

    # Score all teams using shared logic
    scorer = QPFLScorer(season, week)
    results = scorer.score_teams(teams, verbose=verbose)

    return teams, results
