# Weekly "By the Numbers" facts

## Context
The commissioner wants NFL-broadcast-style notes each week ("4th-most points in franchise history, most in 2 years", "one of only 6 matchups decided by 30+") for the newsletter. The data already exists: `web/data/seasons/2020–2026/weeks/week_N.json` holds about 1,000 team-games and about 10,000 scored starter rows. The Hall of Fame generator (`scripts/export_hall_of_fame.py`) already loads every season and computes all-time top-5 lists. But it only produces static lists. Nothing places *this week's* results in historical context.

Goal: a deterministic generator that runs in the score workflow after each completed week. It writes one facts JSON per week. The newsletter `.docx` gets a ranked "By the Numbers" section, and the Hall of Fame page gets a "This Week" card that reads the same file.

Decisions made: newsletter + site; ranked top ~10 in the newsletter (full list kept in the JSON); all games count (regular season, playoffs, consolation, each tagged), but streaks and W/L records use regular season only.

## Step 0
Save this plan as `docs/PLAN_weekly_facts.md` (repo convention).

## Architecture

```
score.yml ─► export_hall_of_fame.py (existing)
         └─► scripts/export_weekly_facts.py --season S --week W      (new)
               │ loads history with hof.load_season_data()
               │ normalizes to TeamGame / PlayerGame rows
               ▼
             qpfl/weekly_facts.py  (pure: detectors + ranking + curation)
               ▼
             web/data/seasons/S/facts/week_W.json
               ├─► api/newsletter_export.py  → "By the Numbers" bullets
               └─► web/app.js renderHallOfFame → "This Week" card
```

### 1. History loader: `scripts/export_weekly_facts.py` (new)
Reuse these helpers from `scripts/export_hall_of_fame.py`:
- `discover_seasons`
- `load_season_data(season, current_season, completed_through=W)`: already excludes unfinished live weeks
- `get_team_score` (keeps legitimate zeros)
- `clean_team_name`
- `clean_player_name` and `player_identity_key`: the same canonical player key the HOF career profiles use
- `get_week_name`
- `FRANCHISE_LINEAGE`: invert it so that MPA→RPA, RCP/JDK→J/J and JRW→AST

The loader flattens the history into plain dataclass rows and passes them to the engine:
- **TeamGame**: season, week, week_label, bracket (`regular` | `playoffs` | `consolation`, read from the matchup's `bracket` key and the regular-season week count of 14 for ≤2021 or 15 after), franchise (resolved through lineage), abbrev, team_name, score, opp_franchise, opp_score, margin, won/lost/tied, two_week flag
- **PlayerGame**: season, week, bracket, player_key, name, position, nfl_team, franchise, score, starter

Skip zero-score placeholder games, as `calculate_team_records` does. Skip two-week playoff aggregates for single-game records.

CLI flags: `--season`, `--week` (defaults to HOF `completed_through`), `--backfill` (regenerate every week of a season, for QA). Don't write the file if only `generated_at` changed. This mirrors `_without_refresh_metadata`.

### 2. Engine: `qpfl/weekly_facts.py` (new, pure, no I/O)
**Point-in-time rule:** each week is compared only against games *before* it, plus same-week ties. Rerunning a past week reproduces what was true then.

Shared primitives:
- `rank_of(value, population, higher=True)` → (rank, total, tied_count)
- `count_at_least(threshold, population, distinct_by=None)` → "Nth time" and "Nth player ever"
- `most_since(value, chronological_population)` → the last game that was ≥ the value, rendered as "most since Week 6, 2024" or "most in 2+ seasons"
- `ordinal()` and the phrasing helpers ("tied for 3rd", "only the 5th time")

Each detector returns `Fact{id, category: league|team|player, subjects:[franchise abbrevs], template, notability, tags}`. The template uses `{team:GSA}` tokens (player names are written inline), so each consumer can render team names its own way.

**Detector catalog (v1)**

League (all-time):
- Team score in the top 10 highest or lowest all-time
- Margin of victory in the top 10, or "one of only N games decided by 30+/40+/50+ points"
- Closest game in the top 10 (includes ties)
- Combined matchup score in the top 10
- League-wide weekly total in the top/bottom 5
- Highest losing score or lowest winning score in the top 5
- Week's high score is the lowest ever to lead a week (lowest "best score in a week")

Team (franchise history, lineage-aware):
- Franchise-best or -worst score in the top 5, plus "most since…" when the gap is a season or more
- Regular-season win/loss streak: current length, and whether it's the franchise or league longest. Also flag a long streak that just ended.
- Season start: "first 4-0 start since…", "one of N teams to start 0-4"
- Head-to-head: series record, "won N straight vs X", "first win vs X since YYYY"
- Points-for pace: PF through week N ranked against every franchise-season through week N (a fair comparison)
- Top-half streaks (the league's top-half scoring)

Player (starters only):
- All-time single-game rank (overall and by position): "best TE game in league history"
- Threshold club: "4th player ever (6th time) to score 55+", with thresholds per position
- Franchise single-game record for a player
- Career milestones: crossing career starter-point marks (250/500/1,000), and "Nth 40-point game, most in league history"
- Hall of shame: D/ST -6 and record-low kicker
- Streaks: "3rd straight week with 30+"

Era note: 2020–21 had 8 teams, a 14-week regular season and different scoring. A `FIRST_SEASON` constant (default 2020) can narrow "league history" later if needed.

**Curation** (`curate(facts, limit=10, per_team=3)`):
- notability = detector weight × rarity, where rarity is roughly 1/rank, scaled by how small the population is
- Scope multiplier: all-time league > franchise > season
- Dedupe: if a value already earned a league-rank fact, drop the same value's franchise-rank fact
- Cap facts per franchise, and keep at least one fact per category when one is available
- The output keeps `headline` (the curated list) and `all` (every fact that cleared its threshold)

### 3. Output: `web/data/seasons/{S}/facts/week_{W}.json`
```json
{"season":2026,"week":4,"generated_at":"…","history_through":"2026 W3",
 "headline":[{"id":"team_score_alltime","category":"league","subjects":["GSA"],
   "template":"{team:GSA}'s 130 is the 4th-highest score in league history and the most since Week 9, 2024.",
   "notability":0.91,"tags":["regular"]}],
 "all":[...]}
```

### 4. Workflow: `.github/workflows/score.yml`
Add this step right after "Refresh Hall of Fame from completed weeks" (around line 289), with the same `if:` guard:
`uv run --frozen python scripts/export_weekly_facts.py --season $CURRENT_SEASON --week ${{ steps.completed_week.outputs.week }}`.
The existing `git add web/data/` already picks up the output, so no other change is needed. Optionally add the same step to `season-transition.yml`.

### 5. Newsletter: `api/newsletter_export.py`
- In `load_newsletter_sources`, also read `web/data/seasons/{season}/facts/week_{results_week}.json` through the existing `read()` callable (one extra GitHub read in `api/transaction.py:1860`). Treat a missing file as `None`.
- Add `_render_fact(template, names)`, which swaps `{team:X}` for `_short_names` (Griff, Kaminska…).
- In `build_newsletter_document`, add a `By the Numbers` Heading2 between Results and Schedule. It holds one `bullet=True` paragraph per headline fact. If no file exists, write "No notes generated this week." The `.docx` stays editable, so the commissioner can trim it.

### 6. Site: `web/app.js` `renderHallOfFame` (~line 6077)
- Read `completed_through[current]` from `hall_of_fame.json`, then fetch `data/seasons/{S}/facts/week_{N}.json`.
- Render a "This Week in QPFL History" card at the top: the headline facts as a list, with team tokens shown as team names from meta. Add a "Show all" toggle for `all`.
- If the fetch fails, hide the card quietly. Use the existing card and list styles in `web/styles.css`.

### 7. Phase 2 (done)
New loader inputs: bench rows (`PlayerGame.starter=False`), each team-game's best possible lineup (`TeamGame.optimal`: the top scorers at each started position), `pregame_total` projections, the championship flag, owner codes (`get_owner_codes`), league drafts (`drafts.json`; early boards' "T. Lawrence" names resolve to a unique player), trades traced from roster moves (`transactions.json` names the players; the weekly rosters say who went where), and NFL rookie seasons from nflverse (`load_players`; rookie notes are skipped when it can't be reached).

New detectors:
- Lineups: bench points left (league top 5 or franchise record), losses the best lineup would have won (margin 15+ or the 3rd+ of a season), first perfect lineup in a long time, benched-player records.
- Luck: all-play record vs. the real one (records only, and only when they disagree), points against through N games, opponents above/below their season averages, straight weeks with the week's top (2+) or lowest (3+) score.
- Stakes: playoff rate for teams with the same record after N games (5+ earlier teams, 80%+ either way), clinches and eliminations (rank points, counting ties against the team so a call is never early) with "earliest ever", defending champion's start vs. earlier title defenses, breaking or evening an all-time series.
- Careers: owner milestones (every 25 wins, every 5,000 points), starts for one franchise (the record, or every 25 from 75), best career average against one team (min. 6 games), revenge games (20+ against a franchise the player made 8+ starts for), RB/WR pair records.
- Drafts and trades: a 3rd-round-or-later pick taking over his class lead (Week 4 on), rookie single-game top 3 and the week the rookie season record falls, a trade's lead changing hands (starter points for the new team since the deal, last two seasons).
- Projections (2026 on): biggest upset by projection and biggest beat/miss, once two weeks exist.

Output fixes: a team's streak is reported as one number (the longer regular-season run replaces the all-games one rather than sitting beside it); teams sharing an N-0 or 0-N start get one combined note; the site's "more notes" list reads a new `more` key capped at 4 notes per team across both lists; a snapped streak is noted only the week it ends.

Still open: rivalry-week and Connor Bowl specific notes.

## Tests
- **`tests/test_weekly_facts.py`** (new), built on synthetic seasons in the style of `tests/test_export_hall_of_fame.py` `_team`/`_week`. Cover:
  - rank and tie phrasing
  - "most since" across seasons
  - the point-in-time rule (a later week can't affect an earlier one)
  - franchise lineage (an MPA score counts toward RPA history)
  - regular-season-only streaks
  - the threshold club's distinct-player count
  - curation caps and dedupe
  - unchanged output isn't rewritten
- **`tests/test_newsletter_export.py`**: the section and its bullets appear, short names are substituted, and a missing facts file falls back cleanly.
- **`tests/test_hall_of_fame_ui.py`**: the card renders and hides when the file is missing.

## Verification
1. `uv run pytest tests/test_weekly_facts.py tests/test_newsletter_export.py tests/test_hall_of_fame_ui.py` and `uv run ruff check`.
2. `uv run python scripts/export_weekly_facts.py --season 2025 --backfill`, then read the 2025 headlines and check them against known history. For example, the 167-point game should be league #1, and checking the HOF top-5 lists confirms the rank math.
3. `uv run python scripts/export_weekly_facts.py --season 2026 --week 4` and read `web/data/seasons/2026/facts/week_4.json`.
4. Build the docx locally: `build_newsletter_document(load_newsletter_sources(local_read, 2026))`, write it to the scratchpad, unzip `word/document.xml`, and confirm the section. Then open it in Word or Pages.
5. Serve `web/` locally (`/run`) and check the Hall of Fame card.
