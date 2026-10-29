# UI polish: from "AI-generated" to crisp sports-data UI

## Context
The site (`web/index.html`, `web/styles.css` ~13k lines, `web/app.js`) works well but reads as AI-generated. On the live site the tells are:
- **Card headers**: a blue accent bar (`.home-card-title::before`), then an UPPERCASE, letter-spaced label (`styles.css:3612`). Same pattern on "Playoff Odds" and elsewhere.
- **Page titles**: centered, gradient-clipped blue text with letter-spacing (`.page-title`, `styles.css:4969`).
- **Nav**: each item is an outlined box. Active state uses a gradient tint, and "My Team" has its own green outline (`.nav-btn`, `styles.css:926–1000`). The header is centered and stacked.
- **Decoration**: 45 linear and 2 radial gradients, a glowing hero on the team page (`.team-hub-hero`), 74 box-shadows, 10 hover lifts (`translateY(-…)`), 9 keyframe animations, 1rem+ card radii, 39 pills or circles.
- **Controls**: outline pill buttons with "→" ("View All Matchups →"), pill segmented tabs, and boxed week numbers next to a large "WEEK" label.
- **Color**: blue is used for scores, ranks, links, labels and bars all at once. Saturated pastel initial-avatars. Blue/red bars under every matchup and standings row.
- **Type**: Inter loaded at 400–900 weights. About 25 ad-hoc font sizes (0.6rem–0.95rem) instead of the scale. 56 uppercase transforms and 78 letter-spacing rules.
- **Emoji** in labels: 🏆 🥉 🥣 🚿 🚽 🎪 👑 🤝 🔒 (`app.js:3136–3142`, `4777–4783`, `3255`, `3271`, `5546`, `6438`, `6481`, `6509`, `10620`, `15076`).

**Target (chosen):** sports-data dense, in the spirit of ESPN, Sleeper or FanGraphs. Neutral dark grays, tight radii, flat surfaces, a left-aligned header with underline tabs, and color only where it carries meaning (win/loss, live, current selection). Remove all emoji. Roll out foundation first.

## Branch
All work happens on a new branch `ui-polish`, created from `main` (`git switch -c ui-polish`) before any edits. Nothing gets committed to `main`. Each phase is its own commit on that branch.

## Principles (apply everywhere)
1. **Flat surfaces.** No gradients (except functional ones, such as a data bar fill), no glows, and no hover lifts. Use one hairline border. Shadows only on floating layers (dropdowns, modals).
2. **Tight geometry.** Radii are 4px (controls), 6px (cards) and 8px (modals). Circles only for avatars. No pills except tiny status chips.
3. **Color has a job.** Neutral text for data. Accent only for the active/selected state and links. Green and red only for W/L and +/−. Scores are neutral by default, and the winner is shown bold rather than colored blue.
4. **Type hierarchy from size and weight, not caps.** Section titles are sentence case, 15–16px, weight 600. Uppercase is allowed only for table column headers (11px, letter-spacing 0.04em max). Weights 400/500/600/700 only.
5. **Quiet controls.** Text links ("All matchups"), no arrows or outline pills. Segmented controls are rectangular, with an underline or filled-neutral active state.

## Phase 1: Foundation (most of the visible win)
All in `web/styles.css` unless noted.

1. **Tokens** (`:root`, line 1):
   - Neutral palette: retune `--bg-deep/#15171f`, `--bg-card`, `--bg-raised`, `--bg-hover` and `--border` toward neutral graphite (less blue tint). Example: `#0f1114 / #16181c / #1c1f24 / #22262c / #2a2e35`.
   - One accent: keep `--accent-primary` but slightly desaturate it. Retire `--accent-tertiary` usages (map them to primary). Drop `--shadow-glow`.
   - Radii: `--radius-sm: 4px; --radius-md: 6px; --radius-lg: 8px; --radius-xl: 8px; --radius-pill` used only for chips.
   - Shadows: set `--shadow-sm/md` to `none`, and keep `--shadow-lg` for popovers.
   - Type: add `--text-2xs: 0.6875rem` (11px). Map the stray 0.6–0.95rem literals to the scale (`2xs/xs/sm/base`) with a careful find/replace.
   - Fonts: `index.html:24` loads only `wght@400;500;600;700`. Replace `font-weight: 800|900` with 700.
2. **Header + nav** (`index.html:41–95`, `.nav-btn` CSS):
   - Header becomes a left-aligned bar: small logo + "QPFL" wordmark (full league name as secondary text on wide screens), season selector and updated time inline, Log In on the right.
   - Nav becomes a horizontal underline-tab bar under the header. Items are plain text, the active item gets a 2px accent underline, and there are no boxes. Remove the special green "My Team" styling (keep it first, unstyled). Preserve the existing `nav-more` mobile overflow and `aria-current` behavior.
3. **Section / card headers**: delete `.home-card-title::before`. Make the titles sentence case, 600 weight, primary text color. The meta on the right ("Week 8", "Through Week 7") is muted and normal case. Apply the same treatment to `.section-title` (`styles.css:5544`) and other uppercase-with-accent-bar headings. Find them via `::before` rules with `width: 4px`/`3px` + `--accent-primary`.
4. **Page titles** (`.page-title`): left-aligned, 24px, weight 700, solid `--text-primary`, no gradient or letter-spacing. Subtitles go muted beneath.
5. **Cards**: 1px border, `--radius-md`, no shadow, no gradient backgrounds. Flatten `.team-hub-hero` (remove the radial/linear gradients).
6. **Buttons and links**:
   - "View all …" buttons become text links (accent color, no border, no arrow).
   - Primary button: solid accent, 4px radius. Secondary: neutral border.
   - Segmented controls (Week View/Schedule, Roster/All Rosters/…, team-abbrev picker): rectangular group with a shared border. Active state is a filled neutral `--bg-raised` with primary text, not filled blue.
   - Week selector (`.week-btn`, `styles.css:1144`): compact 28–32px square-ish cells, 4px radius, no large "WEEK" label (use a small muted label or none).
7. **Tables** (standings, roster): column headers 11px uppercase muted with tight tracking. Rows use hairline dividers and no zebra gradients. Numbers are neutral; bold for season totals/leaders. Rank numbers are neutral, and playoff/elimination lines stay as subtle rules.
8. **Data color audit**: matchup and home score rows show the winner in bold primary and the loser in muted, instead of green/blue. Remove or thin the blue/red bars under every matchup row (keep one thin 2px win-probability bar only where it is informative, in live matchups). Remove the standings row underline bars on home.
9. **Avatars**: keep initials, but use a muted palette (desaturate the team colors in the avatar/color mapping, about 35–45% saturation) and slightly smaller text weight. Check `qpfl/avatars.py` and the color source in `app.js` before changing.
10. **Motion**: remove hover `translateY` lifts and decorative keyframes (keep the loading spinner and live-score pulse if one exists, subtle). Transitions only for color/background, 120ms.

## Phase 2: Emoji removal
- `app.js` bracket labels (`3136–3142`, `4777–4783`; consider consolidating these two duplicate maps into one constant): use plain text ("Playoffs", "Championship", "Consolation Cup", "Mid Bowl", "Sewer Series", "Toilet Bowl", "Jamboree").
- `🏆` champion marker (`3271`) → "1"/bold, or a small inline SVG trophy (monochrome, `currentColor`).
- Rings column (`5546`, `6438`): show a count (e.g. `3`) instead of repeated 🏆.
- `👑` (`6481`), `🏆 Rivalry Week` (`6509`), `🤝` (`15076`), `🔒` (`10620`): remove, or use a small monochrome SVG lock for the locked-starter indicator (it carries meaning).
- `index.html` ⚡/⚠ glyphs: replace with SVG or text.
- Add a tiny inline-SVG icon helper only if 2+ icons are needed (lock, trophy). Otherwise use text.

## Phase 3: Per-view polish
Go through each view after the foundation lands: Home, My Team (lineup/manage), Teams hub, Matchups (cards and expanded rosters), Standings and Playoff Odds, Stats, Transactions, League (history, Hall of Fame, banners), Drafts, Compare, Commissioner. Fix leftovers such as local gradients, uppercase labels, pill chips, inconsistent spacing and over-colored numbers, and align spacing to the `--space-*` scale. Also review mobile (≤480px) for each view.

## Files
- `web/styles.css`: bulk of the work (tokens, then component rules).
- `web/index.html`: header/nav markup, font weights, static glyphs.
- `web/app.js`: emoji strings, "View all →" button markup/classes, score-row color classes, avatar colors.
- `web/preview.html`: check whether it shares the styles and update it if so.
- `tests/test_*_ui.py` (17 read `styles.css`): update string assertions that pin old styles (e.g. emoji labels, class names). Don't weaken accessibility tests.
- Copy this plan to `docs/PLAN_ui_polish.md` (project convention).

## Verification
- `uv run pytest` (UI tests in particular: `tests/test_homepage_ui.py`, `test_accessibility_ui.py`, `test_hall_of_fame_ui.py`, etc.).
- Serve locally (`python -m http.server` from `web/`, or the project's run skill) and screenshot via Chrome at 1440px and 390px: Home, Matchups (expanded), Teams hub, Standings, League/Hall of Fame, Drafts, My Team (logged-out state).
- Grep checks after Phase 1–2: `grep -c 'linear-gradient\|radial-gradient' web/styles.css` near zero (functional only); no `background-clip: text`; no `font-weight: 8|900`; no emoji in `app.js`/`index.html`.
- Contrast check: muted text on the new card bg ≥ 4.5:1 (body) / 3:1 (large).
- Commit Phase 1 on its own on the `ui-polish` branch so the diff can be reviewed before the view-by-view polish. Do not merge into `main` without your sign-off.
