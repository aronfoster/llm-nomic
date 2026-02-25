"""
Unit tests for the private methods extracted from _apply_turn_mutations.

Tests cover:
- _apply_score_changes
- _apply_engine_state_changes
- _apply_rule_changes
- _increment_proposal_counter
"""

from unittest.mock import Mock

import pytest

from src.nomic_engine.core.game_loop import GameLoop
from src.nomic_engine.core.game_manager import GameManager
from src.nomic_engine.data_models import (
    GameState,
    Proposal,
    ProposalType,
    Rule,
    RuleStatus,
    WithdrawalPolicy,
)
from src.nomic_engine.players.base_player import BasePlayer

# ruff: noqa


# --- Fixtures ---


@pytest.fixture
def mock_game_state() -> GameState:
    return GameState(
        scores={"Alice": 10, "Bob": 5, "Charlie": 0},
        current_player_name="Alice",
        move_number=1,
        turn_order=["Alice", "Bob", "Charlie"],
        next_proposal_id=301,
        target_score=100,
    )


@pytest.fixture
def mock_rules() -> list[Rule]:
    return [
        Rule(
            rule_id="101",
            text="All players must follow the rules.",
            status=RuleStatus.IMMUTABLE,
        ),
        Rule(
            rule_id="201",
            text="Players take turns.",
            status=RuleStatus.MUTABLE,
        ),
    ]


@pytest.fixture
def mock_game_manager(
    mock_game_state: GameState, mock_rules: list[Rule]
) -> Mock:
    manager = Mock(spec=GameManager)
    manager.game_state = mock_game_state

    rules_manager = Mock()
    rules_manager.rules = mock_rules
    rules_manager.apply_proposal = Mock()
    manager.rules_manager = rules_manager

    game_logger = Mock()
    game_logger.log_transcript = Mock()
    game_logger.log_event = Mock()
    manager.logger = game_logger

    manager.save_game_state = Mock()
    manager.save_rules = Mock()

    manager.game_config = Mock()
    manager.game_config.withdrawal_policy = WithdrawalPolicy.FORFEIT
    manager.game_config.max_withdrawal_retries = 2

    return manager


@pytest.fixture
def mock_players(
    mock_game_state: GameState, mock_rules: list[Rule]
) -> list[Mock]:
    players = []
    for name in ["Alice", "Bob", "Charlie"]:
        player = Mock(spec=BasePlayer)
        player.player_name = name
        players.append(player)
    return players


@pytest.fixture
def game_loop(mock_game_manager: Mock, mock_players: list[Mock]) -> GameLoop:
    return GameLoop(game_manager=mock_game_manager, players=mock_players)


# --- Tests for _apply_score_changes ---


def test_apply_score_changes_positive_delta(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Score increases by the given positive delta."""
    score_response = {
        "private_thoughts": None,
        "score_adjustments": [
            {"player": "Alice", "delta": 3, "reason": "Great proposal"},
        ],
    }
    game_loop._apply_score_changes(score_response)
    assert mock_game_state.scores["Alice"] == 13


def test_apply_score_changes_negative_delta(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Score decreases by the given negative delta."""
    score_response = {
        "private_thoughts": None,
        "score_adjustments": [
            {"player": "Bob", "delta": -5, "reason": "Poor engagement"},
        ],
    }
    game_loop._apply_score_changes(score_response)
    assert mock_game_state.scores["Bob"] == 0


def test_apply_score_changes_zero_delta(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Zero delta leaves score unchanged."""
    score_response = {
        "private_thoughts": None,
        "score_adjustments": [
            {"player": "Charlie", "delta": 0, "reason": "Neutral"},
        ],
    }
    game_loop._apply_score_changes(score_response)
    assert mock_game_state.scores["Charlie"] == 0


def test_apply_score_changes_multiple_players(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Multiple adjustments are all applied."""
    score_response = {
        "private_thoughts": None,
        "score_adjustments": [
            {"player": "Alice", "delta": 2, "reason": "Proposer bonus"},
            {"player": "Bob", "delta": 1, "reason": "Voter bonus"},
            {"player": "Charlie", "delta": -1, "reason": "Penalty"},
        ],
    }
    game_loop._apply_score_changes(score_response)
    assert mock_game_state.scores["Alice"] == 12
    assert mock_game_state.scores["Bob"] == 6
    assert mock_game_state.scores["Charlie"] == -1


def test_apply_score_changes_empty_adjustments(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Empty score_adjustments list leaves all scores unchanged."""
    original_scores = dict(mock_game_state.scores)
    score_response = {
        "private_thoughts": None,
        "score_adjustments": [],
    }
    game_loop._apply_score_changes(score_response)
    assert mock_game_state.scores == original_scores


# --- Tests for _apply_engine_state_changes ---


def test_apply_engine_state_changes_flag_updated_when_different(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """A flag is written when the new value differs from the current value."""
    mock_game_state.flags = {"vote_mode": "unanimous"}
    state_updates = {"flags": {"vote_mode": "majority"}}
    game_loop._apply_engine_state_changes(state_updates)
    assert mock_game_state.flags["vote_mode"] == "majority"


def test_apply_engine_state_changes_flag_not_written_when_same(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """A flag is not overwritten when the new value equals the current."""
    mock_game_state.flags = {"vote_mode": "unanimous"}
    state_updates = {"flags": {"vote_mode": "unanimous"}}
    game_loop._apply_engine_state_changes(state_updates)
    # Value unchanged — no side effect; just confirm it's still correct
    assert mock_game_state.flags["vote_mode"] == "unanimous"


def test_apply_engine_state_changes_target_score_updated_when_different(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """target_score is written when the new value differs."""
    mock_game_state.target_score = 100
    state_updates = {"target_score": 150}
    game_loop._apply_engine_state_changes(state_updates)
    assert mock_game_state.target_score == 150


def test_apply_engine_state_changes_target_score_not_written_when_same(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """target_score is not overwritten when value equals current."""
    mock_game_state.target_score = 100
    state_updates = {"target_score": 100}
    game_loop._apply_engine_state_changes(state_updates)
    assert mock_game_state.target_score == 100


def test_apply_engine_state_changes_empty_updates(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Empty state_updates leaves flags and target_score unchanged."""
    mock_game_state.flags = {"vote_mode": "unanimous"}
    mock_game_state.target_score = 100
    game_loop._apply_engine_state_changes({})
    assert mock_game_state.flags == {"vote_mode": "unanimous"}
    assert mock_game_state.target_score == 100


def test_apply_engine_state_changes_multiple_flags(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Multiple flag updates are all applied."""
    mock_game_state.flags = {"vote_mode": "unanimous", "allow_veto": True}
    state_updates = {"flags": {"vote_mode": "majority", "allow_veto": False}}
    game_loop._apply_engine_state_changes(state_updates)
    assert mock_game_state.flags["vote_mode"] == "majority"
    assert mock_game_state.flags["allow_veto"] is False


# --- Tests for _apply_rule_changes ---


def test_apply_rule_changes_calls_apply_proposal(
    game_loop: GameLoop, mock_game_manager: Mock
) -> None:
    """apply_proposal is called on rules_manager with the given proposal."""
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        new_text="A brand new rule.",
        rationale="Good idea.",
    )
    game_loop._apply_rule_changes(proposal)
    mock_game_manager.rules_manager.apply_proposal.assert_called_once_with(
        proposal
    )


def test_apply_rule_changes_calls_save_rules(
    game_loop: GameLoop, mock_game_manager: Mock
) -> None:
    """save_rules is called after applying the proposal."""
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        new_text="A brand new rule.",
        rationale="Good idea.",
    )
    game_loop._apply_rule_changes(proposal)
    mock_game_manager.save_rules.assert_called_once()


# --- Tests for _increment_proposal_counter ---


def test_increment_proposal_counter_increments_by_one(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """next_proposal_id is incremented by exactly 1."""
    initial = mock_game_state.next_proposal_id
    game_loop._increment_proposal_counter()
    assert mock_game_state.next_proposal_id == initial + 1


def test_increment_proposal_counter_increments_again(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Calling twice increments by 2 total."""
    initial = mock_game_state.next_proposal_id
    game_loop._increment_proposal_counter()
    game_loop._increment_proposal_counter()
    assert mock_game_state.next_proposal_id == initial + 2
