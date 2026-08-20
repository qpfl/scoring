from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_INDEX = PROJECT_ROOT / 'web' / 'index.html'
WEB_STYLES = PROJECT_ROOT / 'web' / 'styles.css'


def test_desktop_homepage_uses_compact_masthead_and_landscape_champion_card():
    html = WEB_INDEX.read_text(encoding='utf-8')
    styles = WEB_STYLES.read_text(encoding='utf-8')

    assert '<div class="league-heading">' in html
    assert '<div class="league-meta">' in html
    assert 'grid-template-columns: auto minmax(0, 1fr) auto;' in styles
    assert '@media (min-width: 901px)' in styles
    assert 'grid-template-columns: minmax(13rem, 17rem) minmax(0, 1fr);' in styles
    assert 'max-width: 17rem;' in styles


def test_mobile_header_restores_centered_stacked_layout():
    styles = WEB_STYLES.read_text(encoding='utf-8')
    mobile = styles[styles.rindex('@media (max-width: 600px)'):]

    assert 'header {' in mobile
    assert 'display: block;' in mobile
    assert 'text-align: center;' in mobile
    assert 'margin: 0 auto 0.5rem;' in mobile
