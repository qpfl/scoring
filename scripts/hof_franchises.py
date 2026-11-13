"""Hall of Fame franchise index: every franchise seat across its owners.

A franchise is a current team seat, carrying the history of the codes it
grew out of (`export_hall_of_fame.FRANCHISE_LINEAGE`, e.g. RCP -> JDK -> J/J)
and of shared seasons (CWR/SLS counts for both CWR and SLS), matched the way
the team Hall of Fame pages match them (`_matches_franchise`).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable

from qpfl.elo import EloHistory
from qpfl.weekly_facts import CONSOLATION, PlayerGame, TeamGame
from scripts import export_hall_of_fame as hof
from scripts.hof_owners import _record, _season_finishes, owner_codes

PLAYER_NEMESES = 5


def _ordinal(n: int) -> str:
    suffix = 'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f'{n}{suffix}'


def _finish_key(season: dict) -> tuple:
    """Orders seasons best first: a title, then 2nd, 3rd, then regular-season rank."""
    finishes = season['finishes']
    labels = [f.get('label', '') for f in finishes]
    if any(f.get('type') == 'champion' for f in finishes):
        return (0, 0)
    for place, label in ((1, '2nd Place'), (2, '3rd Place')):
        if label in labels:
            return (place, 0)
    return (3, season['rank'] or 99)


def _team_names(seasons: list[dict]) -> list[dict]:
    """Each name the franchise played under, oldest first, with its seasons."""
    names: list[dict] = []
    for season in sorted(seasons, key=lambda s: s['season']):
        for name in season['names']:
            if names and names[-1]['name'] == name:
                if season['season'] not in names[-1]['seasons']:
                    names[-1]['seasons'].append(season['season'])
                continue
            names.append({'name': name, 'seasons': [season['season']]})
    return names


def _owner_eras(seasons: list[dict], owner_names: dict[str, str]) -> list[dict]:
    """Consecutive seasons under the same owners, oldest first."""
    eras: list[dict] = []
    for season in sorted(seasons, key=lambda s: s['season']):
        owners = season['owners']
        if eras and (eras[-1]['owners'], eras[-1]['team']) == (owners, season['team']):
            eras[-1]['last_season'] = season['season']
            eras[-1]['rings'] += season['champion']
            continue
        eras.append(
            {
                'owners': owners,
                'names': [owner_names.get(code, code) for code in owners],
                'team': season['team'],
                'first_season': season['season'],
                'last_season': season['season'],
                'rings': int(season['champion']),
            }
        )
    return eras


def _player_nemeses(
    player_games: Iterable[PlayerGame], profile_key_for: Callable[[str], str]
) -> dict[str, list[dict]]:
    """The opposing starters who scored the most against each franchise."""
    totals: dict[str, dict[str, dict]] = defaultdict(dict)
    for p in sorted(player_games, key=lambda p: p.order):
        # Counted as Top Players counts them: starters, consolation games out.
        if not p.starter or p.bracket == CONSOLATION or p.score <= 0:
            continue
        key = profile_key_for(p.player_key)
        for franchise in p.opp_franchises:
            row = totals[franchise].setdefault(
                key,
                {
                    'player': p.name,
                    'position': p.position,
                    'profile_key': key,
                    'points': 0.0,
                    'games': 0,
                },
            )
            row['points'] += p.score
            row['games'] += 1
            row['player'] = p.name
    nemeses = {}
    for franchise, rows in totals.items():
        top = sorted(rows.values(), key=lambda r: (-r['points'], r['player']))[:PLAYER_NEMESES]
        for row in top:
            row['points'] = round(row['points'], 1)
        nemeses[franchise] = top
    return nemeses


def build_franchise_index(
    all_seasons: list[dict],
    franchises: list[str],
    team_hall_of_fame: dict,
    record_book: dict,
    owner_names: dict[str, str],
    team_games: Iterable[TeamGame] = (),
    player_games: Iterable[PlayerGame] = (),
    profile_key_for: Callable[[str], str] | None = None,
) -> list[dict]:
    elo = EloHistory(team_games)
    current_elo = {f: elo.current().get(f) for f in franchises if f in elo.ratings}
    elo_rank = {
        f: rank for rank, f in enumerate(sorted(current_elo, key=lambda f: -current_elo[f]), 1)
    }
    nemeses = _player_nemeses(player_games, profile_key_for or (lambda key: key))

    # Every name a team went by each season, in order, from the weekly games.
    names_by_season: dict[tuple[int, str], list[str]] = {}
    for season_data in all_seasons:
        for week in season_data['weeks']:
            for matchup in week.get('matchups', []):
                for side in ('team1', 'team2'):
                    team = matchup.get(side)
                    if not isinstance(team, dict) or not team.get('abbrev'):
                        continue
                    name = hof.clean_team_name(team.get('name', ''))
                    names = names_by_season.setdefault((season_data['season'], team['abbrev']), [])
                    if name and name not in names:
                        names.append(name)

    index = []
    for franchise in franchises:
        seasons = []
        for season_data in all_seasons:
            season = season_data['season']
            complete = season_data.get('regular_season_complete', True)
            source = season_data.get('award_standings') if complete else None
            standings = (source or season_data.get('standings') or {}).get('standings', [])
            for rank, team in enumerate(standings, 1):
                abbrev = team.get('abbrev', '')
                if not hof._matches_franchise(abbrev, franchise):
                    continue
                finishes = _season_finishes(
                    {franchise: team_hall_of_fame.get(franchise, {})}, abbrev, season
                )
                names = names_by_season.get((season, abbrev)) or [team.get('name', '')]
                seasons.append(
                    {
                        'season': season,
                        'team': abbrev,
                        'team_name': names[-1],
                        'names': names,
                        'owners': owner_codes(abbrev, season),
                        'record': _record(
                            team.get('wins', 0), team.get('losses', 0), team.get('ties', 0)
                        ),
                        'points_for': team.get('points_for', 0),
                        'rank': rank if complete else None,
                        'teams': len(standings),
                        'complete': complete,
                        'finishes': finishes,
                        'champion': any(f.get('type') == 'champion' for f in finishes),
                    }
                )
                break
        if not seasons:
            continue
        seasons.sort(key=lambda s: s['season'], reverse=True)

        held = []
        for group in record_book.get('groups', []):
            if group.get('position') or group['category'] in ('player-season', 'player-career'):
                continue
            for entry in group['entries']:
                team = entry.get('team')
                if entry['rank'] > 3 or not team or not hof._matches_franchise(team, franchise):
                    continue
                held.append(
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
        held.sort(key=lambda r: (r['rank'], r['category'], r['title']))

        complete = [s for s in seasons if s['complete']]
        best = min(complete, key=_finish_key) if complete else None
        all_time = team_hall_of_fame.get(franchise, {}).get('allTime', {})
        current = seasons[0]
        index.append(
            {
                'abbrev': franchise,
                'name': current['team_name'],
                'owners': [owner_names.get(code, code) for code in current['owners']],
                'owner_codes': current['owners'],
                'lineage': sorted({franchise, *hof.FRANCHISE_LINEAGE.get(franchise, set())}),
                'first_season': seasons[-1]['season'],
                'record': _record(
                    all_time.get('wins', 0), all_time.get('losses', 0), all_time.get('ties', 0)
                ),
                'points_for': all_time.get('totalPoints', 0),
                'rings': sum(s['champion'] for s in seasons),
                'playoff_berths': sum(1 for s in complete if s['rank'] and s['rank'] <= 4),
                'best_finish': {
                    'season': best['season'],
                    'label': next(
                        (f['label'] for f in best['finishes']), f'{_ordinal(best["rank"])} Place'
                    ),
                }
                if best
                else None,
                'eras': _owner_eras(seasons, owner_names),
                'team_names': _team_names(seasons),
                'seasons': [{k: v for k, v in s.items() if k != 'names'} for s in seasons],
                'records_held': held,
                'elo': current_elo.get(franchise),
                'elo_rank': elo_rank.get(franchise),
                'elo_series': [list(point) for point in elo.series.get(franchise, [])],
                'player_nemeses': nemeses.get(franchise, []),
            }
        )
    return index
