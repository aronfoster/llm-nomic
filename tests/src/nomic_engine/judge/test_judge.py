"""
Unit tests for the judge package.

These tests validate the human judge interaction logic in isolation.
"""

from unittest.mock import Mock, patch

import pytest

from src.nomic_engine.core.game_manager import GameManager
from src.nomic_engine.data_models import (
    Discussion,
    GameState,
    Proposal,
    ProposalType,
    Rule,
    RuleStatus,
    Vote,
)
from src.nomic_engine.judge.human_judge import HumanJudge
from src.nomic_engine.players.base_player import BasePlayer


@pytest.fixture
def mock_game_state() -> GameState:
    """Fixture providing a mock game state."""
    return GameState(
        scores={"Alice": 0, "Bob": 0, "Charlie": 0},
        current_player_name="Alice",
        move_number=1,
        turn_order=["Alice", "Bob", "Charlie"],
        next_proposal_id=301,
    )


@pytest.fixture
def mock_rules() -> list[Rule]:
    """Fixture providing a mock rules list with point-related rules."""
    return [
        Rule(
            rule_id="101",
            text="All players must follow the rules.",
            status=RuleStatus.IMMUTABLE,
        ),
        Rule(
            rule_id="201",
            text="A player who makes a good proposal gets 10 points.",
            status=RuleStatus.MUTABLE,
        ),
        Rule(
            rule_id="202",
            text="A player who makes a bad proposal loses 5 points.",
            status=RuleStatus.MUTABLE,
        ),
    ]


@pytest.fixture
def mock_game_manager(
    mock_game_state: GameState, mock_rules: list[Rule]
) -> Mock:
    """Fixture providing a mocked GameManager."""
    manager = Mock(spec=GameManager)
    manager.game_state = mock_game_state

    # Mock RulesManager
    rules_manager = Mock()
    rules_manager.rules = mock_rules
    manager.rules_manager = rules_manager

    return manager


@pytest.fixture
def mock_players() -> list[Mock]:
    """Fixture providing mocked player objects."""
    players = []
    for name in ["Alice", "Bob", "Charlie"]:
        player = Mock(spec=BasePlayer)
        player.player_name = name
        players.append(player)
    return players


@pytest.fixture
def mock_proposal(mock_game_state: GameState) -> Proposal:
    """Fixture providing a minimal proposal for judge context."""

    return Proposal(
        proposer_name="Alice",
        move_number=mock_game_state.move_number,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Test rule text",
        rationale="Testing proposal",
    )


@pytest.fixture
def mock_votes() -> list[Vote]:
    """Fixture providing placeholder votes."""

    return [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="NO"),
    ]


@pytest.fixture
def mock_discussions() -> list[Discussion]:
    """Fixture providing placeholder discussions."""

    return [
        Discussion(player_name="Alice", text="I support this."),
        Discussion(player_name="Bob", text="I oppose this."),
    ]


# --- Tests for get_veto ---


@patch("builtins.input", return_value="y")
def test_get_veto_returns_true_when_y(
    mock_input: Mock,
    mock_game_manager: Mock,
    mock_proposal: Proposal,
    mock_votes: list[Vote],
    mock_discussions: list[Discussion],
) -> None:
    """Test get_veto returns True when judge responds 'y'."""
    judge = HumanJudge()
    result = judge.get_veto(
        mock_game_manager, mock_proposal, mock_votes, mock_discussions
    )

    assert result["veto"] is True
    mock_input.assert_called_once()


@patch("builtins.input", return_value="Y")
def test_get_veto_returns_true_when_uppercase_y(
    mock_input: Mock,
    mock_game_manager: Mock,
    mock_proposal: Proposal,
    mock_votes: list[Vote],
    mock_discussions: list[Discussion],
) -> None:
    """Test get_veto returns True when judge responds 'Y'."""
    judge = HumanJudge()
    result = judge.get_veto(
        mock_game_manager, mock_proposal, mock_votes, mock_discussions
    )

    assert result["veto"] is True
    mock_input.assert_called_once()


@patch("builtins.input", return_value="n")
def test_get_veto_returns_false_when_n(
    mock_input: Mock,
    mock_game_manager: Mock,
    mock_proposal: Proposal,
    mock_votes: list[Vote],
    mock_discussions: list[Discussion],
) -> None:
    """Test get_veto returns False when judge responds 'n'."""
    judge = HumanJudge()
    result = judge.get_veto(
        mock_game_manager, mock_proposal, mock_votes, mock_discussions
    )

    assert result["veto"] is False
    mock_input.assert_called_once()


@patch("builtins.input", return_value="N")
def test_get_veto_returns_false_when_uppercase_n(
    mock_input: Mock,
    mock_game_manager: Mock,
    mock_proposal: Proposal,
    mock_votes: list[Vote],
    mock_discussions: list[Discussion],
) -> None:
    """Test get_veto returns False when judge responds 'N'."""
    judge = HumanJudge()
    result = judge.get_veto(
        mock_game_manager, mock_proposal, mock_votes, mock_discussions
    )

    assert result["veto"] is False
    mock_input.assert_called_once()


@patch("builtins.input", return_value="yes")
def test_get_veto_returns_false_when_not_y(
    mock_input: Mock,
    mock_game_manager: Mock,
    mock_proposal: Proposal,
    mock_votes: list[Vote],
    mock_discussions: list[Discussion],
) -> None:
    """Test get_veto returns False for any response other than 'y'."""
    judge = HumanJudge()
    result = judge.get_veto(
        mock_game_manager, mock_proposal, mock_votes, mock_discussions
    )

    assert result["veto"] is False
    mock_input.assert_called_once()


@patch("builtins.input", return_value="  y  ")
def test_get_veto_strips_whitespace(
    mock_input: Mock,
    mock_game_manager: Mock,
    mock_proposal: Proposal,
    mock_votes: list[Vote],
    mock_discussions: list[Discussion],
) -> None:
    """Test get_veto strips whitespace from input."""
    judge = HumanJudge()
    result = judge.get_veto(
        mock_game_manager, mock_proposal, mock_votes, mock_discussions
    )

    assert result["veto"] is True
    mock_input.assert_called_once()


# --- Tests for get_scores_from_judge ---


@patch("builtins.input", side_effect=["10", "5", "-2"])
def test_get_scores_from_judge_applies_score_changes(
    mock_input: Mock,
    mock_game_manager: Mock,
    mock_players: list[Mock],
    mock_game_state: GameState,
    mock_proposal: Proposal,
    mock_votes: list[Vote],
    mock_discussions: list[Discussion],
) -> None:
    """Test get_scores_from_judge applies score changes correctly."""
    judge = HumanJudge()
    judge.assess_scores(
        mock_game_manager,
        mock_players,
        mock_proposal,
        mock_votes,
        mock_discussions,
    )

    # Verify scores were updated
    assert mock_game_state.scores["Alice"] == 10
    assert mock_game_state.scores["Bob"] == 5
    assert mock_game_state.scores["Charlie"] == -2

    # Verify input was called 3 times (once per player)
    assert mock_input.call_count == 3


@patch("builtins.input", side_effect=["0", "0", "0"])
def test_get_scores_from_judge_handles_zero_scores(
    mock_input: Mock,
    mock_game_manager: Mock,
    mock_players: list[Mock],
    mock_game_state: GameState,
    mock_proposal: Proposal,
    mock_votes: list[Vote],
    mock_discussions: list[Discussion],
) -> None:
    """Test get_scores_from_judge handles zero score changes."""
    judge = HumanJudge()
    judge.assess_scores(
        mock_game_manager,
        mock_players,
        mock_proposal,
        mock_votes,
        mock_discussions,
    )

    # Verify scores remain unchanged (all zeros)
    assert mock_game_state.scores["Alice"] == 0
    assert mock_game_state.scores["Bob"] == 0
    assert mock_game_state.scores["Charlie"] == 0

    assert mock_input.call_count == 3


@patch("builtins.input", side_effect=["abc", "10", "5", "-2"])
def test_get_scores_from_judge_retries_on_invalid_input(
    mock_input: Mock,
    mock_game_manager: Mock,
    mock_players: list[Mock],
    mock_game_state: GameState,
    mock_proposal: Proposal,
    mock_votes: list[Vote],
    mock_discussions: list[Discussion],
) -> None:
    """Test get_scores_from_judge retries on non-integer input."""
    judge = HumanJudge()
    judge.assess_scores(
        mock_game_manager,
        mock_players,
        mock_proposal,
        mock_votes,
        mock_discussions,
    )

    # Verify scores were updated (first invalid input was retried)
    assert mock_game_state.scores["Alice"] == 10
    assert mock_game_state.scores["Bob"] == 5
    assert mock_game_state.scores["Charlie"] == -2

    # Verify input was called 4 times (1 invalid + 3 valid)
    assert mock_input.call_count == 4


@patch("builtins.input", side_effect=["-10", "3", "3"])
def test_get_scores_from_judge_handles_negative_scores(
    mock_input: Mock,
    mock_game_manager: Mock,
    mock_players: list[Mock],
    mock_game_state: GameState,
    mock_proposal: Proposal,
    mock_votes: list[Vote],
    mock_discussions: list[Discussion],
) -> None:
    """Test get_scores_from_judge handles negative scores."""
    judge = HumanJudge()
    judge.assess_scores(
        mock_game_manager,
        mock_players,
        mock_proposal,
        mock_votes,
        mock_discussions,
    )

    # Verify scores were updated with negative values
    assert mock_game_state.scores["Alice"] == -10
    assert mock_game_state.scores["Bob"] == 3
    assert mock_game_state.scores["Charlie"] == 3

    assert mock_input.call_count == 3


@patch("builtins.input", side_effect=["5", "5", "5"])
def test_get_scores_from_judge_accumulates_scores(
    mock_input: Mock,
    mock_game_manager: Mock,
    mock_players: list[Mock],
    mock_game_state: GameState,
    mock_proposal: Proposal,
    mock_votes: list[Vote],
    mock_discussions: list[Discussion],
) -> None:
    """Test get_scores_from_judge accumulates scores across multiple calls."""
    # Set initial scores
    mock_game_state.scores["Alice"] = 10
    mock_game_state.scores["Bob"] = -5
    mock_game_state.scores["Charlie"] = 0

    judge = HumanJudge()
    judge.assess_scores(
        mock_game_manager,
        mock_players,
        mock_proposal,
        mock_votes,
        mock_discussions,
    )

    # Verify scores were accumulated (added to existing scores)
    assert mock_game_state.scores["Alice"] == 15  # 10 + 5
    assert mock_game_state.scores["Bob"] == 0  # -5 + 5
    assert mock_game_state.scores["Charlie"] == 5  # 0 + 5

    assert mock_input.call_count == 3


@patch("builtins.input", side_effect=["100", "-50", "25"])
def test_get_scores_from_judge_handles_large_score_changes(
    mock_input: Mock,
    mock_game_manager: Mock,
    mock_players: list[Mock],
    mock_game_state: GameState,
    mock_proposal: Proposal,
    mock_votes: list[Vote],
    mock_discussions: list[Discussion],
) -> None:
    """Test get_scores_from_judge handles large score changes."""
    judge = HumanJudge()
    judge.assess_scores(
        mock_game_manager,
        mock_players,
        mock_proposal,
        mock_votes,
        mock_discussions,
    )

    assert mock_game_state.scores["Alice"] == 100
    assert mock_game_state.scores["Bob"] == -50
    assert mock_game_state.scores["Charlie"] == 25

    assert mock_input.call_count == 3
