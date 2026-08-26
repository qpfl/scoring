from .config import (
    get_config,
    get_current_season,
    get_roster_slots,
    get_starter_slots,
    get_trade_deadline_week,
)
from .data_fetcher import NFLDataFetcher, load_snapshot, save_snapshot, snapshot_path
from .excel_parser import parse_roster_from_excel, update_excel_scores
from .json_scorer import (
    apply_score_adjustments,
    build_fantasy_team_from_json,
    load_lineup,
    load_rosters,
    save_week_scores,
    score_week_from_json,
    update_standings_json,
)
from .models import FantasyTeam, PlayerScore
from .projections import (
    WeekProjections,
    calculate_week_projections,
    compact_schedule_rows,
    load_projection_schedule_rows,
)
from .schedule import (
    PLAYOFF_STRUCTURE_2026,
    get_full_schedule,
    get_playoff_schedule,
    get_regular_season_schedule,
    parse_schedule_file,
    resolve_playoff_matchups,
    schedule_path_for_season,
)
from .scorer import QPFLScorer, score_week
from .scoring import (
    score_defense,
    score_head_coach,
    score_kicker,
    score_offensive_line,
    score_skill_player,
)
from .utils import load_json, save_json
from .validators import (
    validate_lineup,
    validate_player_score,
    validate_roster,
    validate_team_score,
)

__all__ = [
    # Models
    'PlayerScore',
    'FantasyTeam',
    # Scoring functions
    'score_skill_player',
    'score_kicker',
    'score_defense',
    'score_head_coach',
    'score_offensive_line',
    # Data fetching
    'NFLDataFetcher',
    'snapshot_path',
    'save_snapshot',
    'load_snapshot',
    # Excel-based (legacy/rosters only)
    'parse_roster_from_excel',
    'update_excel_scores',
    'QPFLScorer',
    'score_week',
    # JSON-based (2026+)
    'score_week_from_json',
    'load_rosters',
    'load_lineup',
    'build_fantasy_team_from_json',
    'save_week_scores',
    'update_standings_json',
    'apply_score_adjustments',
    'WeekProjections',
    'calculate_week_projections',
    'compact_schedule_rows',
    'load_projection_schedule_rows',
    # Schedule
    'parse_schedule_file',
    'get_regular_season_schedule',
    'get_playoff_schedule',
    'get_full_schedule',
    'resolve_playoff_matchups',
    'schedule_path_for_season',
    'PLAYOFF_STRUCTURE_2026',
    # Configuration
    'get_config',
    'get_current_season',
    'get_trade_deadline_week',
    'get_roster_slots',
    'get_starter_slots',
    # Validation
    'validate_roster',
    'validate_lineup',
    'validate_player_score',
    'validate_team_score',
    # Utilities
    'load_json',
    'save_json',
]
