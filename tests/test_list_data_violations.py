"""Tests for scripts/list_data_violations.py - the baseline/current violation
reporter used by score.yml to fail only on violations a run itself
introduced, not on a pre-existing one. See docs/ROADMAP_2026.md P3.1 / the
in-season reliability plan, phase 3.4.
"""

import subprocess
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent.parent / 'scripts' / 'list_data_violations.py'


def _run(data_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), '--data-dir', str(data_dir)],
        capture_output=True,
        text=True,
    )


def test_always_exits_zero_even_with_violations(tmp_path):
    """This is a reporting tool, not a gate - it must never fail the step
    that calls it, regardless of what it finds."""
    (tmp_path / 'rosters.json').write_text('{"GSA": "not a list"}')
    result = _run(tmp_path)
    assert result.returncode == 0


def test_prints_one_violation_per_line_with_no_embedded_newlines(tmp_path):
    (tmp_path / 'rosters.json').write_text('{"GSA": "not a list"}')
    result = _run(tmp_path)
    lines = [line for line in result.stdout.splitlines() if line]
    assert len(lines) >= 1
    assert 'rosters.json' in result.stdout
    assert all('\n' not in line for line in lines)


def test_prints_nothing_when_data_dir_is_clean(tmp_path):
    (tmp_path / 'rosters.json').write_text('{}')
    result = _run(tmp_path)
    assert result.stdout.strip() == ''
