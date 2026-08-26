"""Pydantic schemas for the JSON files actually on disk in `data/`.

These models describe the real, flat shapes written by `api/*.py` and read by
`qpfl/json_scorer.py` / `scripts/export_current.py` — not an aspirational
redesign. Keep them in lockstep with the on-disk data; `qpfl/data_validation.py`
is what enforces that in CI and in `score.yml`.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator, model_validator

from qpfl.constants import ALL_TEAMS, POSITION_ORDER
from qpfl.team_names import normalize_team_name_history

VALID_POSITIONS = set(POSITION_ORDER)
VALID_TEAMS = set(ALL_TEAMS)


def _validate_position(v: str) -> str:
    if v not in VALID_POSITIONS:
        raise ValueError(f'Invalid position: {v!r} (expected one of {sorted(VALID_POSITIONS)})')
    return v


def _validate_team(v: str) -> str:
    if v not in VALID_TEAMS:
        raise ValueError(
            f'Invalid team abbreviation: {v!r} (expected one of {sorted(VALID_TEAMS)})'
        )
    return v


# =============================================================================
# data/rosters.json — dict[team_abbrev, list[Player]]
# =============================================================================


class Player(BaseModel):
    """A player on a fantasy roster (active or taxi squad)."""

    name: str = Field(..., min_length=1)
    nfl_team: str = Field(..., min_length=2, max_length=3)
    position: str
    taxi: bool = False

    @field_validator('position')
    @classmethod
    def check_position(cls, v):
        return _validate_position(v)

    model_config = ConfigDict(extra='forbid')


class RostersFile(RootModel[dict[str, list[Player]]]):
    """data/rosters.json: {team_abbrev: [Player, ...]}."""

    @field_validator('root')
    @classmethod
    def check_teams(cls, v):
        for team in v:
            _validate_team(team)
        return v


# =============================================================================
# data/lineups/{season}/week_N.json
# =============================================================================


_LINEUP_META_KEYS = {'submitted_at', 'comment'}


class TeamLineupEntry(RootModel[dict[str, list[str] | str]]):
    """One team's entry in a week file: position -> starters, plus free-text
    `submitted_at`/`comment` metadata keys mixed into the same flat dict."""

    @field_validator('root')
    @classmethod
    def check_entries(cls, v):
        for key, val in v.items():
            if key in _LINEUP_META_KEYS:
                if not isinstance(val, str):
                    raise ValueError(f'{key} must be a string, got {type(val).__name__}')
            else:
                _validate_position(key)
                if not isinstance(val, list):
                    raise ValueError(
                        f'{key} must be a list of starter names, got {type(val).__name__}'
                    )
        return v


class LineupWeekFile(BaseModel):
    """data/lineups/{season}/week_N.json."""

    week: int = Field(..., ge=1, le=18)
    lineups: dict[str, TeamLineupEntry]
    is_playoffs: bool = False
    playoff_round: str | None = None

    @field_validator('lineups')
    @classmethod
    def check_teams(cls, v):
        for team in v:
            _validate_team(team)
        return v

    model_config = ConfigDict(extra='forbid')


# =============================================================================
# data/teams.json
# =============================================================================


class TeamMeta(BaseModel):
    abbrev: str
    name: str = Field(..., min_length=1)
    owner: str = Field(..., min_length=1)
    owner_key: str = Field(..., min_length=1)

    @field_validator('abbrev')
    @classmethod
    def check_abbrev(cls, v):
        return _validate_team(v)

    model_config = ConfigDict(extra='forbid')


class TeamsFile(BaseModel):
    teams: list[TeamMeta]

    model_config = ConfigDict(extra='forbid')


# =============================================================================
# data/pending_trades.json
# =============================================================================


class TradeSide(BaseModel):
    players: list[str] = Field(default_factory=list)
    picks: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra='forbid')


class Trade(BaseModel):
    id: str
    proposer: str
    partner: str
    proposer_gives: TradeSide
    proposer_receives: TradeSide
    status: str = Field(..., pattern=r'^(pending|accepted|rejected|countered|expired|cancelled)$')
    proposed_at: str
    week: int | str

    @field_validator('proposer', 'partner')
    @classmethod
    def check_team(cls, v):
        return _validate_team(v)

    model_config = ConfigDict(extra='allow')  # rejected_at / accepted_at / execution / error


class PendingTradesFile(BaseModel):
    trades: list[Trade]

    model_config = ConfigDict(extra='allow')  # e.g. trade_deadline_week


# =============================================================================
# data/transaction_log.json — heterogeneous entries by `type`
# =============================================================================


class Transaction(BaseModel):
    """One entry in the append-only transaction log.

    Shape varies significantly by `type` (trade / taxi_activation /
    free_agent / team_rename / ...), so only the fields common to every
    entry are required; the rest ride through via extra='allow'.
    """

    type: str = Field(..., min_length=1)
    timestamp: str = Field(..., min_length=1)
    week: int | str | None = None
    season: int | None = None
    operation_id: str | None = None

    model_config = ConfigDict(extra='allow')


class TransactionLogFile(BaseModel):
    transactions: list[Transaction]

    model_config = ConfigDict(extra='forbid')


# =============================================================================
# data/draft_picks.json
# =============================================================================


class DraftPick(BaseModel):
    year: int | str
    round: int = Field(..., ge=1, le=10)
    draft_type: str
    original_team: str
    current_owner: str
    previous_owners: list[str] = Field(default_factory=list)
    condition: str | None = None
    conditional_claim: str | None = None

    @field_validator('original_team', 'current_owner')
    @classmethod
    def check_team(cls, v):
        return _validate_team(v)

    model_config = ConfigDict(extra='forbid')


class DraftPicksFile(BaseModel):
    updated_at: str
    picks: list[DraftPick]

    model_config = ConfigDict(extra='forbid')


# =============================================================================
# data/drafts.json — historical draft results (loosely structured; team/player
# fields carry free-text trade annotations like "Arnav (via Griff/Arnav)")
# =============================================================================


class DraftRoundPick(BaseModel):
    pick: str
    team: str
    player: str

    model_config = ConfigDict(extra='allow')  # dropped, etc.


class DraftRound(BaseModel):
    round: str
    picks: list[DraftRoundPick]

    model_config = ConfigDict(extra='forbid')


class Draft(BaseModel):
    name: str
    year: int | None = None
    type: str
    rounds: list[DraftRound]

    model_config = ConfigDict(extra='allow')


class DraftsFile(BaseModel):
    updated_at: str
    drafts: list[Draft]

    model_config = ConfigDict(extra='forbid')


# =============================================================================
# data/fa_pool.json — top-level list
# =============================================================================


class FAPoolPlayer(BaseModel):
    name: str = Field(..., min_length=1)
    nfl_team: str = Field(..., min_length=2, max_length=3)
    position: str
    available: bool = True

    @field_validator('position')
    @classmethod
    def check_position(cls, v):
        return _validate_position(v)

    model_config = ConfigDict(extra='allow')


class FAPoolFile(RootModel[list[FAPoolPlayer]]):
    pass


# =============================================================================
# data/trade_blocks.json — dict[team, entry]
# =============================================================================


class TradeBlockEntry(BaseModel):
    seeking: list[str] = Field(default_factory=list)
    trading_away: list[str] = Field(default_factory=list)
    players_available: list[str] = Field(default_factory=list)
    notes: str = ''
    updated_at: str | None = None

    model_config = ConfigDict(extra='forbid')


class TradeBlocksFile(RootModel[dict[str, TradeBlockEntry]]):
    @field_validator('root')
    @classmethod
    def check_teams(cls, v):
        for team in v:
            _validate_team(team)
        return v


# =============================================================================
# data/score_adjustments.json — top-level list (docs/ROADMAP_2026.md P2.1)
# =============================================================================


class ScoreAdjustment(BaseModel):
    season: int = Field(..., ge=2020, le=2100)
    week: int = Field(..., ge=1, le=18)
    team: str
    player: str = Field(..., min_length=1)
    points: float
    reason: str = Field(..., min_length=1)

    @field_validator('team')
    @classmethod
    def check_team(cls, v):
        return _validate_team(v)

    model_config = ConfigDict(extra='forbid')


class ScoreAdjustmentsFile(RootModel[list[ScoreAdjustment]]):
    pass


# =============================================================================
# data/rule_proposals.json
# =============================================================================


class RuleComment(BaseModel):
    author: str
    text: str
    timestamp: str

    model_config = ConfigDict(extra='allow')


class RuleProposal(BaseModel):
    id: str
    title: str
    current: str
    nominator: str
    proposed_at: str
    votes: dict[str, str] = Field(default_factory=dict)
    comments: list[RuleComment] = Field(default_factory=list)

    model_config = ConfigDict(extra='allow')


class RuleProposalsFile(BaseModel):
    proposals: list[RuleProposal]

    model_config = ConfigDict(extra='forbid')


# =============================================================================
# data/team_names.json
# =============================================================================


class TeamNameEntry(BaseModel):
    season: int = Field(..., ge=2020, le=2100)
    effective_week: int = Field(..., ge=0, le=17)
    name: str = Field(..., min_length=1, max_length=50)

    @field_validator('name')
    @classmethod
    def check_name(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('team name cannot be blank')
        if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
            raise ValueError('team name cannot contain control characters')
        return value

    model_config = ConfigDict(extra='forbid')


class TeamNamesFile(BaseModel):
    team_names: dict[str, list[TeamNameEntry]] = Field(default_factory=dict)

    @field_validator('team_names', mode='before')
    @classmethod
    def normalize_legacy_entries(cls, value):
        return normalize_team_name_history(value)

    @field_validator('team_names')
    @classmethod
    def check_teams(cls, value):
        for team in value:
            _validate_team(team)
        return value

    model_config = ConfigDict(extra='forbid')


# =============================================================================
# data/avatars.json — dict[team, list[entry]]
# =============================================================================


class AvatarEntry(BaseModel):
    season: int
    week: int
    file: str

    model_config = ConfigDict(extra='forbid')


class AvatarsFile(RootModel[dict[str, list[AvatarEntry]]]):
    @field_validator('root')
    @classmethod
    def check_teams(cls, v):
        for team in v:
            _validate_team(team)
        return v


# =============================================================================
# data/draft_orders.json — dict[year, dict[draft_type, [team, ...]]]
# =============================================================================


class DraftOrdersFile(RootModel[dict[str, dict[str, list[str]]]]):
    @field_validator('root')
    @classmethod
    def check_teams(cls, v):
        for orders_by_type in v.values():
            for order in orders_by_type.values():
                for team in order:
                    _validate_team(team)
        return v


# =============================================================================
# data/name_battles.json
# =============================================================================


class NameBattleCombatant(BaseModel):
    abbrev: str
    win: str
    lose: str

    @field_validator('abbrev')
    @classmethod
    def check_abbrev(cls, v):
        return _validate_team(v)

    model_config = ConfigDict(extra='forbid')


class NameBattle(BaseModel):
    id: str
    name: str
    affects_first_name: bool
    combatants: list[NameBattleCombatant]

    model_config = ConfigDict(extra='forbid')


class NameBattlesFile(BaseModel):
    battles: list[NameBattle]

    model_config = ConfigDict(extra='forbid')


# =============================================================================
# data/league_config.json
# =============================================================================


class LeagueConfig(BaseModel):
    current_season: int = Field(..., ge=2020, le=2100)
    is_offseason: bool = Field(..., strict=True)
    trade_deadline_week: int = Field(..., ge=1, le=18)
    roster_slots: dict[str, int]
    starter_slots: dict[str, int]
    taxi_slots: int = Field(..., ge=0, le=10)
    playoff_structure: dict[str, list[int]]
    regular_season_weeks: int = Field(..., ge=1, le=18)
    playoff_weeks: list[int]

    @field_validator('roster_slots', 'starter_slots')
    @classmethod
    def validate_position_slots(cls, v):
        for pos, count in v.items():
            _validate_position(pos)
            if not (0 <= count <= 10):
                raise ValueError(f'Invalid slot count for {pos}: {count}')
        return v

    model_config = ConfigDict(extra='forbid')


class NflDraftChallengeScoring(BaseModel):
    graduated_through_pick: int = Field(..., ge=0, le=256)
    flat_points_after: int = Field(..., ge=0)

    model_config = ConfigDict(extra='forbid')


class NflDraftChallengeConfig(BaseModel):
    year: int = Field(..., ge=2020, le=2100)
    enabled: bool
    title: str = Field(..., min_length=1, max_length=100)
    lock_time: str | None
    pick_count: int = Field(..., ge=1, le=256)
    max_player_name_length: int = Field(..., ge=1, le=200)
    scoring: NflDraftChallengeScoring
    prospect_source: str | None = Field(default=None, max_length=200)
    prospects: list[str]

    @field_validator('lock_time')
    @classmethod
    def validate_lock_time(cls, value):
        if value is None:
            return value
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except (AttributeError, ValueError) as exc:
            raise ValueError('lock_time must be an ISO-8601 timestamp') from exc
        if parsed.tzinfo is None:
            raise ValueError('lock_time must include a timezone')
        return value

    @model_validator(mode='after')
    def validate_enabled_config(self):
        if self.scoring.graduated_through_pick > self.pick_count:
            raise ValueError('graduated_through_pick cannot exceed pick_count')
        if self.enabled and not self.lock_time:
            raise ValueError('enabled challenge requires lock_time')
        if any(
            not name.strip() or len(name) > self.max_player_name_length for name in self.prospects
        ):
            raise ValueError('prospect names must be non-empty and within max_player_name_length')
        return self

    model_config = ConfigDict(extra='forbid')


class NflDraftChallengePick(BaseModel):
    pick: int = Field(..., ge=1, le=256)
    player: str = Field(..., max_length=200)

    model_config = ConfigDict(extra='forbid')


class NflDraftChallengeSubmission(BaseModel):
    picks: list[NflDraftChallengePick]
    submitted_at: str

    model_config = ConfigDict(extra='forbid')


class NflDraftChallengeState(BaseModel):
    year: int = Field(..., ge=2020, le=2100)
    actual_picks: list[NflDraftChallengePick]
    picks_by_team: dict[str, NflDraftChallengeSubmission]
    updated_at: str | None

    model_config = ConfigDict(extra='forbid')
