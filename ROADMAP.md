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

## Sprint 32: Refactoring & Polish

**Theme:** Pay down technical debt accumulated across Sprints 27–31, with no new user-visible features. Every task is a standalone PR that leaves `make ci` green.

---

**Task 1: Quick-win bug fixes/features**

Bundle the three trivial low-priority bugs/features that don't deserve individual PRs. ✅ Done:

- Allow numeric input anywhere the script currently only accepts text (e.g., entering `2` instead of `llm` for player type, `1` instead of `friendly` for personality). Straightforward input normalization with no architectural impact.
- Fix the initial rule text to match the configured target score when it differs from the default 100.
- Fix the misleading `RULES_BLOCK` label in `LLMJudge.assess_scores` — it said "ALL CURRENT RULES" but only contained scoring rules; now uses `SCORING_RULES_BLOCK` with accurate header.
- Add `make fix` as an alias for `make format` in the Makefile.

**Task 2: Dependency version pinning + update process** ✅ Done:

- All packages in `requirements.txt` are pinned to exact versions (e.g. `anthropic==0.84.0`), set to the latest available at time of merge.
- `make update-deps` fetches the latest version of each dependency, rewrites `requirements.txt` with exact pins, installs them, and runs `make ci` to verify nothing broke. Failures are surfaced, not swallowed.
- The update process is documented in the README (see "Updating Dependencies" section).
- `make ci` passes against the pinned versions.

**Task 3: Parser return type hardening**

Replace the `dict[str, str | None]` return types in `parsers.py` with proper `TypedDict`s or dataclasses — one per response shape (`ProposalResponseData`, `VoteResponseData`, etc.). The current types lie (they include booleans and ints), which silences mypy errors that should be caught. Update callers and add regression tests for the new shapes.


## Future Work

This is the long-term backlog and TODO scratchpad.

### Refactoring (from code review)

* **Decompose `_apply_turn_mutations`:**
  * This method handles rule application, state maintenance, proposal ID tracking, victory detection, turn advancement, transcript logging, and game-over logging — all in ~80 lines.
  * Extract rule application + state maintenance into a private `_apply_rule_changes` method.
  * Extract transcript logging + save into a dedicated method (partially done already with `_log_and_save_turn`).
  * The guiding principle ("only method with side effects") is good, but it should orchestrate discrete sub-steps rather than implement them inline.

* **Decouple Score Mutation from Judge Methods:** - Integrated into Sprint 27 task 1.
  * `LLMJudge.assess_scores` directly mutates `game_manager.game_state.scores`. This creates a hidden dependency: `_detect_victory` only works correctly because the judge's side effect already happened.
  * Consider having the judge *return* score deltas, with `_apply_turn_mutations` being the sole method that writes to game state. This matches the existing architecture's intent.

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


