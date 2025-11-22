"""
Unit tests for the PromptBuilder class.

These tests verify that the PromptBuilder correctly injects game data into
prompt templates, calculates derived fields, and handles edge cases.
"""

import unittest
from unittest.mock import patch

from src.nomic_engine.data_models import (
    ChatMessage,
    GameState,
    Proposal,
    ProposalType,
    Rule,
    RuleStatus,
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
            ("Alice", "I think this is a good idea."),
            ("Charlie", "I'm not sure about this change."),
        ]

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

    def test_format_discussions(self):
        """Test _format_discussions correctly formats discussion tuples."""
        result = self.builder._format_discussions(self.discussions)

        # Verify the format includes player names and messages
        self.assertIn("**Alice:** I think this is a good idea.", result)
        self.assertIn("**Charlie:** I'm not sure about this change.", result)

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

    @patch("src.nomic_engine.llm.prompt_builder.prompts.VOTE_SYSTEM_PROMPT")
    @patch("src.nomic_engine.llm.prompt_builder.prompts.VOTE_USER_TEMPLATE")
    @patch(
        "src.nomic_engine.llm.prompt_builder.prompts.JSON_FORMAT_ENFORCEMENT"
    )
    def test_build_vote_messages_data_injection(
        self, mock_json_format, mock_user_template, mock_system_prompt
    ):
        """
        Test build_vote_messages correctly injects all data into
        templates.

        This test mocks the prompt templates to avoid dependency on
        their exact text, and verifies placeholders are populated.
        """
        # Set up mock templates with all required placeholders
        mock_system_prompt.format = (
            lambda **kwargs: f"System: {kwargs['player_name']}"
        )
        mock_user_template.format = lambda **kwargs: (
            f"move_number={kwargs['move_number']}, "
            f"scores_text={kwargs['scores_text'][:20]}..., "
            f"player_position={kwargs['player_position']}, "
            f"turn_order={kwargs['turn_order']}, "
            f"proposal_id={kwargs['proposal_id']}, "
            f"json_format={kwargs['json_format_enforcement'][:20]}..."
        )
        mock_json_format.return_value = "JSON FORMAT ENFORCEMENT TEXT"

        # Call the method
        messages = self.builder.build_vote_messages(
            proposal=self.proposal,
            rules=self.rules,
            game_state=self.game_state,
            discussions=self.discussions,
            player_name="Bob",
        )

        # Verify the result is a list of exactly 2 ChatMessage objects
        self.assertIsInstance(messages, list)
        self.assertEqual(len(messages), 2)

        # Verify the message roles
        self.assertIsInstance(messages[0], ChatMessage)
        self.assertEqual(messages[0].role, "system")
        self.assertIsInstance(messages[1], ChatMessage)
        self.assertEqual(messages[1].role, "user")

        # Verify system prompt contains player name
        self.assertIn("Bob", messages[0].content)

        # Verify user prompt contains injected data
        user_content = messages[1].content
        self.assertIn("move_number=5", user_content)
        self.assertIn("player_position=2 of 3", user_content)
        self.assertIn("proposal_id=304", user_content)

    def test_build_vote_messages_integration(self):
        """
        Integration test using real prompt templates (not mocked).

        This test verifies that the method works correctly with the actual
        templates from prompts.py and all placeholders are populated.
        """
        # Call with real templates
        messages = self.builder.build_vote_messages(
            proposal=self.proposal,
            rules=self.rules,
            game_state=self.game_state,
            discussions=self.discussions,
            player_name="Charlie",
        )

        # Basic structure verification
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].role, "system")
        self.assertEqual(messages[1].role, "user")

        # Verify system prompt mentions the player
        self.assertIn("Charlie", messages[0].content)

        # Verify user prompt contains key game data
        user_content = messages[1].content
        self.assertIn("Move #5", user_content)
        self.assertIn("3 of 3", user_content)  # Charlie's position
        self.assertIn("Alice, Bob, Charlie", user_content)  # turn order
        self.assertIn("304", user_content)  # proposal ID
        self.assertIn("Bob", user_content)  # proposer name
        self.assertIn("Amend", user_content)  # proposal type
        self.assertIn("201", user_content)  # target rule ID
        self.assertIn("Players gain 1 point", user_content)
        self.assertIn("Players gain 2 points", user_content)
        self.assertIn("encourages more active participation", user_content)

        # Verify JSON format enforcement is included
        self.assertIn("OUTPUT REQUIREMENTS", user_content)
        self.assertIn("pure JSON", user_content)

    def test_build_vote_messages_handles_none_values(self):
        """Test build_vote_messages handles None in proposal fields."""
        # Create a proposal with minimal data (Add type has no target_rule_id)
        minimal_proposal = Proposal(
            proposer_name="Alice",
            move_number=5,
            type=ProposalType.ADD,
            proposal_id="305",
            target_rule_id=None,
            new_text="New rule text here.",
            rationale=None,
        )

        # Should not raise an exception
        messages = self.builder.build_vote_messages(
            proposal=minimal_proposal,
            rules=self.rules,
            game_state=self.game_state,
            discussions=[],
            player_name="Alice",
        )

        # Verify it still produces valid messages
        self.assertEqual(len(messages), 2)
        user_content = messages[1].content

        # Verify None values are handled
        self.assertIn("N/A", user_content)  # target_rule_id and original_text
        self.assertIn("No rationale provided", user_content)
        self.assertIn("No discussions yet", user_content)

    def test_build_vote_messages_self_proposal(self):
        """Test that (YOU) is added when voting on own proposal."""
        # Create a proposal where proposer_name matches player_name
        self_proposal = Proposal(
            proposer_name="Alice",
            move_number=5,
            type=ProposalType.AMEND,
            proposal_id="305",
            target_rule_id="201",
            new_text="Players gain 3 points for successful proposals.",
            rationale="Incentivize more proposals.",
        )

        # Call with player_name matching proposer_name
        messages = self.builder.build_vote_messages(
            proposal=self_proposal,
            rules=self.rules,
            game_state=self.game_state,
            discussions=[],
            player_name="Alice",
        )

        # Verify the user content contains (YOU) after the proposer's name
        user_content = messages[1].content
        self.assertIn("Alice (YOU)", user_content)

    def test_build_vote_messages_other_proposal(self):
        """Test that (YOU) is NOT added when voting on another's proposal."""
        # Use the standard proposal (proposer is Bob)
        messages = self.builder.build_vote_messages(
            proposal=self.proposal,
            rules=self.rules,
            game_state=self.game_state,
            discussions=self.discussions,
            player_name="Alice",  # Alice is voting on Bob's proposal
        )

        # Verify the user content contains Bob's name without (YOU)
        user_content = messages[1].content
        self.assertIn("Bob", user_content)
        self.assertNotIn("Bob (YOU)", user_content)
        self.assertNotIn("Alice (YOU)", user_content)

    def test_build_discuss_messages_self_proposal(self):
        """Test that (YOU) is added when discussing own proposal."""
        # Create a proposal where proposer_name matches player_name
        self_proposal = Proposal(
            proposer_name="Charlie",
            move_number=5,
            type=ProposalType.ADD,
            proposal_id="306",
            target_rule_id=None,
            new_text="A new rule.",
            rationale="For testing.",
        )

        # Call with player_name matching proposer_name
        messages = self.builder.build_discuss_messages(
            proposal=self_proposal,
            rules=self.rules,
            game_state=self.game_state,
            player_name="Charlie",
        )

        # Verify the user content contains (YOU) after the proposer's name
        user_content = messages[1].content
        self.assertIn("Charlie (YOU)", user_content)

    def test_build_discuss_messages_integration(self):
        """
        Integration test using real prompt templates for discuss action.

        This test verifies that the method works correctly with the actual
        templates from prompts.py and all placeholders are populated.
        """
        # Call with real templates
        messages = self.builder.build_discuss_messages(
            proposal=self.proposal,
            rules=self.rules,
            game_state=self.game_state,
            player_name="Charlie",
        )

        # Basic structure verification
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].role, "system")
        self.assertEqual(messages[1].role, "user")

        # Verify system prompt mentions the player
        self.assertIn("Charlie", messages[0].content)

        # Verify user prompt contains key game data
        user_content = messages[1].content
        self.assertIn("Move #5", user_content)
        self.assertIn("3 of 3", user_content)  # Charlie's position
        self.assertIn("Alice, Bob, Charlie", user_content)  # turn order
        self.assertIn("304", user_content)  # proposal ID
        self.assertIn("Bob", user_content)  # proposer name
        self.assertIn("Amend", user_content)  # proposal type
        self.assertIn("201", user_content)  # target rule ID
        self.assertIn("Players gain 1 point", user_content)
        self.assertIn("Players gain 2 points", user_content)
        self.assertIn("encourages more active participation", user_content)

        # Verify JSON format enforcement is included
        self.assertIn("OUTPUT REQUIREMENTS", user_content)
        self.assertIn("pure JSON", user_content)

        # Verify discussion-specific content
        self.assertIn("private_thoughts", user_content)
        self.assertIn("discussion_text", user_content)

    def test_build_discuss_messages_handles_none_values(self):
        """Test build_discuss_messages handles None in proposal fields."""
        # Create a proposal with minimal data (Add type has no target_rule_id)
        minimal_proposal = Proposal(
            proposer_name="Alice",
            move_number=5,
            type=ProposalType.ADD,
            proposal_id="305",
            target_rule_id=None,
            new_text="New rule text here.",
            rationale=None,
        )

        # Should not raise an exception
        messages = self.builder.build_discuss_messages(
            proposal=minimal_proposal,
            rules=self.rules,
            game_state=self.game_state,
            player_name="Alice",
        )

        # Verify it still produces valid messages
        self.assertEqual(len(messages), 2)
        user_content = messages[1].content

        # Verify None values are handled
        self.assertIn("N/A", user_content)  # target_rule_id and original_text
        self.assertIn("No rationale provided", user_content)

    def test_build_propose_messages_integration(self):
        """
        Integration test using real prompt templates for propose action.

        This test verifies that the method works correctly with the actual
        templates from prompts.py and all placeholders are populated.
        """
        # Call with real templates
        messages = self.builder.build_propose_messages(
            rules=self.rules,
            game_state=self.game_state,
            player_name="Alice",
        )

        # Basic structure verification
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].role, "system")
        self.assertEqual(messages[1].role, "user")

        # Verify system prompt mentions the player
        self.assertIn("Alice", messages[0].content)

        # Verify user prompt contains key game data
        user_content = messages[1].content
        self.assertIn("Move #5", user_content)
        self.assertIn("1 of 3", user_content)  # Alice's position
        self.assertIn("Alice, Bob, Charlie", user_content)  # turn order

        # Verify rules are included
        self.assertIn("101", user_content)  # rule ID
        self.assertIn("All players must vote on proposals", user_content)
        self.assertIn("201", user_content)  # rule ID
        self.assertIn("Players gain 1 point", user_content)

        # Verify JSON format enforcement is included
        self.assertIn("OUTPUT REQUIREMENTS", user_content)
        self.assertIn("pure JSON", user_content)

        # Verify proposal-specific content
        self.assertIn("ADD", user_content)
        self.assertIn("AMEND", user_content)
        self.assertIn("REPEAL", user_content)
        self.assertIn("TRANSMUTE", user_content)
        self.assertIn("private_thoughts", user_content)
        self.assertIn("target_rule_id", user_content)
        self.assertIn("new_text", user_content)
        self.assertIn("rationale", user_content)

    def test_build_propose_messages_player_not_found(self):
        """Test build_propose_messages raises ValueError for unknown player."""
        with self.assertRaises(ValueError) as context:
            self.builder.build_propose_messages(
                rules=self.rules,
                game_state=self.game_state,
                player_name="Unknown",
            )

        self.assertIn("Unknown", str(context.exception))
        self.assertIn("not found in turn order", str(context.exception))

    def test_build_propose_messages_empty_rules(self):
        """Test build_propose_messages handles empty rule lists."""
        # Should not raise an exception
        messages = self.builder.build_propose_messages(
            rules=[],
            game_state=self.game_state,
            player_name="Alice",
        )

        # Verify it still produces valid messages
        self.assertEqual(len(messages), 2)
        user_content = messages[1].content

        # Verify no rules message
        self.assertIn("No rules defined", user_content)

    def test_build_revise_messages_integration(self):
        """
        Integration test using real prompt templates for revise action.

        This test verifies that the method works correctly with the actual
        templates from prompts.py and all placeholders are populated.
        """
        # Create sample discussions
        discussions = [
            ("Alice", "I think this is a good idea."),
            ("Charlie", "I'm not sure about this change."),
        ]

        # Call with real templates
        messages = self.builder.build_revise_messages(
            proposal=self.proposal,
            discussions=discussions,
            game_state=self.game_state,
            player_name="Bob",
        )

        # Basic structure verification
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].role, "system")
        self.assertEqual(messages[1].role, "user")

        # Verify system prompt mentions the player
        self.assertIn("Bob", messages[0].content)

        # Verify user prompt contains key game data
        user_content = messages[1].content
        self.assertIn("Move #5", user_content)
        self.assertIn("2 of 3", user_content)  # Bob's position
        self.assertIn("Alice, Bob, Charlie", user_content)  # turn order
        self.assertIn("304", user_content)  # proposal ID
        self.assertIn("Amend", user_content)  # proposal type
        self.assertIn("201", user_content)  # target rule ID
        self.assertIn("Players gain 2 points", user_content)  # new text
        self.assertIn("encourages more active participation", user_content)

        # Verify discussions are included
        self.assertIn("Alice", user_content)
        self.assertIn("I think this is a good idea.", user_content)
        self.assertIn("Charlie", user_content)
        self.assertIn("I'm not sure about this change.", user_content)

        # Verify JSON format enforcement is included
        self.assertIn("OUTPUT REQUIREMENTS", user_content)
        self.assertIn("pure JSON", user_content)

        # Verify revise-specific content
        self.assertIn("private_thoughts", user_content)
        self.assertIn("KEEP", user_content)
        self.assertIn("MODIFY", user_content)
        self.assertIn("WITHDRAW", user_content)

    def test_build_revise_messages_constraint_triggered(self):
        """Test that Rule 112 constraint is triggered when discussion
        contains UNCLEAR or AMBIGUOUS."""
        # Create discussions with UNCLEAR keyword
        discussions = [
            ("Alice", "I think this is unclear to me."),
            ("Charlie", "I agree, very confusing."),
        ]

        messages = self.builder.build_revise_messages(
            proposal=self.proposal,
            discussions=discussions,
            game_state=self.game_state,
            player_name="Bob",
        )

        user_content = messages[1].content

        # Verify the constraint message is present
        self.assertIn("MUST either 'MODIFY' or 'WITHDRAW'", user_content)
        self.assertIn("CANNOT choose 'KEEP'", user_content)

    def test_build_revise_messages_constraint_triggered_ambiguous(self):
        """Test Rule 112 constraint is triggered with AMBIGUOUS keyword."""
        # Create discussions with AMBIGUOUS keyword (case insensitive)
        discussions = [
            ("Alice", "The wording is a bit AMBIGUOUS."),
        ]

        messages = self.builder.build_revise_messages(
            proposal=self.proposal,
            discussions=discussions,
            game_state=self.game_state,
            player_name="Bob",
        )

        user_content = messages[1].content

        # Verify the constraint message is present
        self.assertIn("MUST either 'MODIFY' or 'WITHDRAW'", user_content)

    def test_build_revise_messages_no_constraint(self):
        """Test that permissive message is shown when no UNCLEAR/AMBIGUOUS."""
        # Create normal discussions without UNCLEAR or AMBIGUOUS
        discussions = [
            ("Alice", "I think this is a good idea."),
            ("Charlie", "I support this change."),
        ]

        messages = self.builder.build_revise_messages(
            proposal=self.proposal,
            discussions=discussions,
            game_state=self.game_state,
            player_name="Bob",
        )

        user_content = messages[1].content

        # Verify the permissive message is present
        self.assertIn(
            "You may choose to KEEP, MODIFY, or WITHDRAW based on",
            user_content,
        )
        # Verify the constraint message is NOT present
        self.assertNotIn("CANNOT choose 'KEEP'", user_content)

    def test_build_revise_messages_handles_none_values(self):
        """Test build_revise_messages handles None in proposal fields."""
        # Create a proposal with minimal data (Add type has no target_rule_id)
        minimal_proposal = Proposal(
            proposer_name="Alice",
            move_number=5,
            type=ProposalType.ADD,
            proposal_id="305",
            target_rule_id=None,
            new_text="New rule text here.",
            rationale=None,
        )

        # Should not raise an exception
        messages = self.builder.build_revise_messages(
            proposal=minimal_proposal,
            discussions=[],
            game_state=self.game_state,
            player_name="Alice",
        )

        # Verify it still produces valid messages
        self.assertEqual(len(messages), 2)
        user_content = messages[1].content

        # Verify None values are handled
        self.assertIn("N/A", user_content)  # target_rule_id
        self.assertIn("No rationale provided", user_content)
        self.assertIn("No discussions yet", user_content)


if __name__ == "__main__":
    unittest.main()
