"""
Unit tests for the atomized prompt templates in prompts.py.

These tests verify that all new atomized constants exist and contain
expected substrings, and that placeholders are correctly defined.
"""

from src.nomic_engine.llm import prompts


class TestPersonalityBlocks:
    """Test cases for personality template blocks."""

    def test_machiavellian_personality_exists(self):
        """Test that MACHIAVELLIAN_PERSONALITY constant exists."""
        assert hasattr(prompts, "MACHIAVELLIAN_PERSONALITY")

    def test_machiavellian_personality_contains_player_name(self):
        """Test MACHIAVELLIAN_PERSONALITY has player_name placeholder."""
        assert "{player_name}" in prompts.MACHIAVELLIAN_PERSONALITY

    def test_machiavellian_personality_contains_ruthless(self):
        """Test MACHIAVELLIAN_PERSONALITY contains 'ruthlessly competitive'."""
        assert "ruthlessly competitive" in prompts.MACHIAVELLIAN_PERSONALITY

    def test_friendly_personality_exists(self):
        """Test that FRIENDLY_PERSONALITY constant exists."""
        assert hasattr(prompts, "FRIENDLY_PERSONALITY")

    def test_friendly_personality_contains_player_name(self):
        """Test FRIENDLY_PERSONALITY has player_name placeholder."""
        assert "{player_name}" in prompts.FRIENDLY_PERSONALITY

    def test_friendly_personality_contains_cooperative(self):
        """Test FRIENDLY_PERSONALITY contains 'cooperative'."""
        assert "cooperative" in prompts.FRIENDLY_PERSONALITY

    def test_friendly_personality_contains_consensus(self):
        """Test FRIENDLY_PERSONALITY contains 'consensus'."""
        assert "consensus" in prompts.FRIENDLY_PERSONALITY


class TestDataBlocks:
    """Test cases for data block templates."""

    def test_rules_block_exists(self):
        """Test that RULES_BLOCK constant exists."""
        assert hasattr(prompts, "RULES_BLOCK")

    def test_rules_block_contains_header(self):
        """Test RULES_BLOCK contains rules header."""
        assert "ALL CURRENT RULES" in prompts.RULES_BLOCK

    def test_rules_block_contains_placeholder(self):
        """Test RULES_BLOCK contains rules_text placeholder."""
        assert "{rules_text}" in prompts.RULES_BLOCK

    def test_game_state_block_exists(self):
        """Test that GAME_STATE_BLOCK constant exists."""
        assert hasattr(prompts, "GAME_STATE_BLOCK")

    def test_game_state_block_contains_header(self):
        """Test GAME_STATE_BLOCK contains game state header."""
        assert "GAME STATE" in prompts.GAME_STATE_BLOCK

    def test_game_state_block_contains_placeholders(self):
        """Test GAME_STATE_BLOCK contains all required placeholders."""
        required_placeholders = [
            "{move_number}",
            "{scores_text}",
            "{player_position}",
            "{turn_order}",
        ]
        for placeholder in required_placeholders:
            assert (
                placeholder in prompts.GAME_STATE_BLOCK
            ), f"Missing placeholder: {placeholder}"

    def test_proposal_block_exists(self):
        """Test that PROPOSAL_BLOCK constant exists."""
        assert hasattr(prompts, "PROPOSAL_BLOCK")

    def test_proposal_block_contains_header(self):
        """Test PROPOSAL_BLOCK contains proposal header."""
        assert "PROPOSAL" in prompts.PROPOSAL_BLOCK

    def test_proposal_block_contains_placeholders(self):
        """Test PROPOSAL_BLOCK contains all required placeholders."""
        required_placeholders = [
            "{proposal_id}",
            "{proposer_name}",
            "{proposal_type}",
            "{target_rule_id}",
            "{original_text}",
            "{new_text}",
            "{rationale}",
        ]
        for placeholder in required_placeholders:
            assert (
                placeholder in prompts.PROPOSAL_BLOCK
            ), f"Missing placeholder: {placeholder}"

    def test_discussion_block_exists(self):
        """Test that DISCUSSION_BLOCK constant exists."""
        assert hasattr(prompts, "DISCUSSION_BLOCK")

    def test_discussion_block_contains_header(self):
        """Test DISCUSSION_BLOCK contains discussions header."""
        assert "DISCUSSIONS" in prompts.DISCUSSION_BLOCK

    def test_discussion_block_contains_placeholder(self):
        """Test DISCUSSION_BLOCK contains discussions_text placeholder."""
        assert "{discussions_text}" in prompts.DISCUSSION_BLOCK


class TestInstructionBlocks:
    """Test cases for instruction block templates."""

    def test_instruction_propose_exists(self):
        """Test that INSTRUCTION_PROPOSE constant exists."""
        assert hasattr(prompts, "INSTRUCTION_PROPOSE")

    def test_instruction_propose_contains_propose(self):
        """Test INSTRUCTION_PROPOSE contains 'propose' action."""
        assert "propose" in prompts.INSTRUCTION_PROPOSE.lower()

    def test_instruction_propose_contains_json_format_placeholder(self):
        """Test INSTRUCTION_PROPOSE contains json_format_enforcement."""
        assert "{json_format_enforcement}" in prompts.INSTRUCTION_PROPOSE

    def test_instruction_propose_contains_proposal_types(self):
        """Test INSTRUCTION_PROPOSE contains all proposal types."""
        proposal_types = ["ADD", "AMEND", "REPEAL", "TRANSMUTE"]
        for ptype in proposal_types:
            assert (
                ptype in prompts.INSTRUCTION_PROPOSE
            ), f"Missing proposal type: {ptype}"

    def test_instruction_propose_contains_json_keys(self):
        """Test INSTRUCTION_PROPOSE contains required JSON keys."""
        json_keys = [
            "private_thoughts",
            "type",
            "target_rule_id",
            "new_text",
            "rationale",
        ]
        for key in json_keys:
            assert (
                key in prompts.INSTRUCTION_PROPOSE
            ), f"Missing JSON key: {key}"

    def test_instruction_discuss_exists(self):
        """Test that INSTRUCTION_DISCUSS constant exists."""
        assert hasattr(prompts, "INSTRUCTION_DISCUSS")

    def test_instruction_discuss_contains_discuss(self):
        """Test INSTRUCTION_DISCUSS contains 'discussion' action."""
        assert "discussion" in prompts.INSTRUCTION_DISCUSS.lower()

    def test_instruction_discuss_contains_json_format_placeholder(self):
        """Test INSTRUCTION_DISCUSS contains json_format_enforcement."""
        assert "{json_format_enforcement}" in prompts.INSTRUCTION_DISCUSS

    def test_instruction_discuss_contains_json_keys(self):
        """Test INSTRUCTION_DISCUSS contains required JSON keys."""
        json_keys = ["private_thoughts", "discussion_text"]
        for key in json_keys:
            assert (
                key in prompts.INSTRUCTION_DISCUSS
            ), f"Missing JSON key: {key}"

    def test_instruction_revise_exists(self):
        """Test that INSTRUCTION_REVISE constant exists."""
        assert hasattr(prompts, "INSTRUCTION_REVISE")

    def test_instruction_revise_contains_revise(self):
        """Test INSTRUCTION_REVISE contains revision actions."""
        assert "KEEP" in prompts.INSTRUCTION_REVISE
        assert "MODIFY" in prompts.INSTRUCTION_REVISE
        assert "WITHDRAW" in prompts.INSTRUCTION_REVISE

    def test_instruction_revise_contains_constraint_placeholder(self):
        """Test INSTRUCTION_REVISE contains constraint_message placeholder."""
        assert "{constraint_message}" in prompts.INSTRUCTION_REVISE

    def test_instruction_revise_contains_json_format_placeholder(self):
        """Test INSTRUCTION_REVISE contains json_format_enforcement."""
        assert "{json_format_enforcement}" in prompts.INSTRUCTION_REVISE

    def test_instruction_revise_contains_json_keys(self):
        """Test INSTRUCTION_REVISE contains required JSON keys."""
        json_keys = ["private_thoughts", "action", "new_text", "rationale"]
        for key in json_keys:
            assert (
                key in prompts.INSTRUCTION_REVISE
            ), f"Missing JSON key: {key}"

    def test_instruction_vote_exists(self):
        """Test that INSTRUCTION_VOTE constant exists."""
        assert hasattr(prompts, "INSTRUCTION_VOTE")

    def test_instruction_vote_contains_vote(self):
        """Test INSTRUCTION_VOTE contains 'vote' action."""
        assert "vote" in prompts.INSTRUCTION_VOTE.lower()

    def test_instruction_vote_contains_json_format_placeholder(self):
        """Test INSTRUCTION_VOTE contains json_format_enforcement."""
        assert "{json_format_enforcement}" in prompts.INSTRUCTION_VOTE

    def test_instruction_vote_contains_json_keys(self):
        """Test INSTRUCTION_VOTE contains required JSON keys."""
        json_keys = ["private_thoughts", "public_reason", "vote"]
        for key in json_keys:
            assert key in prompts.INSTRUCTION_VOTE, f"Missing JSON key: {key}"

    def test_instruction_vote_contains_vote_options(self):
        """Test INSTRUCTION_VOTE contains all vote options."""
        vote_options = ["YES", "NO", "ABSTAIN"]
        for option in vote_options:
            assert (
                option in prompts.INSTRUCTION_VOTE
            ), f"Missing vote option: {option}"


class TestExistingConstants:
    """Test that existing constants still exist (backward compatibility)."""

    def test_json_format_enforcement_exists(self):
        """Test that JSON_FORMAT_ENFORCEMENT still exists."""
        assert hasattr(prompts, "JSON_FORMAT_ENFORCEMENT")

    def test_vote_system_prompt_exists(self):
        """Test that old VOTE_SYSTEM_PROMPT still exists."""
        assert hasattr(prompts, "VOTE_SYSTEM_PROMPT")

    def test_vote_user_template_exists(self):
        """Test that old VOTE_USER_TEMPLATE still exists."""
        assert hasattr(prompts, "VOTE_USER_TEMPLATE")

    def test_discuss_system_prompt_exists(self):
        """Test that old DISCUSS_SYSTEM_PROMPT still exists."""
        assert hasattr(prompts, "DISCUSS_SYSTEM_PROMPT")

    def test_discuss_user_template_exists(self):
        """Test that old DISCUSS_USER_TEMPLATE still exists."""
        assert hasattr(prompts, "DISCUSS_USER_TEMPLATE")

    def test_propose_system_prompt_exists(self):
        """Test that old PROPOSE_SYSTEM_PROMPT still exists."""
        assert hasattr(prompts, "PROPOSE_SYSTEM_PROMPT")

    def test_propose_user_template_exists(self):
        """Test that old PROPOSE_USER_TEMPLATE still exists."""
        assert hasattr(prompts, "PROPOSE_USER_TEMPLATE")

    def test_revise_system_prompt_exists(self):
        """Test that old REVISE_SYSTEM_PROMPT still exists."""
        assert hasattr(prompts, "REVISE_SYSTEM_PROMPT")

    def test_revise_user_template_exists(self):
        """Test that old REVISE_USER_TEMPLATE still exists."""
        assert hasattr(prompts, "REVISE_USER_TEMPLATE")
