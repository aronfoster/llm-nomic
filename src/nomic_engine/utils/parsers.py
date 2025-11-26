"""
Parser utilities for reading and converting markdown rules format
into Rule data models.
"""

import logging
import re
from pathlib import Path
from typing import Union

from ..data_models import Rule, RuleStatus

logger = logging.getLogger(__name__)


def parse_rules_md(filepath: Union[str, Path]) -> list[Rule]:
    """
    Parse a markdown rules file and convert it into a list of Rule objects.

    The parser is a state machine that iterates line-by-line through the file,
    tracking the current section (Immutable/Mutable) and building Rule objects
    as it encounters rule headings and text.

    Args:
        filepath: Path to the markdown file to parse (e.g., 'rules.md' or
                  'Nomic_Initial_Ruleset_v0.md')

    Returns:
        A list of Rule objects parsed from the markdown file

    Raises:
        FileNotFoundError: If the specified file does not exist
        ValueError: If the file format is invalid

    Example:
        >>> rules = parse_rules_md("Nomic_Initial_Ruleset_v0.md")
        >>> len(rules)
        33
        >>> rules[0].rule_id
        '101'
        >>> rules[0].status
        <RuleStatus.IMMUTABLE: 'immutable'>
    """
    # Convert to Path object for easier handling
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"Rules file not found: {filepath}")

    # Initialize state variables
    rules: list[Rule] = []
    current_section: RuleStatus | None = None
    current_rule: Rule | None = None

    # Regex pattern to match rule headings: ### {rule_id} ({I|M})
    rule_heading_pattern = re.compile(r"^###\s+(\S+)\s+\(([A-Za-z])\)\s*$")

    with path.open("r", encoding="utf-8") as f:
        logger.debug(f"Opened rules file: {filepath}")
        for line in f:
            # Remove trailing newline for easier matching
            line = line.rstrip("\n")

            # Check for section headings
            if line.startswith("# Immutable Rules"):
                current_section = RuleStatus.IMMUTABLE
                logger.debug("Entering Immutable Rules section")
                continue
            elif line.startswith("# Mutable Rules"):
                current_section = RuleStatus.MUTABLE
                logger.debug("Entering Mutable Rules section")
                continue

            # Check for rule headings
            match = rule_heading_pattern.match(line)
            if match:
                rule_id = match.group(1)
                status_char = match.group(2).upper()

                # The status_char is the authoritative source of truth
                # Validate that it's either I or M
                if status_char == "I":
                    engine_status = RuleStatus.IMMUTABLE
                elif status_char == "M":
                    engine_status = RuleStatus.MUTABLE
                else:
                    raise ValueError(
                        f"Invalid status character '{status_char}' for rule "
                        f"{rule_id}. Must be 'I' (immutable) or 'M' (mutable)."
                    )

                # Log warning if section and status mismatch
                if current_section and engine_status != current_section:
                    logger.warning(
                        f"Rule {rule_id} status ({engine_status.value}) "
                        f"mismatches section {current_section.value}"
                    )

                # Create new rule and add to list
                current_rule = Rule(
                    rule_id=rule_id, text="", status=engine_status
                )
                rules.append(current_rule)
                logger.debug(
                    f"Created rule {rule_id} with status {engine_status.value}"
                )
                continue

            # Check for rule text (non-empty, non-heading lines)
            if line and not line.startswith("#") and current_rule is not None:
                # Append to current rule's text with newline
                current_rule.text += line + "\n"

    # Strip trailing newlines from all rule texts
    for rule in rules:
        rule.text = rule.text.rstrip("\n")

    logger.info(f"Parsed {len(rules)} rules from {filepath}")
    return rules
