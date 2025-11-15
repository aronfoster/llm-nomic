# **Project Plan: Nomic LLM Engine**

This document tracks the high-level plan for the `llm-nomic` project.

## **1. Core Principles**

Our architecture is built on these principles:

1.  **Security First:** API keys are loaded *only* from environment variables.
2.  **Engine vs. Instance:** The Game Engine is stateless and operates on "Game Instance" directories.
3.  **Authoritative Data:** The Game Instance is the sole authority on game state. `rules.jsonl` and `game_state.json` are the sources of truth.

## **2. The "Game Instance" Concept (Implemented)**

A "Game Instance" is a self-contained directory. We create new ones with `create_game.py`.

```
games/my-first-game/
├── config.yml           # Static setup: Player names, model IDs
├── game_state.json      # Dynamic state: Scores, turn order
├── rules.jsonl          # **Authoritative** machine-readable rules
├── rules.md             # Human-readable render of the rules
├── game_log.jsonl       # Machine-readable log of all turns
└── game_transcript.md   # Human-readable log
```

## **3. Phase 1: Engine Foundation (Completed)**

We have successfully built and tested the entire data and tooling foundation for the project.

  * **DONE:** Full CI/CD and local tooling (`make`, `pytest`, `mypy`, `ruff`, `pre-commit`).
  * **DONE:** Core `data_models.py` (Pydantic models with Enums).
  * **DONE:** Secure `config.py` (loads from `.env` and `models.yml`).
  * **DONE:** `rules_manager.py` (the "Rule Book" logic).
  * **DONE:** `utils/parsers.py` (the "Rules MD" importer).
  * **DONE:** `create_game.py` (the "Game Factory" script).
  * **DONE:** Comprehensive unit tests for all core logic.

## **4. Phase 2: The Game Loop (Next Up)**

This is the next major sprint. The goal is to get a game *running* from start to finish on the command line, with a human player and a human judge.

### **Task 8: `GameManager` (The "Loader")**

  * **File:** `src/nomic_engine/game_manager.py`
  * **Goal:** Create a class that loads a "Game Instance" directory into memory.
  * **Requirements:**
      * `__init__(self, game_dir_path)`: Stores the path.
      * `load_game()`: Reads `config.yml`, `game_state.json`, and `rules.jsonl` (using `RulesManager.load_from_jsonl`) into Pydantic objects held by the class.
      * `save_game_state(state: GameState)`: Saves the `GameState` model back to `game_state.json`.
      * `save_rules()`: A helper that calls `self.rules_manager.save_to_jsonl(...)` and `...render_to_markdown(...)`.
      * `log_event(...)`: A helper to append structured data to `game_log.jsonl` and formatted text to `game_transcript.md`.

### **Task 9: `Player` Abstractions (The "Players")**

  * **File:** `src/nomic_engine/players/base_player.py`
      * **Goal:** Define the "Player" interface.
      * **Requirements:** Create an abstract base class `BasePlayer` with abstract methods:
          * `propose(...) -> Proposal`
          * `discuss(...) -> str | None`
          * `vote(...) -> Vote`
  * **File:** `src/nomic_engine/players/human_player.py`
      * **Goal:** Implement the interface for a human user.
      * **Requirements:**
          * Implement `propose`, `discuss`, and `vote` by prompting the user with `input()` and parsing their text.

### **Task 10: `GameLoop` (The "Conductor")**

  * **File:** `src/nomic_engine/game_loop.py`
  * **Goal:** This is the core "turn" logic.
  * **Requirements:**
      * `GameLoop` class initialized with a `GameManager` and a list of `BasePlayer` objects.
      * `run_turn()`: The main method that executes the 5 steps from our ruleset:
        1.  `propose()`: Get proposal from `current_player`.
        2.  `discuss()`: Loop all *other* players and get their discussion.
        3.  `revise()`: (v1) Skip this or ask the proposer to re-submit.
        4.  `vote()`: Loop all *other* players and get their votes.
        5.  `resolve()`:
              * Tally votes.
              * **Human Judge Hook:** Print the proposal and votes, and ask the Human Judge (via `input()`) "Is this proposal legal? (y/n)".
              * **State Calculation:** If "y", calculate score changes based on Rules 202, 204, 206. Update the `GameState`.
              * **Apply Rule:** If the vote passes, call `game_manager.rules_manager.apply_proposal(...)`.
              * **Save State:** Call `game_manager.save_game_state(...)` and `game_manager.save_rules()`.
              * Log the entire turn to the transcript.

### **Task 11: `main.py` (The "Entrypoint")**

  * **File:** `src/nomic_engine/main.py`
  * **Goal:** Tie everything together and start the game.
  * **Requirements:**
      * Use `argparse` to get `--game_dir`.
      * Initialize `GameManager` and call `load_game()`.
      * Create the list of `Player` objects (e.g., `HumanPlayer(...)`) based on the loaded `config.yml`.
      * Initialize `GameLoop` with the manager and player list.
      * Start the main loop (e.g., `while True: game_loop.run_turn()`).

## **5. Phase 3: LLM Integration & Future Ideas**

This is the long-term backlog.

  * **Implement `llm_player.py`:**
      * Create `src/nomic_engine/utils/api_clients.py`: A module to abstract the `openai`, `anthropic`, etc. API calls.
      * **Key Requirement:** The API client must *only* require the key for the *specific model* being called, not all keys in `.env`.
      * Create `src/nomic_engine/utils/prompt_builder.py`: A class that assembles the massive system prompt (rules, game history, task) for the LLM.
      * Implement the `LLMPlayer` class that uses the prompt builder and API client to fulfill the `propose`, `discuss`, and `vote` methods.
  * **LLM as Judge:** Explore replacing the "Human Judge Hook" with an LLM call.
  * **Static Site Generator:** Build the `build_site.py` script to convert a `game_log.jsonl` into a shareable HTML file.
  * **Multiple Rulesets:** Allow `create_game.py` to select from different initial ruleset files.
  * Explore different capabilities/API configs per provider
    * Claude prompt caching (https://docs.claude.com/en/docs/build-with-claude/prompt-caching)
  * Write instructions to install and run things in the README.md. Should start from zero.
