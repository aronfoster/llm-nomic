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

- `game_transcript.md` does not include initial rule proposal, withdrawals, and possibly other player inputs that should be in there.

### Low Priority

- Allow numbers or text (e.g. 2 or llm) in each prompt of create_game.py
- Rules 107, 202, and 205 interaction: If players amend the base rules to allow newly-passed scoring rules to apply retroactively to the turn they were adopted (contrary to current interpretation), the judge scoring prompt would need updating to reflect this change. Currently the prompt explicitly instructs judges not to apply rule changes retroactively.
- Nedd to remove the extraneous DEBUG level logging of private thoughts, which happens after INFO logging of the entire response (including private_thoughts)
- Judge scoring uses RULES_BLOCK which begins "=== ALL CURRENT RULES ===", but is actually sent only points-related rules
- Game creation allows you to pick the target score, but the initial rule isn't changed. Hardcode the initial score.

## Sprint 31: Project Structure Reorganization

Reorganized root-level files into `config/` and `docs/` subdirectories:
- `flag_schema.json` → `config/flag_schema.json`
- `models.yml` → `config/models.yml`
- `PM_CONTEXT.md` → `docs/PM_CONTEXT.md`
- `RULESET_DESIGN.md` → `docs/RULESET_DESIGN.md`
- `Nomic_Initial_Ruleset_v0.md` → `docs/rulesets/Nomic_Initial_Ruleset_v0.md`
- `Nomic_Initial_Ruleset_v1.md` → `docs/rulesets/Nomic_Initial_Ruleset_v1.md`

Updated all references in `src/nomic_engine/constants.py`, `tests/`, and `README.md`.

## Sprint 32: TBD

### Task 1

**Task 1: Transcript fidelity fixes**
- Log withdrawal proposals and their discussion rounds
- Fix `Judge Approval` / `Judge Veto Response` showing `N/A` on failed votes
- Log `maintain_state` decisions
- Kill the duplicate DEBUG logging of private thoughts (it's a one-liner and you're already in that neighborhood)

**Task 2: Startup validation**
- API key validation for all configured players + judge before first turn
- Personality file existence validation at the same startup checkpoint
- These live in the same place and fail for the same reason — ship them together

**Task 3: ApiClient Provider Factory Pattern**
- The if/elif chain is isolated to one file, touches zero game logic, and has a clear "done" state
- Low blast radius, good test story, and it unblocks OpenRouter support which is on the long-term backlog anyway
- This is a satisfying standalone refactor that a dev can own start-to-finish in 1.5-2 days


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
  * Currently, missing API keys aren't discovered until a player is called for proposal or discussion. With bad or missing API keys, this would terminate the program and waste the tokens spent on other players.
  * Add a validation step in `create_game.py` or at `main.py` startup that checks all required env vars for configured players and the judge before gameplay begins.

* **Validate Personality Files at Startup:**
  * Currently, a missing personality file raises a `FileNotFoundError` at the point of first use (inside `PromptBuilder` during a player's turn), not at startup.
  * Add a validation step alongside API key validation that checks all player personality files exist in the `personalities/` directory before gameplay begins.

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
    * For prompt examples, do we use current-game responses instead of static personality file values on turn 2+?
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
    * Specify versions for dependencies and start managing those (pin at least major versions in `requirements.txt` to prevent breakage from upstream changes)
    * Add `make fix` to Makefile that does the same thing as `make format`

* **Dynamic Game Structure**
  * Create "turn structure" game file that defines each step, and can be changed by the judge (maybe players, too, by consensus?). This allows extra steps to be created, or order of steps to be changed.
    * Therefore if rules change the turn steps (e.g an additional round of discussion after voting) it can be supported. Might need to ask the judge to define the steps and provide some guidance to the players.

### Visualization (Web app)

* Plan out a end state for visualizing individual game, all games, rules, profiles for player (slice by model and personality), leaaderboard
* Have badges or awards for players (models)
* Maybe: Build a `build_site.py` script to convert the game history into a shareable HTML file.

### Graphical UI

* Have a GUI for running the game in Electron (?)


