# **Project Plan: Nomic LLM Engine**

This document tracks the high-level plan for the `llm-nomic` project.

## Core Principles**

Our architecture is built on these principles:

1.  **Security First:** API keys are loaded *only* from environment variables.
2.  **Engine vs. Instance:** The Game Engine is stateless and operates on "Game Instance" directories.
3.  **Authoritative Data:** The Game Instance is the sole authority on game state. `rules.jsonl` and `game_state.json` are the sources of truth.

## Bug List**

### HIGH PRIORITY

(none)

### Low Priority

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

## Sprint 5: LLM Implementation (MVP) ✅ **COMPLETE**

**Goal:** A local Ollama-powered `LLMPlayer` can successfully receive a proposal and cast a valid `Vote`.

### Completed Tasks
* ✅ **Task 1:** Create `src/nomic_engine/llm/prompts.py` to store prompt templates as string constants.
* ✅ **Task 2:** Create `src/nomic_engine/llm/api_clients.py` and implement a simple client for the local Ollama/OpenAI-compatible endpoint.
* ✅ **Task 3:** Create `src/nomic_engine/llm/prompt_builder.py` with a class that can build the `vote` prompt.
* ✅ **Task 4:** Create `src/nomic_engine/llm/parsers.py` with a function to parse the LLM's text response into a `Vote` object with proper validation and error handling.
* ✅ **Task 5:** Implement the `LLMPlayer.vote()` method with retry logic, wiring together the new `ApiClient`, `PromptBuilder`, and `parsers`.

**Implementation Notes:**
- Parser validates JSON structure, required keys, and vote values (case-insensitive)
- LLMPlayer implements robust retry logic: feeds error messages back to the LLM for up to 2 attempts
- Falls back to ABSTAIN vote if LLM consistently produces invalid output or API fails
- Comprehensive test coverage for both parsers and LLMPlayer voting logic
- All tests pass (`make ci` ✓)

## Future Work

This is the long-term backlog and TODO scratchpad.
  * **Implement Full `LLMPlayer`:**
    * Implement the remaining `LLMPlayer` methods (`propose`, `discuss`, `revise`).
    * Add output for clear status when waiting for LLM response
    * Expand `api_clients.py` to handle cloud providers (Grok, Anthropic) and their respective API keys.
    * Implement advanced token-saving strategies, async behavior
* **Implement Victory Check:**
    * Add a `target_score` to `GameState`.
    * Add a check for this score in the game loop.
    * Create a "change flags" step for the Judge to update `target_score` or other `GameState` flags (e.g., "unanimous vote" vs. "majority vote").
* **LLM as Judge:**
    * Explore replacing the `human_judge.py` logic with an LLM call.
* **Game State & Rules:**
    * Rename `game_log.jsonl` to `game_history.jsonl` to avoid confusion with console logging.
    * Allow `create_game.py` to select from multiple initial ruleset files.
    * Allow custom model config per game (e.g., for new/local models not in `models.yml`).
    * Query provider APIs to get a list of available models.
* **Tooling & Features:**
    * Build a `build_site.py` script to convert `game_history.jsonl` into a shareable HTML file.
    * Add a "notepad" feature (e.g., a simple file) for LLMs to save plans between turns.
