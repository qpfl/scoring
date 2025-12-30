"""QPFL Export Scripts.

This package contains export scripts for generating web data.

Main scripts:
- hall_of_fame.py: Generate Hall of Fame statistics from all seasons
"""

# Re-export commonly used constants from qpfl.constants
import sys
from pathlib import Path

# Add parent directories to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from qpfl.constants import (
    PROJECT_DIR,
    WEB_DIR,
    DATA_DIR,
    DOCS_DIR,
    WEB_DATA_DIR,
    SHARED_DIR,
    SEASONS_DIR,
    CURRENT_SEASON,
    ensure_dirs,
)

__all__ = [
    'PROJECT_DIR',
    'WEB_DIR',
    'DATA_DIR',
    'DOCS_DIR',
    'WEB_DATA_DIR',
    'SHARED_DIR',
    'SEASONS_DIR',
    'CURRENT_SEASON',
    'ensure_dirs',
]
