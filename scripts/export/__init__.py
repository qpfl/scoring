"""
QPFL Web Export Module

Split data export for better caching and incremental updates.

Usage:
    # Export all data
    python -m scripts.export.all
    
    # Export only shared data (constitution, hall of fame, etc.)
    python -m scripts.export.shared
    
    # Export current season
    python -m scripts.export.season 2025
    
    # Export single week
    python -m scripts.export.week 2025 16
    
    # Export historical season from Excel
    python -m scripts.export.historical 2024
"""

from pathlib import Path

# Base paths
SCRIPT_DIR = Path(__file__).parent
PROJECT_DIR = SCRIPT_DIR.parent.parent
WEB_DIR = PROJECT_DIR / "web"
DATA_DIR = PROJECT_DIR / "data"
DOCS_DIR = PROJECT_DIR / "docs"

# Output paths
WEB_DATA_DIR = WEB_DIR / "data"
SHARED_DIR = WEB_DATA_DIR / "shared"
SEASONS_DIR = WEB_DATA_DIR / "seasons"

# Current season
CURRENT_SEASON = 2025

# Ensure directories exist
def ensure_dirs():
    """Create output directories if they don't exist."""
    SHARED_DIR.mkdir(parents=True, exist_ok=True)
    SEASONS_DIR.mkdir(parents=True, exist_ok=True)

