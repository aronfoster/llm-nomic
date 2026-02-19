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

- Allow numbers or text (e.g. 2 or llm) in each prompt of create_game.py
- Rules 107, 202, and 205 interaction: If players amend the base rules to allow newly-passed scoring rules to apply retroactively to the turn they were adopted (contrary to current interpretation), the judge scoring prompt would need updating to reflect this change. Currently the prompt explicitly instructs judges not to apply rule changes retroactively.

### Sprint 30: Creative Personalities & Withdrawal Fix

**Goal:** Make LLM players propose creative, personality-driven rules instead of exclusively point-manipulation plays. Fix stale context bug on withdrawal retries.

### ~~Task 1: Fix discusser stale context after withdrawal retry (BUG — HIGH)~~ ✅ COMPLETE

**Problem:** When `retain_discusser_history_on_retry=True`, `_collect_discussions` skips `begin_discussion_turn` on retry rounds to preserve accumulated reasoning. But `begin_discussion_turn` is the only place the PROPOSAL_BLOCK gets injected into the discusser's system message. After a withdrawal + pivot, non-proposer LLMs discuss the *old* proposal.

**Fix:**
- Added `on_proposal_updated` abstract method to `BasePlayer`.
- `LLMPlayer.on_proposal_updated` appends one user message (using new `DISCUSS_PROPOSAL_UPDATED_TEMPLATE`) with the new proposal block, preserving history.
- `HumanPlayer.on_proposal_updated` prints withdrawal notice and new proposal details to console.
- `GameLoop._collect_discussions` calls `on_proposal_updated` (instead of skipping) on retry rounds when `retain_discusser_history_on_retry=True`.

### ~~Task 2: Personality files with phase-specific examples (CORE — LARGE)~~ ✅ COMPLETE

**Problem:** All personalities share hardcoded examples in `prompts.py`. These examples exclusively demonstrate point-manipulation strategies, anchoring LLMs to propose only numerical advantage plays. The personality blocks themselves are 4 lines of tone-setting that are not effective at differentiating behavior.

**Solution:** Create dedicated personality files containing persona description, strategic guidance, and phase-specific examples. Wire PromptBuilder to load them.

**Subtasks:**
- Create a `personalities/` directory (sibling to `src/`? inside `src/nomic_engine/`? — developer's call) with one file per personality
  (`machiavellian.md`, `friendly.md`, `none.md`), each containing persona
  description, strategic guidance, and phase-specific examples (propose,
  discuss, revise, vote)
  - Each file contains appropriate sections, e.g. `PERSONA`, `STRATEGIC_GUIDANCE`, `PROPOSE_EXAMPLES`, `DISCUSS_EXAMPLES`, `REVISE_EXAMPLES`, `VOTE_EXAMPLES`
  - **Use the existing hardcoded examples for these files during development** and they will be modified by the PM later, outside this Developer Task
- Update PromptBuilder to load personality from file and inject personality-specific examples into appropriate places, e.g. `INSTRUCTION_PROPOSE`,`INSTRUCTION_DISCUSS`, `INSTRUCTION_REVISE`, and `INSTRUCTION_VOTE`
  templates via a new `{personality_examples}` placeholder
- Remove inline personality constants from `prompts.py`
- Update `create_game.py` to discover available personalities from the
  directory. The game loop should throw an exception and log an error if it attempts to run a turn and finds a player with a personality name that doesn't exist in the directory.
- Personality names are case-insensitive: normalize to lowercase at input,
  enforce lowercase filenames as convention
- Developer seeds personality files using the existing hardcoded examples;
  PM will iterate on file content post-merge

### Task 3: Remove vestigial Rule 112 UNCLEAR/AMBIGUOUS checks (POLISH — LOW)

**Problem:** Two TODO comments mark dead code from the v0 ruleset. The v1 ruleset's Rule 111 was simplified and no longer has the UNCLEAR/AMBIGUOUS triggering mechanism.

**Fix:**
- In `prompt_builder.py` `build_revision_instruction`: Remove the Rule 112 loop that checks for "UNCLEAR"/"AMBIGUOUS" in discussions. Always use the unconditional `constraint_message`.
- In `human_player.py` `revise`: Remove the `must_revise` check and the associated "Rule 112" print/prompt logic. Always show the standard R/S/W prompt.
- Remove both TODO comments.

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
  * Currently, missing API keys aren't discovered until a player's first turn — potentially hours into a game with multiple providers.
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
  * Prompt examples should draw from personality!
    * Consider moving personalities into individual files
  * Implement advanced token-saving strategies, especially context caching
  * Implement async behavior (per model provider?)
  * Add a "notepad" feature (e.g., a simple file) for LLMs to save plans and opinions of other players between turns.
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


