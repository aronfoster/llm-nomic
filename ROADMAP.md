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

* Implement retry logic for judge scoring so that a response with invalid json will get additional tries
  * Add MAX_SCORE_RETRIES = 2 and MAX_VETO_RETRIES = 2 to LLMJudge
  * Wrap the API calls in the same retry loop pattern from LLMPlayer.vote()
  * Use JUDGE_SCORE_RETRY_TEMPLATE and JUDGE_VETO_RETRY_TEMPLATE in prompts.py
* Judge on lower quality models isn't scoring appropriately. Improve prompt to show vote totals in addition to vote/discussion. Reduce rule list to only those with 'point' or 'score' in them.
* Lower quality LLM players are interpreting turn order as rank in the game. Maybe add some smart text to say "It's a 3-way tie" or "You are in last place by 8 points" or some other set of plain -language descriptions of the score situation since LLMs don't do great at math.
* pylance is giving type errors in vs code that aren't caught by `make ci`

### Low Priority

* None

## Sprint 26-1: Modular Resolution & State Compilation

**Goal:** Refactor the unweildy resolution logic and implement a multi-step "State Compiler" to bridge the gap between natural language rules and engine behavior.

### 1. Core Refactor: Clean Resolution Loop ✅ COMPLETE

* **Task:** Decompose `GameLoop._resolve_turn` into discrete, side-effect-free logical steps.
* **Status:** ✅ COMPLETE
* **Completed Sub-tasks:**
  * ✅ Implemented `_tally_vote_results(votes)`: Returns a pure `VoteResult` data object with counts and pass/fail status.
  * ✅ Implemented `_get_judge_decisions(...)`: Consolidates all Judge-specific output (veto, scores) into a `JudgeDecisions` object.
  * ✅ Implemented `_apply_turn_mutations(results, judge_data)`: A single transactional method for updating files (`game_state.json`, `rules.jsonl`) and incrementing counters.
  * ✅ Added granular `logging.debug` coverage across all sub-functions for high-visibility execution tracking.
  * ✅ Created comprehensive unit tests that verify each new method in isolation.
  * ✅ All tests pass with `make ci`.

### 2. Judge Step 1: State Maintenance Interface

* **Task:** Add `maintain_state(rules, game_state, proposal) -> StateUpdates` to `BaseJudge`.
* **Trigger:** Call this in the new `_get_judge_decisions` step immediately after a proposal passes.
* **Logic:** The Judge should return a **delta only**—returning a `StateUpdates` object only if a rule change necessitates an engine change.
* **Implementations:**
   * **HumanJudge:** Interactive CLI loop displaying current flags/target score and prompting for specific overrides.
   * **LLMJudge:** Prepare the factory to accept the "Game State Compiler" prompt logic.

### 3. Judge Step 2: Game State Compiler (LLM)

* **Task:** Implement the "Compiler" prompt for the `LLMJudge`.
* **Sub-tasks:**
* Define a **Supported Feature Registry** in the prompt (limiting updates to valid flags).
* Implement **Conflict Resolution logic**: Instruct the LLM to use Rule 211 (numerical precedence) for value conflicts - if that rule still exists. Send off the full rule list to the judge if not?
* Add an `error_log` field to `StateUpdates`: Allows the Judge to report rules that are "Impossible to Implement" with current engine flags.

### 5. Smart Player Context (Bug Mitigation)

* **Task:** Add plain-language score/rank descriptions to mitigate LLM math errors.
* **Status:** PLANNED
* **Logic:**
* Modify `PromptBuilder._format_game_state_block` in `src/nomic_engine/llm/prompt_builder.py` to include a "Leaderboard Context" line (e.g., "You are in 2nd place, 5 points behind the leader").
  * Would listing the number of turns each player has had be valuable? Humans understand how going first confers an advantage, and that 

## Future Work

This is the long-term backlog and TODO scratchpad.
  * **Implement Full `LLMPlayer`:**
    * Implement advanced token-saving strategies, especially context caching
    * Implement async behavior
    * Add a "notepad" feature (e.g., a simple file) for LLMs to save plans and opinions of other players between turns.
    * Can we get the "thinking" from thinking llm models? Add that as a new field into the logs and transcript?
    * We need to get token usage/metadata about the queries Answer: How big do context windows need to be? What's the cost/total token usage?
    * Need to handle "revision -> withdraw" logic to have them come up with a new proposal
    * Explore https://openrouter.ai/ support for tokens/models
    * Specify versions for dependencies and start managing those

* **Game State & Rules:**
    * Enhanced Voting Architecture**
        * **Task:** Replace binary vote logic with named "Abstention-Aware" modes.
        * **Data Model:** Expand `VoteMode` enum in `data_models.py` to include `UNANIMOUS_STRICT`, `CONSENSUS`, `MAJORITY_TOTAL`, and `MAJORITY_VOTING`.
        * **Engine Logic:** Update `GameLoop._tally_votes` to implement the specific denominator logic for each named mode.
        * **LLM Awareness:** Update `PromptBuilder` to dynamically inject a plain-language explanation of the current `vote_mode` into player prompts, ensuring players understand the tactical weight of an "ABSTAIN" vote.
    * Allow `create_game.py` to select from multiple initial ruleset files.
    * Allow custom model config per game (e.g., for new/local models not in `models.yml`).
    * Query provider APIs to get a list of available models.

* **Tooling & Features:**
    * Build a `build_site.py` script to convert the game history into a shareable HTML file.
    * Need to shift to a dynamic turn structure where if rules change the turn steps (e.g an additional round of discussion after voting) it can be supported. Might need to ask the judge to define the steps and provide some guidance to the players.

* **Structured Metadata for Victory Rules**
    * The current game creation flow sets `target_score` manually, which works well for now.  
    * In a future iteration, the ruleset should become the authoritative source for victory conditions by allowing **structured metadata** inside `rules.jsonl`.
    * Enable rules (e.g., Rule 208) to embed machine-readable metadata that defines the game’s victory condition.

    **Example (proposed format):**
    ```jsonl
    {"id": 208,
     "title": "Victory",
     "text": "The winner is the first player to reach 100 points.",
     "metadata": {
       "victory_condition": "points",
       "target_score": 100
     }}

* **Dynamic Game Structure**
   * Create "turn structure" game file that defines each step, and can be changed by the judge (maybe players, too, by concensus?). This allows extra steps to be created, or order of steps to be changed.
