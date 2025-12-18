# QPFL Scoring System

Automated fantasy football scoring for the Quarantine Perennial Football League using real-time NFL stats from [nflreadpy](https://github.com/nflverse/nflreadpy).

## Quick Start

```bash
# Install dependencies
uv sync

# Score the current week
uv run python autoscorer.py --week 16 --sheet "Week 16"

# Export data for the website
uv run python -m scripts.export.season 2025
uv run python -m scripts.export.legacy

# Run local development server
cd web && python -m http.server 8000
```

## Installation

Using [uv](https://github.com/astral-sh/uv) (recommended):

```bash
uv sync
```

Or using pip:

```bash
pip install nflreadpy polars openpyxl pandas python-docx
```

## Project Structure

```
scoring/
├── 2025 Scores.xlsx           # Current season Excel workbook
├── previous_seasons/          # Historical Excel files
│   ├── 2024 Scores.xlsx
│   ├── 2023 Scores.xlsx
│   └── 2022 Scores.xlsx
├── autoscorer.py              # CLI for scoring weeks
├── validate_scores.py         # Score validation tool
├── qpfl/                      # Core scoring library
├── scripts/
│   ├── export/                # Modular web export system
│   │   ├── season.py          # Export a single season
│   │   ├── shared.py          # Export static data (constitution, HOF, etc.)
│   │   └── legacy.py          # Generate data.json files
│   ├── export_for_web.py      # Legacy single-file export
│   └── migrate_to_json.py     # Excel → JSON migration
├── data/                      # JSON data (rosters, lineups, trades)
├── docs/                      # Word documents (constitution, standings, etc.)
├── api/                       # Vercel serverless functions
└── web/                       # Static website files
```

## Autoscorer CLI

Score fantasy lineups from the Excel file using real NFL stats:

```bash
uv run python autoscorer.py --week 16 --sheet "Week 16" --season 2025
```

### Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--excel` | `-e` | `2025 Scores.xlsx` | Path to Excel file |
| `--sheet` | `-s` | `Week 13` | Sheet name to score |
| `--season` | `-y` | `2025` | NFL season year |
| `--week` | `-w` | `13` | Week number |
| `--update` | `-u` | - | Save scores back to Excel |
| `--quiet` | `-q` | - | Only show final standings |

### Examples

```bash
# Score and update Excel
uv run python autoscorer.py --week 16 --sheet "Week 16" --update

# Quick standings only
uv run python autoscorer.py --week 16 --sheet "Week 16" --quiet

# Score a playoff week
uv run python autoscorer.py --week 17 --sheet "Championship Week 2.0"
```

## Web Data Export

The website data is split into modular files for efficiency. Historical data only needs to be exported once.

### Export Commands

```bash
# Export current season (run weekly during season)
uv run python -m scripts.export.season 2025
uv run python -m scripts.export.legacy

# Export a historical season (after fixing Excel data)
uv run python -m scripts.export.season 2022
uv run python -m scripts.export.legacy

# Export shared data (constitution, banners, transactions)
uv run python -m scripts.export.shared
uv run python -m scripts.export.legacy

# Regenerate Hall of Fame statistics (analyzes all seasons)
uv run python -m scripts.export.hall_of_fame
uv run python -m scripts.export.legacy

# Full rebuild - all seasons and shared data
uv run python -m scripts.export.shared
uv run python -m scripts.export.season 2025
uv run python -m scripts.export.season 2024
uv run python -m scripts.export.season 2023
uv run python -m scripts.export.season 2022
uv run python -m scripts.export.season 2021
uv run python -m scripts.export.season 2020
uv run python -m scripts.export.hall_of_fame
uv run python -m scripts.export.legacy
```

### Web Data Structure

```
web/
├── data.json              # Current season (2025) - legacy format
├── data_2024.json         # Historical seasons - legacy format
├── data_2023.json
├── data_2022.json
├── index.html             # Single-page app
└── data/
    ├── index.json         # Available seasons manifest
    ├── shared/            # Static data
    │   ├── constitution.json
    │   ├── hall_of_fame.json
    │   ├── banners.json
    │   └── transactions.json
    └── seasons/
        └── {year}/
            ├── meta.json
            ├── standings.json
            ├── rosters.json      # Current season only
            ├── draft_picks.json  # Current season only
            ├── live.json         # Current season only
            └── weeks/
                └── week_{n}.json
```

## Scoring Rules

### Skill Positions (QB, RB, WR, TE)
- Passing yards: 1 point per 25 yards
- Rushing yards: 1 point per 10 yards
- Receiving yards: 1 point per 10 yards
- Touchdowns: 6 points each
- Turnovers (INT + fumbles lost): -2 points each
- Two-point conversions: 2 points each

### Kicker (K)
- PATs made: 1 point
- PATs missed: -2 points
- FGs 1-29 yards: 1 point
- FGs 30-39 yards: 2 points
- FGs 40-49 yards: 3 points
- FGs 50-59 yards: 4 points
- FGs 60+ yards: 5 points
- FGs missed: -1 point

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

The autoscorer reads rosters from Excel with this structure:

- **Row 2**: Fantasy team names
- **Row 3**: Owner names
- **Row 4**: Team abbreviations (GSA, CGK, etc.)
- **Rows 6+**: Player rosters by position
- **Bolded players** are starters (scored)
- **Player format**: `Player Name (TEAM)` (e.g., "Patrick Mahomes II (KC)")

Teams are in columns A, C, E, G, I, K, M, O, Q, S with score columns to their right.

## Score Validation

Compare calculated scores against Excel entries:

```bash
# Validate all weeks
uv run python validate_scores.py --all --summary

# Validate specific week
uv run python validate_scores.py --week 16
```

## Automated Deployment

A GitHub Actions workflow automatically scores games and updates the website.

### Schedule

The workflow runs at specific times aligned with nflverse data updates:
- **Daily**: 5:30 AM ET (after 9 AM UTC data update)
- **After TNF**: 1:00 AM ET Friday
- **Sunday early**: 5:30 PM ET (after early games)
- **Sunday late**: 7:35 PM ET (after late games)
- **After SNF**: 1:00 AM ET Monday
- **After MNF**: 1:00 AM ET Tuesday

### Triggers

1. **Scheduled**: Runs automatically during NFL season (Sep-Feb)
2. **Lineup push**: Runs when `data/lineups/**` files are updated
3. **Manual**: Trigger from Actions tab with optional week override

### Email Notifications

When lineups are submitted via the website, the league receives an email notification. Trade proposals only notify the two teams involved.

**Required GitHub Secrets:**

| Secret | Description |
|--------|-------------|
| `SMTP_USERNAME` | Gmail address for sending emails |
| `SMTP_PASSWORD` | Gmail App Password (not regular password) |
| `GSA_EMAIL` | Griff's email |
| `CGK_EMAIL` | Kaminska's email |
| `CWR_EMAIL` | Reardon's email |
| `AYP_EMAIL` | Arnav's email |
| `AST_EMAIL` | Anagh's email |
| `WJK_EMAIL` | Bill's email |
| `SLS_EMAIL` | Stephen's email |
| `RPA_EMAIL` | Ryan's email |
| `S_T_EMAIL` | Spencer/Tim's emails (note: S/T → S_T) |
| `J_J_EMAIL` | Joe/Joe's emails (note: J/J → J_J) |

**Multiple emails per team:** For teams with two owners, separate emails with a comma:
```
S_T_EMAIL=spencer@example.com,tim@example.com
J_J_EMAIL=joe1@example.com,joe2@example.com
```

**Gmail App Password Setup:**
1. Enable 2-Factor Authentication on your Google account
2. Go to https://myaccount.google.com/apppasswords
3. Generate a new app password for "Mail"

## Lineup Submission API

League members can submit lineups via the website, which uses Vercel serverless functions.

### Vercel Setup

1. Import this repository to [Vercel](https://vercel.com)
2. Set environment variables:

| Variable | Description |
|----------|-------------|
| `SKYNET_PAT` | GitHub PAT with `repo` scope |
| `REPO_OWNER` | GitHub username |
| `TEAM_PASSWORD_{ABBREV}` | Password for each team (e.g., `TEAM_PASSWORD_GSA`) |

Note: Slashes become underscores (S/T → `TEAM_PASSWORD_S_T`)

### API Endpoints

- `POST /api/lineup` - Submit weekly lineup
- `POST /api/transaction` - Submit roster transaction

## Notes

- Games not yet played show players as "not found"
- Team abbreviation differences (LAR→LA, JAC→JAX) are handled automatically
- Stats are pulled from nflverse, updated after games complete
- Play-by-play data is used for accurate sack counts and turnover detection
- Bench player scores are calculated for historical seasons using nflreadpy
