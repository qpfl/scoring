# Plan: QPFLTok and league charts (inspired by brazenzone.com)

## Context

A friend's league site, brazenzone.com ("The HFL"), has about 180 chart views and **Chuzz Tok**, a TikTok-style feed with one full-screen chart per swipe. QPFL has almost no charts: only the Scorigami grid (`renderScorigami`, `web/app.js:~8540`) draws SVG, and the "small SVG chart helper" from the earlier analytics plan never shipped. The user wants:

1. **QPFLTok**, a new page with a feed like Chuzz Tok.
2. The best brazenzone charts, added to our architecture.

**Decisions made:**
- **Where charts go:** spread into the existing views. There is no new chart-hub page. QPFLTok is the only place to browse every chart.
- **Wave 1 covers four chart families:** Standings & outlook, Luck & what-if, Managers & rivalries, and Players, moves & awards.
- **QPFLTok entry points:** the More menu plus a teaser card on Home. The four primary mobile tabs stay as they are.

**What's left out:** we have no data for brazenzone's Scouting (height, speed, colleges), Places (hometowns, maps), Weather, or NFL salary charts, so those are dropped. "Corruption Index" and "Brazen Zone" are jokes specific to that league.

**Relation to `docs/PLAN_league_analytics_features.md`:** Phases 0 and 1–5 of that plan have shipped. Phases 6 (trade and draft grades), 7 (Elo, fingerprints and nemeses) and 8 (Awards and Wrapped) are absorbed into this plan's family phases below. Each one becomes a chart plus a QPFLTok card. When this plan starts, mark those phases "superseded by PLAN_qpfltok_and_charts.md" in that file.

**Step 1 of implementation:** save this plan as `docs/PLAN_qpfltok_and_charts.md`.

### What Chuzz Tok does (observed) and what we'll copy

- **Desktop layout:** a phone-sized frame in the center, with "Made for your phone… scroll or use ↑↓ to swipe" and a "Back to the dashboard" link beside it.
- **Feed:** one card per screen with vertical snap scrolling. "Swipe up for more" shows on the first card.
- **Card anatomy:**
  - **Top bar:** Browse, the logo, and a ⚙ settings button.
  - **Pills:** a colored family pill (THIS WEEK, HOLIDAY, AWARDS NIGHT), a season or week pill, the spotlighted manager, and a red **NEW** pill.
  - **Text:** a big title and a one-line subtitle.
  - **Body:** a compact version of the chart.
  - **Bottom-left:** a caption bubble with an emoji and a hook ("📸 Screenshot this for the group chat", "🏆 7 awards handed out", "😭 Read it and weep").
  - **Right rail:** **Share** and **Full chart** buttons.
- **Timely cards come first:** record watch, milestones, last week's awards (with an animated spotlight reveal of 1 of 7), and holiday slates.
- **Settings:** "Spotlight a team" highlights that manager in every chart and builds the feed around them. "Reset my feed" makes every clip NEW again. There's also a theme picker; we skip it because our site has no themes.
- **Browse:** shows the full dashboard section for that chart, with section tabs.

---

## Architecture

```
qpfl/charts.py (new, pure)         scripts/export_charts.py (new)
  elo, fingerprints, nemeses,  ◄──   loads history via export_weekly_facts.load_history
  streaks, distributions, grades     writes web/data/charts.json  (score.yml, after weekly facts)
                                             │
web/charts.js (new, loaded before app.js)    ▼
  SVG primitives  ──►  CHARTS registry  ◄── client data already in app.js
                         │                  (weeks, standings, simulatePlayoffOdds,
             ┌───────────┴───────────┐       WHATIF tables, lineups, facts, pregame)
     in-view sections              QPFLTok view (#tok)
   (Standings, HOF, Stats…)       feed of tok() cards
```

### A. `web/charts.js`: primitives and registry (new file)

`app.js` is already 22k lines. A separate file loads with `<script defer>` before `app.js` (`web/index.html:1070`). Node tests can then `require` it whole instead of using `app_slice`.

**SVG primitives.** These are pure functions that return markup strings.
- **Styling:** colors come from CSS custom properties in `styles.css`.
- **Highlighting:** each primitive takes `highlight`, a franchise code. The highlighted series is colored; the rest are muted.
- **Accessibility:** each chart has `role="img"`, a `<title>`, and a `<details>` table fallback.

| Primitive | Used by |
|---|---|
| `lineChart({series, x, yDomain, highlight})` | Elo, title odds over time, season arcs |
| `bumpChart({series, weeks})` (rank lines, inverted y) | Power rankings, standings replay |
| `barList({rows, valueFmt, highlight})` (ranked horizontal bars) | Most rankings, the default form |
| `divergingBars({rows})` (centered at 0) | Luck, projection luck, strength of schedule, trade margins |
| `heatGrid({cells, xDomain, yDomain})` | Head-to-head grid, schedule swap, finish history, Scorigami |
| `ringStat({pct, label})` | Win-% rings, milestones, perfect-lineup % |
| `stripPlot({rows})` (dot per game plus median) | Score distributions, boom or bust |

- **Scorigami:** its inline SVG moves onto `heatGrid` as the first use. This proves the helper with no visual change.
- **Tooltips:** one delegated handler shows a small tooltip from `data-tip` attributes, on hover or tap.

**Registry.** `const CHARTS = [...]`, one entry per chart:
```js
{ id: 'elo', family: 'managers', title: 'Elo ratings', blurb: '…',
  home: { view: 'history', subview: 'franchises', anchor: 'chart-elo' },
  needs: ['charts'],            // data loaders, resolved by prepareViewData
  compute(ctx) → model | null,  // null = nothing interesting → render nothing anywhere
  render(model, { highlight }) → html,          // full in-view version
  tok(model, { spotlight }) → { pill, sub, body, caption, timely, interest, involves: [codes] } }
```
- **In-view placement:** each view's renderer calls `renderChartSection(id, container)`. That function computes, renders, and wraps the result in a collapsible `<section class="chart-section" id="chart-…">` with Share and expand buttons.
- **Highlighting:** charts highlight `myTeamAbbrev()` (`app.js:14373`). `refreshPersonalization()` (`:1336`) already re-renders when the user logs in.

### B. `qpfl/charts.py` + `scripts/export_charts.py`: cross-season precompute

Anything that needs every season's weeks is computed in Python, so the browser never fetches 7 seasons of week files.
- **Input:** reuse `load_history` / `flatten_season` / `roster_timeline` (`scripts/export_weekly_facts.py:343/89/184`) and `hall_of_fame.json` (`rivalry_records`, `owner_stats`, `finishes_by_year`, `player_career_stats`).
- **Output:** one `web/data/charts.json` (target under 300 KB), with a key per chart plus `generated_at` and `completed_through`.
- **Workflow:** run it in `.github/workflows/score.yml` right after `export_weekly_facts.py` (`score.yml:308`) and add it to that commit. Also add a cache route in `vercel.json`, like the other data files.
- **Client:** loaded through `ensureSharedResource`-style lazy loading (`app.js:797`).

Season-local charts are computed in the browser from data and functions that already exist:
- Season weeks
- `simulatePlayoffOdds(completedThrough)` (`:5593`), which already accepts a past week
- `computeExpectedWins` (`:4378`)
- The `WHATIF_VIEWS` tables (`:4644`)
- The lineups block (`:4544`)

---

## QPFLTok view (`#tok`)

**Status:** shipped in Phase 1. The feed lives in its own file, `web/tok.js`, loaded between `charts.js` and `app.js`. The top half is pure (feed order, NEW state, holiday and milestone parsing, the week cards) so `tests/test_tok_ui.py` runs it in node. The bottom half is the browser controller.

**Shell.**
- **Markup:** a new `#tok-view` `.view-container` in `index.html`, plus a nav link in the More menu (`index.html:88`).
- **Routing:** add `tok` to `PAGE_DESCRIPTIONS`, `pageTitleFor` and `prepareViewData`.
- **Full-screen:** when the view is active, `body.tok-mode` hides the site header and nav, so the feed fills `100dvh`.
- **Desktop (≥ 900px):** a centered 420px phone frame with a short "Made for your phone" note and a "Back to QPFL" link, like brazenzone.

**Feed mechanics.**
- **Scrolling:** a scroller with `scroll-snap-type: y mandatory`. Each card is `height: 100%`, `scroll-snap-align: start` and `scroll-snap-stop: always`.
- **Keyboard:** ↑/↓, j/k and PageUp/PageDown scroll one card.
- **Virtualized rendering:** an IntersectionObserver fills in card bodies only within ±2 of the current card. Other cards are sized placeholders.
- **Deep links:** `#tok/<chartId>` opens on that card and updates as you swipe (`history.replaceState`). This is what Share sends.

**Card anatomy.** A `tokCardHtml(entry, model, tokOut)` function builds:
- **Pills:** family color, season or week, spotlight team, and NEW.
- **Text:** a title and a subtitle.
- **Body:** the compact chart. Long lists scroll inside the card.
- **Caption bubble:** shown at the bottom left.
- **Right rail:**
  - **Share:** uses `navigator.share` when available, otherwise copies the link and shows the existing toast.
  - **Full chart:** navigates to `home.view/subview`, opens the section and scrolls to `#anchor`.

**Feed ordering** (`buildTokFeed(ctx)`, pure and tested):
1. Candidates are registry entries whose `compute` returns non-null.
2. Score = `interest` + timely boost (`tok().timely`, e.g., this week's recap, awards, record watch or rooting guide) + spotlight boost (when `involves` has the spotlight team) + a NEW boost.
3. Cards are sorted by tier. Order within a tier is a shuffle seeded by date, so the feed is fresh each day but stable within a day.
4. Seen cards sink to the end.
- **Seen state:** stored in localStorage at `qpfl.tok.seen = { chartId: dataVersion }`, inside try/catch. `dataVersion` is the hash of `charts.json.generated_at` plus the week, so a chart is NEW again after its data changes.

**Sheets.**
- **⚙ Settings:**
  - **Spotlight a team:** defaults to `myTeamAbbrev()` and is stored in localStorage.
  - **Reset my feed:** clears the seen state.
- **Browse:** every chart grouped by family, with a filter box ("Jump to a chart…"). Tapping a chart jumps to its card. This is the catalog that replaces a dedicated chart page.

**Timely cards built from data we already have** (these ship with the shell, before the chart families):
- **Last week recap:** from the facts recaps.
- **This week in QPFL history:** existing renderer.
- **Matchup storylines and Record watch:** from `web/data/seasons/<yr>/pregame/`.
- **Milestones:** career points, wins and high-score round numbers within reach, shown with `ringStat`.
- **Rooting guide for the spotlight team:** uses `computeRootingGuide` (`:5887`).
- **Holiday slate:** spotlight teams with players in Thanksgiving or Christmas games. It comes from roster `kickoff` dates and appears only that week.

**Home teaser.** A small card, "QPFLTok · N new clips →", that counts unseen cards in the feed. It's hidden when the count is 0. It goes in `renderHome` (`:1472`).

---

## Chart catalog, wave 1 (where each one lives)

Every chart also produces a QPFLTok card. "Client" means the browser computes it; "export" means `charts.json`.

**Standings & outlook**

| Chart | Primitive | Home | Source |
|---|---|---|---|
| Power rankings (weekly rank from record, points for and all-play) | bump | Standings → Table, "Charts" section | client |
| Standings replay (seed by week) | bump | Standings → Table | client |
| Playoff and title odds over time | line | Standings → Playoff Machine | client, `simulatePlayoffOdds(w)` per week, cached, with fewer trials |
| Clinch tracker (clinched, alive, eliminated; magic numbers) | barList | Standings → Playoff Machine | client, `computePlayoffStatus` |
| Projected wins (actual plus expected remaining) | barList, stacked | Standings → Table | client |
| Strength of schedule, remaining | divergingBars | Standings → Table | client |
| Finish history (franchise × season) | heatGrid | History → HOF → Franchises | `finishes_by_year` |

**Luck & what-if** (charts attached to the existing What-if tabs, `WHATIF_VIEWS`)

| Chart | Primitive | Home | Source |
|---|---|---|---|
| Luck: wins minus all-play expected wins | divergingBars | What-if → All-play | client |
| Pythagorean wins vs actual | divergingBars | What-if → All-play | client |
| Schedule swap grid | heatGrid | What-if → Schedule swap | client (existing table data) |
| Perfect-lineup rate | ringStat grid | What-if → Perfect lineups | client |
| Projection luck (actual minus pregame projection, cumulative) | line + divergingBars | Stats → Team Stats | client (`pregame_total`) |
| Wrong opponent (losses that would have beaten most other teams that week) | barList | What-if → All-play | client |

**Managers & rivalries** (replaces old Phase 7; methods as specified there)

| Chart | Primitive | Home | Source |
|---|---|---|---|
| Elo ratings (K=24, margin-of-victory multiplier, ⅓ regression, playoff ×1.25) | line | History → HOF → Franchises; one line on the team page | export |
| Manager fingerprints (six percentile traits; "Compare to…") | barList pair | History → HOF → Owners | export |
| Head-to-head grid (win %) | heatGrid | History → HOF → Franchises | `rivalry_records.h2h_matrix` |
| Nemeses and favorite victims; player nemeses | barList | Teams → Hall of Fame → Head-to-Head | export |
| Streaks: longest and current, hot and cold stretches | barList | History → HOF → Records | export |
| Score distributions | stripPlot | History → HOF → Franchises | export |
| Win-% rings | ringStat | History → HOF → Owners | `owner_stats` |
| Season arcs (cumulative wins by week, every season) | line | Teams → Hall of Fame | export |

**Players, moves & awards** (replaces old Phases 6 and 8; methods as specified there)

| Chart | Primitive | Home | Source |
|---|---|---|---|
| Boom or bust (weekly spread of starters) | stripPlot | Stats → Player Leaders | export |
| One-man armies (one player's share of team points) | barList | Stats → Team Stats | client |
| Benching hall of shame | barList | Stats → Lineups (on top of the existing card) | lineups block |
| Trade grades and manager trade GPA | divergingBars | Transactions, next to `renderTradeBlowouts` (`:11655`) | client, `tradeVerdict` (`:11353`) |
| Draft value over slot and class grades | divergingBars | Drafts → History, `renderDraftPerformanceSummary` (`:12529`) | export |
| Costliest drops | barList | Transactions | export |
| Weekly awards (MVP, high score, blowout, upset, bench MVP, best pickup…) | award reveal card | Matchups → This Week, once the week is final | `awards` block added to the facts file by `export_weekly_facts.py` |
| Season Wrapped | stacked panels | Teams → Hall of Fame (postseason) | `wrapped.json` (old Phase 8) |

---

## Delivery: one PR per phase

0. **Foundations:**
   - `web/charts.js` with the primitives and an empty registry, plus `renderChartSection`.
   - Scorigami moved onto `heatGrid`.
   - `qpfl/charts.py` and `scripts/export_charts.py` writing `charts.json`, with only `generated_at` at first.
   - The `score.yml` step and the `vercel.json` route.
1. **QPFLTok shell:** view, feed, sheets, deep links, Home teaser, More-menu link, and the timely cards from existing data. It ships usable right away.
2. **Standings & outlook.** It's week 11 of 15, so these matter most right now.
3. **Luck & what-if.**
4. **Managers & rivalries.**
5. **Players, moves & awards.** Wrapped can land after the championship.

Each family PR adds `compute`, `render` and `tok` for its charts, the in-view sections, and the export keys with tests.

## Testing

- **Python** (`tests/test_charts_export.py`): Elo math on a hand-made 3-team history, fingerprint percentiles, nemeses with at least 4 games, streaks, and the `charts.json` shape and size budget.
- **Node over stdin, following `tests/test_matchup_preview_ui.py`:**
  - **`tests/test_charts_js.py`:** loads `web/charts.js` whole. Checks that each primitive returns valid SVG with `<title>` and a fallback table, that empty input returns `''`, and that `highlight` marks only one series.
  - **`tests/test_tok_ui.py`:**
    - `buildTokFeed` ordering: timely first, spotlight boost, seen cards sink, deterministic for a given date.
    - The NEW logic.
    - Static checks of `index.html` and `styles.css`: the `#tok-view` exists, the More link exists, and scroll-snap is applied.
- **Per-family UI tests:** `compute` returns null on an empty or early season, and each chart's `home` anchor exists.
- **Before pushing** (from memory): `ruff check`, `ruff format --check`, `pytest`, and `node --check web/app.js web/charts.js`.

## Verification

1. Run `uv run python scripts/export_charts.py --current-season 2026 --completed-through 10` and confirm `web/data/charts.json` is valid and under 300 KB.
2. Serve the site with `cd web && python -m http.server` and open it in Chrome:
   - **QPFLTok at phone width (390×844):** swiping snaps one card at a time, ↑/↓ works, NEW pills clear after viewing, and Reset brings them back.
   - **Spotlight:** changing the spotlight re-orders the feed and highlights that team.
   - **Share and Full chart:** Share copies `#tok/<id>`, and opening that link lands on the same card. Full chart scrolls to the right section in the right view.
   - **Desktop:** QPFLTok shows the phone frame.
   - **In-view sections:** each new section renders in its home view, highlights the logged-in team, and renders nothing for a historical season with no data.
3. Check that the Home teaser count matches the unseen cards.
