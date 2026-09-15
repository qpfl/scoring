import json
from pathlib import Path

import scripts.send_score_update as updates
from scripts.send_score_update import (
    format_standings,
    published_nfl_teams,
    ready_slot,
    slate_of,
    slate_progress,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = PROJECT_ROOT / '.github' / 'workflows' / 'score.yml'

# Real Week 1 2026 kickoffs: a Wednesday opener, a Thursday game, the Sunday
# 1:00 and 4:25 windows, SNF, and MNF.
WED_OPENER = '2026-09-10T00:20:00+00:00'
TNF = '2026-09-11T00:35:00+00:00'
SUN_EARLY = '2026-09-13T17:00:00+00:00'
SUN_LATE = '2026-09-13T20:25:00+00:00'
SNF = '2026-09-14T00:20:00+00:00'
MNF = '2026-09-15T00:15:00+00:00'


def starter(name, nfl_team, kickoff, *, found=True, game_final=True, score=10.0, **extra):
    return {
        'name': name,
        'nfl_team': nfl_team,
        'position': 'WR',
        'score': score,
        'found': found,
        'starter': True,
        'game_final': game_final,
        'kickoff': kickoff,
        **extra,
    }


def week_file(starters, *, games_final=False, has_scores=True, week=1):
    """A minimal week file: two teams in one matchup, splitting `starters`."""
    half = (len(starters) + 1) // 2
    teams = [
        {
            'name': 'Extra CroMahomes',
            'abbrev': 'GSA',
            'total_score': 78.0,
            'roster': starters[:half],
        },
        {'name': 'Austin Bowers', 'abbrev': 'WJK', 'total_score': 88.0, 'roster': starters[half:]},
    ]
    return {
        'week': week,
        'has_scores': has_scores,
        'games_final': games_final,
        'teams': teams,
        'matchups': [{'team1': teams[0], 'team2': teams[1]}],
    }


def write_week(root: Path, data: dict, week: int = 1) -> None:
    weeks_dir = root / 'web' / 'data' / 'seasons' / '2026' / 'weeks'
    weeks_dir.mkdir(parents=True, exist_ok=True)
    (weeks_dir / f'week_{week}.json').write_text(json.dumps(data), encoding='utf-8')
    config_dir = root / 'data'
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / 'league_config.json').write_text(
        json.dumps({'current_season': 2026}), encoding='utf-8'
    )


def write_standings(root: Path) -> None:
    season_dir = root / 'web' / 'data' / 'seasons' / '2026'
    season_dir.mkdir(parents=True, exist_ok=True)
    (season_dir / 'standings.json').write_text(
        json.dumps(
            {
                'standings': [
                    {
                        'name': 'Austin Bowers',
                        'abbrev': 'WJK',
                        'seed': 1,
                        'wins': 1,
                        'losses': 0,
                        'ties': 0,
                        'rank_points': 12.0,
                        'points_for': 88.0,
                        'points_against': 78.0,
                    }
                ]
            }
        ),
        encoding='utf-8',
    )


def run(tmp_path: Path, now: str = '2026-09-13T22:00:00Z', *extra: str) -> int:
    import sys

    original = sys.argv
    sys.argv = ['send_score_update.py', '--root', str(tmp_path), '--now', now, *extra]
    try:
        return updates.main()
    finally:
        sys.argv = original


class TestSlates:
    def test_wednesday_and_thursday_openers_share_the_thursday_slate(self):
        assert slate_of({'kickoff': WED_OPENER}) == 'thursday'
        assert slate_of({'kickoff': TNF}) == 'thursday'

    def test_the_sunday_slate_covers_the_afternoon_windows_but_not_snf(self):
        assert slate_of({'kickoff': SUN_EARLY}) == 'sunday'
        assert slate_of({'kickoff': SUN_LATE}) == 'sunday'
        # SNF kicks off hours after the afternoon settles; waiting for it would
        # push the Sunday email into Monday morning, so it rides with the final.
        assert slate_of({'kickoff': SNF}) == 'monday'
        assert slate_of({'kickoff': MNF}) == 'monday'

    def test_a_player_on_bye_belongs_to_no_slate(self):
        assert slate_of({'on_bye': True}) is None


class TestStatsPublished:
    def test_a_final_game_awaiting_stats_keeps_its_slate_incomplete(self):
        # Both games are final, but nothing on DAL has matched - the feed has
        # not published that game yet, so its 0.0 is not a real score.
        data = week_file(
            [
                starter('Matched Guy', 'CHI', SUN_EARLY),
                starter('Waiting Guy', 'DAL', SUN_EARLY, found=False, score=0.0),
            ]
        )
        started, complete = slate_progress(data)
        assert started == {'sunday'}
        assert complete == set()

    def test_a_teammate_match_proves_the_feed_has_caught_up(self):
        data = week_file(
            [
                starter('Unmatched WR', 'DAL', SUN_EARLY, found=False, score=0.0),
                starter('Matched RB', 'DAL', SUN_EARLY),
            ]
        )
        assert slate_progress(data)[1] == {'sunday'}
        assert published_nfl_teams(data) == {'DAL'}

    def test_a_ruled_out_player_is_a_settled_zero_not_a_pending_one(self):
        data = week_file(
            [starter('Out Guy', 'DAL', SUN_EARLY, found=False, score=0.0, unavailable_reason='out')]
        )
        assert slate_progress(data)[1] == {'sunday'}

    def test_a_head_coach_does_not_prove_the_feed_has_caught_up(self):
        # Coaches score off the schedule result, so they match the moment the
        # clock hits zero - before any stat line exists.
        data = week_file(
            [
                starter('Coach', 'DAL', SUN_EARLY, position='HC'),
                starter('Real WR', 'DAL', SUN_EARLY, found=False, score=0.0),
            ]
        )
        assert published_nfl_teams(data) == set()
        assert slate_progress(data)[1] == set()

    def test_an_unfinished_game_keeps_its_slate_incomplete(self):
        data = week_file([starter('Playing Now', 'KC', MNF, found=False, game_final=False)])
        assert slate_progress(data)[1] == set()


class TestReadySlot:
    def test_thursday_goes_out_once_tnf_is_published(self):
        data = week_file(
            [
                starter('TNF Guy', 'BUF', TNF),
                starter('Sunday Guy', 'CHI', SUN_EARLY, found=False, game_final=False),
            ]
        )
        assert ready_slot(data, []) == 'thursday'
        assert ready_slot(data, ['thursday']) is None

    def test_sunday_goes_out_while_snf_and_mnf_are_still_to_come(self):
        data = week_file(
            [
                starter('TNF Guy', 'BUF', TNF),
                starter('Sunday Guy', 'CHI', SUN_LATE),
                starter('SNF Guy', 'WAS', SNF, found=False, game_final=False),
                starter('MNF Guy', 'KC', MNF, found=False, game_final=False),
            ]
        )
        assert ready_slot(data, ['thursday']) == 'sunday'

    def test_final_waits_for_every_game_and_every_stat_line(self):
        pending_mnf = week_file(
            [
                starter('Sunday Guy', 'CHI', SUN_LATE),
                starter('MNF Guy', 'KC', MNF, found=False, score=0.0),
            ],
            games_final=True,
        )
        # games_final comes off the schedule, so it flips before the feed
        # publishes - the final email must not go out on those zeros.
        assert ready_slot(pending_mnf, ['thursday', 'sunday']) is None

        published = week_file(
            [starter('Sunday Guy', 'CHI', SUN_LATE), starter('MNF Guy', 'KC', MNF)],
            games_final=True,
        )
        assert ready_slot(published, ['thursday', 'sunday']) == 'final'

    def test_a_week_with_no_thursday_game_never_owes_a_thursday_email(self):
        data = week_file([starter('Sunday Guy', 'CHI', SUN_EARLY)])
        assert ready_slot(data, []) == 'sunday'

    def test_the_furthest_ready_slot_wins_when_several_are_unsent(self):
        data = week_file(
            [starter('TNF Guy', 'BUF', TNF), starter('MNF Guy', 'KC', MNF)], games_final=True
        )
        assert ready_slot(data, []) == 'final'


class TestDelivery:
    def _capture(self, monkeypatch):
        deliveries = []
        monkeypatch.setattr(
            updates,
            'send_email',
            lambda subject, body, recipients: deliveries.append((subject, body)) or True,
        )
        monkeypatch.setattr(updates, 'all_recipients', lambda: ['league@example.com'])
        return deliveries

    def test_the_sunday_email_is_sent_once_and_recorded(self, tmp_path, monkeypatch):
        write_week(
            tmp_path,
            week_file(
                [
                    starter('Sunday Guy', 'CHI', SUN_LATE, score=40.0),
                    starter('MNF Guy', 'KC', MNF, found=False, game_final=False),
                ]
            ),
        )
        deliveries = self._capture(monkeypatch)

        assert run(tmp_path) == 0
        subject, body = deliveries[0]
        assert subject == 'QPFL Week 1: Sunday scores'
        assert 'Austin Bowers (WJK)' in body
        assert '(leading)' in body
        assert 'STANDINGS' not in body

        state = json.loads((tmp_path / 'data' / 'score_notifications.json').read_text())
        assert 'sunday' in state['sent']['2026']['1']

        # Every later scoring run in the same slate must stay quiet.
        assert run(tmp_path, '2026-09-13T23:30:00Z') == 0
        assert len(deliveries) == 1

    def test_partial_stats_do_not_trigger_an_email(self, tmp_path, monkeypatch):
        write_week(
            tmp_path,
            week_file(
                [
                    starter('Published', 'CHI', SUN_EARLY),
                    starter('Not Yet Published', 'DAL', SUN_EARLY, found=False, score=0.0),
                ]
            ),
        )
        deliveries = self._capture(monkeypatch)

        assert run(tmp_path) == 0
        assert deliveries == []

    def test_the_final_email_includes_updated_standings(self, tmp_path, monkeypatch):
        write_week(
            tmp_path,
            week_file(
                [starter('Sunday Guy', 'CHI', SUN_LATE), starter('MNF Guy', 'KC', MNF)],
                games_final=True,
            ),
        )
        write_standings(tmp_path)
        deliveries = self._capture(monkeypatch)

        assert run(tmp_path, '2026-09-15T06:00:00Z') == 0
        subject, body = deliveries[0]
        assert subject == 'QPFL Week 1: Final scores & standings'
        assert 'FINAL SCORES' in body
        assert 'WINNER' in body
        assert 'STANDINGS' in body
        assert '1-0-0' in body

    def test_a_final_email_supersedes_earlier_slots_it_already_covers(self, tmp_path, monkeypatch):
        write_week(
            tmp_path,
            week_file(
                [starter('TNF Guy', 'BUF', TNF), starter('MNF Guy', 'KC', MNF)], games_final=True
            ),
        )
        write_standings(tmp_path)
        deliveries = self._capture(monkeypatch)

        assert run(tmp_path, '2026-09-15T06:00:00Z') == 0
        assert deliveries[0][0] == 'QPFL Week 1: Final scores & standings'
        state = json.loads((tmp_path / 'data' / 'score_notifications.json').read_text())
        assert set(state['sent']['2026']['1']) == {'thursday', 'sunday', 'final'}

        # No stale Thursday recap afterwards.
        assert run(tmp_path, '2026-09-15T12:00:00Z') == 0
        assert len(deliveries) == 1

    def test_weeks_that_ended_long_ago_are_not_emailed(self, tmp_path, monkeypatch):
        write_week(
            tmp_path,
            week_file([starter('Sunday Guy', 'CHI', SUN_LATE)], games_final=True),
        )
        deliveries = self._capture(monkeypatch)

        # Two weeks later, with no delivery state - a backlog must not flush.
        assert run(tmp_path, '2026-09-28T06:00:00Z') == 0
        assert deliveries == []

    def test_a_failed_delivery_does_not_record_state(self, tmp_path, monkeypatch):
        write_week(tmp_path, week_file([starter('Sunday Guy', 'CHI', SUN_LATE)]))
        monkeypatch.setattr(updates, 'send_email', lambda *args: False)
        monkeypatch.setattr(updates, 'all_recipients', lambda: ['league@example.com'])

        assert run(tmp_path) == 1
        assert not (tmp_path / 'data' / 'score_notifications.json').exists()


class TestFormatting:
    def test_long_team_names_stay_inside_the_standings_column(self):
        lines = format_standings(
            [
                {
                    'name': 'Burrow my Dicker in my Strange Nabers til it Hurts',
                    'abbrev': 'SLS',
                    'seed': 1,
                    'wins': 0,
                    'losses': 1,
                    'ties': 0,
                    'rank_points': 3.0,
                    'points_for': 67.0,
                    'points_against': 98.0,
                }
            ]
        )
        header, row = lines[4], lines[6]
        assert row.index('0-1-0') + len('0-1-0') == header.index('W-L-T') + len('W-L-T')


def test_workflow_emails_score_updates_on_scheduled_runs_only():
    workflow = WORKFLOW.read_text(encoding='utf-8')

    assert 'python scripts/send_score_update.py --season' in workflow
    assert "if: github.event_name != 'push'" in workflow
    assert 'JRW_EMAIL: ${{ secrets.JRW_EMAIL }}' in workflow
    assert 'CWR_COOWNER_EMAIL: ${{ secrets.CWR_COOWNER_EMAIL }}' in workflow
    assert "steps.score_email.outcome == 'failure'" in workflow
    # Delivery state lives under data/, which the commit step already stages.
    assert 'git add web/data.json web/data/ data/' in workflow
