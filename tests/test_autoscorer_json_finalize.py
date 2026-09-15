"""Tests for autoscorer_json.py's --finalize lock exception.

A week that becomes fully final right as the following week's first game
kicks off never gets a chance to be scored with games_final: true - the lock
takes effect first and nothing after it can write to that week again. Without
--finalize, that week is stuck out of standings permanently. --finalize is a
narrow, auditable exception: it only proceeds when the week's existing output
does NOT already show games_final: true, so it can never re-open a week that
was already correctly closed out. See docs/ROADMAP_2026.md P3.1 / the
in-season reliability plan, phase 2.6.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parent.parent / 'autoscorer_json.py'
_spec = importlib.util.spec_from_file_location('autoscorer_json', MODULE_PATH)
autoscorer_json = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(autoscorer_json)


def test_missing_output_is_not_already_finalized(tmp_path):
    assert autoscorer_json._week_output_already_finalized(tmp_path / 'nope.json') is False


def test_malformed_output_is_not_already_finalized(tmp_path):
    path = tmp_path / 'week_1.json'
    path.write_text('not json')
    assert autoscorer_json._week_output_already_finalized(path) is False


def test_output_without_games_final_key_is_not_already_finalized(tmp_path):
    path = tmp_path / 'week_1.json'
    path.write_text(json.dumps({'week': 1, 'has_scores': True}))
    assert autoscorer_json._week_output_already_finalized(path) is False


def test_output_with_games_final_false_is_not_already_finalized(tmp_path):
    path = tmp_path / 'week_1.json'
    path.write_text(json.dumps({'week': 1, 'games_final': False}))
    assert autoscorer_json._week_output_already_finalized(path) is False


def test_output_with_games_final_true_is_already_finalized(tmp_path):
    path = tmp_path / 'week_1.json'
    path.write_text(json.dumps({'week': 1, 'games_final': True}))
    assert autoscorer_json._week_output_already_finalized(path) is True


def test_finalize_flag_is_registered_and_distinct_from_force():
    """--finalize must be a real, separate CLI flag from --force - a narrow
    exception for a week that was never finalized, not a blanket bypass of
    the lock."""
    result = subprocess.run(
        [sys.executable, str(MODULE_PATH), '--help'],
        capture_output=True,
        text=True,
        check=True,
    )
    assert '--finalize' in result.stdout
    assert '--force' in result.stdout
