# Add Position Rank and Adjusted PPG to the Team Roster table

## Context

The **Rosters → Roster** sub-tab (`renderTeams()`, `web/app.js:4459-4877`) shows each team's
players as a week-by-week score grid:

```
Player | Team | W1 | W2 | … | Season
```

The only summary number is the raw season total. That tells you a player's volume but not
whether he's actually good — a 120-point WR could be WR4 or WR28, and a player who missed
three weeks to injury looks identical to one who played every week and produced nothing.

This change adds two columns to every player row (active roster **and** taxi squad, for every
team): **Rank** — the player's rank at his position among all QPFL-rostered players by season
points — and **PPG** — his average, with NFL bye weeks and weeks he was flagged unable to play
excluded from the denominator.

Decisions taken (per requirements discussion):
- Rank pool = players rostered in QPFL, not all of the NFL.
- Rank metric = **total season points** (matches the `position_rank` definition already used
  elsewhere in the app, so `WR3` means the same thing everywhere).
- PPG excludes NFL bye weeks and weeks flagged out / IR / PUP.
- Current season only.

## Data available (verified)

Everything needed is already in the browser — no pipeline or export changes.

- `data.weeks[]` (from `web/data/seasons/2026/weeks/week_N.json`, merged by
  `ensureSeasonWeek()` at `web/app.js:743`) carries, per player:
  `score`, `starter`, `found`, `on_bye`, `game_final`, and optional `unavailable_reason`.
  Every rostered player appears in every week with a numeric `score` — entries are never
  absent — so "on this roster in week N" is simply "present in that week's team entry".
- `unavailable_reason` vocabulary comes from `qpfl/availability.py:33-56` plus
  `_healthy_backup_reasons` (`qpfl/availability.py:120-169`):
  `out doubtful ir pup nfi suspended reserve retired not_on_roster practice_squad inactive
  exempt backup not_head_coach`. Values observed in 2026 week files so far: `out, ir, backup,
  pup, exempt`.
- Byes are detectable via the existing `getPlayerStatus(player, weekNum)`
  (`web/app.js:3111`), which resolves `data.game_opponents` — a full-season schedule lookup,
  reliable for any week of the current season, not just the live one.

### Two accuracy limits to be aware of (not blockers)

1. **`unavailable_reason` is an availability *forecast*, re-evaluated against current feeds at
   each scoring run** (see the comment at `qpfl/projections.py:892-917`), not a frozen
   "was inactive in week N" record. In practice a week locks once the next week's first game
   kicks off (`qpfl/week_status.py:week_is_locked`) and `autoscorer_json.py:265-283` enforces
   it, so the stamped value is effectively frozen shortly after the week ends. Injury
   exclusion is therefore best-effort, and correct for any settled week.
2. **Pre-2026 seasons have no bye or injury signal at all.** `web/data/seasons/2025/weeks/*.json`
   player entries are only `{name, nfl_team, position, score, starter}`, and historical payloads
   ship `game_opponents: {}` / empty `game_times` (`scripts/export_for_web.py:2754`). The Roster
   sub-tab does render for past seasons, so there PPG degrades gracefully to
   `points / weeks-rostered` (unadjusted) and Rank still works normally. No special-casing
   needed — the exclusion checks simply never fire.

## Approach

### 1. New exclusion constant — `web/app.js`, beside `UNAVAILABLE_BADGES` (~line 194)

```js
// Weeks a player physically could not play don't belong in a per-game average.
// 'backup' is deliberately absent: a healthy backup who dresses and produces
// nothing had a real 0, and dropping those weeks would wildly inflate his PPG.
const PPG_EXCLUDED_REASONS = new Set([
    'out', 'doubtful', 'ir', 'pup', 'nfi', 'suspended',
    'reserve', 'retired', 'not_on_roster', 'practice_squad', 'inactive',
    'exempt', 'not_head_coach',
]);
```

Two judgment calls worth surfacing, both a one-line edit to reverse:
- `backup` is **kept** in the denominator (reasoning in the comment above).
- `not_head_coach` is **excluded** — an HC who isn't the listed coach cannot score at all.

### 2. Two new functions — `web/app.js`, immediately before `function getStatsLeaders()` (line 8243)

Placed there deliberately: it puts them next to the existing by-position aggregation, and gives
the tests a clean source slice ending at `app.index('function getStatsLeaders()')`.

```js
function weekCountsTowardPpg(player, weekNum) { … }   // pure, testable
function getPlayerSeasonMetrics() { … }
```

**`weekCountsTowardPpg(player, weekNum)`** → `false` when the week is a bye
(`getPlayerStatus({ nfl_team: player.nfl_team }, weekNum).status === 'bye'`, falling back to
`player.on_bye === true`) or when `PPG_EXCLUDED_REASONS.has(player.unavailable_reason)`;
`true` otherwise. Pass the *week entry's* `nfl_team`, not the current roster's, so a player
who changed NFL teams mid-season gets the right bye weeks.

**`getPlayerSeasonMetrics()`** — memoized exactly like `getStatsLeaders()`: a module-level
`let _playerSeasonMetricsCache = { dataRef: null, value: null }`, returned early when
`dataRef === data`, **and invalidated alongside `_statsLeadersCache` at `web/app.js:758`**
(`ensureSeasonWeek()` mutates `data.weeks` in place, so the `data`-identity check alone would
serve stale values after a lazy week fetch). Missing that line is the one easy way to get this
subtly wrong.

Behavior:
- Iterate `(data.weeks || []).filter(w => w.has_scores)` — byte-identical to the filter the
  table already uses at `web/app.js:4499`, which guarantees Rank, PPG, and the existing Season
  column are all derived from the same weeks.
- For each week, for each of `matchup.team1` / `team2`, for each player in **both** `roster`
  and `taxi_squad`: key on `` `${position}|${name.toLowerCase()}` ``, accumulate
  `total_points += score`, increment `weeks_rostered`, and increment `ppg_games` when
  `weekCountsTowardPpg` passes. Guard against double-counting with a
  `seen` set of `week|key` (mirrors `seen_appearances` in `scripts/export_hall_of_fame.py:687`).
- Seed the map from `data.rosters` first, the way `getStatsLeaders()` does
  (`web/app.js:8253-8274`), so a just-activated player with no scored week still gets a rank
  rather than a blank cell.
- Group by position, sort by `(-total_points, name)` — the identical rule at
  `scripts/export_hall_of_fame.py:897` — then assign `position_rank = index + 1` and record
  `pool_size` for the tooltip.
- Return a `Map` keyed `` `${position}|${lowercased name}` `` →
  `{ total_points, weeks_rostered, ppg_games, ppg, position_rank, pool_size }`, where
  `ppg = ppg_games ? total_points / ppg_games : null`.

**Why a new function instead of reusing what exists** — worth recording, because both
alternatives look tempting:

- **Stored `position_rank` in `hall_of_fame.json`** (`scripts/export_hall_of_fame.py:889-899`,
  already loaded as `data.hall_of_fame`, already surfaced at `web/app.js:7665` and `14643`) is
  capped at `completed_through` (`scripts/export_hall_of_fame.py:315-325`), which
  `scripts/latest_completed_week.py` sets to the last week where *every* NFL game is final.
  Mid-week, the Roster table's Season column includes the in-progress week but the stored rank
  does not — the two columns would visibly disagree. It also aggregates only
  `team.roster` (`scripts/export_hall_of_fame.py:691`), never `taxi_squad`, so all 40 taxi
  players have no 2026 entry and no rank at all (verified). The new function matches its
  *ordering definition*, so the numbers agree whenever the week is settled.
- **`getStatsLeaders()`** (`web/app.js:8243`) is close but not reusable as-is: it keys on
  `name|nfl_team|position`, so a mid-season NFL team change splits one player into two
  half-point entries, and the roster table's `playerMap` key has no `nfl_team` to match on.
  Its `weeks_played` counter is also wrong for a PPG denominator — `web/app.js:8309-8312`
  skips any genuine 0-point game. Re-keying it would change the Player Leaders table and the
  All Rosters points column, which is out of scope here.

### 3. Shared cell formatter — `web/app.js`, next to `playerInjuryBadge()` (~line 213)

One helper used by both the roster and taxi tables:

```js
function rosterMetricCells(player) { … }  // returns the two <td>s
```

- Looks up `` getPlayerSeasonMetrics().get(`${player.position}|${player.name.toLowerCase()}`) ``.
- Rank cell: `<td class="pos-rank">` with `` `${position}${position_rank}` `` (e.g. `QB2`), or
  `—` when unknown. `title="#N of M rostered QBs by season points"`.
- PPG cell: `<td class="ppg">` with `ppg.toFixed(1)`, or `—` when `ppg_games` is 0.
  `title="{total} pts over {ppg_games} games played · {weeks_rostered - ppg_games} bye/inactive weeks excluded"`.
- Run `player.position` through `escapeHtml()`. Note the surrounding roster table does **not**
  escape `player.nfl_team` (`web/app.js:4684`) or `player.position` (`web/app.js:4635`, `4768`),
  unlike its All Rosters counterpart — don't copy that; the new cells should escape.

### 4. Table wiring — `web/app.js`, inside `renderTeams()`

Both tables become `Player | Team | Rank | PPG | W1 … Wn | Season`, keeping the summary
columns to the left of the horizontally-scrolling week grid so they stay on screen on mobile.

| Edit | Location |
|---|---|
| Insert `<th class="pos-rank-col">Rank</th><th class="ppg-col">PPG</th>` after `<th>Team</th>` | `web/app.js:4865` (main header) |
| Insert `${rosterMetricCells(player)}` after the `player-team` cell | `web/app.js:4684` (main row) |
| Position-group `colspan`: `weeksWithScores.length + 4` → `+ 5` | `web/app.js:4635` |
| TOTAL row `colspan="2"` → `colspan="4"` | `web/app.js:4699` |
| Same two `<th>`s after `<th>Team</th>` | `web/app.js:4789` (taxi header) |
| Same `${rosterMetricCells(playerData)}` after the `player-team` cell | `web/app.js:4771` (taxi row) |

The taxi table has no `colspan` rows to adjust. Note `web/app.js:4635`'s existing `+ 4` is
already an off-by-one overshoot for its `weeks + 3` columns; `+ 5` makes it exactly correct for
the new `weeks + 5`.

### 5. Styles — `web/styles.css`

- **Desktop**, beside the `.roster-table th.season-col` block (~line 2477):
  center-align and monospace the two new columns, matching `.roster-table td.week-score`
  (line 2432). Give `.pos-rank` a muted `var(--text-secondary)` so it reads as metadata next
  to the accent-colored scores.
- **Mobile**, in the `@media (max-width: 768px)` block (~line 11686): add
  `th.pos-rank-col, td.pos-rank, th.ppg-col, td.ppg` to the existing `min-width: 0` rule
  (`web/styles.css:11688-11694`) so two extra columns don't force horizontal scrolling early in
  the season. The sticky first column (`web/styles.css:11696-11705`) keeps the player name
  pinned and needs no change.

## Verification

1. **Unit-test the metrics logic under node**, following the existing source-slice pattern in
   `tests/test_team_hub_ui.py:11-32` (`app[app.index(…) : app.index(…)]` + `subprocess.run(['node', '-e', …])`).
   New file `tests/test_team_roster_metrics_ui.py`; slice
   `[index('function weekCountsTowardPpg') : index('function getStatsLeaders()')]` to pick up
   both functions at once, stub `data` and `getPlayerStatus`, and assert:
   - a bye week is dropped from the denominator but its 0 still counts in the total;
   - `unavailable_reason: 'out'` / `'ir'` / `'pup'` weeks are dropped;
   - `unavailable_reason: 'backup'` is **kept** (pins the judgment call);
   - a genuine 0-point week with no flag is kept (the bug `getStatsLeaders()` has);
   - ranks are 1-based, points-descending, name-tiebroken, and span roster + taxi players;
   - `ppg` is `null`, not `NaN` or `Infinity`, when every week was excluded.
2. **String assertions** in the same file for the header/row/colspan/CSS edits, matching the
   house style of `tests/test_mobile_rosters_ui.py` — including that
   `_playerSeasonMetricsCache.dataRef = null` sits next to the `_statsLeadersCache`
   invalidation in `ensureSeasonWeek()`.
3. `uv run pytest tests/ -q` — full suite, to catch any test that pins the old roster-table
   markup (`tests/test_team_hub_ui.py`, `tests/test_mobile_rosters_ui.py`,
   `tests/test_manage_rosters_ui.py`, `tests/test_all_rosters_taxi_ui.py`).
4. `uv run ruff format --check . && uv run ruff check .` — CI gates on both
   (see commit `3a52c63`).
5. **Check it in the real app**: serve `web/` (`python3 -m http.server -d web 8000`), open
   `#teams/roster/CGK`, and confirm against the data:
   - Josh Allen shows `QB2` / `39.0` — matches the stored 2026 `position_rank` of 2, which is
     the cross-check that the ordering rule was copied correctly.
   - Baker Mayfield `QB22` / `7.0`, Kyle Allen `QB27` / `0.0` (bench points are included in
     both total and rank — verified against `hall_of_fame.json`).
   - Taxi players (e.g. Stefon Diggs) show a real rank, where the stored `position_rank` gives
     nothing.
   - Week 2 is currently `has_scores: false`, so it is correctly absent from every denominator.
   - Switch to a past season (`#2025/teams/roster/CGK`) and confirm Rank still populates and
     PPG falls back to unadjusted without console errors.
6. Narrow the browser to ~390px and confirm the week grid still scrolls with the player name
   pinned, and that the new columns are readable rather than clipped.

## Housekeeping

Per your standing preference, this plan also gets saved into the repo as
`docs/PLAN_roster_position_rank_ppg.md` (alongside `docs/PLAN_personalize_manager_site.md`
and the other `PLAN_*.md` files) as the first step of execution.
