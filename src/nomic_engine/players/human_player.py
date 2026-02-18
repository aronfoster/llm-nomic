"""
Human player implementation for the Nomic game.

This module provides a command-line interface for human players
to participate in the game.
"""

from typing import Literal

from ..data_models import (
    Discussion,
    GameState,
    Proposal,
    ProposalType,
    Rule,
    Vote,
)
from .base_player import BasePlayer


class HumanPlayer(BasePlayer):
    """
    A human player that interacts via command-line input.

    This player implementation prompts the user for input at each
    decision point using the standard input() function.
    """

    def propose(
        self,
        game_state: GameState,
        rules: list[Rule],
        continue_turn: bool = False,
        withdrawal_attempt: int = 0,
        max_withdrawal_retries: int = 0,
    ) -> Proposal:
        """
        Interactively gather a proposal from the human player.

        Prompts the user for:
        - Proposal type (Add/Repeal/Transmute/Emend)
        - Rule ID (if applicable)
        - New text (if applicable)
        - Rationale (optional)

        Args:
            game_state: The current state of the game.
            rules: The current list of all rules.
            continue_turn: True when retrying after a withdrawal.
            withdrawal_attempt: The current withdrawal attempt number.
            max_withdrawal_retries: The maximum number of withdrawal retries.

        Returns:
            A complete Proposal object based on user input.
        """
        if continue_turn:
            print(
                f"\n--- {self.player_name}'s Turn: "
                f"Pivoting After Withdrawal "
                f"(attempt {withdrawal_attempt} of {max_withdrawal_retries})"
                " ---"
            )
            print(
                "You may now submit a fresh proposal with any type or "
                "target rule."
            )
            print(
                "NOTE: If during the revision phase you want to change the "
                "proposal TYPE or TARGET RULE, choose WITHDRAW — not MODIFY. "
                "Withdrawing there will give you another proposal opportunity "
                "(if retries remain)."
            )
        else:
            print(f"\n--- {self.player_name}'s Turn: Making a Proposal ---")

        # Get proposal type
        while True:
            type_input = (
                input("Propose (A)dd, (R)epeal, (T)ransmute, or (E)mend? ")
                .strip()
                .upper()
            )

            if type_input in ["A", "ADD"]:
                proposal_type = ProposalType.ADD
                break
            elif type_input in ["R", "REPEAL"]:
                proposal_type = ProposalType.REPEAL
                break
            elif type_input in ["T", "TRANSMUTE"]:
                proposal_type = ProposalType.TRANSMUTE
                break
            elif type_input in ["E", "EMEND", "AMEND"]:
                proposal_type = ProposalType.AMEND
                break
            else:
                print("Invalid choice. Please enter A, R, T, or E.")

        # Get rule ID (not needed for ADD)
        rule_id: str | None = None
        if proposal_type != ProposalType.ADD:
            while True:
                rule_id_input = input("Rule ID to affect? ").strip()
                if rule_id_input:
                    rule_id = rule_id_input
                    break
                else:
                    print("Rule ID is required for this proposal type.")

        # Get new text (needed for ADD and AMEND)
        new_text: str | None = None
        if proposal_type in [ProposalType.ADD, ProposalType.AMEND]:
            new_text_input = input("New text for the rule? ").strip()
            if new_text_input:
                new_text = new_text_input
            else:
                # Allow empty text but warn the user
                print("Warning: Creating rule with empty text.")
                new_text = ""

        # Get optional rationale
        rationale_input = input("Rationale (optional): ").strip()
        rationale: str | None = rationale_input if rationale_input else None

        # Construct and return the proposal
        return Proposal(
            proposer_name=self.player_name,
            move_number=game_state.move_number,
            type=proposal_type,
            proposal_id=None,
            target_rule_id=rule_id,
            new_text=new_text,
            rationale=rationale,
            private_thoughts=None,
        )

    def discuss(
        self,
        proposal: Proposal,
        game_state: GameState,
        rules: list[Rule],
        continue_turn: bool = False,
    ) -> Discussion:
        """
        Allow the human player to discuss a proposal.

        Displays the proposal and prompts for discussion input.

        Args:
            proposal: The proposal being discussed.
            game_state: The current state of the game.
            rules: The current list of all rules.
            continue_turn: Accepted for interface consistency with LLMPlayer.
                Human players naturally remember prior rounds, so this
                parameter has no behavioural effect.

        Returns:
            A Discussion object containing the player's discussion.
            If the player skips, Discussion.text will be empty.
        """
        print(f"\n--- {self.player_name}'s Turn: Discussion Phase ---")
        print(f"Proposal by {proposal.proposer_name}:")
        print(f"  Type: {proposal.type.value}")
        if proposal.target_rule_id:
            print(f"  Target Rule ID: {proposal.target_rule_id}")

            # Show original rule text for AMEND, REPEAL, or TRANSMUTE
            if proposal.type in [
                ProposalType.AMEND,
                ProposalType.REPEAL,
                ProposalType.TRANSMUTE,
            ]:
                original_rule = next(
                    (
                        rule
                        for rule in rules
                        if rule.rule_id == proposal.target_rule_id
                    ),
                    None,
                )
                if original_rule:
                    print(f"  Original Text: {original_rule.text}")
                else:
                    print("  Original Text: [Rule not found]")

        if proposal.new_text:
            print(f"  New Text: {proposal.new_text}")
        if proposal.rationale:
            print(f"  Rationale: {proposal.rationale}")

        discussion_text = input(
            "Enter discussion (or press Enter to skip): "
        ).strip()
        return Discussion(
            player_name=self.player_name,
            text=discussion_text,
            private_thoughts=None,
        )

    def vote(
        self, proposal: Proposal, game_state: GameState, rules: list[Rule]
    ) -> Vote:
        """
        Gather a vote from the human player.

        Displays the proposal and prompts for a vote (Yes/No/Abstain)
        and optional rationale.

        Args:
            proposal: The proposal being voted on.
            game_state: The current state of the game.
            rules: The current list of all rules.

        Returns:
            A Vote object representing the player's vote.
        """
        print(f"\n--- {self.player_name}'s Turn: Voting Phase ---")
        print(f"Proposal by {proposal.proposer_name}:")
        print(f"  Type: {proposal.type.value}")
        if proposal.target_rule_id:
            print(f"  Target Rule ID: {proposal.target_rule_id}")

            # Show original rule text for AMEND, REPEAL, or TRANSMUTE
            if proposal.type in [
                ProposalType.AMEND,
                ProposalType.REPEAL,
                ProposalType.TRANSMUTE,
            ]:
                original_rule = next(
                    (
                        rule
                        for rule in rules
                        if rule.rule_id == proposal.target_rule_id
                    ),
                    None,
                )
                if original_rule:
                    print(f"  Original Text: {original_rule.text}")
                else:
                    print("  Original Text: [Rule not found]")

        if proposal.new_text:
            print(f"  New Text: {proposal.new_text}")
        if proposal.rationale:
            print(f"  Rationale: {proposal.rationale}")

        # Get vote
        vote_value: Literal["YES", "NO", "ABSTAIN"]
        while True:
            vote_input = (
                input("Vote (Y)es, (N)o, or (A)bstain: ").strip().upper()
            )

            if vote_input in ["Y", "YES"]:
                vote_value = "YES"
                break
            elif vote_input in ["N", "NO"]:
                vote_value = "NO"
                break
            elif vote_input in ["A", "ABSTAIN"]:
                vote_value = "ABSTAIN"
                break
            else:
                print("Invalid choice. Please enter Y, N, or A.")

        # Get optional reason
        reason_input = input("Rationale (optional): ").strip()
        reason: str | None = reason_input if reason_input else None

        return Vote(
            player_name=self.player_name, vote=vote_value, reason=reason
        )

    def revise(
        self,
        proposal: Proposal,
        discussions: list[Discussion],
        game_state: GameState,
        rules: list[Rule],
    ) -> Proposal | None:
        """
        Allow the human player to revise their proposal based on discussion.

        Displays the original proposal, all discussions, and prompts the user
        to revise, submit as-is, or withdraw. Implements Rule 112 enforcement
        (must revise or withdraw if discussions contain "UNCLEAR" or
        "AMBIGUOUS").

        Args:
            proposal: The original proposal made by this player.
            discussions: A list of Discussion objects from all players.
            game_state: The current state of the game.
            rules: The current list of all rules.

        Returns:
            The (potentially) revised Proposal object,
            or None if the player chooses to withdraw the proposal.
        """
        print(f"\n--- {self.player_name}'s Turn: Revision Phase ---")

        # Print original proposal details
        print("\nOriginal Proposal:")
        print(f"  Type: {proposal.type.value}")
        if proposal.target_rule_id:
            print(f"  Target Rule ID: {proposal.target_rule_id}")
        if proposal.new_text:
            print(f"  New Text: {proposal.new_text}")
        if proposal.rationale:
            print(f"  Rationale: {proposal.rationale}")

        # Print all discussions
        print("\n--- Discussions ---")
        for discussion in discussions:
            if discussion.text:
                print(f"{discussion.player_name}: {discussion.text}")
            else:
                print(f"{discussion.player_name}: (Abstained)")

        # Check for Rule 112: must revise if any discussion contains
        # "UNCLEAR" or "AMBIGUOUS"
        must_revise = any(
            "UNCLEAR" in d.text.upper() or "AMBIGUOUS" in d.text.upper()
            for d in discussions
        )

        # Build prompt based on Rule 112
        # TODO: Remove this because rule v1 no longer has this
        if must_revise:
            print(
                "\n⚠️  Rule 112: A discussion contains 'UNCLEAR' or "
                "'AMBIGUOUS'."
            )
            print("You MUST revise or withdraw this proposal.")
            prompt = "You MUST (R)evise or (W)ithdraw: "
        else:
            prompt = "(R)evise, (S)ubmit as-is, or (W)ithdraw: "

        # Handle input
        while True:
            choice = input(prompt).strip().upper()

            if choice in ["W", "WITHDRAW"]:
                print("Proposal withdrawn.")
                return None

            elif choice in ["S", "SUBMIT"] and not must_revise:
                print("Submitting proposal as-is.")
                return proposal

            elif choice in ["R", "REVISE"]:
                # Create a copy of the original proposal
                new_proposal = proposal.model_copy()

                # Prompt for new text (if applicable for this proposal type)
                if proposal.type in [ProposalType.ADD, ProposalType.AMEND]:
                    new_text_input = input(
                        f"New text for the rule (current: "
                        f"'{proposal.new_text}'): "
                    ).strip()
                    if new_text_input:
                        new_proposal.new_text = new_text_input
                    else:
                        print("Keeping original new_text.")

                # Prompt for new rationale
                rationale_input = input(
                    f"New rationale (current: '{proposal.rationale}'): "
                ).strip()
                if rationale_input:
                    new_proposal.rationale = rationale_input
                else:
                    print("Keeping original rationale.")

                print("Proposal revised.")
                return new_proposal

            else:
                if must_revise:
                    print("Invalid choice. You must enter R or W.")
                else:
                    print("Invalid choice. Please enter R, S, or W.")
