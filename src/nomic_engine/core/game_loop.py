"""
GameLoop: The "Conductor" class that orchestrates the 5-step turn logic.

This class is responsible for executing turns, validating all player actions,
calculating state changes, and interfacing with the Human Judge.
"""

import logging

from ..data_models import Discussion, Proposal, ProposalType, Rule, Vote
from ..judge import BaseJudge
from ..judge.base_judge import JudgeScoreResponse, JudgeVetoResponse
from ..judge.human_judge import HumanJudge
from ..players.base_player import BasePlayer
from ..validation.validator import validate_proposal
from .game_manager import GameManager

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
        self,
        game_manager: GameManager,
        players: list[BasePlayer],
        judge: BaseJudge | None = None,
    ) -> None:
        """
        Initialize the GameLoop.

        Args:
            game_manager: The GameManager instance for this game
            players: List of all instantiated player objects
            judge: Optional judge configuration object

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
        self.judge = judge if judge is not None else HumanJudge()

    def run_turn(self) -> bool:
        """
        Execute a complete game turn through all 5 steps.

        This method orchestrates the entire turn process:
        1. Get proposal from current player (with validation)
        2. Collect discussion from all players (per Rule 111)
        3. Allow revision (V1 stub - not implemented)
        4. Collect votes from all players (per Rule 105)
        5. Resolve the turn (tally, judge, apply changes, advance)

        Returns:
            bool: True if the game ended by reaching the target score,
            False otherwise.

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
            proposal = self._get_and_validate_proposal(current_player)
            if proposal is None:
                logger.warning("Turn ended due to illegal proposal")
                return False

            # Step 2: Discuss
            discussions: list[Discussion] = self._collect_discussions(
                proposal, self.players
            )

            # Step 3: Revise
            revised_proposal = self._handle_revision(
                current_player, proposal, discussions
            )

            # Check if proposal was withdrawn
            if revised_proposal is None:
                logger.warning(
                    f"Proposal {proposal.proposal_id} withdrawn by "
                    f"{current_player.player_name}"
                )
                # TODO: Log this withdrawal to the transcript
                return False  # End the turn

            # If not withdrawn, use the revised proposal for voting
            proposal = revised_proposal

            # Step 4: Vote
            votes = self._collect_votes(proposal, self.players)

            # Step 5: Resolve
            game_over = self._resolve_turn(proposal, votes, discussions)

            logger.info(
                f"Completed turn {self.game_manager.game_state.move_number}"
            )

            return game_over

        except Exception as e:
            logger.error(f"Error during turn execution: {e}", exc_info=True)
            raise

        return False

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

    def _log_illegal_proposal(
        self,
        proposal: Proposal,
        player_name: str,
        error_message: str,
        is_revised: bool = False,
    ) -> None:
        """
        Log an illegal proposal to the transcript.

        Args:
            proposal: The illegal proposal
            player_name: Name of the player who proposed it
            error_message: Reason why the proposal is illegal
            is_revised: Whether this is a revised proposal (default False)
        """
        assert self.game_manager.game_state is not None

        # Print to console
        label = (
            "ILLEGAL REVISED PROPOSAL" if is_revised else "ILLEGAL PROPOSAL"
        )
        print(f"\n❌ {label}: {error_message}")
        print(f"Proposer: {player_name}")
        print("The proposal cannot proceed.\n")

        # Build transcript lines
        transcript_lines = [
            f"## MOVE #{self.game_manager.game_state.move_number}",
            f"**Proposer:** {player_name}",
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
                f"**Result:** {label}",
                f"**Reason:** {error_message}",
            ]
        )

        transcript_entry = "\n".join(transcript_lines)
        self.game_manager.logger.log_transcript(transcript_entry)

    def _get_and_validate_proposal(
        self, current_player: BasePlayer
    ) -> Proposal | None:
        """
        Get proposal from current player and validate it.

        This method gets the proposal from the player and validates it
        for legality.

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
        is_valid, error_message = validate_proposal(
            proposal, current_player.player_name, self.game_manager
        )

        if is_valid:
            logger.info(
                f"Proposal validation passed, assigned ID {current_id_str}"
            )
            return proposal
        else:
            # Log illegal proposal
            self._log_illegal_proposal(
                proposal, current_player.player_name, error_message
            )

            # Clear the proposal_id since validation failed
            proposal.proposal_id = None
            return None

    def _collect_discussions(
        self, proposal: Proposal, players: list[BasePlayer]
    ) -> list[Discussion]:
        """
        Collect discussion from all players.

        Per Rule 111, all players may discuss. However, the proposer's
        rationale from the proposal serves as their discussion contribution,
        so they are not prompted again.

        Args:
            proposal: The proposal to discuss
            players: List of all players

        Returns:
            List of Discussion objects from all players (includes abstentions)
        """
        assert self.game_manager.game_state is not None
        assert self.game_manager.rules_manager is not None

        logger.info("Step 2: Discussion phase")

        discussions: list[Discussion] = []

        # Create Discussion object for the proposer using their rationale
        proposer_discussion = Discussion(
            player_name=proposal.proposer_name,
            text=proposal.rationale or "",
            private_thoughts=proposal.private_thoughts,
        )
        discussions.append(proposer_discussion)

        if proposer_discussion.text:
            logger.debug(
                f"{proposal.proposer_name} (proposer) - "
                "using rationale as discussion"
            )
        else:
            logger.debug(
                f"{proposal.proposer_name} (proposer) - no rationale provided"
            )

        # Collect discussion from all other players (excluding proposer)
        for player in players:
            if player.player_name == proposal.proposer_name:
                continue  # Skip the proposer

            discussion = player.discuss(
                proposal=proposal,
                game_state=self.game_manager.game_state,
                rules=self.game_manager.rules_manager.rules,
            )

            discussions.append(discussion)
            if discussion.text:
                logger.debug(f"{player.player_name} provided discussion")
            else:
                logger.debug(f"{player.player_name} abstained from discussion")

        logger.info(f"Collected {len(discussions)} discussion responses")
        return discussions

    def _handle_revision(
        self,
        current_player: BasePlayer,
        proposal: Proposal,
        discussions: list[Discussion],
    ) -> Proposal | None:
        """
        Allow proposer to revise based on discussion.

        Per Rules 111 and 112, the proposer may revise their proposal after
        reviewing discussions. If any discussion contains "UNCLEAR" or
        "AMBIGUOUS", the proposer must revise or withdraw (Rule 112).

        CRITICAL: If the player returns a NEW proposal object (not the
        original), it MUST be re-validated for legality.

        Args:
            current_player: The player who made the proposal
            proposal: The original proposal
            discussions: List of Discussion objects from all players

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
            is_valid, error_message = validate_proposal(
                revised_proposal, current_player.player_name, self.game_manager
            )

            if is_valid:
                logger.info("Revised proposal passed validation")
                return revised_proposal
            else:
                # Log illegal revised proposal
                logger.warning(
                    f"Revised proposal from {current_player.player_name} "
                    f"is ILLEGAL: {error_message}"
                )
                self._log_illegal_proposal(
                    revised_proposal,
                    current_player.player_name,
                    error_message,
                    is_revised=True,
                )
                return None

    def _collect_votes(
        self, proposal: Proposal, players: list[BasePlayer]
    ) -> list[Vote]:
        """
        Collect votes from all players.

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

    def _tally_votes(self, votes: list[Vote]) -> bool:
        """
        Tally votes to determine if proposal passed.

        Per Rule 203, proposals require unanimous YES votes to pass.
        Special case: zero voters (empty votes list) results in automatic pass.

        Args:
            votes: List of Vote objects from all players

        Returns:
            True if proposal passed, False otherwise
        """
        yes_votes = sum(1 for v in votes if v.vote == "YES")
        no_votes = sum(1 for v in votes if v.vote == "NO")
        abstain_votes = sum(1 for v in votes if v.vote == "ABSTAIN")
        total_voters = len(votes)

        # Rule 203: Unanimous pass requirement
        # Special case: If there are zero voters, proposal automatically passes
        if total_voters == 0:
            proposal_passed = True
        else:
            # Proposal must receive unanimous YES votes to pass
            proposal_passed = yes_votes == total_voters

        logger.info(
            f"Vote tally: YES={yes_votes}, NO={no_votes}, "
            f"ABSTAIN={abstain_votes}, Passed={proposal_passed}"
        )

        return proposal_passed

    def _apply_passed_proposal(self, proposal: Proposal) -> None:
        """
        Apply a passed proposal to the rules.

        This method:
        - Applies the proposal to the rules manager
        - Saves the updated rules
        - Increments the next_proposal_id counter

        Args:
            proposal: The proposal to apply
        """
        assert self.game_manager.game_state is not None
        assert self.game_manager.rules_manager is not None

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

    def _advance_turn_state(self) -> None:
        """
        Advance to the next turn.

        This method:
        - Finds the next player in turn order
        - Updates current_player_name
        - Increments move_number
        """
        assert self.game_manager.game_state is not None

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

    def _log_and_save_turn(
        self,
        proposal: Proposal,
        votes: list[Vote],
        discussions: list[Discussion],
        proposal_passed: bool,
        judge_approved: bool,
        judge_veto_response: JudgeVetoResponse,
        judge_score_response: JudgeScoreResponse,
    ) -> None:
        """
        Log the turn transcript and save game state.

        Args:
            proposal: The proposal that was voted on
            votes: List of Vote objects from all players
            discussions: List of Discussion objects from all players
            proposal_passed: Whether the vote passed
            judge_approved: Whether the judge approved (not vetoed)
            judge_veto_response: Data describing the judge's veto decision
            judge_score_response: Data describing the judge's score assessment
        """
        assert self.game_manager.game_state is not None
        assert self.game_manager.rules_manager is not None

        # Format and log transcript
        transcript_entry = self._format_transcript(
            proposal,
            votes,
            proposal_passed,
            judge_approved,
            judge_veto_response,
            judge_score_response,
            discussions,
            self.game_manager.rules_manager.rules,
        )
        self.game_manager.logger.log_transcript(transcript_entry)
        logger.debug("Transcript logged")

        # Save game state
        self.game_manager.save_game_state()
        logger.debug("Game state saved")

    def _detect_victory(self) -> tuple[bool, list[str], int]:
        """Determine whether any player has met the target score."""

        assert self.game_manager.game_state is not None

        target_score = self.game_manager.game_state.target_score
        if target_score is None:
            return False, [], 0

        scores = self.game_manager.game_state.scores
        winners = [
            name for name, score in scores.items() if score >= target_score
        ]

        if not winners:
            return False, [], 0

        top_score = max(scores[name] for name in winners)
        top_winners = [name for name in winners if scores[name] == top_score]

        return True, top_winners, top_score

    def _log_game_over(self, winners: list[str], winning_score: int) -> None:
        """Log a GAME OVER event to the history and transcript."""

        assert self.game_manager.game_state is not None

        target_score = self.game_manager.game_state.target_score
        scores = self.game_manager.game_state.scores
        winners_text = ", ".join(winners)

        self.game_manager.logger.log_event(
            "game_over",
            {
                "target_score": target_score,
                "winners": winners,
                "winning_score": winning_score,
                "final_scores": scores,
            },
        )

        label = "Winners" if len(winners) > 1 else "Winner"
        winner_line = f"{label}: {winners_text} (score: {winning_score})"

        lines = [
            "# GAME OVER",
            f"Target score: {target_score}",
            winner_line,
            "",
            "## Final Scores",
        ]

        for player_name, score in scores.items():
            lines.append(f"- **{player_name}:** {score}")

        self.game_manager.logger.log_transcript("\n".join(lines))

        print(
            "\n🏁 GAME OVER! "
            f"{winners_text} reached the target score of {target_score}."
        )

    def _resolve_turn(
        self,
        proposal: Proposal,
        votes: list[Vote],
        discussions: list[Discussion],
    ) -> bool:
        """
        Resolve the turn by tallying votes, consulting judge, applying changes.

        This method orchestrates the resolution phase by:
        - Tallying votes to determine pass/fail
        - Consulting the human judge for veto decision
        - Prompting judge to manually assign scores
        - Applying proposal to rules if passed and not vetoed
        - Advancing to next turn
        - Saving state and logging transcript

        Args:
            proposal: The proposal that was voted on
            votes: List of Vote objects from all players
            discussions: List of Discussion objects from discussion phase
        Returns:
            bool: True if the game ended by reaching the target score.
        """
        assert self.game_manager.game_state is not None
        assert self.game_manager.rules_manager is not None

        logger.info("Step 5: Resolution phase")

        # Tally votes
        proposal_passed = self._tally_votes(votes)

        # Print proposal and voting results to console
        yes_votes = sum(1 for v in votes if v.vote == "YES")
        no_votes = sum(1 for v in votes if v.vote == "NO")
        abstain_votes = sum(1 for v in votes if v.vote == "ABSTAIN")

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

        # Only consult judge for veto if proposal passed
        if proposal_passed:
            judge_veto_response = self.judge.get_veto(
                self.game_manager, proposal, votes, discussions
            )
            judge_vetoed = judge_veto_response["veto"]
        else:
            judge_vetoed = False
            judge_veto_response = {
                "veto": False,
                "reason": None,
                "private_thoughts": None,
            }

        # Communicate outcome before scoring
        if proposal_passed and not judge_vetoed:
            logger.info("Proposal PASSED and was not vetoed.")
        else:
            # Proposal failed or was vetoed
            if not proposal_passed:
                logger.info("Proposal FAILED by vote.")
                print("\n⚖️  JUDGE: Outcome stands. Proposal FAILED.")
            elif judge_vetoed:
                logger.warning(
                    f"Judge VETOED passed proposal {proposal.proposal_id}"
                )
                print("\n⚖️  JUDGE VETO: Proposal has been VETOED and FAILED.")

        # Score assessment must happen before applying any rule changes
        # so that the judge evaluates the turn against the pre-modification
        # ruleset (Rule 205 compliance).
        judge_score_response = self.judge.assess_scores(
            self.game_manager, self.players, proposal, votes, discussions
        )

        # Apply proposal if passed and not vetoed
        if proposal_passed and not judge_vetoed:
            self._apply_passed_proposal(proposal)

        victory_reached, winners, winning_score = self._detect_victory()

        # Advance turn state only if the game is not over
        if not victory_reached:
            self._advance_turn_state()

        # Log transcript and save state
        judge_approved = proposal_passed and not judge_vetoed
        self._log_and_save_turn(
            proposal,
            votes,
            discussions,
            proposal_passed,
            judge_approved,
            judge_veto_response,
            judge_score_response,
        )

        if victory_reached:
            self._log_game_over(winners, winning_score)

        return victory_reached

    def _format_transcript(
        self,
        proposal: Proposal,
        votes: list[Vote],
        proposal_passed: bool,
        judge_approved: bool,
        judge_veto_response: JudgeVetoResponse,
        judge_score_response: JudgeScoreResponse,
        discussions: list[Discussion],
        rules: list[Rule],
    ) -> str:
        """
        Format a complete turn summary for the transcript.

        Args:
            proposal: The proposal
            votes: List of votes
            proposal_passed: Whether the vote passed
            judge_approved: Whether the judge approved
            judge_veto_response: Details from the judge's veto decision
            judge_score_response: Details from the judge's score assessment
            discussions: List of Discussion objects from all players
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

        if proposal.private_thoughts:
            lines.append(f"**Private Thoughts:** {proposal.private_thoughts}")

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

        # Add discussions section (always include, even if all abstained)
        lines.append("\n### Discussions")
        for discussion in discussions:
            name = discussion.player_name
            if discussion.text:
                lines.append(f"- **{name}:** {discussion.text}")
            else:
                lines.append(f"- **{name}:** *(Abstained)*")
            if discussion.private_thoughts:
                lines.append(
                    f"  - Private Thoughts: {discussion.private_thoughts}"
                )

        lines.append("\n### Votes")
        for vote in votes:
            lines.append(f"- **{vote.player_name}:** {vote.vote}")
            if vote.reason:
                lines.append(f"  - Public Reason: {vote.reason}")
            if vote.private_thoughts:
                lines.append(f"  - Private Thoughts: {vote.private_thoughts}")

        lines.append(
            f"\n**Vote Result:** {'PASSED' if proposal_passed else 'FAILED'}"
        )
        lines.append(
            f"**Judge Approval:** {'YES' if judge_approved else 'NO'}"
        )

        lines.append("\n### Judge Veto Response")
        is_veto = judge_veto_response["veto"]
        judge_veto_decision = "VETO" if is_veto else "ALLOW"
        lines.append(f"- **Decision:** {judge_veto_decision}")
        if judge_veto_response.get("reason"):
            lines.append(f"- **Reason:** {judge_veto_response['reason']}")
        if judge_veto_response.get("private_thoughts"):
            private_thoughts = judge_veto_response["private_thoughts"]
            lines.append(f"  - Private Thoughts: {private_thoughts}")

        lines.append("\n### Judge Score Response")
        if judge_score_response.get("private_thoughts"):
            judge_private = judge_score_response["private_thoughts"]
            lines.append(f"- Private Thoughts: {judge_private}")
        adjustments = judge_score_response.get("score_adjustments", [])
        if adjustments:
            for adj in adjustments:
                adj_text = f"- **{adj['player']}:** {adj['delta']:+d}"
                lines.append(f"{adj_text} ({adj['reason']})")
        else:
            lines.append("- No score adjustments this turn.")

        lines.append("\n### Scores")
        for player_name, score in self.game_manager.game_state.scores.items():
            lines.append(f"- **{player_name}:** {score}")

        return "\n".join(lines)
