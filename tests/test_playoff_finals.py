"""Week 17 finals are drawn from the final Week 16 results.

Covers seeding Week 16 from standings, deciding Week 16 games (a tie goes to
the better seed, per the constitution), filling the Week 17 bracket, the
two-week Mid Bowl total, and recording the champion in the Hall of Fame.
"""

import importlib.util
import json
from pathlib import Path

from qpfl.schedule import (
    get_playoff_schedule,
    playoff_game_result,
    teams_from_games,
    week16_results_from_output,
)
from scripts import export_hall_of_fame as hof
from scripts import send_score_update as updates

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEDULE = PROJECT_ROOT / 'data' / 'seasons' / '2026' / 'schedule.txt'
SEEDS = ['GSA', 'RPA', 'CGK', 'CWR', 'S/T', 'SLS', 'J/J', 'WJK', 'AYP', 'AST']

_spec = importlib.util.spec_from_file_location(
    'autoscorer_json_finals', PROJECT_ROOT / 'autoscorer_json.py'
)
autoscorer_json = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(autoscorer_json)


def _standings():
    return [{'abbrev': abbrev, 'seed': seed} for seed, abbrev in enumerate(SEEDS, 1)]


def _team(abbrev, score):
    return {'abbrev': abbrev, 'name': abbrev, 'total_score': score, 'roster': []}


def _scored(matchups, scores, games_final=True, week=16):
    """A scored week file: each schedule matchup with the given team scores."""
    return {
        'week': week,
        'has_scores': True,
        'games_final': games_final,
        'matchups': [
            {
                **{k: v for k, v in matchup.items() if k not in ('team1', 'team2')},
                'team1': _team(matchup['team1'], scores[matchup['team1']]),
                'team2': _team(matchup['team2'], scores[matchup['team2']]),
            }
            for matchup in matchups
        ],
    }


# 1v4: GSA wins. 2v3: tied, so RPA (2 seed) advances over CGK (3 seed).
# Mid Bowl 5v6. Sewer 7v10: AST (10) wins; 8v9: WJK (8) wins.
WEEK16_SCORES = {
    'GSA': 110,
    'CWR': 90,
    'RPA': 100,
    'CGK': 100,
    'S/T': 95,
    'SLS': 80,
    'J/J': 60,
    'AST': 70,
    'WJK': 88,
    'AYP': 77,
}


def _week16_output(tmp_path, games_final=True):
    week16_schedule = get_playoff_schedule(_standings())[0]['matchups']
    output = _scored(week16_schedule, WEEK16_SCORES, games_final)
    weeks_dir = tmp_path / 'weeks'
    weeks_dir.mkdir(parents=True, exist_ok=True)
    (weeks_dir / 'week_16.json').write_text(json.dumps(output))
    standings_path = tmp_path / 'standings.json'
    standings_path.write_text(json.dumps({'standings': _standings()}))
    return output, standings_path


def test_playoff_tie_goes_to_the_better_seed():
    matchup = {
        'team1': _team('RPA', 100),
        'team2': _team('CGK', 100),
        'seed1': 2,
        'seed2': 3,
    }
    assert playoff_game_result(matchup)['winner'] == 'RPA'
    swapped = {**matchup, 'team1': matchup['team2'], 'team2': matchup['team1']}
    swapped.update(seed1=3, seed2=2)
    assert playoff_game_result(swapped)['winner'] == 'RPA'


def test_playoff_result_needs_two_scored_teams():
    assert playoff_game_result({'team1': 'TBD', 'team2': 'TBD'}) is None
    assert playoff_game_result({'team1': _team('GSA', 1), 'team2': {'abbrev': 'RPA'}}) is None


def test_week16_results_wait_for_every_game_to_be_final(tmp_path):
    output, _ = _week16_output(tmp_path, games_final=False)
    assert week16_results_from_output(output) == {}
    output['games_final'] = True
    results = week16_results_from_output(output)
    assert results['semi_1'] == {
        'winner': 'GSA',
        'loser': 'CWR',
        'winner_seed': 1,
        'loser_seed': 4,
    }
    assert results['semi_2']['winner'] == 'RPA'


def test_finals_teams_list_the_better_seed_first():
    results = {
        'sewer_1': {'winner': 'AST', 'loser': 'J/J', 'winner_seed': 10, 'loser_seed': 7},
        'sewer_2': {'winner': 'WJK', 'loser': 'AYP', 'winner_seed': 8, 'loser_seed': 9},
    }
    game = {'from_games': ['sewer_1', 'sewer_2'], 'take': 'winners'}
    assert teams_from_games(game, results) == [('WJK', 8), ('AST', 10)]
    assert teams_from_games(game, {'sewer_1': results['sewer_1']}) == []


def test_week16_is_seeded_from_standings(tmp_path):
    _, standings_path = _week16_output(tmp_path)
    matchups = autoscorer_json.get_matchups_for_week(SCHEDULE, standings_path, 16)
    by_game = {m['game']: (m['team1'], m['team2']) for m in matchups}
    assert by_game == {
        'semi_1': ('GSA', 'CWR'),
        'semi_2': ('RPA', 'CGK'),
        'mid_bowl_1': ('S/T', 'SLS'),
        'sewer_1': ('J/J', 'AST'),
        'sewer_2': ('WJK', 'AYP'),
    }


def test_week17_finals_come_from_final_week16_results(tmp_path):
    _, standings_path = _week16_output(tmp_path)
    matchups = autoscorer_json.get_matchups_for_week(SCHEDULE, standings_path, 17)
    by_game = {m['game']: m for m in matchups}

    assert matchups[0]['game'] == 'championship'
    championship = by_game['championship']
    assert (championship['team1'], championship['team2']) == ('GSA', 'RPA')
    assert (championship['seed1'], championship['seed2']) == (1, 2)
    assert (by_game['consolation_cup']['team1'], by_game['consolation_cup']['team2']) == (
        'CGK',
        'CWR',
    )
    assert (by_game['mid_bowl_2']['team1'], by_game['mid_bowl_2']['team2']) == ('S/T', 'SLS')
    assert (by_game['7th_place']['team1'], by_game['7th_place']['team2']) == ('WJK', 'AST')
    assert (by_game['toilet_bowl']['team1'], by_game['toilet_bowl']['team2']) == ('J/J', 'AYP')


def test_week17_stays_tbd_until_week16_is_final(tmp_path, capsys):
    _, standings_path = _week16_output(tmp_path, games_final=False)
    matchups = autoscorer_json.get_matchups_for_week(SCHEDULE, standings_path, 17)
    championship = next(m for m in matchups if m['game'] == 'championship')
    assert (championship['team1'], championship['team2']) == ('TBD', 'TBD')
    assert 'Week 16 is not final yet' in capsys.readouterr().out


def _week17_output(tmp_path, scores):
    _, standings_path = _week16_output(tmp_path)
    matchups = autoscorer_json.get_matchups_for_week(SCHEDULE, standings_path, 17)
    return _scored(matchups, scores, week=17)


def test_mid_bowl_email_uses_the_two_week_total(tmp_path):
    week16, _ = _week16_output(tmp_path)
    # S/T led Week 16 by 15; SLS wins Week 17 by 10, so S/T takes the Mid Bowl.
    week17 = _week17_output(tmp_path, {**WEEK16_SCORES, 'S/T': 70, 'SLS': 80})
    mid_bowl = [m for m in week17['matchups'] if m['bracket'] == 'mid_bowl']

    lines = updates.format_matchups(mid_bowl, True, updates.mid_bowl_carryover(week16))
    assert any('(S/T)' in line and '165.0' in line and 'WINNER' in line for line in lines)
    assert any('(SLS)' in line and '160.0' in line and 'WINNER' not in line for line in lines)

    first_week = [m for m in week16['matchups'] if m['bracket'] == 'mid_bowl']
    lines = updates.format_matchups(first_week, True)
    assert not any('WINNER' in line for line in lines)
    assert any('first of two weeks' in line for line in lines)


def test_tied_championship_records_the_better_seed_as_champion(tmp_path):
    week16, _ = _week16_output(tmp_path)
    week17 = _week17_output(tmp_path, {**WEEK16_SCORES, 'GSA': 99, 'RPA': 99})

    finishes = hof.generate_season_finishes({'weeks': [week16, week17]}, 2026)

    assert finishes['champion_abbrev'] == 'GSA'
    lines = updates.format_matchups(week17['matchups'][:1], True)
    assert any('(GSA)' in line and 'WINNER' in line for line in lines)
