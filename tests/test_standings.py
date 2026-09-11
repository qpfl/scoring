"""Tests for qpfl.json_scorer.update_standings_json tiebreaker order (docs/ROADMAP_2026.md P0.4).

Constitution tiebreaker order: 1) rank_points, 2) total wins, 3) total points
scored, 4) head-to-head, 5) commissioner decision (stable order + warning).

Fixtures use two "filler" teams that always outscore the teams under test so
the top-half bonus never applies to them, keeping the rank_points math to
just wins (1.0) and ties (0.5).
"""

import json
from pathlib import Path

from qpfl.json_scorer import save_week_scores, update_standings_json
from qpfl.models import FantasyTeam, PlayerScore


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

    def test_cyclic_head_to_head_falls_back_to_stable_order_and_warns(self, tmp_path, capsys):
        """A pairwise head-to-head tiebreaker is non-transitive: if A beat B,
        B beat C, and C beat A, there's no consistent order - the comparator
        must not silently seed one of them above a team it lost to."""
        weeks_dir = tmp_path / 'weeks'
        weeks_dir.mkdir()

        # A beats B 100-90; B beats C 100-90; C beats A 100-90. Each team ends
        # up 1-1 with points_for 190 - tied on everything the earlier
        # tiebreakers check.
        w1 = _write_week(
            weeks_dir,
            1,
            [_team('A', 100), _team('B', 90), FILLER1, FILLER2],
            [_matchup(_team('A', 100), _team('B', 90))],
        )
        w2 = _write_week(
            weeks_dir,
            2,
            [_team('B', 100), _team('C', 90), FILLER1, FILLER2],
            [_matchup(_team('B', 100), _team('C', 90))],
        )
        w3 = _write_week(
            weeks_dir,
            3,
            [_team('C', 100), _team('A', 90), FILLER1, FILLER2],
            [_matchup(_team('C', 100), _team('A', 90))],
        )

        standings = update_standings_json(tmp_path / 'standings.json', [w1, w2, w3], season=2026)
        by_abbrev = {s['abbrev']: s for s in standings}

        a, b, c = by_abbrev['A'], by_abbrev['B'], by_abbrev['C']
        assert a['rank_points'] == b['rank_points'] == c['rank_points']
        assert a['wins'] == b['wins'] == c['wins'] == 1
        assert a['points_for'] == b['points_for'] == c['points_for'] == 190

        # No team should be silently seeded above a team it lost to
        # head-to-head just because of comparator/sort-order artifacts.
        # C beat A, so A must not outrank C; A beat B, so B must not outrank A;
        # B beat C, so C must not outrank B. A cyclic H2H can't satisfy all
        # three - the fallback (stable insertion order) is what's checked.
        assert a['seed'] < b['seed'] < c['seed']
        assert 'cyclic head-to-head' in capsys.readouterr().out


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


def test_apply_score_adjustments_duplicate_name_applies_once(tmp_path, capsys):
    """Two roster entries sharing a name must not both receive the
    adjustment while the team total only moves once - that would make the
    roster's per-player scores stop summing to the team total."""
    from qpfl.json_scorer import apply_score_adjustments
    from qpfl.models import FantasyTeam, PlayerScore

    team = FantasyTeam(
        name='Team A',
        owner='',
        abbreviation='GSA',
        column_index=0,
        players={'WR': [('Same Name', 'KC', True), ('Same Name', 'BUF', True)]},
    )
    ps1 = PlayerScore('Same Name', 'WR', 'KC', 4.0)
    ps2 = PlayerScore('Same Name', 'WR', 'BUF', 6.0)
    results = {'Team A': (10.0, {'WR': [(ps1, True), (ps2, True)]})}

    adjustments_path = tmp_path / 'score_adjustments.json'
    adjustments_path.write_text(
        json.dumps(
            [{'season': 2026, 'week': 5, 'team': 'GSA', 'player': 'Same Name', 'points': -3}]
        )
    )

    new_results = apply_score_adjustments(
        [team], results, season=2026, week=5, adjustments_path=adjustments_path
    )

    total, scores = new_results['Team A']
    assert total == 7.0
    adjusted = [ps for ps, _ in scores['WR'] if 'adjustment' in ps.breakdown]
    assert len(adjusted) == 1
    assert sum(ps.total_points for ps, _ in scores['WR']) == total
    assert 'ambiguous' in capsys.readouterr().out


class TestOnlyFinishedWeeksCount:
    """A week in progress must not post records. Mid-week the Thursday game is
    final and everything else is 0, so one manager would show 1-0 and his
    opponent 0-1 off a matchup nobody has finished playing."""

    def _write(self, weeks_dir: Path, week: int, **extra) -> Path:
        path = weeks_dir / f'week_{week}.json'
        path.write_text(
            json.dumps(
                {
                    'week': week,
                    'has_scores': True,
                    'teams': [_team('A', 18), _team('B', 0), FILLER1, FILLER2],
                    'matchups': [_matchup(_team('A', 18), _team('B', 0))],
                    **extra,
                }
            )
        )
        return path

    def test_week_still_in_progress_is_excluded(self, tmp_path):
        weeks_dir = tmp_path / 'weeks'
        weeks_dir.mkdir()
        path = self._write(weeks_dir, 1, games_final=False)

        standings = update_standings_json(tmp_path / 'standings.json', [path], season=2026)
        by_abbrev = {s['abbrev']: s for s in standings}

        assert by_abbrev['A']['wins'] == 0
        assert by_abbrev['B']['losses'] == 0
        assert by_abbrev['A']['points_for'] == 0
        assert by_abbrev['A']['rank_points'] == 0

    def test_the_same_week_counts_once_its_games_are_final(self, tmp_path):
        weeks_dir = tmp_path / 'weeks'
        weeks_dir.mkdir()
        path = self._write(weeks_dir, 1, games_final=True)

        standings = update_standings_json(tmp_path / 'standings.json', [path], season=2026)
        by_abbrev = {s['abbrev']: s for s in standings}

        assert by_abbrev['A']['wins'] == 1
        assert by_abbrev['B']['losses'] == 1
        assert by_abbrev['A']['points_for'] == 18

    def test_week_files_predating_the_flag_still_count(self, tmp_path):
        """Every week file written before games_final existed is from a season
        that has long since finished; a missing key must not erase history."""
        weeks_dir = tmp_path / 'weeks'
        weeks_dir.mkdir()
        path = self._write(weeks_dir, 1)

        standings = update_standings_json(tmp_path / 'standings.json', [path], season=2026)

        assert {s['abbrev']: s for s in standings}['A']['wins'] == 1

    def test_no_tie_warning_before_anyone_has_played(self, tmp_path, capsys):
        """Ten teams tied at 0-0-0 is not a commissioner decision, and warning
        about it every run would bury the real ones."""
        weeks_dir = tmp_path / 'weeks'
        weeks_dir.mkdir()
        path = self._write(weeks_dir, 1, games_final=False)

        update_standings_json(tmp_path / 'standings.json', [path], season=2026)

        assert 'commissioner must decide' not in capsys.readouterr().out

    def test_a_real_unresolved_tie_still_warns(self, tmp_path, capsys):
        weeks_dir = tmp_path / 'weeks'
        weeks_dir.mkdir()
        # A and B both win by the same score, with no head-to-head between them.
        w1 = weeks_dir / 'week_1.json'
        w1.write_text(
            json.dumps(
                {
                    'week': 1,
                    'has_scores': True,
                    'games_final': True,
                    'teams': [_team('A', 50), _team('X', 10), _team('B', 50), _team('Y', 10)],
                    'matchups': [
                        _matchup(_team('A', 50), _team('X', 10)),
                        _matchup(_team('B', 50), _team('Y', 10)),
                    ],
                }
            )
        )

        update_standings_json(tmp_path / 'standings.json', [w1], season=2026)

        assert 'commissioner must decide' in capsys.readouterr().out


class TestGamesFinalIsRecorded:
    """save_week_scores is where the standings gate gets its input."""

    def _score(self, tmp_path, **kwargs) -> dict:
        team = FantasyTeam(
            name='Team A',
            owner='',
            abbreviation='A',
            column_index=0,
            players={'QB': [('Passer One', 'KC', True)]},
        )
        score = PlayerScore(
            name='Passer One', position='QB', team='KC', total_points=20, found_in_stats=True
        )
        output = tmp_path / 'week_1.json'
        save_week_scores(output, 1, [team], {'Team A': (20, {'QB': [(score, True)]})}, **kwargs)
        return json.loads(output.read_text())

    def test_games_final_is_written_when_known(self, tmp_path):
        assert self._score(tmp_path, games_final=False)['games_final'] is False
        assert self._score(tmp_path, games_final=True)['games_final'] is True

    def test_key_is_omitted_when_unknown(self, tmp_path):
        """A caller with no schedule in hand must not assert either way - an
        absent key reads as complete, which is right for the archived seasons."""
        assert 'games_final' not in self._score(tmp_path)


# --------------------------------------------------------------------------- #
# Weekly team names reach the week file the matchups page reads
# --------------------------------------------------------------------------- #
def _name_battle_teams():
    from qpfl.models import FantasyTeam, PlayerScore

    team_a = FantasyTeam(
        name='Standing Name A',
        owner='',
        abbreviation='A',
        column_index=0,
        players={'QB': [('Some QB', 'KC', True)]},
    )
    team_b = FantasyTeam(
        name='Standing Name B',
        owner='',
        abbreviation='B',
        column_index=0,
        players={'QB': [('Other QB', 'BUF', True)]},
    )
    results = {
        'Standing Name A': (10.0, {'QB': [(PlayerScore('Some QB', 'QB', 'KC', 10.0), True)]}),
        'Standing Name B': (8.0, {'QB': [(PlayerScore('Other QB', 'QB', 'BUF', 8.0), True)]}),
    }
    return [team_a, team_b], results


def test_save_week_scores_applies_weekly_team_name(tmp_path):
    """The matchups page loads week_N.json directly, so a name picked for that
    week has to be baked into the file - resolving it downstream is too late."""
    teams, results = _name_battle_teams()
    history = {
        'team_names': {
            'A': [{'season': 2026, 'effective_week': 1, 'name': 'Weekly Name A'}],
        }
    }

    output_path = tmp_path / 'week_1.json'
    save_week_scores(
        output_path,
        1,
        teams,
        results,
        [{'team1': 'A', 'team2': 'B'}],
        season=2026,
        team_name_history=history,
    )

    saved = json.loads(output_path.read_text())
    by_abbrev = {t['abbrev']: t for t in saved['teams']}
    assert by_abbrev['A']['name'] == 'Weekly Name A'
    # No entry for B, so it keeps its standing name rather than going blank.
    assert by_abbrev['B']['name'] == 'Standing Name B'
    assert saved['matchups'][0]['team1']['name'] == 'Weekly Name A'
    assert saved['matchups'][0]['team2']['name'] == 'Standing Name B'


def test_save_week_scores_keeps_standing_name_without_history(tmp_path):
    teams, results = _name_battle_teams()

    output_path = tmp_path / 'week_1.json'
    save_week_scores(output_path, 1, teams, results, [{'team1': 'A', 'team2': 'B'}])

    saved = json.loads(output_path.read_text())
    assert {t['name'] for t in saved['teams']} == {'Standing Name A', 'Standing Name B'}


def test_standings_name_comes_from_latest_week_file(tmp_path):
    """Week files arrive in glob order (week_10 before week_2), so standings
    must pick the newest week's name, not whichever file was read first."""
    teams, results = _name_battle_teams()

    paths = []
    for week, name in ((10, 'Week Ten Name'), (2, 'Week Two Name')):
        history = {'team_names': {'A': [{'season': 2026, 'effective_week': week, 'name': name}]}}
        path = tmp_path / f'week_{week}.json'
        save_week_scores(
            path,
            week,
            teams,
            results,
            [{'team1': 'A', 'team2': 'B'}],
            season=2026,
            team_name_history=history,
        )
        paths.append(path)

    # Must land on the later week either way round: reading order is an
    # accident of globbing, not a statement about which name is current.
    for ordering in (paths, list(reversed(paths))):
        standings = update_standings_json(tmp_path / 'standings.json', ordering, 2026)
        row = next(r for r in standings if r['abbrev'] == 'A')
        assert row['name'] == 'Week Ten Name'
