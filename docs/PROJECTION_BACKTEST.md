# Projection backtest

The projection model is tested with a walk-forward replay: every historical week is projected using only the prior season and earlier weeks from the target season. The target week's NFL schedule is treated as pregame, so final scores cannot leak into the projection.

The current parameters were selected on the complete 2024 QPFL season, then evaluated once on the complete 2025 season. The tuning objective was team-score mean absolute error. The search compared prior-season weights, position-average stabilization, and opponent-sample requirements while retaining the requested 10% outlier trimming and exclusion of unverified legacy bench zeroes.

## 2025 unseen evaluation

| Metric | Original model | Tuned model |
| --- | ---: | ---: |
| Starter player predictions | 1,653 | 1,653 |
| Player MAE | 4.842 | 4.823 |
| Player RMSE | 6.639 | 6.574 |
| Player bias | -0.436 | +0.078 |
| Complete team predictions | 115 | 115 |
| Team MAE | 16.300 | 16.568 |
| Team RMSE | 21.680 | 21.166 |
| Team bias | -3.138 | +1.552 |
| Matchup winner accuracy | 57.9% (33/57) | 59.6% (34/57) |
| Win-probability Brier score | 0.227 | 0.235 |

The tuned model improved player MAE, player and team RMSE, absolute bias, and winner accuracy. Team MAE worsened by 0.268 points, and win-probability calibration did not improve. The latter remains an informational estimate rather than a scoring input.

The resulting model gives the current season more weight, stabilizes limited prior-season player history toward the position average, trims the highest and lowest 10% once at least 10 observations exist, excludes unverified legacy bench zeroes, caps opponent effects at 20%, and requires 32 opponent-position observations before applying the full adjustment.

Run the repeatable comparison from the repository root:

```bash
.venv/bin/python scripts/backtest_projections.py --season 2025 --tune
```

The backtest only produces a team result when the stored historical lineup satisfies the current starter-slot rules. That is why the team and matchup sample counts are smaller than the player sample count.
