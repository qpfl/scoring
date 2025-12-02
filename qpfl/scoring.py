"""Scoring functions for each position type."""

import math
from typing import Dict, Tuple


def score_skill_player(stats: dict) -> Tuple[float, Dict[str, float]]:
    """
    Score a skill position player (QB, RB, WR, TE).
    
    Scoring:
        - Passing yards: 1 point per 25 yards
        - Rushing yards: 1 point per 10 yards
        - Receiving yards: 1 point per 10 yards
        - Touchdowns: 6 points each
        - Turnovers: -2 points each
        - Two point conversions: 2 points each
    """
    points = 0.0
    breakdown = {}
    
    # Passing yards
    passing_yards = stats.get('passing_yards', 0) or 0
    passing_pts = math.floor(passing_yards / 25)
    if passing_pts:
        breakdown['passing_yards'] = passing_pts
    points += passing_pts
    
    # Rushing yards
    rushing_yards = stats.get('rushing_yards', 0) or 0
    rushing_pts = math.floor(rushing_yards / 10)
    if rushing_pts:
        breakdown['rushing_yards'] = rushing_pts
    points += rushing_pts
    
    # Receiving yards
    receiving_yards = stats.get('receiving_yards', 0) or 0
    receiving_pts = math.floor(receiving_yards / 10)
    if receiving_pts:
        breakdown['receiving_yards'] = receiving_pts
    points += receiving_pts
    
    # Touchdowns
    total_tds = (
        (stats.get('passing_tds', 0) or 0) +
        (stats.get('rushing_tds', 0) or 0) +
        (stats.get('receiving_tds', 0) or 0)
    )
    td_pts = 6 * total_tds
    if td_pts:
        breakdown['touchdowns'] = td_pts
    points += td_pts
    
    # Turnovers
    turnovers = (
        (stats.get('passing_interceptions', 0) or 0) +
        (stats.get('sack_fumbles_lost', 0) or 0) +
        (stats.get('rushing_fumbles_lost', 0) or 0) +
        (stats.get('receiving_fumbles_lost', 0) or 0)
    )
    turnover_pts = -2 * turnovers
    if turnover_pts:
        breakdown['turnovers'] = turnover_pts
    points += turnover_pts
    
    # Two point conversions
    two_pt = (
        (stats.get('passing_2pt_conversions', 0) or 0) +
        (stats.get('rushing_2pt_conversions', 0) or 0) +
        (stats.get('receiving_2pt_conversions', 0) or 0)
    )
    two_pt_pts = 2 * two_pt
    if two_pt_pts:
        breakdown['two_point_conversions'] = two_pt_pts
    points += two_pt_pts
    
    return points, breakdown


def score_kicker(stats: dict) -> Tuple[float, Dict[str, float]]:
    """
    Score a kicker.
    
    Scoring:
        - PATs made: 1 point each
        - PATs missed: -2 points each
        - FGs 1-29 yards: 1 point each
        - FGs 30-39 yards: 2 points each
        - FGs 40-49 yards: 3 points each
        - FGs 50-59 yards: 4 points each
        - FGs 60+ yards: 5 points each
        - FGs missed: -1 point each
    """
    points = 0.0
    breakdown = {}
    
    # PATs
    pat_made = stats.get('pat_made', 0) or 0
    pat_missed = stats.get('pat_missed', 0) or 0
    
    if pat_made:
        breakdown['pat_made'] = pat_made
    points += pat_made
    
    if pat_missed:
        breakdown['pat_missed'] = -2 * pat_missed
    points -= 2 * pat_missed
    
    # Field Goals by distance
    fg_0_19 = stats.get('fg_made_0_19', 0) or 0
    fg_20_29 = stats.get('fg_made_20_29', 0) or 0
    fg_1_29 = fg_0_19 + fg_20_29
    if fg_1_29:
        breakdown['fg_1_29'] = fg_1_29
    points += fg_1_29
    
    fg_30_39 = stats.get('fg_made_30_39', 0) or 0
    if fg_30_39:
        breakdown['fg_30_39'] = 2 * fg_30_39
    points += 2 * fg_30_39
    
    fg_40_49 = stats.get('fg_made_40_49', 0) or 0
    if fg_40_49:
        breakdown['fg_40_49'] = 3 * fg_40_49
    points += 3 * fg_40_49
    
    fg_50_59 = stats.get('fg_made_50_59', 0) or 0
    if fg_50_59:
        breakdown['fg_50_59'] = 4 * fg_50_59
    points += 4 * fg_50_59
    
    fg_60_plus = stats.get('fg_made_60_', 0) or 0
    if fg_60_plus:
        breakdown['fg_60+'] = 5 * fg_60_plus
    points += 5 * fg_60_plus
    
    # Missed FGs
    fg_missed = stats.get('fg_missed', 0) or 0
    if fg_missed:
        breakdown['fg_missed'] = -1 * fg_missed
    points -= fg_missed
    
    return points, breakdown


def score_defense(team_stats: dict, opponent_stats: dict, game_info: dict) -> Tuple[float, Dict[str, float]]:
    """
    Score a defense/special teams.
    
    Scoring:
        - Points allowed 0: 8 pts | 1-9: 6 pts | 10-13: 4 pts | 14-17: 2 pts
        - Points allowed 18-31: -2 pts | 32-35: -4 pts | 36+: -6 pts
        - Turnovers forced: 2 points each
        - Sacks: 1 point each
        - Safeties: 2 points each
        - Blocked kicks: 2 points each
        - Blocked PATs: 1 point each
        - Defensive TDs: 4 points each
    """
    points = 0.0
    breakdown = {}
    
    # Points allowed
    points_allowed = game_info.get('points_allowed', 0) or 0
    
    if points_allowed == 0:
        pa_pts = 8
    elif points_allowed <= 9:
        pa_pts = 6
    elif points_allowed <= 13:
        pa_pts = 4
    elif points_allowed <= 17:
        pa_pts = 2
    elif points_allowed <= 31:
        pa_pts = -2
    elif points_allowed <= 35:
        pa_pts = -4
    else:
        pa_pts = -6
    
    breakdown['points_allowed'] = pa_pts
    points += pa_pts
    
    # Turnovers forced
    opp_ints = opponent_stats.get('passing_interceptions', 0) or 0
    opp_fumbles_lost = (
        (opponent_stats.get('sack_fumbles_lost', 0) or 0) +
        (opponent_stats.get('rushing_fumbles_lost', 0) or 0) +
        (opponent_stats.get('receiving_fumbles_lost', 0) or 0)
    )
    turnovers_forced = opp_ints + opp_fumbles_lost
    if turnovers_forced:
        breakdown['turnovers_forced'] = 2 * turnovers_forced
    points += 2 * turnovers_forced
    
    # Sacks
    sacks = team_stats.get('def_sacks', 0) or 0
    if sacks:
        breakdown['sacks'] = int(sacks)
    points += int(sacks)
    
    # Safeties
    safeties = team_stats.get('def_safeties', 0) or 0
    if safeties:
        breakdown['safeties'] = 2 * safeties
    points += 2 * safeties
    
    # Blocked kicks
    blocked_fg = opponent_stats.get('fg_blocked', 0) or 0
    if blocked_fg:
        breakdown['blocked_kicks'] = 2 * blocked_fg
    points += 2 * blocked_fg
    
    # Blocked PATs
    blocked_pat = opponent_stats.get('pat_blocked', 0) or 0
    if blocked_pat:
        breakdown['blocked_pats'] = blocked_pat
    points += blocked_pat
    
    # Defensive TDs
    def_tds = team_stats.get('def_tds', 0) or 0
    fumble_recovery_tds = team_stats.get('fumble_recovery_tds', 0) or 0
    total_def_tds = def_tds + fumble_recovery_tds
    if total_def_tds:
        breakdown['defensive_tds'] = 4 * total_def_tds
    points += 4 * total_def_tds
    
    return points, breakdown


def score_head_coach(game_info: dict) -> Tuple[float, Dict[str, float]]:
    """
    Score a head coach.
    
    Scoring:
        - Win by <10: 2 pts | 10-19: 3 pts | 20+: 4 pts
        - Loss by <10: -1 pt | 10-20: -2 pts | 20+: -3 pts
    """
    points = 0.0
    breakdown = {}
    
    team_score = game_info.get('team_score', 0) or 0
    opponent_score = game_info.get('opponent_score', 0) or 0
    margin = team_score - opponent_score
    
    if margin > 0:  # Win
        if margin < 10:
            points = 2
            breakdown['win_margin_<10'] = 2
        elif margin <= 19:
            points = 3
            breakdown['win_margin_10-19'] = 3
        else:
            points = 4
            breakdown['win_margin_20+'] = 4
    elif margin < 0:  # Loss
        loss_margin = abs(margin)
        if loss_margin < 10:
            points = -1
            breakdown['loss_margin_<10'] = -1
        elif loss_margin <= 20:
            points = -2
            breakdown['loss_margin_10-20'] = -2
        else:
            points = -3
            breakdown['loss_margin_20+'] = -3
    
    return points, breakdown


def score_offensive_line(team_stats: dict) -> Tuple[float, Dict[str, float]]:
    """
    Score an offensive line.
    
    Scoring:
        - 1 point per 100 team passing yards
        - 1 point per 50 team rushing yards
        - -1 point per sack allowed
        - +6 points per offensive lineman TD (rare)
    """
    points = 0.0
    breakdown = {}
    
    # Passing yards
    passing_yards = team_stats.get('passing_yards', 0) or 0
    passing_pts = math.floor(passing_yards / 100)
    if passing_pts:
        breakdown['passing_yards'] = passing_pts
    points += passing_pts
    
    # Rushing yards
    rushing_yards = team_stats.get('rushing_yards', 0) or 0
    rushing_pts = math.floor(rushing_yards / 50)
    if rushing_pts:
        breakdown['rushing_yards'] = rushing_pts
    points += rushing_pts
    
    # Sacks allowed
    sacks_allowed = team_stats.get('sacks_suffered', 0) or 0
    if sacks_allowed:
        breakdown['sacks_allowed'] = -sacks_allowed
    points -= sacks_allowed
    
    return points, breakdown

