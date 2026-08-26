# New Season Checklist (Commissioner)

Steps to set up a new QPFL season. Run the automation script first, then handle the manual pieces below.

---

## 1. Run the season creation script

```bash
python scripts/create_new_season.py YYYY
```

This handles: archiving the previous season, creating the new web season directory, creating an empty `data/seasons/YYYY/` input directory, bumping `CURRENT_SEASON` in the GitHub Actions workflow, updating `api/transaction.py` + `api/lineup.py`, updating `data/league_config.json`, creating `data/lineups/YYYY/.gitkeep`, creating disabled annual Draft Challenge configuration/state files, adding the just-frozen season to `protect_historical.yml`, validating `data/` (schema + cross-file integrity), and creating a local `season-{prevYYYY}-final` git tag.

Use `--dry-run` first to preview changes. Push the tag once you're happy with the commit: `git push origin season-{prevYYYY}-final`.

---

## 2. Manual steps after running the script

### Team names
**File:** `data/teams.json`

Update each team's `"name"` field with the new season team names. The `abbrev`, `owner`, and `owner_key` fields stay the same year to year unless ownership changes.

The script copies these team records into `web/data/seasons/YYYY/meta.json` automatically.

---

### Draft Challenge
**File:** `data/nfl_draft_challenges/YYYY_config.json`

The season script creates this annual configuration disabled. Set its title, timezone-aware `lock_time`, prospect source/list, pick count, and scoring, then change `"enabled"` to `true`. The browser and API read this file; no JavaScript or Python changes are needed. Submissions and actual results are stored separately in `data/nfl_draft_challenges/YYYY.json`.

---

### Schedule
**File:** `data/seasons/YYYY/schedule.txt` — the single source of truth for that season's regular-season schedule.

Create this file once the QPFL schedule is set for the 15 regular-season weeks. Do not copy the previous season's file forward:

```
Week 1: GSA versus WJK, RPA versus S/T, CGK versus AST, CWR versus J/J, SLS versus AYP
...
Rivalry Week 5: GSA versus RPA, CWR versus CGK, ...
```

- Use `Rivalry Week N:` for designated rivalry weeks (parsed automatically).
- Use team abbreviations from `data/teams.json`.
- `scripts/export_current.py` parses only the requested season's file via `qpfl.schedule.get_regular_season_schedule`, writes it into `web/data.json` (`"schedule"`) and mirrors it into `web/data/seasons/YYYY/meta.json` — do not hand-edit `meta.json`'s `"schedule"` array directly, it will be overwritten on the next export.
- If the file is absent, the public schedule is empty. Week 1 lineup testing remains available independently.
- Weeks 16–17 (playoffs) are generated automatically from standings once the season reaches week 15; see `qpfl.schedule.get_playoff_schedule`.

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

`scripts/create_new_season.py` resets this to `[]` automatically. The pool is commissioner-curated by design — released players do **not** automatically enter it. After the draft, seed it with undrafted players:

```bash
python scripts/seed_fa_pool.py "Player One" "Player Two"
# or: python scripts/seed_fa_pool.py --names-file undrafted.txt
```

Add more names anytime the same way; it de-dupes against what's already in the pool.

To work out who is *not* rostered, regenerate a current roster snapshot first — `Rosters.xlsx`
goes stale as soon as transactions land, so don't read it for this:

```bash
uv run python scripts/sync_rosters_to_excel.py   # writes Rosters_current.xlsx
```

---

## 3. Config values to double-check

In `web/data/seasons/YYYY/meta.json`:
- `"current_week": 0` — the script sets this; scoring automation increments it
- `"trade_deadline_week": 12` — update if the league changes this

In `data/league_config.json`:
- `"current_season"` — updated by the script
- `"is_offseason"` — reset to `true` by the script; use the Commissioner page switch to start the in-season homepage
- `"trade_deadline_week"` — keep in sync with meta.json
- `"playoff_weeks"` — should be `[16, 17]` unless structure changes

---

## 4. After the season starts

- **Lineups:** Players submit weekly lineups to `data/lineups/YYYY/week_N.json`; the scoring workflow reads these automatically
- **Midseason draft:** Run `sync_drafts_from_excel.py` again after the midseason draft to add the new draft to `data/drafts.json`
- **Taxi squad auto-release:** the constitution releases taxi players at the midseason-draft Thursday and at championship conclusion. There's no calendar trigger for this - run `python scripts/release_stale_taxi.py` (or `--dry-run` first) at those points.
- **Trade deadline:** `league_config.json`'s `trade_deadline_week` is informational only — Vercel doesn't bundle `data/`, so `api/transaction.py`'s own `TRADE_DEADLINE_WEEK` constant is what actually gates the API. `scripts/create_new_season.py` updates both when it runs at season transition; if you change the deadline mid-season, update `api/transaction.py` directly.
