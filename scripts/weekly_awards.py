"""Weekly Awards: a fixed set of superlatives for one finished week.

Written into the week's facts file as `awards` by
scripts/export_weekly_facts.py, shown on Matchups once the week is final and
listed in the commissioner's newsletter export. Teams appear as
`{team:ABBREV}` tokens, as in the weekly facts, so the site and the newsletter
name them the same way.

Awards, each left out when nothing qualifies:
- Top Score and Bottom Score: the week's highest and lowest team totals.
- Biggest Blowout and Nail-biter: the widest and closest one-week results.
- Bench MVP: the highest score left on a bench.
- Benching Blunder: the biggest gap between a benched player and the starter
  he should have replaced (the Lineups tab's swap logic).
- Best Player: the week's top starter.
- Best Pickup: the top starter who wasn't on any roster in one of the two
  weeks before (a free-agent add, or a midseason draft pick).
"""

from __future__ import annotations

from qpfl.weekly_facts import PlayerGame, TeamGame
from scripts.hof_lineups import lineup_swaps

PICKUP_LOOKBACK_WEEKS = 2

Timeline = dict[tuple[int, int], dict[str, str]]


def _points(value: float) -> float:
    return int(value) if float(value).is_integer() else round(value, 2)


def _score_line(g: TeamGame) -> str:
    verb = 'beat' if g.won else 'lost to' if g.lost else 'tied'
    return f'{verb} {{team:{g.opp_abbrev}}} {_points(g.score)}-{_points(g.opp_score)}'


def _games(team_games: list[TeamGame], season: int, week: int) -> list[TeamGame]:
    return [
        g
        for g in team_games
        if g.season == season and g.week == week and (g.score > 0 or g.opp_score > 0)
    ]


def _pickups(
    starters: list[PlayerGame], timeline: Timeline, season: int, week: int
) -> list[PlayerGame]:
    earlier = [
        timeline[(season, w)]
        for w in range(week - PICKUP_LOOKBACK_WEEKS, week)
        if (season, w) in timeline
    ]
    if not earlier:
        return []
    # Team units (D/ST, OL) aren't in the roster timeline, and aren't pickups.
    return [
        p
        for p in starters
        if '::' not in p.player_key and any(p.player_key not in owners for owners in earlier)
    ]


def week_awards(
    team_games: list[TeamGame],
    player_games: list[PlayerGame],
    season: int,
    week: int,
    timeline: Timeline | None = None,
) -> list[dict]:
    games = _games(team_games, season, week)
    if not games:
        return []
    players = [p for p in player_games if p.season == season and p.week == week]
    starters = [p for p in players if p.starter and p.score > 0]
    bench = [p for p in players if not p.starter and p.score > 0]
    # One row per one-week game, from the winner's side (or either, if tied).
    singles = [
        g for g in games if g.single_game and (g.won or (not g.lost and g.abbrev < g.opp_abbrev))
    ]
    awards: list[dict] = []

    def add(key: str, title: str, team: str, value: float, unit: str, subject: str, detail: str):
        awards.append(
            {
                'key': key,
                'title': title,
                'team': team,
                'value': _points(value),
                'unit': unit,
                'subject': subject,
                'detail': detail,
            }
        )

    top = max(games, key=lambda g: (g.score, g.abbrev))
    add(
        'top_score',
        'Top Score',
        top.abbrev,
        top.score,
        'pts',
        f'{{team:{top.abbrev}}}',
        _score_line(top),
    )
    bottom = min(games, key=lambda g: (g.score, g.abbrev))
    add(
        'bottom_score',
        'Bottom Score',
        bottom.abbrev,
        bottom.score,
        'pts',
        f'{{team:{bottom.abbrev}}}',
        _score_line(bottom),
    )
    if singles:
        blowout = max(singles, key=lambda g: (g.score - g.opp_score, g.abbrev))
        add(
            'blowout',
            'Biggest Blowout',
            blowout.abbrev,
            blowout.score - blowout.opp_score,
            'margin',
            f'{{team:{blowout.abbrev}}}',
            _score_line(blowout),
        )
        close = min(singles, key=lambda g: (g.score - g.opp_score, g.abbrev))
        add(
            'nail_biter',
            'Nail-biter',
            close.abbrev,
            close.score - close.opp_score,
            'margin',
            f'{{team:{close.abbrev}}}',
            _score_line(close),
        )
    if bench:
        mvp = max(bench, key=lambda p: (p.score, p.name))
        add(
            'bench_mvp',
            'Bench MVP',
            mvp.abbrev,
            mvp.score,
            'pts',
            mvp.name,
            f"{mvp.position} on {{team:{mvp.abbrev}}}'s bench",
        )

    blunders = []
    for g in games:
        roster = [
            {'name': p.name, 'position': p.position, 'score': p.score, 'starter': p.starter}
            for p in players
            if p.abbrev == g.abbrev
        ]
        for benched, started, margin in lineup_swaps(roster):
            blunders.append((margin, g, benched, started))
    if blunders:
        margin, g, benched, started = max(blunders, key=lambda b: (b[0], b[1].abbrev))
        cost = (
            ', and it cost the game'
            if g.lost and g.single_game and g.score + margin > g.opp_score
            else ''
        )
        add(
            'benching_blunder',
            'Benching Blunder',
            g.abbrev,
            margin,
            'pts',
            f'{{team:{g.abbrev}}}',
            f'benched {benched["name"]} ({_points(benched["score"])}) for '
            f'{started["name"]} ({_points(started["score"])}){cost}',
        )

    if starters:
        best = max(starters, key=lambda p: (p.score, p.name))
        add(
            'best_player',
            'Best Player',
            best.abbrev,
            best.score,
            'pts',
            best.name,
            f'{best.position} for {{team:{best.abbrev}}}',
        )
    pickups = _pickups(starters, timeline or {}, season, week)
    if pickups:
        pickup = max(pickups, key=lambda p: (p.score, p.name))
        add(
            'best_pickup',
            'Best Pickup',
            pickup.abbrev,
            pickup.score,
            'pts',
            pickup.name,
            f'{pickup.position}, added by {{team:{pickup.abbrev}}} in the last two weeks',
        )
    return awards
