# Regenerate Rosters.xlsx from data/rosters.json

## Context

`data/rosters.json` is the live source of truth for 2026+ — it's mutated continuously by
`api/transaction.py` (FA pickups, releases, taxi moves, trades), `api/lineup.py` (depth
charts), and `scripts/update_player_teams.py` (nflreadpy team refreshes).

The root `Rosters.xlsx` has drifted badly out of sync. It was last written 2026-01-01 and has
only two commits in its history, while `data/rosters.json` has moved many times since. The
commissioner uses this workbook to work out who is rostered when seeding the free-agent pool
(`scripts/seed_fa_pool.py`), so a stale copy produces a wrong FA list.

There is no working command to regenerate it. The repo currently contains **three mutually
incompatible Excel roster formats**:

| Location | Format | Status |
|---|---|---|
| `scripts/init_rosters_from_excel.py` (reader) | Canonical QPFL grid — teams in cols 1,3,5…19; positions at fixed rows | The real format; matches `Rosters.xlsx` "Week 1" |
| `scripts/sync_rosters_to_excel.py` (writer) | Flat 5-column table | Never round-trips with the reader; never run in CI |
| `qpfl/roster_sync.py::sync_rosters_to_excel` (writer) | A third grid layout | Dead code — zero importers, not in `qpfl/__init__.py` |

`README.md:86` claims the scoring workflow "Backs up rosters to `Rosters.xlsx`". It does not —
`grep sync_rosters .github/workflows/*.yml` returns nothing.

**Goal:** one command that writes a fresh standalone workbook in the canonical grid layout, so
it round-trips cleanly through `init_rosters_from_excel.py`, and collapse the three formats
into one.

## Decisions (confirmed with user)

- **Fresh standalone file.** Default output `Rosters_current.xlsx`; the existing `Rosters.xlsx`
  (with its formulas and `Team Stats` sheet) is left untouched. `--output` can target it if
  desired.
- **Canonical grid layout, names only** — no formulas, no `Points` columns, no `Score` rows.
- **Scope: refresh only.** No free-agent computation; the user keeps their existing FA workflow.

## Implementation

### 1. Rewrite `qpfl/roster_sync.py::sync_rosters_to_excel` to emit the canonical grid

Replace the dead third-format writer so there is exactly one Excel writer in the codebase.
Keep the existing signature shape but write the layout that
`scripts/init_rosters_from_excel.py` reads, driven entirely by the constants already in
`qpfl/constants.py` — do not hardcode row/column numbers:

- `TEAM_COLUMNS = [1, 3, 5, 7, 9, 11, 13, 15, 17, 19]` paired with `ALL_TEAMS` order
- `POSITION_ROWS` — `{'QB': (6, [7, 8, 9]), 'RB': (11, [12..15]), ...}`; header row gets the
  position label, player rows get the players
- `TAXI_ROWS = [(48, 49), (50, 51), (52, 53), (54, 55)]` — label row above player row; write
  the taxi player's position in the label row, the player in the row below
- Row 2 = team name, row 3 = owner, row 4 = abbrev, pulled from `data/teams.json`
  (`{"teams": [{abbrev, name, owner, owner_key}, ...]}`). Fall back to
  `constants.TEAM_TO_OWNER` if `teams.json` is missing an entry, and to the abbrev itself for
  a missing name.
- Reuse the existing `format_player_for_excel(player)` → `"Name (TEAM)"`, which is exactly the
  format `parse_player_cell`'s regex `^(.+?)\s*\(([A-Z]{2,3})\)$` expects.
- Partition each team's list: non-taxi players (`not p.get('taxi')`) fill `POSITION_ROWS` slots
  in `POSITION_ORDER`; `p.get('taxi')` players fill `TAXI_ROWS`.
- Print a warning (these scripts communicate by `print`, per the existing test pattern) when a
  team has more players at a position than `ROSTER_SLOTS` allows, or more than `TAXI_SLOTS`
  taxi players — and do not silently drop them from the count in the summary line.

Also reuse the existing `load_rosters_json`.

### 2. Make `scripts/sync_rosters_to_excel.py` a thin CLI over it

Delete the flat-table writer in that file and have `main()` call the `qpfl.roster_sync`
function. Keep the `sys.path.insert(0, str(Path(__file__).parent.parent))` bootstrap and
repo-root-relative path resolution used by every other script here.

Arguments:

- `--rosters/-r` — default `data/rosters.json`
- `--output/-o` — default `Rosters_current.xlsx` (**changed** from today's `--excel Rosters.xlsx`,
  which would clobber the live workbook). Keep `--excel` as a hidden alias so the commands in
  `CONTRIBUTING.md` / `docs/2026_SEASON_CHANGES.md` don't break.
- Drop `--transactions` — it only printed a count and wrote nothing.

Command:

```
uv run python scripts/sync_rosters_to_excel.py
```

### 3. Tests — `tests/test_sync_rosters_to_excel.py` (new)

Follow the `tests/test_init_rosters_from_excel.py` pattern: import the function directly
(`from scripts.sync_rosters_to_excel import ...`), use `tmp_path`, assert on parsed output and
on `capsys.readouterr().out` for warnings.

- **Round-trip test (the important one):** build a `rosters.json` fixture → write the workbook
  → feed it to `init_rosters_from_excel` → assert the resulting JSON equals the input, including
  `taxi: true` entries and `nfl_team` values.
- Team name / owner / abbrev land in rows 2/3/4 of the right columns.
- Over-capacity roster and >`TAXI_SLOTS` taxi entries each emit a `WARNING`.
- Missing `data/rosters.json` returns falsy and does not create a file.

### 4. Docs

- `README.md:220` — root-files table row for `Rosters.xlsx`: it is a **stale hand-maintained
  workbook**, not a generated backup. Point the generated-backup description at
  `Rosters_current.xlsx`.
- `README.md:86` — remove the false "Backs up rosters to `Rosters.xlsx`" step from the scoring
  workflow list (CI does not do this).
- `CONTRIBUTING.md:85-88` and `docs/2026_SEASON_CHANGES.md:111-113,195` — update to the
  `uv run` form and note the new default output path.
- `NEW_SEASON_CHECKLIST.md` — mention that `Rosters_current.xlsx` can be regenerated at any time
  and is the file to consult when seeding the FA pool.

## Out of scope

Wiring this into `.github/workflows/score.yml`. It stays a manual command, matching the answer
that scope is "just refresh". Worth revisiting separately.

## Verification

```bash
# 1. Generate
uv run python scripts/sync_rosters_to_excel.py

# 2. Round-trip: regenerated workbook must reproduce rosters.json byte-for-byte
uv run python scripts/init_rosters_from_excel.py \
  --excel Rosters_current.xlsx --output /tmp/rosters_roundtrip.json
diff <(jq -S . data/rosters.json) <(jq -S . /tmp/rosters_roundtrip.json)   # expect no output

# 3. Tests
uv run pytest tests/test_sync_rosters_to_excel.py tests/test_init_rosters_from_excel.py -v

# 4. Integrity + full suite unaffected
uv run python scripts/check_integrity.py
uv run pytest
```

Then open `Rosters_current.xlsx` and spot-check that a team known to have made a recent
transaction (per `data/transaction_log.json`) shows its current roster — confirming the drift
from the old `Rosters.xlsx` is gone.

Note: `Rosters_current.xlsx` is a generated artifact. Check whether `.gitignore` should cover
it rather than committing a binary that changes on every transaction.
