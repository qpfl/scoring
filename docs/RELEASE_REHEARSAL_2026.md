# 2026 Release Rehearsal Record

## Baseline

Recorded August 26, 2026 before live mutation testing. Values are Git blob IDs for the checked-in
file contents, so they remain verifiable even if the branch moves.

| File | Baseline blob |
|---|---|
| `data/rosters.json` | `42116714ad995cc48a1435e092fb6e261f0306ef` |
| `data/draft_picks.json` | `4245a3883e7a9a6ac76235cbe2a510e5d511ebe8` |
| `data/pending_trades.json` | `23bb4c553fcc13dde0c93c4d7ce643323000940a` |
| `data/transaction_log.json` | `ce432eb447a29644c1eb585f9bca5c79eabe09c2` |
| `data/team_names.json` | `413c432f9de09d1bc56d1ca9204c75f2461c175b` |
| `web/data.json` | `7fe1e30c11ea690efe812809da3b3b8339955339` |

Recompute a value with `git hash-object <path>`.

## Repository verification

- [ ] Record the reviewed commit SHA deployed to the preview and production environments.
- [ ] Confirm frozen install on Python 3.10 and 3.11.
- [ ] Confirm CI, dependency audits, schema validation, integrity, and both coverage gates.
- [ ] Compare a current export before/after dependency upgrades; allow only expected timestamps and
  provider-refreshed values.
- [ ] Open commissioner XLSX and DOCX downloads and confirm their structure.
- [ ] Exercise each maintained mutating CLI in dry-run/no-write mode.

## Preview failure injection

- [ ] Unavailable lineup context returns `503` and writes nothing.
- [ ] A post-kickoff lineup change is rejected in both browser and direct API.
- [ ] Disallowed origins, non-JSON requests, malformed lengths, and oversized bodies are rejected
  before authentication/storage calls.
- [ ] An atomic trade conflict retries the whole bundle; a permanent failure changes no file.
- [ ] Two simultaneous accepts result in one completed operation and one rejected/no-op request.
- [ ] A missing or malformed audit log prevents the corresponding domain mutation.
- [ ] Configured provider throttles return `429` with `Retry-After` and later recover.

## Production path

- [ ] Validate all ten manager credentials from the canonical Vercel site.
- [ ] Validate one staging credential from the GitHub Pages mirror.
- [ ] Confirm login survives same-tab refresh and does not survive a closed browser session.
- [ ] Submit a legal temporary GSA Week 1 lineup before kickoff.
- [ ] Record the API-created lineup commit SHA and verify its diff contains only intended data.
- [ ] Confirm the scoring workflow runs, pushes generated data with retry, and records its commit SHA.
- [ ] Confirm Vercel and the dedicated Pages workflow publish that exact committed result.
- [ ] Verify the updated lineup and team name from both hosts, including an old-week point-in-time name.
- [ ] Complete one controlled atomic mixed player/pick trade or equivalent preview-only fixture and
  verify roster, pick, trade, and audit state share one commit.
- [ ] Restore the intended GSA lineup before kickoff if a temporary lineup was used.

## Operational sign-off

- [ ] Rotate team, commissioner, ADMIN, and preview credentials after hardened code is deployed.
- [ ] Verify the `SKYNET_PAT` scope and that no response/log contains submitted credentials.
- [ ] Enable and observe the documented Vercel rate limits and authentication-failure alert.
- [ ] Set the repository Website field to the canonical Vercel URL.
- [ ] Link the workflow runs, deployment URLs, mutation commit SHAs, screenshots, and rollback notes
  below before declaring release readiness.

### Evidence

Not yet recorded. Do not mark the rehearsal complete without production evidence.
