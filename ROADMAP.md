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
* Shouldn't need "discussion" from the proposer in addition to the proposal justification/discussion

### Low Priority

* None

## Sprint 8: Grok & Game Loop

### Theme
Focus on connecting a cheap, smart cloud model (Grok) and closing the game loop so games can actually finish.

---

### ~P0 – Feat: xAI (Grok) Client Integration~ COMPLETED

**Goal:** Enable players to use Grok via the existing `ApiClient` abstraction.

**Status:** Completed – ApiClient now initializes Grok models with the xAI endpoint and documented configuration.

**Tasks:**
- Update `src/nomic_engine/llm/api_clients.py` to support `provider: "xai"`.
- Initialize an OpenAI-compatible client with:
  - `api_key` from the configured env var (e.g., `XAI_API_KEY`, via `model_config.env_key_name`).
  - `base_url="https://api.x.ai/v1"`.
- Ensure `get_completion`:
  - Uses the correct model ID from `models.yml`.
  - Sends/receives messages in the standard internal format.
- Add or update documentation/config examples to show a Grok-based player configuration.

**Acceptance Criteria:**
- Initializing `ApiClient` with a Grok model no longer raises `NotImplementedError`.
- A game run with a Grok-backed player completes at least one turn successfully.
- Basic error handling/logging is present when the Grok call fails.
- Unit tests cover all new code.

---

### ~P1 – Feat: Victory Check (Rule 208 – First to 100 Points)~ COMPLETED

**Goal:** Turn the engine from an infinite turn simulator into a game that can end.

**Status:** Completed – target score is configurable and the game stops when reached.

**Tasks:**
- Add an optional `target_score` field to `GameState` (prompted during game creation).
- Implement a `check_victory` step in `src/nomic_engine/core/game_loop.py` that runs after turn resolution.
- When a player’s score `>= target_score`:
  - Record a “GAME OVER” event in the log/history.
  - Stop the main loop (or return a status indicating the game is over).
- Document how `target_score` is configured (and its default suggestion) in the config/template docs.

**Acceptance Criteria:**
- A game with a player reaching `target_score` stops automatically.
- The winner and end condition are clearly visible in logs/history.
- Existing tests still pass; new tests cover at least one “win” scenario.

---

### ~P2 – Bug: Fix Judge Logic on Failed Votes~ COMPLETED

**Goal:** Avoid unnecessary judge work and clarify game semantics.

**Status:** Completed – Judge veto is now only consulted when proposals pass.

**Tasks:**
- In `src/nomic_engine/core/game_loop.py` (e.g., `_resolve_turn`):
  - Compute whether the proposal passed or failed based on player votes.
  - Only call `self.judge.get_veto()` when the proposal has passed.
  - If the proposal failed by vote, skip the veto step entirely.
- Update or add tests to cover:
  - Proposal failing by votes (judge is not consulted).
  - Proposal passing by votes (judge is consulted and can veto).

**Acceptance Criteria:**
- Games where the proposal fails by vote do not call into the judge veto logic.
- Tests assert correct behavior for both passed and failed proposals.

---

### P3 – Bug: Remove Duplicate Discussion Requirement

**Goal:** Simplify the proposal UX by avoiding redundant “discussion” fields.

**Tasks:**
- Identify where proposals currently require both “discussion” and “justification/discussion”.
- Update schema, prompts, and any validation logic so only a single discussion/justification field is required.
- Adjust any CLI/LLM prompts and docs to reflect the simplified structure.

**Acceptance Criteria:**
- Proposal creation only requires one discussion/justification field.
- No validation errors or prompts refer to a second, redundant “discussion”.
- Tests and docs match the new behavior.


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

