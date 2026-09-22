"""Pick Tracker page: every team's future draft picks on one Drafts subview."""

import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_INDEX = PROJECT_ROOT / 'web' / 'index.html'
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'
WEB_STYLES = PROJECT_ROOT / 'web' / 'styles.css'
DRAFT_PICKS = PROJECT_ROOT / 'data' / 'draft_picks.json'


def test_pick_tracker_subnav_tab_present():
    html = WEB_INDEX.read_text(encoding='utf-8')
    assert 'data-parent="drafts" data-subview="picks">Pick Tracker' in html
    # Matches the role/aria wiring the other subnav tabs use, so keyboard
    # navigation and activateGenericSubview both work.
    assert 'role="tab" aria-selected="false" aria-controls="drafts-picks-subview"' in html


def test_pick_tracker_subview_containers_present():
    html = WEB_INDEX.read_text(encoding='utf-8')
    assert 'id="drafts-picks-subview"' in html
    assert 'id="pick-tracker-type-filters"' in html
    assert 'id="pick-tracker-container"' in html


def test_renderer_and_shared_chip_helper_exist():
    app = WEB_APP.read_text(encoding='utf-8')
    assert 'function renderPickTracker(' in app
    assert 'function pickChipHtml(' in app
    assert 'function pickTrackerTeamPicks(' in app


def test_picks_subview_routes_to_pick_tracker():
    app = WEB_APP.read_text(encoding='utf-8')
    renderers = app[app.index('const VIEW_RENDERERS') :]
    renderers = renderers[: renderers.index('\n};')]
    assert "subview === 'picks'" in renderers
    assert 'renderPickTracker()' in renderers


def test_roster_pick_inventory_uses_shared_helper():
    """The roster renderer must not keep its own copy of the chip markup."""
    app = WEB_APP.read_text(encoding='utf-8')
    assert 'pickChipHtml(p, currentTeam)' in app
    # The old inlined implementation defined these locals; only pickChipHtml should now.
    assert app.count('const isConditionalClaim =') == 1


def test_every_draft_type_has_a_filter_chip():
    """A new draft_type in the data must not silently vanish from the page."""
    picks = json.loads(DRAFT_PICKS.read_text(encoding='utf-8'))['picks']
    data_types = {pick['draft_type'] for pick in picks}

    app = WEB_APP.read_text(encoding='utf-8')
    block = app[app.index('const PICK_DRAFT_TYPES') :]
    block = block[: block.index('];')]
    ui_types = set(re.findall(r"[kK]ey: '([a-z_]+)'", block))

    assert data_types == ui_types


def test_traded_away_pick_style_defined():
    styles = WEB_STYLES.read_text(encoding='utf-8')
    assert '.pick-item.traded-away' in styles
    assert '.pick-tracker-grid' in styles
    # The 10-column grid must scroll inside its own wrapper, not the page body.
    assert '.pick-tracker-scroll' in styles


def _function_source(app: str, name: str) -> str:
    """Source of a top-level `function name(...)` up to its closing brace."""
    start = app.index(f'function {name}(')
    end = app.index('\n}\n', start)
    return app[start:end]


def test_every_pick_surface_derives_from_pick_ownership():
    """Roster list, Pick Tracker, Compare and the trade builder must agree.

    Each of these used to compute "is this my own pick" and "who did it come
    via" from previous_owners itself, so the same pick could read differently
    depending on which page you were on. They all go through pickOwnership now.
    """
    app = WEB_APP.read_text(encoding='utf-8')
    assert 'function pickOwnership(' in app

    for name in ('pickChipHtml', 'getOwnedPicks', 'renderComparePicks'):
        assert 'pickOwnership(' in _function_source(app, name), name

    # The via derivation lives in exactly one place.
    assert app.count('const lastPrevOwner =') == 1


def test_reacquired_pick_is_not_labelled_via():
    """A pick traded away and later bought back belongs to nobody in between.

    previous_owners still records the detour, so without this guard the owner's
    own pick renders as "R2 via <whoever briefly held it>".
    """
    app = WEB_APP.read_text(encoding='utf-8')
    ownership = _function_source(app, 'pickOwnership')
    assert 'pick.current_owner === pick.original_team' in ownership
    assert '!backHome' in ownership


def test_compare_shows_via_and_conditional_picks():
    app = WEB_APP.read_text(encoding='utf-8')
    compare = _function_source(app, 'renderComparePicks')
    assert 'compare-pick-via' in compare
    assert "pickClass = 'conditional'" in compare
    # Conditional claims have to be in the inventory for the class to matter.
    assert 'conditional_claim === teamAbbrev' in _function_source(app, 'getCompareTeamPicks')

    styles = WEB_STYLES.read_text(encoding='utf-8')
    assert '.compare-pick-via' in styles
    assert '.compare-pick-item.conditional' in styles


def test_roster_and_compare_show_traded_away_picks():
    """A team's own picks that now belong to someone else stay visible, greyed out.

    Both surfaces split held vs. traded-away through pickTrackerTeamPicks, the
    same split the Pick Tracker uses, and the chips keep the trade-history hover.
    """
    app = WEB_APP.read_text(encoding='utf-8')
    assert 'pickChipHtml(p, currentTeam, { tradedAway: true })' in app
    assert 'original_team === teamAbbrev' in _function_source(app, 'getCompareTeamPicks')

    compare = _function_source(app, 'renderComparePicks')
    assert 'pickTrackerTeamPicks(' in compare
    assert 'compare-pick-item traded-away' in compare
    assert 'PICK_HISTORY_ATTR' in compare

    styles = WEB_STYLES.read_text(encoding='utf-8')
    assert '.compare-pick-item.traded-away' in styles
