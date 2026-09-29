# Plan: Scope injury labels to the coming week (switch to ESPN's injury feed)

## Context

Injury badges come from Sleeper's `injury_status` (`qpfl/injuries.py`). Sleeper keeps a
game designation until the team files its next practice report, and it has no field that
says which game the designation is for. So on 2026-09-29, Jalen Coker still shows **O**
from Week 4 even though nothing rules him out of Week 5. The same stale status also feeds
`qpfl/availability.py` (`OUT_INJURY_STATUSES`), so it **zeroes his projection** for
the coming week as well.

Data sources checked on 2026-09-29:
- **Sleeper**: `injury_status: Out` with no week, date, or return field. `news_updated` is
  after the game, so it can't be used to detect staleness.
- **nflverse `load_injuries`**: the official per-week report, but only goes up to Week 3,
  so it runs a week or more behind.
- **ESPN** `site.api.espn.com/apis/site/v2/sports/football/nfl/injuries`: one request covers
  all 32 teams. Each entry has `status` (the last official designation), a forward-looking
  `details.fantasyStatus`, `details.returnDate`, `date`, `type`, and athlete name/position/team.
  Coker is `status: Out`, `fantasyStatus: QUESTIONABLE`, `returnDate: 2026-10-04`. 60
  players league-wide show that same stale "Out" but "Questionable" pattern.

**Decision (user):** switch the feed to ESPN and label with its forward-looking status.

## Approach

Keep the public payload shape (`{source, updated_at, players: {key: {status, abbreviation,
body_part?, notes?}}}`) so the website, availability, and projections keep working
without structural changes. Only the fetch and the matching logic change.

### 1. `qpfl/injuries.py`: fetch and match ESPN instead of Sleeper
- Replace `SLEEPER_PLAYERS_URL`/`_fetch_sleeper_players` with `ESPN_INJURIES_URL` and
  `_fetch_espn_injuries(opener)`. Flatten `payload['injuries'][*]['injuries'][*]` into
  records `{name: athlete.displayName, position: athlete.position.abbreviation,
  team: athlete.team.abbreviation, status, fantasy_status, return_date, body_part: details.type,
  detail: details.detail, date}`. Raise `ValueError` on an unexpected shape, which keeps
  the existing "use cached data" fallback.
- Rewrite `match_injuries(targets, espn_records)`. Reuse the existing name/position/team
  identity logic unchanged: `normalize_player_name`, `normalize_team` (add `'LAR'`/`'WSH'`
  aliases if ESPN differs), prefer same-team, and only accept an unambiguous match.
- New `_status_details(record)` decides the **coming-week** label:
  - Skip `status == 'Active'`. These are news-only rows.
  - Use `fantasyStatus` as the label source, mapping `OUT`→Out/O, `DOUBTFUL`→Doubtful/D,
    `QUESTIONABLE`→Questionable/Q, `IR`/`IR-R`→Injured Reserve/IR, `PUP-R`→PUP,
    `NFI-R`→NFI, and `SUSPENSION`→Suspended/SUS.
  - `INACTIVE` (a game-day inactive from the last game): label as Out only if
    `returnDate` is after the team's next kickoff date. Otherwise, no label.
  - Fallback: if `fantasyStatus` is missing, use `status` through the existing
    `_STATUS_ABBREVIATIONS`.
- Entry fields stay as they are (`status`, `abbreviation`, `body_part`, `notes`), and I'll add an
  optional `return_date` (ISO date).
- `load_injury_statuses(...)` gains an optional `next_kickoffs: Mapping[team, iso]` for the
  INACTIVE rule. It's safe when absent: INACTIVE then gets no label.
- `CACHE_TTL`: 24h was Sleeper's once-a-day download policy. ESPN's feed is small, so I'll drop it
  to about 3h, letting scoring runs (`autoscorer_json.py:405`) pick up Wed–Sun report changes.
- Set `'source': 'ESPN'` in `_public_payload` and `refreshed`.

### 2. Pass kickoffs through
- `scripts/export_current.py` `enrich_live_roster_context` (~line 210): load injuries
  **after** `build_week_kickoffs(...)` and pass `next_kickoffs=kickoffs`.
- `autoscorer_json.py:405` and `scripts/refresh_injury_statuses.py`: pass kickoffs where
  already available. Otherwise omit them, since INACTIVE then has no label, which is the
  conservative choice.

### 3. Availability and projections
- `qpfl/availability.py` `OUT_INJURY_STATUSES` already keys off `status` text (out,
  doubtful, IR, PUP, NFI, suspended). The new labels feed it unchanged, so Coker (Q) stops
  projecting zero. I'll update the comments/docstring that mention Sleeper.

### 4. Website (small)
- `web/app.js` `playerInjuryBadge` (~line 253): append `Expected back ${formatDate(return_date)}`
  to the tooltip details when present. The source label already comes from `report.source`.
- Update the comment at `web/app.js:218` from Sleeper to ESPN.

### 5. Workflow and docs
- `.github/workflows/refresh-injuries.yml`: rename the step, and add in-season crons for
  report days (for example Wed/Thu/Fri/Sat/Sun mornings ET) alongside the daily one.
- `scripts/refresh_injury_statuses.py` docstring, and README line ~96: Sleeper→ESPN.
- Per the repo convention, also save this plan as `docs/PLAN_injury_labels_coming_week.md`.

### 6. One-time cache refresh
- The existing `data/injury_statuses.json` is less than 3h old in Sleeper format. Running
  `scripts/refresh_injury_statuses.py` after the TTL change (or deleting the cache first)
  replaces it. Then run `export_current.py` so `web/data.json` picks it up.

## Tests
- `tests/test_injuries.py`: rewrite the fixtures to ESPN-shaped payloads (`JsonResponse` opener
  pattern already exists). Cases:
  - stale Out with `fantasyStatus: QUESTIONABLE` → Q (the Coker case)
  - Out/OUT with a far `returnDate` → O
  - IR → IR
  - Active → absent
  - INACTIVE with `returnDate` ≤ next kickoff → absent, and > next kickoff → O
  - suffix/team alias matching
  - ambiguous name → skipped
  - fetch failure → cached payload
  - TTL freshness
- `tests/test_availability.py`, `tests/test_matchup_projections_ui.py`,
  `tests/test_injury_status_ui.py`: fix any Sleeper-specific fixtures or strings, and add an
  assertion for the return-date tooltip.

## Verification
1. `uv run pytest tests/test_injuries.py tests/test_availability.py tests/test_injury_status_ui.py tests/test_matchup_projections_ui.py`
2. `uv run pytest` (full suite).
3. `uv run python scripts/refresh_injury_statuses.py`, then check `data/injury_statuses.json`:
   `WR|jalen coker` should be **Q** with `return_date: 2026-10-04`, and the count of O labels
   should drop sharply from 20.
4. `uv run python scripts/export_current.py --season 2026`, then serve `web/` locally
   and confirm Coker's badge reads Q with a return-date tooltip, and that his matchup projection is
   no longer zero.
