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

## **Sprint 26-1: Multi-Model Expansion & Dynamic Resolution**

**Goal:** Finalize core engine flexibility and expand LLM connectivity to include major cloud providers.

### **1. Cloud LLM Integration (High Priority)**

* **Task:** Build out `ApiClient` support in `src/nomic_engine/llm/api_clients.py`.
* **Status:** ✅ COMPLETED
* **Sub-tasks:**
* ✅ Implement **OpenAI** client (using existing `openai` library).
* ✅ Implement **Anthropic** client (using `anthropic` library).
* ✅ Implement **Google Gemini** client (using `google-generativeai` library).
* ✅ All models in `models.yml` are now fully supported.

### 2. Engine: Dynamic Voting Logic
* **Task:** Refactor `GameLoop` logic to respect flags.
* **Files:** `src/nomic_engine/core/game_loop.py`
* **Logic:**
  * `_tally_votes`: Switch between 100% (unanimous) and >50% (majority) based on `flags["vote_mode"]`.
  * `_detect_victory`: Ensure it uses the current `target_score` from state.

### 3. Judge: State Maintenance Interface
* **Task:** Add `maintain_state(rules, game_state) -> StateUpdates` to `BaseJudge`.
* **Trigger:** Call this in `GameLoop._resolve_turn` immediately after a proposal is applied.
* **Implementations:**
  * **HumanJudge:** Interactive CLI loop reviewing Flags and Target Score.
  * **LLMJudge:** New prompt: *"Review the new rules. Return JSON updating 'flags' or 'target_score' ONLY if they conflict with the text."*

### 4. Smart Player Context (Bug Mitigation)

* **Task:** Add plain-language score/rank descriptions to mitigate LLM math errors.
* **Status:** PLANNED
* **Logic:**
* Modify `PromptBuilder._format_game_state_block` in `src/nomic_engine/llm/prompt_builder.py` to include a "Leaderboard Context" line (e.g., "You are in 2nd place, 5 points behind the leader").

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

* **Dynamic Game Structure**
   * Create "turn structure" game file that defines each step, and can be changed by the judge (maybe players, too, by concensus?). This allows extra steps to be created, or order of steps to be changed.
