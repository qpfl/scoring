"""League configuration management."""

from functools import lru_cache
from pathlib import Path

from .schemas import LeagueConfig
from .utils import load_json


@lru_cache(maxsize=1)
def get_config() -> LeagueConfig:
    """
    Load league configuration from data/league_config.json.

    Configuration is cached after first load for performance.

    Returns:
        LeagueConfig object with validated settings

    Raises:
        FileNotFoundError: If league_config.json doesn't exist
        ValidationError: If config file has invalid structure

    Example:
        from qpfl.config import get_config
        config = get_config()
        print(f"Current season: {config.current_season}")
    """
    config_path = Path(__file__).parent.parent / 'data' / 'league_config.json'
    return load_json(config_path, schema=LeagueConfig)


def get_current_season() -> int:
    """Get the current season from config."""
    return get_config().current_season


def get_trade_deadline_week() -> int:
    """Get the trade deadline week from config."""
    return get_config().trade_deadline_week


def get_roster_slots() -> dict[str, int]:
    """Get maximum roster slots per position from config."""
    return get_config().roster_slots


def get_starter_slots() -> dict[str, int]:
    """Get maximum starter slots per position from config."""
    return get_config().starter_slots


def get_taxi_slots() -> int:
    """Get number of taxi squad slots from config."""
    return get_config().taxi_slots


def get_playoff_structure() -> dict[str, list[int]]:
    """Get playoff bracket structure from config."""
    return get_config().playoff_structure


def get_regular_season_weeks() -> int:
    """Get number of regular season weeks from config."""
    return get_config().regular_season_weeks


def get_playoff_weeks() -> list[int]:
    """Get list of playoff week numbers from config."""
    return get_config().playoff_weeks


def clear_config_cache() -> None:
    """
    Clear the configuration cache.

    Use this if the config file is modified during runtime
    and you need to reload it.

    Example:
        from qpfl.config import clear_config_cache, get_config
        clear_config_cache()
        config = get_config()  # Reloads from file
    """
    get_config.cache_clear()
