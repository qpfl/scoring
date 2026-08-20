# QPFL 2026 Season Readiness Roadmap

**Audit date:** July 3, 2026 (offseason, pre-schedule-release).
**Goal:** Make this repository correctly handle everything the QPFL needs for the 2026 season — scoring, lineups, trades/transactions, transaction history, and all website features — with correctness as the top priority.

This document is written so a future engineer (or a Sonnet-class model) can pick up any item and implement it without re-deriving context. Each item states the problem, the evidence (file:line), the fix, and how to verify it.

**Priority key:**
- **P0** — Broken today or will break the season. Fix before Week 1 (early September 2026).
- **P1** — Correctness/rules gaps that will produce wrong results in realistic scenarios.
- **P2** — Hardening, missing rule automation, and tooling gaps.
- **P3** — Consolidation and tech debt. Do opportunistically.

---

## Current architecture (context for implementers)

- **Two eras:** 2020–2025 scored from Excel (`autoscorer.py`, frozen); 2026+ scored from JSON (`autoscorer_json.py` → `qpfl/json_scorer.py` → `qpfl/base_scorer.py` → `qpfl/scoring.py`, NFL stats via `qpfl/data_fetcher.py`/nflreadpy).
- **Write path:** Website (`web/app.js`) → Vercel serverless functions (`api/*.py`) → GitHub Contents API commits to JSON files in `data/` → push triggers `.github/workflows/score.yml` → scores/exports → commits `web/data.json` + `web/data/**` → deploys GitHub Pages. The site is also served by Vercel (see `vercel.json` routes).
- **Read path:** `web/app.js` fetches `data.json` (current season) and `data_{year}.json` (historical). The split-file architecture in `docs/ARCHITECTURE.md` (`web/data/…`) is generated but the frontend still reads the legacy monoliths.
- **Auth:** per-team passwords in Vercel env vars (`TEAM_PASSWORD_{ABBREV}`); the frontend stores team+password in `localStorage` (global login added June 2026) and sends them with each API call.
- **Season config:** `data/league_config.json` is the nominal config, but the API functions bake in `CURRENT_SEASON` / `TRADE_DEADLINE_WEEK` constants (Vercel doesn't bundle `data/`); `scripts/create_new_season.py` rewrites those constants at season transition.
- **Tests:** 128 passing (`uv run pytest`). Coverage is good for scoring math and parts of the API, thin for standings, schedule, exports, and the lineup lock merge.

---

## P0 — Season blockers (fix before Week 1)

### P0.1 Consolidate the schedule to a single source of truth ✅ DONE

**Problem:** There are three independent schedule representations, and they disagree:
1. `schedule.txt` (repo root) — has the real 2026 weeks 1–15. Read by `autoscorer_json.py` (via `qpfl/schedule.py:parse_schedule_file`) to attach matchups to scored weeks.
2. `web/data/seasons/2026/meta.json` → `"schedule": []` — **empty**. `scripts/export_current.py:504` treats an empty meta schedule as "offseason", sets `current_week = 0`, and clears `data['schedule']`. As written, the site will stay in offseason mode all year even though `schedule.txt` is populated. Additionally, even once meta.json is populated, `export_current.py` never copies the schedule into `data['schedule']` — it only ever *clears* it (line 511). Nothing else writes it for 2026.
3. `scripts/export_for_web.py:121` — a hardcoded `SCHEDULE` constant containing the **2025** schedule keyed by owner names. A `full_export` run (score.yml manual input) would overwrite the site schedule with 2025 data.

**Fix (recommended):** make `schedule.txt` the single source.
- In `scripts/export_current.py`, inside `export_current_season()`: replace the `has_schedule` check on meta.json with a call to `qpfl.schedule.get_regular_season_schedule('schedule.txt')`. If it returns ≥1 week with matchups, set `data['schedule']` to it, and append playoff weeks via `qpfl.schedule.get_playoff_schedule(standings, season)` once `current_week >= 15` (seeds come from `web/data/seasons/{season}/standings.json`). Also write the same schedule array into `web/data/seasons/{season}/meta.json` so the split-file format stays consistent.
- Offseason detection should become: `schedule.txt` empty/missing **or** explicitly flagged in `league_config.json`, not "meta.json schedule empty".
- In `scripts/export_for_web.py`, ensure the current-season path (`get_schedule_data`, lines 437–, 1352, 2252) is only used for historical re-exports; the 2026+ path must not touch the hardcoded `SCHEDULE`/`OWNER_TO_CODE` constants. Simplest: in the current-season branch, delegate to the same `qpfl.schedule` code used by `export_current.py`.
- Update `NEW_SEASON_CHECKLIST.md` (§ Schedule) to say "edit `schedule.txt`" instead of hand-editing meta.json.

**Verify:** run `uv run python scripts/export_current.py --season 2026` and confirm `web/data.json` has `schedule` with 15 weeks, `is_offseason` handling still correct pre-September (see P0.2), and the Matchups → Schedule tab renders. Add a unit test: parse `schedule.txt`, assert 15 weeks × 5 matchups, rivalry week 5 flagged.

**Nuance:** today (July), the league *is* in the offseason but `schedule.txt` is already populated. Offseason vs in-season should key off the NFL calendar: `nfl.get_current_week()` combined with "does season `{year}` have any scored weeks / has the NFL season started". A pragmatic rule: `is_offseason = (today < first kickoff of season per nflreadpy schedules)`. Implement once, in `export_current.py`, and derive `current_week` from it.

### P0.2 Lineup week selector is empty until a week has been scored ✅ DONE

**Problem:** `web/app.js:initLineupForm()` (~line 5939) builds the week dropdown from `data.weeks` (already-scored weeks) plus playoff weeks found in `data.schedule`. At the start of the season nothing is scored, so there is no Week 1 option and **no team can submit a Week 1 lineup** (chicken-and-egg: weeks only appear after lineups are scored).

**Fix:** build the dropdown from `data.schedule` (all 17 weeks once P0.1 lands), defaulting the selection to `data.current_week`. Optionally restrict to `week >= data.current_week` plus already-scored weeks for review. Keep the playoff-round labels.

**Verify:** with a `data.json` where `weeks: []`, `schedule` populated, `current_week: 1` — the dropdown must offer Week 1 preselected, and `loadRosterForEditing()` must run.

### P0.3 Lineup lock merge can exceed starter limits (server-side) ✅ DONE

**Problem:** `api/lineup.py` validates `max_starters` per position against the *client-submitted* starters (`do_POST`, lines 261–268), but then `update_lineup_file()` merges locked players from the previously saved lineup back in (lines 152–169). The merged `final_pos` can exceed the limit — e.g. saved lineup has RB A (now locked, game started), client submits RB B + RB C → final lineup starts 3 RBs, and `BaseScorer`/`json_scorer` will happily score all three (no starter-count enforcement at scoring time either; `qpfl/validators.py:validate_roster` exists but is not called by `autoscorer_json.py`).

**Fix (both layers):**
1. In `update_lineup_file()`, after computing `final_starters`, enforce `len(final_pos) <= max_starters[pos]`; if exceeded, return a 400 explaining which locked players are consuming slots (the client should then unselect a slot). Move the `max_starters` dict to module level so both call sites share it.
2. Defense in depth: in `autoscorer_json.py`, after building teams, call `qpfl.validators.validate_lineup`/`validate_roster` and print warnings + trim extra starters deterministically (e.g. keep the first N in lineup order), so a bad file can never inflate a score silently.

**Verify:** extend `tests/test_api.py` (there are already lineup-lock tests at lines 300–380) with: saved lineup contains a locked RB, new submission has 2 different RBs → expect 400 (or a lineup with exactly 2 RBs, whichever semantics you choose — pick one and test it).

### P0.4 Standings tiebreakers don't match the constitution (affects playoff seeding) ✅ DONE

**Problem:** The constitution (Standings Calculation) says ties in rank points are broken by: **1) total wins, 2) total points scored, 3) head-to-head, 4) commissioner decision**. But:
- Backend `qpfl/json_scorer.py:update_standings_json` (line 375) sorts by `(rank_points, points_for)` — skips wins and head-to-head. This ordering is saved to `standings.json` and **is used for playoff seeding** by `autoscorer_json.py:get_matchups_for_week()` → `get_playoff_schedule()`.
- Frontend `web/app.js:loadData` (~line 190) re-sorts by `(rank_points, wins, points_for)` — skips head-to-head. So the site can display a different order than the seeding actually used.

**Fix:** implement one canonical comparator in `qpfl/json_scorer.py` (or a new `qpfl/standings.py`): rank_points desc → wins desc → points_for desc → head-to-head (computable from the season's week files' matchups) → stable order with a loud warning that the commissioner must decide. Persist the sorted order and a `seed` field in `standings.json`. Then delete the re-sort in `app.js` and render the persisted order (keep a defensive sort by `seed` only).

**Verify:** unit test with two teams tied on rank points where wins and points_for disagree; assert order matches constitution. Add a head-to-head tie case.

### P0.5 `score.yml` push trigger has no branch filter ✅ DONE

**Problem:** `.github/workflows/score.yml` triggers on `push` to *any* branch touching `data/**` paths. The job then runs scoring and does `git pull --rebase origin main` + `git push` (lines 465–470) from whatever ref was checked out — a push to a feature branch (like this `add-global-login` branch) can run the whole scoring/deploy pipeline and produce confusing rebase states, and `deploy-pages` publishes from that branch's `web/`.

**Fix:** add `branches: [main]` under the `push:` trigger. Same check for `expire-trades.yml` (schedule-only, fine) and `trade_blocks.yml`/`update-player-teams.yml` (verify their triggers while there).

**Verify:** push a data-file change to a feature branch; the autoscorer workflow must not run.

### P0.6 Trade accept is not atomic — accepted trades can double-execute or stick as pending ✅ DONE

**Problem:** `api/transaction.py:handle_respond_trade` executes the roster swap (`execute_trade`) **before** marking the trade accepted in `pending_trades.json` (lines 686–706). If the status write fails (e.g. exhausted 409 retries during a busy scoring push), the rosters have already been swapped but the trade remains `pending` — the partner can accept again, and `execute_trade`'s ownership re-validation won't necessarily stop a second swap (players are now on the *other* rosters, so a re-accept moves them back or errors confusingly). The reverse ordering has the opposite failure (marked accepted, never executed), which is why it was written this way — but there's no reconciliation either way.

**Fix (pragmatic, no infra change):**
1. First, atomically transition the trade `pending → accepted` in `pending_trades.json` with an added `"execution": "in_progress"` marker (inside the optimistic `mutate`, aborting if not pending — this is the concurrency gate; only one accept can win).
2. Then run `execute_trade`. On success, write `"execution": "done"` (best-effort). On failure, revert status to `pending` with the error recorded (best-effort) and return 409.
3. Teach `scripts/../expire-trades.yml` (or a small check in the scoring workflow) to flag trades stuck in `execution: in_progress` for >1 hour so the commissioner gets an email instead of silent inconsistency.

**Verify:** unit tests in `tests/test_api.py` using the existing monkeypatched in-memory store: (a) two concurrent accepts → exactly one executes; (b) roster write fails → trade returns to pending and rosters unchanged (the existing ownership-validation tests cover part of this).

### P0.7 `protect_historical.yml` doesn't protect 2025 ✅ DONE

**Problem:** the guard workflow lists `web/data_2020.json`–`data_2024.json` but 2025 is now historical (`web/data_2025.json` exists and is frozen).

**Fix:** add `web/data_2025.json` to both the `paths:` list and the grep pattern. Better: change the pattern to `data_20\d{2}\.json` minus the current season, or generate the list from `data/league_config.json` in the check step.

### P0.8 Latent crash: `qpfl/schedule.py` imports a module that doesn't exist ✅ DONE

**Problem:** `get_playoff_schedule()` at `qpfl/schedule.py:242` does `from .export_season import PLAYOFF_STRUCTURE` for `season < 2026`. `qpfl/export_season.py` does not exist — any call with a historical season raises `ImportError`.

**Fix:** either delete the `season < 2026` branch (historical seasons are frozen and never re-seeded through this path) and document that this function is 2026+, or move the legacy `PLAYOFF_STRUCTURE` from `scripts/export_for_web.py` into `qpfl/schedule.py`. Add a one-line test calling `get_playoff_schedule(standings, 2024)` so the chosen behavior is pinned.

### P0.9 Pre-Week-1 end-to-end dry run (process item) — ⏸ NOT DONE (requires a live deploy + real season data; do this in August)

Before the season, run the full loop once against real data:
1. Populate rosters post-draft (`scripts/init_rosters_from_excel.py`), confirm `data/rosters.json` matches the draft.
2. Submit a test lineup for Week 1 via the deployed site (all 10 teams' logins work; global login persists).
3. Confirm the push triggered `score.yml`, which wrote `data/lineups/2026/week_1.json`, ran `autoscorer_json.py` (0 points, games unplayed — every starter should be "not found" *before* kickoff, which is expected), exported, and deployed.
4. Confirm `kickoffs` appears in `web/data.json` (from `export_current.py:build_week_kickoffs`) once the NFL schedule is in nflreadpy — the server-side lineup lock is inert without it.
5. Run `uv run python scripts/validate_scores.py --week 1` after the first real games.

---

## P1 — Correctness and league-rule gaps

### P1.1 Trades don't validate roster limits or handle practice-squad players per the rules ✅ DONE

**Evidence:** `api/transaction.py:execute_trade` swaps arbitrary player lists. There is no check against `roster_slots` (3 QB / 4 RB / 5 WR / 3 TE / 2 K / 2 D/ST / 2 HC / 2 OL) or taxi limits. The constitution allows unbalanced trades ("Trades do not need to have equal numbers of players or picks") but requires roster compliance ("a roster spot must be available or cleared"). Also, a taxi (practice-squad) player traded in the flat roster format keeps/loses the `taxi` flag depending on which list it lands in — `execute_trade` appends taxi players to the **active** roster (`partner_roster.extend(players_to_partner)`), silently activating them, whereas the constitution says the receiving team may keep them on the practice squad (subject to the one-per-position rule) or activate them.

**Fix:**
- In `execute_trade`'s `mutate`, after the swap, validate both teams: per-position active counts ≤ `roster_slots`, taxi size ≤ 4, taxi one-per-position. On violation raise `TransactionError(400, …)` explaining the overflow. Since the constitution allows a cleared spot, the practical UX is: reject the trade execution with "team X would have 5 RBs (max 4) — release someone first / include another player in the trade". (A "pending release" flow is more faithful but much more work; rejection with a clear message is correct and simple.)
- Preserve the `taxi` flag through the swap (copy the player dict as-is), and let the receiving manager activate via the existing taxi flow. Enforce one-per-position on the receiving taxi squad; if violated, block the trade with a clear error.
- Read the slot limits from a constant module shared with `qpfl/constants.py` values (duplicate the dict in `api/transaction.py` with a comment — Vercel functions can't import `qpfl` unless it's bundled; see P3.1).

**Verify:** tests: unbalanced 2-for-1 that overflows RB slots → 400; taxi player traded stays taxi; taxi position collision → 400.

### P1.2 Released players vanish instead of entering the FA pool — ❌ NOT A BUG (commissioner-confirmed 2026-07-06)

**Original evidence:** `handle_taxi_activation` and `handle_fa_activation` remove the released player from the roster and only log the transaction; `data/fa_pool.json` is currently `[]` and only ever shrinks.

**Resolution: this is intentional, not a bug.** Released players are deliberately *not* auto-added to the FA pool; the pool is commissioner-curated (see P2.4). Do not implement the auto-append fix described in earlier drafts of this roadmap item.

### P1.3 Playoff ties resolve backwards (lower seed advances) ✅ DONE

**Evidence:** `qpfl/schedule.py:resolve_playoff_matchups` mid-bowl: `if team1_total > team2_total: team1 5th else team2 5th` — an exact tie awards 5th to `team2` (the lower seed). Same pattern in `scripts/export_for_web.py:get_schedule_data` week-16 winner computation (`s1 > s2 → t1 else t2`). The constitution: "Ties [in the playoffs] are broken by the regular season standings" — the **higher seed** must win.

**Fix:** in both places, treat `>=` as a win for the higher-seeded side explicitly: compare scores; on equality, compare seeds (`seed1 < seed2` wins). The week-16 matchup dicts already carry `seed1`/`seed2` (from `PLAYOFF_STRUCTURE_2026`); make sure `save_week_scores` (`qpfl/json_scorer.py:save_week_scores`) preserves `game`, `seed1`, `seed2`, and `bracket` on matchups — today it only copies `bracket` (line 242–244), which also breaks week-17 matchup resolution that needs `game` ids. **Sub-bug:** copy `game`, `seed1`, `seed2`, `take`, `from_games`, `determines` through to the scored week JSON.

**Verify:** unit test `resolve_playoff_matchups` with tied cumulative mid-bowl scores → seed 5 places 5th; integration-style test that a scored week 16 JSON retains `game: semi_1` etc.

### P1.4 Silent zero for players not found in stats ✅ DONE

**Evidence:** `qpfl/base_scorer.py:score_player` returns 0 points with `found_in_stats=False` when `data_fetcher.find_player` misses. Legitimate causes: game not played yet, bye week. Bad causes: stale `nfl_team` in `data/rosters.json` (find_player filters by team, so a traded player scores 0 all season), name spelling drift, nflverse rename. The week JSON keeps no signal (`found_in_stats` isn't exported by `save_week_scores`), so the website can't distinguish "0 points" from "not found".

**Fix:**
1. In `save_week_scores`, include `"found": ps.found_in_stats` on each roster entry (and `data_notes` when present).
2. In `web/app.js` matchup breakdowns (`renderRoster`/`getPlayerStatus` ~line 1831), badge starters with `found: false` after their game has completed (kickoff data exists) as "⚠ no stats matched".
3. ~~Run `scripts/validate_scores.py --week N`~~ — that script is Excel-only (2020–2025 legacy) and has no JSON-pipeline mode, so it can't validate 2026+ weeks. Implemented instead: a `score.yml` step that reads the just-scored week JSON directly (using the new `found`/`data_notes` fields from #1) and writes any not-found starters + data notes to `$GITHUB_STEP_SUMMARY`.
4. `data_fetcher.find_player` improvements: also try the match with the team filter dropped when a same-position exact name match exists league-wide (catches stale `nfl_team`), and prefer position-consistent matches — today position is accepted as a parameter but never used for filtering; add `.filter(pl.col('position') == position)` as a first pass with fallback to unfiltered (nflverse position values: QB/RB/WR/TE/K).

**Verify:** unit test: roster says `nfl_team: "PIT"` for a player whose stats row says `LV` → still found via fallback, with a data note. Existing name-matching tests in `tests/test_scoring.py` should keep passing.

### P1.5 Trade deadline period and offseason edge cases ✅ DONE

**Evidence:** `api/transaction.py`: `TRADE_DEADLINE_WEEK = 12`, blocks `12 <= current_week <= 17`. `get_authoritative_current_week()` reads `web/data.json` `current_week` and **falls back to 1 (deadline open) on any error** — a Vercel/GitHub hiccup during week 13 lets a trade through. Also the constitution says the deadline "concludes after the championship is over" — the code matches (blocks through 17), good — but `NEW_SEASON_CHECKLIST.md:139` claims "`trade_deadline_week` in `league_config.json` gates the API automatically," which is false (the API uses its own constant; `league_config.json` isn't bundled on Vercel).

**Fix:**
- Fail closed on ambiguity *during the plausible deadline window*: if `web/data.json` can't be read, return 503 "cannot verify trade deadline, try again" rather than defaulting open. (Offseason proposals still work because when data.json *is* readable, `current_week` is 0/18.)
- Fix the checklist text; note that `scripts/create_new_season.py` step 5 is what updates the API constants.

### P1.6 Lineup submissions accept players not on the roster ✅ DONE

**Evidence:** `api/lineup.py` never checks that submitted starter names exist on the team's roster (it already fetches `data/rosters.json` for the lock check). The scorer ignores unknown names, so the failure mode is a manager typo (via a hand-crafted request) silently starting nobody — and taxi players can be named as starters (json_scorer skips taxi players entirely, so they'd score 0 while occupying a starter slot).

**Fix:** in `update_lineup_file` (it already loads rosters when computing locks — hoist that), validate every submitted name is on the team's **active** roster at the correct position; 400 otherwise. Keep the check tolerant of the `(TEAM)` suffix style differences by comparing exact `name` strings from `rosters.json` (that's what the UI submits).

**Verify:** test: submission with a taxi player or unknown name → 400 naming the offender.

### P1.7 `update_standings_json` counts a "week file with no matchups" wrong / duplicate-abbrev weeks ✅ DONE

Minor but worth pinning while touching standings (P0.4):
- `has_scores` is `any(total > 0)` (`qpfl/json_scorer.py:225`) — an all-zero-or-negative week (theoretically possible: every team scores ≤0) would be treated as unscored and skipped by standings. Use "any starter had `found_in_stats`" or "scored_at exists and week has kickoff-passed games" instead.
- Standings accumulate only from `week_data['matchups']`; if a week file was scored while `schedule.txt` was missing (matchups omitted), teams get points_for but no W/L — actually they get *nothing* since only the matchup loop adds PF/PA. Make `autoscorer_json.py` **fail loudly** (exit 1) if a regular-season week has no matchups from the schedule, instead of writing a matchup-less week file.

### P1.8 WR starter limit disagreed between `qpfl/constants.py` and the live site ✅ DONE (discovered while fixing P0.3/P3.5)

**Evidence:** `README.md`, `api/lineup.py:MAX_STARTERS`, `web/app.js:LINEUP_CONFIG.positions`, and `data/league_config.json:starter_slots` all agreed the real limit is **2** WR starters — that's what the site and API have actually enforced all season. `qpfl/constants.py:STARTER_SLOTS` had `WR: 3`, which is what `qpfl/validators.py:validate_roster`/`validate_lineup` and the new P0.3 defense-in-depth cap in `qpfl/json_scorer.py:build_fantasy_team_from_json` used.

**Resolution (commissioner-confirmed 2026-07-06): 2 WR is correct.** Fixed `qpfl/constants.py:STARTER_SLOTS['WR']` to `2`, `docs/API.md`, and the tests that assumed 3 (`tests/test_validators.py`, `tests/test_integration.py`). `docs/history/PHASE1_IMPROVEMENTS.md` left as-is (historical changelog entry, not current documentation).

---

## P2 — Rule automation, tooling, and hardening

### P2.1 Unimplemented constitution scoring rules (manual adjustments) ✅ DONE

- **Head Coach ejection = −1**, **Head Coach fired midseason = −5** (applies the week after firing if started) — not represented anywhere in `qpfl/scoring.py:score_head_coach`.
- Commissioner may need one-off corrections (stat corrections, rulings).

**Fix:** add a manual-adjustment mechanism rather than trying to automate firings:
- New file `data/score_adjustments.json`: `[{"season": 2026, "week": 5, "team": "GSA", "player": "Andy Reid", "points": -5, "reason": "HC fired midseason"}]`.
- `autoscorer_json.py`: after `score_week_from_json`, apply adjustments for that season/week — adjust the matching player's `score` (append a `breakdown['adjustment']`) and the team total.
- Surface adjustments in the matchup breakdown UI (the breakdown key will flow through automatically; verify `renderBreakdown` labels it sensibly).

**Verify:** unit test that a −5 adjustment changes the team total and survives re-scoring (idempotent, since scoring recomputes from scratch each run).

### P2.2 Practice-squad (taxi) rule automation ✅ DONE (manual-trigger script, not calendar-automated)

Constitution rules not enforced anywhere:
- Max one taxi player per position (violations only preventable at draft time today).
- Taxi players auto-release at the midseason-draft Thursday and at championship conclusion.
- Players may never be *sent down* to taxi (the API has no such action, so this holds today — keep it that way).

**Fix:** a small scheduled/manual workflow or an addition to `create_new_season.py` + a midseason manual script `scripts/release_stale_taxi.py` that moves lingering taxi players to the FA pool (works with P1.2's pool-append helper). Add the one-per-position check to `init_rosters_from_excel.py` and to trade execution (P1.1).

### P2.3 Commissioner/admin capabilities ✅ DONE

There is no admin path: bad transactions can only be fixed by hand-editing JSON in git (workable, but undocumented and error-prone under the optimistic-concurrency scheme — a manual commit can race the API).

**Fix (lightweight):**
- Add `TEAM_PASSWORD_ADMIN` env var; accept `team: "ADMIN"` in `validate_team` for a new `admin_adjust` action in `api/transaction.py` that can: release/add a player on any roster (with FA-pool sync), reverse a completed trade, and append a manual entry to the transaction log. All admin actions log with `"admin": true`.
- Document the git-edit fallback in `CONTRIBUTING.md`: pull latest, edit `data/*.json`, push to main, and note that in-flight API writes may 409-retry against your commit (that's fine — they re-apply on fresh content).

### P2.4 FA pool seeding tool ✅ DONE (names-file/args mode; `--undrafted-from Drafts.xlsx` auto-derivation not implemented)

The 2025 pool was hand-written. For 2026 add `scripts/seed_fa_pool.py`:
- Input: a list of names (file or args) or `--undrafted-from Drafts.xlsx`; look up `nfl_team`/`position` via `nflreadpy.load_players()` (reuse the matching logic from `scripts/update_player_teams.py`); append to `data/fa_pool.json` with `available: true`.
- Run after each draft. Document in `NEW_SEASON_CHECKLIST.md` (replace the current "reset to []" instruction with "reset, then seed").

### P2.5 Workflow observability and failure alerts ✅ DONE

- `score.yml` failures are silent unless someone checks the Actions tab. Add a final `if: failure()` step emailing `GSA_EMAIL` (reuse the SMTP snippet) or opening a GitHub issue.
- Emit a job summary each run: week scored, per-team totals, validate_scores warnings, players-not-found count (pairs with P1.4.3).

### P2.6 Auth hardening (right-sized for a friends league) ✅ DONE (compare_digest + README note; CORS left as `*` per this section's own "harmless" framing)

- Password comparisons use `!=`; switch to `hmac.compare_digest` in all six `api/*.py` files (one-line each, or via the shared module in P3.1).
- Passwords ride in `localStorage` and in every request body over HTTPS — acceptable for this threat model; don't build sessions/JWTs. Do add a note to `README.md` that all team passwords are commissioner-issued and rotatable via Vercel env vars.
- CORS is `*` on all endpoints; harmless given password auth, but pinning `Access-Control-Allow-Origin` to the site origins is a two-line improvement.

### P2.7 Scoring math consistency: negative yardage truncation

`score_skill_player` uses `int(yards / N)` (truncates toward zero: −19 rushing yards → 0 pts) while `score_offensive_line` uses `math.floor` (−19 net passing → −1 pt). Historical results were produced with exactly this asymmetry, so **do not change silently**: confirm the intended rule with the league, document the ruling in the constitution/README, and add regression tests for negative-yardage cases either way. If skill players should also floor, gate the change at season 2026 (pass `season` into the scoring functions or accept the constant behavior league-wide going forward).

---

## P3 — Consolidation and tech debt

### P3.1 De-duplicate the six Vercel functions' GitHub plumbing — ⏸ NOT DONE (deliberately deferred)

Deferred rather than attempted blind: this touches the shared read/write plumbing of all six production write endpoints (lineup, trade, taxi/FA, team-name, team-avatar, rule-changes/nfl-draft), each of which now has its own test suite in `tests/test_api.py` that monkeypatches that file's specific function names. A refactor here is exactly the kind of change that benefits from a live Vercel preview deploy to sanity-check each endpoint (as the existing verify note for this item says) — which isn't available in this session. Do this with a preview deploy in hand, updating each test file's patch targets to the shared module as you go.

`api/lineup.py`, `transaction.py`, `rule-changes.py`, `nfl-draft.py`, `team-name.py`, `team-avatar.py` each re-implement `_github_headers` / `github_get_file` / `github_put_file` / `update_json_file` / `get_team_password` / `validate_team` with drift between copies (transaction.py's retry re-fetches fresh content; lineup.py's is hand-rolled; team-name.py has **no** 409 retry at all — a concurrent scoring commit can fail a rename).

**Fix:** create `api/_github_util.py` (underscore-prefixed files are not exposed as endpoints by Vercel's Python runtime, and sibling-module imports work within `api/`). Move the canonical implementations (use transaction.py's versions — they're the most evolved), then shrink each endpoint to its handlers. Check `.vercelignore` doesn't exclude it. Port team-name.py to `update_json_file` to gain retries.

**Verify:** `tests/test_api.py` monkeypatches `api/transaction.py` seams — update patch targets to the shared module; deploy to a Vercel preview and hit each endpoint's `validate` action.

### P3.2 Retire or fence the legacy exporter ✅ DONE (fenced via P0.1; `scripts/export/` migration explicitly optional, not done)

`scripts/export_for_web.py` (2,623 lines) carries the 2025 hardcoded schedule, owner-name maps, and Excel parsing. It's still reachable from `score.yml` via the `full_export` manual input, where it would clobber 2026 data with 2025 assumptions (P0.1.3).

**Fix:** after P0.1, make `export_for_web.py` refuse to touch the current season unless `--reexport-historical YEAR` is passed (it has the flag already — make it mandatory, no default full run), and change `score.yml`'s `full_export` branch to run `export_current.py` + `export_hall_of_fame.py` only. Long-term, fold what's still needed into `scripts/export/` per `docs/ARCHITECTURE.md` — but that migration is optional; the legacy `data.json` format works and the frontend depends on it.

### P3.3 Frontend monolith hygiene (don't rewrite; patch) ✅ DONE (dedupe + lint items; XSS audit not re-done)

`web/app.js` is 8,760 lines and works. Do not restructure before the season. Cheap wins:
- Delete the duplicate `escapeHtml` (defined at line 13 **and** line 8752; identical bodies, second wins by hoisting).
- The manage flows read `manageState.password` in ~10 places; they're consistent — leave them.
- 120 `innerHTML` sites with data that is league-controlled → low XSS risk; when touching a renderer, route strings through `escapeHtml` (player names with apostrophes already flow through in most places).
- Add `web/app.js` to some minimal lint (even `node --check web/app.js` in `test.yml`) so syntax errors can't deploy.

### P3.4 Config source-of-truth notes ✅ DONE

`CURRENT_SEASON`/`TRADE_DEADLINE_WEEK` are intentionally baked into `api/*.py` (Vercel doesn't ship `data/`), and `scripts/create_new_season.py` rewrites them. Add a test (`tests/test_config_consistency.py`) that asserts: `league_config.json.current_season` == `api/transaction.py:CURRENT_SEASON` == `api/lineup.py:CURRENT_SEASON` == `score.yml` `CURRENT_SEASON`, and `league_config.trade_deadline_week` == `api/transaction.py:TRADE_DEADLINE_WEEK` (parse with regex, same patterns the transition script uses). This turns "forgot to run the transition script" into a red CI instead of a mis-filed lineup.

### P3.5 Documentation corrections (quick batch) ✅ DONE

- `README.md` D/ST table: shows "18–31 → −2"; constitution and code say 18–27 → 0, 28–31 → −2. Fix the table (add the 0-point band).
- `README.md` project structure lists `validate_scores.py` at repo root; it lives at `scripts/validate_scores.py` (update the two usage snippets too).
- `NEW_SEASON_CHECKLIST.md:137`: "lineups to `data/lineups/YYYY/week_N.xlsx`" → `.json`; §Schedule → point to `schedule.txt` after P0.1; line 139's deadline-gating claim → see P1.5.
- `docs/2026_SEASON_CHANGES.md`: `scripts/sync_rosters.py` doesn't exist → `scripts/sync_rosters_to_excel.py`; `python -m scripts.export.all` — verify `scripts/export/` package still supports this or update to `export_current.py`.
- `create_new_season.py` step 8 resets pending trades but not `data/fa_pool.json` or `data/trade_blocks.json` — add both (fa_pool → `[]`, trade_blocks → `{}`), then update the checklist.
- Root-level `Rosters.xlsx`, `Drafts.xlsx`, `Traded Picks.xlsx`, `schedule.txt` — add a short "root files" section to README saying which are live inputs (schedule.txt, Drafts.xlsx) vs generated backups (Rosters.xlsx).

### P3.6 TODO.md feature (Draft Class Performance Analysis) ✅ DONE

Career data is aggregated into `hall_of_fame.json`; Draft History and the shared player profile expose draft-class output, position rank, ownership, transactions, current roster status, and awards.

---

## Test roadmap (add as items above land)

| Area | Test | Priority |
|------|------|----------|
| Schedule | `parse_schedule_file` on real `schedule.txt`: 15 weeks, 5 matchups, rivalry week 5 | P0.1 |
| Export | `export_current_season` populates `schedule` and correct `current_week`/`is_offseason` (fixture dir) | P0.1 |
| Lineups | lock-merge cannot exceed starter limits; non-roster/taxi starters rejected | P0.3, P1.6 |
| Standings | tiebreakers (wins, PF, H2H); ¼-point top-half tie already covered? add if not | P0.4 |
| Trades | atomic accept (double-accept race); roster-limit overflow; taxi preservation | P0.6, P1.1 |
| FA | released player enters pool; claim after release | P1.2 |
| Playoffs | tie → higher seed advances; scored week 16 retains `game`/`seed` fields; week 17 resolution end-to-end with synthetic scores | P1.3 |
| Config | season/deadline constants consistent across files | P3.4 |
| Adjustments | manual adjustment applied idempotently | P2.1 |

---

## Sequencing

1. **Now (July):** P0.1–P0.8, P3.5 doc batch, P3.4 consistency test. These are all small, independent, and testable offline.
2. **Pre-draft (August):** P1.1, P1.2, P1.6, P2.4 (FA seeding), P2.2 taxi checks in `init_rosters_from_excel.py`, P3.1 API consolidation (do before P1.1 so slot-validation lands once).
3. **Pre-Week-1 (late August/early September):** P0.9 end-to-end dry run, P1.4 (not-found surfacing), P1.5, P2.5 alerts. Populate rosters post-draft; verify kickoff export.
4. **In-season:** P2.1 adjustments (before anyone's coach gets fired), P2.3 admin path, P1.3/P1.7 before week 15 (playoff seeding depends on them — earlier is better since standings accumulate all season; the sort fix P0.4 must be in from Week 1).
5. **Offseason 2027:** P3.2 exporter retirement, P3.3 frontend cleanup, P3.6 draft analysis, ARCHITECTURE.md phase 4/5 decision.
