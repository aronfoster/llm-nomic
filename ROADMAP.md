# **Project Plan: Nomic LLM Engine**

This document tracks the high-level plan for the `llm-nomic` project.

## Core Principles**

Our architecture is built on these principles:

1.  **Security First:** API keys are loaded *only* from environment variables.
2.  **Engine vs. Instance:** The Game Engine is stateless and operates on "Game Instance" directories.
3.  **Authoritative Data:** The Game Instance is the sole authority on game state. `rules.jsonl` and `game_state.json` are the sources of truth.

## Bug List**

### HIGH PRIORITY

* pylance is giving type errors in vs code that aren't caught by `make ci`
* Shouldn't need "discussion" from the proposer

### Low Priority

* ~~Overdue for an update to README.md with instructions to launch the game~~ (Completed: added "Running a Turn" instructions)
* I don't like the logging format. Can we simplify or clarify it? Log level should deftinitely be vertically aligned. It's appearing as

  ```
  2025-11-16 08:48:43,457 - __main__ - INFO - Loading game from games/test1
  2025-11-16 08:48:43,458 - src.nomic_engine.game_manager - INFO - Loaded game config with 1 players
  2025-11-16 08:48:43,458 - src.nomic_engine.game_manager - INFO - Loaded game state at move #1
  2025-11-16 08:48:43,458 - src.nomic_engine.game_manager - INFO - Loaded 33 rules
  2025-11-16 08:48:43,458 - __main__ - INFO - Game loaded successfully
  2025-11-16 08:48:43,458 - __main__ - INFO - Instantiated 1 player(s)
  2025-11-16 08:48:43,458 - __main__ - INFO - Starting turn execution
  ```
* `2025-11-16 10:48:30,725 - src.nomic_engine.game_loop - INFO - Completed turn 2` after completing turn 1.
  * Unsure if this is still an issue

## Sprint 7: The Automated Judge & Victory

**Goal:** Replace the hardcoded `human_judge` functions with a flexible `Judge` interface. This allows for an "LLM Judge" that can autonomously arbitrate legality and calculate scores based on the rules *as they existed at the time of the vote*.

* **Task 1: Fix Scoring Order (Rule 205 Compliance)** ✅
    * **Bug:** Currently, `_resolve_turn` applies the proposal *before* calculating scores. This violates Rule 205 ("rule-change takes full effect at the moment of the completion of the vote").
    * **Fix:** Refactor `_resolve_turn` in `src/nomic_engine/core/game_loop.py` to call `judge.calculate_scores()` **before** calling `_apply_passed_proposal()`.
    * **Requirement:** The Judge must evaluate the turn using the *pre-modification* ruleset.

* **Task 2: Implement Judge Configuration** ✅
    * **Delivered:** Added `JudgeType` to `GameConfig`, captured judge type/model during game creation, and threaded the selected judge into `GameLoop` via `main.py`.
    * **Notes:** Game creation now validates judge input and stores the LLM model definition when applicable.

* **Task 3: Refactor Judge Architecture (Strategy Pattern)** ✅
    * **Delivered:** Added `BaseJudge` interface with veto and scoring hooks, refactored human judge logic into a `HumanJudge` strategy, and updated `GameLoop` to depend on the strategy abstraction.
    * **Additional Detail:** Game instantiation now constructs the appropriate judge strategy from the stored configuration, preparing the engine for interchangeable human/LLM judges.

* **Task 4: Implement `LLMJudge`** ✅
    * **Delivered:** Added `LLMJudge` strategy wired to the configured judge model, with strict JSON prompts for veto and scoring.
    * **Details:** Judge now uses the shared `PromptBuilder`/`ApiClient`, validates schema rigorously, and applies score adjustments to game state.

* **Task 5: Implement Victory Conditions**
    * **Update `BaseJudge`**: Add `check_victory(game_state, rules) -> str | None`.
    * **Update `GameLoop`**: Call `check_victory` at the end of `_resolve_turn`.
    * **Logic**: Judge reads Rule 208 (or current winning condition) and checks if any player meets it.
    * **Additional Detail:** Persist victory announcements to `game_log.jsonl` and halt further turn processing when a winner is returned.

## Future Work

This is the long-term backlog and TODO scratchpad.
  * **Implement Full `LLMPlayer`:**
    * Expand `api_clients.py` to handle cloud providers (Grok, Anthropic) and their respective API keys.
    * Implement advanced token-saving strategies
    * Implement async behavior
    * Add a "notepad" feature (e.g., a simple file) for LLMs to save plans and opinions of other players between turns.
    * Can we get the "thinking" from thinking llm models? Add that as a new field into the logs and transcript?
    * need to handle "revision -> withdraw" logic to have them come up with a new proposal
    * Explore https://openrouter.ai/ support for tokens/models

* **Implement Victory Check:**
    * Add a `target_score` to `GameState`.
    * Add a check for this score in the game loop.
    * Create a "change flags" step for the Judge to update `target_score` or other `GameState` flags (e.g., "unanimous vote" vs. "majority vote").
    * Document how victory settings interact with `judge_type` (e.g., human judges can override, LLM judges must follow rule text) and ensure this is reflected in config templates.

* **Game State & Rules:**
    * Rename `game_log.jsonl` to `game_history.jsonl` to avoid confusion with console logging.
    * Allow `create_game.py` to select from multiple initial ruleset files.
    * Allow custom model config per game (e.g., for new/local models not in `models.yml`).
    * Query provider APIs to get a list of available models.

* **Tooling & Features:**
    * Build a `build_site.py` script to convert `game_history.jsonl` into a shareable HTML file.
