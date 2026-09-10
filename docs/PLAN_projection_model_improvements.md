# Improve the projection model

## Context

`docs/PROJECTION_BACKTEST.md` now covers 2021–2025 (7,262 starter predictions). It shows the
tuning generalized — pooled player MAE 5.041, team MAE 15.592, both better than the
pre-tuning configuration — and it flags D/ST as the one position with a badly non-neutral
bias (-1.773).

Measuring the model against **naive baselines** reframes the problem. Replaying the same
starters walk-forward:

| Position | n | Predict position avg | Predict player's own avg | Model | vs. position avg | vs. player avg |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| QB | 788 | 9.302 | 8.467 | 8.214 | -11.7% | -3.0% |
| RB | 1,561 | 6.412 | 6.257 | 6.068 | -5.4% | -3.0% |
| WR | 1,571 | 5.546 | 5.509 | 5.659 | +2.0% | +2.7% |
| D/ST | 756 | 4.776 | 4.880 | 5.562 | **+16.5%** | **+14.0%** |
| TE | 782 | 4.346 | 4.215 | 4.282 | -1.5% | +1.6% |
| K | 774 | 2.952 | 3.051 | 2.956 | +0.1% | -3.1% |
| HC | 701 | 1.994 | 1.899 | 1.892 | -5.1% | -0.3% |
| OL | 319 | 1.846 | 1.915 | 1.840 | -0.3% | -3.9% |
| **All** | **7,252** | **5.148** | **5.017** | **5.041** | **-2.1%** | **+0.5%** |

Negative means the model wins. **Overall the model beats "always predict the position
average" by 2.1%, and loses to "always predict that player's own running average" by 0.5%.**
Per-position error is also ~0.75–0.94× each position's own standard deviation, i.e. close to
what a constant predictor scores. Real skill exists only at QB, RB, and HC; WR and D/ST are
negative, and D/ST is 16.5% worse than a constant.

(These baselines are approximate — they use simpler filtering than the backtest, n=7,252 vs
7,262. Step 1 makes them exact.)

Two concrete defects are already identifiable in `qpfl/projections.py`:

1. **The position mean is contaminated by bench players.** `_load_history` (line 159) ingests
   every rostered player, so `position_values` mixes starters with bench. After trimming, that
   mean sits below the starter population the model is actually predicting, at every position:

   | | D/ST | HC | K | OL | QB | RB | TE | WR |
   | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
   | Trimmed all-roster mean | 5.94 | 0.92 | 5.75 | 1.66 | 18.39 | 9.35 | 5.03 | 7.96 |
   | Starter mean | 6.57 | 1.35 | 6.02 | 1.70 | 21.19 | 11.24 | 6.44 | 9.48 |
   | Gap | -0.63 | -0.44 | -0.27 | -0.04 | **-2.80** | **-1.90** | -1.40 | -1.53 |

   `PLAYER_POSITION_WEIGHT = 8` (line 29) shrinks every player hard toward that low number, so
   the pull is strongest exactly where history is thinnest.

2. **Symmetric trimming on skewed distributions.** `_trim_extremes` (line 219) drops 10% from
   each end. Fantasy scoring is right-skewed (RB +1.02, WR +0.98, TE +1.40 skew), so equal-count
   trimming removes more *magnitude* from the high tail than the low, biasing the mean down.

**Outcome:** a model that beats both naive baselines at every position, with D/ST no longer
worse than a constant, verified on a season never used for tuning.

## Decisions (confirmed with the user)

- **Structural fixes plus a retune** — not just a parameter sweep. The baseline result says
  parameter search alone won't move much.
- **Optimize pooled player MAE**, not team MAE. 7,262 samples across five seasons rather than
  225 from two. Team MAE becomes a reported guardrail, not the objective.
- **Honest holdout: tune on 2021–2024, evaluate once on 2025.** 2025 must not be touched by any
  search in this work.
- No new external data sources (no Vegas lines, snap counts, usage trends) — out of scope.

Per this project's convention, a copy of this plan goes into the repo's `docs/` on approval.

## Steps

### 1. Make baselines and per-position statistics first-class in the backtest

`scripts/backtest_projections.py`. Everything here is measurement — no model behavior changes.

- Add two naive predictors evaluated on the identical filtered sample the model sees, so the
  comparison is exact rather than approximate: **position running mean** and **player running
  mean** (falling back to position mean when a player has no history). Accumulate them into
  `BacktestMetrics` alongside the model, reusing `ErrorMetrics` (line 41) and the `merge`
  helpers added in the previous change.
- Extend the per-position summary (`BacktestMetrics.positions`, line 70) with the actual-score
  mean and standard deviation, so the report can express error as **MAE / σ** and **skill vs.
  baseline** rather than raw points. Raw MAE is not comparable across positions whose means
  range from 1.35 (HC) to 21.19 (QB).
- Add `--dump-residuals PATH` writing one row per prediction (season, week, position, projected,
  actual, sample_size, opponent_multiplier). This is what makes step 2 possible; without it the
  D/ST diagnosis is guesswork. Default off, so the script's "prints JSON, writes nothing"
  contract holds unless asked.

### 2. Diagnose D/ST before changing it

Using the residual dump, answer: is the -1.773 bias uniform, or concentrated in low-sample
players / specific opponent multipliers / negative-score weeks? Check the interaction with
`projected_points = baseline + abs(baseline) * (multiplier - 1)` (line 405) — the `abs()` makes
the opponent adjustment push the *wrong direction* for a negative baseline, and D/ST is the
position that routinely scores negative.

The bench-contamination gap for D/ST is only -0.63, so it does not by itself explain -1.773.
Do not skip this step and assume it does. If the residual dump shows the cause is something
other than the two defects above, revise steps 3–4 accordingly and say so.

### 3. Fix the two identified defects

`qpfl/projections.py`:

- **Starter-aware position baseline.** `_Observation` (line 73) already has the fields; add a
  `starter` flag in `_load_history` and either restrict `position_values` to starters or weight
  starters higher. Keep `player_values` on all appearances — a player's own history is the
  signal we want, bench weeks included.
- **Skew-aware trimming.** Replace symmetric count trimming in `_trim_extremes` with an
  approach that does not systematically lower the mean of a right-skewed sample — trim only the
  low tail, or trim symmetrically then bias-correct. Whichever wins on the tuning seasons.
- **Guard the opponent adjustment for negative baselines** at line 405 if step 2 confirms it.

Each fix lands as a `ProjectionSettings` flag in the backtest so it can be measured
independently and turned off, matching how `exclude_legacy_bench_zeroes` already works. Do not
combine them into one unmeasurable change.

### 4. Per-position parameters

`PLAYER_POSITION_WEIGHT`, `PRIOR_GAMES_WEIGHT`, and `OUTLIER_TRIM_FRACTION` (lines 22–29) are
global today, applied identically to QB (σ 10.35) and OL (σ 2.25). Convert them to per-position
values with the current global as the default, so a position that wants no shrinkage can have
none. This is the single highest-leverage structural change and the reason to retune.

### 5. Retune and evaluate once

Extend `tune_settings` (line 269) to optimize **pooled player MAE over 2021–2024**. The current
120-combo product grid does not scale to per-position parameters — use a coordinate descent
(tune one position's parameters at a time, holding the rest) or a random search with a fixed
seed. Then run **2025 exactly once** as the holdout.

Ship only if, on held-out 2025, the new model beats both naive baselines overall and at every
position, and does not regress team MAE materially. If it doesn't clear that bar, report the
numbers and keep the current parameters — a negative result documented is a real outcome here.

### 6. Update the docs

`docs/PROJECTION_BACKTEST.md`: add the baseline-comparison and MAE/σ columns to the
per-position table, record the held-out 2025 result for the new model, and keep the existing
"What the backtest does not measure" section. Preserve the plain-English "How to read these
numbers" section, updated.

## Critical files

- `qpfl/projections.py` — the model. Constants lines 22–29; `_load_history` 159; `_trim_extremes`
  219; `_player_mean` 262; projection math 405.
- `scripts/backtest_projections.py` — baselines, per-position stats, residual dump, retuning.
- `tests/test_projection_backtest.py` and `tests/test_projections.py` — cover each new setting
  flag and the baseline predictors.
- `docs/PROJECTION_BACKTEST.md` — the results record.

`qpfl/scoring.py` and `qpfl/base_scorer.py` are **not** touched. Official scoring is unaffected.

## Verification

1. `.venv/bin/python -m pytest tests/ -q` — all 788 tests pass.
2. With every new setting off, `--seasons 2021-2025` reproduces today's documented numbers
   exactly (pooled player MAE 5.041, team MAE 15.592, D/ST bias -1.773). If it doesn't, a
   "measurement-only" change altered behavior and must be fixed before continuing.
3. The exact in-backtest baselines land within ~0.15 of the approximate table above; a large
   divergence means the baseline is not seeing the same sample as the model.
4. Held-out 2025: new model beats both baselines overall and per position; D/ST |bias| well
   under 1.0 and MAE below the 4.78 position-mean baseline.
5. Each fix from steps 3–4 has its own measured before/after, so the doc can attribute the gain
   rather than reporting one lumped improvement.
6. `.venv/bin/python -m ruff check` and `ruff format --check` on changed files.
