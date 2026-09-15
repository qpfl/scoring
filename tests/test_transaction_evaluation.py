import json
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def run_transaction_probe():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for the transaction evaluator regression test')

    app = (PROJECT_ROOT / 'web' / 'app.js').read_text(encoding='utf-8')
    startup = 'loadData();\ncheckRefresh();'
    assert app.count(startup) == 1
    app = app.replace(startup, '')

    harness = r'''
const fs = require('fs');
const noop = () => {};
const element = {
    addEventListener: noop,
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
'''
    probe = r'''
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
sharedData = {
    hall_of_fame: JSON.parse(
        fs.readFileSync('web/data/shared/hall_of_fame.json', 'utf8')
    ),
};
// What ensureSeasonTeamIdentities() fetches in the browser.
seasonTeamIdentities = Object.fromEntries(
    JSON.parse(fs.readFileSync('web/data/index.json', 'utf8')).seasons.map(season => {
        const meta = JSON.parse(
            fs.readFileSync(`web/data/seasons/${season}/meta.json`, 'utf8')
        );
        return [season, Object.fromEntries(
            (meta.teams || []).map(team => [team.abbrev, { name: team.name || '', owner: team.owner || '' }])
        )];
    })
);

const trade = data.transactions.find(tx =>
    (tx.message || '').startsWith('9/3/2023 | To Connor:')
);
const flip = data.transactions.find(tx =>
    (tx.message || '').startsWith('10/9/2024 | To Joe/Censored:')
);
const summarizeTerminal = terminal => ({
    resolved: terminal.resolved,
    skipped: terminal.skipped || false,
    reason: terminal.reason || null,
    player: terminal.selection?.player || null,
    team: terminal.draftingTeam || null,
    points: terminal.performance?.points || 0,
    currentOwner: terminal.currentOwner || null,
});
const jrw = resolvePickTerminal(
    parsePickPhrase('JRW 2024 1st round pick', 2023),
    'AYP'
);
const taxi = resolvePickTerminal(
    parsePickPhrase('JDK 2025 1st round taxi pick', 2024),
    'AYP'
);
const conditional = resolvePickTerminal(
    parsePickPhrase(
        "JDK 2025 1st round midseason pick (if Rashee Rice doesn't play the first 7 games)",
        2024
    ),
    'AYP'
);
const slot = resolvePickTerminal(parsePickPhrase('Pick 3.05', 2024), 'CWR');
const passed = resolvePickTerminal(
    parsePickPhrase('RPA 2025 4th round pick', 2025),
    'RPA'
);
const future = resolvePickTerminal(
    parsePickPhrase('CWR 2026 1st round midseason pick', 2025),
    'CWR'
);
const lower = resolvePickTerminal(
    parsePickPhrase("The lower of AYP/CGK's 2024 2nd round picks", 2023),
    'S/T'
);
const higher = resolvePickTerminal(
    parsePickPhrase('Higher of RPA and CWR 2025 4th round taxi', 2024),
    'RPA'
);
const henry = transactionFranchisePerformance(
    getPlayerCareerProfile('Derrick Henry'),
    'AYP',
    flip
);
const rice = transactionFranchisePerformance(
    getPlayerCareerProfile('Rashee Rice'),
    'AYP',
    flip
);
const derived = derivedPickValue(
    parsePickPhrase('CWR 2025 1st round pick', 2023),
    transactionTimelineMoment(trade),
    0,
    'AYP'
);
// The pick Griff used on a QB he never started: points scored from the
// taxi squad or the bench are nobody's production.
const benchOnly = resolvePickTerminal(
    parsePickPhrase('RPA 2025 2nd round taxi', 2024),
    'GSA'
);
const verdict = tradeVerdict(trade);
const card = renderTransactionItem(trade);
const readable = html => html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
const cardText = readable(card);

// Picks that left our trade record before the draft: whatever they became
// was drafted by a team that isn't a party to the card, so their points
// must not land on either side's total.
const offRecordTrade = data.transactions.find(tx =>
    (tx.message || '').startsWith('1/20/2021 | TO MPA:')
);
const offRecordVerdict = tradeVerdict(offRecordTrade);
const offRecordCard = renderTransactionItem(offRecordTrade);
const offRecordCardText = readable(offRecordCard);
const offRecordPick = derivedPickValue(
    parsePickPhrase('CGK 2022 1st round pick', 2021),
    transactionTimelineMoment(offRecordTrade),
    0,
    'GSA'
);
// Same idea one level up the chain: the pick was flipped on by a team that
// isn't the one holding it here, so the return went to them.
const offRecordFlip = derivedPickValue(
    parsePickPhrase('AYP 2026 3rd rounder', 2022),
    transactionTimelineMoment(
        data.transactions.find(tx =>
            (tx.message || '').includes('Conditions on AYP 2025 1st round pick removed')
        )
    ),
    0,
    'AYP'
);
// The league has had two Connors, so an old message that says only
// "To Redacted:" is ambiguous — the transaction title spells out which one.
const ambiguousTrade = data.transactions.find(tx =>
    (tx.message || '').startsWith('9/11/2024 | To Redacted:')
);
const ambiguousSides = normalizedTradeSides(ambiguousTrade).map(side => side.team);
const ambiguousText = readable(renderTransactionItem(ambiguousTrade));
// The same disambiguation has to work in the other direction: a bare
// "Connor" in a Kaminska trade must not resolve to Reardon.
const kaminskaTrade = data.transactions.find(tx =>
    String(tx.team || '') === 'Trade between Connor Kaminska and Arnav'
);
const kaminskaSides = normalizedTradeSides(kaminskaTrade).map(side => side.team);

// Historical cards name a franchise by who owned it THAT season, not by
// whoever owns it now.
const seasonLabels = {
    cwr2024: seasonTeamLabel('CWR', 2024),
    cwr2026: seasonTeamLabel('CWR', 2026),
    cwr2021: seasonTeamLabel('CWR', 2021),
    jj2020: seasonTeamLabel('J/J', 2020),
    jj2024: seasonTeamLabel('J/J', 2024),
    rpa2020: seasonTeamLabel('RPA', 2020),
    // No season-by-season history for a retired code: fall back, never
    // resolve through franchise succession to whoever inherited the seat.
    mpa2021: seasonTeamLabel('MPA', 2021),
    unknownSeason: seasonTeamLabel('CWR', undefined),
};

// Roster moves name the franchise as it was that season, not as it is now.
const rosterMoveTitles = {};
for (const [key, prefix] of [
    ['cgk2024', '12/5/2024 | Added RB Isaac Guerendo'],
    ['rpa2024', '11/21/2024 | Activated QB Matthew Stafford'],
    ['cgk2025', 'Added WR Isaac TeSlaa'],
]) {
    const tx = data.transactions.find(candidate => (candidate.message || '').includes(prefix));
    rosterMoveTitles[key] = tx ? readable(renderTransactionItem(tx)).slice(0, 90) : null;
}
// A transposed year in the source log must not render or sort as year 2302.
const typoTx = data.transactions.find(tx => (tx.message || '').startsWith('9/20/2302'));
const repairedDate = getTransactionDate(typoTx).dateStr;
const repairedSorts = new Date(transactionTime(typoTx)).getFullYear();

const completedPickAudit = { checked: 0, falsePending: [] };
for (const tx of data.transactions) {
    for (const side of (normalizedTradeSides(tx) || [])) {
        for (const item of side.items) {
            const pickInfo = resolvePickAsset(item, Number(tx.season));
            if (!pickInfo || !findDraftForPick(pickInfo)) continue;
            completedPickAudit.checked += 1;
            const terminal = resolvePickTerminal(pickInfo, side.team);
            if (!terminal.resolved && !terminal.skipped) {
                completedPickAudit.falsePending.push({ season: tx.season, item });
            }
        }
    }
}

console.log(JSON.stringify({
    jrw: summarizeTerminal(jrw),
    benchOnly: summarizeTerminal(benchOnly),
    taxi: summarizeTerminal(taxi),
    conditional: summarizeTerminal(conditional),
    slot: summarizeTerminal(slot),
    passed: summarizeTerminal(passed),
    future: summarizeTerminal(future),
    lower: summarizeTerminal(lower),
    higher: summarizeTerminal(higher),
    henry: henry.points,
    rice: rice.points,
    derived,
    verdict: verdict.sides.map(side => ({
        team: side.team,
        direct: side.direct,
        derived: side.derived,
        pending: side.pending,
        untracked: side.untracked,
        total: side.total,
    })),
    margin: verdict.margin,
    provisional: verdict.provisional,
    untracked: verdict.untracked,
    offRecordPick,
    offRecordFlip,
    offRecordVerdict: {
        totals: offRecordVerdict.sides.map(side => side.total),
        untracked: offRecordVerdict.sides.map(side => side.untracked),
        margin: offRecordVerdict.margin,
        flagged: offRecordVerdict.untracked,
    },
    completedPickAudit,
    rosterMoveTitles,
    repairedDate,
    repairedSorts,
    seasonLabels,
    ambiguousSides,
    kaminskaSides,
    ambiguousCreditsReardon: ambiguousText.includes('91 pts CWR'),
    ambiguousCardNames: ambiguousText,
    ambiguousCreditsKaminska: ambiguousText.includes('pts CGK'),
    card: {
        hasDrakeMaye: cardText.includes('Drake Maye'),
        hasRayDavis: cardText.includes('Ray Davis'),
        hasSkippedCondition: cardText.includes('condition not met'),
        hasHenryPoints: cardText.includes('218 pts AYP'),
        hasRicePoints: cardText.includes('101 pts AYP'),
        hasFalsePending: cardText.includes('owner unknown'),
        // A pick this side flipped away shows the return it fetched, not the
        // player some other team eventually drafted with it.
        hasFlippedPickReturn: cardText.includes('CWR 2025 1st round pick → traded on'),
        creditsRayDavisElsewhere: cardText.includes('0 pts WJK'),
        hasOffRecordNote: cardText.includes('Left AYP in an unrecorded trade'),
        // Badges sit in their own right-hand column at every depth.
        badgeColumns: (card.match(/class="transaction-asset-value"/g) || []).length,
    },
    offRecordCard: {
        creditsLondonElsewhere: offRecordCardText.includes('208 pts CWR'),
        creditsLovElsewhere: offRecordCardText.includes('248 pts JDK'),
        hasOffRecordNote: offRecordCardText.includes('Left GSA in an unrecorded trade'),
        hasPartialTag: offRecordCardText.includes('partial'),
        mutedOtherTeamBadges: (offRecordCard.match(/transaction-performance-badge is-other-team/g) || []).length,
    },
}));
process.exit(0);
'''

    completed = subprocess.run(
        [node],
        cwd=PROJECT_ROOT,
        input=f'{harness}\n{app}\n{probe}',
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_historical_trade_resolves_players_picks_and_conditions():
    result = run_transaction_probe()

    assert result['jrw'] == {
        'resolved': True,
        'skipped': False,
        'reason': None,
        'player': 'Drake Maye (NE)',
        'team': 'AYP',
        'points': 424,
        'currentOwner': None,
    }
    assert result['taxi'] == {
        'resolved': True,
        'skipped': False,
        'reason': None,
        'player': 'Ray Davis (BUF)',
        'team': 'WJK',
        'points': 0,
        'currentOwner': None,
    }
    assert result['conditional']['skipped'] is True
    assert result['conditional']['reason'] == 'condition not met'
    assert result['slot']['player'] == 'Jonnu Smith (MIA)'
    assert result['slot']['points'] == 66
    assert result['passed']['skipped'] is True
    assert result['passed']['reason'] == 'pick was passed'
    assert result['future']['skipped'] is False
    assert result['future']['currentOwner'] == 'S/T'
    assert result['lower']['player'] == 'Brian Thomas Jr. (JAC)'
    assert result['higher']['player'] == 'Wandale Robinson (NYG)'

    # Bench and taxi weeks score nothing: this pick became a QB who never
    # started for the team that drafted him.
    assert result['benchOnly'] == {
        'resolved': True,
        'skipped': False,
        'reason': None,
        'player': 'Shedeur Sanders (CLE)',
        'team': 'GSA',
        'points': 0,
        'currentOwner': None,
    }

    assert result['henry'] == 218
    assert result['rice'] == 101
    # The JDK 2025 1st round taxi pick in this chain became Ray Davis for
    # WJK, so its 9 points stay out of AYP's return and the chain is flagged.
    assert result['derived'] == {'points': 319, 'pending': False, 'untracked': True}
    assert result['verdict'] == [
        {'team': 'CWR', 'direct': 120, 'derived': 0, 'pending': 0, 'untracked': 0, 'total': 120},
        {'team': 'AYP', 'direct': 29, 'derived': 424, 'pending': 0, 'untracked': 1, 'total': 453},
    ]
    assert result['margin'] == 333
    assert result['provisional'] is False
    assert result['untracked'] is True
    assert result['completedPickAudit']['checked'] > 150
    assert result['completedPickAudit']['falsePending'] == []
    assert result['card'] == {
        'hasDrakeMaye': True,
        'hasRayDavis': True,
        'hasSkippedCondition': True,
        'hasHenryPoints': True,
        'hasRicePoints': True,
        'hasFalsePending': False,
        'hasFlippedPickReturn': True,
        'creditsRayDavisElsewhere': True,
        'hasOffRecordNote': True,
        # One badge column per rendered asset row, however deep it sits.
        'badgeColumns': 10,
    }


def test_historical_cards_name_the_owner_of_that_season():
    result = run_transaction_probe()

    assert result['seasonLabels'] == {
        # Jack joined CWR in 2026, so a 2024 card must not credit him.
        'cwr2024': 'Redacted Reardon',
        'cwr2026': 'Redacted Reardon & Jack Reardon',
        # 2021 was the shared CWR/SLS franchise year.
        'cwr2021': 'Connor Reardon & Stephen Schmidt',
        # The J/J seat changed hands entirely.
        'jj2020': 'Ryan P.',
        'jj2024': 'Joe Censored & Censored Ward',
        'rpa2020': 'Miles',
        'mpa2021': 'MPA',
        'unknownSeason': 'Redacted Reardon & Jack Reardon',
    }


def test_roster_moves_name_the_team_of_that_season():
    result = run_transaction_probe()

    # CGK was "Josh Allen's Deleted Tweets" in 2024 and 2025; today it is
    # "2 Billion Dollar Pitts", which must not appear on an old card.
    # (Titles arrive HTML-escaped, so match around the apostrophes.)
    cgk2024 = result['rosterMoveTitles']['cgk2024']
    assert 'Josh Allen' in cgk2024 and 'Deleted Tweets' in cgk2024
    assert '2 Billion Dollar Pitts' not in cgk2024
    assert 'Kaminska' in cgk2024

    # RPA's 2024 name, not the name it carries now.
    assert 'Canseco' in result['rosterMoveTitles']['rpa2024']
    assert 'Pharmacist' in result['rosterMoveTitles']['rpa2024']

    cgk2025 = result['rosterMoveTitles']['cgk2025']
    assert 'Josh Allen' in cgk2025 and 'Deleted Tweets' in cgk2025
    assert '2 Billion Dollar Pitts' not in cgk2025


def test_a_transposed_year_in_the_log_is_repaired_not_rendered():
    result = run_transaction_probe()

    assert result['repairedDate'] == '9/20/2023'
    assert result['repairedSorts'] == 2023


def test_trade_sides_resolve_ambiguous_owner_names_from_the_trade_title():
    result = run_transaction_probe()

    # "Trade between Redacted Reardon and Joe/Censored": the side that says only
    # "To Redacted:" is Reardon's (CWR), not Kaminska's (CGK).
    assert result['ambiguousSides'] == ['CWR', 'J/J']
    assert result['ambiguousCreditsReardon'] is True
    # Named as of 2024 everywhere on the card — title, header and verdict.
    assert result['ambiguousCardNames'].count('Redacted Reardon') >= 3
    assert 'Jack Reardon' not in result['ambiguousCardNames']
    assert result['ambiguousCreditsKaminska'] is False
    assert 'CGK' in result['kaminskaSides']
    assert 'CWR' not in result['kaminskaSides']


def test_picks_traded_off_record_score_for_nobody_on_the_card():
    result = run_transaction_probe()

    # CGK's 2022 1st became Drake London for CWR and its 2023 1st became
    # Jordan Love for JDK — both after leaving GSA in trades we have no
    # record of, so GSA banks neither.
    assert result['offRecordPick'] == {'points': 0, 'pending': False, 'untracked': True}
    assert result['offRecordVerdict'] == {
        'totals': [299, 482],
        'untracked': [0, 2],
        'margin': 183,
        'flagged': True,
    }
    assert result['offRecordCard']['creditsLondonElsewhere'] is True
    assert result['offRecordCard']['creditsLovElsewhere'] is True
    assert result['offRecordCard']['hasOffRecordNote'] is True
    assert result['offRecordCard']['hasPartialTag'] is True
    assert result['offRecordCard']['mutedOtherTeamBadges'] == 2

    # AYP got its own 2026 3rd back in 2022, but CWR is the team our ledger
    # shows flipping it to RPA in 2025 — that return was CWR's, not AYP's.
    assert result['offRecordFlip'] == {'points': 0, 'pending': False, 'untracked': True}
