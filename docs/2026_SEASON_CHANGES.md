# QPFL 2026 Season Changes

Starting in 2026, the QPFL is transitioning to a primarily web-based system. This document outlines the key changes and how to use the new system.

## Overview of Changes

### Data Sources

| Data Type | 2025 and Earlier | 2026+ |
|-----------|------------------|-------|
| **Rosters** | Excel (source of truth) | JSON (source of truth), exportable to an Excel snapshot |
| **Lineups** | Excel (bolded = starter) | JSON via website submission |
| **Scores** | Excel | JSON (auto-calculated from lineups) |
| **Schedule** | Hardcoded | `data/seasons/{year}/schedule.txt` file |
| **Previous Seasons** | Excel (archived) | Excel (read-only, no modifications) |

### Key Principles

1. **JSON is the source of truth** for current season data (rosters, lineups, scores)
2. **Excel is directional, not a second live database** - it seeds a season or receives an explicit snapshot
3. **API roster changes update JSON only** - an operator must explicitly generate an Excel snapshot
4. **Lineups are submitted on the web** - Excel lineup formatting is an explicit, dry-run-first export

## File Structure

```
scoring/
├── data/
│   ├── rosters.json               # Source of truth for rosters
│   ├── teams.json                 # Team names and owners
│   ├── fa_pool.json               # FA pool players
│   ├── pending_trades.json        # Pending trade proposals
│   ├── transaction_log.json       # All completed transactions
│   ├── seasons/
│   │   └── 2026/
│   │       └── schedule.txt        # 2026 regular season schedule (weeks 1-15)
│   └── lineups/
│       └── 2026/
│           ├── week_1.json        # Lineup submissions for week 1
│           ├── week_2.json
│           └── ...
├── Rosters.xlsx                   # Hand-maintained season seed; not updated by the API
├── Rosters_current.xlsx           # Optional generated names-only snapshot
├── Traded Picks.xlsx              # Legacy/manual record; not read by current scripts
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

The season-specific `data/seasons/2026/schedule.txt` file defines the regular season schedule (weeks 1-15). If it is absent, no schedule is published:

```txt
Week 1: GSA versus WJK, RPA versus S/T, CGK versus AST, CWR versus J/J, SLS versus AYP
Week 2: GSA versus AYP, RPA versus WJK, CGK versus S/T, CWR versus SLS, J/J versus AST
Rivalry Week 5: GSA versus RPA, CWR versus CGK, WJK versus J/J, AYP versus AST, S/T versus SLS
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
uv run --frozen python autoscorer_json.py --season 2026 --week 1

# With standings update
uv run --frozen python autoscorer_json.py --season 2026 --week 1 --update-standings
```

### Exporting Rosters to Excel

Snapshot the current `data/rosters.json` to `Rosters_current.xlsx`:

```bash
uv run --frozen python scripts/sync_rosters_to_excel.py
```

### Exporting for Web

```bash
# Export the current season (fast path, used by the scoring workflow)
uv run --frozen python scripts/export_current.py --season 2026

# Re-export a frozen historical season from its Excel file
uv run --frozen python scripts/export_for_web.py --reexport-historical 2022
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
- `validate` - Validate a team credential
- `taxi_activate` - Activate a player from taxi squad
- `fa_activate` - Add a player from FA pool
- `release` - Release a player
- `propose_trade` - Propose a trade
- `respond_trade` - Accept or reject a trade
- `cancel_trade` - Cancel a pending proposal
- `set_depth_chart` - Save roster position order
- `save_tradeblock` - Update trade preferences
- `admin_adjust` - Authenticated commissioner operation

See `docs/API.md` for all six deployed endpoints, request boundaries, and atomic-write guarantees.

## Migration Notes

### From 2025 to 2026

1. **Rosters**: The final 2025 rosters become the starting 2026 rosters
2. **No lineup migration needed**: Lineups are fresh each season
3. **Excel files**: Keep 2025 Scores.xlsx unchanged, create new 2026 Scores.xlsx
4. **Schedule**: Create `data/seasons/2026/schedule.txt` only when the 2026 schedule is official

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

### Roster export issues

1. Ensure `data/rosters.json` is valid JSON
2. Run `uv run --frozen python scripts/sync_rosters_to_excel.py` manually
3. Check the output file isn't open in another program
