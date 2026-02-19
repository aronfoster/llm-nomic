"""
Unit tests for the personality loader module.

Tests cover:
- Successful loading and parsing of personality files
- Correct section splitting on ## headers
- Caching behaviour (file is read once per process)
- Descriptive FileNotFoundError for unknown personalities
- Content of the three seeded personality files
"""

import pytest

from src.nomic_engine.llm.personality_loader import (
    _cache,
    _parse_sections,
    load_personality,
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
        text = "## PROPOSE_EXAMPLES\nSome example."
        result = _parse_sections(text)
        assert "PROPOSE_EXAMPLES" in result

    def test_json_braces_in_content_are_preserved(self):
        """Brace characters in section content are preserved unchanged."""
        text = '## PROPOSE_EXAMPLES\n{\n  "type": "ADD"\n}'
        result = _parse_sections(text)
        assert '{\n  "type": "ADD"\n}' == result["PROPOSE_EXAMPLES"]


# ---------------------------------------------------------------------------
# Tests for load_personality (uses the real personalities/ directory)
# ---------------------------------------------------------------------------


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
        for section in [
            "PERSONA",
            "STRATEGIC_GUIDANCE",
            "PROPOSE_EXAMPLES",
            "DISCUSS_EXAMPLES",
            "REVISE_EXAMPLES",
            "VOTE_EXAMPLES",
        ]:
            assert section in sections, f"Missing section: {section}"

    def test_load_friendly_has_required_sections(self):
        """Friendly file has all required sections."""
        sections = load_personality("friendly")
        for section in [
            "PERSONA",
            "STRATEGIC_GUIDANCE",
            "PROPOSE_EXAMPLES",
            "DISCUSS_EXAMPLES",
            "REVISE_EXAMPLES",
            "VOTE_EXAMPLES",
        ]:
            assert section in sections, f"Missing section: {section}"

    def test_load_none_has_required_sections(self):
        """None file has all required sections."""
        sections = load_personality("none")
        for section in [
            "PERSONA",
            "STRATEGIC_GUIDANCE",
            "PROPOSE_EXAMPLES",
            "DISCUSS_EXAMPLES",
            "REVISE_EXAMPLES",
            "VOTE_EXAMPLES",
        ]:
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
        """Friendly PERSONA describes cooperative play."""
        sections = load_personality("friendly")
        assert "cooperative player" in sections["PERSONA"]

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
