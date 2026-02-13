"""
Unit tests for dynamic voting and victory logic in GameLoop.

These tests validate the dynamic voting modes (unanimous/majority) and
victory detection based on the GameState flags and target_score.
"""

from unittest.mock import Mock

import pytest

from src.nomic_engine.core.game_loop import GameLoop
from src.nomic_engine.core.game_manager import GameManager
from src.nomic_engine.data_models import GameState, Rule, RuleStatus, Vote

# --- Fixtures ---


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
        flags={"vote_mode": "unanimous"},
    )


@pytest.fixture
def mock_rules() -> list[Rule]:
    """Fixture providing a mock rules list."""
    return [
        Rule(
            rule_id="101",
            text="All players must follow the rules.",
            status=RuleStatus.IMMUTABLE,
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

    # Mock GameLogger
    logger = Mock()
    logger.log_transcript = Mock()
    logger.log_event = Mock()
    manager.logger = logger

    # Mock save methods
    manager.save_game_state = Mock()
    manager.save_rules = Mock()

    return manager


@pytest.fixture
def game_loop(mock_game_manager: Mock) -> GameLoop:
    """Fixture providing a GameLoop instance with mocks."""
    return GameLoop(game_manager=mock_game_manager, players=[])


# --- Tests for _tally_vote_results with Unanimous Mode ---


def test_tally_vote_results_unanimous_all_yes_passes(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Test unanimous mode: all YES votes should pass."""
    mock_game_state.flags = {"vote_mode": "unanimous"}

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="YES"),
    ]

    result = game_loop._tally_vote_results(votes)
    assert result.passed is True


def test_tally_vote_results_unanimous_one_no_fails(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Test unanimous mode: any NO vote should fail."""
    mock_game_state.flags = {"vote_mode": "unanimous"}

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="NO"),
        Vote(player_name="Charlie", vote="YES"),
    ]

    result = game_loop._tally_vote_results(votes)
    assert result.passed is False


def test_tally_vote_results_unanimous_one_abstain_fails(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Test unanimous mode: any ABSTAIN vote should fail."""
    mock_game_state.flags = {"vote_mode": "unanimous"}

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="ABSTAIN"),
        Vote(player_name="Charlie", vote="YES"),
    ]

    result = game_loop._tally_vote_results(votes)
    assert result.passed is False


def test_tally_vote_results_unanimous_all_no_fails(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Test unanimous mode: all NO votes should fail."""
    mock_game_state.flags = {"vote_mode": "unanimous"}

    votes = [
        Vote(player_name="Alice", vote="NO"),
        Vote(player_name="Bob", vote="NO"),
        Vote(player_name="Charlie", vote="NO"),
    ]

    result = game_loop._tally_vote_results(votes)
    assert result.passed is False


# --- Tests for _tally_vote_results with Majority Mode ---


def test_tally_vote_results_majority_over_50_percent_passes(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Test majority mode: > 50% YES votes should pass."""
    mock_game_state.flags = {"vote_mode": "majority"}

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="NO"),
    ]

    # 2 YES out of 3 total = 66.67% > 50%
    result = game_loop._tally_vote_results(votes)
    assert result.passed is True


def test_tally_vote_results_majority_exactly_50_percent_fails(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Test majority mode: exactly 50% YES votes should fail."""
    mock_game_state.flags = {"vote_mode": "majority"}

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="NO"),
        Vote(player_name="Dave", vote="NO"),
    ]

    # 2 YES out of 4 total = 50% (not > 50%)
    result = game_loop._tally_vote_results(votes)
    assert result.passed is False


def test_tally_vote_results_majority_under_50_percent_fails(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Test majority mode: < 50% YES votes should fail."""
    mock_game_state.flags = {"vote_mode": "majority"}

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="NO"),
        Vote(player_name="Charlie", vote="NO"),
    ]

    # 1 YES out of 3 total = 33.33% < 50%
    result = game_loop._tally_vote_results(votes)
    assert result.passed is False


def test_tally_vote_results_majority_all_yes_passes(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Test majority mode: all YES votes should pass."""
    mock_game_state.flags = {"vote_mode": "majority"}

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="YES"),
    ]

    # 3 YES out of 3 total = 100% > 50%
    result = game_loop._tally_vote_results(votes)
    assert result.passed is True


def test_tally_vote_results_majority_abstentions_count_in_total(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Test majority mode: abstentions count in total vote count."""
    mock_game_state.flags = {"vote_mode": "majority"}

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="ABSTAIN"),
        Vote(player_name="Dave", vote="ABSTAIN"),
    ]

    # 2 YES out of 4 total = 50% (not > 50%)
    result = game_loop._tally_vote_results(votes)
    assert result.passed is False


def test_tally_vote_results_majority_abstentions_still_allows_pass(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Test majority mode: can still pass with abstentions if > 50%."""
    mock_game_state.flags = {"vote_mode": "majority"}

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="YES"),
        Vote(player_name="Dave", vote="ABSTAIN"),
        Vote(player_name="Eve", vote="NO"),
    ]

    # 3 YES out of 5 total = 60% > 50%
    result = game_loop._tally_vote_results(votes)
    assert result.passed is True


# --- Tests for Invalid/Missing vote_mode ---


def test_tally_vote_results_missing_vote_mode_defaults_to_unanimous(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Test missing vote_mode defaults to unanimous."""
    mock_game_state.flags = {}

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="NO"),
    ]

    # Should use unanimous mode (requires all YES)
    result = game_loop._tally_vote_results(votes)
    assert result.passed is False


def test_tally_vote_results_invalid_vote_mode_defaults_to_unanimous(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Test invalid vote_mode string defaults to unanimous."""
    mock_game_state.flags = {"vote_mode": "invalid_mode"}

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="NO"),
    ]

    # Should default to unanimous mode (requires all YES)
    result = game_loop._tally_vote_results(votes)
    assert result.passed is False


def test_tally_vote_results_non_string_vote_mode_defaults_to_unanimous(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Test non-string vote_mode type defaults to unanimous."""
    mock_game_state.flags = {"vote_mode": 123}  # type: ignore

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="NO"),
    ]

    # Should default to unanimous mode (requires all YES)
    result = game_loop._tally_vote_results(votes)
    assert result.passed is False


# --- Tests for Zero Voters Edge Case ---


def test_tally_vote_results_zero_voters_passes(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Test zero voters (empty votes list) automatically passes."""
    mock_game_state.flags = {"vote_mode": "unanimous"}

    votes: list[Vote] = []

    result = game_loop._tally_vote_results(votes)
    assert result.passed is True


def test_tally_vote_results_zero_voters_passes_in_majority_mode(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Test zero voters passes in majority mode too."""
    mock_game_state.flags = {"vote_mode": "majority"}

    votes: list[Vote] = []

    result = game_loop._tally_vote_results(votes)
    assert result.passed is True


# --- Tests for _detect_victory ---


def test_detect_victory_player_reaches_target(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Test victory detection when a player reaches target score."""
    mock_game_state.scores = {"Alice": 100, "Bob": 50, "Charlie": 30}
    mock_game_state.target_score = 100

    victory, winners, score = game_loop._detect_victory()

    assert victory is True
    assert winners == ["Alice"]
    assert score == 100


def test_detect_victory_player_exceeds_target(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Test victory detection when a player exceeds target score."""
    mock_game_state.scores = {"Alice": 150, "Bob": 50, "Charlie": 30}
    mock_game_state.target_score = 100

    victory, winners, score = game_loop._detect_victory()

    assert victory is True
    assert winners == ["Alice"]
    assert score == 150


def test_detect_victory_no_player_reaches_target(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Test no victory when no player reaches target score."""
    mock_game_state.scores = {"Alice": 90, "Bob": 50, "Charlie": 30}
    mock_game_state.target_score = 100

    victory, winners, score = game_loop._detect_victory()

    assert victory is False
    assert winners == []
    assert score == 0


def test_detect_victory_multiple_winners_tie(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Test victory detection with multiple winners (tie)."""
    mock_game_state.scores = {"Alice": 150, "Bob": 150, "Charlie": 120}
    mock_game_state.target_score = 100

    victory, winners, score = game_loop._detect_victory()

    assert victory is True
    assert set(winners) == {"Alice", "Bob"}
    assert score == 150


def test_detect_victory_no_target_score(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Test no victory when target_score is None."""
    mock_game_state.scores = {"Alice": 1000, "Bob": 500, "Charlie": 300}
    mock_game_state.target_score = None

    victory, winners, score = game_loop._detect_victory()

    assert victory is False
    assert winners == []
    assert score == 0


def test_detect_victory_all_players_reach_target_different_scores(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Test victory when players reach target at different scores."""
    mock_game_state.scores = {"Alice": 150, "Bob": 120, "Charlie": 100}
    mock_game_state.target_score = 100

    victory, winners, score = game_loop._detect_victory()

    # Should return only the highest scorer(s)
    assert victory is True
    assert winners == ["Alice"]
    assert score == 150


# --- Integration Tests for Dynamic Voting in _resolve_turn ---


def test_resolve_turn_uses_majority_mode(
    mock_game_manager: Mock, mock_game_state: GameState
) -> None:
    """Test that _resolve_turn respects majority vote mode."""
    from src.nomic_engine.data_models import Discussion, Proposal, ProposalType

    mock_game_state.flags = {"vote_mode": "majority"}

    # Create a mock judge
    judge = Mock()
    judge.get_veto.return_value = {
        "veto": False,
        "reason": None,
        "private_thoughts": None,
    }
    judge.assess_scores.return_value = {
        "private_thoughts": None,
        "score_adjustments": [],
    }
    judge.maintain_state.return_value = {}

    game_loop = GameLoop(mock_game_manager, [], judge)

    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Test rule.",
    )

    # 2 YES out of 3 = 66.67% > 50% (should pass in majority mode)
    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="NO"),
    ]

    discussions: list[Discussion] = []

    game_loop._resolve_turn(proposal, votes, discussions)

    # Verify proposal was applied (passed in majority mode)
    mock_game_manager.rules_manager.apply_proposal.assert_called_once_with(
        proposal
    )
    mock_game_manager.save_rules.assert_called_once()


def test_resolve_turn_majority_mode_fails_at_50_percent(
    mock_game_manager: Mock, mock_game_state: GameState
) -> None:
    """Test that majority mode fails at exactly 50%."""
    from src.nomic_engine.data_models import Discussion, Proposal, ProposalType

    mock_game_state.flags = {"vote_mode": "majority"}

    # Create a mock judge
    judge = Mock()
    judge.assess_scores.return_value = {
        "private_thoughts": None,
        "score_adjustments": [],
    }
    judge.maintain_state.return_value = {}

    # Need 4 players for a clean 50/50 split
    mock_game_state.scores = {"Alice": 0, "Bob": 0, "Charlie": 0, "Dave": 0}
    mock_game_state.turn_order = ["Alice", "Bob", "Charlie", "Dave"]

    game_loop = GameLoop(mock_game_manager, [], judge)

    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Test rule.",
    )

    # 2 YES out of 4 = 50% (should fail, needs > 50%)
    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="NO"),
        Vote(player_name="Dave", vote="NO"),
    ]

    discussions: list[Discussion] = []

    game_loop._resolve_turn(proposal, votes, discussions)

    # Verify proposal was NOT applied (failed in majority mode at 50%)
    mock_game_manager.rules_manager.apply_proposal.assert_not_called()
    mock_game_manager.save_rules.assert_not_called()
