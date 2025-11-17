"""
GameLoop: The "Conductor" class that orchestrates the 5-step turn logic.

This class is responsible for executing turns, validating all player actions,
calculating state changes, and interfacing with the Human Judge.
"""

import logging

from .data_models import Proposal, ProposalType, Rule, Vote
from .game_manager import GameManager
from .players.base_player import BasePlayer
from .rules_manager import RulesManager

logger = logging.getLogger(__name__)


class GameLoop:
    """
    The main game loop controller.

    Orchestrates the 5-step turn logic:
    1. Propose (with validation)
    2. Discuss
    3. Revise (V1 stub)
    4. Vote
    5. Resolve (tally, judge, apply changes, advance turn)
    """

    def __init__(
        self, game_manager: GameManager, players: list[BasePlayer]
    ) -> None:
        """
        Initialize the GameLoop.

        Args:
            game_manager: The GameManager instance for this game
            players: List of all instantiated player objects

        Raises:
            ValueError: If game_manager is not properly loaded
        """
        # Validate that game_manager is properly loaded
        if game_manager.game_state is None:
            raise ValueError(
                "GameManager must have game_state loaded before "
                "creating GameLoop"
            )
        if game_manager.rules_manager is None:
            raise ValueError(
                "GameManager must have rules_manager loaded before "
                "creating GameLoop"
            )

        self.game_manager = game_manager
        self.players = players

    def run_turn(self) -> None:
        """
        Execute a complete game turn through all 5 steps.

        This method orchestrates the entire turn process:
        1. Get proposal from current player (with validation)
        2. Collect discussion from all players (per Rule 111)
        3. Allow revision (V1 stub - not implemented)
        4. Collect votes from all players (per Rule 105)
        5. Resolve the turn (tally, judge, apply changes, advance)

        Raises:
            Exception: Any unexpected errors during turn execution
        """
        # Type narrowing: These are guaranteed non-None by __init__ validation
        assert self.game_manager.game_state is not None
        assert self.game_manager.rules_manager is not None

        try:
            logger.info(
                f"Starting turn {self.game_manager.game_state.move_number}"
            )

            # Get current player
            current_player = self._get_current_player()

            # Step 1: Propose (with validation)
            proposal = self._run_step_1_propose(current_player)
            if proposal is None:
                logger.warning("Turn ended due to illegal proposal")
                return

            # Step 2: Discuss
            discussions: list[tuple[str, str]] = self._run_step_2_discuss(
                proposal, self.players
            )

            # Step 3: Revise
            revised_proposal = self._run_step_3_revise(
                current_player, proposal, discussions
            )

            # Check if proposal was withdrawn
            if revised_proposal is None:
                logger.warning(
                    f"Proposal {proposal.proposal_id} withdrawn by "
                    f"{current_player.player_name}"
                )
                # TODO: Log this withdrawal to the transcript
                return  # End the turn

            # If not withdrawn, use the revised proposal for voting
            proposal = revised_proposal

            # Step 4: Vote
            votes = self._run_step_4_vote(proposal, self.players)

            # Step 5: Resolve
            self._run_step_5_resolve(proposal, votes, discussions)

            logger.info(
                f"Completed turn {self.game_manager.game_state.move_number}"
            )

        except Exception as e:
            logger.error(f"Error during turn execution: {e}", exc_info=True)
            raise

    def _get_current_player(self) -> BasePlayer:
        """
        Find and return the current player object.

        Returns:
            The BasePlayer object whose turn it is

        Raises:
            ValueError: If current player name not found in players list
        """
        assert self.game_manager.game_state is not None
        current_name = self.game_manager.game_state.current_player_name
        for player in self.players:
            if player.player_name == current_name:
                return player

        raise ValueError(
            f"Current player '{current_name}' not found in players list"
        )

    def _get_other_players(self) -> list[BasePlayer]:
        """
        Get all players except the current player.

        Returns:
            List of BasePlayer objects excluding the current player
        """
        assert self.game_manager.game_state is not None
        current_name = self.game_manager.game_state.current_player_name
        return [p for p in self.players if p.player_name != current_name]

    def _validate_proposal_legality(
        self, proposal: Proposal, player_name: str
    ) -> tuple[bool, str]:
        """
        Validate proposal legality using a side-effect-free dry run.

        This method performs validation by applying the proposal to a
        temporary copy of the rules, ensuring the real rules are never
        modified during validation.

        Args:
            proposal: The proposal to validate (must have proposal_id set)
            player_name: The name of the player making the proposal

        Returns:
            Tuple of (is_valid, error_message)
            - is_valid: True if proposal is legal, False otherwise
            - error_message: Empty string if valid, error description if
              invalid
        """
        assert self.game_manager.game_state is not None
        assert self.game_manager.rules_manager is not None

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
                for rule in self.game_manager.rules_manager.rules
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

    def _run_step_1_propose(
        self, current_player: BasePlayer
    ) -> Proposal | None:
        """
        Step 1: Get proposal from current player and validate it.

        This method performs immediate validation by doing a dry run
        of apply_proposal to check for ValueError (illegal proposals).

        Args:
            current_player: The player whose turn it is

        Returns:
            Proposal object if valid, None if illegal

        Raises:
            ValueError: If player returns invalid proposal
        """
        assert self.game_manager.game_state is not None
        assert self.game_manager.rules_manager is not None

        logger.info(f"Step 1: {current_player.player_name} proposing")

        # Get the proposal from the player
        proposal = current_player.propose(
            game_state=self.game_manager.game_state,
            rules=self.game_manager.rules_manager.rules,
        )

        logger.debug(
            f"Proposal received: type={proposal.type}, "
            f"target_rule_id={proposal.target_rule_id}"
        )

        # Validate that the player did not try to assign a proposal_id
        if proposal.proposal_id is not None:
            raise ValueError(
                "Players cannot assign proposal_id. "
                "It is assigned by the engine."
            )

        # Assign the proposal ID before validation
        current_id_str = str(self.game_manager.game_state.next_proposal_id)
        proposal.proposal_id = current_id_str

        # Validate the proposal using the extracted validation logic
        is_valid, error_message = self._validate_proposal_legality(
            proposal, current_player.player_name
        )

        if is_valid:
            logger.info(
                f"Proposal validation passed, assigned ID {current_id_str}"
            )
            return proposal
        else:
            # Handle illegal proposal
            print(f"\n❌ ILLEGAL PROPOSAL: {error_message}")
            print(f"Proposer: {current_player.player_name}")
            print("The proposal cannot proceed.\n")

            # Log illegal proposal to transcript
            transcript_lines = [
                f"## MOVE #{self.game_manager.game_state.move_number}",
                f"**Proposer:** {current_player.player_name}",
                f"**Type:** {proposal.type.value}",
            ]

            if proposal.target_rule_id:
                transcript_lines.append(
                    f"**Target Rule ID:** {proposal.target_rule_id}"
                )

            if proposal.new_text:
                transcript_lines.append(f"**New Text:** {proposal.new_text}")

            if proposal.rationale:
                transcript_lines.append(f"**Rationale:** {proposal.rationale}")

            transcript_lines.extend(
                [
                    "",
                    "**Result:** ILLEGAL PROPOSAL",
                    f"**Reason:** {error_message}",
                ]
            )

            transcript_entry = "\n".join(transcript_lines)
            self.game_manager.logger.log_transcript(transcript_entry)

            # Clear the proposal_id since validation failed
            proposal.proposal_id = None
            return None

    def _run_step_2_discuss(
        self, proposal: Proposal, players: list[BasePlayer]
    ) -> list[tuple[str, str]]:
        """
        Step 2: Collect discussion from all players.

        Per Rule 111, all players (including the proposer) may discuss.

        Args:
            proposal: The proposal to discuss
            players: List of all players

        Returns:
            List of tuples (player_name, discussion) (excludes None responses)
        """
        assert self.game_manager.game_state is not None
        assert self.game_manager.rules_manager is not None

        logger.info("Step 2: Discussion phase")

        discussions: list[tuple[str, str]] = []

        for player in players:
            discussion = player.discuss(
                proposal=proposal,
                game_state=self.game_manager.game_state,
                rules=self.game_manager.rules_manager.rules,
            )

            if discussion is not None:
                discussions.append((player.player_name, discussion))
                logger.debug(f"{player.player_name} provided discussion")
            else:
                logger.debug(f"{player.player_name} abstained from discussion")

        logger.info(f"Collected {len(discussions)} discussion responses")
        return discussions

    def _run_step_3_revise(
        self,
        current_player: BasePlayer,
        proposal: Proposal,
        discussions: list[tuple[str, str]],
    ) -> Proposal | None:
        """
        Step 3: Allow proposer to revise based on discussion.

        Per Rules 111 and 112, the proposer may revise their proposal after
        reviewing discussions. If any discussion contains "UNCLEAR" or
        "AMBIGUOUS", the proposer must revise or withdraw (Rule 112).

        CRITICAL: If the player returns a NEW proposal object (not the
        original), it MUST be re-validated for legality.

        Args:
            current_player: The player who made the proposal
            proposal: The original proposal
            discussions: List of tuples (player_name, discussion) from players

        Returns:
            The (potentially) revised Proposal object, or None if withdrawn
            or if revised proposal is illegal
        """
        assert self.game_manager.game_state is not None
        assert self.game_manager.rules_manager is not None

        logger.info("Step 3: Revision phase")

        # Call the player's revise method
        revised_proposal = current_player.revise(
            proposal=proposal,
            discussions=discussions,
            game_state=self.game_manager.game_state,
            rules=self.game_manager.rules_manager.rules,
        )

        if revised_proposal is None:
            logger.info(f"Proposal withdrawn by {current_player.player_name}")
            return None
        elif revised_proposal is proposal:
            logger.info("Proposal submitted as-is (no revision)")
            return revised_proposal
        else:
            # Player returned a NEW proposal object - must re-validate
            logger.info("Proposal revised - re-validating for legality")

            # Ensure the revised proposal has the same proposal_id
            if revised_proposal.proposal_id != proposal.proposal_id:
                revised_proposal.proposal_id = proposal.proposal_id

            # Validate the revised proposal
            is_valid, error_message = self._validate_proposal_legality(
                revised_proposal, current_player.player_name
            )

            if is_valid:
                logger.info("Revised proposal passed validation")
                return revised_proposal
            else:
                # Revised proposal is illegal
                logger.warning(
                    f"Revised proposal from {current_player.player_name} "
                    f"is ILLEGAL: {error_message}"
                )
                print(f"\n❌ ILLEGAL REVISED PROPOSAL: {error_message}")
                print(f"Proposer: {current_player.player_name}")
                print("The revised proposal cannot proceed.\n")

                # Log illegal revised proposal to transcript
                transcript_lines = [
                    f"## MOVE #{self.game_manager.game_state.move_number}",
                    f"**Proposer:** {current_player.player_name}",
                    f"**Type:** {revised_proposal.type.value}",
                ]

                if revised_proposal.target_rule_id:
                    transcript_lines.append(
                        f"**Target Rule ID:** "
                        f"{revised_proposal.target_rule_id}"
                    )

                if revised_proposal.new_text:
                    transcript_lines.append(
                        f"**New Text:** {revised_proposal.new_text}"
                    )

                if revised_proposal.rationale:
                    transcript_lines.append(
                        f"**Rationale:** {revised_proposal.rationale}"
                    )

                transcript_lines.extend(
                    [
                        "",
                        "**Result:** ILLEGAL REVISED PROPOSAL",
                        f"**Reason:** {error_message}",
                    ]
                )

                transcript_entry = "\n".join(transcript_lines)
                self.game_manager.logger.log_transcript(transcript_entry)

                return None

    def _run_step_4_vote(
        self, proposal: Proposal, players: list[BasePlayer]
    ) -> list[Vote]:
        """
        Step 4: Collect votes from all players.

        Per Rule 105, every player must participate in every vote.

        Args:
            proposal: The proposal to vote on
            players: List of all players

        Returns:
            List of Vote objects from all players
        """
        assert self.game_manager.game_state is not None
        assert self.game_manager.rules_manager is not None

        logger.info("Step 4: Voting phase")

        votes: list[Vote] = []

        for player in players:
            vote = player.vote(
                proposal=proposal,
                game_state=self.game_manager.game_state,
                rules=self.game_manager.rules_manager.rules,
            )

            votes.append(vote)
            logger.debug(f"{player.player_name} voted: {vote.vote}")

        logger.info(f"Collected {len(votes)} votes")
        return votes

    def _run_step_5_resolve(
        self,
        proposal: Proposal,
        votes: list[Vote],
        discussions: list[tuple[str, str]],
    ) -> None:
        """
        Step 5: Resolve the turn - tally votes, consult judge, apply
        changes.

        This method:
        - Tallies votes to determine pass/fail
        - Consults the human judge for veto decision
        - Prompts judge to manually assign scores
        - Applies proposal to rules if passed and not vetoed
        - Advances to next turn
        - Saves state and logs transcript

        Args:
            proposal: The proposal that was voted on
            votes: List of Vote objects from all players
            discussions: List of tuples (player_name, discussion) from
                discussion phase

        Raises:
            ValueError: If game state is invalid
        """
        assert self.game_manager.game_state is not None
        assert self.game_manager.rules_manager is not None

        logger.info("Step 5: Resolution phase")

        # Tally votes
        yes_votes = sum(1 for v in votes if v.vote == "YES")
        no_votes = sum(1 for v in votes if v.vote == "NO")
        abstain_votes = sum(1 for v in votes if v.vote == "ABSTAIN")

        total_voters = len(votes)

        # Rule 203: Unanimous pass requirement
        # Special case: If there are zero voters (empty votes list),
        # the proposal automatically passes
        if total_voters == 0:
            proposal_passed = True
        else:
            # Proposal must receive unanimous YES votes to pass
            proposal_passed = yes_votes == total_voters

        logger.info(
            f"Vote tally: YES={yes_votes}, NO={no_votes}, "
            f"ABSTAIN={abstain_votes}, Passed={proposal_passed}"
        )

        # Print proposal and voting results to console
        print("\n" + "=" * 60)
        print(f"PROPOSAL #{self.game_manager.game_state.move_number}")
        print(f"Proposal ID: {proposal.proposal_id}")
        print(f"Proposer: {proposal.proposer_name}")
        print(f"Type: {proposal.type}")
        if proposal.target_rule_id:
            print(f"Target Rule ID: {proposal.target_rule_id}")
        if proposal.new_text:
            print(f"New Text: {proposal.new_text}")
        if proposal.rationale:
            print(f"Rationale: {proposal.rationale}")
        print("\nVOTING RESULTS:")
        print(f"  YES: {yes_votes}")
        print(f"  NO: {no_votes}")
        print(f"  ABSTAIN: {abstain_votes}")
        print(f"\nResult: {'PASSED' if proposal_passed else 'FAILED'}")
        print("=" * 60)

        # Prompt 1 (Arbiter): Unambiguous Veto prompt
        judge_response = (
            input("\nJudge (Arbiter), do you VETO this outcome? (y/n): ")
            .strip()
            .lower()
        )
        judge_vetoed = judge_response == "y"

        # Check final status and apply changes accordingly
        if proposal_passed and not judge_vetoed:
            # --- PROPOSAL PASSES ---
            logger.info("Proposal PASSED and was not vetoed.")
            print("\n⚖️  JUDGE: Outcome stands. Applying PASSED proposal.")

            # Apply rules
            self.game_manager.rules_manager.apply_proposal(proposal)
            self.game_manager.save_rules()

            # Increment proposal ID counter (only when proposal passes)
            self.game_manager.game_state.next_proposal_id += 1
            logger.debug(
                f"Proposal ID incremented to "
                f"{self.game_manager.game_state.next_proposal_id}"
            )

            # Call the new scorer
            self._get_scores_from_judge()

        else:
            # --- PROPOSAL FAILS ---
            if not proposal_passed:
                logger.info("Proposal FAILED by vote.")
                print("\n⚖️  JUDGE: Outcome stands. Proposal FAILED.")
            elif judge_vetoed:
                logger.warning(
                    f"Judge VETOED passed proposal {proposal.proposal_id}"
                )
                print("\n⚖️  JUDGE VETO: Proposal has been VETOED and FAILED.")

            # Call the new scorer
            self._get_scores_from_judge()

        # Advance turn
        # Find next player in turn order
        turn_order = self.game_manager.game_state.turn_order
        current_name = self.game_manager.game_state.current_player_name
        current_index = turn_order.index(current_name)
        next_index = (current_index + 1) % len(turn_order)
        next_player_name = turn_order[next_index]

        self.game_manager.game_state.current_player_name = next_player_name
        self.game_manager.game_state.move_number += 1

        logger.debug(
            f"Advanced to move {self.game_manager.game_state.move_number}, "
            f"next player: {next_player_name}"
        )

        # Save game state
        self.game_manager.save_game_state()
        logger.debug("Game state saved")

        # Log to transcript
        # Note: judge_approved = inverse of judge_vetoed for passed proposals
        judge_approved = proposal_passed and not judge_vetoed
        transcript_entry = self._format_transcript(
            proposal,
            votes,
            proposal_passed,
            judge_approved,
            discussions,
            self.game_manager.rules_manager.rules,
        )
        self.game_manager.logger.log_transcript(transcript_entry)
        logger.debug("Transcript logged")

    def _get_scores_from_judge(self) -> None:
        """
        Prompt the Judge to manually assign point changes for each player.

        This method displays all point-related rules and prompts the Judge
        to enter score changes for each player based on the current turn.
        Input is validated to ensure it's an integer.

        Raises:
            AssertionError: If game_state or rules_manager is None
        """
        assert self.game_manager.game_state is not None
        assert self.game_manager.rules_manager is not None

        # Find all point-related rules
        point_rules = [
            r
            for r in self.game_manager.rules_manager.rules
            if "point" in r.text.lower()
        ]

        # Print header
        print(
            f"\n--- Judge (Scorer), please assess points for Move "
            f"#{self.game_manager.game_state.move_number} ---"
        )

        # Print point-scoring rules
        print("\nRelevant Point-Scoring Rules:")
        for rule in point_rules:
            status_char = rule.status.value[0].upper()
            print(f"Rule {rule.rule_id} ({status_char}): {rule.text}")

        print()  # Blank line for readability

        # Loop through each player and get score changes
        for player in self.players:
            while True:
                try:
                    points_input = input(
                        f"Enter point change for {player.player_name}: "
                    )
                    points_change = int(points_input)
                    break  # Valid integer received
                except ValueError:
                    print("Invalid input. Please enter an integer.")
                    continue

            # Apply the score change
            self.game_manager.game_state.scores[
                player.player_name
            ] += points_change
            logger.debug(
                f"Applied {points_change} points to {player.player_name}"
            )

    def _format_transcript(
        self,
        proposal: Proposal,
        votes: list[Vote],
        proposal_passed: bool,
        judge_approved: bool,
        discussions: list[tuple[str, str]],
        rules: list[Rule],
    ) -> str:
        """
        Format a complete turn summary for the transcript.

        Args:
            proposal: The proposal
            votes: List of votes
            proposal_passed: Whether the vote passed
            judge_approved: Whether the judge approved
            discussions: List of tuples (player_name, discussion)
            rules: List of all current rules

        Returns:
            Formatted markdown string for the transcript
        """
        assert self.game_manager.game_state is not None

        lines = [
            f"## MOVE #{proposal.move_number}",
            f"**Proposal ID:** {proposal.proposal_id}",
            f"**Proposer:** {proposal.proposer_name}",
            f"**Type:** {proposal.type.value}",
        ]

        if proposal.target_rule_id:
            lines.append(f"**Target Rule ID:** {proposal.target_rule_id}")

        if proposal.new_text:
            lines.append(f"**New Text:** {proposal.new_text}")

        if proposal.rationale:
            lines.append(f"**Rationale:** {proposal.rationale}")

        # Add original text for AMEND, REPEAL, or TRANSMUTE proposals
        if proposal.type in [
            ProposalType.AMEND,
            ProposalType.REPEAL,
            ProposalType.TRANSMUTE,
        ]:
            if proposal.target_rule_id:
                # Find the original rule
                for rule in rules:
                    if rule.rule_id == proposal.target_rule_id:
                        lines.append(
                            f"**Original Text (Rule {rule.rule_id}):** "
                            f"{rule.text}"
                        )
                        break

        # Add discussions section
        if discussions:
            lines.append("\n### Discussions")
            for player_name, discussion in discussions:
                lines.append(f"- **{player_name}:** {discussion}")

        lines.append("\n### Votes")
        for vote in votes:
            vote_line = f"- **{vote.player_name}:** {vote.vote}"
            if vote.reason:
                vote_line += f" - {vote.reason}"
            lines.append(vote_line)

        lines.append(
            f"\n**Vote Result:** {'PASSED' if proposal_passed else 'FAILED'}"
        )
        lines.append(
            f"**Judge Approval:** {'YES' if judge_approved else 'NO'}"
        )

        lines.append("\n### Scores")
        for player_name, score in self.game_manager.game_state.scores.items():
            lines.append(f"- **{player_name}:** {score}")

        return "\n".join(lines)
