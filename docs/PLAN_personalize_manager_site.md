# Personalize the site for the logged-in manager

## Context

QPFL's site treats every visitor identically. A manager who logs in gets a "My Team"
dashboard under `#manage`, but the rest of the site gives them no cue about which of
the ten teams is theirs. Finding your matchup means scanning five cards; finding your
roster in the all-rosters spreadsheet means scanning ten columns; spotting your
players in the QB leaderboard means reading every row.

The site already knows who you are: `manageState.team` holds the logged-in team's
abbreviation (`'GSA'`, `'S/T'`, …), restored from `localStorage` on boot
(`web/app.js:10278-10313`, used near `:10433`). Nothing outside the manage view
consumes it.

**Goal:** when logged in, your team leads every list it sensibly can, and you and
your players are visibly marked everywhere they appear. When logged out, every page
renders exactly as it does today.

Decisions already made:
- Applies to **all seasons and weeks**, including historical archives.
- Highlight style: **subtle accent tint + 3px left accent bar**. No badge.
- **No preference toggle.** Always on when logged in.
- Hall of Fame free-text records: text-match now, **plus a follow-up** to emit
  structured team fields from the exporter (out of scope for this change).
- Draft picks: **follow franchise lineage** via the existing `draftOwnerTeamCode()`.
- Compare Teams: preselect you on the left **and this week's opponent** on the right.

This plan's file/function references were verified against the current `web/app.js`
(line numbers below are current as of this pass; expect them to drift a few lines by
the time of implementation — always re-locate by function name, not line number).

## Architecture

`web/` is a vanilla-JS SPA: `index.html` shell + a single ~15k-line `app.js` +
`styles.css`. Views render by string-building HTML into containers, dispatched
through `VIEW_RENDERERS` (`app.js:993`) and cached by the `viewFresh` set
(`app.js:1116`). All changes land in `web/app.js` and `web/styles.css` — no data,
API, or Python changes in this pass.

## Step 1 — Shared helpers

Add near `getTeamName()` (`web/app.js:8671`), the existing home for team-identity
helpers. Function declarations hoist, so earlier call sites are fine.

```js
// The logged-in manager's team abbreviation, or null when signed out.
function myTeamAbbrev() {
    return (manageState && manageState.team) || null;
}

// Class hook marking a row/card/column as belonging to the logged-in manager.
function myTeamClass(abbrev) {
    return abbrev && abbrev === myTeamAbbrev() ? 'is-my-team' : '';
}

// Stable reorder floating the logged-in manager's entries to the front.
// getAbbrev may return one abbrev or an array (matchups have two sides).
function floatMyTeam(items, getAbbrev) {
    const me = myTeamAbbrev();
    if (!me) return items;
    const isMine = item => [].concat(getAbbrev(item)).includes(me);
    const mine = items.filter(isMine);
    if (!mine.length || mine.length === items.length) return items;
    return [...mine, ...items.filter(item => !isMine(item))];
}
```

Both helpers no-op when signed out, so every call site below is a pure pass-through
for logged-out visitors. That property is what keeps the blast radius small — and
it is the single most important thing to verify.

**Franchise-lineage variant.** Historical views identify teams by owner name, not
abbrev, and retired codes (`RCP`, `MPA`, `JRW`, `JDK`) map to today's teams through
`draftOwnerTeamCode()` (`app.js:6969`) and `ownerTeamCode()` (`app.js:1978`). Add:

```js
// True when an owner label or legacy code resolves to the logged-in franchise.
// Used by Hall of Fame and draft history, where teams are named, not coded.
function isMyFranchise(ownerLabel, draft) {
    const me = myTeamAbbrev();
    if (!me || !ownerLabel) return false;
    const code = draft ? draftOwnerTeamCode(ownerLabel, draft) : ownerTeamCode(ownerLabel);
    return code === me;
}
```

## Step 2 — Re-render on login/logout

Highlighting must appear the moment you log in. The `viewFresh` cache already has an
established invalidation pattern (near `app.js:10257` and `:11375`).

Add `refreshPersonalization()`: clear `viewFresh`, then re-render the active view via
`ensureViewRendered(getActiveView())`. Call it from:
- `performLogin()` (`app.js:10436`) — **both** success paths, the normal one and the
  localhost-fallback branch at `:10463`.
- `performLogout()` (`app.js:10475`).

On logout it must also clear the preselections from Steps 4 and 6 (`currentTeam`,
`compareTeam1`/`compareTeam2`) so the next render doesn't strand you on someone
else's team.

## Step 3 — Matchups: your matchup first, every week

`renderMatchups()` (`app.js:2702`) has two branches; both get the same treatment.

**Scheduled/pre-game branch** — `team1`/`team2` are bare abbrev strings.
**Scored/live branch** — they are objects with `.abbrev`.

- Non-playoff weeks: wrap the matchup array in
  `floatMyTeam(..., m => [m.team1, m.team2])` (or `m => [m.team1.abbrev, m.team2.abbrev]`).
- Playoff weeks: float **within each bracket's array** after the `matchupsByBracket`
  grouping (`app.js:2725-2732`), leaving `bracketOrder` untouched. Bracket headers are
  meaningful structure; reordering them would confuse more than help.
- Compute `topHalfSet` via `computeTopHalfSet(regularMatchups)` (defined at `:2551`,
  called near `:2879`) **before** reordering.
- `matchupIdx` is assigned during the map, so `roster-${idx}` panel IDs and their
  expand handlers stay consistent under the new order.

**Card markup** — `renderScheduledMatchupCard()` (`:2628`) and the inline scored card
(near `:2959`): add `myTeamClass()` to the `<div class="matchup-card ...">` when either
side is yours, and to the individual `<div class="team">` / `<div class="team right">`
blocks so the correct side is marked.

## Step 4 — Rosters page: your team first and preselected

**All-rosters spreadsheet** — `renderAllRosters()` (`app.js:5561`). The single
ordering point is the `teamAbbrevs` array at `:5598`. Wrap it in
`floatMyTeam(teamAbbrevs, a => a)`. That one change reorders the spreadsheet columns,
the `allRostersSearchEntries` index (declared `:5466`, populated `:5617`), and the
column-toggle buttons together, since all three derive from `teamAbbrevs`. Add
`myTeamClass()` to your column header cell and toggle button.

**Team hub selector and default tab** — `renderTeams()` (`app.js:4409`). Float the
local `teams` array before rendering the `.team-btn` row (`:4422`). Because the
existing default is `currentTeam = teams[0].abbrev` when the URL names no team
(`:4415`), floating alone makes your team the default across the **Roster, Hall of
Fame, and Activity** subviews — they all read the same module-level `currentTeam`
(`app.js:4326`). No extra branch needed.

**A URL that names a team must still win.** `#teams/history/CWR` has to open CWR.
The existing guard at `:4415` only reassigns `currentTeam` when it is unset or
invalid, so this already holds — confirm it during verification rather than adding
logic.

Add `myTeamClass(team.abbrev)` to each `.team-btn`; it composes with `active`.

## Step 5 — Player stats: your players highlighted

This is the one place we highlight **players**, not teams. It is cheap: stat-leader
entries already carry `fantasy_team`, which is the owning abbrev, set during
aggregation in `getStatsLeaders()` (a single function at `app.js:8153`).

In `renderStatsLeaders()` (`app.js:8248`), add `${myTeamClass(player.fantasy_team)}`
to the `<div class="stats-leader-row ${rankClass}">` (`:8317`). GSA then sees Caleb
Williams, Mahomes, and Willis tinted in the QB card, and the same in every other
position card, in both the "All" top-5 view and the expanded single-position view.

No new lookup table is needed — do **not** build a name→team map from `data.rosters`,
since `fantasy_team` already tracks ownership through mid-season moves.

Apply the same class in `renderComparePlayer()` (`:8008`) and the all-rosters player
cells where the owning column is yours.

## Step 6 — Compare Teams: preselect both sides

`initCompareView()` (`app.js:7825`) with module-level `compareTeam1` / `compareTeam2`
(`:7822-7823`), both defaulting to `''`.

When both are empty **and** no `team1`/`team2` route param is present, seed
`compareTeam1 = myTeamAbbrev()` and `compareTeam2` = this week's opponent, found by
scanning `data.schedule` (or `data.weeks`) for `currentWeek` for the matchup
containing your abbrev and taking the other side. Extract that lookup as a small
`myOpponentForWeek(week)` helper — Step 3 and the existing `myTeamActivity` dashboard
code (`app.js:11717`) both do the same scan, so put it somewhere all three can use it.

Guard for the bye/absent case: if no opponent is found, leave the right select empty
and let the existing "Select two teams" empty state render. Route params must
continue to win over the preselect.

## Step 7 — Transactions: every transaction involving you

`renderTransactionItem()` (`app.js:6616`) has four branches, each emitting a
`.transaction-item`, and each resolving team codes differently:
- new trade → `tx.proposer`, `tx.partner`
- old parsed trade → `tradeSideIdentity(team.name, tx).code` per side
- old unparsed trade → `draftOwnerTeamCode(tx.team, ...)`
- non-trade → the `teamCode` computed at `:6677`

Rather than duplicating the logic, add one `transactionTeamCodes(tx)` helper that
returns the set of abbrevs involved, reusing those same resolvers, and apply
`myTeamClass` from it at the top of the function. Each branch then just interpolates
the precomputed class into its `.transaction-item` div.

**Name collision:** `transaction-item-highlight` already exists as a *transient*
deep-link flash, added then removed after 1.5s (`app.js:14812`, `styles.css:5715`).
Keep `is-my-team` fully separate — do not reuse or extend that class, and check the
two render legibly when they land on the same element.

## Step 8 — Drafts: every pick you made

`renderHistoricalDraftPick()` (`app.js:7559`) already computes
`originalOwner = draftTeamCode(pick.team, draft)` (`draftTeamCode` defined at
`:7039`, distinct from `draftOwnerTeamCode`). Add `${myTeamClass(originalOwner)}` to
the `<div class="draft-pick ...">`. Because `draftTeamCode` / `draftOwnerTeamCode`
encode the franchise lineage, this lights up your picks under retired codes too, as
decided.

Also cover the upcoming-draft branch (near `:7798`), keyed on `pick.current_owner`,
and `renderPickTracker()` (`:7647`), where each `.pick-tracker-column` is one team.

Watch the ambiguous-owner cases `draftOwnerDisplayLabel()` calls out explicitly
(`:6990`): "Connor" resolves to **CGK or CWR** depending on year. Rely on
`draftOwnerTeamCode(owner, draft)` with the draft passed in — it disambiguates by
year — never on a bare name comparison.

## Step 9 — Hall of Fame

**Structured parts** (exact, do these first):
- Owner stats table — `app.js:5833`, `<tr>` per owner. Resolve via
  `isMyFranchise(owner.Owner)`.
- Season finish cards — `app.js:5910`; `year.champion_abbrev` is a real abbrev.
- Rivalry table `<tr class="rivalry-week-row">` (`:6042`) and `.rivalry-leader`
  cells (`:6036-6037`).
- The team-history owner table at `app.js:4960`.

**Free-text records** (best-effort, as decided): `mvps`, `team_records`, and
`player_records` are pre-formatted sentences rendered as
`<div class="record-item">${r}</div>` (near `app.js:5966-5996`). Build an alias set
for your franchise — current owner label, `normalizeCoOwnerLabel(team.owner)`, team
name, abbrev — and whole-word match it (`\b` boundaries, case-insensitive) to add
`is-my-team` to the line.

Accept the known false positives: "Connor" matches both CGK and CWR, and there is no
year context in these strings to disambiguate. Do not try to out-clever it here.

> **Note while working in this area:** these record strings are interpolated
> **unescaped** into HTML (unlike the `escapeHtml()` used elsewhere in the file).
> That is a pre-existing issue, not caused by this change — flag it, don't silently
> fix it in the same commit.

**Follow-up (separate change, not this one):** have
`scripts/export_for_web.py` emit a structured team/owner abbrev alongside each
record string so this becomes an exact `myTeamClass()` call and the text matching
can be deleted.

## Step 10 — Remaining team tables

Highlight only — do **not** reorder ranking tables, since rank order is the
information. The pattern is identical: add `${myTeamClass(abbrev)}` to the `<tr>`'s
class list alongside its existing classes.

- `renderStandings()` — `app.js:3499` (composes with `toilet-cutoff`, `:3537`).
- `renderTeamStats()` — `app.js:8347`, the rankings `<tr>`.
- Jamboree scoreboard — `app.js:2784-2787`.
- `renderScheduleMatchup()` — `app.js:4152`; note it already has a
  `schedule-team-focus` class driven by the dropdown filter (`:4159-4160`).
  `is-my-team` is an independent signal — verify the two read clearly together.
- `renderPlayoffOdds()` (`:4052`), `renderWeeklyRankHistory()` (`:3379`),
  `renderHomeSeason()` (`:1312`) mini-standings, `compactHomeMatchup()` (`:1369`).

**Note:** the plan's original line numbers for this section (drawn up against a
slightly earlier revision) drifted 50-60 lines in the standings/stats/home-dashboard
region — the numbers above are current as of this planning pass. Re-locate by
function name if they've moved again by the time you implement.

## Step 11 — CSS

Append one block to the end of `web/styles.css`, under a section banner comment
matching the file's convention.

Reuse the existing accent-tint language rather than inventing one. The all-rosters
search-match rule (`styles.css:2670-2675`) is the closest precedent
(`rgba(91,155,255,.18)` + inset accent shadow); use a **lighter** tint, since
search-match is a transient spotlight and this is persistent. `--accent-primary` is
defined at `styles.css:5`.

Tables here mix `border-collapse: collapse` and `separate`, and **an inset
`box-shadow` on a `<tr>` does not render under `collapse` in Chrome/Safari** — so the
accent bar must live on the first `<td>`, not the row.

```css
/* ====== MY TEAM HIGHLIGHT (logged-in manager's own team) ====== */
.is-my-team {
    background: rgba(91, 155, 255, 0.08);
    box-shadow: inset 3px 0 0 var(--accent-primary);
}

/* Table rows: collapse-safe — paint the cells, bar on the first cell. */
tr.is-my-team { background: none; box-shadow: none; }
tr.is-my-team > td { background: rgba(91, 155, 255, 0.08); }
tr.is-my-team > td:first-child { box-shadow: inset 3px 0 0 var(--accent-primary); }

/* Cards are a large surface — an outline reads better than a full wash. */
.matchup-card.is-my-team {
    background: none;
    box-shadow: none;
    border: 1px solid var(--accent-primary);
}
```

Specificity checks against existing rules:
- `tr.is-my-team > td` (0,2,1) ties `.standings-table tbody tr:nth-child(even) td`
  (0,2,1) — appending at end of file wins, which is what we want.
- `.standings-table tbody tr:hover td` (0,3,1) still beats it, so hover survives on
  your own row. Verify this.
- Confirm the tint does not wash out `.rank.playoffs` / `.rank.toilet-bowl` or
  `.luck-pos` / `.luck-neg`. If it does, lower the alpha rather than raising
  specificity.
- `.stats-leader-row.rank-1/2/3` already carry medal accents — check a tinted
  rank-1 row still reads as rank-1.

## Verification

1. Serve locally: `python3 -m http.server` from `web/`, open `localhost:8000`.
   `performLogin()` has a localhost fallback (`app.js:10463`) that grants login
   **without** server validation when the fetch fails, so any team + any password
   works locally.
2. **Logged out — the critical check.** Walk matchups, standings, teams/all-rosters,
   teams/roster, stats leaders, stats team, schedule, transactions, drafts, history.
   Output must be identical to `main`: no tint, no reordering, no preselection. Every
   helper is designed to no-op when signed out; this proves it.
3. **Log in as `GSA`.** Confirm the active view re-renders without navigating away
   (Step 2), then check each promise from the request:
   - Matchups: GSA's card is first; card and the GSA side are tinted.
   - Teams → All Rosters: GSA is the leftmost column; search and column toggles still
     work against the reordered list.
   - Teams → Roster / Hall of Fame / Activity: GSA preselected on all three.
   - Compare: GSA on the left, this week's opponent on the right, rendering a real
     comparison on arrival.
   - Stats → Leaders: GSA's QBs tinted in the QB card; same in "All" and expanded
     views; repeat for RB/WR/TE/K/D-ST.
   - Stats → Team Stats, Standings: GSA's row tinted at its correct rank.
   - Transactions: every GSA trade and roster move tinted, across all four card
     shapes — find a new trade, an old parsed trade, and a plain add/drop.
   - Drafts: GSA's picks tinted, **including in seasons under a retired code**.
   - History → Hall of Fame: GSA's owner-stats row and rivalry entries tinted.
4. **Deep links must still win over preselection:** open `#teams/history/CWR`,
   `#compare?team1=AYP&team2=SLS`, and a `#transactions` anchor link directly.
   Each must honor the URL, not your team.
5. **Edge cases:** a past season (2024) and a playoff week — bracket headers keep
   canonical order while your matchup leads its own bracket. A week where GSA has a
   bye or is absent — `floatMyTeam` returns its input unchanged, so ordering must be
   untouched, and Compare's right side stays empty.
6. **Log out** — all tinting, reordering, and preselection disappear immediately.
7. `pytest tests/` — especially `tests/test_web_security_ui.py`, which asserts
   against `web/app.js` content.
8. Console clean on every view, logged in and out.

## Housekeeping

Per this project's convention, copy this plan into the repo's `docs/` as the first
step of execution.

## Out of scope

- Any change to the auth model. The plaintext-password-in-localStorage design
  (`app.js:10296`-ish) is untouched here — worth its own look, but not this change.
- The unescaped HoF record interpolation noted in Step 9 — report, don't fix here.
- Reordering ranking tables (standings, team stats, stats leaders).
- A preference toggle to disable personalization.
- The exporter change to structure HoF records (Step 9 follow-up).
