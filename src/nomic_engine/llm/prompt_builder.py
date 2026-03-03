"""
PromptBuilder - Factory for creating LLM chat messages from templates.

This class populates the atomized prompt templates in prompts.py with actual
game data, generating incremental context blocks (System or User messages)
for stateful conversation history per player.

Sprint 6 refactor: Methods now return single ChatMessage objects instead of
full message lists, enabling persistent conversation history per player.
"""

import json

from ..data_models import (
    ChatMessage,
    Discussion,
    GameState,
    Proposal,
    Rule,
    Vote,
)
from ..utils.flag_schema import (
    FlagSchemaError,
    format_current_flags,
    format_supported_flags,
)
from . import prompts
from .personality_loader import load_personality, parse_section_fields


class PromptBuilder:
    """Builds LLM chat message context blocks from atomized templates."""

    def _format_rank(self, rank: int) -> str:
        """Format a numeric rank with an ordinal suffix (1st, 2nd, etc)."""
        if 10 <= rank % 100 <= 20:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(rank % 10, "th")
        return f"{rank}{suffix}"

    def _build_leaderboard_context(
        self, game_state: GameState, player_name: str
    ) -> str:
        """Build strategic leaderboard context for player prompts."""
        sorted_players = sorted(
            game_state.scores.items(), key=lambda item: (-item[1], item[0])
        )

        if not sorted_players:
            return (
                "LEADERBOARD CONTEXT:\n"
                "Rank: N/A.\n"
                "Leaderboard: No scores yet.\n"
                "Goal: No target score is configured.\n"
                "Turn Parity: Turn parity unavailable."
            )

        if player_name not in game_state.scores:
            raise ValueError(
                f"Player '{player_name}' not found in scores: "
                f"{sorted(game_state.scores.keys())}"
            )

        score_groups: dict[int, list[str]] = {}
        for name, score in sorted_players:
            score_groups.setdefault(score, []).append(name)

        player_score = game_state.scores[player_name]
        higher_scores = {
            score for score in score_groups if score > player_score
        }
        rank = len(higher_scores) + 1
        tied_players = [
            name
            for name in score_groups[game_state.scores[player_name]]
            if name != player_name
        ]

        rank_text = self._format_rank(rank)
        if tied_players:
            tied_with = ", ".join(tied_players)
            rank_line = f"Rank: {rank_text} (Tied with {tied_with})."
        else:
            rank_line = f"Rank: {rank_text}."

        leaderboard_parts = [
            f"{index}. {name} ({score})"
            for index, (name, score) in enumerate(sorted_players, start=1)
        ]
        leaderboard_line = f"Leaderboard: {', '.join(leaderboard_parts)}."

        if game_state.target_score is None:
            goal_line = "Goal: No target score is configured."
        else:
            points_needed = max(
                0, game_state.target_score - game_state.scores[player_name]
            )
            goal_line = (
                "Goal: "
                f"{points_needed} points required to reach "
                f"the target score of {game_state.target_score}."
            )

        turn_count = len(game_state.turn_order)
        if turn_count == 0:
            parity_line = "Turn Parity: Turn parity unavailable."
        else:
            completed_turns: dict[str, int] = {}
            full_rounds_completed = (game_state.move_number - 1) // turn_count
            position_in_round = (game_state.move_number - 1) % turn_count
            for idx, name in enumerate(game_state.turn_order):
                completed_turns[name] = full_rounds_completed + (
                    1 if idx < position_in_round else 0
                )

            current_turn_number = completed_turns.get(player_name, 0) + 1
            other_turns = [
                f"{name} has completed {completed_turns[name]} turns"
                for name in game_state.turn_order
                if name != player_name
            ]
            player_turn = self._format_rank(current_turn_number)
            parity_line = f"Turn Parity: This is your {player_turn} turn."
            if other_turns:
                parity_line = f"{parity_line} {' '.join(other_turns)}."

        return "\n".join(
            [
                "LEADERBOARD CONTEXT:",
                rank_line,
                leaderboard_line,
                goal_line,
                parity_line,
            ]
        )

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
        Build the persona block for this personality from the loaded file.

        Combines the PERSONA and STRATEGIC_GUIDANCE sections from the
        personality file into a single string.  The ``{player_name}``
        placeholder in PERSONA is left intact; callers must call
        ``.format(player_name=...)`` on the returned string.

        Args:
            personality: Lowercase personality name (e.g. "machiavellian").
                         Must correspond to a file in ``personalities/``.

        Returns:
            Combined PERSONA + STRATEGIC_GUIDANCE string with
            ``{player_name}`` placeholder preserved.

        Raises:
            FileNotFoundError: If the personality file does not exist.
        """
        sections = load_personality(personality.lower())
        persona = sections.get("PERSONA", "")
        guidance = sections.get("STRATEGIC_GUIDANCE", "").strip()
        if guidance:
            return f"{persona}\n\n{guidance}"
        return persona

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
        leaderboard_context = self._build_leaderboard_context(
            game_state, player_name
        )

        return prompts.GAME_STATE_BLOCK.format(
            move_number=game_state.move_number,
            scores_text=scores_text,
            player_position=player_position,
            turn_order=turn_order_str,
            leaderboard_context=leaderboard_context,
        )

    def _build_propose_examples(self, personality: str) -> str:
        """
        Assemble personality-specific JSON examples for the propose phase.

        Loads the four per-case example sections from the personality file,
        extracts prose field values, and assembles one complete JSON object
        per proposal type (ADD, AMEND, REPEAL, TRANSMUTE).

        Args:
            personality: Lowercase personality name (e.g. "machiavellian").

        Returns:
            Multi-line string of JSON objects separated by blank lines.
        """
        sections = load_personality(personality.lower())
        add_f = parse_section_fields(sections.get("PROPOSE_ADD_EXAMPLE", ""))
        amend_f = parse_section_fields(
            sections.get("PROPOSE_AMEND_EXAMPLE", "")
        )
        repeal_f = parse_section_fields(
            sections.get("PROPOSE_REPEAL_EXAMPLE", "")
        )
        transmute_f = parse_section_fields(
            sections.get("PROPOSE_TRANSMUTE_EXAMPLE", "")
        )
        examples = [
            json.dumps(
                {
                    "private_thoughts": add_f.get("private_thoughts", ""),
                    "type": "ADD",
                    "target_rule_id": None,
                    "new_text": add_f.get("new_text", ""),
                    "rationale": add_f.get("rationale", ""),
                },
                indent=2,
            ),
            json.dumps(
                {
                    "private_thoughts": amend_f.get("private_thoughts", ""),
                    "type": "AMEND",
                    "target_rule_id": amend_f.get("target_rule_id", ""),
                    "new_text": amend_f.get("new_text", ""),
                    "rationale": amend_f.get("rationale", ""),
                },
                indent=2,
            ),
            json.dumps(
                {
                    "private_thoughts": repeal_f.get("private_thoughts", ""),
                    "type": "REPEAL",
                    "target_rule_id": repeal_f.get("target_rule_id", ""),
                    "new_text": None,
                    "rationale": repeal_f.get("rationale", ""),
                },
                indent=2,
            ),
            json.dumps(
                {
                    "private_thoughts": transmute_f.get(
                        "private_thoughts", ""
                    ),
                    "type": "TRANSMUTE",
                    "target_rule_id": transmute_f.get("target_rule_id", ""),
                    "new_text": None,
                    "rationale": transmute_f.get("rationale", ""),
                },
                indent=2,
            ),
        ]
        return "\n\n".join(examples)

    def _build_discuss_examples(self, personality: str) -> str:
        """
        Assemble personality-specific JSON examples for the discuss phase.

        Loads the COMMENT and ABSTAIN example sections, extracts prose
        values, and assembles one JSON object per case.

        Args:
            personality: Lowercase personality name (e.g. "machiavellian").

        Returns:
            Multi-line string of JSON objects separated by blank lines.
        """
        sections = load_personality(personality.lower())
        comment_f = parse_section_fields(
            sections.get("DISCUSS_COMMENT_EXAMPLE", "")
        )
        abstain_f = parse_section_fields(
            sections.get("DISCUSS_ABSTAIN_EXAMPLE", "")
        )
        examples = [
            json.dumps(
                {
                    "private_thoughts": comment_f.get("private_thoughts", ""),
                    "discussion_text": comment_f.get("discussion_text", ""),
                },
                indent=2,
            ),
            json.dumps(
                {
                    "private_thoughts": abstain_f.get("private_thoughts", ""),
                    "discussion_text": "",
                },
                indent=2,
            ),
        ]
        return "\n\n".join(examples)

    def _build_revise_examples(self, personality: str) -> str:
        """
        Assemble personality-specific JSON examples for the revise phase.

        Loads the KEEP, MODIFY, and WITHDRAW example sections, extracts
        prose values, and assembles one JSON object per revision action.

        Args:
            personality: Lowercase personality name (e.g. "machiavellian").

        Returns:
            Multi-line string of JSON objects separated by blank lines.
        """
        sections = load_personality(personality.lower())
        keep_f = parse_section_fields(sections.get("REVISE_KEEP_EXAMPLE", ""))
        modify_f = parse_section_fields(
            sections.get("REVISE_MODIFY_EXAMPLE", "")
        )
        withdraw_f = parse_section_fields(
            sections.get("REVISE_WITHDRAW_EXAMPLE", "")
        )
        examples = [
            json.dumps(
                {
                    "private_thoughts": keep_f.get("private_thoughts", ""),
                    "action": "KEEP",
                    "new_text": None,
                    "rationale": None,
                },
                indent=2,
            ),
            json.dumps(
                {
                    "private_thoughts": modify_f.get("private_thoughts", ""),
                    "action": "MODIFY",
                    "new_text": modify_f.get("new_text", ""),
                    "rationale": modify_f.get("rationale", ""),
                },
                indent=2,
            ),
            json.dumps(
                {
                    "private_thoughts": withdraw_f.get("private_thoughts", ""),
                    "action": "WITHDRAW",
                    "new_text": None,
                    "rationale": None,
                },
                indent=2,
            ),
        ]
        return "\n\n".join(examples)

    def _build_vote_examples(
        self, personality: str, allow_abstention: bool = False
    ) -> str:
        """
        Assemble personality-specific JSON examples for the vote phase.

        Loads the YES and NO example sections, extracts prose values, and
        assembles one JSON object per vote outcome. When allow_abstention is
        True and the personality defines a VOTE_ABSTAIN_EXAMPLE section, an
        ABSTAIN example is included as well.

        Args:
            personality: Lowercase personality name (e.g. "machiavellian").
            allow_abstention: When True, include an ABSTAIN example if
                the personality defines one.

        Returns:
            Multi-line string of JSON objects separated by blank lines.
        """
        sections = load_personality(personality.lower())
        yes_f = parse_section_fields(sections.get("VOTE_YES_EXAMPLE", ""))
        no_f = parse_section_fields(sections.get("VOTE_NO_EXAMPLE", ""))
        examples = [
            json.dumps(
                {
                    "private_thoughts": yes_f.get("private_thoughts", ""),
                    "public_reason": yes_f.get("public_reason", ""),
                    "vote": "YES",
                },
                indent=2,
            ),
            json.dumps(
                {
                    "private_thoughts": no_f.get("private_thoughts", ""),
                    "public_reason": no_f.get("public_reason", ""),
                    "vote": "NO",
                },
                indent=2,
            ),
        ]
        if allow_abstention and "VOTE_ABSTAIN_EXAMPLE" in sections:
            abstain_f = parse_section_fields(sections["VOTE_ABSTAIN_EXAMPLE"])
            examples.append(
                json.dumps(
                    {
                        "private_thoughts": abstain_f.get(
                            "private_thoughts", ""
                        ),
                        "public_reason": abstain_f.get("public_reason", ""),
                        "vote": "ABSTAIN",
                    },
                    indent=2,
                )
            )
        return "\n\n".join(examples)

    def build_proposer_system_message(
        self,
        rules: list[Rule],
        game_state: GameState,
        player_name: str,
        personality: str,
        memory_content: str = "",
    ) -> tuple[ChatMessage, ChatMessage]:
        """
        Build the system and user messages for the Proposer at turn start.

        Splits context into two messages so every API call starts with
        [system, user], enabling cache prefix reuse from the first call:
        - system: stable identity and context (persona, game state, rules,
          memory)
        - user: phase-specific instruction (INSTRUCTION_PROPOSE)

        Args:
            rules: All current rules in the game
            game_state: The current game state
            player_name: The name of the player making the proposal
            personality: The persona key ("machiavellian" or "friendly")
            memory_content: Optional memory content to inject. Omitted when
                empty or whitespace.

        Returns:
            A (system_message, user_message) tuple of ChatMessage objects.

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

        # Assemble stable system message (cacheable prefix)
        system_blocks = [persona_block, game_state_block, rules_block]
        if memory_content.strip():
            memory_block = prompts.MEMORY_INJECTION.format(
                full_memory_content=memory_content
            )
            system_blocks.append(memory_block)
        system_content = "\n\n".join(system_blocks)

        # Phase-specific instruction goes in user message
        instruction_block = prompts.INSTRUCTION_PROPOSE.format(
            json_format_enforcement=prompts.JSON_FORMAT_ENFORCEMENT,
            personality_examples=self._build_propose_examples(personality),
        )

        return (
            ChatMessage(role="system", content=system_content),
            ChatMessage(role="user", content=instruction_block),
        )

    def build_discusser_system_message(
        self,
        proposal: Proposal,
        rules: list[Rule],
        game_state: GameState,
        player_name: str,
        personality: str,
        memory_content: str = "",
    ) -> tuple[ChatMessage, ChatMessage]:
        """
        Build the system and user messages for players discussing a proposal.

        Splits context into two messages so every API call starts with
        [system, user], enabling cache prefix reuse from the first call:
        - system: stable identity and context (persona, game state, rules,
          memory)
        - user: phase-specific content (proposal block + INSTRUCTION_DISCUSS)

        Args:
            proposal: The proposal being discussed
            rules: All current rules in the game
            game_state: The current game state
            player_name: The name of the player who is discussing
            personality: The persona key ("machiavellian" or "friendly")
            memory_content: Optional memory content to inject. Omitted when
                empty or whitespace.

        Returns:
            A (system_message, user_message) tuple of ChatMessage objects.

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

        # Assemble stable system message (cacheable prefix)
        system_blocks = [persona_block, game_state_block, rules_block]
        if memory_content.strip():
            memory_block = prompts.MEMORY_INJECTION.format(
                full_memory_content=memory_content
            )
            system_blocks.append(memory_block)
        system_content = "\n\n".join(system_blocks)

        # Phase-specific content (proposal + instruction) goes in user message
        proposal_block = self._format_proposal(proposal, rules, player_name)
        instruction_block = prompts.INSTRUCTION_DISCUSS.format(
            json_format_enforcement=prompts.JSON_FORMAT_ENFORCEMENT,
            personality_examples=self._build_discuss_examples(personality),
        )
        user_content = "\n\n".join([proposal_block, instruction_block])

        return (
            ChatMessage(role="system", content=system_content),
            ChatMessage(role="user", content=user_content),
        )

    def build_revision_instruction(
        self,
        discussions: list[Discussion],
        personality: str = "friendly",
    ) -> ChatMessage:
        """
        Build the user message with discussion feedback for the Proposer.

        Feeds feedback to the Proposer and asks for revision by assembling:
        - DISCUSSION_BLOCK (formatted with the discussions)
        - INSTRUCTION_REVISE (formatted with constraint_message)

        Args:
            discussions: List of Discussion objects from all players
            personality: Lowercase personality name used to inject
                phase-specific revision examples.

        Returns:
            A single ChatMessage with role="user"
        """
        # Format discussions block
        discussions_text = self._format_discussions(discussions)
        discussions_block = prompts.DISCUSSION_BLOCK.format(
            discussions_text=discussions_text
        )

        constraint_message = (
            "You may choose to KEEP, MODIFY, or WITHDRAW based on "
            "your strategy."
        )

        # Format instruction block with personality-specific examples
        instruction_block = prompts.INSTRUCTION_REVISE.format(
            constraint_message=constraint_message,
            json_format_enforcement=prompts.JSON_FORMAT_ENFORCEMENT,
            personality_examples=self._build_revise_examples(personality),
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
        personality: str = "friendly",
        game_state: GameState | None = None,
    ) -> ChatMessage:
        """
        Build the user message presenting the final proposal for voting.

        Presents the final option to all players and asks for a vote by:
        - PROPOSAL_BLOCK (formatted with the revised proposal details)
        - DISCUSSION_BLOCK (formatted with the discussions)
        - INSTRUCTION_VOTE or INSTRUCTION_VOTE_WITH_ABSTAIN depending on
          the allow_abstention flag

        Args:
            proposal: The (potentially revised) proposal being voted on
            discussions: List of Discussion objects from all players
            rules: All current rules (for original text lookup)
            player_name: The name of the player who is voting
            personality: Lowercase personality name used to inject
                phase-specific vote examples.
            game_state: Optional current game state used to read the
                allow_abstention flag. When None, defaults to False.

        Returns:
            A single ChatMessage with role="user"
        """
        allow_abstention: bool = False
        if game_state is not None:
            allow_abstention = bool(
                game_state.flags.get("allow_abstention", False)
            )

        # Format proposal block (with potentially revised proposal)
        proposal_block = self._format_proposal(proposal, rules, player_name)

        # Format discussions block
        discussions_text = self._format_discussions(discussions)
        discussions_block = prompts.DISCUSSION_BLOCK.format(
            discussions_text=discussions_text
        )

        # Select the appropriate vote instruction template
        vote_template = (
            prompts.INSTRUCTION_VOTE_WITH_ABSTAIN
            if allow_abstention
            else prompts.INSTRUCTION_VOTE
        )

        # Format instruction block with personality-specific examples
        instruction_block = vote_template.format(
            json_format_enforcement=prompts.JSON_FORMAT_ENFORCEMENT,
            personality_examples=self._build_vote_examples(
                personality, allow_abstention=allow_abstention
            ),
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

    def build_judge_context_block(
        self,
        rules: list[Rule],
        game_state: GameState,
        proposal: Proposal,
        votes: list[Vote],
        discussions: list[Discussion],
    ) -> str:
        """Return the full turn context for the Judge as a plain string.

        Produces the same content as the removed
        ``build_judge_context_message`` but as a raw string for embedding
        directly in the system message.
        """
        rules_block = prompts.RULES_BLOCK.format(
            rules_text=self._format_rules(rules)
        )
        proposal_block = self._format_proposal(
            proposal, rules, proposal.proposer_name
        )
        discussions_block = prompts.DISCUSSION_BLOCK.format(
            discussions_text=self._format_discussions(discussions)
        )

        if votes:
            vote_lines = []
            for vote in votes:
                reason = vote.reason or "No public reason provided."
                vote_lines.append(
                    f"- {vote.player_name}: {vote.vote} | Reason: {reason}"
                )
            votes_block = "\n".join(vote_lines)
        else:
            votes_block = "No votes recorded."

        scores_block = self._format_scores(game_state.scores)

        return "\n\n".join(
            [
                rules_block,
                proposal_block,
                discussions_block,
                f"=== VOTES ===\n{votes_block}",
                f"=== SCORES ===\n{scores_block}",
            ]
        )

    def build_judge_veto_prompt(
        self, game_state: GameState | None = None
    ) -> ChatMessage:
        """Build the instructions for the Judge veto decision.

        Args:
            game_state: The current game state. When provided, current
                flag values are included in the prompt.
        """
        current_flags = "No flags currently set."
        if game_state is not None:
            current_flags = format_current_flags(game_state.flags)

        try:
            supported_flags = format_supported_flags()
        except FlagSchemaError:
            supported_flags = "Flag schema unavailable."

        content = prompts.JUDGE_VETO_TEMPLATE.format(
            dynamic_current_flags=current_flags,
            dynamic_supported_flags=supported_flags,
            json_format_enforcement=prompts.JSON_FORMAT_ENFORCEMENT,
        )
        return ChatMessage(role="user", content=content)

    def build_judge_score_prompt(self, proposal_passed: bool) -> ChatMessage:
        """
        Build the instructions for Judge score assessment.

        Args:
            proposal_passed: Whether the proposal passed the vote

        Returns:
            ChatMessage with role="user" containing score prompt
        """
        proposal_outcome = "PASSED" if proposal_passed else "FAILED"
        content = prompts.JUDGE_SCORE_TEMPLATE.format(
            proposal_outcome=proposal_outcome,
            json_format_enforcement=prompts.JSON_FORMAT_ENFORCEMENT,
        )
        return ChatMessage(role="user", content=content)

    def build_judge_maintain_state_prompt(
        self,
        proposal: Proposal,
        original_rule_text: str | None,
        new_rule_text: str | None,
        game_state: GameState,
    ) -> ChatMessage:
        """Build the instructions for Judge state maintenance.

        Args:
            proposal: The proposal being applied
            original_rule_text: The text of the rule being changed (None
                for ADD)
            new_rule_text: The new text being added/amended (None for
                REPEAL)
            game_state: The current game state
        """
        # Format rule text sections
        if original_rule_text:
            original_section = f"Original Rule Text: {original_rule_text}"
        else:
            original_section = "Original Rule Text: N/A (new rule)"

        if new_rule_text:
            new_section = f"New Rule Text: {new_rule_text}"
        else:
            new_section = "New Rule Text: N/A (rule being repealed)"

        # Format current state
        current_flags = format_current_flags(game_state.flags)

        try:
            supported_flags = format_supported_flags()
        except FlagSchemaError:
            supported_flags = "Flag schema unavailable."

        content = prompts.JUDGE_MAINTAIN_STATE_TEMPLATE.format(
            proposal_type=proposal.type.value,
            original_rule_section=original_section,
            new_rule_section=new_section,
            current_target_score=game_state.target_score,
            current_flags=current_flags,
            supported_flags=supported_flags,
            json_format_enforcement=prompts.JSON_FORMAT_ENFORCEMENT,
        )
        return ChatMessage(role="user", content=content)
