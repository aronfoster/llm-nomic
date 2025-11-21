"""
Unit tests for LLM response parsers.
"""

import pytest

from src.nomic_engine.llm.parsers import (
    parse_discussion_response,
    parse_proposal_response,
    parse_vote_response,
)


class TestParseVoteResponse:
    """Tests for the parse_vote_response function."""

    def test_valid_json_response(self):
        """Test parsing a valid JSON response."""
        response = """{
            "private_thoughts": "This is a strategic analysis",
            "public_reason": "This is my public explanation",
            "vote": "YES"
        }"""

        result = parse_vote_response(response)

        assert result["vote"] == "YES"
        assert result["public_reason"] == "This is my public explanation"
        assert result["private_thoughts"] == "This is a strategic analysis"

    def test_valid_json_lowercase_vote(self):
        """Test that vote values are normalized to uppercase."""
        response = """{
            "private_thoughts": "Analysis",
            "public_reason": "Reason",
            "vote": "no"
        }"""

        result = parse_vote_response(response)

        assert result["vote"] == "NO"

    def test_valid_json_mixed_case_vote(self):
        """Test that mixed case votes are normalized."""
        response = """{
            "private_thoughts": "Analysis",
            "public_reason": "Reason",
            "vote": "AbStAiN"
        }"""

        result = parse_vote_response(response)

        assert result["vote"] == "ABSTAIN"

    def test_invalid_json_syntax(self):
        """Test that invalid JSON raises ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "public_reason": "Reason",
            "vote": "YES"
        """  # Missing closing brace

        with pytest.raises(ValueError) as exc_info:
            parse_vote_response(response)

        assert "not valid JSON" in str(exc_info.value)

    def test_missing_vote_key(self):
        """Test that missing 'vote' key raises ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "public_reason": "Reason"
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_vote_response(response)

        assert "Missing required key" in str(exc_info.value)
        assert "vote" in str(exc_info.value)

    def test_missing_public_reason_key(self):
        """Test that missing 'public_reason' key raises ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "vote": "YES"
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_vote_response(response)

        assert "Missing required key" in str(exc_info.value)
        assert "public_reason" in str(exc_info.value)

    def test_missing_private_thoughts_key(self):
        """Test that missing 'private_thoughts' key raises ValueError."""
        response = """{
            "public_reason": "Reason",
            "vote": "YES"
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_vote_response(response)

        assert "Missing required key" in str(exc_info.value)
        assert "private_thoughts" in str(exc_info.value)

    def test_missing_multiple_keys(self):
        """Test that multiple missing keys are all reported."""
        response = """{
            "vote": "YES"
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_vote_response(response)

        error_msg = str(exc_info.value)
        assert "Missing required key" in error_msg
        # Should mention both missing keys
        assert "public_reason" in error_msg or "private_thoughts" in error_msg

    def test_invalid_vote_value(self):
        """Test that invalid vote values raise ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "public_reason": "Reason",
            "vote": "MAYBE"
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_vote_response(response)

        assert "Invalid vote value" in str(exc_info.value)
        assert "MAYBE" in str(exc_info.value)

    def test_vote_not_string(self):
        """Test that non-string vote values raise ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "public_reason": "Reason",
            "vote": 123
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_vote_response(response)

        assert "Vote must be a string" in str(exc_info.value)

    def test_response_is_array_not_object(self):
        """Test that JSON arrays are rejected."""
        response = """["YES", "NO", "ABSTAIN"]"""

        with pytest.raises(ValueError) as exc_info:
            parse_vote_response(response)

        assert "must be a JSON object" in str(exc_info.value)

    def test_response_is_string_not_object(self):
        """Test that plain strings are rejected."""
        response = '"YES"'

        with pytest.raises(ValueError) as exc_info:
            parse_vote_response(response)

        assert "must be a JSON object" in str(exc_info.value)

    def test_public_reason_not_string(self):
        """Test that non-string public_reason raises ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "public_reason": 123,
            "vote": "YES"
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_vote_response(response)

        assert "public_reason must be a string" in str(exc_info.value)

    def test_private_thoughts_not_string(self):
        """Test that non-string private_thoughts raises ValueError."""
        response = """{
            "private_thoughts": ["This", "is", "a", "list"],
            "public_reason": "Reason",
            "vote": "YES"
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_vote_response(response)

        assert "private_thoughts must be a string" in str(exc_info.value)

    def test_markdown_wrapped_json_fails_with_todo_note(self):
        """
        Test that markdown-wrapped JSON currently fails.

        This documents the TODO in parsers.py - cleaning markdown
        will be implemented in a future iteration.
        """
        response = """```json
{
    "private_thoughts": "Analysis",
    "public_reason": "Reason",
    "vote": "YES"
}
```"""

        with pytest.raises(ValueError) as exc_info:
            parse_vote_response(response)

        assert "not valid JSON" in str(exc_info.value)

    def test_extra_keys_are_allowed(self):
        """Test that extra keys don't cause errors (forward compatibility)."""
        response = """{
            "private_thoughts": "Analysis",
            "public_reason": "Reason",
            "vote": "YES",
            "extra_field": "This should not cause an error"
        }"""

        result = parse_vote_response(response)

        assert result["vote"] == "YES"
        assert result["extra_field"] == "This should not cause an error"


class TestParseDiscussionResponse:
    """Tests for the parse_discussion_response function."""

    def test_valid_json_response(self):
        """Test parsing a valid JSON response."""
        response = """{
            "private_thoughts": "This is a strategic analysis",
            "discussion_text": "I think we should consider the implications."
        }"""

        result = parse_discussion_response(response)

        assert result["private_thoughts"] == "This is a strategic analysis"
        assert (
            result["discussion_text"]
            == "I think we should consider the implications."
        )

    def test_valid_json_empty_discussion(self):
        """Test parsing valid JSON with empty discussion (abstain)."""
        response = """{
            "private_thoughts": "I'll stay quiet on this one.",
            "discussion_text": ""
        }"""

        result = parse_discussion_response(response)

        assert result["private_thoughts"] == "I'll stay quiet on this one."
        assert result["discussion_text"] == ""

    def test_invalid_json_syntax(self):
        """Test that invalid JSON raises ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "discussion_text": "Comment"
        """  # Missing closing brace

        with pytest.raises(ValueError) as exc_info:
            parse_discussion_response(response)

        assert "not valid JSON" in str(exc_info.value)

    def test_missing_private_thoughts_key(self):
        """Test that missing 'private_thoughts' key raises ValueError."""
        response = """{
            "discussion_text": "Some comment"
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_discussion_response(response)

        assert "Missing required key" in str(exc_info.value)
        assert "private_thoughts" in str(exc_info.value)

    def test_missing_discussion_text_key(self):
        """Test that missing 'discussion_text' key raises ValueError."""
        response = """{
            "private_thoughts": "Analysis"
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_discussion_response(response)

        assert "Missing required key" in str(exc_info.value)
        assert "discussion_text" in str(exc_info.value)

    def test_private_thoughts_not_string(self):
        """Test that non-string private_thoughts raises ValueError."""
        response = """{
            "private_thoughts": 123,
            "discussion_text": "Comment"
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_discussion_response(response)

        assert "private_thoughts must be a string" in str(exc_info.value)

    def test_discussion_text_not_string(self):
        """Test that non-string discussion_text raises ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "discussion_text": ["Comment", "list"]
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_discussion_response(response)

        assert "discussion_text must be a string" in str(exc_info.value)

    def test_response_is_array_not_object(self):
        """Test that JSON arrays are rejected."""
        response = """["thoughts", "discussion"]"""

        with pytest.raises(ValueError) as exc_info:
            parse_discussion_response(response)

        assert "must be a JSON object" in str(exc_info.value)

    def test_extra_keys_are_allowed(self):
        """Test that extra keys don't cause errors (forward compatibility)."""
        response = """{
            "private_thoughts": "Analysis",
            "discussion_text": "Comment",
            "extra_field": "This should not cause an error"
        }"""

        result = parse_discussion_response(response)

        assert result["private_thoughts"] == "Analysis"
        assert result["discussion_text"] == "Comment"
        assert result["extra_field"] == "This should not cause an error"


class TestParseProposalResponse:
    """Tests for the parse_proposal_response function."""

    def test_parse_proposal_valid_add(self):
        """Test parsing a valid ADD proposal."""
        response = """{
            "private_thoughts": "I'm behind in points. This helps me.",
            "type": "ADD",
            "target_rule_id": null,
            "new_text": "Players gain 5 points for unanimous proposals.",
            "rationale": "This encourages consensus-building."
        }"""

        result = parse_proposal_response(response)

        expected_thoughts = "I'm behind in points. This helps me."
        assert result["private_thoughts"] == expected_thoughts
        assert result["type"] == "Add"
        assert result["target_rule_id"] is None
        new_text = "Players gain 5 points for unanimous proposals."
        assert result["new_text"] == new_text
        assert result["rationale"] == "This encourages consensus-building."

    def test_parse_proposal_valid_amend(self):
        """Test parsing a valid AMEND proposal."""
        response = """{
            "private_thoughts": "Rule 201 gives Alice too much advantage.",
            "type": "AMEND",
            "target_rule_id": "201",
            "new_text": "Players gain 1 point per proposal, max 3 per game.",
            "rationale": "This balances the game and prevents runaway leaders."
        }"""

        result = parse_proposal_response(response)

        assert result["type"] == "Amend"
        assert result["target_rule_id"] == "201"
        expected = "Players gain 1 point per proposal, max 3 per game."
        assert result["new_text"] == expected

    def test_parse_proposal_valid_repeal(self):
        """Test parsing a valid REPEAL proposal."""
        response = """{
            "private_thoughts": "Rule 203 is blocking my strategy.",
            "type": "REPEAL",
            "target_rule_id": "203",
            "new_text": null,
            "rationale": "This rule causes confusion and slows gameplay."
        }"""

        result = parse_proposal_response(response)

        assert result["type"] == "Repeal"
        assert result["target_rule_id"] == "203"
        assert result["new_text"] is None

    def test_parse_proposal_valid_transmute(self):
        """Test parsing a valid TRANSMUTE proposal."""
        response = """{
            "private_thoughts": "Making 105 immutable locks in my advantage.",
            "type": "TRANSMUTE",
            "target_rule_id": "105",
            "new_text": null,
            "rationale": "This core rule should be protected."
        }"""

        result = parse_proposal_response(response)

        assert result["type"] == "Transmute"
        assert result["target_rule_id"] == "105"
        assert result["new_text"] is None

    def test_parse_proposal_lowercase_type_normalized(self):
        """Test that type values are normalized to uppercase."""
        response = """{
            "private_thoughts": "Analysis",
            "type": "add",
            "target_rule_id": null,
            "new_text": "New rule text",
            "rationale": "Reason"
        }"""

        result = parse_proposal_response(response)

        assert result["type"] == "Add"

    def test_parse_proposal_invalid_json(self):
        """Test that invalid JSON raises ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "type": "ADD"
        """  # Missing closing brace

        with pytest.raises(ValueError) as exc_info:
            parse_proposal_response(response)

        assert "not valid JSON" in str(exc_info.value)

    def test_parse_proposal_missing_type_key(self):
        """Test that missing 'type' key raises ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "target_rule_id": null,
            "new_text": "Text",
            "rationale": "Reason"
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_proposal_response(response)

        assert "Missing required key" in str(exc_info.value)
        assert "type" in str(exc_info.value)

    def test_parse_proposal_invalid_type_value(self):
        """Test that invalid type values raise ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "type": "DELETE",
            "target_rule_id": "201",
            "new_text": null,
            "rationale": "Reason"
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_proposal_response(response)

        assert "Invalid type value" in str(exc_info.value)
        assert "DELETE" in str(exc_info.value)

    def test_parse_proposal_amend_without_target_raises_error(self):
        """Test that AMEND without target_rule_id raises ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "type": "AMEND",
            "target_rule_id": null,
            "new_text": "New text",
            "rationale": "Reason"
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_proposal_response(response)

        err = str(exc_info.value)
        assert "Missing 'target_rule_id' for AMEND proposal" in err

    def test_parse_proposal_amend_without_new_text_raises_error(self):
        """Test that AMEND without new_text raises ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "type": "AMEND",
            "target_rule_id": "201",
            "new_text": null,
            "rationale": "Reason"
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_proposal_response(response)

        assert "Missing 'new_text' for AMEND proposal" in str(exc_info.value)

    def test_parse_proposal_add_without_new_text_raises_error(self):
        """Test that ADD without new_text raises ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "type": "ADD",
            "target_rule_id": null,
            "new_text": null,
            "rationale": "Reason"
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_proposal_response(response)

        assert "Missing 'new_text' for ADD proposal" in str(exc_info.value)

    def test_parse_proposal_add_with_target_rule_id_raises_error(self):
        """Test that ADD with target_rule_id raises ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "type": "ADD",
            "target_rule_id": "201",
            "new_text": "New rule text",
            "rationale": "Reason"
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_proposal_response(response)

        err = str(exc_info.value)
        assert "ADD proposals must not have a 'target_rule_id'" in err

    def test_parse_proposal_repeal_without_target_raises_error(self):
        """Test that REPEAL without target_rule_id raises ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "type": "REPEAL",
            "target_rule_id": null,
            "new_text": null,
            "rationale": "Reason"
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_proposal_response(response)

        err = str(exc_info.value)
        assert "Missing 'target_rule_id' for REPEAL proposal" in err

    def test_parse_proposal_repeal_with_new_text_raises_error(self):
        """Test that REPEAL with new_text raises ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "type": "REPEAL",
            "target_rule_id": "201",
            "new_text": "Some text",
            "rationale": "Reason"
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_proposal_response(response)

        err = str(exc_info.value)
        assert "REPEAL proposals must not have 'new_text'" in err

    def test_parse_proposal_transmute_without_target_raises_error(self):
        """Test that TRANSMUTE without target_rule_id raises ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "type": "TRANSMUTE",
            "target_rule_id": null,
            "new_text": null,
            "rationale": "Reason"
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_proposal_response(response)

        err = str(exc_info.value)
        assert "Missing 'target_rule_id' for TRANSMUTE proposal" in err

    def test_parse_proposal_transmute_with_new_text_raises_error(self):
        """Test that TRANSMUTE with new_text raises ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "type": "TRANSMUTE",
            "target_rule_id": "201",
            "new_text": "Some text",
            "rationale": "Reason"
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_proposal_response(response)

        err = str(exc_info.value)
        assert "TRANSMUTE proposals must not have 'new_text'" in err

    def test_parse_proposal_type_not_string_raises_error(self):
        """Test that non-string type raises ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "type": 123,
            "target_rule_id": null,
            "new_text": "Text",
            "rationale": "Reason"
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_proposal_response(response)

        assert "type must be a string" in str(exc_info.value)

    def test_parse_proposal_target_rule_id_not_string_raises_error(self):
        """Test that non-string/non-null target_rule_id raises ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "type": "AMEND",
            "target_rule_id": 201,
            "new_text": "Text",
            "rationale": "Reason"
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_proposal_response(response)

        assert "target_rule_id must be a string or null" in str(exc_info.value)

    def test_parse_proposal_extra_keys_allowed(self):
        """Test that extra keys don't cause errors (forward compatibility)."""
        response = """{
            "private_thoughts": "Analysis",
            "type": "ADD",
            "target_rule_id": null,
            "new_text": "New rule",
            "rationale": "Reason",
            "extra_field": "Should be ignored"
        }"""

        result = parse_proposal_response(response)

        assert result["type"] == "Add"
        assert result["extra_field"] == "Should be ignored"
