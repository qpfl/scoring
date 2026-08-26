# QPFL API

The six production endpoints are Vercel Python functions. The canonical site is
`https://qpfl-scoring.vercel.app`; the GitHub Pages mirror uses the same Vercel API base.

| Endpoint | Purpose | Public actions | Authenticated actions |
|---|---|---|---|
| `/api/lineup` | Weekly lineups | `GET` health | `validate`, `submit` |
| `/api/transaction` | Rosters, trades, trade blocks, commissioner changes | `GET` health | All POST actions |
| `/api/rule-changes` | Rule proposals, comments, and votes | `GET?action=proposals` | `propose`, `comment`, `vote` |
| `/api/nfl-draft` | NFL Draft Challenge | `get_state` returns public state | `validate`, `submit`, `clear`; credentials reveal the caller's saved entry |
| `/api/team-name` | Season-aware franchise names | `GET` health | Rename the authenticated team |
| `/api/team-avatar` | Franchise avatar uploads | `GET` health | Upload the authenticated team's avatar |

## Request contract

POST bodies must be JSON with an accurate `Content-Length`. Ordinary bodies are limited to
64 KiB; the avatar endpoint allows 3 MiB so a validated image of at most 2 MiB can be base64
encoded. Missing or malformed lengths, unsupported content types, oversized bodies, and
disallowed origins are rejected before authentication or GitHub access.

Browser origins are limited to:

- `https://qpfl.org`
- `https://www.qpfl.org`
- `https://qpfl-scoring.vercel.app`
- `https://qpfl.github.io`
- preview origins explicitly listed in `QPFL_ALLOWED_PREVIEW_ORIGINS`

Requests without an `Origin` remain available to authenticated command-line and server
clients. Responses echo only an allowed origin and include `Vary: Origin`. Team passwords are
Vercel environment variables named `TEAM_PASSWORD_{TEAM}`. The commissioner uses the GSA
credential; the legacy `ADMIN` identity remains accepted only where explicitly implemented.
Comparisons use constant-time password checks.

The browser stores a validated manager login in `sessionStorage`, not `localStorage`. A refresh
in the same tab keeps the login; closing the browser session requires signing in again. Never
log, persist, or commit a password.

Unexpected failures return a generic message and a request ID. Raw exception text, GitHub
response bodies, credentials, and tokens are never part of the client response. Use the request
ID to correlate a failure with redacted server logs.

## Lineup API

Validate a credential:

```json
{
  "action": "validate",
  "team": "GSA",
  "password": "..."
}
```

Submit a lineup:

```json
{
  "action": "submit",
  "team": "GSA",
  "password": "...",
  "week": 1,
  "starters": {
    "QB": ["Josh Allen"],
    "RB": ["Breece Hall", "Saquon Barkley"],
    "WR": ["Justin Jefferson", "CeeDee Lamb"],
    "TE": ["Sam LaPorta"],
    "K": ["Brandon Aubrey"],
    "D/ST": ["Buffalo Bills"],
    "HC": ["Sean McDermott"],
    "OL": ["Philadelphia Eagles"]
  },
  "comment": "Optional, at most 500 characters"
}
```

Limits are 1 QB, 2 RB, 2 WR, 1 TE, 1 K, 1 D/ST, 1 HC, and 1 OL. The server loads the
authoritative current season, lineup week, schedule, kickoff map, existing lineup, and roster.
It rejects past weeks, invalid scheduled weeks, non-roster or taxi starters, excess starters,
and any attempt to add or remove a player whose game has kicked off. Future scheduled weeks are
allowed. Client-supplied lock metadata is ignored. If authoritative context cannot be loaded,
the request fails closed with `503`.

## Transaction API

POST `action` values are:

- `validate`
- `taxi_activate`
- `fa_activate`
- `release`
- `propose_trade`
- `respond_trade`
- `cancel_trade`
- `set_depth_chart`
- `save_tradeblock`
- `admin_adjust`

Commissioner `admin_adjust` supports workbook export, audit review, season status/offseason
changes, player add/release, trade reversal, conditional-pick resolution, and score adjustment.
See the browser commissioner tools for the exact payload builder for each operation.

Mutations that change more than one JSON document use one Git commit created through GitHub's
Git Data API. The branch ref advances only if its expected head is still current; a head conflict
re-reads all inputs and retries the entire pure mutation. Roster/pick/trade state and its required
audit record therefore become visible together or not at all. Each request carries an operation
ID so a retry after an ambiguous response can recognize an already-committed operation. Invalid
authorization, validation, malformed data, and rate-limit responses are not retried as conflicts.

## Team name API

```json
{
  "team": "GSA",
  "password": "...",
  "newName": "A New Franchise Name"
}
```

The server derives the season and effective week from repository context; it does not trust a
client-supplied week. Names are trimmed, length- and character-validated, stored as canonical
season/week history, and resolved point-in-time during export so old weeks retain their old name.

## Team avatar API

```json
{
  "team": "GSA",
  "password": "...",
  "season": 2026,
  "week": 1,
  "imageData": "data:image/png;base64,..."
}
```

Only supported image data URLs are accepted. The decoded image must pass type, dimension, and
size validation before it is re-encoded and committed. The API derives a stable team slug for
the resulting asset.

## NFL Draft Challenge API

`get_state` is readable without credentials. Valid credentials additionally identify the caller
and expose that team's private saved entry. `submit` validates the configured year, lock time,
pick count, and payload. `clear` removes the authenticated team's entry. Challenge configuration
comes from `data/nfl_draft_challenges/{year}_config.json`.

## Rule changes API

`GET /api/rule-changes?action=proposals` returns proposals. Authenticated POST actions create a
proposal, comment, or vote. Writes use optimistic conflict retry; callers should surface a final
conflict or service failure instead of blindly replaying an authenticated action.

## Status codes

| Status | Meaning |
|---|---|
| `200` | Success |
| `204` | Allowed preflight |
| `400` | Invalid payload or action |
| `401` | Invalid credential |
| `403` | Disallowed origin or action |
| `409` | State changed or action no longer applies |
| `411` | Missing content length |
| `413` | Body too large |
| `415` | Body is not JSON |
| `429` | Provider rate limit; honor `Retry-After` |
| `500` | Server configuration or unexpected failure |
| `503` | Required repository/upstream state is unavailable or conflicts persisted |

Clients must not implement automatic retries for authenticated mutations. The server retries
only safe branch-head conflicts and supplies idempotency protection for atomic operations.
