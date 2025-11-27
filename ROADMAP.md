# **Project Plan: Nomic LLM Engine**

This document tracks the high-level plan for the `llm-nomic` project.

## Core Principles

Our architecture is built on these principles:

1.  **Security, Structure First:** Having secure code 
2.  **Engine vs. Instance:** The Game Engine is stateless and operates on "Game Instance" directories.
3.  **Authoritative Data:** The Game Instance is the sole authority on game state. `rules.jsonl` and `game_state.json` are the sources of truth.

## Bug List

### HIGH PRIORITY

* Judge on lower quality models isn't scoring appropriately. Improve prompt to show vote totals in addition to vote/discussion. Reduce rule list to only those with 'point' or 'score' in them.
* Lower quality LLM players are interpreting turn order as rank in the game. Maybe add some smart text to say "It's a 3-way tie" or "You are in last place by 8 points" or some other set of plain -language descriptions of the score situation since LLMs don't do great at math.
* pylance is giving type errors in vs code that aren't caught by `make ci`

### Low Priority

* None

## Epic: Game Flags & Dynamic Rules

  * **[Feat] Data Model: Game Flags**
      * Update `GameState` to include a `flags` dictionary.
      * Initialize with default `{"vote_mode": "unanimous"}`.
  * **[Feat] Engine: Dynamic Vote Tallying**
      * Refactor `_tally_votes` in `GameLoop` to check `game_state.flags["vote_mode"]`.
      * Implement logic for "majority" vs "unanimous".
  * **[Feat] Judge: State Maintenance Interface**
      * Add `maintain_state` method to BaseJudge, HumanJudge, and LLMJudge.
      * **Human:** Simple CLI prompt to view/edit flags and target score.
      * **LLM:** New prompt template asking it to synchronize flags with the provided Rules text.
  * **[Feat] Loop: Integration**
      * Call `judge.maintain_state()` in `_resolve_turn` immediately after `_apply_passed_proposal`.

## Future Work

This is the long-term backlog and TODO scratchpad.
  * **Implement Full `LLMPlayer`:**
    * Expand `api_clients.py` to handle cloud providers (Grok, Anthropic) and their respective API keys.
    * Implement advanced token-saving strategies, especially context caching
    * Implement async behavior
    * Add a "notepad" feature (e.g., a simple file) for LLMs to save plans and opinions of other players between turns.
    * Can we get the "thinking" from thinking llm models? Add that as a new field into the logs and transcript?
    * We need to get token usage/metadata about the queries Answer: How big do context windows need to be? What's the cost/total token usage?
    * Need to handle "revision -> withdraw" logic to have them come up with a new proposal
    * Explore https://openrouter.ai/ support for tokens/models

* **Implement Victory Check and Game Flags:**
    * Add a `target_score` to `GameState`.
    * Add a check for this score in the game loop.
    * Create a "change flags" step for the Judge to update `target_score` or other `GameState` flags (e.g., "unanimous vote" vs. "majority vote").
    * Document how victory settings interact with `judge_type` (e.g., human judges can override, LLM judges must follow rule text) and ensure this is reflected in config templates.

* **Game State & Rules:**
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

