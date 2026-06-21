"""League "name battles" engine.

Several managers in the league share a name and fight a recurring head-to-head
battle for it (the "Connor Bowl", "Brother Bowl", "Kuhl Cup"). The winner of the
most recent head-to-head game displays the contested name; the loser's name is
redacted until they next meet. A result in week N takes effect for weeks *after*
N (during week N both still carry their pre-game designation).

The stable identifier is always the team ``abbrev`` — ``owner`` strings are
display-only. This module computes, from game results, who holds each contested
name at a point in time and rewrites ``owner`` strings accordingly. It is pure
(no I/O beyond ``load_config``); callers pass in already-loaded data so it stays
trivially testable.

Config lives in ``data/name_battles.json``. Each combatant carries the exact
``win`` / ``lose`` display substrings, so the engine never has to reason about
first-vs-last name — it just swaps substrings inside a team's owner field. This
also handles the co-owned ``J/J`` team, where only the ``Joe Kuhl`` substring is
contested and ``Censored Ward`` is left untouched.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Battle:
    """One name battle between two team abbrevs."""

    id: str
    name: str
    affects_first_name: bool
    # abbrev -> {"win": <canonical text>, "lose": <redacted text>}
    combatants: dict[str, dict[str, str]]

    @property
    def abbrevs(self) -> tuple[str, str]:
        a, b = tuple(self.combatants)
        return a, b


def load_config(path: str | Path) -> list[Battle]:
    """Load battle definitions from ``data/name_battles.json``."""
    raw = json.loads(Path(path).read_text())
    battles: list[Battle] = []
    for b in raw.get('battles', []):
        combatants = {
            c['abbrev']: {'win': c['win'], 'lose': c['lose']} for c in b['combatants']
        }
        battles.append(
            Battle(
                id=b['id'],
                name=b.get('name', b['id']),
                affects_first_name=bool(b.get('affects_first_name', False)),
                combatants=combatants,
            )
        )
    return battles


def find_h2h_winner(
    weeks: list[dict], abbrev_a: str, abbrev_b: str
) -> tuple[str | None, int | None]:
    """Return ``(winner_abbrev, week)`` of the latest decisive game between the
    two teams within ``weeks``. Returns ``(None, None)`` if they never meet
    decisively.

    A game is skipped (not a real head-to-head) when it is unscored, a tie, or
    either side scored 0 or less — a 0 means that manager never submitted a
    lineup (a bye, forfeit, or eliminated playoff slot), which must not flip the
    title. This is why e.g. WJK's 0-78 "loss" in week 17 doesn't count.
    """
    pair = {abbrev_a, abbrev_b}
    best_week: int | None = None
    best_winner: str | None = None
    for wk in weeks:
        if wk.get('has_scores') is False:
            continue
        wknum = wk.get('week')
        for m in wk.get('matchups', []):
            t1 = m.get('team1', {})
            t2 = m.get('team2', {})
            if {t1.get('abbrev'), t2.get('abbrev')} != pair:
                continue
            s1 = t1.get('total_score')
            s2 = t2.get('total_score')
            if s1 is None or s2 is None or s1 == s2:
                continue  # unplayed or tie -> no change of holder
            if s1 <= 0 or s2 <= 0:
                continue  # a 0 means no lineup submitted -> not a real game
            winner = t1['abbrev'] if s1 > s2 else t2['abbrev']
            if best_week is None or (isinstance(wknum, int) and wknum > best_week):
                best_week = wknum if isinstance(wknum, int) else best_week
                best_winner = winner
    return best_winner, best_week


def compute_season_start_holders(
    battles: list[Battle], prior_seasons: list[list[dict]]
) -> dict[str, str | None]:
    """Holder of each battle at the start of the current season, derived from the
    most recent prior season that had a decisive head-to-head.

    ``prior_seasons`` is a list of weeks-lists ordered newest-first.
    """
    holders: dict[str, str | None] = {}
    for battle in battles:
        a, b = battle.abbrevs
        holder: str | None = None
        for weeks in prior_seasons:
            winner, _ = find_h2h_winner(weeks, a, b)
            if winner:
                holder = winner
                break
        holders[battle.id] = holder
    return holders


def current_holders(
    battles: list[Battle],
    current_weeks: list[dict],
    season_start_holders: dict[str, str | None],
) -> dict[str, str | None]:
    """Holder of each battle right now: winner of the latest scored head-to-head
    this season, falling back to the season-start holder."""
    out: dict[str, str | None] = {}
    for battle in battles:
        a, b = battle.abbrevs
        winner, _ = find_h2h_winner(current_weeks, a, b)
        out[battle.id] = winner or season_start_holders.get(battle.id)
    return out


def holders_for_week(
    battles: list[Battle],
    current_weeks: list[dict],
    season_start_holders: dict[str, str | None],
    week: int,
) -> dict[str, str | None]:
    """Holder of each battle as of ``week`` (decided by games in weeks < ``week``)."""
    prior = [
        wk for wk in current_weeks if isinstance(wk.get('week'), int) and wk['week'] < week
    ]
    out: dict[str, str | None] = {}
    for battle in battles:
        a, b = battle.abbrevs
        winner, _ = find_h2h_winner(prior, a, b)
        out[battle.id] = winner or season_start_holders.get(battle.id)
    return out


def apply_to_owner(owner: str, battle: Battle, holder: str | None) -> str:
    """Normalize an ``owner`` string for one battle given its ``holder``.

    The holder's combatant is forced to its canonical ``win`` text; the loser's
    is forced to its ``lose`` text. Idempotent regardless of the input state, so
    it works whether the source string was canonical or already redacted.
    """
    if holder is None or holder not in battle.combatants:
        return owner
    for abbrev, names in battle.combatants.items():
        win, lose = names['win'], names['lose']
        if abbrev == holder:
            if lose in owner:
                owner = owner.replace(lose, win)
        elif win in owner:
            owner = owner.replace(win, lose)
    return owner


def apply_all(owner: str, battles: list[Battle], holders: dict[str, str | None]) -> str:
    """Apply every battle's redaction to an owner string."""
    if not owner:
        return owner
    for battle in battles:
        owner = apply_to_owner(owner, battle, holders.get(battle.id))
    return owner


def holder_at(
    battle: Battle, seasons_weeks: dict[int, list[dict]], season: int, week
) -> str | None:
    """Holder of ``battle`` at an arbitrary point (``season``, ``week``).

    ``week`` may be a non-int (e.g. ``"Offseason"``), in which case no
    current-season games count and the result is carried from prior seasons.
    Used for point-in-time transaction labels that span multiple seasons.
    """
    a, b = battle.abbrevs
    if isinstance(week, int) and season in seasons_weeks:
        cur = [
            wk
            for wk in seasons_weeks[season]
            if isinstance(wk.get('week'), int) and wk['week'] < week
        ]
        winner, _ = find_h2h_winner(cur, a, b)
        if winner:
            return winner
    for y in sorted(seasons_weeks, reverse=True):
        if y >= season:
            continue
        winner, _ = find_h2h_winner(seasons_weeks[y], a, b)
        if winner:
            return winner
    return None


def first_name_label_at(
    abbrev: str,
    battles: list[Battle],
    seasons_weeks: dict[int, list[dict]],
    season: int,
    week,
) -> str | None:
    """Point-in-time first name for ``abbrev`` if it is in a first-name battle,
    else ``None`` (caller should fall back to its normal label).
    """
    for battle in battles:
        if not battle.affects_first_name or abbrev not in battle.combatants:
            continue
        holder = holder_at(battle, seasons_weeks, season, week)
        if holder is None:
            continue
        names = battle.combatants[abbrev]
        win_first = names['win'].split(' ')[0]
        lose_first = names['lose'].split(' ')[0]
        return win_first if holder == abbrev else lose_first
    return None
