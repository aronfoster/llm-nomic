"""
PromptBuilder - Factory for creating LLM chat messages from templates.

This class populates the atomized prompt templates in prompts.py with actual
game data, generating incremental context blocks (System or User messages)
for stateful conversation history per player.

Sprint 6 refactor: Methods now return single ChatMessage objects instead of
full message lists, enabling persistent conversation history per player.
"""

from ..data_models import ChatMessage, Discussion, GameState, Proposal, Rule
from . import prompts


class PromptBuilder:
    """Builds LLM chat message context blocks from atomized templates."""

    def _format_rules(self, rules: list[Rule]) -> str:
        """
        Format a list of rules into a readable text block.

        Args:
            rules: List of Rule objects to format

        Returns:
            Formatted string with each rule on its own line(s)
            Example: "### 101 (Immutable): The game ends when..."
        """
        if not rules:
            return "No rules defined."

        formatted_lines = []
        for rule in rules:
            # Format: ### {rule_id} ({status}): {text}
            status_label = rule.status.value.capitalize()
            formatted_lines.append(
                f"### {rule.rule_id} ({status_label}): {rule.text}"
            )

        return "\n".join(formatted_lines)

    def _format_scores(self, scores: dict[str, int]) -> str:
        """
        Format the scores dictionary into a readable list.

        Args:
            scores: Dictionary mapping player names to their scores

        Returns:
            Formatted string with each player's score
            Example: "- Alice: 10\n- Bob: 5\n- Charlie: 3"
        """
        if not scores:
            return "No scores yet."

        # Sort by score descending, then alphabetically by name
        sorted_players = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
        return "\n".join(
            f"- {name}: {score}" for name, score in sorted_players
        )

    def _format_discussions(self, discussions: list[Discussion]) -> str:
        """
        Format discussion messages into a readable conversation.

        Args:
            discussions: List of Discussion objects

        Returns:
            Formatted string with each discussion message
            Example: "**Alice:** I think this is a good idea."
        """
        if not discussions:
            return "No discussions yet."

        formatted_lines = []
        for discussion in discussions:
            # Only include non-empty discussions (skip abstentions)
            if discussion.text:
                formatted_lines.append(
                    f"**{discussion.player_name}:** {discussion.text}"
                )

        if not formatted_lines:
            return "No discussions yet."

        return "\n".join(formatted_lines)

    def _format_proposal(
        self, proposal: Proposal, rules: list[Rule], player_name: str
    ) -> str:
        """
        Format a proposal into a PROPOSAL_BLOCK.

        Args:
            proposal: The proposal to format
            rules: All current rules (to find original text for amendments)
            player_name: The current player (to mark if they're the proposer)

        Returns:
            Formatted PROPOSAL_BLOCK string
        """
        # Handle optional fields in proposal
        target_rule_id = proposal.target_rule_id or "N/A"
        original_text = "N/A"
        if proposal.target_rule_id:
            # Try to find the original text from the rules list
            for rule in rules:
                if rule.rule_id == proposal.target_rule_id:
                    original_text = rule.text
                    break

        new_text = proposal.new_text or "N/A"
        rationale = proposal.rationale or "No rationale provided."

        # Mark proposer as (YOU) if they're the current player
        display_proposer = proposal.proposer_name
        if proposal.proposer_name == player_name:
            display_proposer = f"{proposal.proposer_name} (YOU)"

        return prompts.PROPOSAL_BLOCK.format(
            proposal_id=proposal.proposal_id or "Unknown",
            proposer_name=display_proposer,
            proposal_type=proposal.type.value,
            target_rule_id=target_rule_id,
            original_text=original_text,
            new_text=new_text,
            rationale=rationale,
        )

    def _get_player_position(self, player_name: str, state: GameState) -> str:
        """
        Calculate the player's position in the turn order.

        Args:
            player_name: The name of the player
            state: The current game state containing turn order

        Returns:
            String like "1 of 3" or "2 of 4"

        Raises:
            ValueError: If player_name is not found in turn_order
        """
        try:
            position = state.turn_order.index(player_name) + 1  # 1-indexed
            total = len(state.turn_order)
            return f"{position} of {total}"
        except ValueError:
            raise ValueError(
                f"Player '{player_name}' not found in turn order: "
                f"{state.turn_order}"
            )

    def _get_personality_block(self, personality: str) -> str:
        """
        Get the appropriate personality block based on the personality key.

        Args:
            personality: Either "machiavellian" or "friendly"

        Returns:
            The appropriate personality template string
        """
        if personality.lower() == "machiavellian":
            return prompts.MACHIAVELLIAN_PERSONALITY
        else:
            # Default to friendly for any non-machiavellian value
            return prompts.FRIENDLY_PERSONALITY

    def _format_game_state_block(
        self, game_state: GameState, player_name: str
    ) -> str:
        """
        Format the GAME_STATE_BLOCK with current game data.

        Args:
            game_state: The current game state
            player_name: The name of the player (for position calculation)

        Returns:
            Formatted GAME_STATE_BLOCK string
        """
        scores_text = self._format_scores(game_state.scores)
        player_position = self._get_player_position(player_name, game_state)
        turn_order_str = ", ".join(game_state.turn_order)

        return prompts.GAME_STATE_BLOCK.format(
            move_number=game_state.move_number,
            scores_text=scores_text,
            player_position=player_position,
            turn_order=turn_order_str,
        )

    def build_proposer_system_message(
        self,
        rules: list[Rule],
        game_state: GameState,
        player_name: str,
        personality: str,
    ) -> ChatMessage:
        """
        Build the system message for the Proposer at the start of their turn.

        Sets the stage for the Proposer by assembling:
        - Base Persona (based on personality)
        - GAME_STATE_BLOCK (formatted with scores/turn order)
        - RULES_BLOCK (formatted with rules)
        - INSTRUCTION_PROPOSE (formatted with JSON format enforcement)

        Args:
            rules: All current rules in the game
            game_state: The current game state
            player_name: The name of the player making the proposal
            personality: The persona key ("machiavellian" or "friendly")

        Returns:
            A single ChatMessage with role="system"

        Raises:
            ValueError: If player_name is not in turn_order
        """
        # Get personality block and format with player name
        persona_block = self._get_personality_block(personality).format(
            player_name=player_name
        )

        # Format game state block
        game_state_block = self._format_game_state_block(
            game_state, player_name
        )

        # Format rules block
        rules_text = self._format_rules(rules)
        rules_block = prompts.RULES_BLOCK.format(rules_text=rules_text)

        # Format instruction block
        instruction_block = prompts.INSTRUCTION_PROPOSE.format(
            json_format_enforcement=prompts.JSON_FORMAT_ENFORCEMENT
        )

        # Assemble the full system message
        content = "\n\n".join(
            [
                persona_block,
                game_state_block,
                rules_block,
                instruction_block,
            ]
        )

        return ChatMessage(role="system", content=content)

    def build_discusser_system_message(
        self,
        proposal: Proposal,
        rules: list[Rule],
        game_state: GameState,
        player_name: str,
        personality: str,
    ) -> ChatMessage:
        """
        Build the system message for players to discuss the proposal.

        Sets the stage for other players by assembling:
        - Base Persona (based on personality)
        - GAME_STATE_BLOCK (formatted with scores/turn order)
        - RULES_BLOCK (formatted with rules)
        - PROPOSAL_BLOCK (formatted with the initial proposal details)
        - INSTRUCTION_DISCUSS

        Args:
            proposal: The proposal being discussed
            rules: All current rules in the game
            game_state: The current game state
            player_name: The name of the player who is discussing
            personality: The persona key ("machiavellian" or "friendly")

        Returns:
            A single ChatMessage with role="system"

        Raises:
            ValueError: If player_name is not in turn_order
        """
        # Get personality block and format with player name
        persona_block = self._get_personality_block(personality).format(
            player_name=player_name
        )

        # Format game state block
        game_state_block = self._format_game_state_block(
            game_state, player_name
        )

        # Format rules block
        rules_text = self._format_rules(rules)
        rules_block = prompts.RULES_BLOCK.format(rules_text=rules_text)

        # Format proposal block
        proposal_block = self._format_proposal(proposal, rules, player_name)

        # Format instruction block
        instruction_block = prompts.INSTRUCTION_DISCUSS.format(
            json_format_enforcement=prompts.JSON_FORMAT_ENFORCEMENT
        )

        # Assemble the full system message
        content = "\n\n".join(
            [
                persona_block,
                game_state_block,
                rules_block,
                proposal_block,
                instruction_block,
            ]
        )

        return ChatMessage(role="system", content=content)

    def build_revision_instruction(
        self, discussions: list[Discussion]
    ) -> ChatMessage:
        """
        Build the user message with discussion feedback for the Proposer.

        Feeds feedback to the Proposer and asks for revision by assembling:
        - DISCUSSION_BLOCK (formatted with the discussions)
        - INSTRUCTION_REVISE (formatted with constraint_message from Rule 112)

        The constraint_message is derived from checking if any discussion
        contains "UNCLEAR" or "AMBIGUOUS" (case insensitive).

        Args:
            discussions: List of Discussion objects from all players

        Returns:
            A single ChatMessage with role="user"
        """
        # Format discussions block
        discussions_text = self._format_discussions(discussions)
        discussions_block = prompts.DISCUSSION_BLOCK.format(
            discussions_text=discussions_text
        )

        # Rule 112 Check: Detect UNCLEAR or AMBIGUOUS in discussions
        constraint_triggered = False
        for discussion in discussions:
            message_upper = discussion.text.upper()
            if "UNCLEAR" in message_upper or "AMBIGUOUS" in message_upper:
                constraint_triggered = True
                break

        if constraint_triggered:
            constraint_message = (
                "⚠️ CRITICAL: Your proposal was flagged as 'UNCLEAR' or "
                "'AMBIGUOUS'. Per Rule 112, you MUST either 'MODIFY' or "
                "'WITHDRAW'. You CANNOT choose 'KEEP'."
            )
        else:
            constraint_message = (
                "You may choose to KEEP, MODIFY, or WITHDRAW based on "
                "your strategy."
            )

        # Format instruction block
        instruction_block = prompts.INSTRUCTION_REVISE.format(
            constraint_message=constraint_message,
            json_format_enforcement=prompts.JSON_FORMAT_ENFORCEMENT,
        )

        # Assemble the full user message
        content = "\n\n".join(
            [
                discussions_block,
                instruction_block,
            ]
        )

        return ChatMessage(role="user", content=content)

    def build_vote_instruction(
        self,
        proposal: Proposal,
        discussions: list[Discussion],
        rules: list[Rule],
        player_name: str,
    ) -> ChatMessage:
        """
        Build the user message presenting the final proposal for voting.

        Presents the final option to all players and asks for a vote by:
        - PROPOSAL_BLOCK (formatted with the revised proposal details)
        - DISCUSSION_BLOCK (formatted with the discussions)
        - INSTRUCTION_VOTE

        Args:
            proposal: The (potentially revised) proposal being voted on
            discussions: List of Discussion objects from all players
            rules: All current rules (for original text lookup)
            player_name: The name of the player who is voting

        Returns:
            A single ChatMessage with role="user"
        """
        # Format proposal block (with potentially revised proposal)
        proposal_block = self._format_proposal(proposal, rules, player_name)

        # Format discussions block
        discussions_text = self._format_discussions(discussions)
        discussions_block = prompts.DISCUSSION_BLOCK.format(
            discussions_text=discussions_text
        )

        # Format instruction block
        instruction_block = prompts.INSTRUCTION_VOTE.format(
            json_format_enforcement=prompts.JSON_FORMAT_ENFORCEMENT
        )

        # Assemble the full user message
        content = "\n\n".join(
            [
                proposal_block,
                discussions_block,
                instruction_block,
            ]
        )

        return ChatMessage(role="user", content=content)

    # =========================================================================
    # LEGACY METHODS (Backward compatibility for LLMPlayer until Task 3)
    # These wrap the new granular methods to return [system, user] lists.
    # TODO: Remove these after Task 3 refactors LLMPlayer to stateful.
    # =========================================================================

    def build_propose_messages(
        self,
        rules: list[Rule],
        game_state: GameState,
        player_name: str,
    ) -> list[ChatMessage]:
        """
        [LEGACY] Build message list for the PROPOSE action.

        Backward compatibility wrapper. Use build_proposer_system_message()
        for stateful contexts.

        Args:
            rules: All current rules in the game
            game_state: The current game state
            player_name: The name of the player making the proposal

        Returns:
            A list of ChatMessage objects: [system_message, user_message]
        """
        # Use machiavellian as default personality for backward compat
        system_msg = self.build_proposer_system_message(
            rules=rules,
            game_state=game_state,
            player_name=player_name,
            personality="machiavellian",
        )
        # For legacy mode, return system-only message list
        # (The old PROPOSE_USER_TEMPLATE content is now in system message)
        user_msg = ChatMessage(
            role="user", content="Please make your proposal now."
        )
        return [system_msg, user_msg]

    def build_discuss_messages(
        self,
        proposal: Proposal,
        rules: list[Rule],
        game_state: GameState,
        player_name: str,
    ) -> list[ChatMessage]:
        """
        [LEGACY] Build message list for the DISCUSS action.

        Backward compatibility wrapper. Use build_discusser_system_message()
        for stateful contexts.

        Args:
            proposal: The proposal being discussed
            rules: All current rules in the game
            game_state: The current game state
            player_name: The name of the player who is discussing

        Returns:
            A list of ChatMessage objects: [system_message, user_message]
        """
        system_msg = self.build_discusser_system_message(
            proposal=proposal,
            rules=rules,
            game_state=game_state,
            player_name=player_name,
            personality="machiavellian",
        )
        user_msg = ChatMessage(
            role="user", content="Please provide your discussion now."
        )
        return [system_msg, user_msg]

    def build_vote_messages(
        self,
        proposal: Proposal,
        rules: list[Rule],
        game_state: GameState,
        discussions: list[Discussion],
        player_name: str,
    ) -> list[ChatMessage]:
        """
        [LEGACY] Build message list for the VOTE action.

        Backward compatibility wrapper. Use build_discusser_system_message()
        + build_vote_instruction() for stateful contexts.

        Args:
            proposal: The proposal being voted on
            rules: All current rules in the game
            game_state: The current game state
            discussions: List of Discussion objects from all players
            player_name: The name of the player who is voting

        Returns:
            A list of ChatMessage objects: [system_message, user_message]
        """
        # Build system context (as if starting discussion phase)
        system_msg = self.build_discusser_system_message(
            proposal=proposal,
            rules=rules,
            game_state=game_state,
            player_name=player_name,
            personality="machiavellian",
        )
        # Build vote instruction as user message
        user_msg = self.build_vote_instruction(
            proposal=proposal,
            discussions=discussions,
            rules=rules,
            player_name=player_name,
        )
        return [system_msg, user_msg]

    def build_revise_messages(
        self,
        proposal: Proposal,
        discussions: list[Discussion],
        game_state: GameState,
        player_name: str,
    ) -> list[ChatMessage]:
        """
        [LEGACY] Build message list for the REVISE action.

        Backward compatibility wrapper. Use build_proposer_system_message()
        + build_revision_instruction() for stateful contexts.

        Args:
            proposal: The proposal being revised (owned by this player)
            discussions: List of Discussion objects from all players
            game_state: The current game state
            player_name: The name of the player who is revising

        Returns:
            A list of ChatMessage objects: [system_message, user_message]
        """
        # For revise, the player was the proposer, so we need rules
        # But we don't have rules in this signature... Use empty for now
        # This is a limitation of the legacy interface
        persona = self._get_personality_block("machiavellian").format(
            player_name=player_name
        )
        game_state_str = self._format_game_state_block(game_state, player_name)
        proposal_str = (
            f"You proposed: {proposal.type.value} - "
            f"{proposal.new_text or 'N/A'}"
        )
        system_msg = ChatMessage(
            role="system",
            content=f"{persona}\n\n{game_state_str}\n\n{proposal_str}",
        )
        user_msg = self.build_revision_instruction(discussions=discussions)
        return [system_msg, user_msg]
