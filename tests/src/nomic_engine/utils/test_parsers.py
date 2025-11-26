"""
Tests for the rules markdown parser.

This test suite validates that the parser can correctly read markdown rules
files and convert them into Rule data models.
"""

import logging
import tempfile
from pathlib import Path

import pytest

from src.nomic_engine.data_models import RuleStatus
from src.nomic_engine.utils.parsers import parse_rules_md


def test_parse_nomic_initial_ruleset():
    """Test that Nomic_Initial_Ruleset_v0.md is parsed correctly."""
    # Parse the actual initial ruleset file
    rules = parse_rules_md("Nomic_Initial_Ruleset_v0.md")

    # Validate we got the expected number of rules
    # There are 17 immutable rules (101-117) and 16 mutable rules (201-216)
    assert len(rules) == 33

    # Check first rule (101)
    rule_101 = rules[0]
    assert rule_101.rule_id == "101"
    assert rule_101.status == RuleStatus.IMMUTABLE
    assert "All players must always abide" in rule_101.text
    assert "Initial Set are in effect" in rule_101.text

    # Check last immutable rule (117)
    rule_117 = rules[16]
    assert rule_117.rule_id == "117"
    assert rule_117.status == RuleStatus.IMMUTABLE
    assert "not prohibited or regulated" in rule_117.text

    # Check first mutable rule (201)
    rule_201 = rules[17]
    assert rule_201.rule_id == "201"
    assert rule_201.status == RuleStatus.MUTABLE
    assert "Players shall alternate" in rule_201.text

    # Check last rule (216)
    rule_216 = rules[32]
    assert rule_216.rule_id == "216"
    assert rule_216.status == RuleStatus.MUTABLE
    assert "further play is impossible" in rule_216.text


def test_parse_multiline_rule_text():
    """Test that multi-line rule text is captured correctly."""
    # Create a temporary file with multi-line rules
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write("# Immutable Rules\n")
        f.write("\n")
        f.write("### 101 (I)\n")
        f.write("This is the first line.\n")
        f.write("This is the second line.\n")
        f.write("This is the third line.\n")
        f.write("\n")
        f.write("### 102 (I)\n")
        f.write("Single line rule.\n")
        temp_path = f.name

    try:
        rules = parse_rules_md(temp_path)

        # Validate first rule has all three lines
        assert len(rules) == 2
        assert rules[0].rule_id == "101"
        assert rules[0].text == (
            "This is the first line.\n"
            "This is the second line.\n"
            "This is the third line."
        )

        # Validate second rule has single line
        assert rules[1].rule_id == "102"
        assert rules[1].text == "Single line rule."
    finally:
        Path(temp_path).unlink()


def test_parse_status_from_tag():
    """Test that status is correctly parsed from (I)/(M) tags."""
    # Create a temporary file with both immutable and mutable rules
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write("# Immutable Rules\n")
        f.write("\n")
        f.write("### 101 (I)\n")
        f.write("Immutable rule text.\n")
        f.write("\n")
        f.write("# Mutable Rules\n")
        f.write("\n")
        f.write("### 201 (M)\n")
        f.write("Mutable rule text.\n")
        temp_path = f.name

    try:
        rules = parse_rules_md(temp_path)

        # Validate statuses
        assert len(rules) == 2
        assert rules[0].rule_id == "101"
        assert rules[0].status == RuleStatus.IMMUTABLE
        assert rules[1].rule_id == "201"
        assert rules[1].status == RuleStatus.MUTABLE
    finally:
        Path(temp_path).unlink()


def test_parse_status_mismatch_warning(caplog):
    """Test that mismatch logging is triggered when status mismatch."""
    # Create a temporary file with a mismatch: mutable rule in
    # immutable section
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write("# Immutable Rules\n")
        f.write("\n")
        f.write("### 201 (M)\n")
        f.write("This mutable rule is in the immutable section.\n")
        f.write("\n")
        f.write("# Mutable Rules\n")
        f.write("\n")
        f.write("### 101 (I)\n")
        f.write("This immutable rule is in the mutable section.\n")
        temp_path = f.name

    try:
        with caplog.at_level(logging.WARNING):
            rules = parse_rules_md(temp_path)

        # Validate that warnings were logged
        assert len(caplog.records) >= 2

        # Check that the warning messages mention the mismatches
        warning_messages = [record.message for record in caplog.records]
        assert any(
            "Rule 201" in msg and "mismatch" in msg for msg in warning_messages
        )
        assert any(
            "Rule 101" in msg and "mismatch" in msg for msg in warning_messages
        )

        # Validate that the rules use the status from the tag (authoritative)
        assert len(rules) == 2
        assert rules[0].rule_id == "201"
        assert rules[0].status == RuleStatus.MUTABLE  # Tag says M
        assert rules[1].rule_id == "101"
        assert rules[1].status == RuleStatus.IMMUTABLE  # Tag says I
    finally:
        Path(temp_path).unlink()


def test_parse_file_not_found():
    """Test that FileNotFoundError is raised for non-existent files."""
    with pytest.raises(FileNotFoundError):
        parse_rules_md("nonexistent_file.md")


def test_parse_empty_rule_text():
    """Test that rules with no text content are handled correctly."""
    # Create a temporary file with a rule that has no text
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write("# Immutable Rules\n")
        f.write("\n")
        f.write("### 101 (I)\n")
        f.write("\n")
        f.write("### 102 (I)\n")
        f.write("This rule has text.\n")
        temp_path = f.name

    try:
        rules = parse_rules_md(temp_path)

        # Validate that empty rule has empty text
        assert len(rules) == 2
        assert rules[0].rule_id == "101"
        assert rules[0].text == ""
        assert rules[1].rule_id == "102"
        assert rules[1].text == "This rule has text."
    finally:
        Path(temp_path).unlink()


def test_parse_ignores_non_rule_headings():
    """Test that non-rule headings (##, ####) are ignored."""
    # Create a temporary file with various heading levels
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write("# Immutable Rules\n")
        f.write("\n")
        f.write("## This is a subsection heading\n")
        f.write("\n")
        f.write("### 101 (I)\n")
        f.write("Rule text here.\n")
        temp_path = f.name

    try:
        rules = parse_rules_md(temp_path)

        # Validate that only the rule was parsed
        assert len(rules) == 1
        assert rules[0].rule_id == "101"
        assert rules[0].text == "Rule text here."
    finally:
        Path(temp_path).unlink()


def test_parse_rule_ids_can_be_alphanumeric():
    """Test that rule IDs can contain letters and numbers."""
    # Create a temporary file with alphanumeric rule IDs
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write("# Mutable Rules\n")
        f.write("\n")
        f.write("### 301A (M)\n")
        f.write("First variant rule.\n")
        f.write("\n")
        f.write("### 301B (M)\n")
        f.write("Second variant rule.\n")
        temp_path = f.name

    try:
        rules = parse_rules_md(temp_path)

        # Validate that alphanumeric IDs work
        assert len(rules) == 2
        assert rules[0].rule_id == "301A"
        assert rules[1].rule_id == "301B"
    finally:
        Path(temp_path).unlink()


def test_parse_preserves_rule_order():
    """Test that rules are parsed in the order they appear in the file."""
    # Create a temporary file with rules in specific order
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write("# Immutable Rules\n")
        f.write("\n")
        f.write("### 105 (I)\n")
        f.write("Fifth rule.\n")
        f.write("\n")
        f.write("### 103 (I)\n")
        f.write("Third rule.\n")
        f.write("\n")
        f.write("### 101 (I)\n")
        f.write("First rule.\n")
        temp_path = f.name

    try:
        rules = parse_rules_md(temp_path)

        # Validate order is preserved (not sorted)
        assert len(rules) == 3
        assert rules[0].rule_id == "105"
        assert rules[1].rule_id == "103"
        assert rules[2].rule_id == "101"
    finally:
        Path(temp_path).unlink()


def test_parse_invalid_status_character():
    """Test that ValueError is raised for invalid status characters."""
    # Create a temporary file with an invalid status character
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write("# Immutable Rules\n")
        f.write("\n")
        f.write("### 101 (X)\n")
        f.write("Rule with invalid status.\n")
        temp_path = f.name

    try:
        with pytest.raises(ValueError) as exc_info:
            parse_rules_md(temp_path)

        # Validate error message
        assert "Invalid status character 'X'" in str(exc_info.value)
        assert "rule 101" in str(exc_info.value)
        assert "Must be 'I' (immutable) or 'M' (mutable)" in str(
            exc_info.value
        )
    finally:
        Path(temp_path).unlink()


def test_parse_case_insensitive_status():
    """Test that status characters are case-insensitive."""
    # Create a temporary file with lowercase status characters
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write("# Immutable Rules\n")
        f.write("\n")
        f.write("### 101 (i)\n")
        f.write("Immutable rule with lowercase i.\n")
        f.write("\n")
        f.write("# Mutable Rules\n")
        f.write("\n")
        f.write("### 201 (m)\n")
        f.write("Mutable rule with lowercase m.\n")
        temp_path = f.name

    try:
        rules = parse_rules_md(temp_path)

        # Validate that lowercase status characters work
        assert len(rules) == 2
        assert rules[0].rule_id == "101"
        assert rules[0].status == RuleStatus.IMMUTABLE
        assert rules[1].rule_id == "201"
        assert rules[1].status == RuleStatus.MUTABLE
    finally:
        Path(temp_path).unlink()
