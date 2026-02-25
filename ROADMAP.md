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
- Need to change text on last withdrawal attempt to make it clear that withdrawing is still an option, just skips your turn


## Sprint 36: Investigate and Implement Context Caching

### Background

The current codebase makes no explicit use of provider-level prompt caching.
This means every API call may be re-processing the full input from scratch,
including the complete ruleset and game state that are re-sent on every turn.
Caching behaviour varies significantly by provider — some require explicit
opt-in, some are automatic, and some offer no client-side control at all.

This task covers investigation first, then implementation. Do not implement
anything until the investigation phase is complete and costs/savings are
understood per provider.

### Task 1: Investigate
Record structured token usage data for every API call made during a game into
a dedicated file. This file is the foundation for cost analysis, caching
investigation, and future rate limiting or budget enforcement work. It is a
prerequisite to the caching investigation task.

### Task 2: Implementation
Likely need to modify Anthropic handling to use explicit use of `cache_control`

### Task 3: LLMJudge Caching
`LLMJudge` currently rebuilds its full message list from scratch on each of
its four per-turn calls (`get_veto`, `assess_scores`, `maintain_state`,
`update_memory`), re-sending the ruleset many times. Fixing this properly
requires refactoring `LLMJudge` to maintain stateful per-turn context.


## Future Work

This is the long-term backlog and TODO scratchpad.

### Engine Features

* **Improve `LLMPlayer`:**
  * Implement advanced token-saving strategies, especially investigate best use of context caching
  * Implement async behavior (per model provider?)
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
      * Rule 109 adds another dimension to voting: whether transmute should be unanimous
  * Create more personalities: chaos monkey: tries to break the engine
  * Think more about the llm model picker
    * Should we allow custom model config per game (e.g., for new/local models not in `models.yml`)?
    * Shoudl we query provider APIs to get a list of available models?
  * Add the ability of the scoring judge to use random numbers, which would allow Suber's original rule 202 that used a D6 for scoring
    * Would be ideal to allow arbitary random ranges and math to enable creative scoring rules (e.g. 6 points plus a random 1-6 points)
  * Rule 113 asserts that players can quit. Right now we assume all players play forever. Should we remove this rule or add a way to quit the game? Need to track turns differently. Could be part of a more dynamic turn handling system.

* **Dynamic Game Structure**
  * Create "turn structure" game file that defines each step, and can be changed by the judge (maybe players, too, by consensus?). This allows extra steps to be created, or order of steps to be changed.
    * Therefore if rules change the turn steps (e.g an additional round of discussion after voting) it can be supported. Might need to ask the judge to define the steps and provide some guidance to the players.
  * Explore tool calling/MCP to allow players+judge to dynamically modify turn processing.

### Visualization (Web app)

* Plan out a end state for visualizing individual game, all games, rules, profiles for player (slice by model and personality), leaaderboard
* Have badges or awards for players (models)
* Maybe: Build a `build_site.py` script to convert the game history into a shareable HTML file.

### Graphical UI

* Have a GUI for running the game in Electron (?)


