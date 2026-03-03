"""
Unit tests for the allow_abstention flag behavior.

Covers:
1. Vote tally logic — majority denominator (abstentions excluded)
2. Vote tally logic — unanimous formula (no_count == 0)
3. Vote validation — _collect_votes() rejects ABSTAIN when flag is false
4. Flag validation — allow_abstention accepts true/false, rejects others
5. format_current_flags() — boolean renders without quotes
"""

from unittest.mock import Mock

import pytest

from src.nomic_engine.core.game_loop import GameLoop
from src.nomic_engine.core.game_manager import GameManager
from src.nomic_engine.data_models import GameState, Vote
from src.nomic_engine.players.base_player import BasePlayer
from src.nomic_engine.utils.flag_schema import (
    clear_schema_cache,
    format_current_flags,
    validate_flag_value,
    validate_state_updates,
)

# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    """Clear the schema cache before and after each test."""
    clear_schema_cache()
    yield  # type: ignore[misc]
    clear_schema_cache()


@pytest.fixture
def mock_game_state() -> GameState:
    """Fixture providing a mock game state with unanimous vote mode."""
    return GameState(
        scores={"Alice": 0, "Bob": 0, "Charlie": 0},
        current_player_name="Alice",
        move_number=1,
        turn_order=["Alice", "Bob", "Charlie"],
        next_proposal_id=301,
        target_score=100,
        flags={"vote_mode": "unanimous", "allow_abstention": False},
    )


@pytest.fixture
def mock_game_manager(mock_game_state: GameState) -> Mock:
    """Fixture providing a mocked GameManager."""
    manager = Mock(spec=GameManager)
    manager.game_state = mock_game_state

    rules_manager = Mock()
    rules_manager.rules = []
    manager.rules_manager = rules_manager

    logger = Mock()
    logger.log_transcript = Mock()
    logger.log_event = Mock()
    manager.logger = logger

    manager.save_game_state = Mock()
    manager.save_rules = Mock()
    manager.game_config = None

    return manager


@pytest.fixture
def game_loop(mock_game_manager: Mock) -> GameLoop:
    """Fixture providing a GameLoop instance with mocks."""
    return GameLoop(game_manager=mock_game_manager, players=[])


# =========================================================================
# 1. Majority — denominator change (abstentions excluded)
# =========================================================================


def test_majority_two_yes_one_abstain_passes(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """2 YES, 1 ABSTAIN: non-abstaining=2, 2 > 1 → passes."""
    mock_game_state.flags = {
        "vote_mode": "majority",
        "allow_abstention": False,
    }

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="ABSTAIN"),
    ]

    result = game_loop._tally_vote_results(votes)
    assert result.passed is True


def test_majority_one_yes_one_no_two_abstain_fails(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """1 YES, 1 NO, 2 ABSTAIN: non-abstaining=2, 1 > 1 → fails (not >)."""
    mock_game_state.flags = {
        "vote_mode": "majority",
        "allow_abstention": False,
    }

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="NO"),
        Vote(player_name="Charlie", vote="ABSTAIN"),
        Vote(player_name="Dave", vote="ABSTAIN"),
    ]

    result = game_loop._tally_vote_results(votes)
    assert result.passed is False


def test_majority_all_abstain_fails(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """All ABSTAIN: non-abstaining=0, 0 > 0 → False."""
    mock_game_state.flags = {
        "vote_mode": "majority",
        "allow_abstention": True,
    }

    votes = [
        Vote(player_name="Alice", vote="ABSTAIN"),
        Vote(player_name="Bob", vote="ABSTAIN"),
        Vote(player_name="Charlie", vote="ABSTAIN"),
    ]

    result = game_loop._tally_vote_results(votes)
    assert result.passed is False


def test_majority_abstention_denominator_flag_true(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Same denominator formula applies when allow_abstention is true."""
    mock_game_state.flags = {
        "vote_mode": "majority",
        "allow_abstention": True,
    }

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="ABSTAIN"),
    ]

    # 2 YES, 0 NO, 1 ABSTAIN → non-abstaining=2, 2 > 1 → passes
    result = game_loop._tally_vote_results(votes)
    assert result.passed is True


# =========================================================================
# 2. Unanimous — tally (no_count == 0 unconditionally)
# =========================================================================


def test_unanimous_all_yes_zero_no_passes(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """All YES, zero NO → passes."""
    mock_game_state.flags = {"vote_mode": "unanimous"}

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="YES"),
    ]

    result = game_loop._tally_vote_results(votes)
    assert result.passed is True


def test_unanimous_any_no_fails(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Any NO present → fails."""
    mock_game_state.flags = {"vote_mode": "unanimous"}

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="NO"),
        Vote(player_name="Charlie", vote="YES"),
    ]

    result = game_loop._tally_vote_results(votes)
    assert result.passed is False


def test_unanimous_yes_and_abstain_zero_no_passes(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Mix of YES and ABSTAIN, zero NO → passes."""
    mock_game_state.flags = {"vote_mode": "unanimous"}

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="ABSTAIN"),
        Vote(player_name="Charlie", vote="YES"),
    ]

    result = game_loop._tally_vote_results(votes)
    assert result.passed is True


def test_unanimous_all_abstain_zero_no_passes(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """All ABSTAIN, zero NO → passes (no_count == 0)."""
    mock_game_state.flags = {"vote_mode": "unanimous"}

    votes = [
        Vote(player_name="Alice", vote="ABSTAIN"),
        Vote(player_name="Bob", vote="ABSTAIN"),
        Vote(player_name="Charlie", vote="ABSTAIN"),
    ]

    result = game_loop._tally_vote_results(votes)
    assert result.passed is True


# =========================================================================
# 3. Vote validation — _collect_votes() rejects ABSTAIN when flag is false
# =========================================================================


def test_collect_votes_rejects_abstain_when_flag_false(
    mock_game_manager: Mock, mock_game_state: GameState
) -> None:
    """Player returns ABSTAIN when allow_abstention=false → ValueError."""
    from src.nomic_engine.data_models import Proposal, ProposalType

    mock_game_state.flags = {
        "vote_mode": "unanimous",
        "allow_abstention": False,
    }

    abstain_player = Mock(spec=BasePlayer)
    abstain_player.player_name = "Alice"
    abstain_player.vote.return_value = Vote(
        player_name="Alice", vote="ABSTAIN", reason="I abstain"
    )

    game_loop = GameLoop(game_manager=mock_game_manager, players=[])

    proposal = Proposal(
        proposer_name="Bob",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Test rule.",
    )

    with pytest.raises(ValueError, match="ABSTAIN"):
        game_loop._collect_votes(proposal, [abstain_player])


def test_collect_votes_allows_abstain_when_flag_true(
    mock_game_manager: Mock, mock_game_state: GameState
) -> None:
    """Player returns ABSTAIN when allow_abstention=true → accepted."""
    from src.nomic_engine.data_models import Proposal, ProposalType

    mock_game_state.flags = {
        "vote_mode": "unanimous",
        "allow_abstention": True,
    }

    abstain_player = Mock(spec=BasePlayer)
    abstain_player.player_name = "Alice"
    abstain_player.vote.return_value = Vote(
        player_name="Alice", vote="ABSTAIN", reason="I abstain"
    )

    game_loop = GameLoop(game_manager=mock_game_manager, players=[])

    proposal = Proposal(
        proposer_name="Bob",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Test rule.",
    )

    votes = game_loop._collect_votes(proposal, [abstain_player])
    assert len(votes) == 1
    assert votes[0].vote == "ABSTAIN"


# =========================================================================
# 4. Flag validation — allow_abstention
# =========================================================================


def test_allow_abstention_true_is_valid() -> None:
    """allow_abstention: true is accepted by validate_flag_value()."""
    validate_flag_value("allow_abstention", True)


def test_allow_abstention_false_is_valid() -> None:
    """allow_abstention: false is accepted by validate_flag_value()."""
    validate_flag_value("allow_abstention", False)


def test_allow_abstention_string_true_rejected() -> None:
    """String 'true' is rejected for allow_abstention (type mismatch)."""
    with pytest.raises(ValueError, match="expects type"):
        validate_flag_value("allow_abstention", "true")


def test_allow_abstention_integer_one_rejected() -> None:
    """Integer 1 is rejected for allow_abstention (type mismatch)."""
    with pytest.raises(ValueError, match="expects type"):
        validate_flag_value("allow_abstention", 1)


def test_allow_abstention_null_rejected() -> None:
    """None is rejected for allow_abstention (nullable=false)."""
    with pytest.raises(ValueError, match="does not allow null"):
        validate_flag_value("allow_abstention", None)


def test_state_updates_accepts_allow_abstention_true() -> None:
    """StateUpdates with allow_abstention=True is valid."""
    validate_state_updates({"flags": {"allow_abstention": True}})


def test_state_updates_accepts_allow_abstention_false() -> None:
    """StateUpdates with allow_abstention=False is valid."""
    validate_state_updates({"flags": {"allow_abstention": False}})


# =========================================================================
# 5. format_current_flags() — boolean renders without quotes
# =========================================================================


def test_format_current_flags_boolean_false_no_quotes() -> None:
    """allow_abstention: false renders as 'false' (no quotes)."""
    result = format_current_flags({"allow_abstention": False})
    assert "- allow_abstention: false" in result
    assert '"' not in result


def test_format_current_flags_boolean_true_no_quotes() -> None:
    """allow_abstention: true renders as 'true' (no quotes)."""
    result = format_current_flags({"allow_abstention": True})
    assert "- allow_abstention: true" in result
    assert '"' not in result


def test_format_current_flags_boolean_not_capitalized() -> None:
    """Boolean values render as lowercase 'true'/'false', not Python style."""
    result_false = format_current_flags({"allow_abstention": False})
    result_true = format_current_flags({"allow_abstention": True})
    assert "False" not in result_false
    assert "True" not in result_true
