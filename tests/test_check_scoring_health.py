"""Tests for scripts/check_scoring_health.py - the dead-man's switch for the
scoring pipeline. See docs/ROADMAP_2026.md P3.1 / the in-season reliability
plan, phase 2.7."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.check_scoring_health import find_unfinalized_completed_weeks, newest_scored_at

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _final_game(week, season=2026, result='W'):
    return {'game_type': 'REG', 'week': week, 'season': season, 'result': result}


class TestFindUnfinalizedCompletedWeeks:
    def test_flags_a_final_week_with_no_committed_file(self, tmp_path):
        schedule_rows = [_final_game(1)]
        assert find_unfinalized_completed_weeks(2026, tmp_path, schedule_rows) == [1]

    def test_flags_a_final_week_missing_games_final(self, tmp_path):
        (tmp_path / 'week_1.json').write_text(json.dumps({'has_scores': True}))
        schedule_rows = [_final_game(1)]
        assert find_unfinalized_completed_weeks(2026, tmp_path, schedule_rows) == [1]

    def test_flags_a_final_week_missing_has_scores(self, tmp_path):
        (tmp_path / 'week_1.json').write_text(json.dumps({'games_final': True}))
        schedule_rows = [_final_game(1)]
        assert find_unfinalized_completed_weeks(2026, tmp_path, schedule_rows) == [1]

    def test_does_not_flag_a_properly_finalized_week(self, tmp_path):
        (tmp_path / 'week_1.json').write_text(json.dumps({'has_scores': True, 'games_final': True}))
        schedule_rows = [_final_game(1)]
        assert find_unfinalized_completed_weeks(2026, tmp_path, schedule_rows) == []

    def test_does_not_flag_an_in_progress_week(self, tmp_path):
        """A week that hasn't finished yet is not "unfinalized" - it's just
        not done, which is normal and expected."""
        schedule_rows = [_final_game(1, result=None)]
        assert find_unfinalized_completed_weeks(2026, tmp_path, schedule_rows) == []

    def test_only_checks_the_requested_season(self, tmp_path):
        schedule_rows = [_final_game(1, season=2025)]
        assert find_unfinalized_completed_weeks(2026, tmp_path, schedule_rows) == []


class TestNewestScoredAt:
    def test_returns_none_when_directory_is_absent(self, tmp_path):
        assert newest_scored_at(tmp_path / 'nope') is None

    def test_returns_none_when_no_week_has_a_timestamp(self, tmp_path):
        (tmp_path / 'week_1.json').write_text(json.dumps({'week': 1}))
        assert newest_scored_at(tmp_path) is None

    def test_returns_the_most_recent_timestamp_across_weeks(self, tmp_path):
        older = '2026-09-10T12:00:00+00:00'
        newer = '2026-09-14T12:00:00+00:00'
        (tmp_path / 'week_1.json').write_text(json.dumps({'scored_at': older}))
        (tmp_path / 'week_2.json').write_text(json.dumps({'scored_at': newer}))
        assert newest_scored_at(tmp_path) == datetime.fromisoformat(newer)

    def test_ignores_malformed_timestamps(self, tmp_path):
        (tmp_path / 'week_1.json').write_text(json.dumps({'scored_at': 'not-a-date'}))
        assert newest_scored_at(tmp_path) is None


class TestStalenessThreshold:
    def test_recent_scored_at_is_within_threshold(self, tmp_path):
        recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        (tmp_path / 'week_1.json').write_text(json.dumps({'scored_at': recent}))
        newest = newest_scored_at(tmp_path)
        age_hours = (datetime.now(timezone.utc) - newest).total_seconds() / 3600
        assert age_hours < 48.0

    def test_old_scored_at_exceeds_threshold(self, tmp_path):
        old = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
        (tmp_path / 'week_1.json').write_text(json.dumps({'scored_at': old}))
        newest = newest_scored_at(tmp_path)
        age_hours = (datetime.now(timezone.utc) - newest).total_seconds() / 3600
        assert age_hours > 48.0


def test_health_workflow_is_independent_of_score_workflow():
    """The dead-man's switch must not share score.yml's concurrency group or
    schedule - a failure mode that takes out score.yml (a GitHub Actions
    outage, a bug in the workflow itself) must not also silence the thing
    meant to catch it."""
    workflow = (PROJECT_ROOT / '.github' / 'workflows' / 'health.yml').read_text()

    assert 'check_scoring_health.py' in workflow
    assert 'concurrency:' not in workflow
    assert 'if: failure()' in workflow
    assert 'recipients_for(' in workflow
