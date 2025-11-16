"""
Human player implementation for the Nomic game.

This module provides a command-line interface for human players
to participate in the game.
"""

from typing import Literal

from ..data_models import GameState, Proposal, ProposalType, Rule, Vote
from .base_player import BasePlayer


class HumanPlayer(BasePlayer):
    """
    A human player that interacts via command-line input.

    This player implementation prompts the user for input at each
    decision point using the standard input() function.
    """

    def propose(self, game_state: GameState, rules: list[Rule]) -> Proposal:
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

        Returns:
            A complete Proposal object based on user input.
        """
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
        )

    def discuss(
        self, proposal: Proposal, game_state: GameState, rules: list[Rule]
    ) -> str | None:
        """
        Allow the human player to discuss a proposal.

        Displays the proposal and prompts for discussion input.

        Args:
            proposal: The proposal being discussed.
            game_state: The current state of the game.
            rules: The current list of all rules.

        Returns:
            A string containing the discussion, or None if the user
            chooses not to discuss.
        """
        print(f"\n--- {self.player_name}'s Turn: Discussion Phase ---")
        print(f"Proposal by {proposal.proposer_name}:")
        print(f"  Type: {proposal.type.value}")
        if proposal.target_rule_id:
            print(f"  Target Rule ID: {proposal.target_rule_id}")
        if proposal.new_text:
            print(f"  New Text: {proposal.new_text}")
        if proposal.rationale:
            print(f"  Rationale: {proposal.rationale}")

        discussion = input(
            "Enter discussion (or press Enter to skip): "
        ).strip()
        return discussion if discussion else None

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
