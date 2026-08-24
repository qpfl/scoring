"""Deterministic league-history summaries built from the published QPFL data."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


def _team_name(team: dict) -> str:
    name = team.get('team_name') or team.get('name') or team.get('abbrev') or 'TBD'
    return re.sub(r'^\(\d+\)\s*', '', str(name))


def _team_score(team: dict) -> float:
    score = team.get('total_score')
    if isinstance(score, (int, float)):
        return float(score)
    return float(
        sum(
            player.get('score', 0) or 0
            for player in team.get('roster', [])
            if player.get('starter')
        )
    )


def _top_starter(team: dict) -> dict | None:
    starters = [
        player
        for player in team.get('roster', [])
        if player.get('starter') and isinstance(player.get('score'), (int, float))
    ]
    if not starters:
        return None
    player = max(starters, key=lambda item: item.get('score', 0))
    return {
        'name': player.get('name', 'Unknown'),
        'position': player.get('position', ''),
        'score': float(player.get('score', 0)),
    }


def _lineup_analysis(team: dict) -> dict | None:
    roster = [
        player
        for player in team.get('roster', [])
        if not player.get('taxi') and isinstance(player.get('score'), (int, float))
    ]
    starter_counts = Counter(
        player.get('position', '') for player in roster if player.get('starter')
    )
    if not starter_counts:
        return None

    actual = 0.0
    optimal = 0.0
    worst_mistake = None
    for position, count in starter_counts.items():
        players = [player for player in roster if player.get('position', '') == position]
        starters = [player for player in players if player.get('starter')]
        bench = [player for player in players if not player.get('starter')]
        actual += sum(float(player.get('score', 0)) for player in starters)
        optimal += sum(
            float(player.get('score', 0))
            for player in sorted(players, key=lambda item: item.get('score', 0), reverse=True)[:count]
        )
        if not starters or not bench:
            continue
        started = min(starters, key=lambda item: item.get('score', 0))
        benched = max(bench, key=lambda item: item.get('score', 0))
        margin = float(benched.get('score', 0)) - float(started.get('score', 0))
        if margin > 0 and (worst_mistake is None or margin > worst_mistake['margin']):
            worst_mistake = {
                'position': position,
                'benched': benched.get('name', 'Unknown'),
                'benched_score': float(benched.get('score', 0)),
                'started': started.get('name', 'Unknown'),
                'started_score': float(started.get('score', 0)),
                'margin': margin,
            }

    return {
        'actual': actual,
        'optimal': optimal,
        'left_on_bench': max(0.0, optimal - actual),
        'efficiency': actual / optimal if optimal > 0 else None,
        'worst_mistake': worst_mistake,
    }


def _record_for_pair(meetings: list[dict], teams: list[str]) -> dict:
    wins = dict.fromkeys(teams, 0)
    ties = 0
    points = dict.fromkeys(teams, 0.0)
    for meeting in meetings:
        for team in teams:
            points[team] += float(meeting['scores'].get(team, 0))
        winner = meeting.get('winner')
        if winner in wins:
            wins[winner] += 1
        else:
            ties += 1
    return {'wins': wins, 'ties': ties, 'points': points, 'games': len(meetings)}


def _schedule_week(meta: dict, week: int) -> dict:
    return next(
        (item for item in meta.get('schedule', []) if int(item.get('week', 0)) == week),
        {},
    )


def _rivalry_for_matchup(rivalries: list[dict], abbrev1: str, abbrev2: str) -> dict | None:
    pair = {abbrev1, abbrev2}
    return next((item for item in rivalries if set(item.get('teams', [])) == pair), None)


def build_week_chronicle(
    season: int, week: dict, meta: dict, rivalries: list[dict], caption: str = ''
) -> dict | None:
    if not week.get('has_scores') or not week.get('matchups'):
        return None

    week_number = int(week.get('week', 0))
    schedule_week = _schedule_week(meta, week_number)
    is_official_rivalry_week = bool(schedule_week.get('is_rivalry')) or week_number == 5
    matchups = []
    team_entries = []
    top_players = []
    bench_mistakes = []

    for source in week.get('matchups', []):
        team1 = source.get('team1') or {}
        team2 = source.get('team2') or {}
        abbrev1 = team1.get('abbrev')
        abbrev2 = team2.get('abbrev')
        if not abbrev1 or not abbrev2:
            continue

        score1 = _team_score(team1)
        score2 = _team_score(team2)
        if score1 > score2:
            winner, loser = abbrev1, abbrev2
        elif score2 > score1:
            winner, loser = abbrev2, abbrev1
        else:
            winner = loser = None

        analysis1 = _lineup_analysis(team1)
        analysis2 = _lineup_analysis(team2)
        top1 = _top_starter(team1)
        top2 = _top_starter(team2)
        for player, team in ((top1, team1), (top2, team2)):
            if player:
                top_players.append({**player, 'team_abbrev': team['abbrev'], 'team_name': _team_name(team)})
        for analysis, team in ((analysis1, team1), (analysis2, team2)):
            if analysis and analysis.get('worst_mistake'):
                bench_mistakes.append(
                    {
                        **analysis['worst_mistake'],
                        'team_abbrev': team['abbrev'],
                        'team_name': _team_name(team),
                    }
                )

        rivalry = _rivalry_for_matchup(rivalries, abbrev1, abbrev2)
        winner_team = team1 if winner == abbrev1 else team2 if winner == abbrev2 else None
        loser_team = team2 if winner == abbrev1 else team1 if winner == abbrev2 else None
        loser_analysis = analysis2 if winner == abbrev1 else analysis1
        if winner_team:
            summary = (
                f'{_team_name(winner_team)} defeated {_team_name(loser_team)}, '
                f'{max(score1, score2):.1f}–{min(score1, score2):.1f}.'
            )
            winner_top = top1 if winner == abbrev1 else top2
            if winner_top:
                summary += f" {winner_top['name']} led the winner with {winner_top['score']:.1f} points."
            if loser_analysis and loser_analysis['optimal'] > max(score1, score2):
                summary += (
                    f" An optimal {_team_name(loser_team)} lineup would have scored "
                    f"{loser_analysis['optimal']:.1f} and flipped the result."
                )
        else:
            summary = f'{_team_name(team1)} and {_team_name(team2)} tied at {score1:.1f}.'

        matchup = {
            'teams': [
                {'abbrev': abbrev1, 'name': _team_name(team1), 'score': score1},
                {'abbrev': abbrev2, 'name': _team_name(team2), 'score': score2},
            ],
            'winner': winner,
            'loser': loser,
            'margin': abs(score1 - score2),
            'top_starters': {abbrev1: top1, abbrev2: top2},
            'lineup_analysis': {abbrev1: analysis1, abbrev2: analysis2},
            'summary': summary,
            'rivalry_id': rivalry.get('id') if rivalry else None,
            'rivalry_name': rivalry.get('name') if rivalry else None,
            'official_rivalry': bool(rivalry and is_official_rivalry_week),
            'bracket': source.get('bracket'),
        }
        matchups.append(matchup)
        team_entries.extend(
            [
                {
                    'abbrev': abbrev1,
                    'name': _team_name(team1),
                    'score': score1,
                    'won': winner == abbrev1,
                    'lost': loser == abbrev1,
                },
                {
                    'abbrev': abbrev2,
                    'name': _team_name(team2),
                    'score': score2,
                    'won': winner == abbrev2,
                    'lost': loser == abbrev2,
                },
            ]
        )

    if not matchups:
        return None

    closest = min(matchups, key=lambda item: item['margin'])
    blowout = max(matchups, key=lambda item: item['margin'])
    weekly_king = max(team_entries, key=lambda item: item['score'])
    top_player = max(top_players, key=lambda item: item['score']) if top_players else None
    losing_teams = [team for team in team_entries if team['lost']]
    heartbreak = max(losing_teams, key=lambda item: item['score']) if losing_teams else None
    bench_crime = max(bench_mistakes, key=lambda item: item['margin']) if bench_mistakes else None

    named_rivalry = next((item for item in matchups if item.get('rivalry_id')), None)
    championship = next(
        (item for item in matchups if item.get('bracket') == 'championship'), None
    )
    if championship and championship.get('winner'):
        winning_team = next(
            team for team in championship['teams'] if team['abbrev'] == championship['winner']
        )
        headline = f"{winning_team['name']} wins the {season} QPFL championship"
    elif named_rivalry and named_rivalry.get('winner'):
        winning_team = next(
            team for team in named_rivalry['teams'] if team['abbrev'] == named_rivalry['winner']
        )
        headline = f"{winning_team['name']} claims the {named_rivalry['rivalry_name']}"
    elif closest.get('winner') and closest['margin'] <= 5:
        winning_team = next(team for team in closest['teams'] if team['abbrev'] == closest['winner'])
        losing_team = next(team for team in closest['teams'] if team['abbrev'] == closest['loser'])
        headline = f"{winning_team['name']} survives {losing_team['name']} by {closest['margin']:.1f}"
    else:
        headline = f"{weekly_king['name']} rules Week {week_number} with {weekly_king['score']:.1f}"

    awards = [
        {
            'id': 'weekly_king',
            'label': 'Weekly King',
            'title': weekly_king['name'],
            'detail': f"League-high {weekly_king['score']:.1f} points",
            'team_abbrev': weekly_king['abbrev'],
        },
        {
            'id': 'nail_biter',
            'label': 'Nail-Biter',
            'title': ' vs. '.join(team['name'] for team in closest['teams']),
            'detail': f"{closest['margin']:.1f}-point margin",
            'team_abbrev': closest.get('winner'),
        },
        {
            'id': 'beatdown',
            'label': 'Beatdown',
            'title': ' over '.join(
                next(team['name'] for team in blowout['teams'] if team['abbrev'] == code)
                for code in (blowout.get('winner'), blowout.get('loser'))
            )
            if blowout.get('winner')
            else 'Tied matchup',
            'detail': f"{blowout['margin']:.1f}-point margin",
            'team_abbrev': blowout.get('winner'),
        },
    ]
    if top_player:
        awards.append(
            {
                'id': 'top_player',
                'label': 'Player of the Week',
                'title': top_player['name'],
                'detail': f"{top_player['score']:.1f} points for {top_player['team_name']}",
                'team_abbrev': top_player['team_abbrev'],
                'player': top_player['name'],
                'position': top_player['position'],
            }
        )
    if heartbreak:
        awards.append(
            {
                'id': 'heartbreak',
                'label': 'Heartbreak',
                'title': heartbreak['name'],
                'detail': f"Lost despite scoring {heartbreak['score']:.1f}",
                'team_abbrev': heartbreak['abbrev'],
            }
        )
    if bench_crime:
        awards.append(
            {
                'id': 'bench_crime',
                'label': 'Bench Crime',
                'title': bench_crime['team_name'],
                'detail': (
                    f"Sat {bench_crime['benched']} ({bench_crime['benched_score']:.1f}) "
                    f"for {bench_crime['started']} ({bench_crime['started_score']:.1f})"
                ),
                'team_abbrev': bench_crime['team_abbrev'],
                'player': bench_crime['benched'],
            }
        )

    return {
        'season': season,
        'week': week_number,
        'headline': headline,
        'caption': caption,
        'awards': awards,
        'matchups': matchups,
    }


def _meeting_from_matchup(season: int, week: int, matchup: dict) -> dict:
    scores = {team['abbrev']: team['score'] for team in matchup['teams']}
    return {
        'season': season,
        'week': week,
        'teams': matchup['teams'],
        'scores': scores,
        'winner': matchup.get('winner'),
        'loser': matchup.get('loser'),
        'margin': matchup['margin'],
        'official': matchup.get('official_rivalry', False),
        'route': f'#history/lore/week/{season}/{week}',
    }


def _streaks(meetings: list[dict]) -> tuple[dict | None, dict | None]:
    longest = None
    current = None
    for meeting in meetings:
        winner = meeting.get('winner')
        if not winner:
            current = None
            continue
        if current and current['team'] == winner:
            current = {**current, 'count': current['count'] + 1}
        else:
            current = {'team': winner, 'count': 1}
        if longest is None or current['count'] > longest['count']:
            longest = dict(current)
    return current, longest


def _build_rivalry_books(
    rivalry_config: list[dict], meetings_by_rivalry: dict[str, list[dict]], seasons: list[dict]
) -> list[dict]:
    latest_meta = max(seasons, key=lambda item: item['season'])['meta'] if seasons else {}
    completed_by_week = {
        int(week['week'])
        for season in seasons
        if season['season'] == latest_meta.get('season')
        for week in season['weeks']
        if week.get('has_scores')
    }
    team_lookup = {team.get('abbrev'): team for team in latest_meta.get('teams', [])}
    books = []
    for config in rivalry_config:
        teams = list(config.get('teams', []))
        meetings = sorted(
            meetings_by_rivalry.get(config['id'], []),
            key=lambda item: (item['season'], item['week']),
        )
        official = [meeting for meeting in meetings if meeting.get('official')]
        current_streak, longest_streak = _streaks(meetings)
        decisive = [meeting for meeting in meetings if meeting.get('winner')]
        current_holder = decisive[-1]['winner'] if decisive else None
        next_meeting = None
        for schedule_week in latest_meta.get('schedule', []):
            week_number = int(schedule_week.get('week', 0))
            if week_number in completed_by_week:
                continue
            for matchup in schedule_week.get('matchups', []):
                pair = {
                    matchup.get('team1') if isinstance(matchup.get('team1'), str) else matchup.get('team1', {}).get('abbrev'),
                    matchup.get('team2') if isinstance(matchup.get('team2'), str) else matchup.get('team2', {}).get('abbrev'),
                }
                if pair == set(teams):
                    next_meeting = {'season': latest_meta.get('season'), 'week': week_number}
                    break
            if next_meeting:
                break

        books.append(
            {
                **config,
                'team_details': [
                    {
                        'abbrev': team,
                        'name': _team_name(team_lookup.get(team, {'abbrev': team})),
                        'owner': team_lookup.get(team, {}).get('owner', ''),
                    }
                    for team in teams
                ],
                'record': _record_for_pair(meetings, teams),
                'official_record': _record_for_pair(official, teams),
                'current_holder': current_holder,
                'current_streak': current_streak,
                'longest_streak': longest_streak,
                'closest': min(meetings, key=lambda item: item['margin']) if meetings else None,
                'biggest_blowout': max(meetings, key=lambda item: item['margin']) if meetings else None,
                'highest_scoring': max(
                    meetings, key=lambda item: sum(item['scores'].values())
                )
                if meetings
                else None,
                'next_meeting': next_meeting,
                'meetings': list(reversed(meetings)),
            }
        )
    return books


def _champion_for_year(hall_of_fame: dict, season: int, meta: dict) -> dict | None:
    finish = next(
        (
            item
            for item in hall_of_fame.get('finishes_by_year', [])
            if str(item.get('year')) == str(season)
        ),
        None,
    )
    if not finish or not finish.get('champion_abbrev'):
        return None
    abbrev = finish['champion_abbrev']
    team = next((item for item in meta.get('teams', []) if item.get('abbrev') == abbrev), {})
    return {'abbrev': abbrev, 'name': _team_name(team or {'abbrev': abbrev})}


def _draft_highlights(drafts: list[dict], season: int) -> list[dict]:
    highlights = []
    for draft in drafts:
        if int(draft.get('year', 0) or 0) != season:
            continue
        first_pick = None
        for round_data in draft.get('rounds', []):
            first_pick = next(
                (
                    pick
                    for pick in round_data.get('picks', [])
                    if str(pick.get('player', '')).upper() != 'PASS'
                ),
                None,
            )
            if first_pick:
                break
        highlights.append(
            {
                'name': draft.get('name', f'{season} Draft'),
                'type': draft.get('type', ''),
                'first_pick': first_pick,
            }
        )
    return highlights


def _superlatives_for_season(config: dict, season: int) -> dict | None:
    recorded = next(
        (item for item in config.get('superlatives', []) if int(item.get('season', 0)) == season),
        None,
    )
    if recorded:
        return recorded

    ballot = next(
        (
            item
            for item in config.get('superlative_ballots', [])
            if int(item.get('season', 0)) == season and item.get('status') == 'closed'
        ),
        None,
    )
    if not ballot:
        return None

    winners = []
    for category in ballot.get('categories', []):
        totals = Counter(category.get('votes', {}).values())
        if not totals:
            continue
        high_score = max(totals.values())
        winning_ids = {nominee_id for nominee_id, count in totals.items() if count == high_score}
        labels = [
            nominee.get('label', nominee.get('id', ''))
            for nominee in category.get('nominees', [])
            if nominee.get('id') in winning_ids
        ]
        if not labels:
            continue
        winners.append(
            {
                'category': category.get('name', category.get('id', 'Superlative')),
                'winner': ' / '.join(labels),
                'citation': f'{high_score} league vote{"s" if high_score != 1 else ""}',
            }
        )
    return {'season': season, 'winners': winners} if winners else None


def _yearbook(
    season_data: dict,
    chronicles: list[dict],
    hall_of_fame: dict,
    drafts: list[dict],
    config: dict,
) -> dict:
    season = season_data['season']
    all_matchups = [matchup for chronicle in chronicles for matchup in chronicle['matchups']]
    all_awards = [award for chronicle in chronicles for award in chronicle['awards']]
    weekly_kings = Counter(
        award.get('team_abbrev') for award in all_awards if award['id'] == 'weekly_king'
    )
    bench_crimes = Counter(
        award.get('team_abbrev') for award in all_awards if award['id'] == 'bench_crime'
    )
    featured_games = []
    if all_matchups:
        selectors = (
            ('Highest-scoring game', max(all_matchups, key=lambda item: sum(t['score'] for t in item['teams']))),
            ('Closest game', min(all_matchups, key=lambda item: item['margin'])),
            ('Largest blowout', max(all_matchups, key=lambda item: item['margin'])),
        )
        seen = set()
        for label, matchup in selectors:
            chronicle = next(item for item in chronicles if matchup in item['matchups'])
            key = (chronicle['week'],) + tuple(
                sorted(team['abbrev'] for team in matchup['teams'])
            )
            if key in seen:
                continue
            seen.add(key)
            featured_games.append(
                {
                    'label': label,
                    'season': season,
                    'week': chronicle['week'],
                    'teams': matchup['teams'],
                    'margin': matchup['margin'],
                    'route': f"#history/lore/week/{season}/{chronicle['week']}",
                }
            )

    return {
        'season': season,
        'champion': _champion_for_year(hall_of_fame, season, season_data['meta']),
        'standings': season_data.get('standings', []),
        'weeks': len(chronicles),
        'games': len(all_matchups),
        'featured_games': featured_games,
        'award_leaders': {
            'weekly_king': weekly_kings.most_common(3),
            'bench_crime': bench_crimes.most_common(3),
        },
        'drafts': _draft_highlights(drafts, season),
        'note': config.get('season_notes', {}).get(str(season), {}),
        'superlatives': _superlatives_for_season(config, season),
        'complete': bool(_champion_for_year(hall_of_fame, season, season_data['meta'])),
    }


def build_league_lore(
    seasons: list[dict],
    config: dict,
    hall_of_fame: dict | None = None,
    drafts: list[dict] | None = None,
) -> dict:
    hall_of_fame = hall_of_fame or {}
    drafts = drafts or []
    rivalry_config = config.get('rivalries', [])
    captions = {
        (int(moment['season']), int(moment['week'])): moment.get('caption', '')
        for moment in config.get('moments', [])
        if moment.get('week') is not None
    }
    chronicles_by_season = {}
    meetings_by_rivalry: dict[str, list[dict]] = {item['id']: [] for item in rivalry_config}
    timeline = []
    scoring_record = None
    prior_team_names = {}
    rivalry_holders = {}

    for season_data in sorted(seasons, key=lambda item: item['season']):
        season = season_data['season']
        meta = season_data['meta']
        chronicles = []
        current_team_names = {
            team.get('abbrev'): _team_name(team) for team in meta.get('teams', [])
        }
        for abbrev, name in current_team_names.items():
            old_name = prior_team_names.get(abbrev)
            if old_name and old_name != name:
                timeline.append(
                    {
                        'id': f'rename-{season}-{abbrev}',
                        'type': 'team_name',
                        'season': season,
                        'week': 0,
                        'title': f'{abbrev} becomes {name}',
                        'detail': f'Previously {old_name}.',
                        'teams': [abbrev],
                        'route': f'#history/lore/season/{season}',
                    }
                )
        prior_team_names.update(current_team_names)

        for week in sorted(season_data.get('weeks', []), key=lambda item: item.get('week', 0)):
            week_number = int(week.get('week', 0))
            chronicle = build_week_chronicle(
                season,
                week,
                meta,
                rivalry_config,
                captions.get((season, week_number), ''),
            )
            if not chronicle:
                continue
            chronicles.append(chronicle)
            for matchup in chronicle['matchups']:
                score = max(team['score'] for team in matchup['teams'])
                record_team = max(matchup['teams'], key=lambda team: team['score'])
                if scoring_record is None:
                    scoring_record = score
                elif score > scoring_record:
                    scoring_record = score
                    chronicle.setdefault('milestones', []).append(
                        f"{record_team['name']} set a new QPFL scoring record with {score:.1f} points."
                    )
                    timeline.append(
                        {
                            'id': f'score-record-{season}-{week_number}-{record_team["abbrev"]}',
                            'type': 'record',
                            'season': season,
                            'week': week_number,
                            'title': f"{record_team['name']} sets a new scoring record",
                            'detail': f'{score:.1f} points in Week {week_number}.',
                            'teams': [record_team['abbrev']],
                            'route': f'#history/lore/week/{season}/{week_number}',
                        }
                    )
                elif score == scoring_record:
                    chronicle.setdefault('milestones', []).append(
                        f"{record_team['name']} tied the QPFL scoring record with {score:.1f} points."
                    )
                    timeline.append(
                        {
                            'id': f'score-record-tie-{season}-{week_number}-{record_team["abbrev"]}',
                            'type': 'record',
                            'season': season,
                            'week': week_number,
                            'title': f"{record_team['name']} ties the scoring record",
                            'detail': f'{score:.1f} points in Week {week_number}.',
                            'teams': [record_team['abbrev']],
                            'route': f'#history/lore/week/{season}/{week_number}',
                        }
                    )
                rivalry_id = matchup.get('rivalry_id')
                if not rivalry_id:
                    continue
                meeting = _meeting_from_matchup(season, week_number, matchup)
                meetings_by_rivalry[rivalry_id].append(meeting)
                winner = meeting.get('winner')
                if winner and rivalry_holders.get(rivalry_id) != winner:
                    rivalry_holders[rivalry_id] = winner
                    rivalry = next(item for item in rivalry_config if item['id'] == rivalry_id)
                    winner_name = next(
                        team['name'] for team in meeting['teams'] if team['abbrev'] == winner
                    )
                    timeline.append(
                        {
                            'id': f'{rivalry_id}-{season}-{week_number}',
                            'type': 'rivalry',
                            'season': season,
                            'week': week_number,
                            'title': f"{winner_name} claims the {rivalry['name']}",
                            'detail': f"A {meeting['margin']:.1f}-point win changes the holder.",
                            'teams': rivalry['teams'],
                            'route': f'#history/lore/week/{season}/{week_number}',
                        }
                    )
        chronicles_by_season[str(season)] = {
            str(item['week']): item for item in chronicles
        }

    yearbooks = []
    for season_data in sorted(seasons, key=lambda item: item['season'], reverse=True):
        chronicles = list(chronicles_by_season.get(str(season_data['season']), {}).values())
        yearbook = _yearbook(season_data, chronicles, hall_of_fame, drafts, config)
        yearbooks.append(yearbook)
        if yearbook.get('champion'):
            champion = yearbook['champion']
            championship_week = max(
                chronicles_by_season.get(str(yearbook['season']), {}),
                key=int,
                default=17,
            )
            timeline.append(
                {
                    'id': f'champion-{yearbook["season"]}',
                    'type': 'championship',
                    'season': yearbook['season'],
                    'week': int(championship_week),
                    'title': f"{champion['name']} wins the {yearbook['season']} championship",
                    'detail': 'QPFL champion.',
                    'teams': [champion['abbrev']],
                    'route': f'#history/lore/season/{yearbook["season"]}',
                }
            )

    for moment in config.get('moments', []):
        timeline.append(
            {
                'id': moment['id'],
                'type': moment.get('type', 'moment'),
                'season': int(moment['season']),
                'week': int(moment.get('week', 0) or 0),
                'title': moment['title'],
                'detail': moment.get('caption', ''),
                'teams': moment.get('teams', []),
                'route': moment.get('route')
                or (
                    f"#history/lore/week/{moment['season']}/{moment['week']}"
                    if moment.get('week')
                    else f"#history/lore/season/{moment['season']}"
                ),
                'curated': True,
            }
        )

    timeline.sort(key=lambda item: (item['season'], item.get('week', 0), item['id']), reverse=True)
    latest_chronicles = [
        chronicle
        for season in sorted(chronicles_by_season, key=int, reverse=True)
        for chronicle in sorted(
            chronicles_by_season[season].values(), key=lambda item: item['week'], reverse=True
        )
    ][:12]
    return {
        'version': 1,
        'chronicles': chronicles_by_season,
        'latest_chronicles': latest_chronicles,
        'rivalries': _build_rivalry_books(rivalry_config, meetings_by_rivalry, seasons),
        'yearbooks': yearbooks,
        'timeline': timeline,
        'superlative_ballots': config.get('superlative_ballots', []),
    }


def load_published_seasons(web_dir: Path) -> list[dict]:
    seasons_root = web_dir / 'data' / 'seasons'
    seasons = []
    if not seasons_root.exists():
        return seasons
    for season_dir in sorted(seasons_root.iterdir()):
        if not season_dir.is_dir() or not season_dir.name.isdigit():
            continue
        meta = _load_json(season_dir / 'meta.json', {})
        if not meta:
            continue
        standings_payload = _load_json(season_dir / 'standings.json', [])
        standings = (
            standings_payload.get('standings', [])
            if isinstance(standings_payload, dict)
            else standings_payload
        )
        weeks = [
            _load_json(path, {})
            for path in sorted(
                (season_dir / 'weeks').glob('week_*.json') if (season_dir / 'weeks').exists() else [],
                key=lambda path: int(path.stem.split('_')[-1]),
            )
        ]
        seasons.append(
            {
                'season': int(season_dir.name),
                'meta': meta,
                'standings': standings,
                'weeks': [week for week in weeks if week],
            }
        )
    return seasons


def export_league_lore(data_dir: Path, web_dir: Path) -> dict:
    config = _load_json(data_dir / 'league_lore.json', {})
    shared_dir = web_dir / 'data' / 'shared'
    hall_of_fame = _load_json(shared_dir / 'hall_of_fame.json', {})
    drafts_payload = _load_json(shared_dir / 'drafts.json', [])
    drafts = drafts_payload.get('drafts', []) if isinstance(drafts_payload, dict) else drafts_payload
    output = build_league_lore(
        load_published_seasons(web_dir), config, hall_of_fame, drafts
    )
    shared_dir.mkdir(parents=True, exist_ok=True)
    output_path = shared_dir / 'lore.json'
    existing = _load_json(output_path, None)
    if existing != output:
        with open(output_path, 'w', encoding='utf-8') as handle:
            json.dump(output, handle, separators=(',', ':'))
    return output
