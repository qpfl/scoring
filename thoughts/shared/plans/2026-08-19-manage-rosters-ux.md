# Manage Rosters UX Consolidation Implementation Plan

## Overview

Consolidate the Manage Rosters page around the tasks managers actually perform. The depth chart becomes the primary roster workspace, player actions become contextual buttons, and trade-related screens become one grouped area instead of several peer-level tabs.

## Current State Analysis

The page exposes eight top-level tabs even though several operate on the same roster data. Taxi activation and standalone release each repeat the active roster, while proposing, reviewing, and advertising trades are separated despite belonging to one workflow. The depth chart is the best roster overview but currently supports ordering only.

## Desired End State

Managers land on a single Roster workspace where they can review and reorder the active roster, release or begin trading a player, and activate or trade a taxi player. The top navigation contains four clear areas: Roster, Lineup, Add Players, and Trades. Trade proposal, pending trades, and trade-block editing remain separate views within the grouped Trades area.

### Key Discoveries

- The eight current tabs are defined together in `web/index.html:326`, while the related transaction panels already use stable IDs that can be reused.
- The depth chart renderer in `web/app.js:8707` already has the complete active-roster grouping and ordering state needed for the new default workspace.
- Release, taxi activation, and trade proposal functions already call the required APIs and confirmation modal; the UX can reuse the endpoints without a new backend workflow.
- `getTeamData` in `web/app.js:7254` does not split flat roster data by the existing `taxi` flag, so the consolidated roster view must normalize active and taxi players first.
- Manage Rosters styles begin at `web/styles.css:4720` and can be extended with compact, responsive player-action controls.
- Taxi and free-agent actions already treat week `0` as offseason when recording transactions, but their required-field checks incorrectly rejected that value before execution.

## What We're NOT Doing

- Adding transaction endpoints or changing their payloads or roster storage formats.
- Removing confirmation prompts for destructive actions.
- Combining lineup submission with roster transactions.
- Redesigning unrelated public roster, matchup, or transaction-history pages.
- Publishing or pushing the implementation without explicit user approval.

## Implementation Approach

Preserve the existing transaction functions and DOM IDs, then add a small navigation and action-orchestration layer around them. This keeps the API contract stable while reducing navigation and duplicated roster selection. Legacy Taxi and Release panels remain as internal workflow support during this refactor, but they are removed from the primary navigation. Correct the existing required-field validation so week `0` remains a valid offseason transaction value.

## Phase 1: Consolidated Navigation

### Changes Required

#### Manage Rosters markup

**File**: `web/index.html`

**Changes**:

- Reduce primary tabs to Roster, Lineup, Add Players, and Trades.
- Make Roster the default view.
- Add one secondary trade navigation for New Trade, Pending, and Trade Block.
- Collapse team name and avatar controls into a Team Settings disclosure within Lineup.
- Add an action panel and taxi section to the Roster view.

### Success Criteria

#### Automated Verification

- [x] `node --check web/app.js` passes.
- [x] Existing DOM IDs used by transaction functions remain unique.

#### Manual Verification

- [ ] Only four primary management choices appear.
- [ ] The active primary tab remains Trades while moving among its three subviews.

## Phase 2: Unified Roster Actions

### Changes Required

#### Roster normalization and contextual actions

**File**: `web/app.js`

**Changes**:

- Normalize flat and nested roster data into active and taxi collections.
- Add Drop and Trade buttons to each active depth-chart row.
- Add Activate and Trade buttons to each taxi row.
- Reuse existing confirmation and execution functions, routing progress messages to the visible Roster action panel.
- Preselect a player when the Trade shortcut opens the Trades area.
- Keep depth-order dirty state intact when opening actions.

### Success Criteria

#### Automated Verification

- [x] Existing API tests pass, including offseason taxi and free-agent actions.
- [x] JavaScript syntax validation passes.

#### Manual Verification

- [ ] Drop opens the existing destructive confirmation for the selected active player.
- [ ] Trade opens New Trade with the selected active or taxi player already included.
- [ ] Activate shows only same-position active players as release candidates.
- [ ] Depth chart save and undo behavior remains unchanged.

## Phase 3: Responsive and Accessible Presentation

### Changes Required

#### Manage Rosters styles

**File**: `web/styles.css`

**Changes**:

- Style the four primary tabs and secondary Trades navigation as distinct levels.
- Add compact player-action buttons with clear danger, trade, and activation treatments.
- Make depth rows and action panels wrap cleanly on narrow screens.
- Preserve visible focus states and meaningful button labels.

### Success Criteria

#### Automated Verification

- [x] `git diff --check` passes.
- [x] Full Python test suite passes.

#### Manual Verification

- [ ] Player names and actions remain readable on mobile widths.
- [ ] Every icon/action has an accessible text label.
- [ ] Disabled and loading states remain understandable.

## Testing Strategy

### Unit Tests

- Retain the existing transaction API suite as regression coverage.
- Add focused frontend markup assertions for the consolidated navigation and contextual controls.

### Integration Tests

- Validate login initialization, default Roster selection, trade shortcut preselection, drop confirmation, taxi activation selection, and trade subnavigation.

### Manual Testing Steps

1. Log in and confirm Roster is the initial workspace.
2. Reorder a position, save it, and undo a second unsaved reorder.
3. Start a trade from an active player and confirm that player is selected.
4. Start a release and verify the correct player appears in the confirmation.
5. Activate a taxi player and verify only same-position release options appear.
6. Move among New Trade, Pending, and Trade Block while the Trades primary tab stays active.
7. Repeat the primary flows at a narrow viewport.

## Performance Considerations

All interactions reuse data already loaded for the page. The consolidation adds no requests until a manager confirms an existing transaction.

## Migration Notes

No data migration is required. Existing API actions, payloads, stored roster formats, and transaction logs remain compatible.

## References

- Manage Rosters markup: `web/index.html:301`
- Manage workflow logic: `web/app.js:7074`
- Unified roster actions: `web/app.js:8553`
- Manage Rosters styles: `web/styles.css:4720`
