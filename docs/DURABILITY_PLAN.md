# Decades-Durability Plan: Harden the Git-Backed Data Layer (No Database Migration)

## Context

The QPFL scoring repo must run a 10-team dynasty league reliably for decades. The question was whether to restructure the data layer — e.g. migrate to Supabase — to minimize future errors.

**Decision: do not migrate to a database.** See `docs/DATA_LAYER_DECISION.md` for the full reasoning; summary:

- The entire mutable working set is ~600 KB of JSON in `data/`; volumes will stay trivially small forever.
- The write path (Vercel functions → GitHub Contents API) already has well-tested optimistic concurrency: sha-based 409 retry with re-applied mutations (`api/transaction.py:112-159`), a race-tested trade-accept saga (`handle_respond_trade`), and a claim/rollback FA pattern — all covered by `tests/test_api.py`'s fake-GitHub harness.
- The historical corruption incidents (`scripts/fix_historical_scores.py`, `scripts/validate_scores.py`) all trace to the **retired Excel hand-entry pipeline (2020–2025)**, not the JSON+git architecture. The 2026+ pipeline recomputes from source stats and is idempotent.
- Over a 20+ year horizon, git-as-database is the *most* durable option: zero cost, full audit history for free, human-readable/diffable state, portable to any host. A Supabase dependency adds ~$25/mo, vendor-survival risk, opaque state, and a migration that rewrites all six write endpoints + the scoring pipeline — the largest error-injection event possible.

The real decades-scale risks are different, and this plan targets them:
1. **Validation theater** — `qpfl/schemas.py` Pydantic models described a nested roster shape that did not match the flat on-disk `data/rosters.json`; nothing structurally validated `data/*.json` on write or in CI.
2. **No cross-file integrity checking** — nothing verified invariants like "each player on exactly one roster" or "lineup starters exist on the roster" repo-wide.
3. **nflverse dependency** — if `nflreadpy`/nflverse data ever disappears or renames players, historical 2026+ scores become non-reproducible.
4. **No season-freeze ritual / redundancy** beyond `protect_historical.yml`.

## Workstream 1 — Decision record ✅ DONE

`docs/DATA_LAYER_DECISION.md` records the assessment (why not Supabase, what was hardened instead). This plan lives at `docs/DURABILITY_PLAN.md`.

## Workstream 2 — Real schema validation ✅ DONE

**Files:** `qpfl/schemas.py` (rewritten), `qpfl/data_validation.py` (new), `.github/workflows/test.yml`, `.github/workflows/score.yml`, `.pre-commit-config.yaml`, `tests/test_schemas.py` (new).

- `qpfl/schemas.py` now models the actual on-disk shape of every file in `data/`: `RostersFile` (flat `dict[team, list[Player]]` with a `taxi` bool), `LineupWeekFile` (position lists mixed with `submitted_at`/`comment` string metadata), `TeamsFile`, `PendingTradesFile`, `TransactionLogFile` (heterogeneous by `type`, `extra='allow'`), `DraftPicksFile`, `DraftsFile` (loosely structured — historical draft records carry free-text trade annotations), `FAPoolFile`, `TradeBlocksFile`, `ScoreAdjustmentsFile`, `RuleProposalsFile`, `TeamNamesFile`, `AvatarsFile`, `DraftOrdersFile`, `NameBattlesFile`, `LeagueConfig`. Position/team values are validated against `qpfl/constants.py` (`POSITION_ORDER`, `ALL_TEAMS`) instead of duplicated literals.
- `qpfl/data_validation.py::validate_data_dir()` maps each filename to its model and validates the whole `data/` tree (plus every `data/lineups/{season}/week_N.json`); `python -m qpfl.data_validation` is the CLI entry point.
- Enforced in three places: CI (`test.yml`), pre-commit (`validate-data` hook, scoped to `data/` changes), and the scoring workflow (`score.yml`, right before the data gets committed/deployed — failures trigger the existing commissioner-email step).
- Vercel functions still can't import `qpfl` (not bundled), so API-side validation stays in each `mutate_fn`; these checks are the structural backstop that catches anything that slips through.

## Workstream 3 — Cross-file integrity checker ✅ DONE

**Files:** `qpfl/integrity.py` (new), `scripts/check_integrity.py` (new), `tests/test_integrity.py` (new).

Invariants checked, each returning a plain-English violation string:
- **Rosters:** a player is owned by at most one team *per position* (D/ST and OL are independent draftable pools sharing NFL team names — "Chicago Bears" can legitimately be one team's D/ST and another's OL); no duplicate entries; active/taxi counts within `league_config.json` slot limits; taxi one-per-position.
- **Lineups:** every current-season starter exists on the owning team's active (non-taxi) roster at the submitted position — scoped to the *current* season only, since `rosters.json` reflects only current state and prior seasons' rosters have since changed via trades/drafts.
- **Pending trades:** offered players still owned by the offering side (for `pending` trades); no trade stuck in `execution: in_progress` for more than an hour.
- **Draft picks:** each `(year, round, draft_type, original_team)` pick exists exactly once; `current_owner` is a known team.
- **Transaction log:** newest-first ordering, with a documented carve-out for a batch of 2023 entries that share a known placeholder timestamp from a historical backfill (not real corruption).
- **Config consistency** (season/deadline/roster/starter/taxi slots across `league_config.json`, `api/*.py`, `qpfl/constants.py`, `web/app.js`) was already covered by the pre-existing `tests/test_config_consistency.py` — no changes needed there.

Wired into the same three enforcement points as Workstream 2 (`scripts/check_integrity.py` in CI, pre-commit, and `score.yml`).

## Workstream 4 — Stat-input archival (reproducibility without nflverse) ✅ DONE

**Files:** `qpfl/data_fetcher.py`, `qpfl/base_scorer.py`, `qpfl/json_scorer.py`, `autoscorer_json.py`, `.github/workflows/score.yml`.

- `NFLDataFetcher.to_snapshot()` serializes every frame consulted for a scored week (player stats, team stats, schedules, play-by-play, and the OL-position slice of the players database) to plain JSON-safe dicts; `NFLDataFetcher.from_snapshot()` rebuilds a fully-functional fetcher from that dict with zero network access.
- `qpfl.data_fetcher.snapshot_path/save_snapshot/load_snapshot` handle the gzip archival to `data/stat_snapshots/{season}/week_{N}.json.gz`.
- `BaseScorer`/`score_week_from_json` accept an optional pre-built `data_fetcher`, so scoring can run entirely offline from an archive.
- `autoscorer_json.py` gained `--save-snapshot` (archive after a live score) and `--from-snapshot` (score entirely from a prior archive, erroring clearly if none exists). `score.yml` now always passes `--save-snapshot`, so every scored week going forward is permanently reproducible without depending on nflreadpy/nflverse still existing or agreeing with itself.

## Workstream 5 — Season-freeze ritual + redundancy ✅ DONE

**Files:** `scripts/create_new_season.py`, `NEW_SEASON_CHECKLIST.md`, `.github/workflows/protect_historical.yml` (auto-extended by the script, not hand-edited), `.github/workflows/mirror.yml` (new).

- `create_new_season.py` now also: auto-adds the just-frozen season's `web/data_{year}.json` to `protect_historical.yml`'s protected list (closes the recurring "forgot to protect the new frozen season" class — this exact bug was `docs/ROADMAP_2026.md` P0.7); runs `qpfl.data_validation` + `qpfl.integrity` against the resulting `data/` state and prints any issues before declaring the transition done; creates a local (unpushed) `season-{year}-final` git tag so any season's exact final state is one `git checkout` away forever.
- `.github/workflows/mirror.yml`: a weekly scheduled job that bundles the full repo history (`git bundle create --all`) and uploads it as a workflow artifact — insurance against loss of the GitHub account/org itself, independent of GitHub's own storage of the repo.

## Explicitly out of scope

- Supabase/Postgres migration (rejected — see `docs/DATA_LAYER_DECISION.md`).
- Frontend restructuring (`web/app.js`), exporter retirement — already covered by `docs/ROADMAP_2026.md` P3.2/P3.3.
- Auth redesign — per-team env-var passwords are right-sized for the threat model (roadmap P2.6 already hardened comparisons).

## Verification

1. `uv run pytest` — full suite (213 tests as of this work) stays green; `test_schemas.py`, `test_integrity.py`, `test_data_fetcher.py` (snapshot round-trip), and `test_create_new_season.py` cover the new behavior.
2. `uv run python -m qpfl.data_validation` and `uv run python scripts/check_integrity.py` pass against the real `data/` tree.
3. Negative tests exercise: duplicate player across rosters, roster/taxi slot overflow, lineup starter not on roster (including a taxi player named as a starter), a pending trade offering an unowned player, a trade stuck in `execution: in_progress`, duplicate/unknown-owner draft picks, and out-of-order transaction log entries.
4. Snapshot round-trip: `test_snapshot_round_trip_reproduces_scoring_inputs` and `test_snapshot_gzip_round_trip` build a synthetic fetcher, snapshot it, rebuild from the snapshot (including from the gzip file on disk), and confirm identical scoring-relevant lookups (`find_player`, `get_team_stats`, `get_game_info`, `get_ol_touchdowns`).
5. `scripts/create_new_season.py --dry-run` was run against the real repo to confirm every new step (protect_historical.yml update, validation, tagging) reports sensibly before any real transition is attempted.

## Sequencing

1. Schemas rewrite + validator + CI wiring (Workstream 2) — the highest-value slice.
2. Integrity checker (3) — builds on the same models.
3. Stat snapshots (4) — now archived automatically every scored week going forward.
4. Freeze ritual + mirror (5) and docs (1) — done alongside.
