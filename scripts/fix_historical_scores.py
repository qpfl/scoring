#!/usr/bin/env python3
"""Synchronize completed-season web data with the official Excel workbooks.

The split files under ``web/data/seasons`` are what the frontend displays. The
legacy ``web/data_<season>.json`` files are kept in sync so a future migration
cannot reintroduce stale scores.

Usage:
    python scripts/fix_historical_scores.py 2024
    python scripts/fix_historical_scores.py --all
    python scripts/fix_historical_scores.py 2024 --backfill-missing
"""

import argparse
import copy
import json
import re
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from qpfl.historical import load_historical_workbook  # noqa: E402
from scripts.export_for_web import calculate_team_stats, parse_player_name  # noqa: E402

HISTORICAL_SEASONS = tuple(range(2020, 2026))
ROSTER_REBUILD_SEASONS = {2024}
NAME_TOKEN_RE = re.compile(r'[^a-z0-9]+')
SUFFIXES = {'ii', 'iii', 'iv', 'jr', 'sr'}


def load_json(path: Path) -> dict:
    with open(path) as file:
        return json.load(file)


def write_json(path: Path, data: dict, *, compact: bool = False) -> None:
    with open(path, 'w') as file:
        if compact:
            json.dump(data, file, separators=(',', ':'))
        else:
            json.dump(data, file, indent=2)


def player_name_tokens(name: str) -> list[str]:
    tokens = [token for token in NAME_TOKEN_RE.sub(' ', name.lower()).split() if token]
    while tokens and tokens[-1] in SUFFIXES:
        tokens.pop()
    return tokens


def find_player(roster: list[dict], name: str, position: str) -> dict | None:
    wanted = player_name_tokens(name)
    wanted_position = 'D/ST' if position == 'DEF' else position
    exact = [
        player
        for player in roster
        if ('D/ST' if player.get('position') == 'DEF' else player.get('position'))
        == wanted_position
        and player_name_tokens(player.get('name', '')) == wanted
    ]
    if len(exact) == 1:
        return exact[0]

    if not wanted:
        return None
    same_last_name = [
        player
        for player in roster
        if ('D/ST' if player.get('position') == 'DEF' else player.get('position'))
        == wanted_position
        and player_name_tokens(player.get('name', ''))[-1:] == wanted[-1:]
    ]
    if len(same_last_name) == 1:
        return same_last_name[0]
    return None


def canonical_source_player(source: dict, team_abbrev: str) -> dict:
    label = source['name']
    if source.get('nfl_team'):
        label = f'{label} ({source["nfl_team"]})'
    name, nfl_team = parse_player_name(label, season=2024, team_abbrev=team_abbrev)
    return {
        'name': name,
        'nfl_team': nfl_team,
        'position': source['position'],
        'score': source['score'],
        'starter': source['starter'],
    }


def rebuild_roster(
    source_team: dict,
    existing_roster: list[dict],
    scorer=None,
) -> tuple[list[dict], int]:
    roster = []
    filled = 0

    for source in source_team['roster']:
        player = canonical_source_player(source, source_team['abbrev'])
        existing = find_player(existing_roster, player['name'], player['position'])

        if existing is not None:
            player['name'] = existing.get('name', player['name'])
            player['nfl_team'] = existing.get('nfl_team') or player['nfl_team']

        if player['starter'] and player['score'] is not None:
            score = player['score']
        elif existing is not None:
            score = existing.get('score', 0.0)
        elif scorer is not None:
            from scripts.backfill_bench_scores import score_of

            score = score_of(scorer, player)
            score = 0.0 if score is None else score
            filled += int(score != 0.0)
        else:
            score = 0.0

        player['score'] = float(score)
        roster.append(player)

    return roster, filled


def sync_starter_scores(team: dict, source_team: dict) -> None:
    unresolved = []

    for source in source_team['roster']:
        if not source['starter']:
            continue
        player = find_player(team.get('roster', []), source['name'], source['position'])
        if player is None:
            unresolved.append(source)
            continue
        player['starter'] = True
        if source['score'] is None:
            unresolved.append(source)
        else:
            player['score'] = source['score']

    starter_total = sum(
        float(player.get('score') or 0.0)
        for player in team.get('roster', [])
        if player.get('starter')
    )
    difference = round(source_team['total_score'] - starter_total, 1)
    missing_score_players = []
    for source in unresolved:
        player = find_player(team.get('roster', []), source['name'], source['position'])
        if player is not None and source['score'] is None:
            missing_score_players.append(player)

    if difference and len(missing_score_players) == 1:
        missing_score_players[0]['score'] = round(
            float(missing_score_players[0].get('score') or 0.0) + difference,
            1,
        )
        starter_total += difference

    if round(starter_total, 1) != source_team['total_score']:
        raise ValueError(
            f'Week score does not match starter rows for {source_team["abbrev"]}: '
            f'{starter_total} != {source_team["total_score"]}'
        )


def sync_week(
    week: dict,
    source_week: dict,
    *,
    rebuild_rosters: bool,
    scorer=None,
) -> dict[str, int]:
    teams = {team['abbrev']: team for team in week.get('teams', [])}
    stats = {'scores': 0, 'ranks': 0, 'rosters': 0, 'bench_scores': 0}

    for abbrev, source_team in source_week['teams'].items():
        team = teams.get(abbrev)
        if team is None:
            raise ValueError(f'Week {week["week"]} is missing team {abbrev}')

        if rebuild_rosters:
            old_count = len(team.get('roster', []))
            team['roster'], filled = rebuild_roster(source_team, team.get('roster', []), scorer)
            stats['rosters'] += len(team['roster']) - old_count
            stats['bench_scores'] += filled

        sync_starter_scores(team, source_team)
        if team.get('total_score') != source_team['total_score']:
            stats['scores'] += 1
        if team.get('score_rank') != source_team['score_rank']:
            stats['ranks'] += 1
        team['total_score'] = source_team['total_score']
        team['score_rank'] = source_team['score_rank']

    for matchup in week.get('matchups', []):
        for key in ('team1', 'team2'):
            matchup_team = matchup.get(key, {})
            if isinstance(matchup_team, dict) and matchup_team.get('abbrev') in teams:
                matchup[key] = copy.deepcopy(teams[matchup_team['abbrev']])

    week['has_scores'] = any(team.get('total_score', 0) > 0 for team in teams.values())
    return stats


def sync_matchup_teams(week: dict) -> None:
    teams = {team['abbrev']: team for team in week.get('teams', [])}
    for matchup in week.get('matchups', []):
        for key in ('team1', 'team2'):
            matchup_team = matchup.get(key, {})
            if isinstance(matchup_team, dict) and matchup_team.get('abbrev') in teams:
                matchup[key] = copy.deepcopy(teams[matchup_team['abbrev']])


def merge_historical_player_scores(target_week: dict, donor_week: dict) -> None:
    """Keep the most complete non-starter scores without changing official totals."""
    donor_teams: dict[str, list[dict]] = {}
    for team in donor_week.get('teams', []):
        donor_teams.setdefault(team['abbrev'], []).append(team)
    for matchup in donor_week.get('matchups', []):
        for key in ('team1', 'team2'):
            team = matchup.get(key)
            if isinstance(team, dict) and team.get('abbrev'):
                donor_teams.setdefault(team['abbrev'], []).append(team)

    for target_team in target_week.get('teams', []):
        team_versions = donor_teams.get(target_team['abbrev'], [])
        if not team_versions:
            continue

        for group in ('roster', 'taxi_squad'):
            target_players = target_team.get(group, [])
            if group == 'taxi_squad':
                for donor_team in team_versions:
                    for donor_player in donor_team.get(group, []):
                        if (
                            find_player(
                                target_players,
                                donor_player.get('name', ''),
                                donor_player.get('position', ''),
                            )
                            is None
                        ):
                            if group not in target_team:
                                target_team[group] = target_players
                            target_players.append(copy.deepcopy(donor_player))

            for target_player in target_players:
                donor_players = []
                donor_scores = []
                for donor_team in team_versions:
                    donor_player = find_player(
                        donor_team.get(group, []),
                        target_player.get('name', ''),
                        target_player.get('position', ''),
                    )
                    if donor_player is None:
                        continue
                    donor_players.append(donor_player)
                    if isinstance(donor_player.get('score'), (int, float)):
                        donor_scores.append(donor_player['score'])

                if donor_players:
                    identity_donor = donor_players[0]
                    if player_name_tokens(target_player.get('name', '')) != player_name_tokens(
                        identity_donor.get('name', '')
                    ):
                        target_player['name'] = identity_donor['name']
                        target_player['nfl_team'] = identity_donor.get('nfl_team', '')
                    elif not target_player.get('nfl_team') and identity_donor.get('nfl_team'):
                        target_player['nfl_team'] = identity_donor['nfl_team']

                if group == 'roster' and target_player.get('starter'):
                    continue
                if not donor_scores:
                    continue
                donor_score = next((score for score in donor_scores if score != 0), donor_scores[0])
                target_score = target_player.get('score')
                if donor_score != 0 or not isinstance(target_score, (int, float)):
                    target_player['score'] = donor_score

    sync_matchup_teams(target_week)


def calculate_regular_season_stats(
    weeks: list[dict], regular_season_weeks: int, top_half_weight: float
) -> dict:
    standings = {}

    for week in weeks:
        if week['week'] > regular_season_weeks:
            continue

        for matchup in week.get('matchups', []):
            team1 = matchup['team1']
            team2 = matchup['team2']
            for team in (team1, team2):
                standings.setdefault(
                    team['abbrev'],
                    {
                        'rank_points': 0.0,
                        'wins': 0,
                        'losses': 0,
                        'ties': 0,
                        'top_half': 0.0,
                        'points_for': 0.0,
                        'points_against': 0.0,
                    },
                )

            score1 = team1['total_score']
            score2 = team2['total_score']
            stats1 = standings[team1['abbrev']]
            stats2 = standings[team2['abbrev']]
            stats1['points_for'] += score1
            stats1['points_against'] += score2
            stats2['points_for'] += score2
            stats2['points_against'] += score1

            if score1 > score2:
                stats1['wins'] += 1
                stats2['losses'] += 1
                stats1['rank_points'] += 1.0
            elif score2 > score1:
                stats2['wins'] += 1
                stats1['losses'] += 1
                stats2['rank_points'] += 1.0
            else:
                stats1['ties'] += 1
                stats2['ties'] += 1
                stats1['rank_points'] += 0.5
                stats2['rank_points'] += 0.5

        scores: dict[float, list[str]] = {}
        for team in week.get('teams', []):
            scores.setdefault(team['total_score'], []).append(team['abbrev'])

        position = 1
        for _score, abbrevs in sorted(scores.items(), reverse=True):
            top_half_positions = sum(
                slot <= len(week.get('teams', [])) / 2
                for slot in range(position, position + len(abbrevs))
            )
            top_half_credit = top_half_positions / len(abbrevs)
            for abbrev in abbrevs:
                standings[abbrev]['top_half'] += top_half_credit
                standings[abbrev]['rank_points'] += top_half_weight * top_half_credit
            position += len(abbrevs)

    for standing in standings.values():
        for key in ('rank_points', 'top_half', 'points_for', 'points_against'):
            standing[key] = round(standing[key], 2)
    return standings


def update_standings(
    standings: list[dict],
    weeks: list[dict],
    regular_season_weeks: int,
    top_half_weight: float,
) -> list[dict]:
    corrected = calculate_regular_season_stats(weeks, regular_season_weeks, top_half_weight)
    updated = copy.deepcopy(standings)

    for standing in updated:
        stats = corrected.get(standing.get('abbrev'))
        if stats:
            standing.update(stats)
    return updated


def fix_season(season: int, *, backfill_missing: bool = False) -> dict[str, int]:
    workbook_path = PROJECT_DIR / 'previous_seasons' / f'{season} Scores.xlsx'
    season_dir = PROJECT_DIR / 'web' / 'data' / 'seasons' / str(season)
    weeks_dir = season_dir / 'weeks'
    legacy_path = PROJECT_DIR / 'web' / f'data_{season}.json'

    if not workbook_path.exists() or not weeks_dir.exists() or not legacy_path.exists():
        raise FileNotFoundError(f'Historical inputs are incomplete for {season}')

    source_weeks = load_historical_workbook(workbook_path, season)
    legacy = load_json(legacy_path)
    legacy_weeks = {week['week']: week for week in legacy.get('weeks', [])}
    scorer_data = None
    if backfill_missing and season in ROSTER_REBUILD_SEASONS:
        from scripts.backfill_bench_scores import SeasonData

        scorer_data = SeasonData(season)

    totals = {'scores': 0, 'ranks': 0, 'rosters': 0, 'bench_scores': 0}
    repaired_weeks = []
    for week_num, source_week in source_weeks.items():
        week_path = weeks_dir / f'week_{week_num}.json'
        week = load_json(week_path)
        scorer = scorer_data.scorer(week_num) if scorer_data is not None else None
        legacy_week = legacy_weeks.get(week_num)
        if legacy_week is None:
            raise ValueError(f'Legacy data for {season} is missing Week {week_num}')
        merge_historical_player_scores(legacy_week, legacy_week)
        stats = sync_week(
            week,
            source_week,
            rebuild_rosters=season in ROSTER_REBUILD_SEASONS,
            scorer=scorer,
        )
        merge_historical_player_scores(week, legacy_week)
        for key, value in stats.items():
            totals[key] += value
        write_json(week_path, week)
        repaired_weeks.append(week)

        sync_week(
            legacy_week,
            source_week,
            rebuild_rosters=season in ROSTER_REBUILD_SEASONS,
            scorer=scorer,
        )
        merge_historical_player_scores(legacy_week, week)

    regular_season_weeks = 14 if season <= 2021 else 15
    standings_path = season_dir / 'standings.json'
    standings_payload = load_json(standings_path)
    standings_payload['standings'] = update_standings(
        standings_payload.get('standings', []),
        repaired_weeks,
        regular_season_weeks,
        1.0 if season <= 2021 else 0.5,
    )
    write_json(standings_path, standings_payload)

    legacy['standings'] = copy.deepcopy(standings_payload['standings'])
    legacy['team_stats'] = calculate_team_stats(legacy['weeks'], legacy['standings'])
    write_json(legacy_path, legacy, compact=True)

    return totals


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('season', nargs='?', type=int)
    parser.add_argument('--all', action='store_true', help='synchronize every completed season')
    parser.add_argument(
        '--backfill-missing',
        action='store_true',
        help='download archived NFL data to score roster entries missing from old exports',
    )
    args = parser.parse_args()

    if args.all == (args.season is not None):
        parser.error('provide one season or --all')

    seasons = HISTORICAL_SEASONS if args.all else (args.season,)
    for season in seasons:
        stats = fix_season(season, backfill_missing=args.backfill_missing)
        print(
            f'{season}: {stats["scores"]} scores, {stats["ranks"]} ranks, '
            f'{stats["rosters"]} roster entries, {stats["bench_scores"]} bench scores repaired'
        )


if __name__ == '__main__':
    main()
