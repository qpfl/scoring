"""Constants and mappings for QPFL autoscorer."""

from pathlib import Path

# =============================================================================
# FILE PATHS
# =============================================================================

# Base paths (relative to qpfl/ directory)
QPFL_DIR = Path(__file__).parent
PROJECT_DIR = QPFL_DIR.parent
WEB_DIR = PROJECT_DIR / 'web'
DATA_DIR = PROJECT_DIR / 'data'
DOCS_DIR = PROJECT_DIR / 'docs'

# Output paths
WEB_DATA_DIR = WEB_DIR / 'data'
SHARED_DIR = WEB_DATA_DIR / 'shared'
SEASONS_DIR = WEB_DATA_DIR / 'seasons'

# =============================================================================
# QPFL TEAM CONSTANTS
# =============================================================================

# All QPFL team abbreviations
ALL_TEAMS = ['GSA', 'WJK', 'RPA', 'S/T', 'CGK', 'AST', 'CWR', 'J/J', 'SLS', 'AYP']

# Team abbreviation to owner name mapping
TEAM_TO_OWNER = {
    'GSA': 'Griffin',
    'CGK': 'Kaminska',
    'CWR': 'Connor',
    'AYP': 'Arnav',
    'AST': 'Anagh',
    'WJK': 'Bill',
    'SLS': 'Stephen',
    'RPA': 'Ryan',
    'S/T': 'Spencer/Tim',
    'J/J': 'Joe/Joe',
}

# Owner name to team abbreviation mapping
OWNER_TO_TEAM = {v: k for k, v in TEAM_TO_OWNER.items()}

# Team code aliases (for parsing variations in data)
TEAM_ALIASES = {
    'T/S': 'S/T',
    'SPY': 'AYP',
}

# =============================================================================
# NFL TEAM CONSTANTS
# =============================================================================

# NFL team name to abbreviation mapping
NFL_TEAM_ABBREV_MAP = {
    'Arizona Cardinals': 'ARI',
    'Atlanta Falcons': 'ATL',
    'Baltimore Ravens': 'BAL',
    'Buffalo Bills': 'BUF',
    'Carolina Panthers': 'CAR',
    'Chicago Bears': 'CHI',
    'Cincinnati Bengals': 'CIN',
    'Cleveland Browns': 'CLE',
    'Dallas Cowboys': 'DAL',
    'Denver Broncos': 'DEN',
    'Detroit Lions': 'DET',
    'Green Bay Packers': 'GB',
    'Houston Texans': 'HOU',
    'Indianapolis Colts': 'IND',
    'Jacksonville Jaguars': 'JAC',
    'Kansas City Chiefs': 'KC',
    'Las Vegas Raiders': 'LV',
    'Los Angeles Chargers': 'LAC',
    'Los Angeles Rams': 'LAR',
    'Miami Dolphins': 'MIA',
    'Minnesota Vikings': 'MIN',
    'New England Patriots': 'NE',
    'New Orleans Saints': 'NO',
    'New York Giants': 'NYG',
    'New York Jets': 'NYJ',
    'Philadelphia Eagles': 'PHI',
    'Pittsburgh Steelers': 'PIT',
    'San Francisco 49ers': 'SF',
    'Seattle Seahawks': 'SEA',
    'Tampa Bay Buccaneers': 'TB',
    'Tennessee Titans': 'TEN',
    'Washington Commanders': 'WAS',
}

# Reverse mapping
NFL_ABBREV_TO_TEAM = {v: k for k, v in NFL_TEAM_ABBREV_MAP.items()}

# Team abbreviation normalization (Excel format -> nflreadpy format)
NFL_ABBREV_NORMALIZE = {
    'LAR': 'LA',  # Los Angeles Rams
    'JAC': 'JAX',  # Jacksonville Jaguars
}

# Legacy aliases for backward compatibility
TEAM_ABBREV_MAP = NFL_TEAM_ABBREV_MAP
ABBREV_TO_TEAM = NFL_ABBREV_TO_TEAM
TEAM_ABBREV_NORMALIZE = NFL_ABBREV_NORMALIZE

# =============================================================================
# EXCEL LAYOUT CONSTANTS
# =============================================================================

# Position rows in the Excel spreadsheet: {position: (header_row, [player_rows])}
POSITION_ROWS = {
    'QB': (6, [7, 8, 9]),
    'RB': (11, [12, 13, 14, 15]),
    'WR': (17, [18, 19, 20, 21, 22]),
    'TE': (24, [25, 26, 27]),
    'K': (29, [30, 31]),
    'D/ST': (33, [34, 35]),
    'HC': (37, [38, 39]),
    'OL': (41, [42, 43]),
}

# Taxi squad rows in Excel: [(position_row, player_row), ...]
TAXI_ROWS = [(48, 49), (50, 51), (52, 53), (54, 55)]

# Team columns in the Excel spreadsheet (1-based: A=1, C=3, etc.)
TEAM_COLUMNS = [1, 3, 5, 7, 9, 11, 13, 15, 17, 19]

# =============================================================================
# ROSTER CONFIGURATION
# =============================================================================

# Maximum roster slots per position
ROSTER_SLOTS = {
    'QB': 3,
    'RB': 4,
    'WR': 5,
    'TE': 3,
    'K': 2,
    'D/ST': 2,
    'HC': 2,
    'OL': 2,
}

# Starter slots per position
STARTER_SLOTS = {
    'QB': 1,
    'RB': 2,
    'WR': 3,
    'TE': 1,
    'K': 1,
    'D/ST': 1,
    'HC': 1,
    'OL': 1,
}

# Position display order
POSITION_ORDER = ['QB', 'RB', 'WR', 'TE', 'K', 'D/ST', 'HC', 'OL']

# =============================================================================
# SEASON CONFIGURATION
# =============================================================================

# Current season (update annually)
CURRENT_SEASON = 2025

# Regular season weeks
REGULAR_SEASON_WEEKS = 15

# Playoff weeks
PLAYOFF_WEEKS = [16, 17]

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def normalize_team_code(team: str) -> str:
    """Normalize a team code to its canonical form."""
    team = str(team).strip().upper()
    return TEAM_ALIASES.get(team, team)


def ensure_dirs():
    """Create output directories if they don't exist."""
    SHARED_DIR.mkdir(parents=True, exist_ok=True)
    SEASONS_DIR.mkdir(parents=True, exist_ok=True)
