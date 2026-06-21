# QPFL Scoring System

Automated fantasy football scoring for the Quarantine Perennial Football League using real-time NFL stats from [nflreadpy](https://github.com/nflverse/nflreadpy). Controls the QPFL website at the GitHub Pages deployment.

## Quick Start

```bash
# Install dependencies
uv sync

# Run local development server
cd web && python -m http.server 8000
```

---

## Website Features

The website is a single-page app with a season selector (top right) to view any season from 2020 onward.

### Home
Current week's matchups and scores, league standings summary, and a recent transactions feed. During the offseason, shows the championship recap, final standings, draft order for the upcoming season, and top performers.

### Matchups
- **Week View**: All matchups for the selected week with player-by-player scoring breakdowns. Use the week selector to navigate.
- **Schedule**: Full regular-season schedule grid (current season only).

### Standings
Full standings table with wins, losses, points for, points against, rank points, expected W/L (xW-xL), luck rating, and strength of schedule. Includes playoff odds (Monte Carlo simulation) during the regular season.

### Teams
- **All Rosters**: Full grid of all 10 team rosters.
- **Compare**: Side-by-side roster comparison tool — select two teams to compare.
- **Roster**: Individual team roster with player positions and NFL teams.
- **Trade Block**: Teams can list players they're willing to trade and what they're seeking.
- **Team Hall of Fame**: All-time records and achievements for a specific team.

### Stats
- **Player Leaders**: Sortable table of top-scoring players by position.
- **Team Stats**: PPG, record, and other aggregate team stats for the season.

### Transactions
Full historical transaction log (trades, FA pickups, taxi activations) across all seasons with search and filter. Click any transaction to expand details.

### Hall of Fame
- **Records**: All-time league records (highest single-week score, most points in a season, etc.).
- **Banner Room**: Championship and bowl winners by year.
- **Constitution**: League rules and bylaws.

### Drafts
- **Draft History**: Full draft board by year with every pick.
- **Draft Challenge**: NFL Draft Challenge results and scoring.

### Manage Rosters *(current season only, password-protected)*
- **Set Lineup**: Select weekly starters (1 QB, 2 RB, 2 WR, 1 TE, 1 K, 1 D/ST, 1 HC, 1 OL) and submit. Triggers automatic scoring. Players whose NFL game has already kicked off are locked server-side and can't be added to or dropped from the lineup (enforced from kickoff times published in `web/data.json`, not the client).
- **Taxi Squad**: Activate a taxi squad player to the active roster (must release a player at the same position).
- **Free Agents**: Pick up a free agent player (must release a player at the same position).
- **Propose Trade**: Select players and draft picks to give and receive, add conditions and a comment, submit to the other team.
- **Pending Trades**: View and accept or reject incoming trade proposals.
- **Trade Block**: Set which players you're willing to trade and what positions/players you're seeking.

---

## Automation

### How Scoring Works

Scoring runs automatically via GitHub Actions. No manual intervention is needed during the regular season.

**Triggers:**
1. **Scheduled** — Runs multiple times per week timed to when nflverse data updates after games:
   - Daily: 5:30 AM ET (catches late stat corrections)
   - After TNF: 1:00 AM ET Friday
   - Sunday early: 5:30 PM ET
   - Sunday late: 7:35 PM ET
   - After SNF: 1:00 AM ET Monday
   - After MNF: 1:00 AM ET Tuesday
2. **Lineup submission** — Fires immediately when any team submits a lineup via the website.
3. **Roster/trade changes** — Fires when transactions or trades are committed.
4. **Manual** — Can be triggered from the GitHub Actions tab with an optional week override.

**What the workflow does each run:**
1. Determines the current NFL week (via nflreadpy, overridable via manual input)
2. Scores the week using player stats from nflverse
3. Updates standings
4. Backs up rosters to `Rosters.xlsx`
5. Exports scores and standings to `web/data.json`
6. Commits changes and deploys to GitHub Pages

### Email Notifications

When lineups or transactions are submitted, the league automatically receives emails:
- **Lineup submitted**: Sent to all teams showing who started what
- **Trade proposed**: Sent to proposer + partner with full trade details
- **Trade accepted/rejected**: Sent to relevant teams
- **Roster move (FA/taxi)**: Sent to all teams

**Required GitHub Secrets:**

| Secret | Description |
|--------|-------------|
| `SMTP_USERNAME` | Gmail address for sending |
| `SMTP_PASSWORD` | Gmail App Password |
| `GSA_EMAIL`, `CGK_EMAIL`, etc. | Each team's email address |

To test without emailing the whole league: set `DISABLE_EMAILS: 'true'` in `score.yml` — emails go only to GSA.

---

## Season Operations

### Offseason Player Team Updates

During the offseason, players change teams via trades, free agency, and cuts. A scheduled workflow automatically updates the `nfl_team` field for every skill-position player in `data/rosters.json` to reflect their current team.

**Schedule:** Runs on the 1st of each month, February through August.

**What it updates:**
- QB, RB, WR, TE, K: looked up in the nflreadpy player/roster database
- HC (head coaches): looked up via recent schedule data
- D/ST, OL: skipped (these are team-based entries, not individual players)

**Safety:** If more than 35% of players can't be matched (usually means the new season's data isn't seeded yet in nflverse), the script aborts without writing changes.

**Manual run:** Go to GitHub Actions → "QPFL Update Player Teams" → Run workflow. Supports a `dry_run` option to preview changes without saving.

```bash
# Run locally
python scripts/update_player_teams.py

# Preview only
python scripts/update_player_teams.py --dry-run

# Specify season explicitly
python scripts/update_player_teams.py --season 2027
```

---

### Starting a New Season (one-click)

Go to **GitHub Actions → QPFL Season Transition → Run workflow**, enter the new season year (e.g., `2027`), and click Run.

The workflow automatically:
- Finalizes the previous season's Hall of Fame stats
- Archives previous season data (`data_2026.json`)
- Creates the new season directory structure
- Updates `CURRENT_SEASON` in `score.yml`, `api/transaction.py`, and `api/lineup.py`
- Resets pending trades
- Creates `data/lineups/2027/` so lineup submissions work immediately
- Updates `data/league_config.json` with the new season year
- Commits, pushes, and deploys to GitHub Pages

**After running the workflow, two manual steps remain:**
1. **After the draft:** Run `python scripts/init_rosters_from_excel.py` to populate `data/rosters.json` from the draft Excel file.
2. **When the NFL schedule releases (mid-summer):** Add the QPFL matchup schedule to `web/data/seasons/{year}/meta.json`.

### Manual Season Transition (if needed)

```bash
# Dry run first to see what will change
python scripts/create_new_season.py 2027 --dry-run

# Apply changes
python scripts/create_new_season.py 2027
```

### Workflow Configuration

Key environment variables in `.github/workflows/score.yml`:

```yaml
env:
  CURRENT_SEASON: '2026'  # Updated automatically by season-transition workflow
  DISABLE_EMAILS: 'false' # Set 'true' to only email GSA during testing
```

---

## Two Eras of QPFL Scoring

| Era | Seasons | Data Source | Scoring Engine |
|-----|---------|-------------|----------------|
| **Historical** | 2020–2025 | Excel files | `autoscorer.py` |
| **Modern** | 2026+ | JSON files | `autoscorer_json.py` |

### Modern Era (2026+) — JSON-Based

All league operations flow through the website. Data is stored in JSON files committed to the repo via the Vercel API.

**Data flow:**
```
Website → Vercel API → GitHub (JSON files) → GitHub Actions → web/data.json → GitHub Pages
```

**Commands:**
```bash
# Score a week
uv run python autoscorer_json.py --season 2026 --week 1 --update-standings

# Export current season to web
uv run python scripts/export_current.py --season 2026

# Sync roster changes to Excel backup
uv run python scripts/sync_rosters_to_excel.py
```

**Key data files:**

| File | Purpose |
|------|---------|
| `data/rosters.json` | Current roster state (source of truth) |
| `data/lineups/{year}/week_N.json` | Weekly lineup submissions |
| `data/transaction_log.json` | All roster transactions |
| `data/pending_trades.json` | Active trade proposals |
| `data/trade_blocks.json` | Team trade preferences |
| `data/league_config.json` | Season settings (current year, trade deadline, roster slots) |
| `Rosters.xlsx` | Excel backup (no scores) |

### Historical Era (2020–2025) — Excel-Based

Frozen seasons. Only re-export if the Excel source was corrected.

**Commands:**
```bash
# Score a week from Excel (2025)
uv run python autoscorer.py --week 17 --sheet "Week 17" --update

# Re-export a historical season if Excel was fixed
uv run python scripts/export_for_web.py --reexport-historical 2022

# Full export (all historical + current)
uv run python scripts/export_for_web.py --all
```

**Autoscorer options (Excel):**

| Option | Default | Description |
|--------|---------|-------------|
| `--excel` | `2025 Scores.xlsx` | Path to Excel file |
| `--sheet` | `Week N` | Sheet name |
| `--week` | — | Week number |
| `--update` | — | Save scores back to Excel |

**Excel format:**
- Row 2: Fantasy team names
- Row 3: Owner names
- Row 4: Team abbreviations (GSA, CGK, etc.)
- Rows 6+: Player rosters by position
- **Bolded players** are starters (scored)
- Player format: `Player Name (TEAM)` e.g. `Patrick Mahomes II (KC)`

---

## Scoring Rules

### Skill Positions (QB, RB, WR, TE)
- Passing yards: 1 pt / 25 yds
- Rushing yards: 1 pt / 10 yds
- Receiving yards: 1 pt / 10 yds
- Touchdowns: 6 pts
- Turnovers (INT + fumbles lost): −2 pts each
- Two-point conversions: 2 pts

### Kicker (K)
- PATs made: 1 pt | PATs missed: −2 pts
- FGs 1–29 yds: 1 pt | 30–39: 2 pts | 40–49: 3 pts | 50–59: 4 pts | 60+: 5 pts
- FGs missed: −1 pt

### Defense / Special Teams (D/ST)

| Points Allowed | Fantasy Points |
|----------------|---------------|
| 0 | +8 |
| 1–9 | +6 |
| 10–13 | +4 |
| 14–17 | +2 |
| 18–31 | −2 |
| 32–35 | −4 |
| 36+ | −6 |

- Turnovers forced: 2 pts each | Sacks: 1 pt each | Safeties: 2 pts each
- Blocked punts/FGs: 2 pts | Blocked PATs: 1 pt | Defensive TDs: 4 pts

### Head Coach (HC)

| Result | Points |
|--------|--------|
| Win by 20+ | +4 |
| Win by 10–19 | +3 |
| Win by 1–9 | +2 |
| Loss by 1–9 | −1 |
| Loss by 10–20 | −2 |
| Loss by 21+ | −3 |

### Offensive Line (OL)
- Team passing yards: 1 pt / 100 yds
- Team rushing yards: 1 pt / 50 yds
- Sacks allowed: −1 pt each
- OL TDs: 6 pts each

---

## Roster Configuration

| Position | Total Slots | Starting Slots |
|----------|-------------|----------------|
| QB | 3 | 1 |
| RB | 4 | 2 |
| WR | 5 | 2 |
| TE | 3 | 1 |
| K | 2 | 1 |
| D/ST | 2 | 1 |
| HC | 2 | 1 |
| OL | 2 | 1 |

Plus 4 taxi squad slots for developing players.

---

## Installation

Using [uv](https://github.com/astral-sh/uv) (recommended):

```bash
uv sync
```

Or with pip:

```bash
pip install nflreadpy polars openpyxl pandas
```

---

## Vercel Setup

The website's Manage Rosters feature uses Vercel serverless functions to write data back to the repo.

1. Import repository to [Vercel](https://vercel.com)
2. Set environment variables:

| Variable | Description |
|----------|-------------|
| `SKYNET_PAT` | GitHub PAT with `repo` scope |
| `REPO_OWNER` | GitHub username |
| `TEAM_PASSWORD_{ABBREV}` | Password per team (e.g., `TEAM_PASSWORD_GSA`) |

**API endpoints:**
- `POST /api/lineup` — Submit weekly lineup
- `POST /api/transaction` — Submit roster transaction (FA, taxi, trade)
- `POST /api/team-name` — Update team name

---

## Project Structure

```
scoring/
├── autoscorer.py              # Excel-based CLI (2020–2025)
├── autoscorer_json.py         # JSON-based CLI (2026+)
├── validate_scores.py         # Score validation tool
├── qpfl/                      # Core scoring library
│   ├── scoring.py             # Position-specific scoring rules
│   ├── json_scorer.py         # JSON-based scoring (2026+)
│   ├── scorer.py              # Excel-based scoring (historical)
│   ├── data_fetcher.py        # NFL stats via nflreadpy
│   └── ...
├── scripts/
│   ├── create_new_season.py       # Season setup (run via season-transition workflow)
│   ├── export_current.py          # Fast current-season export
│   ├── export_for_web.py          # Full historical export
│   ├── export_hall_of_fame.py     # HOF statistics (run end-of-season)
│   ├── init_rosters_from_excel.py # Populate rosters.json after draft
│   ├── sync_rosters_to_excel.py   # JSON → Excel backup
│   └── ...
├── .github/workflows/
│   ├── score.yml              # Main scoring workflow (scheduled + push triggers)
│   ├── season-transition.yml  # One-click new season setup
│   ├── expire-trades.yml      # Auto-expire stale trade proposals
│   └── trade_blocks.yml       # Trade block management
├── api/                       # Vercel serverless functions
├── data/                      # JSON data (rosters, lineups, trades, config)
├── web/                       # Static website files
│   ├── index.html             # Single-page app shell
│   ├── app.js                 # All client-side logic (~9000 lines)
│   ├── styles.css             # Styles
│   ├── data.json              # Current season (rebuilt each scoring run)
│   ├── data_{year}.json       # Historical seasons (frozen)
│   └── data/
│       ├── index.json         # Season manifest
│       ├── shared/            # Constitution, HOF, banners, transactions
│       └── seasons/{year}/    # Per-season data (standings, weeks, rosters)
└── 2025 Scores.xlsx           # 2025 Excel source (historical)
```

## Score Validation

```bash
# Validate a specific week
uv run python validate_scores.py --week 16

# Validate all weeks with summary
uv run python validate_scores.py --all --summary
```

## Notes

- Player stats come from nflverse, typically updated 1–2 hours after games end
- Players from games not yet played show as "not found" (score of 0)
- NFL team abbreviation differences (LAR→LA, JAC→JAX) are handled automatically
- Historical seasons (2020–2025) are frozen; use `--reexport-historical` only if the Excel source was corrected
