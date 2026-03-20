# **Project Plan: Nomic LLM Engine**

> **Active sprint tasks are tracked in [SPRINT.md](./SPRINT.md).**
> This file tracks the long-term backlog, bug lists, and future work.

This document tracks the high-level plan for the `llm-nomic` project.

## Core Principles

Our architecture is built on these principles:

1.  **Security, Structure First:** Code will be secure and clean (ala Uncle Bob)
2.  **Engine vs. Instance:** The Game Engine is stateless and operates on "Game Instance" directories.
3.  **Permit Play** The Game Engine should allow game-breaking behavior if the players vote on it and judge allows it.
4.  **Authoritative Data:** The Game Instance is the sole authority on game state. `rules.jsonl` and `game_state.json` are the sources of truth.
5.  **Stand alone PRs:** All PRs are small enough to understand, `make ci` passes, and contain unit tests that cover new code

## Bug List Game Engine

### HIGH PRIORITY

- None

### Low Priority

- Rules 107, 202, and 205 interaction: If players amend the base rules to allow newly-passed scoring rules to apply retroactively to the turn they were adopted (contrary to current interpretation), the judge scoring prompt would need updating to reflect this change. Currently the prompt explicitly instructs judges not to apply rule changes retroactively.


## Future Work

This is the long-term backlog and TODO scratchpad.

### Engine Features

* **Improve LLM API Efficiency**
  * Should remove json instruction and have per-provider json flags set for 4 big providers. Fallback to the instruction for Ollama + new providers.
  * Implement async behavior (per model provider?)
    * Batch processing for 24 hour turn around (game summary?). Unlikely to benefit for the near future.
  * Can we get the "thinking" from thinking llm models? Add that as a new field into the logs and transcript?
    * Apparently you just tell them to put it in `<thinking>` blocks. Anthropic lets you pass a parameter, too. Gemini needs a parameter set. OpenAI doesn't share. Open models usually respect the `<thinking>` prompt.
    * We will not include this because it conflicts with json flags.
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
  * Flag for whether to assess points after a withdrawal
  * Create more personalities: chaos monkey: tries to break the engine
  * Think more about the llm model picker
    * Should we allow custom model config per game (e.g., for new/local models not in `models.yml`)?
    * Shoudl we query provider APIs to get a list of available models?
  * Add the ability of the scoring judge to use random numbers, which would allow Suber's original rule 202 that used a D6 for scoring
    * Would be ideal to allow arbitary random ranges and math to enable creative scoring rules (e.g. 6 points plus a random 1-6 points)
  * Rule 113 asserts that players can quit. Right now we assume all players play forever. Should we remove this rule or add a way to quit the game? Need to track turns differently. Could be part of a more dynamic turn handling system.
  * Rule snapshots, memory snapshots, score snapshots for replays

* **Dynamic Game Structure**
  * Create "turn structure" game file that defines each step, and can be changed by the judge (maybe players, too, by consensus?). This allows extra steps to be created, or order of steps to be changed.
    * Therefore if rules change the turn steps (e.g an additional round of discussion after voting) it can be supported. Might need to ask the judge to define the steps and provide some guidance to the players.
  * Explore tool calling/MCP to allow players+judge to dynamically modify turn processing.
  * Update judge prompt to have it remind itself on future turns if game state must change.
  * Support for multiple votes per player

* **Game Loop: Looping**
  * ~~Explore running more than one turn on application execution~~ *(Sprint 39)*
  * ~~Improve console logging to only show game output, not INFO logging about engine steps~~ *(Sprint 39)*
  * ~~**Graceful soft-interrupt**: Detect a keypress (e.g., any non-Ctrl+C key) while a turn is running
    and finish the current turn cleanly before pausing, rather than hard-terminating. Requires
    background thread polling for input while the turn executes. Ctrl+C remains a hard interrupt.~~ *(Sprint 40)*
  * ~~**Full interactive CLI app** *(long-term goal)*: Replace the current "one invocation =
    one turn" model with a single long-running process that is the primary way to play.
    The operator launches the CLI once and is presented with a menu to continue an existing
    game or create a new one. The selected game then runs turn-by-turn with no manual
    re-launch. When a game ends (or the operator quits), the menu returns. The CLI should
    never require the operator to pass `--game_dir` flags or know about internal file paths.~~ *(Sprint 40)*

### Visualization (Web app)

* Plan out a end state for visualizing individual game, all games, rules, profiles for player (slice by model and personality), leaaderboard
* Have badges or awards for players (models)
* Maybe: Build a `build_site.py` script to convert the game history into a shareable HTML file.

### Graphical UI

* Have a GUI for running the game in Electron (?)

### Development

* Improve code documentation using markdown files for developers (especially Claude Code and Codex) to read
