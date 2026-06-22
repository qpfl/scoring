"""Tests for point-in-time team avatar resolution (qpfl/avatars.py).

Avatars are versioned per (season, week); a new upload takes effect for that week
and forward, so completed weeks keep their old image. These tests use small
synthetic manifests and never touch the network.
"""

import json

import pytest

from qpfl import avatars


def _manifest(entries: dict[str, list[tuple]]) -> dict[str, list[dict]]:
    """Build a manifest from {abbrev: [(season, week), ...]} with derived files."""
    return {
        abbrev: [
            {'season': s, 'week': w, 'file': f'{abbrev}/{s}-w{w}.png'}
            for (s, w) in versions
        ]
        for abbrev, versions in entries.items()
    }


# --------------------------------------------------------------------------- #
# load_manifest
# --------------------------------------------------------------------------- #
def test_load_manifest_absent_returns_empty(tmp_path):
    assert avatars.load_manifest(tmp_path / 'nope.json') == {}


def test_load_manifest_reads_mapping_and_wrapper(tmp_path):
    p = tmp_path / 'a.json'
    p.write_text(json.dumps({'GSA': [{'season': 2026, 'week': 1, 'file': 'GSA/2026-w1.png'}]}))
    assert 'GSA' in avatars.load_manifest(p)
    p.write_text(json.dumps({'avatars': {'GSA': []}}))
    assert avatars.load_manifest(p) == {'GSA': []}


# --------------------------------------------------------------------------- #
# avatar_at — point-in-time, current week inclusive
# --------------------------------------------------------------------------- #
def test_avatar_at_inclusive_of_upload_week():
    m = _manifest({'GSA': [(2026, 5)]})
    # Weeks before the upload have no avatar yet.
    assert avatars.avatar_at(m, 'GSA', 2026, 4) is None
    # The upload week itself shows it (inclusive), and every later week.
    assert avatars.avatar_at(m, 'GSA', 2026, 5) == 'images/avatars/GSA/2026-w5.png'
    assert avatars.avatar_at(m, 'GSA', 2026, 9) == 'images/avatars/GSA/2026-w5.png'


def test_avatar_at_picks_latest_at_or_before_week():
    m = _manifest({'GSA': [(2026, 2), (2026, 5)]})
    assert avatars.avatar_at(m, 'GSA', 2026, 2) == 'images/avatars/GSA/2026-w2.png'
    assert avatars.avatar_at(m, 'GSA', 2026, 4) == 'images/avatars/GSA/2026-w2.png'
    assert avatars.avatar_at(m, 'GSA', 2026, 5) == 'images/avatars/GSA/2026-w5.png'
    assert avatars.avatar_at(m, 'GSA', 2026, 17) == 'images/avatars/GSA/2026-w5.png'


def test_avatar_at_carries_forward_across_seasons():
    m = _manifest({'GSA': [(2025, 10)]})
    # No earlier-season upload -> nothing before it.
    assert avatars.avatar_at(m, 'GSA', 2025, 3) is None
    # A later season with no new upload keeps the prior season's avatar.
    assert avatars.avatar_at(m, 'GSA', 2026, 1) == 'images/avatars/GSA/2025-w10.png'


def test_avatar_at_offseason_week_sorts_after_real_weeks():
    m = _manifest({'GSA': [(2026, 3)]})
    # A non-int (offseason) week is after that season's real weeks, so it resolves.
    assert avatars.avatar_at(m, 'GSA', 2026, 'Offseason') == 'images/avatars/GSA/2026-w3.png'
    # An offseason upload (stored with a non-int week) applies in the offseason.
    m2 = {'GSA': [{'season': 2026, 'week': 'Offseason', 'file': 'GSA/2026-off.png'}]}
    assert avatars.avatar_at(m2, 'GSA', 2026, 'Offseason') == 'images/avatars/GSA/2026-off.png'


def test_avatar_at_missing_team_is_none():
    assert avatars.avatar_at(_manifest({'GSA': [(2026, 1)]}), 'XXX', 2026, 5) is None


# --------------------------------------------------------------------------- #
# current_avatar
# --------------------------------------------------------------------------- #
def test_current_avatar_returns_latest_version():
    m = _manifest({'GSA': [(2025, 4), (2026, 2)]})
    assert avatars.current_avatar(m, 'GSA') == 'images/avatars/GSA/2026-w2.png'


def test_current_avatar_missing_team_is_none():
    assert avatars.current_avatar(_manifest({'GSA': [(2026, 1)]}), 'XXX') is None
