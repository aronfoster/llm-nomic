# **Project Plan: Nomic LLM Engine**

This plan is refined for a "clean code" approach, incorporating strong typing, unit testing, and a more robust data model. It explicitly designates the Human as the Judge for v1 and makes the engine the sole authority on game state.

## **1\. Core Principles**

1. **Security First (API Keys):** API keys are loaded *only* from environment variables (via a .env file). The .gitignore file will block this file from *ever* being committed.  
2. **Engine vs. Instance (Neutrality):** The Python application (the "Engine") is stateless. All game state is read from and written to a "Game Instance" directory.  
3. **Authoritative Data (The Engine is the Law):**  
   * **Rules:** The *authoritative* rules are stored in rules.jsonl (machine-readable). A rules.md file is generated from this as a *human-readable render*.  
   * **State:** The *authoritative* game state (scores, turn order) is stored in game\_state.json. The engine is the *only* thing that calculates and updates this state. LLMs are *told* the score; they are *never* asked to calculate it.

## **2\. The "Game Instance" Concept (Revised)**

A "Game Instance" is a self-contained directory. The engine is pointed at this directory to run the game.

nomic-game-1/  
├── config.yml           \# Static setup: Player names, model IDs (e.g., 'gpt-4o'), etc.  
├── game\_state.json      \# Dynamic state: { "scores": {...}, "current\_turn": "...", "move\_number": 1 }  
├── rules.jsonl          \# \*\*Authoritative\*\* rules. One JSON object per line.  
├── rules.md             \# Human-readable \*render\* of rules.jsonl, updated by the engine.  
├── game\_log.jsonl       \# Machine-readable log of all actions, prompts, and raw LLM responses.  
└── game\_transcript.md   \# Human-readable, formatted log of the game.

## **3\. Phased Development Plan**

### **Phase 1: The Core Engine (CLI)**

**Goal:** Create a testable, type-safe engine that can execute a single, 5-step turn, with a Human Judge validating all actions.

1. **Project Setup (The "Skeleton"):**  
   * Create requirements.txt: Add python-dotenv (security), pydantic (for data models), pyyaml (for config.yml), pytest (testing), mypy (type checking).  
   * Create .gitignore: Add .env, \_\_pycache\_\_/, .mypy\_cache/, \*.pyc.  
   * Create .env.template: A non-secret file showing *what* keys are needed (e.g., OPENAI\_API\_KEY=YOUR\_KEY\_HERE).  
2. **Data Models (src/nomic\_engine/data\_models.py):**  
   * Define pydantic models for all data to enforce strong typing.  
   * Rule(rule\_id: int, text: str, status: Literal\['immutable', 'mutable'\])  
   * PlayerConfig(name: str, model\_id: str)  
   * GameState(scores: dict\[str, int\], current\_turn\_player: str, move\_number: int)  
   * Proposal(...)  
3. **Security & Config (src/nomic\_engine/config.py):**  
   * A module to safely load environment variables using python-dotenv.  
   * Provides a function get\_api\_key(model\_id: str) \-\> str.  
4. **Game Instance Manager (src/nomic\_engine/game\_manager.py):**  
   * A class GameManager initialized with a game\_dir\_path.  
   * load\_game(): Reads all files (config.yml, game\_state.json, rules.jsonl) into their Pydantic data models.  
   * save\_game\_state(state: GameState): Saves the GameState model back to game\_state.json.  
5. **Rules Manager (src/nomic\_engine/rules\_manager.py):**  
   * A class RulesManager that holds the list of Rule objects.  
   * load\_from\_jsonl(filepath): Loads rules.jsonl.  
   * apply\_proposal(proposal: Proposal): Modifies the internal list of Rule objects. (This is the "judge's" action).  
   * save\_rules(filepath\_jsonl, filepath\_md): Saves the *updated* rules to rules.jsonl and re-renders the *entire* rulebook to rules.md.  
6. **Player Abstraction (src/nomic\_engine/players/):**  
   * base\_player.py: Abstract BasePlayer with methods: propose(state, rules), discuss(...), vote(...).  
   * human\_player.py: HumanPlayer class that implements methods via input().  
   * llm\_player.py: LLMPlayer class that builds a prompt (see Key Challenges) and calls the API (using a separate api\_clients.py module).  
7. **Game Loop (src/nomic\_engine/game\_loop.py):**  
   * The GameLoop class that takes the loaded GameManager context.  
   * run\_turn(): Executes the 5-step turn logic (Propose, Discuss, Revise, Vote, Resolve).  
   * resolve(proposal, votes):  
     * **Human Judge Hook:** Prompts the human: "Is this proposal valid? (y/n)"  
     * **State Calculation:** If 'y' and passed, *this* is where points are calculated and scores are updated (e.g., state.scores\[player\] \+= 10).  
     * Calls RulesManager.apply\_proposal(...).  
     * Calls GameManager.save\_game\_state(...).  
8. **Main Entrypoint (src/nomic\_engine/main.py):**  
   * Uses argparse to get \--game\_dir.  
   * Initializes GameManager and GameLoop.  
   * Calls game\_loop.run().

## **4\. Key Challenges**

* **Prompt Engineering:** The prompt must be meticulously constructed, *providing* all state (rules, history, scores) to the LLM. The LLM is a *player*, not a *scorekeeper*.  
* **Response Parsing:** We will instruct the LLM to reply using the *exact* Markdown template from your original rule-draft.txt. This is easier to parse than JSON. We'll use simple string/regex parsing to extract the proposal.  
* **Testability:** The "clean code" structure (e.g., data\_models.py, rules\_manager.py) makes unit testing possible. We can write a pytest test for rules\_manager.py *without* needing any APIs.

## **5\. Refined File Structure (The "Engine")**

This structure is designed for "clean code" and testability.

llm-nomic/  
├── .gitignore            \# \<-- Blocks .env, \_\_pycache\_\_, etc.  
├── .env.template         \# Example for developers  
├── .env                  \# \<-- YOUR SECRET KEYS (not committed)  
├── requirements.txt      \# (pydantic, pyyaml, python-dotenv, pytest, mypy)  
├── pyproject.toml        \# Config for pytest, mypy  
│  
├── src/  
│   └── nomic\_engine/  
│       ├── \_\_init\_\_.py  
│       ├── main.py           \# Entrypoint  
│       ├── game\_loop.py      \# Turn logic, state calculation  
│       ├── game\_manager.py   \# Loads/saves a Game Instance  
│       ├── rules\_manager.py  \# Loads/saves/applies rules  
│       ├── data\_models.py    \# Pydantic models (types)  
│       ├── config.py         \# Secure API key loading  
│       │  
│       ├── players/  
│       │   ├── \_\_init\_\_.py  
│       │   ├── base\_player.py  
│       │   ├── human\_player.py  
│       │   └── llm\_player.py  
│       │  
│       └── utils/  
│           ├── \_\_init\_\_.py  
│           ├── api\_clients.py    \# Functions for calling OpenAI, Anthropic, etc.  
│           ├── prompt\_builder.py \# Logic to assemble the master prompt  
│           └── parsers.py        \# Parses LLM's markdown response  
│  
└── tests/  
    ├── test\_rules\_manager.py  
    ├── test\_game\_loop\_scoring.py  
    └── ...  


# Scratch Notes
* Eventually have multiple starting rulesets to pick from
* Do we require that all the xxx_API_KEYs exist? We need to allow users to fill in only the ones they're using.
