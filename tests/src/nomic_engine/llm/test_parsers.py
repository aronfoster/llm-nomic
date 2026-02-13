"""
Unit tests for LLM response parsers.
"""

import pytest

from src.nomic_engine.llm.parsers import (
    parse_discussion_response,
    parse_judge_maintain_state_response,
    parse_judge_score_response,
    parse_judge_veto_response,
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


class TestParseJudgeVetoResponse:
    """Tests for the parse_judge_veto_response function."""

    def test_valid_veto_response(self):
        """Parses a well-formed veto payload."""

        response = (
            '{\n  "private_thoughts": "Analysis",\n'
            '  "veto": true,\n  "reason": "Illegal change"\n}'
        )

        result = parse_judge_veto_response(response)

        assert result["veto"] is True
        assert result["reason"] == "Illegal change"
        assert result["private_thoughts"] == "Analysis"

    @pytest.mark.parametrize(
        "response, expected_message",
        [
            ("not-json", "not valid JSON"),
            ("{}", "Missing required key"),
            (
                '{"private_thoughts": 1, "veto": false, "reason":"x"}',
                "private_thoughts must be a string",
            ),
            (
                '{"private_thoughts":"x", "veto": "nope",' ' "reason":"x"}',
                "veto must be a boolean",
            ),
            (
                '{"private_thoughts":"x", "veto": false, "reason": 3}',
                "reason must be a string",
            ),
        ],
    )
    def test_invalid_veto_response(self, response: str, expected_message: str):
        """Raises ValueError for malformed payloads."""

        with pytest.raises(ValueError) as exc_info:
            parse_judge_veto_response(response)

        assert expected_message in str(exc_info.value)


class TestParseJudgeScoreResponse:
    """Tests for the parse_judge_score_response function."""

    def test_valid_score_response(self):
        """Parses adjustments and preserves order."""

        response = (
            "{"
            '"private_thoughts":"ok",'
            '"score_adjustments":[{'
            '"player":"Alice","delta":2,"reason":"Bonus"},'
            '{"player":"Bob","delta":-1,"reason":"Penalty"}]}'
        )

        result = parse_judge_score_response(response, ["Alice", "Bob"])

        assert result["private_thoughts"] == "ok"
        assert result["score_adjustments"][0]["player"] == "Alice"
        assert result["score_adjustments"][0]["delta"] == 2
        assert result["score_adjustments"][1]["delta"] == -1

    @pytest.mark.parametrize(
        "response, expected_message",
        [
            ("not-json", "not valid JSON"),
            ("{}", "Missing required key"),
            (
                '{"private_thoughts":1,"score_adjustments":[]}',
                "private_thoughts must be a string",
            ),
            (
                '{"private_thoughts":"x","score_adjustments":{}}',
                "score_adjustments must be a list",
            ),
            (
                '{"private_thoughts":"x","score_adjustments":[1]}',
                "must be an object",
            ),
            (
                '{"private_thoughts":"x","score_adjustments":[{"player":"Alice","reason":"r"}]}',
                "missing required key",
            ),
            (
                '{"private_thoughts":"x","score_adjustments":[{"player":5,"delta":1,"reason":"r"}]}',
                "player must be a string",
            ),
            (
                '{"private_thoughts":"x","score_adjustments":[{"player":"Zoe","delta":1,"reason":"r"}]}',
                "unknown player",
            ),
            (
                '{"private_thoughts":"x","score_adjustments":[{"player":"Alice","delta":"one","reason":"r"}]}',
                "delta must be an integer",
            ),
            (
                '{"private_thoughts":"x","score_adjustments":[{"player":"Alice","delta":1,"reason":2}]}',
                "reason must be a string",
            ),
        ],
    )
    def test_invalid_score_response(
        self, response: str, expected_message: str
    ):
        """Raises ValueError for malformed scoring payloads."""

        with pytest.raises(ValueError) as exc_info:
            parse_judge_score_response(response, ["Alice", "Bob"])

        assert expected_message in str(exc_info.value)

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

    def test_markdown_wrapped_json_succeeds(self):
        """Test that markdown-wrapped JSON is parsed successfully."""
        response = """```json
{
    "private_thoughts": "Analysis",
    "public_reason": "Reason",
    "vote": "YES"
}
```"""

        result = parse_vote_response(response)

        assert result["vote"] == "YES"
        assert result["public_reason"] == "Reason"
        assert result["private_thoughts"] == "Analysis"

    def test_json_with_preamble(self):
        """Test that JSON with conversational preamble is parsed."""
        response = """Here is the data: {
    "private_thoughts": "Thinking about this",
    "public_reason": "My reason",
    "vote": "NO"
}"""

        result = parse_vote_response(response)

        assert result["vote"] == "NO"
        assert result["public_reason"] == "My reason"
        assert result["private_thoughts"] == "Thinking about this"

    def test_json_with_postscript(self):
        """Test that JSON with postscript text is parsed successfully."""
        response = """{
    "private_thoughts": "Strategy",
    "public_reason": "Explanation",
    "vote": "ABSTAIN"
} hope this helps!"""

        result = parse_vote_response(response)

        assert result["vote"] == "ABSTAIN"
        assert result["public_reason"] == "Explanation"
        assert result["private_thoughts"] == "Strategy"

    def test_json_embedded(self):
        """Test that JSON embedded in markdown with text is parsed."""
        response = """Sure! ```json
{
    "private_thoughts": "Deep analysis",
    "public_reason": "Clear reason",
    "vote": "YES"
}
``` Done."""

        result = parse_vote_response(response)

        assert result["vote"] == "YES"
        assert result["public_reason"] == "Clear reason"
        assert result["private_thoughts"] == "Deep analysis"

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


class TestParseJudgeMaintainStateResponse:
    """Tests for the parse_judge_maintain_state_response function."""

    def test_valid_empty_changes(self):
        """Test parsing response with no state changes."""
        response = """{
            "private_thoughts": "No engine changes needed.",
            "flags": {},
            "target_score": null
        }"""

        result = parse_judge_maintain_state_response(response)

        assert result["private_thoughts"] == "No engine changes needed."
        assert result["flags"] == {}
        assert result["target_score"] is None

    def test_valid_flag_change_only(self):
        """Test parsing response with only flag changes."""
        response = """{
            "private_thoughts": "Rule changes voting to majority.",
            "flags": {"vote_mode": "majority"},
            "target_score": null
        }"""

        result = parse_judge_maintain_state_response(response)

        assert result["private_thoughts"] == "Rule changes voting to majority."
        assert result["flags"] == {"vote_mode": "majority"}
        assert result["target_score"] is None

    def test_valid_target_score_change_only(self):
        """Test parsing response with only target_score change."""
        response = """{
            "private_thoughts": "Rule sets winning score to 100 points.",
            "flags": {},
            "target_score": 100
        }"""

        result = parse_judge_maintain_state_response(response)

        assert (
            result["private_thoughts"]
            == "Rule sets winning score to 100 points."
        )
        assert result["flags"] == {}
        assert result["target_score"] == 100

    def test_valid_both_changes(self):
        """Test parsing response with both flag and target_score changes."""
        response = """{
            "private_thoughts": "Multiple state changes required.",
            "flags": {"vote_mode": "unanimous"},
            "target_score": 50
        }"""

        result = parse_judge_maintain_state_response(response)

        assert result["flags"] == {"vote_mode": "unanimous"}
        assert result["target_score"] == 50

    def test_invalid_json(self):
        """Test that invalid JSON raises ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "flags": {}
        """  # Missing closing brace

        with pytest.raises(ValueError) as exc_info:
            parse_judge_maintain_state_response(response)

        assert "not valid JSON" in str(exc_info.value)

    def test_missing_private_thoughts(self):
        """Test that missing 'private_thoughts' raises ValueError."""
        response = """{
            "flags": {},
            "target_score": null
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_judge_maintain_state_response(response)

        assert "Missing required key" in str(exc_info.value)
        assert "private_thoughts" in str(exc_info.value)

    def test_missing_flags(self):
        """Test that missing 'flags' raises ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "target_score": null
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_judge_maintain_state_response(response)

        assert "Missing required key" in str(exc_info.value)
        assert "flags" in str(exc_info.value)

    def test_missing_target_score(self):
        """Test that missing 'target_score' raises ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "flags": {}
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_judge_maintain_state_response(response)

        assert "Missing required key" in str(exc_info.value)
        assert "target_score" in str(exc_info.value)

    def test_invalid_private_thoughts_type(self):
        """Test that non-string private_thoughts raises ValueError."""
        response = """{
            "private_thoughts": 123,
            "flags": {},
            "target_score": null
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_judge_maintain_state_response(response)

        assert "private_thoughts must be a string" in str(exc_info.value)

    def test_invalid_flags_type(self):
        """Test that non-dict flags raises ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "flags": "not_a_dict",
            "target_score": null
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_judge_maintain_state_response(response)

        assert "flags must be a dict" in str(exc_info.value)

    def test_invalid_target_score_type(self):
        """Test that non-int target_score raises ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "flags": {},
            "target_score": "100"
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_judge_maintain_state_response(response)

        assert "target_score must be an integer or null" in str(exc_info.value)

    def test_invalid_flag_value(self):
        """Test that invalid flag value raises ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "flags": {"vote_mode": "invalid"},
            "target_score": null
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_judge_maintain_state_response(response)

        assert "not valid" in str(exc_info.value)

    def test_unknown_flag_name(self):
        """Test that unknown flag name raises ValueError."""
        response = """{
            "private_thoughts": "Analysis",
            "flags": {"unknown_flag": "value"},
            "target_score": null
        }"""

        with pytest.raises(ValueError) as exc_info:
            parse_judge_maintain_state_response(response)

        assert "Unknown flag" in str(exc_info.value)

    def test_markdown_wrapped_json(self):
        """Test parsing JSON wrapped in markdown code blocks."""
        response = """```json
        {
            "private_thoughts": "No changes needed.",
            "flags": {},
            "target_score": null
        }
        ```"""

        result = parse_judge_maintain_state_response(response)

        assert result["private_thoughts"] == "No changes needed."
        assert result["flags"] == {}
        assert result["target_score"] is None
