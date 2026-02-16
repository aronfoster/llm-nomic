# **Project Plan: Nomic LLM Engine**

This document tracks the high-level plan for the `llm-nomic` project.

## Core Principles

Our architecture is built on these principles:

1.  **Security, Structure First:** Having secure, clean (Uncle Bob) code 
2.  **Engine vs. Instance:** The Game Engine is stateless and operates on "Game Instance" directories.
3.  **Authoritative Data:** The Game Instance is the sole authority on game state. `rules.jsonl` and `game_state.json` are the sources of truth.
4.  **Stand alone PRs:** All PRs are small enough to understand, `make ci` passes, and contain unit tests that cover new code

## Bug List Game Engine

### HIGH PRIORITY

* Judge on lower quality models isn't scoring appropriately. Improve prompt to show vote totals in addition to vote/discussion. Reduce rule list to only those with 'point' or 'score' in them. Add a clear description of whether the vote passes or fails.
* Lower quality LLM players are interpreting turn order as rank in the game. Maybe add some smart text to say "It's a 3-way tie" or "You are in last place by 8 points" or some other set of plain-language descriptions of the score situation since LLMs don't do great at math.
* Proposals that pass but that are judge vetoed should still award points as if they passed; the rule change just doesn't get applied to the rule list.
  * NOTE (code review): The engine logic may actually be correct here — `assess_scores` runs independently of veto status. The bug is likely in the judge *prompt* rather than the engine: the LLM judge sees the veto and decides not to award points. Verify with a test case targeting this scenario.
* After game victory, running another turn should immediately exit rather than running another turn.
* The game does not automatically switch from unanimous to majority after 2 complete cycles (from base rules)
* I do not believe a revision can correctly change type (e.g. TRANSMUTE to AMEND)

### Low Priority

* Allow numbers or text (e.g. 2 or llm) in each prompt of create_game.py
* Print the command to run the game after create_game.py
* Fix markdown at the start of game transcript md (the first section is all bunched together)
* Final text has the wrong turn number 
* Add the model and personality to each player as a label when their turn is on the screen (Deepti (Machiavellian/Deepseek) is thinking...)

## Sprint 28: Withdrawal Improvement

**Goal:** Implement dynamic withdrawal logic

### 1. Centralized Engine Tuning (Configuration Refactor)

* ✅ **Completed**: Retry constants are now centralized in `GameConfig.tuning` for single-point tuning via `config.yml`.
* **Implemented**:
  * Added `EngineTuningConfig` in `src/nomic_engine/data_models.py` with:
    * `max_propose_retries`
    * `max_discuss_retries`
    * `max_revise_retries`
    * `max_vote_retries`
    * `max_judge_veto_retries`
    * `max_judge_score_retries`
    * `max_judge_maintain_state_retries`
  * Refactored `LLMPlayer` and `LLMJudge` to consume tuning values from `GameConfig` instead of class-level hardcoded constants.
  * Wired `main.py` instantiation so player/judge objects receive `game_manager.game_config.tuning`.


### 2. Dynamic Withdrawal & Cumulative Pivot Logic

* ✅ **Completed**: Dynamic withdrawal handling now supports policy-driven forfeit/retry behavior with cumulative pivot context.
* **Implemented**:
  * Added `withdrawal_policy` (`forfeit` or `retry`) and `max_withdrawal_retries` (default `2`) to `GameConfig`.
  * Updated `GameLoop.run_turn()` to wrap Steps 1-3 in a withdrawal retry loop.
  * Enforced rotation fix: withdrawn proposals now explicitly advance turn state and persist `game_state` when policy is `FORFEIT` or retry budget is exhausted.
  * Added cumulative-context pivot hook (`note_withdrawal_for_retry`) so LLM players preserve full `turn_history` across retries and append a targeted pivot prompt instead of resetting proposal context.
  * Added/updated unit tests for forfeit behavior, retry pivots, retry exhaustion, and new config fields.


* **Example 1: The Forfeit (Move 15, current player ChatGPT 5.2)**
* **Action**: ChatGPT 5.2 withdraws proposal. Policy is `FORFEIT`.
* **Result**: Turn ends. `move_number` increments to 16. `current_player_name` advances to Gemini 2.0.


* **Example 2: The Pivot (Move 15, current player Gemini 2.0)**
* **Action**: Gemini 2.0 withdraws. Policy is `RETRY`.
* **Result**: Engine restarts Step 1. Gemini 2.0 receives a prompt appended to its existing history similar to: *"Your previous proposal was withdrawn. Based on the discussions above, please propose a different rule change."*.



### Integration Note for Developer

The preservation of context is critical for cost-efficiency. Since the application currently runs as a single turn execution, ensure that the `turn_history` list is maintained across the retry loop iterations within `run_turn` and passed back into the `propose` method if a pivot is triggered.

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
    * Need to shift to a dynamic turn structure where if rules change the turn steps (e.g an additional round of discussion after voting) it can be supported. Might need to ask the judge to define the steps and provide some guidance to the players.
    * Specify versions for dependencies and start managing those (pin at least major versions in `requirements.txt` to prevent breakage from upstream changes)
    * Prompt examples should draw from personality files!

* **Dynamic Game Structure**
   * Create "turn structure" game file that defines each step, and can be changed by the judge (maybe players, too, by consensus?). This allows extra steps to be created, or order of steps to be changed.

### Visualization (Web app)

* Plan out a end state for visualizing individual game, all games, rules, profiles for player (slice by model and personality), leaaderboard
* Have badges or awards for players (models)
* Maybe: Build a `build_site.py` script to convert the game history into a shareable HTML file.

### Graphical UI

* Have a GUI for running the game in Electron (?)


