# QPFL Scoring System

Automated fantasy football scoring for the Quarantine Perennial Football League using real-time NFL stats from [nflreadpy](https://github.com/nflverse/nflreadpy).

## Quick Start

```bash
# Install dependencies
uv sync

# Run local development server
cd web && python -m http.server 8000
```

## Two Eras of QPFL Scoring

The scoring system has two distinct modes based on season:

| Era | Seasons | Data Source | Scoring | Notes |
|-----|---------|-------------|---------|-------|
| **Historical** | 2020-2025 | Excel files | `autoscorer.py` | Lineups bolded in Excel |
| **Modern** | 2026+ | JSON files | `autoscorer_json.py` | All data via website |

---

## 2026+ Season (Modern - JSON-Based)

Starting in 2026, all league operations happen through the website:

### Data Flow

```
Website Submissions
       │
       ├──► data/lineups/2026/week_N.json    (weekly lineups)
       ├──► data/transaction_log.json        (FA pickups, taxi activations)
       ├──► data/pending_trades.json         (trades)
       └──► data/rosters.json                (roster state)
       │
       ▼
  autoscorer_json.py  ──► web/data/seasons/2026/weeks/
       │
       ▼
  export_current.py   ──► web/data.json
       │
       ▼
  sync_rosters_to_excel.py ──► Rosters.xlsx (backup only)
```

### Commands

```bash
# Score a week (JSON-based)
uv run python autoscorer_json.py --season 2026 --week 1

# Score and update standings
uv run python autoscorer_json.py --season 2026 --week 1 --update-standings

# Export current season to web
uv run python scripts/export_current.py --season 2026

# Sync roster changes to Excel backup
uv run python scripts/sync_rosters_to_excel.py
```

### Starting a New Season (2026+)

1. After the draft, create `Rosters.xlsx` with all team rosters
2. Initialize JSON rosters:
   ```bash
   # Create data/rosters.json from Excel
   uv run python scripts/init_rosters_from_excel.py
   ```
3. Create lineup directory: `data/lineups/2026/`
4. Update workflow: Set `CURRENT_SEASON: '2026'` in `.github/workflows/score.yml`

### Key Files (2026+)

| File | Purpose |
|------|---------|
| `data/rosters.json` | Current roster state (source of truth) |
| `data/lineups/{year}/week_N.json` | Weekly lineup submissions |
| `data/transaction_log.json` | All roster transactions |
| `data/pending_trades.json` | Active trade proposals |
| `data/trade_blocks.json` | Team trade preferences |
| `Rosters.xlsx` | Excel backup (no scores, no bold) |

---

## 2020-2025 Seasons (Historical - Excel-Based)

Historical seasons use Excel files as the source of truth.

### Data Flow

```
Excel Scores.xlsx (bolded starters)
       │
       ▼
  autoscorer.py  ──► Updates scores in Excel
       │
       ▼
  export_for_web.py  ──► web/data.json
```

### Commands

```bash
# Score a week from Excel
uv run python autoscorer.py --week 17 --sheet "Week 17" --update

# Export current season (2025) from Excel
uv run python scripts/export_for_web.py

# Export with all historical team stats
uv run python scripts/export_for_web.py --all

# Re-export a specific historical season (if Excel was fixed)
uv run python scripts/export_for_web.py --reexport-historical 2022
```

### Autoscorer Options (Excel)

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--excel` | `-e` | `2025 Scores.xlsx` | Path to Excel file |
| `--sheet` | `-s` | `Week N` | Sheet name to score |
| `--season` | `-y` | `2025` | NFL season year |
| `--week` | `-w` | `13` | Week number |
| `--update` | `-u` | - | Save scores back to Excel |
| `--quiet` | `-q` | - | Only show final standings |

### Excel File Format

- **Row 2**: Fantasy team names
- **Row 3**: Owner names
- **Row 4**: Team abbreviations (GSA, CGK, etc.)
- **Rows 6+**: Player rosters by position
- **Bolded players** are starters (scored)
- **Player format**: `Player Name (TEAM)` (e.g., "Patrick Mahomes II (KC)")

---

## Installation

Using [uv](https://github.com/astral-sh/uv) (recommended):

```bash
uv sync
```

Or using pip:

```bash
pip install nflreadpy polars openpyxl pandas
```

## Project Structure

```
scoring/
├── autoscorer.py              # Excel-based CLI (2020-2025)
├── autoscorer_json.py         # JSON-based CLI (2026+)
├── validate_scores.py         # Score validation tool
├── qpfl/                      # Core scoring library
│   ├── constants.py           # All shared constants (teams, positions, paths)
│   ├── scorer.py              # Main scoring engine
│   ├── scoring.py             # Position-specific scoring rules
│   ├── data_fetcher.py        # NFL data via nflreadpy
│   ├── json_scorer.py         # JSON-based scoring (2026+)
│   └── roster_sync.py         # Roster sync utilities
├── scripts/
│   ├── export_current.py      # Lightweight current season export (2026+)
│   ├── export_for_web.py      # Full export (historical, frozen)
│   ├── export_hall_of_fame.py # Generate HOF statistics
│   ├── init_rosters_from_excel.py   # Initialize rosters.json from Excel
│   ├── sync_rosters_to_excel.py     # JSON → Excel roster backup
│   └── sync_lineups_to_excel.py     # JSON → Excel lineup sync (2025)
├── data/                      # JSON data (rosters, lineups, trades)
├── api/                       # Vercel serverless functions
├── web/                       # Static website files
├── 2025 Scores.xlsx           # 2025 season Excel
├── Rosters.xlsx               # Roster template (2026+)
└── previous_seasons/          # Historical Excel files
```

## Web Data Structure

```
web/
├── data.json              # Current season data
├── data_{year}.json       # Historical seasons (legacy)
├── index.html             # Single-page app
└── data/
    ├── index.json         # Available seasons
    ├── shared/            # Static data (no Word docs)
    │   ├── constitution.json
    │   ├── hall_of_fame.json
    │   ├── banners.json
    │   └── transactions.json
    └── seasons/{year}/
        ├── meta.json
        ├── standings.json
        ├── rosters.json
        ├── draft_picks.json
        └── weeks/week_{n}.json
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

## Automated Deployment

A GitHub Actions workflow automatically scores games and updates the website.

### Schedule

Runs at specific times aligned with nflverse data updates:
- **Daily**: 5:30 AM ET
- **After TNF**: 1:00 AM ET Friday
- **Sunday early**: 5:30 PM ET
- **Sunday late**: 7:35 PM ET
- **After SNF**: 1:00 AM ET Monday
- **After MNF**: 1:00 AM ET Tuesday

### Triggers

1. **Scheduled**: Runs automatically during NFL season (Sep-Feb)
2. **Lineup push**: Runs when `data/lineups/**` files are updated
3. **Trade/transaction push**: Runs when `data/pending_trades.json` or `data/transaction_log.json` are updated
4. **Manual**: Trigger from Actions tab with optional week override

### Workflow Configuration

Key environment variables in `.github/workflows/score.yml`:

```yaml
env:
  CURRENT_SEASON: '2025'  # Change to '2026' when new season starts
  DISABLE_EMAILS: 'false' # Set to 'true' to only email GSA (testing)
```

### Email Notifications

When lineups/transactions are submitted, the league receives email notifications.

**Required GitHub Secrets:**

| Secret | Description |
|--------|-------------|
| `SMTP_USERNAME` | Gmail address for sending |
| `SMTP_PASSWORD` | Gmail App Password |
| `{TEAM}_EMAIL` | Each team's email (e.g., `GSA_EMAIL`) |

## Lineup Submission API

League members submit lineups/transactions via the website using Vercel serverless functions.

### Vercel Setup

1. Import repository to [Vercel](https://vercel.com)
2. Set environment variables:

| Variable | Description |
|----------|-------------|
| `SKYNET_PAT` | GitHub PAT with `repo` scope |
| `REPO_OWNER` | GitHub username |
| `TEAM_PASSWORD_{ABBREV}` | Password per team (e.g., `TEAM_PASSWORD_GSA`) |

### API Endpoints

- `POST /api/lineup` - Submit weekly lineup
- `POST /api/transaction` - Submit roster transaction (FA, taxi, trade)

## Score Validation

Compare calculated scores against Excel entries:

```bash
# Validate all weeks
uv run python validate_scores.py --all --summary

# Validate specific week
uv run python validate_scores.py --week 16
```

## Notes

- Games not yet played show players as "not found"
- Team abbreviation differences (LAR→LA, JAC→JAX) handled automatically
- Stats from nflverse, updated after games complete
- Historical seasons (2020-2025) are frozen; use `--reexport-historical` only if Excel was fixed
