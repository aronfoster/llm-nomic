"""
Core Pydantic models to enforce data types and structure for:
- Game configuration (config.yml)
- Game state (game_state.json)
- Rules (rules.jsonl)
- Internal data (Proposal, Vote)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from .judge_contracts import (
    JudgeScoreResponse,
    JudgeVetoResponse,
    StateUpdates,
)

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


class JudgeType(str, Enum):
    """Enum for judge selection."""

    HUMAN = "human"
    LLM = "llm"


class VoteMode(str, Enum):
    """Enum for voting mode settings."""

    UNANIMOUS = "unanimous"
    MAJORITY = "majority"


class WithdrawalPolicy(str, Enum):
    """Enum for withdrawn proposal handling behavior."""

    FORFEIT = "forfeit"
    RETRY = "retry"


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
        default="friendly",
        description=(
            "The strategic persona for this player. Must match the stem "
            "of a file in the personalities/ directory (e.g. 'machiavellian', "
            "'friendly', 'none'). Normalized to lowercase."
        ),
    )


class LLMMemoryConfig(BaseModel):
    """Configuration for LLM memory system."""

    max_characters: Optional[int] = Field(
        default=12000,
        description=(
            "Maximum characters for memory files. " "0 or None = unlimited."
        ),
    )


class LLMLevelConfig(BaseModel):
    """Top-level LLM configuration block."""

    memory: LLMMemoryConfig = Field(
        default_factory=LLMMemoryConfig,
        description="Memory configuration for LLM players.",
    )


class EngineTuningConfig(BaseModel):
    """Engine retry tuning loaded from config.yml."""

    max_propose_retries: int = Field(
        default=2,
        ge=1,
        description="Maximum retries for player proposal generation.",
    )
    max_discuss_retries: int = Field(
        default=2,
        ge=1,
        description="Maximum retries for player discussion generation.",
    )
    max_revise_retries: int = Field(
        default=2,
        ge=1,
        description="Maximum retries for player revision generation.",
    )
    max_vote_retries: int = Field(
        default=2,
        ge=1,
        description="Maximum retries for player vote generation.",
    )
    max_judge_veto_retries: int = Field(
        default=2,
        ge=1,
        description="Maximum retries for judge veto decisions.",
    )
    max_judge_score_retries: int = Field(
        default=2,
        ge=1,
        description="Maximum retries for judge score assessment.",
    )
    max_judge_maintain_state_retries: int = Field(
        default=2,
        ge=1,
        description="Maximum retries for judge state maintenance.",
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
    tuning: EngineTuningConfig = Field(
        default_factory=EngineTuningConfig,
        description="Centralized retry and threshold tuning values.",
    )
    withdrawal_policy: WithdrawalPolicy = Field(
        default=WithdrawalPolicy.RETRY,
        description=(
            "Behavior when the proposer withdraws after discussion: "
            "forfeit turn or retry with cumulative context."
        ),
    )
    # TODO: Should this be in EngineTuningConfig with the others?
    max_withdrawal_retries: int = Field(
        default=2,
        ge=0,
        description=(
            "Maximum number of proposal pivots after withdrawal when "
            "withdrawal_policy is retry."
        ),
    )
    retain_discusser_history_on_retry: bool = Field(
        default=True,
        description=(
            "When True, non-proposing LLM players retain their accumulated "
            "discussion history across withdrawal retries within a single "
            "run_turn execution. This allows them to reason about how and "
            "why the proposal evolved across withdrawal attempts. When False, "
            "each discussion round resets history (identical to pre-flag "
            "behavior)."
        ),
    )
    llm: LLMLevelConfig = Field(
        default_factory=LLMLevelConfig,
        description="LLM-specific configuration (memory, etc.).",
    )

    @model_validator(mode="after")
    def _validate_player_names(self) -> "GameConfig":
        """Validate player names are unique and not reserved."""
        seen: set[str] = set()
        for player in self.players:
            name_lower = player.name.lower()
            if name_lower == "judge":
                raise ValueError(
                    f"Player name '{player.name}' is reserved. "
                    "'Judge' cannot be used as a player name."
                )
            if name_lower in seen:
                raise ValueError(
                    f"Duplicate player name: '{player.name}'. "
                    "Player names must be unique (case-insensitive)."
                )
            seen.add(name_lower)
        return self


# --- Dynamic Game State (for game_state.json) ---


def _get_schema_defaults() -> Dict[str, Any]:
    """Load flag defaults from the schema, with hardcoded fallback."""
    try:
        from .utils.flag_schema import get_flag_defaults

        return get_flag_defaults()
    except Exception as exc:
        logging.warning(
            "Failed to load flag schema defaults; using hardcoded "
            "fallback: %s",
            exc,
        )
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

    This includes veto decisions, score assessments, and state updates,
    returned by _get_judge_decisions.
    """

    veto_response: JudgeVetoResponse = Field(
        ...,
        description="The judge's veto decision response (JudgeVetoResponse)",
    )
    score_response: JudgeScoreResponse = Field(
        ...,
        description=(
            "The judge's score assessment response (JudgeScoreResponse)"
        ),
    )
    judge_approved: bool = Field(
        ..., description="Whether the judge approved (not vetoed)"
    )
    state_updates: StateUpdates = Field(
        ...,
        description=(
            "Engine state changes from maintain_state. Empty dict when "
            "proposal failed, was vetoed, or was a TRANSMUTE."
        ),
    )


# --- LLM API Result and Token Usage Models ---


@dataclass
class CompletionResult:
    """Result of a single LLM API call.

    Carries the completion text, the raw provider response object (for
    metadata extraction), and the measured client-side latency.
    """

    text: str | None
    raw_response: Any
    client_latency_ms: int
    raw_http: Any = None


class TokenUsageRecord(BaseModel):
    """A single structured record of token usage for one LLM API call.

    Written to token_usage.jsonl immediately after each completed call.
    Every field is always present; use null when a value is unavailable.
    """

    timestamp: str = Field(
        description="UTC timestamp in ISO 8601 format, ends with Z."
    )
    move_number: int = Field(
        description="Current game move number at time of call."
    )
    player_name: str = Field(
        description="Player name, or 'Judge' for judge calls."
    )
    provider: str = Field(
        description=(
            "Provider as defined in models.yml "
            "(e.g. 'anthropic', 'openai', 'xai', 'google', 'local')."
        )
    )
    model_id: str = Field(description="Exact api_model_id from models.yml.")
    call_type: str = Field(
        description=(
            "One of: propose, discuss, revise, vote, judge_veto, "
            "judge_score, judge_maintain_state, memory_update."
        )
    )
    input_tokens: int = Field(description="Total billed input tokens.")
    output_tokens: int = Field(description="Billed output tokens.")
    cache_creation_tokens: Optional[int] = Field(
        description=(
            "Provider-specific cache creation tokens; null when not available."
        )
    )
    cache_read_tokens: Optional[int] = Field(
        description=(
            "Provider-specific cache read tokens; null when not available."
        )
    )
    reasoning_tokens: Optional[int] = Field(
        description="OpenAI o-series only; null otherwise."
    )
    finish_reason: Optional[str] = Field(
        description=(
            "Raw provider finish reason value "
            "(e.g. end_turn, stop, length); null when absent."
        )
    )
    client_latency_ms: int = Field(
        description=(
            "Wall-clock milliseconds from request send to response received."
        )
    )
    server_latency_ms: Optional[float] = Field(
        description=(
            "xAI end-to-end latency or Ollama eval_duration; "
            "null for other providers."
        )
    )
    ttft_ms: Optional[float] = Field(
        description="Time to first token in ms; xAI only; null otherwise."
    )
    mean_itl_ms: Optional[float] = Field(
        description=(
            "Mean inter-token latency in ms; xAI only; null otherwise."
        )
    )
    request_id: Optional[str] = Field(
        description="x-request-id response header value; null when absent."
    )
    ratelimit_remaining_requests: Optional[int] = Field(
        description=(
            "x-ratelimit-remaining-requests header value; null when absent."
        )
    )
    ratelimit_remaining_tokens: Optional[int] = Field(
        description=(
            "x-ratelimit-remaining-tokens header value; null when absent."
        )
    )
