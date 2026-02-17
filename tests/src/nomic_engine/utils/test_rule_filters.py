"""
Tests for rule filtering utilities.

This test suite validates the filter_scoring_rules function that filters
rules to only those relevant for scoring decisions.
"""

from src.nomic_engine.data_models import Rule, RuleStatus
from src.nomic_engine.utils.rule_filters import filter_scoring_rules


def test_filter_scoring_rules_with_point():
    """Test that rules containing 'point' are included."""
    rules = [
        Rule(
            rule_id="101",
            text="Players gain 1 point for successful proposals.",
            status=RuleStatus.MUTABLE,
        ),
        Rule(
            rule_id="102",
            text="This rule has nothing to do with scoring.",
            status=RuleStatus.MUTABLE,
        ),
    ]

    result = filter_scoring_rules(rules)

    assert len(result) == 1
    assert result[0].rule_id == "101"


def test_filter_scoring_rules_with_score():
    """Test that rules containing 'score' are included."""
    rules = [
        Rule(
            rule_id="101",
            text="The target score is 100 points.",
            status=RuleStatus.IMMUTABLE,
        ),
        Rule(
            rule_id="102",
            text="This rule is about voting.",
            status=RuleStatus.MUTABLE,
        ),
    ]

    result = filter_scoring_rules(rules)

    assert len(result) == 1
    assert result[0].rule_id == "101"


def test_filter_scoring_rules_with_both():
    """Test that rules containing both 'point' and 'score' are included."""
    rules = [
        Rule(
            rule_id="101",
            text="Each player starts with a score of 0 points.",
            status=RuleStatus.IMMUTABLE,
        ),
        Rule(
            rule_id="102",
            text="Proposals require unanimous approval.",
            status=RuleStatus.MUTABLE,
        ),
    ]

    result = filter_scoring_rules(rules)

    assert len(result) == 1
    assert result[0].rule_id == "101"
    assert "point" in result[0].text.lower()
    assert "score" in result[0].text.lower()


def test_filter_scoring_rules_case_insensitive():
    """Test that filtering is case-insensitive."""
    rules = [
        Rule(
            rule_id="101",
            text="Players gain 1 POINT for proposals.",
            status=RuleStatus.MUTABLE,
        ),
        Rule(
            rule_id="102",
            text="The target SCORE is 100.",
            status=RuleStatus.MUTABLE,
        ),
        Rule(
            rule_id="103",
            text="Mixed case PoInT and ScOrE.",
            status=RuleStatus.MUTABLE,
        ),
        Rule(
            rule_id="104",
            text="No scoring keywords here.",
            status=RuleStatus.MUTABLE,
        ),
    ]

    result = filter_scoring_rules(rules)

    assert len(result) == 3
    result_ids = {r.rule_id for r in result}
    assert result_ids == {"101", "102", "103"}


def test_filter_scoring_rules_empty_list():
    """Test that filtering an empty list returns an empty list."""
    rules = []

    result = filter_scoring_rules(rules)

    assert result == []
    assert isinstance(result, list)


def test_filter_scoring_rules_no_matches():
    """Test that filtering with no matches returns an empty list."""
    rules = [
        Rule(
            rule_id="101",
            text="Proposals must be submitted in writing.",
            status=RuleStatus.MUTABLE,
        ),
        Rule(
            rule_id="102",
            text="Voting is done by majority.",
            status=RuleStatus.MUTABLE,
        ),
        Rule(
            rule_id="103",
            text="The game ends when conditions are met.",
            status=RuleStatus.IMMUTABLE,
        ),
    ]

    result = filter_scoring_rules(rules)

    assert result == []


def test_filter_scoring_rules_all_match():
    """Test that all rules can match if they all contain scoring keywords."""
    rules = [
        Rule(
            rule_id="201",
            text="Players gain 1 point for successful proposals.",
            status=RuleStatus.MUTABLE,
        ),
        Rule(
            rule_id="202",
            text="The target score is 100.",
            status=RuleStatus.IMMUTABLE,
        ),
        Rule(
            rule_id="203",
            text="Unanimous proposals award 2 bonus points.",
            status=RuleStatus.MUTABLE,
        ),
    ]

    result = filter_scoring_rules(rules)

    assert len(result) == 3
    result_ids = [r.rule_id for r in result]
    assert result_ids == ["201", "202", "203"]


def test_filter_scoring_rules_preserves_order():
    """Test that filtering preserves the original order of rules."""
    rules = [
        Rule(
            rule_id="205",
            text="Players gain points for creativity.",
            status=RuleStatus.MUTABLE,
        ),
        Rule(
            rule_id="101",
            text="No scoring here.",
            status=RuleStatus.MUTABLE,
        ),
        Rule(
            rule_id="203",
            text="The score can be negative.",
            status=RuleStatus.MUTABLE,
        ),
        Rule(
            rule_id="102",
            text="Also no scoring.",
            status=RuleStatus.MUTABLE,
        ),
    ]

    result = filter_scoring_rules(rules)

    assert len(result) == 2
    assert result[0].rule_id == "205"
    assert result[1].rule_id == "203"


def test_filter_scoring_rules_partial_word_match():
    """Test that 'point' and 'score' match within larger words."""
    rules = [
        Rule(
            rule_id="101",
            text="Players must appoint a representative.",
            status=RuleStatus.MUTABLE,
        ),
        Rule(
            rule_id="102",
            text="Scores are calculated from scorecard.",
            status=RuleStatus.MUTABLE,
        ),
    ]

    result = filter_scoring_rules(rules)

    # Both should match because "point" is in "appoint" and "score" is in both
    assert len(result) == 2
    result_ids = {r.rule_id for r in result}
    assert result_ids == {"101", "102"}
