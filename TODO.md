# TODO

## Draft Class Performance Analysis

Add rich performance analysis to the Drafts > Draft History page.

**What:** For each player in the draft history board, show:
- Career fantasy points across all seasons they appeared
- Whether they're still on the original team vs. traded/dropped
- Season-by-season breakdown (e.g., 2022: 187 pts, 2023: 214 pts, 2024: cut)
- Position rank for the draft year (e.g., "WR12 in 2022")

**Why it's deferred:** Requires aggregating player scoring data across all historical
`web/data_YYYY.json` files (six seasons). This means either:
- Precomputing a `career_stats.json` in the export pipeline (`export_hall_of_fame.py`
  is the right place, it already aggregates cross-season data), or
- Loading all historical files client-side on demand (expensive: ~6 JSON fetches)

**Recommended approach:** Add a `player_career_stats` key to `web/data/shared/hall_of_fame.json`
during the export. Key by player name, value = `{seasons: {2022: pts, 2023: pts, ...}, total: N}`.
Then wire up a click-to-expand in the draft board rows.

**Files to modify:**
- `scripts/export_hall_of_fame.py` — add cross-season player aggregation
- `web/app.js` — update `renderDraftHistory()` to show stats per pick row
- `web/styles.css` — style for inline stats and expand rows
