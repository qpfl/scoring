# QPFL API Documentation

Version: 2026.1
Base URL: `https://your-vercel-app.vercel.app/api/`

All API endpoints are deployed as Vercel serverless functions and handle CORS automatically.

---

## Table of Contents

- [Authentication](#authentication)
- [Lineup API](#lineup-api)
- [Transaction API](#transaction-api)
- [Team Name API](#team-name-api)
- [Error Codes](#error-codes)
- [Rate Limits](#rate-limits)

---

## Authentication

All endpoints require team-based authentication using passwords stored as environment variables on Vercel.

### Password Format
Team passwords are stored as `TEAM_PASSWORD_{TEAM_ABBREV}` environment variables (e.g., `TEAM_PASSWORD_GSA`).

### Authentication Flow
```json
{
  "team": "GSA",
  "password": "your-team-password"
}
```

**Authentication Errors:**
- `400`: Missing team or password
- `401`: Invalid password
- `500`: Team not configured

---

## Lineup API

**Endpoint:** `/api/lineup`

Submit or validate weekly lineup submissions.

### 1. Validate Password

Check if a team password is valid without submitting a lineup.

**Request:**
```http
POST /api/lineup
Content-Type: application/json

{
  "action": "validate",
  "team": "GSA",
  "password": "your-password"
}
```

**Response (200):**
```json
{
  "success": true,
  "message": "Password valid"
}
```

---

### 2. Submit Lineup

Submit starters for a specific week.

**Request:**
```http
POST /api/lineup
Content-Type: application/json

{
  "team": "GSA",
  "password": "your-password",
  "week": 7,
  "starters": {
    "QB": ["Patrick Mahomes"],
    "RB": ["Derrick Henry", "Saquon Barkley"],
    "WR": ["Justin Jefferson", "Tyreek Hill", "CeeDee Lamb"],
    "TE": ["Travis Kelce"],
    "K": ["Justin Tucker"],
    "D/ST": ["San Francisco"],
    "HC": ["Andy Reid"],
    "OL": ["Philadelphia"]
  },
  "locked_players": ["Patrick Mahomes"],
  "comment": "Optional comment about lineup strategy"
}
```

**Request Fields:**
- `team` (string, required): Team abbreviation
- `password` (string, required): Team password
- `week` (integer, required): Week number (1-17)
- `starters` (object, required): Players to start by position
- `locked_players` (array, optional): Players whose lineup status cannot be changed (merged with existing starters if already locked)
- `comment` (string, optional): Optional comment about lineup

**Starter Limits (Validated):**
- QB: 1
- RB: 2
- WR: 3
- TE: 1
- K: 1
- D/ST: 1
- HC: 1
- OL: 1

**Response (200):**
```json
{
  "success": true,
  "message": "Lineup updated successfully"
}
```

**Validation Errors:**
- `400`: Missing required fields, invalid position, or too many starters for a position
- `401`: Invalid password
- `500`: Server error or GitHub API failure

**Behavior Notes:**
- If `locked_players` is provided and players are already locked in the current lineup, those locked players will be preserved and merged with new starters
- Lineup includes automatic timestamp (`submitted_at`) in ISO 8601 format
- Handles concurrent submissions with retry logic (3 retries with exponential backoff)

---

### 3. Test Endpoint

**Request:**
```http
GET /api/lineup
```

**Response (200):**
```json
{
  "status": "API is running",
  "method": "GET"
}
```

---

## Transaction API

**Endpoint:** `/api/transaction`

Handle all roster transactions including trades, taxi squad activations, FA pickups, and trade blocks.

### Configuration

- **Trade Deadline:** Week 12 (trading blocked weeks 12-17, open before and after)
- **Current Season:** 2026

---

### 1. Validate Password

**Request:**
```http
POST /api/transaction
Content-Type: application/json

{
  "action": "validate",
  "team": "GSA",
  "password": "your-password"
}
```

**Response (200):**
```json
{
  "success": true
}
```

---

### 2. Taxi Squad Activation

Activate a player from taxi squad by releasing an active roster player.

**Request:**
```http
POST /api/transaction
Content-Type: application/json

{
  "action": "taxi_activate",
  "team": "GSA",
  "password": "your-password",
  "player_to_activate": "Rookie Name",
  "player_to_release": "Veteran Name",
  "week": 7
}
```

**Request Fields:**
- `action`: "taxi_activate"
- `team` (string, required): Team abbreviation
- `password` (string, required): Team password
- `player_to_activate` (string, required): Player name from taxi squad
- `player_to_release` (string, required): Active roster player to release
- `week` (integer, required): Current week (or 0/18+ for offseason)

**Validation:**
- Player to activate must be on taxi squad
- Player to release must be on active roster
- Players must be same position

**Response (200):**
```json
{
  "success": true,
  "message": "Activated Rookie Name, released Veteran Name"
}
```

**Transaction Log Entry:**
```json
{
  "type": "taxi_activation",
  "team": "GSA",
  "activated": {
    "name": "Rookie Name",
    "position": "RB",
    "nfl_team": "KC"
  },
  "released": {
    "name": "Veteran Name",
    "position": "RB",
    "nfl_team": "SF"
  },
  "week": 7,
  "season": 2026,
  "timestamp": "2026-10-25T14:30:00Z"
}
```

---

### 3. FA Pool Activation

Add a player from the FA pool by releasing an active roster player.

**Request:**
```http
POST /api/transaction
Content-Type: application/json

{
  "action": "fa_activate",
  "team": "GSA",
  "password": "your-password",
  "player_to_add": "FA Player Name",
  "player_to_release": "Roster Player Name",
  "week": 7
}
```

**Request Fields:**
- `action`: "fa_activate"
- `team` (string, required): Team abbreviation
- `password` (string, required): Team password
- `player_to_add` (string, required): Player name from FA pool
- `player_to_release` (string, required): Active roster player to release
- `week` (integer, required): Current week

**Validation:**
- Player to add must be available in FA pool
- Player to release must be on active roster
- Players must be same position

**Response (200):**
```json
{
  "success": true,
  "message": "Added FA Player Name from FA pool, released Roster Player Name"
}
```

**Side Effects:**
- Marks FA player as unavailable in `fa_pool.json`
- Records which team activated the player and in which week

---

### 4. Propose Trade

Propose a trade with another team (players and/or draft picks).

**Request:**
```http
POST /api/transaction
Content-Type: application/json

{
  "action": "propose_trade",
  "team": "GSA",
  "password": "your-password",
  "trade_partner": "CWR",
  "give_players": ["Player A", "Player B"],
  "give_picks": ["2027-R3-GSA"],
  "receive_players": ["Player C"],
  "receive_picks": ["2027-R1-CWR"],
  "current_week": 7,
  "conditions": {
    "player_must_score": "20+ points"
  },
  "comment": "This trade helps both our teams"
}
```

**Request Fields:**
- `action`: "propose_trade"
- `team` (string, required): Proposer team abbreviation
- `password` (string, required): Proposer password
- `trade_partner` (string, required): Partner team abbreviation
- `give_players` (array, optional): Players proposer gives away
- `give_picks` (array, optional): Draft picks proposer gives away (format: "YYYY-RX-ORIG")
- `receive_players` (array, optional): Players proposer receives
- `receive_picks` (array, optional): Draft picks proposer receives
- `current_week` (integer, optional): Current week for trade deadline validation
- `conditions` (object, optional): Trade conditions (not enforced by API)
- `comment` (string, optional): Optional comment about trade

**Draft Pick Format:**
- `"2027-R3-GSA"` = 2027 3rd round pick originally owned by GSA

**Validation:**
- Trade deadline: Blocked from week 12 through week 17
- Must include at least one player or pick
- Must specify trade partner

**Response (200):**
```json
{
  "success": true,
  "message": "Trade proposed to CWR",
  "trade_id": "a3f5b8c1"
}
```

**Trade Deadline Error (400):**
```json
{
  "error": "Trade deadline has passed (Week 12)"
}
```

---

### 5. Respond to Trade

Accept or reject a trade proposal.

**Request:**
```http
POST /api/transaction
Content-Type: application/json

{
  "action": "respond_trade",
  "team": "CWR",
  "password": "your-password",
  "trade_id": "a3f5b8c1",
  "accept": true
}
```

**Request Fields:**
- `action`: "respond_trade"
- `team` (string, required): Responding team abbreviation
- `password` (string, required): Responding team password
- `trade_id` (string, required): Trade ID to respond to
- `accept` (boolean, required): true to accept, false to reject

**Validation:**
- Only the trade partner can respond
- Trade must be in "pending" status
- Cannot respond to own trade

**Response (200 - Accepted):**
```json
{
  "success": true,
  "message": "Trade accepted and executed"
}
```

**Response (200 - Rejected):**
```json
{
  "success": true,
  "message": "Trade rejected"
}
```

**Side Effects (if accepted):**
- Players swapped between teams in `rosters.json`
- Draft pick ownership updated in `draft_picks.json`
- Trade logged in `transaction_log.json`
- Trade status changed to "accepted" in `pending_trades.json`

**Errors:**
- `400`: Trade not found or already processed
- `403`: You are not the trade partner

---

### 6. Cancel Trade

Cancel a trade proposal (proposer only).

**Request:**
```http
POST /api/transaction
Content-Type: application/json

{
  "action": "cancel_trade",
  "team": "GSA",
  "password": "your-password",
  "trade_id": "a3f5b8c1"
}
```

**Request Fields:**
- `action`: "cancel_trade"
- `team` (string, required): Proposer team abbreviation
- `password` (string, required): Proposer password
- `trade_id` (string, required): Trade ID to cancel

**Validation:**
- Only the proposer can cancel
- Trade must be in "pending" status

**Response (200):**
```json
{
  "success": true,
  "message": "Trade cancelled"
}
```

**Errors:**
- `400`: Trade not found or already processed
- `403`: Only the proposer can cancel this trade

---

### 7. Save Trade Block

Update your team's trade block (what you're seeking/offering).

**Request:**
```http
POST /api/transaction
Content-Type: application/json

{
  "action": "save_tradeblock",
  "team": "GSA",
  "password": "your-password",
  "seeking": ["QB", "RB"],
  "trading_away": ["WR"],
  "players_available": ["Player A", "Player B"],
  "notes": "Looking for a QB1. Open to most offers."
}
```

**Request Fields:**
- `action`: "save_tradeblock"
- `team` (string, required): Team abbreviation
- `password` (string, required): Team password
- `seeking` (array, optional): Positions seeking
- `trading_away` (array, optional): Positions willing to trade
- `players_available` (array, optional): Specific players available
- `notes` (string, optional): Additional notes

**Response (200):**
```json
{
  "success": true,
  "message": "Trade block saved"
}
```

---

### 8. Test Endpoint

**Request:**
```http
GET /api/transaction
```

**Response (200):**
```json
{
  "status": "Transaction API is running"
}
```

---

## Team Name API

**Endpoint:** `/api/team-name`

Change your team name for a specific week forward.

### Change Team Name

**Request:**
```http
POST /api/team-name
Content-Type: application/json

{
  "team": "GSA",
  "password": "your-password",
  "newName": "The New Team Name",
  "week": 8
}
```

**Request Fields:**
- `team` (string, required): Team abbreviation
- `password` (string, required): Team password
- `newName` (string, required): New team name (max 50 characters)
- `week` (integer, optional): Week when name takes effect (default: 1)

**Validation:**
- Team name must be 50 characters or less
- Password must be valid

**Response (200):**
```json
{
  "success": true,
  "message": "Team name updated successfully"
}
```

**Behavior Notes:**
- Team name changes are effective starting from the specified week
- Historical weeks keep the old name
- Previous name changes for the same week are overwritten
- Names are stored in `data/team_names.json` with effective week tracking

**Example Usage:**
```json
// Week 1-7: "Original Name"
// Week 8+:   "The New Team Name" (after this API call with week=8)
```

---

## Error Codes

### HTTP Status Codes

| Code | Meaning | Common Causes |
|------|---------|---------------|
| 200 | Success | Request completed successfully |
| 400 | Bad Request | Missing fields, invalid data, validation errors |
| 401 | Unauthorized | Invalid password |
| 403 | Forbidden | Not authorized to perform this action (e.g., cancel another team's trade) |
| 500 | Server Error | GitHub API failure, configuration error, unexpected exception |

### Common Error Responses

**Missing Authentication:**
```json
{
  "error": "Missing team or password"
}
```

**Invalid Password:**
```json
{
  "error": "Invalid password"
}
```

**Team Not Configured:**
```json
{
  "error": "Team not configured"
}
```

**Validation Failure:**
```json
{
  "error": "Player A is not on your active roster"
}
```

**Server Configuration Error:**
```json
{
  "error": "Server configuration error"
}
```

---

## Rate Limits

### GitHub API Rate Limits
- **Authenticated:** 5,000 requests/hour
- **Per endpoint:** No specific limit

### Concurrent Update Handling
All endpoints that modify data use retry logic with exponential backoff:
- **Max retries:** 3
- **Backoff:** 0.5s, 1.0s, 1.5s
- **Conflict resolution:** Fetches latest state and retries on 409 Conflict

This ensures concurrent submissions (e.g., multiple teams submitting lineups simultaneously) are handled correctly without data loss.

---

## Data Persistence

All API calls write directly to GitHub repository files:
- `data/lineups/2025/week_N.json` - Weekly lineups
- `data/rosters.json` - Team rosters
- `data/pending_trades.json` - Pending trade proposals
- `data/transaction_log.json` - Complete transaction history
- `data/fa_pool.json` - Free agent pool
- `data/draft_picks.json` - Draft pick ownership
- `data/trade_blocks.json` - Trade block preferences
- `data/team_names.json` - Team name history

Git serves as both version control and database, providing:
- Full audit trail of all changes
- Ability to rollback mistakes
- Transparent history for all league members

---

## Best Practices

### Authentication
- Never commit passwords to code
- Store passwords securely on the client side
- Use HTTPS for all API calls

### Error Handling
```javascript
try {
  const response = await fetch('/api/lineup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(lineupData)
  });

  const data = await response.json();

  if (!response.ok) {
    console.error('API error:', data.error);
    // Handle specific error codes
    if (response.status === 401) {
      // Invalid password
    }
  } else {
    console.log('Success:', data.message);
  }
} catch (error) {
  console.error('Network error:', error);
}
```

### Retries
The API includes built-in retry logic for concurrent updates (409 Conflicts). Your client does not need to implement retries for conflicts, but should handle network errors and other failures.

---

## Changelog

### 2026.1 (Current)
- Initial API documentation
- All three endpoints documented
- Comprehensive request/response examples
- Error code reference
