"""
Unit tests for the PromptBuilder class.

These tests verify that the PromptBuilder correctly builds incremental
context blocks (System or User messages) using the atomized prompt templates.

Sprint 6: Tests now verify single ChatMessage outputs instead of message lists.
"""

import unittest
from unittest.mock import patch

from src.nomic_engine.data_models import (
    ChatMessage,
    Discussion,
    GameState,
    Proposal,
    ProposalType,
    Rule,
    RuleStatus,
    Vote,
)
from src.nomic_engine.llm.prompt_builder import PromptBuilder


class TestPromptBuilder(unittest.TestCase):
    """Test cases for the PromptBuilder class."""

    def setUp(self):
        """Set up test fixtures that are used across multiple tests."""
        self.builder = PromptBuilder()

        # Create sample game state
        self.game_state = GameState(
            scores={"Alice": 10, "Bob": 5, "Charlie": 3},
            current_player_name="Alice",
            move_number=5,
            turn_order=["Alice", "Bob", "Charlie"],
            next_proposal_id=305,
        )

        # Create sample rules
        self.rules = [
            Rule(
                rule_id="101",
                text="All players must vote on proposals.",
                status=RuleStatus.IMMUTABLE,
            ),
            Rule(
                rule_id="201",
                text="Players gain 1 point for successful proposals.",
                status=RuleStatus.MUTABLE,
            ),
        ]

        # Create sample proposal
        self.proposal = Proposal(
            proposer_name="Bob",
            move_number=5,
            type=ProposalType.AMEND,
            proposal_id="304",
            target_rule_id="201",
            new_text="Players gain 2 points for successful proposals.",
            rationale="This encourages more active participation.",
        )

        # Create sample discussions
        self.discussions = [
            Discussion(
                player_name="Alice",
                text="I think this is a good idea.",
            ),
            Discussion(
                player_name="Charlie",
                text="I'm not sure about this change.",
            ),
        ]

        self.votes = [
            Vote(player_name="Alice", vote="YES", reason="Great rule"),
            Vote(player_name="Charlie", vote="NO", reason="Too strong"),
        ]

    # =========================================================================
    # Tests for helper methods
    # =========================================================================

    def test_format_rules(self):
        """Test that _format_rules correctly formats a list of rules."""
        result = self.builder._format_rules(self.rules)

        # Verify the format includes rule IDs, status, and text
        self.assertIn("### 101 (Immutable):", result)
        self.assertIn("All players must vote on proposals.", result)
        self.assertIn("### 201 (Mutable):", result)
        self.assertIn("Players gain 1 point for successful proposals.", result)

    def test_format_rules_empty(self):
        """Test that _format_rules handles empty rule lists."""
        result = self.builder._format_rules([])
        self.assertEqual(result, "No rules defined.")

    def test_format_scores(self):
        """Test that _format_scores correctly formats the scores dictionary."""
        result = self.builder._format_scores(self.game_state.scores)

        # Verify scores are sorted by value (descending)
        lines = result.split("\n")
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0], "- Alice: 10")
        self.assertEqual(lines[1], "- Bob: 5")
        self.assertEqual(lines[2], "- Charlie: 3")

    def test_format_scores_empty(self):
        """Test that _format_scores handles empty score dictionaries."""
        result = self.builder._format_scores({})
        self.assertEqual(result, "No scores yet.")

    def test_build_leaderboard_context_rank_goal_and_parity(self):
        """Leaderboard context should include rank, goal, and turn parity."""
        state = GameState(
            scores={"Claude": 45, "Gemini": 42, "GPT-4o": 38},
            target_score=50,
            current_player_name="GPT-4o",
            move_number=11,
            turn_order=["Claude", "Gemini", "GPT-4o"],
            next_proposal_id=312,
        )

        context = self.builder._build_leaderboard_context(state, "GPT-4o")

        self.assertIn("LEADERBOARD CONTEXT:", context)
        self.assertIn("Rank: 3rd.", context)
        self.assertIn(
            "Leaderboard: 1. Claude (45), 2. Gemini (42), 3. GPT-4o (38).",
            context,
        )
        self.assertIn(
            "Goal: 12 points required to reach the target score of 50.",
            context,
        )
        self.assertIn("This is your 4th turn.", context)
        self.assertIn("Claude has completed 4 turns", context)
        self.assertIn("Gemini has completed 3 turns", context)

    def test_build_leaderboard_context_tie_and_no_target(self):
        """Leaderboard context should call out ties and missing target."""
        state = GameState(
            scores={"Claude": 48, "Gemini": 48, "GPT-4o": 40},
            target_score=None,
            current_player_name="Claude",
            move_number=14,
            turn_order=["Claude", "Gemini", "GPT-4o"],
            next_proposal_id=318,
        )

        context = self.builder._build_leaderboard_context(state, "Claude")

        self.assertIn("Rank: 1st (Tied with Gemini).", context)
        self.assertIn("Goal: No target score is configured.", context)

    def test_format_game_state_block_includes_leaderboard_context(self):
        """GAME_STATE block should embed strategic leaderboard context."""
        block = self.builder._format_game_state_block(self.game_state, "Alice")

        self.assertIn("LEADERBOARD CONTEXT:", block)
        self.assertIn("Rank:", block)
        self.assertIn("Turn Parity:", block)

    def test_format_discussions(self):
        """Test _format_discussions correctly formats discussion tuples."""
        result = self.builder._format_discussions(self.discussions)

        # Verify the format includes player names and messages
        self.assertIn("**Alice:** I think this is a good idea.", result)
        self.assertIn("**Charlie:** I'm not sure about this change.", result)

    # =========================================================================
    # Judge prompt helpers
    # =========================================================================

    def test_build_judge_context_message_includes_sections(self):
        """Judge context message should include rules, votes, and scores."""

        message = self.builder.build_judge_context_message(
            rules=self.rules,
            game_state=self.game_state,
            proposal=self.proposal,
            votes=self.votes,
            discussions=self.discussions,
        )

        self.assertEqual(message.role, "user")
        self.assertIn("=== ALL CURRENT RULES ===", message.content)
        self.assertIn("=== DISCUSSIONS ===", message.content)
        self.assertIn("=== VOTES ===", message.content)
        self.assertIn("=== SCORES ===", message.content)
        self.assertIn("Alice: YES", message.content)
        self.assertIn("Charlie: NO", message.content)

    def test_build_judge_veto_prompt_enforces_json(self):
        """Veto prompt should include format enforcement instructions."""

        message = self.builder.build_judge_veto_prompt()

        self.assertEqual(message.role, "user")
        self.assertIn("Review the proposal outcome", message.content)
        self.assertIn("OUTPUT REQUIREMENTS", message.content)

    def test_build_judge_score_prompt_enforces_json(self):
        """Score prompt should include examples and JSON enforcement."""

        message = self.builder.build_judge_score_prompt(proposal_passed=True)

        self.assertEqual(message.role, "user")
        self.assertIn("Assign score changes for this move", message.content)
        self.assertIn("score_adjustments", message.content)
        self.assertIn("OUTPUT REQUIREMENTS", message.content)
        self.assertIn("PASSED", message.content)

    def test_format_discussions_empty(self):
        """Test that _format_discussions handles empty discussion lists."""
        result = self.builder._format_discussions([])
        self.assertEqual(result, "No discussions yet.")

    def test_get_player_position_first(self):
        """Test _get_player_position calculates position for first."""
        result = self.builder._get_player_position("Alice", self.game_state)
        self.assertEqual(result, "1 of 3")

    def test_get_player_position_middle(self):
        """Test _get_player_position calculates position for middle."""
        result = self.builder._get_player_position("Bob", self.game_state)
        self.assertEqual(result, "2 of 3")

    def test_get_player_position_last(self):
        """Test _get_player_position calculates position for last."""
        result = self.builder._get_player_position("Charlie", self.game_state)
        self.assertEqual(result, "3 of 3")

    def test_get_player_position_not_found(self):
        """Test _get_player_position raises ValueError for unknown."""
        with self.assertRaises(ValueError) as context:
            self.builder._get_player_position("Unknown", self.game_state)

        self.assertIn("Unknown", str(context.exception))
        self.assertIn("not found in turn order", str(context.exception))

    def test_format_proposal(self):
        """Test _format_proposal correctly formats a proposal."""
        result = self.builder._format_proposal(
            self.proposal, self.rules, "Charlie"
        )

        # Verify proposal details are included
        self.assertIn("304", result)  # proposal_id
        self.assertIn("Bob", result)  # proposer_name
        self.assertIn("Amend", result)  # proposal_type
        self.assertIn("201", result)  # target_rule_id
        self.assertIn("Players gain 1 point", result)  # original_text
        self.assertIn("Players gain 2 points", result)  # new_text
        self.assertIn("encourages more active participation", result)

    def test_format_proposal_marks_self_as_you(self):
        """Test _format_proposal marks proposer as (YOU) when applicable."""
        result = self.builder._format_proposal(
            self.proposal, self.rules, "Bob"  # Bob is the proposer
        )

        self.assertIn("Bob (YOU)", result)

    def test_format_proposal_handles_none_values(self):
        """Test _format_proposal handles None in proposal fields."""
        minimal_proposal = Proposal(
            proposer_name="Alice",
            move_number=5,
            type=ProposalType.ADD,
            proposal_id="305",
            target_rule_id=None,
            new_text="New rule text here.",
            rationale=None,
        )

        result = self.builder._format_proposal(
            minimal_proposal, self.rules, "Bob"
        )

        self.assertIn("N/A", result)  # target_rule_id
        self.assertIn("No rationale provided", result)

    def test_get_personality_block_machiavellian(self):
        """Test _get_personality_block returns machiavellian persona."""
        result = self.builder._get_personality_block("machiavellian")
        self.assertIn("ruthlessly competitive", result)

    def test_get_personality_block_friendly(self):
        """Test _get_personality_block returns friendly persona."""
        result = self.builder._get_personality_block("friendly")
        self.assertIn("cooperative player", result)

    def test_get_personality_block_defaults_to_friendly(self):
        """Test _get_personality_block defaults to friendly for unknown."""
        result = self.builder._get_personality_block("unknown")
        self.assertIn("cooperative player", result)

    def test_get_personality_block_none(self):
        """Test _get_personality_block returns none persona."""
        result = self.builder._get_personality_block("none")
        self.assertIn("player in a game of Nomic", result)
        # Should be minimal - no strategy guidance
        self.assertNotIn("ruthlessly competitive", result)
        self.assertNotIn("cooperative player", result)

    # =========================================================================
    # Tests for build_proposer_system_message (with mocking)
    # =========================================================================

    @patch("src.nomic_engine.llm.prompt_builder.prompts")
    def test_build_proposer_system_message_mocked(self, mock_prompts):
        """Test build_proposer_system_message with mocked templates."""
        # Setup mocks
        mock_prompts.MACHIAVELLIAN_PERSONALITY = "PERSONA:{player_name}"
        mock_prompts.GAME_STATE_BLOCK = (
            "STATE:{move_number},{scores_text},{player_position},{turn_order}"
        )
        mock_prompts.RULES_BLOCK = "RULES:{rules_text}"
        mock_prompts.INSTRUCTION_PROPOSE = "PROPOSE:{json_format_enforcement}"
        mock_prompts.JSON_FORMAT_ENFORCEMENT = "JSON_ENFORCE"

        message = self.builder.build_proposer_system_message(
            rules=self.rules,
            game_state=self.game_state,
            player_name="Alice",
            personality="machiavellian",
        )

        # Verify returns single system message
        self.assertIsInstance(message, ChatMessage)
        self.assertEqual(message.role, "system")

        # Verify content includes all blocks
        self.assertIn("PERSONA:Alice", message.content)
        self.assertIn("STATE:5,", message.content)
        self.assertIn("1 of 3", message.content)  # player position
        self.assertIn("RULES:", message.content)
        self.assertIn("PROPOSE:JSON_ENFORCE", message.content)

    def test_build_proposer_system_message_integration(self):
        """Integration test using real templates (not mocked)."""
        message = self.builder.build_proposer_system_message(
            rules=self.rules,
            game_state=self.game_state,
            player_name="Alice",
            personality="machiavellian",
        )

        # Verify single system message
        self.assertIsInstance(message, ChatMessage)
        self.assertEqual(message.role, "system")

        # Verify content includes expected data
        self.assertIn("Alice", message.content)  # player name in persona
        self.assertIn("Move #5", message.content)  # from game state
        self.assertIn("1 of 3", message.content)  # Alice's position
        self.assertIn("101", message.content)  # rule ID
        self.assertIn("ADD", message.content)  # from instruction
        self.assertIn("OUTPUT REQUIREMENTS", message.content)  # JSON format

    def test_build_proposer_system_message_friendly_personality(self):
        """Test proposer message with friendly personality."""
        message = self.builder.build_proposer_system_message(
            rules=self.rules,
            game_state=self.game_state,
            player_name="Alice",
            personality="friendly",
        )

        # Verify friendly persona is used
        self.assertIn("cooperative player", message.content)
        self.assertNotIn("ruthlessly competitive", message.content)

    def test_build_proposer_system_message_none_personality(self):
        """Test proposer message with none personality."""
        message = self.builder.build_proposer_system_message(
            rules=self.rules,
            game_state=self.game_state,
            player_name="Alice",
            personality="none",
        )

        # Verify none persona is used - minimal, no strategy guidance
        self.assertIn("Alice", message.content)
        self.assertIn("player in a game of Nomic", message.content)
        self.assertNotIn("cooperative player", message.content)
        self.assertNotIn("ruthlessly competitive", message.content)

    def test_build_proposer_system_message_empty_rules(self):
        """Test proposer message handles empty rule lists."""
        message = self.builder.build_proposer_system_message(
            rules=[],
            game_state=self.game_state,
            player_name="Alice",
            personality="machiavellian",
        )

        self.assertEqual(message.role, "system")
        self.assertIn("No rules defined", message.content)

    def test_build_proposer_system_message_player_not_found(self):
        """Test proposer message raises ValueError for unknown player."""
        with self.assertRaises(ValueError) as context:
            self.builder.build_proposer_system_message(
                rules=self.rules,
                game_state=self.game_state,
                player_name="Unknown",
                personality="machiavellian",
            )

        self.assertIn("Unknown", str(context.exception))
        self.assertIn("not found in turn order", str(context.exception))

    # =========================================================================
    # Tests for build_discusser_system_message (with mocking)
    # =========================================================================

    @patch("src.nomic_engine.llm.prompt_builder.prompts")
    def test_build_discusser_system_message_mocked(self, mock_prompts):
        """Test build_discusser_system_message with mocked templates."""
        # Setup mocks
        mock_prompts.FRIENDLY_PERSONALITY = "PERSONA:{player_name}"
        mock_prompts.GAME_STATE_BLOCK = (
            "STATE:{move_number},{scores_text},{player_position},{turn_order}"
        )
        mock_prompts.RULES_BLOCK = "RULES:{rules_text}"
        mock_prompts.PROPOSAL_BLOCK = (
            "PROPOSAL:{proposal_id},{proposer_name},{proposal_type},"
            "{target_rule_id},{original_text},{new_text},{rationale}"
        )
        mock_prompts.INSTRUCTION_DISCUSS = "DISCUSS:{json_format_enforcement}"
        mock_prompts.JSON_FORMAT_ENFORCEMENT = "JSON_ENFORCE"

        message = self.builder.build_discusser_system_message(
            proposal=self.proposal,
            rules=self.rules,
            game_state=self.game_state,
            player_name="Charlie",
            personality="friendly",
        )

        # Verify returns single system message
        self.assertIsInstance(message, ChatMessage)
        self.assertEqual(message.role, "system")

        # Verify content includes all blocks
        self.assertIn("PERSONA:Charlie", message.content)
        self.assertIn("STATE:5,", message.content)
        self.assertIn("RULES:", message.content)
        self.assertIn("PROPOSAL:304", message.content)
        self.assertIn("DISCUSS:JSON_ENFORCE", message.content)

    def test_build_discusser_system_message_integration(self):
        """Integration test using real templates (not mocked)."""
        message = self.builder.build_discusser_system_message(
            proposal=self.proposal,
            rules=self.rules,
            game_state=self.game_state,
            player_name="Charlie",
            personality="machiavellian",
        )

        # Verify single system message
        self.assertIsInstance(message, ChatMessage)
        self.assertEqual(message.role, "system")

        # Verify content includes expected data
        self.assertIn("Charlie", message.content)  # player name
        self.assertIn("Move #5", message.content)  # from game state
        self.assertIn("3 of 3", message.content)  # Charlie's position
        self.assertIn("304", message.content)  # proposal ID
        self.assertIn("Bob", message.content)  # proposer name
        self.assertIn("Amend", message.content)  # proposal type
        self.assertIn("discussion_text", message.content)  # from instruction

    def test_build_discusser_system_message_self_proposal(self):
        """Test discusser message marks (YOU) when discussing own proposal."""
        message = self.builder.build_discusser_system_message(
            proposal=self.proposal,
            rules=self.rules,
            game_state=self.game_state,
            player_name="Bob",  # Bob is the proposer
            personality="machiavellian",
        )

        self.assertIn("Bob (YOU)", message.content)

    def test_build_discusser_system_message_handles_none_values(self):
        """Test discusser message handles None in proposal fields."""
        minimal_proposal = Proposal(
            proposer_name="Alice",
            move_number=5,
            type=ProposalType.ADD,
            proposal_id="305",
            target_rule_id=None,
            new_text="New rule text here.",
            rationale=None,
        )

        message = self.builder.build_discusser_system_message(
            proposal=minimal_proposal,
            rules=self.rules,
            game_state=self.game_state,
            player_name="Bob",
            personality="machiavellian",
        )

        self.assertEqual(message.role, "system")
        self.assertIn("N/A", message.content)
        self.assertIn("No rationale provided", message.content)

    # =========================================================================
    # Tests for build_revision_instruction (with mocking)
    # =========================================================================

    @patch("src.nomic_engine.llm.prompt_builder.prompts")
    def test_build_revision_instruction_mocked(self, mock_prompts):
        """Test build_revision_instruction with mocked templates."""
        # Setup mocks
        mock_prompts.DISCUSSION_BLOCK = "DISCUSSIONS:{discussions_text}"
        mock_prompts.INSTRUCTION_REVISE = (
            "REVISE:{constraint_message},{json_format_enforcement}"
        )
        mock_prompts.JSON_FORMAT_ENFORCEMENT = "JSON_ENFORCE"

        message = self.builder.build_revision_instruction(
            discussions=self.discussions
        )

        # Verify returns single user message
        self.assertIsInstance(message, ChatMessage)
        self.assertEqual(message.role, "user")

        # Verify content includes all blocks
        self.assertIn("DISCUSSIONS:", message.content)
        self.assertIn("Alice", message.content)
        self.assertIn("Charlie", message.content)
        self.assertIn("REVISE:", message.content)
        self.assertIn("JSON_ENFORCE", message.content)

    def test_build_revision_instruction_integration(self):
        """Integration test using real templates (not mocked)."""
        message = self.builder.build_revision_instruction(
            discussions=self.discussions
        )

        # Verify single user message
        self.assertIsInstance(message, ChatMessage)
        self.assertEqual(message.role, "user")

        # Verify content includes expected data
        self.assertIn("Alice", message.content)
        self.assertIn("I think this is a good idea.", message.content)
        self.assertIn("Charlie", message.content)
        self.assertIn("I'm not sure about this change.", message.content)
        self.assertIn("KEEP", message.content)
        self.assertIn("MODIFY", message.content)
        self.assertIn("WITHDRAW", message.content)

    def test_build_revision_instruction_constraint_triggered_unclear(self):
        """Test Rule 112 constraint is triggered with UNCLEAR keyword."""
        discussions = [
            Discussion(player_name="Alice", text="I think this is UNCLEAR."),
            Discussion(player_name="Charlie", text="I agree."),
        ]

        message = self.builder.build_revision_instruction(
            discussions=discussions
        )

        self.assertIn("MUST either 'MODIFY' or 'WITHDRAW'", message.content)
        self.assertIn("CANNOT choose 'KEEP'", message.content)

    def test_build_revision_instruction_constraint_triggered_ambiguous(self):
        """Test Rule 112 constraint is triggered with AMBIGUOUS keyword."""
        discussions = [
            Discussion(
                player_name="Alice", text="The wording is a bit ambiguous."
            ),
        ]

        message = self.builder.build_revision_instruction(
            discussions=discussions
        )

        self.assertIn("MUST either 'MODIFY' or 'WITHDRAW'", message.content)

    def test_build_revision_instruction_no_constraint(self):
        """Test permissive message shown when no UNCLEAR/AMBIGUOUS."""
        discussions = [
            Discussion(player_name="Alice", text="I think this is good."),
            Discussion(player_name="Charlie", text="I support this change."),
        ]

        message = self.builder.build_revision_instruction(
            discussions=discussions
        )

        self.assertIn(
            "You may choose to KEEP, MODIFY, or WITHDRAW based on",
            message.content,
        )
        self.assertNotIn("CANNOT choose 'KEEP'", message.content)

    def test_build_revision_instruction_empty_discussions(self):
        """Test revision instruction handles empty discussions."""
        message = self.builder.build_revision_instruction(discussions=[])

        self.assertEqual(message.role, "user")
        self.assertIn("No discussions yet", message.content)
        # Should show permissive message when no discussions
        self.assertIn(
            "You may choose to KEEP, MODIFY, or WITHDRAW", message.content
        )

    # =========================================================================
    # Tests for build_vote_instruction (with mocking)
    # =========================================================================

    @patch("src.nomic_engine.llm.prompt_builder.prompts")
    def test_build_vote_instruction_mocked(self, mock_prompts):
        """Test build_vote_instruction with mocked templates."""
        # Setup mocks
        mock_prompts.PROPOSAL_BLOCK = (
            "PROPOSAL:{proposal_id},{proposer_name},{proposal_type},"
            "{target_rule_id},{original_text},{new_text},{rationale}"
        )
        mock_prompts.DISCUSSION_BLOCK = "DISCUSSIONS:{discussions_text}"
        mock_prompts.INSTRUCTION_VOTE = "VOTE:{json_format_enforcement}"
        mock_prompts.JSON_FORMAT_ENFORCEMENT = "JSON_ENFORCE"

        message = self.builder.build_vote_instruction(
            proposal=self.proposal,
            discussions=self.discussions,
            rules=self.rules,
            player_name="Charlie",
        )

        # Verify returns single user message
        self.assertIsInstance(message, ChatMessage)
        self.assertEqual(message.role, "user")

        # Verify content includes all blocks
        self.assertIn("PROPOSAL:304", message.content)
        self.assertIn("DISCUSSIONS:", message.content)
        self.assertIn("VOTE:JSON_ENFORCE", message.content)

    def test_build_vote_instruction_integration(self):
        """Integration test using real templates (not mocked)."""
        message = self.builder.build_vote_instruction(
            proposal=self.proposal,
            discussions=self.discussions,
            rules=self.rules,
            player_name="Charlie",
        )

        # Verify single user message
        self.assertIsInstance(message, ChatMessage)
        self.assertEqual(message.role, "user")

        # Verify content includes expected data
        self.assertIn("304", message.content)  # proposal ID
        self.assertIn("Bob", message.content)  # proposer name
        self.assertIn("Amend", message.content)  # proposal type
        self.assertIn("201", message.content)  # target rule ID
        self.assertIn("Players gain 2 points", message.content)  # new text
        self.assertIn("Alice", message.content)  # from discussions
        self.assertIn("YES", message.content)  # from vote instruction
        self.assertIn("NO", message.content)  # from vote instruction
        self.assertIn("ABSTAIN", message.content)  # from vote instruction

    def test_build_vote_instruction_self_proposal(self):
        """Test vote instruction marks (YOU) when voting on own proposal."""
        message = self.builder.build_vote_instruction(
            proposal=self.proposal,
            discussions=self.discussions,
            rules=self.rules,
            player_name="Bob",  # Bob is the proposer
        )

        self.assertIn("Bob (YOU)", message.content)

    def test_build_vote_instruction_handles_none_values(self):
        """Test vote instruction handles None in proposal fields."""
        minimal_proposal = Proposal(
            proposer_name="Alice",
            move_number=5,
            type=ProposalType.ADD,
            proposal_id="305",
            target_rule_id=None,
            new_text="New rule text here.",
            rationale=None,
        )

        message = self.builder.build_vote_instruction(
            proposal=minimal_proposal,
            discussions=[],
            rules=self.rules,
            player_name="Bob",
        )

        self.assertEqual(message.role, "user")
        self.assertIn("N/A", message.content)
        self.assertIn("No rationale provided", message.content)
        self.assertIn("No discussions yet", message.content)

    def test_build_vote_instruction_empty_discussions(self):
        """Test vote instruction handles empty discussions."""
        message = self.builder.build_vote_instruction(
            proposal=self.proposal,
            discussions=[],
            rules=self.rules,
            player_name="Charlie",
        )

        self.assertEqual(message.role, "user")
        self.assertIn("No discussions yet", message.content)


if __name__ == "__main__":
    unittest.main()
