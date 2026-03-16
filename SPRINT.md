# Sprint 39 — Run the Game

**Goal(s):**
- Allow the engine to run multiple turns in a single invocation via new CLI flags
- Clean up the console so it shows meaningful, readable game content and nothing else
- Unrecoverable errors in any turn stop the application immediately; the next turn never starts

---

## Background

Today the engine runs exactly one turn per invocation. To play a full game you must
re-run the command after every turn, which makes watching or testing a game painful.

The console output also mixes two very different streams: structured engine-internal
`logging` calls (e.g., "Loading game", "Starting turn N", "EVENT: move_start") with
intentional game-facing `print()` output. The transcript file (`game_transcript.md`)
already contains a well-structured, readable markdown summary of every turn. The
console should show exactly that content — nothing more, nothing less.

This sprint delivers both: multi-turn execution and a console experience that mirrors
the transcript.

---

## Tasks

### Task 1 — Silence engine logging on the console

**Priority:** High (foundation for Task 2)

**Description:**
The console log handler currently emits `INFO`-level messages. This causes engine
internals — model loading messages, turn-start notices, `EVENT:` entries from
`GameLogger.log_event()`, and similar — to appear alongside the game output that
players care about. All of these should be invisible on the console.

After this task:
- The console handler threshold is raised so that only `WARNING` and above appear on
  the console. Normal game execution produces no console output from the `logging`
  system at all.
- The file handler is unchanged: `DEBUG` and above continues to be written to
  `game_log.jsonl`.
- `WARNING` and `ERROR` log messages (unexpected conditions, API failures, etc.)
  remain visible on the console because they represent conditions the operator
  needs to know about immediately.
- All existing `print()` statements used for real-time status during LLM calls
  (e.g., "🤔 Alice is thinking about a proposal") are unaffected and continue to
  appear on the console as-is.

**Acceptance Criteria:**
- [ ] Normal game execution produces no `logging`-originated lines on the console
- [ ] `WARNING` and `ERROR` log messages still appear on the console
- [ ] `game_log.jsonl` is unchanged (all log levels still written to file)
- [ ] All `print()`-based status messages from LLM/player actions are unaffected
- [ ] `make ci` passes

---

### Task 2 — Real-time event output as player and judge actions arrive

**Priority:** High

**Description:**
The console should show game events as they happen — not batched at the end of the
turn. When a player's proposal comes back from the LLM, it should appear immediately.
When each discussion comment arrives, it should appear immediately. The same for
votes, the judge's veto decision, scoring, and any rule changes applied. An observer
watching a live run should be able to follow the game moment-to-moment without waiting
for the entire turn to finish before seeing any content.

The existing ad-hoc prints (`_print_proposal_summary()`, `_print_outcome_summary()`)
print a partial summary at the *wrong* time — after voting has already completed —
and omit discussions entirely. These are replaced with targeted prints at the point
each event actually occurs in the game loop:

| Event | When to print |
|-------|---------------|
| Proposal submitted (or withdrawn) | When `propose()` returns |
| Each player's discussion comment | When each `discuss()` returns |
| Revised proposal (if MODIFY) | When `revise()` returns a changed proposal |
| Each player's vote | When each `vote()` returns |
| Vote tally | After all votes are collected |
| Judge veto decision | When `get_veto()` returns |
| Scoring | When `assess_scores()` returns |
| Rule/state changes applied | After `_apply_turn_mutations()` completes |

The content and formatting of each event print is left to the Developer, but must be
consistent and human-readable. It does not need to mirror the markdown format of the
transcript file — the transcript is the durable record; the console is the live view.

The existing real-time LLM status messages (e.g., "🤔 Alice is thinking about a
proposal") are unaffected and continue to appear just before the API call they
describe.

**Acceptance Criteria:**
- [ ] The proposal is printed to the console as soon as it is received, before
  discussion begins
- [ ] Each discussion comment is printed as soon as it is received, not batched
- [ ] Each vote is printed as soon as it is received, not batched
- [ ] The vote tally, judge decision, scoring outcome, and any applied rule changes
  are each printed when they occur
- [ ] A proposal withdrawal is printed immediately when it occurs
- [ ] `_print_proposal_summary()` and `_print_outcome_summary()` are no longer called
- [ ] `make ci` passes

---

### Task 3 — Pre-turn game state header

**Priority:** Medium

**Description:**
Before each turn begins — before any LLM calls are made — print a concise header to
the console that summarises the current game state. This gives the operator at-a-glance
context before the real-time status messages start appearing.

The header must include:
- Turn number
- Name (and model label) of the player whose turn it is
- Current scores for all players, sorted descending
- Target score (if one is set)

The exact formatting is left to the Developer, but it must be clearly visually
separated from the previous turn's output (e.g., a horizontal rule or blank lines).

This header is printed once per turn, at the very start of `run_turn()`, before any
player or judge actions are taken.

**Acceptance Criteria:**
- [ ] A header is printed to the console at the start of every turn
- [ ] The header shows: turn number, active player (name + model), all player scores,
  and target score (when set)
- [ ] The header appears before any LLM status messages for that turn
- [ ] `make ci` passes

---

### Task 4 — Multi-turn CLI flags

**Priority:** High

**Description:**
Add two new optional flags to the CLI. The existing default behaviour (run exactly
one turn, then exit) is unchanged when neither flag is provided.

**`--turns N`**
Run up to N turns in a single invocation. Turns execute back-to-back with no pause
between them. If the game ends (victory condition reached) before N turns have been
played, execution stops and the victory summary is shown. N must be a positive
integer; the CLI should reject invalid values with a clear error message.

**`--until-victory`**
Run turns continuously until the victory condition is reached. If the game has no
target score configured, the flag is accepted but the engine runs indefinitely (the
operator must use Ctrl+C to stop). `--turns` and `--until-victory` are mutually
exclusive; providing both is a CLI error.

**Ctrl+C behaviour (unchanged):**
A `KeyboardInterrupt` at any point hard-terminates the process immediately, exactly
as it does today. State is only guaranteed consistent at turn boundaries (the engine
already saves state atomically at the end of each turn).

**Error behaviour:**
If a turn raises an unrecoverable error, the application stops immediately. The next
turn does not start. This mirrors the existing single-turn behaviour and applies
equally in multi-turn mode.

**Acceptance Criteria:**
- [ ] `--turns N` runs exactly N turns (or fewer if game ends), then exits
- [ ] `--until-victory` runs until the victory condition is reached, then exits
- [ ] `--turns` and `--until-victory` together produce a clear CLI error and exit
  without running any turns
- [ ] Omitting both flags runs exactly one turn (unchanged default)
- [ ] Invalid values for `--turns` (non-integer, zero, negative) produce a clear
  error
- [ ] A `KeyboardInterrupt` hard-terminates at any point
- [ ] An unrecoverable error in any turn stops the application; no further turns run
- [ ] `make ci` passes

---

<!-- Add additional Task blocks as needed. -->
