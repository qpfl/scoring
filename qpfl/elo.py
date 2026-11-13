"""Franchise Elo ratings, game by game across every season.

- Everyone starts at 1500; K is 24.
- A margin-of-victory multiplier, ln(|margin| + 1) x 2.2 / (Δelo x 0.001 + 2.2),
  scales each result, where Δelo is the winner's rating minus the loser's (so a
  favourite's blowout counts for less than an upset's).
- Playoff games weigh 1.25x. Consolation games count at 1x.
- Between seasons every rating regresses a third of the way back to 1500.

Ratings belong to current franchise seats (`TeamGame.franchises`), so a seat
carries its rating across owners and codes. A team shared by two seats (the
2021 CWR/SLS merger) plays at their average and both seats move.

Used by the Hall of Fame (each franchise's rating history) and the pregame
notes (each matchup's ratings and Elo win probability coming in).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable

from qpfl.weekly_facts import PLAYOFFS, TeamGame

START = 1500.0
K = 24.0
PLAYOFF_WEIGHT = 1.25
CARRYOVER = 2 / 3


def expected(rating: float, opponent: float) -> float:
    """The chance a team rated `rating` beats one rated `opponent`."""
    return 1 / (1 + 10 ** ((opponent - rating) / 400))


def mov_multiplier(margin: float, winner_edge: float) -> float:
    return math.log(abs(margin) + 1) * 2.2 / (winner_edge * 0.001 + 2.2)


def _regress(ratings: dict[str, float]) -> None:
    for franchise, rating in ratings.items():
        ratings[franchise] = START + (rating - START) * CARRYOVER


def _side(ratings: dict[str, float], franchises: tuple[str, ...]) -> float:
    return sum(ratings[f] for f in franchises) / len(franchises)


def _games(team_games: Iterable[TeamGame]) -> list[TeamGame]:
    """Each decided, played game once, in order."""
    seen = set()
    games = []
    for g in sorted(team_games, key=lambda g: (g.order, g.abbrev)):
        if not g.decided or not g.franchises or not g.opp_franchises:
            continue
        if g.score <= 0 and g.opp_score <= 0:
            continue
        key = (g.season, g.week, *sorted((g.abbrev, g.opp_abbrev)))
        if key in seen:
            continue
        seen.add(key)
        games.append(g)
    return games


class EloHistory:
    """Every franchise's rating after each week it played."""

    def __init__(self, team_games: Iterable[TeamGame]):
        self.ratings: dict[str, float] = defaultdict(lambda: START)
        self.series: dict[str, list[tuple[int, int, float]]] = defaultdict(list)
        self.last_season: int | None = None
        for g in _games(team_games):
            if self.last_season is not None and g.season != self.last_season:
                _regress(self.ratings)
            self.last_season = g.season
            self._play(g)

    def _play(self, g: TeamGame) -> None:
        mine = _side(self.ratings, g.franchises)
        theirs = _side(self.ratings, g.opp_franchises)
        score = g.result_score if g.result_score is not None else g.score
        opp = g.result_opp_score if g.result_opp_score is not None else g.opp_score
        actual = 1.0 if score > opp else 0.0 if score < opp else 0.5
        margin = score - opp
        if margin:
            edge = mine - theirs if margin > 0 else theirs - mine
            multiplier = mov_multiplier(margin, edge)
        else:
            multiplier = 1.0
        weight = PLAYOFF_WEIGHT if g.bracket == PLAYOFFS else 1.0
        change = K * multiplier * weight * (actual - expected(mine, theirs))
        for franchise in g.franchises:
            self.ratings[franchise] += change
        for franchise in g.opp_franchises:
            self.ratings[franchise] -= change
        for franchise in (*g.franchises, *g.opp_franchises):
            point = (g.season, g.week, round(self.ratings[franchise], 1))
            if self.series[franchise] and self.series[franchise][-1][:2] == point[:2]:
                self.series[franchise][-1] = point
            else:
                self.series[franchise].append(point)

    def rating(self, franchises: tuple[str, ...], season: int) -> float:
        """A side's rating going into a game in `season`, with the offseason
        regression applied if that season hasn't started yet."""
        if not franchises:
            return START
        rating = _side(self.ratings, franchises)
        if self.last_season is not None and season > self.last_season:
            rating = START + (rating - START) * CARRYOVER
        return rating

    def current(self) -> dict[str, float]:
        return {franchise: round(rating, 1) for franchise, rating in self.ratings.items()}
