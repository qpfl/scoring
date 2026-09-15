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
const verdict = tradeVerdict(trade);
const card = renderTransactionItem(trade);
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
        total: side.total,
    })),
    margin: verdict.margin,
    provisional: verdict.provisional,
    completedPickAudit,
    card: {
        hasDrakeMaye: card.includes('Drake Maye'),
        hasRayDavis: card.includes('Ray Davis'),
        hasSkippedCondition: card.includes('skipped · condition not met'),
        hasHenryPoints: card.includes('228 pts for AYP'),
        hasRicePoints: card.includes('97 pts for AYP'),
        hasFalsePending: card.includes('pending / no recorded draft'),
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
        'points': 580,
        'currentOwner': None,
    }
    assert result['taxi'] == {
        'resolved': True,
        'skipped': False,
        'reason': None,
        'player': 'Ray Davis (BUF)',
        'team': 'WJK',
        'points': 9,
        'currentOwner': None,
    }
    assert result['conditional']['skipped'] is True
    assert result['conditional']['reason'] == 'condition not met'
    assert result['slot']['player'] == 'Jonnu Smith (MIA)'
    assert result['slot']['points'] == 118
    assert result['passed']['skipped'] is True
    assert result['passed']['reason'] == 'pick was passed'
    assert result['future']['skipped'] is False
    assert result['future']['currentOwner'] == 'S/T'
    assert result['lower']['player'] == 'Brian Thomas Jr. (JAC)'
    assert result['higher']['player'] == 'Wandale Robinson (NYG)'

    assert result['henry'] == 228
    assert result['rice'] == 97
    assert result['derived'] == {'points': 334, 'pending': False}
    assert result['verdict'] == [
        {'team': 'CWR', 'direct': 210, 'derived': 0, 'pending': 0, 'total': 210},
        {'team': 'AYP', 'direct': 132, 'derived': 914, 'pending': 0, 'total': 1046},
    ]
    assert result['margin'] == 836
    assert result['provisional'] is False
    assert result['completedPickAudit']['checked'] > 150
    assert result['completedPickAudit']['falsePending'] == []
    assert result['card'] == {
        'hasDrakeMaye': True,
        'hasRayDavis': True,
        'hasSkippedCondition': True,
        'hasHenryPoints': True,
        'hasRicePoints': True,
        'hasFalsePending': False,
    }
