# QPFL Web Data Architecture

## Current Issues

The current `data.json` approach has several problems:
1. **Size**: 1.9MB file that must be fully downloaded on every page load
2. **Update frequency mismatch**: Constitution (rarely changes) is bundled with weekly scores
3. **Regeneration**: Must regenerate entire file even for small changes
4. **Historical data**: Duplicates shared resources across season files

## Proposed Architecture

### Data Categories by Update Frequency

| Category | Files | Update Frequency | Size |
|----------|-------|------------------|------|
| **Static** | constitution, hall_of_fame, banners | Rarely (offseason) | ~27 KB |
| **Season-level** | teams, schedule, standings, rosters, draft_picks | Weekly | ~55 KB |
| **Week-level** | Individual week matchups/scores | After each week | ~50 KB each |
| **Live** | game_times, pending_trades, fa_pool | During games | ~20 KB |
| **Historical** | Past season data | Never | ~75 KB/season |

### Proposed Directory Structure

```
web/
├── data/
│   ├── shared/
│   │   ├── constitution.json      # League rules (rarely changes)
│   │   ├── hall_of_fame.json      # Historical records
│   │   ├── banners.json           # Banner images
│   │   └── transactions.json      # All-time transactions
│   │
│   ├── seasons/
│   │   ├── manifest.json          # List of available seasons + current season
│   │   │
│   │   ├── 2025/
│   │   │   ├── meta.json          # teams, schedule, trade_deadline, is_current
│   │   │   ├── standings.json     # Current standings
│   │   │   ├── rosters.json       # Full rosters by team
│   │   │   ├── draft_picks.json   # Pick ownership
│   │   │   ├── live.json          # game_times, fa_pool, pending_trades (fast-changing)
│   │   │   └── weeks/
│   │   │       ├── week_1.json    # Matchups, scores, rosters for week 1
│   │   │       ├── week_2.json
│   │   │       └── ...
│   │   │
│   │   ├── 2024/
│   │   │   ├── meta.json
│   │   │   ├── standings.json
│   │   │   └── weeks/
│   │   │       ├── week_1.json
│   │   │       └── ...
│   │   │
│   │   └── 2023/
│   │       └── ...
│   │
│   └── index.json                 # Bootstrap file with manifest + current season info
│
├── images/
│   ├── banners/
│   ├── hof/
│   └── league_logo.png
│
└── index.html
```

### Export Scripts

```
scripts/
├── export/
│   ├── __init__.py
│   ├── shared.py              # Export constitution, hall_of_fame, banners, transactions
│   ├── season.py              # Export full season (meta, standings, rosters, weeks)
│   ├── week.py                # Export single week (after games complete)
│   ├── live.py                # Export live data (game_times, fa_pool, pending_trades)
│   ├── standings.py           # Update standings only
│   └── historical.py          # Export historical season from Excel
│
└── export_for_web.py          # Legacy script (calls new modules)
```

### Usage Examples

```bash
# Export shared data (run occasionally)
uv run python -m scripts.export.shared

# Export current week scores (run after games)
uv run python -m scripts.export.week 16

# Update standings only (run frequently)
uv run python -m scripts.export.standings

# Export live data (run during games)
uv run python -m scripts.export.live

# Export historical season (run once per old season)
uv run python -m scripts.export.historical 2024

# Full export (for deployment)
uv run python -m scripts.export.all
```

### Frontend Loading Strategy

```javascript
// 1. Load bootstrap file (tiny, tells us what's available)
const index = await fetch('data/index.json').then(r => r.json());
const currentSeason = index.current_season;
const availableSeasons = index.seasons;

// 2. Load shared data (cached aggressively)
const [constitution, hof, banners] = await Promise.all([
    fetch('data/shared/constitution.json'),
    fetch('data/shared/hall_of_fame.json'),
    fetch('data/shared/banners.json'),
]);

// 3. Load current season metadata
const meta = await fetch(`data/seasons/${currentSeason}/meta.json`);
const standings = await fetch(`data/seasons/${currentSeason}/standings.json`);

// 4. Load current week on-demand
const weekData = await fetch(`data/seasons/${currentSeason}/weeks/week_${currentWeek}.json`);

// 5. Load other weeks as user navigates (lazy loading)
```

### Benefits

1. **Faster initial load**: Only ~50KB for bootstrap + current week vs 1.9MB
2. **Better caching**: Static content cached indefinitely, week data cached after completion
3. **Incremental updates**: Can update just standings or just current week
4. **Parallel loading**: Shared data loads in parallel with season data
5. **Lazy loading**: Past weeks load only when user views them
6. **Clear separation**: Easy to understand what needs updating when

### Migration Path

**Current Status: Phase 1 Complete ✓**

1. ✅ Create new directory structure alongside existing `data.json`
2. ✅ Update export scripts to write to new structure
3. ✅ Generate legacy `data.json` from split files for backward compatibility
4. ⏳ Update frontend to use new loading pattern (future)
5. ⏳ Remove legacy file generation once frontend migrated (future)

### Current Usage

```bash
# Full export (recommended for deployments)
uv run python -m scripts.export.all

# Export only shared data (constitution, hall of fame, etc.)
uv run python -m scripts.export.shared

# Export specific season
uv run python -m scripts.export.season 2025
uv run python -m scripts.export.season 2024

# Generate legacy format only (from existing split files)
uv run python -m scripts.export.legacy
```

### Directory Structure (Current)

```
web/
├── data/                      # NEW: Split data files
│   ├── index.json            # Manifest of available seasons
│   ├── shared/
│   │   ├── constitution.json
│   │   ├── hall_of_fame.json
│   │   ├── banners.json
│   │   └── transactions.json
│   └── seasons/
│       ├── 2025/
│       │   ├── meta.json
│       │   ├── standings.json
│       │   ├── rosters.json
│       │   ├── draft_picks.json
│       │   ├── live.json
│       │   └── weeks/
│       │       ├── week_1.json
│       │       └── ...
│       └── 2024/
│           ├── meta.json
│           ├── standings.json
│           └── weeks/
│               └── ...
│
├── data.json                  # LEGACY: Generated from split files
├── data_2024.json             # LEGACY: Generated from split files
└── index.html                 # Uses legacy format for now
```

### Cache Headers (for Vercel/hosting)

```json
{
  "headers": [
    {
      "source": "/data/shared/(.*)",
      "headers": [{ "key": "Cache-Control", "value": "public, max-age=86400" }]
    },
    {
      "source": "/data/seasons/:season/weeks/week_:week.json",
      "headers": [{ "key": "Cache-Control", "value": "public, max-age=31536000, immutable" }]
    },
    {
      "source": "/data/seasons/:season/live.json",
      "headers": [{ "key": "Cache-Control", "value": "public, max-age=60" }]
    }
  ]
}
```

