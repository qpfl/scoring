# QPFL Autoscorer

Automated fantasy football scoring for the QPFL using real-time NFL stats from [nflreadpy](https://github.com/nflverse/nflreadpy).

## Installation

```bash
pip install nflreadpy polars openpyxl
```

Or using the project dependencies:

```bash
pip install -e .
```

## Usage

### Basic Usage

Score the current week with detailed output:

```bash
python autoscorer.py --excel "2025 Scores.xlsx" --sheet "Week 13" --season 2025 --week 13
```

### Command Line Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--excel` | `-e` | `2025 Scores.xlsx` | Path to the Excel file with rosters |
| `--sheet` | `-s` | `Week 13` | Sheet name to score |
| `--season` | `-y` | `2025` | NFL season year |
| `--week` | `-w` | `13` | Week number to score |
| `--update` | `-u` | - | Update Excel file with calculated scores |
| `--quiet` | `-q` | - | Suppress detailed output, show only standings |

### Examples

```bash
# Score Week 13 with full breakdown
python autoscorer.py

# Score a different week
python autoscorer.py --sheet "Week 10" --week 10

# Quick standings only
python autoscorer.py --quiet

# Score and save results back to Excel
python autoscorer.py --update
```

## Scoring Rules

### Skill Positions (QB, RB, WR, TE)
All skill positions use the same scoring:
- Passing yards: 1 point per 25 yards
- Rushing yards: 1 point per 10 yards
- Receiving yards: 1 point per 10 yards
- Touchdowns: 6 points each
- Turnovers (INT + fumbles lost): -2 points each
- Two-point conversions: 2 points each

### Kicker (K)
- PATs made: 1 point each
- PATs missed: -2 points each
- FGs 1-29 yards: 1 point each
- FGs 30-39 yards: 2 points each
- FGs 40-49 yards: 3 points each
- FGs 50-59 yards: 4 points each
- FGs 60+ yards: 5 points each
- FGs missed: -1 point each

### Defense/Special Teams (D/ST)
| Points Allowed | Points |
|----------------|--------|
| 0 | +8 |
| 1-9 | +6 |
| 10-13 | +4 |
| 14-17 | +2 |
| 18-31 | -2 |
| 32-35 | -4 |
| 36+ | -6 |

- Turnovers forced: 2 points each
- Sacks: 1 point each
- Safeties: 2 points each
- Blocked punts/FGs: 2 points each
- Blocked PATs: 1 point each
- Defensive TDs: 4 points each

### Head Coach (HC)
| Result | Points |
|--------|--------|
| Win by 20+ | +4 |
| Win by 10-19 | +3 |
| Win by 1-9 | +2 |
| Loss by 1-9 | -1 |
| Loss by 10-20 | -2 |
| Loss by 21+ | -3 |

### Offensive Line (OL)
- Team passing yards: 1 point per 100 yards
- Team rushing yards: 1 point per 50 yards
- Sacks allowed: -1 point each
- Offensive lineman TDs: 6 points each

## Excel File Format

The autoscorer reads rosters from an Excel file with the following structure:

- **Row 2**: Fantasy team names
- **Row 3**: Owner names
- **Row 4**: Team abbreviations
- **Rows 6+**: Player rosters by position (QB, RB, WR, TE, K, D/ST, HC, OL)
- **Bolded players** are considered "started" and will be scored
- **Player format**: `Player Name (TEAM)` (e.g., "Patrick Mahomes II (KC)")

Teams are arranged in columns: A, C, E, G, I, K, M, O, Q, S with corresponding point columns.

## Output

The autoscorer displays:
- Individual player scores with breakdowns
- ✓ indicates player found in stats
- ✗ indicates player not found (bye week, game not played, or name mismatch)
- Final standings ranked by total points

## Notes

- Games that haven't been played yet will show players as "not found"
- Team abbreviation differences (LAR→LA, JAC→JAX) are handled automatically
- Stats are pulled from nflverse data, updated after games complete
