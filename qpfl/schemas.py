"""Pydantic schemas for JSON data validation."""

from pydantic import BaseModel, Field, field_validator


class Player(BaseModel):
    """Player in a roster."""

    name: str = Field(..., min_length=1)
    position: str = Field(..., pattern=r'^(QB|RB|WR|TE|K|D/ST|HC|OL)$')
    nfl_team: str = Field(..., min_length=2, max_length=3)
    status: str = Field(default='active', pattern=r'^(active|taxi|injured|IR)$')

    class Config:
        extra = 'forbid'


class TeamRoster(BaseModel):
    """Full roster for a fantasy team."""

    team: str = Field(..., min_length=1, max_length=10)
    players: dict[str, list[Player]]

    @field_validator('players')
    @classmethod
    def validate_positions(cls, v):
        """Ensure all positions are valid."""
        valid_positions = {'QB', 'RB', 'WR', 'TE', 'K', 'D/ST', 'HC', 'OL'}
        for pos in v:
            if pos not in valid_positions:
                raise ValueError(f'Invalid position: {pos}')
        return v

    class Config:
        extra = 'forbid'


class RostersFile(BaseModel):
    """Complete rosters.json file structure."""

    rosters: dict[str, TeamRoster]

    class Config:
        extra = 'forbid'


class WeeklyLineup(BaseModel):
    """Weekly lineup submission for a team."""

    team: str = Field(..., min_length=1, max_length=10)
    week: int = Field(..., ge=1, le=17)
    starters: dict[str, list[str]]

    @field_validator('week')
    @classmethod
    def validate_week(cls, v):
        """Ensure week is in valid range."""
        if not (1 <= v <= 17):
            raise ValueError(f'Week must be 1-17, got {v}')
        return v

    @field_validator('starters')
    @classmethod
    def validate_positions(cls, v):
        """Ensure all positions are valid."""
        valid_positions = {'QB', 'RB', 'WR', 'TE', 'K', 'D/ST', 'HC', 'OL'}
        for pos in v:
            if pos not in valid_positions:
                raise ValueError(f'Invalid position: {pos}')
        return v

    class Config:
        extra = 'forbid'


class Transaction(BaseModel):
    """Transaction in the transaction log."""

    type: str = Field(..., pattern=r'^(trade|waiver|free_agent|taxi_activate|taxi_deactivate|IR)$')
    team: str
    timestamp: str
    players_added: list[str] = Field(default_factory=list)
    players_dropped: list[str] = Field(default_factory=list)
    notes: str | None = None

    class Config:
        extra = 'allow'


class Trade(BaseModel):
    """Trade proposal."""

    trade_id: str
    proposing_team: str
    receiving_team: str
    proposing_gives: dict[str, list[str]]
    receiving_gives: dict[str, list[str]]
    status: str = Field(..., pattern=r'^(pending|accepted|rejected|countered)$')
    proposed_at: str
    notes: str | None = None

    @field_validator('proposing_gives', 'receiving_gives')
    @classmethod
    def validate_trade_pieces(cls, v):
        """Ensure trade pieces are categorized correctly."""
        valid_categories = {'players', 'draft_picks'}
        for category in v:
            if category not in valid_categories:
                raise ValueError(f'Invalid trade category: {category}')
        return v

    class Config:
        extra = 'allow'


class PendingTradesFile(BaseModel):
    """Complete pending_trades.json file structure."""

    trades: list[Trade]

    class Config:
        extra = 'forbid'


class DraftPick(BaseModel):
    """Draft pick ownership."""

    year: int = Field(..., ge=2020, le=2030)
    round: int = Field(..., ge=1, le=10)
    original_team: str
    current_owner: str
    pick_number: int | None = Field(None, ge=1, le=120)

    class Config:
        extra = 'forbid'


class DraftPicksFile(BaseModel):
    """Complete draft_picks.json file structure."""

    picks: list[DraftPick]

    class Config:
        extra = 'forbid'


class Team(BaseModel):
    """Team metadata."""

    abbreviation: str = Field(..., min_length=2, max_length=10)
    name: str = Field(..., min_length=1)
    owner: str = Field(..., min_length=1)
    division: str | None = None

    class Config:
        extra = 'forbid'


class TeamsFile(BaseModel):
    """Complete teams.json file structure."""

    teams: list[Team]

    class Config:
        extra = 'forbid'


class LeagueConfig(BaseModel):
    """League configuration settings."""

    current_season: int = Field(..., ge=2020, le=2030)
    trade_deadline_week: int = Field(..., ge=1, le=17)
    roster_slots: dict[str, int]
    starter_slots: dict[str, int]
    taxi_slots: int = Field(..., ge=0, le=10)
    playoff_structure: dict[str, list[int]]
    regular_season_weeks: int = Field(..., ge=1, le=18)
    playoff_weeks: list[int]

    @field_validator('roster_slots', 'starter_slots')
    @classmethod
    def validate_position_slots(cls, v):
        """Ensure all positions have slot counts."""
        valid_positions = {'QB', 'RB', 'WR', 'TE', 'K', 'D/ST', 'HC', 'OL'}
        for pos in v:
            if pos not in valid_positions:
                raise ValueError(f'Invalid position: {pos}')
            if v[pos] < 0 or v[pos] > 10:
                raise ValueError(f'Invalid slot count for {pos}: {v[pos]}')
        return v

    class Config:
        extra = 'forbid'
