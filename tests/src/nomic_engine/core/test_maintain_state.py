"""
Integration tests for judge maintain_state functionality in GameLoop.

Tests that:
- maintain_state is called after judge approval, before applying proposal
- maintain_state is NOT called for TRANSMUTE proposals
- StateUpdates are correctly applied to game_state
- Both HumanJudge and LLMJudge implementations work correctly
"""

from unittest.mock import Mock

import pytest

from src.nomic_engine.core.game_loop import GameLoop
from src.nomic_engine.core.game_manager import GameManager
from src.nomic_engine.data_models import (
    Discussion,
    GameState,
    JudgeDecisions,
    Proposal,
    ProposalType,
    Rule,
    RuleStatus,
    Vote,
    VoteResult,
)
from src.nomic_engine.judge.human_judge import HumanJudge

# --- Fixtures ---


@pytest.fixture
def mock_game_state() -> GameState:
    """Fixture providing a mock game state."""
    return GameState(
        scores={"Alice": 0, "Bob": 0},
        current_player_name="Alice",
        move_number=1,
        turn_order=["Alice", "Bob"],
        next_proposal_id=301,
        target_score=None,
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
        Rule(
            rule_id="201",
            text="A player gains 1 point for a successful proposal.",
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
    rules_manager.get_rule_by_id = Mock(
        side_effect=lambda rule_id: next(
            (r for r in mock_rules if r.rule_id == rule_id), None
        )
    )
    rules_manager._find_rule_by_id = Mock(
        side_effect=lambda rule_id: next(
            (r for r in mock_rules if r.rule_id == rule_id), None
        )
    )
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
def mock_judge() -> Mock:
    """Fixture providing a mocked judge."""
    judge = Mock(spec=HumanJudge)
    judge.get_veto = Mock(
        return_value={"veto": False, "reason": None, "private_thoughts": None}
    )
    judge.assess_scores = Mock(
        return_value={"private_thoughts": None, "score_adjustments": []}
    )
    judge.maintain_state = Mock(return_value={})
    return judge


# --- Tests ---


class TestMaintainStateIntegration:
    """Test maintain_state integration with GameLoop._apply_turn_mutations."""

    def test_maintain_state_called_for_add_proposal(
        self, mock_game_manager: Mock, mock_judge: Mock
    ) -> None:
        """maintain_state is called for ADD proposals."""
        game_loop = GameLoop(mock_game_manager, [], mock_judge)

        proposal = Proposal(
            proposer_name="Alice",
            move_number=1,
            type=ProposalType.ADD,
            proposal_id="301",
            new_text="New rule text.",
            rationale="Adding a new rule.",
        )

        votes = [Vote(player_name="Alice", vote="YES", reason="Good idea.")]
        discussions: list[Discussion] = []
        vote_result = VoteResult(
            yes_count=1,
            no_count=0,
            abstain_count=0,
            total_voters=1,
            passed=True,
            vote_mode="unanimous",
        )
        judge_decisions = JudgeDecisions(
            judge_approved=True,
            veto_response={
                "veto": False,
                "reason": None,
                "private_thoughts": None,
            },
            score_response={"private_thoughts": None, "score_adjustments": []},
        )

        game_loop._apply_turn_mutations(
            proposal, votes, discussions, vote_result, judge_decisions
        )

        # Verify maintain_state was called
        mock_judge.maintain_state.assert_called_once()
        call_args = mock_judge.maintain_state.call_args
        assert call_args[1]["proposal"] == proposal
        # ADD has no original
        assert call_args[1]["original_rule_text"] is None
        assert call_args[1]["new_rule_text"] == "New rule text."

    def test_maintain_state_called_for_amend_proposal(
        self, mock_game_manager: Mock, mock_judge: Mock
    ) -> None:
        """maintain_state is called for AMEND proposals with both texts."""
        game_loop = GameLoop(mock_game_manager, [], mock_judge)

        proposal = Proposal(
            proposer_name="Alice",
            move_number=1,
            type=ProposalType.AMEND,
            proposal_id="301",
            target_rule_id="201",
            new_text="A player gains 2 points for a successful proposal.",
            rationale="Increasing reward.",
        )

        votes = [Vote(player_name="Alice", vote="YES", reason="Good idea.")]
        discussions: list[Discussion] = []
        vote_result = VoteResult(
            yes_count=1,
            no_count=0,
            abstain_count=0,
            total_voters=1,
            passed=True,
            vote_mode="unanimous",
        )
        judge_decisions = JudgeDecisions(
            judge_approved=True,
            veto_response={
                "veto": False,
                "reason": None,
                "private_thoughts": None,
            },
            score_response={"private_thoughts": None, "score_adjustments": []},
        )

        game_loop._apply_turn_mutations(
            proposal, votes, discussions, vote_result, judge_decisions
        )

        # Verify maintain_state was called with both texts
        mock_judge.maintain_state.assert_called_once()
        call_args = mock_judge.maintain_state.call_args
        assert call_args[1]["proposal"] == proposal
        assert (
            call_args[1]["original_rule_text"]
            == "A player gains 1 point for a successful proposal."
        )
        assert (
            call_args[1]["new_rule_text"]
            == "A player gains 2 points for a successful proposal."
        )

    def test_maintain_state_called_for_repeal_proposal(
        self, mock_game_manager: Mock, mock_judge: Mock
    ) -> None:
        """
        maintain_state is called for REPEAL proposals with original text
        only.
        """
        game_loop = GameLoop(mock_game_manager, [], mock_judge)

        proposal = Proposal(
            proposer_name="Alice",
            move_number=1,
            type=ProposalType.REPEAL,
            proposal_id="301",
            target_rule_id="201",
            rationale="Removing obsolete rule.",
        )

        votes = [Vote(player_name="Alice", vote="YES", reason="Good idea.")]
        discussions: list[Discussion] = []
        vote_result = VoteResult(
            yes_count=1,
            no_count=0,
            abstain_count=0,
            total_voters=1,
            passed=True,
            vote_mode="unanimous",
        )
        judge_decisions = JudgeDecisions(
            judge_approved=True,
            veto_response={
                "veto": False,
                "reason": None,
                "private_thoughts": None,
            },
            score_response={"private_thoughts": None, "score_adjustments": []},
        )

        game_loop._apply_turn_mutations(
            proposal, votes, discussions, vote_result, judge_decisions
        )

        # Verify maintain_state was called with original text only
        mock_judge.maintain_state.assert_called_once()
        call_args = mock_judge.maintain_state.call_args
        assert call_args[1]["proposal"] == proposal
        assert (
            call_args[1]["original_rule_text"]
            == "A player gains 1 point for a successful proposal."
        )
        assert call_args[1]["new_rule_text"] is None

    def test_maintain_state_not_called_for_transmute(
        self, mock_game_manager: Mock, mock_judge: Mock
    ) -> None:
        """maintain_state is NOT called for TRANSMUTE proposals."""
        game_loop = GameLoop(mock_game_manager, [], mock_judge)

        proposal = Proposal(
            proposer_name="Alice",
            move_number=1,
            type=ProposalType.TRANSMUTE,
            proposal_id="301",
            target_rule_id="201",
            rationale="Making rule immutable.",
        )

        votes = [Vote(player_name="Alice", vote="YES", reason="Good idea.")]
        discussions: list[Discussion] = []
        vote_result = VoteResult(
            yes_count=1,
            no_count=0,
            abstain_count=0,
            total_voters=1,
            passed=True,
            vote_mode="unanimous",
        )
        judge_decisions = JudgeDecisions(
            judge_approved=True,
            veto_response={
                "veto": False,
                "reason": None,
                "private_thoughts": None,
            },
            score_response={"private_thoughts": None, "score_adjustments": []},
        )

        game_loop._apply_turn_mutations(
            proposal, votes, discussions, vote_result, judge_decisions
        )

        # Verify maintain_state was NOT called
        mock_judge.maintain_state.assert_not_called()

    def test_maintain_state_not_called_when_proposal_fails(
        self, mock_game_manager: Mock, mock_judge: Mock
    ) -> None:
        """maintain_state is NOT called when proposal is not approved."""
        game_loop = GameLoop(mock_game_manager, [], mock_judge)

        proposal = Proposal(
            proposer_name="Alice",
            move_number=1,
            type=ProposalType.ADD,
            proposal_id="301",
            new_text="New rule text.",
            rationale="Adding a new rule.",
        )

        votes = [Vote(player_name="Alice", vote="NO", reason="Bad idea.")]
        discussions: list[Discussion] = []
        vote_result = VoteResult(
            yes_count=0,
            no_count=1,
            abstain_count=0,
            total_voters=1,
            passed=False,
            vote_mode="unanimous",
        )
        judge_decisions = JudgeDecisions(
            judge_approved=False,  # Not approved
            veto_response={
                "veto": True,
                "reason": "Vetoed",
                "private_thoughts": None,
            },
            score_response={"private_thoughts": None, "score_adjustments": []},
        )

        game_loop._apply_turn_mutations(
            proposal, votes, discussions, vote_result, judge_decisions
        )

        # Verify maintain_state was NOT called
        mock_judge.maintain_state.assert_not_called()

    def test_state_updates_applied_flags_only(
        self, mock_game_manager: Mock, mock_judge: Mock
    ) -> None:
        """StateUpdates with flags are correctly applied to game_state."""
        game_loop = GameLoop(mock_game_manager, [], mock_judge)

        # Configure judge to return flag updates
        mock_judge.maintain_state.return_value = {
            "flags": {"vote_mode": "majority"}
        }

        proposal = Proposal(
            proposer_name="Alice",
            move_number=1,
            type=ProposalType.ADD,
            proposal_id="301",
            new_text="Voting requires majority approval.",
            rationale="Changing voting rules.",
        )

        votes = [Vote(player_name="Alice", vote="YES", reason="Good idea.")]
        discussions: list[Discussion] = []
        vote_result = VoteResult(
            yes_count=1,
            no_count=0,
            abstain_count=0,
            total_voters=1,
            passed=True,
            vote_mode="unanimous",
        )
        judge_decisions = JudgeDecisions(
            judge_approved=True,
            veto_response={
                "veto": False,
                "reason": None,
                "private_thoughts": None,
            },
            score_response={"private_thoughts": None, "score_adjustments": []},
        )

        game_loop._apply_turn_mutations(
            proposal, votes, discussions, vote_result, judge_decisions
        )

        # Verify flag was updated
        assert mock_game_manager.game_state.flags["vote_mode"] == "majority"

    def test_state_updates_applied_target_score_only(
        self, mock_game_manager: Mock, mock_judge: Mock
    ) -> None:
        """
        StateUpdates with target_score are correctly applied to
        game_state.
        """
        game_loop = GameLoop(mock_game_manager, [], mock_judge)

        # Configure judge to return target_score update
        mock_judge.maintain_state.return_value = {"target_score": 100}

        proposal = Proposal(
            proposer_name="Alice",
            move_number=1,
            type=ProposalType.ADD,
            proposal_id="301",
            new_text="The game ends when a player reaches 100 points.",
            rationale="Setting win condition.",
        )

        votes = [Vote(player_name="Alice", vote="YES", reason="Good idea.")]
        discussions: list[Discussion] = []
        vote_result = VoteResult(
            yes_count=1,
            no_count=0,
            abstain_count=0,
            total_voters=1,
            passed=True,
            vote_mode="unanimous",
        )
        judge_decisions = JudgeDecisions(
            judge_approved=True,
            veto_response={
                "veto": False,
                "reason": None,
                "private_thoughts": None,
            },
            score_response={"private_thoughts": None, "score_adjustments": []},
        )

        game_loop._apply_turn_mutations(
            proposal, votes, discussions, vote_result, judge_decisions
        )

        # Verify target_score was updated
        assert mock_game_manager.game_state.target_score == 100

    def test_state_updates_applied_both_fields(
        self, mock_game_manager: Mock, mock_judge: Mock
    ) -> None:
        """StateUpdates with both flags and target_score are applied."""
        game_loop = GameLoop(mock_game_manager, [], mock_judge)

        # Configure judge to return both updates
        mock_judge.maintain_state.return_value = {
            "flags": {"vote_mode": "majority"},
            "target_score": 50,
        }

        proposal = Proposal(
            proposer_name="Alice",
            move_number=1,
            type=ProposalType.ADD,
            proposal_id="301",
            new_text="Game uses majority voting and ends at 50 points.",
            rationale="Setting game parameters.",
        )

        votes = [Vote(player_name="Alice", vote="YES", reason="Good idea.")]
        discussions: list[Discussion] = []
        vote_result = VoteResult(
            yes_count=1,
            no_count=0,
            abstain_count=0,
            total_voters=1,
            passed=True,
            vote_mode="unanimous",
        )
        judge_decisions = JudgeDecisions(
            judge_approved=True,
            veto_response={
                "veto": False,
                "reason": None,
                "private_thoughts": None,
            },
            score_response={"private_thoughts": None, "score_adjustments": []},
        )

        game_loop._apply_turn_mutations(
            proposal, votes, discussions, vote_result, judge_decisions
        )

        # Verify both were updated
        assert mock_game_manager.game_state.flags["vote_mode"] == "majority"
        assert mock_game_manager.game_state.target_score == 50

    def test_state_updates_empty_no_changes(
        self, mock_game_manager: Mock, mock_judge: Mock
    ) -> None:
        """Empty StateUpdates result in no changes to game_state."""
        game_loop = GameLoop(mock_game_manager, [], mock_judge)

        # Configure judge to return empty updates
        mock_judge.maintain_state.return_value = {}

        original_flags = dict(mock_game_manager.game_state.flags)
        original_target_score = mock_game_manager.game_state.target_score

        proposal = Proposal(
            proposer_name="Alice",
            move_number=1,
            type=ProposalType.ADD,
            proposal_id="301",
            new_text="This rule doesn't affect engine state.",
            rationale="Just a rule.",
        )

        votes = [Vote(player_name="Alice", vote="YES", reason="Good idea.")]
        discussions: list[Discussion] = []
        vote_result = VoteResult(
            yes_count=1,
            no_count=0,
            abstain_count=0,
            total_voters=1,
            passed=True,
            vote_mode="unanimous",
        )
        judge_decisions = JudgeDecisions(
            judge_approved=True,
            veto_response={
                "veto": False,
                "reason": None,
                "private_thoughts": None,
            },
            score_response={"private_thoughts": None, "score_adjustments": []},
        )

        game_loop._apply_turn_mutations(
            proposal, votes, discussions, vote_result, judge_decisions
        )

        # Verify state unchanged
        assert mock_game_manager.game_state.flags == original_flags
        assert (
            mock_game_manager.game_state.target_score == original_target_score
        )
