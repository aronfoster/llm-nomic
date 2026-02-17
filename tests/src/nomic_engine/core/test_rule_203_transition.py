"""
Unit tests for Rule 203 automatic unanimous → majority transition.

These tests validate that the engine correctly switches vote_mode from
"unanimous" to "majority" after 2 complete circuits, as required by Rule 203.
"""

from unittest.mock import Mock

import pytest

from src.nomic_engine.core.game_loop import GameLoop
from src.nomic_engine.core.game_manager import GameManager
from src.nomic_engine.data_models import (
    GameState,
    Rule,
    RuleStatus,
)

# --- Fixtures ---


@pytest.fixture
def mock_game_manager() -> Mock:
    """Fixture providing a mocked GameManager with minimal setup."""
    manager = Mock(spec=GameManager)

    # Mock RulesManager with Rule 203 present
    rules_manager = Mock()
    rules_manager.rules = [
        Rule(
            rule_id="101",
            text="All players must follow the rules.",
            status=RuleStatus.IMMUTABLE,
        ),
        Rule(
            rule_id="203",
            text=(
                "A rule-change is adopted if and only if the vote is "
                "unanimous among the eligible voters. If this rule is not "
                "amended by the end of the second complete circuit of turns, "
                "it automatically changes to require only a simple majority."
            ),
            status=RuleStatus.MUTABLE,
        ),
    ]
    rules_manager._find_rule_by_id = lambda rule_id: next(
        (r for r in rules_manager.rules if r.rule_id == rule_id), None
    )
    manager.rules_manager = rules_manager

    # Mock GameLogger
    logger = Mock()
    logger.log_transcript = Mock()
    logger.log_event = Mock()
    manager.logger = logger

    return manager


@pytest.fixture
def game_state_2_players() -> GameState:
    """Fixture providing game state with 2 players."""
    return GameState(
        scores={"Alice": 0, "Bob": 0},
        current_player_name="Alice",
        move_number=1,
        turn_order=["Alice", "Bob"],
        next_proposal_id=301,
        flags={"vote_mode": "unanimous"},
    )


@pytest.fixture
def game_state_3_players() -> GameState:
    """Fixture providing game state with 3 players."""
    return GameState(
        scores={"Alice": 0, "Bob": 0, "Charlie": 0},
        current_player_name="Alice",
        move_number=1,
        turn_order=["Alice", "Bob", "Charlie"],
        next_proposal_id=301,
        flags={"vote_mode": "unanimous"},
    )


# --- Tests ---


class TestRule203Transition:
    """Test suite for Rule 203 automatic transition logic."""

    def test_transition_fires_after_2_circuits_with_2_players(
        self, mock_game_manager: Mock, game_state_2_players: GameState
    ) -> None:
        """
        Transition fires at the end of turn 4 (2 complete circuits, 2 players).

        With 2 players, circuit 1 completes at end of turn 2,
        circuit 2 completes at end of turn 4.
        """
        mock_game_manager.game_state = game_state_2_players
        game_loop = GameLoop(mock_game_manager, [], None)

        # Simulate advancing to turn 5 (after 4 turns completed)
        # Turn 1: Alice, Turn 2: Bob (circuit 1 complete)
        # Turn 3: Alice, Turn 4: Bob (circuit 2 complete)
        # Turn 5: should trigger transition
        game_loop.game_manager.game_state.move_number = 5

        # Manually call the transition check
        game_loop._check_rule_203_transition()

        # Verify transition occurred
        assert (
            game_loop.game_manager.game_state.flags["vote_mode"] == "majority"
        )
        mock_game_manager.logger.log_transcript.assert_called_once()
        transcript_call = mock_game_manager.logger.log_transcript.call_args[0][
            0
        ]
        assert "[ENGINE] Automatic transition" in transcript_call
        assert (
            "vote_mode changed from 'unanimous' to 'majority'"
            in transcript_call
        )

    def test_transition_fires_after_2_circuits_with_3_players(
        self, mock_game_manager: Mock, game_state_3_players: GameState
    ) -> None:
        """
        Transition fires at the end of turn 6 (2 complete circuits, 3 players).

        With 3 players, circuit 1 completes at end of turn 3,
        circuit 2 completes at end of turn 6.
        """
        mock_game_manager.game_state = game_state_3_players
        game_loop = GameLoop(mock_game_manager, [], None)

        # Simulate advancing to turn 7 (after 6 turns completed)
        game_loop.game_manager.game_state.move_number = 7

        # Manually call the transition check
        game_loop._check_rule_203_transition()

        # Verify transition occurred
        assert (
            game_loop.game_manager.game_state.flags["vote_mode"] == "majority"
        )
        mock_game_manager.logger.log_transcript.assert_called_once()

    def test_no_transition_before_2_circuits(
        self, mock_game_manager: Mock, game_state_2_players: GameState
    ) -> None:
        """
        Transition does not fire before 2 complete circuits.

        With 2 players, testing at turn 3 (1.5 circuits).
        """
        mock_game_manager.game_state = game_state_2_players
        game_loop = GameLoop(mock_game_manager, [], None)

        # Turn 3 is in the middle of circuit 2
        game_loop.game_manager.game_state.move_number = 3

        # Manually call the transition check
        game_loop._check_rule_203_transition()

        # Verify transition did NOT occur
        assert (
            game_loop.game_manager.game_state.flags["vote_mode"] == "unanimous"
        )
        mock_game_manager.logger.log_transcript.assert_not_called()

    def test_no_transition_at_end_of_first_circuit(
        self, mock_game_manager: Mock, game_state_2_players: GameState
    ) -> None:
        """
        Transition does not fire at end of turn 2N-1 (first complete).

        With 2 players, testing at turn 3
        (end of circuit 1, start of circuit 2).
        """
        mock_game_manager.game_state = game_state_2_players
        game_loop = GameLoop(mock_game_manager, [], None)

        # Turn 3 is the start of circuit 2 (after circuit 1 completes)
        game_loop.game_manager.game_state.move_number = 3

        # Manually call the transition check
        game_loop._check_rule_203_transition()

        # Verify transition did NOT occur
        assert (
            game_loop.game_manager.game_state.flags["vote_mode"] == "unanimous"
        )
        mock_game_manager.logger.log_transcript.assert_not_called()

    def test_no_transition_when_rule_203_absent(
        self, mock_game_manager: Mock, game_state_2_players: GameState
    ) -> None:
        """
        Transition does not fire when Rule 203 has been amended (absent).

        Simulates scenario where players amended Rule 203 before 2 circuits.
        """
        mock_game_manager.game_state = game_state_2_players
        game_loop = GameLoop(mock_game_manager, [], None)

        # Remove Rule 203 from ruleset (simulating amendment)
        mock_game_manager.rules_manager.rules = [
            r
            for r in mock_game_manager.rules_manager.rules
            if r.rule_id != "203"
        ]

        # Simulate advancing to turn 5 (after 2 complete circuits)
        game_loop.game_manager.game_state.move_number = 5

        # Manually call the transition check
        game_loop._check_rule_203_transition()

        # Verify transition did NOT occur (vote_mode remains unanimous)
        assert (
            game_loop.game_manager.game_state.flags["vote_mode"] == "unanimous"
        )
        mock_game_manager.logger.log_transcript.assert_not_called()

    def test_transition_is_idempotent(
        self, mock_game_manager: Mock, game_state_2_players: GameState
    ) -> None:
        """
        Transition is idempotent - calling multiple times has no effect.

        Once vote_mode is "majority", repeated calls do nothing.
        """
        mock_game_manager.game_state = game_state_2_players
        game_loop = GameLoop(mock_game_manager, [], None)

        # Set vote_mode to majority already
        game_loop.game_manager.game_state.flags["vote_mode"] = "majority"

        # Simulate advancing to turn 5 (after 2 complete circuits)
        game_loop.game_manager.game_state.move_number = 5

        # Call transition check multiple times
        game_loop._check_rule_203_transition()
        game_loop._check_rule_203_transition()
        game_loop._check_rule_203_transition()

        # Verify vote_mode is still majority
        assert (
            game_loop.game_manager.game_state.flags["vote_mode"] == "majority"
        )
        # Verify no transcript entries were added
        mock_game_manager.logger.log_transcript.assert_not_called()

    def test_transition_fires_after_3_circuits(
        self, mock_game_manager: Mock, game_state_2_players: GameState
    ) -> None:
        """
        Transition fires even after more than 2 circuits (>= 2 check).

        With 2 players, testing at turn 7 (3 complete circuits).
        """
        mock_game_manager.game_state = game_state_2_players
        game_loop = GameLoop(mock_game_manager, [], None)

        # Simulate advancing to turn 7 (after 3 complete circuits)
        game_loop.game_manager.game_state.move_number = 7

        # Manually call the transition check
        game_loop._check_rule_203_transition()

        # Verify transition occurred
        assert (
            game_loop.game_manager.game_state.flags["vote_mode"] == "majority"
        )
        mock_game_manager.logger.log_transcript.assert_called_once()

    def test_circuit_math_with_1_player(self, mock_game_manager: Mock) -> None:
        """
        Circuit count math is correct with 1 player (edge case).

        With 1 player, each turn completes a circuit.
        Turn 3 should trigger transition (2 circuits complete).
        """
        game_state = GameState(
            scores={"Alice": 0},
            current_player_name="Alice",
            move_number=1,
            turn_order=["Alice"],
            next_proposal_id=301,
            flags={"vote_mode": "unanimous"},
        )
        mock_game_manager.game_state = game_state
        game_loop = GameLoop(mock_game_manager, [], None)

        # Simulate advancing to turn 3 (after 2 complete circuits)
        game_loop.game_manager.game_state.move_number = 3

        # Manually call the transition check
        game_loop._check_rule_203_transition()

        # Verify transition occurred
        assert (
            game_loop.game_manager.game_state.flags["vote_mode"] == "majority"
        )
        mock_game_manager.logger.log_transcript.assert_called_once()

    def test_no_transition_with_missing_vote_mode_flag(
        self, mock_game_manager: Mock, game_state_2_players: GameState
    ) -> None:
        """
        Transition handles missing vote_mode flag gracefully.

        If flags dict doesn't have vote_mode, default to "unanimous".
        """
        mock_game_manager.game_state = game_state_2_players
        game_loop = GameLoop(mock_game_manager, [], None)

        # Remove vote_mode from flags
        if "vote_mode" in game_loop.game_manager.game_state.flags:
            del game_loop.game_manager.game_state.flags["vote_mode"]

        # Simulate advancing to turn 5 (after 2 complete circuits)
        game_loop.game_manager.game_state.move_number = 5

        # Manually call the transition check
        game_loop._check_rule_203_transition()

        # Verify transition occurred (flag was created)
        assert (
            game_loop.game_manager.game_state.flags["vote_mode"] == "majority"
        )
        mock_game_manager.logger.log_transcript.assert_called_once()

    def test_automatic_transitions_method_calls_rule_203(
        self, mock_game_manager: Mock, game_state_2_players: GameState
    ) -> None:
        """
        _check_automatic_transitions() calls _check_rule_203_transition.

        This verifies the integration point works as expected.
        """
        mock_game_manager.game_state = game_state_2_players
        game_loop = GameLoop(mock_game_manager, [], None)

        # Simulate advancing to turn 5 (after 2 complete circuits)
        game_loop.game_manager.game_state.move_number = 5

        # Call the public automatic transitions method
        game_loop._check_automatic_transitions()

        # Verify transition occurred via the integrated call
        assert (
            game_loop.game_manager.game_state.flags["vote_mode"] == "majority"
        )
        mock_game_manager.logger.log_transcript.assert_called_once()

    def test_transition_at_exact_boundary_2_players(
        self, mock_game_manager: Mock, game_state_2_players: GameState
    ) -> None:
        """
        Transition fires at exact turn 2N boundary (not 2N-1 or 2N+1).

        With 2 players:
        - Turn 4: end of circuit 2, should NOT transition yet
        - Turn 5: start of circuit 3, should transition
        """
        mock_game_manager.game_state = game_state_2_players
        game_loop = GameLoop(mock_game_manager, [], None)

        # Test turn 4 (end of circuit 2) - should NOT transition yet
        game_loop.game_manager.game_state.move_number = 4
        game_loop._check_rule_203_transition()
        assert (
            game_loop.game_manager.game_state.flags["vote_mode"] == "unanimous"
        )

        # Test turn 5 (start of circuit 3) - should transition
        game_loop.game_manager.game_state.move_number = 5
        game_loop._check_rule_203_transition()
        assert (
            game_loop.game_manager.game_state.flags["vote_mode"] == "majority"
        )

    def test_transition_at_exact_boundary_3_players(
        self, mock_game_manager: Mock, game_state_3_players: GameState
    ) -> None:
        """
        Transition fires at exact turn 2N boundary with 3 players.

        With 3 players:
        - Turn 6: end of circuit 2, should NOT transition yet
        - Turn 7: start of circuit 3, should transition
        """
        mock_game_manager.game_state = game_state_3_players
        game_loop = GameLoop(mock_game_manager, [], None)

        # Test turn 6 (end of circuit 2) - should NOT transition yet
        game_loop.game_manager.game_state.move_number = 6
        game_loop._check_rule_203_transition()
        assert (
            game_loop.game_manager.game_state.flags["vote_mode"] == "unanimous"
        )

        # Test turn 7 (start of circuit 3) - should transition
        game_loop.game_manager.game_state.move_number = 7
        game_loop._check_rule_203_transition()
        assert (
            game_loop.game_manager.game_state.flags["vote_mode"] == "majority"
        )
