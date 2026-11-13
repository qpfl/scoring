"""Postgame recap notes for each matchup of a finished week.

The weekly "By the Numbers" notes (`qpfl.weekly_facts`) keep to what is
notable across the whole league. A matchup's recap says as much as it can
about that one game: where the series stands, how the margin and the scores
rank in the owners' history and the league's, upsets against the projection,
who carried each side, player scores that crack the record book, and the
final's place in scorigami history.

Notes use the same `Fact` shape and `{team:X}` tokens as the weekly facts.
They are written into each week's facts file under `recaps` by
scripts/export_weekly_facts.py and shown in the site's matchup Recap.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from qpfl import scorigami
from qpfl.weekly_facts import (
    PLAYER,
    TEAM,
    Fact,
    PlayerGame,
    TeamGame,
    WeekContext,
    _result,
    _runs,
    _series,
    _sides,
    article,
    number,
    rank_phrase,
    record,
    team,
    when,
)

# How far down a ranking a game still earns a note.
SERIES_RANK = 3
LEAGUE_RANK = 25
OWNER_RANK = 5
PLAYER_RANK = 10
# Meetings before a series ranking means anything.
SERIES_MIN_GAMES = 3
SERIES_DEEP_GAMES = 6
# A player score shared by this many others (head coaches, kickers) is no feat.
PLAYER_TIES_MAX = 2
# A projection gap the winner overcame before it counts as an upset.
UPSET_POINTS = 3
STREAK_MIN = 2


def _possessive(name: str) -> str:
    return f"{name}'" if name.endswith('s') else f"{name}'s"


def _count(value: float, unit: str) -> str:
    return f'{number(value)} {unit}' + ('' if value == 1 else 's')


def _ranked(value: float, population: Iterable[float], higher: bool = True) -> tuple[int, int]:
    """(rank, others tied) of a value within a population that holds it."""
    values = list(population)
    better = sum(1 for v in values if (v > value if higher else v < value))
    tied = sum(1 for v in values if v == value) - 1
    return better + 1, max(tied, 0)


def _owners_games(ctx: WeekContext, game: TeamGame) -> list[TeamGame]:
    """Every scored game this side's owners have played, through this week."""
    mine = _sides(game)[0]
    return [g for g in ctx.team_all if _sides(g)[0] & mine and g.score > 0]


def _series_notes(ctx: WeekContext, winner: TeamGame, loser: TeamGame) -> list[Fact]:
    subjects = [winner.abbrev, loser.abbrev]
    series = [g for g in _series(ctx, winner) if g.decided and g.score > 0]
    if not series:
        return []
    wins = sum(1 for g in series if g.won)
    losses = sum(1 for g in series if g.lost)
    ties = len(series) - wins - losses
    notes = []
    if len(series) == 1:
        verb = 'tied' if not winner.won else 'won'
        notes.append(
            Fact(
                'recap_series_first',
                TEAM,
                subjects,
                f'{team(winner.abbrev)} {verb} the first meeting between the two.',
                0.5,
            )
        )
    else:
        result, length = _runs([_result(g) for g in series])[-1]
        if winner.won and wins == losses:
            text = f'{team(winner.abbrev)} evened the series at {record(wins, losses, ties)}.'
        elif winner.won and wins == losses + 1:
            text = (
                f'{team(winner.abbrev)} took the lead in the series, {record(wins, losses, ties)}.'
            )
        else:
            lead = winner if wins >= losses else loser
            high, low = max(wins, losses), min(wins, losses)
            word = 'leads' if lead is winner else 'still leads'
            text = (
                f'{team(lead.abbrev)} {word} the series {record(high, low, ties)} '
                f'after {len(series)} meetings.'
                if high != low
                else f'The series is level at {record(wins, losses, ties)}.'
            )
        notes.append(Fact('recap_series_record', TEAM, subjects, text, 0.4))
        if result == 'W' and STREAK_MIN <= length < len(series):
            notes.append(
                Fact(
                    'recap_series_streak',
                    TEAM,
                    subjects,
                    f"That's {length} straight for {team(winner.abbrev)} against "
                    f'{team(loser.abbrev)}.',
                    0.35 + 0.04 * min(length, 8),
                )
            )
        else:
            # A win that ends the other side's run.
            previous = _runs([_result(g) for g in series[:-1]])
            if previous and previous[-1][0] == 'L' and previous[-1][1] >= 3 and winner.won:
                notes.append(
                    Fact(
                        'recap_series_snapped',
                        TEAM,
                        subjects,
                        f'{team(winner.abbrev)} snapped {article(previous[-1][1])} '
                        f'{previous[-1][1]}-game losing run '
                        f'against {team(loser.abbrev)}.',
                        0.55,
                    )
                )

    single = [g for g in series if g.single_game]
    if winner.single_game and len(single) >= SERIES_MIN_GAMES and winner.won:
        margins = [g.margin for g in single]
        size = len(single)
        # Second or third of a handful of meetings says little.
        reach = SERIES_RANK if size >= SERIES_DEEP_GAMES else 1
        rank, tied = _ranked(winner.margin, margins)
        if rank <= reach:
            notes.append(
                Fact(
                    'recap_series_blowout',
                    TEAM,
                    subjects,
                    f'The {number(winner.margin)}-point margin was '
                    f'{rank_phrase(rank, tied, "largest")} in {size} meetings between them.',
                    0.55 - 0.05 * (rank - 1),
                )
            )
        rank, tied = _ranked(winner.margin, margins, higher=False)
        if rank <= reach and winner.margin <= 10:
            notes.append(
                Fact(
                    'recap_series_close',
                    TEAM,
                    subjects,
                    f'At {_count(winner.margin, "point")}, it was '
                    f'{rank_phrase(rank, tied, "closest")} of their {size} meetings.',
                    0.5 - 0.05 * (rank - 1),
                )
            )
        totals = [g.score + g.opp_score for g in single]
        combined = winner.score + winner.opp_score
        for higher, word in ((True, 'highest'), (False, 'lowest')):
            rank, tied = _ranked(combined, totals, higher)
            if rank <= min(reach, 2):
                notes.append(
                    Fact(
                        f'recap_series_{word}_scoring',
                        TEAM,
                        subjects,
                        f'Their {number(combined)} combined points were '
                        f'{rank_phrase(rank, tied, word)}-scoring meeting of {size}.',
                        0.4,
                    )
                )
    return notes


def _margin_notes(ctx: WeekContext, winner: TeamGame, loser: TeamGame) -> list[Fact]:
    if not winner.single_game or not winner.won:
        return []
    subjects = [winner.abbrev, loser.abbrev]
    league = [g.margin for g in ctx.team_all if g.single_game and g.won and g.score > 0]
    rank, tied = _ranked(winner.margin, league)
    notes = []
    if rank <= LEAGUE_RANK:
        notes.append(
            Fact(
                'recap_league_blowout',
                TEAM,
                subjects,
                f'A {number(winner.margin)}-point win, {rank_phrase(rank, tied, "largest")} '
                f'margin in league history ({len(league)} games).',
                0.6 + 0.2 / rank,
            )
        )
    season = [
        g.margin
        for g in ctx.team_all
        if g.season == ctx.season and g.single_game and g.won and g.score > 0
    ]
    rank, tied = _ranked(winner.margin, season)
    if rank == 1 and len(season) > 5:
        notes.append(
            Fact(
                'recap_season_blowout',
                TEAM,
                subjects,
                f'The {number(winner.margin)}-point margin is {rank_phrase(1, tied, "largest")} '
                f'of the {ctx.season} season.',
                0.5,
            )
        )
    rank, tied = _ranked(winner.margin, league, higher=False)
    if rank <= LEAGUE_RANK and winner.margin <= 3:
        notes.append(
            Fact(
                'recap_league_close',
                TEAM,
                subjects,
                f'Decided by {_count(winner.margin, "point")}, {rank_phrase(rank, tied, "closest")} '
                'finish in league history.',
                0.55,
            )
        )
    return notes


def _score_notes(ctx: WeekContext, game: TeamGame) -> list[Fact]:
    """Where one side's score ranks: the league, its owners, the season."""
    if game.score <= 0 or not game.single_game:
        return []
    subjects = [game.abbrev]
    notes = []
    league = [g.score for g in ctx.team_all if g.score > 0 and g.single_game]
    for higher, word, weight in ((True, 'highest', 0.6), (False, 'lowest', 0.45)):
        rank, tied = _ranked(game.score, league, higher)
        if rank <= LEAGUE_RANK:
            notes.append(
                Fact(
                    f'recap_league_{word}_score',
                    TEAM,
                    subjects,
                    f'{team(game.abbrev)} scored {number(game.score)}, '
                    f'{rank_phrase(rank, tied, word)} score in league history.',
                    weight + 0.2 / rank,
                )
            )
            return notes
    owners = [g.score for g in _owners_games(ctx, game) if g.single_game]
    if len(owners) >= 10:
        for higher, word in ((True, 'best'), (False, 'worst')):
            rank, tied = _ranked(game.score, owners, higher)
            if rank <= OWNER_RANK:
                notes.append(
                    Fact(
                        f'recap_owner_{word}_score',
                        TEAM,
                        subjects,
                        f'{number(game.score)} was {rank_phrase(rank, tied, word)} score of '
                        f"{team(game.abbrev)}'s {len(owners)} career games.",
                        0.45 + 0.1 / rank,
                    )
                )
                return notes
    season = [g.score for g in _owners_games(ctx, game) if g.season == ctx.season and g.single_game]
    if len(season) >= 3:
        for higher, word in ((True, 'high'), (False, 'low')):
            rank, tied = _ranked(game.score, season, higher)
            if rank == 1:
                notes.append(
                    Fact(
                        f'recap_season_{word}',
                        TEAM,
                        subjects,
                        f"{number(game.score)} was {team(game.abbrev)}'s season "
                        f'{word}{" (tied)" if tied else ""}.',
                        0.35,
                    )
                )
                break
    return notes


def _week_rank_notes(ctx: WeekContext, game: TeamGame) -> list[Fact]:
    scores = [g.score for g in ctx.current if g.score > 0]
    if game.score <= 0 or len(scores) < 4:
        return []
    for higher, word in ((True, 'top'), (False, 'bottom')):
        rank, tied = _ranked(game.score, scores, higher)
        if rank == 1:
            tail = 'tied for the' if tied else 'the'
            return [
                Fact(
                    f'recap_week_{word}',
                    TEAM,
                    [game.abbrev],
                    f"{team(game.abbrev)}'s {number(game.score)} was {tail} week's "
                    f'{"highest" if higher else "lowest"} score.',
                    0.4,
                )
            ]
    return []


def _projection_notes(winner: TeamGame, loser: TeamGame) -> list[Fact]:
    if winner.projected is None or loser.projected is None or not winner.won:
        return []
    gap = loser.projected - winner.projected
    subjects = [winner.abbrev, loser.abbrev]
    if gap >= UPSET_POINTS:
        return [
            Fact(
                'recap_upset',
                TEAM,
                subjects,
                f'An upset: {team(winner.abbrev)} won despite a projected '
                f'{number(round(gap, 1))}-point deficit.',
                0.5 + min(gap, 30) / 100,
            )
        ]
    notes = []
    for side in (winner, loser):
        beat = side.score - (side.projected or 0)
        if abs(beat) >= 25:
            word = 'beat' if beat > 0 else 'fell short of'
            notes.append(
                Fact(
                    f'recap_projection_{"beat" if beat > 0 else "miss"}',
                    TEAM,
                    [side.abbrev],
                    f'{team(side.abbrev)} {word} {article(round(side.projected or 0))} '
                    f'{number(round(side.projected or 0, 1))}-point '
                    f'projection by {number(round(abs(beat), 1))}.',
                    0.4,
                )
            )
    return notes


def _player_notes(
    ctx: WeekContext, winner: TeamGame, loser: TeamGame, players: list[PlayerGame]
) -> list[Fact]:
    """The game's top scorer, and starts that crack a record list."""
    in_game = [
        p for p in players if p.abbrev in (winner.abbrev, loser.abbrev) and p.score is not None
    ]
    if not in_game:
        return []
    notes = []
    best = max(in_game, key=lambda p: p.score)
    if best.score > 0:
        notes.append(
            Fact(
                'recap_top_player',
                PLAYER,
                [best.abbrev],
                f'{best.name} ({best.position}) led the game with '
                f'{_count(best.score, "point")} for {team(best.abbrev)}.',
                0.35,
                [best.name],
            )
        )
    by_position: dict[str, list[float]] = defaultdict(list)
    season_position: dict[str, list[float]] = defaultdict(list)
    for p in ctx.player_all:
        by_position[p.position].append(p.score)
        if p.season == ctx.season:
            season_position[p.position].append(p.score)
    for p in sorted(in_game, key=lambda p: -p.score):
        if p.score <= 0:
            continue
        rank, tied = _ranked(p.score, by_position[p.position])
        if rank <= PLAYER_RANK and tied <= PLAYER_TIES_MAX:
            notes.append(
                Fact(
                    'recap_player_record',
                    PLAYER,
                    [p.abbrev],
                    f'{_possessive(p.name)} {number(p.score)} is {rank_phrase(rank, tied, "most")} by a '
                    f'{p.position} in a QPFL game.',
                    0.55 + 0.2 / rank,
                    [p.name],
                )
            )
            continue
        rank, tied = _ranked(p.score, season_position[p.position])
        if rank == 1 and not tied and len(season_position[p.position]) > 10:
            notes.append(
                Fact(
                    'recap_player_season_high',
                    PLAYER,
                    [p.abbrev],
                    f'{_possessive(p.name)} {number(p.score)} is {rank_phrase(1, tied, "most")} by a '
                    f'{p.position} this season.',
                    0.45,
                    [p.name],
                )
            )
    return notes


def _lineup_notes(game: TeamGame, opponent: TeamGame) -> list[Fact]:
    if game.optimal is None or game.score <= 0:
        return []
    left = game.optimal - game.score
    if game.lost and game.optimal > opponent.score:
        return []  # the weekly notes already call out a lineup that cost the game
    if left < 15:
        return []
    return [
        Fact(
            'recap_bench_points',
            TEAM,
            [game.abbrev],
            f'{team(game.abbrev)} left {_count(round(left, 1), "point")} on the bench '
            f'(best possible lineup: {number(round(game.optimal, 1))}).',
            0.3,
        )
    ]


def _scorigami_note(ctx: WeekContext, winner: TeamGame, loser: TeamGame) -> list[Fact]:
    prior = scorigami.finals(ctx.history)
    current = [
        f
        for f in scorigami.finals(ctx.current)
        if {f.winner, f.loser} == {winner.abbrev, loser.abbrev}
    ]
    if not current or len(prior) < 50:
        return []
    final = current[0]
    seen = [f for f in prior if f.score == final.score]
    score = f'{final.high}-{final.low}'
    if not seen:
        text = f'Scorigami: the first {score} final in QPFL history.'
    else:
        last = seen[-1]
        times = 'once' if len(seen) == 1 else 'twice' if len(seen) == 2 else f'{len(seen)} times'
        text = (
            f'Not a scorigami: {score} had happened {times} before '
            f'(most recently {when(last.week_label, last.season)}).'
        )
    return [Fact('recap_scorigami', TEAM, [winner.abbrev, loser.abbrev], text, 0.3)]


# Recap notes the weekly notes may already cover: (recap id prefix, weekly id
# prefixes). The weekly note wins.
COVERED = (
    ('recap_series_record', ('h2h_', 'rivalry_wins')),
    ('recap_series_streak', ('h2h_',)),
    ('recap_series_snapped', ('h2h_',)),
    ('recap_series_first', ('h2h_',)),
    ('recap_series_blowout', ('rivalry_margin_alltime',)),
    ('recap_series_close', ('rivalry_margin_close',)),
    ('recap_series_highest', ('rivalry_series_best',)),
    ('recap_upset', ('projection_upset',)),
    ('recap_projection_', ('projection_beat', 'projection_miss')),
    ('recap_scorigami', ('scorigami_new', 'scorigami_repeat')),
    ('recap_league_blowout', ('margin_alltime', 'rivalry_margin_alltime')),
    ('recap_league_close', ('week_margin_', 'rivalry_margin_close')),
    ('recap_league_highest_score', ('team_score_',)),
    ('recap_league_lowest_score', ('team_score_',)),
    ('recap_owner_', ('team_score_',)),
    ('recap_season_high', ('team_score_',)),
    ('recap_season_low', ('team_score_',)),
    ('recap_week_', ('week_top_low',)),
    ('recap_bench_points', ('bench_points', 'lineup_cost')),
)
PLAYER_COVERED = ('player_game', 'player_franchise_record', 'player_carry', 'player_hot_streak')


def merge_with_weekly(recaps: list[dict], weekly: list[dict]) -> list[dict]:
    """Each recap's notes with the week's own notes about that matchup (every
    team they name played in it), minus recap notes those already cover."""
    out = []
    for recap in recaps:
        pair = {recap['team1'], recap['team2']}
        mine = [f for f in weekly if f.get('subjects') and set(f['subjects']) <= pair]
        notes = list(mine)
        for note in recap['notes']:
            subjects = set(note['subjects'])
            related = [f for f in mine if subjects & set(f['subjects'])]
            covered = any(
                note['id'].startswith(prefix)
                and any(f['id'].startswith(w) for f in related for w in weekly_ids)
                for prefix, weekly_ids in COVERED
            )
            name = note['tags'][0] if note.get('tags') else None
            if name and any(
                f['id'].startswith(PLAYER_COVERED) and name in f['template'] for f in related
            ):
                covered = True
            if not covered:
                notes.append(note)
        notes.sort(key=lambda f: -f['notability'])
        out.append({**recap, 'notes': notes})
    return out


def generate_recaps(
    team_games: list[TeamGame],
    player_games: list[PlayerGame],
    season: int,
    week: int,
    first_season: int | None = None,
) -> list[dict]:
    """[{team1, team2, notes}] for each of the week's matchups, most notable first."""
    ctx = WeekContext(team_games, player_games, season, week, first_season)
    out = []
    for winner, loser in ctx.matchups():
        notes: list[Fact] = []
        notes += _series_notes(ctx, winner, loser)
        notes += _margin_notes(ctx, winner, loser)
        notes += _projection_notes(winner, loser)
        for side, other in ((winner, loser), (loser, winner)):
            notes += _score_notes(ctx, side)
            notes += _week_rank_notes(ctx, side)
            notes += _lineup_notes(side, other)
        notes += _player_notes(ctx, winner, loser, ctx.player_current)
        notes += _scorigami_note(ctx, winner, loser)
        seen = set()
        unique = []
        for note in sorted(notes, key=lambda f: -f.notability):
            if note.template in seen:
                continue
            seen.add(note.template)
            unique.append(note)
        out.append(
            {
                'team1': winner.abbrev,
                'team2': loser.abbrev,
                'notes': [f.to_dict() for f in unique],
            }
        )
    return out
