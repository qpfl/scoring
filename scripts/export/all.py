#!/usr/bin/env python3
"""Export all data for the web.

This is the main entry point that exports:
- Shared data (constitution, hall of fame, banners, transactions)
- Current season data
- Historical seasons
- Index manifest
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from . import CURRENT_SEASON, PROJECT_DIR, SEASONS_DIR, WEB_DATA_DIR, ensure_dirs
from .legacy import export_legacy
from .season import export_season
from .shared import export_shared


def get_available_seasons() -> list[int]:
    """Find all available seasons with Excel files."""
    seasons = []
    
    # Current season
    current_excel = PROJECT_DIR / f"{CURRENT_SEASON} Scores.xlsx"
    if current_excel.exists():
        seasons.append(CURRENT_SEASON)
    
    # Historical seasons
    previous_dir = PROJECT_DIR / "previous_seasons"
    if previous_dir.exists():
        for excel_file in previous_dir.glob("*Scores.xlsx"):
            import re
            match = re.match(r'^(\d{4})\s+Scores\.xlsx$', excel_file.name)
            if match:
                seasons.append(int(match.group(1)))
    
    return sorted(seasons, reverse=True)


def export_index():
    """Export the index manifest file."""
    ensure_dirs()
    
    print("Exporting index.json...")
    
    available_seasons = get_available_seasons()
    
    index = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "current_season": CURRENT_SEASON,
        "seasons": available_seasons,
    }
    
    with open(WEB_DATA_DIR / "index.json", 'w') as f:
        json.dump(index, f, indent=2)
    
    print(f"  Available seasons: {available_seasons}")


def export_all(include_historical: bool = True):
    """Export everything."""
    ensure_dirs()
    
    print("=" * 50)
    print("QPFL Web Data Export")
    print("=" * 50)
    
    # Export shared data
    print("\n[1/3] Shared Data")
    print("-" * 30)
    export_shared()
    
    # Export current season
    print(f"\n[2/3] Current Season ({CURRENT_SEASON})")
    print("-" * 30)
    export_season(CURRENT_SEASON)
    
    # Export historical seasons
    if include_historical:
        available = get_available_seasons()
        historical = [s for s in available if s != CURRENT_SEASON]
        
        if historical:
            print(f"\n[3/3] Historical Seasons")
            print("-" * 30)
            for season in historical:
                export_season(season)
    
    # Export index
    print("\nGenerating index...")
    export_index()
    
    # Generate legacy format for backward compatibility
    print("\nGenerating legacy format...")
    export_legacy()
    
    print("\n" + "=" * 50)
    print("Export complete!")
    print("=" * 50)


if __name__ == "__main__":
    import sys
    
    if "--current-only" in sys.argv:
        export_all(include_historical=False)
    else:
        export_all()

