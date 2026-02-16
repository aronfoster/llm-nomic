"""
GameLoop: The "Conductor" class that orchestrates the 5-step turn logic.

This class is responsible for executing turns, validating all player actions,
calculating state changes, and interfacing with the Human Judge.
"""

import logging

from ..data_models import (
    Discussion,
    JudgeDecisions,
    Proposal,
    ProposalType,
    Rule,
    Vote,
    VoteResult,
    WithdrawalPolicy,
)
from ..judge import BaseJudge
from ..judge.human_judge import HumanJudge
from ..judge_contracts import JudgeScoreResponse, JudgeVetoResponse
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

            max_withdrawal_retries = 2
            withdrawal_policy = WithdrawalPolicy.FORFEIT
            if self.game_manager.game_config is not None:
                max_withdrawal_retries = (
                    self.game_manager.game_config.max_withdrawal_retries
                )
                withdrawal_policy = (
                    self.game_manager.game_config.withdrawal_policy
                )

            proposal: Proposal | None = None
            discussions: list[Discussion] = []
            turn_ready_for_vote = False

            # Loop covers initial attempt plus configured withdrawal pivots.
            for withdrawal_attempt in range(max_withdrawal_retries + 1):
                # Step 1: Propose (with validation)
                proposal = self._get_and_validate_proposal(
                    current_player,
                    continue_turn=withdrawal_attempt > 0,
                )
                if proposal is None:
                    logger.warning("Turn ended due to illegal proposal")
                    break

                # Step 2: Discuss
                discussions = self._collect_discussions(proposal, self.players)

                # Step 3: Revise
                revised_proposal = self._handle_revision(
                    current_player, proposal, discussions
                )

                if revised_proposal is not None:
                    proposal = revised_proposal
                    turn_ready_for_vote = True
                    break

                logger.warning(
                    "Proposal %s withdrawn by %s",
                    proposal.proposal_id,
                    current_player.player_name,
                )

                retries_exhausted = (
                    withdrawal_attempt >= max_withdrawal_retries
                )
                if (
                    withdrawal_policy != WithdrawalPolicy.RETRY
                    or retries_exhausted
                ):
                    self._advance_turn_state()
                    self.game_manager.save_game_state()
                    break

                current_player.note_withdrawal_for_retry(
                    discussions=discussions,
                    withdrawal_attempt=withdrawal_attempt + 1,
                    max_withdrawal_retries=max_withdrawal_retries,
                )
                logger.info(
                    "Retrying proposal after withdrawal: attempt %d/%d",
                    withdrawal_attempt + 1,
                    max_withdrawal_retries,
                )

            if not turn_ready_for_vote:
                return False

            assert proposal is not None

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
        self, current_player: BasePlayer, continue_turn: bool = False
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
            continue_turn=continue_turn,
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

    def _tally_vote_results(self, votes: list[Vote]) -> VoteResult:
        """
        Calculate the outcome of the vote (side-effect-free).

        This is a pure function that analyzes votes and returns a structured
        VoteResult object containing counts and the pass/fail determination.

        The voting mode is determined by the 'vote_mode' flag in GameState:
        - 'unanimous': Proposal passes only if all votes are "YES"
        - 'majority': Proposal passes if YES votes > 50% of total votes cast

        Abstentions are counted in the total for majority calculations.
        Special case: zero voters (empty votes list) results in automatic pass.

        Args:
            votes: List of Vote objects from all players

        Returns:
            VoteResult: Structured data containing vote counts and
                pass/fail status
        """
        assert self.game_manager.game_state is not None

        logger.debug(f"Entering _tally_vote_results with {len(votes)} votes")

        # Count votes by type
        yes_count = sum(1 for v in votes if v.vote == "YES")
        no_count = sum(1 for v in votes if v.vote == "NO")
        abstain_count = sum(1 for v in votes if v.vote == "ABSTAIN")
        total_voters = len(votes)

        # Get vote_mode from flags with type safety
        flags = self.game_manager.game_state.flags
        vote_mode = flags.get("vote_mode", "unanimous")

        # Validate vote_mode is a string
        if not isinstance(vote_mode, str):
            logger.warning(
                f"Invalid vote_mode type in flags: {type(vote_mode)}. "
                "Defaulting to 'unanimous'"
            )
            vote_mode = "unanimous"

        # Special case: If there are zero voters, proposal automatically passes
        if total_voters == 0:
            passed = True
            logger.debug(
                "Vote tally: Zero voters, proposal automatically passes"
            )
        elif vote_mode == "majority":
            # Majority mode: YES votes must be > 50% of total votes
            passed = yes_count > (total_voters / 2)
            logger.debug(
                f"Vote tally (majority mode): YES={yes_count}, "
                f"NO={no_count}, ABSTAIN={abstain_count}, "
                f"Total={total_voters}, Passed={passed}"
            )
        else:
            # Unanimous mode (default): All votes must be YES
            if vote_mode != "unanimous":
                logger.warning(
                    f"Unknown vote_mode '{vote_mode}' in flags. "
                    "Defaulting to 'unanimous'"
                )
                vote_mode = "unanimous"
            passed = yes_count == total_voters
            logger.debug(
                f"Vote tally (unanimous mode): YES={yes_count}, "
                f"NO={no_count}, ABSTAIN={abstain_count}, "
                f"Passed={passed}"
            )

        result = VoteResult(
            yes_count=yes_count,
            no_count=no_count,
            abstain_count=abstain_count,
            total_voters=total_voters,
            passed=passed,
            vote_mode=vote_mode,
        )

        logger.debug(f"Exiting _tally_vote_results: passed={result.passed}")
        return result

    def _get_judge_decisions(
        self,
        proposal: Proposal,
        votes: list[Vote],
        discussions: list[Discussion],
        vote_result: VoteResult,
    ) -> JudgeDecisions:
        """
        Consolidate interpretive data from the Judge.

        This method encapsulates all Judge interactions for the current turn:
        - Veto decision (only if proposal passed)
        - Score assessments (always)

        Args:
            proposal: The proposal being judged
            votes: List of votes cast
            discussions: List of discussions
            vote_result: The vote tallying result

        Returns:
            JudgeDecisions: Consolidated judge responses and approval status
        """
        logger.debug(
            f"Entering _get_judge_decisions "
            f"(proposal_passed={vote_result.passed})"
        )

        # Only consult judge for veto if proposal passed
        if vote_result.passed:
            logger.debug("Consulting judge for veto decision")
            veto_response = self.judge.get_veto(
                self.game_manager, proposal, votes, discussions
            )
            judge_vetoed = veto_response["veto"]
            logger.debug(f"Judge veto decision: vetoed={judge_vetoed}")
        else:
            # Proposal failed vote, no veto needed
            logger.debug("Proposal failed vote, skipping veto consultation")
            veto_response = {
                "veto": False,
                "reason": None,
                "private_thoughts": None,
            }
            judge_vetoed = False

        # Score assessment always happens
        logger.debug("Consulting judge for score assessment")
        score_response = self.judge.assess_scores(
            self.game_manager, self.players, proposal, votes, discussions
        )
        logger.debug(
            f"Judge score assessment complete: "
            f"{len(score_response.get('score_adjustments', []))} adjustments"
        )

        # Calculate approval status
        judge_approved = vote_result.passed and not judge_vetoed

        decisions = JudgeDecisions(
            veto_response=veto_response,
            score_response=score_response,
            judge_approved=judge_approved,
        )

        logger.debug(
            f"Exiting _get_judge_decisions: "
            f"judge_approved={decisions.judge_approved}"
        )
        return decisions

    def _apply_turn_mutations(
        self,
        proposal: Proposal,
        votes: list[Vote],
        discussions: list[Discussion],
        vote_result: VoteResult,
        judge_decisions: JudgeDecisions,
    ) -> bool:
        """
        Authoritative state and file persistence.

        This is the ONLY method with side effects.

        This method:
        - Applies passed proposals to rules
        - Increments proposal counters
        - Detects victory conditions
        - Advances turn state
        - Saves game state and rules
        - Logs transcript

        Args:
            proposal: The proposal being resolved
            votes: List of votes cast
            discussions: List of discussions
            vote_result: Vote tallying result
            judge_decisions: Consolidated judge decisions

        Returns:
            bool: True if game ended by victory, False otherwise
        """
        assert self.game_manager.game_state is not None
        assert self.game_manager.rules_manager is not None

        logger.debug("Entering _apply_turn_mutations")

        # Apply judge-provided score deltas (state mutation centralized here)
        adjustments = judge_decisions.score_response.get(
            "score_adjustments", []
        )
        for adjustment in adjustments:
            player_name = adjustment["player"]
            delta = adjustment["delta"]
            reason = adjustment["reason"]
            self.game_manager.game_state.scores[player_name] += delta
            logger.info(
                "Applied score adjustment: %s %+d points (%s)",
                player_name,
                delta,
                reason,
            )

        # Apply proposal if passed and approved
        if judge_decisions.judge_approved:
            # Maintain state before applying proposal (skip for TRANSMUTE)
            from ..data_models import ProposalType

            if proposal.type != ProposalType.TRANSMUTE:
                logger.debug(
                    "Calling maintain_state for proposal %s",
                    proposal.proposal_id,
                )

                # Determine original and new rule text based on proposal type
                original_rule_text = None
                new_rule_text = None

                if proposal.type == ProposalType.ADD:
                    # ADD: no original text, new text from proposal
                    new_rule_text = proposal.new_text
                elif proposal.type == ProposalType.AMEND:
                    # AMEND: both texts present
                    if proposal.target_rule_id:
                        target_rule = (
                            self.game_manager.rules_manager._find_rule_by_id(
                                proposal.target_rule_id
                            )
                        )
                        if target_rule:
                            original_rule_text = target_rule.text
                    new_rule_text = proposal.new_text
                elif proposal.type == ProposalType.REPEAL:
                    # REPEAL: original text only
                    if proposal.target_rule_id:
                        target_rule = (
                            self.game_manager.rules_manager._find_rule_by_id(
                                proposal.target_rule_id
                            )
                        )
                        if target_rule:
                            original_rule_text = target_rule.text

                # Call judge's maintain_state method
                state_updates = self.judge.maintain_state(
                    game_manager=self.game_manager,
                    proposal=proposal,
                    original_rule_text=original_rule_text,
                    new_rule_text=new_rule_text,
                )

                # Apply state updates if any (only if values changed)
                if state_updates:
                    if "flags" in state_updates:
                        for flag_name, flag_value in state_updates[
                            "flags"
                        ].items():
                            current_value = (
                                self.game_manager.game_state.flags.get(
                                    flag_name
                                )
                            )
                            if current_value != flag_value:
                                self.game_manager.game_state.flags[
                                    flag_name
                                ] = flag_value
                                logger.info(
                                    "Updated flag %s from %s to %s",
                                    flag_name,
                                    current_value,
                                    flag_value,
                                )
                    if "target_score" in state_updates:
                        new_score = state_updates["target_score"]
                        current_score = (
                            self.game_manager.game_state.target_score
                        )
                        if current_score != new_score:
                            self.game_manager.game_state.target_score = (
                                new_score
                            )
                            logger.info(
                                "Updated target_score from %s to %s",
                                current_score,
                                new_score,
                            )
            else:
                logger.debug(
                    "Skipping maintain_state for TRANSMUTE proposal %s",
                    proposal.proposal_id,
                )

            logger.debug(
                f"Applying passed proposal {proposal.proposal_id} to rules"
            )
            self.game_manager.rules_manager.apply_proposal(proposal)
            self.game_manager.save_rules()
            logger.debug("Proposal applied and rules saved")

        else:
            logger.debug(
                "Proposal not applied (failed vote or vetoed), "
                "skipping rule modifications"
            )

        # Increment proposal ID for all valid proposals (Rule 108)
        self.game_manager.game_state.next_proposal_id += 1
        logger.debug(
            "Proposal ID incremented to %s",
            self.game_manager.game_state.next_proposal_id,
        )

        # Detect victory
        victory_reached, winners, winning_score = self._detect_victory()
        logger.debug(f"Victory detection: victory_reached={victory_reached}")

        # Advance turn state only if the game is not over
        if not victory_reached:
            logger.debug("No victory, advancing turn state")
            self._advance_turn_state()
        else:
            logger.debug(
                f"Victory detected for {winners} with score {winning_score}, "
                "not advancing turn"
            )

        # Log transcript and save state
        logger.debug("Logging transcript and saving game state")
        self._log_and_save_turn(
            proposal,
            votes,
            discussions,
            vote_result.passed,
            judge_decisions.judge_approved,
            judge_decisions.veto_response,
            judge_decisions.score_response,
        )

        # Log game over if victory reached
        if victory_reached:
            logger.debug("Logging game over event")
            self._log_game_over(winners, winning_score)

        logger.debug(
            f"Exiting _apply_turn_mutations: game_over={victory_reached}"
        )
        return victory_reached

    def _print_proposal_summary(
        self, proposal: Proposal, vote_result: VoteResult
    ) -> None:
        """
        Print proposal details and voting results to console.

        Args:
            proposal: The proposal being voted on
            vote_result: The vote tallying result
        """
        assert self.game_manager.game_state is not None

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
        print(f"  YES: {vote_result.yes_count}")
        print(f"  NO: {vote_result.no_count}")
        print(f"  ABSTAIN: {vote_result.abstain_count}")
        print(f"\nResult: {'PASSED' if vote_result.passed else 'FAILED'}")
        print("=" * 60)

    def _print_outcome_summary(
        self, vote_result: VoteResult, judge_decisions: JudgeDecisions
    ) -> None:
        """
        Print judge decision outcome to console.

        Args:
            vote_result: The vote tallying result
            judge_decisions: The consolidated judge decisions
        """
        if judge_decisions.judge_approved:
            logger.info("Proposal PASSED and was not vetoed.")
            print("\n⚖️  JUDGE: Outcome stands. Applying PASSED proposal.")
        else:
            # Proposal failed or was vetoed
            if not vote_result.passed:
                logger.info("Proposal FAILED by vote.")
                print("\n⚖️  JUDGE: Outcome stands. Proposal FAILED.")
            else:
                # Proposal passed but was vetoed
                logger.warning("Judge VETOED passed proposal")
                print("\n⚖️  JUDGE VETO: Proposal has been VETOED and FAILED.")

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

    def check_existing_victory(self) -> tuple[bool, list[str], int]:
        """
        Check if victory has already been achieved in the loaded game state.

        This method is used to detect if a game has already ended before
        starting a new turn. It wraps _detect_victory() for external use.

        Returns:
            tuple[bool, list[str], int]: A tuple containing:
                - bool: True if victory condition is met, False otherwise
                - list[str]: List of winner names (empty if no victory)
                - int: Winning score (0 if no victory)
        """
        return self._detect_victory()

    def _print_victory_summary(
        self,
        winners: list[str],
        winning_score: int,
        sorted_scores: list[tuple[str, int]],
        target_score: int,
        total_turns: int,
    ) -> None:
        """
        Print a comprehensive victory summary to the console.

        Args:
            winners: List of player names who won
            winning_score: The winning score achieved
            sorted_scores: List of (player_name, score) tuples in descending
                          order by score
            target_score: The target score that was reached
            total_turns: Total number of completed turns
        """

        # Print victory banner
        print("\n" + "=" * 70)
        print("🏁 GAME OVER - VICTORY ACHIEVED! 🏁")
        print("=" * 70)

        # Print winner(s)
        if len(winners) == 1:
            print(f"\nWinner: {winners[0]}")
        else:
            winners_text = ", ".join(winners)
            print(f"\nWinners (tie): {winners_text}")
        print(f"Winning Score: {winning_score}")
        print(f"Target Score: {target_score}")

        # Print final scores
        print("\nFinal Scores:")
        for player_name, score in sorted_scores:
            marker = " 👑" if player_name in winners else ""
            print(f"  {player_name}: {score}{marker}")

        # Print game statistics
        print(f"\nTotal Turns Completed: {total_turns}")

        # Print instructions
        print("\nThe game has concluded. To review the complete game history,")
        print("please see the transcript file in the game directory.")
        print("To start a new game, run create_game.py.")
        print("=" * 70 + "\n")

    def _log_game_over(self, winners: list[str], winning_score: int) -> None:
        """Log a GAME OVER event to the history and transcript."""

        assert self.game_manager.game_state is not None

        target_score = self.game_manager.game_state.target_score
        assert target_score is not None  # Victory requires target_score
        scores = self.game_manager.game_state.scores
        winners_text = ", ".join(winners)

        # Sort scores once for both transcript and console (descending order)
        sorted_scores = sorted(
            scores.items(), key=lambda x: x[1], reverse=True
        )

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

        for player_name, score in sorted_scores:
            lines.append(f"- **{player_name}:** {score}")

        lines.append("")
        lines.append(
            f"Game completed after {self.game_manager.game_state.move_number} "
            f"turn(s)."
        )

        self.game_manager.logger.log_transcript("\n".join(lines))

        # Print comprehensive victory summary to console (reuse sorted scores)
        self._print_victory_summary(
            winners=winners,
            winning_score=winning_score,
            sorted_scores=sorted_scores,
            target_score=target_score,
            total_turns=self.game_manager.game_state.move_number,
        )

    def _resolve_turn(
        self,
        proposal: Proposal,
        votes: list[Vote],
        discussions: list[Discussion],
    ) -> bool:
        """
        Resolve the turn by tallying, judging, and applying changes.

        This method orchestrates the resolution phase using three discrete
        steps:
        1. Tallying: Calculate vote results (side-effect-free)
        2. Judging: Consolidate judge decisions (veto + scoring)
        3. Application: Apply mutations (the ONLY phase with side effects)

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

        # Phase 1: Tally votes (side-effect-free)
        logger.info("Phase 1: Tallying votes")
        vote_result = self._tally_vote_results(votes)

        # Print proposal and voting results to console
        self._print_proposal_summary(proposal, vote_result)

        # Phase 2: Get judge decisions (veto and scoring)
        logger.info("Phase 2: Consulting judge")
        judge_decisions = self._get_judge_decisions(
            proposal, votes, discussions, vote_result
        )

        # Communicate outcome before application
        self._print_outcome_summary(vote_result, judge_decisions)

        # Phase 3: Apply mutations (the ONLY phase with side effects)
        logger.info("Phase 3: Applying turn mutations")
        game_over = self._apply_turn_mutations(
            proposal, votes, discussions, vote_result, judge_decisions
        )

        logger.info(f"Resolution phase complete: game_over={game_over}")
        return game_over

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
