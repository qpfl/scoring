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
- **Projections**: Current-season matchups show projected points for every player, projected starter totals, and win probabilities once both lineups are complete. Final NFL games contribute actual points while unfinished games retain their projections.
- **Schedule**: Full regular-season schedule grid (current season only).

### Standings
Full standings table with wins, losses, points for, points against, rank points, expected W/L (xW-xL), luck rating, and strength of schedule. Includes playoff odds (Monte Carlo simulation) during the regular season.

### Teams
- **All Rosters**: Full grid of all 10 team rosters.
- **Compare**: Side-by-side roster comparison tool — select two teams to compare.
- **Roster**: Individual roster with weekly scores, taxi squad, and future picks.
- **Hall of Fame**: Franchise summary, championships, Ring of Honor, owner records, head-to-head records, season finishes, and all-time performances.
- **Activity**: Trade block and franchise-filtered transaction history in one place.

### Stats
- **Player Leaders**: Sortable table of top-scoring players by position.
- **Team Stats**: PPG, record, and other aggregate team stats for the season.

### Transactions
Full historical transaction log (trades, FA pickups, taxi activations) across all seasons with search and filter. Click any transaction to expand details.

### Hall of Fame
- **League Hall**: Season finishes, owner achievements, all-time team and player records, and Rivalry Week history.
- **Banner Room**: Championship and bowl winners by year.
- **Constitution**: League rules and bylaws.

### Drafts
- **Draft History**: Full draft board by year with every pick.
- **Draft Challenge**: NFL Draft Challenge results and scoring.

### My Team *(current season only, password-protected)*
- **Dashboard**: See your next matchup, weekly lineup status, pending trades, Draft Challenge status, and recent roster activity at a glance.
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
4. Re-scores the latest fully completed week and refreshes calculated Hall of Fame records
5. Exports scores and standings to `web/data.json`
6. Commits changes and deploys to GitHub Pages

Matchup projections refresh on the same schedule. They blend the previous season with current-season performance, apply a bounded opponent-versus-position adjustment, and switch a player from projected to actual points only after the NFL schedule marks the game final.

League and team Hall of Fame calculations only include weeks for which every NFL game has a
final result, so partial-week zeroes cannot become low-score records. MVPs and Team Ring of
Honor owners, players, rings, and team-name history remain manually maintained.

(Rosters are **not** exported to Excel by this workflow — run
`uv run python scripts/sync_rosters_to_excel.py` when you want a current snapshot.)

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
- Creates disabled `data/nfl_draft_challenges/2027_config.json` and empty `2027.json` Draft Challenge files
- Updates `data/league_config.json` with the new season year
- Commits, pushes, and deploys to GitHub Pages

**After running the workflow, three manual steps remain:**
1. **Before opening the Draft Challenge:** Fill in the one annual `data/nfl_draft_challenges/{year}_config.json` file with the lock time, prospect source/list, and `"enabled": true`. The title, pick count, scoring, browser UI, and API all read that file.
2. **After the draft:** Run `python scripts/init_rosters_from_excel.py` to populate `data/rosters.json` from the draft Excel file.
3. **When the NFL schedule releases (mid-summer):** Add the QPFL matchup schedule to `web/data/seasons/{year}/meta.json`.

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
| `schedule.txt` | **Live input.** Single source of truth for the regular-season schedule; edit this to set matchups (see `NEW_SEASON_CHECKLIST.md`) |
| `Drafts.xlsx` | **Live input.** Draft results, synced into `data/drafts.json` via `scripts/sync_drafts_from_excel.py` |
| `Rosters.xlsx` | Hand-maintained workbook (formulas, `Team Stats` sheet). Seeds `data/rosters.json` once per season via `scripts/init_rosters_from_excel.py`; goes stale as transactions land, and no script writes it |
| `Rosters_current.xlsx` | Generated snapshot (names only, no scores or formulas) — run `scripts/sync_rosters_to_excel.py` for an up-to-date view of who is rostered |
| `Traded Picks.xlsx` | Legacy/manual record of draft-pick trades; not read by any current script |
| `data/nfl_draft_challenges/{year}_config.json` | Annual Draft Challenge title, lock time, pick count, scoring, and prospect suggestions |
| `data/nfl_draft_challenges/{year}.json` | That year's submitted entries and actual NFL draft results |
| `web/data/shared/manual_honors.json` | Manually curated Team Hall/Ring of Honor entries, kept out of application code |

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
| 18–27 | 0 |
| 28–31 | −2 |
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

The website's My Team feature uses Vercel serverless functions to write data back to the repo.

1. Import repository to [Vercel](https://vercel.com)
2. Set environment variables:

| Variable | Description |
|----------|-------------|
| `SKYNET_PAT` | GitHub PAT with `repo` scope |
| `REPO_OWNER` | GitHub username |
| `TEAM_PASSWORD_{ABBREV}` | Password per team (e.g., `TEAM_PASSWORD_GSA`) |
| `TEAM_PASSWORD_ADMIN` | Legacy commissioner password for raw `/api/transaction` admin requests |

**API endpoints:**
- `POST /api/lineup` — Submit weekly lineup
- `POST /api/transaction` — Submit roster transaction (FA, taxi, trade)
- `POST /api/team-name` — Update team name

**Commissioner tools:** Log in as GSA to reveal the protected **Commissioner** subpage under **My Team**. The server revalidates the GSA password for every action; hiding the tab is not the authorization boundary. The tools support:

- `admin_action: "release"` — remove a player from any team's roster (`target_team`, `player`)
- `admin_action: "add"` — add a player to any team's roster (`target_team`, `player: {name, position, nfl_team, taxi}`)
- `admin_action: "reverse_trade"` — reverse an accepted/completed trade by transferring its players and picks back (`trade_id`, `reason`); pending negotiations are never listed in the commissioner tools
- `admin_action: "conditional_picks"` — return unresolved conditions directly from the authoritative draft-pick source
- `admin_action: "resolve_conditional_pick"` — resolve a conditional by selecting the conveying pick and final owner (`condition`, `winning_pick_id`, `final_owner`, `reason`); every candidate is shown with its current owner, and non-conveying picks retain their ownership
- `admin_action: "download_rosters"` — download `Rosters_current.xlsx`, built from the authoritative rosters and team metadata
- `admin_action: "download_draft_board"` — download an editable current-season draft board whose slots and ownership come from `draft_orders.json` and `draft_picks.json`, including trade lineage
- `admin_action: "score_adjustment"` — append a manual scoring correction (`season`, `week`, `target_team`, `player`, `points`, `reason`)
- `admin_action: "audit_log"` — return recent commissioner actions to the protected audit-log UI

Raw API clients can continue using `team: "ADMIN"` with `TEAM_PASSWORD_ADMIN`; the browser screen uses the authenticated GSA credentials. All modifying actions are logged to the transaction history with `"admin": true`, the acting credential, timestamp, and optional reason. If you'd rather edit JSON directly: pull latest, edit `data/*.json`, push to main — an in-flight API write may hit a 409 and retry against your commit, which is expected and safe.

**A note on security:** team passwords are commissioner-issued (not user-chosen) and travel with every request over HTTPS — acceptable for a friends league, not intended to resist a dedicated attacker. Rotate a team's password anytime by updating its `TEAM_PASSWORD_{ABBREV}` Vercel env var; no code change needed.

---

## Project Structure

```
scoring/
├── autoscorer.py              # Excel-based CLI (2020–2025)
├── autoscorer_json.py         # JSON-based CLI (2026+)
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
│   ├── export_hall_of_fame.py     # HOF statistics from completed weeks
│   ├── init_rosters_from_excel.py # Populate rosters.json after draft
│   ├── sync_rosters_to_excel.py   # JSON → Excel backup
│   └── ...
├── .github/workflows/
│   ├── score.yml              # Main scoring workflow (scheduled + push triggers)
│   ├── season-transition.yml  # One-click new season setup
│   ├── expire-trades.yml      # Auto-expire stale trade proposals
│   └── trade_blocks.yml       # Trade block management
├── api/                       # Vercel serverless functions
├── data/                      # JSON data (rosters, lineups, trades, annual Draft Challenge files)
├── web/                       # Static website files
│   ├── index.html             # Single-page app shell
│   ├── app.js                 # All client-side logic (~9000 lines)
│   ├── styles.css             # Styles
│   ├── data.json              # Current season (rebuilt each scoring run)
│   ├── data_{year}.json       # Historical seasons (frozen)
│   └── data/
│       ├── index.json         # Season manifest
│       ├── shared/            # Constitution, HOF, honors, banners, transactions
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
