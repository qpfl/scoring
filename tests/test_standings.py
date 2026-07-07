"""Tests for qpfl.json_scorer.update_standings_json tiebreaker order (docs/ROADMAP_2026.md P0.4).

Constitution tiebreaker order: 1) rank_points, 2) total wins, 3) total points
scored, 4) head-to-head, 5) commissioner decision (stable order + warning).

Fixtures use two "filler" teams that always outscore the teams under test so
the top-half bonus never applies to them, keeping the rank_points math to
just wins (1.0) and ties (0.5).
"""

import json
from pathlib import Path

from qpfl.json_scorer import update_standings_json


def _team(abbrev, score):
    return {'abbrev': abbrev, 'name': abbrev, 'owner': '', 'total_score': score}


def _write_week(dir_path: Path, week: int, teams: list, matchups: list) -> Path:
    path = dir_path / f'week_{week}.json'
    path.write_text(
        json.dumps({'week': week, 'has_scores': True, 'teams': teams, 'matchups': matchups})
    )
    return path


FILLER1 = _team('FIL1', 1000)
FILLER2 = _team('FIL2', 900)


def _matchup(t1, t2):
    return {'team1': t1, 'team2': t2}


class TestWinsBeatsPointsFor:
    def test_wins_tiebreak_overrides_points_for(self, tmp_path):
        weeks_dir = tmp_path / 'weeks'
        weeks_dir.mkdir()

        # Week 1: A beats X 100-10 (A: 1 win, pf 100).
        w1 = _write_week(
            weeks_dir,
            1,
            [_team('A', 100), _team('X', 10), FILLER1, FILLER2],
            [_matchup(_team('A', 100), _team('X', 10))],
        )
        # Week 2: B ties Y 90-90 (B: 1 tie, pf 90).
        w2 = _write_week(
            weeks_dir,
            2,
            [_team('B', 90), _team('Y', 90), FILLER1, FILLER2],
            [_matchup(_team('B', 90), _team('Y', 90))],
        )
        # Week 3: B ties Z 95-95 (B: 2nd tie, pf 185 total).
        w3 = _write_week(
            weeks_dir,
            3,
            [_team('B', 95), _team('Z', 95), FILLER1, FILLER2],
            [_matchup(_team('B', 95), _team('Z', 95))],
        )

        standings = update_standings_json(tmp_path / 'standings.json', [w1, w2, w3], season=2026)
        by_abbrev = {s['abbrev']: s for s in standings}

        a, b = by_abbrev['A'], by_abbrev['B']
        assert a['rank_points'] == b['rank_points'] == 1.0
        assert a['wins'] == 1 and b['wins'] == 0
        assert a['points_for'] == 100 and b['points_for'] == 185
        # B has more points_for, but A has more wins - A must rank ahead.
        assert a['seed'] < b['seed']


class TestHeadToHeadTiebreak:
    def test_head_to_head_decides_when_everything_else_ties(self, tmp_path):
        weeks_dir = tmp_path / 'weeks'
        weeks_dir.mkdir()

        # Week 1: P beats Q 100-90.
        w1 = _write_week(
            weeks_dir,
            1,
            [_team('P', 100), _team('Q', 90), FILLER1, FILLER2],
            [_matchup(_team('P', 100), _team('Q', 90))],
        )
        # Week 2: Q beats R 100-90.
        w2 = _write_week(
            weeks_dir,
            2,
            [_team('Q', 100), _team('R', 90), FILLER1, FILLER2],
            [_matchup(_team('Q', 100), _team('R', 90))],
        )
        # Week 3: S beats P 100-90.
        w3 = _write_week(
            weeks_dir,
            3,
            [_team('S', 100), _team('P', 90), FILLER1, FILLER2],
            [_matchup(_team('S', 100), _team('P', 90))],
        )

        standings = update_standings_json(tmp_path / 'standings.json', [w1, w2, w3], season=2026)
        by_abbrev = {s['abbrev']: s for s in standings}

        p, q = by_abbrev['P'], by_abbrev['Q']
        assert p['rank_points'] == q['rank_points'] == 1.0
        assert p['wins'] == q['wins'] == 1
        assert p['points_for'] == q['points_for'] == 190
        # P beat Q head-to-head in week 1 - P must rank ahead of Q.
        assert p['seed'] < q['seed']

    def test_unresolved_tie_keeps_stable_order_and_warns(self, tmp_path, capsys):
        weeks_dir = tmp_path / 'weeks'
        weeks_dir.mkdir()

        # C and D never play each other and end up identical in every stat.
        w1 = _write_week(
            weeks_dir,
            1,
            [_team('C', 50), _team('E', 10), FILLER1, FILLER2],
            [_matchup(_team('C', 50), _team('E', 10))],
        )
        w2 = _write_week(
            weeks_dir,
            2,
            [_team('D', 50), _team('F', 10), FILLER1, FILLER2],
            [_matchup(_team('D', 50), _team('F', 10))],
        )

        standings = update_standings_json(tmp_path / 'standings.json', [w1, w2], season=2026)
        by_abbrev = {s['abbrev']: s for s in standings}

        c, d = by_abbrev['C'], by_abbrev['D']
        assert c['rank_points'] == d['rank_points']
        assert c['wins'] == d['wins']
        assert c['points_for'] == d['points_for']
        # C was inserted first (week 1) -> stable sort keeps it ahead.
        assert c['seed'] < d['seed']

        assert 'commissioner must decide' in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# save_week_scores playoff metadata passthrough (P1.3)
# --------------------------------------------------------------------------- #
def test_save_week_scores_preserves_playoff_matchup_metadata(tmp_path):
    from qpfl.json_scorer import save_week_scores
    from qpfl.models import FantasyTeam, PlayerScore

    team_a = FantasyTeam(
        name='Team A',
        owner='',
        abbreviation='A',
        column_index=0,
        players={'QB': [('Some QB', 'KC', True)]},
    )
    team_b = FantasyTeam(
        name='Team B',
        owner='',
        abbreviation='B',
        column_index=0,
        players={'QB': [('Other QB', 'BUF', True)]},
    )
    results = {
        'Team A': (10.0, {'QB': [(PlayerScore('Some QB', 'QB', 'KC', 10.0), True)]}),
        'Team B': (8.0, {'QB': [(PlayerScore('Other QB', 'QB', 'BUF', 8.0), True)]}),
    }
    matchups = [
        {
            'team1': 'A',
            'team2': 'B',
            'bracket': 'mid_bowl',
            'game': 'mid_bowl_1',
            'seed1': 5,
            'seed2': 6,
            'two_week': True,
        }
    ]

    output_path = tmp_path / 'week_16.json'
    save_week_scores(output_path, 16, [team_a, team_b], results, matchups)

    saved = json.loads(output_path.read_text())
    matchup = saved['matchups'][0]
    assert matchup['game'] == 'mid_bowl_1'
    assert matchup['seed1'] == 5
    assert matchup['seed2'] == 6
    assert matchup['two_week'] is True
    assert matchup['bracket'] == 'mid_bowl'


def test_save_week_scores_has_scores_true_when_starter_found_even_if_zero(tmp_path):
    """P1.7: has_scores must key off found_in_stats, not total > 0 - a bye-week
    /pre-kickoff week where every starter nets 0 is still legitimately unscored,
    but a week where stats *were* matched (even to a 0-point game) has scores."""
    from qpfl.json_scorer import save_week_scores
    from qpfl.models import FantasyTeam, PlayerScore

    team_a = FantasyTeam(
        name='Team A',
        owner='',
        abbreviation='A',
        column_index=0,
        players={'QB': [('Some QB', 'KC', True)]},
    )
    results = {
        'Team A': (
            0.0,
            {'QB': [(PlayerScore('Some QB', 'QB', 'KC', 0.0, found_in_stats=True), True)]},
        ),
    }

    output_path = tmp_path / 'week_1.json'
    save_week_scores(output_path, 1, [team_a], results)

    saved = json.loads(output_path.read_text())
    assert saved['has_scores'] is True
    assert saved['teams'][0]['roster'][0]['found'] is True


def test_save_week_scores_has_scores_false_when_nothing_found(tmp_path):
    from qpfl.json_scorer import save_week_scores
    from qpfl.models import FantasyTeam, PlayerScore

    team_a = FantasyTeam(
        name='Team A',
        owner='',
        abbreviation='A',
        column_index=0,
        players={'QB': [('Some QB', 'KC', True)]},
    )
    results = {
        'Team A': (
            0.0,
            {'QB': [(PlayerScore('Some QB', 'QB', 'KC', 0.0, found_in_stats=False), True)]},
        ),
    }

    output_path = tmp_path / 'week_1.json'
    save_week_scores(output_path, 1, [team_a], results)

    saved = json.loads(output_path.read_text())
    assert saved['has_scores'] is False
    assert saved['teams'][0]['roster'][0]['found'] is False


# --------------------------------------------------------------------------- #
# Manual score adjustments (P2.1)
# --------------------------------------------------------------------------- #
def test_apply_score_adjustments_matched_player(tmp_path):
    from qpfl.json_scorer import apply_score_adjustments
    from qpfl.models import FantasyTeam, PlayerScore

    team = FantasyTeam(
        name='Team A',
        owner='',
        abbreviation='GSA',
        column_index=0,
        players={'HC': [('Andy Reid', 'KC', True)]},
    )
    ps = PlayerScore('Andy Reid', 'HC', 'KC', 4.0)
    results = {'Team A': (4.0, {'HC': [(ps, True)]})}

    adjustments_path = tmp_path / 'score_adjustments.json'
    adjustments_path.write_text(
        json.dumps(
            [
                {
                    'season': 2026,
                    'week': 5,
                    'team': 'GSA',
                    'player': 'Andy Reid',
                    'points': -5,
                    'reason': 'HC fired midseason',
                }
            ]
        )
    )

    new_results = apply_score_adjustments(
        [team], results, season=2026, week=5, adjustments_path=adjustments_path
    )

    total, scores = new_results['Team A']
    assert total == -1.0
    adjusted_ps = scores['HC'][0][0]
    assert adjusted_ps.total_points == -1.0
    assert adjusted_ps.breakdown['adjustment'] == -5


def test_apply_score_adjustments_wrong_week_is_noop(tmp_path):
    from qpfl.json_scorer import apply_score_adjustments
    from qpfl.models import FantasyTeam, PlayerScore

    team = FantasyTeam(
        name='Team A',
        owner='',
        abbreviation='GSA',
        column_index=0,
        players={'HC': [('Andy Reid', 'KC', True)]},
    )
    results = {'Team A': (4.0, {'HC': [(PlayerScore('Andy Reid', 'HC', 'KC', 4.0), True)]})}

    adjustments_path = tmp_path / 'score_adjustments.json'
    adjustments_path.write_text(
        json.dumps(
            [{'season': 2026, 'week': 5, 'team': 'GSA', 'player': 'Andy Reid', 'points': -5}]
        )
    )

    new_results = apply_score_adjustments(
        [team], results, season=2026, week=6, adjustments_path=adjustments_path
    )

    assert new_results['Team A'][0] == 4.0


def test_apply_score_adjustments_unmatched_player_still_adjusts_team_total(tmp_path):
    from qpfl.json_scorer import apply_score_adjustments
    from qpfl.models import FantasyTeam, PlayerScore

    team = FantasyTeam(
        name='Team A',
        owner='',
        abbreviation='GSA',
        column_index=0,
        players={'HC': [('Andy Reid', 'KC', True)]},
    )
    results = {'Team A': (4.0, {'HC': [(PlayerScore('Andy Reid', 'HC', 'KC', 4.0), True)]})}

    adjustments_path = tmp_path / 'score_adjustments.json'
    adjustments_path.write_text(
        json.dumps(
            [{'season': 2026, 'week': 5, 'team': 'GSA', 'player': 'Typo Name', 'points': -3}]
        )
    )

    new_results = apply_score_adjustments(
        [team], results, season=2026, week=5, adjustments_path=adjustments_path
    )

    assert new_results['Team A'][0] == 1.0
