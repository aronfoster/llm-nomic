"""
Comprehensive unit tests for the RulesManager class.

These tests validate all business logic, error handling, and file I/O
operations while ensuring test isolation via temporary files.
"""

import json
import tempfile
from pathlib import Path
from typing import List

import pytest

from src.nomic_engine.data_models import (
    Proposal,
    ProposalType,
    Rule,
    RuleStatus,
)
from src.nomic_engine.rules_manager import RulesManager

# --- Fixtures ---


@pytest.fixture
def sample_rules() -> List[Rule]:
    """Fixture providing a sample list of rules for testing."""
    return [
        Rule(
            rule_id="101",
            text="All players must follow the rules.",
            status=RuleStatus.IMMUTABLE,
        ),
        Rule(
            rule_id="102",
            text="Players take turns in order.",
            status=RuleStatus.IMMUTABLE,
        ),
        Rule(
            rule_id="201",
            text="Players can propose rule changes.",
            status=RuleStatus.MUTABLE,
        ),
        Rule(
            rule_id="202",
            text="Proposals must be voted on.",
            status=RuleStatus.MUTABLE,
        ),
    ]


@pytest.fixture
def rules_manager(sample_rules: List[Rule]) -> RulesManager:
    """Fixture providing a RulesManager instance with sample rules."""
    return RulesManager(rules=sample_rules)


# --- Tests for ProposalType.ADD ---


def test_apply_proposal_add_success(rules_manager: RulesManager) -> None:
    """Test successful addition of a new rule."""
    initial_count = len(rules_manager.rules)

    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        rule_id="301",
        new_text="New players start with 10 points.",
    )

    rules_manager.apply_proposal(proposal)

    assert len(rules_manager.rules) == initial_count + 1
    new_rule = rules_manager._find_rule_by_id("301")
    assert new_rule is not None
    assert new_rule.text == "New players start with 10 points."
    assert new_rule.status == RuleStatus.MUTABLE


def test_apply_proposal_add_duplicate_rule_id(
    rules_manager: RulesManager,
) -> None:
    """Test that adding a rule with duplicate rule_id raises ValueError."""
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        rule_id="101",  # Already exists
        new_text="Duplicate rule.",
    )

    with pytest.raises(ValueError, match="Rule 101 already exists"):
        rules_manager.apply_proposal(proposal)


def test_apply_proposal_add_missing_new_text(
    rules_manager: RulesManager,
) -> None:
    """Test that Add proposal without new_text raises ValueError."""
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        rule_id="301",
        new_text=None,
    )

    with pytest.raises(
        ValueError, match="Add proposals must have a rule_id and new_text"
    ):
        rules_manager.apply_proposal(proposal)


def test_apply_proposal_add_missing_rule_id(
    rules_manager: RulesManager,
) -> None:
    """Test that Add proposal without rule_id raises ValueError."""
    proposal = Proposal(
        proposer_name="Alice",
        move_number=1,
        type=ProposalType.ADD,
        rule_id=None,
        new_text="Some rule text.",
    )

    with pytest.raises(
        ValueError, match="Add proposals must have a rule_id and new_text"
    ):
        rules_manager.apply_proposal(proposal)


# --- Tests for ProposalType.AMEND ---


def test_apply_proposal_amend_success(rules_manager: RulesManager) -> None:
    """Test successful amendment of an existing mutable rule."""
    proposal = Proposal(
        proposer_name="Bob",
        move_number=2,
        type=ProposalType.AMEND,
        rule_id="201",
        new_text="Players can propose rule changes with proper justification.",
    )

    rules_manager.apply_proposal(proposal)

    amended_rule = rules_manager._find_rule_by_id("201")
    assert amended_rule is not None
    assert (
        amended_rule.text
        == "Players can propose rule changes with proper justification."
    )
    assert amended_rule.status == RuleStatus.MUTABLE


def test_apply_proposal_amend_nonexistent_rule(
    rules_manager: RulesManager,
) -> None:
    """Test that amending a non-existent rule_id raises ValueError."""
    proposal = Proposal(
        proposer_name="Bob",
        move_number=2,
        type=ProposalType.AMEND,
        rule_id="999",
        new_text="Updated text.",
    )

    with pytest.raises(ValueError, match="Rule 999 not found"):
        rules_manager.apply_proposal(proposal)


def test_apply_proposal_amend_missing_new_text(
    rules_manager: RulesManager,
) -> None:
    """Test that Amend proposal without new_text raises ValueError."""
    proposal = Proposal(
        proposer_name="Bob",
        move_number=2,
        type=ProposalType.AMEND,
        rule_id="201",
        new_text=None,
    )

    with pytest.raises(
        ValueError, match="Amend proposals must have a rule_id and new_text"
    ):
        rules_manager.apply_proposal(proposal)


def test_apply_proposal_amend_immutable_rule(
    rules_manager: RulesManager,
) -> None:
    """Test that amending an immutable rule raises ValueError."""
    proposal = Proposal(
        proposer_name="Bob",
        move_number=2,
        type=ProposalType.AMEND,
        rule_id="101",  # Immutable rule
        new_text="Cannot change this.",
    )

    with pytest.raises(ValueError, match="Cannot amend immutable rule 101"):
        rules_manager.apply_proposal(proposal)


# --- Tests for ProposalType.REPEAL ---


def test_apply_proposal_repeal_success(rules_manager: RulesManager) -> None:
    """Test successful repeal of an existing mutable rule."""
    initial_count = len(rules_manager.rules)

    proposal = Proposal(
        proposer_name="Charlie",
        move_number=3,
        type=ProposalType.REPEAL,
        rule_id="201",
    )

    rules_manager.apply_proposal(proposal)

    assert len(rules_manager.rules) == initial_count - 1
    assert rules_manager._find_rule_by_id("201") is None


def test_apply_proposal_repeal_nonexistent_rule(
    rules_manager: RulesManager,
) -> None:
    """Test that repealing a non-existent rule_id raises ValueError."""
    proposal = Proposal(
        proposer_name="Charlie",
        move_number=3,
        type=ProposalType.REPEAL,
        rule_id="999",
    )

    with pytest.raises(ValueError, match="Rule 999 not found"):
        rules_manager.apply_proposal(proposal)


def test_apply_proposal_repeal_immutable_rule(
    rules_manager: RulesManager,
) -> None:
    """Test that repealing an immutable rule raises ValueError."""
    proposal = Proposal(
        proposer_name="Charlie",
        move_number=3,
        type=ProposalType.REPEAL,
        rule_id="102",  # Immutable rule
    )

    with pytest.raises(ValueError, match="Cannot repeal immutable rule 102"):
        rules_manager.apply_proposal(proposal)


# --- Tests for ProposalType.TRANSMUTE ---


def test_apply_proposal_transmute_mutable_to_immutable(
    rules_manager: RulesManager,
) -> None:
    """Test successful transmutation from mutable to immutable."""
    proposal = Proposal(
        proposer_name="Dana",
        move_number=4,
        type=ProposalType.TRANSMUTE,
        rule_id="201",
    )

    rule = rules_manager._find_rule_by_id("201")
    assert rule is not None
    assert rule.status == RuleStatus.MUTABLE

    rules_manager.apply_proposal(proposal)

    assert rule.status == RuleStatus.IMMUTABLE


def test_apply_proposal_transmute_immutable_to_mutable(
    rules_manager: RulesManager,
) -> None:
    """Test successful transmutation from immutable to mutable."""
    proposal = Proposal(
        proposer_name="Dana",
        move_number=4,
        type=ProposalType.TRANSMUTE,
        rule_id="101",
    )

    rule = rules_manager._find_rule_by_id("101")
    assert rule is not None
    assert rule.status == RuleStatus.IMMUTABLE

    rules_manager.apply_proposal(proposal)

    assert rule.status == RuleStatus.MUTABLE


def test_apply_proposal_transmute_nonexistent_rule(
    rules_manager: RulesManager,
) -> None:
    """Test that transmuting a non-existent rule_id raises ValueError."""
    proposal = Proposal(
        proposer_name="Dana",
        move_number=4,
        type=ProposalType.TRANSMUTE,
        rule_id="999",
    )

    with pytest.raises(ValueError, match="Rule 999 not found"):
        rules_manager.apply_proposal(proposal)


# --- Tests for File I/O: load_from_jsonl ---


def test_load_from_jsonl_success() -> None:
    """Test successful loading from a correctly formatted JSONL file."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as f:
        temp_path = Path(f.name)
        f.write(
            '{"rule_id": "101", "text": "First rule.", '
            '"status": "immutable"}\n'
        )
        f.write(
            '{"rule_id": "201", "text": "Second rule.", "status": "mutable"}\n'
        )

    try:
        manager = RulesManager.load_from_jsonl(temp_path)

        assert len(manager.rules) == 2
        assert manager.rules[0].rule_id == "101"
        assert manager.rules[0].text == "First rule."
        assert manager.rules[0].status == RuleStatus.IMMUTABLE
        assert manager.rules[1].rule_id == "201"
        assert manager.rules[1].text == "Second rule."
        assert manager.rules[1].status == RuleStatus.MUTABLE
    finally:
        temp_path.unlink()


def test_load_from_jsonl_empty_lines() -> None:
    """Test that empty lines in JSONL file are skipped."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as f:
        temp_path = Path(f.name)
        f.write(
            '{"rule_id": "101", "text": "First rule.", '
            '"status": "immutable"}\n'
        )
        f.write("\n")
        f.write(
            '{"rule_id": "201", "text": "Second rule.", "status": "mutable"}\n'
        )
        f.write("   \n")

    try:
        manager = RulesManager.load_from_jsonl(temp_path)
        assert len(manager.rules) == 2
    finally:
        temp_path.unlink()


def test_load_from_jsonl_file_not_found() -> None:
    """Test that loading from a non-existent file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        RulesManager.load_from_jsonl("/nonexistent/path/rules.jsonl")


def test_load_from_jsonl_invalid_json() -> None:
    """Test that invalid JSON in a line raises JSONDecodeError."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as f:
        temp_path = Path(f.name)
        f.write(
            '{"rule_id": "101", "text": "First rule.", '
            '"status": "immutable"}\n'
        )
        f.write("invalid json here\n")

    try:
        with pytest.raises(json.JSONDecodeError):
            RulesManager.load_from_jsonl(temp_path)
    finally:
        temp_path.unlink()


# --- Tests for File I/O: save_to_jsonl ---


def test_save_to_jsonl_success(rules_manager: RulesManager) -> None:
    """Test successful saving of rules to a JSONL file."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as f:
        temp_path = Path(f.name)

    try:
        rules_manager.save_to_jsonl(temp_path)

        # Read back the file and verify contents
        with temp_path.open("r", encoding="utf-8") as f:
            lines = f.readlines()

        assert len(lines) == 4

        # Parse each line and verify
        rule_data_0 = json.loads(lines[0])
        assert rule_data_0["rule_id"] == "101"
        assert rule_data_0["text"] == "All players must follow the rules."
        assert rule_data_0["status"] == "immutable"

        rule_data_2 = json.loads(lines[2])
        assert rule_data_2["rule_id"] == "201"
        assert rule_data_2["status"] == "mutable"
    finally:
        temp_path.unlink()


def test_save_to_jsonl_enum_serialization() -> None:
    """Test that RuleStatus enum is correctly serialized to string values."""
    rules = [
        Rule(rule_id="101", text="Test rule.", status=RuleStatus.IMMUTABLE),
        Rule(rule_id="201", text="Another test.", status=RuleStatus.MUTABLE),
    ]
    manager = RulesManager(rules=rules)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as f:
        temp_path = Path(f.name)

    try:
        manager.save_to_jsonl(temp_path)

        with temp_path.open("r", encoding="utf-8") as f:
            lines = f.readlines()

        rule_data_0 = json.loads(lines[0])
        rule_data_1 = json.loads(lines[1])

        # Verify enum is serialized as string
        assert rule_data_0["status"] == "immutable"
        assert rule_data_1["status"] == "mutable"
    finally:
        temp_path.unlink()


# --- Tests for Markdown Rendering: render_to_markdown ---


def test_render_to_markdown_format(rules_manager: RulesManager) -> None:
    """Test that markdown file is generated with correct format."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        temp_path = Path(f.name)

    try:
        rules_manager.render_to_markdown(temp_path)

        with temp_path.open("r", encoding="utf-8") as f:
            content = f.read()

        # Check for main section headings
        assert "# Immutable Rules" in content
        assert "# Mutable Rules" in content

        # Check for rule headings with proper format (### not ##)
        assert "### 101 (I)" in content
        assert "### 102 (I)" in content
        assert "### 201 (M)" in content
        assert "### 202 (M)" in content

        # Check for rule text
        assert "All players must follow the rules." in content
        assert "Players can propose rule changes." in content

        # Ensure no horizontal rules (---) are present
        assert "---" not in content
    finally:
        temp_path.unlink()


def test_render_to_markdown_sorting() -> None:
    """Test markdown sorts immutable rules first, then mutable rules."""
    # Create rules in mixed order
    rules = [
        Rule(rule_id="301", text="Mutable rule 1.", status=RuleStatus.MUTABLE),
        Rule(
            rule_id="102",
            text="Immutable rule 2.",
            status=RuleStatus.IMMUTABLE,
        ),
        Rule(rule_id="201", text="Mutable rule 2.", status=RuleStatus.MUTABLE),
        Rule(
            rule_id="101",
            text="Immutable rule 1.",
            status=RuleStatus.IMMUTABLE,
        ),
    ]
    manager = RulesManager(rules=rules)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        temp_path = Path(f.name)

    try:
        manager.render_to_markdown(temp_path)

        with temp_path.open("r", encoding="utf-8") as f:
            content = f.read()

        # Find positions of rule headings
        pos_101 = content.find("### 101 (I)")
        pos_102 = content.find("### 102 (I)")
        pos_201 = content.find("### 201 (M)")
        pos_301 = content.find("### 301 (M)")

        # Verify immutable rules come before mutable rules
        assert pos_101 < pos_201
        assert pos_102 < pos_201
        assert pos_101 < pos_301
        assert pos_102 < pos_301

        # Verify alphanumeric sorting within each group
        assert pos_101 < pos_102  # 101 before 102 (both immutable)
        assert pos_201 < pos_301  # 201 before 301 (both mutable)
    finally:
        temp_path.unlink()


def test_render_to_markdown_alphanumeric_sorting() -> None:
    """Test alphanumeric sorting within status groups."""
    rules = [
        Rule(
            rule_id="Z99",
            text="Last alphabetically.",
            status=RuleStatus.MUTABLE,
        ),
        Rule(
            rule_id="A10",
            text="First alphabetically.",
            status=RuleStatus.MUTABLE,
        ),
        Rule(
            rule_id="B5",
            text="Second alphabetically.",
            status=RuleStatus.MUTABLE,
        ),
    ]
    manager = RulesManager(rules=rules)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        temp_path = Path(f.name)

    try:
        manager.render_to_markdown(temp_path)

        with temp_path.open("r", encoding="utf-8") as f:
            content = f.read()

        pos_a10 = content.find("### A10 (M)")
        pos_b5 = content.find("### B5 (M)")
        pos_z99 = content.find("### Z99 (M)")

        # Verify alphanumeric order
        assert pos_a10 < pos_b5 < pos_z99
    finally:
        temp_path.unlink()


def test_render_to_markdown_only_immutable() -> None:
    """Test markdown rendering with only immutable rules."""
    rules = [
        Rule(
            rule_id="101", text="First immutable.", status=RuleStatus.IMMUTABLE
        ),
        Rule(
            rule_id="102",
            text="Second immutable.",
            status=RuleStatus.IMMUTABLE,
        ),
    ]
    manager = RulesManager(rules=rules)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        temp_path = Path(f.name)

    try:
        manager.render_to_markdown(temp_path)

        with temp_path.open("r", encoding="utf-8") as f:
            content = f.read()

        assert "# Immutable Rules" in content
        assert "# Mutable Rules" not in content
        assert "### 101 (I)" in content
        assert "### 102 (I)" in content
    finally:
        temp_path.unlink()


def test_render_to_markdown_only_mutable() -> None:
    """Test markdown rendering with only mutable rules."""
    rules = [
        Rule(rule_id="201", text="First mutable.", status=RuleStatus.MUTABLE),
        Rule(rule_id="202", text="Second mutable.", status=RuleStatus.MUTABLE),
    ]
    manager = RulesManager(rules=rules)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        temp_path = Path(f.name)

    try:
        manager.render_to_markdown(temp_path)

        with temp_path.open("r", encoding="utf-8") as f:
            content = f.read()

        assert "# Immutable Rules" not in content
        assert "# Mutable Rules" in content
        assert "### 201 (M)" in content
        assert "### 202 (M)" in content
    finally:
        temp_path.unlink()
