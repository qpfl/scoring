# Umami Cloud Analytics Implementation Plan

## Overview

Add privacy-conscious usage analytics to the QPFL website with Umami Cloud. The rollout will measure production traffic, meaningful hash-routed page views, referrers, devices, approximate location, and visit duration. After anonymous tracking is verified, authenticated activity will be attributable to a QPFL team—not an individual owner—without sending passwords, owner names, form contents, roster contents, or search/filter text.

The integration will use Umami Cloud's generated browser tracker and existing client-side `window.umami` API. It will not add a backend endpoint, database, Cloud API key, cookie banner, session replay, or heatmaps.

## Current State Analysis

QPFL is a static, framework-free single-page application served canonically from Vercel. Navigation is implemented with URL fragments such as `#matchups/week/6`, `#teams/roster/GSA`, and `#manage`; the visible document title is updated after route changes. No analytics tracker, privacy disclosure, Content Security Policy, or site footer currently exists.

The website already has a useful authentication boundary for team attribution. A team is not considered signed in until its password is validated by the Vercel transaction API. The authenticated team and password are stored together in `localStorage` for seven days. Analytics must read only the validated team abbreviation from in-memory state and must never read, copy, hash, or transmit the password.

Umami can automatically track hash-based single-page applications, but QPFL should use manual page views. Several QPFL navigation handlers call `history.pushState()` before updating `document.title`; automatic tracking could therefore record a new path with the preceding page's title. Manual tracking also lets QPFL remove filter/search parameters and normalize player detail paths before data leaves the browser.

## Desired End State

- Only traffic on `qpfl-scoring.vercel.app` is collected. Localhost, Vercel preview deployments, and GitHub Pages mirrors are excluded unless they are deliberately added later.
- Every meaningful QPFL route produces one page view with the correct view-specific title.
- Query-like hash state—including transaction searches, selected filters, and comparison selections—is not sent to Umami.
- Anonymous visitors remain anonymous and cookie-free.
- After a successful QPFL login, Umami associates subsequent activity with a stable team-level ID such as `qpfl-team-GSA`. Co-owners intentionally appear as one team because QPFL does not have individual accounts.
- A short, always-available disclosure explains anonymous collection and signed-in team attribution.
- Successful high-value actions can be counted without including sensitive payloads.
- Ad blockers and Do Not Track may reduce counts without breaking the website.
- The Umami dashboard, share URLs, credentials, and any future API key remain private.
- Disabling the script or removing the website in Umami cleanly stops collection without affecting league functionality.

### Key Discoveries

- `web/index.html:3-25` contains the document head where Umami's generated deferred tracker belongs.
- `web/index.html:872-875` closes the main application and loads `app.js`; there is currently no persistent footer or privacy surface.
- `vercel.json:1-55` statically serves `web/**` and has no build-time HTML substitution, analytics configuration, or CSP. The public Umami website UUID should therefore be committed directly in the script tag; no secret is required.
- `web/app.js:834-891` centralizes page title generation in `pageTitleFor()` and `updatePageMetadata()`.
- `web/app.js:7328-7354` parses hash paths separately from query-like route parameters, providing a clean boundary for URL redaction.
- `web/app.js:7401-7462` centralizes primary view activation, while `web/app.js:7645-7704` handles primary navigation, subnavigation, team navigation, and browser history.
- Team and Hall of Fame selectors also replace routes at `web/app.js:3546` and `web/app.js:4000`; these paths must flow through the same analytics helper.
- Player profile routing has a separate metadata path around `web/app.js:11118-11136`; direct player links first activate All Rosters at `web/app.js:7626-7636`, which must not generate an intermediate analytics page view.
- `web/app.js:7716-7748` persists the QPFL session, `web/app.js:7865-7895` validates login, `web/app.js:7898-7926` logs out, and `web/app.js:8034-8047` restores a saved login. These are the only analytics identity lifecycle points needed.
- `tests/test_ux_quick_wins.py:71-80` already verifies view-specific browser metadata, and `tests/test_manage_rosters_ui.py` covers global authentication contracts. A focused analytics regression file can follow these static-test patterns.
- Umami Cloud now routes collection through its own gateway. The exact tracker URL and attributes should be copied from the Cloud dashboard rather than reconstructed from older examples.

## What We're NOT Doing

- Adding Google Analytics, advertising pixels, fingerprinting, cookies, or cross-site tracking.
- Identifying individual owners. Shared/co-owned teams remain one analytics identity.
- Sending QPFL passwords, owner names, email addresses, comments, trade conditions, lineup contents, transaction contents, player search terms, or filter values.
- Recording session replays, heatmaps, keystrokes, form fields, or DOM snapshots.
- Adding engagement heartbeats in the initial rollout. Umami duration will be based on the time between real page views and events.
- Creating or committing an Umami Cloud API key.
- Building an analytics dashboard inside QPFL.
- Proxying the tracker through QPFL to evade ad blockers.
- Tracking localhost, automated tests, preview deployments, or the GitHub Pages mirror.
- Making the Umami dashboard public or enabling a public Share URL.
- Treating analytics as a security or audit log. League-changing actions continue to use the existing authenticated API and transaction history.

## Implementation Approach

Roll out analytics in two production stages. Stage one adds the Cloud tracker, canonical manual page views, Do Not Track support, and a disclosure. It stays anonymous long enough to validate paths, titles, duration, usage, and accidental data exposure. Stage two enables team attribution after validated login and adds only a small event taxonomy.

Keep analytics behind resilient helpers in `web/app.js`. Every helper must no-op if the tracker is blocked, slow, disabled, or absent. Analytics failures must never block rendering, navigation, login, lineup submission, or roster transactions.

Use manual page views by setting `data-auto-pageview="false"`. Route tracking will call `window.umami.track()` only after `document.title` is correct, preserve Umami's default payload via the function form, replace the URL with a redacted canonical path, and deduplicate repeated render/metadata calls.

## Phase 1: Create and Secure the Umami Cloud Website

### Overview

Create the external Umami Cloud resource and establish production/privacy defaults before any tracker is committed.

### Changes Required

#### 1. Create the Cloud account

**External system**: [Umami Cloud signup](https://cloud.umami.is/signup)

**Changes**:

1. Register with a commissioner-controlled email address and store the credentials in the commissioner's password manager.
2. Verify the emailed six-digit code.
3. Select the US data region for this US-based league.
4. Stay on the free Hobby plan initially. QPFL's traffic should be well within a small-site tier; confirm actual usage after the first month before considering an upgrade.
5. Do not create an API key. Browser collection needs only the public website UUID.

#### 2. Add the QPFL website

**External system**: Umami Cloud → Websites → Add website

**Changes**:

- Name: `QPFL`
- Domain: `qpfl-scoring.vercel.app`
- Keep the website private and do not generate a Share URL.
- Leave session replay and heatmaps disabled.
- Copy the exact generated Tracking Code from the website's Edit screen.
- Record the public website UUID in the implementation work item; do not put account credentials in the repository.

### Success Criteria

#### Automated Verification

- [ ] No implementation file contains an API key, bearer header, account email, or Cloud password: `! rg -n "UMAMI_API_KEY|Authorization: Bearer|cloud\.umami\.is.*password" web tests README.md vercel.json`

#### Manual Verification

- [ ] Umami Cloud account email is verified and the data region is US.
- [ ] The QPFL website exists with the exact production domain.
- [ ] Website analytics are private, with no Share URL.
- [ ] Replay and heatmap collection are disabled.
- [ ] The exact generated tracking snippet and public website UUID are available for Phase 2.

---

## Phase 2: Add Anonymous Production Tracking and Disclosure

### Overview

Load Umami only on the canonical production hostname, respect Do Not Track, disable automatic page views, and tell visitors exactly what is collected.

### Changes Required

#### 1. Install the generated Cloud tracker

**File**: `web/index.html`

**Changes**:

- Insert the exact Cloud-generated deferred tracker in `<head>` after the existing metadata and before application styles.
- Keep the generated `src` value rather than hardcoding an endpoint from documentation.
- Retain the public `data-website-id` UUID.
- Add `data-domains="qpfl-scoring.vercel.app"` so previews, localhost, and mirrors do not collect data.
- Add `data-do-not-track="true"`.
- Add `data-auto-pageview="false"` because QPFL will send redacted page views after updating titles.
- Do not add `data-performance`, replay, heatmap, or automatic click-tracking configuration in the initial rollout.

The expected shape is:

```html
<script
    defer
    src="[exact URL copied from Umami Cloud]"
    data-website-id="[public QPFL website UUID]"
    data-domains="qpfl-scoring.vercel.app"
    data-do-not-track="true"
    data-auto-pageview="false"
></script>
```

#### 2. Add a concise disclosure

**File**: `web/index.html`

**Changes**:

- Add a compact site footer immediately after `</main>` and before the container closes.
- Use normal text or a `<details>` element; do not add a blocking consent dialog because the selected configuration is cookie-free and respects Do Not Track.
- Use disclosure copy equivalent to:

> QPFL uses privacy-friendly, cookie-free analytics to understand site usage. Page views, referrers, browser/device details, approximate region, and visit duration may be collected. When you sign in, activity may be associated with your team. Passwords and league form contents are never sent.

- Link “privacy-friendly analytics” to Umami's public privacy/FAQ documentation in a new tab with safe external-link attributes.

#### 3. Style the footer without competing with league content

**File**: `web/styles.css`

**Changes**:

- Add a low-emphasis footer using existing text, border, spacing, and link tokens.
- Ensure the footer remains visible above the mobile bottom navigation and safe-area padding.
- Keep disclosure text readable at 320px without introducing horizontal scrolling.

### Success Criteria

#### Automated Verification

- [ ] Tracker markup uses `defer`, the real UUID, the exact production domain, DNT support, and manual page views: `python3 -m pytest tests/test_analytics_ui.py -q`
- [ ] Tracker markup does not enable replay, heatmaps, performance, or preview domains: `python3 -m pytest tests/test_analytics_ui.py -q`
- [ ] The disclosure includes anonymous fields, team attribution, and explicit password/form exclusions: `python3 -m pytest tests/test_analytics_ui.py -q`
- [ ] HTML IDs and accessibility regressions remain clean: `python3 -m pytest tests/test_accessibility_ui.py -q`

#### Manual Verification

- [ ] Localhost and a Vercel preview do not send Umami collection requests.
- [ ] Production loads the tracker successfully with Do Not Track disabled.
- [ ] Enabling browser Do Not Track prevents collection.
- [ ] Blocking the tracker produces no console exception and no functional QPFL regression.
- [ ] The footer is readable on desktop and mobile and remains above the fixed mobile navigation.

---

## Phase 3: Track Canonical Hash Routes Once

### Overview

Send one accurate, redacted page view after each meaningful route/title change.

### Changes Required

#### 1. Add resilient analytics helpers

**File**: `web/app.js`

**Changes**:

- Add `analyticsPathForRoute(route)` near the existing route/metadata helpers.
- Build paths from `location.pathname` and `route.path`, not `route.raw`, so hash query parameters never leave the browser.
- Normalize an empty route to `#home`.
- Normalize any player detail to `#player/profile`; the player profile key is not needed for usage analytics.
- Preserve useful public dimensions such as matchup week and team roster abbreviation.
- Add `trackAnalyticsPageView()` that:
  - Returns immediately unless `window.umami?.track` is a function.
  - Uses the function payload form to preserve Umami's website/host/referrer defaults.
  - Overrides only `url` and `title`.
  - Deduplicates by canonical URL plus final document title.
  - Catches/logs only a debug-level warning if the optional tracker rejects a call.
- Do not queue analytics in QPFL code. The Cloud script handles its own readiness, and a blocked event is acceptable.

Illustrative shape:

```javascript
let lastAnalyticsPageKey = null;

function analyticsPathForRoute(route = parseHashRoute()) {
    const path = route.view === 'player' ? 'player/profile' : (route.path || 'home');
    return `${location.pathname}#${path}`;
}

function trackAnalyticsPageView(route = parseHashRoute()) {
    if (typeof window.umami?.track !== 'function') return;
    const url = analyticsPathForRoute(route);
    const key = `${url}\u0000${document.title}`;
    if (key === lastAnalyticsPageKey) return;
    lastAnalyticsPageKey = key;
    window.umami.track(properties => ({
        ...properties,
        url,
        title: document.title,
    }));
}
```

The implementation may use an ASCII delimiter instead of a literal null character to keep `web/app.js` text-tool friendly.

#### 2. Track after metadata is final

**File**: `web/app.js`

**Changes**:

- Extend `updatePageMetadata()` to accept a tracking option and call `trackAnalyticsPageView()` only after all title/description fields are updated.
- Normal primary, subview, team, and browser-history navigation should continue to use `updatePageMetadata()` as the single tracking boundary.
- Route-param replacements for searches/filters may continue updating metadata but must deduplicate because their canonical path and title are unchanged.
- Update team selector and Hall of Fame selector route replacements to call the centralized metadata/tracking boundary after the URL changes.
- For player deep links, suppress the intermediate All Rosters page view, finish player metadata, then emit only normalized `#player/profile`.
- Ensure the initial page view fires after season data has loaded so the title contains the correct season/week.

#### 3. Keep duration honest

**File**: `web/app.js`

**Changes**:

- Do not emit timer heartbeats, scroll events, hover events, or visibility pings in v1.
- Let real page views and the small Phase 4 event set establish visit duration.
- Document in the disclosure/runbook that single-event visits have no reliable duration; Umami calculates time from the interval between events.

### Success Criteria

#### Automated Verification

- [ ] Canonical hash paths retain meaningful route segments and strip `URLSearchParams`: `python3 -m pytest tests/test_analytics_ui.py -q`
- [ ] Player detail routes normalize to `#player/profile`: `python3 -m pytest tests/test_analytics_ui.py -q`
- [ ] Page views no-op when `window.umami` is absent: `python3 -m pytest tests/test_analytics_ui.py -q`
- [ ] Page views are sent after `document.title` is assigned and duplicate metadata calls are suppressed: `python3 -m pytest tests/test_analytics_ui.py -q`
- [ ] Direct player routes suppress the intermediate All Rosters event: `python3 -m pytest tests/test_analytics_ui.py -q`
- [ ] Existing metadata behavior still passes: `python3 -m pytest tests/test_ux_quick_wins.py -q`
- [ ] JavaScript remains syntactically valid: `node --check web/app.js`

#### Manual Verification

- [ ] Umami Realtime shows distinct paths for Home, Matchups, Standings, My Team, Drafts, and team rosters.
- [ ] Titles in Realtime match the destination just opened, including matchup week and season.
- [ ] Changing transaction search/filter state does not expose the search text or create extra page views.
- [ ] Opening a shared player URL emits only `/...#player/profile`, not All Rosters or a player identifier.
- [ ] Browser Back/Forward emits one page view for the resulting destination.
- [ ] Ad-blocker failure leaves routing and metadata fully functional.

---

## Phase 4: Add Authenticated Team Attribution and Minimal Events

### Overview

Associate signed-in usage with a public team abbreviation only after server validation, then count a small set of successful interactions.

### Changes Required

#### 1. Identify a validated team

**File**: `web/app.js`

**Changes**:

- Add `identifyAnalyticsTeam(team)` beside the analytics helpers.
- Accept only a team abbreviation found in the loaded QPFL team list.
- Send a stable ID in the form `qpfl-team-${team}` and a single `team` session property.
- Never derive identity from owner name, email, password, localStorage contents, IP address, or browser fingerprint.
- Call the helper only after `performLogin()` receives `result.success` from the API.
- The existing saved-session flow reuses `performLogin()`, so it will be attributed only after revalidation.
- Localhost's development-only login fallback must not produce analytics because `data-domains` prevents the tracker from running there.

```javascript
function identifyAnalyticsTeam(team) {
    if (!data?.teams?.some(candidate => candidate.abbrev === team)) return;
    if (typeof window.umami?.identify !== 'function') return;
    window.umami.identify(`qpfl-team-${team}`, { team });
}
```

#### 2. Make logout behavior explicit

**File**: `web/app.js`

**Changes**:

- Track `team-logout` before clearing `manageState.team`.
- Clear QPFL's local analytics team context during `performLogout()`.
- Do not invent an undocumented `umami.reset()` or `identify(null)` call.
- Because Umami does not document a browser identity-reset operation, stop sending QPFL analytics while the current document remains logged out. A fresh page load starts anonymous again, and a newly validated login may explicitly re-enable tracking for that team.
- Document that events already recorded before logout remain associated with the team and cannot be retroactively anonymized.

#### 3. Add a constrained event wrapper

**File**: `web/app.js`

**Changes**:

- Add `trackAnalyticsEvent(name, properties = {})` that no-ops safely and permits only an allowlisted event name/property shape.
- Never accept arbitrary form objects or DOM input values.
- Use lowercase kebab-case names under 50 characters.
- Initial allowlist:

| Event | When sent | Allowed properties |
|---|---|---|
| `team-login` | Successful server-validated login or saved-session revalidation | `team` |
| `team-logout` | Immediately before logout clears the team | `team` |
| `lineup-submitted` | API confirms lineup submission | `week` |
| `transaction-completed` | API confirms a roster-changing operation | `type` from a fixed enum only |
| `player-profile-opened` | Player sheet opens | `surface`, `position`; never player name/key |
| `share-link-copied` | A copy-link action succeeds | `surface` from a fixed enum |

- Fixed `type` values may include `free-agent`, `release`, `taxi`, and `trade`; do not send traded/released player names or partner notes.
- Fixed `surface` values may include `roster`, `depth-chart`, `leaders`, `trade-block`, and `player-profile`.
- Emit success events only after the underlying action succeeds, not on clicks that may fail validation.

### Success Criteria

#### Automated Verification

- [ ] Identification occurs only inside the successful login branch and saved sessions still revalidate first: `python3 -m pytest tests/test_analytics_ui.py -q`
- [ ] Team IDs use abbreviations and contain no owner name, email, or password: `python3 -m pytest tests/test_analytics_ui.py -q`
- [ ] Logout is recorded before state clears and analytics suppression is enabled afterward: `python3 -m pytest tests/test_analytics_ui.py -q`
- [ ] Event names and properties are allowlisted and no helper accepts arbitrary payload objects: `python3 -m pytest tests/test_analytics_ui.py -q`
- [ ] Sensitive field names and route-query values never appear in analytics calls: `python3 -m pytest tests/test_analytics_ui.py -q`
- [ ] Authentication regressions remain green: `python3 -m pytest tests/test_manage_rosters_ui.py tests/test_api.py -q`

#### Manual Verification

- [ ] A successful login produces `qpfl-team-[ABBREV]`; a failed password produces no identity or login event.
- [ ] Restoring a saved QPFL session identifies the team only after the validation request succeeds.
- [ ] Co-owner activity is intentionally grouped under one team identity.
- [ ] Logging out records one event and subsequent navigation sends nothing until reload or a new validated login.
- [ ] Event payloads contain no password, owner name, player name, comment, condition, search term, lineup selection, or trade contents.
- [ ] Successful lineup/transaction events appear once; failed actions do not appear.

---

## Phase 5: Regression Coverage, Production Rollout, and Operations

### Overview

Turn privacy and routing expectations into tests, validate production collection, and document routine ownership and rollback.

### Changes Required

#### 1. Add focused static regressions

**File**: `tests/test_analytics_ui.py`

**Changes**:

- Parse `web/index.html` to verify the tracker is deferred and constrained to production.
- Assert DNT and manual-pageview attributes are present.
- Assert replay/heatmap configuration and API keys are absent.
- Assert the disclosure covers collected categories, team attribution, and password/form exclusions.
- Verify helper contracts for no-op behavior, canonicalization, deduplication, metadata order, identity validation, logout suppression, and allowlisted event fields.
- Verify player deep links produce only a normalized player path.

#### 2. Extend adjacent regression files

**Files**:

- `tests/test_ux_quick_wins.py`
- `tests/test_manage_rosters_ui.py`

**Changes**:

- Keep view-specific metadata and analytics invocation in the same tested contract.
- Assert team analytics identification remains downstream of authenticated global login.
- Avoid brittle assertions against the Cloud script URL beyond the exact required tracker attributes.

#### 3. Add an operator runbook

**File**: `README.md`

**Changes**:

- Add an “Umami Cloud Analytics” subsection near Vercel Setup covering:
  - Dashboard ownership and login URL.
  - Website/domain name and US region.
  - Where to view Realtime, Pages, Sessions, Events, and Usage.
  - The event/data exclusions in this plan.
  - DNT/ad-blocker undercounting as expected behavior.
  - Hobby usage monitoring; Umami counts page hits, custom events, and stored event/session properties toward usage.
  - How to disable collection and how to remove historical data.
- Do not put account email, password, API keys, or private dashboard links in README.

#### 4. Roll out in two checkpoints

**External systems**: GitHub, Vercel, Umami Cloud

**Changes**:

1. Deploy Phases 1–3 first with anonymous page views only.
2. With DNT off and ad blocking disabled, visit a unique sequence of production hash routes.
3. Inspect Umami Realtime and browser Network payloads for correct redacted URLs/titles.
4. Observe anonymous data for 24–48 hours and confirm no query/filter/form data appears.
5. Deploy Phase 4 team attribution and events.
6. Validate one successful and one failed login, a logout, and one safe event.
7. Review Usage after one week and again after one month.

#### 5. Define rollback

**Files**: `web/index.html`, `web/app.js`

**Changes**:

- Emergency stop: remove or comment out only the Umami tracker script. All helpers already no-op, so QPFL behavior remains intact.
- Full code rollback: revert the tracker, analytics helpers/call sites, footer, styles, and analytics tests together.
- Historical deletion: use Umami Cloud's website reset/delete controls only after exporting data if retention is desired.
- Credential incident: rotate the Cloud account credential. The public website UUID in HTML is not a secret and does not grant dashboard/API access.

### Success Criteria

#### Automated Verification

- [ ] Analytics-focused tests pass: `python3 -m pytest tests/test_analytics_ui.py -q`
- [ ] Adjacent UX/auth/accessibility tests pass: `python3 -m pytest tests/test_ux_quick_wins.py tests/test_manage_rosters_ui.py tests/test_accessibility_ui.py -q`
- [ ] Full suite passes: `python3 -m pytest -q`
- [ ] JavaScript syntax is valid: `node --check web/app.js`
- [ ] No whitespace errors remain: `git diff --check`
- [ ] No API credential is present in implementation files: `! rg -n "UMAMI_API_KEY|Authorization: Bearer" web tests README.md vercel.json`
- [ ] Analytics privacy tests reject password, comment, condition, search, lineup, and trade payloads: `python3 -m pytest tests/test_analytics_ui.py -q`

#### Manual Verification

- [ ] Anonymous production route and title data are correct for 24–48 hours before identity is enabled.
- [ ] Network inspection confirms filter/search/form values never leave for Umami.
- [ ] Team login attribution works only after valid authentication.
- [ ] Dashboard Realtime, Pages, Sessions, Events, and Usage are understandable to the commissioner.
- [ ] Localhost and previews remain silent.
- [ ] Mobile layout remains usable with the new footer.
- [ ] Removing the tracker script stops collection without affecting QPFL.

---

## Testing Strategy

### Static and Unit-Level Tests

- Treat tracker attributes and disclosure copy as data/privacy contracts.
- Test canonical route construction from representative hashes:
  - `#home` → `/#home`
  - `#matchups/week/6` → `/#matchups/week/6`
  - `#transactions?q=smith&type=TRADE` → `/#transactions`
  - `#teams/compare?team1=GSA&team2=AST` → `/#teams/compare`
  - `#player/[profile-key]` → `/#player/profile`
- Test repeated metadata calls do not double-count the same URL/title.
- Test blocked or unavailable `window.umami` never throws.
- Test identities are constrained to known team abbreviations.
- Test all event names and values come from fixed allowlists.

### Integration Tests

- Run the existing API tests to ensure analytics remains downstream of successful mutations.
- Run the full repository suite because `web/app.js` is a shared application bundle.
- Do not make automated tests call Umami Cloud; production collection is verified manually in Realtime.

### Manual Testing Steps

1. Confirm localhost and preview deployments send no Umami request.
2. Open production with DNT off and ad blocking disabled.
3. Navigate Home → Matchups Week 6 → a team roster → Transactions with filters → a player profile.
4. Verify Realtime shows redacted canonical paths and the correct titles exactly once.
5. Inspect request payloads for absence of route query parameters and form contents.
6. Attempt an invalid login and confirm no identity is created.
7. Complete a valid login and confirm only the team abbreviation is associated.
8. Log out and confirm the logout event is last until reload or another successful login.
9. Enable DNT and confirm new navigation does not collect.
10. Block the tracker and confirm all QPFL features still work.

## Privacy and Data Contract

### Allowed

- Canonical redacted route
- Final document title
- Referrer domain/path as collected by Umami
- Browser, operating system, device type, screen size, language
- Approximate country/region as derived by Umami
- Anonymous session/visit timing
- Public QPFL team abbreviation after validated login
- Fixed event name and the explicitly listed low-cardinality properties

### Prohibited

- Passwords or any transformation/hash of a password
- Owner names, email addresses, or other individual identity
- IP addresses added by QPFL code
- Comments, trade conditions, or commissioner reasons
- Lineup/player/pick selections or transaction payloads
- Player names/profile keys in analytics URLs or events
- Search text, filter query values, team-comparison query values
- DOM snapshots, replay, heatmaps, keystrokes, or arbitrary click text
- Cloud account credentials, API keys, or private dashboard/share URLs

Any future event or property must update this plan's successor documentation, disclosure copy, allowlist, tests, and usage estimate before deployment.

## Performance and Cost Considerations

- The tracker is deferred and must not delay initial QPFL rendering.
- Manual page-view deduplication avoids inflated counts during data rerenders and filter changes.
- No heartbeat events are added; this limits cost and avoids misleading engagement totals.
- Umami Cloud usage counts page hits, custom events, and stored event/session properties. Review the Cloud Usage screen after one week and monthly thereafter.
- Ad blockers and DNT cause expected undercounting. Do not proxy around user choices.
- Visit duration is calculated from time between events; single-event visits do not have reliable duration.

## Migration Notes

- There is no historical backfill. Analytics begins when the production tracker is deployed.
- The public website UUID may be committed because it can submit events but cannot read the private dashboard; it is not an API credential.
- If the canonical QPFL domain changes, update both the Umami website Domain and `data-domains` in the same deployment.
- Adding GitHub Pages or a custom domain later is an explicit expansion of collection scope and requires updating the disclosure and tests.
- Existing QPFL localStorage sessions require no migration. They are revalidated through `performLogin()` before team identification.

## References

- [Umami Cloud overview](https://docs.umami.is/docs/cloud)
- [Create and verify a Cloud account](https://docs.umami.is/docs/cloud/sign-up)
- [Add a website](https://docs.umami.is/docs/add-a-website)
- [Install the tracking code](https://docs.umami.is/docs/collect-data)
- [Tracker configuration](https://docs.umami.is/docs/tracker-configuration)
- [Track single-page applications and hash routes](https://docs.umami.is/docs/guides/track-single-page-apps)
- [Tracker functions and manual page views](https://docs.umami.is/docs/tracker-functions)
- [Identify logged-in users](https://docs.umami.is/docs/guides/identify-logged-in-users)
- [Distinct IDs](https://docs.umami.is/docs/distinct-ids)
- [Metric definitions, including visit duration](https://docs.umami.is/docs/metric-definitions)
- [Umami Cloud FAQ and usage accounting](https://docs.umami.is/docs/cloud/faq)
- [Umami Cloud changelog](https://docs.umami.is/docs/cloud/changelog)
- [Private-by-default analytics sharing](https://docs.umami.is/docs/enable-share-url)
