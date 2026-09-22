# Cut Vercel deployment storage, then move the site to GitHub Pages

## Context

Vercel warned that this project is at **75% of its deployment storage quota** (Hobby plan).
Deployment storage is the sum of source files plus build output across *every retained
deployment*, so usage grows as `payload size x deployment count`. Both factors are inflated:

- **Payload.** Each deployment uploads **22.1 MB** of source across 190 files. About **9.1 MB of
  that is never requested by a browser** - legacy compatibility artifacts and Excel-derived
  verification data that only local scripts and tests read.
- **Deployment count.** ~862 commits since 2025-12-01. During game windows the scoring workflows
  push to `main` several times per hour (five pushes in ~3.5 hours on 2026-09-22), each firing a
  full production deployment. September 2026 alone: 319 commits, roughly 7 GB of deployments.

A premise worth correcting before anything else: **`qpfl.org` is served by Vercel, not GitHub
Pages.** `dig qpfl.org` returns `216.198.79.1` / `64.29.17.1`, `www.qpfl.org` is a CNAME to
`575865efe563d698.vercel-dns-017.com`, and `curl -I https://qpfl.org` returns `server: Vercel`.
The GitHub Pages build (`.github/workflows/deploy-pages.yml`) is a mirror, and it is a *project*
page at **https://qpfl.github.io/scoring/**, not an org root page.

This plan has two phases that can ship independently:

- **Phase 1** keeps Vercel canonical and cuts usage now: 22.1 MB -> ~13.0 MB per deployment,
  no-op commits stop producing build output, and retention reclaims what has already accumulated.
- **Phase 2** makes GitHub Pages the canonical host for `qpfl.org` and leaves Vercel serving only
  the Python API, taking each Vercel deployment to well under 1 MB. It is the larger win and the
  larger change; Phase 1 is not wasted work if Phase 2 follows, because the payload cuts shrink
  the Pages artifact too.

---

# Phase 1 - Reduce Vercel usage with Vercel still canonical

## 1.1 Read the real numbers first

Nothing below depends on this, but it sizes the headroom.

1. Vercel dashboard -> `qpfl-scoring` -> **Usage**: record current deployment storage and the
   Hobby quota.
2. Project Settings -> **Deployment Retention**. Confirm what Hobby allows, then set the shortest
   acceptable retention for **Preview** and **Canceled/Errored** deployments, and a bounded
   retention for **Production**. This is the only lever that reclaims storage *already* consumed;
   everything else only slows future growth. Expect it to be the single largest win.
3. Settings -> Git: confirm whether preview deployments are wanted for this repo at all.

If retention is not configurable on Hobby, fall back to deleting old deployments by hand plus the
payload cuts below.

## 1.2 Stop shipping bytes the browser never asks for

All of the following are confirmed unreferenced at runtime. `web/app.js` loads **only** the split
layout (`data/index.json`, `data/seasons/**`, `data/shared/**`), and `tests/test_split_data_ui.py:37`
already asserts `app.js` never fetches `data.json`. The API handlers read their data from the
**GitHub API** (`api/lineup.py:31-32`, `api/transaction.py:43`, `api/team-name.py:127`, all via
`_read_github_json`), not from the deployed bundle, so nothing in `api/` depends on these files
being uploaded.

Add to `.vercelignore`:

| Pattern | Size | Why it is safe |
| --- | --- | --- |
| `web/data.json` | 1.6 MB | Exporter state and test fixture (`scripts/export_current.py:790-793,1151`). Never fetched by the browser; `api/` migrated off it. |
| `web/data_20*.json` | 4.3 MB | Frozen per-season compatibility archives (2020-2025). The only consumer inside `web/` is `web/preview.html`, which `.vercelignore` already excludes. |
| `web/data/historical/` | 2.7 MB | Excel-derived verification sources (`scripts/export_historical.py`). Not fetched by the frontend at all; used locally by `scripts/fix_historical_scores.py`. |
| `web/data/shared/Rule Changes By Year.txt` | 20 KB | Raw source text; the site reads `rule_changes_history.json`. |

Subtotal: **-8.7 MB per deployment.**

Then delete the two now-dead route blocks from `vercel.json` so requests 404 cleanly rather than
advertising files that are no longer uploaded:

- `{ "src": "/(data_\\d{4}\\.json)", ... }`
- `{ "src": "/(data\\.json)", ... }`

No test asserts these routes exist. Keep the catch-all route last: `tests/test_web_security_ui.py:95`
indexes `routes[-1]`.

**Guard it.** Beside the existing `test_vercel_deploy_includes_split_data_tree`
(`tests/test_split_data_ui.py:276`), add `test_vercel_deploy_excludes_unfetched_payloads`: parse
`.vercelignore`, assert each of the four patterns above is present, and assert the split-tree
bootstrap files are still not matched. That file already pins deploy composition, and the guard
stops `scripts/create_new_season.py` silently reintroducing the archives at season rollover.

## 1.3 Delete the orphaned Hall-of-Fame images

`web/images/hof/image1.png` ... `image5.png`, `image6.jpg` (**356 KB**) have no reference in
`app.js`, `index.html`, `styles.css`, any JSON, or any script - the `hof/` hits at
`web/app.js:1103-1107` are route aliases, not image paths. Re-confirm with
`grep -rn "images/hof" web/ scripts/ qpfl/ api/` returning nothing, then `git rm` them. This shrinks
the Pages artifact as well.

Subtotal: **-0.36 MB.** Running total: 22.1 MB -> **~13.0 MB (-41%)**.

Leave the versioned avatar files (`web/images/avatars/CWR/2026-w0.png` and friends) alone - they are
intentional history. Re-encoding them is listed under Deferred below.

## 1.4 Stop rebuilding on commits that change nothing deployable

Scope decision: skip no-op deploys only; live scoring cadence is unchanged.

Vercel -> Project Settings -> Git -> **Ignored Build Step**, custom command:

```bash
git diff --quiet HEAD^ HEAD -- web api vercel.json requirements.txt .vercelignore
```

Exit 0 (nothing in those paths changed) means Vercel skips the build and reuses the previous build
output, so no new artifacts are stored. Exit 1 builds normally.

This catches commits that only touch `data/scoring_state.json`, `data/injury_statuses.json`, or
`data/stat_snapshots/**` - all already `.vercelignore`d - plus every docs/tests/scripts-only commit.
In-game score pushes do touch `web/`, so live scores keep deploying at today's speed.

The setting lives in the dashboard, not the repo, so record it in `docs/ARCHITECTURE.md`.

## 1.5 Record the decisions

`docs/ARCHITECTURE_EVALUATION.md:192-200` already flags the legacy-payload duplication; note that it
is now resolved for deployment purposes (the files remain in-repo for the exporter and tests, they
are just not uploaded). Add a short "Vercel deployment storage" section to `docs/ARCHITECTURE.md`
covering retention, the ignored build step, and why `web/data.json`, `web/data_20*.json`, and
`web/data/historical/` are repo-only.

## Phase 1 verification

1. `uv run --frozen pytest tests/test_split_data_ui.py tests/test_docs.py tests/test_api_router.py tests/test_web_security_ui.py`,
   then the full suite - `test_docs.py` and `test_api_router.py` both parse `vercel.json`.
2. Reproduce the 22.1 MB baseline and confirm the drop to ~13.0 MB:
   ```bash
   git ls-files \
     | grep -vE '^(scripts/|qpfl/|docs/|data/|\.github/|previous_seasons/|tests/|thoughts/)' \
     | grep -vE '\.(xlsx|docx)$' \
     | grep -vE '^(pyproject\.toml|uv\.lock|autoscorer\.py|web/preview\.html)$' \
     | grep -vE '^(web/data\.json|web/data_20.*\.json|web/data/historical/|web/images/hof/)' \
     | xargs wc -c | tail -1
   ```
3. Deploy to a **preview**, not `main`. On the preview URL confirm every tab renders (standings,
   rosters, weeks, history/matchups, drafts, transactions, constitution) - the history view pulls
   the 2.2 MB `data/shared/hall_of_fame.json`, which is deliberately kept - and that devtools shows
   zero requests to `data.json`, `data_20*.json`, or `data/historical/*`.
4. API smoke test against the preview: `GET /api/maintenance` returns 200 and `/api/team-name`
   still resolves season metadata, proving the GitHub-API reads are unaffected.
5. After merge, push a docs-only commit and confirm the Vercel dashboard marks it *skipped*.
6. Re-read Vercel Usage ~24h after setting retention and confirm the number dropped.

---

# Phase 2 - Make GitHub Pages canonical for qpfl.org, Vercel API-only

**Outcome:** `qpfl.org` is served by GitHub Pages; the Vercel project keeps only the Python
functions, so a deployment carries `api/` plus config (well under 1 MB) instead of 13 MB. Combined
with Phase 1 retention, deployment storage stops being a recurring problem.

Most of the groundwork is already done, which is what makes this tractable:

- **CORS is already migration-ready.** `api/request_util.py:12-17` allowlists `https://qpfl.org`,
  `https://www.qpfl.org`, `https://qpfl-scoring.vercel.app`, and `https://qpfl.github.io`, and
  `request_util.py:72-94` emits `Access-Control-Allow-Origin` / `Vary: Origin` plus a preflight
  handler. No API change is required.
- **The CSP already permits the cross-origin API call.** `web/index.html:6` carries a
  `<meta http-equiv="Content-Security-Policy">` with `connect-src 'self' https://qpfl-scoring.vercel.app`.
  Meta CSP is honored on Pages.
- **The Pages deploy already publishes committed content** from `./web`
  (`.github/workflows/deploy-pages.yml:47`) after each data-writing workflow succeeds.

### 2.1 Point the frontend at the Vercel API from every host

`web/api-config.js:11-24` returns `productionOrigin` only for `localhost`, `127.0.0.1`, and
`qpfl.github.io`, and otherwise returns `location.origin`. Once Pages serves `qpfl.org`, that
fallback would send API calls to `https://www.qpfl.org/api/...`, which will not exist.

Add `qpfl.org` and `www.qpfl.org` to the host list. Extend the assertion at
`tests/test_web_security_ui.py:18` to cover all four hostnames so the branch cannot be dropped.

### 2.2 Claim the custom domain on Pages

1. Add `web/CNAME` containing `www.qpfl.org` (the Pages artifact root is `./web`). A custom domain
   on a project page serves at the domain root, so the current `/scoring/` subpath disappears -
   but `https://qpfl.github.io/scoring/` will then redirect to the custom domain, ending the
   independent mirror. Decide deliberately whether that is acceptable.
2. Repo Settings -> Pages -> set the custom domain to `www.qpfl.org` and enable **Enforce HTTPS**
   once the certificate is issued.
3. Update `web/index.html:14,15,20` (`og:url`, `og:image`, `twitter:image`) to `https://www.qpfl.org/...`.

### 2.3 Cut Vercel down to the API

In `vercel.json`, drop the `{ "src": "web/**", "use": "@vercel/static" }` build and every static
route, keeping the `@vercel/python` build and the seven `/api/*` routes. Then remove `qpfl.org` and
`www.qpfl.org` from the Vercel project's Domains so only `qpfl-scoring.vercel.app` remains - that
hostname stays in the CORS allowlist and is what the browser will call.

`tests/test_web_security_ui.py:93-101` reads `vercel['routes'][-1]['headers']` and will need
rewriting, since the header-bearing catch-all route is going away.

### 2.4 Accept, or mitigate, what Pages cannot do

Two real regressions, both verified against the live mirror:

- **Header-only security controls are lost.** `curl -I https://qpfl.github.io/scoring/` returns only
  `strict-transport-security` and `cache-control`. Pages sends no `X-Content-Type-Options`, no
  `Permissions-Policy`, and no `Referrer-Policy`, and those cannot be set from a meta tag. Neither
  can CSP `frame-ancestors 'none'` - meta CSP ignores it - so clickjacking protection is lost
  unless a `frame-busting` script is added, which conflicts with `script-src 'self'` only in the
  sense that it must live in `app.js` rather than inline. `<meta name="referrer" content="strict-origin-when-cross-origin">`
  does work and should be added. The rest of `vercel.json:60-65` has no Pages equivalent; this is
  the main security cost of the move and should be an explicit, recorded decision.
- **Cache control becomes uniform and slower.** Pages serves a flat `cache-control: max-age=600`
  with no per-path control. Today `vercel.json` gives `data/seasons/**/live.json` and
  `weeks/week_N.json` `max-age=60, stale-while-revalidate=300`. In-game score freshness would
  degrade from about a minute to about ten. Mitigation: append a cache-busting query string to the
  live resources the way `web/app.js:715-739` already does for
  `data/shared/hall_of_fame.json?v=20260827-matchup-history` - for live data the token should be
  derived from the payload's `updated_at` rather than hardcoded. This needs to be designed before
  cutover, not after; it is the most likely thing to be noticed by managers on game day.

### 2.5 Make the Pages deploy production-grade

`.github/workflows/deploy-pages.yml` currently sets `concurrency: { group: pages, cancel-in-progress: true }`.
As a mirror, a cancelled run is harmless. As the canonical host, a cancelled run means live scores
stall until the next push. Switch to `cancel-in-progress: false` so queued deploys drain.

### 2.6 Repoint DNS

At the registrar, replace the Vercel records:

- Apex `qpfl.org` A records -> `185.199.108.153`, `185.199.109.153`, `185.199.110.153`,
  `185.199.111.153` (and AAAA -> `2606:50c0:8000::153` through `2606:50c0:8003::153`).
- `www.qpfl.org` CNAME -> `qpfl.github.io` (replacing the current `...vercel-dns-017.com`).

Lower the TTL to 300s at least 24 hours beforehand so rollback is fast. Do the cutover outside a
game window.

### 2.7 Update outbound links

Notification and reminder links still point at Vercel and should point at the site:
`.github/workflows/score.yml:344`, `.github/workflows/lineup-reminders.yml:59`,
`.github/workflows/notify.yml:223,269`, `.github/workflows/expire-trades.yml:151`, and the defaults
in `scripts/send_lineup_reminders.py:152` and `scripts/send_score_update.py:348`.
`.github/workflows/notify.yml:142` already uses `https://qpfl.org/`, and
`tests/test_email_delivery.py:78-79` pins that convention. Also update
`docs/API.md:4,27` and `docs/2026_DRAFT_READINESS_CHECKLIST.md:227`.

## Phase 2 verification

1. Before touching DNS, set the Pages custom domain and confirm `https://www.qpfl.org` serves from
   Pages while `qpfl.org` still resolves to Vercel - the two can be validated independently.
2. From the Pages-served origin, confirm in devtools that API calls go to
   `https://qpfl-scoring.vercel.app/api/...`, that the preflight `OPTIONS` returns 204, and that
   `Access-Control-Allow-Origin` echoes the Pages origin. Exercise one authenticated write
   (a lineup submit) end to end, not just a read.
3. Confirm no CSP violations in the console - `connect-src` must cover the Vercel origin.
4. Confirm live-score freshness against the new cache behavior during an actual game window before
   declaring the migration done.
5. Keep the Vercel project and its `qpfl-scoring.vercel.app` domain alive throughout; rollback is
   repointing DNS back, which is why the TTL is lowered first.

---

## Deferred

- Re-encoding avatar PNGs to WebP (~1 MB recoverable; touches `api/team-avatar.py`, which writes
  them).
- Throttling in-game scoring pushes to reduce deployment count further.
