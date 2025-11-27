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

from src.nomic_engine.core.game_loop import GameLoop
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
    logger.log_event = Mock()
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

        # Default discussion (return Discussion object)
        player.discuss = Mock(
            return_value=Discussion(
                player_name=name,
                text=f"{name}'s discussion",
                private_thoughts=None,
            )
        )

        # Default revise (return the original proposal unchanged)
        # This is a callable that takes a proposal argument and returns it
        def make_revise_func():
            def revise_func(proposal, **kwargs):
                return proposal

            return revise_func

        player.revise = Mock(side_effect=make_revise_func())

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
    """Test _get_and_validate_proposal with a valid proposal."""
    alice = mock_players[0]

    proposal = game_loop._get_and_validate_proposal(alice)

    assert proposal is not None
    assert proposal.proposer_name == "Alice"
    assert proposal.type == ProposalType.ADD
    assert proposal.proposal_id == "301"
    # Counter not incremented by _get_and_validate_proposal (in run_turn)
    assert mock_game_state.next_proposal_id == 301
    alice.propose.assert_called_once()


def test_step_1_propose_invalid_amend_immutable(
    game_loop: GameLoop,
    mock_players: list[Mock],
    mock_game_manager: Mock,
    mock_game_state: GameState,
) -> None:
    """Test _get_and_validate_proposal rejects amending immutable rule."""
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
    proposal = game_loop._get_and_validate_proposal(alice)

    assert proposal is None
    alice.propose.assert_called_once()

    # Verify next_proposal_id was NOT incremented (illegal proposal)
    assert mock_game_state.next_proposal_id == 301

    # Verify the real rules_manager was never touched
    mock_game_manager.rules_manager.apply_proposal.assert_not_called()


def test_step_1_propose_never_touches_real_rules(
    game_loop: GameLoop, mock_players: list[Mock], mock_game_manager: Mock
) -> None:
    """Test _get_and_validate_proposal never modifies real rules_manager."""
    alice = mock_players[0]

    # Get the original rules reference
    original_rules = mock_game_manager.rules_manager.rules

    proposal = game_loop._get_and_validate_proposal(alice)

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
    """Test _get_and_validate_proposal rejects mismatched proposer_name."""
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
    proposal = game_loop._get_and_validate_proposal(alice)

    assert proposal is None
    alice.propose.assert_called_once()

    # Verify next_proposal_id was NOT incremented (illegal proposal)
    assert mock_game_state.next_proposal_id == 301


# --- Tests for Step 2: Discuss ---


def test_step_2_discuss_collects_all_responses(
    game_loop: GameLoop, mock_players: list[Mock]
) -> None:
    """Test _collect_discussions collects discussions from all players.

    The proposer's rationale serves as their discussion, so they are not
    prompted again. Only N-1 players (excluding the proposer) are prompted.
    """
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Test rule.",
        rationale="This is a good idea.",
    )

    all_players = mock_players  # Alice, Bob, and Charlie

    discussions = game_loop._collect_discussions(proposal, all_players)

    # All 3 players should have discussions (including the proposer)
    assert len(discussions) == 3

    # Alice's discussion should come from her proposal rationale
    assert discussions[0].player_name == "Alice"
    assert discussions[0].text == "This is a good idea."

    # Bob and Charlie's discussions should come from their discuss() calls
    assert discussions[1].player_name == "Bob"
    assert discussions[1].text == "Bob's discussion"
    assert discussions[2].player_name == "Charlie"
    assert discussions[2].text == "Charlie's discussion"

    # CRITICAL: Alice (the proposer) should NOT be prompted for discussion
    mock_players[0].discuss.assert_not_called()

    # But Bob and Charlie should be prompted
    mock_players[1].discuss.assert_called_once()
    mock_players[2].discuss.assert_called_once()


def test_step_2_discuss_includes_abstentions(
    game_loop: GameLoop, mock_players: list[Mock]
) -> None:
    """Test _collect_discussions includes abstentions (empty text)."""
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Test rule.",
        rationale="",  # Alice provided no rationale
    )

    # Bob abstains (returns Discussion with empty text)
    mock_players[1].discuss.return_value = Discussion(
        player_name="Bob",
        text="",
        private_thoughts="Strategic silence",
    )

    all_players = mock_players

    discussions = game_loop._collect_discussions(proposal, all_players)

    # All 3 players should be collected, including abstentions
    assert len(discussions) == 3

    # Alice's discussion should be empty (no rationale provided)
    assert discussions[0].player_name == "Alice"
    assert discussions[0].text == ""

    # Bob abstained
    assert discussions[1].player_name == "Bob"
    assert discussions[1].text == ""  # Bob abstained
    assert discussions[1].private_thoughts == "Strategic silence"

    # Charlie provided discussion
    assert discussions[2].player_name == "Charlie"
    assert discussions[2].text == "Charlie's discussion"

    # Alice (proposer) should not be prompted
    mock_players[0].discuss.assert_not_called()
    # Bob and Charlie should be prompted
    mock_players[1].discuss.assert_called_once()
    mock_players[2].discuss.assert_called_once()


# --- Tests for Step 3: Revise ---


def test_step_3_revise_can_return_revised_proposal(
    game_loop: GameLoop, mock_players: list[Mock]
) -> None:
    """Test _handle_revision can return a revised proposal."""
    alice = mock_players[0]

    original_proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Test rule.",
    )

    # Create a revised proposal (different object)
    revised_proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Revised test rule.",
        rationale="Updated based on feedback.",
    )

    discussions = [
        Discussion(player_name="Alice", text="Discussion 1"),
        Discussion(player_name="Bob", text="Discussion 2"),
    ]

    # Mock the player's revise method to return the revised proposal
    alice.revise = Mock(return_value=revised_proposal)

    result = game_loop._handle_revision(alice, original_proposal, discussions)

    # Should return the revised proposal object
    assert result is revised_proposal
    alice.revise.assert_called_once()


def test_step_3_revise_rejects_illegal_revised_proposal(
    game_loop: GameLoop,
    mock_players: list[Mock],
    mock_game_manager: Mock,
) -> None:
    """Test _handle_revision rejects illegal revised proposals.

    This test verifies that when a player returns a NEW proposal object
    (not the original), it is re-validated for legality. If the revised
    proposal is illegal, the turn should end.
    """
    alice = mock_players[0]

    original_proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Original legal proposal.",
    )

    # Create an ILLEGAL revised proposal (trying to amend immutable rule)
    illegal_revised_proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.AMEND,
        target_rule_id="101",  # Immutable rule from fixture
        proposal_id="301",
        new_text="Trying to amend immutable rule.",
        rationale="This should be rejected.",
    )

    discussions = [Discussion(player_name="Bob", text="Discussion")]

    # Mock the player's revise method to return the illegal revised proposal
    alice.revise = Mock(return_value=illegal_revised_proposal)

    result = game_loop._handle_revision(alice, original_proposal, discussions)

    # CRITICAL: Should return None (illegal revised proposal)
    assert result is None
    alice.revise.assert_called_once()

    # Verify the illegal revised proposal was logged to transcript
    mock_game_manager.logger.log_transcript.assert_called_once()

    # Verify the logged transcript contains expected details
    logged_transcript = mock_game_manager.logger.log_transcript.call_args[0][0]
    assert "ILLEGAL REVISED PROPOSAL" in logged_transcript
    assert "Alice" in logged_transcript
    assert "Amend" in logged_transcript


# --- Tests for Step 4: Vote ---


def test_step_4_vote_collects_all_votes(
    game_loop: GameLoop, mock_players: list[Mock]
) -> None:
    """Test _collect_votes collects votes from all players."""
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Test rule.",
    )

    all_players = mock_players

    votes = game_loop._collect_votes(proposal, all_players)

    assert len(votes) == 3
    assert all(isinstance(v, Vote) for v in votes)

    for player in all_players:
        player.vote.assert_called_once()


def test_step_4_vote_respects_individual_votes(
    game_loop: GameLoop, mock_players: list[Mock]
) -> None:
    """Test _collect_votes correctly records each player's vote."""
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

    votes = game_loop._collect_votes(proposal, all_players)

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
    """Test _resolve_turn with unanimous YES votes and no veto."""
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

    discussions: list[Discussion] = []

    # Store initial next_proposal_id
    initial_proposal_id = mock_game_state.next_proposal_id

    game_loop._resolve_turn(proposal, votes, discussions)

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

    # CRITICAL: Verify next_proposal_id was incremented (proposal passed)
    assert mock_game_state.next_proposal_id == initial_proposal_id + 1


def test_step_5_resolve_triggers_game_over(
    mock_game_manager: Mock,
    mock_players: list[Mock],
    mock_game_state: GameState,
) -> None:
    """Ensure the game ends when a player reaches the target score."""

    mock_game_state.scores = {"Alice": 99, "Bob": 50, "Charlie": 30}
    mock_game_state.target_score = 100

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

    def assess_scores_side_effect(*_args, **_kwargs):
        mock_game_state.scores["Alice"] += 5
        return {
            "private_thoughts": None,
            "score_adjustments": [
                {"player": "Alice", "delta": 5, "reason": "Reached target"}
            ],
        }

    judge = Mock()
    judge.get_veto.return_value = {
        "veto": False,
        "reason": None,
        "private_thoughts": None,
    }
    judge.assess_scores.side_effect = assess_scores_side_effect

    game_loop = GameLoop(mock_game_manager, mock_players, judge)

    game_over = game_loop._resolve_turn(proposal, votes, [])

    assert game_over is True
    assert mock_game_state.current_player_name == "Alice"
    assert mock_game_state.move_number == 1

    mock_game_manager.save_game_state.assert_called_once()
    assert mock_game_manager.logger.log_transcript.call_count == 2

    event_call = mock_game_manager.logger.log_event.call_args
    assert event_call[0][0] == "game_over"
    payload = event_call[0][1]
    assert payload["target_score"] == 100
    assert payload["winners"] == ["Alice"]
    assert payload["winning_score"] == 104
    assert payload["final_scores"]["Alice"] == 104


def test_detect_victory_skips_without_target(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """_detect_victory should return no victory when target_score is None."""

    mock_game_state.scores = {"Alice": 15, "Bob": 20}
    mock_game_state.target_score = None

    victory, winners, score = game_loop._detect_victory()

    assert victory is False
    assert winners == []
    assert score == 0


def test_detect_victory_handles_ties(
    game_loop: GameLoop, mock_game_state: GameState
) -> None:
    """_detect_victory should return all top scorers that meet the target."""

    mock_game_state.scores = {"Alice": 150, "Bob": 150, "Charlie": 120}
    mock_game_state.target_score = 100

    victory, winners, score = game_loop._detect_victory()

    assert victory is True
    assert set(winners) == {"Alice", "Bob"}
    assert score == 150


def test_step_5_resolve_skips_game_over_without_target(
    mock_game_manager: Mock,
    mock_players: list[Mock],
    mock_game_state: GameState,
) -> None:
    """Ensure no victory is detected when target_score is absent."""

    mock_game_state.scores = {"Alice": 200, "Bob": 150, "Charlie": 120}
    mock_game_state.target_score = None

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

    game_loop = GameLoop(mock_game_manager, mock_players, judge)

    game_over = game_loop._resolve_turn(proposal, votes, [])

    assert game_over is False
    mock_game_manager.logger.log_event.assert_not_called()


@patch("builtins.input", side_effect=["y", "0", "0", "0"])
def test_step_5_resolve_judge_veto(
    mock_input: Mock,
    game_loop: GameLoop,
    mock_game_manager: Mock,
    mock_game_state: GameState,
) -> None:
    """Test _resolve_turn when judge vetoes a passed proposal."""
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

    discussions: list[Discussion] = []

    # Store initial next_proposal_id
    initial_proposal_id = mock_game_state.next_proposal_id

    game_loop._resolve_turn(proposal, votes, discussions)

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

    # CRITICAL: Verify next_proposal_id was NOT incremented (vetoed)
    assert mock_game_state.next_proposal_id == initial_proposal_id


@patch("builtins.input", side_effect=["-10", "3", "3"])
def test_step_5_resolve_failed_proposal_score_penalty(
    mock_input: Mock,
    game_loop: GameLoop,
    mock_game_manager: Mock,
    mock_game_state: GameState,
) -> None:
    """Test _resolve_turn with failed proposal and manual scoring.

    When a proposal fails the vote, the judge should NOT be asked for veto.
    """
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

    discussions: list[Discussion] = []

    # Store initial next_proposal_id
    initial_proposal_id = mock_game_state.next_proposal_id

    game_loop._resolve_turn(proposal, votes, discussions)

    # Verify judge was only consulted for scoring
    # (3 score prompts, NO veto prompt)
    assert mock_input.call_count == 3

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

    # CRITICAL: Verify next_proposal_id was NOT incremented (failed)
    assert mock_game_state.next_proposal_id == initial_proposal_id


@patch("builtins.input", side_effect=["8", "0", "10"])
def test_step_5_resolve_manual_score_entry(
    mock_input: Mock,
    game_loop: GameLoop,
    mock_game_state: GameState,
) -> None:
    """Test manual score entry by judge with mixed votes.

    When a proposal fails the vote, the judge should NOT be asked for veto.
    """
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

    discussions: list[Discussion] = []

    game_loop._resolve_turn(proposal, votes, discussions)

    # Verify judge was only consulted for scoring
    # (3 score prompts, NO veto prompt)
    assert mock_input.call_count == 3

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

    discussions: list[Discussion] = []

    # Current player is Alice, should advance to Bob
    game_loop._resolve_turn(proposal, votes, discussions)

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

    discussions: list[Discussion] = []

    # Set current player to Charlie (last in turn order)
    mock_game_state.current_player_name = "Charlie"

    game_loop._resolve_turn(proposal, votes, discussions)

    # Should wrap around to Alice
    assert mock_game_state.current_player_name == "Alice"


@patch("builtins.input", side_effect=["n", "5", "5", "5"])
def test_step_5_resolve_zero_voters_automatic_pass(
    mock_input: Mock,
    game_loop: GameLoop,
    mock_game_manager: Mock,
    mock_game_state: GameState,
) -> None:
    """Test _resolve_turn with zero voters results in automatic pass.

    Per game rules, a proposal with zero total voters (empty votes list)
    is treated as an automatic PASS.
    """
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Test rule with zero voters.",
    )

    # Empty votes list (zero voters)
    votes: list[Vote] = []

    discussions: list[Discussion] = []

    # Store initial next_proposal_id
    initial_proposal_id = mock_game_state.next_proposal_id

    game_loop._resolve_turn(proposal, votes, discussions)

    # Verify judge was consulted (veto prompt + 3 score prompts)
    assert mock_input.call_count == 4

    # CRITICAL: Verify proposal was applied (automatic pass with 0 voters)
    mock_game_manager.rules_manager.apply_proposal.assert_called_once_with(
        proposal
    )

    # Verify rules were saved
    mock_game_manager.save_rules.assert_called_once()

    # Verify game state was saved
    mock_game_manager.save_game_state.assert_called_once()

    # Verify transcript was logged
    mock_game_manager.logger.log_transcript.assert_called_once()

    # Verify scores were applied
    assert mock_game_state.scores["Alice"] == 5
    assert mock_game_state.scores["Bob"] == 5
    assert mock_game_state.scores["Charlie"] == 5

    # CRITICAL: Verify next_proposal_id was incremented (proposal passed)
    assert mock_game_state.next_proposal_id == initial_proposal_id + 1


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

    discussions: list[Discussion] = []

    game_loop._resolve_turn(proposal, votes, discussions)

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


def test_judge_veto_not_called_when_proposal_fails(
    mock_game_manager: Mock,
    mock_players: list[Mock],
    mock_game_state: GameState,
) -> None:
    """Test that judge.get_veto is NOT called when proposal fails vote.

    This is the key optimization from P2: don't ask the judge for veto
    if the proposal already failed the player vote.
    """
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Test rule.",
    )

    # Proposal fails (Charlie votes NO, not unanimous)
    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="NO"),
    ]

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

    game_loop = GameLoop(mock_game_manager, mock_players, judge)

    game_loop._resolve_turn(proposal, votes, [])

    # CRITICAL: Verify judge.get_veto was NOT called (proposal failed)
    judge.get_veto.assert_not_called()

    # Verify judge.assess_scores was still called (scoring always happens)
    judge.assess_scores.assert_called_once()


def test_judge_veto_called_when_proposal_passes(
    mock_game_manager: Mock,
    mock_players: list[Mock],
    mock_game_state: GameState,
) -> None:
    """Test that judge.get_veto IS called when proposal passes vote.

    When a proposal passes the vote, the judge must be consulted for veto.
    """
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Test rule.",
    )

    # Proposal passes (unanimous YES votes)
    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
        Vote(player_name="Charlie", vote="YES"),
    ]

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

    game_loop = GameLoop(mock_game_manager, mock_players, judge)

    game_loop._resolve_turn(proposal, votes, [])

    # CRITICAL: Verify judge.get_veto WAS called (proposal passed)
    judge.get_veto.assert_called_once()

    # Verify judge.assess_scores was also called (scoring always happens)
    judge.assess_scores.assert_called_once()


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

    # CRITICAL: Alice (proposer) should NOT be prompted for discussion
    # Only Bob and Charlie should be prompted
    alice.discuss.assert_not_called()
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

    # CRITICAL: Verify that the illegal proposal was logged to the transcript
    mock_game_manager.logger.log_transcript.assert_called_once()

    # Verify the logged transcript contains the expected details
    logged_transcript = mock_game_manager.logger.log_transcript.call_args[0][0]
    assert "MOVE #1" in logged_transcript
    assert "Alice" in logged_transcript
    assert "ILLEGAL PROPOSAL" in logged_transcript
    assert "Amend" in logged_transcript


def test_run_turn_handles_exceptions(
    game_loop: GameLoop, mock_players: list[Mock]
) -> None:
    """Test run_turn re-raises exceptions after logging."""
    # Make propose raise an exception
    mock_players[0].propose.side_effect = RuntimeError("Test error")

    with pytest.raises(RuntimeError, match="Test error"):
        game_loop.run_turn()


def test_run_turn_stops_if_proposal_withdrawn(
    game_loop: GameLoop, mock_players: list[Mock], mock_game_manager: Mock
) -> None:
    """Test run_turn stops early if proposal is withdrawn during revision."""
    alice = mock_players[0]

    # Mock the player's revise method to return None (withdrawal)
    alice.revise = Mock(return_value=None)

    game_loop.run_turn()

    # Alice proposed
    alice.propose.assert_called_once()

    # CRITICAL: Alice (proposer) should NOT be prompted for discussion
    # Only Bob and Charlie should be prompted (discussion happens before
    # revision)
    alice.discuss.assert_not_called()
    mock_players[1].discuss.assert_called_once()
    mock_players[2].discuss.assert_called_once()

    # Alice was given chance to revise
    alice.revise.assert_called_once()

    # But no voting should happen for any player (proposal was withdrawn)
    alice.vote.assert_not_called()
    mock_players[1].vote.assert_not_called()
    mock_players[2].vote.assert_not_called()

    # No judge interaction should happen
    mock_game_manager.rules_manager.apply_proposal.assert_not_called()
    mock_game_manager.save_game_state.assert_not_called()
    mock_game_manager.save_rules.assert_not_called()

    # Transcript should not be logged for withdrawn proposals
    mock_game_manager.logger.log_transcript.assert_not_called()


# --- Tests for Transcript Formatting ---


def test_format_transcript_includes_all_details(
    game_loop: GameLoop, mock_rules: list[Rule]
) -> None:
    """Test _format_transcript includes all required details."""
    # Create an AMEND proposal to test original text inclusion
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.AMEND,
        proposal_id="301",
        target_rule_id="201",  # Mutable rule from fixture
        new_text="Updated rule text.",
        rationale="This is a good idea.",
        private_thoughts="I think this will give me an advantage.",
    )

    votes = [
        Vote(
            player_name="Bob",
            vote="YES",
            reason="I agree",
            private_thoughts="Strategic analysis: this aligns with my goals",
        ),
        Vote(player_name="Charlie", vote="NO", reason="I disagree"),
    ]

    discussions = [
        Discussion(
            player_name="Bob",
            text="This is unclear",
            private_thoughts="Testing the proposer's reasoning",
        ),
        Discussion(
            player_name="Charlie",
            text="I have concerns",
            private_thoughts=None,
        ),
    ]

    judge_veto_response = {
        "veto": False,
        "reason": "No conflicts with rules.",
        "private_thoughts": "I think this is within scope.",
    }

    judge_score_response = {
        "private_thoughts": "No adjustments necessary.",
        "score_adjustments": [
            {
                "player": "Alice",
                "delta": 2,
                "reason": "Strong proposal and engagement.",
            }
        ],
    }

    transcript = game_loop._format_transcript(
        proposal=proposal,
        votes=votes,
        proposal_passed=False,
        judge_approved=True,
        judge_veto_response=judge_veto_response,
        judge_score_response=judge_score_response,
        discussions=discussions,
        rules=mock_rules,
    )

    # Verify key proposal elements are present
    assert "MOVE #1" in transcript
    assert "Alice" in transcript
    assert "Amend" in transcript
    assert "301" in transcript
    assert "Updated rule text." in transcript
    assert "This is a good idea." in transcript

    # Verify proposal private thoughts are present
    assert "I think this will give me an advantage." in transcript

    # Verify original text is present (for AMEND proposal)
    assert "Original Text (Rule 201):" in transcript
    assert "Players take turns." in transcript  # Text from mock_rules fixture

    # Verify discussions section is present
    assert "### Discussions" in transcript
    assert "Bob" in transcript
    assert "This is unclear" in transcript
    assert "Charlie" in transcript
    assert "I have concerns" in transcript

    # Verify discussion private thoughts for Bob
    assert "Testing the proposer's reasoning" in transcript

    # Verify votes section with reasons
    assert "### Votes" in transcript
    assert "YES" in transcript
    assert "I agree" in transcript
    assert "NO" in transcript
    assert "I disagree" in transcript

    # Verify private thoughts appear for Bob's vote (LLM player)
    assert "Strategic analysis: this aligns with my goals" in transcript

    # Verify vote result and judge approval
    assert "FAILED" in transcript
    assert "Judge Approval:**" in transcript or "Judge Approval:" in transcript

    # Verify judge responses are logged
    assert "Judge Veto Response" in transcript
    assert "No conflicts with rules." in transcript
    assert "I think this is within scope." in transcript
    assert "Judge Score Response" in transcript
    assert "Strong proposal and engagement." in transcript
    assert "+2" in transcript


def test_format_transcript_shows_abstentions(
    game_loop: GameLoop, mock_rules: list[Rule]
) -> None:
    """Test _format_transcript shows abstentions as '(Abstained)'."""
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        proposal_id="301",
        new_text="Test rule.",
        rationale="I support my proposal.",
    )

    votes = [
        Vote(player_name="Alice", vote="YES"),
        Vote(player_name="Bob", vote="YES"),
    ]

    # Alice's discussion comes from rationale
    # Bob abstains (empty text)
    discussions = [
        Discussion(
            player_name="Alice",
            text="I support my proposal.",
            private_thoughts=None,
        ),
        Discussion(
            player_name="Bob",
            text="",
            private_thoughts="Nothing useful to say",
        ),
    ]

    transcript = game_loop._format_transcript(
        proposal=proposal,
        votes=votes,
        proposal_passed=True,
        judge_approved=True,
        judge_veto_response={
            "veto": False,
            "reason": None,
            "private_thoughts": None,
        },
        judge_score_response={
            "private_thoughts": None,
            "score_adjustments": [],
        },
        discussions=discussions,
        rules=mock_rules,
    )

    # Verify Alice's rationale appears in discussion
    assert "I support my proposal." in transcript
    # Verify abstention appears
    assert "*(Abstained)*" in transcript
    # Bob's private thoughts should still appear
    assert "Nothing useful to say" in transcript
