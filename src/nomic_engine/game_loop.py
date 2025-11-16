"""
GameLoop: The "Conductor" class that orchestrates the 5-step turn logic.

This class is responsible for executing turns, validating all player actions,
calculating state changes, and interfacing with the Human Judge.
"""

import logging

from .data_models import Proposal, Vote
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
        2. Collect discussion from other players
        3. Allow revision (V1 stub - not implemented)
        4. Collect votes from other players
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

            # Get current player and other players
            current_player = self._get_current_player()
            other_players = self._get_other_players()

            # Step 1: Propose (with validation)
            proposal = self._run_step_1_propose(current_player)
            if proposal is None:
                logger.warning("Turn ended due to illegal proposal")
                return

            # Step 2: Discuss
            discussions = self._run_step_2_discuss(proposal, other_players)

            # Step 3: Revise (V1 stub)
            proposal = self._run_step_3_revise(proposal, discussions)

            # Step 4: Vote
            votes = self._run_step_4_vote(proposal, other_players)

            # Step 5: Resolve
            self._run_step_5_resolve(proposal, votes)

            # Increment the proposal ID counter after the turn
            self.game_manager.game_state.next_proposal_id += 1
            logger.debug(
                f"Next proposal ID incremented to "
                f"{self.game_manager.game_state.next_proposal_id}"
            )

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

        # Validate the proposal with a side-effect-free dry run
        try:
            # Create deep copies of all rules (Pydantic model_copy)
            rules_copy = [
                rule.model_copy(deep=True)
                for rule in self.game_manager.rules_manager.rules
            ]

            # Create a temporary RulesManager for validation
            temp_rules_manager = RulesManager(rules=rules_copy)

            # Temporarily assign a proposal_id for validation purposes
            # Use the next available ID
            current_id_str = str(self.game_manager.game_state.next_proposal_id)
            proposal.proposal_id = current_id_str

            # Try to apply the proposal on the TEMP manager
            # The real rules_manager is never touched
            temp_rules_manager.apply_proposal(proposal)

            # If we get here, the proposal is valid
            # We discard temp_rules_manager and return success
            logger.info(
                f"Proposal validation passed, assigned ID {current_id_str}"
            )
            return proposal

        except ValueError as e:
            logger.warning(
                f"Illegal proposal from {current_player.player_name}: {e}"
            )
            print(f"\n❌ ILLEGAL PROPOSAL: {e}")
            print(f"Proposer: {current_player.player_name}")
            print("The proposal cannot proceed.\n")
            # Clear the proposal_id since validation failed
            proposal.proposal_id = None
            return None

    def _run_step_2_discuss(
        self, proposal: Proposal, other_players: list[BasePlayer]
    ) -> list[str]:
        """
        Step 2: Collect discussion from other players.

        Args:
            proposal: The proposal to discuss
            other_players: List of players excluding the proposer

        Returns:
            List of discussion strings (excludes None responses)
        """
        assert self.game_manager.game_state is not None
        assert self.game_manager.rules_manager is not None

        logger.info("Step 2: Discussion phase")

        discussions: list[str] = []

        for player in other_players:
            discussion = player.discuss(
                proposal=proposal,
                game_state=self.game_manager.game_state,
                rules=self.game_manager.rules_manager.rules,
            )

            if discussion is not None:
                discussions.append(discussion)
                logger.debug(f"{player.player_name} provided discussion")
            else:
                logger.debug(f"{player.player_name} abstained from discussion")

        logger.info(f"Collected {len(discussions)} discussion responses")
        return discussions

    def _run_step_3_revise(
        self, proposal: Proposal, discussions: list[str]
    ) -> Proposal:
        """
        Step 3: Allow proposer to revise based on discussion (V1 stub).

        In V1, this is not implemented - we simply return the original
        proposal.

        Args:
            proposal: The original proposal
            discussions: List of discussion strings from other players

        Returns:
            The proposal (unchanged in V1)
        """
        logger.info("Step 3: Revision phase (V1 stub - skipping)")
        logger.debug(
            f"Received {len(discussions)} discussions but revision not "
            f"implemented"
        )
        return proposal

    def _run_step_4_vote(
        self, proposal: Proposal, other_players: list[BasePlayer]
    ) -> list[Vote]:
        """
        Step 4: Collect votes from other players.

        Args:
            proposal: The proposal to vote on
            other_players: List of players excluding the proposer

        Returns:
            List of Vote objects from all other players
        """
        assert self.game_manager.game_state is not None
        assert self.game_manager.rules_manager is not None

        logger.info("Step 4: Voting phase")

        votes: list[Vote] = []

        for player in other_players:
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
        self, proposal: Proposal, votes: list[Vote]
    ) -> None:
        """
        Step 5: Resolve the turn - tally votes, consult judge, apply
        changes.

        This method:
        - Tallies votes to determine pass/fail
        - Consults the human judge for final approval
        - Calculates and applies score changes
        - Applies proposal to rules if passed and legal
        - Advances to next turn
        - Saves state and logs transcript

        Args:
            proposal: The proposal that was voted on
            votes: List of Vote objects from all players

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

        # Rule 203: Unanimous pass requirement (for now)
        # Note: Proposal must receive unanimous YES votes to pass
        proposal_passed = yes_votes == total_voters and total_voters > 0

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

        # Rule 213: Human Judge Hook
        judge_response = (
            input("\nJudge, is this proposal legal? (y/n): ").strip().lower()
        )
        judge_approved = judge_response == "y"

        if not judge_approved:
            logger.warning("Judge vetoed the proposal")
            print("\n⚖️  JUDGE VETO: Proposal rejected by the Judge.\n")
            # End turn without applying changes (except score penalties)
            # TODO: Apply any judge-related score penalties if rules
            # require
            return

        logger.info("Judge approved the proposal")

        # Calculate score changes based on Rules 202, 204, 206
        # Rule 202: Proposer gets 12 * (fraction of favorable votes),
        # rounded
        # Note: favorable votes means YES votes
        if total_voters > 0:
            favorable_fraction = yes_votes / total_voters
        else:
            favorable_fraction = 0

        proposer_points = round(12 * favorable_fraction)

        logger.debug(
            f"Score calculation: proposer gets {proposer_points} points "
            f"(12 * {favorable_fraction})"
        )

        # Apply proposer points (Rule 202)
        self.game_manager.game_state.scores[
            proposal.proposer_name
        ] += proposer_points

        # Rule 206: If proposal defeated, proposer loses 10 points
        if not proposal_passed:
            self.game_manager.game_state.scores[proposal.proposer_name] -= 10
            logger.debug(
                f"{proposal.proposer_name} loses 10 points (defeated "
                f"proposal)"
            )

        # Rule 204: Players who vote against winning proposals get 10
        # points
        # Note: This only applies when unanimity is not required (future
        # state)
        # For now, with unanimous voting, no one votes against a winning
        # proposal
        # We'll implement this for future-proofing
        if proposal_passed:
            for vote in votes:
                if vote.vote == "NO":
                    self.game_manager.game_state.scores[vote.player_name] += 10
                    logger.debug(
                        f"{vote.player_name} gets 10 points (voted "
                        f"against winner)"
                    )

        # Apply the proposal to rules if it passed and was legal
        if proposal_passed and judge_approved:
            logger.info("Applying proposal to rules")
            self.game_manager.rules_manager.apply_proposal(proposal)
            self.game_manager.save_rules()
            logger.debug("Rules saved")

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
        transcript_entry = self._format_transcript(
            proposal, votes, proposal_passed, judge_approved
        )
        self.game_manager.logger.log_transcript(transcript_entry)
        logger.debug("Transcript logged")

    def _format_transcript(
        self,
        proposal: Proposal,
        votes: list[Vote],
        proposal_passed: bool,
        judge_approved: bool,
    ) -> str:
        """
        Format a complete turn summary for the transcript.

        Args:
            proposal: The proposal
            votes: List of votes
            proposal_passed: Whether the vote passed
            judge_approved: Whether the judge approved

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
