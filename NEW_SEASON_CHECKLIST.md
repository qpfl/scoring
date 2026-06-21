# New Season Checklist (Commissioner)

Steps to set up a new QPFL season. Run the automation script first, then handle the manual pieces below.

---

## 1. Run the season creation script

```bash
python scripts/create_new_season.py YYYY
```

This handles: archiving the previous season, creating the new season directory, bumping `CURRENT_SEASON` in the GitHub Actions workflow, updating `api/transaction.py` + `api/lineup.py`, updating `data/league_config.json`, and creating `data/lineups/YYYY/.gitkeep`.

Use `--dry-run` first to preview changes.

---

## 2. Manual steps after running the script

### Team names
**File:** `data/teams.json`

Update each team's `"name"` field with the new season team names. The `abbrev`, `owner`, and `owner_key` fields stay the same year to year unless ownership changes.

The script copies these team records into `web/data/seasons/YYYY/meta.json` automatically.

---

### Schedule
**File:** `web/data/seasons/YYYY/meta.json` → `"schedule"` array

Add all 17 weeks once the NFL schedule is released. Each week is an object:

```json
{
  "week": 1,
  "is_rivalry": false,
  "is_playoffs": false,
  "matchups": [
    { "team1": "GSA", "team2": "WJK" },
    { "team1": "RPA", "team2": "S/T" },
    { "team1": "CGK", "team2": "AST" },
    { "team1": "CWR", "team2": "J/J" },
    { "team1": "SLS", "team2": "AYP" }
  ]
}
```

- Weeks 16–17 should have `"is_playoffs": true`
- Set `"is_rivalry": true` for designated rivalry weeks
- Use team abbreviations from `data/teams.json`

---

### Rosters (post-draft)
**File:** `data/rosters.json`

After the offseason draft, populate rosters from the draft Excel file:

```bash
python scripts/init_rosters_from_excel.py --excel "Rosters.xlsx"
```

The Excel file format expected:
- Row 2: Team names
- Row 3: Owner names
- Row 4: Team abbreviations (GSA, CGK, etc.)
- Rows 6+: Players by position with position headers
- Player format: `Player Name (NFL_TEAM)`

---

### Draft results
**File:** `data/drafts.json` → `"drafts"` array

After each draft (offseason + midseason), sync picks from the Excel file:

```bash
python scripts/sync_drafts_from_excel.py --excel "Drafts.xlsx"
```

Each draft entry in the JSON looks like:
```json
{
  "name": "2026 Offseason Draft",
  "year": 2026,
  "type": "offseason",
  "rounds": [ ... ]
}
```

---

### Draft pick ownership
**File:** `data/draft_picks.json` → `"picks"` array

Before the offseason draft, update which teams own each other's picks (due to trades). Each pick:

```json
{
  "year": "2026",
  "round": 1,
  "draft_type": "offseason",
  "original_team": "GSA",
  "current_owner": "AYP",
  "previous_owners": ["GSA"]
}
```

This only needs updating if picks were traded during the previous season.

---

### FA pool
**File:** `data/fa_pool.json`

Reset to `[]` at the start of the season. Players added via the FA system will populate this automatically.

---

## 3. Config values to double-check

In `web/data/seasons/YYYY/meta.json`:
- `"current_week": 0` — the script sets this; scoring automation increments it
- `"trade_deadline_week": 12` — update if the league changes this

In `data/league_config.json`:
- `"current_season"` — updated by the script
- `"trade_deadline_week"` — keep in sync with meta.json
- `"playoff_weeks"` — should be `[16, 17]` unless structure changes

---

## 4. After the season starts

- **Lineups:** Players submit weekly lineups to `data/lineups/YYYY/week_N.xlsx`; the scoring workflow reads these automatically
- **Midseason draft:** Run `sync_drafts_from_excel.py` again after the midseason draft to add the new draft to `data/drafts.json`
- **Trade deadline:** No config change needed; `trade_deadline_week` in `league_config.json` gates the API automatically
