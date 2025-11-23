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

* Overdue for an update to README.md with instructions to launch the game
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

## Sprint 6: Context-Aware Conversation Architecture

**Goal:** Implement a stateful conversation history per player, per turn. This allows LLMs to "remember" their own previous actions (e.g., "I just proposed this") and reduces token redundancy.

* **Task 1: Atomize Prompt Templates** ✅ COMPLETE
    * Refactored `src/nomic_engine/llm/prompts.py` to break monolithic templates into composable blocks.
    * Added `personality` field to `PlayerConfig` in `data_models.py`.
    * New atomized blocks:
      * `MACHIAVELLIAN_PERSONALITY`: Ruthless, competitive persona.
      * `FRIENDLY_PERSONALITY`: Cooperative, consensus-building persona.
      * `RULES_BLOCK`: Header and placeholder for rules text.
      * `GAME_STATE_BLOCK`: Move number, scores, position, turn order.
      * `PROPOSAL_BLOCK`: Active proposal details.
      * `DISCUSSION_BLOCK`: Peer discussion text.
      * `INSTRUCTION_PROPOSE`: Instructions + JSON format for proposing.
      * `INSTRUCTION_DISCUSS`: Instructions + JSON format for discussing.
      * `INSTRUCTION_REVISE`: Instructions + JSON format for revision (with constraint_message).
      * `INSTRUCTION_VOTE`: Instructions + JSON format for voting.
    * Old templates retained for backward compatibility until Task 2.

* **Task 2: Refactor PromptBuilder for Stateful Context** ✅ COMPLETE
    * Updated `src/nomic_engine/llm/prompt_builder.py` with granular methods.
    * New methods that return single `ChatMessage` context blocks:
      * `build_proposer_system_message()`: System message for proposer with persona, game state, rules, and instructions.
      * `build_discusser_system_message()`: System message for discussers with persona, game state, rules, proposal, and instructions.
      * `build_revision_instruction()`: User message with discussions and revision instructions (preserves Rule 112 constraint).
      * `build_vote_instruction()`: User message with final proposal, discussions, and vote instructions.
    * Added `_format_proposal()` and `_get_personality_block()` helper methods.
    * Legacy wrapper methods maintained for backward compatibility with current LLMPlayer.
    * Comprehensive unit tests with mocking to isolate template dependencies.

* **Task 3: Implement Stateful LLMPlayer** ✅ COMPLETE
    * Updated `src/nomic_engine/players/llm_player.py` to maintain `self.turn_history: list[ChatMessage]`.
    * Implemented `_reset_history(system_message)` helper to clear and initialize history.
    * Refactored `propose()` and `discuss()` to **reset** history (start new turn):
        1.  Build system message using `build_proposer_system_message()` or `build_discusser_system_message()`.
        2.  Call `_reset_history()` with the system message.
        3.  Send `turn_history` to `ApiClient`.
        4.  Append valid response (Assistant message) to history on success.
        5.  Append invalid response + retry instruction on failure.
    * Refactored `revise()` and `vote()` to **extend** history (continue turn):
        1.  Build instruction using `build_revision_instruction()` or `build_vote_instruction()`.
        2.  Append instruction (User message) to existing `turn_history`.
        3.  Send full history to `ApiClient`.
        4.  Append response (Assistant message) to history.
    * Added optional `discussions` parameter to `vote()` for context.
    * Updated unit tests with new PromptBuilder method mocks and history assertions.
    * Added `TestLLMPlayerStatefulHistory` test class with:
        * `test_propose_initializes_history`: Verifies [System, Assistant] after propose.
        * `test_revise_extends_history`: Verifies history grows from [S, A] to [S, A, U, A].
        * `test_vote_extends_history`: Verifies history grows from [S, A] to [S, A, U, A].
        * `test_discuss_initializes_history`: Verifies discuss resets history.
        * `test_propose_resets_existing_history`: Verifies propose resets old history.

* **Task 4: Add Configurable Personality to Game Creation** ✅ COMPLETE
    * Added `PlayerPersonality` enum to `src/nomic_engine/data_models.py`:
      * `MACHIAVELLIAN = "machiavellian"`
      * `FRIENDLY = "friendly"` (default)
    * Updated `PlayerConfig` to use strongly-typed `PlayerPersonality` enum instead of string.
    * Updated `create_game.py` to prompt users for personality selection when configuring LLM players.
    * Updated `LLMPlayer` constructor to accept `personality` parameter.
    * Updated `LLMPlayer.propose()` and `LLMPlayer.discuss()` to use the player's personality.
    * Updated `main.py` to pass personality from `PlayerConfig` to `LLMPlayer`.
    * Added comprehensive unit tests for `PlayerPersonality` enum behavior and validation.

## Future Work

This is the long-term backlog and TODO scratchpad.
  * **Implement Full `LLMPlayer`:**
    * Expand `api_clients.py` to handle cloud providers (Grok, Anthropic) and their respective API keys.
    * Implement advanced token-saving strategies
    * Implement async behavior
    * Add a "notepad" feature (e.g., a simple file) for LLMs to save plans and opinions of other players between turns.
    * Can we get the "thinking" from thinking llm models? Add that as a new field into the logs and transcript?
    * need to handle "revision -> withdraw" logic to have them come up with a new proposal

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
