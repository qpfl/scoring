import json
import re
from pathlib import Path

from qpfl.constants import STARTER_SLOTS

ROOT = Path(__file__).resolve().parent.parent
LIVING_DOCS = (
    ROOT / 'README.md',
    ROOT / 'CONTRIBUTING.md',
    ROOT / 'docs/API.md',
    ROOT / 'docs/ARCHITECTURE.md',
    ROOT / 'docs/2026_SEASON_CHANGES.md',
    ROOT / 'docs/2026_DRAFT_READINESS_CHECKLIST.md',
    ROOT / 'docs/ROADMAP_2026.md',
)


def test_documented_python_scripts_exist():
    documented = set()
    for path in LIVING_DOCS:
        documented.update(re.findall(r'scripts/[A-Za-z0-9_./-]+\.py', path.read_text()))

    missing = [script for script in sorted(documented) if not (ROOT / script).is_file()]
    assert missing == []


def test_documented_api_endpoints_match_vercel_routes_and_browser_allowlist():
    docs_endpoints = set(re.findall(r'/api/([a-z-]+)', (ROOT / 'docs/API.md').read_text()))
    vercel = json.loads((ROOT / 'vercel.json').read_text())
    route_endpoints = {
        route['src'].removeprefix('/api/')
        for route in vercel['routes']
        if route['src'].startswith('/api/')
    }
    browser_endpoints = set(
        re.findall(r"^\s*'([a-z-]+)',?$", (ROOT / 'web/api-config.js').read_text(), re.M)
    )

    assert docs_endpoints == route_endpoints == browser_endpoints


def test_documented_lineup_example_matches_starter_limits():
    api_docs = (ROOT / 'docs/API.md').read_text()
    match = re.search(r'Submit a lineup:\s*```json\s*(\{.*?\})\s*```', api_docs, re.S)
    assert match is not None
    starters = json.loads(match.group(1))['starters']

    assert set(starters) == set(STARTER_SLOTS)
    assert {position: len(players) for position, players in starters.items()} == STARTER_SLOTS
