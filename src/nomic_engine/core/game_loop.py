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
from ..judge.llm_judge import LLMJudge
from ..judge_contracts import (
    JudgeScoreResponse,
    JudgeVetoResponse,
    StateUpdates,
)
from ..players.base_player import BasePlayer
from ..players.llm_player import LLMPlayer
from ..utils.player_label import format_player_label
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

        self._reset_judge_turn_state()

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
            original_proposal_for_log: Proposal | None = None

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
                discussions = self._collect_discussions(
                    proposal,
                    self.players,
                    is_retry=withdrawal_attempt > 0,
                    withdrawal_attempt=withdrawal_attempt,
                    max_withdrawal_retries=max_withdrawal_retries,
                )

                # Step 3: Revise
                # Save the proposal before revision so we can detect MODIFY
                pre_revision_proposal = proposal
                revised_proposal = self._handle_revision(
                    current_player, proposal, discussions
                )

                if revised_proposal is not None:
                    # Detect if the proposer actually modified the proposal
                    if revised_proposal is not pre_revision_proposal:
                        # MODIFY: track original for transcript (REQ-5)
                        original_proposal_for_log = pre_revision_proposal
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
                    self._update_all_memories()
                    break

                # Log withdrawn proposal to transcript before retry (REQ-1)
                withdrawn_entry = self._format_withdrawn_proposal_transcript(
                    proposal, discussions
                )
                self.game_manager.logger.log_transcript(withdrawn_entry)

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

            completed_turn_number = self.game_manager.game_state.move_number

            # Step 5: Resolve
            game_over = self._resolve_turn(
                proposal,
                votes,
                discussions,
                original_proposal=original_proposal_for_log,
            )

            self._update_all_memories()

            logger.info(f"Completed turn {completed_turn_number}")

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
        player_label = format_player_label(
            player_name, self.game_manager.game_config
        )
        print(f"\n❌ {label}: {error_message}")
        print(f"Proposer: {player_label}")
        print("The proposal cannot proceed.\n")

        blocks = [
            f"## MOVE #{self.game_manager.game_state.move_number}",
            f"**Proposer:** {player_label}",
            f"**Type:** {proposal.type.value}",
        ]

        if proposal.target_rule_id:
            blocks.append(f"**Target Rule ID:** {proposal.target_rule_id}")

        if proposal.new_text:
            blocks.append(f"**New Text:** {proposal.new_text}")

        if proposal.rationale:
            blocks.append(f"**Rationale:** {proposal.rationale}")

        blocks.append(f"**Result:** {label}")
        blocks.append(f"**Reason:** {error_message}")

        transcript_entry = "\n\n".join(blocks)
        self.game_manager.logger.log_transcript(transcript_entry)

    def _format_withdrawn_proposal_transcript(
        self,
        proposal: Proposal,
        discussions: list[Discussion],
    ) -> str:
        """
        Format a withdrawn proposal entry for the transcript.

        Args:
            proposal: The proposal that was withdrawn
            discussions: Discussion comments received before withdrawal

        Returns:
            Formatted markdown string for the transcript
        """
        assert self.game_manager.game_state is not None

        proposer_label = format_player_label(
            proposal.proposer_name, self.game_manager.game_config
        )

        blocks: list[str] = []
        blocks.append(f"## MOVE #{proposal.move_number} (Withdrawn Proposal)")
        blocks.append(f"**Proposal ID:** {proposal.proposal_id}")
        blocks.append(f"**Proposer:** {proposer_label}")
        blocks.append(f"**Type:** {proposal.type.value}")

        if proposal.target_rule_id:
            blocks.append(f"**Target Rule ID:** {proposal.target_rule_id}")

        if proposal.new_text:
            blocks.append(f"**New Text:** {proposal.new_text}")

        if proposal.rationale:
            blocks.append(f"**Rationale:** {proposal.rationale}")

        discussion_lines = ["### Discussions"]
        for discussion in discussions:
            disc_label = format_player_label(
                discussion.player_name, self.game_manager.game_config
            )
            if discussion.text:
                discussion_lines.append(
                    f"- **{disc_label}:** {discussion.text}"
                )
            else:
                discussion_lines.append(f"- **{disc_label}:** *(Abstained)*")
        blocks.append("\n".join(discussion_lines))

        blocks.append("**Result:** WITHDRAWN")

        return "\n\n".join(blocks)

    def _get_and_validate_proposal(
        self,
        current_player: BasePlayer,
        continue_turn: bool = False,
    ) -> Proposal | None:
        """
        Get proposal from current player and validate it.

        This method gets the proposal from the player and validates it
        for legality.

        Args:
            current_player: The player whose turn it is
            continue_turn: True when retrying after a withdrawal

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
        self,
        proposal: Proposal,
        players: list[BasePlayer],
        is_retry: bool = False,
        withdrawal_attempt: int = 0,
        max_withdrawal_retries: int = 0,
    ) -> list[Discussion]:
        """
        Collect discussion from all players.

        Per Rule 111, all players may discuss. However, the proposer's
        rationale from the proposal serves as their discussion contribution,
        so they are not prompted again.

        On a retry round with ``retain_discusser_history_on_retry=True``,
        ``on_proposal_updated`` is called on each non-proposing player to
        inject the new proposal into their existing discussion context
        without resetting accumulated history.

        Args:
            proposal: The proposal to discuss
            players: List of all players
            is_retry: True when this discussion round follows a withdrawal
                retry.
            withdrawal_attempt: The current withdrawal attempt number
                (1-based; 0 on the first attempt). Forwarded to
                ``on_proposal_updated``.
            max_withdrawal_retries: The maximum number of withdrawal retries
                configured for this game. Forwarded to
                ``on_proposal_updated``.

        Returns:
            List of Discussion objects from all players (includes abstentions)
        """
        assert self.game_manager.game_state is not None
        assert self.game_manager.rules_manager is not None

        logger.info("Step 2: Discussion phase")

        retain_history = (
            is_retry
            and self.game_manager.game_config is not None
            and self.game_manager.game_config.retain_discusser_history_on_retry
        )

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

            if retain_history:
                # Retry round with history preservation: inject the new
                # proposal into the player's existing context without
                # resetting accumulated reasoning.
                player.on_proposal_updated(
                    proposal=proposal,
                    game_state=self.game_manager.game_state,
                    rules=self.game_manager.rules_manager.rules,
                    withdrawal_attempt=withdrawal_attempt,
                    max_withdrawal_retries=max_withdrawal_retries,
                )
            else:
                # First round or retry without history preservation: reset
                # the player's discussion context with the new proposal.
                player.begin_discussion_turn(
                    proposal=proposal,
                    game_state=self.game_manager.game_state,
                    rules=self.game_manager.rules_manager.rules,
                )

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
            self.game_manager,
            self.players,
            proposal,
            votes,
            discussions,
            proposal_passed=vote_result.passed,
        )
        logger.debug(
            f"Judge score assessment complete: "
            f"{len(score_response.get('score_adjustments', []))} adjustments"
        )

        # Calculate approval status
        judge_approved = vote_result.passed and not judge_vetoed

        # Call maintain_state only when judge approved a non-TRANSMUTE proposal
        if judge_approved and proposal.type != ProposalType.TRANSMUTE:
            assert self.game_manager.rules_manager is not None
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

            state_updates = self.judge.maintain_state(
                game_manager=self.game_manager,
                proposal=proposal,
                original_rule_text=original_rule_text,
                new_rule_text=new_rule_text,
            )
            logger.debug(
                "maintain_state returned %d key(s)", len(state_updates)
            )
        else:
            # Proposal failed, was vetoed, or is a TRANSMUTE — no state updates
            state_updates = {}

        decisions = JudgeDecisions(
            veto_response=veto_response,
            score_response=score_response,
            judge_approved=judge_approved,
            state_updates=state_updates,
        )

        logger.debug(
            f"Exiting _get_judge_decisions: "
            f"judge_approved={decisions.judge_approved}"
        )
        return decisions

    def _apply_score_changes(self, score_response: JudgeScoreResponse) -> None:
        """Apply each score delta in score_response to game_state.scores."""
        assert self.game_manager.game_state is not None

        for adjustment in score_response.get("score_adjustments", []):
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

    def _apply_engine_state_changes(self, state_updates: StateUpdates) -> None:
        """Apply flag and target_score changes to game_state (if changed)."""
        assert self.game_manager.game_state is not None

        if "flags" in state_updates:
            for flag_name, flag_value in state_updates["flags"].items():
                current_value = self.game_manager.game_state.flags.get(
                    flag_name
                )
                if current_value != flag_value:
                    self.game_manager.game_state.flags[flag_name] = flag_value
                    logger.info(
                        "Updated flag %s from %s to %s",
                        flag_name,
                        current_value,
                        flag_value,
                    )

        if "target_score" in state_updates:
            new_score = state_updates["target_score"]
            current_score = self.game_manager.game_state.target_score
            if current_score != new_score:
                self.game_manager.game_state.target_score = new_score
                logger.info(
                    "Updated target_score from %s to %s",
                    current_score,
                    new_score,
                )

    def _apply_rule_changes(self, proposal: Proposal) -> None:
        """Apply the proposal to rules and persist the updated rules."""
        assert self.game_manager.rules_manager is not None

        logger.debug(
            f"Applying passed proposal {proposal.proposal_id} to rules"
        )
        self.game_manager.rules_manager.apply_proposal(proposal)
        self.game_manager.save_rules()
        logger.debug("Proposal applied and rules saved")

    def _increment_proposal_counter(self) -> None:
        """Increment next_proposal_id by 1."""
        assert self.game_manager.game_state is not None

        self.game_manager.game_state.next_proposal_id += 1
        logger.debug(
            "Proposal ID incremented to %s",
            self.game_manager.game_state.next_proposal_id,
        )

    def _save_turn(self) -> None:
        """Persist the current game state to disk."""
        self.game_manager.save_game_state()
        logger.debug("Game state saved")

    def _log_turn(
        self,
        proposal: Proposal,
        votes: list[Vote],
        discussions: list[Discussion],
        vote_result: VoteResult,
        judge_decisions: JudgeDecisions,
        original_proposal: Proposal | None,
    ) -> None:
        """Format and write the transcript entry for this turn."""
        assert self.game_manager.rules_manager is not None

        transcript_entry = self._format_transcript(
            proposal,
            votes,
            vote_result.passed,
            judge_decisions.judge_approved,
            judge_decisions.veto_response,
            judge_decisions.score_response,
            discussions,
            self.game_manager.rules_manager.rules,
            state_updates=judge_decisions.state_updates,
            original_proposal=original_proposal,
        )
        self.game_manager.logger.log_transcript(transcript_entry)
        logger.debug("Transcript logged")

    def _apply_turn_mutations(
        self,
        proposal: Proposal,
        votes: list[Vote],
        discussions: list[Discussion],
        vote_result: VoteResult,
        judge_decisions: JudgeDecisions,
        original_proposal: Proposal | None = None,
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
            original_proposal: The proposal before revision, if modified
                (None when the proposal was kept as-is)

        Returns:
            bool: True if game ended by victory, False otherwise
        """
        assert self.game_manager.game_state is not None
        assert self.game_manager.rules_manager is not None

        logger.debug("Entering _apply_turn_mutations")

        self._apply_score_changes(judge_decisions.score_response)

        if judge_decisions.judge_approved:
            self._apply_engine_state_changes(judge_decisions.state_updates)
            self._apply_rule_changes(proposal)
        else:
            logger.debug(
                "Proposal not applied (failed vote or vetoed), "
                "skipping rule modifications"
            )

        self._increment_proposal_counter()

        victory_reached, winners, winning_score = self._detect_victory()
        logger.debug(f"Victory detection: victory_reached={victory_reached}")

        if not victory_reached:
            logger.debug("No victory, advancing turn state")
            self._advance_turn_state()
        else:
            logger.debug(
                f"Victory detected for {winners} with score {winning_score}, "
                "not advancing turn"
            )

        self._log_turn(
            proposal,
            votes,
            discussions,
            vote_result,
            judge_decisions,
            original_proposal,
        )
        self._save_turn()

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

        proposer_label = format_player_label(
            proposal.proposer_name, self.game_manager.game_config
        )
        print("\n" + "=" * 60)
        print(f"PROPOSAL #{self.game_manager.game_state.move_number}")
        print(f"Proposal ID: {proposal.proposal_id}")
        print(f"Proposer: {proposer_label}")
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
        - Checks for automatic rule transitions
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

        # Check for automatic rule transitions after turn state is updated
        self._check_automatic_transitions()

    def _reset_judge_turn_state(self) -> None:
        """Reset the judge's per-turn cached responses.

        Clears ``_judge_turn_responses`` on an ``LLMJudge`` so each turn
        starts with a fresh accumulator. Is a no-op for a ``HumanJudge`` or
        any other non-LLM judge.
        """
        if isinstance(self.judge, LLMJudge):
            self.judge._judge_turn_responses = []

    def _update_all_memories(self) -> None:
        """Trigger memory updates for all LLM players and the LLM judge.

        Called after every resolved turn (including forfeit/withdrawal exits).
        Human players and a ``HumanJudge`` are silently skipped.
        """
        judge_outputs = (
            self.judge._judge_turn_responses
            if isinstance(self.judge, LLMJudge)
            else None
        )

        for player in self.players:
            if isinstance(player, LLMPlayer):
                player.update_memory(judge_turn_outputs=judge_outputs)
        if isinstance(self.judge, LLMJudge):
            self.judge.update_memory()

    def _check_automatic_transitions(self) -> None:
        """
        Check and apply automatic engine-enforced rule transitions.

        This method is the single location for all automatic transitions
        enforced by the engine. Currently implements:
        - Rule 203: unanimous → majority voting after 2 complete circuits

        Future automatic transitions should be added as focused private
        methods called from here.
        """
        self._check_rule_203_transition()

    def _check_rule_203_transition(self) -> None:
        """
        Check and apply Rule 203 automatic unanimous → majority transition.

        Rule 203 states: "If this rule is not amended by the end of the
        second complete circuit of turns, it automatically changes to
        require only a simple majority."

        This method:
        - Does nothing if vote_mode is already "majority" (idempotent)
        - Does nothing if Rule 203 has been amended (no rule_id="203" exists)
        - Calculates completed circuits from move_number and turn_order
        - If exactly 2 complete circuits have been completed, transitions
          vote_mode from "unanimous" to "majority"
        - Logs the transition and adds a transcript entry
        """
        assert self.game_manager.game_state is not None
        assert self.game_manager.rules_manager is not None

        current_vote_mode = self.game_manager.game_state.flags.get(
            "vote_mode", "unanimous"
        )
        if current_vote_mode == "majority":
            return

        rule_203 = self.game_manager.rules_manager._find_rule_by_id("203")
        if rule_203 is None:
            # Rule 203 has been amended, don't apply automatic transition
            return

        # A complete circuit = all players taking one turn
        # Completes at the end of each multiple of N turns
        move_number = self.game_manager.game_state.move_number
        num_players = len(self.game_manager.game_state.turn_order)
        completed_circuits = (move_number - 1) // num_players

        if completed_circuits >= 2:
            self.game_manager.game_state.flags["vote_mode"] = "majority"

            logger.info(
                "Automatic Rule 203 transition: vote_mode changed from "
                "'unanimous' to 'majority' after %d complete circuits",
                completed_circuits,
            )

            transcript_entry = (
                "[ENGINE] Automatic transition: Rule 203 has been in "
                f"effect for {completed_circuits} complete circuits "
                "without amendment. vote_mode changed from 'unanimous' "
                "to 'majority'."
            )
            self.game_manager.logger.log_transcript(transcript_entry)

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

    def _format_victory_summary(
        self,
        winners: list[str],
        winning_score: int,
        scores: dict[str, int],
        target_score: int,
        total_turns: int,
    ) -> str:
        """
        Format a comprehensive victory summary as a string.

        Args:
            winners: List of player names who won
            winning_score: The winning score achieved
            scores: Dictionary mapping player names to their scores
            target_score: The target score that was reached
            total_turns: Total number of completed turns

        Returns:
            Formatted victory summary string
        """
        # Sort scores in descending order for display
        sorted_scores = sorted(
            scores.items(), key=lambda x: x[1], reverse=True
        )

        lines = [
            "",
            "=" * 70,
            "🏁 GAME OVER - VICTORY ACHIEVED! 🏁",
            "=" * 70,
            "",
        ]

        # Winner(s)
        if len(winners) == 1:
            lines.append(f"Winner: {winners[0]}")
        else:
            winners_text = ", ".join(winners)
            lines.append(f"Winners (tie): {winners_text}")
        lines.append(f"Winning Score: {winning_score}")
        lines.append(f"Target Score: {target_score}")

        # Final scores
        lines.append("")
        lines.append("Final Scores:")
        for player_name, score in sorted_scores:
            marker = " 👑" if player_name in winners else ""
            lines.append(f"  {player_name}: {score}{marker}")

        # Game statistics
        lines.append("")
        lines.append(f"Total Turns Completed: {total_turns}")

        # Instructions
        lines.append("")
        lines.append(
            "The game has concluded. To review the complete game history,"
        )
        lines.append("please see the transcript file in the game directory.")
        lines.append("To start a new game, run create_game.py.")
        lines.append("=" * 70)
        lines.append("")

        return "\n".join(lines)

    def _log_game_over(self, winners: list[str], winning_score: int) -> None:
        """Log a GAME OVER event to the history and transcript."""

        assert self.game_manager.game_state is not None

        target_score = self.game_manager.game_state.target_score
        assert target_score is not None  # Victory requires target_score
        scores = self.game_manager.game_state.scores

        # Log structured event for programmatic access
        self.game_manager.logger.log_event(
            "game_over",
            {
                "target_score": target_score,
                "winners": winners,
                "winning_score": winning_score,
                "final_scores": scores,
            },
        )

        # Generate victory summary (used for both transcript and console)
        # Note: _format_victory_summary handles sorting internally
        victory_summary = self._format_victory_summary(
            winners=winners,
            winning_score=winning_score,
            scores=scores,
            target_score=target_score,
            total_turns=self.game_manager.game_state.move_number,
        )

        # Log to transcript and print to console
        self.game_manager.logger.log_transcript(victory_summary)
        print(victory_summary)

    def _resolve_turn(
        self,
        proposal: Proposal,
        votes: list[Vote],
        discussions: list[Discussion],
        original_proposal: Proposal | None = None,
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
            original_proposal: The proposal before revision, if the proposer
                chose MODIFY (None when the proposal was kept as-is)

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
            proposal,
            votes,
            discussions,
            vote_result,
            judge_decisions,
            original_proposal=original_proposal,
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
        state_updates: StateUpdates | None = None,
        original_proposal: Proposal | None = None,
    ) -> str:
        """
        Format a complete turn summary for the transcript.

        Args:
            proposal: The final proposal (after any revision)
            votes: List of votes
            proposal_passed: Whether the vote passed
            judge_approved: Whether the judge approved
            judge_veto_response: Details from the judge's veto decision
            judge_score_response: Details from the judge's score assessment
            discussions: List of Discussion objects from all players
            rules: List of all current rules
            state_updates: Engine state changes from maintain_state, or None
                if maintain_state was not called (failed/vetoed proposal)
            original_proposal: The proposal before revision when the proposer
                chose MODIFY; None when the proposal was kept as-is

        Returns:
            Formatted markdown string for the transcript
        """
        assert self.game_manager.game_state is not None

        blocks: list[str] = []

        proposer_label = format_player_label(
            proposal.proposer_name, self.game_manager.game_config
        )

        blocks.append(f"## MOVE #{proposal.move_number}")
        blocks.append(f"**Proposal ID:** {proposal.proposal_id}")
        blocks.append(f"**Proposer:** {proposer_label}")

        if original_proposal is not None:
            # REQ-5: Proposal was revised (MODIFY) — show original before
            # discussions, then revised submission after discussions.

            # --- Original Submission ---
            orig_lines: list[str] = []
            orig_lines.append("**Original Submission**")
            orig_lines.append(f"**Type:** {original_proposal.type.value}")
            if original_proposal.target_rule_id:
                orig_lines.append(
                    f"**Target Rule ID:** "
                    f"{original_proposal.target_rule_id}"
                )
            if original_proposal.new_text:
                orig_lines.append(
                    f"**New Text:** {original_proposal.new_text}"
                )
            if original_proposal.rationale:
                orig_lines.append(
                    f"**Rationale:** {original_proposal.rationale}"
                )
            blocks.append("\n".join(orig_lines))

            # --- Discussions ---
            discussion_lines = ["### Discussions"]
            for discussion in discussions:
                disc_label = format_player_label(
                    discussion.player_name, self.game_manager.game_config
                )
                if discussion.text:
                    discussion_lines.append(
                        f"- **{disc_label}:** {discussion.text}"
                    )
                else:
                    discussion_lines.append(
                        f"- **{disc_label}:** *(Abstained)*"
                    )
                if discussion.private_thoughts:
                    discussion_lines.append(
                        f"  - Private Thoughts: "
                        f"{discussion.private_thoughts}"
                    )
            blocks.append("\n".join(discussion_lines))

            # --- Revised Submission ---
            rev_lines: list[str] = []
            rev_lines.append("**Revised Submission**")
            rev_lines.append(f"**Type:** {proposal.type.value}")
            if proposal.target_rule_id:
                rev_lines.append(
                    f"**Target Rule ID:** {proposal.target_rule_id}"
                )
            if proposal.new_text:
                rev_lines.append(f"**New Text:** {proposal.new_text}")
            if proposal.rationale:
                rev_lines.append(f"**Rationale:** {proposal.rationale}")
            if proposal.private_thoughts:
                rev_lines.append(
                    f"**Private Thoughts:** {proposal.private_thoughts}"
                )
            # Add original rule text for AMEND/REPEAL/TRANSMUTE
            if proposal.type in [
                ProposalType.AMEND,
                ProposalType.REPEAL,
                ProposalType.TRANSMUTE,
            ]:
                if proposal.target_rule_id:
                    for rule in rules:
                        if rule.rule_id == proposal.target_rule_id:
                            rev_lines.append(
                                f"**Original Text (Rule {rule.rule_id}):** "
                                f"{rule.text}"
                            )
                            break
            blocks.append("\n".join(rev_lines))

        else:
            # No revision (KEEP) or first-time proposal — standard format.
            blocks.append(f"**Type:** {proposal.type.value}")

            if proposal.target_rule_id:
                blocks.append(f"**Target Rule ID:** {proposal.target_rule_id}")

            if proposal.new_text:
                blocks.append(f"**New Text:** {proposal.new_text}")

            if proposal.rationale:
                blocks.append(f"**Rationale:** {proposal.rationale}")

            if proposal.private_thoughts:
                blocks.append(
                    f"**Private Thoughts:** {proposal.private_thoughts}"
                )

            # Add original text for AMEND, REPEAL, or TRANSMUTE proposals
            if proposal.type in [
                ProposalType.AMEND,
                ProposalType.REPEAL,
                ProposalType.TRANSMUTE,
            ]:
                if proposal.target_rule_id:
                    for rule in rules:
                        if rule.rule_id == proposal.target_rule_id:
                            blocks.append(
                                f"**Original Text (Rule {rule.rule_id}):** "
                                f"{rule.text}"
                            )
                            break

            discussion_lines = ["### Discussions"]
            for discussion in discussions:
                disc_label = format_player_label(
                    discussion.player_name, self.game_manager.game_config
                )
                if discussion.text:
                    discussion_lines.append(
                        f"- **{disc_label}:** {discussion.text}"
                    )
                else:
                    discussion_lines.append(
                        f"- **{disc_label}:** *(Abstained)*"
                    )
                if discussion.private_thoughts:
                    discussion_lines.append(
                        f"  - Private Thoughts: {discussion.private_thoughts}"
                    )
            blocks.append("\n".join(discussion_lines))

        # --- Votes ---
        vote_lines = ["### Votes"]
        for vote in votes:
            vote_label = format_player_label(
                vote.player_name, self.game_manager.game_config
            )
            vote_lines.append(f"- **{vote_label}:** {vote.vote}")
            if vote.reason:
                vote_lines.append(f"  - Public Reason: {vote.reason}")
            if vote.private_thoughts:
                vote_lines.append(
                    f"  - Private Thoughts: {vote.private_thoughts}"
                )
        blocks.append("\n".join(vote_lines))

        blocks.append(
            f"**Vote Result:** {'PASSED' if proposal_passed else 'FAILED'}"
        )

        # REQ-2: Suppress judge fields when proposal failed the vote
        if proposal_passed:
            blocks.append(
                f"**Judge Approval:** {'YES' if judge_approved else 'NO'}"
            )
        else:
            blocks.append("**Judge Approval:** N/A")

        # REQ-2: Judge Veto Response — N/A when proposal failed
        veto_lines = ["### Judge Veto Response"]
        if not proposal_passed:
            veto_lines.append("N/A")
        else:
            is_veto = judge_veto_response["veto"]
            judge_veto_decision = "VETO" if is_veto else "ALLOW"
            veto_lines.append(f"- **Decision:** {judge_veto_decision}")
            if judge_veto_response.get("reason"):
                veto_lines.append(
                    f"- **Reason:** {judge_veto_response['reason']}"
                )
            if judge_veto_response.get("private_thoughts"):
                private_thoughts = judge_veto_response["private_thoughts"]
                veto_lines.append(f"  - Private Thoughts: {private_thoughts}")
        blocks.append("\n".join(veto_lines))

        score_resp_lines = ["### Judge Score Response"]
        if judge_score_response.get("private_thoughts"):
            judge_private = judge_score_response["private_thoughts"]
            score_resp_lines.append(f"- Private Thoughts: {judge_private}")
        adjustments = judge_score_response.get("score_adjustments", [])
        if adjustments:
            for adj in adjustments:
                adj_text = f"- **{adj['player']}:** {adj['delta']:+d}"
                score_resp_lines.append(f"{adj_text} ({adj['reason']})")
        else:
            score_resp_lines.append("- No score adjustments this turn.")
        blocks.append("\n".join(score_resp_lines))

        # REQ-3: Judge State Maintenance — only when judge_approved
        # (skipped entirely when proposal failed or was vetoed)
        if judge_approved:
            state_lines = ["### Judge State Maintenance"]
            has_flag_changes = bool(
                state_updates and state_updates.get("flags")
            )
            has_score_change = bool(
                state_updates and "target_score" in state_updates
            )
            if has_flag_changes or has_score_change:
                assert state_updates is not None
                if state_updates.get("flags"):
                    for flag_name, flag_value in state_updates[
                        "flags"
                    ].items():
                        state_lines.append(
                            f"- **Flag `{flag_name}`:** {flag_value}"
                        )
                if "target_score" in state_updates:
                    state_lines.append(
                        f"- **`target_score`:** "
                        f"{state_updates['target_score']}"
                    )
            else:
                state_lines.append("No engine state changes.")
            blocks.append("\n".join(state_lines))

        # Scores section – bare player names are sufficient here;
        # adding personality/model labels would be visually noisy in what
        # is purely a numeric summary.
        score_display_lines = ["### Scores"]
        for p_name, score in self.game_manager.game_state.scores.items():
            score_display_lines.append(f"- **{p_name}:** {score}")
        blocks.append("\n".join(score_display_lines))

        return "\n\n".join(blocks)
