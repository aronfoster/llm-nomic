# **Project Plan: Nomic LLM Engine**

This document tracks the high-level plan for the `llm-nomic` project.

## Core Principles**

Our architecture is built on these principles:

1.  **Security First:** API keys are loaded *only* from environment variables.
2.  **Engine vs. Instance:** The Game Engine is stateless and operates on "Game Instance" directories.
3.  **Authoritative Data:** The Game Instance is the sole authority on game state. `rules.jsonl` and `game_state.json` are the sources of truth.

## Bug List**

### HIGH PRIORITY

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

* **Task 1: Atomize Prompt Templates**
    * Refactor `src/nomic_engine/llm/prompts.py` to break monolithic templates into composable blocks (e.g. Persona, Game State, Rules, Action Instructions).
      * **Requirement:** We need to break these into composable "atoms" so we can mix and match them to build the initial context and subsequent updates.
      * Keep `JSON_FORMAT_ENFORCEMENT`
      * `MACHIAVELLIAN_PERSONALITY`: Introduction of game, player, personality (from existing text)
      * `FRIENDLY_PERSONALITY`: Introduction of game, player, personality (for a more friendly player)
        * This may also require adding a personality type to PlayerConfig, or we could default to one of them
      * `RULES_BLOCK`: The formatting for rules.
      * `GAME_STATE_BLOCK`: Scores, Turn Order, Position.
      * `PROPOSAL_BLOCK`: rule under discussion
      * `DISCUSSION_BLOCK`: Responses from other players
      * `INSTRUCTION_PROPOSE`: Specific instructions & examples for proposing.
      * `INSTRUCTION_DISCUSS`: Specific instructions & examples for discussing.
      * `INSTRUCTION_REVISE`: Specific instructions & examples for revision.
      * `INSTRUCTION_VOTE`: Specific instructions & examples for voting.

* **Task 2: Refactor PromptBuilder for Stateful Context**
    * Update `src/nomic_engine/llm/prompt_builder.py`.
    * Create `build_propose_context(...)` to generate the starting system prompt for the proposer's turn.
    * Create `build_discuss_context(...)` to generate the starting system prompt for non-proposer's turn.
    * Create `build_revision_context(...)` to generate the user prompt containing discussion from other players plus instructions_revise
    * Create `build_vote_context(...)` to generate the user prompt containing discussion from other players, revised rule proposal, and instruction_vote

* **Task 3: Implement Stateful LLMPlayer**
    * Update `src/nomic_engine/players/llm_player.py` to maintain `self.turn_history: list[ChatMessage]`.
    * Implement `_add_message(role, content)` helper.
    * Refactor `propose`, `discuss`, `revise`, and `vote` to:
        1.  Check if history exists; if not, build initial context.
        2.  If history exists, append the new instruction (User message).
        3.  Send full history to `ApiClient`.
        4.  Append response (Assistant message) to history.
    * Ensure history is cleared at the start of a new turn.

## Future Work

This is the long-term backlog and TODO scratchpad.
  * **Implement Full `LLMPlayer`:**
    * Expand `api_clients.py` to handle cloud providers (Grok, Anthropic) and their respective API keys.
    * Implement advanced token-saving strategies
    * Implement async behavior
    * Add a "notepad" feature (e.g., a simple file) for LLMs to save plans and opinions of other players between turns.
    * Can we get the "thinking" from thinking llm models? Add that as a new field into the logs and transcript?
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
