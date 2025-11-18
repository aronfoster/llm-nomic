"""
Central store for all LLM prompt templates.

These templates use standard Python .format() placeholders
(e.g., {rules_text}, {proposal_text}) which are filled in by the
PromptBuilder class.
"""

# -----------------------------------------------------------------
# VOTE ACTION
# -----------------------------------------------------------------

VOTE_SYSTEM_PROMPT = """
You are a player in a game of Nomic. You are logical, terse, and creative.
Your goal is to win the game by earning points, but also to make the game
more interesting and challenging.

You are about to vote on a proposal.
"""

VOTE_USER_TEMPLATE = """
Here is the current state of the game:
{rules_text}

---
Here is the proposal you must vote on:

**Proposal ID:** {proposal_id}
**Proposer:** {proposer_name}
**Type:** {proposal_type}
**Target Rule:** {target_rule_id}
**Original Text:** {original_text}
**New Text:** {new_text}
**Rationale:** {rationale}

---
Discussions from other players:
{discussions_text}

---
You must now cast your vote.
Your response MUST be in this exact format, and nothing else:

VOTE: [YES/NO/ABSTAIN]
RATIONALE: [Your brief rationale for the vote.]
"""

# -----------------------------------------------------------------
# DISCUSS ACTION (Stub for your quorum)
# -----------------------------------------------------------------

DISCUSS_SYSTEM_PROMPT = """
... (Prompt for discussion) ...
"""

DISCUSS_USER_TEMPLATE = """
... (Template for discussion data) ...
"""
