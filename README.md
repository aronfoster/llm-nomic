# LLM Nomic Project

This is a Python 3.12 project to create games of Suber's 1982 game Nomic, to be played by human and LLM players.

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

To create and launch a new Nomic game:

```bash
python3 create_game.py
```

This interactive script will:
1. Prompt you for a game name
2. Ask for the number of players
3. Allow you to configure each player (human or LLM)
4. For LLM players, let you choose from available models
5. Generate all required game files in `games/<game-name>/`

**Example game creation session:**
```
Enter new game name: My First Game
How many players? 2

--- Configuring Player 1 ---
Player name: Alice
Player type (human/llm): human

--- Configuring Player 2 ---
Player name: Bob
Player type (human/llm): llm

Available LLM models:
  1. gpt-4 (openai)
  2. claude-3-opus (anthropic)
  ...
Choose a model by number: 2
```

### Running a Turn

After creating a game, run one turn at a time with:

```bash
python -m src.nomic_engine.main --game_dir games/<game-name>
```

The command will:

1. Load the specified game directory
2. Instantiate each configured player
3. Walk through the proposal, discussion, vote, judge, and scoring steps
4. Save the updated game state and transcript back into the same directory

Logging is written to the console and to `game_log.jsonl` inside the game directory so you can review detailed turn data.

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

## Project Structure

```
llm-nomic/
├── src/                        # Source code
│   └── nomic_engine/           # Core game engine
├── tests/                      # Test files
├── games/                      # Game instances (created by create_game.py)
├── create_game.py              # Interactive game creation script
├── models.yml                  # Available LLM model definitions
├── Nomic_Initial_Ruleset_v0.md # Initial game rules
├── requirements.txt            # Python dependencies
├── Makefile                    # Development commands
└── .env                        # API keys (not in git)
```
