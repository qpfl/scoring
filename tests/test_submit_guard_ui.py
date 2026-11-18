"""Submission helpers in web/app.js: honest error messages and the
one-press-at-a-time button guard.

Regression context: executeTaxiActivation once referenced an undefined
variable, the ReferenceError was caught and shown as "Network error", and no
taxi activation could be submitted.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'

DOM_STUB = """
class FakeButton {
    constructor(id) {
        this.id = id;
        this.disabled = false;
        this.isConnected = true;
        this.attrs = {};
        const classes = new Set();
        this.classList = {
            add: c => classes.add(c),
            remove: c => classes.delete(c),
            contains: c => classes.has(c),
            toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
        };
    }
    setAttribute(k, v) { this.attrs[k] = v; }
    removeAttribute(k) { delete this.attrs[k]; }
    closest() { return this; }
}
globalThis.Element = FakeButton;
let clickListener = null;
globalThis.document = {
    addEventListener: (type, fn) => { if (type === 'click') clickListener = fn; },
};
const press = button => clickListener({ target: button });
const snapshot = b => ({ disabled: b.disabled, busy: b.classList.contains('is-busy') });
"""


def _helpers(app: str) -> str:
    start = app.index('function describeSubmitError')
    end = app.index('// Function declarations below are hoisted', start)
    return app[start:end]


def _function(app: str, name: str) -> str:
    start = app.index(f'async function {name}(')
    end = app.index('\n}\n', start) + 3
    return app[start:end]


def _run(body: str):
    if not shutil.which('node'):
        pytest.skip('Node.js is required for the submit guard UI test')
    app = WEB_APP.read_text(encoding='utf-8')
    script = f"""
{DOM_STUB}
{_helpers(app)}
console.error = () => {{}};
(async () => {{
{body}
}})().then(out => process.stdout.write(JSON.stringify(out)));
"""
    result = subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def test_only_fetch_failures_are_reported_as_network_errors():
    out = _run("""
        return {
            network: describeSubmitError(new TypeError('Failed to fetch')),
            safari: describeSubmitError(new TypeError('Load failed')),
            bug: describeSubmitError(new ReferenceError('conditionalNotes is not defined')),
            html: describeSubmitError(new SyntaxError('Unexpected token <')),
        };
    """)
    assert out['network'].startswith('Network error')
    assert out['safari'].startswith('Network error')
    assert 'Network error' not in out['bug']
    assert 'conditionalNotes is not defined' in out['bug']
    assert 'unexpected response' in out['html']


def test_repeat_presses_are_ignored_and_the_button_greys_out_until_done():
    out = _run("""
        const button = new FakeButton('go');
        let calls = 0;
        let finish;
        const action = guardSubmission('t', () => {
            calls += 1;
            return new Promise(resolve => { finish = resolve; });
        });
        press(button);
        const first = action();
        const during = snapshot(button);
        press(button);
        await action();  // ignored while the first is in flight
        finish(false);
        await first;
        return { calls, during, after: snapshot(button) };
    """)
    assert out['calls'] == 1
    assert out['during'] == {'disabled': True, 'busy': True}
    assert out['after'] == {'disabled': False, 'busy': False}


def test_button_that_opened_the_confirm_modal_stays_locked_after_success():
    out = _run("""
        const opener = new FakeButton('open');
        const modalConfirm = new FakeButton('confirm');
        confirmModalOpener = opener;
        press(modalConfirm);
        const action = guardSubmission('t', async () => true);
        await action();
        return { opener: snapshot(opener) };
    """)
    assert out['opener'] == {'disabled': True, 'busy': True}


def test_self_managed_buttons_are_only_marked_busy():
    out = _run("""
        const button = new FakeButton('save');
        let finish;
        const action = guardSubmission('t', () => new Promise(r => { finish = r; }),
            { manageButtons: false });
        press(button);
        const run = action();
        const during = snapshot(button);
        finish();
        await run;
        return { during, after: snapshot(button) };
    """)
    assert out['during'] == {'disabled': False, 'busy': True}
    assert out['after'] == {'disabled': False, 'busy': False}


def test_taxi_activation_reaches_the_server():
    app = WEB_APP.read_text(encoding='utf-8')
    out = _run(f"""
        const status = {{ className: '', textContent: '' }};
        document.getElementById = id => (id === 'taxi-status' ? status : null);
        const manageState = {{
            team: 'GSA', password: 'pw',
            selectedTaxiPlayer: {{ name: 'Emmett Johnson', position: 'RB' }},
            selectedReleasePlayer: 'RJ Harvey',
        }};
        const data = {{ current_week: 11 }};
        const MANAGE_CONFIG = {{ apiUrl: '/api/transaction' }};
        const loadData = () => {{}};
        globalThis.setTimeout = () => {{}};
        let sent = null;
        globalThis.fetch = async (url, options) => {{
            sent = JSON.parse(options.body);
            return {{ json: async () => ({{ success: true, message: 'Activated' }}) }};
        }};
        {_function(app, 'executeTaxiActivation')}
        const result = await executeTaxiActivation();
        return {{ result, sent, status: status.textContent }};
    """)
    assert out['result'] is True
    assert out['sent']['action'] == 'taxi_activate'
    assert out['sent']['player_to_activate'] == 'Emmett Johnson'
    assert out['sent']['player_to_release'] == 'RJ Harvey'
    assert out['status'] == 'Activated'
