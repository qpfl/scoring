from qpfl.config import (
    clear_config_cache,
    get_config,
    get_current_season,
    get_playoff_structure,
    get_playoff_weeks,
    get_regular_season_weeks,
    get_roster_slots,
    get_starter_slots,
    get_taxi_slots,
    get_trade_deadline_week,
)


def test_config_accessors_match_validated_config():
    config = get_config()

    assert get_current_season() == config.current_season
    assert get_trade_deadline_week() == config.trade_deadline_week
    assert get_roster_slots() == config.roster_slots
    assert get_starter_slots() == config.starter_slots
    assert get_taxi_slots() == config.taxi_slots
    assert get_playoff_structure() == config.playoff_structure
    assert get_regular_season_weeks() == config.regular_season_weeks
    assert get_playoff_weeks() == config.playoff_weeks

    clear_config_cache()
    assert get_config() is not config
