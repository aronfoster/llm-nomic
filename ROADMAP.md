# **Project Plan: Nomic LLM Engine**

This document tracks the high-level plan for the `llm-nomic` project.

## Core Principles

Our architecture is built on these principles:

1.  **Security, Structure First:** Code will be secure and clean (ala Uncle Bob)
2.  **Engine vs. Instance:** The Game Engine is stateless and operates on "Game Instance" directories.
3.  **Authoritative Data:** The Game Instance is the sole authority on game state. `rules.jsonl` and `game_state.json` are the sources of truth.
4.  **Stand alone PRs:** All PRs are small enough to understand, `make ci` passes, and contain unit tests that cover new code

## Bug List Game Engine

### HIGH PRIORITY

- None

### Low Priority

- Rules 107, 202, and 205 interaction: If players amend the base rules to allow newly-passed scoring rules to apply retroactively to the turn they were adopted (contrary to current interpretation), the judge scoring prompt would need updating to reflect this change. Currently the prompt explicitly instructs judges not to apply rule changes retroactively.


## Sprint 33: GameLoop Mutation Refactoring

**Theme:** Clean up the architectural boundary violations and decompose `_apply_turn_mutations` in `game_loop.py`. No new user-visible features. Two standalone PRs, each leaving `make ci` green.

---

**Task 1: Move `maintain_state` out of `_apply_turn_mutations`**

Currently `maintain_state` is called inside `_apply_turn_mutations` — a mutation method is making a judge call to decide what to mutate. This is a query hiding inside a side-effect method. Fix the boundary.

- Move the `maintain_state` judge call into `_get_judge_decisions`, alongside the existing `veto` and `assess_scores` calls.
- Add a `state_updates: StateUpdates` field to `JudgeDecisions`.
- Remove the `maintain_state` call and its surrounding logic from `_apply_turn_mutations`. The method must make zero judge calls after this change.
- Update `_apply_turn_mutations` to read `state_updates` from `judge_decisions` instead.
- The transcript output for state maintenance must be identical before and after this change.
- `make ci` passes.

**Task 2: Decompose `_apply_turn_mutations` into single-responsibility methods** ✅ Done

With Task 1 merged, `_apply_turn_mutations` is a pure orchestrator of already-decided changes. Extract each concern into its own private method. The orchestrator body should contain only delegation calls — no inline logic.

Extracted private methods:

- `_apply_score_changes(score_response)` — applies delta adjustments to `game_state.scores`
- `_apply_engine_state_changes(state_updates)` — applies flag and `target_score` updates to `game_state`
- `_apply_rule_changes(proposal)` — calls `rules_manager.apply_proposal` and `save_rules`
- `_increment_proposal_counter()` — increments `game_state.next_proposal_id`
- `_save_turn()` — persists game state to disk via `save_game_state`
- `_log_turn(...)` — writes the transcript entry

`_log_and_save_turn` removed (superseded by `_save_turn` and `_log_turn`).

Behavior identical before and after. Unit tests added for each extracted method. `make ci` passes.



## Future Work

This is the long-term backlog and TODO scratchpad.

### Engine Features

* **Improve `LLMPlayer`:**
  * Implement advanced token-saving strategies, especially context caching
  * Implement async behavior (per model provider?)
  * Add a "notepad" feature (e.g., a simple file) for LLMs to save plans and opinions of other players between turns.
    * For prompt examples, do we use current-game responses instead of static personality file values on turn 2+?
    * Recommended notepad sections: 1 per other player, long term strategy, rules to watch, more?
  * Can we get the "thinking" from thinking llm models? Add that as a new field into the logs and transcript?
  * We need to get token usage/metadata about the queries Answer: How big do context windows need to be? What's the cost/total token usage?
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
  * Create more personalities: chaos monkey, showman
  * Think more about the llm model picker
    * Should we allow custom model config per game (e.g., for new/local models not in `models.yml`)?
    * Shoudl we query provider APIs to get a list of available models?
  * Add the ability of the scoring judge to use random numbers, which would allow Suber's original rule 202 that used a D6 for scoring
    * Would be ideal to allow arbitary random ranges and math to enable creative scoring rules (e.g. 6 points plus a random 1-6 points)
  * Rule 109 makes 3 different parameters for vote interpretation: majority/unanimous, whether to count abstain votes as the total, and whether transmute should be unanimous.
  * Rule 113 asserts that players can quit. Right now we assume all players play forever. Should we remove this rule or add a way to quit the game? Need to track turns differently. Could be part of a more dynamic turn handling system.

* **Tooling & Features:**
    * ~~Specify versions for dependencies and start managing those~~ — Done: all deps pinned with `make update-deps` workflow.

* **Dynamic Game Structure**
  * Create "turn structure" game file that defines each step, and can be changed by the judge (maybe players, too, by consensus?). This allows extra steps to be created, or order of steps to be changed.
    * Therefore if rules change the turn steps (e.g an additional round of discussion after voting) it can be supported. Might need to ask the judge to define the steps and provide some guidance to the players.

### Visualization (Web app)

* Plan out a end state for visualizing individual game, all games, rules, profiles for player (slice by model and personality), leaaderboard
* Have badges or awards for players (models)
* Maybe: Build a `build_site.py` script to convert the game history into a shareable HTML file.

### Graphical UI

* Have a GUI for running the game in Electron (?)


