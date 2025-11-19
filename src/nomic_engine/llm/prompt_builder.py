"""
PromptBuilder - Factory for creating LLM chat messages from templates.

This class populates the prompt templates in prompts.py with actual
game data, calculating derived fields like player position and
formatting complex data structures.
"""

from ..data_models import ChatMessage, GameState, Proposal, Rule
from . import prompts


class PromptBuilder:
    """Builds LLM chat message lists by populating templates."""

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

    def _format_discussions(self, discussions: list[tuple[str, str]]) -> str:
        """
        Format discussion messages into a readable conversation.

        Args:
            discussions: List of (player_name, message) tuples

        Returns:
            Formatted string with each discussion message
            Example: "**Alice:** I think this is a good idea."
        """
        if not discussions:
            return "No discussions yet."

        formatted_lines = []
        for player_name, message in discussions:
            formatted_lines.append(f"**{player_name}:** {message}")

        return "\n".join(formatted_lines)

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

    def build_vote_messages(
        self,
        proposal: Proposal,
        rules: list[Rule],
        game_state: GameState,
        discussions: list[tuple[str, str]],
        player_name: str,
    ) -> list[ChatMessage]:
        """
        Build the complete chat message list for the VOTE action.

        This method populates the VOTE_SYSTEM_PROMPT and VOTE_USER_TEMPLATE
        with all necessary game data, including calculating derived fields.

        Args:
            proposal: The proposal being voted on
            rules: All current rules in the game
            game_state: The current game state
            discussions: List of (player_name, message) tuples
            player_name: The name of the player who is voting

        Returns:
            A list of ChatMessage objects: [system_message, user_message]

        Raises:
            ValueError: If player_name is not in turn_order
            KeyError: If template placeholders are missing
        """
        # Prepare formatted data
        scores_text = self._format_scores(game_state.scores)
        rules_text = self._format_rules(rules)
        discussions_text = self._format_discussions(discussions)
        player_position = self._get_player_position(player_name, game_state)
        turn_order_str = ", ".join(game_state.turn_order)

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

        # Format the system prompt
        system_prompt_str = prompts.VOTE_SYSTEM_PROMPT.format(
            player_name=player_name
        )

        # Format the user prompt with ALL required placeholders
        user_prompt_str = prompts.VOTE_USER_TEMPLATE.format(
            move_number=game_state.move_number,
            scores_text=scores_text,
            player_position=player_position,
            turn_order=turn_order_str,
            rules_text=rules_text,
            proposal_id=proposal.proposal_id or "Unknown",
            proposer_name=proposal.proposer_name,
            proposal_type=proposal.type.value,  # Use the enum value
            target_rule_id=target_rule_id,
            original_text=original_text,
            new_text=new_text,
            rationale=rationale,
            discussions_text=discussions_text,
            json_format_enforcement=prompts.JSON_FORMAT_ENFORCEMENT,
        )

        # Return the message list
        return [
            ChatMessage(role="system", content=system_prompt_str),
            ChatMessage(role="user", content=user_prompt_str),
        ]
