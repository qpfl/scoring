# Repository Reliability, Security, and Cleanup Implementation Plan

## Overview

Bring the QPFL scoring repository from its current high-risk pre-Week-1 state to a release-ready state without changing the league's Git-backed JSON architecture. The work fixes the broken deployed write path, closes data-integrity holes in lineups and transactions, restores trustworthy automation, repairs the team-name pipeline, hardens authentication and request boundaries, removes unsafe and dead tooling, and finishes with a recorded live end-to-end rehearsal.

The work is intentionally split into independently reviewable and reversible pull requests. Correctness and containment land before architectural cleanup. No phase should be merged with unrelated generated-data changes.

## Current State Analysis

- The static site is served from both Vercel and GitHub Pages, but the browser derives API URLs from `window.location.origin`. Pages therefore calls nonexistent `github.io/api/*` paths (`web/app.js:6884`, `web/app.js:7244`, `web/app.js:8207`).
- Pages deployment is coupled to scoring and season-transition jobs rather than ordinary committed `web/**` changes (`.github/workflows/score.yml:550`).
- The team-name writer stores effective-week history (`api/team-name.py:23`), its schema expects plain strings (`qpfl/schemas.py:374`), and the 2026 exporter ignores the history (`scripts/export_current.py:496`).
- User-controlled names and API text reach raw `innerHTML` sinks, including the pending-trade renderer at `web/app.js:10730`.
- Lineup reads collapse all GitHub failures into “missing,” disabling both server locks and active-roster validation (`api/lineup.py:36`, `api/lineup.py:53`, `api/lineup.py:141`).
- A trade writes rosters before draft picks and reopens the negotiation if the later write fails (`api/transaction.py:796`, `api/transaction.py:847`, `api/transaction.py:940`).
- Transaction audit writes are separate and best-effort (`api/transaction.py:1738`).
- Four workflow push loops can return success after every push fails (`score.yml:543`, `season-transition.yml:67`, `update-player-teams.yml:67`, `expire-trades.yml:255`).
- `scripts/export_for_web.py --all` bypasses the current-season safety guard and invokes the hardcoded 2025 exporter (`scripts/export_for_web.py:2720`, `scripts/export_for_web.py:2763`); the README currently advertises the unsafe command (`README.md:252`).
- Main CI is red, whole-repository Ruff finds three lint violations and 14 formatting changes, and Mypy has ten errors but is advisory (`.github/workflows/test.yml:27`).
- Core `qpfl` line coverage is 82%. Combined `qpfl` and `api` coverage is 67%, with three API files at 0% and the NFL Draft API at 31%.
- The production lock has nine unique known advisories across six runtime packages. CI and operational workflows do not install from the lock.
- All six APIs use wildcard CORS, accept an uncapped declared body before authentication, and have no application-configured durable throttling.
- The browser persists raw team passwords in `localStorage` for seven days (`web/app.js:8213`).
- Confirmed dead code includes `qpfl/logging_config.py`, `scripts/export/name_matcher.py`, `scripts/export/playoff_calculator.py`, and the stale `scripts/export` package initializer.
- The remaining live rehearsal in `docs/2026_DRAFT_READINESS_CHECKLIST.md:168` has not been completed.

## Desired End State

- Vercel is the documented canonical site and API host; GitHub Pages remains a fully functional mirror that calls the Vercel API.
- Every committed `web/**` change can deploy Pages independently of scoring, and Pages deploys only committed `main` content.
- Team names are season-aware, point-in-time data accepted by validation and consistently applied to current and historical views.
- Untrusted text is rendered as text, inline event handlers are gone, and a working Content Security Policy limits script execution.
- Current and future lineup submissions always validate against an authoritative active roster; current-week lock data fails closed.
- Every multi-file roster mutation and its audit record are committed atomically or not at all.
- Workflows fail visibly if authoritative changes cannot be pushed.
- CI is green, deterministic, lockfile-backed, whole-repository linted, type-safe for `qpfl`, and guarded by meaningful coverage and dependency-audit floors.
- Unsafe/dead CLIs and modules are removed or repaired, living documentation matches the system, and the frontend is placed on a safe incremental modularization path.
- A live Week-1 rehearsal proves the complete browser → API → Git commit → score/export → deployment loop and records evidence.

### Architectural Decisions

- Keep GitHub-backed JSON as the authoritative store. Do not migrate to a database during pre-season stabilization.
- Make Vercel canonical because current Open Graph metadata, league links, API hosting, and the planned analytics deployment already use it. Keep Pages operational and update the repository Website field only after both hosts pass the same smoke checks.
- Use a single atomic Git commit for multi-file mutations. Compensating writes are not sufficient because compensation can also fail.
- Preserve point-in-time team-name history and add `season`; do not overwrite `data/teams.json` on each rename.
- Preserve future-week lineup entry because the UI intentionally exposes scheduled future weeks. Reject past weeks; require complete lock data for the authoritative open week.
- Use session-scoped browser credentials, strict rendering, CSP, password rotation, and provider-level rate limiting. Do not introduce OAuth or a new session database for this friends-league application.
- Decompose `web/app.js` only after release-critical behavior has browser coverage. Do not combine a framework rewrite with Week-1 fixes.

## What We're NOT Doing

- Migrating live data to Supabase, PostgreSQL, or another database.
- Rewriting frozen 2020–2025 scoring logic or historical JSON unless a specific historical correction is requested.
- Re-exporting all historical seasons as part of routine release work.
- Weakening schema or integrity validation to accommodate current API output.
- Adding a second API implementation to GitHub Pages.
- Building OAuth, user accounts, or a durable server-side session service.
- Replacing the frontend framework or redesigning the UI during correctness remediation.
- Rewriting legacy transaction history to add new operation IDs; old entries remain valid.
- Marking the live rehearsal complete without recorded production evidence.

## Implementation Approach and PR Boundaries

The merge order is mandatory because later phases rely on trust boundaries created earlier:

1. Immediate containment and green baseline.
2. Safe browser rendering and unified API routing.
3. Durable workflow push/deploy behavior.
4. Team-name model and export repair.
5. Fail-closed lineup validation.
6. Atomic transaction and mandatory audit commits.
7. API request/authentication hardening.
8. Dependency, typing, coverage, and maintenance automation.
9. Dead code, CLI, documentation, and frontend modularization cleanup.
10. Live release rehearsal and sign-off.

Use one PR per numbered phase except Phase 6 and the frontend portion of Phase 9, which should be smaller PR series as specified. Every PR must begin from green `main`, include its regression tests, and avoid generated score/data changes unless the phase explicitly requires a fixture or migration.

## Phase 0: Immediate Operational Containment

### Overview

Prevent known unsafe paths from being used while the fixes are under review. This phase changes operational behavior, not stored league data.

### Actions Required

- Direct managers to `https://qpfl-scoring.vercel.app/` for authenticated actions until Phase 2 is deployed.
- Suspend team-name changes until Phase 4 is deployed; a current rename can create schema-invalid data that the current exporter ignores.
- Do not accept trades containing both players and picks until Phase 6 is deployed. Commissioner-assisted manual processing must update all assets and the audit trail in one reviewed commit.
- Do not run `scripts/export_for_web.py --all` or `--force-current-season`. Historical corrections may use only an explicit `--reexport-historical YEAR` after reviewing the diff.
- Record the current SHAs of `data/rosters.json`, `data/draft_picks.json`, `data/pending_trades.json`, `data/transaction_log.json`, `data/team_names.json`, and `web/data.json` before live mutation testing.

### Success Criteria

#### Manual Verification

- [ ] Commissioners and managers have the temporary Vercel URL and the three temporary restrictions.
- [ ] No current trade has `execution: "in_progress"` or `reversal_execution: "in_progress"`.
- [ ] Baseline data-file SHAs are recorded in the release rehearsal notes.

---

## Phase 1: Restore a Trustworthy Green Baseline

### Overview

Make quality signals deterministic before functional changes begin, remove the dangerous all-season export entrypoint, and eliminate the literal NUL source artifact.

### Changes Required

#### 1. Restore and widen Ruff enforcement

**Files**: `.github/workflows/test.yml`, `.pre-commit-config.yaml`, the 14 files reported by `ruff format --check .`

- Apply Ruff formatting and fix the three whole-repository lint findings.
- Change CI to `ruff check .` and `ruff format --check .`.
- Align the pre-commit Ruff revision with the version locked for CI.
- Keep formatting-only commits separate from semantic fixes where practical.

#### 2. Remove literal NUL comparisons

**Files**: `web/app.js`, a focused UI regression test

- Add explicit ordered-array and unordered-set comparison helpers.
- Replace the delimiter joins at `web/app.js:11207`, `web/app.js:11216`, and `web/app.js:11358`.
- Add a test asserting `web/app.js` contains no NUL bytes.

#### 3. Disable the unsafe legacy export route

**Files**: `scripts/export_for_web.py`, `README.md`, `tests/test_export_for_web.py`, new `tests/test_cli_help.py`

- Replace manual argument parsing with `argparse` for this command.
- Expose only `--reexport-historical YEAR`; reject the current/future season.
- Remove `--all`, `--json`, `--season`, and `--force-current-season` from the public CLI.
- Remove the advertised `--all` command from README immediately.
- Prove `--help` exits 0 and creates or edits no files.

### Success Criteria

#### Automated Verification

- [ ] `uv run ruff check .`
- [ ] `uv run ruff format --check .`
- [ ] `uv run pytest -q`
- [ ] `node --check web/app.js`
- [ ] `git diff --check`
- [ ] `python -c "from pathlib import Path; assert b'\0' not in Path('web/app.js').read_bytes()"`
- [ ] `uv run python scripts/export_for_web.py --help` exits 0.
- [ ] `uv run python scripts/export_for_web.py --all` exits nonzero without changing files.

#### Manual Verification

- [ ] The GitHub Tests workflow is green on the PR.
- [ ] The PR contains no league-data changes.

---

## Phase 2: Establish Browser Trust Boundaries and Fix Deployment Routing

### Overview

Prevent stored/script injection before reconnecting the team-name feature, route both public hosts to the correct API, and decouple Pages deployment from scoring.

### Changes Required

#### 1. Render untrusted values safely

**Files**: `web/app.js`, `web/index.html`, `vercel.json`, new `tests/test_web_security.py`

- Treat every JSON/API value as untrusted: team and owner names, player/pick labels, transaction messages, conditions, notes, API errors, titles, attributes, and CSS-class inputs.
- Prefer `textContent` and DOM construction for status/error regions. Use `escapeHtml` only at unavoidable HTML-template text and attribute sinks.
- Rename trusted HTML-returning values with an `...Html` suffix so reviews can distinguish markup from text.
- Allow-list CSS-class/status values and local avatar paths.
- Remove inline `onclick`/`onerror` handlers and attach listeners from JavaScript.
- Add malicious fixtures such as `"><img src=x onerror=globalThis.pwned=1>` to standings, team comparison, transactions, pending trades, and manager status tests.

#### 2. Add an enforceable Content Security Policy

**Files**: `web/index.html`, `vercel.json`

- Add a Pages-compatible meta CSP and matching Vercel headers after inline script handlers are removed.
- Required directives: `default-src 'self'`, `script-src 'self'`, `connect-src 'self' https://qpfl-scoring.vercel.app`, `img-src 'self' data: blob:`, Google Fonts style/font origins, `object-src 'none'`, and `base-uri 'self'`.
- Retain `style-src 'unsafe-inline'` temporarily because inline styles are widespread; track removal in the frontend modularization series.
- Add `X-Content-Type-Options: nosniff`, a restrictive `Referrer-Policy`, and `Permissions-Policy` on Vercel.

#### 3. Centralize API endpoint resolution

**Files**: preferably new `web/api-config.js`, `web/index.html`, `web/app.js`, new `tests/test_api_routing_ui.py`

- Define one immutable API-origin resolver:
  - localhost/127.0.0.1 → production Vercel API;
  - `qpfl.github.io` → production Vercel API;
  - Vercel production and preview hosts → their own origin.
- Define all six endpoint URLs from that resolver.
- Replace `RULE_CHANGES_API_URL`, `LINEUP_CONFIG.workerUrl`, `MANAGE_CONFIG.apiUrl`, and `.replace('/lineup', ...)` endpoint derivation.
- Never accept an API origin from query parameters, local storage, or downloaded data.

#### 4. Deploy committed Pages content independently

**Files**: new `.github/workflows/deploy-pages.yml`, `.github/workflows/score.yml`, `.github/workflows/season-transition.yml`

- Deploy Pages on committed `main` changes under `web/**` and on manual dispatch.
- Use the standard Pages permissions and a `pages` concurrency group.
- Remove Pages upload/deploy steps from scoring and season-transition workflows after the dedicated workflow is proven.
- Deploy only checked-out committed content; never deploy a working tree whose preceding push failed.

### Success Criteria

#### Automated Verification

- [ ] Hostname-table tests cover localhost, Pages, Vercel production, and Vercel preview.
- [ ] A source test finds exactly one API-origin resolver and all six endpoint paths.
- [ ] Malicious fixtures render as visible text and create no injected elements.
- [ ] No inline JavaScript event attributes remain.
- [ ] `node --check web/app.js` passes.
- [ ] Existing UI, accessibility, and full Python tests pass.
- [ ] Workflow configuration tests prove Pages deploys committed `web/**` content independently.

#### Manual Verification

- [ ] All six health/OPTIONS calls from Pages reach Vercel rather than `github.io/api`.
- [ ] A staging credential validates from Pages without a browser CORS/network failure.
- [ ] Vercel preview calls its own preview APIs.
- [ ] A harmless `web/**` commit deploys Pages without running the scorer.
- [ ] Browser developer tools show no required-resource CSP violations.

---

## Phase 3: Make Workflow Persistence Fail Reliably

### Overview

Ensure workflows cannot claim success or deploy output unless authoritative Git changes were pushed.

### Changes Required

#### 1. Add one tested retry helper

**Files**: new `scripts/git_push_with_retry.sh`, new `tests/test_workflow_push_retry.py`

- Accept remote, branch, and attempt count.
- Pull/rebase and push explicitly to the requested branch.
- Exit immediately on a rebase conflict with a clear error.
- Retry push rejections with backoff, sleep only between attempts, and exit nonzero after the final failure.
- Preserve command output needed for Actions diagnostics.

#### 2. Replace every maintained inline loop

**Files**: `.github/workflows/score.yml`, `season-transition.yml`, `update-player-teams.yml`, `expire-trades.yml`, `lineup-reminders.yml`

- Replace the four false-success loops.
- Replace the currently correct reminders loop too, leaving one maintained implementation.
- Keep deployment and success notifications after the retry helper so a failure naturally blocks them.

### Success Criteria

#### Automated Verification

- [ ] A fake `git` succeeds on attempt three and the helper returns 0 after exactly three pushes.
- [ ] Exhausted pushes return nonzero.
- [ ] A pull/rebase failure returns nonzero without a push.
- [ ] No sleep occurs after the final attempt.
- [ ] `bash -n scripts/git_push_with_retry.sh`
- [ ] No targeted workflow contains `if git push; then break`.

#### Manual Verification

- [ ] A dry-run/manual workflow using a disposable branch shows a successful retry.
- [ ] The scorer cannot reach Pages deployment after a forced push failure in a disposable workflow test.

---

## Phase 4: Repair the Team-Name Data Contract End to End

### Overview

Ship the schema, resolver, writer, workflow trigger, and render safety together so the feature cannot again write data that no consumer understands.

### Changes Required

#### 1. Define the canonical season-aware model

**Files**: `qpfl/schemas.py`, new `qpfl/team_names.py`, `data/team_names.json`

Canonical entry:

```json
{
  "season": 2026,
  "effective_week": 0,
  "name": "New Team Name"
}
```

- Add `TeamNameEntry` with bounded integer `season`, bounded integer `effective_week` including 0, trimmed 1–50 character `name`, and no control characters.
- Change `TeamNamesFile.team_names` to `dict[str, list[TeamNameEntry]]` and validate known team abbreviations.
- Resolve the newest `(season, effective_week)` not later than the requested point; a late-season name carries forward to the next season but never changes earlier history.
- Include a tested compatibility normalizer for legacy string values and list entries missing `season`, even though the checked-in file is currently empty.

#### 2. Apply names consistently during scoring/export

**Files**: `autoscorer_json.py`, `scripts/export_current.py`, `scripts/export_for_web.py`

- Use the shared resolver rather than the legacy exporter's private implementation.
- Stamp point-in-time names into each scored week and its matchups.
- Apply the current name to current teams and standings.
- Preserve earlier weekly names after a later rename.
- Ensure the split current-season metadata and legacy compatibility payload agree.

#### 3. Harden the writer

**Files**: `api/team-name.py`, `web/app.js`

- Validate strings, known team codes, trimmed names, controls, and maximum length.
- Derive authoritative season/effective week from trusted current site/config data; do not allow a manager to backdate history through request fields.
- Reject `<` and `>` as defense in depth while still storing plain text rather than pre-encoded HTML.
- Retry GitHub 409 conflicts by refetching and reapplying the mutation.
- Return generic external errors; keep detailed redacted diagnostics server-side.

#### 4. Trigger the consumer

**File**: `.github/workflows/score.yml`

- Add `data/team_names.json` to the data-change trigger.
- Ensure a name-only change runs validation, current export, push, and the dedicated Pages deployment.

### Migration Notes

- Snapshot `data/team_names.json` before deployment.
- The current file is empty, so no production entry rewrite is expected.
- If an unexpected legacy entry exists at deployment, run the normalizer in dry-run mode, review its diff, then commit it separately before enabling the API.
- Do not deploy the writer before its schema and exporter.

### Success Criteria

#### Automated Verification

- [ ] API-produced team-name JSON passes `python -m qpfl.data_validation`.
- [ ] Tests cover empty history, week 0, same-week replacement, 409 retry, malformed types, control characters, multiple seasons, and carry-forward.
- [ ] A Week-8 rename leaves Weeks 1–7 unchanged and affects Week 8+, current standings, `web/data.json`, and split metadata.
- [ ] A team-name change is included in workflow trigger/config tests.
- [ ] XSS fixture names remain plain text on every tested surface.

#### Manual Verification

- [ ] A preview rename produces a valid data commit, export commit, and deployment.
- [ ] Reloading Vercel and Pages preserves the new current name.
- [ ] Earlier weeks retain their prior name.
- [ ] A malicious-looking name cannot execute markup.

---

## Phase 5: Make Lineup Validation Authoritative and Fail Closed

### Overview

Reject submissions when the server cannot prove roster membership and lock state, without removing the supported ability to enter a future scheduled lineup.

### Changes Required

#### 1. Replace ambiguous reads with typed outcomes

**File**: `api/lineup.py`

- Add a typed GitHub read error that distinguishes 404, authentication, transport, decoding, and malformed content.
- Return `None` only for explicitly optional paths.
- Fetch site context and rosters once at the beginning of a submission and derive validation/locks from the same snapshot.

#### 2. Validate the complete request contract

**File**: `api/lineup.py`

- Require a real integer week, explicitly rejecting booleans, strings, 0, and values over 17.
- Require the week to exist in the authoritative schedule.
- Reject weeks earlier than `lineup_week` with 409.
- Permit the authoritative `lineup_week` and scheduled future weeks.
- Require `starters` to be a dictionary whose values are lists of unique, nonempty strings.
- Always validate submitted players and positions against the active roster; taxi players remain invalid.
- Retain `locked_players` only as ignored backward-compatible input. Never union a client-supplied lock list into authority.

#### 3. Fail closed at the lock boundary

**File**: `api/lineup.py`

- For `week == lineup_week`, require a valid kickoff map and fail with 503 if site, roster, or kickoff data is unavailable/malformed.
- Treat a missing team in a valid kickoff map as a bye, not a global failure.
- Fail on malformed existing kickoff timestamps instead of silently skipping them.
- Future scheduled weeks still require roster validation but do not require kickoff data until they become authoritative.
- Perform no lineup PUT on any upstream/context failure.

### Success Criteria

#### Automated Verification

- [ ] Site/roster 404, 500, invalid JSON, or malformed shapes return 503 with zero lineup writes.
- [ ] Missing/malformed kickoff data for the open week returns 503.
- [ ] `"1"`, `True`, 0, and 18 return 400.
- [ ] A past week returns 409; a valid future scheduled week remains supported.
- [ ] Unknown, wrong-position, duplicate, and taxi starters return 400.
- [ ] Valid pre-kickoff starters succeed.
- [ ] A started player cannot be added, removed, or moved.
- [ ] Existing current-season path and concurrency retry tests remain green.

#### Manual Verification

- [ ] A preview branch with unavailable context returns 503 and receives no data commit.
- [ ] A valid current-week lineup succeeds before kickoff.
- [ ] A post-kickoff direct API attempt and browser attempt are both rejected.

---

## Phase 6: Commit Multi-File Transactions and Audit Logs Atomically

### Overview

Replace partial multi-file sagas with one branch-head compare-and-swap commit. Split this phase into foundation, trade, and remaining-mutations PRs.

### Changes Required

#### 1. Add an atomic Git JSON bundle primitive

**Files**: new `api/github_store.py`, new `tests/test_github_store.py`

Proposed interface:

```python
update_json_bundle(
    paths_with_defaults,
    mutate_fn,
    commit_message,
    operation_id,
    max_retries=5,
)
```

- Capture the branch head and read every requested file at that exact commit.
- Deep-copy and validate the complete snapshot before creating remote objects.
- Create blobs, a tree based on the captured head, and one commit with that head as parent.
- Update the branch ref with `force: false`.
- On a genuine non-fast-forward conflict, reread the new head and rerun validation/mutation from scratch.
- Surface authorization, rate-limit, validation, and malformed-response errors immediately; do not retry them as conflicts.
- If the response is ambiguous after ref update, reread state and check `operation_id` before deciding whether to retry.
- Confirm the sibling module is bundled in a Vercel preview before endpoint adoption.

#### 2. Make trade acceptance and reversal atomic

**File**: `api/transaction.py`

- Convert transfer logic into a pure snapshot mutation with no network writes.
- In one fresh-snapshot mutation, revalidate trade status, responder, player/pick ownership, roster/taxi limits, and conditions.
- Mutate `pending_trades.json`, `rosters.json`, optional `draft_picks.json`, and `transaction_log.json` in one commit.
- Set the accepted trade directly to `execution: "done"`; remove the pending → in-progress → partial writes → revert sequence.
- Use the same transfer primitive for commissioner reversal.
- Keep stale `in_progress` detection temporarily for legacy data only.

#### 3. Make every promised audit event mandatory

**Files**: `api/transaction.py`, `qpfl/schemas.py`

- Replace side-effecting `add_transaction_log` with a pure `_append_audit_event` used inside the bundle mutation.
- Add an optional `operation_id` to the schema; require it for new events and deduplicate retries by it rather than timestamp.
- Migrate in bounded groups:
  - taxi activation and standalone release: rosters + log;
  - FA activation: FA pool + rosters + log;
  - trade acceptance/reversal: pending trades + rosters + picks + log;
  - offseason toggle: league config + log;
  - commissioner release/add: rosters + log;
  - conditional-pick resolution: picks + log;
  - score adjustment: adjustments + log.
- Treat a missing, malformed, or unwritable audit log as a failed mutation.
- Delete `add_transaction_log` after all call sites are migrated.

### Migration Notes

- Existing log entries remain valid without `operation_id`.
- The current repository has no trade with either in-progress execution marker, so no reconciliation migration is currently needed; recheck immediately before deployment.
- Git history is the rollback record. A failed ref update changes no authoritative file.
- Preserve all current JSON shapes except the optional audit `operation_id`.

### Success Criteria

#### Automated Verification

- [ ] One bundle commit changes several files atomically.
- [ ] Failure before ref update changes none.
- [ ] Concurrent unrelated commits are preserved after retry/revalidation.
- [ ] Exhausted ref conflicts change none.
- [ ] An ambiguous successful response is detected by operation ID and does not duplicate effects.
- [ ] A player-plus-pick trade changes pending status, rosters, picks, and audit log in exactly one commit.
- [ ] A forced pick failure leaves every file byte-for-byte unchanged.
- [ ] Two concurrent accepts produce one transfer and one audit event.
- [ ] Every migrated mutation fails entirely when audit serialization/write fails.
- [ ] `python -m qpfl.data_validation` and `python scripts/check_integrity.py` remain green.

#### Manual Verification

- [ ] A Vercel preview targets a disposable Git branch with copied JSON data.
- [ ] A mixed player/pick trade creates one reviewed commit.
- [ ] Two simultaneous accept requests produce exactly one accepted trade.
- [ ] A release, FA activation, and commissioner action each commit domain state and log together.

---

## Phase 7: Harden API Requests and Browser Authentication

### Overview

Apply consistent request boundaries to all six APIs after their behavior is covered, then rotate credentials after the XSS protections are live.

### Changes Required

#### 1. Add a small shared request utility

**Files**: new `api/request_util.py`, all six endpoint files, API tests

- Keep this limited to request parsing, response headers, generic errors, and origin checks; do not combine it with the broader GitHub store refactor.
- Require JSON content type for POST.
- Reject missing, malformed, negative, or oversized content lengths before reading.
- Use a 64 KiB JSON limit for ordinary APIs and an approximately 3 MiB encoded limit for the 2 MiB avatar payload.
- Return 413 before invoking authentication or GitHub.
- Stop returning raw exception and GitHub response bodies. Return a generic message plus a request ID; log only redacted details.

#### 2. Pin allowed origins

**Files**: `api/request_util.py`, Vercel environment/configuration

- Allow `https://qpfl-scoring.vercel.app` and `https://qpfl.github.io`.
- Configure trusted preview origins explicitly in preview environments rather than accepting arbitrary `*.vercel.app` hosts.
- Echo only an allowed origin, add `Vary: Origin`, reject disallowed preflights, and allow missing `Origin` for authenticated CLI/server clients.

#### 3. Reduce credential persistence

**File**: `web/app.js`

- Move the validated team/password session from `localStorage` to `sessionStorage` so refresh remains supported but browser restarts require login.
- Delete the legacy local-storage key on first load and never copy its password into the new session.
- Keep commissioner credentials memory/session-only.
- Update the readiness and security documentation to match the shorter lifecycle.

#### 4. Add durable throttling and rotate secrets

**External system**: Vercel firewall/rate-limit configuration and Vercel environment variables

- Configure a conservative API POST limit by source IP and a tighter avatar-upload limit; return 429 with `Retry-After`.
- Start with 60 API POSTs per minute per source IP and 5 avatar uploads per hour per source IP; review Vercel logs after two weeks and tune only with recorded false positives/abuse evidence.
- Alert on more than 20 authentication failures from one source in five minutes without recording submitted credentials.
- Monitor repeated 401s without logging supplied passwords.
- After XSS/CSP and session-storage changes are deployed, rotate all ten team passwords, the commissioner credential, the legacy ADMIN credential, and any exposed preview credentials.
- Verify `SKYNET_PAT` remains server-only and least-privileged for the target repository.

### Success Criteria

#### Automated Verification

- [ ] Parameterized tests cover all handlers for allowed/disallowed/no Origin, OPTIONS, content type, malformed length, oversized body, and generic 500 output.
- [ ] Oversized requests do not call password validation or GitHub.
- [ ] Passwords are absent from `localStorage` in browser tests.
- [ ] Existing `hmac.compare_digest` authorization tests remain green.
- [ ] Vercel preview import/bundle smoke tests include the shared utility.

#### Manual Verification

- [ ] Pages and Vercel authenticated actions work with allowed origins.
- [ ] A disallowed preflight is rejected.
- [ ] Rate-limit testing returns 429 and later recovers.
- [ ] Old passwords no longer authenticate after rotation.
- [ ] No secret or raw upstream error appears in browser/network output.

---

## Phase 8: Make Dependencies, Types, Coverage, and Maintenance Reproducible

### Overview

Eliminate known dependency advisories and turn the currently advisory or incomplete quality checks into enforceable release gates.

### Changes Required

#### 1. Upgrade the production lock safely

**Files**: `pyproject.toml`, `uv.lock`, `requirements.txt`

- Resolve to non-vulnerable versions at least equivalent to:
  - `idna >= 3.15`;
  - `lxml >= 6.1.0`;
  - `pydantic-settings >= 2.14.2`;
  - `python-dotenv >= 1.2.2`;
  - `requests >= 2.33.0`;
  - `urllib3 >= 2.7.0`.
- Prefer upgrading parent dependencies (`nflreadpy`, `python-docx`) or uv constraints rather than pretending every transitive package is application-owned.
- Pin the minimal Vercel `requirements.txt` separately and audit it independently.

#### 2. Install reproducibly everywhere

**Files**: `.github/workflows/test.yml`, `score.yml`, `season-transition.yml`, `update-player-teams.yml`, `lineup-reminders.yml`, `pyproject.toml`

- Add Mypy and pip-audit to the declared development extra.
- Install CI from `uv.lock` with frozen `uv` commands; remove secondary floating `pip install` steps.
- Convert scoring and operational workflows to frozen production installs and `uv run --frozen`.
- Validate Python 3.10 and the workflow's Python 3.11 runtime.

#### 3. Enforce type correctness

**Files**: `qpfl/schedule.py`, `qpfl/data_fetcher.py`, `qpfl/json_scorer.py`, `.github/workflows/test.yml`

- Replace the ten current errors with typed playoff structures, explicit Polars row conversion, and validated/cast deserialized score-adjustment structures.
- Do not use blanket ignores.
- Remove `continue-on-error` and require `mypy qpfl` to pass.
- Add API typing incrementally after `github_store.py` and `request_util.py` establish shared contracts.

#### 4. Establish meaningful coverage gates

**Files**: `pyproject.toml`, `.github/workflows/test.yml`, API tests

- Collect branch coverage for `qpfl` and `api`; do not dilute the production gate with operational scripts.
- Preserve an 80% minimum for `qpfl` core.
- Add handler-level tests for team-name, team-avatar, and rule-changes, plus the remaining NFL Draft request/auth/failure cases.
- Establish an API-specific floor after these tests, starting no lower than 55%, and ratchet it upward with each API PR.
- Treat explicit critical-path behavioral tests as the real gate; percentages do not replace failure-injection tests.

#### 5. Automate dependency maintenance

**Files**: new `.github/dependabot.yml`, new `.github/workflows/dependency-audit.yml`

- Run a weekly/manual production-only pip-audit against an exported frozen lock and the Vercel requirements.
- Add monthly, non-auto-merged dependency update PRs for Python and GitHub Actions.
- Require every advisory waiver to include its ID, exposure analysis, owner, and expiration date.

### Success Criteria

#### Automated Verification

- [ ] `uv lock --check`
- [ ] A fresh `uv sync --frozen --extra dev` succeeds on Python 3.10 and 3.11.
- [ ] Production and Vercel dependency audits report zero unwaived known vulnerabilities.
- [ ] `uv run mypy qpfl` has zero errors.
- [ ] `uv run pytest -q --cov=qpfl --cov=api --cov-branch --cov-report=term-missing` passes both configured floors.
- [ ] Ruff, Node syntax, schema validation, integrity, and the full suite remain green.
- [ ] A before/after export comparison differs only in expected timestamps/provider-refreshed fields.

#### Manual Verification

- [ ] One preview scoring/export cycle completes with the upgraded lock.
- [ ] One nflreadpy fetch preserves expected tables/columns.
- [ ] Commissioner XLSX and DOCX generation paths open successfully.
- [ ] Every changed operational workflow succeeds in dry-run/no-write mode.

---

## Phase 9: Remove Dead Code, Repair Operator UX and Docs, Then Modularize Safely

### Overview

Finish confirmed cleanup without confusing it with release-critical behavior. The frontend split is a post-readiness PR series, not one rewrite.

### Changes Required

#### 1. Delete confirmed dead code

**Files to remove**:

- `qpfl/logging_config.py`
- `scripts/export/name_matcher.py`
- `scripts/export/playoff_calculator.py`
- `scripts/export/__init__.py`
- `TODO.md`

- Re-run repository-wide import/reference searches immediately before deletion.
- Preserve references inside `docs/history/` as historical records.
- Remove stale CI paths that exist only for the deleted `scripts/export` package.

#### 2. Repair remaining operator CLIs

**Files**: `scripts/export_historical.py`, `scripts/sync_lineups_to_excel.py`, new/expanded `tests/test_cli_help.py`

- Replace manual `sys.argv` parsing with `argparse`.
- Make `--help` exit 0 and invalid arguments nonzero without writes.
- Give lineup sync explicit `--season`, `--week`, `--excel`, and `--lineup-file` options; remove hidden 2025/Week-16 defaults.
- Require an explicit output target or default to dry-run for commands that mutate workbooks.
- Remove the ineffective `full_export` workflow input because both branches run the same current exporter.

#### 3. Correct living documentation and add drift tests

**Files**: `README.md`, `CONTRIBUTING.md`, `docs/API.md`, `docs/ARCHITECTURE.md`, `docs/2026_SEASON_CHANGES.md`, `docs/2026_DRAFT_READINESS_CHECKLIST.md`, `docs/ROADMAP_2026.md`, new `tests/test_docs.py`

- Remove volatile test-count claims and link to the canonical CI command.
- Document all six deployed APIs, public vs authenticated actions, atomic write guarantees, CORS/session behavior, and generic error semantics.
- Fix the three-WR lineup example and stale 2025 persistence path.
- Rewrite current architecture sections around code that exists; remove nonexistent `scripts.export.*` usage.
- State that JSON is authoritative and Excel import/export is directional rather than bidirectional.
- Document Vercel as canonical and Pages as a supported mirror after both are verified; update the GitHub repository Website field manually.
- Add tests proving documented scripts exist, documented endpoints match `vercel.json`, and lineup examples match configured starter limits.

#### 4. Modularize the frontend behind browser coverage

**Files**: `web/app.js`, `web/index.html`, new `web/js/*`, browser tests

PR series:

1. Add Playwright smoke coverage for bootstrap, navigation, historical season switching, login failure, lineup render, transaction dialog, and mobile navigation.
2. Remove any remaining global inline-handler dependencies.
3. Change the entrypoint to an ES module.
4. Extract pure modules first: API configuration/client, escaping/render utilities, resource loading/cache, and routing.
5. Extract one feature per PR: home, matchups, standings, rosters, Hall of Fame, manager tools, commissioner tools, and NFL Draft.
6. Keep state ownership explicit and preserve visual behavior.
7. Ratchet `app.js` size downward after each extraction; do not set an arbitrary one-PR rewrite target.
8. Remove `style-src 'unsafe-inline'` only after inline styles have been migrated and browser tests prove the stricter CSP.

### Success Criteria

#### Automated Verification

- [ ] Repository-wide searches find no live imports/references to deleted modules.
- [ ] Every maintained operator CLI returns 0 for `--help`, nonzero for invalid input, and makes no help-path writes.
- [ ] `tests/test_docs.py` passes endpoint, path, and starter-limit drift checks.
- [ ] Playwright smoke tests, existing UI contract tests, `node --check`, Ruff, Mypy, and full Pytest pass after every module extraction.

#### Manual Verification

- [ ] Commissioner dry-runs of each maintained CLI show explicit inputs and outputs.
- [ ] Historical documents remain untouched.
- [ ] Each frontend extraction preview is visually and functionally equivalent on desktop and mobile.

---

## Phase 10: Complete and Record the Live Week-1 Rehearsal

### Overview

Prove the production system after all release-critical phases are deployed. This is the release gate, not an optional cleanup exercise.

### Changes Required Before Rehearsal

#### 1. Add safe reminder test modes

**Files**: `.github/workflows/lineup-reminders.yml`, `tests/test_lineup_reminders.py`

- Manual dispatch defaults to dry-run.
- A test-recipient mode routes all email to a masked `REMINDER_TEST_EMAIL` and does not write production delivery state.
- Production manual delivery requires an explicit mode selection.
- Tests prove dry-run/test modes neither contact team addresses nor mutate delivery state.

#### 2. Use a disposable preview branch first

- Point Vercel preview GitHub writes at a disposable branch containing copied current JSON.
- Exercise failure injection there: unavailable lineup context, atomic trade conflict/failure, disallowed origins, oversized bodies, rate limiting, and simultaneous accepts.
- Delete or archive the disposable branch only after evidence has been captured; do not point preview mutation tests at `main`.

### Production Rehearsal Steps

1. Record deployed commit SHA, baseline data-file SHAs, `web/data.json` timestamp, and relevant workflow run IDs.
2. Confirm main Tests, dependency audit, Pages deploy, and latest Autoscorer runs are green.
3. Probe all ten credentials through validation without printing or persisting passwords.
4. Log in through Vercel and Pages, refresh each, and confirm session-scoped persistence.
5. Submit one legal GSA Week-1 lineup before kickoff.
6. Confirm the API commit contains only the intended lineup file and operation metadata.
7. Confirm the commit triggers scoring/export, that its generated-data push succeeds, and that dedicated Pages/Vercel deployments publish the committed result.
8. Compare deployed split data and compatibility payloads to the repository commit.
9. Confirm unstarted players remain editable before kickoff.
10. After a real kickoff, attempt to replace one started player through both browser and direct API; both must reject it while valid unstarted changes remain possible.
11. Perform a preview/staging mixed player-and-pick trade and verify one atomic commit contains all asset, status, and audit changes.
12. Run the reminder workflow in test-recipient mode and verify one controlled message with no production delivery-state mutation.
13. Restore the intended GSA lineup before kickoff if the rehearsal lineup was temporary.
14. Record SHAs, workflow URLs, timestamps, outcomes, and any restoration in `docs/2026_DRAFT_READINESS_CHECKLIST.md`.
15. Mark P0.9 complete in `docs/ROADMAP_2026.md` only after every exit criterion is met.

### Release Exit Criteria

#### Automated Verification

- [ ] Main Tests, dependency audit, Pages deployment, and Autoscorer workflows are green.
- [ ] All six production health endpoints pass.
- [ ] All ten credential validations pass without secret disclosure.
- [ ] Schema validation and cross-file integrity report no errors.
- [ ] Production dependency audit has no unwaived advisory.

#### Manual Verification

- [ ] Both public hosts can perform authenticated actions against the intended Vercel API.
- [ ] One real lineup completes API → Git commit → scoring/export → committed deployment.
- [ ] Started-player changes fail in both browser and API.
- [ ] A mixed trade is proven atomic in preview/staging.
- [ ] Reminder test reaches only the controlled recipient.
- [ ] Production data ends in its intended state or is explicitly restored and documented.

---

## Testing Strategy

### Unit and Component Tests

- Pure team-name resolution across seasons/weeks and compatibility normalization.
- HTML/attribute escaping and API-origin resolution.
- Typed lineup context/error handling and complete request validation.
- Pure transaction snapshot mutations, operation-ID idempotency, and audit ordering.
- Push retry exit behavior.
- CLI argument/help behavior and documentation drift checks.

### Integration Tests

- API-produced team-name JSON through schema validation and current export.
- Lineup failure injection proving zero writes on incomplete context.
- In-memory Git branch/head model proving multi-file atomicity and conflict retries.
- Browser smoke tests against a local static server.
- Workflow configuration tests for triggers, committed deployment, and shared retry usage.

### Manual and Preview Tests

- Use a Vercel preview wired to a disposable Git branch for every mutating API test.
- Verify both Vercel and Pages origins.
- Inspect the exact Git diff/commit created by each high-risk action.
- Test desktop and mobile after frontend rendering/module changes.
- Never print passwords, PATs, SMTP credentials, or signing material in logs or screenshots.

## Performance and Operational Considerations

- Atomic bundle commits should reduce GitHub API write commits for multi-file actions, but retry logic must respect GitHub rate limits and retry only head conflicts.
- Dedicated Pages deployment prevents scoring jobs from spending time on deployment and prevents deployment of uncommitted output.
- CSP and safe rendering should not alter payload size materially.
- Playwright belongs in CI only after its runtime/browser download cost is measured; a focused smoke project is sufficient.
- Dependency updates should be isolated so scoring-output changes can be attributed and rolled back cleanly.
- Do not allow concurrent test automation to write to production `main`; preview environments use disposable branches.

## Migration and Rollback Notes

- Team names: current production data is empty; snapshot and normalize only if unexpected entries appear. Roll back UI/API independently, but keep valid history in Git.
- Transactions: legacy logs remain valid without operation IDs. Recheck for in-progress trades immediately before deployment and route any found record to commissioner review.
- Authentication: remove the old local-storage key and rotate credentials only after XSS/CSP and session-storage code is live. A rollback requires issuing fresh credentials, never restoring retired ones.
- Dependencies: revert `pyproject.toml`, `uv.lock`, requirements, and workflow install changes together. Do not include generated scoring data in the dependency PR.
- Workflows: a retry-helper failure is intentionally blocking. Roll back the helper/workflow call sites together if a real push path is incompatible.
- Git data provides recovery for valid committed mutations; never use a force push or destructive reset as rollback.

## Completion Checklist

- [ ] Phases 1–9 merged with their automated/manual evidence.
- [ ] Main CI and dependency audit green.
- [ ] Release-critical API behavior covered by failure-injection tests.
- [ ] Vercel canonical site and Pages mirror documented and functional.
- [ ] Unsafe exporter route and confirmed dead code removed.
- [ ] Living docs pass drift checks.
- [ ] Live rehearsal evidence recorded and P0.9 marked complete.
- [ ] No unresolved high- or medium-severity audit finding remains.

## References

- Audit target: `main` at `76b2965` on August 25, 2026.
- `docs/ROADMAP_2026.md`
- `docs/2026_DRAFT_READINESS_CHECKLIST.md`
- `docs/DATA_LAYER_DECISION.md`
- `docs/DURABILITY_PLAN.md`
- `.github/workflows/test.yml`
- `.github/workflows/score.yml`
