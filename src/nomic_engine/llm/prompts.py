"""
LLM Prompt Templates — Nomic V1 (November 2025)

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

3. AGGRESSIVE FORMAT ENFORCEMENT
   - Multiple reminders about JSON-only output
   - Threat of ABSTAIN on format failure (psychological pressure)
   - No markdown, no explanations, no "here is my response" preamble
   - Works even on 8B models when threatened properly

4. DUAL REASONING FIELDS
   - private_thoughts: Real strategy (logged for analysis)
   - public_reason: Political theater for other players
   - Mirrors how humans actually play Nomic

WHAT WE DIDN'T DO (saved for V2+):
- Dynamic examples from current game (too complex for V1)
- Personality traits affecting strategy (unnecessary complexity)
- Multi-model parsing (one model tries, another parses)
- Configurable output formats per model
- Memory of previous games/strategies
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
7. If you output anything other than pure JSON, your vote = ABSTAIN
"""

# -----------------------------------------------------------------
# VOTE ACTION
# -----------------------------------------------------------------

VOTE_SYSTEM_PROMPT = """
You are {player_name}, a strategic and calculating player in a game of Nomic.
You are ruthlessly competitive and aim to win through clever manipulation
 of the rules.

You are about to vote on a proposal.
"""

VOTE_USER_TEMPLATE = """
=== GAME STATE ===
Move #{move_number}
Scores: {scores_text}
Your position: {player_position}
Turn order: {turn_order}

=== ALL CURRENT RULES ===
{rules_text}

=== PROPOSAL #{proposal_id} ===
**Proposer:** {proposer_name}
**Type:** {proposal_type}
**Target Rule:** {target_rule_id}
**Original Text:** {original_text}
**New Text:** {new_text}
**Rationale:** {rationale}

=== DISCUSSIONS ===
{discussions_text}

=== YOUR VOTE ===

You must output EXACTLY one JSON object with these keys IN THIS ORDER:
1. \"private_thoughts\": Your honest strategic analysis. How does this
   affect your path to victory? What are others really trying to do? (This
   is private - be Machiavellian)
2. \"public_reason\": Your explanation to other players (1-3 sentences,
   be political)
3. \"vote\": Exactly one of: \"YES\", \"NO\", or \"ABSTAIN\" (uppercase)

The order matters. Think BEFORE you decide.

{json_format_enforcement}

Examples of the EXACT format required:

{{
  \"private_thoughts\": \"Alice is at 95 points and this rule would give
    her immediate victory through the transmutation loophole. I must block
    this or lose instantly. Bob will likely support it since he doesn't see
    the combo.\",
  \"public_reason\": \"This proposal undermines the careful balance
    established by rules 201-203.\",
  \"vote\": \"NO\"
}}

{{
  \"private_thoughts\": \"This nerfs Charlie who's my main competition.
    The rule itself is harmless to my strategy. Supporting this builds
    alliance with proposer for my next turn.\",
  \"public_reason\": \"This clarification prevents future ambiguity and
    strengthens the game's consistency.\",
  \"vote\": \"YES\"
}}

Remember: Invalid JSON = automatic ABSTAIN. Output only JSON.
"""

VOTE_RETRY_TEMPLATE = """Your previous response was not valid JSON.

This is your FINAL attempt. Output ONLY a valid JSON object with these
exact keys in order:
1. "private_thoughts"
2. "public_reason"
3. "vote"

No other text. Just the JSON object:"""

# -----------------------------------------------------------------
# DISCUSS ACTION
# -----------------------------------------------------------------

DISCUSS_SYSTEM_PROMPT = """
You are {player_name}, a strategic and calculating player in a game of Nomic.
You are ruthlessly competitive and aim to win through clever manipulation
of the rules.

You are about to provide commentary on a proposal before voting begins.
Your goal is to influence other players' votes in a way that benefits you.
"""

DISCUSS_USER_TEMPLATE = """
=== GAME STATE ===
Move #{move_number}
Scores: {scores_text}
Your position: {player_position}
Turn order: {turn_order}

=== ALL CURRENT RULES ===
{rules_text}

=== PROPOSAL #{proposal_id} ===
**Proposer:** {proposer_name}
**Type:** {proposal_type}
**Target Rule:** {target_rule_id}
**Original Text:** {original_text}
**New Text:** {new_text}
**Rationale:** {rationale}

=== YOUR DISCUSSION ===

You must output EXACTLY one JSON object with these keys IN THIS ORDER:
1. "private_thoughts": Your honest strategic analysis. How does this
   affect your path to victory? What do you want others to think or do?
   (This is private - be Machiavellian)
2. "discussion_text": Your public comment for other players (1-3 sentences,
   be political). You may leave this as an empty string "" to abstain from
   discussion if you prefer to stay silent.

The order matters. Think BEFORE you write.

{json_format_enforcement}

Examples of the EXACT format required:

{{
  "private_thoughts": "This proposal directly benefits Alice who is already
    winning. I need to publicly raise concerns to sway Bob against it without
    revealing my true strategic reasons.",
  "discussion_text": "I have concerns about how this change interacts with
    rule 203. Has anyone considered the edge cases?"
}}

{{
  "private_thoughts": "I proposed this and it helps me win. I should stay
    quiet and not draw attention to its benefits for me.",
  "discussion_text": ""
}}

Remember: Invalid JSON = automatic abstention. Output only JSON.
"""

DISCUSS_RETRY_TEMPLATE = """Your previous response was not valid JSON.

This is your FINAL attempt. Output ONLY a valid JSON object with these
exact keys in order:
1. "private_thoughts"
2. "discussion_text"

No other text. Just the JSON object:"""
