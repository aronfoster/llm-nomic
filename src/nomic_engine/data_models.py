"""
Core Pydantic models to enforce data types and structure for:
- Game configuration (config.yml)
- Game state (game_state.json)
- Rules (rules.jsonl)
- Internal data (Proposal, Vote)
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

# --- Enums ---


class RuleStatus(str, Enum):
    """Enum for rule status values."""

    IMMUTABLE = "immutable"
    MUTABLE = "mutable"


class ProposalType(str, Enum):
    """Enum for proposal type values."""

    ADD = "Add"
    AMEND = "Amend"
    REPEAL = "Repeal"
    TRANSMUTE = "Transmute"


class PlayerPersonality(str, Enum):
    """Enum for player personality/persona values."""

    MACHIAVELLIAN = "machiavellian"
    FRIENDLY = "friendly"
    NONE = "none"
    # Add others here later (e.g. CHAOTIC)


class JudgeType(str, Enum):
    """Enum for judge selection."""

    HUMAN = "human"
    LLM = "llm"


class VoteMode(str, Enum):
    """Enum for voting mode settings."""

    UNANIMOUS = "unanimous"
    MAJORITY = "majority"


# --- Rule Data Model (for rules.jsonl) ---


class Rule(BaseModel):
    """A single rule, stored in rules.jsonl."""

    rule_id: str = Field(
        ..., description="The unique ID, e.g., '101' or '301'"
    )
    text: str = Field(..., description="The full text of the rule.")
    status: RuleStatus = Field(..., description="The status of the rule.")


# --- Game Instance Configuration (for config.yml) ---


class PlayerConfig(BaseModel):
    """Configuration for a single player, loaded from config.yml."""

    name: str = Field(
        ..., description="The player's unique name (e.g., 'Claude')."
    )
    model_id: str = Field(
        ...,
        description=(
            "The API model ID (e.g., 'claude-3-5-sonnet-20240620') "
            "or 'human'."
        ),
    )
    personality: PlayerPersonality = Field(
        default=PlayerPersonality.FRIENDLY,
        description="The strategic persona for this player.",
    )


class GameConfig(BaseModel):
    """The static configuration for a game instance, from config.yml."""

    players: List[PlayerConfig] = Field(
        ..., description="A list of player configurations."
    )
    target_score: Optional[int] = Field(
        default=None,
        description=(
            "Score required to win the game. When omitted, the game has no "
            "automatic end condition."
        ),
    )
    judge_type: JudgeType = Field(
        default=JudgeType.HUMAN, description="Who will act as the judge."
    )
    judge_model: Optional[ModelDefinition] = Field(
        default=None,
        description=(
            "LLM model definition to use when the judge is model-powered. "
            "Required if judge_type is 'llm'."
        ),
    )


# --- Dynamic Game State (for game_state.json) ---


def _get_schema_defaults() -> Dict[str, Any]:
    """Load flag defaults from the schema, with hardcoded fallback."""
    try:
        from .utils.flag_schema import get_flag_defaults

        return get_flag_defaults()
    except Exception:
        return {"vote_mode": "unanimous"}


class GameState(BaseModel):
    """The dynamic state of the game, saved in game_state.json."""

    scores: Dict[str, int] = Field(
        ..., description="Mapping of player name to current score."
    )
    target_score: Optional[int] = Field(
        default=None, description="Score required to win the game."
    )
    flags: Dict[str, Any] = Field(
        default_factory=lambda: _get_schema_defaults(),
        description="Rules-driven engine toggles.",
    )
    current_player_name: str = Field(
        ..., description="The name of the player whose turn it is."
    )
    move_number: int = Field(
        ..., description="The number for the current move (e.g., 'MOVE #n')."
    )
    turn_order: List[str] = Field(
        ..., description="List of player names in order of play."
    )
    next_proposal_id: int = Field(
        ...,
        description=(
            "The next sequential proposal ID to assign (starts at 301)."
        ),
    )

    @model_validator(mode="after")
    def _validate_flags(self) -> "GameState":
        """Validate flag values against the flag schema."""
        from .utils.flag_schema import FlagSchemaError, validate_flags

        try:
            validate_flags(self.flags)
        except FlagSchemaError:
            # Schema unavailable — skip validation gracefully
            pass
        return self


# --- Internal Data Models (for game logic) ---


class Proposal(BaseModel):
    """Represents a player's proposed rule change."""

    proposer_name: str
    move_number: int
    type: ProposalType
    proposal_id: Optional[str] = Field(
        None,
        description="The sequential ID (e.g., '301') assigned by the engine.",
    )
    target_rule_id: Optional[str] = Field(
        None,
        description=(
            "The rule_id to be affected (for Amend/Repeal/Transmute). "
            "None for 'Add'."
        ),
    )
    new_text: Optional[str] = Field(
        None, description="The new text for 'Add' or 'Amend'."
    )
    rationale: Optional[str] = Field(
        None, description="The player's justification."
    )
    private_thoughts: Optional[str] = Field(
        None,
        description="The LLM's private reasoning (for transcript logging).",
    )


class Discussion(BaseModel):
    """Represents a player's discussion comment on a proposal."""

    player_name: str
    text: str
    private_thoughts: Optional[str] = None


class Vote(BaseModel):
    """Represents a single player's vote on a proposal."""

    player_name: str
    vote: Literal["YES", "NO", "ABSTAIN"]
    reason: Optional[str] = None
    private_thoughts: Optional[str] = None


# --- Root Model Library (for models.yml) ---


class ModelDefinition(BaseModel):
    """Defines a single available LLM."""

    id: str = Field(
        ...,
        description=(
            "The unique friendly ID for this engine "
            "(e.g., 'claude-3-5-sonnet')."
        ),
    )
    provider: str = Field(
        ..., description="The provider (e.g., 'anthropic', 'openai', 'local')."
    )
    api_model_id: str = Field(
        ..., description="The actual model ID used by the API."
    )
    env_key_name: Optional[str] = Field(
        None,
        description="The name of the environment variable for the API key.",
    )


class ModelLibrary(BaseModel):
    """The root object for models.yml."""

    models: List[ModelDefinition]


# --- LLM API Data Models ---


# TODO: Explain user is for game and other players text,
# whereas assistant is this player
class ChatMessage(BaseModel):
    """A single message in a chat completion request."""

    role: Literal["system", "user", "assistant"]
    content: str


# --- Turn Resolution Data Models ---


class VoteResult(BaseModel):
    """
    Encapsulates the outcome of vote tallying.

    This is a pure data object returned by _tally_vote_results,
    containing vote counts and the final pass/fail status.
    """

    yes_count: int = Field(..., description="Number of YES votes")
    no_count: int = Field(..., description="Number of NO votes")
    abstain_count: int = Field(..., description="Number of ABSTAIN votes")
    total_voters: int = Field(..., description="Total number of voters")
    passed: bool = Field(
        ..., description="Whether the proposal passed the vote"
    )
    vote_mode: str = Field(
        ..., description="The voting mode used (unanimous or majority)"
    )


class JudgeDecisions(BaseModel):
    """
    Consolidates all interpretive data from the Judge.

    This includes veto decisions and score assessments,
    returned by _get_judge_decisions.
    """

    veto_response: Any = Field(
        ...,
        description="The judge's veto decision response (JudgeVetoResponse)",
    )
    score_response: Any = Field(
        ...,
        description=(
            "The judge's score assessment response (JudgeScoreResponse)"
        ),
    )
    judge_approved: bool = Field(
        ..., description="Whether the judge approved (not vetoed)"
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)
