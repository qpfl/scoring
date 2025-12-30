#!/usr/bin/env python3
"""
Sync rosters from JSON to Excel.

This script should be run after any roster changes to keep the Excel file in sync.
The JSON file (data/rosters.json) is the source of truth for 2026+.

Usage:
    python scripts/sync_rosters.py
    python scripts/sync_rosters.py --excel "2026 Scores.xlsx" --sheet "Rosters"
"""

import argparse
from pathlib import Path
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from qpfl.roster_sync import sync_rosters_to_excel


def main():
    parser = argparse.ArgumentParser(description="Sync rosters from JSON to Excel")
    parser.add_argument(
        "--rosters", "-r",
        default="data/rosters.json",
        help="Path to rosters.json file",
    )
    parser.add_argument(
        "--excel", "-e",
        default="2026 Scores.xlsx",
        help="Path to Excel file to update",
    )
    parser.add_argument(
        "--sheet", "-s",
        default="Rosters",
        help="Sheet name for rosters",
    )
    
    args = parser.parse_args()
    
    rosters_path = Path(args.rosters)
    excel_path = Path(args.excel)
    
    if not rosters_path.exists():
        print(f"❌ Rosters file not found: {rosters_path}")
        sys.exit(1)
    
    success = sync_rosters_to_excel(rosters_path, excel_path, args.sheet)
    
    if success:
        print("✅ Rosters synced successfully")
    else:
        print("❌ Failed to sync rosters")
        sys.exit(1)


if __name__ == "__main__":
    main()

