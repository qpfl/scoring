# Architecture Evaluation: Multi-Page App? Move Off JSON?

**Date:** September 2026. Companion to `docs/DATA_LAYER_DECISION.md`.

## Context

Two questions were raised about QPFL's architecture:

1. Should the SPA become a multi-page app? Evaluate on cost, hosting impact, and whether
   it actually improves the app.
2. Is git-backed JSON the right data store, versus other free or cheap options?

Stated motivations: `web/app.js` (15,334 lines, 679 KB) is unmaintainable; concern about
Vercel Hobby-tier limits and future cost; friction in the data-store write path. Both
Vercel and the GitHub Pages mirror are live and must stay working.

`docs/DATA_LAYER_DECISION.md` (July 2026) already answered question 2 in the negative for
Supabase specifically. This evaluation re-tests that conclusion against the wider field of
cheap stores, and answers question 1, which has not been formally evaluated.

---

## Verdicts

| Question | Verdict |
|---|---|
| Multi-page app | **No.** The pain it targets is real; MPA is the wrong instrument. Use native ES modules with dynamic `import()` — same benefit, no build step, no URL breakage, no dual-host divergence. |
| Move off git-backed JSON | **No.** Every cheap alternative loses more than it gains at this scale. The friction you feel is in the *pipeline*, not the store, and is fixable directly. |
| Do nothing? | **No.** There are three cheap, high-payoff wins that neither migration would have delivered anyway. |

---

## Question 1 — Multi-page app

### Does it improve the app?

**Load time: weaker argument than it looks.** First load is 679 KB JS + 245 KB CSS +
73 KB HTML ≈ 976 KB — but that is *uncompressed*. Vercel and GitHub Pages both serve
compressed; 15k lines of repetitive template-literal JS compresses roughly 6–8×, so the
real wire cost is on the order of 100–150 KB of JS. That is not a load-time emergency, and
it is fully cached after first visit for a league of ten returning managers. The genuine
cost is parse/compile/execute of 15k lines on every cold load, which is real but modest.

The actual data-loading hot spots are bigger than the code:

- `web/data/shared/hall_of_fame.json` is **2.15 MB** and is fetched by six of eight views,
  usually for one slice of it.
- `ensureAllSeasonWeeks()` runs for `matchups`, `standings`, `stats`, and `teams` —
  opening Standings for 2024 pulls **~1.5 MB** of week files.

An MPA fixes neither. Both are data-shape problems.

**Maintainability: the real motivation — and MPA is an indirect route to it.** Splitting
into nine HTML files does not by itself split `app.js`; you still have to decompose 451
top-level functions and ~9 shared mutable globals (`data`, `sharedData`, `currentSeason`,
`currentWeek`, `LIVE_SEASON`, `dataIndex`, `availableSeasons`, `resourceCache`,
`activeRouteParams`). That decomposition *is* the work. MPA adds page-splitting on top of
it as an extra, separately-risky change.

**What MPA actively costs here:**

- **URL breakage.** Every route is a hash route (`#matchups/week/3`, `#teams/roster/CGK`,
  `#player/<key>`) with a `LEGACY_HASH_REDIRECTS` table already accreted for retired
  routes. Real paths mean breaking every bookmark and shared link in the league, and
  maintaining a second redirect layer forever.
- **Shell duplication with no build step.** There is deliberately no `package.json`, no
  bundler, no npm — CI's only JS check is `node --check web/app.js`. Nine copies of the
  nav, header, and season selector either get hand-maintained or you adopt a build
  toolchain, which is a much larger change than the one being evaluated.
- **Dual-host divergence.** Vercel's `cleanUrls` and GitHub Pages' static file serving
  resolve extensionless paths differently. Today both hosts serve one identical
  `index.html` and cannot diverge. With nine pages they can, and the Pages mirror would
  need its own verification.
- **Lost in-session caching.** `resourceCache` (`web/app.js:15`) makes cross-view
  navigation instant. A full page reload drops it each time; you'd fall back to HTTP cache,
  which for live data is only `max-age=60`.

**What MPA would buy that modules don't:** SEO and crawlable URLs — irrelevant for a
password-gated ten-person league; and hard isolation between pages, which matters mainly
for the `#manage` write surface. Not enough.

### Cost and hosting impact

Effectively none, and that is the point — it's not where the savings are.

- **Hosting model doesn't change.** Both hosts are static. An MPA is still static files;
  no new infrastructure, no new plan tier.
- **`vercel.json` grows.** Route count is capped at 2048, so no ceiling risk, but the
  header/rewrite block becomes nine-way and the per-path `Cache-Control` tiers need
  re-deriving.
- **Vercel bandwidth is a non-issue** at this traffic level, before or after.

The Hobby limits that *do* matter — and neither MPA nor an SPA changes them:

| Hobby limit | Value | Relevance |
|---|---|---|
| Deployments per day | **100** (also 100/hr, 60 per 5 min) | **The one real ceiling.** Every write commit to `data/` triggers a Vercel deploy. Draft day or deadline day with ten managers is the scenario to watch. |
| Static file uploads | 100 MB | `web/` is ~21 MB and grows ~1.5 MB/season from legacy archives. Headroom, but it compounds. |
| Functions per deployment | Framework-dependent | Already worked around by consolidating 7 endpoints into `api/index.py`. |
| Function duration | 60s max | `github_store.py`'s CAS loop retries up to 8× with backoff; worth knowing the ceiling. |

### Recommendation: native ES modules instead

`<script type="module">` plus dynamic `import()` gets the maintainability win with none of
the MPA costs. It requires **no build step** (native in every browser), keeps every URL,
keeps `resourceCache`, keeps one shell, keeps both hosts identical, and is compatible with
the existing CSP (`script-src 'self'` permits modules).

The codebase is unusually well-positioned for it: `prepareViewData(view, subview)`
(`web/app.js:896`) already declares each view's exact data dependencies, and the
`VIEW_RENDERERS` map already dispatches per view. That is a per-view code-splitting
manifest already written — a dynamic `import()` keyed off the same map lazy-loads view
*code* exactly the way `prepareViewData` already lazy-loads view *data*.

Be honest about scope: decomposing 15,334 lines and ~451 globals is a multi-week
incremental effort, not a weekend. Sequence it so it is safe to stop at any point:

1. **Leaf utilities first** — `escapeHtml`, `posBadge`, `posClassKey`, formatters. Pure
   functions, no shared state, mechanical.
2. **Data layer** — `fetchJsonResource`, `loadSeasonBase`, `ensureSharedResource`,
   `ensureSeasonWeek`, `ensureAllSeasonWeeks`, `ensureCurrentSeasonFiles`,
   `ensureSeasonTeamIdentities`, `ensureManualHonors`, plus the `SHARED_RESOURCES` map,
   into one module that owns the mutable state and exposes accessors. This is the step
   that converts the globals into explicit imports, and the hardest one.
3. **Router** — `parseHashRoute`, `seasonAwareRoute`, `applyRouteState`,
   `LEGACY_HASH_REDIRECTS`.
4. **One view module per top-level view**, largest first (`manage`, `teams`,
   `transactions`), each behind a dynamic `import()`.

Extend CI's `node --check web/app.js` to check every module, or the check silently stops
covering most of the code.

---

## Question 2 — JSON / git-as-database vs. cheap alternatives

### Re-testing the existing decision

`docs/DATA_LAYER_DECISION.md` rejected Supabase on volume, concurrency, and durability
grounds. Those arguments hold and are not repeated here. Two facts strengthen them:

- **Free managed Postgres suspends idle projects.** Supabase pauses free projects after a
  week of inactivity; Neon's free tier auto-suspends compute. This app is dormant
  February–August. The store would be cold or paused *exactly* when the season restarts —
  a pathology git does not have.
- **The audit log is the product.** `data/transaction_log.json` plus git history *is* a
  dynasty league's permanent record. Every alternative below requires building and paying
  for an audit trail that git provides for free, forever, diffable and greppable.

### The wider field

| Option | Free tier | Why it loses here |
|---|---|---|
| **Git + JSON (current)** | Free, unbounded | Audit log free, diffable, portable, zero vendor risk, 600 KB working set |
| SQLite committed to repo | Free | Binary blob: destroys diffs, review, and `protect_historical.yml`. No safe concurrent write from stateless functions. Strictly worse than JSON. |
| Turso / libSQL | Generous; no idle suspend | Genuinely viable technically. Still: vendor bet over a 20-year horizon, no free audit log, and migration touches all 7 write endpoints plus the scoring pipeline at once. |
| Cloudflare D1 | 5 GB, 5M reads/day | Tied to Workers; you're on Vercel Python. Would mean porting `api/` to JS. |
| Neon / Vercel Postgres | ~0.5 GB | Idle suspend → cold starts in a serverless write path. |
| Supabase | 500 MB | Pauses after 7 days idle. Disqualifying for a seasonal app. |
| Cloudflare KV / Vercel Edge Config | Cheap | **Eventually consistent.** Breaks the compare-and-swap invariants `github_store.py` depends on. |
| Vercel Blob | 1 GB | A file store with no transactions and no history. Strictly worse than git. |

None of these clears the bar. `api/github_store.py` is a genuinely well-built CAS layer —
atomic multi-file tree commits, jittered exponential backoff on ref conflict, idempotency
via `operation_id`, and ambiguous-outcome verification. Replacing it with a database means
re-earning correctness you already have and race-tested.

### Where the friction actually is

The friction attributed to the data store is mostly in the **pipeline around it**:

1. **A write triggers the whole world.** `score.yml` fires on push to `data/lineups/**`,
   `data/rosters.json`, `data/pending_trades.json`, `data/transaction_log.json`,
   `data/avatars.json`, `data/team_names.json`, `data/league_config.json`. One manager
   setting a lineup kicks off a full rescore → export → commit → Vercel deploy → Pages
   deploy. The `qpfl-web-data` concurrency group serializes and coalesces these, so it's
   already partly mitigated — but `data/avatars.json` and `data/team_names.json` are
   cosmetic and cannot change any score. They should not be in that trigger list.
2. **20 MB of JSON is regenerated and committed on every scoring run**, several times daily
   in season — which is also what burns deployments against the Hobby ceiling.
3. **Write latency** is ~6–10 GitHub API calls per write (get ref → read N files → create
   blobs → tree → commit → update ref). Fine at ten managers; the PAT's 5,000/hr limit is
   not close.

Point 1 is a one-line fix. Point 2 is the next section. Neither is a reason to migrate.

---

## What to actually do, ranked

**1. Delete the legacy monoliths** — highest payoff per unit of effort.
`web/data.json` (1.5 MB) and `web/data_2020..2025.json` (5.7 MB total) are still generated
by `scripts/export_current.py` and committed by `score.yml`, but **`app.js` never fetches
them**. The only live dependency is `api/lineup.py` reading kickoff times out of
`web/data.json` — point it at `web/data/seasons/{year}/live.json`, which already carries
`kickoffs`/`game_times`. Then stop generating them. Cuts ~30% off every deploy's static
payload and off per-run commit churn, and stops the ~1.5 MB/season growth.
Touches: `api/lineup.py`, `scripts/export_current.py`, `scripts/export_hall_of_fame.py`,
`scripts/update_trade_blocks.py`, `score.yml`'s `git add`, `protect_historical.yml`,
`vercel.json` route rules for `data_\d{4}.json` and `data.json`. Also check
`web/data/historical/*.json` (2.7 MB) for the same dead-weight status.

**2. Narrow `score.yml`'s push triggers.** Remove `data/avatars.json` and
`data/team_names.json` — cosmetic files that cannot affect a score. Directly reduces
deploys/day and pipeline noise.

**3. Shard `hall_of_fame.json`.** 2.15 MB fetched by six of eight views. It is already
sectioned (`player_career_stats`, `team_records`, `player_records`, `owner_stats`,
`rivalry_records`, `team_hall_of_fame`, `mvps`, `finishes_by_year`, `fun_stats`). Split it
into `data/shared/hof/*.json` and extend the `SHARED_RESOURCES` map (`web/app.js:650`) so
each view pulls only its section. Same pattern as the existing per-season split, mechanical
in `scripts/export_hall_of_fame.py`.

**4. Modularize `app.js` via ES modules**, in the four-stage sequence above. The large,
slow, valuable one.

**5. Not now: `ensureAllSeasonWeeks()` for historical seasons.** Pulling ~1.5 MB of week
files to render Standings is wasteful, but the fix is a precomputed per-season aggregate in
the export — worth doing only after (3), which shares the same approach.

**Explicitly rejected:** multi-page split; any database migration.

---

## Verification

- **Items 1–3 (data changes):** run `python scripts/export_current.py` and
  `python scripts/export_hall_of_fame.py` locally, then `python scripts/check_integrity.py`
  and the schema validation in `qpfl/data_validation.py`. Serve `web/` locally
  (`python -m http.server`) and walk all eight views plus the player modal with DevTools
  Network open — confirm no 404s, no fetch of the deleted monoliths, and that
  `hall_of_fame` requests are now per-section. Confirm `api/lineup.py`'s lineup-lock
  behavior against `live.json` kickoff times with a pre- and post-kickoff case in
  `tests/test_api.py`.
- **Item 2:** push a change touching only `data/avatars.json` and confirm `score.yml` does
  not fire.
- **Item 4 (modules):** `node --check` each module in CI; then the same eight-view manual
  walk, plus back/forward navigation, deep links (`#teams/roster/CGK`, `#matchups/week/3`,
  `#player/<key>`), a `?year=2024` historical load, and the `#manage` login flow with its
  `sessionStorage` credential path. Verify on both hosts — the Vercel deployment and the
  GitHub Pages mirror — since both are live.
- Full suite throughout: `pytest` with the existing coverage floors, `ruff`, `mypy`.
