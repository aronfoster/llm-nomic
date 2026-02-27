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

- Players tend to modify Rule 203 to switch to majority after the first complete circuit (instead of second)
  - Might just turn this into a flag since it's so common.
  - What if we modified the judge memory prompt to tell it to remind itself about future game state changes?
- Players are not clear on vote result and final score when writing memories. Needs to be explicit.

### Low Priority

- Rules 107, 202, and 205 interaction: If players amend the base rules to allow newly-passed scoring rules to apply retroactively to the turn they were adopted (contrary to current interpretation), the judge scoring prompt would need updating to reflect this change. Currently the prompt explicitly instructs judges not to apply rule changes retroactively.
- Need to change text on last withdrawal attempt to make it clear that withdrawing is still an option, just skips your turn
- Remove ephemeral block from `memory_update` for Anthropic clients so we're not paying to write to the cache.
- On illegal proposal (e.g. AMEND a rule that doesn't exist) game should count as a withdrawal and allow a retry, not crash


## Sprint 37: TBD


## Future Work

This is the long-term backlog and TODO scratchpad.

### Engine Features

* **Improve LLM API Efficiency**
  * Should remove json instruction and have per-provider json flags set for 4 big providers. Fallback to the instruction for Ollama + new providers.
  * Implement async behavior (per model provider?)
    * Batch processing for 24 hour turn around (game summary?). Unlikely to benefit for the near future.
  * Can we get the "thinking" from thinking llm models? Add that as a new field into the logs and transcript?
    * Apparently you just tell them to put it in `<thinking>` blocks. Anthropic lets you pass a parameter, too. Gemini needs a parameter set. OpenAI doesn't share. Open models usually respect the `<thinking>` prompt.
  * Explore https://openrouter.ai/ support for tokens/models, along with other providers
  * Cache token usage tested on xAI and Anthropic. Need to test behavior with Google, OpenAI, and Ollama.
    * Ollama should correctly log tokens but not use caching
    * Google and OpenAI should log token usage and show significant caching.
    * Need to add a note somewhere about minimum 16k tokens, recommend 32k tokens as a model context requirement

* **Rate Limiting & Cost Tracking**
  * Add per-turn and per-game token/cost tracking. Print token counts from API responses at the end of the turn.
    * Would need to hard code cost/million tokens. Maybe prompt to update during game creation? Harcode defaults and put optional custom values per game?
  * Rate limiting an option? Not sure that could work.
  
* **Game State & Rules**
  * Enhanced Voting Architecture
      * **Task:** Replace binary vote logic with named "Abstention-Aware" modes.
      * **Data Model:** Expand `VoteMode` enum in `data_models.py` to include `UNANIMOUS_STRICT`, `CONSENSUS`, `MAJORITY_TOTAL`, and `MAJORITY_VOTING`?
      * **Engine Logic:** Update `GameLoop._tally_votes` to implement the specific denominator logic for each named mode.
      * **LLM Awareness:** Update `PromptBuilder` to dynamically inject a plain-language explanation of the current `vote_mode` into player prompts, ensuring players understand the tactical weight of an "ABSTAIN" vote.
      * Rule 109 adds another dimension to voting: whether transmute should be unanimous
      * Also minimum yes votes as a voting mode
      * Flag for whether to assess points after a withdrawal
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

* **Game Loop: Looping**
  * Explore running more than one turn on application execution
  * Could turn it into a more mature CLI app:
    * Pick an existing (unfinished) game or create a new one
    * Run turns until key press, then finish the in-progress turn
    * Improve console logging to only show game output, not INFO logging about engine steps

### Visualization (Web app)

* Plan out a end state for visualizing individual game, all games, rules, profiles for player (slice by model and personality), leaaderboard
* Have badges or awards for players (models)
* Maybe: Build a `build_site.py` script to convert the game history into a shareable HTML file.

### Graphical UI

* Have a GUI for running the game in Electron (?)

### Development

* Improve code documentation using markdown files for developers (especially Claude Code and Codex) to read
