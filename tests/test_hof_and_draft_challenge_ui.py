import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_APP = PROJECT_ROOT / 'web' / 'app.js'


def test_draft_challenge_results_header_is_not_a_header_element():
    # A bare `header` rule styles the site masthead (flex row, right padding),
    # so a <header> here would inherit that layout.
    app = WEB_APP.read_text(encoding='utf-8')
    assert '<header class="nfl-draft-results-header">' not in app
    assert '<div class="nfl-draft-results-header">' in app


def _record_rows(records):
    app = WEB_APP.read_text(encoding='utf-8')
    helper = app[app.index('function hofRecordRow') : app.index('function renderHallOfFame()')]
    script = f"""
function isMyFranchiseTextMatch() {{ return false; }}
{helper}
process.stdout.write(JSON.stringify({json.dumps(records)}.map(hofRecordRow)));
"""
    result = subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def test_hof_records_split_into_holder_when_and_value():
    team, streak, negative, other = _record_rows(
        [
            "Josh Allen's Deleted Tweets (CGK) - 167 (Week 15, 2025)",
            'Connor Kaminska (CGK) - 11 games (Week 14, 2021 to Week 8, 2022)',
            'QB Spencer Rattler (CWR) - -2 (Week 8, 2025)',
            'Something in another shape',
        ]
    )

    assert "Josh Allen's Deleted Tweets (CGK)" in team
    assert '<span class="record-when">Week 15, 2025</span>' in team
    assert '<span class="record-value">167</span>' in team
    assert '<span class="record-value">11 games</span>' in streak
    assert '<span class="record-value">-2</span>' in negative
    assert 'record-row' not in other
    assert 'Something in another shape' in other
