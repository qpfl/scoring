#!/usr/bin/env python3
"""Generate legacy data.json and data_YEAR.json from split files.

This allows the existing frontend to continue working while we have
the new split data structure as the source of truth.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from . import CURRENT_SEASON, SEASONS_DIR, SHARED_DIR, WEB_DATA_DIR, WEB_DIR, ensure_dirs


def load_json(path: Path) -> dict:
    """Load JSON file, returning empty dict if not found."""
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def generate_legacy_data(season: int) -> dict:
    """Generate legacy data.json format from split files."""
    season_dir = SEASONS_DIR / str(season)
    weeks_dir = season_dir / "weeks"
    
    is_current = season == CURRENT_SEASON
    
    # Load season meta
    meta = load_json(season_dir / "meta.json")
    standings_data = load_json(season_dir / "standings.json")
    
    # Load weeks
    weeks = []
    week_files = sorted(weeks_dir.glob("week_*.json"), key=lambda p: int(p.stem.split("_")[1]))
    for week_file in week_files:
        week_data = load_json(week_file)
        weeks.append(week_data)
    
    # Build legacy format
    data = {
        "updated_at": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        "season": season,
        "current_week": meta.get("current_week", 17),
        "is_historical": meta.get("is_historical", not is_current),
        "teams": meta.get("teams", []),
        "weeks": weeks,
        "standings": standings_data.get("standings", []),
        "schedule": meta.get("schedule", []),
    }
    
    # Add current season data
    if is_current:
        rosters_data = load_json(season_dir / "rosters.json")
        live_data = load_json(season_dir / "live.json")
        draft_picks_data = load_json(season_dir / "draft_picks.json")
        
        data["rosters"] = rosters_data.get("rosters", {})
        data["game_times"] = live_data.get("game_times", {})
        data["fa_pool"] = live_data.get("fa_pool", [])
        data["pending_trades"] = live_data.get("pending_trades", [])
        data["trade_deadline_week"] = meta.get("trade_deadline_week", 12)
        data["draft_picks"] = draft_picks_data.get("picks", {})
    
    # Add shared data (for all seasons)
    constitution = load_json(SHARED_DIR / "constitution.json")
    hof = load_json(SHARED_DIR / "hall_of_fame.json")
    banners = load_json(SHARED_DIR / "banners.json")
    transactions = load_json(SHARED_DIR / "transactions.json")
    
    if constitution:
        data["constitution"] = constitution.get("articles", [])
    if hof:
        hof_copy = dict(hof)
        hof_copy.pop("updated_at", None)
        data["hall_of_fame"] = hof_copy
    if banners:
        data["banners"] = banners.get("banners", [])
    if transactions:
        data["transactions"] = transactions.get("seasons", [])
    
    return data


def export_legacy():
    """Export legacy format files from split data."""
    ensure_dirs()
    
    print("Generating legacy format files...")
    
    # Get available seasons from index
    index = load_json(WEB_DATA_DIR / "index.json")
    seasons = index.get("seasons", [CURRENT_SEASON])
    
    for season in seasons:
        print(f"  - {'data.json' if season == CURRENT_SEASON else f'data_{season}.json'}")
        
        data = generate_legacy_data(season)
        
        if season == CURRENT_SEASON:
            output_path = WEB_DIR / "data.json"
        else:
            output_path = WEB_DIR / f"data_{season}.json"
        
        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    print("Legacy files generated!")


if __name__ == "__main__":
    export_legacy()

