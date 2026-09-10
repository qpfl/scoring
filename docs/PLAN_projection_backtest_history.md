# Evaluate projection accuracy across all replayable seasons

## Context

We backtested the projection model once before. `docs/PROJECTION_BACKTEST.md` records a
single evaluation: parameters tuned on the complete 2024 season, then scored once on the
unseen 2025 season (1,653 starter predictions, 115 team predictions, player MAE 4.823,
team MAE 16.568, 59.6% winner accuracy).

That is one season of evidence. `web/data/seasons/` actually holds a replayable week corpus
for **2020–2025** (16–17 weeks each; the 2026 directory is empty), and
`scripts/backtest_projections.py` already accepts `--season`, so the model can be replayed
against five seasons of history with no new model code. Nothing about the results is
persisted either — the numbers live only in the markdown prose, with no CI check, so they
can silently drift from the code.

**Outcome:** a season-by-season and position-by-position accuracy history for the projection
model, replacing the single-season snapshot in `docs/PROJECTION_BACKTEST.md`. No model
behavior changes.

## Decisions

- **Scope: run and document.** No re-tuning, no parameter changes, no new persisted JSON
  artifact. (Re-tuning on the fuller history is a reasonable follow-up but is explicitly out
  of scope here.)
- **Evaluable seasons: 2021–2025.** 2020 is excluded — the walk-forward model needs a prior
  season, and 2020 is the earliest data we have. 2020 still contributes as the prior season
  for 2021.
- The **current** production settings are the subject. The script also reports the
  `original_model` baseline for free; keep that comparison since it shows whether the tuning
  generalized past 2025 or just fit it.

Per this project's convention, a copy of this plan goes into the repo's `docs/` on approval.

## Steps

### 1. Add a multi-season driver to the backtest script

`scripts/backtest_projections.py` — `main()` (line 306) hardcodes one season into the report.
Extend the CLI rather than looping in the shell, so the run is reproducible from one command:

- Accept `--season` repeatedly (or add `--seasons 2021-2025`), defaulting to today's single-
  season behavior so the documented `--season 2025 --tune` command in
  `docs/PROJECTION_BACKTEST.md:29` keeps working unchanged.
- For each season, reuse the existing `run_backtest(season, weeks, settings, history_root,
  schedule_rows)` (line 197) with `ProjectionSettings()` (current) and the existing hardcoded
  `baseline` (line 320). Note `load_projection_schedule_rows` (line 319) is called per season
  with `[season-2, season-1, season]` — load the union once across all requested seasons
  instead of refetching per season.
- Emit a report keyed by season, plus an **all-seasons pooled** roll-up. Pool by summing the
  raw `ErrorMetrics` accumulators (`count`, `absolute_error`, `squared_error`,
  `signed_error` — lines 41–63) and the matchup counters, *not* by averaging per-season MAEs;
  season sample sizes differ. This likely wants a small `ErrorMetrics.merge()` /
  `BacktestMetrics.merge()` helper — the only new logic in the task.
- Leave `--tune` alone; it stays a single-season operation.

Keep the script's existing contract: print JSON to stdout, write nothing to disk.

### 2. Run it

```bash
.venv/bin/python scripts/backtest_projections.py --seasons 2021-2025
```

Capture the JSON to the scratchpad for transcription. Expect this to be slow-ish — five
seasons × ~17 weeks × two settings — but far cheaper than the 120-combo `--tune` grid.

### 3. Rewrite `docs/PROJECTION_BACKTEST.md`

Preserve the doc's existing framing (walk-forward replay, no score leakage, tuned-on-2024 /
evaluated-on-2025 provenance) and the **"What the backtest does not measure"** section at the
end — the availability-gate blind spot is still true and still the reason these figures are
the pessimistic case. Then replace the single 2025 table with:

- **Per-season table** (2021–2025 rows): player count / MAE / RMSE / bias, team count / MAE /
  RMSE / bias, matchup winner accuracy, Brier score.
- **Pooled all-seasons row** for the current model, with the original-model pooled row beside
  it — this is the headline "how have our projections performed historically" answer.
- **Per-position breakdown** (pooled): MAE / RMSE / bias / sample count per position. This is
  already computed by `BacktestMetrics.positions` (line 70) but has never been surfaced in the
  doc, and is the most actionable new information — it shows which positions the model is
  actually bad at.
- A short prose read of the results: whether accuracy is stable across seasons, whether the
  2025-tuned parameters hold up on 2021–2024, and any position that is a clear outlier.

Add the new command to the doc's runnable-command block.

### 4. Update tests

`tests/test_projection_backtest.py` (58 lines, 4 tests) covers settings-match-production,
`_pregame_schedule` masking, settings restoration, and `ErrorMetrics` math. Add a test for the
new merge/pooling helper — pooled MAE of two accumulators must equal the sample-weighted
result, not the mean of the two MAEs. Confirm the existing four still pass.

## Critical files

- `scripts/backtest_projections.py` — the only code change (CLI + pooling helper).
- `docs/PROJECTION_BACKTEST.md` — the deliverable.
- `tests/test_projection_backtest.py` — one added test.
- `qpfl/projections.py` (tunable constants, lines 22–28) — **read only, not modified.**
- `web/data/seasons/<year>/weeks/week_N.json` — the replay corpus, untouched.

## Verification

1. `.venv/bin/python scripts/backtest_projections.py --season 2025` still prints the same
   `current_model` numbers as `docs/PROJECTION_BACKTEST.md` records today (player MAE 4.823,
   team MAE 16.568, 1,653 players / 115 teams). If this drifts, the model changed since the
   doc was written and that is itself a finding worth reporting before continuing.
2. `.venv/bin/python scripts/backtest_projections.py --seasons 2021-2025` completes and the
   2025 slice of its output is byte-identical to the single-season run above.
3. Pooled `count` equals the sum of the per-season counts; spot-check one pooled MAE by hand
   against the per-season absolute-error totals.
4. `.venv/bin/python -m pytest tests/test_projection_backtest.py` passes.
5. Every number in the rewritten doc traces to a line in the captured JSON — no figures
   carried over from the old doc except the explicitly-labeled 2025 tuning provenance.
