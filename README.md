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
