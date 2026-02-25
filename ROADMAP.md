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

- None

### Low Priority

- Rules 107, 202, and 205 interaction: If players amend the base rules to allow newly-passed scoring rules to apply retroactively to the turn they were adopted (contrary to current interpretation), the judge scoring prompt would need updating to reflect this change. Currently the prompt explicitly instructs judges not to apply rule changes retroactively.
- Need to change text on last withdrawal attempt to make it clear that withdrawing is still an option, just skips your turn


## Sprint 34: LLM Player Persistent Memory

### Task 1 — Infrastructure ✅ DONE
Config schema (`llm.memory.max_characters`), `MemoryManager` utility,
`create_game.py` memory initialisation, `GameManager.load_game()` robustness,
duplicate/reserved player-name validation.  All covered by unit tests;
`make ci` passes.

### Goal
Add a lightweight, model-agnostic persistent memory system for every **LLM player only** (including Judge when it is an LLM). Each LLM gets its own `*_MEMORY.md` file that survives between turns, rides along in context for the entire turn, and is updated at the very end of every turn. This dramatically improves long-term strategy, consistency, and “aliveness” without touching any existing JSON flows or adding model-specific logic.

### Non-Negotiable Requirements
- Works with **every** model (old/weak/strong/future) — no structured output, no thinking tags, no tools.
- Zero breakage to existing propose/discuss/vote/judge JSON calls.
- Memory is injected **exactly once per turn** (in the first message the player receives that turn) and then stays in context naturally via the existing `{"role": "user"}` / `{"role": "assistant"}` conversation history.
- Humans get **no** memory file at all.
- LLMs may edit their memory **any way they want** (even if they make it non-human-readable, delete sections, or write gibberish). The engine never sanitizes or rejects content.
- Update is **mandatory** for every LLM player every turn.
- Truncation is dumb character slicing only (no token counting, no section parsing).
- Simple robustness: if a memory file is missing or empty, silently create it with the template.
- Fix bug to enforce unique Player names

### File Structure
- Directory: `games/<game-name>/memories/` (created automatically)
- Files: `<PlayerName>_MEMORY.md` (e.g. `Alice_MEMORY.md`, `Judge_MEMORY.md`)

### Memory Template (used only when creating a new/missing file)
```markdown
# {PlayerName}'s Private Memory

## Long-term Strategy & Goals

## Observations of Other Players
- Alice: 
- Bob: 
- Carol: 
...
- Judge:

## Key Rules & Tactics to Exploit

## Recent Events & Plans

## Private Notes
```
(The template explicitly lists every other player so even weak models are forced to consider everyone.)

### Injection (once per turn)
In the **very first prompt** the LLM player receives in a turn (usually the propose step or first discussion message), insert the full current `MEMORY.md` content using a single string defined in `prompts.py`. This string will be added as a `{"role": "user"}` message, placed before or after the full ruleset (exact placement to be finalized with PM).

Example skeleton (in `prompts.py`):
```python
MEMORY_INJECTION = """=== YOUR PRIVATE MEMORY (read-only this turn — you will update it at the very end) ===
{full_memory_content}
=== END YOUR PRIVATE MEMORY ==="""
```
All later messages in the turn use the normal role-based history, so the memory stays in context automatically via caching. No re-injection.

### Memory Update Step (new final step after scoring)
After scoring and any rule changes are applied:
- For **every LLM player only**, append **one final** `{"role": "user"}` message (defined in `prompts.py`) that triggers the update.
- The model already has the **entire turn history** in context, so no separate summary is sent.
- The final user message must clearly tell the model:
  - This is the moment to update its memory based on everything that happened this turn.
  - The **entirety** of its response will be saved verbatim to its `MEMORY.md` file.
  - If the response exceeds the configured character limit, it will be truncated by simply cutting off after the limit and appending the exact string:  
    `[MEMORY TRUNCATED]`
- The model must figure out on its own whether to delete old content, condense, restructure, etc. (no explicit instructions on pruning).

Exact wording of the final update prompt will be finalized with the PM, but it must include:
- “Output your complete updated MEMORY.md. The entire response you give will become the new file content (then truncated if too long).”
- “Start directly with the markdown header if you wish, or any format you prefer — there is no required structure.”

### Truncation (simple & transparent)
In `config.yaml` (and `GameConfig`):
```yaml
llm:
  memory:
    max_characters: 12000   # 0 or null = unlimited
```
- Before saving a memory:
  - Log entire repsponse to DEBUG
  - If longer than limit → `content = content[:max_characters] + "\n[MEMORY TRUNCATED]"`
	- Log INFO that memory was saved and/or truncated.
- Truncation happens at save, not injection

### Creation & Robustness
- New games (`create_game.py`): create `memories/` + one templated file per LLM player.
- Any game load (old or new): if a required `*_MEMORY.md` is missing or empty → silently create it with the template.  
  (This prevents crashes even if someone manually deletes a file; no full migration command needed since you own all current games.)
- Humans: no file created, no update call.

### Error Handling (minimal)
- If the final update call returns < 50 characters → keep the old memory unchanged and log a warning (do not crash turn).
- All other responses (even garbage, non-markdown, etc.) are accepted verbatim — LLMs own their memory quality.


## Future Work

This is the long-term backlog and TODO scratchpad.

### Engine Features

* **Improve `LLMPlayer`:**
  * Implement advanced token-saving strategies, especially investigate best use of context caching
  * Implement async behavior (per model provider?)
  * Add a "notepad" feature (e.g., a simple file) for LLMs to save plans and opinions of other players between turns.
    * For prompt examples, do we use current-game responses instead of static personality file values on turn 2+?
    * Recommended notepad sections: 1 per other player, long term strategy, rules to watch, more?
  * Can we get the "thinking" from thinking llm models? Add that as a new field into the logs and transcript?
  * We need to get token usage/metadata about the queries Answer: How big do context windows need to be? What's the cost/total token usage?
  * Explore https://openrouter.ai/ support for tokens/models

* **Rate Limiting & Cost Tracking:**
  * Each turn can generate 20+ API calls when retries are involved (propose + discuss × N + revise + vote × N + judge veto + judge score + judge maintain_state, each with up to 2 retries).
  * Add per-turn and per-game token/cost tracking. Log token counts from API responses. Consider adding configurable per-turn cost limits.
  
* **Game State & Rules:**
  * Enhanced Voting Architecture
      * **Task:** Replace binary vote logic with named "Abstention-Aware" modes.
      * **Data Model:** Expand `VoteMode` enum in `data_models.py` to include `UNANIMOUS_STRICT`, `CONSENSUS`, `MAJORITY_TOTAL`, and `MAJORITY_VOTING`.
      * **Engine Logic:** Update `GameLoop._tally_votes` to implement the specific denominator logic for each named mode.
      * **LLM Awareness:** Update `PromptBuilder` to dynamically inject a plain-language explanation of the current `vote_mode` into player prompts, ensuring players understand the tactical weight of an "ABSTAIN" vote.
      * Rule 109 adds another dimension to voting: whether transmute should be unanimous
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

### Visualization (Web app)

* Plan out a end state for visualizing individual game, all games, rules, profiles for player (slice by model and personality), leaaderboard
* Have badges or awards for players (models)
* Maybe: Build a `build_site.py` script to convert the game history into a shareable HTML file.

### Graphical UI

* Have a GUI for running the game in Electron (?)


