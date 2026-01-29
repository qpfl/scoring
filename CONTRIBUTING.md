# Contributing to QPFL Scoring System

Thank you for your interest in contributing to the QPFL Fantasy Football Scoring System!

## Development Setup

### Prerequisites
- Python 3.10 or higher
- uv (recommended) or pip

### Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/qpfl-scoring.git
cd qpfl-scoring
```

2. Install dependencies using uv (recommended):
```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install project dependencies
uv sync
```

Or using pip:
```bash
pip install -e ".[dev]"
```

### Running Tests

Run the test suite to verify your setup:
```bash
python -m pytest tests/ -v
```

Run tests with coverage report:
```bash
# Install pytest-cov first
pip install pytest-cov

# Run with coverage
python -m pytest tests/ --cov=qpfl --cov-report=html
```

View coverage report by opening `htmlcov/index.html` in your browser.

## Common Tasks

### Scoring a Week

Score a specific week using the JSON-based scorer (2026+):
```bash
python autoscorer_json.py --season 2026 --week 7
```

Score using the Excel-based scorer (2020-2025):
```bash
python autoscorer.py --season 2025 --week 17
```

### Validating Scores

After scoring, validate that calculated scores match expected values:
```bash
python scripts/validate_scores.py --season 2025 --week 17
```

### Exporting Data for Web

Export the current season's data to the website:
```bash
python scripts/export_current.py --season 2026
```

Export all historical data (takes 2-3 minutes):
```bash
python scripts/export_for_web.py
```

### Syncing Rosters

Sync JSON rosters to Excel backup:
```bash
python scripts/sync_rosters_to_excel.py
```

Sync lineups to Excel (bolds started players):
```bash
python scripts/sync_lineups_to_excel.py --season 2026 --week 7
```

## Making Changes

### Before Making Changes

1. Create a feature branch:
```bash
git checkout -b feature/your-feature-name
```

2. Run tests to establish baseline:
```bash
python -m pytest tests/ -v
```

### Development Workflow

1. Make your changes to the codebase
2. Add tests for your changes in `tests/`
3. Run tests to verify nothing broke:
```bash
python -m pytest tests/ -v
```

4. Run linter (if installed):
```bash
ruff check --fix .
```

5. Commit your changes:
```bash
git add .
git commit -m "Brief description of changes"
```

6. Push and create a pull request:
```bash
git push origin feature/your-feature-name
```

## Modifying League Settings

### Changing Scoring Rules

Edit `qpfl/scoring.py` to modify scoring rules. Each position has its own function:
- `score_skill_player()` - QB, RB, WR, TE
- `score_kicker()` - K
- `score_defense()` - D/ST
- `score_head_coach()` - HC
- `score_offensive_line()` - OL

**Important:** After modifying scoring rules, add tests in `tests/test_scoring.py` to verify the changes work correctly.

Example test:
```python
def test_new_scoring_rule(self):
    """Test description."""
    stats = {'stat_name': 100}
    points, breakdown = score_skill_player(stats)
    assert points == expected_value
```

### Updating Roster Limits

Edit `data/league_config.json`:
```json
{
  "roster_slots": {
    "QB": 3,
    "RB": 4,
    ...
  },
  "starter_slots": {
    "QB": 1,
    "RB": 2,
    ...
  }
}
```

The configuration is automatically loaded by the system.

### Changing the Schedule

Edit `schedule.txt`:
```
Week 1
GSA vs. CGK
AYP vs. WJK
...
```

Format: Each week starts with "Week N", followed by matchups on separate lines.

### Updating Current Season

Edit `data/league_config.json`:
```json
{
  "current_season": 2026,
  ...
}
```

This single change updates the season across all components.

### Modifying Trade Deadline

Edit `data/league_config.json`:
```json
{
  "trade_deadline_week": 12,
  ...
}
```

## Adding New Features

### Adding a New Position

Adding a new position (e.g., FLEX) requires changes in multiple places:

1. Update `data/league_config.json`:
```json
{
  "roster_slots": {
    ...
    "FLEX": 1
  },
  "starter_slots": {
    ...
    "FLEX": 1
  }
}
```

2. Add scoring function in `qpfl/scoring.py`:
```python
def score_flex(stats: dict, position: str) -> Tuple[float, Dict[str, float]]:
    """Score a FLEX player (RB/WR/TE)."""
    # Implementation
    pass
```

3. Update scorers to handle FLEX:
- `qpfl/json_scorer.py` - JSON-based scoring
- `qpfl/scorer.py` - Excel-based scoring (if needed)

4. Add tests in `tests/test_scoring.py`:
```python
class TestFlexScoring:
    def test_flex_rb(self):
        """Test FLEX with RB."""
        # Test implementation
        pass
```

5. Update Excel templates (if using Excel-based scoring)

6. Update web frontend (`web/index.html`) to display FLEX

### Adding Validation Rules

Add new validation functions to `qpfl/validators.py`:
```python
def validate_new_rule(data) -> List[str]:
    """
    Validate new rule.

    Returns:
        List of error messages (empty if valid)
    """
    errors = []
    # Validation logic
    return errors
```

Add tests in `tests/test_validators.py`:
```python
def test_new_validation_rule(self):
    """Test new validation rule."""
    errors = validate_new_rule(test_data)
    assert errors == []
```

## Architecture Overview

### Directory Structure
```
/qpfl/                      # Core business logic library
├── constants.py            # League constants (teams, positions)
├── models.py               # Data models (PlayerScore, FantasyTeam)
├── config.py               # Configuration management
├── utils.py                # JSON I/O utilities
├── schemas.py              # Pydantic validation schemas
├── validators.py           # Roster/score validation
├── scoring.py              # Position-specific scoring rules
├── scorer.py               # Excel-based scorer (2020-2025)
├── json_scorer.py          # JSON-based scorer (2026+)
├── data_fetcher.py         # NFL stats API wrapper
└── schedule.py             # Schedule parsing

/scripts/                   # Build & maintenance scripts
├── export_current.py       # Fast current season export
├── export_for_web.py       # Full historical export
├── validate_scores.py      # Score validation
└── sync_*.py               # Data sync utilities

/data/                      # JSON data files (2026+)
├── league_config.json      # Centralized configuration
├── rosters.json            # Current rosters
├── lineups/                # Weekly lineups
├── transaction_log.json    # Transaction history
└── ...

/tests/                     # Test suite
├── test_scoring.py         # Scoring function tests
├── test_validators.py      # Validation tests
└── ...

/web/                       # Static website
├── index.html              # Single-page app
└── data/                   # Exported data for web
```

### Data Flow

1. **Lineup Submission** → API (`api/lineup.py`) → JSON files (`data/lineups/`)
2. **Scoring** → GitHub Actions → `autoscorer_json.py` → NFL stats API → Calculated scores
3. **Export** → `scripts/export_current.py` → Web data (`web/data/`)
4. **Display** → Static website loads JSON → Renders standings/scores

### Two-Era System

The codebase supports two parallel systems:
- **2020-2025**: Excel-based (`scorer.py`, `previous_seasons/*.xlsx`)
- **2026+**: JSON-based (`json_scorer.py`, `data/*.json`)

When modifying scoring rules, update both if historical data needs recalculation.

## Testing Guidelines

### What to Test

**Critical (must have tests):**
- Scoring calculations
- Roster/lineup validation
- Data schema validation
- Configuration loading

**Important (should have tests):**
- Data fetching logic
- Export/sync scripts
- Schedule parsing

**Optional (nice to have):**
- Utility functions
- Helper methods

### Test Structure

```python
class TestFeatureName:
    """Tests for feature description."""

    def test_basic_case(self):
        """Test basic functionality."""
        result = function_to_test(input_data)
        assert result == expected_output

    def test_edge_case(self):
        """Test edge case description."""
        # Test edge case
        pass

    def test_error_handling(self):
        """Test error handling."""
        with pytest.raises(ExpectedError):
            function_to_test(invalid_data)
```

### Running Specific Tests

```bash
# Run single test file
python -m pytest tests/test_scoring.py -v

# Run single test class
python -m pytest tests/test_scoring.py::TestSkillPlayerScoring -v

# Run single test
python -m pytest tests/test_scoring.py::TestSkillPlayerScoring::test_passing_yards_basic -v

# Run tests matching pattern
python -m pytest tests/ -k "kicker" -v
```

## Code Style

### Formatting
- Use 4 spaces for indentation (not tabs)
- Maximum line length: 100 characters
- Use double quotes for strings
- Add docstrings to all functions and classes

### Naming Conventions
- Functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Private methods: `_leading_underscore`

### Documentation
- Add docstrings to all public functions
- Include type hints for function parameters and return values
- Document expected exceptions in docstrings

Example:
```python
def calculate_score(stats: dict, position: str) -> float:
    """
    Calculate fantasy points for a player.

    Args:
        stats: Player statistics dict from nflreadpy
        position: Position code (QB, RB, WR, TE)

    Returns:
        Total fantasy points

    Raises:
        ValueError: If position is invalid
    """
    # Implementation
    pass
```

## Getting Help

- **Issues**: Open an issue on GitHub for bugs or feature requests
- **Questions**: Ask in the league Discord/group chat
- **Documentation**: See README.md and ARCHITECTURE.md

## Pull Request Process

1. Ensure all tests pass
2. Update documentation if needed
3. Add tests for new functionality
4. Keep changes focused and atomic
5. Write clear commit messages
6. Reference any related issues

## License

This project is maintained for the QPFL fantasy football league.
