# Merge "My Team" (`#manage`) into the team page (`#teams`)

## Context

QPFL's site has two pages that are both "a team's page":

- **`#teams`** (nav label "Rosters") — read-only. Sub-tabs All Rosters / Roster /
  Hall of Fame / Activity / Compare Teams, with a `.team-btn` selector for the ten
  franchises. Markup at `web/index.html:257-321`; renderers `renderTeams()`
  (`web/app.js:4496`), `renderTeamHubHeader()` (`:4424`), `renderTeamHistory()`
  (`:4922`), `renderTeamActivity()` (`:5342`), `renderActiveTeamSubview()` (`:5370`).
- **`#manage`** (nav label "My Team") — the logged-in manager's workspace. Tabs
  Dashboard / Roster / Set Lineup / Add Players / Trades / Commissioner. ~500 lines
  of markup at `web/index.html:398-899` and roughly 4,000 lines of `app.js`.

Since the personalization pass (`docs/PLAN_personalize_manager_site.md`), `#teams`
already floats the logged-in manager's team to the front and preselects it —
`floatMyTeam(teams, t => t.abbrev)` at `app.js:4502`, feeding the
`currentTeam = teams[0].abbrev` default at `:4504`, plus `myTeamClass()` on each
`.team-btn` at `:4511`. So a logged-in manager landing on `#teams` is *already*
looking at their own team.

That makes the two pages redundant, and the redundancy is not cosmetic:

| Concern | `#teams` | `#manage` |
|---|---|---|
| Rank / record / points | `renderTeamHubHeader()` `:4424` | `myTeamSummary()` `:12038` in the dashboard intro |
| Roster + taxi | weekly-score matrix inline in `renderTeams()` `:4657`, `:4742` | `renderDepthChartTab()` `:13960` + `renderRosterTaxiSquad()` `:13894` |
| Recent transactions | `teamTransactions()` `:5281` → `teamTransactionHtml()` `:5332` | `myTeamActivity()` `:12017` dashboard card |
| Trade block | `renderTeamTradeBlock()` `:5376` (read) | `renderTradeBlockTab()` `:13650` (write) |
| Draft picks | picks grid inline `:4840` | `renderTradePicks()` `:13073` |
| Team name / avatar | shown in hub header | edited in `#my-team-settings` |

Two renderers, two markup blocks, two mental models for the same franchise. The
Dashboard tab in particular is ~100% derived display — Next Matchup re-derives what
`#matchups` shows, the summary line restates `#standings`, Recent Roster Activity is
the first five rows of what the Activity sub-tab renders in full.

**Goal:** one page. `#teams` becomes the single franchise page; when the selected
team is yours and you're logged in, it grows the manager tools. `#manage` stops
existing as a route and becomes a redirect. Nothing about the write path (the
`api/transaction.py` action set, `manageState` credentials) changes — this is a
consolidation of *surface*, not of behavior.

Decisions already made:
- **Full merge.** All six manage tabs move under `#teams`; `#manage` is retired.
- **A separate, second tab bar for manager tools.** The manager sub-tabs are *not*
  appended to the shared `.team-subnav` — they live in their own `.my-team-subnav`
  row that appears only when `currentTeam === myTeamAbbrev()` and you're logged in
  (Commissioner additionally requires `isCommissioner()`). Mixing "pages every team
  has" with "things only you can do" in one list would make the shared bar's length
  depend on who you are; two bars keep each list stable and make the manager tools
  read as a distinct group.
- **Nav keeps a "My Team" entry**, deep-linking to `#teams/roster/<your abbrev>`;
  logged out it points at `#teams` and the page shows the login CTA.
- The Dashboard tab is **not** carried over as a tab. Its one non-duplicated card
  (lineup status) and its Edit Team control fold into the team hub header.

Line numbers below are current as of this planning pass against `web/app.js`
(15,662 lines). Re-locate by function name, not line number.

## Target shape

Viewing **any** team (the shared bar only):

```
#teams/<subview>[/<ABBR>]

 [All Rosters] [Roster] [Hall of Fame] [Activity] [Compare]      ← .team-subnav
 [GSA][AYP][CGK*][CWR][SLS][MPA][JRW][JDK][…]                    ← .team-selector

 ┌─ team hub header ─────────────────────────────────────────┐
 │ avatar   Connor's Team      No.5 · 3–4 · 902 pts · 128.9 PPG │
 │          Connor Kelly                                        │
 └──────────────────────────────────────────────────────────────┘
```

Viewing **your own** team while logged in — a second bar appears below the hub
header, and the shared bar above is untouched:

```
 [All Rosters] [Roster] [Hall of Fame] [Activity] [Compare]      ← .team-subnav (unchanged)
 [GSA*][AYP][CGK][CWR][SLS][MPA][JRW][JDK][…]

 ┌─ team hub header ─────────────────────────────────────────┐
 │ avatar   Griffin's Team     No.3 · 5–2 · 1043 pts · 141.2 PPG │
 │          Griffin Ansel                                        │
 │  [Lineup: Submitted ●] [Next: vs AYP wk3] [Trades: 1] [Edit Team] │
 └──────────────────────────────────────────────────────────────┘

 ── Manage ────────────────────────────────────────────────────  ← .my-team-subnav
 [Set Lineup] [Add Players] [Trades] [Commissioner]                 hidden unless
                                                                    canManageCurrentTeam()
```

The two bars drive **one** `.team-subview` panel set: at most one button across
both bars is `active` at a time, and selecting in one clears the other.

New routes (all reuse the existing `#view/subview/detail` parser —
`parseHashRoute()` `app.js:10166` — so no routing-grammar change):

| Old | New |
|---|---|
| `#manage` (dashboard) | `#teams/roster/<ABBR>` |
| `#manage` → Roster tab | `#teams/roster/<ABBR>` (depth editor mounts above the weekly matrix) |
| `#manage` → Set Lineup | `#teams/lineup/<ABBR>` |
| `#manage` → Add Players | `#teams/add/<ABBR>` |
| `#manage` → Trades | `#teams/trades/<ABBR>` (keeps its nested New/Matches/Pending/Block bar) |
| `#manage/commissioner` | `#teams/commissioner/GSA` |

## Step 1 — Move the markup

In `web/index.html`, relocate the manage panels from `#manage-view` (398-899) into
`#teams-view` (257-321) as `.team-subview` panels, and delete `#manage-view`.

- `#tx-lineup` → `#team-lineup-subview`
- `#tx-fa` → `#team-add-subview`
- `#tx-trade`, `#tx-tradematches`, `#tx-pending`, `#tx-tradeblock` → wrapped in a
  single `#team-trades-subview` that retains the existing `#trade-center-tabs`
  `.manage-subtab` bar verbatim
- `#tx-commissioner` → `#team-commissioner-subview`
- `#tx-depth` inner content (`#roster-action-panel`, `#depth-chart-groups`, the
  save/undo actions, `#roster-taxi-players`) → moves *inside* `#team-roster-subview`,
  above the existing `#team-roster-container`, wrapped in a new
  `<section id="my-roster-tools" hidden>`
- `#my-team-settings` (team name + avatar editors) → moves next to
  `#team-hub-header` as `<section id="my-team-settings" hidden>`
- `#tx-taxi` and `#tx-release` are **orphan panels** — no tab button points at them;
  their flows were folded into the roster action panel. Delete them along with
  `renderTaxiTab()` (`:12369`) / `renderReleaseTab()` (`:12681`) and their
  select/submit helpers. Keep `executeTaxiActivation` (`:12468`) and
  `executeRelease` (`:12734`) — `openRosterAction()` still calls them.
- Delete `#manage-access-message`, `#manage-panel`, `#manage-header` /
  `#manage-team-name` (the hub header already names the team), and the
  `.transaction-tabs` bar.

Add a **second tablist** immediately after `#team-hub-header` (index.html:270),
hidden as a whole by default. `.team-subnav` (index.html:259) is not touched.

```html
<div class="my-team-subnav" id="my-team-subnav" role="tablist"
     aria-label="Manage my team" hidden>
    <span class="my-team-subnav-label">Manage</span>
    <button class="team-subnav-btn my-team-btn" id="team-lineup-tab" role="tab"
            aria-selected="false" aria-controls="team-lineup-subview" tabindex="-1"
            data-subview="lineup">Set Lineup</button>
    <!-- …add, trades, commissioner the same way -->
    <button class="team-subnav-btn my-team-btn" id="team-commissioner-tab" …
            data-subview="commissioner" hidden>Commissioner</button>
</div>
```

The buttons keep the `.team-subnav-btn` class and `data-subview` attribute so the
**existing** click handler (`app.js:10522`) picks them up with no change. The
container hides/shows as a unit; only Commissioner needs its own per-button `hidden`
(it requires `isCommissioner()` on top of owning the team).

This **must be static markup**, not injected: `.team-subnav-btn` handlers are bound
once at module load with `document.querySelectorAll`. Gating toggles `hidden`, never
adds or removes the elements.

DOM-id uniqueness is asserted by `test_manage_rosters_dom_ids_are_unique`; keep that
property when merging the two subtrees.

## Step 2 — Routing

**`TEAM_HUB_SUBVIEWS`** (`app.js:4416`) currently `roster|history|activity`. Add a
second set rather than widening it, since the two have different gating:

```js
const TEAM_HUB_SUBVIEWS = new Set(['roster', 'history', 'activity']);
const MY_TEAM_SUBVIEWS = new Set(['lineup', 'add', 'trades', 'commissioner']);
const TEAM_DETAIL_SUBVIEWS = new Set([...TEAM_HUB_SUBVIEWS, ...MY_TEAM_SUBVIEWS]);
```

Replace the three hardcoded `['roster', 'history', 'activity']` literals — in
`activateTeamsSubview()` (`:10396`) and the `.team-subnav-btn` handler (`:10527`) —
with `TEAM_DETAIL_SUBVIEWS.has(sub)` so the selector and hub header stay visible on
the manager sub-tabs too.

**`activateTeamsSubview()`** (`:10384`) must now coordinate two tablists. Today it
does `setActiveTab(teamBtn.closest('[role="tablist"]'), teamBtn)`, which only clears
the `active`/`aria-selected` state within the button's own bar — so selecting
"Set Lineup" would leave "Roster" looking active. Clear both explicitly:

```js
function activateTeamsSubview(sub) {
    const teamBtn = document.querySelector(`.team-subnav-btn[data-subview="${sub}"]`);
    if (!teamBtn) return;
    // Two tablists (shared + my-team) drive one panel set, so deselect across both
    // before marking the target active.
    document.querySelectorAll('.team-subnav-btn').forEach(btn => {
        btn.classList.remove('active');
        btn.setAttribute('aria-selected', 'false');
        btn.tabIndex = -1;
    });
    setActiveTab(teamBtn.closest('[role="tablist"]'), teamBtn);
    …  // panel toggling and selector/hub visibility unchanged
}
```

Check what `setActiveTab` already does before writing this — if it takes a root, the
cleanest version passes both bars rather than hand-rolling the reset.

Roving-tabindex/arrow-key behavior, if `setActiveTab` or a keydown handler
implements it, should treat the two bars as **separate** tablists (arrow keys wrap
within a bar), which is the correct ARIA reading of two `role="tablist"` elements.

**`renderActiveTeamSubview()`** (`:5370`) gains the new branches:

```js
function renderActiveTeamSubview(subview) {
    if (subview === 'history') return renderTeamHistory();
    if (subview === 'activity') return renderTeamActivity();
    if (!MY_TEAM_SUBVIEWS.has(subview)) return;
    if (!canManageCurrentTeam()) return;           // Step 3
    if (subview === 'lineup') return initLineupForm();
    if (subview === 'add') return renderFaTab();
    if (subview === 'trades') return renderTradeCenter();   // new thin wrapper
    if (subview === 'commissioner') return initCommissionerTools();
}
```

`renderTradeCenter()` is a small new function that calls `renderTradeTab()`
(`:12794`), `renderPendingTrades()` (`:13393`), `renderTradeMatches()` (`:12920`),
and `renderTradeBlockTab()` (`:13650`) — the same fan-out `showManagePanelForTeam()`
(`:10958`) does today — and keeps the `[data-trade-tab]` sub-tab wiring.

**`applyHash()`** (`:10402`) already carries a block of teams-specific legacy
rewrites (`:10416-10440`). Add `#manage` there rather than to
`LEGACY_HASH_REDIRECTS` (`:1063`), because the target depends on who is logged in:

```js
// #manage was the old My Team page; it is now the logged-in manager's own
// team page. Logged out there is no "my" team, so land on the roster list.
if (route.view === 'manage') {
    const mine = myTeamAbbrev();
    const sub = route.subview === 'commissioner' ? 'commissioner' : 'roster';
    hash = mine ? `teams/${sub}/${mine}` : 'teams';
    ...
}
```

Keep `'commissioner': 'manage/commissioner'` in `LEGACY_HASH_REDIRECTS` — it now
lands on `#manage/commissioner`, which the above rewrite forwards again. Verify the
double hop resolves in one `applyHash()` pass; if it doesn't, point the entry
straight at `teams/commissioner`.

**`navigateToView()`** (`:10274`): delete the `manage` special case at
`:10334-10338` (`prepareViewData('manage')` → `initManageRoster()`). The teams
branch at `:10303-10315` already applies `detail` → `currentTeam` and handles
`teamRouteSubview`; it needs no change.

**`VIEW_RENDERERS.teams`** (`:1043`) stays as-is — it already calls `renderTeams()`
then `renderActiveTeamSubview(subview)`.

**`prepareViewData()`** (`:981`): fold the `manage` branch (`:1026-1031`,
`ensureCurrentSeasonFiles({rosters:true, draftPicks:true})` + `ensureHomeWeekData()`)
into the `teams` branch, conditioned on `MY_TEAM_SUBVIEWS.has(subview)`. `lineup`
and `add` need rosters + the current week; `trades` additionally needs draft picks.

**Metadata**: `pageTitleFor()` (`:1114-1131`) — drop the `manage` branch at `:1146`,
add the new teams subviews; `PAGE_DESCRIPTIONS.manage` (`:1104`) is deleted.

## Step 3 — Gating

One predicate, used by the tab bar and every manager renderer:

```js
// True when the team currently selected on #teams is the logged-in manager's own,
// in the live season. Manager tools are current-season-only.
function canManageCurrentTeam() {
    return Boolean(myTeamAbbrev())
        && currentTeam === myTeamAbbrev()
        && currentSeason === LIVE_SEASON;
}
```

Reuse `myTeamAbbrev()` (`:8907`) and `isCommissioner()` (`:10672`) — do not
re-derive from `manageState` at call sites.

Add `syncMyTeamTabs()`, called at the end of `renderTeams()` (after the hub header
render at `:4533`) and from `refreshPersonalization()` (`:1197`):

- toggle `hidden` on `#my-team-subnav` as a whole from `canManageCurrentTeam()`, and
  on `#team-commissioner-tab` from `canManageCurrentTeam() && isCommissioner()`
- toggle `hidden` on `#my-roster-tools` and `#my-team-settings`
- if the active subview is now hidden (you switched to another team, logged out, or
  changed season), fall back to `roster` via `activateTeamsSubview('roster')` and
  `history.replaceState` the corrected URL

That last bounce is the one behavior that doesn't exist today and is easy to miss.
Three paths reach it: the `.team-btn` click handler (`:4517`), `performLogout()`
(`:10754`), and a season change (`loadData()` / the season selector).

**Direct-URL defense.** `#teams/lineup/AYP` typed by a GSA manager must not render
the lineup editor. `renderActiveTeamSubview()` returns early on
`!canManageCurrentTeam()`; `syncMyTeamTabs()` then bounces to `roster`. This is a UX
guard only — server-side authorization is unchanged, every write still posts
`{team, password}` and `api/transaction.py` is the real gate.

**Logged-out state.** The old `#manage-access-message` card is gone. `#teams` renders
normally for anonymous visitors; the manager tabs simply aren't there. The
`data-login-trigger` CTA is preserved by the header login button
(`#global-login-btn`), which `test_global_auth_is_the_only_login_surface` already
pins as the sole login surface.

## Step 4 — Fold the Dashboard into the hub header

Delete `renderMyTeamDashboard()` (`:12059`), `wireMyTeamDashboard()` (`:12182`),
`myTeamSummary()` (`:12038`), and `myTeamActivity()` (`:12017`). Their content is
either already on the page or moves as follows:

| Dashboard card | Disposition |
|---|---|
| Identity + "Standings: r/N, PPG, Streak" | Already in `renderTeamHubHeader()` (`:4424`) as rank / record / points. Extend that header to also show PPG and streak from `data.team_stats[currentTeam]` — for **all** teams, not just yours. Strictly more information for everyone. |
| Next Matchup | New strip in the hub header, gated on `canManageCurrentTeam()`, built from the surviving `findMyTeamMatchup()` (`:11854`) / `myOpponentForWeek()` (`:11842`). Keeps its "View Matchup" route to `#matchups/week/N`. |
| Lineup status | Same strip, from the surviving `lineupDashboardStatus()` (`:11881`). "Set Lineup" now routes to `#teams/lineup/<ABBR>`. |
| Pending Trades count | Same strip; routes to `#teams/trades/<ABBR>`. |
| Draft Challenge | Same strip, from `draftDashboardStatus()` (`:11984`); routes to `#drafts/challenge`. |
| Recent Roster Activity | **Deleted.** The Activity sub-tab renders the same feed, longer and better (`teamTransactions()` `:5281`). Link to it from the strip. |
| Edit (name / avatar) | "Edit Team" button in the hub header toggling `#my-team-settings`, preserving the existing `aria-expanded` / `aria-controls` toggle logic from `wireMyTeamDashboard()` (`:12186-12197`). |

`[data-my-team-action]` handlers move into a `wireMyTeamHeader()` alongside
`renderTeamHubHeader()`. Keep the `data-my-team-action` attribute names —
`test_my_team_dashboard_has_required_statuses_and_actions` asserts on
`data-my-team-action="lineup"` and that test is being rewritten anyway, but the
attribute is also the hook the lineup-reminder banner uses.

## Step 5 — Roster sub-tab: read matrix + edit tools

`#team-roster-subview` renders, in order:

1. `#my-roster-tools` — `renderDepthChartTab()` (`:13960`) + `renderRosterTaxiSquad()`
   (`:13894`) + `#roster-action-panel`. Hidden unless `canManageCurrentTeam()`.
2. `#team-roster-container` — the existing weekly-score matrix + taxi history +
   picks grid built inline by `renderTeams()` (`:4657`, `:4742`, `:4840`), unchanged,
   for every team including yours.

Do **not** try to unify the two roster tables in this pass. They answer different
questions (season history vs. current depth order) and merging them is a separate,
larger design problem. Note it as follow-up.

`renderTeams()` must call `initDepthChartTab()` (`:14179`) when
`canManageCurrentTeam()`, and must **not** re-render the depth chart while
`isDepthChartDirty()` (`:13954`) — switching sub-tabs re-enters `renderTeams()` and
would silently discard unsaved reordering.

`saveDepthChart()` already calls `renderAllRosters()` (`:14176`) to propagate the new
order; it should now also re-render the roster matrix.

## Step 6 — Retarget everything that pointed at `#manage`

| Site | Current | Change |
|---|---|---|
| `web/index.html:80` | `<a href="#manage" data-view="manage">My Team</a>` | `data-view="teams"` + `data-my-team-link`; href kept as `#teams` and rewritten to `#teams/roster/<ABBR>` on login by `updateGlobalAuthUI()` (`:10680`) |
| Nav handler `:10487-10502` | special-cases `manage` for `LIVE_SEASON` | key the `loadData(LIVE_SEASON)` force-load off `data-my-team-link` instead of `view === 'manage'` |
| `switchTxTab()` `:12248` | DOM tab switcher + commissioner guard | delete; callers route instead |
| `renderLineupReminder()` `:11947` banner button | `navigateToView('manage')` + `switchTxTab('lineup')` | `#teams/lineup/<ABBR>` |
| `startTradeForPlayer()` `:12774` | `switchTxTab('trade')` | `#teams/trades/<ABBR>` + activate the New Trade sub-tab |
| `startTradeFromMatch()` `:13001` | same | same |
| `updateGlobalAuthUI()` `:10680-10709` | hides commissioner tab, redirects off `#manage/commissioner` | same logic against `#team-commissioner-tab` and `#teams/commissioner` |
| `initManageRoster()` `:10926`, `showManagePanelForTeam()` `:10958` | mount + fan-out | delete; `renderTeams()` + `renderActiveTeamSubview()` do this |
| `confirmManageNavigation()` `:10661` | exempts `targetView === 'manage'` | must now also fire when moving **between** `#teams` sub-tabs or teams, since both the source and destination are `teams`. Change the signature to take the target subview/team, and call it from the `.team-btn` handler (`:4517`) as well as the `.team-subnav-btn` handler (`:10525`). **This is the subtlest part of the change** — today "still on manage" implied "changes still live"; now it doesn't. |
| `hasUnsavedManageChanges()` `:10638` | gates on `getActiveView() !== 'manage'` | gate on `getActiveView() !== 'teams' \|\| !canManageCurrentTeam()` |
| `beforeunload` `:10666`, `popstate` `:10545` | unchanged logic, new predicate | — |

`resetManageState()` (`:12227`) and `performLogout()` (`:10754`) already null
`currentTeam`; add a `syncMyTeamTabs()` call so the tabs disappear immediately.

Leave `manageState` (`:10590`), `GLOBAL_SESSION_KEY` (`:10559`), `MANAGE_CONFIG`
(`:10553`), `performLogin()` (`:10713`), and every `execute*` write helper **exactly
as they are**. The auth model is out of scope; keeping it untouched is what makes
this a presentational refactor.

## Step 7 — CSS

`web/styles.css`: the manage panel styles (`.manage-container`, `.manage-panel`,
`.transaction-tabs`, `.tx-tab`, `.tx-content`, `.tx-section`, `.my-team-dashboard*`)
either get deleted with their markup or rescoped. Keep `.manage-subtab` (the trade
sub-tab bar survives), `.tx-section`, `.player-list`, `.lineup-*`, and
`.roster-action-*` — all still used.

`.team-subnav` (styles.css:5290-5300, 6845) is unchanged — it keeps its five
buttons. Add `.my-team-subnav` next to it, inheriting the same button styling
(`.team-subnav-btn`) but visually subordinate: a "Manage" label, a rule above it,
and a lighter/accented treatment so it reads as yours rather than as another row of
site navigation. Reuse `--accent-primary` (styles.css:5), the same token
`.is-my-team` (styles.css:11915) uses, to tie the two signals together.

At mobile widths it needs the same horizontal-scroll rail treatment as
`.team-subnav` (styles.css:1128, 11521); `centerActiveScrollableItem()` (`:1261`) is
already generic and should be called for this bar too.

The `.is-my-team` rule (styles.css:11915) is unchanged.

## Step 8 — Tests

Six files reference the retired markup and need rewriting, not deleting:

- `tests/test_manage_rosters_ui.py` — the core one. `primary_tabs` /
  `active_content` assertions (`:40-42`) are replaced by assertions that
  `.team-subnav` still holds exactly the five shared tabs and `#my-team-subnav`
  holds the four manager tabs and is `hidden`; `trade_tabs` (`:41`) stays
  as-is. `test_team_settings_open_from_dashboard_and_are_removed_from_roster`
  (`:93`) becomes "settings open from the hub header". Keep
  `test_manage_rosters_dom_ids_are_unique` (`:75`) and
  `test_global_auth_is_the_only_login_surface` (`:110`) — both still meaningful and
  both are load-bearing for this merge.
- `tests/test_team_hub_ui.py` — `test_team_pages_center_roster_hall_and_activity_without_a_team_home` (`:109`) must
  learn the new subviews.
- `tests/test_mobile_navigation_ui.py:50` — `primary_views == ['home','manage','teams','matchups']`
  becomes `['home','teams','teams','matchups']`, or better, assert on the nav
  hrefs/labels rather than `data-view`.
- `tests/test_commissioner_ui.py:19` — `id="tx-commissioner"` after `id="manage-panel"`
  → assert it lives inside `#teams-view`.
- `tests/test_lineup_reminders.py:143-144` — `navigateToView('manage')` /
  `switchTxTab('lineup')` → the new route.
- `tests/test_decision_tools_ui.py:163,168` — `#tx-tradematches` id and
  `switchTxTab('trade')`.

Add one new test: `#my-team-subnav` is `hidden` in the shipped `index.html`, the
shared `.team-subnav` contains none of the manager `data-subview` values, and the
only thing that unhides the bar is `canManageCurrentTeam()`.

## Suggested commit split

Landing this as one commit is a ~1,500-line diff across two files with no reviewable
intermediate. Split it:

1. **Extract, no move** — introduce `canManageCurrentTeam()`, `syncMyTeamTabs()`,
   the two-tablist `activateTeamsSubview()`,
   `renderTradeCenter()`, and the `MY_TEAM_SUBVIEWS` sets; retarget `switchTxTab()`
   callers to go through a routing helper. `#manage` still works. Tests green.
2. **Move the markup** — relocate the panels, add the `#my-team-subnav` bar, wire the
   new subviews, add the `#manage` rewrite in `applyHash()`. Delete `#manage-view`.
   Rewrite the six test files here.
3. **Fold the dashboard** — Step 4, delete `renderMyTeamDashboard()` et al.
4. **CSS cleanup** — Step 7.

## Verification

1. `python3 -m http.server` from `web/`, open `localhost:8000`. `performLogin()` has
   a localhost fallback (`:10739-10748`) that grants login without server validation
   when the fetch fails, so any team + any password works locally.
2. **Logged out**, walk `#teams` and every sub-tab: no manager tabs, no
   `#my-roster-tools`, no `#my-team-settings`, console clean. `#manage` redirects to
   `#teams`.
3. **Log in as a non-commissioner team.** Confirm the active view re-renders
   immediately (`refreshPersonalization()`), your team is preselected, the
   `Manage` bar appears below the hub header with Set Lineup / Add Players / Trades
   but no Commissioner, and the shared `.team-subnav` above still shows exactly its
   five buttons. Click between the two bars: exactly one button is highlighted at a
   time, and the shared bar visibly deselects when a manager tab is chosen.
   Then click another team's chip — the `Manage` bar disappears entirely.
4. **Exercise every write path end-to-end** — this is the real risk of the change,
   since each one moved DOM containers:
   - Set Lineup: week select → lineup assistant (Use Projected, Copy Last
     Submitted) → submit → reload and confirm the submission restores
     (`test_lineup_editor_restores_the_active_week_submission_after_reload`).
   - Roster: drag-reorder → Save Depth Chart → confirm All Rosters reflects the new
     order; row actions Trade / Drop / Activate each open `#roster-action-panel`.
   - Add Players: pick an FA, pick a release, confirm the modal fires.
   - Trades: propose (players + picks + a conditional), see it in Pending, respond,
     cancel; edit and save the Trade Block and confirm the **read-only** block on the
     Activity sub-tab updates.
   - Team name + avatar upload from the hub header Edit button.
5. **Log in as `GSA`.** Commissioner tab appears; `#teams/commissioner/GSA` loads the
   panel; the audit log, workbook export, season mode, and maintenance toggles all
   work.
6. **Gating:** as GSA, manually enter `#teams/lineup/AYP` — must bounce to
   `#teams/roster/AYP` with no editor rendered. Then `#teams/lineup/GSA` — must work.
7. **Unsaved-changes guard:** start a depth-chart reorder, then (a) click another
   `.team-btn`, (b) click another sub-tab, (c) click a top-nav item, (d) reload.
   All four must prompt. Repeat with a dirty trade block.
8. **Season switch:** with the manager tabs open, switch to an archived season —
   tabs must disappear and the view fall back to `roster`. The "My Team" nav item
   must force-load `LIVE_SEASON`.
9. **Legacy URLs:** `#manage`, `#manage/commissioner`, `#commissioner`,
   `#teams/hof/GSA`, `#hof/teams/GSA`, `#history/teams/GSA`, `#teams/tradeblock/GSA`,
   `#all-rosters`, `#compare?team1=AYP&team2=SLS`, and a `#player/<key>` deep link.
   Each must land somewhere sensible in one hop.
10. **Mobile width (~390px):** both bars scroll horizontally and center their active
    tab; stacked they don't eat the viewport — if they do, the `Manage` bar is the
    one to compact. The nav's four primary items still fit.
    Keyboard: Tab reaches both bars; arrow keys move within a bar, not across.
11. `pytest tests/` — the six rewritten files plus `test_accessibility_ui.py` and
    `test_web_security_ui.py`, which assert against `web/app.js` / `index.html`
    content.

## Out of scope

- The auth model. Plaintext password in `localStorage` (`:10559-10586`) and
  `{team, password}` in every request body are untouched here. Worth its own pass.
- Unifying the two roster tables (weekly-score matrix vs. depth chart) into one
  component — noted in Step 5 as follow-up.
- Any change to `api/transaction.py`, `api/lineup.py`, `api/team-name.py`,
  `api/team-avatar.py`, or their action sets.
- The Draft Challenge view (`#drafts/challenge`), which stays a separate page and is
  only linked from the hub header strip.
- The commissioner panel's internals — it moves wholesale, its forms are not
  redesigned.
