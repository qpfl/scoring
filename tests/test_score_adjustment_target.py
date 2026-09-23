import pytest

from scripts.score_adjustment_target import added_adjustments, target_week


def adjustment(week, *, season=2026, player='Josh Allen'):
    return {'season': season, 'week': week, 'player': player, 'points': -1}


def test_added_adjustments_handles_existing_entries():
    existing = adjustment(1)
    new = adjustment(2)

    assert added_adjustments([existing, new], [existing]) == [new]


def test_target_week_returns_the_single_current_season_addition():
    existing = adjustment(1)

    assert target_week([existing, adjustment(5)], [existing], 2026) == 5


def test_target_week_rejects_missing_or_multiple_targets():
    with pytest.raises(ValueError):
        target_week([adjustment(1)], [adjustment(1)], 2026)
    with pytest.raises(ValueError):
        target_week([adjustment(1), adjustment(2)], [], 2026)


def test_changed_weeks_covers_additions_removals_and_coalesced_pushes():
    from scripts.score_adjustment_target import changed_weeks

    kept = adjustment(1)
    assert changed_weeks([kept, adjustment(5), adjustment(7)], [kept], 2026) == [5, 7]
    assert changed_weeks([kept], [kept, adjustment(4)], 2026) == [4]
    assert changed_weeks([kept, adjustment(3, season=2025)], [kept], 2026) == []
    reworded = {**adjustment(6), 'points': -2}
    assert changed_weeks([reworded], [adjustment(6)], 2026) == [6]


def test_state_mode_records_applied_adjustments(tmp_path):
    import json
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parent.parent / 'scripts' / 'score_adjustment_target.py'
    adjustments = tmp_path / 'score_adjustments.json'
    state = tmp_path / 'scoring_state.json'
    adjustments.write_text(json.dumps([adjustment(2)]))
    state.write_text(json.dumps({'score_adjustments': []}))

    def run(*extra):
        return subprocess.run(
            [
                sys.executable,
                str(script),
                '--season',
                '2026',
                '--path',
                str(adjustments),
                '--state',
                str(state),
                *extra,
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    assert run() == '2'
    run('--record')
    assert json.loads(state.read_text())['score_adjustments'] == [adjustment(2)]
    assert run() == ''
