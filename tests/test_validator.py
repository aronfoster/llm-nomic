"""
Unit tests for the validation package.

These tests validate the proposal legality checking logic in isolation.
"""

from unittest.mock import Mock

import pytest

from src.nomic_engine.data_models import (
    Proposal,
    ProposalType,
    Rule,
    RuleStatus,
)
from src.nomic_engine.game_manager import GameManager
from src.nomic_engine.validation.validator import validate_proposal


@pytest.fixture
def mock_rules() -> list[Rule]:
    """Fixture providing a mock rules list."""
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
def mock_game_manager(mock_rules: list[Rule]) -> Mock:
    """Fixture providing a mocked GameManager."""
    manager = Mock(spec=GameManager)

    # Mock game_state (not None)
    manager.game_state = Mock()
    manager.game_state.next_proposal_id = 301

    # Mock RulesManager
    rules_manager = Mock()
    rules_manager.rules = mock_rules
    rules_manager.apply_proposal = Mock()
    manager.rules_manager = rules_manager

    return manager


def test_validate_proposal_valid_add(
    mock_game_manager: Mock,
) -> None:
    """Test validate_proposal with a valid ADD proposal."""
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="New rule text.",
        rationale="This is a good idea.",
    )

    is_valid, error_message = validate_proposal(
        proposal, "Alice", mock_game_manager
    )

    assert is_valid is True
    assert error_message == ""


def test_validate_proposal_invalid_amend_immutable(
    mock_game_manager: Mock,
) -> None:
    """Test validate_proposal rejects proposal to amend immutable rule."""
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.AMEND,
        proposal_id="301",
        target_rule_id="101",  # Immutable rule
        new_text="Trying to change immutable rule.",
    )

    is_valid, error_message = validate_proposal(
        proposal, "Alice", mock_game_manager
    )

    assert is_valid is False
    assert "immutable" in error_message.lower()


def test_validate_proposal_mismatched_proposer_name(
    mock_game_manager: Mock,
) -> None:
    """Test validate_proposal rejects mismatched proposer_name."""
    proposal = Proposal(
        proposer_name="Bob",  # Alice trying to impersonate Bob
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Malicious proposal.",
        rationale="Trying to frame another player.",
    )

    is_valid, error_message = validate_proposal(
        proposal, "Alice", mock_game_manager
    )

    assert is_valid is False
    assert "Alice" in error_message
    assert "Bob" in error_message
    assert "illegal proposal" in error_message.lower()


def test_validate_proposal_valid_amend_mutable(
    mock_game_manager: Mock,
) -> None:
    """Test validate_proposal with a valid AMEND proposal on mutable rule."""
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.AMEND,
        proposal_id="301",
        target_rule_id="201",  # Mutable rule
        new_text="Updated rule text.",
    )

    is_valid, error_message = validate_proposal(
        proposal, "Alice", mock_game_manager
    )

    assert is_valid is True
    assert error_message == ""


def test_validate_proposal_invalid_repeal_immutable(
    mock_game_manager: Mock,
) -> None:
    """Test validate_proposal rejects proposal to repeal immutable rule."""
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.REPEAL,
        proposal_id="301",
        target_rule_id="101",  # Immutable rule
    )

    is_valid, error_message = validate_proposal(
        proposal, "Alice", mock_game_manager
    )

    assert is_valid is False
    assert "immutable" in error_message.lower()


def test_validate_proposal_does_not_modify_real_rules(
    mock_game_manager: Mock,
) -> None:
    """Test validate_proposal never modifies the real rules_manager.

    This is a critical test to ensure validation is side-effect-free.
    """
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="New rule text.",
    )

    # Get the original rules reference
    original_rules = mock_game_manager.rules_manager.rules

    validate_proposal(proposal, "Alice", mock_game_manager)

    # CRITICAL: The real rules_manager.apply_proposal should NEVER be called
    # Validation happens on a temporary RulesManager instead
    mock_game_manager.rules_manager.apply_proposal.assert_not_called()

    # Verify the rules list reference was never changed
    assert mock_game_manager.rules_manager.rules is original_rules
