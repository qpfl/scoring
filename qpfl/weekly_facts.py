"""Weekly "By the Numbers" facts: one week's results in league-history context.

The engine is pure. It takes every team and player game the league has played
(flattened by `scripts/export_weekly_facts.py`) plus a target week, compares the
target week only against what came before it, and returns notes like "the
4th-highest score in league history" or "the most since Week 9, 2024".

Facts name teams with `{team:ABBREV}` tokens so the newsletter (owner short
names) and the site (team names) can each render them their own way.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

REGULAR = 'regular'
PLAYOFFS = 'playoffs'
CONSOLATION = 'consolation'

LEAGUE = 'league'
TEAM = 'team'
PLAYER = 'player'

# How far down an all-time list a result has to land to be worth a note.
LEAGUE_TOP = 10
LEAGUE_TOP_SHORT = 5
FRANCHISE_TOP = 5
# "One of only N" clubs stay notable while they are this small.
MARGIN_CLUB_MAX = 15
PLAYER_CLUB_MAX_GAMES = 25
POSITION_CLUB_MAX_GAMES = 10
# A "most since" callback needs at least this many league weeks of gap.
SINCE_MIN_GAP_WEEKS = 17
SINCE_STANDALONE_GAP_WEEKS = 34
MIN_FRANCHISE_GAMES = 20
STREAK_MIN = 4
SNAPPED_STREAK_MIN = 5
CAREER_MILESTONES = (250, 500, 750, 1000, 1250, 1500, 2000, 2500, 3000)
BIG_GAME_POINTS = 40
HOT_STREAK_POINTS = 30
HOT_STREAK_MIN = 3
# Season starts and career clubs stop being news once this many have done it.
RARE_CLUB_MAX = 6
MILESTONE_CLUB_MAX = 10
MILESTONE_POSITIONS = ('QB', 'RB', 'WR', 'TE')
# Team-unit positions score in narrow, heavily tied ranges; ranking them is noise.
RANKED_POSITIONS = ('QB', 'RB', 'WR', 'TE', 'K', 'D/ST')
CLUB_POSITIONS = ('QB', 'RB', 'WR', 'TE', 'D/ST')

CATEGORY_WEIGHT = {LEAGUE: 1.0, PLAYER: 0.9, TEAM: 0.8}


# --------------------------------------------------------------------------- #
# Rows
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TeamGame:
    season: int
    week: int
    week_label: str
    bracket: str
    abbrev: str
    franchises: tuple[str, ...]
    score: float
    opp_abbrev: str
    opp_franchises: tuple[str, ...]
    opp_score: float
    # Two-week playoff legs: each week's score is real, but only the final leg
    # carries a result, decided by the two-week totals in result_*_score.
    two_week: bool = False
    result_score: float | None = None
    result_opp_score: float | None = None

    @property
    def order(self) -> tuple[int, int]:
        return (self.season, self.week)

    @property
    def single_game(self) -> bool:
        """A one-week matchup, whose margin and combined score mean something."""
        return not self.two_week

    @property
    def decided(self) -> bool:
        """Carries a win/loss: every one-week game, plus a two-week final leg."""
        return not self.two_week or self.result_score is not None

    def _result_scores(self) -> tuple[float, float]:
        if self.result_score is not None and self.result_opp_score is not None:
            return self.result_score, self.result_opp_score
        return self.score, self.opp_score

    @property
    def won(self) -> bool:
        mine, theirs = self._result_scores()
        return self.decided and mine > theirs

    @property
    def lost(self) -> bool:
        mine, theirs = self._result_scores()
        return self.decided and mine < theirs

    @property
    def margin(self) -> float:
        return abs(self.score - self.opp_score)


@dataclass(frozen=True)
class PlayerGame:
    season: int
    week: int
    week_label: str
    bracket: str
    player_key: str
    name: str
    position: str
    abbrev: str
    franchises: tuple[str, ...]
    score: float

    @property
    def order(self) -> tuple[int, int]:
        return (self.season, self.week)


@dataclass
class Fact:
    id: str
    category: str
    subjects: list[str]
    template: str
    notability: float
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'category': self.category,
            'subjects': self.subjects,
            'template': self.template,
            'notability': round(self.notability, 3),
            'tags': self.tags,
        }


# --------------------------------------------------------------------------- #
# Primitives
# --------------------------------------------------------------------------- #


def rank_of(value: float, population: Iterable[float], higher: bool = True) -> tuple[int, int, int]:
    """Rank `value` within a population that already contains it.

    Returns (rank, total, tied) where `tied` counts the *other* entries with
    the same value, so a unique record is (1, n, 0).
    """
    values = list(population)
    better = sum(1 for v in values if (v > value if higher else v < value))
    tied = sum(1 for v in values if v == value) - 1
    return better + 1, len(values), max(tied, 0)


def ordinal(number: int) -> str:
    if 10 <= number % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(number % 10, 'th')
    return f'{number}{suffix}'


def nth(number: int) -> str:
    """'first' reads better than '1st' in prose."""
    return 'first' if number == 1 else ordinal(number)


def article(number: int) -> str:
    """'a' or 'an' before a spoken number (an 8-game, an 11-game)."""
    return 'an' if str(number).startswith('8') or number in (11, 18) else 'a'


def rank_phrase(rank: int, tied: int, superlative: str) -> str:
    """'the highest', 'tied for the 3rd-highest', ..."""
    core = superlative if rank == 1 else f'{ordinal(rank)}-{superlative}'
    return f'tied for the {core}' if tied else f'the {core}'


def number(value: float) -> str:
    value = float(value)
    return f'{value:,.0f}' if value.is_integer() else f'{value:,.1f}'


def team(abbrev: str) -> str:
    return f'{{team:{abbrev}}}'


def has(abbrev: str) -> str:
    """'has' or 'have', agreeing with however the consumer names the team."""
    return f'{{has:{abbrev}}}'


def is_(abbrev: str) -> str:
    """'is' or 'are', agreeing with however the consumer names the team."""
    return f'{{is:{abbrev}}}'


TOKEN_PATTERN = re.compile(r'\{(team|has|is):([^}]+)\}')
PLURAL_VERBS = {'has': 'have', 'is': 'are'}


def is_plural_name(name: str) -> bool:
    """Co-owned teams read as plural: 'Spencer/Tim have', 'Joe & Joe are'."""
    return '/' in name or '&' in name or ' and ' in name


def render(template: str, names: dict[str, str]) -> str:
    """Swap `{team:X}` tokens for display names (falling back to the abbrev)
    and `{has:X}`/`{is:X}` for verbs that agree with that name. The newsletter
    and site renderers mirror this."""

    def swap(match: re.Match[str]) -> str:
        kind: str = match.group(1)
        abbrev: str = match.group(2)
        name = names.get(abbrev, abbrev)
        if kind == 'team':
            return name
        return PLURAL_VERBS[kind] if is_plural_name(name) else kind

    return TOKEN_PATTERN.sub(swap, template)


def when(label: str, season: int) -> str:
    if label.startswith('Week '):
        return f'{label}, {season}'
    return f'the {season} {label}'


def week_index(orders: Iterable[tuple[int, int]]) -> dict[tuple[int, int], int]:
    return {order: i for i, order in enumerate(sorted(set(orders)))}


def _rarity(rank: int) -> float:
    """1.0 for a record, decaying with rank."""
    return 1.0 / math.pow(rank, 0.6)


def _scope_tags(bracket: str) -> list[str]:
    return [bracket]


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #


class WeekContext:
    """Everything a detector needs: the target week and the history before it."""

    def __init__(
        self,
        team_games: list[TeamGame],
        player_games: list[PlayerGame],
        season: int,
        week: int,
        first_season: int | None = None,
    ):
        target = (season, week)
        if first_season is not None:
            team_games = [g for g in team_games if g.season >= first_season]
            player_games = [g for g in player_games if g.season >= first_season]
        self.season = season
        self.week = week
        self.target = target
        self.team_all = sorted((g for g in team_games if g.order <= target), key=lambda g: g.order)
        self.player_all = sorted(
            (g for g in player_games if g.order <= target), key=lambda g: g.order
        )
        self.current = [g for g in self.team_all if g.order == target]
        self.history = [g for g in self.team_all if g.order < target]
        self.player_current = [g for g in self.player_all if g.order == target]
        self.player_history = [g for g in self.player_all if g.order < target]
        self.index = week_index(g.order for g in self.team_all)

    def gap_weeks(self, order: tuple[int, int]) -> int:
        return self.index.get(self.target, 0) - self.index.get(order, 0)

    def matchups(self) -> list[tuple[TeamGame, TeamGame]]:
        """This week's matchups, each listed once as (winner-or-first, other)."""
        seen = set()
        pairs = []
        for game in self.current:
            key = (game.abbrev, game.opp_abbrev)
            if key in seen or (game.opp_abbrev, game.abbrev) in seen:
                continue
            opponent = next(
                (
                    g
                    for g in self.current
                    if g.abbrev == game.opp_abbrev and g.opp_abbrev == game.abbrev
                ),
                None,
            )
            if opponent is None:
                continue
            seen.add(key)
            first = game.won or (not opponent.won and game.score >= opponent.score)
            pairs.append((game, opponent) if first else (opponent, game))
        return pairs

    def franchise_games(self, franchise: str, games: Iterable[TeamGame]) -> list[TeamGame]:
        return [g for g in games if franchise in g.franchises]


def _primary_franchise(game: TeamGame) -> str:
    return game.franchises[0] if game.franchises else game.abbrev


def _unique_games(games: Iterable[TeamGame]) -> list[TeamGame]:
    """One row per matchup (team rows come in mirrored pairs)."""
    seen = set()
    out = []
    for g in games:
        key = (g.season, g.week, *sorted((g.abbrev, g.opp_abbrev)))
        if key in seen:
            continue
        seen.add(key)
        out.append(g)
    return out


def _most_since(
    ctx: WeekContext,
    value: float,
    games: Iterable[TeamGame],
    get: Callable[[TeamGame], float],
    higher: bool = True,
) -> TeamGame | None:
    """The latest prior game that matched or beat `value`, or None for a record."""
    latest = None
    for g in games:
        if g.order >= ctx.target:
            continue
        v = get(g)
        matched = v >= value if higher else v <= value
        if matched and (latest is None or g.order > latest.order):
            latest = g
    return latest


# --------------------------------------------------------------------------- #
# League + franchise team detectors
# --------------------------------------------------------------------------- #


def _team_score_facts(ctx: WeekContext) -> list[Fact]:
    facts = []
    scored = [g for g in ctx.team_all if g.score > 0]
    league_scores = [g.score for g in scored]
    for game in ctx.current:
        if game.score <= 0:
            continue
        for higher, word, fewest in ((True, 'highest', 'most'), (False, 'lowest', 'fewest')):
            rank, total, tied = rank_of(game.score, league_scores, higher)
            franchise = _primary_franchise(game)
            history = [g for g in scored if franchise in g.franchises]
            parts = []
            category = TEAM
            notability = 0.0
            if rank <= LEAGUE_TOP:
                parts.append(f'{rank_phrase(rank, tied, word)} score in league history')
                category = LEAGUE
                notability = _rarity(rank)
            elif len(history) >= MIN_FRANCHISE_GAMES:
                f_rank, _, f_tied = rank_of(game.score, [g.score for g in history], higher)
                if f_rank <= FRANCHISE_TOP:
                    parts.append(
                        f'{rank_phrase(f_rank, f_tied, fewest)} points in franchise history'
                    )
                    notability = 0.8 * _rarity(f_rank)
            since = _most_since(ctx, game.score, history, lambda g: g.score, higher)
            if since is not None:
                gap = ctx.gap_weeks(since.order)
                if parts and gap >= SINCE_MIN_GAP_WEEKS:
                    parts.append(f'the {fewest} since {when(since.week_label, since.season)}')
                elif not parts and gap >= SINCE_STANDALONE_GAP_WEEKS:
                    parts.append(
                        f'the {fewest} points since {when(since.week_label, since.season)}'
                    )
                    notability = 0.45 + min(gap, 102) / 102 * 0.25
            if not parts:
                continue
            text = f"{team(game.abbrev)}'s {number(game.score)} was {' and '.join(parts)}"
            facts.append(
                Fact(
                    id=f'team_score_{"high" if higher else "low"}',
                    category=category,
                    subjects=[game.abbrev],
                    template=text + '.',
                    notability=notability,
                    tags=_scope_tags(game.bracket),
                )
            )
    return facts


def _club_size(values: Iterable[float], threshold: float, higher: bool = True) -> int:
    return sum(1 for v in values if (v >= threshold if higher else v <= threshold))


def _matchup_facts(ctx: WeekContext) -> list[Fact]:
    facts = []
    decided = [
        g for g in _unique_games(ctx.team_all) if g.single_game and g.score > 0 and g.opp_score > 0
    ]
    margins = [g.margin for g in decided]
    combined = [g.score + g.opp_score for g in decided]
    for winner, loser in ctx.matchups():
        if not winner.single_game or winner.score <= 0 or loser.score <= 0:
            continue
        subjects = [winner.abbrev, loser.abbrev]
        tags = _scope_tags(winner.bracket)
        margin = winner.margin
        head = (
            f'{team(winner.abbrev)} and {team(loser.abbrev)} tied at {number(winner.score)}'
            if margin == 0
            else f'{team(winner.abbrev)} beat {team(loser.abbrev)} by {number(margin)}'
        )

        # Blowouts
        rank, _, tied = rank_of(margin, margins, True)
        if rank <= LEAGUE_TOP:
            facts.append(
                Fact(
                    'margin_alltime',
                    LEAGUE,
                    subjects,
                    f'{head}, {rank_phrase(rank, tied, "largest")} margin of victory in league history.',
                    _rarity(rank),
                    tags,
                )
            )
        else:
            for threshold in (100, 90, 80, 70, 60, 50, 40):
                if margin >= threshold:
                    size = _club_size(margins, threshold)
                    if size <= MARGIN_CLUB_MAX:
                        facts.append(
                            Fact(
                                'margin_club',
                                LEAGUE,
                                subjects,
                                f'{head}, one of only {size} games decided by {threshold}+ points in league history.',
                                0.35 + 0.3 / size**0.5,
                                tags,
                            )
                        )
                    break

        # Nail-biters
        rank, _, tied = rank_of(margin, margins, False)
        close_club = _club_size(margins, max(margin, 1), False)
        if margin <= 3 and close_club <= MARGIN_CLUB_MAX:
            what = (
                'a tie'
                if margin == 0
                else f'{number(max(margin, 1))} point{"s" if max(margin, 1) != 1 else ""} or fewer'
            )
            if margin == 0:
                text = f'{head}, just the {ordinal(_club_size(margins, 0, False))} tie in league history.'
            else:
                text = (
                    f'{head}, one of only {close_club} games decided by {what} in league history.'
                )
            facts.append(
                Fact('margin_close', LEAGUE, subjects, text, 0.4 + 0.3 / close_club**0.5, tags)
            )

        # Shootouts
        total = winner.score + loser.score
        rank, _, tied = rank_of(total, combined, True)
        if rank <= LEAGUE_TOP:
            facts.append(
                Fact(
                    'combined_alltime',
                    LEAGUE,
                    subjects,
                    f'{team(winner.abbrev)} ({number(winner.score)}) and {team(loser.abbrev)} '
                    f'({number(loser.score)}) combined for {number(total)}, '
                    f'{rank_phrase(rank, tied, "most")} in a matchup in league history.',
                    0.9 * _rarity(rank),
                    tags,
                )
            )

        # Hard-luck losses and lucky wins
        losing = [g.score for g in ctx.team_all if g.single_game and g.lost and g.score > 0]
        rank, _, tied = rank_of(loser.score, losing, True)
        if margin > 0 and rank <= LEAGUE_TOP_SHORT:
            facts.append(
                Fact(
                    'losing_score_high',
                    LEAGUE,
                    [loser.abbrev],
                    f"{team(loser.abbrev)}'s {number(loser.score)} in a loss to {team(winner.abbrev)} is "
                    f'{rank_phrase(rank, tied, "highest")} losing score in league history.',
                    0.85 * _rarity(rank),
                    tags,
                )
            )
        winning = [g.score for g in ctx.team_all if g.single_game and g.won and g.score > 0]
        rank, _, tied = rank_of(winner.score, winning, False)
        if margin > 0 and rank <= LEAGUE_TOP_SHORT:
            facts.append(
                Fact(
                    'winning_score_low',
                    LEAGUE,
                    [winner.abbrev],
                    f'{team(winner.abbrev)} won with just {number(winner.score)}, '
                    f'{rank_phrase(rank, tied, "lowest")} winning score in league history.',
                    0.85 * _rarity(rank),
                    tags,
                )
            )
    return facts


def _league_week_facts(ctx: WeekContext) -> list[Fact]:
    """Whole-week numbers, averaged per team so 8- and 10-team years compare."""
    by_week: dict[tuple[int, int], list[TeamGame]] = defaultdict(list)
    for g in ctx.team_all:
        by_week[g.order].append(g)
    complete = {
        order: games
        for order, games in by_week.items()
        if games and all(g.score > 0 for g in games)
    }
    if ctx.target not in complete:
        return []
    averages = {
        order: sum(g.score for g in games) / len(games) for order, games in complete.items()
    }
    tops = {order: max(g.score for g in games) for order, games in complete.items()}
    current = complete[ctx.target]
    tags = sorted({g.bracket for g in current})
    facts = []
    avg = averages[ctx.target]
    for higher, word in ((True, 'highest'), (False, 'lowest')):
        rank, _, tied = rank_of(round(avg, 1), [round(v, 1) for v in averages.values()], higher)
        if rank <= LEAGUE_TOP_SHORT:
            facts.append(
                Fact(
                    f'league_week_{"high" if higher else "low"}',
                    LEAGUE,
                    [],
                    f'Teams averaged {number(round(avg, 1))} points this week, '
                    f'{rank_phrase(rank, tied, word)}-scoring week in league history.',
                    0.95 * _rarity(rank),
                    tags,
                )
            )
    top = tops[ctx.target]
    rank, _, tied = rank_of(top, list(tops.values()), False)
    if rank <= 3:
        leader = next(g for g in current if g.score == top)
        facts.append(
            Fact(
                'week_top_low',
                LEAGUE,
                [leader.abbrev],
                f"{team(leader.abbrev)}'s {number(top)} led the league, "
                f'{rank_phrase(rank, tied, "lowest")} score to top a week in league history.',
                0.7 * _rarity(rank),
                tags,
            )
        )
    return facts


def _runs(results: list[str]) -> list[tuple[str, int]]:
    """Collapse a W/L/T sequence into (result, length) runs."""
    runs: list[tuple[str, int]] = []
    for r in results:
        if runs and runs[-1][0] == r:
            runs[-1] = (r, runs[-1][1] + 1)
        else:
            runs.append((r, 1))
    return runs


def _result(game: TeamGame) -> str:
    return 'W' if game.won else 'L' if game.lost else 'T'


def _franchise_results(ctx: WeekContext, regular_only: bool) -> dict[str, list[TeamGame]]:
    """Each franchise's decided games in order. Streaks follow every game a
    team plays (a playoff loss ends a win streak); season records and pace
    stay regular-season only."""
    out: dict[str, list[TeamGame]] = defaultdict(list)
    for g in ctx.team_all:
        if (regular_only and g.bracket != REGULAR) or not g.decided or g.score <= 0:
            continue
        for f in g.franchises:
            out[f].append(g)
    return out


def _streak_facts(ctx: WeekContext) -> list[Fact]:
    facts = []
    by_franchise = _franchise_results(ctx, regular_only=False)
    regular_by_franchise = _franchise_results(ctx, regular_only=True)
    # Every run that has ever happened, per result type, for league ranking.
    league_runs: dict[str, list[int]] = defaultdict(list)
    for games in by_franchise.values():
        for result, length in _runs([_result(g) for g in games]):
            league_runs[result].append(length)
    regular_league_runs: dict[str, list[int]] = defaultdict(list)
    for games in regular_by_franchise.values():
        for result, length in _runs([_result(g) for g in games]):
            regular_league_runs[result].append(length)

    for game in ctx.current:
        if not game.decided or game.score <= 0:
            continue
        franchise = _primary_franchise(game)
        games = by_franchise.get(franchise, [])
        if not games or games[-1].order != ctx.target:
            continue
        runs = _runs([_result(g) for g in games])
        result, length = runs[-1]
        word = {'W': 'won', 'L': 'lost'}.get(result)

        # A regular-season-only streak runs longer when it skips past playoff
        # or consolation results; it is only ever reported with that caveat.
        regular_length = 0
        regular_games = regular_by_franchise.get(franchise, [])
        if game.bracket == REGULAR and regular_games and regular_games[-1].order == ctx.target:
            regular_result, n = _runs([_result(g) for g in regular_games])[-1]
            if regular_result == result and n > length:
                regular_length = n

        if word and length >= STREAK_MIN:
            rank, _, tied = rank_of(length, league_runs[result], True)
            franchise_runs = [n for r, n in runs if r == result]
            kind = 'win' if result == 'W' else 'losing'
            text = f'{team(game.abbrev)} {has(game.abbrev)} {word} {length} straight'
            if regular_length:
                text += f' ({regular_length} straight in the regular season)'
            notability = 0.3 + 0.04 * min(length, 10)
            if rank <= 3:
                text += f', {rank_phrase(rank, tied, "longest")} {kind} streak in league history'
                notability = max(0.9 * _rarity(rank), 0.65)
            elif max(franchise_runs) == length and len(franchise_runs) > 1:
                text += f', the longest {kind} streak in franchise history'
                notability = 0.6
            facts.append(
                Fact(
                    f'streak_{kind}',
                    TEAM,
                    [game.abbrev],
                    text + '.',
                    notability,
                    _scope_tags(game.bracket),
                )
            )
        elif word and regular_length >= STREAK_MIN:
            kind = 'win' if result == 'W' else 'losing'
            rank, _, tied = rank_of(regular_length, regular_league_runs[result], True)
            text = (
                f'{team(game.abbrev)} {has(game.abbrev)} {word} {regular_length} '
                'straight regular-season games'
            )
            notability = 0.25 + 0.04 * min(regular_length, 10)
            if rank <= 3:
                text += (
                    f', {rank_phrase(rank, tied, "longest")} regular-season {kind} streak '
                    'in league history'
                )
                notability = max(0.8 * _rarity(rank), 0.55)
            facts.append(
                Fact(
                    f'streak_{kind}_regular',
                    TEAM,
                    [game.abbrev],
                    text + '.',
                    notability,
                    ['regular'],
                )
            )
        if len(runs) >= 2:
            prev_result, prev_length = runs[-2]
            if (
                result != prev_result
                and prev_result in ('W', 'L')
                and prev_length >= SNAPPED_STREAK_MIN
            ):
                if prev_result == 'W':
                    text = f"{team(game.opp_abbrev)} snapped {team(game.abbrev)}'s {prev_length}-game win streak."
                else:
                    text = (
                        f'{team(game.abbrev)} snapped {article(prev_length)} '
                        f'{prev_length}-game losing streak.'
                    )
                facts.append(
                    Fact(
                        'streak_snapped',
                        TEAM,
                        [game.abbrev, game.opp_abbrev] if prev_result == 'W' else [game.abbrev],
                        text,
                        0.4 + 0.04 * min(prev_length, 10),
                        _scope_tags(game.bracket),
                    )
                )
    return facts


def _season_start_facts(ctx: WeekContext) -> list[Fact]:
    facts = []
    by_franchise = _franchise_results(ctx, regular_only=True)
    for game in ctx.current:
        if game.bracket != REGULAR or not game.decided:
            continue
        franchise = _primary_franchise(game)
        season_games = [g for g in by_franchise.get(franchise, []) if g.season == ctx.season]
        n = len(season_games)
        if n < 3 or season_games[-1].order != ctx.target:
            continue
        for result, label in (('W', f'{n}-0'), ('L', f'0-{n}')):
            if not all(_result(g) == result for g in season_games):
                continue
            # Every earlier franchise-season that opened the same way.
            starts = []
            for f, games in by_franchise.items():
                seasons: dict[int, list[TeamGame]] = defaultdict(list)
                for g in games:
                    seasons[g.season].append(g)
                for season, rows in seasons.items():
                    if season == ctx.season:
                        continue
                    if len(rows) >= n and all(_result(g) == result for g in rows[:n]):
                        starts.append((f, season))
            mine = sorted(s for f, s in starts if f == franchise)
            league_count = len(starts) + 1
            parts = []
            if league_count == 1:
                parts.append(f'the first {label} start in league history')
            else:
                if not mine:
                    parts.append('for the first time in franchise history')
                elif ctx.season - mine[-1] >= 2:
                    parts.append(f'for the first time since {mine[-1]}')
                if league_count <= RARE_CLUB_MAX:
                    parts.append(f'just the {nth(league_count)} {label} start in league history')
            if not parts:
                continue
            text = f'{team(game.abbrev)} {is_(game.abbrev)} {label}'
            for part in parts:
                text += (' ' if part.startswith('for ') else ', ') + part
            text += '.'
            facts.append(
                Fact(
                    'season_start',
                    TEAM,
                    [game.abbrev],
                    text,
                    0.5 + 0.4 / league_count**0.5 if league_count <= RARE_CLUB_MAX else 0.45,
                    ['regular'],
                )
            )
    return facts


def _head_to_head_facts(ctx: WeekContext) -> list[Fact]:
    facts = []
    for winner, loser in ctx.matchups():
        if not winner.won or winner.score <= 0:
            continue
        a, b = _primary_franchise(winner), _primary_franchise(loser)
        series = [
            g
            for g in ctx.team_all
            if g.decided and a in g.franchises and b in g.opp_franchises and g.score > 0
        ]
        wins = sum(1 for g in series if g.won)
        losses = sum(1 for g in series if g.lost)
        record = f'{wins}-{losses}' + (
            f'-{len(series) - wins - losses}' if len(series) > wins + losses else ''
        )
        runs = _runs([_result(g) for g in series])
        streak = runs[-1][1] if runs and runs[-1][0] == 'W' else 0
        prior_wins = [g for g in series[:-1] if g.won]
        subjects = [winner.abbrev, loser.abbrev]
        tags = _scope_tags(winner.bracket)
        if len(series) >= 3 and not prior_wins:
            facts.append(
                Fact(
                    'h2h_first_win',
                    TEAM,
                    subjects,
                    f'{team(winner.abbrev)} beat {team(loser.abbrev)} for the first time in '
                    f'{len(series)} meetings.',
                    0.6 + 0.02 * min(len(series), 10),
                    tags,
                )
            )
        elif prior_wins and ctx.gap_weeks(prior_wins[-1].order) >= SINCE_STANDALONE_GAP_WEEKS:
            last = prior_wins[-1]
            facts.append(
                Fact(
                    'h2h_drought',
                    TEAM,
                    subjects,
                    f'{team(winner.abbrev)} beat {team(loser.abbrev)} for the first time since '
                    f'{when(last.week_label, last.season)} (series: {record}).',
                    0.55,
                    tags,
                )
            )
        elif streak >= STREAK_MIN:
            facts.append(
                Fact(
                    'h2h_streak',
                    TEAM,
                    subjects,
                    f'{team(winner.abbrev)} {has(winner.abbrev)} won {streak} straight against '
                    f'{team(loser.abbrev)} '
                    f'(series: {record}).',
                    0.35 + 0.04 * min(streak, 10),
                    tags,
                )
            )
    return facts


def _pace_facts(ctx: WeekContext) -> list[Fact]:
    """Points for through N regular-season games, against every franchise-season."""
    facts = []
    by_franchise = _franchise_results(ctx, regular_only=True)
    season_rows: dict[tuple[str, int], list[TeamGame]] = defaultdict(list)
    for f, games in by_franchise.items():
        for g in games:
            season_rows[(f, g.season)].append(g)
    for game in ctx.current:
        if game.bracket != REGULAR:
            continue
        franchise = _primary_franchise(game)
        mine = season_rows.get((franchise, ctx.season), [])
        n = len(mine)
        if n < 3 or mine[-1].order != ctx.target:
            continue
        totals = [sum(g.score for g in rows[:n]) for rows in season_rows.values() if len(rows) >= n]
        total = sum(g.score for g in mine)
        for higher, word in ((True, 'most'), (False, 'fewest')):
            rank, _, tied = rank_of(total, totals, higher)
            if rank <= 3:
                facts.append(
                    Fact(
                        f'pace_{"high" if higher else "low"}',
                        TEAM,
                        [game.abbrev],
                        f'{team(game.abbrev)} {has(game.abbrev)} scored {number(total)} points '
                        f'through {n} games, '
                        f'{rank_phrase(rank, tied, word)} through {n} games in league history.',
                        0.75 * _rarity(rank),
                        ['regular'],
                    )
                )
    return facts


def _top_half_facts(ctx: WeekContext) -> list[Fact]:
    """Consecutive regular-season weeks finishing in the top half of the league."""
    by_week: dict[tuple[int, int], list[TeamGame]] = defaultdict(list)
    for g in ctx.team_all:
        if g.bracket == REGULAR and g.score > 0:
            by_week[g.order].append(g)
    top_half: dict[str, list[tuple[tuple[int, int], bool]]] = defaultdict(list)
    for order in sorted(by_week):
        games = by_week[order]
        cutoff = len(games) // 2
        for g in games:
            rank = 1 + sum(1 for other in games if other.score > g.score)
            for f in g.franchises:
                top_half[f].append((order, rank <= cutoff))
    league_runs: list[int] = []
    for rows in top_half.values():
        league_runs.extend(
            n for r, n in _runs(['Y' if hit else 'N' for _, hit in rows]) if r == 'Y'
        )
    facts = []
    for game in ctx.current:
        if game.bracket != REGULAR:
            continue
        rows = top_half.get(_primary_franchise(game), [])
        if not rows or rows[-1][0] != ctx.target:
            continue
        result, length = _runs(['Y' if hit else 'N' for _, hit in rows])[-1]
        if result != 'Y' or length < 5:
            continue
        rank, _, tied = rank_of(length, league_runs, True)
        text = (
            f'{team(game.abbrev)} {has(game.abbrev)} finished in the top half '
            f'{length} straight weeks'
        )
        if rank <= 3:
            text += f', {rank_phrase(rank, tied, "longest")} such run in league history'
        facts.append(
            Fact(
                'top_half_streak',
                TEAM,
                [game.abbrev],
                text + '.',
                0.45 + (0.3 if rank <= 3 else 0),
                ['regular'],
            )
        )
    return facts


# --------------------------------------------------------------------------- #
# Player detectors
# --------------------------------------------------------------------------- #


def _player_label(p: PlayerGame) -> str:
    return f'{p.name} ({team(p.abbrev)})'


def _player_game_facts(ctx: WeekContext) -> list[Fact]:
    facts = []
    all_scores = [p.score for p in ctx.player_all]
    by_position: dict[str, list[PlayerGame]] = defaultdict(list)
    for p in ctx.player_all:
        by_position[p.position].append(p)

    for p in ctx.player_current:
        parts = []
        notability = 0.0
        category = PLAYER
        tags = _scope_tags(p.bracket)

        rank, _, tied = rank_of(p.score, all_scores, True)
        if rank <= LEAGUE_TOP and p.score > 0:
            parts.append(
                f'{rank_phrase(rank, tied, "highest")} single-game score in league history'
            )
            notability = _rarity(rank)
        elif p.position in RANKED_POSITIONS:
            pos_scores = [g.score for g in by_position[p.position]]
            rank, _, tied = rank_of(p.score, pos_scores, True)
            if rank <= LEAGUE_TOP_SHORT and p.score > 0 and tied <= 2:
                parts.append(
                    f'{rank_phrase(rank, tied, "best")} {p.position} game in league history'
                )
                notability = 0.85 * _rarity(rank)

        # "Nth player ever to score X+"
        club: tuple[int, list[PlayerGame], str | None] | None = None
        for threshold in range(int(p.score // 5 * 5), 0, -5):
            if threshold < 20:
                break
            games = [g for g in ctx.player_all if g.score >= threshold]
            if len(games) <= PLAYER_CLUB_MAX_GAMES:
                club = (threshold, games, None)
            break
        if club is None and p.position in CLUB_POSITIONS:
            for threshold in range(int(p.score // 5 * 5), 0, -5):
                if threshold < 15:
                    break
                games = [g for g in by_position[p.position] if g.score >= threshold]
                if len(games) <= POSITION_CLUB_MAX_GAMES:
                    club = (threshold, games, p.position)
                break
        if club:
            threshold, games, position = club
            prior_players = {g.player_key for g in games if g.order < ctx.target}
            players_through = len(prior_players | {p.player_key})
            who = f'{position} ' if position else 'player '
            if p.player_key in prior_players:
                times = sum(1 for g in games if g.player_key == p.player_key)
                parts.append(
                    f'his {ordinal(times)} {threshold}+ game; only {players_through} '
                    f'{who.strip()}s have ever reached {threshold}'
                )
            else:
                parts.append(f'just the {nth(players_through)} {who}ever to score {threshold}+')
            notability = max(notability, 0.5 + 0.4 / players_through**0.5)

        if not parts:
            continue
        facts.append(
            Fact(
                'player_game',
                category,
                [p.abbrev],
                f'{_player_label(p)} scored {number(p.score)}, ' + ', and '.join(parts) + '.',
                notability,
                tags,
            )
        )

        # Franchise single-game record for a player
        franchise = p.franchises[0] if p.franchises else p.abbrev
        franchise_scores = [g.score for g in ctx.player_all if franchise in g.franchises]
        f_rank, _, f_tied = rank_of(p.score, franchise_scores, True)
        if (
            f_rank == 1
            and len(franchise_scores) > 100
            and not any('league history' in x for x in parts[:1])
        ):
            facts.append(
                Fact(
                    'player_franchise_record',
                    PLAYER,
                    [p.abbrev],
                    f"{p.name}'s {number(p.score)} is "
                    f'{"tied for " if f_tied else ""}the most by a {team(p.abbrev)} player in franchise history.',
                    0.7,
                    tags,
                )
            )
    return facts


def _player_low_facts(ctx: WeekContext) -> list[Fact]:
    facts = []
    by_position: dict[str, list[float]] = defaultdict(list)
    for p in ctx.player_all:
        by_position[p.position].append(p.score)
    shame_count = sum(1 for p in ctx.player_all if p.position == 'D/ST' and p.score == -6)
    for p in ctx.player_current:
        tags = _scope_tags(p.bracket)
        if p.position == 'D/ST' and p.score == -6:
            facts.append(
                Fact(
                    'defensive_shame',
                    PLAYER,
                    [p.abbrev],
                    f'The {_player_label(p)} defense bottomed out at -6, the '
                    f'{ordinal(shame_count)} entry in the Defensive Hall of Shame.',
                    0.55,
                    tags,
                )
            )
            continue
        if p.position not in ('QB', 'RB', 'WR', 'TE', 'K'):
            continue
        rank, _, tied = rank_of(p.score, by_position[p.position], False)
        if rank <= 3 and p.score < 0 and tied <= 2:
            facts.append(
                Fact(
                    'player_low',
                    PLAYER,
                    [p.abbrev],
                    f'{_player_label(p)} posted {number(p.score)}, '
                    f'{rank_phrase(rank, tied, "worst")} {p.position} game in league history.',
                    0.6 * _rarity(rank),
                    tags,
                )
            )
    return facts


def _player_career_facts(ctx: WeekContext) -> list[Fact]:
    facts = []
    career: dict[str, float] = defaultdict(float)
    big_games: dict[str, int] = defaultdict(int)
    for p in ctx.player_history:
        career[p.player_key] += p.score
        if p.score >= BIG_GAME_POINTS:
            big_games[p.player_key] += 1
    after = dict(career)
    after_big = dict(big_games)
    for p in ctx.player_current:
        after[p.player_key] = after.get(p.player_key, 0.0) + p.score
        if p.score >= BIG_GAME_POINTS:
            after_big[p.player_key] = after_big.get(p.player_key, 0) + 1

    for p in ctx.player_current:
        before, now = career.get(p.player_key, 0.0), after[p.player_key]
        crossed = [m for m in CAREER_MILESTONES if before < m <= now]
        club = sum(1 for total in after.values() if crossed and total >= crossed[-1])
        if crossed and p.position in MILESTONE_POSITIONS and club <= MILESTONE_CLUB_MAX:
            mark = crossed[-1]
            facts.append(
                Fact(
                    'career_milestone',
                    PLAYER,
                    [p.abbrev],
                    f'{_player_label(p)} passed {number(mark)} career QPFL points as a starter, '
                    f'the {nth(club)} player to get there.',
                    0.4 + 0.4 / club**0.5,
                    _scope_tags(p.bracket),
                )
            )
        if p.score >= BIG_GAME_POINTS:
            count = after_big[p.player_key]
            rank, _, tied = rank_of(count, list(after_big.values()), True)
            if count >= 3 and rank <= 3:
                facts.append(
                    Fact(
                        'career_big_games',
                        PLAYER,
                        [p.abbrev],
                        f'{_player_label(p)} has {count} career {BIG_GAME_POINTS}-point games, '
                        f'{rank_phrase(rank, tied, "most")} in league history.',
                        0.5 + 0.2 * _rarity(rank),
                        _scope_tags(p.bracket),
                    )
                )
    return facts


def _player_streak_facts(ctx: WeekContext) -> list[Fact]:
    """Consecutive starts at HOT_STREAK_POINTS+ within one season."""
    starts: dict[tuple[str, int], list[PlayerGame]] = defaultdict(list)
    for p in ctx.player_all:
        starts[(p.player_key, p.season)].append(p)
    league_runs: list[int] = []
    current_runs: dict[str, int] = {}
    for (key, season), rows in starts.items():
        runs = _runs(['Y' if g.score >= HOT_STREAK_POINTS else 'N' for g in rows])
        league_runs.extend(n for r, n in runs if r == 'Y')
        if season == ctx.season and rows[-1].order == ctx.target and runs[-1][0] == 'Y':
            current_runs[key] = runs[-1][1]
    facts = []
    for p in ctx.player_current:
        length = current_runs.get(p.player_key, 0)
        if length < HOT_STREAK_MIN:
            continue
        rank, _, tied = rank_of(length, league_runs, True)
        text = f'{_player_label(p)} has scored {HOT_STREAK_POINTS}+ in {length} straight starts'
        notability = 0.4 + 0.05 * length
        if rank <= 3:
            text += f', {rank_phrase(rank, tied, "longest")} streak in league history'
            notability = 0.8 * _rarity(rank)
        facts.append(
            Fact(
                'player_hot_streak',
                PLAYER,
                [p.abbrev],
                text + '.',
                notability,
                _scope_tags(p.bracket),
            )
        )
    return facts


def _cycle_facts(ctx: WeekContext) -> list[Fact]:
    """A win that completes a beat-every-team cycle faster than the franchise
    (or anyone in the league) ever had before."""
    rivals = {_primary_franchise(g) for g in ctx.current}
    cycles = all_cycles(ctx.team_all, rivals)
    prior = [c for c in cycles if c.end.order < ctx.target]
    this_week = [c for c in cycles if c.end.order == ctx.target]
    league_best = min(prior, key=lambda c: (c.games, c.end.order), default=None)
    fastest_now = min((c.games for c in this_week), default=None)
    facts = []
    for cycle in this_week:
        mine = [c.games for c in prior if c.franchise == cycle.franchise]
        span = (
            f'{team(cycle.end.abbrev)} {has(cycle.end.abbrev)} now beaten every other team in a span of '
            f'{cycle.games} games ({when(cycle.start.week_label, cycle.start.season)} '
            f'to {when(cycle.end.week_label, cycle.end.season)})'
        )
        # A league record has to beat every earlier cycle and match the best
        # one finished this same week.
        sets_record = (league_best is None or cycle.games < league_best.games) and (
            cycle.games == fastest_now
        )
        if sets_record:
            record = ''
            if league_best is not None:
                holder = (
                    'their own'
                    if league_best.franchise == cycle.franchise
                    else f"{team(league_best.franchise)}'s"
                )
                record = f', breaking {holder} record of {league_best.games}'
            text, notability, category = (
                f'{span}, the fastest in league history{record}.',
                1.0,
                LEAGUE,
            )
        elif league_best is not None and cycle.games == league_best.games:
            holder = (
                'their own'
                if league_best.franchise == cycle.franchise
                else f"{team(league_best.franchise)}'s"
            )
            text, notability, category = f'{span}, tying {holder} league record.', 0.85, LEAGUE
        elif not mine:
            text, notability, category = (
                f'{span}, the first time the franchise has done it.',
                0.5,
                TEAM,
            )
        elif cycle.games < min(mine):
            text, notability, category = (
                f'{span}, the fastest in franchise history (previous best: {min(mine)}).',
                0.6,
                TEAM,
            )
        else:
            continue
        facts.append(
            Fact(
                'cycle_fastest',
                category,
                [cycle.end.abbrev],
                text,
                notability,
                _scope_tags(cycle.end.bracket),
            )
        )
    return facts


DETECTORS: tuple[Callable[[WeekContext], list[Fact]], ...] = (
    _team_score_facts,
    _matchup_facts,
    _league_week_facts,
    _streak_facts,
    _season_start_facts,
    _head_to_head_facts,
    _pace_facts,
    _top_half_facts,
    _player_game_facts,
    _player_low_facts,
    _player_career_facts,
    _player_streak_facts,
    _cycle_facts,
)


# --------------------------------------------------------------------------- #
# Curation + entry point
# --------------------------------------------------------------------------- #


def curate(facts: list[Fact], limit: int = 10, per_team: int = 3) -> list[Fact]:
    """The most notable facts, spread across categories and teams."""
    ranked = sorted(
        facts,
        key=lambda f: (-f.notability * CATEGORY_WEIGHT.get(f.category, 1.0), f.id, f.template),
    )
    picked: list[Fact] = []
    per_subject: dict[str, int] = defaultdict(int)

    def take(fact: Fact) -> bool:
        if fact in picked or len(picked) >= limit:
            return False
        if any(per_subject[s] >= per_team for s in fact.subjects):
            return False
        picked.append(fact)
        for s in fact.subjects:
            per_subject[s] += 1
        return True

    for category in (LEAGUE, PLAYER, TEAM):
        for fact in ranked:
            if fact.category == category and take(fact):
                break
    for fact in ranked:
        take(fact)
    return sorted(picked, key=lambda f: ranked.index(f))


def generate_week_facts(
    team_games: list[TeamGame],
    player_games: list[PlayerGame],
    season: int,
    week: int,
    limit: int = 10,
    first_season: int | None = None,
) -> dict:
    ctx = WeekContext(team_games, player_games, season, week, first_season)
    if not ctx.current:
        return {'season': season, 'week': week, 'headline': [], 'all': []}
    facts: list[Fact] = []
    for detector in DETECTORS:
        facts.extend(detector(ctx))
    ranked = sorted(
        facts,
        key=lambda f: (-f.notability * CATEGORY_WEIGHT.get(f.category, 1.0), f.id, f.template),
    )
    previous = ctx.history[-1] if ctx.history else None
    return {
        'season': season,
        'week': week,
        'week_label': ctx.current[0].week_label,
        'history_through': f'{previous.season} {previous.week_label}' if previous else None,
        'headline': [f.to_dict() for f in curate(facts, limit=limit)],
        'all': [f.to_dict() for f in ranked],
    }


# --------------------------------------------------------------------------- #
# Beat-everyone cycles (Hall of Fame)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Cycle:
    """The shortest run of a franchise's games with a win over every rival."""

    franchise: str
    games: int
    start: TeamGame
    end: TeamGame


def all_cycles(team_games: Iterable[TeamGame], franchises: Iterable[str]) -> list[Cycle]:
    """Every beat-everyone cycle, one per game that completed one: the shortest
    stretch of a franchise's consecutive games (every decided game, playoffs
    included) ending with the win that crossed off its last unbeaten rival
    among `franchises`.

    A co-owned team (2021's CGK/SRY, CWR/SLS) counts only as its primary
    franchise here, so one win can't cross off two rivals, and a franchise
    can't be beaten before it had a team of its own."""
    franchise_set = set(franchises)
    by_franchise: dict[str, list[TeamGame]] = defaultdict(list)
    for g in sorted(team_games, key=lambda g: g.order):
        if not g.decided or g.score <= 0:
            continue
        if g.franchises and g.franchises[0] in franchise_set:
            by_franchise[g.franchises[0]].append(g)

    cycles = []
    for franchise, games in by_franchise.items():
        rivals = franchise_set - {franchise}
        if not rivals:
            continue
        beaten = [
            {g.opp_franchises[0]} & rivals if g.won and g.opp_franchises else set() for g in games
        ]
        counts: dict[str, int] = defaultdict(int)
        start = 0
        for end, opponents in enumerate(beaten):
            for rival in opponents:
                counts[rival] += 1
            # Drop games off the front that the window doesn't need.
            while start < end and all(counts[rival] > 1 for rival in beaten[start]):
                for rival in beaten[start]:
                    counts[rival] -= 1
                start += 1
            complete = all(counts[rival] for rival in rivals)
            if complete and any(counts[rival] == 1 for rival in opponents):
                cycles.append(Cycle(franchise, end - start + 1, games[start], games[end]))
    return cycles


def fastest_cycles(team_games: Iterable[TeamGame], franchises: Iterable[str]) -> list[Cycle]:
    """Each franchise's fastest cycle (see all_cycles), fewest games first.
    Franchises that never managed one are left out; ties go to whoever
    finished first."""
    best: dict[str, Cycle] = {}
    for cycle in all_cycles(team_games, franchises):
        current = best.get(cycle.franchise)
        if current is None or (cycle.games, cycle.end.order) < (current.games, current.end.order):
            best[cycle.franchise] = cycle
    return sorted(best.values(), key=lambda c: (c.games, c.end.order, c.franchise))
