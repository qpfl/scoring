# TODO

## Draft Class Performance Analysis ✅ DONE

Draft History now includes class-level career totals, current roster retention, the top
performer, and per-pick career points, draft-year position rank, and ownership state.
Selecting a player opens the full career profile.

The shared Hall of Fame export precomputes `player_career_stats` across every archived
season. Live ownership, roster status, and transactions still come from `data.json`, so
post-action refreshes do not wait for a historical rebuild.

The player profile includes:
- Career fantasy points across all seasons they appeared
- Whether they're still on the original team vs. traded/dropped
- Season-by-season points, owners, games, starts, and position rank
- Original draft position and drafting team
- Current owner and active/taxi/free-agent status
- Awards and completed transaction history
