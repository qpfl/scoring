# Five improvements to player-level projection accuracy

## Context

`docs/PROJECTION_BACKTEST.md` now measures the model against two naive predictors on the
identical sample. Pooled 2021–2025, the current model is 2.8% better than "predict each
position's running average" and 5.4% better than "predict that player's own running average."
That is a real but thin margin, and two positions — **D/ST (+1.7%) and OL (+1.7%)** — still
lose to their own position average outright.

Per-position error sits at 0.73–0.87 × each position's standard deviation. A predictor that
always guesses the mean scores ~0.80, so the model is only modestly better than a constant
almost everywhere. **Set expectations accordingly: weekly fantasy scoring is dominated by
irreducible variance, and the realistic combined gain from everything below is on the order of
5–10% MAE, not a step change.** The value is that all five are cheap, measurable, and use data
the pipeline already fetches.

Each suggestion below was tested against the real corpus before being proposed. The evidence
is stated with each one.

## Decisions (confirmed with the user)

- Implement all five, in the order given, each behind a `ProjectionSettings` flag with its own
  measured before/after — the pattern established by `treat_unknown_team_as_bye` and
  `position_mean_starters_only`.
- Market lines are acceptable: `spread_line` and `total_line` already ship with the nflverse
  schedule `load_projection_schedule_rows` loads every run. No new dependency.
- Selection on 2021–2024, confirmed once on held-out 2025, objective pooled player MAE. Team
  MAE, winner accuracy and Brier stay guardrails.

---

## 1. Use market lines for HC and D/ST

**The single highest value-per-effort item.** `compact_schedule_rows` (`qpfl/projections.py`)
keeps 10 columns and throws away `spread_line`, `total_line`, `div_game`, `roof`, `temp`,
`wind`, and the rest. Spreads and totals are *pregame* forecasts, so using them is not leakage.

`score_head_coach` (`qpfl/scoring.py:292`) is a pure step function of the game's final margin —
nothing player-specific at all. So the right HC projection is the expected value of that step
function under a distribution centred on the spread.

**Evidence.** Scoring HC as `E[f(margin)]` with `margin ~ Normal(spread, 13.5)` — no fitting,
a textbook σ — over 697 matched predictions:

| HC predictor | MAE |
| --- | ---: |
| Position-average baseline | 1.839 |
| Current model | 1.828 |
| **Spread-based** | **1.734** (−5.1%) |

Correlation between actual score and the opponent's market-implied team total:

| | D/ST | HC | K | RB | WR | OL | TE | QB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| r | **-0.309** | **-0.292** | -0.095 | -0.068 | -0.022 | -0.032 | +0.024 | +0.001 |

The signal is concentrated in exactly the two positions the model handles worst, and is
essentially absent for skill positions. **Apply market lines to HC and D/ST only** — do not
wire them into QB/RB/WR/TE, where the evidence says there is nothing to gain.

Implementation: add the columns to `compact_schedule_rows`, carry them onto `GameContext`
(which already exists and already reaches the projection loop), and give HC a dedicated
spread-driven path plus D/ST an opponent-implied-total adjustment analogous to the existing
`_opponent_multiplier`. Tune σ and the D/ST coefficient on 2021–2024.

## 2. Predict the MAE-optimal point estimate per position

MAE is minimised by the conditional **median**, not the mean, and QPFL scoring is right-skewed
(TE skew +1.40, RB +1.02, WR +0.98). The model currently returns a trimmed *mean* everywhere.

**Evidence** — walk-forward, position-average predictor, mean vs median:

| | HC | TE | WR | RB | OL | D/ST | K | QB | **All** |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Median vs mean | **-9.6%** | **-4.2%** | -1.6% | -1.4% | -1.2% | +0.2% | +0.1% | +0.3% | **-1.5%** |

It helps most positions and hurts three slightly, so make the central-tendency estimator a
**per-position choice** (trimmed mean, median, or a tunable quantile) in the same table-driven
way `OUTLIER_TRIM_FRACTION_BY_POSITION` now works. Note this partially overlaps with trimming,
which already pulls toward the median — measure it *after* step 1 so the gains aren't
double-counted.

## 3. Use home/away

`GameContext.is_home` is already computed, already stored in the week files, and **never read
by the projection math.** Free signal.

**Evidence** — mean starter score, home vs away, 2021–2025:

| | QB | RB | D/ST | OL | K | WR | HC | TE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Home − away | **+1.65** | +0.66 | +0.66 | +0.57 | +0.47 | +0.40 | +0.32 | -0.20 |

Add a per-position home/away adjustment, shrunk by sample size the way `_opponent_multiplier`
already shrinks via `OPPONENT_FULL_WEIGHT_SAMPLES`. TE's negative sign is almost certainly
noise, which the shrinkage will handle on its own.

## 4. Widen the history window — and explicitly do *not* weight by recency

`_load_history` hard-codes `for history_season in (season - 1, season)`. Two seasons is an
arbitrary cut, and thin-history players are exactly where the model is weakest.

The obvious companion idea — weight recent games more — is **wrong here, and the data is
unambiguous.** Walk-forward within each player, last-4-games mean vs all-prior mean:

| | D/ST | K | WR | RB | OL | TE | HC | QB | **All** |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| last-4 vs all-prior | +8.7% | +7.5% | +6.7% | +4.6% | +4.4% | +3.7% | +3.0% | +3.2% | **+5.3%** |

Positive means worse. Recency is *worse at every single position* — week-to-week "form" is
noise. This corroborates the retune, where 7 of 8 positions chose a prior-season weight of 8
over 2. So: **extend to three seasons of history, keep shrinking hard, add no decay term.**
Guard the cost — `_load_history` re-reads and re-parses every week file on every call, so a
third season makes the backtest ~50% slower unless the parse is cached.

## 5. Tune the opponent adjustment per position, and defer to the position average where the model has no skill

Two related findings.

**The opponent adjustment is net positive but not universally.** Pooled 2021–2025:

| | Overall | D/ST | QB | RB | TE | K | OL | HC | WR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| With adjustment | 4.857 | 4.696 | 8.063 | 6.017 | 4.174 | 2.880 | 1.827 | 1.828 | 5.472 |
| Without | 4.884 | 4.760 | 8.136 | 6.062 | 4.202 | 2.897 | 1.845 | **1.824** | **5.463** |

It earns its keep everywhere except WR and HC. Make `opponent_cap` per-position like the other
tunables.

**And for the positions with no skill, say so in the math.** Optimal blend weight toward the
position average, fitted per position:

| Position | Best weight on position average | MAE gain |
| --- | ---: | ---: |
| D/ST | 0.75 | −1.8% |
| OL | 0.70 | −2.0% |
| Everything else | ≤ 0.45 | ≤ 0.3% |

Overall this is only −0.3% and the weights are in-sample, so the honest gain is smaller — but
it is the direct fix for the two positions that currently lose to a constant. Implement as a
per-position blend weight tuned on 2021–2024, not as fitted-on-everything weights.

---

## Deliberately not proposed: usage-based stat projection

Projecting carries/targets/attempts from nflverse and running them through
`score_skill_player` is the only idea with a shot at a step change, since usage is far more
stable than the fantasy points it produces. It is excluded here because the scope dwarfs all
five items combined, it needs a new historical stat pipeline, and it does nothing for HC, OL,
or D/ST (2,000 of 7,262 predictions), whose scoring is not usage-driven at all. Revisit if the
five above land and the margin over baseline is still thin.

## Critical files

- `qpfl/projections.py` — all model changes. `compact_schedule_rows` (schedule columns),
  `GameContext`, `_load_history` (window), `_opponent_multiplier` / `_player_mean` /
  `_trim_extremes` (per-position tables already threaded through), the projection loop.
- `qpfl/scoring.py:292` — `score_head_coach`, read-only reference for the HC margin function.
- `scripts/backtest_projections.py` — one `ProjectionSettings` flag per step; extend the tuner.
- `tests/test_projections.py` — the autouse `fixed_projection_parameters` fixture pins the
  mechanics tests to global parameters; new per-position behaviour needs its own tests.
- `docs/PROJECTION_BACKTEST.md` — record each step's measured contribution.

## Verification

1. Every step off ⇒ `--seasons 2021-2025` reproduces today's numbers exactly (player MAE 4.857,
   D/ST 4.696, skill vs position average −2.78%). Any drift means a "measurement-only" change
   altered behaviour.
2. Each step gets its own pooled before/after row, so the doc can attribute gains rather than
   reporting one lump. Steps 1 and 2 overlap — measure in order and report the marginal effect.
3. Held-out 2025 run **once** at the end. Ship criterion: pooled player MAE improves, no
   position regresses more than 1%, and team MAE / winner accuracy / Brier do not regress.
4. Target for D/ST and OL specifically: both must stop losing to their position average.
5. `.venv/bin/python -m pytest tests/ -q` (793 currently passing) plus `ruff check` and
   `ruff format --check`.
6. Sanity-check that market-line columns are absent for future/unplayed games and that the code
   fails open when `spread_line` is null — the projection must never depend on a line existing.
