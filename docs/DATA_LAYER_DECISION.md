# Data Layer Decision: Git-as-Database, Not a Database Migration

**Date:** July 2026. **Context:** this repo is meant to run QPFL scoring for
decades. Before further investing in the data layer, we evaluated whether to
migrate off git-backed JSON onto a real database (Supabase/Postgres was the
concrete option considered).

## Decision

**Stay with git-as-database.** Instead, harden it — see `docs/DURABILITY_PLAN.md`
for what was actually built (schema validation, cross-file integrity checks,
stat-input archival, season-freeze tooling).

## Why not migrate

- **Volume is a non-issue.** The entire mutable working set (`data/`) is
  ~600 KB. It will stay trivially small forever — a fantasy league doesn't
  accumulate write volume the way a real application does.
- **Concurrency is already handled, and well-tested.** Every write goes
  through an optimistic read-modify-write against the GitHub Contents API
  (`api/transaction.py:update_json_file`): fetch fresh content + sha, apply
  the mutation, PUT with that sha, retry on 409 by re-fetching and re-applying.
  Multi-file operations that can't be a single atomic commit (trade accept,
  FA activation) are implemented as explicit sagas with a gate step, and are
  covered by race-condition tests in `tests/test_api.py` (a fake-GitHub-repo
  harness enforcing sha/409 semantics).
- **The historical corruption incidents don't indict this architecture.**
  `scripts/fix_historical_scores.py` and `scripts/validate_scores.py` exist
  because 2020–2025 scores were hand-entered into Excel and drifted from the
  computed values — a spreadsheet-entry problem. The 2026+ pipeline
  (`autoscorer_json.py` → `qpfl/json_scorer.py`) recomputes every score from
  source stats on every run; there's no hand-entry step left to corrupt.
- **Git is arguably the more durable choice over a 20+ year horizon:** free
  forever, full audit history for free (every change is a commit with a
  timestamp and message), human-readable and diffable, and portable to any
  future host with zero migration. A Supabase dependency adds recurring cost,
  a vendor-survival bet over decades, opaque binary/row state instead of
  diffable files, and — critically — a migration that touches all six write
  endpoints and the scoring pipeline simultaneously, which is itself the
  single largest error-injection event available to this codebase.

## What we hardened instead

The real decades-scale risks, and what addresses each:

1. **Validation theater.** `qpfl/schemas.py` modeled a roster shape that
   didn't match the flat on-disk `data/rosters.json` — nothing was actually
   validating the write path. Rewritten to match reality; enforced via
   `qpfl/data_validation.py` in CI, pre-commit, and the scoring workflow.
2. **No cross-file integrity checking.** `qpfl/integrity.py` /
   `scripts/check_integrity.py` check invariants no single-file schema can
   express: a player owned by at most one roster, lineup starters actually on
   the active roster, pending trades offering only owned players, draft pick
   uniqueness, transaction log ordering.
3. **The nflverse dependency.** If nflreadpy/nflverse ever disappears or
   renames/reclassifies players, historical 2026+ scores become
   non-reproducible. `qpfl/data_fetcher.py`'s snapshot archival
   (`--save-snapshot` / `--from-snapshot` on `autoscorer_json.py`) freezes the
   exact stats consumed for each scored week so any week can be re-scored
   bit-for-bit forever, independent of the upstream data source.
4. **No season-freeze ritual.** `scripts/create_new_season.py` now also
   auto-extends `protect_historical.yml`'s protected-file list (closing the
   recurring "forgot to protect the just-frozen season" class), validates
   `data/` before calling the transition done, and tags
   `season-{year}-final` locally so any season's exact final state is one
   `git checkout` away forever.

See `docs/DURABILITY_PLAN.md` for the full implementation plan and file map.
