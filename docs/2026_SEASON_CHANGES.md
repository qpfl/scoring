# QPFL 2026 Season Changes

Starting in 2026, the QPFL is transitioning to a primarily web-based system. This document outlines the key changes and how to use the new system.

## Overview of Changes

### Data Sources

| Data Type | 2025 and Earlier | 2026+ |
|-----------|------------------|-------|
| **Rosters** | Excel (source of truth) | JSON (source of truth), synced to Excel |
| **Lineups** | Excel (bolded = starter) | JSON via website submission |
| **Scores** | Excel | JSON (auto-calculated from lineups) |
| **Schedule** | Hardcoded | `schedule.txt` file |
| **Previous Seasons** | Excel (archived) | Excel (read-only, no modifications) |

### Key Principles

1. **JSON is the source of truth** for current season data (rosters, lineups, scores)
2. **Excel is maintained for compatibility** and manual editing when needed
3. **Roster changes sync bidirectionally** - API updates JSON, scripts sync to Excel
4. **Lineups are web-only** - no more bolding in Excel

## File Structure

```
scoring/
├── schedule.txt                    # Regular season schedule (weeks 1-15)
├── data/
│   ├── rosters.json               # Source of truth for rosters
│   ├── teams.json                 # Team names and owners
│   ├── fa_pool.json               # FA pool players
│   ├── pending_trades.json        # Pending trade proposals
│   ├── transaction_log.json       # All completed transactions
│   └── lineups/
│       └── 2026/
│           ├── week_1.json        # Lineup submissions for week 1
│           ├── week_2.json
│           └── ...
├── 2026 Scores.xlsx               # Excel file (for rosters sheet only)
├── Traded Picks.xlsx              # Draft pick ownership
└── web/
    └── data/
        └── seasons/
            └── 2026/
                ├── meta.json       # Season metadata
                ├── standings.json  # Current standings
                ├── rosters.json    # Rosters (copy for web)
                └── weeks/
                    ├── week_1.json # Scored week data
                    └── ...
```

## Schedule Format

The `schedule.txt` file defines the regular season schedule (weeks 1-15):

```txt
# QPFL 2026 Regular Season Schedule
# Format: Week N
# Team1 vs Team2

Week 1
GSA vs WJK
RPA vs S/T
CGK vs AST
CWR vs J/J
SLS vs AYP

Week 2
...
```

## Playoff Structure (Weeks 16-17)

### Week 16: Semifinals

| Matchup | Bracket | Impact |
|---------|---------|--------|
| 1 seed vs 4 seed | Playoffs | Determines championship participants |
| 2 seed vs 3 seed | Playoffs | Determines championship participants |
| 5 seed vs 6 seed | Mid Bowl | Week 1 of 2-week cumulative |
| 7 seed vs 10 seed | Sewer Series | No standings impact |
| 8 seed vs 9 seed | Sewer Series | No standings impact |

### Week 17: Finals

| Matchup | Bracket | Result |
|---------|---------|--------|
| Winners of 1v4 and 2v3 | Championship | 1st/2nd place |
| Losers of 1v4 and 2v3 | Consolation Cup | 3rd/4th place |
| 5 vs 6 (cumulative) | Mid Bowl | 5th/6th place (weeks 16+17 total) |
| Losers of Sewer Series | Toilet Bowl | 9th/10th (loser is Toilet Bowl loser) |
| Winners of Sewer Series | 7th Place Game | 7th/8th place |

## Scripts and Commands

### Scoring a Week

```bash
# Score using JSON-based autoscorer (2026+)
python autoscorer_json.py --season 2026 --week 1

# With standings update
python autoscorer_json.py --season 2026 --week 1 --update-standings
```

### Syncing Rosters to Excel

After roster changes via the API, sync to Excel:

```bash
python scripts/sync_rosters.py
```

### Exporting for Web

```bash
# Export all data
python -m scripts.export.all

# Export specific season
python -m scripts.export.season 2026
```

## API Endpoints

### Lineup Submission

POST `/api/lineup`

```json
{
  "action": "submit",
  "team": "GSA",
  "password": "...",
  "week": 1,
  "starters": {
    "QB": ["Josh Allen"],
    "RB": ["Saquon Barkley", "Derrick Henry"],
    "WR": ["Ja'Marr Chase", "Justin Jefferson"],
    "TE": ["Travis Kelce"],
    "K": ["Harrison Butker"],
    "D/ST": ["San Francisco 49ers"],
    "HC": ["Andy Reid"],
    "OL": ["Philadelphia Eagles"]
  }
}
```

### Transaction API

POST `/api/transaction`

Actions:
- `taxi_activate` - Activate a player from taxi squad
- `fa_activate` - Add a player from FA pool
- `propose_trade` - Propose a trade
- `respond_trade` - Accept or reject a trade

## Migration Notes

### From 2025 to 2026

1. **Rosters**: The final 2025 rosters become the starting 2026 rosters
2. **No lineup migration needed**: Lineups are fresh each season
3. **Excel files**: Keep 2025 Scores.xlsx unchanged, create new 2026 Scores.xlsx
4. **Schedule**: Create new `schedule.txt` for 2026

### What Stays the Same

- Team abbreviations (GSA, CGK, etc.)
- Scoring rules
- Position requirements (1 QB, 2 RB, 2 WR, etc.)
- Draft pick structure
- Website UI (updated to use new data sources)

## Troubleshooting

### Lineups not appearing

1. Check `data/lineups/2026/week_N.json` exists
2. Verify the team abbrev matches (case-sensitive)
3. Check the API logs for submission errors

### Scores not calculating

1. Verify NFL week matches QPFL week
2. Check player names match roster exactly
3. Run with `--verbose` for detailed output

### Roster sync issues

1. Ensure `data/rosters.json` is valid JSON
2. Run `python scripts/sync_rosters.py` manually
3. Check Excel file isn't open in another program

