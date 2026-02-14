# **Project Plan: Nomic LLM Engine**

This document tracks the high-level plan for the `llm-nomic` project.

## Core Principles

Our architecture is built on these principles:

1.  **Security, Structure First:** Having secure, clean (Uncle Bob) code 
2.  **Engine vs. Instance:** The Game Engine is stateless and operates on "Game Instance" directories.
3.  **Authoritative Data:** The Game Instance is the sole authority on game state. `rules.jsonl` and `game_state.json` are the sources of truth.
4.  **Stand alone PRs:** All PRs are small enough to understand, `make ci` passes, and contain unit tests that cover new code

## Bug List

### HIGH PRIORITY

* Judge on lower quality models isn't scoring appropriately. Improve prompt to show vote totals in addition to vote/discussion. Reduce rule list to only those with 'point' or 'score' in them.
  * TODO: check if this is still an issue
* Lower quality LLM players are interpreting turn order as rank in the game. Maybe add some smart text to say "It's a 3-way tie" or "You are in last place by 8 points" or some other set of plain-language descriptions of the score situation since LLMs don't do great at math.
* Proposals that pass but that are judge vetoed should still award points as if they passed; the rule change just doesn't get applied to the rule list.
  * NOTE (code review): The engine logic may actually be correct here — `assess_scores` runs independently of veto status. The bug is likely in the judge *prompt* rather than the engine: the LLM judge sees the veto and decides not to award points. Verify with a test case targeting this scenario.
* After game victory, running another turn should immediately exit rather than running another turn.

### Low Priority

* None

## Sprint 27: Code Review Bugfixes & Hardening

**Goal:** Fix correctness bugs and type safety issues identified during code review. Clean up dead code.

### 1. Centralize State Mutations & Fix Proposal ID Tracking

* **Task:** Refactor `GameLoop._apply_turn_mutations` to be the exclusive point of state modification and fix the non-sequential Proposal ID bug. This involves decoupling the scoring logic from the Judge and ensuring compliance with Rule 108.
* **Status:** ✅ Completed
* **Current behavior:** * `next_proposal_id` only increments if a proposal is adopted, which violates Rule 108 ("each rule-change... shall receive the next successive integer, whether or not the proposal is adopted").
* `LLMJudge.assess_scores` directly mutates `game_manager.game_state.scores`, creating a hidden side effect and a dependency where `_detect_victory` only works because the Judge already changed the state.


* **Fix:**
* **Unconditional ID Increment:** Move the `next_proposal_id += 1` logic in `src/nomic_engine/core/game_loop.py` outside the `judge_approved` conditional so it fires for all valid proposals.
* **Score Decoupling:** Update the `BaseJudge.assess_scores` interface in `src/nomic_engine/judge/base_judge.py` to be side-effect-free. It should only return a `JudgeScoreResponse` containing the intended deltas.
* **State Committer Pattern:** Modify `_apply_turn_mutations` to take the deltas from the Judge's response and apply them to `game_state.scores` directly.
* **Strict Typing:** Replace `Any` types in the `JudgeDecisions` and `JudgeScoreResponse` models within `src/nomic_engine/data_models.py` with the specific TypedDict shapes defined in the base judge class.


* **Tests:** * Add test cases verifying `next_proposal_id` increments for failed votes and vetoed proposals.
* Add unit tests for `_apply_turn_mutations` to ensure scores are updated correctly based on Judge-provided deltas.
* Verify that `_detect_victory` correctly identifies a winner after the engine (not the Judge) updates the scores.

### 2. Type `JudgeDecisions` Fields Properly

* **Task:** `JudgeDecisions.veto_response` and `score_response` are typed as `Any` despite having well-defined TypedDict shapes (`JudgeVetoResponse` and `JudgeScoreResponse`).
* **Status:** ✅ Completed
* **Fix:** Replace `Any` with the proper TypedDict types. Remove `ConfigDict(arbitrary_types_allowed=True)` once `Any` is gone.
* **Tests:** Existing tests should continue to pass; mypy will now catch misuse.

### 3. Remove Unreachable Code in `run_turn`

* **Task:** `GameLoop.run_turn()` has an unreachable `return False` after the try/except block. Every path through the try already returns, and the except re-raises.
* **Status:** ✅ Completed
* **Fix:** Delete the dead `return False`.

### 4. Clean Up Empty / Dead Files

* **Task:** Remove empty placeholder files that are no longer needed:
  * `src/nomic_engine/utils/api_clients.py` (empty — logic lives in `llm/api_clients.py`)
  * `src/nomic_engine/utils/prompt_builder.py` (empty — logic lives in `llm/prompt_builder.py`)
* **Status:** ✅ Completed
* **Fix:** Deleted the files, verified no imports reference them, and ran `make ci`.

### 5. Fix Prompt Inconsistencies

* **Task:** Two minor prompt issues that can confuse LLMs:
  1. `JSON_FORMAT_ENFORCEMENT` threatens "your vote = ABSTAIN" but this text is injected into proposal, discussion, and revision contexts where ABSTAIN doesn't apply. Make the threat text generic or context-specific.
  2. Proposal examples in `INSTRUCTION_PROPOSE` use multi-line strings inside JSON values (literal newlines). Some models produce invalid JSON with actual newline characters. Switch examples to single-line values.
* **Status:** ✅ Completed
* **Fix:** Updated `prompts.py` templates with generic rejection text and single-line JSON example values.
* **Tests:** Verified via `make ci`.

### 6. Fix Duplicate Step Comments in Parsers

* **Task:** Several parser functions in `llm/parsers.py` have duplicate `# Step 2` comments from copy-paste drift (e.g., `parse_vote_response`, `parse_discussion_response`, `parse_proposal_response`).
* **Status:** ✅ Completed
* **Fix:** Renumbered parser step comments sequentially.

### 7. Add Fallback Logging in `data_models._get_schema_defaults`

* **Task:** If `flag_schema.json` is broken or missing, `_get_schema_defaults()` silently falls back to a hardcoded dict with no logging.
* **Status:** ✅ Completed
* **Fix:** Added a `logging.warning()` in the except branch so silent schema failures are visible in logs.

This task for the `ROADMAP.md` formalizes the implementation of a dedicated score assessment method within the `PromptBuilder` to improve LLM strategic reasoning.

### 8. Smart Player Context (Strategic standing Assessment)

* **Goal:** Mitigate LLM math errors and "temporal confusion" (first-mover advantage) by providing a plain-language strategic summary of the leaderboard.
* **Status:** ✅ Completed
* **Implementation:** Create a dedicated method `PromptBuilder._build_leaderboard_context()` in `src/nomic_engine/llm/prompt_builder.py`.
* **Logic Requirements:**
* **Rank & Tie Detection:** Identify the player's current rank. Explicitly state if they are in a tie and with whom.
* **Full Leaderboard Display:** Generate a list of all players and their current scores in descending order.
* **Proximity to Victory:** Calculate the points remaining until the `target_score` is reached, or a note that there is no target score if it is null.
* **Turn Parity Calculation:** Use the `move_number` and `turn_order` length to determine how many turns the current player has completed versus the other okayers.

* **Integration:** Inject the resulting string into the `GAME_STATE` block of the player's prompt.
* **Fix:** Added `_build_leaderboard_context()` and `_format_rank()` to generate rank/tie detection, sorted leaderboard text, target-score proximity messaging, and turn parity based on `move_number` + `turn_order`. Updated `GAME_STATE_BLOCK` to include this strategic context.
* **Tests:** Added PromptBuilder unit tests for leaderboard context content (ranking, ties, goal messaging, turn parity) and verified prompt game-state integration. Confirmed via `make ci`.

#### Example 1:

> **LEADERBOARD CONTEXT:**
> **Rank:** 3rd.
> **Leaderboard:** 1. Claude (45), 2. Gemini (42), 3. GPT-4o (38).
> **Goal:** 12 points required to reach the target score of 50.
> **Turn Parity:** This is your 4th turn. Claude has completed 4 turns. Gemini has completed 4 turns.

#### Example 2:

> **LEADERBOARD CONTEXT:**
> **Rank:** 1st (Tied with Gemini).
> **Leaderboard:** 1. Claude (48), 2. Gemini (48), 3. GPT-4o (40).
> **Goal:** 52 points required to reach the target score of 100.
> **Turn Parity:** This is your 5th turn. Gemini has completed 5 turns. GPT-4o has completed 4 turns.

## Future Work

This is the long-term backlog and TODO scratchpad.

### Refactoring (from code review)

* **Decompose `_apply_turn_mutations`:**
  * This method handles rule application, state maintenance, proposal ID tracking, victory detection, turn advancement, transcript logging, and game-over logging — all in ~80 lines.
  * Extract rule application + state maintenance into a private `_apply_rule_changes` method.
  * Extract transcript logging + save into a dedicated method (partially done already with `_log_and_save_turn`).
  * The guiding principle ("only method with side effects") is good, but it should orchestrate discrete sub-steps rather than implement them inline.

* **Provider Factory Pattern for `ApiClient`:**
  * The constructor is a long if/elif chain that will grow with every new provider. Each branch does nearly identical work: check env key, get API key, create client.
  * Refactor to a registry or factory pattern (even a dict mapping provider names to initialization callables). This also makes adding OpenRouter support cleaner.

* **Validate API Keys at Startup:**
  * Currently, missing API keys aren't discovered until a player's first turn — potentially hours into a game with multiple providers.
  * Add a validation step in `create_game.py` or at `main.py` startup that checks all required env vars for configured players and the judge before gameplay begins.

* **Decouple Score Mutation from Judge Methods:** - Integrated into Sprint 27 task 1.
  * `LLMJudge.assess_scores` directly mutates `game_manager.game_state.scores`. This creates a hidden dependency: `_detect_victory` only works correctly because the judge's side effect already happened.
  * Consider having the judge *return* score deltas, with `_apply_turn_mutations` being the sole method that writes to game state. This matches the existing architecture's intent.

* **Parser Return Types:**
  * Several parsers (e.g., `parse_proposal_response`) declare return types like `dict[str, str | None]` but actually return values that include booleans, ints, etc.
  * Replace with proper TypedDicts or dataclasses for each response shape.

### Engine Features

* **Improve `LLMPlayer`:**
  * Implement advanced token-saving strategies, especially context caching
  * Implement async behavior (per model provider?)
  * Add a "notepad" feature (e.g., a simple file) for LLMs to save plans and opinions of other players between turns.
  * Can we get the "thinking" from thinking llm models? Add that as a new field into the logs and transcript?
  * We need to get token usage/metadata about the queries Answer: How big do context windows need to be? What's the cost/total token usage?
  * Need to handle "revision -> withdraw" logic
    * Do we move to the next player when a proposal is withdrawn, or let them propose a new one?
  * Explore https://openrouter.ai/ support for tokens/models

* **Rate Limiting & Cost Tracking:**
  * Each turn can generate 20+ API calls when retries are involved (propose + discuss × N + revise + vote × N + judge veto + judge score + judge maintain_state, each with up to 2 retries).
  * Add per-turn and per-game token/cost tracking. Log token counts from API responses. Consider adding configurable per-turn cost limits.
  
* **Game State & Rules:**
    * Enhanced Voting Architecture
        * **Task:** Replace binary vote logic with named "Abstention-Aware" modes.
        * **Data Model:** Expand `VoteMode` enum in `data_models.py` to include `UNANIMOUS_STRICT`, `CONSENSUS`, `MAJORITY_TOTAL`, and `MAJORITY_VOTING`.
        * **Engine Logic:** Update `GameLoop._tally_votes` to implement the specific denominator logic for each named mode.
        * **LLM Awareness:** Update `PromptBuilder` to dynamically inject a plain-language explanation of the current `vote_mode` into player prompts, ensuring players understand the tactical weight of an "ABSTAIN" vote.
    * Allow `create_game.py` to select from multiple initial ruleset files.
    * Allow custom model config per game (e.g., for new/local models not in `models.yml`).
    * Query provider APIs to get a list of available models.
    * **Rule 111 Word Limit Enforcement:** Rule 111 caps discussion comments at 75 words, but the engine doesn't validate this. Decide whether to enforce in the engine (truncate/reject) or in the prompt (and accept the risk of LLM non-compliance). Document the decision either way.

* **Tooling & Features:**
    * Build a `build_site.py` script to convert the game history into a shareable HTML file.
    * Need to shift to a dynamic turn structure where if rules change the turn steps (e.g an additional round of discussion after voting) it can be supported. Might need to ask the judge to define the steps and provide some guidance to the players.
    * Specify versions for dependencies and start managing those (pin at least major versions in `requirements.txt` to prevent breakage from upstream changes)
    * Prompt examples should draw from personality files!

* **Dynamic Game Structure**
   * Create "turn structure" game file that defines each step, and can be changed by the judge (maybe players, too, by consensus?). This allows extra steps to be created, or order of steps to be changed.
