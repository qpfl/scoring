from html.parser import HTMLParser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_INDEX = PROJECT_ROOT / 'web' / 'index.html'
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'
WEB_STYLES = PROJECT_ROOT / 'web' / 'styles.css'


class ControlLabelParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.controls = []
        self.label_targets = set()
        self.label_depth = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'label':
            self.label_depth += 1
        if tag in {'input', 'select', 'textarea'}:
            attributes['_nested_label'] = self.label_depth > 0
            self.controls.append(attributes)
        if tag == 'label' and attributes.get('for'):
            self.label_targets.add(attributes['for'])

    def handle_endtag(self, tag):
        if tag == 'label':
            self.label_depth -= 1


def test_page_has_skip_link_and_main_landmark():
    html = WEB_INDEX.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')

    assert '<a class="skip-link" href="#main-content">Skip to main content</a>' in html
    assert '<main id="main-content" tabindex="-1" aria-busy="true">' in html
    assert '.skip-link:focus' in styles


def test_tabsets_expose_relationships_and_keyboard_navigation():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')

    assert html.count('role="tablist"') >= 8
    assert 'role="tab" aria-selected="true" aria-controls="matchups-week-subview"' in html
    assert 'role="tabpanel" aria-labelledby="matchups-week-tab"' in html
    assert 'function setActiveTab(tablist, activeTab)' in app
    assert "event.key === 'ArrowRight' || event.key === 'ArrowDown'" in app
    assert "event.key === 'Home'" in app
    assert 'panel.hidden = !active;' in app


def test_dialogs_are_modal_and_trap_and_restore_focus():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')

    assert html.count('role="dialog" aria-modal="true"') == 2
    assert 'id="confirm-modal-overlay" class="confirm-modal-overlay" aria-hidden="true"' in html
    assert 'id="player-modal-overlay" class="confirm-modal-overlay" aria-hidden="true"' in html
    assert 'function trapModalFocus(event, overlay)' in app
    assert "document.querySelector('.container')?.setAttribute('inert', '');" in app
    assert 'confirmModalReturnFocus = document.activeElement;' in app
    assert 'playerModalReturnFocus = document.activeElement;' in app
    assert "if (e.key === 'Tab' && activeOverlay)" in app


def test_static_form_controls_have_accessible_names():
    parser = ControlLabelParser()
    parser.feed(WEB_INDEX.read_text(encoding='utf-8'))

    unlabeled = []
    for control in parser.controls:
        control_id = control.get('id')
        has_name = (
            control.get('aria-label')
            or control.get('aria-labelledby')
            or control_id in parser.label_targets
            or control.get('_nested_label')
        )
        if not has_name:
            unlabeled.append(control_id or control)

    assert unlabeled == []


def test_dynamic_controls_are_labeled():
    app = WEB_APP.read_text(encoding='utf-8')

    assert 'for="rc-propose-title"' in app
    assert 'aria-label="Comment on rule proposal"' in app
    assert 'aria-label="${escapeHtml(`Condition for ${item.label}`)}"' in app
    assert 'aria-label="Player for pick ${i}"' in app
    assert 'aria-pressed="${transactionTypeFilter === t.key}"' in app


def test_initial_load_failure_replaces_spinner_with_retry_screen():
    html = WEB_INDEX.read_text(encoding='utf-8')
    app = WEB_APP.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')

    assert 'id="app-load-error-panel" role="alert" hidden' in html
    assert 'id="app-load-retry"' in html
    assert 'function showInitialLoadError()' in app
    assert 'if (!data) {' in app
    assert 'showInitialLoadError();' in app
    assert 'loadData(null, { forceRefresh: true });' in app
    assert 'body:not(.app-loading):not(.app-load-error) .app-spinner' in styles
