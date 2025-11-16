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
                for rule in immutable_rules:
                    f.write(f"### {rule.rule_id} (I)\n")
                    f.write(f"{rule.text}\n\n")

            # Add blank line between sections if both exist
            if immutable_rules and mutable_rules:
                f.write("\n")

            # Write mutable rules section
            if mutable_rules:
                f.write("# Mutable Rules\n\n")
                for rule in mutable_rules:
                    f.write(f"### {rule.rule_id} (M)\n")
                    f.write(f"{rule.text}\n\n")

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

        Per Rule 108, ADD, AMEND, and TRANSMUTE proposals use the
        proposal's ID as the new rule ID. AMEND and TRANSMUTE are
        "repeal and replace" operations.

        Args:
            proposal: The Proposal object to apply (must have
                proposal_id assigned)

        Raises:
            ValueError: If the proposal is invalid or cannot be applied
        """
        # Validate that proposal_id has been assigned
        if proposal.proposal_id is None:
            raise ValueError(
                "Proposal must have proposal_id assigned before applying."
            )

        if proposal.type == ProposalType.ADD:
            # Validation: ADD proposals should not have a target_rule_id
            if proposal.target_rule_id is not None:
                raise ValueError(
                    "Add proposals must not have a target_rule_id."
                )

            if proposal.new_text is None:
                raise ValueError("Add proposals must have new_text.")

            # Check if rule with this ID already exists
            if self._find_rule_by_id(proposal.proposal_id) is not None:
                raise ValueError(
                    f"Rule {proposal.proposal_id} already exists."
                )

            # Create and add new rule with proposal_id (defaults to mutable)
            new_rule = Rule(
                rule_id=proposal.proposal_id,
                text=proposal.new_text,
                status=RuleStatus.MUTABLE,
            )
            self.rules.append(new_rule)
            logger.info(f"Added new rule {proposal.proposal_id}")

        elif proposal.type == ProposalType.AMEND:
            # Validation: AMEND requires target_rule_id and new_text
            if proposal.target_rule_id is None:
                raise ValueError("Amend proposals must have a target_rule_id.")

            if proposal.new_text is None:
                raise ValueError("Amend proposals must have new_text.")

            # Find the target rule
            target_rule = self._find_rule_by_id(proposal.target_rule_id)
            if target_rule is None:
                raise ValueError(f"Rule {proposal.target_rule_id} not found.")

            # Check if target rule is mutable
            if target_rule.status != RuleStatus.MUTABLE:
                raise ValueError(
                    f"Cannot amend immutable rule {proposal.target_rule_id}."
                )

            # Repeal and replace: Remove the original rule
            self.rules.remove(target_rule)

            # Add a new rule with the proposal_id
            new_rule = Rule(
                rule_id=proposal.proposal_id,
                text=proposal.new_text,
                status=RuleStatus.MUTABLE,
            )
            self.rules.append(new_rule)
            logger.info(
                f"Amended rule {proposal.target_rule_id} -> "
                f"new rule {proposal.proposal_id}"
            )

        elif proposal.type == ProposalType.REPEAL:
            # Validation: REPEAL requires target_rule_id
            if proposal.target_rule_id is None:
                raise ValueError(
                    "Repeal proposals must have a target_rule_id."
                )

            # Find the target rule
            target_rule = self._find_rule_by_id(proposal.target_rule_id)
            if target_rule is None:
                raise ValueError(f"Rule {proposal.target_rule_id} not found.")

            # Check if rule is mutable
            if target_rule.status != RuleStatus.MUTABLE:
                raise ValueError(
                    f"Cannot repeal immutable rule {proposal.target_rule_id}."
                )

            # Remove the rule (no replacement for REPEAL)
            self.rules.remove(target_rule)
            logger.info(f"Repealed rule {proposal.target_rule_id}")

        elif proposal.type == ProposalType.TRANSMUTE:
            # Validation: TRANSMUTE requires target_rule_id
            if proposal.target_rule_id is None:
                raise ValueError(
                    "Transmute proposals must have a target_rule_id."
                )

            # Find the target rule
            target_rule = self._find_rule_by_id(proposal.target_rule_id)
            if target_rule is None:
                raise ValueError(f"Rule {proposal.target_rule_id} not found.")

            # Determine the new status (flip)
            if target_rule.status == RuleStatus.MUTABLE:
                new_status = RuleStatus.IMMUTABLE
            else:
                new_status = RuleStatus.MUTABLE

            # Repeal and replace: Remove the original rule
            self.rules.remove(target_rule)

            # Add a new rule with the proposal_id, original text,
            # and flipped status
            new_rule = Rule(
                rule_id=proposal.proposal_id,
                text=target_rule.text,
                status=new_status,
            )
            self.rules.append(new_rule)
            logger.info(
                f"Transmuted rule {proposal.target_rule_id} -> "
                f"new rule {proposal.proposal_id} "
                f"with status {new_status.value}"
            )
