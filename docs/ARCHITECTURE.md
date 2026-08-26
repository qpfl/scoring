# QPFL Architecture

QPFL is a static web application backed by versioned JSON in Git. Vercel is the canonical
deployment because it serves both the site and six Python API functions. GitHub Pages is a
supported static mirror; `web/api-config.js` sends its API calls to the canonical Vercel origin.

## Data flow

```text
manager browser
  -> Vercel API
  -> GitHub Git Data/Contents API
  -> authoritative JSON under data/
  -> GitHub Actions score/export
  -> committed static JSON under web/
  -> Vercel and GitHub Pages
```

Modern-season JSON in `data/` is authoritative. The browser never writes exported `web/*.json`
directly. Scoring and exporters derive those public files from authoritative inputs. Git commits
provide history and trigger the scoring workflow.

Excel is directional:

- `Rosters.xlsx` seeds a new season through `scripts/init_rosters_from_excel.py`.
- `scripts/sync_rosters_to_excel.py` creates a current names-only snapshot.
- `scripts/sync_lineups_to_excel.py` can produce an explicit workbook update when an operator asks
  for one; it is dry-run by default.
- Excel is not a second live source of truth and changes do not automatically flow back to JSON.
- Frozen 2020–2025 score workbooks remain the historical source for explicit re-exports.

## Authoritative inputs

| Path | Role |
|---|---|
| `data/league_config.json` | Current season, week/deadline settings, roster and starter limits |
| `data/rosters.json` | Active and taxi roster ownership |
| `data/lineups/{season}/week_{week}.json` | Submitted weekly starters |
| `data/pending_trades.json` | Proposed and completed trade state |
| `data/draft_picks.json` | Draft-pick ownership and history |
| `data/transaction_log.json` | Required mutation audit records |
| `data/team_names.json` | Season/week-aware franchise-name history |
| `schedule.txt` | Regular-season fantasy matchups |

Some serverless constants are intentionally copied from league configuration because Vercel does
not package runtime data as application configuration. `scripts/create_new_season.py` updates
those copies, and `tests/test_config_consistency.py` prevents drift.

## Public output

`scripts/export_current.py` writes both the split data tree and compatibility payloads:

```text
web/
  data/index.json
  data/shared/*.json
  data/seasons/{season}/meta.json
  data/seasons/{season}/standings.json
  data/seasons/{season}/rosters.json
  data/seasons/{season}/draft_picks.json
  data/seasons/{season}/live.json
  data/seasons/{season}/weeks/week_{week}.json
  data.json
  data_{historical-season}.json
```

The frontend bootstraps from the split index, loads shared/season resources on demand, and keeps
the compatibility payload while remaining consumers are migrated. Current/live resources receive
short cache lifetimes; frozen history and rarely changed shared resources receive long lifetimes.
The exact routes and cache policy live in `vercel.json`.

Maintained export commands are:

```bash
uv run --frozen python scripts/export_current.py --season 2026
uv run --frozen python scripts/export_for_web.py --reexport-historical 2025
uv run --frozen python scripts/export_historical.py 2025
```

Historical re-export commands require an explicit past year and reject the current/future season.
There is no bulk `scripts.export.*` package and no current-season route through the legacy exporter.

## Write consistency

Single-document changes use optimistic SHA comparison. Multi-document roster, pick, trade, and
audit mutations use `api/github_store.py` to create one Git tree and commit, then advance the branch
head without force. A conflict re-reads the whole bundle and reapplies a pure mutation. Operation
IDs make ambiguous update responses idempotent. Required audit serialization is part of the same
bundle, so domain state cannot commit without its audit event.

GitHub Actions commits use `scripts/git_push_with_retry.sh`. On a non-fast-forward rejection the
helper fetches/rebases and retries a bounded number of times; exhaustion fails the workflow instead
of reporting a false success.

## Browser and API trust boundaries

- `web/api-config.js` owns the six-endpoint allowlist and origin selection.
- `web/index.html` and `vercel.json` apply the Content Security Policy and security headers.
- API POSTs require JSON, bounded content length, and an allowed/missing origin as documented in
  `docs/API.md`.
- Credentials are checked server-side and retained by the browser only in `sessionStorage`.
- The server determines authoritative season/week, kickoff locks, roster ownership, and trade state;
  client lock metadata and client dates are not trusted.
- Unexpected external failures return a request ID and generic text.

## Deployment

`.github/workflows/score.yml` scores and commits generated data. Static deployment is independent:
`.github/workflows/deploy-pages.yml` publishes committed `web/**` changes to GitHub Pages. Vercel
deploys the same static directory plus the Python functions configured in `vercel.json`.

CI installs from `uv.lock` with frozen commands on Python 3.10 and 3.11, then enforces whole-repo
Ruff, Mypy for `qpfl`, core and API branch-coverage floors, Node syntax, schema validation, integrity,
and the complete test suite. Dependency auditing runs weekly and on demand.
