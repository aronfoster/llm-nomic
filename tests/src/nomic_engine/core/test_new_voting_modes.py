"""
Unit tests for Sprint 37 Task 4: min_yes_votes and
unanimous_strict voting modes.

Covers:
1. min_yes_votes tally: threshold passes/fails correctly.
2. min_yes_votes tally with null flag: vote fails + logger.warning.
3. unanimous_strict tally: all YES passes; any NO or ABSTAIN fails.
4. VoteResult.vote_mode reflects new modes.
5. transmute_immutable_vote_mode = "min_yes_votes" integration.
6. Flag schema validation for new valid_values.
7. format_current_flags() integer rendering (no quotes).
"""

from unittest.mock import Mock, patch

import pytest

from src.nomic_engine.core.game_loop import GameLoop
from src.nomic_engine.core.game_manager import GameManager
from src.nomic_engine.data_models import (
    GameState,
    Proposal,
    ProposalType,
    Rule,
    RuleStatus,
    Vote,
)
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


def _make_game_loop(flags: dict) -> tuple[GameLoop, GameState]:
    """Build a GameLoop with the given flags."""
    game_state = GameState(
        scores={"Alice": 0, "Bob": 0, "Charlie": 0},
        current_player_name="Alice",
        move_number=1,
        turn_order=["Alice", "Bob", "Charlie"],
        next_proposal_id=301,
        target_score=100,
        flags=flags,
    )

    manager = Mock(spec=GameManager)
    manager.game_state = game_state

    rules_manager = Mock()
    rules_manager.rules = []
    rules_manager._find_rule_by_id = Mock(return_value=None)
    manager.rules_manager = rules_manager

    log = Mock()
    log.log_transcript = Mock()
    log.log_event = Mock()
    manager.logger = log

    manager.save_game_state = Mock()
    manager.save_rules = Mock()
    manager.game_config = None

    game_loop = GameLoop(game_manager=manager, players=[])
    return game_loop, game_state


def _make_game_loop_with_rule(
    flags: dict, rule: Rule
) -> tuple[GameLoop, GameState]:
    """Build a GameLoop with the given flags and a rule stub."""
    game_loop, game_state = _make_game_loop(flags)
    game_loop.game_manager.rules_manager.rules = [rule]
    game_loop.game_manager.rules_manager._find_rule_by_id = Mock(
        return_value=rule
    )
    return game_loop, game_state


# =========================================================================
# 1. min_yes_votes tally
# =========================================================================


class TestMinYesVotesTally:
    """Tests for the min_yes_votes voting mode tally logic."""

    def test_threshold_2_with_2_yes_passes(self) -> None:
        """2 YES votes meets threshold of 2 — passes."""
        game_loop, _ = _make_game_loop(
            {"vote_mode": "min_yes_votes", "min_yes_votes": 2}
        )
        votes = [
            Vote(player_name="Alice", vote="YES"),
            Vote(player_name="Bob", vote="YES"),
            Vote(player_name="Charlie", vote="NO"),
        ]
        result = game_loop._tally_vote_results(votes)
        assert result.passed is True
        assert result.vote_mode == "min_yes_votes"

    def test_threshold_2_with_1_yes_fails(self) -> None:
        """1 YES vote does not meet threshold of 2 — fails."""
        game_loop, _ = _make_game_loop(
            {"vote_mode": "min_yes_votes", "min_yes_votes": 2}
        )
        votes = [
            Vote(player_name="Alice", vote="YES"),
            Vote(player_name="Bob", vote="NO"),
            Vote(player_name="Charlie", vote="NO"),
        ]
        result = game_loop._tally_vote_results(votes)
        assert result.passed is False
        assert result.vote_mode == "min_yes_votes"

    def test_threshold_2_with_3_yes_passes(self) -> None:
        """3 YES votes exceeds threshold of 2 — passes."""
        game_loop, _ = _make_game_loop(
            {"vote_mode": "min_yes_votes", "min_yes_votes": 2}
        )
        votes = [
            Vote(player_name="Alice", vote="YES"),
            Vote(player_name="Bob", vote="YES"),
            Vote(player_name="Charlie", vote="YES"),
        ]
        result = game_loop._tally_vote_results(votes)
        assert result.passed is True
        assert result.vote_mode == "min_yes_votes"

    def test_threshold_3_with_2_yes_and_1_no_fails(self) -> None:
        """2 YES + 1 NO does not reach threshold of 3 — fails."""
        game_loop, _ = _make_game_loop(
            {"vote_mode": "min_yes_votes", "min_yes_votes": 3}
        )
        votes = [
            Vote(player_name="Alice", vote="YES"),
            Vote(player_name="Bob", vote="YES"),
            Vote(player_name="Charlie", vote="NO"),
        ]
        result = game_loop._tally_vote_results(votes)
        assert result.passed is False
        assert result.vote_mode == "min_yes_votes"

    def test_vote_result_vote_mode_is_min_yes_votes(self) -> None:
        """VoteResult.vote_mode is 'min_yes_votes' regardless of outcome."""
        game_loop, _ = _make_game_loop(
            {"vote_mode": "min_yes_votes", "min_yes_votes": 1}
        )
        votes = [Vote(player_name="Alice", vote="NO")]
        result = game_loop._tally_vote_results(votes)
        assert result.vote_mode == "min_yes_votes"


# =========================================================================
# 2. min_yes_votes tally with null flag
# =========================================================================


class TestMinYesVotesNullFlag:
    """Tests for min_yes_votes mode when the threshold flag is null."""

    def test_null_min_yes_votes_flag_vote_fails(self) -> None:
        """vote_mode='min_yes_votes' but min_yes_votes=null → fails."""
        game_loop, _ = _make_game_loop(
            {"vote_mode": "min_yes_votes", "min_yes_votes": None}
        )
        votes = [
            Vote(player_name="Alice", vote="YES"),
            Vote(player_name="Bob", vote="YES"),
            Vote(player_name="Charlie", vote="YES"),
        ]
        result = game_loop._tally_vote_results(votes)
        assert result.passed is False

    def test_null_min_yes_votes_flag_logs_warning(self) -> None:
        """vote_mode='min_yes_votes' but min_yes_votes=null → warning."""
        game_loop, _ = _make_game_loop(
            {"vote_mode": "min_yes_votes", "min_yes_votes": None}
        )
        votes = [Vote(player_name="Alice", vote="YES")]
        with patch("src.nomic_engine.core.game_loop.logger") as mock_logger:
            game_loop._tally_vote_results(votes)
            mock_logger.warning.assert_called_once()
            assert "min_yes_votes" in mock_logger.warning.call_args[0][0]

    def test_null_min_yes_votes_flag_vote_mode_still_set(self) -> None:
        """VoteResult.vote_mode is 'min_yes_votes' even when flag is null."""
        game_loop, _ = _make_game_loop(
            {"vote_mode": "min_yes_votes", "min_yes_votes": None}
        )
        votes = [Vote(player_name="Alice", vote="YES")]
        result = game_loop._tally_vote_results(votes)
        assert result.vote_mode == "min_yes_votes"


# =========================================================================
# 3. unanimous_strict tally
# =========================================================================


class TestUnanimousStrictTally:
    """Tests for the unanimous_strict voting mode tally logic."""

    def test_all_yes_passes(self) -> None:
        """All YES votes — passes."""
        game_loop, _ = _make_game_loop({"vote_mode": "unanimous_strict"})
        votes = [
            Vote(player_name="Alice", vote="YES"),
            Vote(player_name="Bob", vote="YES"),
            Vote(player_name="Charlie", vote="YES"),
        ]
        result = game_loop._tally_vote_results(votes)
        assert result.passed is True
        assert result.vote_mode == "unanimous_strict"

    def test_two_yes_one_no_fails(self) -> None:
        """2 YES + 1 NO — fails (any NO causes failure)."""
        game_loop, _ = _make_game_loop({"vote_mode": "unanimous_strict"})
        votes = [
            Vote(player_name="Alice", vote="YES"),
            Vote(player_name="Bob", vote="YES"),
            Vote(player_name="Charlie", vote="NO"),
        ]
        result = game_loop._tally_vote_results(votes)
        assert result.passed is False
        assert result.vote_mode == "unanimous_strict"

    def test_two_yes_one_abstain_fails(self) -> None:
        """2 YES + 1 ABSTAIN — fails (any non-YES causes failure)."""
        game_loop, _ = _make_game_loop({"vote_mode": "unanimous_strict"})
        votes = [
            Vote(player_name="Alice", vote="YES"),
            Vote(player_name="Bob", vote="YES"),
            Vote(player_name="Charlie", vote="ABSTAIN"),
        ]
        result = game_loop._tally_vote_results(votes)
        assert result.passed is False
        assert result.vote_mode == "unanimous_strict"

    def test_single_yes_passes(self) -> None:
        """Single voter with YES — passes."""
        game_loop, _ = _make_game_loop({"vote_mode": "unanimous_strict"})
        votes = [Vote(player_name="Alice", vote="YES")]
        result = game_loop._tally_vote_results(votes)
        assert result.passed is True

    def test_vote_result_vote_mode_is_unanimous_strict(self) -> None:
        """VoteResult.vote_mode is 'unanimous_strict' regardless."""
        game_loop, _ = _make_game_loop({"vote_mode": "unanimous_strict"})
        votes = [Vote(player_name="Alice", vote="NO")]
        result = game_loop._tally_vote_results(votes)
        assert result.vote_mode == "unanimous_strict"


# =========================================================================
# 4. transmute_immutable_vote_mode = "min_yes_votes" integration
# =========================================================================


class TestTransmuteImmutableMinYesVotes:
    """Tests for transmute_immutable_vote_mode='min_yes_votes'."""

    def test_immutable_transmute_min_yes_votes_override(self) -> None:
        """IMMUTABLE→MUTABLE TRANSMUTE with override='min_yes_votes'
        and min_yes_votes=2: 2 YES passes."""
        immutable_rule = Rule(
            rule_id="101",
            text="An immutable rule.",
            status=RuleStatus.IMMUTABLE,
        )
        game_loop, _ = _make_game_loop_with_rule(
            {
                "vote_mode": "unanimous",
                "transmute_immutable_vote_mode": "min_yes_votes",
                "min_yes_votes": 2,
            },
            immutable_rule,
        )
        proposal = Proposal(
            proposer_name="Alice",
            move_number=1,
            type=ProposalType.TRANSMUTE,
            proposal_id="301",
            target_rule_id="101",
        )
        votes = [
            Vote(player_name="Alice", vote="YES"),
            Vote(player_name="Bob", vote="YES"),
            Vote(player_name="Charlie", vote="NO"),
        ]
        override = game_loop._resolve_effective_vote_mode(proposal)
        result = game_loop._tally_vote_results(votes, override)

        assert result.passed is True
        assert result.vote_mode == "min_yes_votes"

    def test_immutable_transmute_min_yes_votes_insufficient(self) -> None:
        """IMMUTABLE→MUTABLE TRANSMUTE with min_yes_votes=3: 2 YES fails."""
        immutable_rule = Rule(
            rule_id="101",
            text="An immutable rule.",
            status=RuleStatus.IMMUTABLE,
        )
        game_loop, _ = _make_game_loop_with_rule(
            {
                "vote_mode": "unanimous",
                "transmute_immutable_vote_mode": "min_yes_votes",
                "min_yes_votes": 3,
            },
            immutable_rule,
        )
        proposal = Proposal(
            proposer_name="Alice",
            move_number=1,
            type=ProposalType.TRANSMUTE,
            proposal_id="301",
            target_rule_id="101",
        )
        votes = [
            Vote(player_name="Alice", vote="YES"),
            Vote(player_name="Bob", vote="YES"),
            Vote(player_name="Charlie", vote="NO"),
        ]
        override = game_loop._resolve_effective_vote_mode(proposal)
        result = game_loop._tally_vote_results(votes, override)

        assert result.passed is False
        assert result.vote_mode == "min_yes_votes"


# =========================================================================
# 5. Flag schema validation
# =========================================================================


class TestNewVoteModeValidation:
    """Flag schema validation tests for new vote_mode values."""

    def test_vote_mode_accepts_min_yes_votes(self) -> None:
        """'min_yes_votes' is a valid vote_mode value."""
        validate_flag_value("vote_mode", "min_yes_votes")

    def test_vote_mode_accepts_unanimous_strict(self) -> None:
        """'unanimous_strict' is a valid vote_mode value."""
        validate_flag_value("vote_mode", "unanimous_strict")

    def test_transmute_mode_accepts_min_yes_votes(self) -> None:
        """'min_yes_votes' is valid for transmute_immutable_vote_mode."""
        validate_flag_value("transmute_immutable_vote_mode", "min_yes_votes")

    def test_transmute_mode_accepts_unanimous_strict(self) -> None:
        """'unanimous_strict' is valid for transmute_immutable_vote_mode."""
        validate_flag_value(
            "transmute_immutable_vote_mode", "unanimous_strict"
        )

    def test_transmute_mode_rejects_other_string(self) -> None:
        """Other strings are still rejected for the transmute flag."""
        with pytest.raises(ValueError, match="not valid"):
            validate_flag_value("transmute_immutable_vote_mode", "consensus")

    def test_state_updates_accepts_vote_mode_min_yes_votes(self) -> None:
        """StateUpdates with vote_mode='min_yes_votes' is valid."""
        validate_state_updates({"flags": {"vote_mode": "min_yes_votes"}})

    def test_state_updates_accepts_vote_mode_unanimous_strict(
        self,
    ) -> None:
        """StateUpdates with vote_mode='unanimous_strict' is valid."""
        validate_state_updates({"flags": {"vote_mode": "unanimous_strict"}})

    def test_state_updates_accepts_transmute_min_yes_votes(self) -> None:
        """StateUpdates with transmute override='min_yes_votes' is valid."""
        validate_state_updates(
            {"flags": {"transmute_immutable_vote_mode": "min_yes_votes"}}
        )


# =========================================================================
# 6. min_yes_votes flag schema validation
# =========================================================================


class TestMinYesVotesFlagValidation:
    """Flag schema validation tests for the min_yes_votes flag itself."""

    def test_accepts_positive_integer(self) -> None:
        """Positive integers are valid for min_yes_votes."""
        validate_flag_value("min_yes_votes", 1)
        validate_flag_value("min_yes_votes", 3)
        validate_flag_value("min_yes_votes", 10)

    def test_accepts_null(self) -> None:
        """None is valid (nullable=true)."""
        validate_flag_value("min_yes_votes", None)

    def test_rejects_float(self) -> None:
        """Floats are rejected (type mismatch)."""
        with pytest.raises(ValueError, match="expects type"):
            validate_flag_value("min_yes_votes", 2.5)

    def test_rejects_string(self) -> None:
        """Strings are rejected (type mismatch)."""
        with pytest.raises(ValueError, match="expects type"):
            validate_flag_value("min_yes_votes", "3")

    def test_state_updates_accepts_min_yes_votes_integer(self) -> None:
        """StateUpdates with min_yes_votes=3 is valid."""
        validate_state_updates({"flags": {"min_yes_votes": 3}})

    def test_state_updates_accepts_min_yes_votes_null(self) -> None:
        """StateUpdates with min_yes_votes=null is valid."""
        validate_state_updates({"flags": {"min_yes_votes": None}})


# =========================================================================
# 7. format_current_flags integer rendering
# =========================================================================


class TestFormatCurrentFlagsIntegerRendering:
    """Tests for integer flag rendering without quotes."""

    def test_min_yes_votes_integer_renders_without_quotes(self) -> None:
        """min_yes_votes: 3 renders as '- min_yes_votes: 3' (no quotes)."""
        result = format_current_flags({"min_yes_votes": 3})
        assert "- min_yes_votes: 3" in result
        assert '"3"' not in result

    def test_majority_after_loops_renders_without_quotes(self) -> None:
        """majority_after_loops: 2 renders without quotes."""
        result = format_current_flags({"majority_after_loops": 2})
        assert "- majority_after_loops: 2" in result
        assert '"2"' not in result

    def test_allow_abstention_bool_still_renders_without_quotes(
        self,
    ) -> None:
        """allow_abstention boolean still renders without quotes."""
        result = format_current_flags({"allow_abstention": True})
        assert "- allow_abstention: true" in result
        result2 = format_current_flags({"allow_abstention": False})
        assert "- allow_abstention: false" in result2

    def test_min_yes_votes_null_renders_as_null(self) -> None:
        """min_yes_votes: null renders as '- min_yes_votes: null'."""
        result = format_current_flags({"min_yes_votes": None})
        assert "- min_yes_votes: null" in result

    def test_string_flag_still_renders_with_quotes(self) -> None:
        """String flags still render with quotes."""
        result = format_current_flags({"vote_mode": "unanimous"})
        assert '- vote_mode: "unanimous"' in result
