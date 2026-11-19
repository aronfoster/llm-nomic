# LLM Nomic — Play Peter Suber’s Self-Amending Game with Humans + LLMs

## What is Nomic?

**Nomic** is Peter Suber’s 1982 self-amending game: every turn a player proposes a rule change, everyone discusses and votes, and if it passes the ruleset itself evolves. The game is literally *about* changing the rules.

This project runs full games of Nomic with any mix of human and LLM players. The engine is stateless, authoritative game-state files drive everything, and the ruleset is a deliberate, documented adaptation of the 1982 original.

### Key Project Documents

- **[SPRINT.md](SPRINT.md)** — Active sprint: goals and tasks with acceptance criteria.
  **Developers: start here for your current work.**

- **[ROADMAP.md](ROADMAP.md)** — Long-term backlog, bug lists, and future work not yet scheduled into a sprint.

- **[RULESET_DESIGN.md](docs/RULESET_DESIGN.md)** — Why and how the ruleset differs from Suber’s original (plus a side-by-side table of changes). Essential context for anyone playing or extending the game.

- [Peter Suber’s original 1982 rules](http://legacy.earlham.edu/~peters/writing/nomic.htm) (external reference)

## Prerequisites

- Python 3.12 or higher
- pip (Python package manager)
- Git

## Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd llm-nomic
   ```

2. **Install dependencies:**
   ```bash
   make install
   ```

   This will:
   - Upgrade pip to the latest version
   - Install all required Python packages from `requirements.txt`
   - Set up pre-commit hooks for code quality checks

   Alternatively, you can install dependencies manually:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   pre-commit install
   ```

3. **Configure API keys (required for LLM players):**

   Copy the template environment file and add your API keys:
   ```bash
   cp .env.template .env
   ```

   Then edit `.env` and add your API keys:
   ```
   OPENAI_API_KEY=your_openai_key_here
   ANTHROPIC_API_KEY=your_anthropic_key_here
   GOOGLE_API_KEY=your_google_key_here
   XAI_API_KEY=your_xai_key_here
   ```

   Note: You only need to provide keys for the LLM providers you plan to use.

## Launching the Application

### Creating a New Game

The easiest way to create a game is through the interactive console (see
**Running the Game** below). Select **2. New game** from the main menu.

Alternatively, run the standalone creation script directly:

```bash
python3 create_game.py
```

Both paths prompt for the same information:
1. Game name
2. Number of players
3. Each player's name, type (human or LLM), and — for LLM players — model choice
4. Target score (default 100, or `none` to disable)

Game files are written to `games/<game-name>/`.

### Running the Game

#### Interactive mode (recommended)

Launch the engine without any flags to enter the interactive console:

```bash
python -m src.nomic_engine.main
```

You will be presented with a menu:

```
========================================
  NOMIC — Main Menu
========================================
  1. Continue a game
  2. New game
  3. Quit
========================================
```

- **Continue a game** — lists all discovered games with their turn number,
  current player, and status. Select one by number to resume it.
- **New game** — runs the interactive game-creation flow inline, then offers
  to start playing immediately.
- **Quit** — exits with code 0.

After a game ends (victory or soft-interrupt), the menu is shown again. The
process never exits between games.

#### Graceful soft-interrupt

While turns are running, press any key followed by Enter to signal
"finish this turn, then stop". The current turn — including all in-flight
LLM API calls — completes normally before the loop exits, returning you to
the main menu. Press **Ctrl+C** at any point to hard-terminate immediately.

#### Batch / scripting mode

Provide `--game_dir` to bypass the menu and run a game directly:

```bash
# Continuous loop until victory (default when --game_dir is given)
python -m src.nomic_engine.main --game_dir games/<game-name>

# Run a fixed number of turns
python -m src.nomic_engine.main --game_dir games/<game-name> --turns 5

# Run until the victory condition is reached
python -m src.nomic_engine.main --game_dir games/<game-name> --until-victory
```

`--turns N` and `--until-victory` are mutually exclusive. If the game ends
before N turns are completed, execution stops and the victory summary is shown.

#### Inexpensive test games

`docs/examples/cheap-test/config.yml` is a checked-in profile for a short,
bounded game: two `gpt-5-mini` players, a `gpt-5-mini` LLM judge,
`target_score` 100, `withdrawal_policy: forfeit`, `max_withdrawal_retries: 0`,
two attempts per action, `max_calls_per_game: 60`,
`max_total_tokens_per_game: 150000`, `max_wall_seconds: 1200`, a 60-second
per-call timeout, and `max_output_tokens: 2048`. For `gpt-5-mini` that output
cap is sent as `max_completion_tokens`.

The file is not a runnable game directory. `games/` is gitignored runtime
state, and the engine also needs `game_state.json`, `rules.jsonl`, and the
other files `create_game.py` writes. Create a game with those players and
judge (menu option **2. New game**, or `python3 create_game.py`), then replace
that game's `config.yml` with the example, or copy its `budget`, `tuning`,
`withdrawal_policy`, and `max_withdrawal_retries` into the generated file.
Then run:

```bash
python -m src.nomic_engine.main --game_dir games/<game-name> --turns 3
```

What that command bounds, and what it does not:

- `--turns 3` stops after three turns. `max_calls_per_game: 60` stops before
  the next provider call once 60 calls have been made, including retries,
  timeouts, quota errors, and memory updates. Both limits apply.
- Each call uses a 60-second client timeout and asks for at most 2048 output
  tokens. `gpt-5-mini` counts hidden reasoning tokens against
  `max_completion_tokens`, so 1024 can be exhausted before any visible text
  and return empty content with `finish_reason=length`; 2048 leaves room for
  a short visible answer, and an empty truncated response is logged and
  retried within the budget rather than treated as success. Anthropic still
  sends `max_tokens` (8192 when a game does not set `max_output_tokens`).
  Google receives `max_output_tokens` and, when a timeout is set,
  `http_options.timeout` in milliseconds.
- `max_total_tokens_per_game: 150000` and `max_wall_seconds: 1200` are set.
  `max_wall_seconds` is measured per process, from the time the game is
  loaded, and does not accumulate across restarts.
- A configured token cap is **not precise**. The call that crosses it can
  overshoot by up to `max_output_tokens` plus that call's prompt. If a call
  returns no usable usage metadata, that call is **unavailable, not zero**,
  and the engine refuses the next provider call. It does not assume the
  missing tokens were zero, and it does not switch to another provider.
- Call and token totals are restored from `token_usage.jsonl` when a game is
  loaded, so a restart does not forget calls that were logged. A failed
  append can under-count only after a later restart; within the process the
  guard still counts the call. The logger itself still never raises.
- Startup API-key checks run outside this budget. OpenAI, xAI, and Google
  only call `models.list()`, and Anthropic only checks that the key starts
  with `sk-ant-`. None of those four send a completion. The local (Ollama)
  check can send one tiny completion before the first turn.
- The end of a run prints a per-turn and per-game usage summary. Quota and
  timeout failures are logged by name and count against the budget.
- If a configured limit refuses the next call, the process saves partial
  state, prints the summary, and exits with code 3.

Each run will:

1. Load the specified game directory
2. Instantiate each configured player
3. Walk through the proposal, discussion, vote, judge, and scoring steps for each turn
4. Save the updated game state and transcript back into the same directory after each turn

`WARNING` and `ERROR` messages are written to the console; full debug logs go to
`game_log.jsonl` inside the game directory.

### Game Files

After creation, each game directory contains:
- `config.yml` - Player configuration
- `game_state.json` - Current game state (scores, turn order, etc.)
- `rules.jsonl` - Rules in JSON Lines format
- `rules.md` - Human-readable rules in Markdown
- `game_log.jsonl` - Game event log
- `game_transcript.md` - Human-readable game transcript

### Victory Condition

Games end automatically when a player reaches the `target_score`.

- During game creation you'll be asked: `Target score? [Default: 100]`. Press
  Enter to use the default, type a number to set a custom target, or enter
  `none` to disable automatic game end.
- The chosen value is stored in both `config.yml` and `game_state.json`. If you
  disable it, the game will not end based on score.
- You can also customize it by editing `config.yml` before starting the game:

  ```yaml
  target_score: 150
  players:
    - name: "Alice"
      model_id: "gpt-4o-mini"
  ```

When any player's score meets or exceeds `target_score`, the engine logs a
"GAME OVER" event and halts further turns.

## Development Workflow

Before committing code, always run:
```bash
make ci
```

This ensures your code passes all quality checks (linting, type checking, and tests).

## Updating Dependencies

All packages in `requirements.txt` are pinned to exact versions. To upgrade
every package to its latest available release and verify the suite still
passes, run:

```bash
make update-deps
```

This command:
1. Queries PyPI for the latest version of each package in `requirements.txt`
2. Rewrites `requirements.txt` with the new exact pins
3. Installs the updated packages
4. Runs `make ci` to confirm nothing broke

**If `make ci` fails after the update:** the updated `requirements.txt` is left
on disk so you can see which versions were pulled in. Investigate the failure,
pin the offending package back to its previous working version by editing
`requirements.txt` manually, then re-run `make ci` until it is green again.
Commit the working `requirements.txt` when done.

**How often to update:** run `make update-deps` roughly once a month, or
before starting any sprint that touches the LLM API clients (`openai`,
`anthropic`, `google-genai`), which release frequently.

## Project Structure

```
llm-nomic/
├── src/                        # Source code
│   └── nomic_engine/           # Core game engine
├── tests/                      # Test files
├── games/                      # Game instances (created by create_game.py)
├── config/                     # Configuration files
│   ├── flag_schema.json        # Flag schema definitions
│   └── models.yml              # Available LLM model definitions
├── docs/                       # Project documentation
│   ├── PM_CONTEXT.md           # PM guidelines
│   ├── RULESET_DESIGN.md       # Ruleset design rationale
│   └── rulesets/               # Initial ruleset files
├── create_game.py              # Interactive game creation script
├── requirements.txt            # Python dependencies
├── Makefile                    # Development commands
├── SPRINT.md                   # Active sprint goals and tasks (PM-maintained)
├── ROADMAP.md                  # Long-term backlog and future work
└── .env                        # API keys (not in git)
```
