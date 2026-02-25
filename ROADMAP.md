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

- Player context for creating memories does not include judge outputs but it should
- Need to add INFO log before starting the request for creating a memory
  - Example: 🤖 Max (Machiavellian / grok-4-1-fast-non-reasoning) is remembering...
- Players tend to modify Rule 203 to switch to majority after the first complete circuit (instead of second)
  - Might just turn this into a flag since it's so common.
  - What if we modified the judge memory prompt to tell it to remind itself about future game state changes?

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

**New file**  
`games/<game-name>/token_usage.jsonl` (JSON Lines, one record per completed API call, created automatically by `create_game.py`)

**Exact record schema** (every field must always be present; use `null` when a value is unavailable):

```json
{
  "timestamp": "2026-02-25T14:32:01.123Z",
  "move_number": 4,
  "player_name": "Alice",
  "provider": "anthropic",
  "model_id": "claude-sonnet-4-5",
  "call_type": "propose",
  "input_tokens": 3821,
  "output_tokens": 214,
  "cache_creation_tokens": 3600,
  "cache_read_tokens": 0,
  "reasoning_tokens": null,
  "finish_reason": "end_turn",
  "client_latency_ms": 2341,
  "server_latency_ms": 1890.4,
  "ttft_ms": 436.4,
  "mean_itl_ms": 11.1,
  "request_id": "00-c6b29b304098785563835c9e39972a9f-a7e2a5a3001eed83-01",
  "ratelimit_remaining_requests": 607,
  "ratelimit_remaining_tokens": 4000000
}
```

**Field requirements**:

| Field                          | Type          | Source / Notes |
|--------------------------------|---------------|----------------|
| `timestamp`                    | ISO 8601      | UTC, ends with Z |
| `move_number`                  | int           | Current game move |
| `player_name`                  | string        | Player name or "Judge" |
| `provider`                     | string        | any option from models.yml |
| `model_id`                     | string        | Exact api_model_id from models.yml |
| `call_type`                    | string        | propose / discuss / revise / vote / judge_veto / judge_score / judge_maintain_state / memory_update |
| `input_tokens`                 | int           | Total billed input tokens |
| `output_tokens`                | int           | Billed output tokens |
| `cache_creation_tokens`        | int or null   | Provider-specific |
| `cache_read_tokens`            | int or null   | Provider-specific |
| `reasoning_tokens`             | int or null   | OpenAI o-series only |
| `finish_reason`                | string or null| Raw provider value (end_turn, stop, length, etc.) |
| `client_latency_ms`            | int           | Client-side wall-clock time |
| `server_latency_ms`            | float or null | xAI (e2e) or Ollama (eval_duration) |
| `ttft_ms`                      | float or null | xAI only |
| `mean_itl_ms`                  | float or null | xAI only |
| `request_id`                   | string or null| x-request-id header |
| `ratelimit_remaining_requests` | int or null   | Header value |
| `ratelimit_remaining_tokens`   | int or null   | Header value |

**Requirements**
- `TokenUsageLogger` class in `src/nomic_engine/utils/token_usage_logger.py` that never raises (failed writes → WARNING only).
- All API clients return a `CompletionResult` object instead of bare text.
- `GameManager` creates and passes the logger to `LLMPlayer` and `LLMJudge`.
- Every call site logs immediately after receiving the result (even on error).
- `create_game.py` creates an empty `token_usage.jsonl`.
- Full test coverage for logging, header extraction, and null handling per provider.
- `make ci` passes with no behaviour change to gameplay.

**Out of scope**  
Dollar-cost calculation, rate-limit enforcement, analysis scripts.

### Task 2: Implementation
Require explicit ephemeral cache_control on the system message in every `LLMPlayer` call. Target the exact prefix that repeats within a turn.

### Task 3: LLMJudge Caching
`LLMJudge` currently rebuilds its full message list from scratch on each of
its four per-turn calls (`get_veto`, `assess_scores`, `maintain_state`,
`update_memory`), re-sending the ruleset many times. Fixing this properly
requires refactoring `LLMJudge` to maintain stateful per-turn context.


## Future Work

This is the long-term backlog and TODO scratchpad.

### Engine Features

* **Improve LLM Interactions:**
  * Implement advanced token-saving strategies, especially investigate best use of context caching
  * Implement async behavior (per model provider?)
  * Can we get the "thinking" from thinking llm models? Add that as a new field into the logs and transcript?
  * We need to get token usage/metadata about the queries Answer: How big do context windows need to be? What's the cost/total token usage?
  * Explore https://openrouter.ai/ support for tokens/models

* **Rate Limiting & Cost Tracking:**
  * Each turn can generate 20+ API calls when retries are involved (propose + discuss × N + revise + vote × N + judge veto + judge score + judge maintain_state, each with up to 2 retries).
  * Add per-turn and per-game token/cost tracking. Log token counts from API responses. Consider adding configurable per-turn cost limits.
    * Would need to hard code cost/million tokens. Maybe prompt to update during game creation? Harcode defaults and put optional custom values per game?
  
* **Game State & Rules:**
  * Enhanced Voting Architecture
      * **Task:** Replace binary vote logic with named "Abstention-Aware" modes.
      * **Data Model:** Expand `VoteMode` enum in `data_models.py` to include `UNANIMOUS_STRICT`, `CONSENSUS`, `MAJORITY_TOTAL`, and `MAJORITY_VOTING`.
      * **Engine Logic:** Update `GameLoop._tally_votes` to implement the specific denominator logic for each named mode.
      * **LLM Awareness:** Update `PromptBuilder` to dynamically inject a plain-language explanation of the current `vote_mode` into player prompts, ensuring players understand the tactical weight of an "ABSTAIN" vote.
      * Rule 109 adds another dimension to voting: whether transmute should be unanimous
      * Also minimum yes votes as a voting mode
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


