"""Season Wrapped: each team's season in one card, once the season is over.

Written to web/data/seasons/<season>/wrapped.json by
scripts/export_hall_of_fame.py for every season with a champion, and shown at
the top of Teams → Hall of Fame for that season. The site adds the pieces it
already computes: the best trade's grade (Transactions' trade report cards)
and records set (the franchise's record-book entries for the season).

Per team:
- Record, regular-season rank and finish.
- Best and worst week, biggest win and worst loss.
- MVP (most points as a starter) and most-started player.
- Lineup IQ (points as a share of the best possible lineups) and luck (wins
  above the all-play expectation), as on the owner fingerprints.
- Top add: the player who joined from outside the league's rosters (a
  free-agent add or a midseason draft pick) and scored the most as a starter.
- Revenge wins: beating a team that had already beaten you that season.
- Nemesis of the year: the opposing starter who scored the most against you.
"""

from __future__ import annotations

from qpfl.weekly_facts import CONSOLATION, PlayerGame, TeamGame
from scripts.hof_owners import _record, _season_finishes, all_play_share, regular_games

Timeline = dict[tuple[int, int], dict[str, str]]


def _points(value: float) -> float:
    return int(value) if float(value).is_integer() else round(value, 1)


def _game(g: TeamGame) -> dict:
    return {
        'week': g.week,
        'week_label': g.week_label,
        'score': _points(g.score),
        'opponent': g.opp_abbrev,
        'opponent_score': _points(g.opp_score),
        'result': 'W' if g.won else 'L' if g.lost else 'T',
    }


def _player_totals(players: list[PlayerGame]) -> list[dict]:
    totals: dict[str, dict] = {}
    for p in players:
        row = totals.setdefault(
            p.player_key, {'player': p.name, 'position': p.position, 'points': 0.0, 'starts': 0}
        )
        row['points'] += p.score
        row['starts'] += 1
    for row in totals.values():
        row['points'] = _points(row['points'])
    return list(totals.values())


def _top_add(
    abbrev: str, starters: list[PlayerGame], timeline: Timeline, season: int
) -> dict | None:
    """The team's best starter who wasn't on any roster the week before he
    first started for it."""
    weeks = sorted(w for s, w in timeline if s == season)
    if not weeks:
        return None
    first_week = weeks[0]
    joined: dict[str, int] = {}
    for week in weeks[1:]:
        before = timeline.get((season, week - 1), {})
        for key, team in timeline[(season, week)].items():
            if team == abbrev and key not in joined and key not in before:
                joined[key] = week
    adds = [
        p
        for p in starters
        if '::' not in p.player_key
        and p.player_key in joined
        and p.week >= joined[p.player_key] > first_week
    ]
    if not adds:
        return None
    best = max(_player_totals(adds), key=lambda r: (r['points'], r['player']))
    key = next(p.player_key for p in adds if p.name == best['player'])
    return {**best, 'week': joined[key]}


def _revenge(games: list[TeamGame]) -> list[dict]:
    beaten_by: set[str] = set()
    wins = []
    for g in sorted(games, key=lambda g: g.order):
        if g.won and g.opp_abbrev in beaten_by:
            wins.append(_game(g))
            beaten_by.discard(g.opp_abbrev)
        if g.lost:
            beaten_by.add(g.opp_abbrev)
    return wins


def build_season_wrapped(
    season_data: dict,
    team_games: list[TeamGame],
    player_games: list[PlayerGame],
    timeline: Timeline,
    team_hall_of_fame: dict,
) -> dict:
    season = season_data['season']
    games = [g for g in team_games if g.season == season and (g.score > 0 or g.opp_score > 0)]
    regular = regular_games(games)
    all_play = all_play_share(regular)
    starters = [p for p in player_games if p.season == season and p.starter and p.score > 0]
    # Who each team faced each week, to credit opposing starters' points.
    opponent = {(g.week, g.abbrev): g.opp_abbrev for g in games}
    standings = (season_data.get('award_standings') or season_data.get('standings') or {}).get(
        'standings', []
    )

    teams = {}
    for rank, row in enumerate(standings, 1):
        abbrev = row.get('abbrev', '')
        mine = [g for g in games if g.abbrev == abbrev]
        if not abbrev or not mine:
            continue
        my_regular = [g for g in regular if g.abbrev == abbrev]
        decided = [g for g in mine if g.single_game and g.decided]
        wins = [g for g in decided if g.won]
        losses = [g for g in decided if g.lost]
        lineups = [g for g in mine if g.optimal]
        my_starters = [p for p in starters if p.abbrev == abbrev and p.bracket != CONSOLATION]
        players = _player_totals(my_starters)
        against = [
            p
            for p in starters
            if p.bracket != CONSOLATION and opponent.get((p.week, p.abbrev)) == abbrev
        ]
        nemesis = _player_totals(against)
        luck = sum(g.won + (not g.won and not g.lost) / 2 - all_play(g) for g in my_regular)
        teams[abbrev] = {
            'team': abbrev,
            'team_name': next((m.get('name') for m in _team_rows(season_data, abbrev)), ''),
            'record': _record(row.get('wins', 0), row.get('losses', 0), row.get('ties', 0)),
            'rank': rank,
            'teams': len(standings),
            'finishes': [
                f.get('label') for f in _season_finishes(team_hall_of_fame, abbrev, season)
            ],
            'points_for': _points(row.get('points_for', 0)),
            'best_week': _game(max(mine, key=lambda g: (g.score, -g.week))),
            'worst_week': _game(min(mine, key=lambda g: (g.score, g.week))),
            'biggest_win': _game(max(wins, key=lambda g: (g.score - g.opp_score, -g.week)))
            if wins
            else None,
            'worst_loss': _game(max(losses, key=lambda g: (g.opp_score - g.score, -g.week)))
            if losses
            else None,
            'mvp': max(players, key=lambda r: (r['points'], r['player'])) if players else None,
            'most_started': max(players, key=lambda r: (r['starts'], r['points']))
            if players
            else None,
            'lineup_iq': round(
                100 * sum(g.score for g in lineups) / sum(g.optimal for g in lineups), 1
            )
            if lineups
            else None,
            'luck': round(luck, 1),
            'top_add': _top_add(abbrev, my_starters, timeline, season),
            'revenge_wins': _revenge(decided),
            'nemesis': max(nemesis, key=lambda r: (r['points'], r['player'])) if nemesis else None,
        }
    return {'season': season, 'teams': teams}


def _team_rows(season_data: dict, abbrev: str):
    for week in reversed(season_data.get('weeks', [])):
        for matchup in week.get('matchups', []):
            for side in ('team1', 'team2'):
                team = matchup.get(side)
                if isinstance(team, dict) and team.get('abbrev') == abbrev:
                    yield team
