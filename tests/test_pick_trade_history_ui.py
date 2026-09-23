"""Hovering a pick that changed hands shows the trade that moved it.

The pick pages and the Transactions page read the same trade ledger, so a
pick's provenance can't say one thing on the Pick Tracker and another on a
trade card. These run the real browser code against the real exports.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

# Reads the live exported site data, which the scorer rewrites every run.
pytestmark = pytest.mark.live_data

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'
WEB_STYLES = PROJECT_ROOT / 'web' / 'styles.css'

HARNESS = r"""
const fs = require('fs');
const noop = () => {};
const element = {
    addEventListener: noop,
    appendChild: noop,
    querySelector: () => null,
    querySelectorAll: () => [],
    setAttribute: noop,
    removeAttribute: noop,
    classList: { add: noop, remove: noop, toggle: noop, contains: () => false },
    style: {},
    dataset: {},
    focus: noop,
    contains: () => false,
};
global.document = {
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener: noop,
    createElement: () => ({ ...element, style: {} }),
    body: element,
    documentElement: element,
};
global.window = {
    addEventListener: noop,
    innerWidth: 1200,
    location: { hash: '', pathname: '/', search: '' },
};
global.location = window.location;
global.history = { pushState: noop, replaceState: noop };
global.localStorage = { getItem: () => null, setItem: noop, removeItem: noop };
global.sessionStorage = global.localStorage;
global.fetch = () => new Promise(() => {});
global.setTimeout = global.setInterval = () => 0;
global.clearTimeout = global.clearInterval = global.requestAnimationFrame = noop;
global.QPFL_API = { url: value => value };
"""

PROBE = r"""
data = {
    ...JSON.parse(fs.readFileSync('web/data.json', 'utf8')),
    transactions: JSON.parse(
        fs.readFileSync('web/data/shared/transactions.json', 'utf8')
    ).transactions,
    drafts: JSON.parse(fs.readFileSync('web/data/shared/drafts.json', 'utf8')).drafts,
    draft_picks: JSON.parse(
        fs.readFileSync('web/data/seasons/2026/draft_picks.json', 'utf8')
    ),
};

const picks = data.draft_picks;
const moved = p => (p.previous_owners || []).length > 0 || p.current_owner !== p.original_team;
const tagged = html => (html.match(/data-pick-history="([^"]+)"/g) || [])
    .map(m => m.slice('data-pick-history="'.length, -1));

// A pick that was traded away and later reacquired is back home with an
// empty previous_owners, so the pick data alone cannot see it moved.
const hasHistory = picks.filter(pickHasTradeHistory);
const roundTripped = hasHistory.filter(p => !moved(p));
const movedPicks = picks.filter(moved);
const teams = [...new Set(picks.map(p => p.current_owner))].sort();

// Every surface that lists picks must tag exactly the picks that moved.
const surfaces = {
    chip: picks.flatMap(p => tagged(pickChipHtml(p, p.current_owner))),
    tradedAway: picks
        .filter(p => p.current_owner !== p.original_team)
        .flatMap(p => tagged(pickChipHtml(p, p.original_team, { tradedAway: true }))),
    compare: teams.flatMap(t => tagged(renderComparePicks(getCompareTeamPicks(t), t))),
    tradeBuilder: teams.flatMap(t => getOwnedPicks(t).map(p => p.historyKey).filter(Boolean)),
};

// Keys have to survive the round trip back to a pick.
const allKeys = [...new Set(Object.values(surfaces).flat())];
const unresolved = allKeys.filter(key => !picks.some(p => pickLedgerKey(p) === key));

const withText = hasHistory.filter(p => pickTradeTooltip(p)).length;
const inertTagged = picks
    .filter(p => !pickHasTradeHistory(p))
    .flatMap(p => tagged(pickChipHtml(p, p.current_owner))).length;
const inertWithText = picks.filter(p => !pickHasTradeHistory(p) && pickTradeTooltip(p)).length;

// A pick acquired in one logged trade, and one that changed hands repeatedly.
const single = picks.find(p => String(p.year) === '2027'
    && p.draft_type === 'offseason_taxi' && p.round === 1 && p.original_team === 'CGK');
const chain = picks.find(p => String(p.year) === '2027'
    && p.draft_type === 'offseason' && p.round === 1 && p.original_team === 'CWR');

console.log(JSON.stringify({
    movedCount: movedPicks.length,
    historyCount: hasHistory.length,
    roundTripped: roundTripped.map(p =>
        `${p.year} ${p.draft_type} R${p.round} ${p.original_team}`),
    taggedPerSurface: Object.fromEntries(
        Object.entries(surfaces).map(([name, keys]) => [name, new Set(keys).size])
    ),
    tradedAwayCount: picks.filter(p => p.current_owner !== p.original_team).length,
    unresolved,
    withText,
    inertTagged,
    inertWithText,
    single: pickTradeTooltip(single),
    chainHops: pickTradeHops(chain).map(hop => ({
        date: getTransactionDate(hop.tx).dateStr,
        from: hop.from,
        to: hop.to,
    })),
    // Where the ledger leaves each pick, against where the pick data says it
    // ended up. Franchises get renamed, so compare normalised codes.
    endpoints: picks
        .filter(p => pickTradeHops(p).length)
        .map(p => {
            const last = pickTradeHops(p).at(-1);
            const norm = t => (t ? franchiseSuccessionCodes(t).at(-1) : null);
            return {
                pick: `${p.year} ${p.draft_type} R${p.round} ${p.original_team}`,
                ledger: norm(last.to),
                owner: norm(p.current_owner),
            };
        }),
}));
"""


def run_probe():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for the pick trade-history regression test')

    app = WEB_APP.read_text(encoding='utf-8')
    startup = 'loadData();\ncheckRefresh();'
    assert app.count(startup) == 1
    app = app.replace(startup, '')

    completed = subprocess.run(
        [node],
        cwd=PROJECT_ROOT,
        input=f'{HARNESS}\n{app}\n{PROBE}',
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.fixture(scope='module')
def probe():
    return run_probe()


def test_every_pick_surface_tags_the_picks_with_a_history(probe):
    history = probe['historyCount']
    assert history > 0
    assert probe['taggedPerSurface']['chip'] == history
    assert probe['taggedPerSurface']['compare'] == history
    assert probe['taggedPerSurface']['tradeBuilder'] == history
    assert probe['taggedPerSurface']['tradedAway'] == probe['tradedAwayCount']


def test_reacquired_picks_keep_their_history(probe):
    """Back home with an empty previous_owners, so only the ledger remembers
    the round trip -- the chip still has to offer it."""
    assert probe['roundTripped']
    assert probe['historyCount'] > probe['movedCount']


def test_picks_with_no_history_get_no_hover_target(probe):
    """A pick with nothing behind it must not look hoverable."""
    assert probe['inertTagged'] == 0
    assert probe['inertWithText'] == 0


def test_every_tagged_key_resolves_back_to_a_pick(probe):
    assert probe['unresolved'] == []


def test_most_picks_with_history_resolve_to_a_logged_trade(probe):
    """A handful were seeded from the league spreadsheet with no trade behind
    them; those fall back to a "no transaction on record" card. Everything
    else has to find its trade."""
    assert probe['withText'] >= probe['historyCount'] - 2


def test_single_trade_pick_names_date_teams_and_return(probe):
    text = probe['single']
    assert '10/21/2025' in text
    assert 'CGK → S/T' in text
    # What S/T gave up for it, straight off the trade card.
    assert 'S/T 2027 3rd round taxi' in text


def _as_date(text):
    month, day, year = (int(part) for part in text.split('/'))
    return (year, month, day)


def test_multi_hop_pick_lists_every_trade_oldest_first(probe):
    """Trades are stamped to the week, so two offseason trades tie on the
    league timeline and only their dates can order them."""
    hops = probe['chainHops']
    assert len(hops) >= 3
    dates = [_as_date(hop['date']) for hop in hops]
    assert dates == sorted(dates)
    assert all(hop['from'] and hop['to'] for hop in hops)


def test_ledger_leaves_each_pick_where_the_pick_data_has_it(probe):
    """The last trade to touch a pick has to hand it to whoever owns it now.

    Where these disagree, either the pick data missed a trade or the ledger
    has one the pick data never applied -- and the hover card would show a
    history that contradicts the chip it is attached to.
    """
    disagreements = [
        f'{row["pick"]}: ledger ends at {row["ledger"]}, pick data says {row["owner"]}'
        for row in probe['endpoints']
        if row['ledger'] != row['owner']
    ]
    assert disagreements == []


def test_hover_card_escapes_the_pick_tracker_scroll_container():
    """An absolutely positioned tooltip would be clipped by the Pick Tracker's
    horizontal scroll container, so the card is fixed to the viewport."""
    styles = WEB_STYLES.read_text(encoding='utf-8')
    card = styles[styles.index('.pick-history-card {') :]
    card = card[: card.index('}')]
    assert 'position: fixed' in card
    assert 'pointer-events: none' in card

    app = WEB_APP.read_text(encoding='utf-8')
    assert 'document.body.appendChild(pickHistoryCard)' in app
    # Hidden again whenever the anchor could have moved out from under it.
    assert "window.addEventListener('scroll', hidePickHistoryCard, true)" in app
    assert "window.addEventListener('resize', hidePickHistoryCard)" in app


def test_pick_surfaces_load_the_transaction_ledger():
    """The hover card reads data.transactions, which these views did not load."""
    app = WEB_APP.read_text(encoding='utf-8')
    loader = app[app.index('async function prepareViewData') :]
    loader = loader[: loader.index('\n// Map of view name to its render function')]
    for view in ("view === 'teams'", "view === 'drafts'"):
        block = loader[loader.index(view) :]
        block = block[: block.index('} else if') if '} else if' in block else len(block)]
        assert "ensureSharedResource('transactions')" in block, view
