# Plan: Expand and redesign the Hall of Fame

## Context

The League → Hall of Fame page (`renderHallOfFame`, `web/app.js:6636`) is one long scroll: season cards, the owner table, team records, player records and Rivalry Week, with a small jump index. It has outgrown that shape:

- Records are pre-formatted strings (`"Holder (ABBR) - 167 (Week 15, 2025)"`) that the UI regex-parses (`hofRecordRow`, `app.js:6578`), so they can't be filtered, grouped or linked to players/owners reliably.
- Only 9 record categories exist. `fun_stats` (league-total weeks, closest games, combined scores) is exported but never shown. `mvps` is empty, and every player's `awards` is empty.
- Owners appear only as a table row. There's nowhere to see one person's career across franchises and co-ownerships.
- Franchise history lives only on each team's Hall of Fame tab (`renderTeamHistory`, `app.js:5613`), with no league-level index.
- Players have rich career data (`player_career_stats`, ~630 profiles) but no leaderboards or honors on the HoF.

Goal: a tabbed Hall of Fame (Overview, Records, Owners, Franchises, Players) with structured data, many more records, owner profile pages, a franchise index, and player leaderboards with computed and manual honors.

Decisions made with the user: tabbed sections, separate owner profiles, and both manual and computed player honors.

## Approach

### 1. Data layer (export): structured and expanded

Work in `scripts/export_hall_of_fame.py`. It's already 2,800 lines, so put the new calculations in a sibling module `scripts/hof_records.py` and call it from `generate_hall_of_fame` (`:2570`). Reuse the existing helpers: `load_season_data`, `get_week_name`, `get_team_score`, `clean_team_name`, `franchise_codes`, `get_owner_codes`, `_owner_identity_code`, `_owner_label_for_team`, `FRANCHISE_LINEAGE`, `OWNER_IDENTITY_PRIMARY`, `calculate_perfect_lineups`, and the Connor Bowl naming pass.

**a. Structured record entries.** Replace each record group's string list with
`{id, title, category, scope, unit, entries: [{rank, value, team, owner_code, team_name, player, profile_key, position, season, week, week_label, opponent, detail}]}`.
Keep the `records` string list for one release so `export_weekly_facts.py` and older clients keep working, then remove it. Check `export_weekly_facts.py` for its uses of `hof.*` first.

**b. New records.** Each is top 5, computed from week files. The rosters already include starters, bench and scores.

| Category | Records |
|---|---|
| Team · game | most/fewest points (existing), biggest margin (existing), most points in a loss, fewest points in a win, most bench points left unused, lowest lineup efficiency (starters ÷ best possible) |
| Team · season | most PF, best/worst PPG, best/worst record, longest win and loss streaks (across seasons), most 100-point games |
| Playoffs | highest playoff score, biggest playoff win, closest playoff game, highest championship-game score |
| Player · game | existing four, plus best bench performance (not started) and best playoff game |
| Player · season | most points overall and by position (QB/RB/WR/TE/K/D/ST) |
| Player · career | most points overall and by position, most starts, most franchises played for, most starts for one franchise, most 30-point games |
| League / oddities | fold in `fun_stats` (league-total weeks, closest games, combined score), fastest cycle (existing), perfect lineups (existing) |

**c. Owner profiles.** Add `owner_profiles: {CODE: {...}}` keyed by owner identity, which follows `OWNER_IDENTITY_PRIMARY` (so `CGK/SRY` maps to `CGK`). Each profile holds:
- display name and eras, from `_summarize_owner_eras` and the `manual_honors.team_ring_of_honor[*].owners` entries
- a season-by-season timeline: franchise, team name, record, PF, finish badge (`_season_finish_badges`)
- career totals: W-L-T, PF/PA, PPG, playoff record, rings and podiums, prestige (reuse the `calculate_owner_stats` output)
- best and worst seasons
- head-to-head against every other owner, built from the existing `_owner_head_to_head` data
- perfect lineups
- the most-started players (top 10)
- records held: back-references to record entry ids where `owner_code` matches

**d. Franchise index.** Add `franchises: [{abbrev, lineage_codes, active, current_owner, owners, team_names, seasons, record, rings, best_finish}]`, from `FRANCHISE_LINEAGE`, `team_hall_of_fame` and the `team_names` in manual honors.

**e. Player leaderboards and honors.**
- `player_leaderboards`: career and per-season top 25 overall and by position, plus PPG (minimum 16 games). Entries are `profile_key` references, so `player_career_stats` doesn't get duplicated.
- Computed awards, written into `player_career_stats[key].awards` (the player modal already renders badges, `app.js:16974`):
  - season scoring leader at each position
  - All-QPFL team per season: the top season scorers filling the lineup slots
  - championship-winning starter
- Manual honors: add an optional `mvps: [{year, name, position, team, note}]` and `awards: [...]` to `web/data/shared/manual_honors.json`. Merge them into `mvps` and into the player awards. A manual entry wins over a computed duplicate.

**f. Size.** `hall_of_fame.json` is already 2.3 MB. The new sections are small because they use key references. Check the file size before and after; if it grows by more than about 10%, split the new sections out into `web/data/shared/hall_of_fame_records.json`.

### 2. UI shell: tabbed Hall of Fame

- Inside the Hall of Fame subview (`index.html:349`), add a second-level tab row: Overview · Records · Owners · Franchises · Players.
- Routes are `#history/records/<tab>` and `#history/records/owners/<CODE>`. Extend the route parsing near `app.js:1152` and `:11895`, and map the old `?section=hof-*` links onto the matching tab so existing links keep working.
- Change `renderHallOfFame()` into a dispatcher that calls `renderHofOverview`, `renderHofRecords`, `renderHofOwners`, `renderOwnerProfile(code)`, `renderHofFranchises` and `renderHofPlayers`. Each renders only when its tab is opened.
- Keep the existing building blocks: `matchupLink`, `hofLinkWeeks`, `isMyFranchise`/`myTeamClass` (my-team highlighting), `playerProfileButton` (`:200`), `teamProfileButton`, `seasonAwareRoute`, `escapeHtml`.
- Style with the existing tokens and `--space-*` scale, following `docs/PLAN_ui_polish.md` (no gradients or pill chips, restrained number colors), and make every tab work at 390px.

### 3. Tabs

- **Overview.** "This Week in QPFL History" (`renderWeeklyFactsCard`); a champions timeline (year → champion, linking to the owner profile); records set or tied this season (entries where `season === LIVE_SEASON`); and a "the marquee records" strip with the #1 entry for about six headline records.
  - Note: `tests/test_hall_of_fame_ui.py:22` asserts that the old `league-hof-summary` was removed. This Overview is a deliberate replacement with different content, so update that test rather than restoring the old class.
- **Records.** Category chips (Team game · Team season · Playoffs · Player game · Player season · Player career · League) and a position filter for player records. Each record is a card with the #1 entry featured and ranks 2–5 listed below it. Players open the player modal, teams open the franchise, and weeks link to the matchup. Season finish cards move here as "Seasons", or into Overview's timeline; choose whichever reads better once it's built.
- **Owners.** A sortable leaderboard (the current owner table: Win%, rings, prestige, PF/PPG; keep the prestige formula note). Each owner card links to the **owner profile**: header with name, eras and rings; season timeline strip; career stat tiles; head-to-head grid; records held; most-started players; perfect lineups.
- **Franchises.** Cards for every franchise, active and defunct, showing lineage, owners over time, team names, rings and best finish. Each links to the existing team HoF tab (`#teams/history/ABBR`). Rivalry Week records move here. Enrich `renderTeamHistory` with a season-by-season finish table and a "records held" list.
- **Players.** Career and season leaderboards with position and season filters; an MVP and awards list (manual and computed); the All-QPFL team per season; and a league-wide Ring of Honor aggregated from `manual_honors.team_ring_of_honor[*].players`.

### 4. Delivery order

Each step is its own PR or commit, and each leaves the site working:
1. Export: structured entries and new records, plus tests.
2. UI shell: tabs, routes, and the existing sections moved into tabs.
3. Records tab.
4. Owner profiles (export and UI).
5. Franchises tab and team HoF enrichment.
6. Players tab, awards and manual MVPs.
7. Overview tab.


## Critical files

- `scripts/export_hall_of_fame.py`: wire up the new sections; structured entries
- `scripts/hof_records.py` (new): new records, owner profiles, franchise index, leaderboards, awards
- `web/data/shared/manual_honors.json`: optional `mvps` / `awards`
- `web/app.js`: `renderHallOfFame` and the new tab renderers, routing (~`:1063–1220`, `:11895`), `renderTeamHistory`
- `web/index.html`: the HoF tab row
- `web/styles.css`: HoF section styles (~`:5139–5540`, `:177–221`)
- Tests: `tests/test_export_hall_of_fame.py`, `tests/test_hall_of_fame_ui.py`, `tests/test_hof_and_draft_challenge_ui.py`, `tests/test_hof_draft_ui.py`

## Verification

- `uv run pytest tests/test_export_hall_of_fame.py tests/test_hall_of_fame_ui.py tests/test_hof_and_draft_challenge_ui.py tests/test_hof_draft_ui.py`, then the full `uv run pytest`.
- Add unit tests for each new calculation, using small synthetic season fixtures in the style of the existing `test_export_hall_of_fame.py`: streaks across seasons, co-owner identity folding, bench-points record, manual MVP overriding a computed award.
- Regenerate with `uv run python scripts/export_hall_of_fame.py --current-season 2026 --completed-through 8`. Spot-check known values (CGK's 167 in Week 15 of 2025, Griff's 3 rings, the 2020–2025 champions) and compare file size before and after.
- Serve `web/` locally (`python -m http.server` or the run skill) and check each tab and an owner profile at 1440px and 390px in light and dark mode. Check that the old `?section=hof-*` links and `#teams/history/ABBR` still resolve, that my-team highlighting works, and that clicking a player opens the modal with award badges.
- Confirm `.github/workflows/score.yml:296` still runs the export unchanged (same CLI flags).

## Outcome (2026-11-05)

All seven steps shipped. Where the build differs from the plan above:

- **Separate data file.** The record book, owner profiles, franchise index and player honors live in `web/data/shared/hall_of_fame_records.json` (built by `scripts/export_hall_of_fame.py`, loaded only by the Hall of Fame and team Hall of Fame pages, 60-second cache in `vercel.json`). Adding them to `hall_of_fame.json` would have grown the file every view loads by 17%.
- **Legacy record strings kept.** `team_records`, `player_records` and `fun_stats` still export as strings; the site reads the record book instead.
- **New modules.** `scripts/hof_records.py` (record book), `scripts/hof_owners.py` (owner profiles), `scripts/hof_franchises.py` (franchise index), `scripts/hof_players.py` (leaderboards, awards, rings).
- **Ties.** Record groups list five entries and count further ties (`more_tied`) instead of dropping them. League-total weeks count any week every team played (so the 987-point 2024 Semi-Finals is the record).
- **Hall of Shame.** Unwanted records are flagged (`SHAME` in `hof_records.py`) and listed separately on owner and team pages.
- **MVPs.** Moved from a hand-kept "QPFL MVPs" entry in the generated `hall_of_fame.json` to `manual_honors.json` (`mvps`, plus `player_awards` for other hand-picked awards).
- **Finish fix.** Team finishes match the names of whoever ran the seat that season, which restored Joe Ward's 2023 3rd place to his old seat (AST).
