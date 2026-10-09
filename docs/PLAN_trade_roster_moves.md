# Plan: Roster moves attached to trades (unbalanced trades without commissioner help)

## Context

The constitution allows unbalanced trades, but the receiving roster has to have room ("a roster spot must be available or cleared"). Today, `_apply_trade_assets` (`api/transaction.py:1124`) checks the final rosters and rejects the trade if a team is over a limit. The only way to make room is to release players *before* accepting. That has two gaps:

1. **Taxi conflicts can't be cleared in advance.** A team can't activate a player it doesn't own yet. The normal release action only works on active players (`api/transaction.py:680`), so a team can't clear its own taxi squad either. The GSA↔WJK trade (b9e5ac99) needed commissioner edits because Hubbard arriving on WJK's taxi squad collided with Gainwell.
2. **Releasing early is risky.** If the trade then fails, the release can't be undone.

There is also a timing bug. Gainwell was a taxi player on both sides, so he could never score, but because his game had started he pushed the whole trade to Week 6 (`route_roster_move`, `api/transaction.py:468`).

**Goal:** each side of a trade can attach its own roster moves: **release** players (active or taxi) and **activate** taxi players (its own or incoming). The moves run in the same atomic write as the trade, before roster limits are checked. Taxi players who stay on a taxi squad no longer cause deferral. (Both decisions confirmed with the user.)

Constitution guardrail: players can never be *sent down* to taxi (ROADMAP P2.2), so there is no "demote" move.

## Data model

New optional field on a trade in `data/pending_trades.json`:

```json
"roster_moves": {
  "GSA": {"release": ["Jonathan Brooks"], "activate": []},
  "WJK": {"release": [], "activate": ["Chuba Hubbard"]}
}
```

- The proposer's entry is set in `propose_trade` (new `roster_moves` payload field).
- The partner's entry arrives with `respond_trade` when `accept: true`. It is stored on the trade when the trade is accepted.
- `qpfl/schemas.py` `Trade` already has `extra='allow'`, so the schema needs no change. Optionally add a typed model for validation.

## Backend: `api/transaction.py`

1. **`_valid_roster_moves(moves, team)`**: structural validation of the payload: dict of `release`/`activate` lists of non-empty strings, no duplicates, no name in both lists, and a small cap on length. Model it on `_trade_asset_error` / `_valid_trade_conditions` (~line 1091–1113).

2. **`_apply_trade_assets(..., roster_moves=None)`**: after `new_rosters` is built (~line 1192) and **before** the violations loop, apply each team's moves:
   - **release:** the player must have been on that team *before* the trade and must not be in the outgoing list. Remove him from active or taxi. Otherwise raise a 400 such as `"{name} is not on {team}'s roster"`.
   - **activate:** the player must be on the team's *post-trade* taxi squad (own or incoming). Move him to active and drop the `taxi` flag (same as `set_roster_and_taxi` / `handle_taxi_activation`).
   - Return `released` / `activated` player dicts per team in the details, for logging and lineups.
   - The existing checks (position limits, ≤4 taxi, one taxi per position) then run on the final state. The error text should mention the new option: "…release or activate a player in the trade".
   - Pass `roster_moves` through in both callers inside `accept_trade` (live rosters ~line 1514 and the frozen-week lambda ~line 1529) so the frozen Week N roster gets the same moves.

3. **`handle_propose_trade`**: accept and validate `roster_moves` for the proposer only, and store it as `trade['roster_moves'] = {team: moves}`. Run a dry-run `_apply_trade_assets` on a deepcopy of the current rosters (picks skipped) and fail only if **the proposer's** team would break a limit. The partner's overflow is theirs to solve at accept time. This needs a rosters read, which propose doesn't do today; use `github_get_file('data/rosters.json')`.

4. **`handle_respond_trade` (accept path)**: read `roster_moves` from the payload, validate it for `team` (the partner), and merge it into `trade['roster_moves'][partner]` inside `accept_trade` before applying. The proposer's stored moves are re-checked at accept, and a stale one fails clearly (e.g. the proposer already released that player).

5. **Deferral fix**: replace the "every traded player's NFL team" list (~line 1527) with `_trade_scoring_nfl_teams(details)`. It includes only players who were active before **or** active after on either side: active traded players, activated players, and released *active* players. Taxi→taxi traded players and released taxi players are excluded. (Optional: apply the same filter to `handle_release` for a taxi release once it exists, but that isn't needed here.)

6. **Lineups**: add each team's released players to `outgoing_by_team` in `_invalidate_trade_lineups` (`api/transaction.py:1341`) so they leave future lineups.

7. **Stale pending trades**: extend `_cancel_stale_pending_trades` (`api/transaction.py:1296`) to also cancel a pending trade when the proposer's `roster_moves.release` names a player the proposer no longer owns. Mirror this in `qpfl/integrity.py:check_pending_trades`.

8. **Transaction log**: add `roster_moves: {team: {released: [player dicts], activated: [player dicts]}}` to the `'trade'` audit event (~line 1585) and to the accept response message ("…; WJK released X, activated Y").

## Frontend: `web/app.js`

- **Proposal** (`renderTradeTab` / `submitTradeProposal`, ~line 13676 / 14199): add an "Make room on your roster (optional)" section under the trade builder. It has two picker lists: *Release* (your active and taxi players not being traded away) and *Activate* (your taxi players plus incoming taxi players). Store the choices in `manageState.tradeRosterMoves`. Show them in the confirm modal and send them in `executeTradeProposal` as `roster_moves`. Reset them along with the other trade state.
- **Client-side preview**: a small `projectTradeRoster(team, trade, moves)` helper computes the post-trade per-position counts and taxi checks from `getTeamData()`, using the same limits as `ROSTER_SLOTS` (already mirrored in the frontend; reuse that constant). The UI shows something like "WJK would have 2 taxi RBs (max 1)" live. This is advisory; the server stays authoritative.
- **Pending trade card** (`renderPendingTrades`, ~line 14305): list the proposer's attached moves under their side ("GSA will release: …").
- **Accept dialog** (`respondToTrade`, ~line 14433): if the projected partner roster breaks a rule, show inline Release/Activate pickers in the confirm modal content. Disable "Accept Trade" until the preview is clean. Pass `roster_moves` through `executeTradeResponse`. `showConfirmModal` (~line 15182) takes HTML content; it may need an `onRender` hook to wire the pickers, so check before building.
- **Transactions view**: render the new `roster_moves` on trade entries where trade details expand (near `normalizedTradeSides`, ~line 6876).
- README §Trades: document the option.

## Tests

Extend `tests/test_api.py` (near `test_apply_trade_assets_rejects_roster_overflow` :844, `test_apply_trade_assets_preserves_taxi_status` :1930, `test_trade_accept_swaps_rosters_and_marks_execution_done` :2145) and `tests/test_roster_moves.py`:
- The GSA/WJK scenario: incoming taxi RB collides; the partner activates the incoming RB and releases an active RB → succeeds, final rosters correct.
- The same trade without moves → 400 that mentions the fix.
- The proposer releases a taxi player to make taxi room → succeeds.
- Release of a player being traded away, or not owned → 400. Activate of a non-taxi player → 400.
- Stale proposer move: the proposer released the player separately before acceptance → the pending trade is auto-cancelled, and if accepted anyway → 409/400.
- Deferral: a taxi→taxi player whose game has kicked off does **not** defer. An active traded player whose game has kicked off still defers. An activated player whose game has kicked off defers.
- Frozen-week path: moves are applied to the snapshot rosters too.
- Released players are removed from future lineups.
- Propose dry-run rejects the proposer's own overflow but not the partner's.

## Verification

1. `uv run pytest -q`. Expect everything to pass except the existing unrelated failure `test_matchup_projections_ui.py::test_matchup_highlight_covers_the_full_card_instead_of_one_team`.
2. `uv run python -m qpfl.data_validation` (or the integrity check CI runs) against `data/` to confirm the schema and integrity checks pass with a trade that carries `roster_moves`.
3. Vercel preview deploy (`vercel.json`). Using two test team logins, propose a trade like b9e5ac99 with a proposer-side move, accept with a partner-side activation and release, then confirm `data/rosters.json`, the week snapshot, the lineups and the transaction log on the preview branch. Also run through the UI preview and the disabled-accept state in the browser.
