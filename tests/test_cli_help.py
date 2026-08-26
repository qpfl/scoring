"""Regression tests for operator CLI argument handling and source hygiene."""

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize(
    'script',
    [
        'scripts/export_for_web.py',
        'scripts/export_historical.py',
        'scripts/sync_lineups_to_excel.py',
    ],
)
def test_operator_cli_help_succeeds_without_writes(script, tmp_path):
    before = set(tmp_path.iterdir())

    result = subprocess.run(
        [sys.executable, str(PROJECT_DIR / script), '--help'],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert 'usage:' in result.stdout.lower()
    assert set(tmp_path.iterdir()) == before


def test_legacy_full_export_is_not_available(tmp_path):
    result = subprocess.run(
        [sys.executable, str(PROJECT_DIR / 'scripts/export_for_web.py'), '--all'],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert not list(tmp_path.iterdir())


def test_web_app_contains_no_literal_nul_bytes():
    assert b'\0' not in (PROJECT_DIR / 'web/app.js').read_bytes()
