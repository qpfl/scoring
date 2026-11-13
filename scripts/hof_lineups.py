"""Lineup superlatives for the Stats → Lineups tab: the decisions behind the
scores, by season and all-time.

- Bench blunders: the biggest gap between a benched player and the starter he
  should have replaced at the same position, flagged when the swap would have
  won the game.
- Bench MVPs: the most points scored on the bench.
- Ghost starters: starters whose game was played and who scored zero or less.
- Bye and OUT blunders: starters on bye, or (2026 on, when the week files
  carry designations) listed out, doubtful, on IR or as a backup who then
  didn't score.
- Decided by special teams: games where the kicker or defense gap between the
  two lineups was bigger than the final margin.
- Perfect lineups: games a team started the best lineup its roster allowed.

Written to web/data/shared/lineup_superlatives.json by
scripts/export_hall_of_fame.py.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from scripts import export_hall_of_fame as hof

TOP = 10
SPECIAL_TEAMS = ('K', 'D/ST')
# Team units (head coaches, defenses, offensive lines) go negative most
# weeks, so a zero there is no blunder; ghosts are players.
GHOST_EXCLUDED = ('HC', 'D/ST', 'OL')


def _score(player: dict) -> float | None:
    value = player.get('score')
    return float(value) if isinstance(value, (int, float)) else None


def _number(value: float) -> float:
    return int(value) if float(value).is_integer() else round(value, 2)


class _Week:
    """One team's side of one game, with what the entries need to name it."""

    def __init__(self, season: int, week: int, team: dict, opp: dict, two_week: bool):
        self.season = season
        self.week = week
        self.label = hof.get_week_name(week, season)
        self.team = team
        self.opp = opp
        self.abbrev = team.get('abbrev', '')
        self.score = float(hof.get_team_score(team) or 0)
        self.opp_score = float(hof.get_team_score(opp) or 0)
        self.two_week = two_week

    def fields(self, owner_label: Callable[[str, int], str]) -> dict:
        return {
            'season': self.season,
            'week': self.week,
            'week_label': self.label,
            'team': self.abbrev,
            'team_name': hof.clean_team_name(self.team.get('name', '')),
            'owner_code': hof._owner_identity_code(self.abbrev),
            'owner': owner_label(self.abbrev, self.season),
            'opponent': self.opp.get('abbrev', ''),
            'score': _number(self.score),
            'opponent_score': _number(self.opp_score),
        }


def _games(all_seasons: list[dict]):
    for season_data in all_seasons:
        season = season_data['season']
        for week in season_data.get('weeks', []):
            number = week.get('week')
            if not isinstance(number, int) or week.get('has_scores') is False:
                continue
            for matchup in week.get('matchups', []):
                t1, t2 = matchup.get('team1'), matchup.get('team2')
                if not isinstance(t1, dict) or not isinstance(t2, dict):
                    continue
                if hof.get_team_score(t1) is None or hof.get_team_score(t2) is None:
                    continue
                two_week = bool(matchup.get('two_week'))
                yield _Week(season, number, t1, t2, two_week)
                yield _Week(season, number, t2, t1, two_week)


def _blunders(game: _Week) -> list[tuple[dict, dict, float]]:
    return lineup_swaps(game.team.get('roster', []))


def lineup_swaps(roster: list[dict]) -> list[tuple[dict, dict, float]]:
    """(benched, started, margin) for each swap the best lineup would make,
    pairing the best benched player with the best starter he displaces, as the
    site's optimal-lineup view does. Players are dicts with `position`,
    `score` and `starter` (the weekly awards pass the same shape)."""
    by_position: dict[str, list[dict]] = defaultdict(list)
    for player in roster:
        if _score(player) is not None:
            by_position[hof.canonical_profile_position(player.get('position'))].append(player)
    out = []
    for players in by_position.values():
        starters = [p for p in players if p.get('starter')]
        if not starters:
            continue
        ranked = sorted(players, key=lambda p: -(_score(p) or 0))
        best = [p for p in ranked[: len(starters)] if (_score(p) or 0) >= 0]
        best_ids = {id(p) for p in best}
        should_start = [p for p in best if not p.get('starter')]
        should_sit = sorted(
            (p for p in starters if id(p) not in best_ids), key=lambda p: -(_score(p) or 0)
        )
        for benched, started in zip(should_start, should_sit, strict=False):
            margin = (_score(benched) or 0) - (_score(started) or 0)
            if margin > 0:
                out.append((benched, started, margin))
    return out


def _player(player: dict, profile_key_for: Callable[[str], str]) -> dict:
    name = hof.clean_player_name(player.get('name', ''))
    position = hof.canonical_profile_position(player.get('position'))
    return {
        'player': name,
        'position': position,
        'profile_key': profile_key_for(hof.player_identity_key(name, position)),
    }


def _top(rows: list[dict], key: Callable[[dict], tuple]) -> list[dict]:
    return sorted(rows, key=key)[:TOP]


def _sections(rows: dict[str, list[dict]]) -> dict:
    newest = lambda r: (-r['season'], -r['week'])  # noqa: E731
    return {
        'bench_blunders': _top(rows['bench_blunders'], lambda r: (-r['margin'], *newest(r))),
        'bench_mvps': _top(rows['bench_mvps'], lambda r: (-r['points'], -r['games'])),
        'bench_games': _top(rows['bench_games'], lambda r: (-r['points'], *newest(r))),
        'ghost_starters': _top(rows['ghost_starters'], lambda r: (r['points'], *newest(r))),
        'unavailable_starters': _top(rows['unavailable_starters'], newest),
        'unavailable_counts': _top(rows['unavailable_counts'], lambda r: (-r['count'], r['owner'])),
        'special_teams': _top(rows['special_teams'], lambda r: (-r['gap'], *newest(r))),
        'perfect_lineups': _top(
            rows['perfect_lineups'], lambda r: (-r['count'], -r['rate'], r['owner'])
        ),
    }


def build_lineup_superlatives(
    all_seasons: list[dict],
    owner_label: Callable[[str, int], str],
    profile_key_for: Callable[[str], str] | None = None,
) -> dict:
    # Imported here: export_weekly_facts imports export_hall_of_fame at load.
    from scripts.export_weekly_facts import best_lineup

    key_for = profile_key_for or (lambda key: key)
    per_season: dict[int, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    bench_points: dict[tuple[int, str], dict] = {}
    unavailable: dict[tuple[int, str], dict] = {}
    perfect: dict[tuple[int, str], dict] = {}
    special_seen: set[tuple] = set()

    for game in _games(all_seasons):
        rows = per_season[game.season]
        fields = game.fields(owner_label)
        lost = game.score < game.opp_score

        for benched, started, margin in _blunders(game):
            flipped = lost and not game.two_week and game.score + margin > game.opp_score
            rows['bench_blunders'].append(
                {
                    **fields,
                    'benched': _player(benched, key_for),
                    'benched_score': _number(_score(benched) or 0),
                    'started': _player(started, key_for),
                    'started_score': _number(_score(started) or 0),
                    'margin': _number(margin),
                    'flipped': flipped,
                }
            )

        roster = game.team.get('roster', [])
        scored = [p for p in roster if _score(p) is not None]
        for player in scored:
            points = _score(player) or 0
            if not player.get('starter'):
                if points > 0:
                    info = _player(player, key_for)
                    rows['bench_games'].append({**fields, **info, 'points': _number(points)})
                    total = bench_points.setdefault(
                        (game.season, info['profile_key']),
                        {**info, 'season': game.season, 'points': 0.0, 'games': 0},
                    )
                    total['points'] += points
                    total['games'] += 1
                continue
            # A designation counts once the player didn't play: it can land
            # mid-game, and a doubtful player sometimes suits up.
            reason = player.get('unavailable_reason') if points == 0 else None
            if player.get('on_bye') or reason:
                rows['unavailable_starters'].append(
                    {
                        **fields,
                        **_player(player, key_for),
                        'reason': 'bye' if player.get('on_bye') else str(reason),
                    }
                )
                count = unavailable.setdefault(
                    (game.season, fields['owner_code']),
                    {
                        'season': game.season,
                        'owner_code': fields['owner_code'],
                        'owner': fields['owner'],
                        'team': game.abbrev,
                        'count': 0,
                    },
                )
                count['count'] += 1
                continue
            position = hof.canonical_profile_position(player.get('position'))
            if points <= 0 and player.get('found') is not False and position not in GHOST_EXCLUDED:
                rows['ghost_starters'].append(
                    {**fields, **_player(player, key_for), 'points': _number(points)}
                )

        # Perfect lineup, judged as the Hall of Fame's perfect_lineups is:
        # every rostered player scored and the score is the best possible.
        optimal = best_lineup(game.team, game.score)
        if optimal is not None and game.score > 0:
            tally = perfect.setdefault(
                (game.season, fields['owner_code']),
                {
                    'season': game.season,
                    'owner_code': fields['owner_code'],
                    'owner': fields['owner'],
                    'team': game.abbrev,
                    'count': 0,
                    'games': 0,
                },
            )
            tally['games'] += 1
            if game.score == optimal:
                tally['count'] += 1

        # Special teams, once per game from the winner's side.
        if game.score > game.opp_score and not game.two_week:
            key = (game.season, game.week, game.abbrev, fields['opponent'])
            if key not in special_seen:
                special_seen.add(key)
                margin = game.score - game.opp_score

                def unit(team: dict, position: str) -> float:
                    return sum(
                        _score(p) or 0
                        for p in team.get('roster', [])
                        if p.get('starter')
                        and hof.canonical_profile_position(p.get('position')) == position
                    )

                for position in SPECIAL_TEAMS:
                    gap = unit(game.team, position) - unit(game.opp, position)
                    if gap > margin:
                        rows['special_teams'].append(
                            {
                                **fields,
                                'unit': position,
                                'gap': _number(gap),
                                'margin': _number(margin),
                            }
                        )

    for (season, _), total in bench_points.items():
        total['points'] = _number(total['points'])
        per_season[season]['bench_mvps'].append(total)
    for (season, _), count in unavailable.items():
        per_season[season]['unavailable_counts'].append(count)
    for (season, _), tally in perfect.items():
        tally['rate'] = round(tally['count'] / tally['games'], 3) if tally['games'] else 0
        per_season[season]['perfect_lineups'].append(tally)

    # All-time: every season's rows, with season totals rolled up by player
    # (bench MVPs) and owner (blunder and perfect-lineup counts).
    all_rows: dict[str, list[dict]] = defaultdict(list)
    for rows in per_season.values():
        for name, items in rows.items():
            all_rows[name].extend(items)

    def rolled(items: list[dict], key: str, sums: tuple[str, ...]) -> list[dict]:
        merged: dict[str, dict] = {}
        for item in items:
            row = merged.setdefault(item[key], {**item, **dict.fromkeys(sums, 0), 'seasons': 0})
            for s in sums:
                row[s] += item[s]
            row['seasons'] += 1
            row.pop('season', None)
        for row in merged.values():
            for s in sums:
                row[s] = _number(row[s])
        return list(merged.values())

    all_rows['bench_mvps'] = rolled(all_rows['bench_mvps'], 'profile_key', ('points', 'games'))
    all_rows['unavailable_counts'] = rolled(
        all_rows['unavailable_counts'], 'owner_code', ('count',)
    )
    perfect_all = rolled(all_rows['perfect_lineups'], 'owner_code', ('count', 'games'))
    for row in perfect_all:
        row['rate'] = round(row['count'] / row['games'], 3) if row['games'] else 0
    all_rows['perfect_lineups'] = perfect_all

    seasons = sorted(per_season, reverse=True)
    return {
        'seasons': seasons,
        'by_season': {str(season): _sections(per_season[season]) for season in seasons},
        'all_time': _sections(all_rows),
    }
