# Projection backtest

The projection model is tested with a walk-forward replay: every historical week is projected using only the prior season and earlier weeks from the target season. The target week's NFL schedule is treated as pregame, so final scores cannot leak into the projection.

Run either evaluation from the repository root:

```bash
# Every replayable season, pooled
.venv/bin/python scripts/backtest_projections.py --seasons 2021-2025

# One season, plus a grid search on the preceding season
.venv/bin/python scripts/backtest_projections.py --season 2025 --tune

# One row per prediction, for diagnosing a position
.venv/bin/python scripts/backtest_projections.py --seasons 2021-2025 --dump-residuals residuals.jsonl
```

The three models the report compares:

- **Original** — before any tuning work.
- **Previous** — tuned on 2024, shipped after a single 2025 evaluation.
- **Current** — the model described below. Every change was selected on 2021–2024 and confirmed once on held-out 2025; anything that did not survive that holdout was reverted and is listed under "Ideas that were tested and rejected".

## Is the model better than guessing?

Raw MAE says nothing on its own, so every prediction is also scored by two naive predictors on the identical sample:

- **Position average** — the running average of every starter at that position.
- **Player average** — the player's own running average, falling back to the position average when he has no history.

Pooled over 2021–2025:

| Model | Player MAE | vs. position average | vs. player average |
| --- | ---: | ---: | ---: |
| Position-average baseline | 4.995 | — | — |
| Player-average baseline | 5.134 | — | — |
| Original | 5.051 | +1.1% | -1.6% |
| Previous | 5.041 | +0.9% | -1.8% |
| **Current** | **4.828** | **-3.4%** | **-6.0%** |

Negative means the model wins. **An earlier shipped model was worse than simply predicting each position's running average.** The current model beats both baselines, but by 3–6%, not an order of magnitude. Treat projections as a modest refinement of "this player scores about what he usually scores," not as precision forecasting.

`mae_over_sd` in the JSON report expresses the same idea per position: error divided by that position's own standard deviation. A predictor that always guesses the mean lands near 0.80, so values below that are skill and values above it are not. Do not read the pooled `mae_over_sd` across all positions — it is deflated by between-position variance.

## Season-by-season accuracy

Current model, weeks 1–17.

| Season | Player predictions | Player MAE | Player RMSE | Player bias | Team predictions | Team MAE | Team RMSE | Team bias | Matchups | Winner accuracy | Brier score |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2021 | 1,111 | 5.110 | 6.957 | -0.014 | 0 | — | — | — | 0 | — | — |
| 2022 | 1,414 | 4.764 | 6.531 | +0.051 | 0 | — | — | — | 0 | — | — |
| 2023 | 1,431 | 5.074 | 6.828 | -0.296 | 0 | — | — | — | 0 | — | — |
| 2024 | 1,653 | 4.614 | 6.399 | -0.580 | 110 | 14.730 | 19.106 | -2.899 | 55 | 60.0% | 0.241 |
| 2025 | 1,653 | 4.692 | 6.475 | -0.257 | 115 | 16.707 | 21.234 | -0.058 | 57 | 63.2% | 0.232 |
| **All** | **7,262** | **4.828** | **6.615** | **-0.241** | **225** | **15.740** | **20.222** | **-1.447** | **112** | **61.6%** | **0.236** |

2020 is not evaluated — the walk-forward model needs a prior season and 2020 is the earliest data we have. It still serves as the prior season for 2021.

**2021–2023 produce no team or matchup results.** The backtest only reports a team total when the stored historical lineup satisfies the *current* starter-slot rules, and the OL starter slot was not introduced until 2024. Pre-2024 lineups can therefore never form a complete team.

## Accuracy by position, 2021–2025 pooled

| Position | Predictions | MAE | RMSE | Bias | MAE/σ | Position-avg baseline | Player-avg baseline | vs. position avg | vs. player avg |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| QB | 788 | 8.063 | 10.132 | -0.191 | 0.78 | 8.270 | 8.618 | -2.5% | -6.5% |
| RB | 1,561 | 6.017 | 7.716 | -0.319 | 0.75 | 6.332 | 6.386 | -5.0% | -5.8% |
| WR | 1,571 | 5.472 | 7.011 | -0.555 | 0.78 | 5.595 | 5.738 | -2.2% | -4.6% |
| D/ST | 756 | 4.669 | 5.988 | -0.038 | 0.79 | 4.617 | 4.982 | **+1.1%** | -6.3% |
| TE | 782 | 4.174 | 5.570 | -0.483 | 0.73 | 4.442 | 4.423 | -6.0% | -5.6% |
| K | 774 | 2.880 | 3.712 | +0.018 | 0.77 | 2.893 | 3.028 | -0.5% | -4.9% |
| OL | 329 | 1.782 | 2.267 | +0.011 | 0.79 | 1.796 | 1.947 | -0.8% | -8.5% |
| HC | 701 | 1.578 | 2.069 | +0.226 | 0.75 | 1.839 | 1.856 | **-14.2%** | -15.0% |

Every position beats the player-average baseline. **D/ST is the one position still short of its own position average**, by 1.1% — see "Positions the model cannot beat" below for why the fallback does not take it all the way to parity.

HC is now the model's strongest position relative to its baseline, having been among the weakest — see below.

## Head coaches are projected from the market spread

`score_head_coach` (`qpfl/scoring.py`) is a pure step function of the game's final margin and contains nothing player-specific. The right projection is therefore that step function evaluated against the best available forecast of the margin, which is the pregame betting line. `spread_line` and `total_line` ship with the nflverse schedule the pipeline already loads; `compact_schedule_rows` simply used to discard them.

Tuning drives the smoothing width toward zero, i.e. toward scoring the spread itself. That is not overfitting: for a monotone step function the median outcome is `f(spread)`, and the median is what minimises absolute error. A small non-zero width remains so the projection does not jump a full point when a line moves half a point.

Measured across 2024–2025, the two seasons with team-level data:

| | Previous | With market lines |
| --- | ---: | ---: |
| HC MAE | 1.741 | **1.498** (-14%) |
| Overall player MAE | 4.684 | 4.662 |

Lines are used for **head coaches only**. The correlation between a position's score and its opponent's market-implied team total is -0.29 for HC and -0.31 for D/ST but under 0.10 for every skill position, and wiring the lines into D/ST produced no holdout gain — the existing opponent adjustment already captures it.

## Positions the model cannot beat are projected at the position average

If a player-specific projection is worse than simply predicting the position's running average, the honest thing to publish is the running average. D/ST and OL were both in that state, so `POSITION_AVERAGE_WEIGHT_BY_POSITION` now sets them to 1.0: every starter at those two positions is projected at the position average, with no player history, opponent adjustment or home/away input surviving the blend.

The anchor is the *plain* mean of every starter observation in the history window, not the model's own trimmed, prior-blended position estimate (`POSITION_AVERAGE_USES_PLAIN_MEAN`). The naive predictor being matched is a plain mean, so matching it with a trimmed one would miss.

Pooled 2021–2025:

| | Player-specific | Position average |
| --- | ---: | ---: |
| D/ST MAE | 4.696 (+1.7% vs baseline) | **4.669 (+1.1%)** |
| D/ST bias | -0.137 | **-0.038** |
| OL MAE | 1.827 (+1.7%) | **1.782 (-0.8%)** |
| OL bias | -0.026 | **+0.011** |
| Overall player MAE | 4.832 | **4.828** |
| Team bias | -1.548 | **-1.447** |

OL now beats its baseline outright. **D/ST closes about a third of its gap but does not reach parity**, and the reason is a windowing difference rather than a modelling one: the model averages the two seasons it loads, while the baseline predictor accumulates a running mean over every week replayed so far. Closing that fully would mean widening D/ST's history window, which was tested separately and gained nothing on the holdout.

Weights between 0 and 1 were also measured. D/ST at 0.75 and OL at 0.5 were marginally better on the 2021–2024 tuning seasons and worse on held-out 2025, so the full average was kept — it is also the setting that actually states what the measurement found.

K and WR were tested here too: K gained 0.8% on the tuning seasons and gave back more on the holdout, and WR was flat. Neither uses the fallback.

**One visible consequence:** every D/ST projects the same number in a given week, as does every OL. That is the point — the model is saying it cannot tell them apart — but it does look inert on the matchup page next to positions that vary.

## Team totals use a different estimator than player projections

A player projection is tuned to minimise *his* absolute error, and trimming pulls it toward the median of a right-skewed distribution — below his mean. That is the right number to show for one player and the wrong one to add up: nine of them systematically under-project a team. Pooled team bias was -3.16 while player bias was only -0.27.

Team totals therefore sum an untrimmed mean (`_unbiased_baseline`) rather than the displayed projection. Across 2024–2025 this moved team bias from -3.16 to -1.45 with team MAE flat (15.72 → 15.74).

For the avoidance of doubt, that comparison is against the *same* model with the estimator switched off. Against the previously shipped model the team-level picture is a wash rather than a win: team MAE 15.592 → 15.740 and team bias +0.141 → -1.447, while player MAE improves 5.041 → 4.828 and winner accuracy 58.0% → 61.6%. The team numbers rest on 225 predictions from two seasons, the player numbers on 7,262 from five, which is why selection was run on the latter.

**Winner accuracy fell as a side effect**, from 73/112 to 69/112 across the same seasons. Two caveats: 112 matchups is a thin sample where three games is 2.7 points, and every change in this round that improved player-level accuracy moved winner accuracy the other way. That relationship is not yet understood and is the most important open question in this document.

## Ideas that were tested and rejected

Recorded so they are not re-attempted. Each is still available behind a flag in `qpfl/projections.py`.

| Idea | Result |
| --- | --- |
| **Recency weighting** | A player's last four games predict *worse* than his whole history, at every position, by 3–9%. Week-to-week "form" is noise. Corroborated by tuning, where 7 of 8 positions chose the maximum prior-season weight. |
| **Home/away** | The raw gap is real (QB +1.65 points, most others +0.3 to +0.7) but applying it makes the model slightly worse. Home teams are disproportionately favourites, and the opponent adjustment and market lines already capture that. |
| **Median instead of mean** | Minimising absolute error argues for the median, and it beats the mean by 1.5% as a *position* predictor. Inside the model it does not: trimming and shrinkage already pull toward the median, and a quantile of a thin per-player sample is noisier than its mean. TE and WR gained on the tuning seasons and gave it back on the holdout. |
| **Wider history window** | Extending D/ST and QB to every available season was worth 3.5% and 0.7% on the tuning seasons and nothing on the holdout. |
| **Per-position opponent cap** | No override survived the holdout. |
| **Position-average fallback at K and WR** | K gained 0.8% on the tuning seasons and gave back more on the holdout; WR was flat. Kept for D/ST and OL only, where the model genuinely loses to the average — see above. |

The pattern is consistent: ideas that help a *position-level* predictor mostly fail inside the model, because the model's shrinkage already extracts that signal from far larger samples than any individual player provides.

## How to read these numbers

Figures below are the pooled 2021–2025 current-model results.

  - **Player MAE 4.828 / RMSE 6.615**: on average, individual player predictions are off by about 4.8 points, with the higher RMSE indicating a handful of larger misses pull the error up.
  - **Player bias -0.241**: predictions run about a quarter-point low on average, across 7,262 starter predictions.
  - **Team MAE 15.740 / RMSE 20.222**: complete team score predictions are off by about 15.7 points on average, across 225 team predictions.
  - **Team bias -1.447**: team totals are predicted about 1.4 points low — down from -3.16 before team totals got their own estimator, and now small next to the typical error.
  - **Matchup winner accuracy 61.6% (69/112)**: correctly picks the winning team in about 3 of 5 matchups.
  - **Win-probability Brier score 0.236**: how well-calibrated the predicted win probabilities are (0 = perfect, 0.25 = no better than always guessing 50%). Still close to the coin-flip baseline, meaning the probability estimates aren't sharp even when the winner pick is right.
  - **Skill vs. baseline**: the only number that says whether the model is worth having. -3.4% against the position average means the model's error is 3.4% smaller than always predicting each position's running average.

## What the backtest does not measure

The availability gate — zeroing players an injury designation or NFL roster status rules out, and coaches who are no longer their team's listed head coach — is **not** exercised here. Both feeds describe the present: Sleeper reports only current designations, and `data/coach_overrides.json` is maintained for the live week. Replaying 2025 cannot recover who was listed out in Week 6 of that season, so `scripts/backtest_projections.py` passes no availability data and the numbers above measure the underlying model exactly as before.

In production the gate can only remove points from a player who was already going to score near zero, so it should improve real error slightly. Treat the figures above as the pessimistic case.

Neither does it measure the **live** projection the site shows above the pregame one. That line replaces a starter's projection with his real points once his game is final, so its error falls to zero as a week resolves and averaging it over a season would say more about kickoff times than about the model. The replay masks the target week's results (`_pregame_schedule`), so no game is ever final inside it and the two lines are identical by construction — every figure in this document, winner accuracy and Brier included, is the pregame projection.

## Known data defects in the replay corpus

`nfl_team` is blank on some archived roster entries, which removes them from player and opponent history entirely. Counts by season and position: 2021 D/ST 118/256, 2022 D/ST 340/340, 2020 QB 12/384, 2024 HC 4/340, plus a handful of singletons. 2023, 2025 and the current season are clean. Repairing the 2021–2022 D/ST entries would improve those seasons' replays, but the files are frozen historical data protected by `.github/workflows/protect_historical.yml` and were left untouched.
