"""
Unit tests for the personality loader module.

Tests cover:
- Successful loading and parsing of personality files
- Correct section splitting on ## headers
- Caching behaviour (file is read once per process)
- Descriptive FileNotFoundError for unknown personalities
- Content of the three seeded personality files
- parse_section_fields: field extraction from prose sections
"""

import pytest

from src.nomic_engine.llm.personality_loader import (
    _cache,
    _parse_sections,
    load_personality,
    parse_section_fields,
)

# ---------------------------------------------------------------------------
# Tests for _parse_sections (pure parser — no filesystem)
# ---------------------------------------------------------------------------


class TestParseSections:
    """Unit tests for the low-level markdown section parser."""

    def test_single_section(self):
        """A single ## section is parsed into a one-entry dict."""
        text = "## PERSONA\nYou are {player_name}."
        result = _parse_sections(text)
        assert result == {"PERSONA": "You are {player_name}."}

    def test_multiple_sections(self):
        """Multiple ## sections are all captured."""
        text = (
            "## PERSONA\nYou are {player_name}.\n\n"
            "## STRATEGIC_GUIDANCE\nBe strategic.\n"
        )
        result = _parse_sections(text)
        assert result["PERSONA"] == "You are {player_name}."
        assert result["STRATEGIC_GUIDANCE"] == "Be strategic."

    def test_content_before_first_header_is_ignored(self):
        """Lines before the first ## header are discarded."""
        text = "<!-- comment -->\n# Title\n## PERSONA\nContent."
        result = _parse_sections(text)
        assert list(result.keys()) == ["PERSONA"]
        assert result["PERSONA"] == "Content."

    def test_section_content_is_stripped(self):
        """Leading/trailing whitespace within each section is stripped."""
        text = "## PERSONA\n\n  You are {player_name}.  \n\n"
        result = _parse_sections(text)
        assert result["PERSONA"] == "You are {player_name}."

    def test_empty_section(self):
        """An empty section yields an empty string."""
        text = "## PERSONA\n## STRATEGIC_GUIDANCE\nSome text."
        result = _parse_sections(text)
        assert result["PERSONA"] == ""
        assert result["STRATEGIC_GUIDANCE"] == "Some text."

    def test_empty_input(self):
        """Empty input returns an empty dict."""
        assert _parse_sections("") == {}

    def test_section_names_preserved(self):
        """Section names are returned exactly as written."""
        text = "## PROPOSE_ADD_EXAMPLE\nSome example."
        result = _parse_sections(text)
        assert "PROPOSE_ADD_EXAMPLE" in result

    def test_field_text_in_content_is_preserved(self):
        """Field text in section content is preserved unchanged."""
        text = (
            "## PROPOSE_ADD_EXAMPLE\n"
            "private_thoughts: I want to win.\n"
            "new_text: A rule."
        )
        result = _parse_sections(text)
        section = result["PROPOSE_ADD_EXAMPLE"]
        assert "private_thoughts: I want to win." in section
        assert "new_text: A rule." in section


# ---------------------------------------------------------------------------
# Tests for parse_section_fields (pure parser — no filesystem)
# ---------------------------------------------------------------------------


class TestParseSectionFields:
    """Unit tests for the labeled prose field parser."""

    def test_single_field(self):
        """A single field line is parsed into a one-entry dict."""
        text = "private_thoughts: I want to win."
        result = parse_section_fields(text)
        assert result == {"private_thoughts": "I want to win."}

    def test_multiple_fields(self):
        """Multiple field lines are all captured."""
        text = (
            "private_thoughts: I want to win.\n"
            "new_text: A rule that helps.\n"
            "rationale: It is fair.\n"
        )
        result = parse_section_fields(text)
        assert result["private_thoughts"] == "I want to win."
        assert result["new_text"] == "A rule that helps."
        assert result["rationale"] == "It is fair."

    def test_empty_input(self):
        """Empty input returns an empty dict."""
        assert parse_section_fields("") == {}

    def test_field_value_is_stripped(self):
        """Leading/trailing whitespace in field values is stripped."""
        text = "private_thoughts:   Some thought.   "
        result = parse_section_fields(text)
        assert result["private_thoughts"] == "Some thought."

    def test_continuation_line_joined(self):
        """Non-field continuation lines are joined to previous value."""
        text = (
            "private_thoughts: First part\n"
            "  second part\n"
            "new_text: A rule.\n"
        )
        result = parse_section_fields(text)
        assert result["private_thoughts"] == "First part second part"
        assert result["new_text"] == "A rule."

    def test_blank_lines_ignored(self):
        """Blank lines between fields do not affect parsing."""
        text = "private_thoughts: Thought.\n\nnew_text: Rule.\n"
        result = parse_section_fields(text)
        assert result["private_thoughts"] == "Thought."
        assert result["new_text"] == "Rule."

    def test_field_with_colon_in_value(self):
        """Colons in field values are preserved."""
        text = "private_thoughts: See rules 201-203: they matter."
        result = parse_section_fields(text)
        assert result["private_thoughts"] == "See rules 201-203: they matter."

    def test_missing_field_returns_empty(self):
        """Accessing a missing field via .get returns the default."""
        text = "private_thoughts: A thought."
        result = parse_section_fields(text)
        assert result.get("new_text", "") == ""

    def test_target_rule_id_field(self):
        """target_rule_id field is parsed as a plain string."""
        text = (
            "private_thoughts: Amend it.\n"
            "target_rule_id: 201\n"
            "rationale: Better."
        )
        result = parse_section_fields(text)
        assert result["target_rule_id"] == "201"


# ---------------------------------------------------------------------------
# Tests for load_personality (uses the real personalities/ directory)
# ---------------------------------------------------------------------------

_NEW_SECTIONS = [
    "PERSONA",
    "STRATEGIC_GUIDANCE",
    "PROPOSE_ADD_EXAMPLE",
    "PROPOSE_AMEND_EXAMPLE",
    "PROPOSE_REPEAL_EXAMPLE",
    "PROPOSE_TRANSMUTE_EXAMPLE",
    "DISCUSS_COMMENT_EXAMPLE",
    "DISCUSS_ABSTAIN_EXAMPLE",
    "REVISE_KEEP_EXAMPLE",
    "REVISE_MODIFY_EXAMPLE",
    "REVISE_WITHDRAW_EXAMPLE",
    "VOTE_YES_EXAMPLE",
    "VOTE_NO_EXAMPLE",
]


class TestLoadPersonality:
    """Integration tests for load_personality using real personality files."""

    def test_load_machiavellian_returns_dict(self):
        """load_personality('machiavellian') returns a non-empty dict."""
        sections = load_personality("machiavellian")
        assert isinstance(sections, dict)
        assert len(sections) > 0

    def test_load_machiavellian_has_required_sections(self):
        """Machiavellian file has all required sections."""
        sections = load_personality("machiavellian")
        for section in _NEW_SECTIONS:
            assert section in sections, f"Missing section: {section}"

    def test_load_friendly_has_required_sections(self):
        """Friendly file has all required sections."""
        sections = load_personality("friendly")
        for section in _NEW_SECTIONS:
            assert section in sections, f"Missing section: {section}"

    def test_load_none_has_required_sections(self):
        """None file has all required sections."""
        sections = load_personality("none")
        for section in _NEW_SECTIONS:
            assert section in sections, f"Missing section: {section}"

    def test_machiavellian_persona_has_player_name_placeholder(self):
        """Machiavellian PERSONA section contains {player_name}."""
        sections = load_personality("machiavellian")
        assert "{player_name}" in sections["PERSONA"]

    def test_friendly_persona_has_player_name_placeholder(self):
        """Friendly PERSONA section contains {player_name}."""
        sections = load_personality("friendly")
        assert "{player_name}" in sections["PERSONA"]

    def test_none_persona_has_player_name_placeholder(self):
        """None PERSONA section contains {player_name}."""
        sections = load_personality("none")
        assert "{player_name}" in sections["PERSONA"]

    def test_machiavellian_persona_contains_expected_content(self):
        """Machiavellian PERSONA describes ruthlessly competitive play."""
        sections = load_personality("machiavellian")
        assert "ruthlessly competitive" in sections["PERSONA"]

    def test_friendly_persona_contains_expected_content(self):
        """Friendly PERSONA is non-empty and distinct from machiavellian."""
        friendly = load_personality("friendly")
        machiavellian = load_personality("machiavellian")
        assert len(friendly["PERSONA"]) > 0
        assert friendly["PERSONA"] != machiavellian["PERSONA"]

    def test_none_persona_contains_expected_content(self):
        """None PERSONA is minimal — contains 'player in a game of Nomic'."""
        sections = load_personality("none")
        assert "player in a game of Nomic" in sections["PERSONA"]

    def test_none_persona_is_minimal(self):
        """None PERSONA does not contain strategy-specific language."""
        sections = load_personality("none")
        assert "ruthlessly" not in sections["PERSONA"]
        assert "cooperative" not in sections["PERSONA"]
        assert "alliance" not in sections["PERSONA"]

    def test_example_sections_contain_private_thoughts_field(self):
        """All per-case example sections contain a private_thoughts field."""
        example_sections = [s for s in _NEW_SECTIONS if s.endswith("_EXAMPLE")]
        for personality in ("machiavellian", "friendly", "none"):
            sections = load_personality(personality)
            for section in example_sections:
                fields = parse_section_fields(sections[section])
                assert (
                    "private_thoughts" in fields
                ), f"{personality}/{section} missing private_thoughts field"

    def test_propose_add_example_has_required_fields(self):
        """PROPOSE_ADD_EXAMPLE sections have new_text and rationale."""
        for personality in ("machiavellian", "friendly", "none"):
            sections = load_personality(personality)
            fields = parse_section_fields(sections["PROPOSE_ADD_EXAMPLE"])
            assert (
                "new_text" in fields
            ), f"{personality} PROPOSE_ADD_EXAMPLE missing new_text"
            assert (
                "rationale" in fields
            ), f"{personality} PROPOSE_ADD_EXAMPLE missing rationale"

    def test_propose_amend_example_has_target_rule_id(self):
        """PROPOSE_AMEND_EXAMPLE sections have a target_rule_id field."""
        for personality in ("machiavellian", "friendly", "none"):
            sections = load_personality(personality)
            fields = parse_section_fields(sections["PROPOSE_AMEND_EXAMPLE"])
            assert (
                "target_rule_id" in fields
            ), f"{personality} PROPOSE_AMEND_EXAMPLE missing target_rule_id"

    def test_discuss_comment_example_has_discussion_text_field(self):
        """DISCUSS_COMMENT_EXAMPLE sections have a discussion_text field."""
        for personality in ("machiavellian", "friendly", "none"):
            sections = load_personality(personality)
            fields = parse_section_fields(sections["DISCUSS_COMMENT_EXAMPLE"])
            assert (
                "discussion_text" in fields
            ), f"{personality} DISCUSS_COMMENT_EXAMPLE: no discussion_text"

    def test_vote_examples_have_public_reason_field(self):
        """VOTE_YES_EXAMPLE and VOTE_NO_EXAMPLE have a public_reason field."""
        for personality in ("machiavellian", "friendly", "none"):
            sections = load_personality(personality)
            for section in ("VOTE_YES_EXAMPLE", "VOTE_NO_EXAMPLE"):
                fields = parse_section_fields(sections[section])
                assert (
                    "public_reason" in fields
                ), f"{personality} {section} missing public_reason"

    def test_missing_personality_raises_file_not_found(self):
        """load_personality raises FileNotFoundError for unknown name."""
        with pytest.raises(FileNotFoundError) as exc_info:
            load_personality("nonexistent_personality_xyz")
        assert "nonexistent_personality_xyz" in str(exc_info.value)

    def test_missing_personality_error_is_descriptive(self):
        """FileNotFoundError message includes the expected path."""
        with pytest.raises(FileNotFoundError) as exc_info:
            load_personality("nonexistent_personality_xyz")
        message = str(exc_info.value)
        assert "nonexistent_personality_xyz.md" in message

    def test_result_is_cached(self):
        """A second call with the same name returns the cached dict."""
        # Warm the cache
        first = load_personality("friendly")
        # Retrieve again — must be the exact same object (cached)
        second = load_personality("friendly")
        assert first is second

    def test_cached_value_is_in_module_cache(self):
        """After loading, the result appears in the module-level cache."""
        load_personality("none")
        assert "none" in _cache
