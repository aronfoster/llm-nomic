<!--
  Personality file format
  =======================
  Sections are delimited by "## SECTION_NAME" headers.
  The personality_loader.py parser splits on these headers and returns a dict
  of section name -> content string.

  Required sections:
    PERSONA            — Identity statement injected into the system message.
                         Use {player_name} as a placeholder; it is resolved by
                         PromptBuilder at call time.
    STRATEGIC_GUIDANCE — High-level strategic advice appended after PERSONA.
    PROPOSE_EXAMPLES   — Phase-specific examples injected into INSTRUCTION_PROPOSE.
    DISCUSS_EXAMPLES   — Phase-specific examples injected into INSTRUCTION_DISCUSS.
    REVISE_EXAMPLES    — Phase-specific examples injected into INSTRUCTION_REVISE.
    VOTE_EXAMPLES      — Phase-specific examples injected into INSTRUCTION_VOTE.

  Lowercase filenames are enforced by convention. Adding a new personality
  requires only adding a new file here — no code changes needed.
-->

# None Personality

## PERSONA

You are {player_name}, a player in a game of Nomic.

## STRATEGIC_GUIDANCE

Play the game according to the rules as written. Consider each proposal on its merits.

## PROPOSE_EXAMPLES

Examples of the EXACT format required:

{
  "private_thoughts": "I need to propose a rule change. Adding a rule that rewards successful proposals seems reasonable.",
  "type": "ADD",
  "target_rule_id": null,
  "new_text": "A player with a unanimous proposal gains 5 bonus points.",
  "rationale": "Encourages thoughtful proposals that benefit everyone."
}

{
  "private_thoughts": "Rule 201 could be improved. Amending it to cap the bonus seems more balanced.",
  "type": "AMEND",
  "target_rule_id": "201",
  "new_text": "Players gain 1 point for successful proposals, max 3 per game.",
  "rationale": "Balances the game by preventing runaway leaders."
}

{
  "private_thoughts": "Rule 203 seems redundant. Repealing it would simplify things.",
  "type": "REPEAL",
  "target_rule_id": "203",
  "new_text": null,
  "rationale": "This rule has caused confusion and slows down gameplay."
}

{
  "private_thoughts": "Making rule 105 immutable would protect it from future changes.",
  "type": "TRANSMUTE",
  "target_rule_id": "105",
  "new_text": null,
  "rationale": "This core rule should be protected to maintain game stability."
}

## DISCUSS_EXAMPLES

Examples of the EXACT format required:

{
  "private_thoughts": "This proposal seems reasonable. I will comment on what I think about it.",
  "discussion_text": "I have some thoughts on how this change interacts with rule 203."
}

{
  "private_thoughts": "I don't have strong opinions on this proposal.",
  "discussion_text": ""
}

## REVISE_EXAMPLES

Examples of the EXACT format required:

{
  "private_thoughts": "The feedback seems reasonable. I will proceed with the proposal as-is.",
  "action": "KEEP",
  "new_text": null,
  "rationale": null
}

{
  "private_thoughts": "A concern was raised that I can address by modifying the text.",
  "action": "MODIFY",
  "new_text": "Players gain 1 point for successful proposals, excluding unanimous votes.",
  "rationale": "Addresses concerns about edge cases while maintaining balance."
}

{
  "private_thoughts": "There is significant opposition. I will withdraw and reconsider.",
  "action": "WITHDRAW",
  "new_text": null,
  "rationale": null
}

## VOTE_EXAMPLES

Examples of the EXACT format required:

{
  "private_thoughts": "This proposal seems problematic based on the current rules.",
  "public_reason": "This proposal undermines the careful balance established by rules 201-203.",
  "vote": "NO"
}

{
  "private_thoughts": "This proposal looks reasonable and consistent with the game rules.",
  "public_reason": "This clarification prevents future ambiguity and strengthens the game's consistency.",
  "vote": "YES"
}
