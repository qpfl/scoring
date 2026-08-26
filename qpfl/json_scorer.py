"""JSON-based scoring for 2026+.

This module provides scoring that reads lineups from JSON files instead of Excel.
Rosters are still sourced from rosters.json (which syncs with Excel for roster management).
"""

import functools
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from .base_scorer import BaseScorer
from .constants import STARTER_SLOTS
from .models import FantasyTeam, PlayerScore
from .projections import WeekProjections, player_projection_key


def load_rosters(rosters_path: str | Path) -> dict[str, list[dict[str, Any]]]:
    """Load team rosters from rosters.json.

    Args:
        rosters_path: Path to rosters.json file

    Returns:
        Dict mapping team abbrev to list of player dicts
    """
    rosters_path = Path(rosters_path)
    if not rosters_path.exists():
        raise FileNotFoundError(f'Rosters file not found: {rosters_path}')

    with open(rosters_path) as f:
        return json.load(f)  # type: ignore[no-any-return]


def load_lineup(lineup_path: str | Path, week: int) -> dict[str, dict[str, Any]]:
    """Load lineup submissions for a week.

    Args:
        lineup_path: Path to lineup JSON file (e.g., data/lineups/2026/week_1.json)
        week: Week number (for validation)

    Returns:
        Dict mapping team abbrev to lineup dict with starters per position
    """
    lineup_path = Path(lineup_path)
    if not lineup_path.exists():
        raise FileNotFoundError(f'Lineup file not found: {lineup_path}')

    with open(lineup_path) as f:
        data = json.load(f)

    if data.get('week') != week:
        raise ValueError(
            f"Lineup file week ({data.get('week')}) doesn't match expected week "
            f'({week}) in {lineup_path} — scoring would use the wrong week.'
        )

    return data.get('lineups', {})  # type: ignore[no-any-return]


def build_fantasy_team_from_json(
    team_abbrev: str,
    rosters: dict[str, list[dict[str, Any]]],
    lineups: dict[str, dict[str, Any]],
    teams_info: dict[str, dict[str, Any]] | None = None,
) -> FantasyTeam:
    """Build a FantasyTeam from JSON roster and lineup data.

    Args:
        team_abbrev: Team abbreviation (e.g., 'GSA')
        rosters: Full rosters dict from rosters.json
        lineups: Week lineups dict from week_N.json
        teams_info: Optional team info dict with name/owner

    Returns:
        FantasyTeam object with players and starter status
    """
    roster = rosters.get(team_abbrev, [])
    lineup = lineups.get(team_abbrev, {})

    # Get team info
    team_info = teams_info.get(team_abbrev, {}) if teams_info else {}
    team_name = team_info.get('name', team_abbrev)
    owner = team_info.get('owner', '')

    # Build starters set from lineup, capped at STARTER_SLOTS as a defense-in-depth
    # safety net: a bad/bypassed lineup file (e.g. a lock merge that slipped past
    # the API's own check) should never inflate a score by starting more players
    # than allowed. Deterministic: keep the first N names in submission order.
    # See docs/ROADMAP_2026.md P0.3.
    starters = set()
    for position, player_names in lineup.items():
        if position in ('submitted_at', 'comment'):
            continue
        limit = STARTER_SLOTS.get(position)
        capped_names = player_names[:limit] if limit is not None else player_names
        if limit is not None and len(player_names) > limit:
            print(
                f'WARNING: {team_abbrev} lineup has {len(player_names)} {position} starters '
                f'(max {limit}); scoring only the first {limit} in submission order: '
                f'{capped_names}'
            )
        for name in capped_names:
            starters.add(name)

    # Build players dict
    players: dict[str, list[tuple[str, str, bool]]] = {}
    taxi_players: set[tuple[str, str]] = set()

    for player in roster:
        name = player.get('name', '')
        nfl_team = player.get('nfl_team', '')
        position = player.get('position', '')
        is_taxi = player.get('taxi', False)

        if position not in players:
            players[position] = []

        is_starter = name in starters and not is_taxi
        players[position].append((name, nfl_team, is_starter))
        if is_taxi:
            taxi_players.add((name, position))

    return FantasyTeam(
        name=team_name,
        owner=owner,
        abbreviation=team_abbrev,
        column_index=0,  # Not used for JSON-based scoring
        players=players,
        taxi_players=taxi_players,
    )


def score_week_from_json(
    rosters_path: str | Path,
    lineup_path: str | Path,
    season: int,
    week: int,
    teams_info: dict[str, dict[str, Any]] | None = None,
    verbose: bool = True,
    data_fetcher: Any = None,
) -> tuple[list[FantasyTeam], dict[str, tuple[float, dict[str, list[tuple[PlayerScore, bool]]]]]]:
    """Score all fantasy teams for a week using JSON data sources.

    Args:
        rosters_path: Path to rosters.json
        lineup_path: Path to week lineup JSON (e.g., data/lineups/2026/week_1.json)
        season: NFL season year
        week: Week number
        teams_info: Optional dict mapping team abbrev to {name, owner}
        verbose: Whether to print detailed output
        data_fetcher: Optional pre-built NFLDataFetcher (e.g. from a stat snapshot,
            see docs/DURABILITY_PLAN.md); defaults to a live fetch from nflreadpy.

    Returns:
        Tuple of (teams, results) where results maps team name to (total_score, position_scores)
    """
    # Load data
    rosters = load_rosters(rosters_path)
    lineups = load_lineup(lineup_path, week)

    # Build fantasy teams
    teams = []
    for team_abbrev in rosters:
        team = build_fantasy_team_from_json(team_abbrev, rosters, lineups, teams_info)
        teams.append(team)

    if verbose:
        print(f'\nFound {len(teams)} fantasy teams')
        for team in teams:
            started_count = sum(
                1 for players in team.players.values() for _, _, is_started in players if is_started
            )
            print(f'  - {team.name} ({team.abbreviation}): {started_count} started players')

    # Score all teams using shared logic from BaseScorer
    scorer = BaseScorer(season, week, data_fetcher=data_fetcher)
    results = scorer.score_teams(teams, verbose=verbose)

    return teams, results


def load_score_adjustments(path: str | Path) -> list[dict]:
    """Load manual score adjustments (data/score_adjustments.json), if present."""
    path = Path(path)
    if not path.exists():
        return []
    with open(path) as f:
        adjustments = json.load(f)
    if not isinstance(adjustments, list):
        raise ValueError(f'Score adjustments must contain a JSON array: {path}')
    return cast(list[dict], adjustments)


def apply_score_adjustments(
    teams: list[FantasyTeam],
    results: dict[str, tuple[float, dict]],
    season: int,
    week: int,
    adjustments_path: str | Path = 'data/score_adjustments.json',
) -> dict[str, tuple[float, dict]]:
    """Apply manual commissioner corrections for this season/week.

    Covers rules that aren't automated (e.g. Head Coach fired/ejected penalties
    - see docs/ROADMAP_2026.md P2.1) as well as one-off stat corrections.
    Idempotent: re-running scoring re-applies adjustments from this file rather
    than accumulating them, since scoring recomputes from scratch each run.

    Each entry: {"season", "week", "team", "player", "points", "reason"}.
    `player` is matched by name against that week's roster; if not found, the
    adjustment is still applied to the team total (with a console warning) so
    a typo'd name doesn't silently no-op a correction.
    """
    adjustments = [
        a
        for a in load_score_adjustments(adjustments_path)
        if a.get('season') == season and a.get('week') == week
    ]
    if not adjustments:
        return results

    abbrev_to_name = {t.abbreviation: t.name for t in teams}

    for adj in adjustments:
        team_abbrev = adj.get('team')
        if not isinstance(team_abbrev, str):
            print(f'WARNING: score adjustment has an invalid team and was skipped: {adj}')
            continue
        team_name = abbrev_to_name.get(team_abbrev)
        points = adj.get('points', 0)
        player_name = adj.get('player')
        reason = adj.get('reason', '')

        if team_name is None or team_name not in results:
            print(f'WARNING: score adjustment for unknown team {team_abbrev!r} skipped: {adj}')
            continue

        total, scores = results[team_name]
        matched = False
        matching_entries = [
            ps
            for player_scores in scores.values()
            for ps, _is_starter in player_scores
            if ps.name == player_name
        ]
        if len(matching_entries) > 1:
            print(
                f'WARNING: score adjustment player {player_name!r} matches {len(matching_entries)} '
                f'roster entries on {team_abbrev} for week {week} - applying to the first only '
                f'(ambiguous name, adjustment not applied to the others): {adj}'
            )
        if matching_entries:
            ps = matching_entries[0]
            ps.total_points += points
            ps.breakdown['adjustment'] = ps.breakdown.get('adjustment', 0) + points
            if reason:
                ps.data_notes.append(f'Adjustment: {points:+g} ({reason})')
            matched = True

        if not matched:
            print(
                f'WARNING: score adjustment player {player_name!r} not found on {team_abbrev} '
                f'roster for week {week} - applying {points:+g} to team total only: {adj}'
            )

        results[team_name] = (total + points, scores)

    return results


def save_week_scores(
    output_path: str | Path,
    week: int,
    teams: list[FantasyTeam],
    results: dict[str, tuple[float, dict]],
    matchups: list[dict[str, Any]] | None = None,
    projections: WeekProjections | None = None,
) -> None:
    """Save scored week data to JSON.

    Args:
        output_path: Path to output JSON file
        week: Week number
        teams: List of FantasyTeam objects
        results: Scoring results dict
        matchups: Optional list of matchup dicts for the week
        projections: Optional player, team, and matchup forecasts
    """
    teams_data = []

    for team in teams:
        if team.name not in results:
            continue

        total, scores = results[team.name]

        roster: list[dict[str, Any]] = []
        taxi_squad: list[dict[str, Any]] = []
        for position, player_scores in scores.items():
            for ps, is_starter in player_scores:
                is_taxi = (ps.name, position) in team.taxi_players
                player_entry: dict = {
                    'name': ps.name,
                    'nfl_team': ps.team,
                    'position': position,
                    'score': ps.total_points,
                    # Distinguishes a legitimate 0 (bye week, game not yet
                    # played) from a stat-matching miss (stale nfl_team, name
                    # drift) - see docs/ROADMAP_2026.md P1.4.
                    'found': ps.found_in_stats,
                }
                if not is_taxi:
                    player_entry['starter'] = is_starter
                if projections:
                    player_projection = projections.players.get(
                        player_projection_key(team.abbreviation, ps.name, position)
                    )
                    if player_projection:
                        player_entry.update(
                            {
                                'projected_points': player_projection.projected_points,
                                'nfl_opponent': player_projection.game.opponent,
                                'kickoff': player_projection.game.kickoff,
                                'game_final': player_projection.game.final,
                                'on_bye': player_projection.on_bye,
                            }
                        )
                if ps.breakdown:
                    player_entry['breakdown'] = ps.breakdown
                if ps.data_notes:
                    player_entry['data_notes'] = ps.data_notes
                (taxi_squad if is_taxi else roster).append(player_entry)

        team_entry: dict[str, Any] = {
            'name': team.name,
            'owner': team.owner,
            'abbrev': team.abbreviation,
            'roster': roster,
            'taxi_squad': taxi_squad,
            'total_score': round(total, 1),
        }
        if projections:
            team_projection = projections.teams.get(team.abbreviation)
            if team_projection:
                team_entry.update(
                    {
                        'projection_ready': team_projection.ready,
                        'projected_total': team_projection.projected_total,
                        'win_probability': (
                            round(team_projection.win_probability, 4)
                            if team_projection.win_probability is not None
                            else None
                        ),
                        'starters_remaining': team_projection.starters_remaining,
                    }
                )
        teams_data.append(team_entry)

    # Sort by score for ranking
    sorted_teams: list[dict[str, Any]] = sorted(
        teams_data, key=lambda t: float(t['total_score']), reverse=True
    )
    for rank, team_dict in enumerate(sorted_teams, 1):
        team_dict['score_rank'] = rank

    # A week "has scores" if at least one starter's stats were actually
    # matched - not "any team total > 0", which would wrongly treat an
    # all-zero-or-negative week (every starter on bye/not-yet-played, or a
    # week where every starter nets a negative score) as unscored and skip it
    # in standings. See docs/ROADMAP_2026.md P1.7.
    has_scores = any(
        entry.get('starter') and entry.get('found') for t in teams_data for entry in t['roster']
    )

    week_data = {
        'week': week,
        'scored_at': datetime.now(timezone.utc).isoformat(),
        'teams': teams_data,
        'has_scores': has_scores,
    }

    if matchups:
        # Build matchup data with scores
        matchups_data = []
        team_by_abbrev = {t['abbrev']: t for t in teams_data}

        for matchup in matchups:
            t1_abbrev = matchup.get('team1')
            t2_abbrev = matchup.get('team2')

            matchup_data = {
                'team1': team_by_abbrev.get(t1_abbrev, {'abbrev': t1_abbrev}),
                'team2': team_by_abbrev.get(t2_abbrev, {'abbrev': t2_abbrev}),
            }

            # Preserve playoff metadata needed downstream by
            # resolve_playoff_matchups (week 17 depends on 'game' ids from
            # week 16) and the frontend (bracket labels, seeds). See
            # docs/ROADMAP_2026.md P1.3.
            for key in (
                'bracket',
                'game',
                'seed1',
                'seed2',
                'take',
                'from_games',
                'determines',
                'two_week',
            ):
                if key in matchup:
                    matchup_data[key] = matchup[key]

            matchups_data.append(matchup_data)

        week_data['matchups'] = matchups_data

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump(week_data, f, indent=2)

    print(f'Scores saved to {output_path}')


def _has_cycle(beats: dict[str, set]) -> bool:
    """True if the directed "beats" relation (node -> set of nodes it beats)
    contains a cycle, via iterative DFS with a coloring scheme."""
    white, gray, black = 0, 1, 2
    color = dict.fromkeys(beats, white)

    for start in beats:
        if color[start] != white:
            continue
        stack = [(start, iter(beats[start]))]
        color[start] = gray
        while stack:
            node, neighbors = stack[-1]
            advanced = False
            for nxt in neighbors:
                if color[nxt] == gray:
                    return True
                if color[nxt] == white:
                    color[nxt] = gray
                    stack.append((nxt, iter(beats[nxt])))
                    advanced = True
                    break
            if not advanced:
                color[node] = black
                stack.pop()

    return False


def update_standings_json(
    standings_path: str | Path,
    week_data_paths: list[str | Path],
    season: int,
) -> list[dict]:
    """Update standings based on scored weeks.

    Args:
        standings_path: Path to standings.json output
        week_data_paths: List of paths to scored week JSON files
        season: Season year

    Returns:
        Updated standings list
    """

    standings = {}
    # head_to_head[a][b] = {'wins', 'losses', 'ties'} for a's regular-season
    # record against b specifically (constitution tiebreaker #3).
    head_to_head: dict[str, dict[str, dict[str, int]]] = {}
    regular_season_weeks = 15

    for week_path in week_data_paths:
        week_path = Path(week_path)
        if not week_path.exists():
            continue

        with open(week_path) as f:
            week_data = json.load(f)

        week_num = week_data.get('week', 0)
        if week_num > regular_season_weeks:
            continue
        if not week_data.get('has_scores'):
            # A week file that exists but has no starter with matched stats is
            # ambiguous: it's either genuinely unplayed (bye week, kickoff
            # hasn't happened) or a leaguewide stats-matching outage silently
            # dropped every starter. Either way, standings excludes it - flag
            # loudly so a human notices rather than the week vanishing quietly.
            # See docs/ROADMAP_2026.md P1.7.
            print(
                f'WARNING: week {week_num} at {week_path} has has_scores=False '
                '(no starter had stats matched) - excluded from standings. If '
                'games have already been played this week, this likely means a '
                'stats-matching outage, not a legitimate bye/pre-kickoff week.'
            )
            continue

        # Process team scores
        for team in week_data.get('teams', []):
            abbrev = team['abbrev']
            if abbrev not in standings:
                standings[abbrev] = {
                    'name': team['name'],
                    'owner': team.get('owner', ''),
                    'abbrev': abbrev,
                    'rank_points': 0.0,
                    'wins': 0,
                    'losses': 0,
                    'ties': 0,
                    'top_half': 0,
                    'points_for': 0.0,
                    'points_against': 0.0,
                }

        # Process matchups for W/L
        for matchup in week_data.get('matchups', []):
            t1 = matchup.get('team1', {})
            t2 = matchup.get('team2', {})

            if not t1 or not t2:
                continue

            s1 = t1.get('total_score', 0)
            s2 = t2.get('total_score', 0)
            a1 = t1.get('abbrev', '')
            a2 = t2.get('abbrev', '')

            if a1 not in standings or a2 not in standings:
                continue

            standings[a1]['points_for'] += s1
            standings[a1]['points_against'] += s2
            standings[a2]['points_for'] += s2
            standings[a2]['points_against'] += s1

            head_to_head.setdefault(a1, {}).setdefault(a2, {'wins': 0, 'losses': 0, 'ties': 0})
            head_to_head.setdefault(a2, {}).setdefault(a1, {'wins': 0, 'losses': 0, 'ties': 0})

            if s1 > s2:
                standings[a1]['rank_points'] += 1.0
                standings[a1]['wins'] += 1
                standings[a2]['losses'] += 1
                head_to_head[a1][a2]['wins'] += 1
                head_to_head[a2][a1]['losses'] += 1
            elif s2 > s1:
                standings[a2]['rank_points'] += 1.0
                standings[a2]['wins'] += 1
                standings[a1]['losses'] += 1
                head_to_head[a2][a1]['wins'] += 1
                head_to_head[a1][a2]['losses'] += 1
            else:
                standings[a1]['rank_points'] += 0.5
                standings[a2]['rank_points'] += 0.5
                standings[a1]['ties'] += 1
                standings[a2]['ties'] += 1
                head_to_head[a1][a2]['ties'] += 1
                head_to_head[a2][a1]['ties'] += 1

        # Top half scoring
        teams_by_score = sorted(
            week_data.get('teams', []), key=lambda x: x.get('total_score', 0), reverse=True
        )
        num_teams = len(teams_by_score)
        top_half_cutoff = num_teams // 2

        current_rank = 1
        i = 0
        while i < len(teams_by_score):
            current_score = teams_by_score[i].get('total_score', 0)
            tied_teams = []
            while (
                i < len(teams_by_score) and teams_by_score[i].get('total_score', 0) == current_score
            ):
                tied_teams.append(teams_by_score[i])
                i += 1

            tied_positions = list(range(current_rank, current_rank + len(tied_teams)))
            positions_in_top_half = [p for p in tied_positions if p <= top_half_cutoff]

            if positions_in_top_half:
                points_per_team = (0.5 * len(positions_in_top_half)) / len(tied_teams)
                for team in tied_teams:
                    abbrev = team.get('abbrev', '')
                    if abbrev in standings:
                        standings[abbrev]['rank_points'] += points_per_team
                        standings[abbrev]['top_half'] += len(positions_in_top_half) / len(
                            tied_teams
                        )

            current_rank += len(tied_teams)

    # A pairwise head-to-head tiebreaker is inherently non-transitive: three
    # teams tied on rank_points/wins/points_for with a cyclic H2H record (A
    # beat B, B beat C, C beat A) have no consistent total order, and feeding
    # that into cmp_to_key would silently seed one team above another it lost
    # to. Detect such cycles up front, per tied group, and fall back to a
    # stable order (with a loud warning) for any group where they occur
    # instead of letting the comparator "resolve" them arbitrarily.
    tie_groups: dict[tuple, list[str]] = {}
    for abbrev, team in standings.items():
        key = (team['rank_points'], team['wins'], team['points_for'])
        tie_groups.setdefault(key, []).append(abbrev)

    h2h_cyclic_groups: list[frozenset] = []
    for abbrevs in tie_groups.values():
        if len(abbrevs) < 3:
            continue  # a two-team tie can't cycle

        beats: dict[str, set] = {a: set() for a in abbrevs}
        for a in abbrevs:
            for b in abbrevs:
                if a == b:
                    continue
                record = head_to_head.get(a, {}).get(b)
                if record and record['wins'] > record['losses']:
                    beats[a].add(b)

        if _has_cycle(beats):
            h2h_cyclic_groups.append(frozenset(abbrevs))
            print(
                f'WARNING: standings tie among {sorted(abbrevs)} has a cyclic head-to-head '
                'record (e.g. A beat B, B beat C, C beat A) that head-to-head cannot resolve '
                '- commissioner must decide. Leaving current relative order in place for '
                'this group.'
            )

    def _in_cyclic_group(a: str, b: str) -> bool:
        return any(a in group and b in group for group in h2h_cyclic_groups)

    # Sort standings per the constitution's tiebreaker order: 1) rank_points,
    # 2) total wins, 3) total points scored, 4) head-to-head, 5) commissioner
    # decision (logged, order left stable). See docs/ROADMAP_2026.md P0.4.
    def _compare(a: dict, b: dict) -> int:
        for key in ('rank_points', 'wins', 'points_for'):
            if a[key] != b[key]:
                return -1 if a[key] > b[key] else 1

        if _in_cyclic_group(a['abbrev'], b['abbrev']):
            return 0

        record = head_to_head.get(a['abbrev'], {}).get(b['abbrev'])
        if record and record['wins'] != record['losses']:
            return -1 if record['wins'] > record['losses'] else 1

        print(
            f'WARNING: standings tie between {a["abbrev"]} and {b["abbrev"]} is unresolved by '
            f'rank_points, wins, points_for, and head-to-head — commissioner must decide. '
            f'Leaving current relative order in place.'
        )
        return 0

    sorted_standings = sorted(standings.values(), key=functools.cmp_to_key(_compare))
    for seed, team in enumerate(sorted_standings, 1):
        team['seed'] = seed

    # Save to file
    standings_path = Path(standings_path)
    standings_path.parent.mkdir(parents=True, exist_ok=True)

    with open(standings_path, 'w') as f:
        json.dump(
            {
                'updated_at': datetime.now(timezone.utc).isoformat(),
                'standings': sorted_standings,
            },
            f,
            indent=2,
        )

    return sorted_standings
