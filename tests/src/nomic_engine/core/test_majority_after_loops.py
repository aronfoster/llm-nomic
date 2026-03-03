"""
Unit tests for the majority_after_loops flag automatic transition.

These tests validate that the engine correctly switches vote_mode
from "unanimous" to "majority" after the configured number of
complete game loops, as implemented by _check_majority_after_loops().
"""

from unittest.mock import Mock

import pytest

from src.nomic_engine.core.game_loop import GameLoop
from src.nomic_engine.core.game_manager import GameManager
from src.nomic_engine.data_models import GameState

# --- Fixtures ---


@pytest.fixture
def mock_game_manager() -> Mock:
    """Fixture providing a mocked GameManager with minimal setup."""
    manager = Mock(spec=GameManager)

    # Required by GameLoop.__init__ validation
    manager.rules_manager = Mock()

    # Mock GameLogger
    game_logger = Mock()
    game_logger.log_transcript = Mock()
    game_logger.log_event = Mock()
    manager.logger = game_logger

    return manager


@pytest.fixture
def game_state_3_players() -> GameState:
    """Fixture providing game state with 3 players and flag=2."""
    return GameState(
        scores={"Alice": 0, "Bob": 0, "Charlie": 0},
        current_player_name="Alice",
        move_number=1,
        turn_order=["Alice", "Bob", "Charlie"],
        next_proposal_id=301,
        flags={"vote_mode": "unanimous", "majority_after_loops": 2},
    )


@pytest.fixture
def game_state_2_players() -> GameState:
    """Fixture providing game state with 2 players and flag=2."""
    return GameState(
        scores={"Alice": 0, "Bob": 0},
        current_player_name="Alice",
        move_number=1,
        turn_order=["Alice", "Bob"],
        next_proposal_id=301,
        flags={"vote_mode": "unanimous", "majority_after_loops": 2},
    )


# --- Tests ---


class TestMajorityAfterLoopsTransition:
    """Test suite for majority_after_loops automatic transition logic."""

    def test_null_flag_disables_transition(
        self,
        mock_game_manager: Mock,
        game_state_3_players: GameState,
    ) -> None:
        """When majority_after_loops is None, no transition fires."""
        game_state_3_players.flags["majority_after_loops"] = None
        mock_game_manager.game_state = game_state_3_players
        game_loop = GameLoop(mock_game_manager, [], None)

        game_loop.game_manager.game_state.move_number = 100
        game_loop._check_majority_after_loops()

        assert (
            game_loop.game_manager.game_state.flags["vote_mode"] == "unanimous"
        )
        mock_game_manager.logger.log_transcript.assert_not_called()

    def test_flag_absent_disables_transition(
        self, mock_game_manager: Mock
    ) -> None:
        """When majority_after_loops key is absent, no transition fires."""
        game_state = GameState(
            scores={"Alice": 0, "Bob": 0},
            current_player_name="Alice",
            move_number=100,
            turn_order=["Alice", "Bob"],
            next_proposal_id=301,
            flags={"vote_mode": "unanimous"},
        )
        mock_game_manager.game_state = game_state
        game_loop = GameLoop(mock_game_manager, [], None)

        game_loop._check_majority_after_loops()

        assert (
            game_loop.game_manager.game_state.flags["vote_mode"] == "unanimous"
        )
        mock_game_manager.logger.log_transcript.assert_not_called()

    def test_flag_1_fires_at_move_4_with_3_players(
        self,
        mock_game_manager: Mock,
        game_state_3_players: GameState,
    ) -> None:
        """
        With flag=1 and 3 players, transition fires at move_number=4.

        4/3 = 1.33 > 1, so it fires.
        """
        game_state_3_players.flags["majority_after_loops"] = 1
        mock_game_manager.game_state = game_state_3_players
        game_loop = GameLoop(mock_game_manager, [], None)

        game_loop.game_manager.game_state.move_number = 4
        game_loop._check_majority_after_loops()

        assert (
            game_loop.game_manager.game_state.flags["vote_mode"] == "majority"
        )
        assert (
            game_loop.game_manager.game_state.flags["majority_after_loops"]
            is None
        )
        mock_game_manager.logger.log_transcript.assert_called_once()

    def test_flag_1_does_not_fire_at_move_3_with_3_players(
        self,
        mock_game_manager: Mock,
        game_state_3_players: GameState,
    ) -> None:
        """
        With flag=1 and 3 players, no transition at move_number=3.

        3/3 = 1.0, which is not > 1.
        """
        game_state_3_players.flags["majority_after_loops"] = 1
        mock_game_manager.game_state = game_state_3_players
        game_loop = GameLoop(mock_game_manager, [], None)

        game_loop.game_manager.game_state.move_number = 3
        game_loop._check_majority_after_loops()

        assert (
            game_loop.game_manager.game_state.flags["vote_mode"] == "unanimous"
        )
        mock_game_manager.logger.log_transcript.assert_not_called()

    def test_flag_2_fires_at_move_7_with_3_players(
        self,
        mock_game_manager: Mock,
        game_state_3_players: GameState,
    ) -> None:
        """
        With flag=2 (default) and 3 players, fires at move_number=7.

        7/3 = 2.33 > 2, so it fires. Matches previous Rule 203 behavior.
        """
        mock_game_manager.game_state = game_state_3_players
        game_loop = GameLoop(mock_game_manager, [], None)

        game_loop.game_manager.game_state.move_number = 7
        game_loop._check_majority_after_loops()

        assert (
            game_loop.game_manager.game_state.flags["vote_mode"] == "majority"
        )
        assert (
            game_loop.game_manager.game_state.flags["majority_after_loops"]
            is None
        )
        mock_game_manager.logger.log_transcript.assert_called_once()

    def test_flag_2_does_not_fire_at_move_6_with_3_players(
        self,
        mock_game_manager: Mock,
        game_state_3_players: GameState,
    ) -> None:
        """
        With flag=2 and 3 players, no transition at move_number=6.

        6/3 = 2.0, which is not > 2.
        """
        mock_game_manager.game_state = game_state_3_players
        game_loop = GameLoop(mock_game_manager, [], None)

        game_loop.game_manager.game_state.move_number = 6
        game_loop._check_majority_after_loops()

        assert (
            game_loop.game_manager.game_state.flags["vote_mode"] == "unanimous"
        )
        mock_game_manager.logger.log_transcript.assert_not_called()

    def test_flag_resets_to_none_after_transition(
        self,
        mock_game_manager: Mock,
        game_state_3_players: GameState,
    ) -> None:
        """After transition fires, majority_after_loops resets to None."""
        mock_game_manager.game_state = game_state_3_players
        game_loop = GameLoop(mock_game_manager, [], None)

        game_loop.game_manager.game_state.move_number = 7
        game_loop._check_majority_after_loops()

        assert (
            game_loop.game_manager.game_state.flags["majority_after_loops"]
            is None
        )

    def test_no_transition_when_already_majority(
        self,
        mock_game_manager: Mock,
        game_state_3_players: GameState,
    ) -> None:
        """No transition fires when vote_mode is already 'majority'."""
        game_state_3_players.flags["vote_mode"] = "majority"
        mock_game_manager.game_state = game_state_3_players
        game_loop = GameLoop(mock_game_manager, [], None)

        game_loop.game_manager.game_state.move_number = 7
        game_loop._check_majority_after_loops()

        assert (
            game_loop.game_manager.game_state.flags["vote_mode"] == "majority"
        )
        mock_game_manager.logger.log_transcript.assert_not_called()

    def test_transcript_entry_on_transition(
        self,
        mock_game_manager: Mock,
        game_state_3_players: GameState,
    ) -> None:
        """Transition logs an [ENGINE] transcript entry."""
        mock_game_manager.game_state = game_state_3_players
        game_loop = GameLoop(mock_game_manager, [], None)

        game_loop.game_manager.game_state.move_number = 7
        game_loop._check_majority_after_loops()

        mock_game_manager.logger.log_transcript.assert_called_once()
        transcript_call = mock_game_manager.logger.log_transcript.call_args[0][
            0
        ]
        assert "[ENGINE] Automatic transition" in transcript_call
        assert (
            "vote_mode changed from 'unanimous' to 'majority'"
            in transcript_call
        )

    def test_automatic_transitions_calls_majority_after_loops(
        self,
        mock_game_manager: Mock,
        game_state_3_players: GameState,
    ) -> None:
        """_check_automatic_transitions calls _check_majority_after_loops."""
        mock_game_manager.game_state = game_state_3_players
        game_loop = GameLoop(mock_game_manager, [], None)

        game_loop.game_manager.game_state.move_number = 7
        game_loop._check_automatic_transitions()

        assert (
            game_loop.game_manager.game_state.flags["vote_mode"] == "majority"
        )
        mock_game_manager.logger.log_transcript.assert_called_once()

    def test_transition_with_2_players(
        self,
        mock_game_manager: Mock,
        game_state_2_players: GameState,
    ) -> None:
        """With flag=2 and 2 players, transition fires at move_number=5."""
        mock_game_manager.game_state = game_state_2_players
        game_loop = GameLoop(mock_game_manager, [], None)

        # 5/2 = 2.5 > 2 → fires
        game_loop.game_manager.game_state.move_number = 5
        game_loop._check_majority_after_loops()

        assert (
            game_loop.game_manager.game_state.flags["vote_mode"] == "majority"
        )

    def test_no_transition_at_boundary_with_2_players(
        self,
        mock_game_manager: Mock,
        game_state_2_players: GameState,
    ) -> None:
        """With flag=2 and 2 players, no transition at move_number=4."""
        mock_game_manager.game_state = game_state_2_players
        game_loop = GameLoop(mock_game_manager, [], None)

        # 4/2 = 2.0, not > 2 → no transition
        game_loop.game_manager.game_state.move_number = 4
        game_loop._check_majority_after_loops()

        assert (
            game_loop.game_manager.game_state.flags["vote_mode"] == "unanimous"
        )
        mock_game_manager.logger.log_transcript.assert_not_called()

    def test_transition_does_not_retrigger_after_reset(
        self,
        mock_game_manager: Mock,
        game_state_3_players: GameState,
    ) -> None:
        """After flag resets to None, calling again does not retrigger."""
        mock_game_manager.game_state = game_state_3_players
        game_loop = GameLoop(mock_game_manager, [], None)

        game_loop.game_manager.game_state.move_number = 7
        game_loop._check_majority_after_loops()

        # Now flag is None and vote_mode is majority; call again
        game_loop.game_manager.game_state.move_number = 10
        game_loop._check_majority_after_loops()

        # Transcript only called once (from first transition)
        assert mock_game_manager.logger.log_transcript.call_count == 1
