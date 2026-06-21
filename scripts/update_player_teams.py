#!/usr/bin/env python3
"""
Update NFL team assignments for all players in data/rosters.json.

Uses nflreadpy to look up each player's current team and updates the
nfl_team field. Run monthly during the offseason to capture trades,
free-agent signings, and cuts.

Skill-position players (QB, RB, WR, TE, K) are updated via the nflreadpy
player database. D/ST and OL entries are team-based and skipped. HC
(head coaches) are looked up via recent schedule data.

Usage:
    python scripts/update_player_teams.py [--season YEAR] [--dry-run]
"""

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

import polars as pl

try:
    import nflreadpy as nfl
except ImportError:
    raise ImportError('Please install nflreadpy: pip install nflreadpy')

# Our abbreviations that differ from nflreadpy (LAR→LA, JAC→JAX)
# Reverse mapping so we can convert nflreadpy abbrevs back to our format.
NFLREADPY_TO_OURS = {'LA': 'LAR', 'JAX': 'JAC'}

REPO_ROOT = Path(__file__).parent.parent
ROSTERS_PATH = REPO_ROOT / 'data' / 'rosters.json'

# Positions handled via player lookup
SKILL_POSITIONS = {'QB', 'RB', 'WR', 'TE', 'K'}

# Positions that are NFL teams, not individual players — skip
TEAM_POSITIONS = {'D/ST', 'OL'}


def clean_name(name: str) -> str:
    """Strip name suffixes (Jr., Sr., II, III) for looser matching."""
    return re.sub(r'\s+(Sr\.?|Jr\.?|II|III|IV|V)$', '', name.strip()).strip()


def normalize_team(nflreadpy_abbrev: str | None) -> str:
    """Convert nflreadpy team abbreviation to our system's abbreviation."""
    if not nflreadpy_abbrev:
        return 'FA'
    return NFLREADPY_TO_OURS.get(str(nflreadpy_abbrev), str(nflreadpy_abbrev))


def load_player_db(season: int) -> pl.DataFrame | None:
    """
    Load current player database from nflreadpy.

    Tries load_rosters first (more current), falls back to load_players.
    Returns None if neither is available for the requested season.
    """
    # Try load_rosters (season-specific, most accurate for current team)
    try:
        df = nfl.load_rosters(seasons=[season])
        if df is not None and df.height > 0:
            print(f'  Loaded {df.height} roster entries for {season} season')
            return df
    except Exception as e:
        print(f'  load_rosters({season}) unavailable: {e}')

    # Try the previous season if current hasn't been seeded yet
    if season > datetime.date.today().year:
        prev = season - 1
        try:
            df = nfl.load_rosters(seasons=[prev])
            if df is not None and df.height > 0:
                print(f'  Loaded {df.height} roster entries for {prev} season (fallback)')
                return df
        except Exception:
            pass

    # Fall back to the general player database
    try:
        df = nfl.load_players()
        if df is not None and df.height > 0:
            print(f'  Loaded {df.height} entries from player database (fallback)')
            return df
    except Exception as e:
        print(f'  load_players() failed: {e}')

    return None


def load_coach_db(season: int) -> dict[str, str]:
    """
    Build a {coach_name: team_abbrev} mapping from recent schedule data.

    Uses schedule data from the given season (or the previous one as fallback).
    Only coaches who appear in games are captured — newly hired coaches
    who haven't coached a game yet won't appear here.
    """
    coach_map: dict[str, str] = {}

    for yr in [season, season - 1]:
        try:
            schedules = nfl.load_schedules(seasons=yr)
            if schedules is None or schedules.height == 0:
                continue

            for col, team_col in [('home_coach', 'home_team'), ('away_coach', 'away_team')]:
                if col not in schedules.columns or team_col not in schedules.columns:
                    continue
                rows = schedules.select([col, team_col]).filter(
                    pl.col(col).is_not_null() & (pl.col(col) != '')
                )
                # Use the LAST game each coach coached (most recent team assignment)
                for row in rows.iter_rows(named=True):
                    coach_name = row.get(col, '')
                    team = row.get(team_col, '')
                    if coach_name and team:
                        coach_map[coach_name.lower()] = normalize_team(team)

            if coach_map:
                print(f'  Built coach map from {yr} schedules ({len(coach_map)} coaches)')
                return coach_map
        except Exception as e:
            print(f'  Could not load schedules for {yr}: {e}')

    return coach_map


def detect_name_col(df: pl.DataFrame) -> str | None:
    for candidate in ['player_name', 'player_display_name', 'display_name', 'full_name']:
        if candidate in df.columns:
            return candidate
    return None


def detect_team_col(df: pl.DataFrame) -> str | None:
    for candidate in ['team', 'team_abbr', 'recent_team']:
        if candidate in df.columns:
            return candidate
    return None


def find_team_for_player(
    name: str,
    position: str,
    players_df: pl.DataFrame,
    name_col: str,
    team_col: str,
) -> str | None:
    """
    Look up the current team for a skill-position player.

    Returns our system's team abbreviation, "FA" for unsigned players,
    or None if no confident match was found.
    """
    cleaned = clean_name(name)

    def best_match(df: pl.DataFrame) -> str | None:
        if df.height == 0:
            return None
        if df.height == 1:
            val = df[team_col][0]
            return normalize_team(val) if val else 'FA'
        # Multiple matches — try to narrow by position
        if 'position' in df.columns:
            pos_df = df.filter(pl.col('position') == position)
            if pos_df.height == 1:
                val = pos_df[team_col][0]
                return normalize_team(val) if val else 'FA'
        return None  # ambiguous

    # 1. Exact match
    exact = players_df.filter(
        pl.col(name_col).str.to_lowercase() == cleaned.lower()
    )
    result = best_match(exact)
    if result is not None:
        return result

    # 2. DB name contains our cleaned name (handles short names like "Tua")
    contains = players_df.filter(
        pl.col(name_col).str.to_lowercase().str.contains(cleaned.lower(), literal=True)
    )
    result = best_match(contains)
    if result is not None:
        return result

    # 3. First + last name tokens present anywhere in DB name
    parts = cleaned.split()
    if len(parts) >= 2:
        first, last = parts[0], parts[-1]
        both = players_df.filter(
            pl.col(name_col).str.to_lowercase().str.contains(first.lower(), literal=True)
            & pl.col(name_col).str.to_lowercase().str.contains(last.lower(), literal=True)
        )
        result = best_match(both)
        if result is not None:
            return result

    return None


def main() -> None:
    parser = argparse.ArgumentParser(description='Update player NFL team assignments')
    parser.add_argument(
        '--season',
        type=int,
        default=None,
        help='Season year to query (default: current calendar year)',
    )
    parser.add_argument(
        '--dry-run', '-n', action='store_true',
        help='Print changes without writing files',
    )
    args = parser.parse_args()

    season = args.season or datetime.date.today().year
    print(f"\nQPFL Player Team Updater — season {season}")
    print('=' * 50)

    # Load data sources
    print('\nLoading player data...')
    players_df = load_player_db(season)
    if players_df is None:
        print('ERROR: Could not load player database. Aborting.')
        sys.exit(1)

    name_col = detect_name_col(players_df)
    team_col = detect_team_col(players_df)
    if not name_col or not team_col:
        print(f'ERROR: Cannot find name/team columns in player data. '
              f'Available: {players_df.columns}')
        sys.exit(1)

    print(f'  Using columns: name={name_col!r}, team={team_col!r}')

    print('\nLoading coach data...')
    coach_map = load_coach_db(season)

    # Load rosters
    with open(ROSTERS_PATH) as f:
        rosters: dict = json.load(f)

    updated: list[str] = []
    unchanged: list[str] = []
    not_found: list[str] = []
    skipped: list[str] = []

    for qpfl_team, players in rosters.items():
        for player in players:
            name = player.get('name', '')
            position = player.get('position', '')
            old_team = player.get('nfl_team', '')

            # D/ST and OL entries represent NFL teams, not individual players.
            if position in TEAM_POSITIONS:
                skipped.append(f'  [{qpfl_team}] {name} ({position}) — team-based, skipped')
                continue

            # HC: look up via schedule-derived coach map
            if position == 'HC':
                coach_key = clean_name(name).lower()
                new_team = coach_map.get(coach_key)
                if new_team is None:
                    not_found.append(
                        f'  [{qpfl_team}] {name} ({position}) — not in schedule data, '
                        f'kept as {old_team or "unknown"}'
                    )
                    continue
                if new_team != old_team:
                    updated.append(f'  [{qpfl_team}] {name} ({position}): {old_team} → {new_team}')
                    if not args.dry_run:
                        player['nfl_team'] = new_team
                else:
                    unchanged.append(f'  [{qpfl_team}] {name} ({position}): {old_team} ✓')
                continue

            # Skill positions: look up in player database
            if position in SKILL_POSITIONS:
                new_team = find_team_for_player(name, position, players_df, name_col, team_col)
                if new_team is None:
                    not_found.append(
                        f'  [{qpfl_team}] {name} ({position}) — no match found, '
                        f'kept as {old_team or "unknown"}'
                    )
                    continue
                if new_team != old_team:
                    updated.append(f'  [{qpfl_team}] {name} ({position}): {old_team} → {new_team}')
                    if not args.dry_run:
                        player['nfl_team'] = new_team
                else:
                    unchanged.append(f'  [{qpfl_team}] {name} ({position}): {old_team} ✓')
                continue

            skipped.append(f'  [{qpfl_team}] {name} ({position}) — unknown position, skipped')

    # Print results
    prefix = 'DRY RUN: ' if args.dry_run else ''
    print(f'\n{prefix}Results')
    print('=' * 50)

    if updated:
        print(f'\nUpdated ({len(updated)}):')
        for line in updated:
            print(line)

    if not_found:
        print(f'\nNot found — kept existing ({len(not_found)}):')
        for line in not_found:
            print(line)

    if skipped:
        print(f'\nSkipped ({len(skipped)}):')
        for line in skipped:
            print(line)

    print(f'\nUnchanged: {len(unchanged)}')

    skill_total = len(updated) + len(not_found) + len(unchanged)
    print(
        f'\nSummary: {len(updated)} updated, {len(not_found)} not found, '
        f'{len(unchanged)} unchanged, {len(skipped)} skipped'
    )

    # Safety check: abort if too many players couldn't be matched.
    # High miss rate usually means the data source doesn't have this season yet.
    if skill_total > 0 and len(not_found) / skill_total > 0.35:
        pct = len(not_found) / skill_total
        print(
            f'\nWARNING: {len(not_found)}/{skill_total} skill-position players not found '
            f'({pct:.0%}). The {season} roster data may not be available yet.'
        )
        if not args.dry_run:
            print('Aborting file write to avoid overwriting good data with stale data.')
            sys.exit(1)

    if not args.dry_run:
        with open(ROSTERS_PATH, 'w') as f:
            json.dump(rosters, f, indent=2)
        print(f'\nWrote {ROSTERS_PATH}')
    else:
        print('\n(Dry run — no files written)')


if __name__ == '__main__':
    main()
