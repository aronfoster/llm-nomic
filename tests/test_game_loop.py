"""
Comprehensive integration tests for the GameLoop class.

These tests validate the complete turn orchestration logic, including:
- All 5 steps executed in correct order
- Proposal validation
- Score calculations
- State persistence
- Human judge interaction
"""

from unittest.mock import Mock, patch

import pytest

from src.nomic_engine.data_models import (
    GameState,
    Proposal,
    ProposalType,
    Rule,
    RuleStatus,
    Vote,
)
from src.nomic_engine.game_loop import GameLoop
from src.nomic_engine.game_manager import GameManager
from src.nomic_engine.players.base_player import BasePlayer

# --- Fixtures ---


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
def mock_game_manager(
    mock_game_state: GameState, mock_rules: list[Rule]
) -> Mock:
    """Fixture providing a mocked GameManager."""
    manager = Mock(spec=GameManager)
    manager.game_state = mock_game_state

    # Mock RulesManager
    rules_manager = Mock()
    rules_manager.rules = mock_rules
    rules_manager.apply_proposal = Mock()
    manager.rules_manager = rules_manager

    # Mock GameLogger
    logger = Mock()
    logger.log_transcript = Mock()
    manager.logger = logger

    # Mock save methods
    manager.save_game_state = Mock()
    manager.save_rules = Mock()

    return manager


@pytest.fixture
def mock_players(
    mock_game_state: GameState, mock_rules: list[Rule]
) -> list[Mock]:
    """Fixture providing mocked player objects."""
    players = []

    for name in ["Alice", "Bob", "Charlie"]:
        player = Mock(spec=BasePlayer)
        player.player_name = name

        # Default proposal (Alice proposes to add a rule)
        player.propose = Mock(
            return_value=Proposal(
                proposer_name=name,
                move_number=1,
                type=ProposalType.ADD,
                new_text="New rule text.",
                rationale="This is a good idea.",
            )
        )

        # Default discussion (return some text)
        player.discuss = Mock(return_value=f"{name}'s discussion")

        # Default vote (YES)
        player.vote = Mock(
            return_value=Vote(
                player_name=name,
                vote="YES",
                reason=f"{name} approves",
            )
        )

        players.append(player)

    return players


@pytest.fixture
def game_loop(mock_game_manager: Mock, mock_players: list[Mock]) -> GameLoop:
    """Fixture providing a GameLoop instance with mocks."""
    return GameLoop(game_manager=mock_game_manager, players=mock_players)


# --- Tests for Helper Methods ---


def test_get_current_player_success(game_loop: GameLoop) -> None:
    """Test _get_current_player returns the correct player."""
    current_player = game_loop._get_current_player()

    assert current_player.player_name == "Alice"


def test_get_current_player_not_found(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """Test _get_current_player raises ValueError if player not found."""
    # Set current player to someone not in the players list
    mock_game_state.current_player_name = "NonExistent"

    with pytest.raises(
        ValueError, match="Current player 'NonExistent' not found"
    ):
        game_loop._get_current_player()


def test_get_other_players(game_loop: GameLoop) -> None:
    """Test _get_other_players returns all players except current."""
    other_players = game_loop._get_other_players()

    assert len(other_players) == 2
    assert all(p.player_name != "Alice" for p in other_players)
    assert {p.player_name for p in other_players} == {"Bob", "Charlie"}


# --- Tests for Step 1: Propose ---


def test_step_1_propose_valid(
    game_loop: GameLoop, mock_players: list[Mock], mock_game_state: GameState
) -> None:
    """Test _run_step_1_propose with a valid proposal."""
    alice = mock_players[0]

    proposal = game_loop._run_step_1_propose(alice)

    assert proposal is not None
    assert proposal.proposer_name == "Alice"
    assert proposal.type == ProposalType.ADD
    assert proposal.proposal_id == "301"
    # Counter is not incremented by _run_step_1_propose (happens in run_turn)
    assert mock_game_state.next_proposal_id == 301
    alice.propose.assert_called_once()


def test_step_1_propose_invalid_amend_immutable(
    game_loop: GameLoop,
    mock_players: list[Mock],
    mock_game_manager: Mock,
    mock_game_state: GameState,
) -> None:
    """Test _run_step_1_propose rejects proposal to amend immutable rule."""
    alice = mock_players[0]

    # Make Alice propose an invalid amendment
    alice.propose.return_value = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.AMEND,
        target_rule_id="101",  # Immutable rule (from fixture)
        new_text="Trying to change immutable rule.",
    )

    # The validation will fail because rule 101 is immutable
    # This is tested on a temporary RulesManager, not the mock
    proposal = game_loop._run_step_1_propose(alice)

    assert proposal is None
    alice.propose.assert_called_once()

    # Verify next_proposal_id was NOT incremented (illegal proposal)
    assert mock_game_state.next_proposal_id == 301

    # Verify the real rules_manager was never touched
    mock_game_manager.rules_manager.apply_proposal.assert_not_called()


def test_step_1_propose_never_touches_real_rules(
    game_loop: GameLoop, mock_players: list[Mock], mock_game_manager: Mock
) -> None:
    """Test _run_step_1_propose never modifies real rules_manager."""
    alice = mock_players[0]

    # Get the original rules reference
    original_rules = mock_game_manager.rules_manager.rules

    proposal = game_loop._run_step_1_propose(alice)

    # CRITICAL: The real rules_manager.apply_proposal should NEVER be called
    # Validation happens on a temporary RulesManager instead
    mock_game_manager.rules_manager.apply_proposal.assert_not_called()

    # Verify the rules list reference was never changed
    assert mock_game_manager.rules_manager.rules is original_rules

    # Verify the proposal was returned successfully
    assert proposal is not None


def test_step_1_propose_rejects_mismatched_proposer_name(
    game_loop: GameLoop,
    mock_players: list[Mock],
    mock_game_state: GameState,
) -> None:
    """Test _run_step_1_propose rejects mismatched proposer_name."""
    alice = mock_players[0]

    # Make Alice propose a proposal attributed to Bob (security violation)
    alice.propose.return_value = Proposal(
        proposer_name="Bob",  # Alice trying to impersonate Bob
        move_number=1,
        type=ProposalType.ADD,
        new_text="Malicious proposal.",
        rationale="Trying to frame another player.",
    )

    # The validation should fail because proposer_name doesn't match
    proposal = game_loop._run_step_1_propose(alice)

    assert proposal is None
    alice.propose.assert_called_once()

    # Verify next_proposal_id was NOT incremented (illegal proposal)
    assert mock_game_state.next_proposal_id == 301


# --- Tests for Step 2: Discuss ---


def test_step_2_discuss_collects_all_responses(
    game_loop: GameLoop, mock_players: list[Mock]
) -> None:
    """Test _run_step_2_discuss collects discussions from all players."""
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Test rule.",
    )

    all_players = mock_players  # Alice, Bob, and Charlie

    discussions = game_loop._run_step_2_discuss(proposal, all_players)

    assert len(discussions) == 3
    assert "Alice's discussion" in discussions
    assert "Bob's discussion" in discussions
    assert "Charlie's discussion" in discussions

    for player in all_players:
        player.discuss.assert_called_once()


def test_step_2_discuss_filters_none_responses(
    game_loop: GameLoop, mock_players: list[Mock]
) -> None:
    """Test _run_step_2_discuss filters out None responses (abstentions)."""
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Test rule.",
    )

    # Bob abstains (returns None)
    mock_players[1].discuss.return_value = None

    all_players = mock_players

    discussions = game_loop._run_step_2_discuss(proposal, all_players)

    assert len(discussions) == 2
    assert "Alice's discussion" in discussions
    assert "Charlie's discussion" in discussions
    assert "Bob's discussion" not in discussions


# --- Tests for Step 3: Revise ---


def test_step_3_revise_returns_original_proposal(game_loop: GameLoop) -> None:
    """Test _run_step_3_revise returns original proposal (V1 stub)."""
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Test rule.",
    )

    discussions = ["Discussion 1", "Discussion 2"]

    result = game_loop._run_step_3_revise(proposal, discussions)

    # Should return the same proposal object
    assert result is proposal


# --- Tests for Step 4: Vote ---


def test_step_4_vote_collects_all_votes(
    game_loop: GameLoop, mock_players: list[Mock]
) -> None:
    """Test _run_step_4_vote collects votes from all players."""
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Test rule.",
    )

    all_players = mock_players

    votes = game_loop._run_step_4_vote(proposal, all_players)

    assert len(votes) == 3
    assert all(isinstance(v, Vote) for v in votes)

    for player in all_players:
        player.vote.assert_called_once()


def test_step_4_vote_respects_individual_votes(
    game_loop: GameLoop, mock_players: list[Mock]
) -> None:
    """Test _run_step_4_vote correctly records each player's vote."""
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Test rule.",
    )

    # Alice votes YES, Bob votes YES, Charlie votes NO
    mock_players[0].vote.return_value = Vote(
        player_name="Alice", vote="YES", reason="My proposal"
    )
    mock_players[1].vote.return_value = Vote(
        player_name="Bob", vote="YES", reason="Good idea"
    )
    mock_players[2].vote.return_value = Vote(
        player_name="Charlie", vote="NO", reason="Bad idea"
    )

    all_players = mock_players

    votes = game_loop._run_step_4_vote(proposal, all_players)

    assert votes[0].player_name == "Alice"
    assert votes[0].vote == "YES"
    assert votes[1].player_name == "Bob"
    assert votes[1].vote == "YES"
    assert votes[2].player_name == "Charlie"
    assert votes[2].vote == "NO"


# --- Tests for Step 5: Resolve ---


@patch("builtins.input", side_effect=["n", "10", "5", "-2"])
def test_step_5_resolve_unanimous_pass_with_judge_approval(
    mock_input: Mock,
    game_loop: GameLoop,
    mock_game_manager: Mock,
    mock_game_state: GameState,
) -> None:
    """Test _run_step_5_resolve with unanimous YES votes and no veto."""
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Test rule.",
    )

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="YES"),
    ]

    game_loop._run_step_5_resolve(proposal, votes)

    # Verify judge was consulted (veto prompt + 3 score prompts)
    assert mock_input.call_count == 4

    # Verify proposal was applied to rules
    mock_game_manager.rules_manager.apply_proposal.assert_called_once_with(
        proposal
    )

    # Verify rules were saved
    mock_game_manager.save_rules.assert_called_once()

    # Verify game state was saved
    mock_game_manager.save_game_state.assert_called_once()

    # Verify transcript was logged
    mock_game_manager.logger.log_transcript.assert_called_once()

    # Verify manually entered scores were applied
    assert mock_game_state.scores["Alice"] == 10
    assert mock_game_state.scores["Bob"] == 5
    assert mock_game_state.scores["Charlie"] == -2

    # Verify turn advanced
    assert mock_game_state.current_player_name == "Bob"
    assert mock_game_state.move_number == 2


@patch("builtins.input", side_effect=["y", "0", "0", "0"])
def test_step_5_resolve_judge_veto(
    mock_input: Mock,
    game_loop: GameLoop,
    mock_game_manager: Mock,
    mock_game_state: GameState,
) -> None:
    """Test _run_step_5_resolve when judge vetoes a passed proposal."""
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Test rule.",
    )

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="YES"),
    ]

    game_loop._run_step_5_resolve(proposal, votes)

    # Verify judge was consulted (veto prompt + 3 score prompts)
    assert mock_input.call_count == 4

    # Verify proposal was NOT applied (vetoed)
    mock_game_manager.rules_manager.apply_proposal.assert_not_called()

    # Verify rules were NOT saved (vetoed)
    mock_game_manager.save_rules.assert_not_called()

    # Verify game state WAS saved (turn advances even on veto)
    mock_game_manager.save_game_state.assert_called_once()

    # Verify transcript WAS logged
    mock_game_manager.logger.log_transcript.assert_called_once()

    # Verify scores were still entered (all zeros in this test)
    assert mock_game_state.scores["Alice"] == 0
    assert mock_game_state.scores["Bob"] == 0
    assert mock_game_state.scores["Charlie"] == 0


@patch("builtins.input", side_effect=["n", "-10", "3", "3"])
def test_step_5_resolve_failed_proposal_score_penalty(
    mock_input: Mock,
    game_loop: GameLoop,
    mock_game_manager: Mock,
    mock_game_state: GameState,
) -> None:
    """Test _run_step_5_resolve with failed proposal and manual scoring."""
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Test rule.",
    )

    # Proposal fails (not unanimous)
    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="NO"),
    ]

    game_loop._run_step_5_resolve(proposal, votes)

    # Verify proposal was NOT applied (failed vote)
    mock_game_manager.rules_manager.apply_proposal.assert_not_called()

    # Verify manually entered scores were applied
    # Judge entered: Alice=-10, Bob=3, Charlie=3
    assert mock_game_state.scores["Alice"] == -10
    assert mock_game_state.scores["Bob"] == 3
    assert mock_game_state.scores["Charlie"] == 3

    # Verify turn advanced anyway
    assert mock_game_state.current_player_name == "Bob"
    assert mock_game_state.move_number == 2


@patch("builtins.input", side_effect=["n", "8", "0", "10"])
def test_step_5_resolve_manual_score_entry(
    mock_input: Mock,
    game_loop: GameLoop,
    mock_game_state: GameState,
) -> None:
    """Test manual score entry by judge with mixed votes."""
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Test rule.",
    )

    # 2 YES out of 3 voters (proposal fails, not unanimous)
    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="NO"),
    ]

    game_loop._run_step_5_resolve(proposal, votes)

    # Verify manually entered scores
    # Judge manually entered: Alice=8, Bob=0, Charlie=10
    assert mock_game_state.scores["Alice"] == 8
    assert mock_game_state.scores["Bob"] == 0
    assert mock_game_state.scores["Charlie"] == 10


@patch("builtins.input", side_effect=["n", "0", "0", "0"])
def test_step_5_resolve_turn_advances_correctly(
    mock_input: Mock,
    game_loop: GameLoop,
    mock_game_state: GameState,
) -> None:
    """Test turn advancement to next player in turn order."""
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Test rule.",
    )

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="YES"),
    ]

    # Current player is Alice, should advance to Bob
    game_loop._run_step_5_resolve(proposal, votes)

    assert mock_game_state.current_player_name == "Bob"
    assert mock_game_state.move_number == 2


@patch("builtins.input", side_effect=["n", "0", "0", "0"])
def test_step_5_resolve_turn_wraps_around(
    mock_input: Mock,
    game_loop: GameLoop,
    mock_game_state: GameState,
) -> None:
    """Test turn order wraps around to first player."""
    proposal = Proposal(
        proposer_name="Charlie",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Test rule.",
    )

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="YES"),
    ]

    # Set current player to Charlie (last in turn order)
    mock_game_state.current_player_name = "Charlie"

    game_loop._run_step_5_resolve(proposal, votes)

    # Should wrap around to Alice
    assert mock_game_state.current_player_name == "Alice"


@patch("builtins.input", side_effect=["y", "-5", "0", "0"])
def test_step_5_resolve_veto_blocks_proposal_application(
    mock_input: Mock,
    game_loop: GameLoop,
    mock_game_manager: Mock,
    mock_game_state: GameState,
) -> None:
    """Test that judge veto prevents proposal from being applied to rules.

    This test verifies that when proposal_passed is True but the judge
    vetoes (responds 'y' to veto prompt), the proposal is NOT applied.
    """
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="This proposal will be vetoed.",
    )

    # Unanimous YES votes - proposal would pass without veto
    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="YES"),
    ]

    game_loop._run_step_5_resolve(proposal, votes)

    # CRITICAL: Verify proposal was NOT applied due to veto
    mock_game_manager.rules_manager.apply_proposal.assert_not_called()

    # CRITICAL: Verify rules were NOT saved
    mock_game_manager.save_rules.assert_not_called()

    # Verify game state was still saved (turn advances)
    mock_game_manager.save_game_state.assert_called_once()

    # Verify transcript was logged
    mock_game_manager.logger.log_transcript.assert_called_once()

    # Verify judge was consulted (veto + 3 score prompts)
    assert mock_input.call_count == 4

    # Verify scores were applied (Alice gets -5 penalty)
    assert mock_game_state.scores["Alice"] == -5
    assert mock_game_state.scores["Bob"] == 0
    assert mock_game_state.scores["Charlie"] == 0


# --- Tests for run_turn Integration ---


@patch("builtins.input", side_effect=["n", "10", "5", "0"])
def test_run_turn_full_integration_success(
    mock_input: Mock,
    game_loop: GameLoop,
    mock_players: list[Mock],
    mock_game_manager: Mock,
) -> None:
    """Test run_turn executes all 5 steps in correct order."""
    game_loop.run_turn()

    # Verify all player methods were called in order
    alice = mock_players[0]
    bob = mock_players[1]
    charlie = mock_players[2]

    # Alice proposes
    alice.propose.assert_called_once()

    # All players (Alice, Bob, and Charlie) discuss
    alice.discuss.assert_called_once()
    bob.discuss.assert_called_once()
    charlie.discuss.assert_called_once()

    # All players (Alice, Bob, and Charlie) vote
    alice.vote.assert_called_once()
    bob.vote.assert_called_once()
    charlie.vote.assert_called_once()

    # Judge was consulted (veto + 3 score prompts)
    assert mock_input.call_count == 4

    # Game state and rules were saved
    mock_game_manager.save_game_state.assert_called_once()
    mock_game_manager.save_rules.assert_called_once()

    # Transcript was logged
    mock_game_manager.logger.log_transcript.assert_called_once()


@patch("builtins.input", return_value="y")
def test_run_turn_stops_on_illegal_proposal(
    mock_input: Mock,
    game_loop: GameLoop,
    mock_players: list[Mock],
    mock_game_manager: Mock,
) -> None:
    """Test run_turn stops early if proposal is illegal."""
    # Make Alice propose an ILLEGAL proposal (amend immutable rule)
    mock_players[0].propose.return_value = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.AMEND,
        target_rule_id="101",  # Immutable rule from fixture
        new_text="Trying to amend immutable rule.",
    )

    game_loop.run_turn()

    # Alice proposed
    mock_players[0].propose.assert_called_once()

    # But no discussion, voting, or resolution should happen for any player
    mock_players[0].discuss.assert_not_called()
    mock_players[1].discuss.assert_not_called()
    mock_players[2].discuss.assert_not_called()
    mock_players[0].vote.assert_not_called()
    mock_players[1].vote.assert_not_called()
    mock_players[2].vote.assert_not_called()

    mock_input.assert_not_called()
    mock_game_manager.save_game_state.assert_not_called()
    mock_game_manager.save_rules.assert_not_called()


def test_run_turn_handles_exceptions(
    game_loop: GameLoop, mock_players: list[Mock]
) -> None:
    """Test run_turn re-raises exceptions after logging."""
    # Make propose raise an exception
    mock_players[0].propose.side_effect = RuntimeError("Test error")

    with pytest.raises(RuntimeError, match="Test error"):
        game_loop.run_turn()


# --- Tests for Transcript Formatting ---


def test_format_transcript_includes_all_details(game_loop: GameLoop) -> None:
    """Test _format_transcript includes all required details."""
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Test rule text.",
        rationale="This is a good idea.",
    )

    votes = [
        Vote(player_name="Bob", vote="YES", reason="I agree"),
        Vote(player_name="Charlie", vote="NO", reason="I disagree"),
    ]

    transcript = game_loop._format_transcript(
        proposal=proposal,
        votes=votes,
        proposal_passed=False,
        judge_approved=True,
    )

    # Verify key elements are present
    assert "MOVE #1" in transcript
    assert "Alice" in transcript
    assert "Add" in transcript
    assert "301" in transcript
    assert "Test rule text." in transcript
    assert "This is a good idea." in transcript
    assert "Bob" in transcript
    assert "Charlie" in transcript
    assert "YES" in transcript
    assert "NO" in transcript
    assert "FAILED" in transcript
    assert "Judge Approval:**" in transcript or "Judge Approval:" in transcript
