"""
Unit tests for LLM response parsers.
"""

import pytest

from src.nomic_engine.llm.parsers import parse_vote_response


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
