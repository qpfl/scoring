#!/usr/bin/env python3
"""
Create a new QPFL season.

This script automates the transition from one season to the next:
1. Archives the previous season (sets is_historical=true, removes working files)
2. Creates the new season directory structure
3. Updates configuration files with the new season year

Usage:
    python scripts/create_new_season.py 2027
    python scripts/create_new_season.py 2027 --dry-run
"""

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path


def load_json(path: Path) -> dict | list:
    """Load JSON file."""
    with open(path) as f:
        return json.load(f)


def save_json(path: Path, data: dict | list, indent: int = 2) -> None:
    """Save JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=indent)


def update_file_pattern(path: Path, pattern: str, replacement: str, dry_run: bool = False) -> bool:
    """Update a file by replacing a regex pattern."""
    if not path.exists():
        print(f"  Warning: {path} not found")
        return False
    
    content = path.read_text()
    new_content = re.sub(pattern, replacement, content)
    
    if content == new_content:
        print(f"  No changes needed in {path}")
        return False
    
    if dry_run:
        print(f"  Would update {path}")
    else:
        path.write_text(new_content)
        print(f"  Updated {path}")
    return True


def archive_season(season_dir: Path, web_dir: Path, prev_season: int, dry_run: bool = False) -> None:
    """Archive a completed season."""
    meta_path = season_dir / "meta.json"
    
    if not meta_path.exists():
        print(f"  Warning: {meta_path} not found, skipping archive")
        return
    
    # Update meta.json
    meta = load_json(meta_path)
    meta["is_current"] = False
    meta["is_historical"] = True
    meta["current_week"] = 17
    meta["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    if dry_run:
        print(f"  Would update {meta_path} to historical")
    else:
        save_json(meta_path, meta)
        print(f"  Updated {meta_path} to historical")
    
    # Remove working files that shouldn't be in archived seasons
    working_files = ["draft_picks.json", "live.json", "rosters.json"]
    for filename in working_files:
        file_path = season_dir / filename
        if file_path.exists():
            if dry_run:
                print(f"  Would remove {file_path}")
            else:
                file_path.unlink()
                print(f"  Removed {file_path}")
    
    # Create historical data file (data_YYYY.json)
    historical_path = web_dir / f"data_{prev_season}.json"
    if not historical_path.exists():
        standings_path = season_dir / "standings.json"
        weeks_dir = season_dir / "weeks"
        
        if standings_path.exists() and weeks_dir.exists():
            weeks = []
            for week_file in sorted(weeks_dir.glob("week_*.json"), 
                                    key=lambda x: int(x.stem.split('_')[1])):
                weeks.append(load_json(week_file))
            
            historical_data = {
                "season": prev_season,
                "is_historical": True,
                "is_current": False,
                "current_week": 17,
                "weeks": weeks,
                "standings": load_json(standings_path),
                "teams": meta.get("teams", []),
                "schedule": meta.get("schedule", []),
                "trade_deadline_week": meta.get("trade_deadline_week", 12),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            
            if dry_run:
                print(f"  Would create {historical_path}")
            else:
                save_json(historical_path, historical_data)
                print(f"  Created {historical_path}")


def create_new_season_dir(
    season_dir: Path,
    new_season: int,
    teams: list[dict],
    dry_run: bool = False
) -> None:
    """Create the directory structure for a new season."""
    if season_dir.exists():
        print(f"  Warning: {season_dir} already exists")
        return
    
    if dry_run:
        print(f"  Would create {season_dir}")
        print(f"  Would create {season_dir / 'weeks'}")
        print(f"  Would create {season_dir / 'meta.json'}")
        print(f"  Would create {season_dir / 'standings.json'}")
        return
    
    # Create directories
    (season_dir / "weeks").mkdir(parents=True, exist_ok=True)
    print(f"  Created {season_dir / 'weeks'}")
    
    # Create meta.json
    meta = {
        "season": new_season,
        "is_current": True,
        "is_historical": False,
        "current_week": 0,
        "trade_deadline_week": 12,
        "teams": teams,
        "schedule": [],
        "weeks_available": []
    }
    save_json(season_dir / "meta.json", meta)
    print(f"  Created {season_dir / 'meta.json'}")
    
    # Create empty standings.json
    save_json(season_dir / "standings.json", [])
    print(f"  Created {season_dir / 'standings.json'}")


def get_teams_from_data(data_dir: Path) -> list[dict]:
    """Get current team data from data/teams.json."""
    teams_path = data_dir / "teams.json"
    if teams_path.exists():
        data = load_json(teams_path)
        return data.get("teams", [])
    
    # Fallback to default teams
    return [
        {"abbrev": "GSA", "name": "TBD", "owner": "Griffin Ansel", "owner_key": "griffin_ansel"},
        {"abbrev": "CGK", "name": "TBD", "owner": "Connor Kaminska", "owner_key": "connor_kaminska"},
        {"abbrev": "RPA", "name": "TBD", "owner": "Ryan Redacted", "owner_key": "ryan_redacted"},
        {"abbrev": "S/T", "name": "TBD", "owner": "Spencer/Tim", "owner_key": "spencer_tim"},
        {"abbrev": "CWR", "name": "TBD", "owner": "Redacted Reardon", "owner_key": "redacted_reardon"},
        {"abbrev": "J/J", "name": "TBD", "owner": "Joe Censored/Censored Ward", "owner_key": "joe_censored_censored_ward"},
        {"abbrev": "SLS", "name": "TBD", "owner": "Stephen Schmidt", "owner_key": "stephen_schmidt"},
        {"abbrev": "AYP", "name": "TBD", "owner": "Arnav Patel", "owner_key": "arnav_patel"},
        {"abbrev": "AST", "name": "TBD", "owner": "Anagh Tiwary", "owner_key": "anagh_tiwary"},
        {"abbrev": "WJK", "name": "TBD", "owner": "Bill Kuhl", "owner_key": "bill_kuhl"},
    ]


def main():
    parser = argparse.ArgumentParser(description="Create a new QPFL season")
    parser.add_argument("new_season", type=int, help="New season year (e.g., 2027)")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Show what would be done without making changes")
    args = parser.parse_args()
    
    new_season = args.new_season
    prev_season = new_season - 1
    dry_run = args.dry_run
    
    # Paths
    project_dir = Path(__file__).parent.parent
    seasons_dir = project_dir / "web" / "data" / "seasons"
    data_dir = project_dir / "data"
    
    prev_season_dir = seasons_dir / str(prev_season)
    new_season_dir = seasons_dir / str(new_season)
    
    print(f"\n{'DRY RUN: ' if dry_run else ''}Creating season {new_season}")
    print("=" * 50)
    
    # Step 1: Archive previous season
    print(f"\n1. Archiving {prev_season} season...")
    web_dir = project_dir / "web"
    if prev_season_dir.exists():
        archive_season(prev_season_dir, web_dir, prev_season, dry_run)
    else:
        print(f"  Warning: {prev_season_dir} not found, skipping archive")
    
    # Step 2: Create new season directory
    print(f"\n2. Creating {new_season} season directory...")
    teams = get_teams_from_data(data_dir)
    create_new_season_dir(new_season_dir, new_season, teams, dry_run)
    
    # Step 3: Update GitHub Actions workflow
    print("\n3. Updating GitHub Actions workflow...")
    workflow_path = project_dir / ".github" / "workflows" / "score.yml"
    update_file_pattern(
        workflow_path,
        r"CURRENT_SEASON:\s*'(\d{4})'",
        f"CURRENT_SEASON: '{new_season}'",
        dry_run
    )
    
    # Step 4: Update export_current.py defaults
    print("\n4. Updating export_current.py...")
    export_path = project_dir / "scripts" / "export_current.py"
    update_file_pattern(
        export_path,
        r"season:\s*int\s*=\s*\d{4}",
        f"season: int = {new_season}",
        dry_run
    )
    update_file_pattern(
        export_path,
        r"default=\d{4},\s*help=\"Season year\"",
        f"default={new_season}, help=\"Season year\"",
        dry_run
    )
    
    # Step 5: Update API transaction.py
    print("\n5. Updating API transaction.py...")
    api_path = project_dir / "api" / "transaction.py"
    update_file_pattern(
        api_path,
        r"CURRENT_SEASON\s*=\s*\d{4}",
        f"CURRENT_SEASON = {new_season}",
        dry_run
    )
    
    # Step 6: Update frontend CURRENT_SEASON in index.html
    print("\n6. Updating frontend index.html...")
    index_path = project_dir / "web" / "index.html"
    update_file_pattern(
        index_path,
        r"const CURRENT_SEASON = \d{4};",
        f"const CURRENT_SEASON = {new_season};",
        dry_run
    )
    
    # Step 7: Clear pending trades for new season
    print("\n7. Resetting pending trades...")
    pending_trades_path = data_dir / "pending_trades.json"
    if pending_trades_path.exists():
        if dry_run:
            print(f"  Would reset {pending_trades_path}")
        else:
            pending = {"trades": [], "trade_deadline_week": 12}
            save_json(pending_trades_path, pending)
            print(f"  Reset {pending_trades_path}")
    
    # Summary
    print("\n" + "=" * 50)
    print(f"{'DRY RUN COMPLETE' if dry_run else 'SEASON CREATION COMPLETE'}")
    print("\nNext steps:")
    print(f"  1. Update team names in data/teams.json for {new_season}")
    print(f"  2. Add the schedule to web/data/seasons/{new_season}/meta.json when available")
    print("  3. Run export script: python scripts/export_current.py")
    print("  4. Commit and push changes")
    print("  5. Deploy to GitHub Pages")


if __name__ == "__main__":
    main()

