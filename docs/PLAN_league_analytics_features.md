# Plan: League analytics features (inspired by HFL Analytics / brazenzone.com)

## Context

A friend's league site (brazenzone.com, "HFL Analytics") has ~130 analytics views. The goal
is to bring the best of them to QPFL **without cluttering the site**: no new top-level nav,
new material lives in collapsed sections, sub-tabs of existing views, or Hall of Fame
sections, and anything that has nothing interesting to say renders nothing.

Priorities from the user:
1. **Pregame matchup extras**: storylines, revenge games, matchup stats, records that
   could fall. These go inside each matchup card and in a new league-wide Preview tab.
2. **Playoff Machine** (managers play out scenarios) as a **Standings sub-tab**, plus a
   **Rooting Guide**.
3. **Scorigami** in the Hall of Fame, with a chart.
4. Everything else, planned in full: what-if standings, lineup-decision stats, trade and
   draft grades, Elo, manager fingerprints, nemeses, weekly awards, Season Wrapped.

What already exists and is reused:
- **Matchups and facts:** the matchup card renderers (`web/app.js:3290`, `:3648`);
  `renderH2HBadge` (`:6273`); the postgame weekly-facts pipeline (`qpfl/weekly_facts.py`,
  `DETECTORS` at `:3206`), including `_revenge_facts` (`:2124`), `_head_to_head_facts`
  (`:962`), `_streak_facts` (`:728`) and `_career_milestone_facts` (`:2873`).
- **History loading:** `flatten_season` / `load_history` / `roster_timeline` in
  `scripts/export_weekly_facts.py`; the record book in `scripts/hof_records.py`; and
  `player_career_stats[].franchise_stints` in `hall_of_fame.json`.
- **Playoff odds:** `simulatePlayoffOdds` (`:4744`) and `computePlayoffStatus` (`:4686`).
- **Standings and grading:** `computeExpectedWins` (`:4328`), `computeOptimalLineup`
  (`:1954`), `tradeVerdict` (`:8510`) and `renderDraftPerformanceSummary` (`:9667`).
- **Viewer's team:** `myTeamAbbrev()` (`:11509`).

Facts about the data:
- **Coverage:** player-level weekly data, including the bench, covers every season
  (2020–2026).
- **Scores:** all are whole numbers.
- **No charts yet:** the site has no chart library and no SVG helpers.
- **Hardcoded format:** the front end hardcodes the playoff format (`PLAYOFF_SLOTS=4`,
  `REGULAR_SEASON_LAST_WEEK=15`, `app.js:4456`) instead of reading
  `data/league_config.json`.

**Step 1 of implementation:** copy this plan to `docs/PLAN_league_analytics_features.md`.
Each phase below ships as its own PR.

**Suggested order:** 0 → 2 → 1 → 3 → 4 → 5 → 6 → 7 → 8. The Playoff Machine comes early
because it's Week 10 of 15 and it's only useful during the regular season.

---

## Phase 0: Shared foundations

**0a. League format in the browser.** Have `scripts/export_for_web.py` write
`playoff_slots`, `regular_season_weeks`, `playoff_weeks` and `playoff_structure` (from
`qpfl/config.py`) into `web/data/seasons/<yr>/meta.json`. Add
`seasonFormat(season)` in app.js, which reads meta and falls back to today's constants
(and to 14 weeks for seasons up to 2021). Replace direct uses of `PLAYOFF_SLOTS` and
`REGULAR_SEASON_LAST_WEEK` with it.

**0b. A small SVG chart helper.** Add a block of pure functions near the other render
helpers in app.js. Each returns an SVG string and uses existing CSS custom properties so
it works in light and dark themes:
- `svgHeatGrid({cells, xDomain, yDomain, cellTitle})`, for Scorigami
- `svgLineChart({series, xLabels, yDomain})`, for Elo
- `svgBarPair(...)`, mirrored bars for the matchup comparison and fingerprints

Each chart gets a `<title>`/`aria-label`, and a `<details>` table fallback for screen
readers. No library.

**0c. A pregame export.**
- **New module:** `qpfl/pregame.py`, pure and testable. It works from `TeamGame` and
  `PlayerGame` rows, the upcoming schedule (`meta.json`), the current week file (rosters,
  starters, `projected_points`), `hall_of_fame.json` (`player_career_stats`,
  `rivalry_records`) and `hall_of_fame_records.json` (`record_book`).
- **New CLI:** `scripts/export_pregame.py --season S --week W`, which writes
  `web/data/seasons/<S>/pregame/week_<W>.json`:
  ```json
  {"season":2026,"week":11,"generated_at":"…",
   "matchups":{"GSA|J/J":{"storylines":[…],"revenge":[…],"records":[…],"milestones":[…]}},
   "league":{"records":[…],"milestones":[…],"revenge":[…]},
   "names":{…}}
  ```
- **Item format:** items use the weekly-facts shape
  (`{id, category, subjects, template, notability, tags}`) and the same
  `{team:X}`/`{has:X}`/`{is:X}` tokens. The front end reuses the facts token renderer
  used by `loadWeeklyFacts` (`app.js:7988`).
- **When it runs:** add a step to `.github/workflows/score.yml` after the facts step that
  exports for `lineup_week`, every run, writing only on change (same pattern as the Hall
  of Fame writer). That keeps revenge games and records current as lineups change.
- **Fallback:** if no week file exists yet (future weeks), rosters come from
  `data/rosters.json`.

---

## Phase 2: Playoff Machine and Rooting Guide (Standings)

**2a. Refactor the simulation.** Split `simulatePlayoffOdds` into a pure core,
`runPlayoffSim({standings, scoresByTeam, remaining, fixed, trials, seed, format})`:
- `fixed` maps `"week|A|B"` to the winning abbreviation. In the head-to-head loop
  (`:4858`), when the sampled winner contradicts a fixed pick, swap `s1` and `s2`. That
  keeps the top-half rank-point logic consistent.
- It returns the current `byTeam` plus `seedCounts[abbrev][seed]` and bracket odds for
  each bracket in `playoff_structure` (Championship, Mid Bowl, Sewer Series, Toilet Bowl).
- **Keep current behaviour:** `simulatePlayoffOdds` becomes a thin wrapper, so
  `renderPlayoffOdds` output doesn't change.
- **Clinch logic:** extend `computePlayoffStatus` to take `fixed`, so the Machine can say
  "clinched in this scenario".

**2b. Standings sub-navigation.** In `index.html`, add a subnav to `#standings-view`
with **Table | Playoff Machine** (`data-parent="standings"`). Move the existing content
into `#standings-table-subview`. Add `standings` to the `activateGenericSubview` branch
in `navigateToView` (`:12952`), plus `DEFAULT_SUBVIEW`, `pageTitleFor` and
`PAGE_DESCRIPTIONS`. Add a "Play out scenarios →" link in the playoff odds card header.
Show the tab only for the live season while regular-season weeks remain; otherwise
show a short "Season decided" note.

**2c. Playoff Machine UI** (`renderPlayoffMachine()`):
- **Left:** remaining weeks as compact rows. Each matchup is a three-state segmented
  toggle: `[Team1] [Sim] [Team2]`. Shortcuts: "Favorites win" (higher stabilized mean),
  "Reset", "My team wins out" (when logged in).
- **Right:** the live odds table with playoff %, change versus baseline (pp), and a seed
  distribution strip (stacked CSS bar, seeds 1–10). Also shows bracket odds, plus
  "Clinched/Eliminated in this scenario" chips.
- **Performance:** about 2,000 trials, recomputed after a 150ms debounce. Measure it; if a
  full re-sim is over 100ms on a phone, move `runPlayoffSim` into an inline Blob Web
  Worker.
- **Shareable state:** picks are encoded in the hash
  (`#standings/machine?picks=11.GSA,11.J~J,…`) so a scenario can be shared in the group
  chat.
- **Logged in:** your team's row is pinned and highlighted.

**2d. Rooting Guide** (`computeRootingGuide(team, week)`):
- For each game in the next week not involving `team`, run the sim twice (A wins, B wins)
  with the **same seed**. Common random numbers keep the noise small. Swing is
  `odds(A) − odds(B)`; sort by absolute swing.
- Use about 1,500 trials, and cache by `(completedThrough, team, fixedPicksHash)`.
- **Where it appears:**
  1. A panel on the Playoff Machine (team selector, defaulting to `myTeamAbbrev()`).
     It also respects the user's current picks.
  2. The Matchups Preview tab (1d).
  3. One line in the viewer's own matchup card, e.g. "Root for PRT over CGK (+11 pp)".
- **Stakes for each game:** reuse it for a per-matchup "stakes" storyline: the two
  teams' odds if they win versus lose, e.g. "Win and GSA's odds go to 81%; lose and they
  fall to 37%."
- Only shown while odds aren't decided (skip teams that have clinched or are eliminated).

---

## Phase 1: Pregame matchup extras (Matchups)

**1a. Card Preview drawer.**
- **Where:** in both card builders (`renderScheduledMatchupCard` `:3290` and the scored
  branch `:3648`), add a collapsed `<details class="matchup-preview">` under the
  `vs-container`.
- **When:** only before the matchup is final (use the `matchupFinal` logic at `:3715`).
  After that, the existing weekly-facts recap takes over.
- **Summary line:** small text chips such as "Revenge game · Record watch · 3 storylines",
  so it stays out of the way until opened. If there's nothing to show, it renders nothing.
- **Contents, in order:**
  - **Storylines** (2–4, by notability)
  - **Tale of the tape**
  - **Revenge watch**
  - **Records & milestones within reach**
  - **Stakes** (from 2d)
- **Data:** the pregame file is loaded lazily on first open (`fetchJsonResource`).

**1b. Storylines** (in `qpfl/pregame.py`). Candidates, each scored for notability like
the facts:
- **Series history:** the all-time series and the last meeting (score, week, notable
  margin), reusing the `_head_to_head_facts` helpers.
- **Streaks:** each team's current win/loss or top-half streak, and the series streak
  ("GSA has won 5 straight vs J/J").
- **Rematches:** a playoff rematch or last season's championship rematch.
- **Rivalry week:** the `is_rivalry` flag, and the Rivalry Week record.
- **Matchup type:** "1 vs 2 in the standings", "both teams need a win", "battle for the
  top half".
- **Owner and franchise:** history such as a former co-owner or franchise lineage, from
  the existing owner facts.

**1c. Revenge watch** (pregame counterpart to `_revenge_facts`):
- **Who qualifies:** a player rostered by A (starters first; bench players are flagged as
  "on the bench") whose `franchise_stints` include B's franchise (via
  `FRANCHISE_LINEAGE`/`franchises_for`).
- **Thresholds:** at least `REVENGE_MIN_STARTS` starts with B, **or** traded or dropped by
  B this season or last (`transactions.json` via `load_trades`).
- **Wording:** "Josh Allen faces the franchise that traded him (Week 4, 2026). 34 starts,
  612 pts for J/J." It also shows the player's points against B in past meetings.
- **League-wide list:** every revenge game that week, for the Preview tab.

**1d. Records within reach.** Rules, all deterministic and tested:
- **Player season and career totals** (`player-season`, `player-career`):
  - *"On pace"* when current + this week's projection ≥ a top-5 entry.
  - *"Within reach"* when the gap ≤ the player's season-high game.
  - Show the rank it would move into ("would pass Derrick Henry for #2 all-time").
- **Team season** (most points, best PPG, 100-point games): shown when current + projected
  passes an entry, or (for season totals) when the projected full-season pace beats
  #1.
- **Streaks:** a team or series streak that ties or breaks a record with one more win or
  loss.
- **Single-game records** (team-game, player-game): only when the projection is at least
  85% of the #5 entry. Stated as "would need X to enter the record book", never as a
  prediction.
- **Milestones:** career points crossing 500/1,000/1,500/…; career starts 50/100/150;
  franchise wins 50/100; 30-point games 10/25. A milestone counts when current +
  projection crosses it, or when it's within one typical game.
- **Where they show:** in the matchup drawer for that matchup's teams and players, and
  league-wide on the Preview tab.

**1e. Tale of the tape** (client side, from `all_weeks_loaded`):
- **Rows:** season PPG, last-3 average, high and low, top-half finishes, all-play
  record, points against, projected total, and per-position PPG for starters.
- **Display:** mirrored bars (`svgBarPair`); the better side is bold.

**1f. Matchups → Preview sub-tab.** Add a third tab (**This Week | Preview | Schedule**,
route `#matchups/preview`) for the upcoming `lineup_week`. Sections, each collapsible and
omitted when empty:
1. **Rooting Guide** for the viewer's team (or a team picker)
2. **Biggest stakes games** (largest combined swing)
3. **Record Watch**
4. **Milestones**
5. **Revenge Games**
6. **Storylines**, grouped by matchup, with links to the card
   (`matchupLink`/`focusMatchupCard`)

---

## Phase 3: Scorigami (Hall of Fame → Records) (done)

**Exporter** (`scripts/hof_records.py`): add `build_scorigami(team_games)`:
- **Which games:** one per matchup (winner and loser only); regular season and playoff
  single-week games. For two-week playoff legs, only the combined total counts as the
  final (there's an existing test for this).
- **Ties:** ties are a separate list.
- **Output:** written to `hall_of_fame_records.json → scorigami`:
  `{games, unique, cells:[{w, l, count, first:{season, week, winner, loser}, latest:{…}}], recent:[…last 10 new scorigamis…], ties:[…]}`.

**UI:** a new section in `hofRecordsHtml` (`app.js:6768`), "Scorigami":
- **Grid:** an `svgHeatGrid` with the winning score on x and the losing score on y. Only
  the lower triangle is drawn. Colour shows count, and an accent outlines the newest
  scorigami.
- **Hover:** tooltips show the score, count, and first and most recent games.
- **Layout:** it sits in a horizontal-scroll region on phones.
- **Below the grid:** stat tiles ("412 games · 318 unique finals · 77% scorigami rate"), a
  "Recent scorigamis" list, and "Most common final".

**Weekly fact:** a new detector, `_scorigami_facts`, in `qpfl/weekly_facts.py`
("First 143–97 final in QPFL history, the league's 319th unique score"). It feeds the
newsletter and the weekly-facts cards for free.

---

## Phase 4: What-if standings (Standings → Table) (done)

**As built:** every view is ranked by rank points under the real rules (a win
is 1, a top-half week 0.5 with ties at the cutoff splitting it), not by W-L.
All-play, Points only, Perfect lineups (everyone's best lineup, top halves
recomputed, plus what a perfect lineup alone would have gained) and Schedule
swap (wins change, a team's own top-half points don't). Pythagorean wins was
dropped: top-half points already reward raw scoring, so it repeated Points
only.

Add a collapsed `<details class="standings-whatif">` "Alternate standings" below the
standings table. It's computed client side from loaded weeks and has a segmented
control:
- **All-play record:** W-L-T against every team every week (extends `computeExpectedWins`
  to keep counts).
- **Points-only:** ranked by points for.
- **Perfect lineups:** each team's best possible lineup score every week (the
  `TeamGame` optimal score is already exported per week, or `computeOptimalLineup`),
  re-run against opponents' *actual* scores. Also shows "points left on bench".
- **Pythagorean wins:** `PF^2.37 / (PF^2.37 + PA^2.37) × games`.
- **Schedule swap:** a 10×10 grid of each team's record if it had another team's schedule.
  The diagonal is the actual record; cells are colour-coded against it.

Each view shows the rank change against actual standings (↑2 / ↓1).

---

## Phase 5: Lineup decisions (Stats → new "Lineups" sub-tab) (done)

**As built:** `scripts/hof_lineups.py`. Ghost starters leave out team units
(HC, D/ST, OL), which go negative most weeks. A designated starter only
counts as an OUT blunder when he then scored 0 (designations can land
mid-game). Perfect lineups use the Hall of Fame's own `best_lineup` test.

**Exporter:** a new `lineup_superlatives` block in `hall_of_fame_records.json`, computed
from `PlayerGame`, by season and all-time:
- **Benching hall of shame:** the largest (best bench score − started score) at a slot the
  bench player was eligible for. Flags when it flipped the result.
- **Bench MVPs:** the most bench points by player, season and all-time.
- **Ghost starters:** starters who scored ≤ 0 points with a game played.
- **Bye/OUT blunders:** a starter with `on_bye`, or (2026+) listed OUT in
  `injury_statuses` snapshots. Older seasons are bye-only.
- **Decided by special teams:** games where the K, DST or punter margin was larger than the
  final margin.
- **Perfect lineups:** count per team (`perfect_lineups` already exists; surface it here).

**UI:** a new tab, `#stats/lineups`, with a season selector plus "All-time". Each
superlative is a small ranked card (reuse `hofRecordCard` styling).

**Weekly facts:** `_bench_facts` / `_lineup_facts` already exist; add a "ghost starter"
template only if it's missing.

---

## Phase 6: Trade and draft grades (done)

**As built** (all client-side in `web/app.js`, section "GRADES"; tests in
`tests/test_grades_ui.py`):
- **Grades** curve against league history in 13 equal percentile bands (A+ to F,
  midrank percentiles), so the two sides of a trade mirror each other and a dead-even
  trade is a C+ for both. GPA uses the 4.0 scale (A+ and A both 4.0).
- **Trades:** every trade `tradeVerdict` can score (not unparsed or untracked; 49 of 87
  today) is graded on each side's points margin. Grades show as chips on each trade's
  verdict bar. A collapsed "Trade Report Cards" section under Most Lopsided Trades
  follows the season selector: Biggest fleecing, Best for both (the best worse-off side
  among trades both sides passed with C- or better), Most even (smallest margin share
  among trades at or above the median combined total), and a GPA table (teams with fewer
  than 3 graded trades listed last). Teams → Activity shows the team's trade GPA.
- **Drafts:** value over slot compares each Offseason or Midseason pick with the average
  pick within one slot in the other drafts of the same kind, measured over the same
  window (first two seasons, 34 weeks, or as many weeks as the draft has played), so new
  drafts aren't judged against years of production. Class grades curve each team's
  value over slot per week. Shown on Draft History: steal, bust, class grade chips and a
  "vs slot" figure on each pick. Grades appear after six weeks.
- **Costliest drops** (client-side, not the exporter): drops from the draft sheets'
  `dropped` column and the transaction log's releases, scored by the player's starts for
  other teams in the year after the drop (from `franchise_stints`). A collapsed section
  under Trade Report Cards, following the season selector. Free-agent weeks don't count,
  so the off-roster note wasn't needed.

**Original plan:**


**Trades.** Build on `tradeVerdict` (`app.js:8510`) and `normalizedTradeSides` (`:8456`):
- **Letter grades:** A+ to F for each side, from the verdict's points-produced margin
  after the trade (starts only, and rest-of-tenure). Thresholds are set by percentile of
  all trades.
- **Trade GPA:** for each manager, plus "Best trade", "Biggest fleecing" and "Most even
  trade".
- **Where:** a collapsed "Trade report cards" section in the Transactions view next to
  `renderTradeBlowouts` (`:8793`), plus a GPA line on Teams → Activity.

**Drafts.** Extend `renderDraftPerformanceSummary` (`:9667`):
- **Expected value per pick:** the league-wide average career points of picks at that
  overall slot (all drafts, smoothed with a 3-slot moving window).
- **Grades:** each pick gets "value over slot"; each team's draft class gets a grade.
  Shown as a badge in Draft History, plus "Steal of the draft" and "Biggest bust".

**Costliest drops** (exporter, from roster timelines plus drops in the transaction log):
points a player scored on *other fantasy rosters* after a team dropped them (starts only,
next 365 days). This goes in the same Transactions section. Off-roster free-agent scores
only count for 2026 (`data/off_roster_scores`); the UI notes that.

---

## Phase 7: Elo, fingerprints and nemeses (Hall of Fame) (done)

**As built:**
- **Elo** is one model, `qpfl/elo.py` (`EloHistory`), with the planned constants. Every
  decided game counts once, two-week games on their combined result, and consolation
  games at 1×. Ratings belong to current franchise seats (`TeamGame.franchises`), so a
  shared 2021 team plays at its seats' average and moves both.
  - The Hall of Fame export puts `elo`, `elo_rank` and `elo_series` on each entry of
    `hall_of_fame_records.franchises` (`scripts/hof_franchises.py`).
  - The pregame export puts `elo` (both ratings and team1's win chance, coming in) on
    each matchup, which the Tale of the Tape shows as two rows. Weeks 1-10 of 2026 were
    regenerated; only that block changed.
  - The Elo chart leads HOF → Franchises: grey lines, up to 3 highlighted franchises in
    the palette's all-pairs-safe slots (the viewer's team and the leader by default), a
    hover crosshair, direct end labels and a ratings table. The team page shows an Elo
    tile with its rank.
- **Fingerprints** (`hof_owners._fingerprints`): six traits as midrank percentiles among
  owners with 15+ regular-season games. Playoffs uses the owner stats table's playoff
  record, so it matches the profile header. Shown as bars on the owner profile, with a
  "Compare to" picker that overlays a second owner.
- **Nemeses** reuse the head-to-head lists already on each page instead of
  `rivalry_records`: the owner profile's `head_to_head`, and the team page's owner
  series summed across the franchise's owners (`franchiseOpponentRecords`). One helper,
  `nemesisAndVictim`, needs 4+ games and breaks ties by series length, then name.
  **Player nemeses** (`hof_franchises._player_nemeses`) count opposing starters' points
  against each franchise, consolation games out (as Top Players counts them), and show
  as a card on the team page.

**Original plan:**


**Elo** (`hof_franchises.py`):
- **Model:** start at 1500, K=24, with a margin-of-victory multiplier
  `ln(|margin|+1) × 2.2/((Δelo×0.001)+2.2)`. Regress one third toward 1500 between
  seasons. Playoff games weigh 1.25×.
- **Output:** `franchises[].elo_series` (by week) and a current Elo for each franchise.
- **UI:** an `svgLineChart` on HOF → Franchises with franchise toggles (the viewer's own
  franchise is highlighted). A one-line "Elo: 1,612 (3rd)" on the team page.
- **Win probability:** Elo is also an optional "Elo win prob" line in the Tale of the
  Tape. It's *not* fed into the playoff sim.

**Manager fingerprints** (`hof_owners.py`):
- **Six traits:** Scoring (PPG), Consistency (−SD), Lineup IQ (actual / optimal), Luck
  (wins − all-play expected wins), Clutch (record in games decided by under 10), and
  Playoffs (playoff win %). Each is shown as a percentile among all owners.
- **UI:** six horizontal percentile bars on each owner profile in HOF → Owners, with a
  "Compare to…" picker that overlays a second owner. Bars, not a radar chart, so it stays
  readable on phones.

**Nemeses and favourite victims:** from `rivalry_records`, with a minimum of 4 games:
worst and best win % against each franchise. Shown on the franchise page and the owner
profile. Also **player nemeses**: opposing players with the most points scored against
this franchise, from `PlayerGame` `opp_franchises`.

---

## Phase 8: Weekly Awards and Season Wrapped

**Weekly Awards card.**
- **Where:** on Matchups → This Week once every game for the week is final.
- **What:** a compact, screenshot-friendly card with fixed awards: Top Score, Bottom
  Score, Biggest Blowout, Nail-biter, Bench MVP, Benching Blunder, Best Player, Best
  Pickup (an add from the last 2 weeks who started).
- **How:** computed in `export_weekly_facts.py` as an `awards` block in the existing facts
  file, so there's no new file or workflow step. Also added to the newsletter export
  (`api/newsletter_export.py`).

**Season Wrapped.**
- **When:** generated once the season ends, by the existing Hall of Fame refresh.
- **Output:** `web/data/seasons/<yr>/wrapped.json`.
- **Per team:** record and finish, best and worst week, MVP player, most-started player,
  biggest win and worst loss, Lineup IQ %, luck, best trade (grade), top waiver add,
  revenge games, records set, and nemesis of the year.
- **UI:** a card at the top of Teams → Hall of Fame for that season, as styled stacked
  panels sized to screenshot. A Home banner "2026 Wrapped is here" appears for two weeks
  after the championship.

---

## Testing (every phase)

- **Python** (pytest, following `tests/test_weekly_facts.py` and
  `tests/test_export_hall_of_fame.py`):
  - `tests/test_pregame.py`: storylines, revenge thresholds, every records-within-reach
    rule and milestone crossing, with synthetic `TeamGame`/`PlayerGame` rows.
  - `tests/test_hof_records.py`: Scorigami (two-week legs, ties, first-occurrence
    ordering) and lineup superlatives.
  - Elo and fingerprint math, in the existing franchise and owner test files.
- **JS** (node slice harness, like `tests/test_hof_and_draft_challenge_ui.py:39`):
  - `runPlayoffSim`: no `fixed` gives the same output as today's `simulatePlayoffOdds`
    (seeded).
  - Fixing every remaining game gives 0/100% odds that match `computePlayoffStatus`.
  - Rooting-guide sign and ordering.
  - Pick-hash round trip.
  - What-if standings maths.
  - SVG helpers produce valid markup with an `aria-label`.
- **UI text checks** (`tests/test_*_ui.py` style): new subnav tabs, routes,
  `DEFAULT_SUBVIEW` entries, and that empty sections render nothing.
- **CI gates:** `node --check web/app.js`, and keep the 80% coverage gate on `qpfl/`.

## Verification

1. `pytest` and `node --check web/app.js`.
2. Run the exporters locally:
   ```
   python scripts/export_pregame.py --season 2026 --week 11
   python scripts/export_hall_of_fame.py
   ```
   Then check `web/data/seasons/2026/pregame/week_11.json` and the `scorigami` block by
   hand against known history, e.g. a revenge game you know about, or the current
   scoring record.
3. Serve the site with `python -m http.server -d web` and check it in Chrome:
   - **Matchup cards:** the Preview drawer opens with content, and is absent on final
     matchups.
   - **`#matchups/preview`:** the tab works.
   - **`#standings/machine`:** with no picks, odds match the Standings card within
     noise. Fixing a team to win out shows "clinched" where the maths says so. A shared
     `?picks=` link restores the picks.
   - **Scorigami grid:** renders in both themes and at phone width without horizontal
     page scroll.
4. Time `runPlayoffSim` in the browser console on a throttled CPU. Use the Worker
   fallback if needed.
