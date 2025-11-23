"""
Core Pydantic models to enforce data types and structure for:
- Game configuration (config.yml)
- Game state (game_state.json)
- Rules (rules.jsonl)
- Internal data (Proposal, Vote)
"""

from enum import Enum
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

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
    personality: str = Field(
        "machiavellian",
        description="The persona key to use (machiavellian|friendly)",
    )


class GameConfig(BaseModel):
    """The static configuration for a game instance, from config.yml."""

    players: List[PlayerConfig] = Field(
        ..., description="A list of player configurations."
    )


# --- Dynamic Game State (for game_state.json) ---


class GameState(BaseModel):
    """The dynamic state of the game, saved in game_state.json."""

    scores: Dict[str, int] = Field(
        ..., description="Mapping of player name to current score."
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
