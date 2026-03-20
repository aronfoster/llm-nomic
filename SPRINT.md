# Sprint 40 — Full Interactive CLI Console

**Goal(s):**
- Replace the one-shot invocation model with a single long-running interactive
  process as the primary way to play
- The operator launches once, picks or creates a game from a menu, and runs
  turns interactively until they choose to stop
- The existing `--game_dir`, `--turns`, and `--until-victory` flags are
  preserved and continue to work as a non-interactive batch/scripting mode
- A graceful soft-interrupt lets the operator signal "finish this turn, then
  pause" without hard-killing the process

---

## Background

After Sprint 39, the CLI can run multiple turns in a single invocation and
displays clean, readable game output. The remaining friction is workflow-level:
the operator still has to know the `--game_dir` path, re-launch the process
manually, and cannot stop mid-run without killing the process.

This sprint delivers the **Full interactive CLI app** described in ROADMAP.md's
long-term backlog, along with the **Graceful soft-interrupt** item that pairs
naturally with it.

---

## Task Overview

| # | Task | Depends on |
|---|------|------------|
| 1 | Extract game-creation logic into an importable module | — |
| 2 | Game discovery utility | — |
| 3 | Top-level interactive console menu | 1, 2 |
| 4 | Interactive turn loop | 3 |
| 5 | Graceful soft-interrupt | 4 |

---

## Task 1 — Extract game-creation logic into an importable module

**Priority:** High (unblocks Task 3)

**Description:**

`create_game.py` at the repo root contains the complete game-creation flow
(prompting for game name, players, judge, target score; writing all game
files). Currently its logic is only reachable by running the script directly.
The new interactive console (Task 3) must be able to invoke this flow inline.

This task makes the game-creation functions callable from within the
`nomic_engine` package without altering the existing script behaviour.

The exact approach — moving functions, adding a package module, re-exporting
from an existing module — is left to the Developer. What matters is:

- All game-creation functions are importable from within `src/nomic_engine/`
  using normal relative or absolute package imports.
- `create_game.py` at the repo root continues to work identically when run
  directly (`python create_game.py`). Its visible behaviour must not change.
- No change to the game-creation flow itself (prompts, validation, file
  output).

**Acceptance Criteria:**
- [ ] Game-creation logic is importable from within the `nomic_engine` package
- [ ] `python create_game.py` produces identical behaviour to before this task
- [ ] No behavioural change to the game-creation flow
- [ ] `make ci` passes

---

## Task 2 — Game discovery utility

**Priority:** High (unblocks Task 3)

**Description:**

A utility function that scans `GAMES_DIR` (`games/`) for valid existing game
instances and returns a structured list suitable for display in the console
menu.

A directory is a valid game instance if it contains at minimum `config.yml`
and `game_state.json`. Directories that are missing required files are silently
skipped — they must not cause errors or appear in the list.

Each entry in the returned list must expose:

| Field | Source |
|-------|--------|
| Display name | Derived from the directory name |
| Full path | Absolute or repo-relative path to the game directory |
| Current turn number | `move_number` from `game_state.json` |
| Current active player name | `current_player_name` from `game_state.json` |
| Game complete | Whether a winner already exists (victory condition reached) |

If `GAMES_DIR` does not exist or contains no valid game instances, the
function returns an empty list without raising an error.

**Acceptance Criteria:**
- [ ] Function returns correct metadata for each valid game directory under
  `GAMES_DIR`
- [ ] Directories missing `config.yml` or `game_state.json` are silently skipped
- [ ] `GAMES_DIR` not existing returns an empty list without error
- [ ] Unit tests cover: empty `GAMES_DIR`, multiple valid games, mixed
  valid/invalid directories, `GAMES_DIR` absent
- [ ] `make ci` passes

---

## Task 3 — Top-level interactive console menu

**Priority:** High (unblocks Task 4)

**Description:**

When `main.py` is invoked without `--game_dir`, display an interactive console
menu instead of exiting with an error. The menu is the primary entry point for
normal use.

**Menu options:**

1. **Continue a game** — Display the list of discovered games (Task 2) with
   their summary (display name, turn number, current player, complete/in
   progress). The operator selects a game by number. If no games exist, print a
   message and return to the menu without error.
2. **New game** — Run the game-creation flow (Task 1) inline in the same
   process. After successful creation, offer the operator the option to start
   playing immediately. If they decline, return to the main menu.
3. **Quit** — Exit the process cleanly (exit code 0).

After the operator finishes with a game — either the game reaches victory or
they choose to stop — the top-level menu is displayed again. The process does
not exit between games.

**Existing flag behaviour (unchanged):**

Providing `--game_dir` on the command line bypasses the menu entirely and goes
directly into the turn loop for that game (as it did before this sprint). The
operator is not shown a menu.

**Acceptance Criteria:**
- [ ] Launching `main.py` without `--game_dir` shows the top-level menu
- [ ] "Continue a game" lists discovered games; selecting one enters the turn
  loop
- [ ] "Continue a game" with no available games prints a message and returns to
  the menu without error
- [ ] "New game" runs the creation flow inline and offers to play immediately
- [ ] "Quit" exits with code 0
- [ ] After a game ends or the operator quits, the menu is shown again
- [ ] Launching with `--game_dir` bypasses the menu (unchanged behaviour)
- [ ] `make ci` passes

---

## Task 4 — Interactive turn loop

**Priority:** High

**Description:**

Replace the current "run N turns then exit" behaviour with a continuous
auto-advancing loop. Turns run back-to-back with no input required between
them, until the game ends or the operator signals a stop via the soft-interrupt
(Task 5).

**Default interactive behaviour (no batch flags):**

Turns advance automatically, one after another, with no prompt between them.
The operator does not need to press anything to continue. The loop ends when:

- The game reaches the victory condition — display the victory summary, then
  return to the top-level menu (or exit cleanly if launched with `--game_dir`).
- The operator triggers the soft-interrupt (Task 5) — after the current turn
  completes fully, return to the top-level menu (or exit cleanly if launched
  with `--game_dir`).
- The operator presses Ctrl+C — hard-terminate immediately (unchanged).

**Default behaviour change:**

Previously, omitting all flags ran exactly one turn. After this task, omitting
all flags enters the continuous auto-advancing loop. This applies whether the
game was reached via the menu or via `--game_dir`.

**Batch flags (unchanged):**

`--turns N` and `--until-victory` continue to work as before. Their behaviour
is now identical to the new default loop, except `--turns N` still stops after
N turns. If used in combination with `--game_dir`, behaviour is identical to
Sprint 39.

**Already-complete games:**

If the selected game has already reached victory, display the victory summary
immediately and return to the menu (or exit). No turns are run.

**Acceptance Criteria:**
- [ ] Turns advance automatically with no input required between them
- [ ] Victory ends the loop, shows the summary, and returns to the menu
- [ ] A game already at victory shows the summary without running any turns
- [ ] `--turns N` still stops after N turns
- [ ] `--until-victory` still runs until victory (behaviour now matches the
  default)
- [ ] Omitting all flags no longer runs exactly one turn; the continuous loop
  is entered instead
- [ ] Ctrl+C hard-terminates immediately (unchanged)
- [ ] `make ci` passes

---

## Task 5 — Graceful soft-interrupt

**Priority:** Medium

**Description:**

When a turn is running, the operator should be able to signal "finish this turn
and then pause" without hard-terminating the process. This lets the current
turn — including all in-flight LLM API calls — complete normally before the
loop stops.

**Behaviour:**

- During turn execution, a background mechanism (implementation detail for the
  Developer) monitors for a designated keypress (e.g. `p` or `s`).
- Pressing the key while a turn is running sets an internal "stop after this
  turn" flag and immediately prints a brief acknowledgement such as
  `"Stopping after this turn…"`.
- The current turn runs to full completion: all LLM calls, voting, scoring, and
  state save proceed normally.
- After the turn completes, the turn loop exits and the operator is returned
  to the top-level menu. If the process was launched with `--game_dir`
  directly (no menu), the process exits cleanly (exit code 0).
- Pressing the key when no turn is running has no visible effect.
- **Ctrl+C continues to hard-terminate the process immediately at any point.**
  This is unchanged from current behaviour.

**Acceptance Criteria:**
- [ ] Pressing the designated key during turn execution sets the stop flag and
  prints an acknowledgement
- [ ] The running turn always completes fully before the loop exits
- [ ] After the turn completes, the operator is returned to the top-level menu
  (or the process exits cleanly if launched with `--game_dir`)
- [ ] The soft-interrupt works in both interactive mode and batch mode
  (`--turns`, `--until-victory`)
- [ ] Pressing the key when no turn is running has no visible effect
- [ ] Ctrl+C still hard-terminates immediately
- [ ] `make ci` passes

---

<!-- Add additional Task blocks as needed. -->
