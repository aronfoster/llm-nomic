"""
Proposal validation logic.

This module contains functions for validating proposal legality
using side-effect-free dry runs.
"""

import logging

from ..data_models import Proposal
from ..core.game_manager import GameManager
from ..core.rules_manager import RulesManager

logger = logging.getLogger(__name__)


def validate_proposal(
    proposal: Proposal, player_name: str, game_manager: GameManager
) -> tuple[bool, str]:
    """
    Validate proposal legality using a side-effect-free dry run.

    This function performs validation by applying the proposal to a
    temporary copy of the rules, ensuring the real rules are never
    modified during validation.

    Args:
        proposal: The proposal to validate (must have proposal_id set)
        player_name: The name of the player making the proposal
        game_manager: The GameManager instance for accessing game state
            and rules

    Returns:
        Tuple of (is_valid, error_message)
        - is_valid: True if proposal is legal, False otherwise
        - error_message: Empty string if valid, error description if
          invalid
    """
    assert game_manager.game_state is not None
    assert game_manager.rules_manager is not None

    try:
        # Validate that proposer_name matches the player
        if proposal.proposer_name != player_name:
            return (
                False,
                f"Player {player_name} submitted an illegal proposal "
                f"attributed to {proposal.proposer_name}.",
            )

        # Create deep copies of all rules (Pydantic model_copy)
        rules_copy = [
            rule.model_copy(deep=True)
            for rule in game_manager.rules_manager.rules
        ]

        # Create a temporary RulesManager for validation
        temp_rules_manager = RulesManager(rules=rules_copy)

        # Try to apply the proposal on the TEMP manager
        # The real rules_manager is never touched
        temp_rules_manager.apply_proposal(proposal)

        # If we get here, the proposal is valid
        logger.info(
            f"Proposal validation passed for ID {proposal.proposal_id}"
        )
        return (True, "")

    except ValueError as e:
        logger.warning(f"Illegal proposal from {player_name}: {e}")
        return (False, str(e))
