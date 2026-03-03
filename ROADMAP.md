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
- Need to have all LLM input failures (e.g. bad rule number, ABSTAIN vote when not allowed, etc.) go through retry logic with basic (sanitized) error descriptions so the LLM can fix it.

### Low Priority

- Rules 107, 202, and 205 interaction: If players amend the base rules to allow newly-passed scoring rules to apply retroactively to the turn they were adopted (contrary to current interpretation), the judge scoring prompt would need updating to reflect this change. Currently the prompt explicitly instructs judges not to apply rule changes retroactively.
- Need to change text on last withdrawal attempt to make it clear that withdrawing is still an option, just skips your turn
- Remove ephemeral block from `memory_update` for Anthropic clients so we're not paying to write to the cache.
- On illegal proposal (e.g. AMEND a rule that doesn't exist) game should count as a withdrawal and allow a retry, not crash


## Sprint 37: Additional Flags

* Task 1: `majority_after_loops` Flag — Auto-Transition from Unanimous to Majority Voting ✓ DONE

  **Overview:** Add a configurable engine flag that replaces the hardcoded Rule 203 circuit-counting logic in `_check_rule_203_transition()`. The flag specifies how many complete game loops must pass before `vote_mode` automatically switches from `unanimous` to `majority`. A "complete loop" = all players have each taken exactly one turn.

  **1. New flag in `config/flag_schema.json`:**
  ```json
  "majority_after_loops": {
    "type": "integer",
    "nullable": true,
    "min_value": 1,
    "valid_values": null,
    "default": 2,
    "description": "Number of complete game loops (each player takes one turn) after which vote_mode automatically switches from 'unanimous' to 'majority'. Once triggered, this flag resets to null. Set to null to disable automatic switching."
  }
  ```
  - Type: positive integer (≥ 1) or `null`
  - Default: `2` (preserves current Rule 203 behavior)
  - `null` disables the automatic transition

  Note: `load_flag_schema()` currently requires `valid_values` as a field; keep it with a JSON `null` value. Two new optional schema fields are introduced: `nullable` (bool) and `min_value` (int).

  **2. Flag schema validation updates (`src/nomic_engine/utils/flag_schema.py`):**
  - `validate_flag_value()`: if flag definition has `"nullable": true`, allow `None` as a valid value (skip type/min_value checks when value is None). Otherwise, if `"min_value"` is set, raise `ValueError` if the integer value is less than `min_value`.
  - `validate_flags()` and `validate_state_updates()`: no changes needed; they call `validate_flag_value()`.
  - `format_current_flags()`: when a flag value is `None`, render it as `null` (not `"None"`). Example: `- majority_after_loops: null`
  - `format_supported_flags()`: for flags with `"nullable": true`, append `"or null"` to the type label. If `min_value` is set, include it in the display. Example: `- majority_after_loops (integer or null, min 1): Number of complete game loops...`
  - `get_flag_defaults()`: current behavior (skip flags with `null` defaults) is correct — the default here is `2`, so it will be included.

  **3. Engine logic (`src/nomic_engine/core/game_loop.py`):**
  - **Remove** `_check_rule_203_transition()` entirely.
  - **Replace** the call in `_check_automatic_transitions()` with a call to a new `_check_majority_after_loops()` method:
    ```python
    def _check_majority_after_loops(self) -> None:
        flags = self.game_manager.game_state.flags
        loops_flag = flags.get("majority_after_loops")
        if loops_flag is None:
            return
        if flags.get("vote_mode", "unanimous") != "unanimous":
            return
        move_number = self.game_manager.game_state.move_number
        num_players = len(self.game_manager.game_state.turn_order)
        if move_number / num_players > loops_flag:
            flags["vote_mode"] = "majority"
            flags["majority_after_loops"] = None
            # log the transition and add a transcript entry
    ```
  - This check runs inside `_advance_turn_state()` (after `move_number` is incremented) via `_check_automatic_transitions()`, matching the existing call site.
  - Condition uses float division: `move_number / num_players > loops_flag`. With 3 players and flag=2, this fires at move_number=7 (start of the 3rd loop), identical to the existing Rule 203 logic.
  - The new method does NOT check whether Rule 203 exists — the flag is the sole trigger, independent of any rule.
  - After transition: log with `logger.info` and add a `[ENGINE]` transcript entry (follow the pattern from `_check_rule_203_transition()`).

  **4. Judge prompt:** No prompt builder changes needed. The flag description in `flag_schema.json` is injected into judge prompts automatically by the existing `format_supported_flags()` and `format_current_flags()` calls in `PromptBuilder`.

  **5. Files to modify:**
  | File | Change |
  |------|--------|
  | `config/flag_schema.json` | Add `majority_after_loops` entry |
  | `src/nomic_engine/utils/flag_schema.py` | Support `nullable` and `min_value` schema fields in validation and formatting |
  | `src/nomic_engine/core/game_loop.py` | Remove `_check_rule_203_transition()`, add `_check_majority_after_loops()`, update `_check_automatic_transitions()` |

  **6. Tests (`tests/`):**
  - Update any tests for `_check_rule_203_transition()` to target the new `_check_majority_after_loops()` method.
  - `majority_after_loops = null`: no automatic transition fires at any move_number.
  - `majority_after_loops = 1` with 3 players: fires at move_number=4 (`4/3=1.33 > 1`), not at move_number=3 (`3/3=1.0`, not `> 1`).
  - `majority_after_loops = 2` (default) with 3 players: fires at move_number=7 (`7/3=2.33 > 2`), not at move_number=6 (`6/3=2.0`, not `> 2`). Matches previous Rule 203 behavior.
  - After the transition fires: `vote_mode` is `"majority"` and `majority_after_loops` is `None`.
  - No transition when `vote_mode` is already `"majority"`.
  - Judge can set `majority_after_loops` to a valid integer or `null` via `StateUpdates`; validation accepts both.
  - Validation rejects `0`, negative integers, floats, strings; accepts positive integers and `null`.

* Task 2: `allow_abstention` Flag — Configurable Abstention Voting ✓ DONE

  **Overview:** Add a boolean flag `allow_abstention` that controls whether players may cast an ABSTAIN vote. When `false`, only YES and NO are valid vote options. When `true`, YES, NO, and ABSTAIN are all valid, and the unanimous and majority tally semantics change to treat abstentions as neutral. Additionally, the majority tally denominator changes to non-abstaining voters in all cases (flag true or false).

  **1. New flag in `config/flag_schema.json`:**
  ```json
  "allow_abstention": {
    "type": "boolean",
    "nullable": false,
    "valid_values": null,
    "default": false,
    "description": "When true, players may vote ABSTAIN in addition to YES and NO. Unanimous voting passes when no player votes NO (ABSTAIN is neutral). Majority voting counts only non-abstaining players in the denominator. When false, only YES and NO are valid options and unanimous requires all YES votes."
  }
  ```
  - Type: `boolean`; default: `false`; not nullable

  **2. Flag schema changes (`src/nomic_engine/utils/flag_schema.py`):**
  - `validate_flag_value()`: Already supports `"boolean"` type — no change needed.
  - `format_current_flags()`: Boolean values must render without quotes as `true` or `false` (not as `"True"` or `"False"`). Example: `- allow_abstention: false`
  - `format_supported_flags()`: No change needed; `"boolean"` already renders correctly as a type label.

  **3. Vote tally logic (`src/nomic_engine/core/game_loop.py` — `_tally_vote_results()`):**

  Three changes:

  **Change A — Remove the zero-voter auto-pass special case (behavior change):**
  The existing `if total_voters == 0: passed = True` guard must be removed. It is no longer needed and is inconsistent with the new formula:
  - Unanimous with zero voters: `yes_count(0) == total_voters(0)` → True; or `no_count(0) == 0` → True. Both formula variants pass naturally without the guard.
  - Majority with zero voters: **the old guard forced a pass; new behavior is a fail** (`0 > 0` is False). A vote with no participants should not pass under majority.

  **Change B — Majority denominator (always applies, regardless of flag):**
  - OLD: `passed = yes_count > (total_voters / 2)` — abstentions counted in denominator
  - NEW: `passed = yes_count > ((yes_count + no_count) / 2)` — only non-abstaining voters count
  - All ABSTAIN: non-abstaining denominator is 0; `0 > 0` → fails.
  - Zero voters (empty list): covered by Change A above — fails under majority.

  **Change C — Unanimous formula (unconditional):**
  - NEW: `passed = no_count == 0` — a proposal passes unanimous if nobody voted NO. This applies regardless of the `allow_abstention` flag.
  - The flag does not change the tally formula; it controls whether ABSTAIN votes are accepted in the first place (see Change D below).
  - OLD (`yes_count == total_voters`) is removed entirely.

  **4. Vote validation (`_collect_votes()` in `src/nomic_engine/core/game_loop.py`):**

  **Change D — Reject ABSTAIN when flag is false:**
  - When `allow_abstention` is `false` (default), any player that returns an ABSTAIN vote must be rejected. The system should raise a `ValueError` (or equivalent) rather than silently counting the vote.
  - When `allow_abstention` is `true`, ABSTAIN is a valid response and passes through to the tally.
  - This means `_collect_votes()` must read the `allow_abstention` flag from `GameState` and enforce it per-vote.

  **5. Vote instruction prompt (`src/nomic_engine/llm/prompts.py` and `src/nomic_engine/llm/prompt_builder.py`):**

  `build_vote_instruction()` must receive the current `allow_abstention` flag value (Developer decides the cleanest way to pass it — e.g., add a `flags` or `game_state` argument). The rendered vote instruction must differ based on the flag:

  - **When `allow_abstention` is `false`:**
    - List only `"YES"` and `"NO"` as valid vote values.
    - No mention of ABSTAIN.

  - **When `allow_abstention` is `true`:**
    - List `"YES"`, `"NO"`, and `"ABSTAIN"` as valid vote values.
    - Include a plain-language explanation of abstention semantics for each vote mode. Example wording (Developer may refine):
      - *"If the current vote mode is unanimous, a proposal passes only if no one votes NO — ABSTAIN is treated as neutral."*
      - *"If the current vote mode is majority, abstaining players are excluded from the count — YES votes must exceed half of non-abstaining (YES + NO) voters."*
    - The explanation should appear regardless of the current `vote_mode` value, so players understand both scenarios.

  The "Invalid JSON = automatic ABSTAIN" fallback line in the current prompt should remain as-is. Note: if `allow_abstention` is `false`, an LLM that falls back to ABSTAIN will be rejected by `_collect_votes()` — this is intentional and acceptable.

  **6. Personality vote examples (`src/nomic_engine/llm/prompt_builder.py` — `_build_vote_examples()`):**
  - When `allow_abstention` is `true`, include an ABSTAIN example in addition to the YES and NO examples (if personality data supports it). If no ABSTAIN example is defined for a personality, omit it gracefully — do not error.

  **7. Files to modify:**
  | File | Change |
  |------|--------|
  | `config/flag_schema.json` | Add `allow_abstention` entry |
  | `src/nomic_engine/utils/flag_schema.py` | Render booleans without quotes in `format_current_flags()` |
  | `src/nomic_engine/core/game_loop.py` | `_collect_votes()`: reject ABSTAIN when flag is false; `_tally_vote_results()`: new majority denominator, remove zero-voter guard, unanimous becomes `no_count == 0` unconditionally |
  | `src/nomic_engine/llm/prompts.py` | Update or split `INSTRUCTION_VOTE` to support both flag states |
  | `src/nomic_engine/llm/prompt_builder.py` | Pass flag value into `build_vote_instruction()`; update `_build_vote_examples()` for optional ABSTAIN example |

  **8. Tests (`tests/`):**
  - Update `test_tally_vote_results_zero_voters_passes` to reflect the removed auto-pass: zero voters under majority must now **fail**.
  - Update `test_tally_vote_results_majority_abstentions_count_in_total` (or equivalent) to reflect the new denominator: abstentions are excluded from the majority denominator.
  - **Zero voters — behavior change:**
    - Zero voters, majority: fails (behavior change from current auto-pass).
    - Zero voters, unanimous: passes naturally (`no_count(0) == 0`).
  - **Majority — denominator change (flag=false, default behavior):**
    - 3 players: 2 YES, 1 ABSTAIN → non-abstaining = 2, `2 > 2/2=1` → passes.
    - 4 players: 1 YES, 1 NO, 2 ABSTAIN → non-abstaining = 2, `1 > 2/2=1` → fails (not strictly greater).
    - All ABSTAIN: non-abstaining = 0, `0 > 0` → fails.
  - **Majority — denominator change (flag=true):** Same denominator formula; verify it also applies when abstention is enabled.
  - **Unanimous — tally (flag is irrelevant at tally layer):**
    - All YES, zero NO → passes (`no_count == 0`).
    - Any NO present → fails.
    - Mix of YES and ABSTAIN, zero NO → passes.
    - All ABSTAIN, zero NO → passes.
  - **Vote validation — ABSTAIN rejection (flag=false):**
    - Player returns ABSTAIN when flag is false → `_collect_votes()` raises `ValueError` (test at the `_collect_votes()` level, not tally).
  - **Flag validation:**
    - `allow_abstention: true` and `allow_abstention: false` are accepted by `validate_flag_value()`.
    - Non-boolean values (e.g. `"true"`, `1`, `null`) are rejected.
  - **`format_current_flags()` with boolean:**
    - `allow_abstention: false` renders as `- allow_abstention: false` (no quotes).
    - `allow_abstention: true` renders as `- allow_abstention: true` (no quotes).

* Task 3: Create a flag for what type of voting is required for TRANSMUTE. Defaults to unanimous. Relates to rule 109. Uses the same voting mode class as is used for other proposals. Engine should use this flag to determine whether TRANSMUTE proposals pass or fail.

* Task 4: Add 2 voting modes: "minimum yes votes" and "unanimous strict". Minimum yes votes comes with an integer (any value less than player count) that is checked against the count of YES votes. "Unanimous strict" only is available after ABSTAIN flag is TRUE, and requires all YES votes and zero ANSTAIN votes. If voting mode is unanimous strict and ABSTAIN flag is set to FALSE, it behaves like unanimous.


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
  * Rule snapshots, memory snapshots, score snapshots for replays

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
