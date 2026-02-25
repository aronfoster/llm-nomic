"""
LLM Prompt Templates — Nomic V1.2 (February 2026)

Design Decisions & Tradeoffs (DO NOT DELETE THIS COMMENT BLOCK):

1. Strict JSON output
   - Won over XML tags (harder to parse reliably)
   - Won over free text (parsing nightmare)
   - Chosen over XML, VOTE:/RATIONALE, etc. after testing all options
   - Zero regex parsing code. json.loads() either works or it doesn't.

2. KEY ORDERING (CRITICAL)
   - "private_thoughts" MUST come first
   - Forces Chain-of-Thought reasoning before commitment
   - LLMs generate linearly - they can't "think ahead" to later JSON keys

3. AGGRESSIVE FORMAT THREAT
   - Multiple reminders about JSON-only output
   - Threat of ABSTAIN on format failure (psychological pressure)
   - No markdown, no explanations, no "here is my response" preamble
   - Works even on 8B models when threatened properly
   - Engine actually drops everything before the first { and after the last }

4. DUAL REASONING FIELDS
   - private_thoughts: Real strategy (logged for analysis)
   - public_reason: Political theater for other players
   - Mirrors how humans actually play Nomic

5. FEW-SHOT PROMPTING
   - Each instruction template has a {personality_examples} block
   - PromptBuilder fills it with relevant examples from the active personality
   - Examples show personality style, JSON structure, and ordering

"""

# =====================================================================
# PROMPTING CONSTANTS - The aggressive enforcement that actually works
# =====================================================================

JSON_FORMAT_ENFORCEMENT = """
OUTPUT REQUIREMENTS:
1. Your response must be EXACTLY one JSON object
2. Start with { and end with }
3. No text before the {
4. No text after the }
5. No markdown code blocks
6. No \"Here is my response\" or similar preamble
7. If you output anything other than pure JSON, your response is rejected
"""

# -----------------------------------------------------------------
# JUDGE PROMPTS
# -----------------------------------------------------------------

JUDGE_SYSTEM_PROMPT = (
    "You are the impartial Judge of Nomic. You enforce legality, resolve "
    "ambiguities, and award points exactly as written in the current "
    "ruleset. Always respond concisely and follow the required JSON "
    "schemas."
)

JUDGE_VETO_TEMPLATE = """Review the proposal outcome.

Current Engine Configuration:
{dynamic_current_flags}

Supported Engine Capabilities:
{dynamic_supported_flags}

You should veto proposals that require engine capabilities that are not
currently supported.

Respond with EXACTLY one JSON object with these keys IN THIS ORDER:
1. "private_thoughts" (your reasoning for internal logging)
2. "veto" (true if you veto, false if the outcome stands)
3. "reason" (brief public explanation)

{json_format_enforcement}
"""

JUDGE_SCORE_TEMPLATE = """Assign score changes for this move.

The proposal **{proposal_outcome}** the vote.

Base your decision strictly on the current rules and the provided turn
context (proposal, votes, and discussions). If no points should change,
return an empty list for score_adjustments.

SCORING SCOPE: Apply only rules that were in effect before this turn's
proposal. Even if the proposal passed and its text introduces or modifies
a scoring rule, do not apply it to this turn's point calculation; rule
changes take effect on future turns only, never retroactively on the turn
they were adopted.

Example: If the passed proposal states "the proposer of any vote earns 500
bonus points," that rule does NOT award 500 points this turn. Score this
turn as if that rule does not yet exist.

Respond with EXACTLY one JSON object with these keys IN THIS ORDER:
1. "private_thoughts" (concise reasoning for the log)
2. "score_adjustments" (list of objects with keys: player, delta, reason)

Examples:
{{"private_thoughts": "No scoring rule applies.", "score_adjustments": []}}
{{"private_thoughts": "Awarding proposer.", "score_adjustments": [
  {{"player": "Alice", "delta": 2, "reason": "Rule 202 bonus"}},
  {{"player": "Bob", "delta": -1, "reason": "Rule 204 penalty"}}
]}}

{json_format_enforcement}
"""

JUDGE_MAINTAIN_STATE_TEMPLATE = """Review the rule change and determine
if the game engine configuration needs to be updated.

=== RULE CHANGE SUMMARY ===
Proposal Type: {proposal_type}
{original_rule_section}
{new_rule_section}

=== CURRENT ENGINE STATE ===
Target Score: {current_target_score}
Current Flags:
{current_flags}

=== SUPPORTED ENGINE CAPABILITIES ===
{supported_flags}

Your task is to determine if this rule change requires updating the engine
configuration (flags or target_score). Consider:
- Does the new/amended rule define a winning score? Update target_score.
- Does the rule change voting requirements? Update vote_mode flag.
- Does the rule reference engine behavior that maps to a supported flag?

Respond with EXACTLY one JSON object with these keys IN THIS ORDER:
1. "private_thoughts" (your reasoning about whether state changes are needed)
2. "flags" (object with flag name -> new value mappings, or {{}})
3. "target_score" (integer for new target, or null to leave unchanged)

Examples:
{{"private_thoughts": "Rule sets winning score to 100 points.",
  "flags": {{}}, "target_score": 100}}
{{"private_thoughts": "Rule changes voting to majority.",
  "flags": {{"vote_mode": "majority"}}, "target_score": null}}
{{"private_thoughts": "No engine changes needed.",
  "flags": {{}}, "target_score": null}}

IMPORTANT: Only include flags that need to be CHANGED. Return {{}} for flags
if no changes are needed. Return null for target_score if it should remain
unchanged.

{json_format_enforcement}
"""

# -----------------------------------------------------------------
# RETRY TEMPLATES (still in use by LLMPlayer)
# -----------------------------------------------------------------

VOTE_RETRY_TEMPLATE = """Your previous response was not valid JSON.

This is your FINAL attempt. Output ONLY a valid JSON object with these
exact keys in order:
1. "private_thoughts"
2. "public_reason"
3. "vote"

No other text. Just the JSON object:"""

DISCUSS_RETRY_TEMPLATE = """Your previous response was not valid JSON.

This is your FINAL attempt. Output ONLY a valid JSON object with these
exact keys in order:
1. "private_thoughts"
2. "discussion_text"

No other text. Just the JSON object:"""

PROPOSE_RETRY_TEMPLATE = """Your previous response was not valid.

Error: {validation_error}

This is your FINAL attempt. Output ONLY a valid JSON object with these
exact keys in order:
1. "private_thoughts"
2. "type" (one of: "ADD", "AMEND", "REPEAL", "TRANSMUTE")
3. "target_rule_id" (rule ID string or null)
4. "new_text" (rule text string or null)
5. "rationale"

Remember the validation rules:
- ADD: target_rule_id must be null, new_text is required
- AMEND: target_rule_id AND new_text are both required
- REPEAL/TRANSMUTE: target_rule_id is required, new_text must be null

No other text. Just the JSON object:"""

REVISE_RETRY_TEMPLATE = """Your previous response was not valid JSON.

Error: {validation_error}

This is your FINAL attempt. Output ONLY a valid JSON object with these
exact keys in order:
1. "private_thoughts"
2. "action" (one of: "KEEP", "MODIFY", "WITHDRAW")
3. "new_text" (string if modifying rule text, else null)
4. "rationale" (string if modifying rationale, else null)

Remember:
- If action is "MODIFY", at least one of new_text or rationale must be provided
- If action is "KEEP" or "WITHDRAW", both new_text and rationale should be null

No other text. Just the JSON object:"""

JUDGE_VETO_RETRY_TEMPLATE = """Your previous response was not valid JSON.

Error: {validation_error}

This is your FINAL attempt. Output ONLY a valid JSON object with these
exact keys in order:
1. "private_thoughts"
2. "veto" (boolean: true or false)
3. "reason"

No other text. Just the JSON object:"""

JUDGE_SCORE_RETRY_TEMPLATE = """Your previous response was not valid JSON.

Error: {validation_error}

This is your FINAL attempt. Output ONLY a valid JSON object with these
exact keys in order:
1. "private_thoughts"
2. "score_adjustments" (list of objects with keys: player, delta, reason)

Remember:
- score_adjustments must be a list (can be empty [])
- Each adjustment needs: player (string), delta (integer), reason (string)
- Player names must match valid players in the game

No other text. Just the JSON object:"""

JUDGE_MAINTAIN_STATE_RETRY_TEMPLATE = """Your previous response was not valid.

Error: {validation_error}

This is your FINAL attempt. Output ONLY a valid JSON object with these
exact keys in order:
1. "private_thoughts"
2. "flags" (object with flag name -> value mappings, or {{}})
3. "target_score" (integer or null)

Remember:
- flags must be an object/dict (can be empty {{}})
- Only include flags that are changing
- target_score must be null or a positive integer
- Flag names and values must match the supported schema

No other text. Just the JSON object:"""


MEMORY_INJECTION = """\
=== YOUR PRIVATE MEMORY ===
(Read-only this turn. You will update it at the very end.)

{full_memory_content}

=== END YOUR PRIVATE MEMORY ==="""

MEMORY_UPDATE_PROMPT = """\
The turn is now complete. Update your private memory.

Your entire response will be saved verbatim as your new memory file. If it
exceeds the character limit of {character_limit} it will be truncated
automatically.

Write your complete updated memory now. You may restructure, condense,
expand, or rewrite any section however you like. There is no required
format. Start directly with your content."""

WITHDRAWAL_RETRY_TEMPLATE = """Your previous proposal was withdrawn \
after discussion.

WITHDRAWAL ATTEMPT: {withdrawal_attempt} of {max_withdrawal_retries}

Return only valid JSON using the standard proposal schema."""

DISCUSS_PROPOSAL_UPDATED_TEMPLATE = """The proposer has withdrawn \
their previous proposal and submitted a new one.

WITHDRAWAL ATTEMPT: {withdrawal_attempt} of {max_withdrawal_retries}

{proposal_block}

Please provide your discussion on the new proposal above.

{json_format_enforcement}"""

# =====================================================================
# ATOMIZED PROMPT BLOCKS (Sprint 6 - Stateful Context)
# These composable blocks are used by PromptBuilder for stateful contexts.
# =====================================================================

# -----------------------------------------------------------------
# 1. DATA BLOCKS - Placeholders for game context
# -----------------------------------------------------------------

RULES_BLOCK = """=== ALL CURRENT RULES ===
{rules_text}"""

SCORING_RULES_BLOCK = """=== SCORING-RELEVANT RULES ===
{rules_text}"""

GAME_STATE_BLOCK = """=== GAME STATE ===
Move #{move_number}
Scores: {scores_text}
Your position: {player_position}
Turn order: {turn_order}

{leaderboard_context}"""

PROPOSAL_BLOCK = """=== PROPOSAL #{proposal_id} ===
**Proposer:** {proposer_name}
**Type:** {proposal_type}
**Target Rule:** {target_rule_id}
**Original Text:** {original_text}
**New Text:** {new_text}
**Rationale:** {rationale}"""

DISCUSSION_BLOCK = """=== DISCUSSIONS ===
{discussions_text}"""

# -----------------------------------------------------------------
# 2. INSTRUCTION BLOCKS - Action-specific guidance with JSON format
#    Each block has a {personality_examples} placeholder that
#    PromptBuilder fills from the active personality file at call time.
# -----------------------------------------------------------------

INSTRUCTION_PROPOSE = """=== YOUR PROPOSAL ===

You must propose a rule change. Choose one of these proposal types:
- "ADD": Create a new rule (provide new_text, NOT target_rule_id)
- "AMEND": Modify an existing rule (provide target_rule_id AND new_text)
- "REPEAL": Delete an existing rule (provide target_rule_id, NOT new_text)
- "TRANSMUTE": Change rule status mutable/immutable (provide target_rule_id)

You must output EXACTLY one JSON object with these keys IN THIS ORDER:
1. "private_thoughts": Your honest strategic analysis. Why are you making this
   proposal? How does it help you win? What are the risks? (This is private)
2. "type": Exactly one of: "ADD", "AMEND", "REPEAL", or "TRANSMUTE" (uppercase)
3. "target_rule_id": The ID of the rule to affect (e.g., "201") or null for ADD
4. "new_text": The text of the new/amended rule, or null for REPEAL/TRANSMUTE
5. "rationale": Your public explanation to convince other players to vote YES
   (1-3 sentences, be political)

The order matters. Think BEFORE you decide.

{json_format_enforcement}

The following examples illustrate reasoning style and decision-making. Treat
them as models for how to think, not what to propose — the game state will
always differ and better opportunities will exist.

{personality_examples}

CRITICAL VALIDATION RULES:
- ADD: target_rule_id must be null, new_text is required
- AMEND: target_rule_id AND new_text are both required
- REPEAL: target_rule_id is required, new_text must be null
- TRANSMUTE: target_rule_id is required, new_text must be null

Remember: Invalid JSON or invalid proposal logic = automatic rejection.
Output only JSON."""

INSTRUCTION_DISCUSS = """=== YOUR DISCUSSION ===

Provide commentary on the proposal to influence other players' votes in a way
that benefits you. Be strategic about what you reveal and how you frame issues.

You must output EXACTLY one JSON object with these keys IN THIS ORDER:
1. "private_thoughts": Your honest strategic analysis. How does this
   affect your path to victory? What do you want others to think or do?
   (This is private)
2. "discussion_text": Your public comment for other players (1-3 sentences,
   be political). You may leave this as an empty string "" to abstain from
   discussion if you prefer to stay silent.

The order matters. Think BEFORE you write.

{json_format_enforcement}

{personality_examples}

Remember: Invalid JSON = automatic abstention. Output only JSON."""

INSTRUCTION_REVISE = """=== REVISION DECISION ===

{constraint_message}

Based on the feedback, you must decide what to do with your proposal:
- "KEEP": Proceed to vote with the original proposal unchanged
- "MODIFY": Change the proposal text and/or rationale before voting
- "WITHDRAW": Cancel the proposal entirely (no vote will occur)

You must output EXACTLY one JSON object with these keys IN THIS ORDER:
1. "private_thoughts": Your honest strategic analysis. What did you learn from
   the discussions? How do you interpret other players' positions? What is
   your best move here? (This is private)
2. "action": Exactly one of: "KEEP", "MODIFY", or "WITHDRAW" (uppercase)
3. "new_text": If action is "MODIFY" and you want to change the rule text,
   provide the new text here. Otherwise null.
4. "rationale": If action is "MODIFY" and you want to change the rationale,
   provide the new rationale here. Otherwise null.

The order matters. Think BEFORE you decide.

{json_format_enforcement}

{personality_examples}

Remember: Invalid JSON = automatic KEEP. Output only JSON."""

INSTRUCTION_VOTE = """=== YOUR VOTE ===

Cast your vote on this proposal. Consider how it affects your position,
the game balance, and your relationships with other players.

You must output EXACTLY one JSON object with these keys IN THIS ORDER:
1. "private_thoughts": Your honest strategic analysis. How does this
   affect your path to victory? What are others really trying to do? (This
   is private)
2. "public_reason": Your explanation to other players (1-3 sentences,
   be political)
3. "vote": Exactly one of: "YES", "NO", or "ABSTAIN" (uppercase)

The order matters. Think BEFORE you decide.

{json_format_enforcement}

{personality_examples}

Remember: Invalid JSON = automatic ABSTAIN. Output only JSON."""
