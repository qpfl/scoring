"""Hall of Fame owner profiles: one person's career across every team they ran.

Owners are credited the way the owner stats table credits them
(`export_hall_of_fame.get_owner_codes`): each co-owner of a team gets its
games. Profiles are keyed by the same codes as `owner_stats`, so the table
and the profile always agree.
"""

from __future__ import annotations

import statistics
from collections import defaultdict

from qpfl.weekly_facts import CONSOLATION, PLAYOFFS, REGULAR, PlayerGame, TeamGame
from scripts import export_hall_of_fame as hof

TOP_PLAYERS = 10
# Owners with fewer regular-season games get no fingerprint: a handful of
# games puts them at the extremes of every trait.
FINGERPRINT_MIN_GAMES = 15
# A game decided by less than this is close, for the Clutch trait.
CLOSE_GAME_MARGIN = 10


def owner_codes(abbrev: str, season: int) -> list[str]:
    """The owner profiles a team's game counts toward."""
    return list(dict.fromkeys(hof.get_owner_codes(abbrev, season)))


def _record(wins: int, losses: int, ties: int) -> str:
    return f'{wins}-{losses}' + (f'-{ties}' if ties else '')


def _season_finishes(team_hall_of_fame: dict, abbrev: str, season: int) -> list[dict]:
    for franchise, history in team_hall_of_fame.items():
        if not hof._matches_franchise(abbrev, franchise):
            continue
        for row in history.get('seasons', []):
            if row.get('season') == season:
                return row.get('seasonFinishes', [])
    return []


def _timeline(all_seasons: list[dict], team_hall_of_fame: dict, team_names: dict) -> dict:
    """Each owner's regular seasons: team, record, points, rank and finish."""
    timelines: dict[str, list[dict]] = defaultdict(list)
    for season_data in all_seasons:
        season = season_data['season']
        complete = season_data.get('regular_season_complete', True)
        source = season_data.get('award_standings') if complete else None
        standings = (source or season_data.get('standings') or {}).get('standings', [])
        for rank, team in enumerate(standings, 1):
            abbrev = team.get('abbrev', '')
            if not abbrev:
                continue
            row = {
                'season': season,
                'team': abbrev,
                'team_name': team_names.get((season, abbrev)) or team.get('name', ''),
                'record': _record(team.get('wins', 0), team.get('losses', 0), team.get('ties', 0)),
                'wins': team.get('wins', 0),
                'losses': team.get('losses', 0),
                'ties': team.get('ties', 0),
                'points_for': team.get('points_for', 0),
                'points_against': team.get('points_against', 0),
                # Live standings aren't in rank order until the season ends.
                'rank': rank if complete else None,
                'teams': len(standings),
                'complete': complete,
                'finishes': _season_finishes(team_hall_of_fame, abbrev, season),
                'co_owners': [],
            }
            codes = owner_codes(abbrev, season)
            for code in codes:
                timelines[code].append({**row, 'co_owners': [c for c in codes if c != code]})
    for rows in timelines.values():
        rows.sort(key=lambda r: r['season'], reverse=True)
    return timelines


def _head_to_head(team_games: list[TeamGame], names: dict[str, str]) -> dict:
    """Every owner's record against every other owner, all decided games."""
    table: dict[str, dict[str, dict]] = defaultdict(dict)
    for g in team_games:
        if not g.decided or (g.score <= 0 and g.opp_score <= 0):
            continue
        mine = owner_codes(g.abbrev, g.season)
        theirs = owner_codes(g.opp_abbrev, g.season)
        for owner in mine:
            for opponent in theirs:
                if owner == opponent:
                    continue
                row = table[owner].setdefault(
                    opponent,
                    {
                        'opponent': opponent,
                        'name': names.get(opponent, opponent),
                        'wins': 0,
                        'losses': 0,
                        'ties': 0,
                        'points_for': 0.0,
                        'points_against': 0.0,
                        'playoff_wins': 0,
                        'playoff_losses': 0,
                        'last': None,
                    },
                )
                won, lost = g.won, g.lost
                row['wins'] += won
                row['losses'] += lost
                row['ties'] += not won and not lost
                row['points_for'] += g.score
                row['points_against'] += g.opp_score
                if g.bracket == PLAYOFFS:
                    row['playoff_wins'] += won
                    row['playoff_losses'] += lost
                if row['last'] is None or g.order >= (row['last']['season'], row['last']['week']):
                    row['last'] = {
                        'season': g.season,
                        'week': g.week,
                        'week_label': g.week_label,
                        'team': g.abbrev,
                        'score': g.score,
                        'opponent_score': g.opp_score,
                        'result': 'W' if won else 'L' if lost else 'T',
                    }
    result = {}
    for owner, rows in table.items():
        ordered = sorted(
            rows.values(),
            key=lambda r: (-(r['wins'] + r['losses'] + r['ties']), r['name']),
        )
        for row in ordered:
            row['record'] = _record(row['wins'], row['losses'], row['ties'])
            row['points_for'] = round(row['points_for'], 1)
            row['points_against'] = round(row['points_against'], 1)
        result[owner] = ordered
    return result


def _top_players(player_games: list[PlayerGame], profile_key_for) -> dict:
    """Each owner's most productive starters: points scored in their lineups."""
    totals: dict[str, dict[str, dict]] = defaultdict(dict)
    for p in sorted(player_games, key=lambda p: p.order):
        if not p.starter or p.bracket == CONSOLATION:
            continue
        key = profile_key_for(p.player_key)
        for owner in owner_codes(p.abbrev, p.season):
            row = totals[owner].setdefault(
                key,
                {
                    'player': p.name,
                    'profile_key': key,
                    'position': p.position,
                    'points': 0.0,
                    'starts': 0,
                    'seasons': [],
                },
            )
            row['player'] = p.name
            row['points'] += p.score
            row['starts'] += 1
            if p.season not in row['seasons']:
                row['seasons'].append(p.season)
    return {
        owner: sorted(rows.values(), key=lambda r: (-r['points'], r['player']))[:TOP_PLAYERS]
        for owner, rows in totals.items()
    }


def _midrank(values: list[float]):
    """Percentile (0-100) of a value among `values`, ties sharing their run."""
    ordered = sorted(values)

    def percentile(value: float) -> int:
        below = sum(1 for v in ordered if v < value)
        equal = sum(1 for v in ordered if v == value)
        return round(100 * (below + equal / 2) / len(ordered))

    return percentile


def _win_pct(games: list[TeamGame]) -> float | None:
    if not games:
        return None
    return (sum(g.won for g in games) + sum(not g.won and not g.lost for g in games) / 2) / len(
        games
    )


def _fingerprints(team_games: list[TeamGame], playoff_records: dict[str, str]) -> dict:
    """Six traits per owner, each as a percentile among qualifying owners.

    Scoring (regular-season points per game), Consistency (the standard
    deviation of those scores, lower is better), Lineup IQ (points as a share of
    the best lineup the roster allowed), Luck (wins above what the all-play
    record expects, per game), Clutch (win % in games decided by under 10) and
    Playoffs (playoff win %, from the owner stats table's playoff record so the
    two always agree).
    """
    regular = [g for g in team_games if g.bracket == REGULAR and g.single_game and g.score > 0]
    # All-play: the share of the week's other scores each team beat.
    weeks: dict[tuple[int, int], dict[str, float]] = defaultdict(dict)
    for g in regular:
        weeks[g.order][g.abbrev] = g.score

    def all_play(g: TeamGame) -> float:
        others = [s for team, s in weeks[g.order].items() if team != g.abbrev]
        if not others:
            return 0.5
        return (sum(s < g.score for s in others) + sum(s == g.score for s in others) / 2) / len(
            others
        )

    by_owner: dict[str, list[TeamGame]] = defaultdict(list)
    for g in regular:
        for owner in owner_codes(g.abbrev, g.season):
            by_owner[owner].append(g)
    close: dict[str, list[TeamGame]] = defaultdict(list)
    for g in team_games:
        if not g.decided or g.score <= 0:
            continue
        if g.single_game and abs(g.score - g.opp_score) < CLOSE_GAME_MARGIN:
            for owner in owner_codes(g.abbrev, g.season):
                close[owner].append(g)

    raw: dict[str, dict[str, tuple[float, str] | None]] = {}
    for owner, games in by_owner.items():
        if len(games) < FINGERPRINT_MIN_GAMES:
            continue
        scores = [g.score for g in games]
        sd = statistics.pstdev(scores)
        lineup = [g for g in games if g.optimal]
        luck = sum(g.won + (not g.won and not g.lost) / 2 - all_play(g) for g in games)
        clutch = close.get(owner, [])
        playoff_wins, playoff_losses = (
            int(n) for n in (playoff_records.get(owner) or '0-0').split('-')[:2]
        )
        playoff_games = playoff_wins + playoff_losses

        def record(gs: list[TeamGame]) -> str:
            wins = sum(g.won for g in gs)
            losses = sum(g.lost for g in gs)
            return _record(wins, losses, len(gs) - wins - losses)

        raw[owner] = {
            'scoring': (statistics.fmean(scores), f'{statistics.fmean(scores):.1f} PPG'),
            'consistency': (-sd, f'±{sd:.1f} a week'),
            'lineup_iq': (
                sum(g.score for g in lineup) / sum(g.optimal for g in lineup),
                f'{100 * sum(g.score for g in lineup) / sum(g.optimal for g in lineup):.1f}% of optimal',
            )
            if lineup
            else None,
            'luck': (
                luck / len(games),
                f'{luck:+.1f} wins vs all-play',
            ),
            'clutch': (_win_pct(clutch), f'{record(clutch)} in close games') if clutch else None,
            'playoffs': (
                playoff_wins / playoff_games,
                f'{playoff_wins}-{playoff_losses} in the playoffs',
            )
            if playoff_games
            else None,
        }

    labels = {
        'scoring': 'Scoring',
        'consistency': 'Consistency',
        'lineup_iq': 'Lineup IQ',
        'luck': 'Luck',
        'clutch': 'Clutch',
        'playoffs': 'Playoffs',
    }
    rankers = {
        key: _midrank([traits[key][0] for traits in raw.values() if traits[key]]) for key in labels
    }
    return {
        owner: [
            {
                'key': key,
                'label': label,
                'detail': traits[key][1],
                'percentile': rankers[key](traits[key][0]),
            }
            if traits[key]
            else {'key': key, 'label': label, 'detail': None, 'percentile': None}
            for key, label in labels.items()
        ]
        for owner, traits in raw.items()
    }


def _records_held(record_book: dict) -> dict:
    """Record book entries each owner holds, top three ranks only."""
    held: dict[str, list[dict]] = defaultdict(list)
    for group in record_book.get('groups', []):
        # Player season and career totals belong to the player, not to
        # whoever happened to start him last.
        if group.get('position') or group['category'] in ('player-season', 'player-career'):
            continue
        for entry in group['entries']:
            if entry['rank'] > 3 or not entry.get('team'):
                continue
            for owner in owner_codes(entry['team'], entry['season']):
                held[owner].append(
                    {
                        'group': group['id'],
                        'title': group['title'],
                        'category': group['category'],
                        'unit': group['unit'],
                        'shame': group.get('shame', False),
                        'rank': entry['rank'],
                        **{
                            k: entry[k]
                            for k in (
                                'value',
                                'record',
                                'season',
                                'week',
                                'week_label',
                                'team',
                                'team_name',
                                'player',
                                'position',
                            )
                            if k in entry
                        },
                    }
                )
    for rows in held.values():
        rows.sort(key=lambda r: (r['rank'], r['category'], r['title']))
    return held


def _best_and_worst(seasons: list[dict]) -> tuple[dict | None, dict | None]:
    complete = [s for s in seasons if s['complete']]
    if not complete:
        return None, None

    def pct(s):
        games = s['wins'] + s['losses'] + s['ties']
        return (s['wins'] + s['ties'] / 2) / games if games else 0

    def summary(s):
        return {k: s[k] for k in ('season', 'team', 'team_name', 'record', 'points_for', 'rank')}

    best = max(complete, key=lambda s: (pct(s), s['points_for']))
    worst = min(complete, key=lambda s: (pct(s), s['points_for']))
    return summary(best), summary(worst)


def build_owner_profiles(
    all_seasons: list[dict],
    owner_stats: list[dict],
    team_hall_of_fame: dict,
    record_book: dict,
    perfect_lineups: list[dict],
    profile_key_for=None,
) -> dict:
    # Imported here: export_weekly_facts imports export_hall_of_fame at load.
    from scripts.export_weekly_facts import flatten_season

    profile_key_for = profile_key_for or (lambda key: key)
    team_games: list[TeamGame] = []
    player_games: list[PlayerGame] = []
    team_names: dict[tuple[int, str], str] = {}
    for season_data in all_seasons:
        games, players = flatten_season(season_data)
        team_games.extend(games)
        player_games.extend(players)
        for week in season_data['weeks']:
            for matchup in week.get('matchups', []):
                for side in ('team1', 'team2'):
                    team = matchup.get(side)
                    if isinstance(team, dict) and team.get('abbrev'):
                        team_names[(season_data['season'], team['abbrev'])] = hof.clean_team_name(
                            team.get('name', '')
                        )

    names = {row['Code']: row['Owner'] for row in owner_stats}
    timelines = _timeline(all_seasons, team_hall_of_fame, team_names)
    head_to_head = _head_to_head(team_games, names)
    top_players = _top_players(player_games, profile_key_for)
    records_held = _records_held(record_book)
    perfect = {row['code']: row for row in perfect_lineups}
    fingerprints = _fingerprints(
        team_games, {row['Code']: row.get('Playoff Record', '0-0') for row in owner_stats}
    )

    playoff_games: dict[str, list[TeamGame]] = defaultdict(list)
    for g in team_games:
        if g.bracket == PLAYOFFS and g.decided and g.score > 0:
            for owner in owner_codes(g.abbrev, g.season):
                playoff_games[owner].append(g)

    profiles = {}
    for row in owner_stats:
        code = row['Code']
        seasons = timelines.get(code, [])
        best, worst = _best_and_worst(seasons)
        regular = [
            g
            for g in team_games
            if g.bracket == REGULAR and code in owner_codes(g.abbrev, g.season) and g.score > 0
        ]
        teams = []
        for s in sorted(seasons, key=lambda s: s['season']):
            # One entry per spell running a team with the same co-owners.
            if teams and (teams[-1]['team'], teams[-1]['co_owners']) == (s['team'], s['co_owners']):
                teams[-1]['last_season'] = s['season']
                continue
            teams.append(
                {
                    'team': s['team'],
                    'first_season': s['season'],
                    'last_season': s['season'],
                    'co_owners': s['co_owners'],
                }
            )
        profiles[code] = {
            'code': code,
            'name': row['Owner'],
            'summary': {
                'seasons': int(row['Seasons']),
                'record': row['Record'],
                'win_pct': row['Win%'],
                'points_for': float(row['Points For']),
                'ppg': round(sum(g.score for g in regular) / len(regular), 1) if regular else 0,
                'playoff_berths': int(row['Playoff Berths']),
                'playoff_record': row['Playoff Record'],
                'rings': int(row['Rings']),
                'second': int(row['2nd Place']),
                'third': int(row['3rd Place']),
                'last_place': int(row['Last Place']),
                'prestige': row['Prestige'],
            },
            'teams': teams,
            'seasons': seasons,
            'best_season': best,
            'worst_season': worst,
            'head_to_head': head_to_head.get(code, []),
            'top_players': top_players.get(code, []),
            'records_held': records_held.get(code, []),
            'perfect_lineups': perfect.get(code),
            'playoff_games': len(playoff_games.get(code, [])),
            'fingerprint': fingerprints.get(code),
        }
    return profiles
