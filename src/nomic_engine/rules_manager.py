"""
RulesManager: The sole authority for loading, saving, and modifying
the game's rule set.
"""

import json
import logging
from pathlib import Path
from typing import Optional, Union

from .data_models import (
    Proposal,
    ProposalType,
    Rule,
    RuleStatus,
)

logger = logging.getLogger(__name__)


class RulesManager:
    """Manages the game's rule set - loading, saving, and applying changes."""

    def __init__(self, rules: list[Rule]) -> None:
        """
        Initialize the RulesManager with a list of rules.

        Args:
            rules: List of Rule objects representing the game's rules
        """
        self.rules = rules

    @classmethod
    def load_from_jsonl(cls, filepath: Union[str, Path]) -> "RulesManager":
        """
        Load rules from a JSONL file and return a new RulesManager instance.

        Args:
            filepath: Path to the rules.jsonl file

        Returns:
            A new RulesManager instance with the loaded rules

        Raises:
            FileNotFoundError: If the file doesn't exist
            json.JSONDecodeError: If a line is not valid JSON
            pydantic.ValidationError: If a line doesn't match the Rule schema
        """
        filepath = Path(filepath)
        rules: list[Rule] = []

        logger.debug(f"Loading rules from {filepath}")

        with filepath.open("r", encoding="utf-8") as f:
            for line_number, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue

                try:
                    rule_data = json.loads(line)
                    rule = Rule(**rule_data)
                    rules.append(rule)
                except json.JSONDecodeError as e:
                    logger.error(
                        f"Invalid JSON on line {line_number} in "
                        f"{filepath}: {e}"
                    )
                    raise
                except Exception as e:
                    logger.error(
                        f"Failed to validate rule on line {line_number} "
                        f"in {filepath}: {e}"
                    )
                    raise

        logger.debug(f"Successfully loaded {len(rules)} rules from {filepath}")
        return cls(rules)

    def save_to_jsonl(self, filepath: Union[str, Path]) -> None:
        """
        Save the current rules to a JSONL file.

        Args:
            filepath: Path to the rules.jsonl file to write

        Raises:
            IOError: If the file cannot be written
        """
        filepath = Path(filepath)
        logger.debug(f"Saving {len(self.rules)} rules to {filepath}")

        with filepath.open("w", encoding="utf-8") as f:
            for rule in self.rules:
                json_line = rule.model_dump_json()
                f.write(json_line + "\n")

        logger.debug(f"Successfully saved rules to {filepath}")

    def render_to_markdown(self, filepath: Union[str, Path]) -> None:
        """
        Generate a human-readable markdown file from the current rules.

        Rules are sorted with immutable rules first, then mutable rules.
        Within each group, rules are sorted alphanumerically by rule_id.

        Args:
            filepath: Path to the rules.md file to write

        Raises:
            IOError: If the file cannot be written
        """
        filepath = Path(filepath)
        logger.debug(f"Rendering rules to markdown at {filepath}")

        # Separate and sort rules
        immutable_rules = [
            r for r in self.rules if r.status == RuleStatus.IMMUTABLE
        ]
        mutable_rules = [
            r for r in self.rules if r.status == RuleStatus.MUTABLE
        ]

        # Sort each group by rule_id alphanumerically
        immutable_rules.sort(key=lambda r: r.rule_id)
        mutable_rules.sort(key=lambda r: r.rule_id)

        with filepath.open("w", encoding="utf-8") as f:
            # Write immutable rules section
            if immutable_rules:
                f.write("# Immutable Rules\n\n")
                for i, rule in enumerate(immutable_rules):
                    f.write(f"## Rule {rule.rule_id} (I)\n")
                    f.write(f"{rule.text}\n")
                    if i < len(immutable_rules) - 1:
                        f.write("\n---\n\n")

            # Add separator between sections if both exist
            if immutable_rules and mutable_rules:
                f.write("\n\n---\n\n")

            # Write mutable rules section
            if mutable_rules:
                f.write("# Mutable Rules\n\n")
                for i, rule in enumerate(mutable_rules):
                    f.write(f"## Rule {rule.rule_id} (M)\n")
                    f.write(f"{rule.text}\n")
                    if i < len(mutable_rules) - 1:
                        f.write("\n---\n\n")

        logger.debug(
            f"Successfully rendered {len(self.rules)} rules to {filepath}"
        )

    def _find_rule_by_id(self, rule_id: str) -> Optional[Rule]:
        """
        Find a rule by its ID.

        Args:
            rule_id: The rule ID to search for

        Returns:
            The Rule object if found, None otherwise
        """
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule
        return None

    def apply_proposal(self, proposal: Proposal) -> None:
        """
        Apply a proposal to modify the rules in memory.

        Args:
            proposal: The Proposal object to apply

        Raises:
            ValueError: If the proposal is invalid or cannot be applied
        """
        if proposal.type == ProposalType.ADD:
            # Validation
            if proposal.rule_id is None or proposal.new_text is None:
                raise ValueError(
                    "Add proposals must have a rule_id and new_text."
                )

            # Check if rule already exists
            if self._find_rule_by_id(proposal.rule_id) is not None:
                raise ValueError(f"Rule {proposal.rule_id} already exists.")

            # Create and add new rule (defaults to mutable)
            new_rule = Rule(
                rule_id=proposal.rule_id,
                text=proposal.new_text,
                status=RuleStatus.MUTABLE,
            )
            self.rules.append(new_rule)
            logger.info(f"Added new rule {proposal.rule_id}")

        elif proposal.type == ProposalType.AMEND:
            # Validation
            if proposal.rule_id is None or proposal.new_text is None:
                raise ValueError(
                    "Amend proposals must have a rule_id and new_text."
                )

            # Find the rule
            rule = self._find_rule_by_id(proposal.rule_id)
            if rule is None:
                raise ValueError(f"Rule {proposal.rule_id} not found.")

            # Check if rule is mutable
            if rule.status != RuleStatus.MUTABLE:
                raise ValueError(
                    f"Cannot amend immutable rule {proposal.rule_id}."
                )

            # Update the rule text
            rule.text = proposal.new_text
            logger.info(f"Amended rule {proposal.rule_id}")

        elif proposal.type == ProposalType.REPEAL:
            # Validation
            if proposal.rule_id is None:
                raise ValueError("Repeal proposals must have a rule_id.")

            # Find the rule
            rule = self._find_rule_by_id(proposal.rule_id)
            if rule is None:
                raise ValueError(f"Rule {proposal.rule_id} not found.")

            # Check if rule is mutable
            if rule.status != RuleStatus.MUTABLE:
                raise ValueError(
                    f"Cannot repeal immutable rule {proposal.rule_id}."
                )

            # Remove the rule
            self.rules.remove(rule)
            logger.info(f"Repealed rule {proposal.rule_id}")

        elif proposal.type == ProposalType.TRANSMUTE:
            # Validation
            if proposal.rule_id is None:
                raise ValueError("Transmute proposals must have a rule_id.")

            # Find the rule
            rule = self._find_rule_by_id(proposal.rule_id)
            if rule is None:
                raise ValueError(f"Rule {proposal.rule_id} not found.")

            # Flip the rule's status
            if rule.status == RuleStatus.MUTABLE:
                rule.status = RuleStatus.IMMUTABLE
            else:
                rule.status = RuleStatus.MUTABLE
            logger.info(
                f"Transmuted rule {proposal.rule_id} to {rule.status.value}"
            )
